# -*- coding: utf-8 -*-
"""
CMD API server for VerifyPDB — FastAPI implementation.

Runs a FastAPI/uvicorn HTTP server in a background thread, exposing the
PDB instance's api_* methods and command queue via REST endpoints so
external tools can inspect/control the agent without touching the console.
"""

import collections
import copy
import io
import json
import re
import sys
import threading
import time
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
        from ucagent.tui.utils import PersistentConsoleMirror
        while isinstance(original, (_ConsoleCapture, PersistentConsoleMirror)):
            original = original._original
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
    GET  /api/status                   - Agent status string (?sub_worspace=...)
    GET  /api/server_info              - Running servers info (cmd_api, master_api, mcp)
    GET  /api/pdb_status               - PDB runtime status (tui, pending cmds, break state)
    GET  /api/tasks                    - Task list (?sub_worspace=...)
    GET  /api/task/{index}             - Task detail (?sub_worspace=...)
    GET  /api/mission                  - Mission overview (raw ANSI; ?strip_ansi=true to strip&sub_worspace=...)
    GET  /api/cmds                     - All available PDB commands  (?prefix=)
    GET  /api/help                     - Command help  (?cmd=<name>)
    GET  /api/tools                    - Tool list with call counts
    GET  /api/changed_files            - Recently changed output files  (?count=10)
    GET  /api/stage/{index}/task       - Get task detail from a stage
    GET  /api/stage/{index}/file       - Get file content from a stage  (?file_path=...)
    GET  /api/stage/{index}/file_current - Get current stage file content (?file_path=...)
    GET  /api/console                  - Captured stdout/stderr ring buffer (?lines=200&strip_ansi=false)
    DELETE /api/console                - Clear captured stdout buffer
    POST /api/cmd                      - Enqueue a single PDB command  {"cmd": "..."}
    POST /api/cmds/batch               - Enqueue multiple PDB commands  {"cmds": [...]}
    POST /api/interrupt                - Send Ctrl-C interrupt to PDB
    GET  /api/files                    - List workspace directory  (?path=subdir&sub_worspace=...)
    GET  /api/file                     - Read text file content  (?path=...&sub_worspace=...)
    POST /api/file/new                 - Create new text file  body: {"path":"...","content":"..."}
    POST /api/file/rename              - Rename file or directory  body: {"path":"...","new_name":"..."}
    POST /api/file/edit                - Save/overwrite text file  body: {"path":"...","content":"..."}
    DELETE /api/file                   - Delete file or empty directory  (?path=...)
    GET  /api/file/download            - Download file or directory as attachment  (?path=...)
    GET  /api/workspace/download       - Download whole workspace as {DUT}.tar.gz
    POST /api/file/upload              - Upload file (multipart)  (?path=target_dir)
    GET  /workspace/{path}             - Serve workspace files as static assets (redirects to dashboard for root)
    GET  /static/{path}                - Serve bundled static assets
    GET  /surfer/ and /surfer/{path}   - Surfer waveform viewer (static)
    GET  /docs, /redoc                 - OpenAPI docs (Swagger UI, ReDoc)
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
        # Set console sync handler to capture output from log functions
        from ucagent.util import log
        self._original_sync_handler = log.get_console_sync_handler()
        def sync_to_capture(text: str):
            self._console_capture.write(text)
            if self._original_sync_handler:
                self._original_sync_handler(text)
        log.set_console_sync_handler(sync_to_capture)
        self._app = self._build_app()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_app(self):  # noqa: C901 – intentionally long; each section is self-contained
        import mimetypes
        import os
        import pathlib
        import shutil
        import tarfile
        import tempfile

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning, module="fastapi")
            from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
            from fastapi.responses import FileResponse, HTMLResponse, Response
            from starlette.background import BackgroundTask
        from pydantic import BaseModel
        from ucagent.util import diff_ops
        from ucagent.util.functions import (
            find_files_by_pattern,
            fmt_time_deta,
            fmt_time_stamp,
            list_files_by_mtime,
        )
        from ucagent.util.log import L_GREEN, L_RED, L_YELLOW, RESET

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

        class StageFlagsBody(BaseModel):
            indices: List[int]
            hmcheck_needed: Optional[bool] = None
            skip: Optional[bool] = None
            llm_fail_suggestion: Optional[bool] = None
            llm_pass_suggestion: Optional[bool] = None
        # ── path / sub-workspace helpers ───────────────────────────────
        def _base_workspace_root() -> str:
            return os.path.abspath(pdb.agent.workspace)

        def _workspace_root(workspace_root: Optional[str] = None) -> str:
            return os.path.abspath(workspace_root or _base_workspace_root())

        def _is_under(base: str, candidate: str) -> bool:
            try:
                base_real = os.path.realpath(os.path.abspath(base))
                cand_real = os.path.realpath(os.path.abspath(candidate))
                return os.path.commonpath([base_real, cand_real]) == base_real
            except ValueError:
                return False

        def _rel_to_base(abs_path: str) -> str:
            base = _base_workspace_root()
            rel = os.path.relpath(os.path.abspath(abs_path), base)
            return "" if rel == "." else rel

        def _ucagent_info_path(workspace_root: str) -> str:
            return os.path.join(os.path.abspath(workspace_root), ".ucagent", "ucagent_info.json")

        def _is_ucagent_workspace(workspace_root: str) -> bool:
            return os.path.isfile(_ucagent_info_path(workspace_root))

        def _load_ucagent_info_for_workspace(workspace_root: str) -> dict:
            info_path = _ucagent_info_path(workspace_root)
            if not os.path.isfile(info_path):
                return {}
            with open(info_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}

        def _query_sub_workspace(request: Optional[Request]) -> str:
            if request is None:
                return ""
            # Keep the documented typo for compatibility and accept the
            # corrected spelling too.
            return (
                request.query_params.get("sub_worspace")
                or request.query_params.get("sub_workspace")
                or ""
            ).strip()

        def _resolve_sub_workspace(raw_sub_workspace: str = "") -> Tuple[str, str, bool]:
            base = _base_workspace_root()
            raw = (raw_sub_workspace or "").strip()
            if not raw:
                return base, "", False

            expanded = os.path.expanduser(raw)
            candidate = (
                os.path.abspath(expanded)
                if os.path.isabs(expanded)
                else os.path.abspath(os.path.join(base, expanded.lstrip("/")))
            )
            if not _is_under(base, candidate):
                raise HTTPException(status_code=403, detail="Sub workspace must be under the current workspace")
            if os.path.realpath(candidate) == os.path.realpath(base):
                return base, "", False
            if not os.path.isdir(candidate):
                raise HTTPException(status_code=404, detail=f"Sub workspace '{raw}' not found")
            if not _is_ucagent_workspace(candidate):
                raise HTTPException(
                    status_code=400,
                    detail=f"'{_rel_to_base(candidate)}' is not a UCAgent workspace",
                )
            return candidate, _rel_to_base(candidate), True

        def _request_workspace(request: Optional[Request]) -> Tuple[str, str, bool]:
            return _resolve_sub_workspace(_query_sub_workspace(request))

        def _safe_abs(rel_path: str, workspace_root: Optional[str] = None) -> str:
            """Resolve rel_path within workspace, raise 403 on traversal."""
            root = _workspace_root(workspace_root)
            clean = rel_path.strip().lstrip("/")
            if clean:
                candidate = os.path.normpath(os.path.join(root, clean))
            else:
                candidate = root
            if not _is_under(root, candidate):
                raise HTTPException(status_code=403, detail="Path traversal not allowed")
            return candidate

        def _rel(abs_path: str, workspace_root: Optional[str] = None) -> str:
            root = _workspace_root(workspace_root)
            rel = os.path.relpath(abs_path, root)
            return "" if rel == "." else rel

        def _stage_items_from_info(info: dict) -> list[Tuple[int, dict]]:
            stages_info = info.get("stages_info", {})
            if not isinstance(stages_info, dict):
                return []

            def _stage_key(item) -> int:
                key, _ = item
                try:
                    return int(key)
                except (TypeError, ValueError):
                    return 0

            items = []
            for raw_key, stage_info in sorted(stages_info.items(), key=_stage_key):
                if not isinstance(stage_info, dict):
                    continue
                try:
                    index = int(raw_key)
                except (TypeError, ValueError):
                    index = len(items)
                items.append((index, stage_info))
            return items

        def _sub_mission_name(workspace_root: str, info: dict) -> str:
            for key in ("mission_name", "mission", "misson_name"):
                value = info.get(key)
                if value:
                    return str(value)
            return os.path.basename(os.path.normpath(workspace_root)) or "Sub Workspace"

        def _format_stage_time_cost(value) -> str:
            if value in (None, "", 0, 0.0):
                return ""
            try:
                return fmt_time_deta(value)
            except Exception:
                return str(value)

        def _format_sub_status(workspace_root: str, info: dict) -> str:
            stage_items = _stage_items_from_info(info)
            stage_index = info.get("stage_index", 0)
            all_completed = bool(info.get("all_completed", False))
            try:
                stage_index_int = int(stage_index)
            except (TypeError, ValueError):
                stage_index_int = 0
            run_end = info.get("time_end") or time.time()
            run_time = None
            if info.get("time_begin") is not None:
                try:
                    run_time = fmt_time_deta(float(run_end) - float(info.get("time_begin")))
                except Exception:
                    run_time = None
            rows = [
                ("UCAgent", info.get("version", "unknown")),
                ("Workspace", workspace_root),
                ("Seed", info.get("seed", "N/A")),
                ("Stage", f"{stage_index_int}/{len(stage_items)}"),
                ("All Completed", all_completed),
                ("Agent Exit", bool(info.get("is_agent_exit", False))),
            ]
            if info.get("time_begin") is not None:
                rows.append(("Start Time", fmt_time_stamp(info.get("time_begin"))))
            if run_time:
                rows.append(("Run Time", run_time))
            return "\n".join(f"{key}: {value}" for key, value in rows)

        def _sub_task_list(workspace_root: str, info: dict) -> dict:
            stage_items = _stage_items_from_info(info)
            stage_index = info.get("stage_index", 0)
            try:
                stage_index = int(stage_index)
            except (TypeError, ValueError):
                stage_index = 0
            if bool(info.get("all_completed", False)):
                stage_index = len(stage_items)
            stage_list = []
            for index, detail in stage_items:
                task = detail.get("task", {}) if isinstance(detail.get("task", {}), dict) else {}
                skill_list = task.get("skill_list", [])
                if isinstance(skill_list, dict):
                    skill_list = list(skill_list.keys())
                elif not isinstance(skill_list, list):
                    skill_list = []
                stage_list.append({
                    "index": index,
                    "title": task.get("title") or detail.get("title") or f"Stage {index}",
                    "reached": bool(detail.get("reached", index <= stage_index)),
                    "fail_count": detail.get("fail_count", 0),
                    "skill_list": skill_list,
                    "is_skipped": bool(detail.get("is_skipped", False)),
                    "time_start": "",
                    "time_end": "",
                    "time_cost": _format_stage_time_cost(detail.get("time_cost")),
                    "is_completed": bool(detail.get("is_completed", index < stage_index)),
                    "needs_human_check": bool(detail.get("needs_human_check", False)),
                    "need_fail_llm_suggestion": bool(detail.get("need_fail_llm_suggestion", False)),
                    "need_pass_llm_suggestion": bool(detail.get("need_pass_llm_suggestion", False)),
                })
            current_task = "No stages available"
            if 0 <= stage_index < len(stage_list):
                current_task = stage_list[stage_index]["title"]
            return {
                "mission_name": _sub_mission_name(workspace_root, info),
                "task_index": stage_index,
                "task_list": {
                    "mission": _sub_mission_name(workspace_root, info),
                    "all_completed": bool(info.get("all_completed", False)),
                    "stage_list": stage_list,
                    "process": f"{stage_index}/{len(stage_list)}",
                    "current_stage_index": stage_index if stage_index < len(stage_list) else None,
                    "current_stage_name": current_task,
                    "current_task": current_task,
                    "last_check_result": {},
                },
            }

        def _sub_stage_detail_with_journal(workspace_root: str, info: dict, index: int):
            stage_items = _stage_items_from_info(info)
            stage_map = {stage_index: detail for stage_index, detail in stage_items}
            if index not in stage_map:
                if not stage_items:
                    return "Index 0 out of range, valid: (none)"
                valid_min = min(stage_map)
                valid_max = max(stage_map)
                return f"Index {index} out of range, valid: ({valid_min}-{valid_max})"
            detail = copy.deepcopy(stage_map[index])
            meta_data = detail.get("meta_data", {}) if isinstance(detail.get("meta_data", {}), dict) else {}
            journal = meta_data.get("journal")
            llm_suggestions = {
                "pass": meta_data.get("llm_pass_suggestion"),
                "fail": meta_data.get("llm_fail_suggestion"),
            }
            try:
                stage_index = int(info.get("stage_index", 0) or 0)
            except (TypeError, ValueError):
                stage_index = 0
            data = {
                "is_current": (index == stage_index) and not bool(info.get("all_completed", False)),
                "detail": detail,
                "journal": journal,
                "StageJournal": journal,
                "last_do_check_info": None,
                "llm_suggestions": llm_suggestions,
                "workspace": workspace_root,
            }
            detail["journal"] = journal
            detail["StageJournal"] = journal
            detail["last_do_check_info"] = None
            detail["llm_suggestions"] = llm_suggestions
            return data

        def _sub_stage_outcome(workspace_root: str, detail: dict) -> dict:
            task = detail.get("task", {}) if isinstance(detail.get("task", {}), dict) else {}
            output_patterns = task.get("output_files", [])
            if isinstance(output_patterns, str):
                output_patterns = [output_patterns]
            if not isinstance(output_patterns, list):
                output_patterns = []
            output_files = {}
            for pattern in output_patterns:
                try:
                    output_files[str(pattern)] = find_files_by_pattern(
                        workspace_root,
                        str(pattern),
                        ignore_warn=True,
                    )
                except Exception:
                    output_files[str(pattern)] = []

            changed_files = []
            meta_data = detail.get("meta_data", {}) if isinstance(detail.get("meta_data", {}), dict) else {}
            commit_hash = meta_data.get("commit", {}).get("hash") if isinstance(meta_data.get("commit", {}), dict) else None
            if commit_hash:
                try:
                    changed_files = diff_ops.get_commit_changed_files(
                        os.path.join(workspace_root, ".ucagent", "history"),
                        commit_hash,
                    )
                except Exception:
                    changed_files = []
            return {
                "output_files": output_files,
                "changed_files": changed_files,
                "commit_hash": commit_hash,
                "commit_message": meta_data.get("commit", {}).get("message") if isinstance(meta_data.get("commit", {}), dict) else None,
            }

        def _sub_mission_info(workspace_root: str, info: dict) -> dict:
            task_data = _sub_task_list(workspace_root, info)
            current_index = task_data["task_index"]
            stage_list = task_data["task_list"]["stage_list"]
            ret = collections.OrderedDict({
                "misson_name": task_data["mission_name"],
                "current_index": current_index,
                "enable_llm_fail_suggestion": any(s.get("need_fail_llm_suggestion") for s in stage_list),
                "enable_llm_pass_suggestion": any(s.get("need_pass_llm_suggestion") for s in stage_list),
                "stages": [],
            })
            stage_detail_map = {index: detail for index, detail in _stage_items_from_info(info)}
            for stage in stage_list:
                index = stage["index"]
                title = stage.get("title") or f"Stage {index}"
                fail_count = stage.get("fail_count", 0)
                time_cost = stage.get("time_cost", "")
                is_skipped = bool(stage.get("is_skipped", False))
                is_current = index == current_index and not bool(info.get("all_completed", False))
                is_completed = bool(stage.get("is_completed", False)) or index < current_index or bool(info.get("all_completed", False))
                fail_count_msg = "" if is_skipped else f" ({fail_count} fails{', ' + time_cost if time_cost else ''})"
                display_title = f"{title} (skipped)" if is_skipped else title
                color = ""
                if is_completed:
                    color = L_GREEN
                if is_current:
                    color = L_RED
                if is_skipped:
                    color = L_YELLOW
                cend = RESET if color else ""
                text = f"{color}{index:2d}{cend} {color}{display_title}{fail_count_msg}{cend}"
                detail = stage_detail_map.get(index, {})
                outcome = None
                if stage.get("reached", False) or is_completed or is_current:
                    outcome = _sub_stage_outcome(workspace_root, detail)
                ret["stages"].append({
                    "index": index,
                    "text": text,
                    "out_come": outcome,
                    "title": title,
                    "is_current": is_current,
                    "is_completed": is_completed,
                    "is_skipped": is_skipped,
                    "needs_human_check": bool(stage.get("needs_human_check", False)),
                    "need_fail_llm_suggestion": bool(stage.get("need_fail_llm_suggestion", False)),
                    "need_pass_llm_suggestion": bool(stage.get("need_pass_llm_suggestion", False)),
                    "can_edit_flags": False,
                })
            return ret

        def _read_text_file_payload(abs_path: str, rel_path: str) -> dict:
            if not os.path.isfile(abs_path):
                raise HTTPException(status_code=404, detail=f"File '{rel_path}' not found")
            if not _is_text_file(abs_path):
                raise HTTPException(status_code=400, detail=f"'{rel_path}' does not appear to be a text file")
            st = os.stat(abs_path)
            for enc in ("utf-8", "utf-8-sig", "latin-1"):
                try:
                    with open(abs_path, encoding=enc) as fh:
                        content = fh.read()
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise HTTPException(status_code=400, detail="File encoding not supported (tried utf-8, latin-1)")
            return {
                "status": "ok",
                "path": rel_path,
                "size": st.st_size,
                "content": content,
            }

        def _sub_stage_file_payload(workspace_root: str, info: dict, index: int, file_path: str, current: bool) -> dict:
            detail_data = _sub_stage_detail_with_journal(workspace_root, info, index)
            if isinstance(detail_data, str):
                return {"error": detail_data}
            detail = detail_data.get("detail", {})
            meta_data = detail.get("meta_data", {}) if isinstance(detail.get("meta_data", {}), dict) else {}
            commit_hash = meta_data.get("commit", {}).get("hash") if isinstance(meta_data.get("commit", {}), dict) else None
            hist_dir = os.path.join(workspace_root, ".ucagent", "history")
            if commit_hash and os.path.isdir(hist_dir):
                try:
                    if current:
                        return diff_ops.get_current_file_content_and_diff_from_commit(hist_dir, commit_hash, file_path)
                    return diff_ops.get_commit_file_content_and_diff(hist_dir, commit_hash, file_path)
                except Exception as exc:
                    hist_error = str(exc)
                else:
                    hist_error = ""
            else:
                hist_error = "stage history is unavailable"

            try:
                abs_path = _safe_abs(file_path, workspace_root)
                payload = _read_text_file_payload(abs_path, file_path)
                return {
                    "is_text": True,
                    "content": payload.get("content", ""),
                    "diff": "",
                    "error": None if current else hist_error,
                }
            except Exception as exc:
                return {"is_text": False, "content": "", "diff": "", "error": f"{hist_error}; {exc}"}

        def _commands_for_workspace(
            cmds: List[str],
            workspace_root: str,
            workspace_rel: str,
        ) -> List[str]:
            if not workspace_rel:
                return cmds
            routed = []
            chcwd_cmd = f"chcwd {workspace_root}"
            for cmd in cmds:
                # In sub-workspace mode, reset-style cwd commands should land
                # at the active sub-workspace root. Other commands run as-is.
                if cmd.strip().lower() in ("cd", "chcwd ."):
                    routed.append(chcwd_cmd)
                else:
                    routed.append(cmd)
            return routed

        def _archive_dir_response(abs_dir: str, archive_base: str, filename: str):
            fd, archive_path = tempfile.mkstemp(
                prefix=f"{archive_base}.",
                suffix=".tar.gz",
            )
            os.close(fd)
            try:
                with tarfile.open(archive_path, "w:gz") as tar:
                    tar.add(abs_dir, arcname=archive_base, recursive=True)
            except Exception:
                try:
                    os.remove(archive_path)
                except OSError:
                    pass
                raise
            return FileResponse(
                path=archive_path,
                filename=filename,
                media_type="application/gzip",
                background=BackgroundTask(os.remove, archive_path),
            )

        def _safe_archive_base(name: str, default: str = "workspace") -> str:
            base = pathlib.Path(str(name or "").strip()).name
            return base or default

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

        # ── GET /api/status ────────────────────────────────────────────
        @app.get("/api/status", summary="Agent status")
        def get_status(request: Request):
            try:
                workspace_root, _, is_sub_workspace = _request_workspace(request)
                if is_sub_workspace:
                    info = _load_ucagent_info_for_workspace(workspace_root)
                    return {"status": "ok", "data": _format_sub_status(workspace_root, info)}
                return {"status": "ok", "data": pdb.api_status()}
            except HTTPException:
                raise
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
                running_cmds = pdb.get_running_commands()
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
        def get_tasks(request: Request):
            try:
                workspace_root, _, is_sub_workspace = _request_workspace(request)
                if is_sub_workspace:
                    info = _load_ucagent_info_for_workspace(workspace_root)
                    return {"status": "ok", "data": _sub_task_list(workspace_root, info)}
                return {"status": "ok", "data": pdb.api_task_list()}
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        def _task_detail_with_journal(index: int):
            data = pdb.api_task_detail(index=index)
            if isinstance(data, dict):
                stage = pdb.agent.stage_manager.get_stage(index)
                journal = stage.meta_get_journal() if stage else None
                last_do_check_info = None
                get_last_do_check_info = getattr(stage, "get_last_do_check_info", None) if stage else None
                if callable(get_last_do_check_info):
                    last_do_check_info = get_last_do_check_info()
                llm_suggestions = None
                if stage:
                    get_pass_suggestion = getattr(stage, "meta_get_llm_pass_suggestion", None)
                    get_fail_suggestion = getattr(stage, "meta_get_llm_fail_suggestion", None)
                    llm_suggestions = {
                        "pass": get_pass_suggestion() if callable(get_pass_suggestion) else None,
                        "fail": get_fail_suggestion() if callable(get_fail_suggestion) else None,
                    }
                data["journal"] = journal
                data["StageJournal"] = journal
                data["last_do_check_info"] = last_do_check_info
                data["llm_suggestions"] = llm_suggestions
                detail = data.get("detail")
                if isinstance(detail, dict):
                    detail["journal"] = journal
                    detail["StageJournal"] = journal
                    detail["last_do_check_info"] = last_do_check_info
                    detail["llm_suggestions"] = llm_suggestions
            return data

        # ── GET /api/task/{index} ──────────────────────────────────────
        @app.get("/api/task/{index}", summary="Task detail")
        def get_task(index: int, request: Request):
            try:
                workspace_root, _, is_sub_workspace = _request_workspace(request)
                if is_sub_workspace:
                    info = _load_ucagent_info_for_workspace(workspace_root)
                    return {"status": "ok", "data": _sub_stage_detail_with_journal(workspace_root, info, index)}
                return {"status": "ok", "data": _task_detail_with_journal(index)}
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /api/stage/{index}/task ────────────────────────────────
        @app.get("/api/stage/{index}/task", summary="Get task detail from a stage")
        def get_stage_task(index: int, request: Request):
            try:
                workspace_root, _, is_sub_workspace = _request_workspace(request)
                if is_sub_workspace:
                    info = _load_ucagent_info_for_workspace(workspace_root)
                    return {"status": "ok", "data": _sub_stage_detail_with_journal(workspace_root, info, index)}
                return {"status": "ok", "data": _task_detail_with_journal(index)}
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /api/mission ───────────────────────────────────────────
        @app.get("/api/mission", summary="Mission overview")
        def get_mission(
            request: Request,
            strip_ansi: bool = Query(default=False, description="Strip ANSI escape codes from output"),
        ):
            try:
                workspace_root, _, is_sub_workspace = _request_workspace(request)
                if is_sub_workspace:
                    info = _load_ucagent_info_for_workspace(workspace_root)
                    mission_data = _sub_mission_info(workspace_root, info)
                else:
                    mission_data = pdb.api_mission_info(return_dict=True)
                if strip_ansi:
                    for stage in mission_data["stages"]:
                        stage["text"] = _strip_ansi(stage["text"])
                return {"status": "ok", "data": mission_data}
            except HTTPException:
                raise
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
        def get_tools(request: Request):
            try:
                _, _, is_sub_workspace = _request_workspace(request)
                if is_sub_workspace:
                    return {"status": "ok", "data": []}
                tools = pdb.api_tool_status()
                data = [
                    {"name": name, "call_count": count, "is_hot": is_hot}
                    for name, count, is_hot in tools
                ]
                return {"status": "ok", "data": data}
            except HTTPException:
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
                files = pdb.api_changed_files(count)
                data = [
                    {"delta_seconds": d, "timestamp": t, "file": f}
                    for d, t, f in files
                ]
                _workspace = os.path.abspath(pdb.agent.workspace)
                _output_dir = os.path.abspath(pdb.agent.output_dir)
                output_dir_rel = os.path.relpath(_output_dir, _workspace)
                return {"status": "ok", "data": data, "output_dir": output_dir_rel}
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /api/stage/{index}/file ────────────────────────────────
        @app.get("/api/stage/{index}/file", summary="Get file content from a stage")
        def get_stage_file(
            request: Request,
            index: int,
            file_path: str = Query(..., description="Path to the file in the stage")
        ):
            try:
                workspace_root, _, is_sub_workspace = _request_workspace(request)
                if is_sub_workspace:
                    info = _load_ucagent_info_for_workspace(workspace_root)
                    return {
                        "status": "ok",
                        "data": _sub_stage_file_payload(workspace_root, info, index, file_path, current=False),
                    }
                data = pdb.api_get_stage_file(index, file_path)
                return {"status": "ok", "data": data}
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /api/stage/{index}/file_current ────────────────────────────
        @app.get("/api/stage/{index}/file_current", summary="Get file content from a stage")
        def get_stage_file_current(
            request: Request,
            index: int,
            file_path: str = Query(..., description="Path to the file in the stage")
        ):
            try:
                workspace_root, _, is_sub_workspace = _request_workspace(request)
                if is_sub_workspace:
                    info = _load_ucagent_info_for_workspace(workspace_root)
                    return {
                        "status": "ok",
                        "data": _sub_stage_file_payload(workspace_root, info, index, file_path, current=True),
                    }
                data = pdb.api_get_stage_file_current(index, file_path)
                return {"status": "ok", "data": data}
            except HTTPException:
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

        # ── POST /api/cmd ─────────────────────────────────────────────────
        @app.post("/api/cmd", summary="Enqueue a single PDB command")
        def post_cmd(body: CmdBody, request: Request):
            try:
                workspace_root, workspace_rel, _ = _request_workspace(request)
                cmd = body.cmd.strip()
                if not cmd:
                    raise HTTPException(status_code=400, detail="'cmd' must not be empty")
                _capture.inject(f"{pdb.prompt}{cmd}")
                pdb.add_cmds(_commands_for_workspace([cmd], workspace_root, workspace_rel))
                return {"status": "ok", "message": f"Command enqueued", "cmd": cmd}
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── POST /api/cmds/batch ─────────────────────────────────────────────
        @app.post("/api/cmds/batch", summary="Enqueue multiple PDB commands")
        def post_cmds_batch(body: CmdsBody, request: Request):
            try:
                workspace_root, workspace_rel, _ = _request_workspace(request)
                cmds = [c.strip() for c in body.cmds if c.strip()]
                if not cmds:
                    raise HTTPException(status_code=400, detail="'cmds' list is empty or all blank")
                for c in cmds:
                    _capture.inject(f"{pdb.prompt}{c}")
                pdb.add_cmds(_commands_for_workspace(cmds, workspace_root, workspace_rel))
                return {"status": "ok", "message": f"{len(cmds)} command(s) enqueued", "count": len(cmds), "cmds": cmds}
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        @app.post("/api/stages/update", summary="Update stage flags")
        def post_stage_update(body: StageFlagsBody, request: Request):
            try:
                _, _, is_sub_workspace = _request_workspace(request)
                if is_sub_workspace:
                    raise HTTPException(status_code=400, detail="Stage flags cannot be modified from sub-workspace view")
                updated = pdb.api_update_stage_flags(
                    indices=body.indices,
                    hmcheck_needed=body.hmcheck_needed,
                    skip=body.skip,
                    llm_fail_suggestion=body.llm_fail_suggestion,
                    llm_pass_suggestion=body.llm_pass_suggestion,
                )
                return {"status": "ok", "data": updated}
            except HTTPException:
                raise
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
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
            request: Request,
            path: str = Query(default="", description="Relative path within workspace (default: root)")
        ):
            try:
                import datetime
                workspace_root, workspace_rel, is_sub_workspace = _request_workspace(request)
                abs_path = _safe_abs(path, workspace_root)
                if not os.path.isdir(abs_path):
                    raise HTTPException(status_code=400, detail=f"'{path}' is not a directory")
                entries = []
                base_root = _base_workspace_root()
                for name in sorted(os.listdir(abs_path)):
                    full = os.path.join(abs_path, name)
                    try:
                        st = os.stat(full)
                    except OSError:
                        continue
                    is_dir = os.path.isdir(full)
                    parent_rel = _rel(abs_path, workspace_root)
                    rel_entry = os.path.join(parent_rel, name) if parent_rel else name
                    ext = pathlib.Path(name).suffix.lstrip(".").lower() if not is_dir else ""
                    is_ucagent_dir = (
                        is_dir
                        and _is_ucagent_workspace(full)
                        and _is_under(base_root, full)
                        and os.path.realpath(full) != os.path.realpath(base_root)
                    )
                    entries.append({
                        "name": name,
                        "path": rel_entry,
                        "is_dir": is_dir,
                        "size": st.st_size if not is_dir else 0,
                        "mtime": st.st_mtime,
                        "mtime_str": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                        "type": ext,
                        "is_text": (not is_dir) and _is_text_file(full),
                        "is_ucagent_workspace": is_ucagent_dir,
                        "sub_workspace_path": _rel_to_base(full) if is_ucagent_dir else "",
                    })
                entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
                rel_path = _rel(abs_path, workspace_root)
                current_is_ucagent = (
                    _is_ucagent_workspace(abs_path)
                    and _is_under(base_root, abs_path)
                    and os.path.realpath(abs_path) != os.path.realpath(base_root)
                )
                current_sub_workspace = _rel_to_base(abs_path) if current_is_ucagent else ""
                return {
                    "status": "ok",
                    "path": rel_path,
                    "workspace": workspace_root,
                    "base_workspace": base_root,
                    "sub_workspace": workspace_rel,
                    "is_sub_workspace": is_sub_workspace,
                    "current_is_ucagent_workspace": current_is_ucagent,
                    "current_sub_workspace": current_sub_workspace,
                    "data": entries,
                }
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /api/file ──────────────────────────────────────────────
        @app.get("/api/file", summary="Read text file content")
        def read_file_api(
            request: Request,
            path: str = Query(..., description="Relative path within workspace")
        ):
            try:
                workspace_root, _, _ = _request_workspace(request)
                abs_path = _safe_abs(path, workspace_root)
                return _read_text_file_payload(abs_path, path)
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── POST /api/file/new ──────────────────────────────────────────
        class FileNewBody(BaseModel):
            path: str      # relative path including filename
            content: str = ""

        @app.post("/api/file/new", summary="Create a new text file (fails if already exists)")
        def new_file(body: FileNewBody, request: Request):
            try:
                workspace_root, _, _ = _request_workspace(request)
                abs_path = _safe_abs(body.path, workspace_root)
                if os.path.exists(abs_path):
                    raise HTTPException(status_code=409, detail=f"'{body.path}' already exists")
                parent = os.path.dirname(abs_path)
                if not os.path.isdir(parent):
                    raise HTTPException(status_code=400, detail=f"Parent directory does not exist: {os.path.relpath(parent, workspace_root)}")
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
        def rename_file(body: FileRenameBody, request: Request):
            try:
                workspace_root, _, _ = _request_workspace(request)
                abs_src = _safe_abs(body.path, workspace_root)
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
                _safe_abs(os.path.relpath(abs_dst, workspace_root), workspace_root)
                if os.path.exists(abs_dst):
                    raise HTTPException(status_code=409, detail=f"'{new_name}' already exists in the same directory")
                os.rename(abs_src, abs_dst)
                new_rel = os.path.relpath(abs_dst, workspace_root)
                return {"status": "ok", "message": f"Renamed to '{new_name}'", "path": new_rel}
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── POST /api/file/edit ────────────────────────────────────────
        @app.post("/api/file/edit", summary="Save/overwrite a text file")
        def edit_file(body: FileEditBody, request: Request):
            try:
                workspace_root, _, _ = _request_workspace(request)
                abs_path = _safe_abs(body.path, workspace_root)
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
            request: Request,
            path: str = Query(..., description="Relative path within workspace")
        ):
            try:
                workspace_root, _, _ = _request_workspace(request)
                abs_path = _safe_abs(path, workspace_root)
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
        @app.get("/api/file/download", summary="Download a file or directory as attachment")
        def download_file(
            request: Request,
            path: str = Query(..., description="Relative path within workspace")
        ):
            try:
                workspace_root, _, _ = _request_workspace(request)
                abs_path = _safe_abs(path, workspace_root)
                if not os.path.exists(abs_path):
                    raise HTTPException(status_code=404, detail=f"Path '{path}' not found")
                if os.path.isdir(abs_path):
                    archive_base = _safe_archive_base(
                        os.path.basename(os.path.normpath(abs_path)),
                        "workspace",
                    )
                    return _archive_dir_response(
                        abs_path,
                        archive_base,
                        f"{archive_base}.tar.gz",
                    )
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

        # ── GET /api/workspace/download ────────────────────────────────
        @app.get("/api/workspace/download", summary="Download the whole workspace as {DUT}.tar.gz")
        def download_workspace(request: Request):
            try:
                workspace_root, _, is_sub_workspace = _request_workspace(request)
                dut_name = (
                    os.path.basename(os.path.normpath(workspace_root))
                    if is_sub_workspace
                    else (getattr(pdb.agent, "dut_name", "") or "workspace")
                )
                archive_base = _safe_archive_base(dut_name, "workspace")
                return _archive_dir_response(
                    workspace_root,
                    archive_base,
                    f"{archive_base}.tar.gz",
                )
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # ── POST /api/file/upload ──────────────────────────────────────
        @app.post("/api/file/upload", summary="Upload a file into the workspace")
        async def upload_file(
            request: Request,
            path: str = Query(default="", description="Target directory (relative to workspace root)"),
            file: UploadFile = File(...),
        ):
            try:
                workspace_root, _, _ = _request_workspace(request)
                target_dir = _safe_abs(path, workspace_root)
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
                    "path": _rel(dest, workspace_root),
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
        def serve_workspace_file(path: str, request: Request):
            try:
                workspace_root, _, _ = _request_workspace(request)
                abs_path = _safe_abs(path, workspace_root)
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

        # Restore original console sync handler
        from ucagent.util import log
        log.set_console_sync_handler(self._original_sync_handler)

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
