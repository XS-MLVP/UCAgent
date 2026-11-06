"""Master HTTP and WebSocket routes, authentication, and UI resources."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import base64
import json
import mimetypes
import os
import pathlib
import shutil
import shlex
import tempfile
from typing import Any, Dict, Optional
from urllib.parse import urlencode
from ucagent.util.log import warning
from ucagent.util.workspace_archive import WorkspaceArchiveError

from .common import (
    BaseModel,
    Body,
    Depends,
    FastAPI,
    HTMLResponse,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    _CONTAINER_LAUNCH_MODES,
    _Header,
    _PROXY_METHODS,
    _WAITING_TASK_STATUS,
    _copy_jsonable,
    _fix_reported_tcp_url,
    _is_text_file,
    _master_log,
    _normalize_launch_mode_list,
    _now,
    _parse_module_names,
    _path_is_under,
    _plain_config_value,
    _rewrite_html,
    _strip_ansi,
    _sync_reported_service_tcp_url,
    _task_logs_for_display,
)


class RoutesMixin:
    """Master HTTP and WebSocket routes, authentication, and UI resources."""

    def _build_app(self):  # noqa: C901
        """Build the authenticated Master application and its HTTP and WebSocket routes."""
        import aiohttp
        import secrets as _secrets

        @asynccontextmanager
        async def lifespan(app):
            """Close this listener's proxy session on its own event loop after draining."""
            try:
                yield
            finally:
                session = self._proxy_sessions.pop(asyncio.get_running_loop(), None)
                if session is not None:
                    await session.close()

        app = FastAPI(
            lifespan=lifespan,
            title="UCAgent Master API",
            description="Aggregates heartbeats and manages launched UCAgent tasks.",
            version="2.0.0",
        )

        access_key = self.access_key
        password = self.password
        security = HTTPBasic(auto_error=False)
        proxy_timeout = aiohttp.ClientTimeout(total=120, connect=3, sock_connect=3, sock_read=120)
        from ucagent.server.api_cmd.transport import XpraBrowserAccess
        xpra_browser_access = XpraBrowserAccess(password)

        async def _proxy_http_request(
            request: Request,
            target_url: str,
            headers: Dict[str, str],
            html_rewrites: Dict[str, str],
            failure_label: str,
        ) -> Response:
            body = await request.body()
            # Advertise aiohttp's own decoders rather than inheriting browser
            # codecs such as Brotli/Zstandard that may not be installed here.
            headers = {key: value for key, value in headers.items() if key.lower() != "accept-encoding"}
            if request.method == "HEAD":
                headers["Accept-Encoding"] = "identity"
            session = self._proxy_sessions.get(asyncio.get_running_loop())
            if session is None or session.closed:
                connector = aiohttp.TCPConnector(limit=256, limit_per_host=64, ttl_dns_cache=30, keepalive_timeout=30)
                session = aiohttp.ClientSession(connector=connector, timeout=proxy_timeout)
                self._proxy_sessions[asyncio.get_running_loop()] = session
            last_exc: Optional[BaseException] = None
            for attempt in range(3):
                try:
                    async with session.request(
                        request.method,
                        target_url,
                        data=body or None,
                        headers=headers,
                        allow_redirects=False,
                    ) as resp:
                        raw = await resp.read()
                        content_type = resp.headers.get("Content-Type", "")
                        if "text/html" in content_type and html_rewrites:
                            text = raw.decode("utf-8", errors="replace")
                            text = _rewrite_html(text, html_rewrites)
                            raw = text.encode("utf-8")
                        response_headers = {}
                        for key, value in resp.headers.items():
                            if key.lower() in {"content-length", "transfer-encoding", "content-encoding", "connection", "www-authenticate"}:
                                continue
                            response_headers[key] = value
                        if request.method == "HEAD" and "Content-Length" in resp.headers:
                            response_headers["Content-Length"] = resp.headers["Content-Length"]
                        response = Response(content=raw, status_code=resp.status, headers=response_headers, media_type=None)
                        return xpra_browser_access.grant(request, response)
                except (aiohttp.ClientConnectorError, aiohttp.ServerDisconnectedError, aiohttp.ClientOSError, asyncio.TimeoutError) as exc:
                    last_exc = exc
                    if attempt >= 2:
                        break
                    await asyncio.sleep(0.15 * (attempt + 1))
            raise HTTPException(status_code=502, detail=f"Failed to proxy {failure_label}: {last_exc}") from last_exc

        async def _check_access_key(x_access_key: str = _Header(default="")):
            if access_key and x_access_key != access_key:
                raise HTTPException(status_code=403, detail="Invalid or missing access key.")

        async def _check_access_key_query(key: str = Query(default=""), x_access_key: str = _Header(default="")):
            if access_key and key != access_key and x_access_key != access_key:
                raise HTTPException(status_code=403, detail="Invalid or missing access key.")

        async def _check_workspace_archive_access(
            key: str = Query(default=""),
            x_access_key: str = _Header(default=""),
            credentials: Optional[HTTPBasicCredentials] = Depends(security),
        ):
            if access_key and (key == access_key or x_access_key == access_key):
                return
            if password and credentials is not None and _secrets.compare_digest(
                credentials.password.encode("utf-8"), password.encode("utf-8")
            ):
                return
            if access_key or password:
                raise HTTPException(status_code=403, detail="Invalid or missing workspace archive credentials.")

        async def _check_password(credentials: Optional[HTTPBasicCredentials] = Depends(security)):
            if not password:
                return
            if credentials is None or not _secrets.compare_digest(
                credentials.password.encode("utf-8"), password.encode("utf-8")
            ):
                raise HTTPException(
                    status_code=401,
                    detail="Authentication required.",
                    headers={"WWW-Authenticate": 'Basic realm="UCAgent Master"'},
                )

        def _check_ws_password(headers: Dict[str, str]) -> None:
            if not password:
                return
            auth = headers.get("authorization", "")
            if not auth.startswith("Basic "):
                raise PermissionError("Authentication required")
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8")
            except Exception as exc:  # pragma: no cover - defensive
                raise PermissionError("Invalid authentication header") from exc
            _, _, pwd = decoded.partition(":")
            if not _secrets.compare_digest(pwd.encode("utf-8"), password.encode("utf-8")):
                raise PermissionError("Authentication required")

        def _fix_tcp_url(url: str, client_ip: str) -> str:
            return _fix_reported_tcp_url(url, client_ip)

        def _sync_service_tcp_url(service: Dict[str, Any], client_ip: str) -> Dict[str, Any]:
            return _sync_reported_service_tcp_url(service, client_ip)

        class StopTaskBody(BaseModel):
            force: bool = False

        @app.get("/", summary="Dashboard", response_class=HTMLResponse, dependencies=[Depends(_check_password)])
        def index():
            html_path = os.path.join(self._TEMPLATE_DIR, "master.html")
            try:
                with open(html_path, "r", encoding="utf-8") as fh:
                    return HTMLResponse(content=fh.read())
            except FileNotFoundError:
                return HTMLResponse("<h2>UCAgent Master API</h2><p><a href='/docs'>Swagger UI</a></p>")

        @app.get("/launch/", summary="Launch page", response_class=HTMLResponse, dependencies=[Depends(_check_password)])
        def launch_page():
            path = os.path.join(self._TEMPLATE_DIR, "launch.html")
            with open(path, "r", encoding="utf-8") as fh:
                return HTMLResponse(content=fh.read())

        @app.get("/task/", summary="Task page", response_class=HTMLResponse, dependencies=[Depends(_check_password)])
        def task_page():
            path = os.path.join(self._TEMPLATE_DIR, "task.html")
            with open(path, "r", encoding="utf-8") as fh:
                return HTMLResponse(content=fh.read())

        @app.get("/api/ui-meta", summary="UI metadata", dependencies=[Depends(_check_password)])
        def ui_meta():
            from ucagent.version import __version__

            uptime_s = 0.0
            if self.started_at:
                uptime_s = max(0.0, _now() - self.started_at)
            return {
                "status": "ok",
                "data": {
                    "product": "UCAgent",
                    "version": __version__,
                    "started_at": self.started_at,
                    "uptime_s": round(uptime_s, 1),
                },
            }

        @app.get("/api/capabilities", summary="Client-facing master capabilities", dependencies=[Depends(_check_access_key)])
        def capabilities(agent_id: str = Query(default="")):
            return {
                "status": "ok",
                "capabilities": {
                    "workspace_sync_back": self._workspace_sync_status(agent_id),
                },
            }

        @app.get("/api/workspace-sync/status", summary="Workspace sync-back status", dependencies=[Depends(_check_access_key)])
        def workspace_sync_status(agent_id: str = Query(default="")):
            return {"status": "ok", "data": self._workspace_sync_status(agent_id)}

        @app.post("/api/records", summary="Report structured records", dependencies=[Depends(_check_access_key)])
        def report_records(body: Dict[str, Any] = Body(default_factory=dict)):
            raw_agent_id = body.get("agent_id")
            raw_record_type = body.get("record_type")
            raw_data_key = body.get("data_key", "")
            if not isinstance(raw_agent_id, str) or not raw_agent_id.strip():
                raise HTTPException(status_code=400, detail="'agent_id' must not be empty")
            if not isinstance(raw_record_type, str) or not raw_record_type.strip():
                raise HTTPException(status_code=400, detail="'record_type' must not be empty")
            if not isinstance(raw_data_key, str):
                raise HTTPException(status_code=400, detail="'data_key' must be a string")
            if "payload" not in body:
                raise HTTPException(status_code=400, detail="'payload' is required")
            schema_version = body.get("schema_version", 1)
            if isinstance(schema_version, bool) or not isinstance(schema_version, int):
                raise HTTPException(status_code=400, detail="'schema_version' must be an integer")
            if schema_version < 1:
                raise HTTPException(status_code=400, detail="'schema_version' must be at least 1")
            source = body.get("source", {})
            if source is None:
                source = {}
            if not isinstance(source, dict):
                raise HTTPException(status_code=400, detail="'source' must be an object")

            agent_id = raw_agent_id.strip()
            record_type = raw_record_type.strip()
            data_key = raw_data_key.strip()
            payload = body["payload"]
            launch_order = []
            if (
                record_type.lower() == "launch"
                and isinstance(payload, dict)
                and isinstance(payload.get("task_list"), list)
            ):
                task_list = payload["task_list"]
                item_count = len(task_list)
                for index, task in enumerate(task_list):
                    if isinstance(task, dict):
                        task_label = (
                            task.get("task_name")
                            or task.get("selected_module")
                            or task.get("dut_name")
                            or f"task-{index + 1}"
                        )
                    else:
                        task_label = task
                    launch_order.append(str(task_label))
            elif isinstance(payload, (list, dict)):
                item_count = len(payload)
            else:
                item_count = 0 if payload is None else 1
            stage_name = str(source.get("stage_name") or "").strip()
            launch_summary = (
                f" launch_order={json.dumps(launch_order, ensure_ascii=False)}"
                if launch_order
                else ""
            )
            _master_log(
                f"Record report received agent='{agent_id}' type='{record_type}' "
                f"data_key='{data_key or '-'}' stage='{stage_name or '-'}' items={item_count} "
                f"schema_version={schema_version}{launch_summary}"
            )
            return {
                "status": "ok",
                "message": "Record report accepted.",
                "accepted": {
                    "agent_id": agent_id,
                    "record_type": record_type,
                    "data_key": data_key,
                    "item_count": item_count,
                    "schema_version": schema_version,
                },
            }

        @app.post("/api/workspace-sync/back", summary="Sync a client workspace archive back to master", dependencies=[Depends(_check_access_key)])
        async def workspace_sync_back(request: Request):
            temp_dir = tempfile.mkdtemp(prefix="ucagent_workspace_sync_upload_")
            archive_path = os.path.join(temp_dir, "workspace.tar.gz")
            try:
                try:
                    form = await request.form()
                except Exception as exc:
                    raise HTTPException(status_code=400, detail=f"Failed to parse upload form: {exc}") from exc

                agent_id = str(
                    form.get("agent_id")
                    or request.query_params.get("agent_id")
                    or request.headers.get("X-UCAgent-Agent-Id", "")
                ).strip()
                upload_file = None
                for key in ("archive", "file", "workspace"):
                    candidate = form.get(key)
                    if hasattr(candidate, "read"):
                        upload_file = candidate
                        break
                if upload_file is None:
                    raise HTTPException(status_code=400, detail="Missing uploaded workspace archive")
                if not agent_id:
                    raise HTTPException(status_code=400, detail="'agent_id' is required")

                size = 0
                with open(archive_path, "wb") as fh:
                    while True:
                        chunk = await upload_file.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        fh.write(chunk)
                if size <= 0:
                    raise HTTPException(status_code=400, detail="Uploaded workspace archive is empty")
                sync_info = self._sync_workspace_archive_back(agent_id, archive_path, archive_size=size)
                return {"status": "ok", "sync": sync_info}
            except HTTPException:
                raise
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except (WorkspaceArchiveError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

        @app.post("/api/register", summary="Register or heartbeat", dependencies=[Depends(_check_access_key)])
        def register(body: Dict[str, Any] = Body(default_factory=dict), request: Request = None):
            agent_id = str(body.get("id") or "").strip()
            if not agent_id:
                raise HTTPException(status_code=400, detail="'id' must not be empty")

            client_ip = request.client.host if request.client else ""
            is_force = bool(body.get("force"))
            is_client_exit = bool(body.get("client_exit") or body.get("exit"))
            if agent_id in self._removed:
                if is_force:
                    self._removed.discard(agent_id)
                else:
                    return {"status": "removed", "message": "This agent has been removed from the master."}

            now = _now()
            with self._agents_lock:
                existing = self._agents.get(agent_id, {})
                is_new = not existing
                try:
                    reported_exited_at = float(body.get("exited_at")) if body.get("exited_at") not in (None, "") else now
                except (TypeError, ValueError):
                    reported_exited_at = now
                exit_reason = str(body.get("exit_reason") or ("quit" if is_client_exit else "")).strip()
                client_exit = True if is_client_exit else (False if is_force else bool(existing.get("client_exit")))
                exited_at = (
                    reported_exited_at
                    if is_client_exit
                    else (0 if not client_exit else existing.get("exited_at", 0))
                )
                exit_reason_value = (
                    exit_reason
                    if is_client_exit
                    else ("" if not client_exit else existing.get("exit_reason", ""))
                )
                tcp_url = _fix_tcp_url(str(body.get("cmd_api_tcp") or ""), client_ip)
                current_stage_index = int(body.get("current_stage_index", -1) or -1)
                total_stage_count = int(body.get("total_stage_count", 0) or 0)
                raw_meta = body.get("meta")
                meta = _copy_jsonable(raw_meta) if isinstance(raw_meta, dict) else _copy_jsonable(existing.get("meta", {}))

                # Normalize web_console field
                raw_web_console = body.get("web_console")
                web_console = {}
                if isinstance(raw_web_console, str) and raw_web_console.strip():
                    # If web_console is a string (address), convert to object
                    fixed_web_console_url = _fix_tcp_url(raw_web_console.strip(), client_ip)
                    web_console = {
                        "enabled": True,
                        "tcp_url": fixed_web_console_url,
                        "host": fixed_web_console_url.strip().split(":")[0] if ":" in fixed_web_console_url else fixed_web_console_url.strip(),
                        "port": int(fixed_web_console_url.strip().split(":")[1]) if ":" in fixed_web_console_url else 8000
                    }
                elif isinstance(raw_web_console, dict):
                    web_console = _sync_service_tcp_url(raw_web_console, client_ip)
                    # Ensure enabled field exists
                    if "enabled" not in web_console:
                        web_console["enabled"] = bool(web_console.get("tcp_url") or web_console.get("base_url_internal") or web_console.get("port"))
                    # Ensure at least one address field exists
                    if web_console.get("host") and web_console.get("port") and not web_console.get("tcp_url"):
                        web_console["tcp_url"] = f"{web_console['host']}:{web_console['port']}"
                else:
                    # Use existing if no new data
                    web_console = _copy_jsonable(existing.get("web_console", {}))

                # Normalize terminal_api field
                raw_terminal_api = body.get("terminal_api")
                terminal_api = {}
                if isinstance(raw_terminal_api, str) and raw_terminal_api.strip():
                    # If terminal_api is a string (address), convert to object
                    fixed_terminal_url = _fix_tcp_url(raw_terminal_api.strip(), client_ip)
                    terminal_api = {
                        "enabled": True,
                        "tcp_url": fixed_terminal_url,
                        "host": fixed_terminal_url.strip().split(":")[0] if ":" in fixed_terminal_url else fixed_terminal_url.strip(),
                        "port": int(fixed_terminal_url.strip().split(":")[1]) if ":" in fixed_terminal_url else 8818
                    }
                elif isinstance(raw_terminal_api, dict):
                    terminal_api = _sync_service_tcp_url(raw_terminal_api, client_ip)
                    # Ensure enabled field exists
                    if "enabled" not in terminal_api:
                        terminal_api["enabled"] = bool(terminal_api.get("tcp_url") or terminal_api.get("base_url_internal") or terminal_api.get("port"))
                    # Ensure at least one address field exists
                    if terminal_api.get("host") and terminal_api.get("port") and not terminal_api.get("tcp_url"):
                        terminal_api["tcp_url"] = f"{terminal_api['host']}:{terminal_api['port']}"
                else:
                    # Use existing if no new data
                    terminal_api = _copy_jsonable(existing.get("terminal_api", {}))

                self._agents[agent_id] = {
                    "id": agent_id,
                    "host": str(body.get("host") or "") or existing.get("host", ""),
                    "version": str(body.get("version") or "") or existing.get("version", ""),
                    "cmd_api_tcp": tcp_url or existing.get("cmd_api_tcp", ""),
                    "cmd_api_sock": str(body.get("cmd_api_sock") or "") or existing.get("cmd_api_sock", ""),
                    "cmd_api_password": str(body.get("cmd_api_password") or ""),
                    "web_console": web_console,
                    "terminal_api": terminal_api,
                    "task_list": body.get("task_list") if body.get("task_list") is not None else existing.get("task_list"),
                    "current_stage_index": current_stage_index if current_stage_index >= 0 else existing.get("current_stage_index", -1),
                    "total_stage_count": total_stage_count if total_stage_count > 0 else existing.get("total_stage_count", 0),
                    "is_mission_complete": bool(body.get("is_mission_complete")),
                    "current_stage_name": str(body.get("current_stage_name") or "") or existing.get("current_stage_name", ""),
                    "mcp_running": bool(body.get("mcp_running")),
                    "is_break": bool(body.get("is_break")),
                    "last_cmd": str(body.get("last_cmd") or "") or existing.get("last_cmd", ""),
                    "mission_info_ansi": str(body.get("mission_info_ansi") or "") or existing.get("mission_info_ansi", ""),
                    "run_time": str(body.get("run_time") or "") or existing.get("run_time", ""),
                    "meta": meta,
                    "extra": body.get("extra") or existing.get("extra", {}),
                    "last_launch_task_id": str(
                        body.get("launch_task_id")
                        or body.get("task_id")
                        or existing.get("last_launch_task_id")
                        or existing.get("launch_task_id")
                        or ""
                    ).strip(),
                    "client_exit": client_exit,
                    "exited_at": exited_at,
                    "exit_reason": exit_reason_value,
                    "first_seen": existing.get("first_seen", now),
                    "last_seen": now,
                }
            self._mark_dirty()
            if is_client_exit:
                _master_log(f"Agent '{agent_id}' exited ({exit_reason_value or 'exit'})")
                self._save_db()
            elif is_new or is_force:
                action = "rejoined" if is_force else "joined"
                _master_log(f"Agent '{agent_id}' {action} host={str(body.get('host') or '?')}")
            return {
                "status": "ok",
                "message": f"Agent '{agent_id}' registered.",
                "capabilities": {
                    "workspace_sync_back": self._workspace_sync_status(agent_id),
                },
            }

        @app.get("/api/agents", summary="List all agents", dependencies=[Depends(_check_password)])
        def list_agents(
            include_offline: bool = True,
            include_self: bool = True,
            strip_ansi: bool = True,
            page: int = 1,
            page_size: int = 20,
            sort_by: str = "last_seen",
            sort_desc: bool = True,
        ):
            page = max(1, page)
            page_size = max(1, min(page_size, 1000))
            valid_sort = {"id", "host", "status", "last_seen", "first_seen", "current_stage_index"}
            if sort_by not in valid_sort:
                sort_by = "last_seen"
            waiting_task_count = len(self._waiting_tasks())
            with self._agents_lock:
                data = []
                for agent in self._agents.values():
                    if not include_self and str(agent.get("id") or "") == "self":
                        continue
                    st = self._agent_status(agent)
                    if not include_offline and st != "online":
                        continue
                    tl = agent.get("task_list") or {}
                    raw_mi = agent.get("mission_info_ansi", "")
                    launch_task = self._launched_task_for_agent_id(agent["id"])
                    launch_task_exists = bool(launch_task)
                    launch_task_id = launch_task.get("task_id", "") if launch_task else self._agent_cached_launch_task_id(agent)
                    launch_task_status = str(launch_task.get("process_status") or "") if launch_task else ""
                    launch_task_finished = self._task_is_finished(launch_task)
                    completed_sub_workspace = self._agent_completed_sub_workspace(agent, launch_task)
                    data.append({
                        "id": agent["id"],
                        "host": agent["host"],
                        "version": agent["version"],
                        "cmd_api_tcp": agent["cmd_api_tcp"],
                        "cmd_api_sock": agent["cmd_api_sock"],
                        "status": st,
                        "client_exit": bool(agent.get("client_exit")),
                        "exited_at": agent.get("exited_at", 0),
                        "exit_reason": agent.get("exit_reason", ""),
                        "last_seen": agent["last_seen"],
                        "first_seen": agent["first_seen"],
                        "mission": tl.get("mission_name", ""),
                        "task_index": tl.get("task_index", -1),
                        "current_stage_index": agent.get("current_stage_index", -1),
                        "total_stage_count": agent.get("total_stage_count", 0),
                        "is_mission_complete": agent.get("is_mission_complete", False),
                        "current_stage_name": agent.get("current_stage_name", ""),
                        "mcp_running": agent.get("mcp_running", False),
                        "is_break": agent.get("is_break", False),
                        "last_cmd": agent.get("last_cmd", ""),
                        "run_time": agent.get("run_time", ""),
                        "meta": _copy_jsonable(agent.get("meta", {})) if isinstance(agent.get("meta"), dict) else {},
                        "mission_info_ansi": _strip_ansi(raw_mi) if strip_ansi else raw_mi,
                        "task_list": agent.get("task_list"),
                        "launch": bool(launch_task_id),
                        "launch_task_exists": launch_task_exists,
                        "launch_task_id": launch_task_id,
                        "launch_task_status": launch_task_status,
                        "launch_task_finished": launch_task_finished,
                        "completed_sub_workspace": completed_sub_workspace,
                        "cmd_api_proxy": f"/task/{launch_task_id}/cmd/" if launch_task_exists else f"/agent/{agent['id']}/cmd/",
                    })
                reverse = sort_desc
                if sort_by == "status":
                    status_rank = {"online": 0, "offline": 1, "exit": 2}
                    data.sort(key=lambda a: status_rank.get(a["status"], 3), reverse=reverse)
                else:
                    data.sort(key=lambda a: a.get(sort_by, ""), reverse=reverse)
                total_count = len(data)
                online_count = sum(1 for item in data if item.get("status") == "online")
                offline_count = sum(1 for item in data if item.get("status") != "online")
                total_pages = (total_count + page_size - 1) // page_size
                if total_pages and page > total_pages:
                    page = total_pages
                start_idx = (page - 1) * page_size
                page_data = data[start_idx:start_idx + page_size]
            return {
                "status": "ok",
                "count": total_count,
                "online_count": online_count,
                "offline_count": offline_count,
                "waiting_task_count": waiting_task_count,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "sort_by": sort_by,
                "sort_desc": sort_desc,
                "agents": page_data,
            }

        @app.get("/api/agent/{agent_id}", summary="Agent detail", dependencies=[Depends(_check_password)])
        def get_agent(agent_id: str, strip_ansi: bool = True):
            with self._agents_lock:
                agent = self._agents.get(agent_id)
            if agent is None:
                raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
            st = self._agent_status(agent)
            tl = agent.get("task_list") or {}
            raw_mi = agent.get("mission_info_ansi", "")
            launch_task = self._launched_task_for_agent_id(agent["id"])
            launch_task_exists = bool(launch_task)
            launch_task_id = launch_task.get("task_id", "") if launch_task else self._agent_cached_launch_task_id(agent)
            launch_task_status = str(launch_task.get("process_status") or "") if launch_task else ""
            launch_task_finished = self._task_is_finished(launch_task)
            completed_sub_workspace = self._agent_completed_sub_workspace(agent, launch_task)
            data = {
                "id": agent["id"],
                "host": agent["host"],
                "version": agent["version"],
                "cmd_api_tcp": agent["cmd_api_tcp"],
                "cmd_api_sock": agent["cmd_api_sock"],
                "status": st,
                "client_exit": bool(agent.get("client_exit")),
                "exited_at": agent.get("exited_at", 0),
                "exit_reason": agent.get("exit_reason", ""),
                "last_seen": agent["last_seen"],
                "first_seen": agent["first_seen"],
                "mission": tl.get("mission_name", ""),
                "task_index": tl.get("task_index", -1),
                "current_stage_index": agent.get("current_stage_index", -1),
                "total_stage_count": agent.get("total_stage_count", 0),
                "is_mission_complete": agent.get("is_mission_complete", False),
                "current_stage_name": agent.get("current_stage_name", ""),
                "mcp_running": agent.get("mcp_running", False),
                "is_break": agent.get("is_break", False),
                "last_cmd": agent.get("last_cmd", ""),
                "run_time": agent.get("run_time", ""),
                "meta": _copy_jsonable(agent.get("meta", {})) if isinstance(agent.get("meta"), dict) else {},
                "mission_info_ansi": _strip_ansi(raw_mi) if strip_ansi else raw_mi,
                "task_list": agent.get("task_list"),
                "launch": bool(launch_task_id),
                "launch_task_exists": launch_task_exists,
                "launch_task_id": launch_task_id,
                "launch_task_status": launch_task_status,
                "launch_task_finished": launch_task_finished,
                "completed_sub_workspace": completed_sub_workspace,
                "cmd_api_proxy": f"/task/{launch_task_id}/cmd/" if launch_task_exists else f"/agent/{agent['id']}/cmd/",
            }
            return {"status": "ok", "agent_status": st, "data": data}

        @app.delete("/api/agent/{agent_id}", summary="Remove an agent", dependencies=[Depends(_check_password)])
        def delete_agent(agent_id: str, block_rejoin: bool = True):
            with self._agents_lock:
                if agent_id not in self._agents:
                    raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
                del self._agents[agent_id]
            if block_rejoin:
                self._removed.add(agent_id)
            else:
                self._removed.discard(agent_id)
            self._mark_dirty()
            action = "unregistered" if block_rejoin else "deleted"
            _master_log(f"Agent '{agent_id}' {action} by operator")
            return {"status": "ok", "message": f"Agent '{agent_id}' {action}.", "block_rejoin": block_rejoin}

        @app.get("/api/launch/file-roots", summary="List configured launch file roots", dependencies=[Depends(_check_password)])
        def launch_file_roots():
            return {"status": "ok", "roots": self._launch_roots}

        @app.get("/api/launch/config", summary="Get launch default configuration", dependencies=[Depends(_check_password)])
        def launch_config():
            """Expose launch defaults and current runtime and simulator availability."""
            default_args = _plain_config_value(self.cfg.get_value("launch.default_args", {}) or {})
            backend_cfg = _plain_config_value(self.cfg.get_value("backend", {}) or {})
            backend_key_name = backend_cfg.get("key_name", "") if isinstance(backend_cfg, dict) else ""
            backend_options = []
            if isinstance(backend_cfg, dict):
                for key in backend_cfg.keys():
                    if key.startswith("_") or key == "key_name":
                        continue
                    if isinstance(backend_cfg.get(key), dict):
                        backend_options.append({"name": key, "value": key})
            launch_modes = self._launch_mode_options()
            enabled_launch_modes = self._enabled_launch_modes()
            default_launch_mode = enabled_launch_modes[0] if enabled_launch_modes else "process"
            if isinstance(default_args, dict):
                try:
                    enabled_launch_modes = _normalize_launch_mode_list(default_args.get("launch_mode", ["process"]))
                except ValueError:
                    enabled_launch_modes = ["process"]
                default_args["launch_mode"] = enabled_launch_modes
            first_available = next(
                (item["value"] for item in launch_modes if item["value"] in enabled_launch_modes and item["enabled"]),
                "",
            )
            if first_available:
                default_launch_mode = first_available
            elif not any(item["value"] == default_launch_mode and item["enabled"] for item in launch_modes):
                default_launch_mode = "process"
            simulators = self._picker_simulator_options()
            return {
                "status": "ok",
                "default_args": default_args,
                "backend_key_name": backend_key_name,
                "backend_options": backend_options,
                "simulators": simulators,
                "default_simulator": next((item["value"] for item in simulators if item["enabled"]), ""),
                "launch_modes": launch_modes,
                "default_launch_mode": default_launch_mode,
                "cluster": self._launch_cluster_config(),
            }

        @app.get("/api/launch/simulators", summary="Detect Picker simulators in the Master environment", dependencies=[Depends(_check_password)])
        def launch_simulators():
            """Refresh simulator executable availability without starting a compile."""
            simulators = self._picker_simulator_options()
            return {
                "status": "ok",
                "simulators": simulators,
                "default_simulator": next((item["value"] for item in simulators if item["enabled"]), ""),
            }

        @app.get("/api/launch/env-preview", summary="Preview inherited launch environment", dependencies=[Depends(_check_password)])
        def launch_env_preview():
            return {"status": "ok", "items": self._launch_env_preview()}

        @app.get("/api/launch/files", summary="Browse server files for launch", dependencies=[Depends(_check_password)])
        def launch_files(root_id: str, path: str = "", q: str = ""):
            try:
                root = self._get_launch_root(root_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            try:
                current = self._safe_under_root(root["path"], path)
            except ValueError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
            if not os.path.isdir(current):
                raise HTTPException(status_code=404, detail="Directory not found")

            query = q.strip().lower()
            dirs = []
            files = []
            for entry in sorted(os.listdir(current)):
                abs_path = os.path.join(current, entry)
                rel_path = os.path.relpath(abs_path, root["path"])
                rel_path = "" if rel_path == "." else rel_path
                if query and query not in entry.lower() and query not in rel_path.lower():
                    continue
                info = {
                    "name": entry,
                    "path": rel_path,
                    "size": os.path.getsize(abs_path) if os.path.isfile(abs_path) else 0,
                    "mtime": os.path.getmtime(abs_path),
                }
                if os.path.isdir(abs_path):
                    dirs.append(info)
                elif os.path.isfile(abs_path):
                    info["text"] = _is_text_file(abs_path)
                    files.append(info)
            parent_rel = os.path.relpath(os.path.dirname(current), root["path"])
            parent_rel = "" if parent_rel == "." else parent_rel
            breadcrumbs = []
            rel_current = os.path.relpath(current, root["path"])
            rel_current = "" if rel_current == "." else rel_current
            accum = []
            for part in [p for p in rel_current.split(os.sep) if p]:
                accum.append(part)
                breadcrumbs.append({"name": part, "path": os.path.join(*accum)})
            return {
                "status": "ok",
                "root": root,
                "path": rel_current,
                "parent_path": parent_rel if current != root["path"] else "",
                "breadcrumbs": breadcrumbs,
                "dirs": dirs,
                "files": files,
            }

        @app.post("/api/workspace", summary="Create launch workspace", dependencies=[Depends(_check_password)])
        def create_workspace():
            ws = self._create_workspace()
            return {"status": "ok", "workspace": self._workspace_public(ws)}

        @app.post("/api/workspace/{workspace_id}/heartbeat", summary="Refresh launch workspace page heartbeat", dependencies=[Depends(_check_password)])
        def workspace_heartbeat(workspace_id: str, body: Dict[str, Any] = Body(default_factory=dict)):
            try:
                status = str((body or {}).get("status") or "").strip()
                ws = self._touch_workspace_launch_session(workspace_id, status=status)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            if ws.get("launch_status") == "released":
                self._cleanup_stale_workspaces()
            return {"status": "ok", "workspace": self._workspace_public(ws)}

        @app.get("/api/workspace/{workspace_id}.tar.gz", summary="Download compiled DUT workspace archive", dependencies=[Depends(_check_workspace_archive_access)])
        def workspace_download_compiled_archive(workspace_id: str):
            return _workspace_download_compiled(workspace_id)

        @app.get("/api/workspace/{workspace_id}", summary="Workspace detail", dependencies=[Depends(_check_password)])
        def get_workspace(workspace_id: str):
            try:
                ws = self._get_workspace(workspace_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return {"status": "ok", "workspace": self._workspace_public(ws)}

        @app.get("/api/workspace/{workspace_id}/files", summary="List workspace files", dependencies=[Depends(_check_password)])
        def workspace_files(workspace_id: str):
            try:
                entries = self._list_workspace_tree(workspace_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return {"status": "ok", "files": entries}

        @app.post("/api/workspace/{workspace_id}/file/upload", summary="Upload a file into launch workspace", dependencies=[Depends(_check_password)])
        async def workspace_upload_file(workspace_id: str, request: Request):
            try:
                self._get_workspace(workspace_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            try:
                form = await request.form()
            except Exception as exc:
                warning(f"Launch upload parse failed for workspace '{workspace_id}': {exc}")
                raise HTTPException(status_code=400, detail=f"Failed to parse upload form: {exc}") from exc
            category = str(form.get("category") or "misc").strip() or "misc"
            upload_file = None
            for key in ("file", "upload", "files"):
                candidate = form.get(key)
                if hasattr(candidate, "read"):
                    upload_file = candidate
                    break
            if upload_file is None:
                form_keys = sorted(str(key) for key in form.keys())
                detail = "Missing uploaded file"
                if form_keys:
                    detail += f"; received form fields: {', '.join(form_keys)}"
                raise HTTPException(status_code=400, detail=detail)
            category = str(category or "misc").strip() or "misc"
            if not hasattr(upload_file, "read"):
                raise HTTPException(status_code=400, detail="Invalid uploaded file")
            data = await upload_file.read()
            item = self._store_file_bytes(
                workspace_id,
                category,
                upload_file.filename or "upload.bin",
                data,
                "upload",
                upload_file.filename or "",
            )
            ws = self._get_workspace(workspace_id)
            return {"status": "ok", "file": self._workspace_file_public(ws, item), "workspace": self._workspace_public(ws)}

        @app.post("/api/workspace/{workspace_id}/import-files", summary="Import files from server into launch workspace", dependencies=[Depends(_check_password)])
        def workspace_import_files(workspace_id: str, body: Dict[str, Any] = Body(default_factory=dict)):
            root_id = str(body.get("root_id") or "").strip()
            if not root_id and self._launch_roots:
                root_id = self._launch_roots[0]["id"]
            category = str(body.get("category") or "misc").strip() or "misc"
            raw_paths = body.get("paths") or []
            if isinstance(raw_paths, str):
                paths = [raw_paths]
            elif isinstance(raw_paths, list):
                paths = [str(item).strip() for item in raw_paths if str(item).strip()]
            else:
                raise HTTPException(status_code=400, detail="'paths' must be a list of relative file paths")
            if not paths:
                raise HTTPException(status_code=400, detail="No files were selected for import")
            try:
                self._get_workspace(workspace_id)
                root = self._get_launch_root(root_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            imported = []
            for rel_path in paths:
                try:
                    abs_path = self._safe_under_root(root["path"], rel_path)
                except ValueError as exc:
                    raise HTTPException(status_code=403, detail=str(exc)) from exc
                if not os.path.isfile(abs_path):
                    raise HTTPException(status_code=400, detail=f"'{rel_path}' is not a file")
                imported.append(self._store_existing_file(workspace_id, category, abs_path))
            ws = self._get_workspace(workspace_id)
            return {
                "status": "ok",
                "files": [self._workspace_file_public(ws, item) for item in imported],
                "workspace": self._workspace_public(ws),
            }

        @app.post("/api/workspace/{workspace_id}/apply-yaml", summary="Apply launch YAML spec to workspace", dependencies=[Depends(_check_password)])
        def workspace_apply_yaml(workspace_id: str, body: Dict[str, Any] = Body(default_factory=dict)):
            root_id = str(body.get("root_id") or "").strip()
            if not root_id and self._launch_roots:
                root_id = self._launch_roots[0]["id"]
            rel_path = str(body.get("path") or body.get("yaml_path") or "").strip()
            if not rel_path:
                raise HTTPException(status_code=400, detail="'path' is required")
            try:
                self._get_workspace(workspace_id)
                root = self._get_launch_root(root_id)
                yaml_path = self._safe_under_root(root["path"], rel_path)
                result = self._apply_launch_yaml_spec(workspace_id, yaml_path)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"status": "ok", **result}

        @app.patch("/api/workspace/{workspace_id}/file", summary="Update launch workspace file metadata", dependencies=[Depends(_check_password)])
        def workspace_update_file(workspace_id: str, body: Dict[str, Any] = Body(default_factory=dict)):
            try:
                item_id = str(body.get("item_id") or "").strip()
                category = str(body.get("category") or "").strip()
                if not item_id:
                    raise ValueError("'item_id' is required")
                if not category:
                    raise ValueError("'category' is required")
                ws = self._update_workspace_item_category(workspace_id, item_id, category)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"status": "ok", "workspace": ws}

        @app.delete("/api/workspace/{workspace_id}/file", summary="Delete file from launch workspace", dependencies=[Depends(_check_password)])
        def workspace_delete_file(workspace_id: str, path: str = Query(...)):
            try:
                ws = self._get_workspace(workspace_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            item_id = str(path or "").strip()
            item_by_id = self._find_workspace_item_by_id(ws, item_id)
            if item_by_id is not None:
                stored_path = item_by_id.get("stored_path", "")
                with self._workspaces_lock:
                    ws_locked = self._workspaces.get(workspace_id)
                    if ws_locked is not None:
                        ws_locked["files"] = [
                            item for item in ws_locked.get("files", [])
                            if item.get("item_id") != item_id
                        ]
                        self._clear_workspace_compile_locked(ws_locked)
                if stored_path and _path_is_under(ws["workspace_dir"], stored_path) and os.path.exists(stored_path):
                    if os.path.isdir(stored_path):
                        shutil.rmtree(stored_path)
                    else:
                        os.unlink(stored_path)
                self._mark_dirty()
                return {"status": "ok"}
            try:
                abs_path = self._safe_under_root(ws["workspace_dir"], path)
            except ValueError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
            if not os.path.exists(abs_path):
                raise HTTPException(status_code=404, detail="Path not found")
            if os.path.isdir(abs_path):
                shutil.rmtree(abs_path)
            else:
                os.unlink(abs_path)
            with self._workspaces_lock:
                ws = self._workspaces.get(workspace_id)
                if ws is not None:
                    ws["files"] = [item for item in ws.get("files", []) if os.path.abspath(item.get("stored_path", "")) != os.path.abspath(abs_path)]
                    self._clear_workspace_compile_locked(ws)
            self._mark_dirty()
            return {"status": "ok"}

        @app.get("/api/workspace/{workspace_id}/file/download", summary="Download workspace file", dependencies=[Depends(_check_password)])
        def workspace_download_file(workspace_id: str, path: str):
            from fastapi.responses import FileResponse

            try:
                ws = self._get_workspace(workspace_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            item = self._find_workspace_item_by_id(ws, str(path or "").strip())
            if item is not None:
                abs_path = item.get("stored_path", "")
            else:
                try:
                    abs_path = self._safe_under_root(ws["workspace_dir"], path)
                except ValueError as exc:
                    raise HTTPException(status_code=403, detail=str(exc)) from exc
            if not os.path.isfile(abs_path):
                raise HTTPException(status_code=404, detail="File not found")
            return FileResponse(abs_path, filename=os.path.basename(abs_path))

        def _workspace_download_compiled(workspace_id: str):
            from starlette.background import BackgroundTask
            from fastapi.responses import FileResponse

            try:
                ws = self._get_workspace_by_id_or_dirname(workspace_id)
                archive_path, filename, temp_dir = self._create_compiled_workspace_archive(ws, workspace_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return FileResponse(
                archive_path,
                filename=filename,
                media_type="application/gzip",
                background=BackgroundTask(shutil.rmtree, temp_dir, ignore_errors=True),
            )

        @app.get("/api/workspace/{workspace_id}/download", summary="Download compiled DUT workspace", dependencies=[Depends(_check_password)])
        def workspace_download_compiled(workspace_id: str):
            return _workspace_download_compiled(workspace_id)

        @app.post("/api/workspace/{workspace_id}/verilog/modules", summary="Parse module names from a Verilog file", dependencies=[Depends(_check_password)])
        def workspace_parse_modules(workspace_id: str, body: Dict[str, Any] = Body(default_factory=dict)):
            try:
                ws = self._get_workspace(workspace_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            file_path = str(body.get("file_path") or "").strip()
            try:
                item = self._select_main_item(ws, file_path)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if item is None:
                raise HTTPException(status_code=400, detail="No main Verilog file found in workspace")
            try:
                with open(item["stored_path"], "r", encoding="utf-8", errors="replace") as fh:
                    modules = _parse_module_names(fh.read())
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Failed to parse Verilog file: {exc}") from exc
            return {"status": "ok", "file": self._workspace_file_public(ws, item), "modules": modules}

        @app.post("/api/workspace/{workspace_id}/compile", summary="Compile DUT in launch workspace", dependencies=[Depends(_check_password)])
        @app.post("/api/workspace/{workspace_id}/picker", summary="Run picker export in launch workspace", dependencies=[Depends(_check_password)])
        def workspace_picker(workspace_id: str, body: Dict[str, Any] = Body(default_factory=dict)):
            """Compile a workspace using validated simulator settings and return its result."""
            try:
                selected_module = str(body.get("selected_module") or "").strip()
                if not selected_module:
                    raise ValueError("'selected_module' is required")
                result = self._compile_workspace_dut(
                    workspace_id=workspace_id,
                    effective_dut=str(body.get("dut_name") or "").strip() or selected_module,
                    selected_module=selected_module,
                    main_verilog_path=str(body.get("main_verilog_path") or ""),
                    picker_extra_args=body.get("picker_args", body.get("picker_extra_args", None)),
                    simulator=body.get("simulator"),
                )
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            ws = self._get_workspace(workspace_id)
            return {
                "status": "ok" if result["picker"]["success"] else "failed",
                "workspace": self._workspace_public(ws),
                "compile": self._workspace_compile_public(ws),
                "result": result["picker"],
                "prepared": result["prepared"],
            }

        @app.post("/api/workspace/{workspace_id}/compile/stream", summary="Compile DUT with streaming logs", dependencies=[Depends(_check_password)])
        def workspace_compile_stream(workspace_id: str, body: Dict[str, Any] = Body(default_factory=dict)):
            """Compile a workspace with NDJSON progress and a final simulator-specific result."""
            from fastapi.responses import StreamingResponse

            selected_module = str(body.get("selected_module") or "").strip()
            if not selected_module:
                raise HTTPException(status_code=400, detail="'selected_module' is required")
            effective_dut = str(body.get("dut_name") or "").strip() or selected_module
            main_verilog_path = str(body.get("main_verilog_path") or "")
            try:
                simulator, picker_extra_args = self._validate_compile_options(
                    body.get("simulator"), body.get("picker_args", body.get("picker_extra_args", None)),
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            def emit(event: Dict[str, Any]) -> bytes:
                return (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")

            def stream():
                """Emit preparation, process output, and the persisted compilation result as NDJSON."""
                try:
                    prepared = self._prepare_workspace_layout(
                        workspace_id,
                        effective_dut=effective_dut,
                        selected_module=selected_module,
                        main_verilog_path=main_verilog_path,
                        picker_extra_args=picker_extra_args,
                        simulator=simulator,
                    )
                    yield emit({
                        "type": "info",
                        "message": (
                            f"Prepared workspace layout: RTL={prepared['rtl_dir']} DOC={prepared['doc_dir']}\n"
                            f"Picker: {shlex.join(prepared['picker_command'])}"
                        ),
                    })
                    picker = yield from self._stream_picker_run(
                        workspace_dir=prepared["workspace_dir"],
                        picker_workspace=prepared["picker_workspace"],
                        dut_name=prepared["dut_name"],
                        selected_module=selected_module,
                        main_verilog_path=prepared["main_verilog_path"],
                        filelist_path=prepared["filelist_path"],
                        f_filelist_paths=prepared["f_filelist_paths"],
                        picker_extra_args=prepared["picker_extra_args"],
                        command=prepared["picker_command"],
                    )
                    if self._picker_create_conflict(prepared["picker_workspace"], prepared["dut_name"], picker["stdout"] + picker["stderr"]):
                        yield emit({
                            "type": "info",
                            "message": f"Detected existing package directory, cleaning {os.path.join(prepared['picker_workspace'], prepared['dut_name'])} and retrying...",
                        })
                        shutil.rmtree(os.path.join(prepared["picker_workspace"], prepared["dut_name"]), ignore_errors=True)
                        picker = yield from self._stream_picker_run(
                            workspace_dir=prepared["workspace_dir"],
                            picker_workspace=prepared["picker_workspace"],
                            dut_name=prepared["dut_name"],
                            selected_module=selected_module,
                            main_verilog_path=prepared["main_verilog_path"],
                            filelist_path=prepared["filelist_path"],
                            f_filelist_paths=prepared["f_filelist_paths"],
                            picker_extra_args=prepared["picker_extra_args"],
                            command=prepared["picker_command"],
                        )
                    readme_path = ""
                    if picker["success"]:
                        readme_path = self._copy_requirement_readme(self._get_workspace(workspace_id), prepared["dut_dir"])
                    compile_info = {
                        "status": "success" if picker["success"] else "failed",
                        "dut_name": prepared["dut_name"],
                        "selected_module": selected_module,
                        "main_verilog_path": prepared["source_main_verilog_path"],
                        "compiled_main_verilog_path": prepared["main_verilog_path"],
                        "picker_workspace": prepared["picker_workspace"],
                        "rtl_dir": prepared["rtl_dir"],
                        "doc_dir": prepared["doc_dir"],
                        "dut_dir": prepared["dut_dir"],
                        "filelist_path": prepared["filelist_path"],
                        "source_f_filelist_paths": prepared["source_f_filelist_paths"],
                        "f_filelist_paths": prepared["f_filelist_paths"],
                        "generated_filelist": prepared["generated_filelist"],
                        "config_path": prepared.get("config_path", ""),
                        "readme_path": readme_path,
                        "compiled_at": _now(),
                        "copied_files": prepared["copied_files"],
                        "simulator": prepared["simulator"],
                        "waveform_suffix": prepared["waveform_suffix"],
                        "picker_command": picker["command"],
                        "picker_extra_args": prepared["picker_extra_args"],
                        "picker_exit_code": picker["exit_code"],
                        "picker_stdout": picker["stdout"],
                        "picker_stderr": picker["stderr"],
                    }
                    with self._workspaces_lock:
                        ws = self._workspaces.get(workspace_id)
                        if ws is None:
                            raise KeyError(f"Workspace '{workspace_id}' not found")
                        ws["compile"] = compile_info
                    self._mark_dirty()
                    ws = self._get_workspace(workspace_id)
                    yield emit({
                        "type": "final",
                        "status": "ok" if picker["success"] else "failed",
                        "workspace": self._workspace_public(ws),
                        "compile": self._workspace_compile_public(ws),
                        "result": picker,
                        "prepared": prepared,
                    })
                except Exception as exc:
                    yield emit({"type": "final", "status": "failed", "error": str(exc)})

            return StreamingResponse(stream(), media_type="application/x-ndjson")

        @app.post("/api/workspace/{workspace_id}/compile/start", summary="Start background DUT compile", dependencies=[Depends(_check_password)])
        def workspace_compile_start(workspace_id: str, body: Dict[str, Any] = Body(default_factory=dict)):
            """Validate a simulator selection and start or reuse its background compilation."""
            try:
                self._get_workspace(workspace_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            selected_module = str(body.get("selected_module") or "").strip()
            if not selected_module:
                raise HTTPException(status_code=400, detail="'selected_module' is required")
            try:
                runtime = self._start_compile_job(
                    workspace_id,
                    str(body.get("dut_name") or "").strip() or selected_module,
                    selected_module,
                    str(body.get("main_verilog_path") or ""),
                    body.get("picker_args", body.get("picker_extra_args", None)),
                    body.get("simulator"),
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"status": "ok", "runtime": runtime}

        @app.get("/api/workspace/{workspace_id}/compile/status", summary="Get background DUT compile status", dependencies=[Depends(_check_password)])
        def workspace_compile_status(workspace_id: str, cursor: int = 0):
            try:
                self._get_workspace(workspace_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return {"status": "ok", "runtime": self._compile_runtime_public(workspace_id, cursor)}

        @app.get("/api/workspace/{workspace_id}/config-options", summary="Get available config options for workspace", dependencies=[Depends(_check_password)])
        def workspace_config_options(workspace_id: str):
            ws = self._get_workspace(workspace_id)
            compile_info = ws.get("compile") or {}
            doc_dir = compile_info.get("doc_dir") or ""
            default_args = self.cfg.get_value("launch.default_args", {}) or {}
            if hasattr(default_args, "as_dict"):
                default_args = default_args.as_dict()
            predefined_configs = default_args.get("configs", {}) if isinstance(default_args, dict) else {}
            options = []
            if isinstance(predefined_configs, dict):
                for name, value in predefined_configs.items():
                    name_str = str(name)
                    if name_str.startswith("_"):
                        continue
                    cfg_value = ""
                    defaults: Dict[str, Any] = {}
                    value = _plain_config_value(value)
                    if isinstance(value, dict):
                        defaults = dict(value)
                        cfg_value = defaults.pop("cfg", defaults.get("config", ""))
                        if cfg_value not in (None, ""):
                            defaults["config"] = cfg_value
                    else:
                        cfg_value = value
                        if cfg_value not in (None, ""):
                            defaults["config"] = cfg_value
                    options.append({
                        "name": name_str,
                        "value": str(cfg_value or name_str),
                        "source": "predefined",
                        "defaults": defaults,
                        "preset_name": name_str,
                    })
            if doc_dir and os.path.isdir(doc_dir):
                try:
                    for entry in sorted(os.listdir(doc_dir)):
                        if entry.lower().endswith((".yaml", ".yml")):
                            options.append({"name": entry, "value": entry, "source": "doc_dir"})
                except OSError:
                    pass
            return {"status": "ok", "options": options, "doc_dir": doc_dir}

        @app.post("/api/tasks", summary="Create and start a managed task", dependencies=[Depends(_check_password)])
        def create_task(body: Dict[str, Any] = Body(default_factory=dict)):
            try:
                task = self._run_task_launch(dict(body))
            except (KeyError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"status": "ok" if task["process_status"] != "failed" else "failed", "task": self._task_public(task, include_logs=True)}

        @app.get("/api/relaunch/status", summary="Check relaunch availability", dependencies=[Depends(_check_password)])
        def relaunch_status(
            task_id: str = "",
            workspace_id: str = "",
            sub_worspace: str = "",
            sub_workspace: str = "",
        ):
            try:
                data = self._relaunch_status(
                    task_id=task_id,
                    workspace_id=workspace_id,
                    sub_workspace=sub_worspace or sub_workspace,
                )
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"status": "ok", "data": data}

        @app.delete("/api/relaunch/ucagent-info", summary="Switch saved relaunch UCAgent info by config", dependencies=[Depends(_check_password)])
        def clear_relaunch_ucagent_info(
            task_id: str = "",
            workspace_id: str = "",
            sub_worspace: str = "",
            sub_workspace: str = "",
            target_config: str = "",
        ):
            try:
                data = self._clear_relaunch_ucagent_info(
                    task_id=task_id,
                    workspace_id=workspace_id,
                    sub_workspace=sub_worspace or sub_workspace,
                    target_config=target_config,
                )
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"status": "ok", "data": data}

        @app.post("/api/relaunch", summary="Relaunch a completed managed task", dependencies=[Depends(_check_password)])
        def relaunch_task(body: Dict[str, Any] = Body(default_factory=dict)):
            """Relaunch a completed task with its recorded DUT package and simulator."""
            req = dict(body)
            try:
                status = self._relaunch_status(
                    task_id=str(req.get("task_id") or ""),
                    workspace_id=str(req.get("workspace_id") or ""),
                    sub_workspace=str(req.get("sub_worspace") or req.get("sub_workspace") or ""),
                )
                if not status.get("can_relaunch"):
                    raise ValueError(status.get("message") or "Task cannot be relaunched yet")
                compile_info = status.get("compile") or {}
                ucagent_info = status.get("ucagent_info") or {}
                info_dut_name = str(ucagent_info.get("dut_name") or ucagent_info.get("DUT") or "").strip()
                info_selected_module = str(ucagent_info.get("selected_module") or "").strip()
                requested_config = str(req.get("config") or "").strip()
                if requested_config:
                    target = self._resolve_relaunch_target(
                        task_id=status["task_id"],
                        workspace_id=status["workspace_id"],
                        sub_workspace=str(req.get("sub_worspace") or req.get("sub_workspace") or ""),
                    )
                    self._switch_relaunch_ucagent_info_config(target["workspace"], requested_config)
                self._drop_finished_task_record_for_relaunch(status["task_id"])
                req["task_id"] = status["task_id"]
                req["task_name"] = status["task_id"]
                req["workspace_id"] = status["workspace_id"]
                req["dut_name"] = str(compile_info.get("dut_name") or info_dut_name or req.get("dut_name") or "")
                req["selected_module"] = str(compile_info.get("selected_module") or info_selected_module or req.get("selected_module") or req["dut_name"])
                req["main_verilog_path"] = compile_info.get("main_verilog_path") or ""
                req["picker_args"] = list(compile_info.get("picker_extra_args") or [])
                if compile_info.get("simulator"):
                    req["simulator"] = compile_info["simulator"]
                if status.get("workspace_source") == "ucagent_info":
                    req["_relaunch_from_ucagent_info"] = True
                task = self._run_task_launch(req)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"status": "ok" if task["process_status"] != "failed" else "failed", "task": self._task_public(task, include_logs=True)}

        @app.get("/api/tasks", summary="List managed tasks", dependencies=[Depends(_check_password)])
        def list_tasks(status: str = "", dut: str = "", q: str = ""):
            self._refresh_task_states()
            status = status.strip().lower()
            dut = dut.strip().lower()
            q = q.strip().lower()
            with self._tasks_lock:
                tasks = [self._task_public(task) for task in self._tasks.values()]
            queue_positions = self._waiting_queue_positions()
            data = []
            for task in tasks:
                if status and task.get("process_status", "").lower() != status:
                    continue
                hay_dut = f"{task.get('dut_name', '')} {task.get('selected_module', '')}".lower()
                if dut and dut not in hay_dut:
                    continue
                hay = f"{task.get('task_id', '')} {task.get('pid', '')} {task.get('workspace_dir', '')}".lower()
                if q and q not in hay:
                    continue
                if str(task.get("process_status") or "") == _WAITING_TASK_STATUS:
                    task["queue_position"] = queue_positions.get(str(task.get("task_id") or ""))
                data.append(task)
            data.sort(key=lambda item: item.get("created_at", 0), reverse=True)
            return {"status": "ok", "tasks": data, "count": len(data), "max_task_count": self._max_task_count()}

        @app.post("/api/tasks/waiting/order", summary="Reorder the waiting launch queue", dependencies=[Depends(_check_password)])
        def reorder_waiting_tasks(body: Dict[str, Any] = Body(default_factory=dict)):
            task_ids = body.get("task_ids")
            if not isinstance(task_ids, list):
                raise HTTPException(
                    status_code=400,
                    detail="'task_ids' must be a list of every waiting task id in the desired start order",
                )
            try:
                order = self._reorder_waiting_tasks(task_ids)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"status": "ok", "task_ids": order, "count": len(order)}

        _STATIC_DIR = pathlib.Path(__file__).resolve().parent.parent / "static"

        @app.get("/static/{path:path}", summary="Serve bundled static assets", include_in_schema=False, dependencies=[Depends(_check_password)])
        def serve_static(path: str):
            from fastapi.responses import FileResponse

            abs_path = (_STATIC_DIR / path).resolve()
            if not str(abs_path).startswith(str(_STATIC_DIR)):
                raise HTTPException(status_code=403, detail="Forbidden")
            if not abs_path.is_file():
                raise HTTPException(status_code=404, detail=f"Static asset '{path}' not found")
            media_type, _ = mimetypes.guess_type(str(abs_path))
            return FileResponse(path=str(abs_path), media_type=media_type or "application/octet-stream")

        @app.get("/api/task/{task_id}", summary="Managed task detail", dependencies=[Depends(_check_password)])
        def get_task(task_id: str):
            self._refresh_task_states()
            try:
                task = self._get_task(task_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            data = self._task_public(task, include_logs=True)
            if str(data.get("process_status") or "") == _WAITING_TASK_STATUS:
                data["queue_position"] = self._waiting_queue_positions().get(task_id)
            return {"status": "ok", "task": data}

        @app.get("/api/task/{task_id}/command", summary="Managed task command", dependencies=[Depends(_check_password)])
        def get_task_command(task_id: str):
            self._refresh_task_states()
            try:
                task = self._get_task(task_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return {"status": "ok", "command": task.get("resolved_command", []), "env": task.get("env", {})}

        @app.get("/api/task/{task_id}/logs", summary="Managed task logs", dependencies=[Depends(_check_password)])
        def get_task_logs(task_id: str):
            self._refresh_task_states()
            try:
                task = self._get_task(task_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            self._drain_finished_task_runtime(task)
            logs = _task_logs_for_display(task)
            return {
                "status": "ok",
                "stdout": logs["stdout"],
                "stderr": logs["stderr"],
            }

        @app.post("/api/task/{task_id}/stop", summary="Stop managed task", dependencies=[Depends(_check_password)])
        def stop_task(task_id: str, body: Dict[str, Any] = Body(default_factory=dict)):
            try:
                task = self._get_task(task_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            if task["process_status"] in {"stopped", "failed"}:
                return {"status": "ok", "task": self._task_public(task), "message": "Task already stopped"}
            if task["process_status"] == _WAITING_TASK_STATUS:
                # Nothing is executing yet; leaving the queue keeps the record
                # and its workspace so the task can be relaunched later.
                task["process_status"] = "stopped"
                task["finished_at"] = _now()
                task["cmd_api"]["status"] = "stopped"
                task["terminal_api"]["status"] = "stopped"
                self._append_task_log(task["stderr_log_path"], "Task removed from the waiting queue before it started.")
                self._mark_dirty()
                return {"status": "ok", "task": self._task_public(task), "message": "Task removed from waiting queue"}
            task["process_status"] = "stopping"
            force = bool((body or {}).get("force"))
            self._terminate_task(task, force=force)
            if task.get("launch_mode") in _CONTAINER_LAUNCH_MODES:
                task["finished_at"] = task.get("finished_at") or _now()
                task["exit_code"] = task.get("exit_code")
                task["process_status"] = "stopped"
                task["cmd_api"]["status"] = "stopped"
                task["terminal_api"]["status"] = "stopped"
            self._mark_dirty()
            return {"status": "ok", "task": self._task_public(task)}

        @app.delete("/api/task/{task_id}", summary="Delete managed task record", dependencies=[Depends(_check_password)])
        def delete_task(task_id: str):
            task_snapshot: Dict[str, Any] = {}
            with self._tasks_lock:
                task = self._tasks.get(task_id)
                if task is None:
                    raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
                if task.get("process_status") in {"starting", "running"}:
                    raise HTTPException(status_code=400, detail="Running task cannot be deleted")
                task_snapshot = dict(task)
                del self._tasks[task_id]
            if task_snapshot.get("process_status") == _WAITING_TASK_STATUS:
                # Cancelling a waiting task also drops its workspace so the
                # queued submission leaves nothing behind.
                removed_dir = self._purge_waiting_task_workspace(task_snapshot)
                self._close_task_runtime(task_id)
                self._mark_dirty()
                return {"status": "ok", "removed_workspace_dir": removed_dir}
            self._remember_task_launch_agent(task_snapshot)
            self._close_task_runtime(task_id)
            self._mark_dirty()
            return {"status": "ok"}

        @app.api_route("/task/{task_id}/cmd", methods=_PROXY_METHODS, dependencies=[Depends(_check_password)], include_in_schema=False)
        @app.api_route("/task/{task_id}/cmd/{subpath:path}", methods=_PROXY_METHODS, dependencies=[Depends(_check_password)], include_in_schema=False)
        async def proxy_cmd(task_id: str, request: Request, subpath: str = ""):
            try:
                task = self._get_task(task_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            if task["cmd_api"].get("status") not in {"running", "starting", "unavailable"}:
                raise HTTPException(status_code=503, detail="CMD API service is not available")

            target_url = self._cmd_proxy_url(task, subpath)
            if request.url.query:
                target_url += "?" + request.url.query
            headers = self._build_proxy_headers(task["cmd_api"].get("password", ""), dict(request.headers))
            return await _proxy_http_request(
                request,
                target_url,
                headers,
                {
                    '"/api/': f'"/task/{task_id}/cmd/api/',
                    "'/api/": f"'/task/{task_id}/cmd/api/",
                    '"/workspace': f'"/task/{task_id}/cmd/workspace',
                    "'/workspace": f"'/task/{task_id}/cmd/workspace",
                    '"/complete': f'"/task/{task_id}/cmd/complete',
                    "'/complete": f"'/task/{task_id}/cmd/complete",
                    '"/static/': f'"/task/{task_id}/cmd/static/',
                    "'/static/": f"'/task/{task_id}/cmd/static/",
                    '"/wave': f'"/task/{task_id}/cmd/wave',
                    "'/wave": f"'/task/{task_id}/cmd/wave",
                    '"/surfer': f'"/task/{task_id}/cmd/surfer',
                    "'/surfer": f"'/task/{task_id}/cmd/surfer",
                },
                "CMD API",
            )

        @app.api_route("/agent/{agent_id}/cmd", methods=_PROXY_METHODS, dependencies=[Depends(_check_password)], include_in_schema=False)
        @app.api_route("/agent/{agent_id}/cmd/{subpath:path}", methods=_PROXY_METHODS, dependencies=[Depends(_check_password)], include_in_schema=False)
        async def proxy_agent_cmd(agent_id: str, request: Request, subpath: str = ""):
            try:
                with self._agents_lock:
                    agent = self._agents.get(agent_id)
                    if not agent:
                        raise KeyError(f"Agent '{agent_id}' not found")
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

            status = self._agent_status(agent)
            if status != "online":
                raise HTTPException(status_code=503, detail="Agent is offline")

            if not agent.get("cmd_api_tcp"):
                raise HTTPException(status_code=503, detail="CMD API service is not available for this agent")

            target_url = self._agent_cmd_proxy_url(agent, subpath)
            if request.url.query:
                target_url += "?" + request.url.query

            # Agent CMD API may not have password, use empty string if none
            password = agent.get("cmd_api_password", "")
            headers = self._build_proxy_headers(password, dict(request.headers))
            return await _proxy_http_request(
                request,
                target_url,
                headers,
                {
                    '"/api/': f'"/agent/{agent_id}/cmd/api/',
                    "'/api/": f"'/agent/{agent_id}/cmd/api/",
                    '"/workspace': f'"/agent/{agent_id}/cmd/workspace',
                    "'/workspace": f"'/agent/{agent_id}/cmd/workspace",
                    '"/complete': f'"/agent/{agent_id}/cmd/complete',
                    "'/complete": f"'/agent/{agent_id}/cmd/complete",
                    '"/static/': f'"/agent/{agent_id}/cmd/static/',
                    "'/static/": f"'/agent/{agent_id}/cmd/static/",
                    '"/wave': f'"/agent/{agent_id}/cmd/wave',
                    "'/wave": f"'/agent/{agent_id}/cmd/wave",
                    '"/surfer': f'"/agent/{agent_id}/cmd/surfer',
                    "'/surfer": f"'/agent/{agent_id}/cmd/surfer",
                },
                "Agent CMD API",
            )

        @app.api_route("/task/{task_id}/terminal", methods=_PROXY_METHODS, dependencies=[Depends(_check_password)], include_in_schema=False)
        @app.api_route("/task/{task_id}/terminal/{subpath:path}", methods=_PROXY_METHODS, dependencies=[Depends(_check_password)], include_in_schema=False)
        async def proxy_terminal(task_id: str, request: Request, subpath: str = ""):
            if subpath == "ws":
                raise HTTPException(status_code=400, detail="Use WebSocket endpoint")
            try:
                task = self._get_task(task_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            if task["terminal_api"].get("status") not in {"running", "starting", "unavailable"}:
                raise HTTPException(status_code=503, detail="Terminal API service is not available")

            target_url = self._terminal_proxy_url(task, subpath)
            if request.url.query:
                target_url += "?" + request.url.query
            headers = self._build_proxy_headers(task["terminal_api"].get("password", ""), dict(request.headers))
            body = await request.body()
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.request(request.method, target_url, data=body or None, headers=headers, allow_redirects=False) as resp:
                        raw = await resp.read()
                        content_type = resp.headers.get("Content-Type", "")
                        if "text/html" in content_type:
                            text = raw.decode("utf-8", errors="replace")
                            text = _rewrite_html(text, {
                                '"/ws': f'"/task/{task_id}/terminal/ws',
                                "'/ws": f"'/task/{task_id}/terminal/ws",
                                '"/api/': f'"/task/{task_id}/terminal/api/',
                                "'/api/": f"'/task/{task_id}/terminal/api/",
                                '"/static/': f'"/task/{task_id}/terminal/static/',
                                "'/static/": f"'/task/{task_id}/terminal/static/",
                            })
                            raw = text.encode("utf-8")
                        response_headers = {}
                        for key, value in resp.headers.items():
                            if key.lower() in {"content-length", "transfer-encoding", "content-encoding", "connection", "www-authenticate"}:
                                continue
                            response_headers[key] = value
                        return Response(content=raw, status_code=resp.status, headers=response_headers, media_type=None)
                except Exception as exc:
                    raise HTTPException(status_code=502, detail=f"Failed to proxy Terminal API: {exc}") from exc

        @app.api_route("/agent/{agent_id}/terminal", methods=_PROXY_METHODS, dependencies=[Depends(_check_password)], include_in_schema=False)
        @app.api_route("/agent/{agent_id}/terminal/{subpath:path}", methods=_PROXY_METHODS, dependencies=[Depends(_check_password)], include_in_schema=False)
        async def proxy_agent_terminal(agent_id: str, request: Request, subpath: str = ""):
            if subpath == "ws":
                raise HTTPException(status_code=400, detail="Use WebSocket endpoint")
            try:
                with self._agents_lock:
                    agent = self._agents.get(agent_id)
                    if not agent:
                        raise KeyError(f"Agent '{agent_id}' not found")
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

            status = self._agent_status(agent)
            if status != "online":
                raise HTTPException(status_code=503, detail="Agent is offline")

            terminal_api = agent.get("terminal_api", {})
            if not terminal_api:
                raise HTTPException(status_code=503, detail="Terminal API service is not available for this agent")

            target_url = self._agent_terminal_proxy_url(agent, subpath)
            if request.url.query:
                target_url += "?" + request.url.query

            password = terminal_api.get("password", "")
            headers = self._build_proxy_headers(password, dict(request.headers))
            body = await request.body()
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.request(request.method, target_url, data=body or None, headers=headers, allow_redirects=False) as resp:
                        raw = await resp.read()
                        content_type = resp.headers.get("Content-Type", "")
                        if "text/html" in content_type:
                            text = raw.decode("utf-8", errors="replace")
                            text = _rewrite_html(text, {
                                '"/ws': f'"/agent/{agent_id}/terminal/ws',
                                "'/ws": f"'/agent/{agent_id}/terminal/ws",
                                '"/api/': f'"/agent/{agent_id}/terminal/api/',
                                "'/api/": f"'/agent/{agent_id}/terminal/api/",
                                '"/static/': f'"/agent/{agent_id}/terminal/static/',
                                "'/static/": f"'/agent/{agent_id}/terminal/static/",
                            })
                            raw = text.encode("utf-8")
                        response_headers = {}
                        for key, value in resp.headers.items():
                            if key.lower() in {"content-length", "transfer-encoding", "content-encoding", "connection", "www-authenticate"}:
                                continue
                            response_headers[key] = value
                        return Response(content=raw, status_code=resp.status, headers=response_headers, media_type=None)
                except Exception as exc:
                    raise HTTPException(status_code=502, detail=f"Failed to proxy Agent Terminal API: {exc}") from exc

        @app.api_route("/task/{task_id}/web-console", methods=_PROXY_METHODS, dependencies=[Depends(_check_password)], include_in_schema=False)
        @app.api_route("/task/{task_id}/web-console/{subpath:path}", methods=_PROXY_METHODS, dependencies=[Depends(_check_password)], include_in_schema=False)
        async def proxy_web_console(task_id: str, request: Request, subpath: str = ""):
            if subpath == "ws":
                raise HTTPException(status_code=400, detail="Use WebSocket endpoint")
            try:
                task = self._get_task(task_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            if not (task.get("web_console") or {}).get("enabled"):
                raise HTTPException(status_code=503, detail="Web console service is not enabled")

            target_url = self._web_console_proxy_url(task, subpath)
            if request.url.query:
                target_url += "?" + request.url.query
            headers = self._build_proxy_headers((task.get("web_console") or {}).get("password", ""), dict(request.headers))
            body = await request.body()
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.request(request.method, target_url, data=body or None, headers=headers, allow_redirects=False) as resp:
                        raw = await resp.read()
                        content_type = resp.headers.get("Content-Type", "")
                        if "text/html" in content_type:
                            text = raw.decode("utf-8", errors="replace")
                            text = _rewrite_html(text, {
                                '"/ws': f'"/task/{task_id}/web-console/ws',
                                "'/ws": f"'/task/{task_id}/web-console/ws",
                                '"/api/': f'"/task/{task_id}/web-console/api/',
                                "'/api/": f"'/task/{task_id}/web-console/api/",
                                '"/static/': f'"/task/{task_id}/web-console/static/',
                                "'/static/": f"'/task/{task_id}/web-console/static/",
                            })
                            raw = text.encode("utf-8")
                        response_headers = {}
                        for key, value in resp.headers.items():
                            if key.lower() in {"content-length", "transfer-encoding", "content-encoding", "connection", "www-authenticate"}:
                                continue
                            response_headers[key] = value
                        return Response(content=raw, status_code=resp.status, headers=response_headers, media_type=None)
                except Exception as exc:
                    raise HTTPException(status_code=502, detail=f"Failed to proxy Web console: {exc}") from exc

        @app.api_route("/agent/{agent_id}/web-console", methods=_PROXY_METHODS, dependencies=[Depends(_check_password)], include_in_schema=False)
        @app.api_route("/agent/{agent_id}/web-console/{subpath:path}", methods=_PROXY_METHODS, dependencies=[Depends(_check_password)], include_in_schema=False)
        async def proxy_agent_web_console(agent_id: str, request: Request, subpath: str = ""):
            if subpath == "ws":
                raise HTTPException(status_code=400, detail="Use WebSocket endpoint")
            try:
                with self._agents_lock:
                    agent = self._agents.get(agent_id)
                    if not agent:
                        raise KeyError(f"Agent '{agent_id}' not found")
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

            status = self._agent_status(agent)
            if status != "online":
                raise HTTPException(status_code=503, detail="Agent is offline")

            web_console = agent.get("web_console", {})
            if not web_console or not web_console.get("enabled", False):
                raise HTTPException(status_code=503, detail="Web console service is not available for this agent")

            target_url = self._agent_web_console_proxy_url(agent, subpath)
            if request.url.query:
                target_url += "?" + request.url.query

            password = web_console.get("password", "")
            headers = self._build_proxy_headers(password, dict(request.headers))
            body = await request.body()
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.request(request.method, target_url, data=body or None, headers=headers, allow_redirects=False) as resp:
                        raw = await resp.read()
                        content_type = resp.headers.get("Content-Type", "")
                        if "text/html" in content_type:
                            text = raw.decode("utf-8", errors="replace")
                            text = _rewrite_html(text, {
                                '"/ws': f'"/agent/{agent_id}/web-console/ws',
                                "'/ws": f"'/agent/{agent_id}/web-console/ws",
                                '"/api/': f'"/agent/{agent_id}/web-console/api/',
                                "'/api/": f"'/agent/{agent_id}/web-console/api/",
                                '"/static/': f'"/agent/{agent_id}/web-console/static/',
                                "'/static/": f"'/agent/{agent_id}/web-console/static/",
                            })
                            raw = text.encode("utf-8")
                        response_headers = {}
                        for key, value in resp.headers.items():
                            if key.lower() in {"content-length", "transfer-encoding", "content-encoding", "connection"}:
                                continue
                            response_headers[key] = value
                        return Response(content=raw, status_code=resp.status, headers=response_headers, media_type=None)
                except Exception as exc:
                    raise HTTPException(status_code=502, detail=f"Failed to proxy Agent Web console: {exc}") from exc

        @app.websocket("/task/{task_id}/terminal/ws")
        async def proxy_terminal_ws(websocket: WebSocket, task_id: str):
            try:
                task = self._get_task(task_id)
            except KeyError:
                await websocket.close(code=4404)
                return
            if task["terminal_api"].get("status") not in {"running", "starting", "unavailable"}:
                await websocket.close(code=4503)
                return

            terminal_api = task.get("terminal_api") or {}
            try:
                target_url = self._terminal_proxy_url(task, "ws").replace("http://", "ws://")
            except Exception:
                await websocket.close(code=4503)
                return
            if websocket.url.query:
                target_url += "?" + urlencode(dict(websocket.query_params))
            upstream_headers = self._build_ws_proxy_headers(terminal_api.get("password", ""), dict(websocket.headers))
            # Set correct Origin header for upstream CORS validation
            from urllib.parse import urlparse
            parsed_url = urlparse(target_url)
            upstream_origin = f"{parsed_url.scheme.replace('ws', 'http')}://{parsed_url.netloc}"
            upstream_headers["Origin"] = upstream_origin
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.ws_connect(target_url, heartbeat=20, headers=upstream_headers, max_msg_size=100*1024*1024) as upstream:
                        # Pass negotiated subprotocol from upstream to client
                        await websocket.accept(subprotocol=upstream.protocol)

                        async def client_to_upstream():
                            try:
                                while True:
                                    msg = await websocket.receive()
                                    if msg["type"] == "websocket.disconnect":
                                        try:
                                            await upstream.close()
                                        except Exception:
                                            pass
                                        return
                                    if msg.get("text") is not None:
                                        await upstream.send_str(msg["text"])
                                    elif msg.get("bytes") is not None:
                                        await upstream.send_bytes(msg["bytes"])
                            except Exception:
                                try:
                                    await upstream.close()
                                except Exception:
                                    pass

                        async def upstream_to_client():
                            try:
                                async for msg in upstream:
                                    if msg.type == aiohttp.WSMsgType.TEXT:
                                        await websocket.send_text(msg.data)
                                    elif msg.type == aiohttp.WSMsgType.BINARY:
                                        await websocket.send_bytes(msg.data)
                                    elif msg.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                                        try:
                                            if websocket.client_state.name != "DISCONNECTED":
                                                await websocket.close(code=msg.data if msg.type == aiohttp.WSMsgType.CLOSE else 1011)
                                        except Exception:
                                            pass
                                        return
                            except Exception:
                                try:
                                    if websocket.client_state.name != "DISCONNECTED":
                                        await websocket.close()
                                except Exception:
                                    pass

                        task1 = asyncio.create_task(client_to_upstream())
                        task2 = asyncio.create_task(upstream_to_client())
                        try:
                            await asyncio.gather(task1, task2)
                        except (WebSocketDisconnect, RuntimeError, ConnectionError):
                            pass
                        finally:
                            task1.cancel()
                            task2.cancel()
                            for t in (task1, task2):
                                try:
                                    await t
                                except asyncio.CancelledError:
                                    pass
                            # Ensure all connections are properly closed
                            try:
                                await upstream.close()
                            except Exception:
                                pass
                            try:
                                if websocket.client_state.name != "DISCONNECTED":
                                    await websocket.close()
                            except Exception:
                                pass
                except WebSocketDisconnect:
                    return

        @app.websocket("/agent/{agent_id}/web-console/ws")
        async def proxy_agent_web_console_ws(websocket: WebSocket, agent_id: str):
            try:
                with self._agents_lock:
                    agent = self._agents.get(agent_id)
                    if not agent:
                        raise KeyError(f"Agent '{agent_id}' not found")
            except KeyError:
                await websocket.close(code=4404)
                return

            status = self._agent_status(agent)
            if status != "online":
                await websocket.close(code=4503)
                return

            web_console = agent.get("web_console") or {}
            if not web_console.get("enabled"):
                await websocket.close(code=4503)
                return

            base_url = web_console.get("base_url_internal", "") or web_console.get("tcp_url", "")
            if not base_url:
                await websocket.close(code=4503)
                return

            if not base_url.startswith("http"):
                base_url = f"http://{base_url}"
            target_url = base_url.replace("http://", "ws://").rstrip("/") + "/ws"
            if websocket.url.query:
                target_url += "?" + urlencode(dict(websocket.query_params))

            upstream_headers = self._build_ws_proxy_headers(web_console.get("password", ""), dict(websocket.headers))
            # Set correct Origin header for upstream CORS validation
            from urllib.parse import urlparse
            parsed_url = urlparse(target_url)
            upstream_origin = f"{parsed_url.scheme.replace('ws', 'http')}://{parsed_url.netloc}"
            upstream_headers["Origin"] = upstream_origin

            async with aiohttp.ClientSession() as session:
                try:
                    async with session.ws_connect(target_url, heartbeat=20, headers=upstream_headers, max_msg_size=100*1024*1024) as upstream:
                        # Pass negotiated subprotocol from upstream to client
                        await websocket.accept(subprotocol=upstream.protocol)

                        async def client_to_upstream():
                            try:
                                while True:
                                    msg = await websocket.receive()
                                    if msg["type"] == "websocket.disconnect":
                                        try:
                                            await upstream.close()
                                        except Exception:
                                            pass
                                        return
                                    if msg.get("text") is not None:
                                        await upstream.send_str(msg["text"])
                                    elif msg.get("bytes") is not None:
                                        await upstream.send_bytes(msg["bytes"])
                            except Exception:
                                try:
                                    await upstream.close()
                                except Exception:
                                    pass

                        async def upstream_to_client():
                            try:
                                async for msg in upstream:
                                    if msg.type == aiohttp.WSMsgType.TEXT:
                                        await websocket.send_text(msg.data)
                                    elif msg.type == aiohttp.WSMsgType.BINARY:
                                        await websocket.send_bytes(msg.data)
                                    elif msg.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                                        try:
                                            if websocket.client_state.name != "DISCONNECTED":
                                                await websocket.close(code=msg.data if msg.type == aiohttp.WSMsgType.CLOSE else 1011)
                                        except Exception:
                                            pass
                                        return
                            except Exception:
                                try:
                                    if websocket.client_state.name != "DISCONNECTED":
                                        await websocket.close()
                                except Exception:
                                    pass

                        task1 = asyncio.create_task(client_to_upstream())
                        task2 = asyncio.create_task(upstream_to_client())
                        try:
                            await asyncio.gather(task1, task2)
                        except (WebSocketDisconnect, RuntimeError, ConnectionError):
                            pass
                        finally:
                            task1.cancel()
                            task2.cancel()
                            for t in (task1, task2):
                                try:
                                    await t
                                except asyncio.CancelledError:
                                    pass
                            # Ensure all connections are properly closed
                            try:
                                await upstream.close()
                            except Exception:
                                pass
                            try:
                                if websocket.client_state.name != "DISCONNECTED":
                                    await websocket.close()
                            except Exception:
                                pass
                except WebSocketDisconnect:
                    return

        @app.websocket("/agent/{agent_id}/terminal/ws")
        async def proxy_agent_terminal_ws(websocket: WebSocket, agent_id: str):
            try:
                with self._agents_lock:
                    agent = self._agents.get(agent_id)
                    if not agent:
                        raise KeyError(f"Agent '{agent_id}' not found")
            except KeyError:
                await websocket.close(code=4404)
                return

            status = self._agent_status(agent)
            if status != "online":
                await websocket.close(code=4503)
                return

            terminal_api = agent.get("terminal_api") or {}
            base_url = terminal_api.get("base_url_internal", "") or terminal_api.get("tcp_url", "")
            if not base_url:
                await websocket.close(code=4503)
                return

            if not base_url.startswith("http"):
                base_url = f"http://{base_url}"
            target_url = base_url.replace("http://", "ws://").rstrip("/") + "/ws"
            if websocket.url.query:
                target_url += "?" + urlencode(dict(websocket.query_params))

            upstream_headers = self._build_ws_proxy_headers(terminal_api.get("password", ""), dict(websocket.headers))
            # Set correct Origin header for upstream CORS validation
            from urllib.parse import urlparse
            parsed_url = urlparse(target_url)
            upstream_origin = f"{parsed_url.scheme.replace('ws', 'http')}://{parsed_url.netloc}"
            upstream_headers["Origin"] = upstream_origin
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.ws_connect(target_url, heartbeat=20, headers=upstream_headers, max_msg_size=100*1024*1024) as upstream:
                        # Pass negotiated subprotocol from upstream to client
                        await websocket.accept(subprotocol=upstream.protocol)

                        async def client_to_upstream():
                            try:
                                while True:
                                    msg = await websocket.receive()
                                    if msg["type"] == "websocket.disconnect":
                                        try:
                                            await upstream.close()
                                        except Exception:
                                            pass
                                        return
                                    if msg.get("text") is not None:
                                        await upstream.send_str(msg["text"])
                                    elif msg.get("bytes") is not None:
                                        await upstream.send_bytes(msg["bytes"])
                            except Exception:
                                try:
                                    await upstream.close()
                                except Exception:
                                    pass

                        async def upstream_to_client():
                            try:
                                async for msg in upstream:
                                    if msg.type == aiohttp.WSMsgType.TEXT:
                                        await websocket.send_text(msg.data)
                                    elif msg.type == aiohttp.WSMsgType.BINARY:
                                        await websocket.send_bytes(msg.data)
                                    elif msg.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                                        try:
                                            if websocket.client_state.name != "DISCONNECTED":
                                                await websocket.close(code=msg.data if msg.type == aiohttp.WSMsgType.CLOSE else 1011)
                                        except Exception:
                                            pass
                                        return
                            except Exception:
                                try:
                                    if websocket.client_state.name != "DISCONNECTED":
                                        await websocket.close()
                                except Exception:
                                    pass

                        task1 = asyncio.create_task(client_to_upstream())
                        task2 = asyncio.create_task(upstream_to_client())
                        try:
                            await asyncio.gather(task1, task2)
                        except (WebSocketDisconnect, RuntimeError, ConnectionError):
                            pass
                        finally:
                            task1.cancel()
                            task2.cancel()
                            for t in (task1, task2):
                                try:
                                    await t
                                except asyncio.CancelledError:
                                    pass
                            # Ensure all connections are properly closed
                            try:
                                await upstream.close()
                            except Exception:
                                pass
                            try:
                                if websocket.client_state.name != "DISCONNECTED":
                                    await websocket.close()
                            except Exception:
                                pass
                except WebSocketDisconnect:
                    return
                except Exception:
                    try:
                        if websocket.client_state.name != "DISCONNECTED":
                            await websocket.close(code=1011)
                    except Exception:
                        pass

        @app.websocket("/task/{task_id}/web-console/ws")
        async def proxy_web_console_ws(websocket: WebSocket, task_id: str):
            try:
                task = self._get_task(task_id)
            except KeyError:
                await websocket.close(code=4404)
                return
            web_console = task.get("web_console") or {}
            if not web_console.get("enabled"):
                await websocket.close(code=4503)
                return

            try:
                target_url = self._web_console_proxy_url(task, "ws").replace("http://", "ws://")
            except Exception:
                await websocket.close(code=4503)
                return
            if websocket.url.query:
                target_url += "?" + urlencode(dict(websocket.query_params))
            upstream_headers = self._build_ws_proxy_headers(web_console.get("password", ""), dict(websocket.headers))
            # Set correct Origin header for upstream CORS validation
            from urllib.parse import urlparse
            parsed_url = urlparse(target_url)
            upstream_origin = f"{parsed_url.scheme.replace('ws', 'http')}://{parsed_url.netloc}"
            upstream_headers["Origin"] = upstream_origin

            async with aiohttp.ClientSession() as session:
                try:
                    async with session.ws_connect(target_url, heartbeat=20, headers=upstream_headers, max_msg_size=100*1024*1024) as upstream:
                        # Pass negotiated subprotocol from upstream to client
                        await websocket.accept(subprotocol=upstream.protocol)

                        async def client_to_upstream():
                            try:
                                while True:
                                    msg = await websocket.receive()
                                    if msg["type"] == "websocket.disconnect":
                                        try:
                                            await upstream.close()
                                        except Exception:
                                            pass
                                        return
                                    if msg.get("text") is not None:
                                        await upstream.send_str(msg["text"])
                                    elif msg.get("bytes") is not None:
                                        await upstream.send_bytes(msg["bytes"])
                            except Exception:
                                try:
                                    await upstream.close()
                                except Exception:
                                    pass

                        async def upstream_to_client():
                            try:
                                async for msg in upstream:
                                    if msg.type == aiohttp.WSMsgType.TEXT:
                                        await websocket.send_text(msg.data)
                                    elif msg.type == aiohttp.WSMsgType.BINARY:
                                        await websocket.send_bytes(msg.data)
                                    elif msg.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                                        try:
                                            if websocket.client_state.name != "DISCONNECTED":
                                                await websocket.close(code=msg.data if msg.type == aiohttp.WSMsgType.CLOSE else 1011)
                                        except Exception:
                                            pass
                                        return
                            except Exception:
                                try:
                                    if websocket.client_state.name != "DISCONNECTED":
                                        await websocket.close()
                                except Exception:
                                    pass

                        task1 = asyncio.create_task(client_to_upstream())
                        task2 = asyncio.create_task(upstream_to_client())
                        try:
                            await asyncio.gather(task1, task2)
                        except (WebSocketDisconnect, RuntimeError, ConnectionError):
                            pass
                        finally:
                            task1.cancel()
                            task2.cancel()
                            for t in (task1, task2):
                                try:
                                    await t
                                except asyncio.CancelledError:
                                    pass
                            # Ensure all connections are properly closed
                            try:
                                await upstream.close()
                            except Exception:
                                pass
                            try:
                                if websocket.client_state.name != "DISCONNECTED":
                                    await websocket.close()
                            except Exception:
                                pass
                except WebSocketDisconnect:
                    return
                except Exception:
                    try:
                        if websocket.client_state.name != "DISCONNECTED":
                            await websocket.close(code=1011)
                    except Exception:
                        pass

        from ucagent.server.api_cmd.master_proxy import register_master_xpra_routes
        register_master_xpra_routes(app, self, xpra_browser_access)
        return app
