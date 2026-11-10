# -*- coding: utf-8 -*-
"""Authenticated HTTP controls, operation results and workspace inspection."""

import atexit
import os
import re
import threading
from ucagent.runtime.services import start_http_listeners, stop_http_listeners
import warnings
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Output is retained by the runtime buffer shared with other frontends.
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _strip_ansi(text: str) -> str:
    """Remove terminal styling from a text response."""
    return _ANSI_RE.sub("", text)


class ControlApiServer:
    """
    Authenticated FastAPI control surface for one runtime instance.

    Endpoints
    ---------
    GET  /                             - HTML dashboard (agent status + file manager)
    GET  /api/status                   - Structured agent status (?sub_workspace=...)
    GET  /api/server_info              - Running servers info (cmd_api, master_api, mcp)
    GET  /api/runtime/status           - Instance, execution and operation state
    GET  /api/tasks                    - Task list (?sub_worspace=...)
    GET  /api/task/{index}             - Task detail (?sub_worspace=...)
    GET  /api/mission                  - Mission overview (raw ANSI; ?strip_ansi=true to strip&sub_worspace=...)
    GET  /api/cmds                     - All available commands  (?prefix=)
    GET  /api/help                     - Command help  (?cmd=<name>)
    GET  /api/tools                    - Tool list with call counts
    GET  /api/changed_files            - Recently changed output files  (?count=10)
    GET  /api/sub_workspaces           - List UCAgent sub-workspace summaries (?page=1&page_size=20)
    GET  /api/sub_workspace            - Get one sub-workspace summary (?path=... or ?task_id=...)
    DELETE /api/sub_workspace          - Delete a sub-workspace and optional wrapper dirs (?path=...)
    GET  /api/stage/{index}/task       - Get task detail from a stage
    GET  /api/stage/{index}/file       - Get file content from a stage  (?file_path=...)
    GET  /api/stage/{index}/file_current - Get current stage file content (?file_path=...)
    GET  /api/workspace_git_status     - Workspace Git modified/untracked files (?sub_worspace=...)
    GET  /api/workspace_git_file       - Workspace Git file content and diff (?file_path=...)
    GET  /api/console                  - Captured stdout/stderr ring buffer (?lines=200&strip_ansi=false)
    DELETE /api/console                - Clear captured stdout buffer
    POST /api/cmd                      - Enqueue a single PDB command  {"cmd": "..."}
    POST /api/cmds/batch               - Submit ordered registered commands  {"cmds": [...]}
    POST /api/runtime/pause            - Pause at the next safe boundary
    GET  /api/files                    - List workspace directory  (?path=subdir&sub_worspace=...)
    GET  /api/file                     - Read text file content  (?path=...&sub_worspace=...)
    POST /api/file/new                 - Create new text file  body: {"path":"...","content":"..."}
    POST /api/file/rename              - Rename file or directory  body: {"path":"...","new_name":"..."}
    POST /api/file/edit                - Save/overwrite text file  body: {"path":"...","content":"..."}
    DELETE /api/file                   - Delete file or directory within the workspace  (?path=...)
    GET  /api/file/download            - Download file or directory as attachment  (?path=...)
    GET  /api/workspace/download       - Download whole workspace as {DUT}.tar.gz
    GET  /wave/                        - Dispatch a metadata-based waveform viewer
    POST /api/file/upload              - Upload file (multipart)  (?path=target_dir)
    GET  /workspace/{path}             - Serve workspace files as static assets (redirects to dashboard for root)
    GET  /static/{path}                - Serve bundled static assets
    GET  /surfer/ and /surfer/{path}   - Surfer waveform viewer (static)
    GET  /docs, /redoc                 - OpenAPI docs (Swagger UI, ReDoc)
    """

    def __init__(
        self,
        controller,
        *,
        registry=None,
        operations=None,
        services=None,
        host_control=None,
        host: str = "127.0.0.1",
        port: int = 8765,
        sock: Optional[str] = None,
        tcp: bool = True,
        password: str = "",
    ) -> None:
        """Bind explicit controls and owned operations while preserving HTTP authentication."""
        from ucagent.runtime.control.commands import create_registry, SessionCommands
        from ucagent.runtime.operations import OperationExecutor

        self.controller = controller
        self.agent = controller.agent
        self.operations = operations or controller.operations or OperationExecutor(controller)
        self.services = services or getattr(self.agent, "services", None)
        self.host_control = host_control
        self.registry = registry or create_registry(controller, executors={
            "operations": self.operations, "stages": self.operations.stages,
            "services": self.services, "host": host_control, "session": SessionCommands()})
        self._sessions = {}

        # Resolve sock:
        #   None  → auto-generate a default path that embeds the port
        #   ""    → explicitly disabled
        #   other → use as-is (user-supplied path)
        if sock is None:
            sock = f"/tmp/ucagent_cmd_{port}.sock" if port else f"/tmp/ucagent_cmd_{os.getpid()}_{id(self):x}.sock"
        elif sock == "":
            sock = None

        if not tcp and not sock:
            raise ValueError("At least one of 'tcp' or 'sock' must be enabled.")

        self.host = host
        self.port = port
        self.sock = sock
        self.tcp = tcp
        self.password = password
        self._xpra = self._new_xpra_manager()
        self._lifecycle_lock = threading.RLock()
        self._listener_sockets = []
        self._listener_errors = []
        self._owned_sock_path = None
        self._stop_requested = False
        self._running = False
        self.started_at: Optional[float] = None
        # TCP listener state
        self._tcp_server = None
        self._tcp_thread: Optional[threading.Thread] = None
        # Unix socket listener state
        self._sock_server = None
        self._sock_thread: Optional[threading.Thread] = None
        from ucagent.runtime.output import OutputBuffer
        self._console_capture = host_control.output if host_control else OutputBuffer()
        self._owns_output = host_control is None
        self._app = self._build_app()
        self._console_capture.install()
        atexit.register(self.close_sessions)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _new_xpra_manager(self):
        """Create an isolated manager from the agent's resolved server settings."""
        from ucagent.interfaces.server.api_cmd.xpra import XpraSessionManager
        return XpraSessionManager(self.agent.workspace, getattr(self.agent, "cfg", None),
                                  secrets=(self.password,))

    def close_sessions(self):
        """Clean up owned GUI applications without closing terminal services."""
        self._xpra.close()

    def _build_app(self):  # noqa: C901 – intentionally long; each section is self-contained
        import mimetypes
        import os
        import pathlib

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning, module="fastapi")
            from fastapi import FastAPI, HTTPException, Query, Request
            from fastapi.responses import FileResponse, HTMLResponse
        from pydantic import BaseModel, Field
        from uuid import uuid4
        from ucagent.util.functions import list_files_by_mtime

        app = FastAPI(
            title="UCAgent Control API",
            description=(
                "REST API for the UCAgent runtime. "
                "Use GET /api/status, /api/mission, /api/tasks, /api/console for monitoring. "
                "GET /api/cmds lists available commands."
            ),
            version="1.0.0",
        )

        # ── auth middleware (HTTP Basic, skips /docs and /redoc) ──────────
        from ucagent.interfaces.server.api_cmd.transport import basic_authorized
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request as _Request
        from fastapi.responses import JSONResponse as _JSONResponse

        _password = self.password
        _EXCLUDED_PATHS = {"/docs", "/redoc", "/openapi.json"}

        class _AuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: _Request, call_next):
                if request.url.path in _EXCLUDED_PATHS:
                    return await call_next(request)
                auth = request.headers.get("Authorization", "")
                if basic_authorized(_password, auth):
                    return await call_next(request)
                return _JSONResponse(
                    status_code=401,
                    content={"detail": "Authentication required."},
                    headers={"WWW-Authenticate": 'Basic realm="UCAgent CMD API"'},
                )

        app.add_middleware(_AuthMiddleware)

        from ucagent.runtime.control.controller import ControlError

        @app.exception_handler(ControlError)
        async def control_error(request, error):
            """Translate typed business errors without reporting them as successful commands."""
            code = 409 if error.code in {"busy", "stale_revision", "stale_stage", "closing"} else 404 if error.code in {"unknown_command", "unknown_operation", "not_found"} else 400
            return _JSONResponse(status_code=code, content={"status": "error", "error": error.as_dict()})


        from ucagent.interfaces.server.api_cmd.xpra_routes import register_xpra_routes
        register_xpra_routes(app, self)

        control = self.controller
        access = control.workspace_access
        queries = control.workspace_queries

        from ucagent.core.workspace.files import WorkspaceAccessError

        @app.exception_handler(WorkspaceAccessError)
        async def workspace_error(request, error):
            """Translate domain file errors at the HTTP boundary."""
            status = {"invalid_path": 403, "not_found": 404, "conflict": 409}.get(error.code, 400)
            return _JSONResponse(status_code=status, content={"detail": str(error)})

        @app.exception_handler(PermissionError)
        async def permission_error(request, error):
            """Report OS permission failures without attempting chmod escalation."""
            return _JSONResponse(status_code=403, content={"detail": str(error)})


        # ── request bodies ─────────────────────────────────────────────
        class CmdBody(BaseModel):
            cmd: str
            session_id: str = Field(default_factory=lambda: uuid4().hex)
            cwd: Optional[str] = None
            confirmed: bool = False

        class CmdsBody(CmdBody):
            cmd: str = ""
            cmds: List[str]

        class StageFlagsBody(BaseModel):
            indices: List[int]
            expected_revision: int
            hmcheck_needed: Optional[bool] = None
            skip: Optional[bool] = None
            llm_fail_suggestion: Optional[bool] = None
            llm_pass_suggestion: Optional[bool] = None
        class StageReviewBody(BaseModel):
            """Bind approval to one observed stage revision."""
            index: int
            expected_revision: int
            approved: bool
            message: str = ""
            resume: bool = False
            session_id: str = Field(default_factory=lambda: uuid4().hex)


        def _query_sub_workspace(request: Optional[Request]) -> str:
            """Read the selected workspace from the existing HTTP query contract."""
            if request is None:
                return ""
            # Keep the documented typo for compatibility and accept the
            # corrected spelling too.
            return (
                request.query_params.get("sub_worspace")
                or request.query_params.get("sub_workspace")
                or ""
            ).strip()


        def _request_workspace(request: Optional[Request]):
            """Resolve the requested workspace through the runtime access owner."""
            return access.select(_query_sub_workspace(request))

        from ucagent.interfaces.server.api_cmd.file_routes import register_file_routes
        from ucagent.interfaces.server.api_cmd.stage_routes import register_stage_routes
        register_file_routes(app, access, queries, _request_workspace,
                             dut_name=getattr(self.agent, "dut_name", "") or "workspace")
        register_stage_routes(app, control, queries, _request_workspace, _strip_ansi)


        def command_session(request, session_id, cwd=None, confirmed=False):
            """Keep directories scoped to a client and selected workspace, with traversal checks."""
            from ucagent.runtime.control.commands import CommandSession
            from pathlib import Path

            workspace, relative, is_sub = _request_workspace(request)
            key = (session_id, workspace)
            with self._lifecycle_lock:
                session = self._sessions.setdefault(key, CommandSession(Path(workspace), repeat=False))
                if cwd is not None:
                    candidate = (Path(workspace) / cwd).resolve()
                    if not candidate.is_relative_to(Path(workspace).resolve()) or not candidate.is_dir():
                        raise HTTPException(403, "Command directory must be inside the selected workspace")
                    session.cwd = candidate
                session.confirmed = confirmed
            return session, is_sub

        def submit_command(line, session, is_sub):
            """Record synchronous results and return existing IDs for real background operations."""
            from ucagent.runtime.control.controller import ControlError

            spec = self.registry.resolve(line.split(maxsplit=1)[0])
            if spec.owner == "view":
                raise ControlError("unavailable", "Display commands require a local view.")
            if is_sub and spec.name not in {"ls", "cd", "chcwd", "pwd", "help"}:
                raise HTTPException(403, "This command cannot control the parent from a sub-workspace")
            result = self.registry.submit(line, session)
            data = result.data
            if isinstance(data, dict) and "id" in data and "state" in data:
                return data
            return self.operations.record_result(result.command, data)


        # ── HTML dashboard templates ─────────────────────────────────────
        _TEMPLATE_DIR = pathlib.Path(__file__).resolve().parents[1] / "templates"
        _HTML = (_TEMPLATE_DIR / "agent.html").read_text(encoding="utf-8")
        _COMPLETE_HTML = (_TEMPLATE_DIR / "complete.html").read_text(encoding="utf-8")
        # ── index: HTML dashboard ───────────────────────────────────────
        @app.get("/", summary="HTML dashboard", response_class=HTMLResponse)
        def index():
            return HTMLResponse(content=_HTML)

        @app.get("/complete", summary="Sub-workspace completion dashboard", response_class=HTMLResponse)
        @app.get("/complete/", include_in_schema=False, response_class=HTMLResponse)
        def complete_page():
            return HTMLResponse(content=_COMPLETE_HTML)

        @app.get("/api/ui-meta", summary="UI metadata")
        def get_ui_meta():
            from ucagent.version import __version__
            import time as _time

            uptime_s = 0.0
            if self.started_at:
                uptime_s = max(0.0, _time.time() - self.started_at)
            return {
                "status": "ok",
                "data": {
                    "product": "UCAgent",
                    "version": __version__,
                    "started_at": self.started_at,
                    "uptime_s": round(uptime_s, 1),
                },
            }


        # ── GET /api/server_info ───────────────────────────────────────────
        @app.get("/api/server_info", summary="Running servers info (cmd_api, master_api, mcp)")
        def get_server_info():
            try:
                return {"status": "ok", "data": self.services.server_info()}
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        @app.get("/api/runtime/status", summary="Runtime and operation state")
        def runtime_status():
            """Expose application state separately from actual operation results."""
            state = self.host_control.snapshot() if self.host_control else {"instance": "ready", "execution": "idle"}
            return {"status": "ok", "data": {**state, "operations": self.operations.list()}}

        @app.get("/api/operations/{operation_id}")
        def operation_status(operation_id: str):
            """Read a detached operation without joining its worker."""
            return {"status": "ok", "data": control.operation_status(operation_id)}

        @app.post("/api/operations/{operation_id}/cancel")
        def cancel_operation(operation_id: str, request: Request):
            """Cancel the identified operation; sub-workspace views cannot control the parent."""
            if _request_workspace(request)[2]:
                raise HTTPException(403, "Parent operations cannot be cancelled from a sub-workspace")
            return {"status": "ok", "data": control.cancel_operation(operation_id)}

        @app.post("/api/runtime/pause")
        def pause_runtime(request: Request):
            """Request a safe pause instead of delivering process signals."""
            if _request_workspace(request)[2]:
                raise HTTPException(403, "Parent runtime cannot be paused from a sub-workspace")
            return {"status": "ok", "data": self.host_control.pause()}

        @app.get("/api/stages/state")
        def stage_state():
            """Expose the revision required by review and flag updates."""
            return {"status": "ok", "data": control.stage_state()}


        # ── GET /api/cmds ──────────────────────────────────────────────
        @app.get("/api/cmds", summary="List available commands")
        def get_cmds(
            prefix: str = Query(default="", description="Filter commands by prefix")
        ):
            try:
                return {"status": "ok", "data": self.registry.complete(prefix)}
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        @app.get("/api/help", summary="Registered command help")
        def get_help(cmd: str = ""):
            """Describe only declared commands; debugger methods are never discovered."""
            return {"status": "ok", "data": self.registry.describe(cmd or None)}

        # ── GET /api/tools ─────────────────────────────────────────────
        @app.get("/api/tools", summary="Tool list with call counts")
        def get_tools(request: Request):
            try:
                _, _, is_sub_workspace = _request_workspace(request)
                if is_sub_workspace:
                    return {"status": "ok", "data": []}
                data = control.tool_list()
                return {"status": "ok", "data": data}
            except (HTTPException, WorkspaceAccessError):
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /api/changed_files ─────────────────────────────────────
        @app.get("/api/changed_files", summary="Recently changed output files")
        def get_changed_files(
            request: Request,
            count: int = Query(default=10, description="Maximum number of files to return")
        ):
            try:
                workspace_root, _, is_sub_workspace = _request_workspace(request)
                if is_sub_workspace:
                    files = list_files_by_mtime(workspace_root, count)
                    data = [
                        {"delta_seconds": d, "timestamp": t, "file": f}
                        for d, t, f in files
                    ]
                    return {"status": "ok", "data": data, "output_dir": ""}
                files = control.changed_files(count)
                data = [
                    {"delta_seconds": row["age_seconds"], "timestamp": row["mtime"], "file": row["path"]}
                    for row in files
                ]
                _workspace = os.path.abspath(self.agent.workspace)
                _output_dir = os.path.abspath(self.agent.output_dir)
                output_dir_rel = os.path.relpath(_output_dir, _workspace)
                return {"status": "ok", "data": data, "output_dir": output_dir_rel}
            except (HTTPException, WorkspaceAccessError):
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))


        # ── GET /api/console ───────────────────────────────────────────
        _capture = self._console_capture  # capture ref for closures

        @app.get("/api/console", summary="Captured stdout ring buffer")
        def get_console(
            lines: int = Query(default=200, description="Max lines to return (0 = all)"),
            strip_ansi: bool = Query(default=False, description="Strip ANSI colour codes"),
        ):
            try:
                data = _capture.get_lines(lines)
                if strip_ansi:
                    data = [_strip_ansi(l) for l in data]
                return {"status": "ok", "data": data, "count": len(data)}
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        @app.delete("/api/console", summary="Clear captured stdout buffer")
        def clear_console():
            try:
                _capture.clear()
                return {"status": "ok", "message": "Console buffer cleared"}
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        @app.post("/api/cmd", summary="Submit a registered command")
        def post_cmd(body: CmdBody, request: Request):
            """Return an operation ID that identifies success, failure or pending work."""
            if not body.cmd.strip():
                raise HTTPException(400, "Command cannot be empty")
            session, is_sub = command_session(request, body.session_id, body.cwd, body.confirmed)
            operation = submit_command(body.cmd.strip(), session, is_sub)
            _capture.inject(f"ucagent> {body.cmd}")
            return {"status": "accepted", "operation_id": operation["id"], "session_id": body.session_id, "data": operation}

        @app.post("/api/cmds/batch", summary="Submit ordered commands")
        def post_cmds_batch(body: CmdsBody, request: Request):
            """Execute each command after its predecessor finishes and retain per-command errors."""
            session, is_sub = command_session(request, body.session_id, body.cwd, body.confirmed)
            commands = [line.strip() for line in body.cmds if line.strip()]
            if not commands:
                raise HTTPException(400, "Command list cannot be empty")

            def batch(context):
                """Wait for child results without claiming the model reservation itself."""
                from ucagent.runtime.control.controller import ControlError
                from ucagent.runtime.operations import OperationFailure
                results = []
                for line in commands:
                    context.checkpoint()
                    try:
                        child = submit_command(line, session, is_sub)
                        child = self.operations.wait_tree(context, child["id"])
                        results.append({"cmd": line, "operation_id": child["id"], "state": child["state"], "error": child["error"]})
                    except (ControlError, HTTPException) as error:
                        detail = error.as_dict() if isinstance(error, ControlError) else {"code": "forbidden", "message": str(error.detail), "details": {}}
                        child = self.operations.record_result(line, None, error=detail)
                        results.append({"cmd": line, "operation_id": child["id"], "state": "failed", "error": detail})
                if any(row["state"] != "succeeded" for row in results):
                    raise OperationFailure("batch_failed", "One or more commands failed or were cancelled.", results)
                return results

            operation = self.operations.submit("batch", batch)
            return {"status": "accepted", "operation_id": operation["id"], "session_id": body.session_id, "data": operation}

        @app.post("/api/stages/review", summary="Review the observed current stage")
        def review_stage(body: StageReviewBody, request: Request):
            """Persist revision-checked human approval before optional coordinated resume."""
            session, is_sub = command_session(request, body.session_id)
            if is_sub:
                raise HTTPException(403, "Parent stage review is unavailable from a sub-workspace")
            return {"status": "ok", "data": control.review_stage(
                body.index, body.expected_revision, body.approved, body.message,
                resume=body.resume, session=session)}

        @app.post("/api/stages/update", summary="Update stage flags")
        def post_stage_update(body: StageFlagsBody, request: Request):
            try:
                _, _, is_sub_workspace = _request_workspace(request)
                if is_sub_workspace:
                    raise HTTPException(status_code=400, detail="Stage flags cannot be modified from sub-workspace view")
                updated = control.update_stage_flags(
                    expected_revision=body.expected_revision,
                    indices=body.indices,
                    **body.model_dump(exclude_unset=True, exclude={"indices", "expected_revision"}),
                )
                return {"status": "ok", "data": updated}
            except (HTTPException, WorkspaceAccessError):
                raise
            except ControlError:
                raise
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))


        from ucagent.interfaces.server.api_cmd.waveform_routes import register_waveform_routes
        register_waveform_routes(app, self, _request_workspace)


        # ── GET /static/{path} — bundled static assets ─────────────────
        _STATIC_DIR = pathlib.Path(__file__).resolve().parents[1] / "static"

        @app.get("/static/{path:path}", summary="Serve bundled static assets", include_in_schema=False)
        def serve_static(path: str):
            abs_path = (_STATIC_DIR / path).resolve()
            if not str(abs_path).startswith(str(_STATIC_DIR)):
                raise HTTPException(status_code=403, detail="Forbidden")
            if not abs_path.is_file():
                raise HTTPException(status_code=404, detail=f"Static asset '{path}' not found")
            media_type, _ = mimetypes.guess_type(str(abs_path))
            return FileResponse(path=str(abs_path), media_type=media_type or "application/octet-stream")

        # ── GET /surfer — waveform viewer (redirects to /surfer/) ─────
        _SURFER_DIR = _STATIC_DIR / "surfer"
        _SURFER_ISOLATION_HEADERS = {
            "Cross-Origin-Embedder-Policy": "require-corp",
            "Cross-Origin-Opener-Policy": "same-origin",
        }
        _SURFER_BOOTSTRAP_ASSETS = {
            "deep-link.js",
            "fst-converter.wasm",
            "fst-fallback-worker.js",
            "fst-fallback.js",
            "sw.js",
            "ucagent-wave-ready.sucl",
        }

        def _surfer_file_response(
            path: pathlib.Path,
            media_type: str,
            *,
            prevent_stale_cache: bool = False,
        ):
            headers = dict(_SURFER_ISOLATION_HEADERS)
            if prevent_stale_cache:
                headers["Cache-Control"] = "no-store"
            return FileResponse(
                path=str(path),
                media_type=media_type,
                headers=headers,
            )

        @app.get("/surfer", include_in_schema=False)
        def serve_surfer_redirect():
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url="/surfer/")

        @app.api_route(
            "/surfer/",
            methods=["GET", "HEAD"],
            include_in_schema=False,
        )
        def serve_surfer_root():
            abs_path = _SURFER_DIR / "index.html"
            if not abs_path.is_file():
                raise HTTPException(status_code=404, detail="Surfer waveform viewer not found")
            return _surfer_file_response(
                abs_path,
                "text/html",
                prevent_stale_cache=True,
            )

        @app.api_route(
            "/surfer/{path:path}",
            methods=["GET", "HEAD"],
            include_in_schema=False,
        )
        def serve_surfer_asset(path: str):
            abs_path = (_SURFER_DIR / path).resolve()
            if not str(abs_path).startswith(str(_SURFER_DIR)):
                raise HTTPException(status_code=403, detail="Forbidden")
            if not abs_path.is_file():
                raise HTTPException(status_code=404, detail=f"Surfer asset '{path}' not found")
            media_type, _ = mimetypes.guess_type(str(abs_path))
            return _surfer_file_response(
                abs_path,
                media_type or "application/octet-stream",
                prevent_stale_cache=path in _SURFER_BOOTSTRAP_ASSETS,
            )

        return app

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, timeout=10) -> Tuple[bool, str]:
        """Use the common readiness lifecycle while retaining current command routes."""
        if self._xpra._closed:
            self._xpra = self._new_xpra_manager()
        atexit.unregister(self.close_sessions)
        atexit.register(self.close_sessions)
        return start_http_listeners(self, timeout=timeout, name="command", lifespan="off")

    def stop(self, timeout=5) -> Tuple[bool, str]:
        """Restore captures only after all native request handlers have stopped."""
        ok, message = stop_http_listeners(self, timeout=timeout)
        if not ok:
            return ok, message
        self.close_sessions()
        atexit.unregister(self.close_sessions)
        if self._owns_output:
            self._console_capture.close()

        return True, "CMD API server stopped"

    @property
    def is_running(self) -> bool:
        """Keep startup and draining threads visible to the service owner."""
        return any(thread is not None and thread.is_alive()
                   for thread in (self._tcp_thread, self._sock_thread))

    @property
    def is_ready(self) -> bool:
        """Report readiness for every enabled listener, independently of route migration."""
        return self._running and not self._stop_requested and all(
            server is not None and server.started and thread is not None and thread.is_alive()
            for enabled, server, thread in ((self.tcp, self._tcp_server, self._tcp_thread),
                                            (bool(self.sock), self._sock_server, self._sock_thread)) if enabled)

    def url(self) -> str:
        """Return a human-readable address string for all active listeners."""
        parts: List[str] = []
        if self.tcp:
            parts.append(f"http://{self.host}:{self.port}")
        if self.sock:
            parts.append(f"unix://{self.sock}")
        return " | ".join(parts) if parts else "(none)"
