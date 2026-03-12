# -*- coding: utf-8 -*-
"""
Master API server and client for UCAgent.

Architecture
------------
Master side  (PdbMasterApiServer)
    A single FastAPI/uvicorn server that collects heartbeats from multiple
    UCAgent instances.  Agents are shown as *online* while heartbeats
    arrive, and transition to *offline* once they stop.

Client side  (PdbMasterClient)
    A background thread that periodically POSTs a heartbeat + status
    snapshot to the master.  If the master replies
    ``{"status": "removed"}`` the client stops and prints a warning.

Master endpoints
----------------
GET  /                          - API index
GET  /api/agents                - List all registered agents  (?include_offline=true)
GET  /api/agent/{agent_id}      - Detail for one agent
DELETE /api/agent/{agent_id}    - Remove agent (client notified on next heartbeat)
POST /api/register              - Register / heartbeat  (called by clients)
GET  /docs                      - Swagger UI
"""

import json
import os
import re
import socket
import threading
import time
import warnings
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from ucagent.util.log import echo_g, warning
from ucagent.util.functions import get_abs_path_cwd_ucagent

if TYPE_CHECKING:
    from ucagent.verify_pdb import VerifyPDB

_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _local_ip() -> str:
    """Best-effort local IP (non-loopback)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _master_log(msg: str) -> None:
    """Print a timestamped master-server log line to stdout."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    echo_g(f"[Master {ts}] {msg}")


# ---------------------------------------------------------------------------
# Master server
# ---------------------------------------------------------------------------

class PdbMasterApiServer:
    """
    FastAPI-based master that aggregates status from multiple UCAgent
    instances.  Each agent registers itself via POST /api/register and the
    master marks agents as *offline* when heartbeats stop.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8800,
        sock: Optional[str] = None,
        tcp: bool = True,
        offline_timeout: float = 30.0,
        workspace: str = "",
        access_key: str = "",
        password: str = "",
    ) -> None:
        """
        Parameters
        ----------
        host : str
            TCP bind address.
        port : int
            TCP bind port.
        sock : str, optional
            Unix-domain socket path (independent of TCP).
        tcp : bool
            Enable TCP listener (default True).
        offline_timeout : float
            Seconds without a heartbeat before an agent is marked offline.
        workspace : str
            Base workspace directory used to locate the persistent database.
            The database is stored at ``<workspace>/.ucagent/master_db/agents.json``.
        access_key : str
            If non-empty, POST /api/register requires ``X-Access-Key: <key>``
            header to match this value.  Clients without the key get HTTP 403.
        password : str
            If non-empty, the dashboard (GET /) and all read/write API endpoints
            require HTTP Basic Auth with this password.  Username is ignored.
        """
        try:
            import fastapi  # noqa: F401
            import uvicorn  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "FastAPI and uvicorn are required.  "
                "Install with:  pip install fastapi uvicorn"
            ) from exc

        if not tcp and not sock:
            raise ValueError("At least one of 'tcp' or 'sock' must be enabled.")

        self.host = host
        self.port = port
        self.sock = sock
        self.tcp = tcp
        self.offline_timeout = offline_timeout
        self.access_key = access_key  # Required X-Access-Key header for POST /api/register
        self.password = password       # HTTP Basic password for dashboard / API access

        # Persistent storage path
        if not workspace:
            raise ValueError("'workspace' is required and must not be empty.")
        _db_dir = get_abs_path_cwd_ucagent(workspace, "master_db")
        os.makedirs(_db_dir, exist_ok=True)
        self._db_path: str = os.path.join(_db_dir, "agents.json")

        # agent registry: {agent_id: {...}}
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._agents_lock = threading.Lock()
        # set of agent_ids removed by the operator
        self._removed: set = set()

        self._running = False
        self._tcp_server = None
        self._tcp_thread: Optional[threading.Thread] = None
        self._sock_server = None
        self._sock_thread: Optional[threading.Thread] = None
        # monitor thread: detects offline transitions
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_stop = threading.Event()
        self._online_cache: Dict[str, bool] = {}  # agent_id -> last known online state

        # Dirty-write tracking: save only when necessary
        self._dirty: bool = False          # unsaved changes exist
        self._last_saved: float = 0.0      # epoch of last successful save

        # Load persisted agents before building the app
        self._load_db()
        self._app = self._build_app()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load_db(self) -> None:
        """Load the persisted agent registry from disk (called once at startup)."""
        if not os.path.exists(self._db_path):
            return
        try:
            with open(self._db_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            agents = data.get("agents", {})
            removed = data.get("removed", [])
            with self._agents_lock:
                self._agents.update(agents)
            self._removed.update(removed)
            _master_log(
                f"Loaded {len(agents)} agent(s) from persistent DB: {self._db_path}"
            )
        except Exception as exc:
            _master_log(f"Warning: failed to load persistent DB: {exc}")

    # Seconds of accumulated changes before the monitor loop flushes to disk.
    PERIODIC_SAVE_INTERVAL: float = 20.0

    def _save_db(self) -> None:
        """Persist the current agent registry to disk (thread-safe snapshot)."""
        try:
            with self._agents_lock:
                agents_snapshot = {k: dict(v) for k, v in self._agents.items()}
            removed_snapshot = list(self._removed)
            data = {"agents": agents_snapshot, "removed": removed_snapshot}
            tmp_path = self._db_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._db_path)
            self._dirty = False
            self._last_saved = time.time()
        except Exception as exc:
            _master_log(f"Warning: failed to save persistent DB: {exc}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _agent_status(self, agent: Dict[str, Any]) -> str:
        return (
            "online"
            if time.time() - agent["last_seen"] <= self.offline_timeout
            else "offline"
        )

    # Path to the HTML template directory (same package, sibling folder)
    _TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")

    def _build_app(self):
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning, module="fastapi")
            from fastapi import FastAPI, HTTPException
        from fastapi.responses import HTMLResponse
        from pydantic import BaseModel
        import secrets as _secrets
        from fastapi import Depends, Header as _Header
        from fastapi.security import HTTPBasic as _HTTPBasic, HTTPBasicCredentials as _HTTPBasicCredentials

        # ── auth helpers ──────────────────────────────────────────────────
        _access_key = self.access_key
        _password = self.password
        _security = _HTTPBasic(auto_error=False)

        async def _check_access_key(x_access_key: str = _Header(default="")):
            """Verify X-Access-Key header for the register endpoint."""
            if _access_key and x_access_key != _access_key:
                raise HTTPException(status_code=403, detail="Invalid or missing access key.")

        async def _check_password(
            credentials: Optional[_HTTPBasicCredentials] = Depends(_security),
        ):
            """Verify HTTP Basic Auth password for dashboard / API endpoints."""
            if not _password:
                return
            if credentials is None or not _secrets.compare_digest(
                credentials.password.encode("utf-8"), _password.encode("utf-8")
            ):
                raise HTTPException(
                    status_code=401,
                    detail="Authentication required.",
                    headers={"WWW-Authenticate": 'Basic realm="UCAgent Master"'},
                )

        app = FastAPI(
            title="UCAgent Master API",
            description=(
                "Aggregates heartbeats from multiple UCAgent instances. "
                "Use GET /api/agents to see all registered agents."
            ),
            version="1.0.0",
        )

        import re as _re
        _LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}

        def _fix_cmd_api_url(url: str, client_ip: str) -> str:
            """Replace a localhost/any-interface host in url with the real client IP."""
            if not url or not client_ip:
                return url
            m = _re.match(r'^(https?://)([^:/]+)((?::\d+)?.*)$', url)
            if m and m.group(2).strip().lower() in _LOCAL_HOSTS:
                return m.group(1) + client_ip + m.group(3)
            return url

        agents = self._agents
        agents_lock = self._agents_lock
        removed = self._removed
        save_db = self._save_db

        # ── request body ────────────────────────────────────────────────
        class RegisterBody(BaseModel):
            id: str                          # unique agent identifier
            host: str = ""                   # agent's own IP / hostname
            version: str = ""               # ucagent version
            # optional cmd_api address the master can relay to browsers
            cmd_api_tcp: str = ""           # e.g. "http://1.2.3.4:8765"
            cmd_api_sock: str = ""          # e.g. "/tmp/ucagent_cmd.sock"
            task_list: Optional[dict] = None
            # task progress summary (extracted from task_list by client)
            current_stage_index: int = -1
            total_stage_count: int = 0
            is_mission_complete: bool = False
            current_stage_name: str = ""
            # runtime state
            mcp_running: bool = False       # is MCP server running
            is_break: bool = False          # is agent in break/pause state
            last_cmd: str = ""              # last PDB command executed
            # raw ANSI-colored output of api_mission_info() (list joined with \n)
            mission_info_ansi: str = ""
            run_time: str = ""              # formatted total run time (e.g. "01:20:05")
            extra: Optional[dict] = None    # any additional metadata
            force: bool = False             # if True, clear removed status and re-register

        # ── index ────────────────────────────────────────────────────────
        _template_dir = self._TEMPLATE_DIR

        @app.get("/", summary="Dashboard", response_class=HTMLResponse,
                 dependencies=[Depends(_check_password)])
        def index():
            html_path = os.path.join(_template_dir, "master.html")
            try:
                with open(html_path, "r", encoding="utf-8") as fh:
                    content = fh.read()
                return HTMLResponse(content=content)
            except FileNotFoundError:
                # Fallback: plain JSON index when template is missing
                return HTMLResponse(
                    content="<h2>UCAgent Master API</h2><p>Template not found. "
                            '<a href="/docs">Swagger UI</a></p>',
                )

        # ── POST /api/register ──────────────────────────────────────────
        from fastapi import Request as _Request

        @app.post("/api/register", summary="Register or heartbeat",
                  dependencies=[Depends(_check_access_key)])
        def register(body: RegisterBody, request: _Request):
            agent_id = body.id.strip()
            if not agent_id:
                raise HTTPException(status_code=400, detail="'id' must not be empty")
            # Resolve the actual client IP for localhost-style cmd_api addresses
            _client_ip = request.client.host if request.client else ""

            # notify removed agents
            if agent_id in removed:
                if body.force:
                    removed.discard(agent_id)
                else:
                    return {"status": "removed", "message": "This agent has been removed from the master."}

            now = time.time()
            with agents_lock:
                existing = agents.get(agent_id, {})
                is_new = not existing
                _tcp = _fix_cmd_api_url(body.cmd_api_tcp, _client_ip)
                agents[agent_id] = {
                    "id": agent_id,
                    "host": body.host or existing.get("host", ""),
                    "version": body.version or existing.get("version", ""),
                    "cmd_api_tcp": _tcp or existing.get("cmd_api_tcp", ""),
                    "cmd_api_sock": body.cmd_api_sock or existing.get("cmd_api_sock", ""),
                    "task_list": body.task_list if body.task_list is not None else existing.get("task_list"),
                    # task progress
                    "current_stage_index": body.current_stage_index if body.current_stage_index >= 0 else existing.get("current_stage_index", -1),
                    "total_stage_count": body.total_stage_count if body.total_stage_count > 0 else existing.get("total_stage_count", 0),
                    "is_mission_complete": body.is_mission_complete,
                    "current_stage_name": body.current_stage_name or existing.get("current_stage_name", ""),
                    # runtime state
                    "mcp_running": body.mcp_running,
                    "is_break": body.is_break,
                    "last_cmd": body.last_cmd or existing.get("last_cmd", ""),
                    "mission_info_ansi": body.mission_info_ansi or existing.get("mission_info_ansi", ""),
                    "run_time": body.run_time or existing.get("run_time", ""),
                    "extra": body.extra or existing.get("extra", {}),

                    "first_seen": existing.get("first_seen", now),
                    "last_seen": now,
                }
            if is_new or body.force:
                action = "rejoined" if body.force else "joined"
                host = body.host or "?"
                _master_log(f"Agent '{agent_id}' {action}  host={host}")
                # Agent count changed (new join / forced rejoin): save immediately.
                save_db()
            else:
                # Regular heartbeat: just mark dirty; monitor loop will flush.
                self._dirty = True
            return {"status": "ok", "message": f"Agent '{agent_id}' registered."}

        # ── GET /api/agents ─────────────────────────────────────────────
        @app.get("/api/agents", summary="List all agents",
                 dependencies=[Depends(_check_password)])
        def list_agents(
            include_offline: bool = True,
            strip_ansi: bool = True,
            page: int = 1,
            page_size: int = 20,
            sort_by: str = "last_seen",
            sort_desc: bool = True
        ):
            # Validate pagination parameters
            if page < 1:
                page = 1
            if page_size < 1 or page_size > 1000:
                page_size = 20
            # Validate sort parameters
            valid_sort_fields = {'id', 'host', 'status', 'last_seen', 'first_seen', 'current_stage_index'}
            if sort_by not in valid_sort_fields:
                sort_by = 'last_seen'
            with agents_lock:
                data = []
                for a in agents.values():
                    st = (
                        "online"
                        if time.time() - a["last_seen"] <= self.offline_timeout
                        else "offline"
                    )
                    if not include_offline and st == "offline":
                        continue
                    tl = a.get("task_list") or {}
                    raw_mi = a.get("mission_info_ansi", "")
                    data.append({
                        "id": a["id"],
                        "host": a["host"],
                        "version": a["version"],
                        "cmd_api_tcp": a["cmd_api_tcp"],
                        "cmd_api_sock": a["cmd_api_sock"],
                        "status": st,
                        "last_seen": a["last_seen"],
                        "first_seen": a["first_seen"],
                        "mission": tl.get("mission_name", ""),
                        "task_index": tl.get("task_index", -1),
                        # task progress
                        "current_stage_index": a.get("current_stage_index", -1),
                        "total_stage_count": a.get("total_stage_count", 0),
                        "is_mission_complete": a.get("is_mission_complete", False),
                        "current_stage_name": a.get("current_stage_name", ""),
                        # runtime state
                        "mcp_running": a.get("mcp_running", False),
                        "is_break": a.get("is_break", False),
                        "last_cmd": a.get("last_cmd", ""),
                        "run_time": a.get("run_time", ""),
                        # mission info (ANSI or stripped)
                        "mission_info_ansi": _strip_ansi(raw_mi) if strip_ansi else raw_mi,
                        # full task_list payload for detail views
                        "task_list": a.get("task_list"),
                    })
                # Apply sorting
                reverse = sort_desc
                if sort_by == 'status':
                    # For status: online=0, offline=1 (so online comes first when desc=True)
                    data.sort(key=lambda a: (a['status'] != 'online'), reverse=reverse)
                elif sort_by in ['id', 'host']:
                    data.sort(key=lambda a: a[sort_by], reverse=reverse)
                elif sort_by in ['last_seen', 'first_seen', 'current_stage_index']:
                    data.sort(key=lambda a: a[sort_by], reverse=reverse)
                # Apply pagination
                total_count = len(data)
                total_pages = (total_count + page_size - 1) // page_size  # ceiling division
                # Clamp page to valid range
                if page > total_pages and total_count > 0:
                    page = total_pages
                if page < 1:
                    page = 1
                start_idx = (page - 1) * page_size
                end_idx = min(start_idx + page_size, total_count)
                page_data = data[start_idx:end_idx]
            return {
                "status": "ok",
                "count": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "sort_by": sort_by,
                "sort_desc": sort_desc,
                "agents": page_data
            }

        # ── GET /api/agent/{agent_id} ───────────────────────────────────
        @app.get("/api/agent/{agent_id}", summary="Agent detail",
                 dependencies=[Depends(_check_password)])
        def get_agent(agent_id: str, strip_ansi: bool = True):
            with agents_lock:
                a = agents.get(agent_id)
            if a is None:
                raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
            st = (
                "online"
                if time.time() - a["last_seen"] <= self.offline_timeout
                else "offline"
            )
            tl = a.get("task_list") or {}
            raw_mi = a.get("mission_info_ansi", "")
            data = {
                "id": a["id"],
                "host": a["host"],
                "version": a["version"],
                "cmd_api_tcp": a["cmd_api_tcp"],
                "cmd_api_sock": a["cmd_api_sock"],
                "status": st,
                "last_seen": a["last_seen"],
                "first_seen": a["first_seen"],
                "mission": tl.get("mission_name", ""),
                "task_index": tl.get("task_index", -1),
                "current_stage_index": a.get("current_stage_index", -1),
                "total_stage_count": a.get("total_stage_count", 0),
                "is_mission_complete": a.get("is_mission_complete", False),
                "current_stage_name": a.get("current_stage_name", ""),
                "mcp_running": a.get("mcp_running", False),
                "is_break": a.get("is_break", False),
                "last_cmd": a.get("last_cmd", ""),
                "run_time": a.get("run_time", ""),
                "mission_info_ansi": _strip_ansi(raw_mi) if strip_ansi else raw_mi,
                "task_list": a.get("task_list"),
            }
            return {"status": "ok", "agent_status": st, "data": data}

        # ── DELETE /api/agent/{agent_id} ────────────────────────────────
        @app.delete("/api/agent/{agent_id}", summary="Remove an agent",
                    dependencies=[Depends(_check_password)])
        def delete_agent(agent_id: str):
            with agents_lock:
                if agent_id not in agents:
                    raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
                del agents[agent_id]
            removed.add(agent_id)
            _master_log(f"Agent '{agent_id}' removed by operator")
            save_db()
            return {"status": "ok", "message": f"Agent '{agent_id}' removed."}

        return app

    # ------------------------------------------------------------------
    # Monitor thread
    # ------------------------------------------------------------------

    def _monitor_loop(self) -> None:
        """Background thread: log when agents go offline and flush dirty DB."""
        while not self._monitor_stop.is_set():
            self._monitor_stop.wait(10)  # check every 10 s
            if self._monitor_stop.is_set():
                break
            now = time.time()
            with self._agents_lock:
                current_ids = set(self._agents.keys())
                for aid, a in self._agents.items():
                    is_online = (now - a["last_seen"]) <= self.offline_timeout
                    was_online = self._online_cache.get(aid, True)
                    if was_online and not is_online:
                        elapsed = int(now - a["last_seen"])
                        _master_log(
                            f"Agent '{aid}' went offline  "
                            f"(no heartbeat for {elapsed}s, host={a.get('host', '?')})"
                        )
                    self._online_cache[aid] = is_online
            # clean up cache entries for agents that no longer exist
            for aid in list(self._online_cache):
                if aid not in current_ids:
                    del self._online_cache[aid]
            # Periodic flush: write dirty data once the interval has elapsed.
            if self._dirty and (now - self._last_saved) >= self.PERIODIC_SAVE_INTERVAL:
                self._save_db()
    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> Tuple[bool, str]:
        if self._running:
            return False, f"Master API server is already running at {self.url()}"

        import uvicorn

        started: List[str] = []
        errors: List[str] = []

        if self.tcp:
            try:
                cfg = uvicorn.Config(self._app, host=self.host, port=self.port,
                                     log_level="error", ws="none")
                self._tcp_server = uvicorn.Server(cfg)
                self._tcp_thread = threading.Thread(
                    target=self._tcp_server.run, daemon=True, name="master-api-tcp")
                self._tcp_thread.start()
                started.append(f"TCP  http://{self.host}:{self.port}  (docs: http://{self.host}:{self.port}/docs)")
            except Exception as exc:
                errors.append(f"TCP listener failed: {exc}")
                self._tcp_server = None
                self._tcp_thread = None

        if self.sock:
            if os.path.exists(self.sock):
                try:
                    os.unlink(self.sock)
                except OSError as exc:
                    errors.append(f"Cannot remove socket '{self.sock}': {exc}")
            if not any("Cannot remove" in e for e in errors):
                try:
                    cfg = uvicorn.Config(self._app, uds=self.sock,
                                         log_level="error", ws="none")
                    self._sock_server = uvicorn.Server(cfg)
                    self._sock_thread = threading.Thread(
                        target=self._sock_server.run, daemon=True, name="master-api-sock")
                    self._sock_thread.start()
                    started.append(
                        f"Sock {self.sock}"
                        f"  (docs: curl --unix-socket {self.sock} http://localhost/docs)")
                except Exception as exc:
                    errors.append(f"Socket listener failed: {exc}")
                    self._sock_server = None
                    self._sock_thread = None

        if not started:
            return False, "Master API server failed to start:\n  " + "\n  ".join(errors)

        self._running = True
        self._monitor_stop.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="master-monitor")
        self._monitor_thread.start()
        msg = "Master API server started:\n  " + "\n  ".join(started)
        if errors:
            msg += "\n  (warnings) " + "; ".join(errors)
        return True, msg

    def stop(self) -> Tuple[bool, str]:
        if not self._running:
            return False, "Master API server is not running"
        if self._tcp_server:
            self._tcp_server.should_exit = True
            self._tcp_server = None
        self._tcp_thread = None
        if self._sock_server:
            self._sock_server.should_exit = True
            self._sock_server = None
        self._sock_thread = None
        self._running = False
        self._monitor_stop.set()
        self._monitor_thread = None
        self._online_cache.clear()
        # Flush any unsaved changes accumulated before shutdown.
        if self._dirty:
            self._save_db()
        if self.sock:
            try:
                if os.path.exists(self.sock):
                    os.unlink(self.sock)
            except OSError:
                pass
        return True, "Master API server stopped"

    @property
    def is_running(self) -> bool:
        tcp_alive = self.tcp and self._tcp_thread is not None and self._tcp_thread.is_alive()
        sock_alive = bool(self.sock) and self._sock_thread is not None and self._sock_thread.is_alive()
        return self._running and (tcp_alive or sock_alive)

    def url(self) -> str:
        parts: List[str] = []
        if self.tcp:
            parts.append(f"http://{self.host}:{self.port}")
        if self.sock:
            parts.append(f"unix://{self.sock}")
        return " | ".join(parts) if parts else "(none)"

    def agent_count(self) -> Dict[str, int]:
        online = offline = 0
        with self._agents_lock:
            for a in self._agents.values():
                if time.time() - a["last_seen"] <= self.offline_timeout:
                    online += 1
                else:
                    offline += 1
        return {"online": online, "offline": offline}


# ---------------------------------------------------------------------------
# Master client
# ---------------------------------------------------------------------------

class PdbMasterClient:
    """
    Background thread that periodically sends a heartbeat + status snapshot
    to a PdbMasterApiServer via HTTP.

    The master replies ``{"status": "removed"}`` when the agent has been
    deleted via DELETE /api/agent/{id}.  The client then stops and prints
    a console alert.
    """

    def __init__(
        self,
        pdb_instance: "VerifyPDB",
        master_url: str,
        agent_id: Optional[str] = None,
        interval: float = 5.0,
        reconnect_interval: float = 10.0,
        access_key: str = "",
    ) -> None:
        """
        Parameters
        ----------
        pdb_instance : VerifyPDB
            The local PDB instance to read status from.
        master_url : str
            Base URL of the master, e.g. ``http://192.168.1.10:8800``.
        agent_id : str, optional
            Unique id for this agent.  Defaults to ``<hostname>-<pid>``.
        interval : float
            Heartbeat interval in seconds (default 5).
        reconnect_interval : float
            Seconds to wait between reconnect attempts after a network
            failure (default 10).  Set to 0 to disable auto-reconnect.
        access_key : str
            If the master requires an access key, supply it here.  Sent as
            the ``X-Access-Key`` HTTP header on every heartbeat request.
        """
        try:
            import requests  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "'requests' is required for the master client.  "
                "Install with:  pip install requests"
            ) from exc

        self.pdb = pdb_instance
        self.master_url = master_url.rstrip("/")
        self.agent_id = agent_id or f"{socket.gethostname()}-{os.getpid()}"
        self.interval = interval
        self.reconnect_interval = reconnect_interval
        self.access_key = access_key

        self._running = False
        self._kicked = False       # True when master explicitly removed this agent
        self._auth_failed = False  # True when master rejected our access key (HTTP 403)
        self._connected = False    # True only while heartbeats are succeeding
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._force_next = False  # set True by start() so first heartbeat uses force=True

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_payload(self) -> dict:
        from ucagent.version import __version__
        pdb = self.pdb
        srv = getattr(pdb, "_cmd_api_server", None)
        tcp_url = ""
        sock_path = ""
        if srv and srv.is_running:
            if getattr(srv, "tcp", False):
                tcp_url = f"http://{srv.host}:{srv.port}"
            if getattr(srv, "sock", None):
                sock_path = srv.sock

        try:
            task_list = pdb.api_task_list()
        except Exception:
            task_list = None

        # Extract progress fields from task_list
        current_stage_index = -1
        total_stage_count = 0
        is_mission_complete = False
        current_stage_name = ""
        if task_list:
            tl_inner = task_list.get("task_list") or {}  # result of stage_manager.status()
            stage_list = tl_inner.get("stage_list", [])
            total_stage_count = len(stage_list)
            raw_index = task_list.get("task_index", -1)
            current_stage_index = raw_index
            # mission complete when stage_index >= total stages
            is_mission_complete = (total_stage_count > 0 and raw_index >= total_stage_count)
            current_stage_name = tl_inner.get("current_stage_name", "")
            if not current_stage_name and 0 <= raw_index < total_stage_count:
                current_stage_name = stage_list[raw_index].get("title", "")

        # run time
        run_time = ""
        try:
            from ucagent.util.functions import fmt_time_deta as _fmt_time_deta
            agent_tmp = getattr(pdb, "agent", None)
            if agent_tmp is not None:
                run_time = _fmt_time_deta(agent_tmp.stage_manager.get_time_cost())
            else:
                run_time = "-"
                warning("Cannot get run_time: pdb.agent is None")
        except Exception as e:
            warning("Failed to get run_time from agent.stage_manager.get_time_cost(): " + str(e))
            run_time = "-"

        # runtime state
        agent = getattr(pdb, "agent", None)
        mcp_running = False
        if agent is not None:
            mcps = getattr(agent, "_mcps", None)
            mcp_thread = getattr(agent, "_mcp_server_thread", None)
            mcp_running = mcps is not None and (
                mcp_thread is None or mcp_thread.is_alive()
            )
        is_break = bool(agent.is_break()) if agent is not None else False
        last_cmd = getattr(pdb, "lastcmd", "") or ""

        try:
            mission_info_lines = pdb.api_mission_info()
            mission_info_ansi = "\n".join(str(l) for l in mission_info_lines)
        except Exception as e:
            warning("Failed to get mission_info_ansi: " + str(e))
            mission_info_ansi = ""

        return {
            "id": self.agent_id,
            "host": _local_ip(),
            "version": __version__,
            "cmd_api_tcp": tcp_url,
            "cmd_api_sock": sock_path,
            "task_list": task_list,
            "current_stage_index": current_stage_index,
            "total_stage_count": total_stage_count,
            "is_mission_complete": is_mission_complete,
            "current_stage_name": current_stage_name,
            "run_time": run_time,
            "mcp_running": mcp_running,
            "is_break": is_break,
            "last_cmd": last_cmd,
            "mission_info_ansi": mission_info_ansi,
            "extra": {
                "workspace": getattr(agent, "workspace", ""),
                "pid": os.getpid(),
            },
        }

    def _heartbeat_loop(self):
        import requests
        from ucagent.util.log import echo_r, echo_y

        register_url = f"{self.master_url}/api/register"
        _connected = False  # local mirror; synced to self._connected
        _headers = {"X-Access-Key": self.access_key} if self.access_key else {}

        while not self._stop_event.is_set():
            try:
                payload = self._build_payload()
                # Use force=True on the very first send or on each reconnect
                if self._force_next or not _connected:
                    payload["force"] = True
                    self._force_next = False
                resp = requests.post(register_url, json=payload, timeout=10, headers=_headers)
                if resp.ok:
                    data = resp.json()
                    if data.get("status") == "removed":
                        # Server has explicitly removed this agent — do NOT reconnect.
                        self._kicked = True
                        self._running = False
                        try:
                            echo_r(
                                f"\n[MasterClient] Agent '{self.agent_id}' has been "
                                f"REMOVED from master {self.master_url}. "
                                f"Stopping heartbeat.\n"
                            )
                        except Exception:
                            print(
                                f"[MasterClient] Agent '{self.agent_id}' removed from master. "
                                "Stopping heartbeat."
                            )
                        return
                    # Successful heartbeat
                    if not _connected:
                        _master_log(
                            f"[MasterClient] (Re)connected to master {self.master_url} "
                            f"as '{self.agent_id}'"
                        )
                    _connected = True
                    self._connected = True
                else:
                    # Non-OK HTTP response — check whether it's a fatal auth error.
                    if resp.status_code == 403:
                        # Wrong or missing access key — do NOT reconnect.
                        self._auth_failed = True
                        self._running = False
                        self._connected = False
                        try:
                            from ucagent.util.log import echo_r as _echo_r
                            _echo_r(
                                f"\n[MasterClient] Access key rejected by master "
                                f"{self.master_url} (HTTP 403). "
                                f"Stopping heartbeat — check your --key value.\n"
                            )
                        except Exception:
                            print(
                                f"[MasterClient] Access key rejected by {self.master_url} "
                                "(HTTP 403). Stopping heartbeat."
                            )
                        return
                    # Other non-OK HTTP response (e.g. 5xx) — treat as transient failure.
                    if _connected:
                        _master_log(
                            f"[MasterClient] Lost connection to {self.master_url} "
                            f"(HTTP {resp.status_code}). "
                            f"Retrying in {self.reconnect_interval}s …"
                        )
                    _connected = False
                    self._connected = False
                    self._stop_event.wait(self.reconnect_interval)
                    continue
            except Exception as exc:
                # Network-level error (connection refused, timeout, …)
                if _connected:
                    _master_log(
                        f"[MasterClient] Connection to {self.master_url} lost: {exc}. "
                        f"Retrying in {self.reconnect_interval}s …"
                    )
                _connected = False
                self._connected = False
                self._stop_event.wait(self.reconnect_interval)
                continue

            # Normal heartbeat cadence
            self._stop_event.wait(self.interval)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> Tuple[bool, str]:
        if self._running:
            return False, f"Already connected to master at {self.master_url}"
        if self._kicked:
            return False, (
                f"This agent was removed from master {self.master_url}. "
                "Use a new PdbMasterClient instance to reconnect."
            )
        if self._auth_failed:
            return False, (
                f"Access key was rejected by master {self.master_url} (HTTP 403). "
                "Provide the correct --key value and use a new connection."
            )
        self._stop_event.clear()
        self._force_next = True
        self._thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="master-client"
        )
        self._thread.start()
        self._running = True
        return True, (
            f"Connected to master {self.master_url} "
            f"as '{self.agent_id}' (interval={self.interval}s, "
            f"reconnect_interval={self.reconnect_interval}s)"
        )

    def stop(self) -> Tuple[bool, str]:
        if not self._running:
            return False, "Not connected to master"
        # Signal the loop to exit — this is a voluntary stop, not a kick.
        self._stop_event.set()
        self._running = False
        self._connected = False
        self._thread = None
        return True, f"Disconnected from master {self.master_url}"

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def is_kicked(self) -> bool:
        """True if the master explicitly removed this agent."""
        return self._kicked

    @property
    def is_auth_failed(self) -> bool:
        """True if the master rejected our access key (HTTP 403)."""
        return self._auth_failed
