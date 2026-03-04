# -*- coding: utf-8 -*-
"""
CMD API server for VerifyPDB — FastAPI implementation.

Runs a FastAPI/uvicorn HTTP server in a background thread, exposing the
PDB instance's api_* methods and command queue via REST endpoints so
external tools can inspect/control the agent without touching the console.
"""

import re
import threading
import warnings
from typing import TYPE_CHECKING, List, Optional, Tuple

if TYPE_CHECKING:
    from ucagent.verify_pdb import VerifyPDB

_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class PdbCmdApiServer:
    """
    FastAPI-based CMD API wrapper around a :class:`VerifyPDB` instance.

    Endpoints
    ---------
    GET  /                             - API index / usage
    GET  /api/status                   - Agent status string
    GET  /api/tasks                    - Task list
    GET  /api/task/{index}             - Task detail
    GET  /api/mission                  - Mission overview (raw ANSI; ?strip_ansi=true to strip)
    GET  /api/cmds                     - All available PDB commands  (?prefix=)
    GET  /api/help                     - Command help  (?cmd=<name>)
    GET  /api/tools                    - Tool list with call counts
    GET  /api/changed_files            - Recently changed output files  (?count=10)
    POST /api/cmd                      - Enqueue one command   body: {"cmd": "..."}
    POST /api/cmds/batch               - Enqueue multiple cmds body: {"cmds": [...]}
    GET  /docs                         - Swagger UI (auto-generated)
    GET  /redoc                        - ReDoc (auto-generated)
    """

    def __init__(
        self,
        pdb_instance: "VerifyPDB",
        host: str = "127.0.0.1",
        port: int = 8765,
        sock: Optional[str] = None,
        tcp: bool = True,
    ) -> None:
        """
        Parameters
        ----------
        pdb_instance : VerifyPDB
            The PDB instance to wrap.
        host : str
            TCP host address for the HTTP listener.
        port : int
            TCP port for the HTTP listener.
        sock : str, optional
            Path to a Unix-domain socket file.  When provided the server
            also listens on this socket (independent of TCP).
        tcp : bool
            Whether to enable the TCP listener.  Defaults to True.
            Set to False to run on Unix socket only.
        """
        try:
            import fastapi  # noqa: F401
            import uvicorn  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "FastAPI and uvicorn are required for the CMD API server. "
                "Install them with:  pip install fastapi uvicorn"
            ) from exc

        if not tcp and not sock:
            raise ValueError("At least one of 'tcp' or 'sock' must be enabled.")

        self.pdb = pdb_instance
        self.host = host
        self.port = port
        self.sock = sock
        self.tcp = tcp
        self._running = False
        # TCP listener state
        self._tcp_server = None
        self._tcp_thread: Optional[threading.Thread] = None
        # Unix socket listener state
        self._sock_server = None
        self._sock_thread: Optional[threading.Thread] = None
        self._app = self._build_app()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_app(self):
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning, module="fastapi")
            from fastapi import FastAPI, HTTPException, Query
        from pydantic import BaseModel

        app = FastAPI(
            title="UCAgent PDB CMD API",
            description=(
                "REST API for inspecting and controlling the UCAgent VerifyPDB instance. "
                "Use POST /api/cmd or POST /api/cmds/batch to enqueue PDB commands."
            ),
            version="1.0.0",
        )

        pdb = self.pdb  # capture for closures

        # ── request bodies ─────────────────────────────────────────────
        class CmdBody(BaseModel):
            cmd: str

        class CmdsBatchBody(BaseModel):
            cmds: List[str]

        # ── index ──────────────────────────────────────────────────────
        @app.get("/", summary="API index")
        def index():
            return {
                "service": "UCAgent PDB CMD API",
                "version": "1.0.0",
                "endpoints": [
                    "GET  /api/status                   - Agent status",
                    "GET  /api/tasks                    - Task list",
                    "GET  /api/task/{index}             - Task detail",
                    "GET  /api/mission                  - Mission overview (raw ANSI; ?strip_ansi=true to strip)",
                    "GET  /api/cmds[?prefix=]           - List PDB commands",
                    "GET  /api/help[?cmd=]              - Command help",
                    "GET  /api/tools                    - Tool list",
                    "GET  /api/changed_files[?count=10] - Changed output files",
                    'POST /api/cmd                      - Enqueue command {"cmd":"..."}',
                    'POST /api/cmds/batch               - Enqueue commands {"cmds":[...]}',
                    "GET  /docs                         - Swagger UI",
                ],
            }

        # ── GET /api/status ────────────────────────────────────────────
        @app.get("/api/status", summary="Agent status")
        def get_status():
            try:
                return {"status": "ok", "data": pdb.api_status()}
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /api/tasks ─────────────────────────────────────────────
        @app.get("/api/tasks", summary="Task list")
        def get_tasks():
            try:
                return {"status": "ok", "data": pdb.api_task_list()}
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /api/task/{index} ──────────────────────────────────────
        @app.get("/api/task/{index}", summary="Task detail")
        def get_task(index: int):
            try:
                return {"status": "ok", "data": pdb.api_task_detail(index=index)}
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /api/mission ───────────────────────────────────────────
        @app.get("/api/mission", summary="Mission overview")
        def get_mission(strip_ansi: bool = Query(default=False, description="Strip ANSI escape codes from output")):
            try:
                lines = pdb.api_mission_info()
                if strip_ansi:
                    lines = [_strip_ansi(line) for line in lines]
                return {"status": "ok", "data": lines}
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /api/cmds ──────────────────────────────────────────────
        @app.get("/api/cmds", summary="List available PDB commands")
        def get_cmds(
            prefix: str = Query(default="", description="Filter commands by prefix")
        ):
            try:
                return {"status": "ok", "data": pdb.api_all_cmds(prefix)}
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /api/help ──────────────────────────────────────────────
        @app.get("/api/help", summary="Command help")
        def get_help(
            cmd: str = Query(default="", description="Command name; omit to list all")
        ):
            try:
                if cmd:
                    func = getattr(pdb, f"do_{cmd}", None)
                    if func is None:
                        raise HTTPException(
                            status_code=404,
                            detail=f"Command '{cmd}' not found",
                        )
                    return {
                        "status": "ok",
                        "data": {"cmd": cmd, "help": (func.__doc__ or "").strip()},
                    }
                result = {}
                for c in pdb.api_all_cmds():
                    func = getattr(pdb, f"do_{c}", None)
                    if func:
                        doc = (func.__doc__ or "").strip()
                        result[c] = doc.split("\n")[0] if doc else ""
                return {"status": "ok", "data": result}
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /api/tools ─────────────────────────────────────────────
        @app.get("/api/tools", summary="Tool list with call counts")
        def get_tools():
            try:
                tools = pdb.api_tool_status()
                data = [
                    {"name": name, "call_count": count, "is_hot": is_hot}
                    for name, count, is_hot in tools
                ]
                return {"status": "ok", "data": data}
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /api/changed_files ─────────────────────────────────────
        @app.get("/api/changed_files", summary="Recently changed output files")
        def get_changed_files(
            count: int = Query(default=10, description="Maximum number of files to return")
        ):
            try:
                files = pdb.api_changed_files(count)
                data = [
                    {"delta_seconds": d, "timestamp": t, "file": f}
                    for d, t, f in files
                ]
                return {"status": "ok", "data": data}
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── POST /api/cmd ──────────────────────────────────────────────
        @app.post("/api/cmd", summary="Enqueue a single PDB command")
        def send_cmd(body: CmdBody):
            cmd = body.cmd.strip()
            if not cmd:
                raise HTTPException(
                    status_code=400,
                    detail="'cmd' must be a non-empty string",
                )
            try:
                pdb.add_cmds(cmd)
                return {"status": "ok", "message": f"Command '{cmd}' added to queue"}
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── POST /api/cmds/batch ───────────────────────────────────────
        @app.post("/api/cmds/batch", summary="Enqueue multiple PDB commands")
        def send_cmds_batch(body: CmdsBatchBody):
            cmds = body.cmds
            if not cmds:
                raise HTTPException(
                    status_code=400,
                    detail="'cmds' must be a non-empty list",
                )
            try:
                pdb.add_cmds(cmds)
                return {
                    "status": "ok",
                    "message": f"{len(cmds)} command(s) added to queue",
                }
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        return app

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> Tuple[bool, str]:
        """Start the CMD API server.  TCP and Unix-socket listeners start
        independently and may both be active at the same time.

        Returns
        -------
        (success, message)
        """
        if self._running:
            return False, f"CMD API server is already running at {self.url()}"

        import os
        import uvicorn

        started_lines: List[str] = []
        errors: List[str] = []

        # ── TCP listener ───────────────────────────────────────────────
        if self.tcp:
            try:
                tcp_cfg = uvicorn.Config(
                    self._app,
                    host=self.host,
                    port=self.port,
                    log_level="error",
                    ws="none",
                )
                self._tcp_server = uvicorn.Server(tcp_cfg)
                self._tcp_thread = threading.Thread(
                    target=self._tcp_server.run,
                    daemon=True,
                    name="pdb-cmd-api-tcp",
                )
                self._tcp_thread.start()
                started_lines.append(
                    f"TCP  http://{self.host}:{self.port}  (docs: http://{self.host}:{self.port}/docs)"
                )
            except Exception as exc:
                errors.append(f"TCP listener failed: {exc}")
                self._tcp_server = None
                self._tcp_thread = None

        # ── Unix-socket listener ───────────────────────────────────────
        if self.sock:
            # Remove stale socket file so uvicorn can bind cleanly
            if os.path.exists(self.sock):
                try:
                    os.unlink(self.sock)
                except OSError as exc:
                    errors.append(f"Cannot remove existing socket '{self.sock}': {exc}")
            if not any(e.startswith("Cannot remove") for e in errors):
                try:
                    sock_cfg = uvicorn.Config(
                        self._app,
                        uds=self.sock,
                        log_level="error",
                        ws="none",
                    )
                    self._sock_server = uvicorn.Server(sock_cfg)
                    self._sock_thread = threading.Thread(
                        target=self._sock_server.run,
                        daemon=True,
                        name="pdb-cmd-api-sock",
                    )
                    self._sock_thread.start()
                    started_lines.append(
                        f"Sock {self.sock}"
                        f"  (docs: curl --unix-socket {self.sock} http://localhost/docs)"
                    )
                except Exception as exc:
                    errors.append(f"Socket listener failed: {exc}")
                    self._sock_server = None
                    self._sock_thread = None

        if not started_lines:
            # Nothing started
            return False, "CMD API server failed to start:\n  " + "\n  ".join(errors)

        self._running = True
        msg = "CMD API server started:\n  " + "\n  ".join(started_lines)
        if errors:
            msg += "\n  (warnings) " + "; ".join(errors)
        return True, msg

    def stop(self) -> Tuple[bool, str]:
        """Cleanly shut down all active listeners."""
        if not self._running:
            return False, "CMD API server is not running"

        if self._tcp_server is not None:
            self._tcp_server.should_exit = True
            self._tcp_server = None
        self._tcp_thread = None

        if self._sock_server is not None:
            self._sock_server.should_exit = True
            self._sock_server = None
        self._sock_thread = None

        self._running = False

        # Clean up the socket file
        if self.sock:
            import os
            try:
                if os.path.exists(self.sock):
                    os.unlink(self.sock)
            except OSError:
                pass

        return True, "CMD API server stopped"

    @property
    def is_running(self) -> bool:
        tcp_alive = (
            self.tcp
            and self._tcp_thread is not None
            and self._tcp_thread.is_alive()
        )
        sock_alive = (
            bool(self.sock)
            and self._sock_thread is not None
            and self._sock_thread.is_alive()
        )
        return self._running and (tcp_alive or sock_alive)

    def url(self) -> str:
        """Return a human-readable address string for all active listeners."""
        parts: List[str] = []
        if self.tcp:
            parts.append(f"http://{self.host}:{self.port}")
        if self.sock:
            parts.append(f"unix://{self.sock}")
        return " | ".join(parts) if parts else "(none)"
