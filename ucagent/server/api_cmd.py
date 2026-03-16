# -*- coding: utf-8 -*-
"""
CMD API server for VerifyPDB — FastAPI implementation.

Runs a FastAPI/uvicorn HTTP server in a background thread, exposing the
PDB instance's api_* methods and command queue via REST endpoints so
external tools can inspect/control the agent without touching the console.
"""

import collections
import io
import re
import sys
import threading
import warnings
from typing import TYPE_CHECKING, List, Optional, Tuple

if TYPE_CHECKING:
    from ucagent.verify_pdb import VerifyPDB


# ---------------------------------------------------------------------------
# Console capture – tees sys.stdout into a fixed-size ring buffer so the
# REST API can surface recent output without re-running commands.
# ---------------------------------------------------------------------------

class _ConsoleCapture:
    """Thread-safe wrapper that mirrors writes to both the original stream and
    an in-memory ring buffer of *complete* lines.

    Install via ``sys.stdout = _ConsoleCapture(sys.stdout)``.
    """

    def __init__(self, original, maxlines: int = 2000) -> None:
        self._original = original
        self._buf: collections.deque = collections.deque(maxlen=maxlines)
        self._lock = threading.Lock()
        self._pending = ""          # accumulates bytes until a newline arrives

    # ---- stream interface -----------------------------------------------

    def write(self, s) -> int:
        if isinstance(s, (bytes, bytearray)):
            s = s.decode(getattr(self._original, "encoding", "utf-8") or "utf-8",
                          errors="replace")
        elif not isinstance(s, str):
            s = str(s)
        self._original.write(s)
        # Split on newlines; every complete segment goes into the ring buffer
        with self._lock:
            text = self._pending + s
            lines = text.split("\n")
            for line in lines[:-1]:   # all complete lines
                self._buf.append(line)
            self._pending = lines[-1]  # remainder (possibly empty)
        return len(s)

    def flush(self):
        self._original.flush()

    def isatty(self) -> bool:
        return getattr(self._original, "isatty", lambda: False)()

    def fileno(self) -> int:
        return self._original.fileno()

    @property
    def encoding(self):
        return getattr(self._original, "encoding", "utf-8")

    @property
    def errors(self):
        return getattr(self._original, "errors", "replace")

    def __getattr__(self, name):
        return getattr(self._original, name)

    # ---- buffer helpers -------------------------------------------------

    def get_lines(self, n: int = 200) -> list:
        """Return the most recent *n* lines (including any pending partial line)."""
        with self._lock:
            lines = list(self._buf)
            if self._pending:
                lines.append(self._pending)
        return lines[-n:] if n > 0 else lines

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()
            self._pending = ""

    def inject(self, line: str) -> None:
        """Add a line directly to the ring buffer without writing to the
        underlying stream.  Used to echo API-submitted commands so the
        web console shows prompt + command like the terminal does."""
        with self._lock:
            self._buf.append(line)

_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class PdbCmdApiServer:
    """
    FastAPI-based CMD API wrapper around a :class:`VerifyPDB` instance.

    Endpoints
    ---------
    GET  /                             - HTML dashboard (agent status + file manager)
    GET  /api/status                   - Agent status string
    GET  /api/server_info              - Running servers info (cmd_api, master_api, mcp)
    GET  /api/pdb_status               - PDB runtime status (tui, pending cmds, break state)
    GET  /api/tasks                    - Task list
    GET  /api/task/{index}             - Task detail
    GET  /api/mission                  - Mission overview (raw ANSI; ?strip_ansi=true to strip)
    GET  /api/cmds                     - All available PDB commands  (?prefix=)
    GET  /api/help                     - Command help  (?cmd=<name>)
    GET  /api/tools                    - Tool list with call counts
    GET  /api/changed_files            - Recently changed output files  (?count=10)
    GET  /api/console                  - Captured stdout/stderr ring buffer (?lines=200&strip_ansi=false)
    DELETE /api/console                - Clear captured stdout buffer
    POST /api/cmd                      - Enqueue a single PDB command  {"cmd": "..."}
    POST /api/cmds/batch               - Enqueue multiple PDB commands  {"cmds": [...]}
    POST /api/interrupt                - Send Ctrl-C interrupt to PDB
    GET  /api/files                    - List workspace directory  (?path=subdir)
    GET  /api/file                     - Read text file content  (?path=...)
    POST /api/file/new                 - Create new text file  body: {"path":"...","content":"..."}
    POST /api/file/rename              - Rename file or directory  body: {"path":"...","new_name":"..."}
    POST /api/file/edit                - Save/overwrite text file  body: {"path":"...","content":"..."}
    DELETE /api/file                   - Delete file or empty directory  (?path=...)
    GET  /api/file/download            - Download file as attachment  (?path=...)
    POST /api/file/upload              - Upload file (multipart)  (?path=target_dir)
    GET  /workspace/{path}             - Serve workspace files as static assets
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
        password: str = "",
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
        password : str
            If non-empty, all API endpoints (except /docs and /redoc) require
            HTTP Basic Auth with this password.  Username is ignored.
        """
        try:
            import fastapi  # noqa: F401
            import uvicorn  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "FastAPI and uvicorn are required for the CMD API server. "
                "Install them with:  pip install fastapi uvicorn"
            ) from exc

        # Resolve sock:
        #   None  → auto-generate a default path that embeds the port
        #   ""    → explicitly disabled
        #   other → use as-is (user-supplied path)
        if sock is None:
            sock = f"/tmp/ucagent_cmd_{port}.sock"
        elif sock == "":
            sock = None

        if not tcp and not sock:
            raise ValueError("At least one of 'tcp' or 'sock' must be enabled.")

        self.pdb = pdb_instance
        self.host = host
        self.port = port
        self.sock = sock
        self.tcp = tcp
        self.password = password
        self._running = False
        self.started_at: Optional[float] = None
        # TCP listener state
        self._tcp_server = None
        self._tcp_thread: Optional[threading.Thread] = None
        # Unix socket listener state
        self._sock_server = None
        self._sock_thread: Optional[threading.Thread] = None
        # Install stdout ring-buffer capture so /api/console can surface output
        self._original_stdout = sys.stdout
        self._console_capture = _ConsoleCapture(sys.stdout)
        sys.stdout = self._console_capture
        # Also redirect pdb.stdout so PDB prompt/output goes into the capture
        pdb_instance.stdout = self._console_capture
        self._app = self._build_app()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_app(self):  # noqa: C901 – intentionally long; each section is self-contained
        import mimetypes
        import os
        import pathlib
        import shutil

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning, module="fastapi")
            from fastapi import FastAPI, File, HTTPException, Query, UploadFile
            from fastapi.responses import FileResponse, HTMLResponse, Response
        from pydantic import BaseModel

        app = FastAPI(
            title="UCAgent PDB CMD API",
            description=(
                "REST API for inspecting the UCAgent VerifyPDB instance. "
                "Use GET /api/status, /api/mission, /api/tasks, /api/console for monitoring. "
                "GET /api/cmds lists available PDB commands."
            ),
            version="1.0.0",
        )

        # ── auth middleware (HTTP Basic, skips /docs and /redoc) ──────────
        import base64 as _base64
        import secrets as _secrets
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request as _Request
        from fastapi.responses import JSONResponse as _JSONResponse

        _password = self.password
        _EXCLUDED_PATHS = {"/docs", "/redoc", "/openapi.json"}

        class _AuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: _Request, call_next):
                if not _password or request.url.path in _EXCLUDED_PATHS:
                    return await call_next(request)
                auth = request.headers.get("Authorization", "")
                if auth.startswith("Basic "):
                    try:
                        decoded = _base64.b64decode(auth[6:]).decode("utf-8")
                        _, _, pwd = decoded.partition(":")
                        if _secrets.compare_digest(
                            pwd.encode("utf-8"), _password.encode("utf-8")
                        ):
                            return await call_next(request)
                    except Exception:
                        pass
                return _JSONResponse(
                    status_code=401,
                    content={"detail": "Authentication required."},
                    headers={"WWW-Authenticate": 'Basic realm="UCAgent CMD API"'},
                )

        app.add_middleware(_AuthMiddleware)

        pdb = self.pdb  # capture for closures

        # ── request bodies ─────────────────────────────────────────────
        class FileEditBody(BaseModel):
            path: str
            content: str
        class CmdBody(BaseModel):
            cmd: str

        class CmdsBody(BaseModel):
            cmds: List[str]
        # ── path helpers ───────────────────────────────────────────────
        def _workspace_root() -> str:
            return os.path.abspath(pdb.agent.workspace)

        def _safe_abs(rel_path: str) -> str:
            """Resolve rel_path within workspace, raise 403 on traversal."""
            root = _workspace_root()
            clean = rel_path.strip().lstrip("/")
            if clean:
                candidate = os.path.normpath(os.path.join(root, clean))
            else:
                candidate = root
            if not (candidate == root or candidate.startswith(root + os.sep)):
                raise HTTPException(status_code=403, detail="Path traversal not allowed")
            return candidate

        def _rel(abs_path: str) -> str:
            root = _workspace_root()
            rel = os.path.relpath(abs_path, root)
            return "" if rel == "." else rel

        def _fmt_size(n: int) -> str:
            for unit in ("B", "KB", "MB", "GB"):
                if n < 1024:
                    return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
                n /= 1024
            return f"{n:.1f} TB"

        _TEXT_EXTS = {
            ".txt", ".md", ".rst", ".py", ".js", ".ts", ".css", ".html", ".htm",
            ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".sh",
            ".bash", ".zsh", ".fish", ".v", ".sv", ".svh", ".vhd", ".vhdl",
            ".c", ".h", ".cpp", ".hpp", ".java", ".rs", ".go", ".rb", ".php",
            ".xml", ".csv", ".log", ".env", ".gitignore", ".makefile", ".mk",
            ".scala", ".lua", ".r", ".m", ".tex", ".bib", ".diff", ".patch",
        }

        def _is_text_file(path: str) -> bool:
            ext = pathlib.Path(path).suffix.lower()
            if ext in _TEXT_EXTS:
                return True
            mime, _ = mimetypes.guess_type(path)
            return bool(mime and mime.startswith("text/"))

        # ── HTML dashboard template (loaded from templates/agent.html) ────
        _TMPL_PATH = pathlib.Path(__file__).resolve().parent / "templates" / "agent.html"
        _HTML = _TMPL_PATH.read_text(encoding="utf-8")
        # ── index: HTML dashboard ───────────────────────────────────────
        @app.get("/", summary="HTML dashboard", response_class=HTMLResponse)
        def index():
            return HTMLResponse(content=_HTML)

        # ── GET /api/status ────────────────────────────────────────────
        @app.get("/api/status", summary="Agent status")
        def get_status():
            try:
                return {"status": "ok", "data": pdb.api_status()}
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /api/server_info ───────────────────────────────────────────
        @app.get("/api/server_info", summary="Running servers info (cmd_api, master_api, mcp)")
        def get_server_info():
            try:
                return {"status": "ok", "data": pdb.api_server_info()}
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /api/pdb_status ─────────────────────────────────────────────
        @app.get("/api/pdb_status", summary="PDB runtime status")
        def get_pdb_status():
            try:
                in_tui = getattr(pdb, "_in_tui", False)
                init_cmd = list(pdb.init_cmd) if pdb.init_cmd else []
                cmdqueue = list(pdb.cmdqueue) if pdb.cmdqueue else []
                pending = init_cmd if in_tui else cmdqueue
                is_break = pdb.agent.is_break()
                # running commands
                if in_tui and getattr(pdb, "_tui_app", None) is not None:
                    running_cmds = pdb._tui_app.key_handler.get_running_commands()
                else:
                    current = getattr(pdb, "_current_cmd", None)
                    running_cmds = [current] if current else []
                return {
                    "status": "ok",
                    "data": {
                        "in_tui": in_tui,
                        "is_break": is_break,
                        "pending_cmds": pending,
                        "pending_count": len(pending),
                        "prompt": pdb.prompt,
                        "running_cmds": running_cmds,
                    },
                }
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
                mission_data = pdb.api_mission_info(return_dict=True)
                if strip_ansi:
                    for stage in mission_data["stages"]:
                        stage["text"] = _strip_ansi(stage["text"])
                return {"status": "ok", "data": mission_data}
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
                _workspace = os.path.abspath(pdb.agent.workspace)
                _output_dir = os.path.abspath(pdb.agent.output_dir)
                output_dir_rel = os.path.relpath(_output_dir, _workspace)
                return {"status": "ok", "data": data, "output_dir": output_dir_rel}
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /api/stage/{index}/file ────────────────────────────────
        @app.get("/api/stage/{index}/file", summary="Get file content from a stage")
        def get_stage_file(
            index: int,
            file_path: str = Query(..., description="Path to the file in the stage")
        ):
            try:
                data = pdb.api_get_stage_file(index, file_path)
                return {"status": "ok", "data": data}
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /api/stage/{index}/file_current ────────────────────────────
        @app.get("/api/stage/{index}/file_current", summary="Get file content from a stage")
        def get_stage_file_current(
            index: int,
            file_path: str = Query(..., description="Path to the file in the stage")
        ):
            try:
                data = pdb.api_get_stage_file_current(index, file_path)
                return {"status": "ok", "data": data}
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

        # ── POST /api/cmd ─────────────────────────────────────────────────
        @app.post("/api/cmd", summary="Enqueue a single PDB command")
        def post_cmd(body: CmdBody):
            try:
                cmd = body.cmd.strip()
                if not cmd:
                    raise HTTPException(status_code=400, detail="'cmd' must not be empty")
                _capture.inject(f"{pdb.prompt}{cmd}")
                pdb.add_cmds(cmd)
                return {"status": "ok", "message": f"Command enqueued", "cmd": cmd}
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── POST /api/cmds/batch ─────────────────────────────────────────────
        @app.post("/api/cmds/batch", summary="Enqueue multiple PDB commands")
        def post_cmds_batch(body: CmdsBody):
            try:
                cmds = [c.strip() for c in body.cmds if c.strip()]
                if not cmds:
                    raise HTTPException(status_code=400, detail="'cmds' list is empty or all blank")
                for c in cmds:
                    _capture.inject(f"{pdb.prompt}{c}")
                pdb.add_cmds(cmds)
                return {"status": "ok", "message": f"{len(cmds)} command(s) enqueued", "count": len(cmds), "cmds": cmds}
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── POST /api/interrupt ──────────────────────────────────────────────
        @app.post("/api/interrupt", summary="Send Ctrl-C interrupt to PDB")
        def post_interrupt():
            import signal as _signal
            try:
                # Set the break flag first so the installed signal handler
                # will NOT raise KeyboardInterrupt when the OS signal arrives.
                pdb.agent.set_break(True)
                # Deliver SIGINT to the main thread (Python always delivers
                # signals to the main thread, where the handler is registered).
                os.kill(os.getpid(), _signal.SIGINT)
                return {"status": "ok", "message": "Interrupt sent"}
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /api/files ─────────────────────────────────────────────
        @app.get("/api/files", summary="List workspace directory")
        def list_files(
            path: str = Query(default="", description="Relative path within workspace (default: root)")
        ):
            try:
                import datetime
                abs_path = _safe_abs(path)
                if not os.path.isdir(abs_path):
                    raise HTTPException(status_code=400, detail=f"'{path}' is not a directory")
                entries = []
                for name in sorted(os.listdir(abs_path)):
                    full = os.path.join(abs_path, name)
                    try:
                        st = os.stat(full)
                    except OSError:
                        continue
                    is_dir = os.path.isdir(full)
                    rel_entry = os.path.join(_rel(abs_path), name) if _rel(abs_path) else name
                    ext = pathlib.Path(name).suffix.lstrip(".").lower() if not is_dir else ""
                    entries.append({
                        "name": name,
                        "path": rel_entry,
                        "is_dir": is_dir,
                        "size": st.st_size if not is_dir else 0,
                        "mtime": st.st_mtime,
                        "mtime_str": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                        "type": ext,
                        "is_text": (not is_dir) and _is_text_file(full),
                    })
                entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
                rel_path = _rel(abs_path)
                return {
                    "status": "ok",
                    "path": rel_path,
                    "workspace": _workspace_root(),
                    "data": entries,
                }
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /api/file ──────────────────────────────────────────────
        @app.get("/api/file", summary="Read text file content")
        def read_file_api(
            path: str = Query(..., description="Relative path within workspace")
        ):
            try:
                abs_path = _safe_abs(path)
                if not os.path.isfile(abs_path):
                    raise HTTPException(status_code=404, detail=f"File '{path}' not found")
                if not _is_text_file(abs_path):
                    raise HTTPException(status_code=400, detail=f"'{path}' does not appear to be a text file")
                st = os.stat(abs_path)
                for enc in ("utf-8", "utf-8-sig", "latin-1"):
                    try:
                        content = abs_path and open(abs_path, encoding=enc).read()
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    raise HTTPException(status_code=400, detail="File encoding not supported (tried utf-8, latin-1)")
                return {
                    "status": "ok",
                    "path": path,
                    "size": st.st_size,
                    "content": content,
                }
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── POST /api/file/new ──────────────────────────────────────────
        class FileNewBody(BaseModel):
            path: str      # relative path including filename
            content: str = ""

        @app.post("/api/file/new", summary="Create a new text file (fails if already exists)")
        def new_file(body: FileNewBody):
            try:
                abs_path = _safe_abs(body.path)
                if os.path.exists(abs_path):
                    raise HTTPException(status_code=409, detail=f"'{body.path}' already exists")
                parent = os.path.dirname(abs_path)
                if not os.path.isdir(parent):
                    raise HTTPException(status_code=400, detail=f"Parent directory does not exist: {os.path.relpath(parent, _workspace_root())}")
                with open(abs_path, "w", encoding="utf-8") as fh:
                    fh.write(body.content)
                return {"status": "ok", "message": f"File '{body.path}' created", "path": body.path, "size": len(body.content.encode("utf-8"))}
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── POST /api/file/rename ─────────────────────────────────────
        class FileRenameBody(BaseModel):
            path: str       # current relative path
            new_name: str   # new filename only (no directory component)

        @app.post("/api/file/rename", summary="Rename a file or directory")
        def rename_file(body: FileRenameBody):
            try:
                abs_src = _safe_abs(body.path)
                if not os.path.exists(abs_src):
                    raise HTTPException(status_code=404, detail=f"'{body.path}' not found")
                new_name = os.path.basename(body.new_name.strip())
                if not new_name:
                    raise HTTPException(status_code=400, detail="new_name must not be empty")
                if new_name != os.path.basename(new_name):
                    raise HTTPException(status_code=400, detail="new_name must be a plain name without path separators")
                parent = os.path.dirname(abs_src)
                abs_dst = os.path.join(parent, new_name)
                # ensure destination is still inside workspace
                _safe_abs(os.path.relpath(abs_dst, _workspace_root()))
                if os.path.exists(abs_dst):
                    raise HTTPException(status_code=409, detail=f"'{new_name}' already exists in the same directory")
                os.rename(abs_src, abs_dst)
                new_rel = os.path.relpath(abs_dst, _workspace_root())
                return {"status": "ok", "message": f"Renamed to '{new_name}'", "path": new_rel}
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── POST /api/file/edit ────────────────────────────────────────
        @app.post("/api/file/edit", summary="Save/overwrite a text file")
        def edit_file(body: FileEditBody):
            try:
                abs_path = _safe_abs(body.path)
                parent = os.path.dirname(abs_path)
                if not os.path.isdir(parent):
                    raise HTTPException(status_code=400, detail=f"Parent directory does not exist: {parent}")
                with open(abs_path, "w", encoding="utf-8") as fh:
                    fh.write(body.content)
                return {"status": "ok", "message": f"File '{body.path}' saved", "size": len(body.content.encode("utf-8"))}
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── DELETE /api/file ───────────────────────────────────────────
        @app.delete("/api/file", summary="Delete a file or empty directory")
        def delete_file(
            path: str = Query(..., description="Relative path within workspace")
        ):
            try:
                abs_path = _safe_abs(path)
                if not os.path.exists(abs_path):
                    raise HTTPException(status_code=404, detail=f"'{path}' not found")
                if os.path.isdir(abs_path):
                    try:
                        os.rmdir(abs_path)
                    except OSError:
                        # non-empty dir — remove recursively but only inside workspace
                        shutil.rmtree(abs_path)
                else:
                    os.remove(abs_path)
                return {"status": "ok", "message": f"Deleted '{path}'"}
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /api/file/download ─────────────────────────────────────
        @app.get("/api/file/download", summary="Download a file as attachment")
        def download_file(
            path: str = Query(..., description="Relative path within workspace")
        ):
            try:
                abs_path = _safe_abs(path)
                if not os.path.isfile(abs_path):
                    raise HTTPException(status_code=404, detail=f"File '{path}' not found")
                filename = os.path.basename(abs_path)
                media_type, _ = mimetypes.guess_type(abs_path)
                return FileResponse(
                    path=abs_path,
                    filename=filename,
                    media_type=media_type or "application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'},
                )
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── POST /api/file/upload ──────────────────────────────────────
        @app.post("/api/file/upload", summary="Upload a file into the workspace")
        async def upload_file(
            path: str = Query(default="", description="Target directory (relative to workspace root)"),
            file: UploadFile = File(...),
        ):
            try:
                target_dir = _safe_abs(path)
                if not os.path.isdir(target_dir):
                    raise HTTPException(status_code=400, detail=f"Target path '{path}' is not a directory")
                filename = pathlib.Path(file.filename or "upload").name  # strip any dir components
                dest = os.path.join(target_dir, filename)
                with open(dest, "wb") as fh:
                    while True:
                        chunk = await file.read(1 << 20)  # 1 MiB chunks
                        if not chunk:
                            break
                        fh.write(chunk)
                size = os.path.getsize(dest)
                return {
                    "status": "ok",
                    "message": f"Uploaded '{filename}'",
                    "path": _rel(dest),
                    "size": size,
                }
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /workspace — redirect to dashboard ────────────────────
        @app.get("/workspace", summary="Workspace root (redirects to dashboard)", include_in_schema=False)
        @app.get("/workspace/", include_in_schema=False)
        def serve_workspace_root():
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url="/")

        # ── GET /workspace/{path} — static asset serving ──────────────
        @app.get("/workspace/{path:path}", summary="Serve workspace file as static asset")
        def serve_workspace_file(path: str):
            try:
                abs_path = _safe_abs(path)
                if not os.path.isfile(abs_path):
                    raise HTTPException(status_code=404, detail=f"'{path}' not found or is a directory")
                media_type, _ = mimetypes.guess_type(abs_path)
                return FileResponse(
                    path=abs_path,
                    media_type=media_type or "application/octet-stream",
                )
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /static/{path} — bundled static assets ─────────────────
        _STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"

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

        @app.get("/surfer", include_in_schema=False)
        def serve_surfer_redirect():
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url="/surfer/")

        @app.get("/surfer/", include_in_schema=False)
        def serve_surfer_root():
            abs_path = _SURFER_DIR / "index.html"
            if not abs_path.is_file():
                raise HTTPException(status_code=404, detail="Surfer waveform viewer not found")
            return FileResponse(path=str(abs_path), media_type="text/html")

        @app.get("/surfer/{path:path}", include_in_schema=False)
        def serve_surfer_asset(path: str):
            abs_path = (_SURFER_DIR / path).resolve()
            if not str(abs_path).startswith(str(_SURFER_DIR)):
                raise HTTPException(status_code=403, detail="Forbidden")
            if not abs_path.is_file():
                raise HTTPException(status_code=404, detail=f"Surfer asset '{path}' not found")
            media_type, _ = mimetypes.guess_type(str(abs_path))
            return FileResponse(path=str(abs_path), media_type=media_type or "application/octet-stream")

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
                    lifespan="off",
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
                        lifespan="off",
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
        self.started_at = __import__('time').time()
        # Register atexit cleanup so the sock file is removed even if stop()
        # is never called (e.g. process exits via sys.exit or reaches end).
        if self.sock:
            import atexit as _atexit, os as _os
            _sock = self.sock
            def _cleanup_sock():
                try:
                    if _os.path.exists(_sock):
                        _os.unlink(_sock)
                except OSError:
                    pass
            _atexit.register(_cleanup_sock)
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
        self.started_at = None

        # Restore stdout/stderr.  Use the *current* downstream of the capture
        # wrapper (``_original``), NOT the value saved at __init__ time.  If
        # PdbCmdApiServer was created inside a TUI session, _original_stdout
        # captures the TUI's sink, which is dead after TUI exits.  However,
        # the TUI exit path relinks _console_capture._original to the real
        # stdout, so _console_capture._original is always the correct target.
        restore_to = getattr(self._console_capture, '_original', self._original_stdout)
        if sys.stdout is self._console_capture:
            sys.stdout = restore_to
        if self.pdb.stdout is self._console_capture:
            self.pdb.stdout = restore_to

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
