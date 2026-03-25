# -*- coding: utf-8 -*-
"""
Master API server and client for UCAgent.

This module now serves three roles:

1. Aggregate heartbeats from multiple UCAgent instances.
2. Launch and manage new UCAgent subprocess tasks.
3. Proxy task-local CMD API / Terminal API through the master port.
"""

from __future__ import annotations

import asyncio
import base64
import collections
import json
import mimetypes
import os
import pathlib
import re
import secrets
import queue
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import warnings
from typing import TYPE_CHECKING, Any, Deque, Dict, List, Optional, Tuple
from urllib.parse import urlencode

try:
    from fastapi import Body, Depends, FastAPI, Header as _Header, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.security import HTTPBasic, HTTPBasicCredentials
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover - optional dependency checked at runtime
    Body = Depends = FastAPI = HTTPException = Query = Request = Response = WebSocket = WebSocketDisconnect = None
    _Header = HTMLResponse = JSONResponse = HTTPBasic = HTTPBasicCredentials = BaseModel = Field = None

from ucagent.util.config import get_config
from ucagent.util.functions import find_available_port, get_abs_path_cwd_ucagent, is_port_free
from ucagent.util.log import echo_g, warning

if TYPE_CHECKING:
    from ucagent.verify_pdb import VerifyPDB

_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_MODULE_RE = re.compile(r"^\s*module\s+([A-Za-z_][A-Za-z0-9_$]*)\b", re.MULTILINE)
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}
_TEXT_EXTS = {
    ".txt", ".md", ".rst", ".py", ".js", ".ts", ".css", ".html", ".htm",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".sh",
    ".bash", ".zsh", ".fish", ".v", ".sv", ".svh", ".vh", ".vhd", ".vhdl",
    ".c", ".h", ".cpp", ".hpp", ".java", ".rs", ".go", ".rb", ".php",
    ".xml", ".csv", ".log", ".env", ".gitignore", ".makefile", ".mk",
    ".scala", ".lua", ".r", ".m", ".tex", ".bib", ".diff", ".patch",
}
_CATEGORY_DIRS = {
    "main_verilog": "_launch_uploads/main_verilog",
    "rtl_extra": "_launch_uploads/rtl_extra",
    "source_extra": "_launch_uploads/source_extra",
    "spec": "_launch_uploads/spec",
    "requirement": "_launch_uploads/requirement",
    "config": "_launch_uploads/config",
    "misc": "_launch_uploads/misc",
}
_LAUNCH_STATUS_FILE = ".launch_status"
_LAUNCH_STATUS_EXPIRE_SECONDS = 600
_CATEGORY_LABELS = {
    "main_verilog": "Main RTL",
    "rtl_extra": "Extra RTL",
    "source_extra": "Other Source",
    "spec": "Spec",
    "requirement": "Verification Needs",
    "config": "Config",
    "misc": "Unassigned",
}
_RTL_SOURCE_EXTS = {".v", ".sv", ".vh", ".svh", ".scala"}
_FILELIST_EXTS = {".v", ".sv", ".vh", ".svh"}
_RTL_SPECIAL_FILES = {"filelist.txt"}
_PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _local_ip() -> str:
    """Best-effort local IP (non-loopback)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _master_log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    echo_g(f"[Master {ts}] {msg}")


def _now() -> float:
    return time.time()


def _safe_name(name: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "").strip())
    return cleaned or fallback


def _tail_file(path: str, max_lines: int = 200) -> str:
    if not path or not os.path.isfile(path):
        return ""
    dq: Deque[str] = collections.deque(maxlen=max_lines)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            dq.append(line)
    return "".join(dq)


def _mask_secret(value: str) -> str:
    if value is None:
        return ""
    raw = str(value)
    if len(raw) <= 4:
        return "*" * len(raw)
    return raw[:2] + "*" * max(4, len(raw) - 4) + raw[-2:]


def _is_pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _rewrite_html(content: str, replacements: Dict[str, str]) -> str:
    for src, dst in replacements.items():
        content = content.replace(src, dst)
    return content


def _split_master_spec(spec: str) -> Tuple[str, str]:
    parts = spec.strip().split()
    if not parts:
        return "", ""
    host_port = parts[0]
    access_key = parts[1] if len(parts) > 1 else ""
    return host_port, access_key


def _parse_service_spec(spec: str, default_host: str, default_port: int) -> Tuple[str, int, str]:
    raw = (spec or "").strip()
    if not raw:
        return default_host, default_port, ""
    addr = raw
    password = ""
    if " " in raw:
        addr, password = raw.split(" ", 1)
        password = password.strip()
    addr = addr.strip()
    if not addr:
        return default_host, default_port, password
    if ":" in addr:
        host, port_str = addr.rsplit(":", 1)
        return host.strip() or default_host, int(port_str), password
    return addr, default_port, password


def _merge_launch_default_args(req: Dict[str, Any], default_args: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(default_args or {})
    merged.pop("configs", None)
    for key, value in (req or {}).items():
        merged[key] = value
    for key, value in (default_args or {}).items():
        if key == "configs":
            continue
        if key not in merged:
            merged[key] = value
            continue
        current = merged.get(key)
        if current is None:
            merged[key] = value
        elif isinstance(current, str) and not current.strip():
            merged[key] = value
        elif isinstance(current, (list, tuple)) and not current:
            merged[key] = value
    return merged


def _parse_web_terminal_spec(spec: str) -> Tuple[str, int, str]:
    return _parse_service_spec(spec, "127.0.0.1", 8818)


def _resolve_web_console_spec(spec: Any) -> Tuple[str, int, str]:
    raw = "" if spec in (None, True, "__default__", "__bare__", "__enabled__") else str(spec).strip()
    if not raw or raw == "-1":
        host = "localhost"
        port = 8000
        password = ""
    else:
        parts = raw.split(":", 2)
        if len(parts) < 2:
            raise ValueError(
                f"Invalid --web-console value '{raw}'. Expected format: host:port[:password]"
            )
        host = parts[0].strip()
        if not host:
            raise ValueError(
                f"Invalid --web-console value '{raw}'. host cannot be empty."
            )
        try:
            port = int(parts[1].strip())
        except ValueError as exc:
            raise ValueError(
                f"Invalid --web-console value '{raw}'. Port must be an integer."
            ) from exc
        password = parts[2] if len(parts) == 3 else ""
        if port == -1:
            port = find_available_port(start_port=8000, end_port=65535)
        elif port < 1 or port > 65535:
            raise ValueError(
                f"Invalid --web-console value '{raw}'. Port must be in range 1..65535."
            )
        elif not is_port_free(host, port):
            raise ValueError(f"Port {port} on host '{host}' is unavailable for --web-console.")
    if raw in {"", "-1"} and not is_port_free(host, port):
        port = find_available_port(start_port=port, end_port=65535)
    return host, port, password


def _copy_jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _merge_runtime_service_info(current: Optional[Dict[str, Any]], reported: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(current or {})
    for key, value in (reported or {}).items():
        if value in (None, ""):
            continue
        merged[key] = value
    return merged


def _is_text_file(path: str) -> bool:
    ext = pathlib.Path(path).suffix.lower()
    return ext in _TEXT_EXTS


def _category_label(category: str) -> str:
    return _CATEGORY_LABELS.get(category, _CATEGORY_LABELS["misc"])


def _parse_module_names(text: str) -> List[str]:
    seen: List[str] = []
    for name in _MODULE_RE.findall(text):
        if name not in seen:
            seen.append(name)
    return seen


def _is_rtl_workspace_file(name: str, category: str) -> bool:
    lower_name = os.path.basename(name or "").lower()
    suffix = pathlib.Path(lower_name).suffix.lower()
    if category in {"main_verilog", "rtl_extra", "source_extra"}:
        return True
    if lower_name in _RTL_SPECIAL_FILES:
        return True
    return suffix in _RTL_SOURCE_EXTS or suffix in _FILELIST_EXTS


def _default_launch_root() -> str:
    import ucagent.cli as _cli

    cli_dir = os.path.dirname(os.path.abspath(_cli.__file__))
    return os.path.abspath(os.path.join(cli_dir, os.pardir, "examples"))


class PdbMasterApiServer:
    """FastAPI-based master that aggregates agents and manages launched tasks."""

    PERIODIC_SAVE_INTERVAL: float = 20.0
    MONITOR_INTERVAL: float = 1.0
    CHILD_READY_TIMEOUT: float = 30.0
    _TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")

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
        try:
            import fastapi  # noqa: F401
            import uvicorn  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "FastAPI and uvicorn are required. Install with: pip install fastapi uvicorn"
            ) from exc

        if sock is None:
            sock = f"/tmp/ucagent_master_{port}.sock"
        elif sock == "":
            sock = None
        if not tcp and not sock:
            raise ValueError("At least one of 'tcp' or 'sock' must be enabled.")
        if not workspace:
            raise ValueError("'workspace' is required and must not be empty.")

        self.host = host
        self.port = port
        self.sock = sock
        self.tcp = tcp
        self.offline_timeout = offline_timeout
        self.workspace = os.path.abspath(workspace)
        self.access_key = access_key
        self.password = password

        self.cfg = get_config(workspace=self.workspace)

        self._db_dir = get_abs_path_cwd_ucagent(self.workspace, "master_db")
        os.makedirs(self._db_dir, exist_ok=True)
        self._db_path = os.path.join(self._db_dir, "agents.json")
        self._tasks_path = os.path.join(self._db_dir, "tasks.json")
        self._workspaces_path = os.path.join(self._db_dir, "workspaces.json")
        self._logs_dir = os.path.join(self._db_dir, "task_logs")
        os.makedirs(self._logs_dir, exist_ok=True)

        self._agents: Dict[str, Dict[str, Any]] = {}
        self._agents_lock = threading.Lock()
        self._removed: set = set()
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._tasks_lock = threading.Lock()
        self._workspaces: Dict[str, Dict[str, Any]] = {}
        self._workspaces_lock = threading.Lock()
        self._task_runtime: Dict[str, Dict[str, Any]] = {}
        self._compile_runtime: Dict[str, Dict[str, Any]] = {}
        self._compile_runtime_lock = threading.Lock()

        self._running = False
        self.started_at: Optional[float] = None
        self._tcp_server = None
        self._tcp_thread: Optional[threading.Thread] = None
        self._sock_server = None
        self._sock_thread: Optional[threading.Thread] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_stop = threading.Event()
        self._online_cache: Dict[str, bool] = {}
        self._dirty = False
        self._last_saved = 0.0

        self._launch_roots = self._resolve_launch_roots()

        self._load_db()
        self._app = self._build_app()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _resolve_launch_roots(self) -> List[Dict[str, str]]:
        configured = self.cfg.get_value("launch.file_browser_roots", None)
        raw_roots = configured if isinstance(configured, list) else []
        if not raw_roots:
            raw_roots = [_default_launch_root()]
        resolved: List[Dict[str, str]] = []
        seen = set()
        for idx, item in enumerate(raw_roots):
            if isinstance(item, dict):
                path = os.path.abspath(str(item.get("path", "")).strip())
                name = str(item.get("name", "")).strip() or os.path.basename(path) or f"root-{idx + 1}"
            else:
                path = os.path.abspath(str(item).strip())
                name = os.path.basename(path) or f"root-{idx + 1}"
            if not path or path in seen or not os.path.isdir(path):
                continue
            seen.add(path)
            resolved.append({"id": f"root-{idx + 1}", "name": name, "path": path})
        if not resolved:
            default_path = _default_launch_root()
            os.makedirs(default_path, exist_ok=True)
            resolved.append({"id": "root-1", "name": os.path.basename(default_path) or "examples", "path": default_path})
        return resolved

    def _load_json_file(self, path: str, default: Any) -> Any:
        if not os.path.exists(path):
            return default
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:
            _master_log(f"Warning: failed to load '{path}': {exc}")
            return default

    def _load_db(self) -> None:
        agents_data = self._load_json_file(self._db_path, {"agents": {}, "removed": []})
        with self._agents_lock:
            self._agents.update(agents_data.get("agents", {}))
        self._removed.update(agents_data.get("removed", []))

        tasks_data = self._load_json_file(self._tasks_path, {"tasks": {}})
        with self._tasks_lock:
            self._tasks.update(tasks_data.get("tasks", {}))
        workspaces_data = self._load_json_file(self._workspaces_path, {"workspaces": {}})
        with self._workspaces_lock:
            self._workspaces.update(workspaces_data.get("workspaces", {}))

        if self._agents or self._tasks or self._workspaces:
            _master_log(
                f"Loaded {len(self._agents)} agent(s), {len(self._tasks)} task(s), "
                f"{len(self._workspaces)} workspace(s) from '{self._db_dir}'"
            )

    def _save_db(self) -> None:
        try:
            with self._agents_lock:
                agents_snapshot = {k: dict(v) for k, v in self._agents.items()}
            with self._tasks_lock:
                tasks_snapshot = {k: dict(v) for k, v in self._tasks.items()}
            with self._workspaces_lock:
                ws_snapshot = {k: dict(v) for k, v in self._workspaces.items()}

            payloads = [
                (self._db_path, {"agents": agents_snapshot, "removed": list(self._removed)}),
                (self._tasks_path, {"tasks": tasks_snapshot}),
                (self._workspaces_path, {"workspaces": ws_snapshot}),
            ]
            for path, data in payloads:
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, ensure_ascii=False, indent=2)
                os.replace(tmp, path)
            self._dirty = False
            self._last_saved = _now()
        except Exception as exc:
            _master_log(f"Warning: failed to save persistent DB: {exc}")

    def _mark_dirty(self) -> None:
        self._dirty = True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _agent_status(self, agent: Dict[str, Any]) -> str:
        return "online" if _now() - agent["last_seen"] <= self.offline_timeout else "offline"

    def _get_launch_root(self, root_id: str) -> Dict[str, str]:
        for root in self._launch_roots:
            if root["id"] == root_id:
                return root
        raise KeyError(f"Launch root '{root_id}' not found")

    def _safe_under_root(self, root_path: str, rel_path: str) -> str:
        root = os.path.abspath(root_path)
        clean = (rel_path or "").strip().lstrip("/")
        candidate = os.path.abspath(os.path.join(root, clean))
        if not (candidate == root or candidate.startswith(root + os.sep)):
            raise ValueError("Path traversal is not allowed")
        return candidate

    def _snapshot_agents(self) -> List[Dict[str, Any]]:
        with self._agents_lock:
            return [dict(v) for v in self._agents.values()]

    def _get_workspace(self, workspace_id: str) -> Dict[str, Any]:
        with self._workspaces_lock:
            ws = self._workspaces.get(workspace_id)
            if ws is None:
                raise KeyError(f"Workspace '{workspace_id}' not found")
            if self._normalize_workspace_locked(ws):
                self._mark_dirty()
            return ws

    def _get_task(self, task_id: str) -> Dict[str, Any]:
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(f"Task '{task_id}' not found")
            return task

    def _workspace_item_target(self, category: str, filename: str) -> str:
        subdir = _CATEGORY_DIRS.get(category, _CATEGORY_DIRS["misc"])
        return os.path.join(subdir, filename)

    def _normalize_workspace_locked(self, ws: Dict[str, Any]) -> bool:
        changed = False
        files = ws.setdefault("files", [])
        root = ws.get("workspace_dir", "")
        if "compile" not in ws:
            ws["compile"] = {}
            changed = True
        if "picker_workspace" not in ws and root:
            ws["picker_workspace"] = os.path.join(root, "workspace")
            changed = True
        for item in files:
            stored_path = item.get("stored_path", "")
            if not item.get("item_id"):
                item["item_id"] = secrets.token_hex(8)
                changed = True
            if item.get("category") not in _CATEGORY_DIRS:
                item["category"] = "misc"
                changed = True
            if not item.get("source"):
                item["source"] = "upload"
                changed = True
            if not item.get("original_name"):
                item["original_name"] = os.path.basename(stored_path) or "file"
                changed = True
            if root:
                relpath = os.path.relpath(stored_path, root) if stored_path else ""
                relpath = "" if relpath == "." else relpath
                if item.get("stored_relpath") != relpath:
                    item["stored_relpath"] = relpath
                    changed = True
            if not item.get("created_at"):
                try:
                    item["created_at"] = os.path.getmtime(stored_path) if stored_path and os.path.exists(stored_path) else _now()
                except Exception:
                    item["created_at"] = _now()
                changed = True
        return changed

    def _clear_workspace_compile_locked(self, ws: Dict[str, Any]) -> None:
        ws["compile"] = {}

    def _workspace_compile_public(self, ws: Dict[str, Any]) -> Dict[str, Any]:
        compile_info = dict(ws.get("compile") or {})
        if not compile_info:
            return {}
        return {
            "status": compile_info.get("status", ""),
            "dut_name": compile_info.get("dut_name", ""),
            "selected_module": compile_info.get("selected_module", ""),
            "main_verilog_path": compile_info.get("main_verilog_path", ""),
            "compiled_main_verilog_path": compile_info.get("compiled_main_verilog_path", ""),
            "rtl_dir": compile_info.get("rtl_dir", ""),
            "doc_dir": compile_info.get("doc_dir", ""),
            "dut_dir": compile_info.get("dut_dir", ""),
            "filelist_path": compile_info.get("filelist_path", ""),
            "generated_filelist": bool(compile_info.get("generated_filelist")),
            "config_path": compile_info.get("config_path", ""),
            "readme_path": compile_info.get("readme_path", ""),
            "compiled_at": compile_info.get("compiled_at", 0),
            "copied_files": list(compile_info.get("copied_files") or []),
            "picker_command": list(compile_info.get("picker_command") or []),
            "picker_exit_code": compile_info.get("picker_exit_code"),
            "picker_stdout": compile_info.get("picker_stdout", ""),
            "picker_stderr": compile_info.get("picker_stderr", ""),
        }

    def _find_workspace_item_by_id(self, ws: Dict[str, Any], item_id: str) -> Optional[Dict[str, Any]]:
        for item in ws.get("files", []):
            if item.get("item_id") == item_id:
                return item
        return None

    def _workspace_file_public(self, ws: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
        stored_path = item.get("stored_path", "")
        name = item.get("original_name") or os.path.basename(stored_path) or "file"
        suffix = pathlib.Path(name).suffix.lower()
        exists = bool(stored_path and os.path.isfile(stored_path))
        size = os.path.getsize(stored_path) if exists else 0
        return {
            "item_id": item.get("item_id", ""),
            "name": name,
            "original_name": name,
            "category": item.get("category", "misc"),
            "tag_label": _category_label(item.get("category", "misc")),
            "source": item.get("source", ""),
            "source_path": item.get("source_path", ""),
            "stored_path": stored_path,
            "stored_relpath": item.get("stored_relpath", ""),
            "created_at": item.get("created_at", 0),
            "size": size,
            "exists": exists,
            "file_type": suffix or "file",
            "is_text": _is_text_file(stored_path) if exists else False,
        }

    def _workspace_public(self, ws: Dict[str, Any]) -> Dict[str, Any]:
        files = [self._workspace_file_public(ws, item) for item in ws.get("files", [])]
        files.sort(key=lambda item: (item.get("created_at", 0), item.get("name", "")), reverse=True)
        return {
            "workspace_id": ws.get("workspace_id", ""),
            "workspace_dir": ws.get("workspace_dir", ""),
            "base_root": ws.get("base_root", ""),
            "created_at": ws.get("created_at", 0),
            "task_id": ws.get("task_id", ""),
            "files": files,
            "compile": self._workspace_compile_public(ws),
        }

    def _update_workspace_item_category(self, workspace_id: str, item_id: str, category: str) -> Dict[str, Any]:
        if category not in _CATEGORY_DIRS:
            raise ValueError(f"Unsupported category '{category}'")
        with self._workspaces_lock:
            ws = self._workspaces.get(workspace_id)
            if ws is None:
                raise KeyError(f"Workspace '{workspace_id}' not found")
            self._normalize_workspace_locked(ws)
            item = self._find_workspace_item_by_id(ws, item_id)
            if item is None:
                raise KeyError(f"Workspace file '{item_id}' not found")
            if category == "main_verilog":
                suffix = pathlib.Path(item.get("stored_path", "")).suffix.lower()
                if suffix not in _FILELIST_EXTS:
                    raise ValueError("Main RTL must be a Verilog/SystemVerilog file")
                for existing in ws.get("files", []):
                    if existing is not item and existing.get("category") == "main_verilog":
                        existing["category"] = "rtl_extra"
            if category == "requirement":
                for existing in ws.get("files", []):
                    if existing is not item and existing.get("category") == "requirement":
                        existing["category"] = "spec"
            item["category"] = category
            self._clear_workspace_compile_locked(ws)
        self._mark_dirty()
        return self._workspace_public(self._get_workspace(workspace_id))

    def _create_workspace(self, base_root: str = "/tmp") -> Dict[str, Any]:
        base_root = os.path.abspath(base_root or "/tmp")
        os.makedirs(base_root, exist_ok=True)
        ws_dir = tempfile.mkdtemp(prefix="ucagent_launch_", dir=base_root)
        workspace_id = secrets.token_hex(8)
        picker_workspace = os.path.join(ws_dir, "workspace")
        os.makedirs(picker_workspace, exist_ok=True)
        self._write_launch_status(ws_dir, "created")
        ws = {
            "workspace_id": workspace_id,
            "workspace_dir": ws_dir,
            "picker_workspace": picker_workspace,
            "base_root": base_root,
            "created_at": _now(),
            "files": [],
            "task_id": "",
            "compile": {},
        }
        with self._workspaces_lock:
            self._workspaces[workspace_id] = ws
        self._mark_dirty()
        return ws

    def _write_launch_status(self, ws_dir: str, status: str) -> None:
        status_file = os.path.join(ws_dir, _LAUNCH_STATUS_FILE)
        status_data = {
            "status": status,
            "updated_at": _now(),
        }
        try:
            with open(status_file, "w", encoding="utf-8") as fh:
                json.dump(status_data, fh)
        except Exception:
            pass

    def _read_launch_status(self, ws_dir: str) -> Dict[str, Any]:
        status_file = os.path.join(ws_dir, _LAUNCH_STATUS_FILE)
        try:
            with open(status_file, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {"status": "unknown", "updated_at": 0}

    def _cleanup_stale_workspaces(self, base_root: str = "/tmp") -> int:
        base_root = os.path.abspath(base_root or "/tmp")
        if not os.path.isdir(base_root):
            return 0
        cleaned = 0
        now = _now()
        for entry in os.listdir(base_root):
            if not entry.startswith("ucagent_launch_"):
                continue
            ws_dir = os.path.join(base_root, entry)
            if not os.path.isdir(ws_dir):
                continue
            status = self._read_launch_status(ws_dir)
            status_val = status.get("status", "unknown")
            updated_at = status.get("updated_at", 0)
            if status_val == "launched":
                continue
            if now - updated_at > _LAUNCH_STATUS_EXPIRE_SECONDS:
                try:
                    shutil.rmtree(ws_dir)
                    cleaned += 1
                except Exception:
                    pass
        return cleaned

    def _record_workspace_file(
        self,
        workspace_id: str,
        *,
        category: str,
        source: str,
        src_path: str,
        stored_path: str,
        original_name: str,
    ) -> Dict[str, Any]:
        item = {
            "item_id": secrets.token_hex(8),
            "category": category,
            "source": source,
            "source_path": src_path,
            "stored_path": stored_path,
            "stored_relpath": os.path.relpath(stored_path, self._get_workspace(workspace_id)["workspace_dir"]),
            "original_name": original_name,
            "created_at": _now(),
        }
        with self._workspaces_lock:
            ws = self._workspaces.get(workspace_id)
            if ws is None:
                raise KeyError(f"Workspace '{workspace_id}' not found")
            ws.setdefault("files", []).append(item)
            self._clear_workspace_compile_locked(ws)
        self._mark_dirty()
        return item

    def _find_workspace_item(self, ws: Dict[str, Any], stored_path: str) -> Optional[Dict[str, Any]]:
        wanted = os.path.abspath(stored_path)
        for item in ws.get("files", []):
            if os.path.abspath(item.get("stored_path", "")) == wanted:
                return item
        return None

    def _store_file_bytes(self, workspace_id: str, category: str, filename: str, data: bytes, source: str, src_path: str) -> Dict[str, Any]:
        ws = self._get_workspace(workspace_id)
        safe_name = _safe_name(filename, "file")
        rel_target = self._workspace_item_target(category, safe_name)
        abs_target = self._safe_under_root(ws["workspace_dir"], rel_target)
        os.makedirs(os.path.dirname(abs_target), exist_ok=True)
        with open(abs_target, "wb") as fh:
            fh.write(data)
        return self._record_workspace_file(
            workspace_id,
            category=category,
            source=source,
            src_path=src_path,
            stored_path=abs_target,
            original_name=filename,
        )

    def _store_existing_file(self, workspace_id: str, category: str, source_path: str) -> Dict[str, Any]:
        with open(source_path, "rb") as fh:
            data = fh.read()
        return self._store_file_bytes(
            workspace_id,
            category,
            os.path.basename(source_path),
            data,
            source="server",
            src_path=source_path,
        )

    def _list_workspace_tree(self, workspace_id: str) -> List[Dict[str, Any]]:
        ws = self._get_workspace(workspace_id)
        root = ws["workspace_dir"]
        entries: List[Dict[str, Any]] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            filenames.sort()
            rel_dir = os.path.relpath(dirpath, root)
            rel_dir = "" if rel_dir == "." else rel_dir
            for d in dirnames:
                abs_path = os.path.join(dirpath, d)
                entries.append({
                    "path": os.path.join(rel_dir, d).lstrip("./"),
                    "type": "dir",
                    "size": 0,
                    "mtime": os.path.getmtime(abs_path),
                })
            for fn in filenames:
                abs_path = os.path.join(dirpath, fn)
                entries.append({
                    "path": os.path.join(rel_dir, fn).lstrip("./"),
                    "type": "file",
                    "size": os.path.getsize(abs_path),
                    "mtime": os.path.getmtime(abs_path),
                    "text": _is_text_file(abs_path),
                })
        return entries

    def _select_main_item(self, ws: Dict[str, Any], main_verilog_path: str = "") -> Dict[str, Any]:
        if main_verilog_path:
            item = self._find_workspace_item(ws, main_verilog_path)
            if item is None:
                raise ValueError("Main Verilog file not found in workspace")
            return item
        for item in reversed(ws.get("files", [])):
            if item.get("category") == "main_verilog":
                return item
        raise ValueError("No main Verilog file found in workspace")

    def _select_workspace_item_by_category(self, ws: Dict[str, Any], category: str) -> Optional[Dict[str, Any]]:
        for item in reversed(ws.get("files", [])):
            if item.get("category") == category:
                return item
        return None

    def _reset_compiled_workspace_dirs(self, picker_workspace: str, dut: str) -> Tuple[str, str, str]:
        rtl_dir = os.path.join(picker_workspace, f"{dut}_RTL")
        doc_dir = os.path.join(picker_workspace, f"{dut}_Doc")
        dut_dir = os.path.join(picker_workspace, dut)
        for path in (rtl_dir, doc_dir, dut_dir):
            if os.path.exists(path):
                shutil.rmtree(path)
        os.makedirs(rtl_dir, exist_ok=True)
        os.makedirs(doc_dir, exist_ok=True)
        return rtl_dir, doc_dir, dut_dir

    def _prepare_workspace_layout(
        self,
        workspace_id: str,
        *,
        effective_dut: str,
        main_verilog_path: str = "",
    ) -> Dict[str, Any]:
        ws = self._get_workspace(workspace_id)
        root = ws["workspace_dir"]
        picker_workspace = ws.get("picker_workspace") or os.path.join(root, "workspace")
        dut = _safe_name(effective_dut, "DUT")
        rtl_dir, doc_dir, dut_dir = self._reset_compiled_workspace_dirs(picker_workspace, dut)

        main_item = self._select_main_item(ws, main_verilog_path)
        copied: List[str] = []
        main_target = ""
        filelist_path = ""
        rtl_sources: List[str] = []
        config_path = ""
        for item in ws.get("files", []):
            src = item["stored_path"]
            cat = item.get("category", "misc")
            filename = os.path.basename(src)
            if _is_rtl_workspace_file(filename, cat):
                target_dir = rtl_dir
            else:
                target_dir = doc_dir
            os.makedirs(target_dir, exist_ok=True)
            target = os.path.join(target_dir, filename)
            if os.path.abspath(src) != os.path.abspath(target):
                shutil.copy2(src, target)
            copied.append(target)
            if target_dir == rtl_dir and pathlib.Path(target).suffix.lower() in _FILELIST_EXTS:
                rtl_sources.append(target)
            if os.path.abspath(src) == os.path.abspath(main_item["stored_path"]):
                main_target = target
            if filename.lower() == "filelist.txt":
                filelist_path = target
            if cat == "config" and not config_path:
                config_path = os.path.relpath(target, root)

        if not main_target:
            raise ValueError("Failed to locate copied main Verilog file")
        generated_filelist = False
        if not filelist_path:
            deps = [path for path in rtl_sources if os.path.abspath(path) != os.path.abspath(main_target)]
            if deps:
                filelist_path = os.path.join(rtl_dir, "filelist.txt")
                with open(filelist_path, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(sorted(os.path.abspath(path) for path in deps)) + "\n")
                copied.append(filelist_path)
                generated_filelist = True
        return {
            "workspace_dir": root,
            "picker_workspace": picker_workspace,
            "dut_name": dut,
            "rtl_dir": rtl_dir,
            "dut_dir": dut_dir,
            "doc_dir": doc_dir,
            "source_main_verilog_path": main_item["stored_path"],
            "main_verilog_path": main_target,
            "filelist_path": filelist_path,
            "generated_filelist": generated_filelist,
            "copied_files": copied,
            "config_path": config_path,
        }

    def _copy_requirement_readme(self, ws: Dict[str, Any], dut_dir: str) -> str:
        requirement = self._select_workspace_item_by_category(ws, "requirement")
        if requirement is None:
            return ""
        src = requirement.get("stored_path", "")
        if not src or not os.path.isfile(src):
            return ""
        os.makedirs(dut_dir, exist_ok=True)
        readme_path = os.path.join(dut_dir, "README.md")
        shutil.copy2(src, readme_path)
        return readme_path

    def _compile_workspace_dut(
        self,
        workspace_id: str,
        *,
        effective_dut: str,
        selected_module: str,
        main_verilog_path: str = "",
    ) -> Dict[str, Any]:
        ws = self._get_workspace(workspace_id)
        prepared = self._prepare_workspace_layout(
            workspace_id,
            effective_dut=effective_dut,
            main_verilog_path=main_verilog_path,
        )
        picker = self._run_picker(
            workspace_dir=prepared["workspace_dir"],
            picker_workspace=prepared["picker_workspace"],
            dut_name=prepared["dut_name"],
            selected_module=selected_module,
            main_verilog_path=prepared["main_verilog_path"],
            filelist_path=prepared["filelist_path"],
        )
        readme_path = ""
        if picker["success"]:
            readme_path = self._copy_requirement_readme(ws, prepared["dut_dir"])
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
            "generated_filelist": prepared["generated_filelist"],
            "config_path": prepared.get("config_path", ""),
            "readme_path": readme_path,
            "compiled_at": _now(),
            "copied_files": prepared["copied_files"],
            "picker_command": picker["command"],
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
        return {"prepared": prepared, "picker": picker, "compile": compile_info}

    def _run_picker(
        self,
        *,
        workspace_dir: str,
        picker_workspace: str,
        dut_name: str,
        selected_module: str,
        main_verilog_path: str,
        filelist_path: str = "",
    ) -> Dict[str, Any]:
        cmd = self._build_picker_command(
            workspace_dir=workspace_dir,
            picker_workspace=picker_workspace,
            dut_name=dut_name,
            selected_module=selected_module,
            main_verilog_path=main_verilog_path,
            filelist_path=filelist_path,
        )
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=workspace_dir)
        already_exists = self._picker_create_conflict(picker_workspace, dut_name, result.stdout + result.stderr)
        if already_exists:
            shutil.rmtree(os.path.join(picker_workspace, dut_name), ignore_errors=True)
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=workspace_dir)
        return {
            "command": cmd,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "success": result.returncode == 0,
        }

    def _build_picker_command(
        self,
        *,
        workspace_dir: str,
        picker_workspace: str,
        dut_name: str,
        selected_module: str,
        main_verilog_path: str,
        filelist_path: str = "",
    ) -> List[str]:
        fst_path = os.path.join(picker_workspace, dut_name, f"{dut_name}.fst")
        cmd = [
            "picker",
            "export",
            main_verilog_path,
            "--rw",
            "1",
            "--sname",
            selected_module,
            "--tdir",
            os.path.join(picker_workspace, ""),
            "-c",
            "-w",
            fst_path,
        ]
        if filelist_path and os.path.isfile(filelist_path):
            cmd.extend(["--fs", filelist_path])
        return cmd

    def _picker_create_conflict(self, picker_workspace: str, dut_name: str, output: str) -> bool:
        return f"Create: {os.path.join(picker_workspace, dut_name)} fail" in (output or "")

    def _append_compile_log(self, workspace_id: str, text: str, stream: str = "") -> None:
        with self._compile_runtime_lock:
            runtime = self._compile_runtime.get(workspace_id)
            if runtime is None:
                return
            runtime["log"] = runtime.get("log", "") + str(text or "")
            runtime["cursor"] = len(runtime["log"])
            runtime["last_stream"] = stream

    def _compile_runtime_public(self, workspace_id: str, cursor: int = 0) -> Dict[str, Any]:
        with self._compile_runtime_lock:
            runtime = dict(self._compile_runtime.get(workspace_id) or {})
        log = str(runtime.get("log") or "")
        safe_cursor = max(0, min(int(cursor or 0), len(log)))
        return {
            "status": runtime.get("status", ""),
            "cursor": len(log),
            "chunk": log[safe_cursor:],
            "started_at": runtime.get("started_at", 0),
            "finished_at": runtime.get("finished_at", 0),
            "error": runtime.get("error", ""),
            "workspace": runtime.get("workspace"),
            "compile": runtime.get("compile"),
            "result": runtime.get("result"),
        }

    def _run_compile_job(self, workspace_id: str, effective_dut: str, selected_module: str, main_verilog_path: str) -> None:
        prepared: Dict[str, Any] = {}
        picker: Dict[str, Any] = {"command": [], "exit_code": None, "stdout": "", "stderr": "", "success": False}
        try:
            prepared = self._prepare_workspace_layout(
                workspace_id,
                effective_dut=effective_dut,
                main_verilog_path=main_verilog_path,
            )
            self._append_compile_log(
                workspace_id,
                f"Prepared workspace layout:\n  RTL: {prepared['rtl_dir']}\n  DOC: {prepared['doc_dir']}\n  DUT: {prepared['dut_dir']}\n",
                "info",
            )

            def _run_once() -> Dict[str, Any]:
                cmd = self._build_picker_command(
                    workspace_dir=prepared["workspace_dir"],
                    picker_workspace=prepared["picker_workspace"],
                    dut_name=prepared["dut_name"],
                    selected_module=selected_module,
                    main_verilog_path=prepared["main_verilog_path"],
                    filelist_path=prepared["filelist_path"],
                )
                proc = subprocess.Popen(
                    cmd,
                    cwd=prepared["workspace_dir"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
                out_parts: List[str] = []
                err_parts: List[str] = []
                events: "queue.Queue[Tuple[str, Optional[str]]]" = queue.Queue()

                def _pump(pipe, stream_name: str):
                    try:
                        for line in iter(pipe.readline, ""):
                            events.put((stream_name, line))
                    finally:
                        try:
                            pipe.close()
                        except Exception:
                            pass
                        events.put((stream_name, None))

                threads = [
                    threading.Thread(target=_pump, args=(proc.stdout, "stdout"), daemon=True),
                    threading.Thread(target=_pump, args=(proc.stderr, "stderr"), daemon=True),
                ]
                for thread in threads:
                    thread.start()

                closed = 0
                while closed < 2 or proc.poll() is None:
                    try:
                        stream_name, chunk = events.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if chunk is None:
                        closed += 1
                        continue
                    if stream_name == "stdout":
                        out_parts.append(chunk)
                    else:
                        err_parts.append(chunk)
                    self._append_compile_log(workspace_id, chunk, stream_name)
                proc.wait()
                return {
                    "command": cmd,
                    "exit_code": proc.returncode,
                    "stdout": "".join(out_parts),
                    "stderr": "".join(err_parts),
                    "success": proc.returncode == 0,
                }

            picker = _run_once()
            if self._picker_create_conflict(prepared["picker_workspace"], prepared["dut_name"], picker["stdout"] + picker["stderr"]):
                self._append_compile_log(
                    workspace_id,
                    f"Detected existing package directory, cleaning {os.path.join(prepared['picker_workspace'], prepared['dut_name'])} and retrying...\n",
                    "info",
                )
                shutil.rmtree(os.path.join(prepared["picker_workspace"], prepared["dut_name"]), ignore_errors=True)
                picker = _run_once()

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
                "generated_filelist": prepared["generated_filelist"],
                "config_path": prepared.get("config_path", ""),
                "readme_path": readme_path,
                "compiled_at": _now(),
                "copied_files": prepared["copied_files"],
                "picker_command": picker["command"],
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
            ws_public = self._workspace_public(self._get_workspace(workspace_id))
            with self._compile_runtime_lock:
                runtime = self._compile_runtime.get(workspace_id)
                if runtime is not None:
                    runtime["status"] = "success" if picker["success"] else "failed"
                    runtime["finished_at"] = _now()
                    runtime["workspace"] = ws_public
                    runtime["compile"] = self._workspace_compile_public(self._get_workspace(workspace_id))
                    runtime["result"] = picker
        except Exception as exc:
            self._append_compile_log(workspace_id, f"{exc}\n", "stderr")
            with self._compile_runtime_lock:
                runtime = self._compile_runtime.get(workspace_id)
                if runtime is not None:
                    runtime["status"] = "failed"
                    runtime["finished_at"] = _now()
                    runtime["error"] = str(exc)

    def _start_compile_job(self, workspace_id: str, effective_dut: str, selected_module: str, main_verilog_path: str) -> Dict[str, Any]:
        with self._compile_runtime_lock:
            existing = self._compile_runtime.get(workspace_id)
            if existing and existing.get("status") == "running":
                return dict(existing)
            runtime = {
                "status": "running",
                "started_at": _now(),
                "finished_at": 0,
                "log": "",
                "cursor": 0,
                "error": "",
                "workspace": None,
                "compile": None,
                "result": None,
            }
            self._compile_runtime[workspace_id] = runtime
        thread = threading.Thread(
            target=self._run_compile_job,
            args=(workspace_id, effective_dut, selected_module, main_verilog_path),
            daemon=True,
            name=f"compile-{workspace_id}",
        )
        thread.start()
        return dict(runtime)

    def _stream_picker_run(
        self,
        *,
        workspace_dir: str,
        picker_workspace: str,
        dut_name: str,
        selected_module: str,
        main_verilog_path: str,
        filelist_path: str = "",
    ):
        cmd = self._build_picker_command(
            workspace_dir=workspace_dir,
            picker_workspace=picker_workspace,
            dut_name=dut_name,
            selected_module=selected_module,
            main_verilog_path=main_verilog_path,
            filelist_path=filelist_path,
        )
        proc = subprocess.Popen(
            cmd,
            cwd=workspace_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        out_parts: List[str] = []
        err_parts: List[str] = []
        events: "queue.Queue[Tuple[str, Optional[str]]]" = queue.Queue()

        def _pump(pipe, stream_name: str):
            try:
                for line in iter(pipe.readline, ""):
                    events.put((stream_name, line))
            finally:
                try:
                    pipe.close()
                except Exception:
                    pass
                events.put((stream_name, None))

        threads = [
            threading.Thread(target=_pump, args=(proc.stdout, "stdout"), daemon=True),
            threading.Thread(target=_pump, args=(proc.stderr, "stderr"), daemon=True),
        ]
        for thread in threads:
            thread.start()

        closed = 0
        while closed < 2 or proc.poll() is None:
            try:
                stream_name, chunk = events.get(timeout=0.1)
            except queue.Empty:
                continue
            if chunk is None:
                closed += 1
                continue
            if stream_name == "stdout":
                out_parts.append(chunk)
            else:
                err_parts.append(chunk)
            yield {"type": "log", "stream": stream_name, "text": chunk}
        proc.wait()
        return {
            "command": cmd,
            "exit_code": proc.returncode,
            "stdout": "".join(out_parts),
            "stderr": "".join(err_parts),
            "success": proc.returncode == 0,
        }

    def _create_task_record(self, data: Dict[str, Any]) -> Dict[str, Any]:
        task_id = secrets.token_hex(8)
        stdout_log = os.path.join(self._logs_dir, f"{task_id}.stdout.log")
        stderr_log = os.path.join(self._logs_dir, f"{task_id}.stderr.log")
        task = {
            "task_id": task_id,
            "task_name": data.get("task_name", "") or task_id,
            "client_id": data.get("client_id", ""),
            "workspace_id": data.get("workspace_id", ""),
            "workspace_dir": data.get("workspace_dir", ""),
            "dut_name": data.get("dut_name", ""),
            "selected_module": data.get("selected_module", ""),
            "main_verilog_path": data.get("main_verilog_path", ""),
            "env": data.get("env", {}),
            "cli_args_structured": data.get("cli_args_structured", {}),
            "cli_args_extra": data.get("cli_args_extra", []),
            "resolved_command": data.get("resolved_command", []),
            "pid": None,
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
            "process_status": "pending",
            "exit_code": None,
            "registered_to_master": False,
            "registered_agent_id": "",
            "picker_status": "not_started",
            "picker_command": [],
            "picker_exit_code": None,
            "picker_stdout": "",
            "picker_stderr": "",
            "stdout_log_path": stdout_log,
            "stderr_log_path": stderr_log,
            "cmd_api": data.get("cmd_api", {}),
            "terminal_api": data.get("terminal_api", {}),
            "web_console": data.get("web_console", {}),
        }
        pathlib.Path(stdout_log).touch()
        pathlib.Path(stderr_log).touch()
        with self._tasks_lock:
            self._tasks[task_id] = task
        if task["workspace_id"]:
            with self._workspaces_lock:
                ws = self._workspaces.get(task["workspace_id"])
                if ws is not None:
                    ws["task_id"] = task_id
        self._mark_dirty()
        return task

    def _build_ucagent_command(self, req: Dict[str, Any], prepared: Dict[str, Any], cmd_api: Dict[str, Any]) -> Tuple[List[str], Dict[str, str]]:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        cli_path = os.path.normpath(os.path.join(current_dir, "..", "cli.py"))
        picker_workspace = prepared.get("picker_workspace") or prepared["workspace_dir"]
        argv = [sys.executable, cli_path, picker_workspace, prepared["dut_name"]]

        def add_flag(flag: str, enabled: Any) -> None:
            if enabled:
                argv.append(flag)

        def add_value(flag: str, value: Any) -> None:
            if value is None:
                return
            if isinstance(value, str) and not value.strip():
                return
            argv.extend([flag, str(value)])

        def add_list(flag: str, values: List[Any]) -> None:
            for value in values or []:
                add_value(flag, value)

        add_value("--config", req.get("config"))
        add_value("--template-dir", req.get("template_dir"))
        add_flag("--template-overwrite", req.get("template_overwrite"))
        add_list("--template-cfg-override", req.get("template_cfg_override", []))
        add_value("--output", req.get("output") or "unity_test")

        override = req.get("override") or {}
        if override:
            override_str = ",".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in override.items())
            add_value("--override", override_str)

        add_flag("--stream-output", req.get("stream_output"))
        add_flag("--human", req.get("human"))
        add_value("--interaction-mode", req.get("interaction_mode") or "standard")
        add_flag("--force-todo", req.get("force_todo"))
        add_flag("--use-todo-tools", req.get("use_todo_tools"))
        add_flag("--emulate-config", req.get("emulate_config"))
        if req.get("use_skill") not in (None, False, ""):
            if req.get("use_skill") is True:
                argv.append("--use-skill")
            else:
                add_value("--use-skill", req.get("use_skill"))
        add_value("--seed", req.get("seed"))
        add_flag("--tui", req.get("tui"))
        web_console = req.get("web_console")
        if web_console in (True, "__default__", "__bare__", "__enabled__"):
            argv.append("--web-console")
        else:
            add_value("--web-console", web_console)
        web_terminal = req.get("web_terminal")
        if web_terminal in (True, "__default__", "__bare__", "__enabled__"):
            argv.append("--web-terminal")
        else:
            add_value("--web-terminal", web_terminal)
        add_value("--sys-tips", req.get("sys_tips"))
        add_list("--ex-tools", req.get("ex_tools", []))
        if req.get("no_embed_tools") is not None:
            if req.get("no_embed_tools") is True:
                argv.append("--no-embed-tools")
            else:
                add_value("--no-embed-tools", "false")
        add_flag("--loop", req.get("loop"))
        add_value("--loop-msg", req.get("loop_msg"))
        add_flag("--log", req.get("log"))
        add_value("--log-file", req.get("log_file"))
        add_value("--msg-file", req.get("msg_file"))
        add_flag("--mcp-server", req.get("mcp_server"))
        add_flag("--mcp-server-no-file-tools", req.get("mcp_server_no_file_tools"))
        add_value("--mcp-server-host", req.get("mcp_server_host"))
        if req.get("mcp_server_port") is not None:
            add_value("--mcp-server-port", req.get("mcp_server_port"))
        if req.get("force_stage_index") is not None:
            add_value("--force-stage-index", req.get("force_stage_index"))
        if req.get("no_write"):
            argv.append("--no-write")
            argv.extend([str(v) for v in req.get("no_write", [])])
        add_value("--gen-instruct-file", req.get("gen_instruct_file"))
        add_value("--backend", req.get("backend"))
        add_list("--append-py-path", req.get("append_py_path", []))
        add_list("--ref", req.get("ref", []))
        add_list("--skip", req.get("skip", []))
        add_list("--unskip", req.get("unskip", []))
        add_list("--icmd", req.get("icmd", []))
        add_flag("--no-history", req.get("no_history"))
        add_flag("--enable-context-manage-tools", req.get("enable_context_manage_tools"))
        add_flag("--exit-on-completion", req.get("exit_on_completion"))
        add_value("--client-id", req.get("client_id"))

        master_spec = (req.get("master") or "").strip()
        if not master_spec:
            if not self.tcp:
                raise ValueError("Current master has no TCP listener; cannot auto-connect launched task")
            host_port = f"127.0.0.1:{self.port}"
            if self.access_key:
                master_spec = f"{host_port} {self.access_key}"
            else:
                master_spec = host_port
        host_port, key = _split_master_spec(master_spec)
        if host_port:
            argv.extend(["--master", host_port])
            if key:
                argv.append(key)

        export_cmd_spec = req.get("export_cmd_api")
        if not export_cmd_spec:
            export_cmd_spec = f"{cmd_api['host']}:{cmd_api['port']} {cmd_api['password']}"
        add_value("--export-cmd-api", export_cmd_spec)

        argv.extend([str(v) for v in req.get("extra_args", []) if str(v).strip()])

        env = os.environ.copy()
        env_updates = req.get("env") or {}
        env_updates = {
            **self._launch_default_env_updates(env_updates),
            **{str(k): str(v) for k, v in env_updates.items() if str(v).strip()},
        }
        sorted_env = self._sort_env_by_dependencies(env_updates)
        env.update({str(k): str(v) for k, v in sorted_env.items()})
        return argv, env

    def _sort_env_by_dependencies(self, env_updates: Dict[str, Any]) -> Dict[str, Any]:
        import re
        env_updates = {str(k): str(v) for k, v in env_updates.items()}
        var_pattern = re.compile(r'\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?')
        dependencies = {}
        for key, value in env_updates.items():
            deps = set()
            for match in var_pattern.finditer(value):
                dep_var = match.group(1)
                if dep_var in env_updates:
                    deps.add(dep_var)
            dependencies[key] = deps
        sorted_keys = []
        visited = set()
        temp_visited = set()
        def visit(key):
            if key in temp_visited:
                return
            if key in visited:
                return
            temp_visited.add(key)
            for dep in dependencies.get(key, set()):
                visit(dep)
            temp_visited.remove(key)
            visited.add(key)
            sorted_keys.append(key)
        for key in env_updates.keys():
            visit(key)
        return {k: env_updates[k] for k in sorted_keys}

    def _start_task_process(self, task: Dict[str, Any], env: Dict[str, str]) -> subprocess.Popen:
        stdout_log = open(task["stdout_log_path"], "a", encoding="utf-8", buffering=1)
        stderr_log = open(task["stderr_log_path"], "a", encoding="utf-8", buffering=1)
        proc = subprocess.Popen(
            task["resolved_command"],
            cwd=task["workspace_dir"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
            start_new_session=True,
        )
        runtime = {
            "process": proc,
            "stdout_log": stdout_log,
            "stderr_log": stderr_log,
            "stdout_thread": threading.Thread(
                target=self._pipe_task_log,
                args=(task["task_id"], proc.stdout, stdout_log, "stdout"),
                daemon=True,
                name=f"task-{task['task_id']}-stdout",
            ),
            "stderr_thread": threading.Thread(
                target=self._pipe_task_log,
                args=(task["task_id"], proc.stderr, stderr_log, "stderr"),
                daemon=True,
                name=f"task-{task['task_id']}-stderr",
            ),
        }
        self._task_runtime[task["task_id"]] = runtime
        runtime["stdout_thread"].start()
        runtime["stderr_thread"].start()
        return proc

    def _pipe_task_log(self, task_id: str, stream: Any, log_fh: Any, stream_name: str) -> None:
        try:
            for line in iter(stream.readline, ""):
                log_fh.write(line)
        except Exception as exc:
            warning(f"Task {task_id} {stream_name} capture failed: {exc}")
        finally:
            try:
                stream.close()
            except Exception:
                pass
            try:
                log_fh.flush()
            except Exception:
                pass

    def _close_task_runtime(self, task_id: str) -> None:
        runtime = self._task_runtime.pop(task_id, None)
        if not runtime:
            return
        for key in ("stdout_log", "stderr_log"):
            fh = runtime.get(key)
            try:
                fh.close()
            except Exception:
                pass

    def _probe_child_service(self, svc: Dict[str, Any]) -> bool:
        if not svc.get("enabled"):
            return False
        try:
            import requests

            kwargs: Dict[str, Any] = {"timeout": 1.5}
            if svc.get("password"):
                kwargs["auth"] = ("", svc["password"])
            url = svc["base_url_internal"].rstrip("/") + "/api/status"
            resp = requests.get(url, **kwargs)
            return resp.ok
        except Exception:
            return False

    def _refresh_task_states(self) -> None:
        now = _now()
        agents = self._snapshot_agents()
        with self._tasks_lock:
            for task in self._tasks.values():
                pid = task.get("pid")
                pid_str = str(pid) if pid not in (None, "") else ""
                task_workspace = os.path.abspath(str(task.get("workspace_dir") or ""))
                task_client_id = str(task.get("client_id") or "").strip()
                runtime = self._task_runtime.get(task["task_id"])
                alive = False
                exit_code = task.get("exit_code")
                if runtime and runtime.get("process") is not None:
                    code = runtime["process"].poll()
                    alive = code is None
                    if code is not None:
                        exit_code = code
                else:
                    alive = _is_pid_alive(pid)

                if task["process_status"] in {"starting", "running", "stopping"}:
                    if not alive:
                        task["finished_at"] = task.get("finished_at") or now
                        task["exit_code"] = exit_code
                        task["process_status"] = "stopped" if task["process_status"] == "stopping" or exit_code == 0 else "failed"
                        task["cmd_api"]["status"] = "stopped"
                        task["terminal_api"]["status"] = "stopped"
                        self._close_task_runtime(task["task_id"])
                        self._mark_dirty()
                    else:
                        cmd_ok = self._probe_child_service(task["cmd_api"])
                        term_ok = self._probe_child_service(task["terminal_api"])
                        term_enabled = bool((task.get("terminal_api") or {}).get("enabled"))
                        new_cmd_status = "running" if cmd_ok else "unavailable"
                        if term_enabled:
                            new_term_status = "running" if term_ok else "unavailable"
                        else:
                            new_term_status = "stopped"
                        if task["cmd_api"].get("status") != new_cmd_status:
                            task["cmd_api"]["status"] = new_cmd_status
                            self._mark_dirty()
                        if task["terminal_api"].get("status") != new_term_status:
                            task["terminal_api"]["status"] = new_term_status
                            self._mark_dirty()
                        if task["process_status"] == "starting" and cmd_ok and (term_ok or not term_enabled):
                            task["process_status"] = "running"
                            self._mark_dirty()

                matched_agent_id = ""
                for agent in agents:
                    agent_id = str(agent.get("id") or "").strip()
                    if task_client_id and agent_id == task_client_id:
                        matched_agent_id = agent_id
                        reported_terminal_api = agent.get("terminal_api") or {}
                        merged_terminal_api = _merge_runtime_service_info(task.get("terminal_api"), reported_terminal_api)
                        if merged_terminal_api != (task.get("terminal_api") or {}):
                            task["terminal_api"] = merged_terminal_api
                            self._mark_dirty()
                        reported_web_console = agent.get("web_console") or {}
                        merged_web_console = _merge_runtime_service_info(task.get("web_console"), reported_web_console)
                        if merged_web_console != (task.get("web_console") or {}):
                            task["web_console"] = merged_web_console
                            self._mark_dirty()
                        break
                    extra = agent.get("extra") or {}
                    agent_pid = extra.get("pid")
                    agent_pid_str = str(agent_pid) if agent_pid not in (None, "") else ""
                    agent_workspace = str(extra.get("workspace") or "").strip()
                    agent_workspace_abs = os.path.abspath(agent_workspace) if agent_workspace else ""
                    if (pid_str and agent_pid_str == pid_str) or (task_workspace and agent_workspace_abs == task_workspace):
                        matched_agent_id = agent.get("id", "")
                        reported_terminal_api = agent.get("terminal_api") or {}
                        merged_terminal_api = _merge_runtime_service_info(task.get("terminal_api"), reported_terminal_api)
                        if merged_terminal_api != (task.get("terminal_api") or {}):
                            task["terminal_api"] = merged_terminal_api
                            self._mark_dirty()
                        reported_web_console = agent.get("web_console") or {}
                        merged_web_console = _merge_runtime_service_info(task.get("web_console"), reported_web_console)
                        if merged_web_console != (task.get("web_console") or {}):
                            task["web_console"] = merged_web_console
                            self._mark_dirty()
                        break
                registered = bool(matched_agent_id)
                if task.get("registered_to_master") != registered:
                    task["registered_to_master"] = registered
                    self._mark_dirty()
                if task.get("registered_agent_id") != matched_agent_id:
                    task["registered_agent_id"] = matched_agent_id
                    self._mark_dirty()

    def _run_task_launch(self, req: Dict[str, Any]) -> Dict[str, Any]:
        req = dict(req)
        default_args = self.cfg.get_value("launch.default_args", {}) or {}
        if hasattr(default_args, "as_dict"):
            default_args = default_args.as_dict()
        if isinstance(default_args, dict):
            req = _merge_launch_default_args(req, default_args)
        if not str(req.get("client_id") or "").strip():
            req["client_id"] = uuid.uuid4().hex
        workspace_id = req.get("workspace_id", "")
        if not workspace_id:
            raise ValueError("'workspace_id' is required for launch")
        ws = self._get_workspace(workspace_id)

        selected_module = (req.get("selected_module") or "").strip()
        if not selected_module:
            raise ValueError("'selected_module' is required")
        effective_dut = (req.get("dut_name") or "").strip() or selected_module
        compile_info = dict((ws.get("compile") or {}))
        compile_matches = (
            compile_info.get("status") == "success"
            and compile_info.get("dut_name") == _safe_name(effective_dut, "DUT")
            and compile_info.get("selected_module") == selected_module
            and (
                not req.get("main_verilog_path")
                or os.path.abspath(str(compile_info.get("main_verilog_path") or "")) == os.path.abspath(str(req.get("main_verilog_path") or ""))
            )
        )
        if not compile_matches:
            raise ValueError(
                f"Workspace '{workspace_id}' has no successful compile matching DUT '{_safe_name(effective_dut, 'DUT')}' "
                f"and module '{selected_module}'. Please compile first."
            )

        prepared = {
            "workspace_dir": ws["workspace_dir"],
            "picker_workspace": compile_info.get("picker_workspace", ""),
            "dut_name": compile_info.get("dut_name", ""),
            "rtl_dir": compile_info.get("rtl_dir", ""),
            "doc_dir": compile_info.get("doc_dir", ""),
            "dut_dir": compile_info.get("dut_dir", ""),
            "main_verilog_path": compile_info.get("compiled_main_verilog_path", ""),
            "filelist_path": compile_info.get("filelist_path", ""),
            "generated_filelist": bool(compile_info.get("generated_filelist")),
            "copied_files": list(compile_info.get("copied_files") or []),
            "config_path": compile_info.get("config_path", ""),
        }

        compiled_config = str(compile_info.get("config_path") or "").strip()
        current_config = str(req.get("config") or "").strip()
        if compiled_config and (not current_config or current_config == os.path.basename(compiled_config)):
            req["config"] = compiled_config

        cmd_api_host, cmd_api_port, cmd_api_password = _parse_service_spec(
            req.get("export_cmd_api", ""),
            "127.0.0.1",
            find_available_port(start_port=int(self.cfg.get_value("cmd_api.port", 8765))),
        )
        cmd_api = {
            "enabled": True,
            "host": cmd_api_host,
            "port": cmd_api_port,
            "password": cmd_api_password or secrets.token_hex(8),
            "base_url_internal": f"http://{cmd_api_host}:{cmd_api_port}",
            "status": "starting",
        }
        req["export_cmd_api"] = f"{cmd_api['host']}:{cmd_api['port']} {cmd_api['password']}"

        terminal_api = {"enabled": False, "status": "stopped"}
        web_terminal_spec = req.get("web_terminal")
        if web_terminal_spec is not None:
            term_host, term_port, term_password = _parse_web_terminal_spec(str(web_terminal_spec))
            terminal_api = {
                "enabled": True,
                "host": term_host,
                "port": term_port,
                "password": term_password,
                "base_url_internal": f"http://{term_host}:{term_port}",
                "status": "starting",
            }
        web_console = {"enabled": False, "status": "stopped"}
        web_console_spec = req.get("web_console")
        if web_console_spec not in (None, False, ""):
            wc_host, wc_port, wc_password = _resolve_web_console_spec(web_console_spec)
            req["web_console"] = f"{wc_host}:{wc_port}" + (f":{wc_password}" if wc_password else "")
            web_console = {
                "enabled": True,
                "host": wc_host,
                "port": wc_port,
                "password": wc_password,
                "base_url_internal": f"http://{wc_host}:{wc_port}",
                "status": "starting",
            }

        task = self._create_task_record({
            "task_name": req.get("task_name") or selected_module,
            "client_id": req.get("client_id", ""),
            "workspace_id": workspace_id,
            "workspace_dir": prepared["workspace_dir"],
            "dut_name": prepared["dut_name"],
            "selected_module": selected_module,
            "main_verilog_path": prepared["main_verilog_path"],
            "env": req.get("env") or {},
            "cli_args_structured": req,
            "cli_args_extra": req.get("extra_args", []),
            "cmd_api": cmd_api,
            "terminal_api": terminal_api,
            "web_console": web_console,
        })

        task["picker_command"] = list(compile_info.get("picker_command") or [])
        task["picker_exit_code"] = compile_info.get("picker_exit_code")
        task["picker_status"] = compile_info.get("status", "not_started")
        self._mark_dirty()

        if task["picker_status"] != "success":
            task["process_status"] = "failed"
            task["finished_at"] = _now()
            return task

        resolved_command, env = self._build_ucagent_command(req, prepared, cmd_api)
        task["resolved_command"] = resolved_command
        task["process_status"] = "starting"
        proc = self._start_task_process(task, env)
        task["pid"] = proc.pid
        task["started_at"] = _now()
        code = proc.poll()
        if code is not None:
            task["process_status"] = "failed" if code != 0 else "stopped"
            task["exit_code"] = code
            task["finished_at"] = _now()
            task["cmd_api"]["status"] = "stopped"
            task["terminal_api"]["status"] = "stopped"
            self._close_task_runtime(task["task_id"])
        else:
            task["cmd_api"]["status"] = "starting"
            if not task["terminal_api"].get("enabled"):
                task["terminal_api"]["status"] = "stopped"
        self._mark_dirty()
        return task

    def _terminate_task(self, task: Dict[str, Any], force: bool = False) -> None:
        pid = task.get("pid")
        if not pid:
            return
        sig = signal.SIGKILL if force else signal.SIGTERM
        try:
            os.killpg(pid, sig)
        except OSError:
            try:
                os.kill(pid, sig)
            except OSError:
                pass

    def _task_public(self, task: Dict[str, Any], include_logs: bool = False) -> Dict[str, Any]:
        data = json.loads(json.dumps(task))
        if isinstance(data.get("cmd_api"), dict):
            data["cmd_api"].pop("password", None)
        if isinstance(data.get("terminal_api"), dict):
            data["terminal_api"].pop("password", None)
        if isinstance(data.get("web_console"), dict):
            data["web_console"].pop("password", None)
        if include_logs:
            data["stdout_tail"] = _tail_file(task.get("stdout_log_path", ""))
            data["stderr_tail"] = _tail_file(task.get("stderr_log_path", ""))
        else:
            data.pop("stdout_log_path", None)
            data.pop("stderr_log_path", None)
        return data

    def _build_proxy_headers(self, password: str, original_headers: Dict[str, str]) -> Dict[str, str]:
        headers = {}
        for key, value in original_headers.items():
            lk = key.lower()
            if lk in {"host", "content-length", "authorization"}:
                continue
            headers[key] = value
        if password:
            token = base64.b64encode(f":{password}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        return headers

    def _build_ws_proxy_headers(self, password: str, original_headers: Dict[str, str]) -> Dict[str, str]:
        headers = {}
        for key, value in original_headers.items():
            lk = key.lower()
            if lk in {
                "host",
                "connection",
                "upgrade",
                "authorization",
                "cookie",
                "origin",
                "sec-websocket-key",
                "sec-websocket-version",
                "sec-websocket-extensions",
                "sec-websocket-accept",
            }:
                continue
            headers[key] = value
        if password:
            token = base64.b64encode(f":{password}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        return headers

    def _launch_env_preview(self) -> List[Dict[str, Any]]:
        configured = self.cfg.get_value("launch.default_env", []) or []
        if hasattr(configured, "as_dict"):
            configured = configured.as_dict()
        if not isinstance(configured, list):
            configured = []
        secret_markers = ("KEY", "TOKEN", "SECRET", "PASSWORD")
        ref_pattern = re.compile(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?$")
        items = []
        for entry in configured:
            if hasattr(entry, "as_dict"):
                entry = entry.as_dict()
            mode = "required"
            reference_key = ""
            raw_value = ""
            if isinstance(entry, str):
                key = entry.strip()
            elif isinstance(entry, dict) and len(entry) == 1:
                key, raw = next(iter(entry.items()))
                key = str(key).strip()
                raw_value = str(raw)
                match = ref_pattern.match(raw_value.strip())
                if match:
                    mode = "reference"
                    reference_key = match.group(1)
                else:
                    mode = "literal"
            else:
                continue
            if not key:
                continue
            resolved_value = ""
            if mode == "required":
                resolved_value = os.environ.get(key, "")
            elif mode == "reference":
                resolved_value = os.environ.get(reference_key, "")
            else:
                resolved_value = raw_value
            masked = any(marker in key for marker in secret_markers) or any(marker in reference_key for marker in secret_markers)
            items.append({
                "key": key,
                "mode": mode,
                "reference_key": reference_key,
                "raw_value": (raw_value if (not masked or mode == "reference") else ""),
                "present": "yes" if resolved_value else "no",
                "value": _mask_secret(resolved_value) if (resolved_value and masked) else resolved_value,
                "masked": masked,
                "source": "config" if mode in {"literal", "reference"} else "environment",
            })
        return items

    def _launch_default_env_updates(self, env_updates: Dict[str, Any]) -> Dict[str, str]:
        configured = self.cfg.get_value("launch.default_env", []) or []
        if hasattr(configured, "as_dict"):
            configured = configured.as_dict()
        if not isinstance(configured, list):
            configured = []
        ref_pattern = re.compile(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?$")
        current = {str(k): str(v) for k, v in (os.environ or {}).items()}
        current.update({str(k): str(v) for k, v in (env_updates or {}).items() if str(v).strip()})
        default_updates: Dict[str, str] = {}
        for entry in configured:
            if hasattr(entry, "as_dict"):
                entry = entry.as_dict()
            if isinstance(entry, str):
                continue
            if not isinstance(entry, dict) or len(entry) != 1:
                continue
            key, raw = next(iter(entry.items()))
            key = str(key).strip()
            if not key or str((env_updates or {}).get(key, "")).strip():
                continue
            raw_value = str(raw)
            match = ref_pattern.match(raw_value.strip())
            if match:
                ref_key = match.group(1)
                if str(current.get(ref_key, "")).strip():
                    default_updates[key] = raw_value
                    current[key] = raw_value
                continue
            if raw_value.strip():
                default_updates[key] = raw_value
                current[key] = raw_value
        return default_updates

    def _launched_task_for_agent_id(self, agent_id: str) -> Optional[Dict[str, Any]]:
        agent_id = str(agent_id or "").strip()
        if not agent_id:
            return None
        matched: List[Dict[str, Any]] = []
        with self._tasks_lock:
            for task in self._tasks.values():
                if str(task.get("registered_agent_id") or "").strip() == agent_id or str(task.get("client_id") or "").strip() == agent_id:
                    matched.append(task)
        if not matched:
            return None
        matched.sort(key=lambda item: item.get("created_at", 0), reverse=True)
        return matched[0]

    def _cmd_proxy_url(self, task: Dict[str, Any], subpath: str) -> str:
        cmd_api = task.get("cmd_api") or {}
        base = cmd_api.get("base_url_internal", "")
        if not base:
            raise ValueError("CMD API base URL not available")
        base = base.rstrip("/")
        return f"{base}/{subpath.lstrip('/')}" if subpath else f"{base}/"

    def _terminal_proxy_url(self, task: Dict[str, Any], subpath: str) -> str:
        terminal_api = task.get("terminal_api") or {}
        base = terminal_api.get("base_url_internal", "")
        if not base:
            raise ValueError("Terminal API base URL not available")
        base = base.rstrip("/")
        return f"{base}/{subpath.lstrip('/')}" if subpath else f"{base}/"

    def _web_console_proxy_url(self, task: Dict[str, Any], subpath: str) -> str:
        web_console = task.get("web_console") or {}
        base = web_console.get("base_url_internal", "")
        if not base:
            raise ValueError("Web console base URL not available")
        base = base.rstrip("/")
        return f"{base}/{subpath.lstrip('/')}" if subpath else f"{base}/"

    def _agent_cmd_proxy_url(self, agent: Dict[str, Any], subpath: str) -> str:
        base = agent.get("cmd_api_tcp", "")
        if not base:
            raise HTTPException(status_code=503, detail="CMD API service is not available for this agent")
        if not base.startswith("http"):
            base = f"http://{base}"
        base = base.rstrip("/")
        return f"{base}/{subpath.lstrip('/')}" if subpath else f"{base}/"

    def _agent_terminal_proxy_url(self, agent: Dict[str, Any], subpath: str) -> str:
        terminal_api = agent.get("terminal_api", {})
        base = terminal_api.get("base_url_internal", "") or terminal_api.get("tcp_url", "")
        if not base:
            raise HTTPException(status_code=503, detail="Terminal API service is not available for this agent")
        if not base.startswith("http"):
            base = f"http://{base}"
        base = base.rstrip("/")
        return f"{base}/{subpath.lstrip('/')}" if subpath else f"{base}/"

    def _agent_web_console_proxy_url(self, agent: Dict[str, Any], subpath: str) -> str:
        web_console = agent.get("web_console", {})
        if not web_console.get("enabled", False):
            raise HTTPException(status_code=503, detail="Web console service is not available for this agent")
        
        # Get base URL from any possible field
        base = web_console.get("base_url_internal", "") or web_console.get("tcp_url", "")
        if not base and web_console.get("host") and web_console.get("port"):
            base = f"{web_console['host']}:{web_console['port']}"
            
        if not base:
            raise HTTPException(status_code=503, detail="Web console service address not found")
            
        if not base.startswith("http"):
            base = f"http://{base}"
        base = base.rstrip("/")
        return f"{base}/{subpath.lstrip('/')}" if subpath else f"{base}/"

    # ------------------------------------------------------------------
    # FastAPI app
    # ------------------------------------------------------------------

    def _build_app(self):  # noqa: C901
        import aiohttp
        import secrets as _secrets

        app = FastAPI(
            title="UCAgent Master API",
            description="Aggregates heartbeats and manages launched UCAgent tasks.",
            version="2.0.0",
        )

        access_key = self.access_key
        password = self.password
        security = HTTPBasic(auto_error=False)

        async def _check_access_key(x_access_key: str = _Header(default="")):
            if access_key and x_access_key != access_key:
                raise HTTPException(status_code=403, detail="Invalid or missing access key.")

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

        def _fix_cmd_api_url(url: str, client_ip: str) -> str:
            if not url or not client_ip:
                return url
            m = re.match(r"^(https?://)([^:/]+)((?::\d+)?.*)$", url)
            if m and m.group(2).strip().lower() in _LOCAL_HOSTS:
                return m.group(1) + client_ip + m.group(3)
            return url

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

        @app.post("/api/register", summary="Register or heartbeat", dependencies=[Depends(_check_access_key)])
        def register(body: Dict[str, Any] = Body(default_factory=dict), request: Request = None):
            agent_id = str(body.get("id") or "").strip()
            if not agent_id:
                raise HTTPException(status_code=400, detail="'id' must not be empty")

            client_ip = request.client.host if request.client else ""
            if agent_id in self._removed:
                if bool(body.get("force")):
                    self._removed.discard(agent_id)
                else:
                    return {"status": "removed", "message": "This agent has been removed from the master."}

            now = _now()
            with self._agents_lock:
                existing = self._agents.get(agent_id, {})
                is_new = not existing
                tcp_url = _fix_cmd_api_url(str(body.get("cmd_api_tcp") or ""), client_ip)
                current_stage_index = int(body.get("current_stage_index", -1) or -1)
                total_stage_count = int(body.get("total_stage_count", 0) or 0)
                
                # Normalize web_console field
                raw_web_console = body.get("web_console")
                web_console = {}
                if isinstance(raw_web_console, str) and raw_web_console.strip():
                    # If web_console is a string (address), convert to object
                    web_console = {
                        "enabled": True,
                        "tcp_url": raw_web_console.strip(),
                        "host": raw_web_console.strip().split(":")[0] if ":" in raw_web_console else raw_web_console.strip(),
                        "port": int(raw_web_console.strip().split(":")[1]) if ":" in raw_web_console else 8000
                    }
                elif isinstance(raw_web_console, dict):
                    web_console = _copy_jsonable(raw_web_console)
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
                    terminal_api = {
                        "enabled": True,
                        "tcp_url": raw_terminal_api.strip(),
                        "host": raw_terminal_api.strip().split(":")[0] if ":" in raw_terminal_api else raw_terminal_api.strip(),
                        "port": int(raw_terminal_api.strip().split(":")[1]) if ":" in raw_terminal_api else 8818
                    }
                elif isinstance(raw_terminal_api, dict):
                    terminal_api = _copy_jsonable(raw_terminal_api)
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
                    "extra": body.get("extra") or existing.get("extra", {}),
                    "first_seen": existing.get("first_seen", now),
                    "last_seen": now,
                }
            self._mark_dirty()
            if is_new or bool(body.get("force")):
                action = "rejoined" if bool(body.get("force")) else "joined"
                _master_log(f"Agent '{agent_id}' {action} host={str(body.get('host') or '?')}")
            return {"status": "ok", "message": f"Agent '{agent_id}' registered."}

        @app.get("/api/agents", summary="List all agents", dependencies=[Depends(_check_password)])
        def list_agents(
            include_offline: bool = True,
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
            with self._agents_lock:
                data = []
                for agent in self._agents.values():
                    st = self._agent_status(agent)
                    if not include_offline and st == "offline":
                        continue
                    tl = agent.get("task_list") or {}
                    raw_mi = agent.get("mission_info_ansi", "")
                    launch_task = self._launched_task_for_agent_id(agent["id"])
                    data.append({
                        "id": agent["id"],
                        "host": agent["host"],
                        "version": agent["version"],
                        "cmd_api_tcp": agent["cmd_api_tcp"],
                        "cmd_api_sock": agent["cmd_api_sock"],
                        "status": st,
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
                        "mission_info_ansi": _strip_ansi(raw_mi) if strip_ansi else raw_mi,
                        "task_list": agent.get("task_list"),
                        "launch": bool(launch_task),
                        "launch_task_id": launch_task.get("task_id", "") if launch_task else "",
                        "cmd_api_proxy": f"/task/{launch_task['task_id']}/cmd/" if launch_task else f"/agent/{agent['id']}/cmd/",
                    })
                reverse = sort_desc
                if sort_by == "status":
                    data.sort(key=lambda a: (a["status"] != "online"), reverse=reverse)
                else:
                    data.sort(key=lambda a: a.get(sort_by, ""), reverse=reverse)
                total_count = len(data)
                total_pages = (total_count + page_size - 1) // page_size
                if total_pages and page > total_pages:
                    page = total_pages
                start_idx = (page - 1) * page_size
                page_data = data[start_idx:start_idx + page_size]
            return {
                "status": "ok",
                "count": total_count,
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
            data = {
                "id": agent["id"],
                "host": agent["host"],
                "version": agent["version"],
                "cmd_api_tcp": agent["cmd_api_tcp"],
                "cmd_api_sock": agent["cmd_api_sock"],
                "status": st,
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
                "mission_info_ansi": _strip_ansi(raw_mi) if strip_ansi else raw_mi,
                "task_list": agent.get("task_list"),
                "launch": bool(launch_task),
                "launch_task_id": launch_task.get("task_id", "") if launch_task else "",
                "cmd_api_proxy": f"/task/{launch_task['task_id']}/cmd/" if launch_task else "",
            }
            return {"status": "ok", "agent_status": st, "data": data}

        @app.delete("/api/agent/{agent_id}", summary="Remove an agent", dependencies=[Depends(_check_password)])
        def delete_agent(agent_id: str):
            with self._agents_lock:
                if agent_id not in self._agents:
                    raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
                del self._agents[agent_id]
            self._removed.add(agent_id)
            self._mark_dirty()
            _master_log(f"Agent '{agent_id}' removed by operator")
            return {"status": "ok", "message": f"Agent '{agent_id}' removed."}

        @app.get("/api/launch/file-roots", summary="List configured launch file roots", dependencies=[Depends(_check_password)])
        def launch_file_roots():
            return {"status": "ok", "roots": self._launch_roots}

        @app.get("/api/launch/config", summary="Get launch default configuration", dependencies=[Depends(_check_password)])
        def launch_config():
            def to_dict(obj):
                if hasattr(obj, "as_dict"):
                    obj = obj.as_dict()
                if isinstance(obj, dict):
                    return {k: to_dict(v) for k, v in obj.items()}
                if isinstance(obj, list):
                    return [to_dict(v) for v in obj]
                return obj
            default_args = to_dict(self.cfg.get_value("launch.default_args", {}) or {})
            workspace_root = self.cfg.get_value("launch.workspace_root", "/tmp/") or "/tmp/"
            backend_cfg = to_dict(self.cfg.get_value("backend", {}) or {})
            backend_key_name = backend_cfg.get("key_name", "") if isinstance(backend_cfg, dict) else ""
            backend_options = []
            if isinstance(backend_cfg, dict):
                for key in backend_cfg.keys():
                    if key.startswith("_") or key == "key_name":
                        continue
                    if isinstance(backend_cfg.get(key), dict):
                        backend_options.append({"name": key, "value": key})
            return {
                "status": "ok",
                "workspace_root": workspace_root,
                "default_args": default_args,
                "backend_key_name": backend_key_name,
                "backend_options": backend_options,
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
        def create_workspace(
            body: Dict[str, Any] = Body(default_factory=dict),
            workspace_root: str = Query("/tmp"),
        ):
            root = str(body.get("workspace_root") or workspace_root or "/tmp").strip() or "/tmp"
            ws = self._create_workspace(root)
            return {"status": "ok", "workspace": self._workspace_public(ws)}

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
            try:
                abs_path = self._safe_under_root(ws["workspace_dir"], path)
            except ValueError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
            if not os.path.isfile(abs_path):
                raise HTTPException(status_code=404, detail="File not found")
            return FileResponse(abs_path, filename=os.path.basename(abs_path))

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
            try:
                with open(item["stored_path"], "r", encoding="utf-8", errors="replace") as fh:
                    modules = _parse_module_names(fh.read())
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Failed to parse Verilog file: {exc}") from exc
            return {"status": "ok", "file": self._workspace_file_public(ws, item), "modules": modules}

        @app.post("/api/workspace/{workspace_id}/compile", summary="Compile DUT in launch workspace", dependencies=[Depends(_check_password)])
        @app.post("/api/workspace/{workspace_id}/picker", summary="Run picker export in launch workspace", dependencies=[Depends(_check_password)])
        def workspace_picker(workspace_id: str, body: Dict[str, Any] = Body(default_factory=dict)):
            try:
                selected_module = str(body.get("selected_module") or "").strip()
                if not selected_module:
                    raise ValueError("'selected_module' is required")
                result = self._compile_workspace_dut(
                    workspace_id=workspace_id,
                    effective_dut=str(body.get("dut_name") or "").strip() or selected_module,
                    selected_module=selected_module,
                    main_verilog_path=str(body.get("main_verilog_path") or ""),
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
            from fastapi.responses import StreamingResponse

            selected_module = str(body.get("selected_module") or "").strip()
            if not selected_module:
                raise HTTPException(status_code=400, detail="'selected_module' is required")
            effective_dut = str(body.get("dut_name") or "").strip() or selected_module
            main_verilog_path = str(body.get("main_verilog_path") or "")

            def emit(event: Dict[str, Any]) -> bytes:
                return (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")

            def stream():
                try:
                    prepared = self._prepare_workspace_layout(
                        workspace_id,
                        effective_dut=effective_dut,
                        main_verilog_path=main_verilog_path,
                    )
                    yield emit({
                        "type": "info",
                        "message": f"Prepared workspace layout: RTL={prepared['rtl_dir']} DOC={prepared['doc_dir']}",
                    })
                    picker = yield from self._stream_picker_run(
                        workspace_dir=prepared["workspace_dir"],
                        picker_workspace=prepared["picker_workspace"],
                        dut_name=prepared["dut_name"],
                        selected_module=selected_module,
                        main_verilog_path=prepared["main_verilog_path"],
                        filelist_path=prepared["filelist_path"],
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
                        "generated_filelist": prepared["generated_filelist"],
                        "config_path": prepared.get("config_path", ""),
                        "readme_path": readme_path,
                        "compiled_at": _now(),
                        "copied_files": prepared["copied_files"],
                        "picker_command": picker["command"],
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
            try:
                self._get_workspace(workspace_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            selected_module = str(body.get("selected_module") or "").strip()
            if not selected_module:
                raise HTTPException(status_code=400, detail="'selected_module' is required")
            runtime = self._start_compile_job(
                workspace_id,
                str(body.get("dut_name") or "").strip() or selected_module,
                selected_module,
                str(body.get("main_verilog_path") or ""),
            )
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
                    if name.startswith("_"):
                        continue
                    options.append({"name": name, "value": value, "source": "predefined"})
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

        @app.get("/api/tasks", summary="List managed tasks", dependencies=[Depends(_check_password)])
        def list_tasks(status: str = "", dut: str = "", q: str = ""):
            status = status.strip().lower()
            dut = dut.strip().lower()
            q = q.strip().lower()
            with self._tasks_lock:
                tasks = [self._task_public(task) for task in self._tasks.values()]
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
                data.append(task)
            data.sort(key=lambda item: item.get("created_at", 0), reverse=True)
            return {"status": "ok", "tasks": data, "count": len(data)}

        _STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"

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
            try:
                task = self._get_task(task_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return {"status": "ok", "task": self._task_public(task, include_logs=True)}

        @app.get("/api/task/{task_id}/command", summary="Managed task command", dependencies=[Depends(_check_password)])
        def get_task_command(task_id: str):
            try:
                task = self._get_task(task_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return {"status": "ok", "command": task.get("resolved_command", []), "env": task.get("env", {})}

        @app.get("/api/task/{task_id}/logs", summary="Managed task logs", dependencies=[Depends(_check_password)])
        def get_task_logs(task_id: str):
            try:
                task = self._get_task(task_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return {
                "status": "ok",
                "stdout": _tail_file(task.get("stdout_log_path", "")),
                "stderr": _tail_file(task.get("stderr_log_path", "")),
                "picker_stdout": task.get("picker_stdout", ""),
                "picker_stderr": task.get("picker_stderr", ""),
            }

        @app.post("/api/task/{task_id}/stop", summary="Stop managed task", dependencies=[Depends(_check_password)])
        def stop_task(task_id: str, body: Dict[str, Any] = Body(default_factory=dict)):
            try:
                task = self._get_task(task_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            if task["process_status"] in {"stopped", "failed"}:
                return {"status": "ok", "task": self._task_public(task), "message": "Task already stopped"}
            task["process_status"] = "stopping"
            force = bool((body or {}).get("force"))
            self._terminate_task(task, force=force)
            self._mark_dirty()
            return {"status": "ok", "task": self._task_public(task)}

        @app.delete("/api/task/{task_id}", summary="Delete managed task record", dependencies=[Depends(_check_password)])
        def delete_task(task_id: str):
            with self._tasks_lock:
                task = self._tasks.get(task_id)
                if task is None:
                    raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
                if task.get("process_status") in {"starting", "running", "stopping"}:
                    raise HTTPException(status_code=400, detail="Running task cannot be deleted")
                del self._tasks[task_id]
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
            body = await request.body()
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.request(request.method, target_url, data=body or None, headers=headers, allow_redirects=False) as resp:
                        raw = await resp.read()
                        content_type = resp.headers.get("Content-Type", "")
                        if "text/html" in content_type:
                            text = raw.decode("utf-8", errors="replace")
                            text = _rewrite_html(text, {
                                '"/api/': f'"/task/{task_id}/cmd/api/',
                                "'/api/": f"'/task/{task_id}/cmd/api/",
                                '"/workspace': f'"/task/{task_id}/cmd/workspace',
                                "'/workspace": f"'/task/{task_id}/cmd/workspace",
                                '"/static/': f'"/task/{task_id}/cmd/static/',
                                "'/static/": f"'/task/{task_id}/cmd/static/",
                                '"/surfer': f'"/task/{task_id}/cmd/surfer',
                                "'/surfer": f"'/task/{task_id}/cmd/surfer",
                            })
                            raw = text.encode("utf-8")
                        response_headers = {}
                        for key, value in resp.headers.items():
                            if key.lower() in {"content-length", "transfer-encoding", "content-encoding", "connection"}:
                                continue
                            response_headers[key] = value
                        return Response(content=raw, status_code=resp.status, headers=response_headers, media_type=None)
                except Exception as exc:
                    raise HTTPException(status_code=502, detail=f"Failed to proxy CMD API: {exc}") from exc

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
            body = await request.body()
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.request(request.method, target_url, data=body or None, headers=headers, allow_redirects=False) as resp:
                        raw = await resp.read()
                        content_type = resp.headers.get("Content-Type", "")
                        if "text/html" in content_type:
                            text = raw.decode("utf-8", errors="replace")
                            text = _rewrite_html(text, {
                                '"/api/': f'"/agent/{agent_id}/cmd/api/',
                                "'/api/": f"'/agent/{agent_id}/cmd/api/",
                                '"/workspace': f'"/agent/{agent_id}/cmd/workspace',
                                "'/workspace": f"'/agent/{agent_id}/cmd/workspace",
                                '"/static/': f'"/agent/{agent_id}/cmd/static/',
                                "'/static/": f"'/agent/{agent_id}/cmd/static/",
                                '"/surfer': f'"/agent/{agent_id}/cmd/surfer',
                                "'/surfer": f"'/agent/{agent_id}/cmd/surfer",
                            })
                            raw = text.encode("utf-8")
                        response_headers = {}
                        for key, value in resp.headers.items():
                            if key.lower() in {"content-length", "transfer-encoding", "content-encoding", "connection"}:
                                continue
                            response_headers[key] = value
                        return Response(content=raw, status_code=resp.status, headers=response_headers, media_type=None)
                except Exception as exc:
                    raise HTTPException(status_code=502, detail=f"Failed to proxy Agent CMD API: {exc}") from exc

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
                            if key.lower() in {"content-length", "transfer-encoding", "content-encoding", "connection"}:
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
                            if key.lower() in {"content-length", "transfer-encoding", "content-encoding", "connection"}:
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
                            if key.lower() in {"content-length", "transfer-encoding", "content-encoding", "connection"}:
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
            base_url = terminal_api.get("base_url_internal", "")
            if not base_url:
                await websocket.close(code=4503)
                return
            target_url = base_url.replace("http://", "ws://").rstrip("/") + "/ws"
            if websocket.url.query:
                target_url += "?" + urlencode(dict(websocket.query_params))
            auth = aiohttp.BasicAuth("", terminal_api.get("password", "")) if terminal_api.get("password") else None
            upstream_headers = self._build_ws_proxy_headers(terminal_api.get("password", ""), dict(websocket.headers))
            # Set correct Origin header for upstream CORS validation
            from urllib.parse import urlparse
            parsed_url = urlparse(target_url)
            upstream_origin = f"{parsed_url.scheme.replace('ws', 'http')}://{parsed_url.netloc}"
            upstream_headers["Origin"] = upstream_origin
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.ws_connect(target_url, auth=auth, heartbeat=20, headers=upstream_headers, max_msg_size=100*1024*1024) as upstream:
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
            
            auth = aiohttp.BasicAuth("", web_console.get("password", "")) if web_console.get("password") else None
            upstream_headers = self._build_ws_proxy_headers(web_console.get("password", ""), dict(websocket.headers))
            # Set correct Origin header for upstream CORS validation
            from urllib.parse import urlparse
            parsed_url = urlparse(target_url)
            upstream_origin = f"{parsed_url.scheme.replace('ws', 'http')}://{parsed_url.netloc}"
            upstream_headers["Origin"] = upstream_origin
            
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.ws_connect(target_url, auth=auth, heartbeat=20, headers=upstream_headers, max_msg_size=100*1024*1024) as upstream:
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
            
            auth = aiohttp.BasicAuth("", terminal_api.get("password", "")) if terminal_api.get("password") else None
            upstream_headers = self._build_ws_proxy_headers(terminal_api.get("password", ""), dict(websocket.headers))
            # Set correct Origin header for upstream CORS validation
            from urllib.parse import urlparse
            parsed_url = urlparse(target_url)
            upstream_origin = f"{parsed_url.scheme.replace('ws', 'http')}://{parsed_url.netloc}"
            upstream_headers["Origin"] = upstream_origin
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.ws_connect(target_url, auth=auth, heartbeat=20, headers=upstream_headers, max_msg_size=100*1024*1024) as upstream:
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

            base_url = web_console.get("base_url_internal", "")
            if not base_url:
                await websocket.close(code=4503)
                return
            target_url = base_url.replace("http://", "ws://").rstrip("/") + "/ws"
            if websocket.url.query:
                target_url += "?" + urlencode(dict(websocket.query_params))
            auth = aiohttp.BasicAuth("", web_console.get("password", "")) if web_console.get("password") else None
            upstream_headers = self._build_ws_proxy_headers(web_console.get("password", ""), dict(websocket.headers))
            # Set correct Origin header for upstream CORS validation
            from urllib.parse import urlparse
            parsed_url = urlparse(target_url)
            upstream_origin = f"{parsed_url.scheme.replace('ws', 'http')}://{parsed_url.netloc}"
            upstream_headers["Origin"] = upstream_origin
            
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.ws_connect(target_url, auth=auth, heartbeat=20, headers=upstream_headers, max_msg_size=100*1024*1024) as upstream:
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

        return app

    # ------------------------------------------------------------------
    # Monitor thread
    # ------------------------------------------------------------------

    def _monitor_loop(self) -> None:
        while not self._monitor_stop.is_set():
            self._monitor_stop.wait(self.MONITOR_INTERVAL)
            if self._monitor_stop.is_set():
                break
            now = _now()
            with self._agents_lock:
                current_ids = set(self._agents.keys())
                for aid, agent in self._agents.items():
                    is_online = (now - agent["last_seen"]) <= self.offline_timeout
                    was_online = self._online_cache.get(aid, True)
                    if was_online and not is_online:
                        elapsed = int(now - agent["last_seen"])
                        _master_log(
                            f"Agent '{aid}' went offline (no heartbeat for {elapsed}s, host={agent.get('host', '?')})"
                        )
                    self._online_cache[aid] = is_online
            for aid in list(self._online_cache):
                if aid not in current_ids:
                    del self._online_cache[aid]

            self._refresh_task_states()

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
                cfg = uvicorn.Config(self._app, host=self.host, port=self.port, log_level="error")
                self._tcp_server = uvicorn.Server(cfg)
                self._tcp_thread = threading.Thread(target=self._tcp_server.run, daemon=True, name="master-api-tcp")
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
            if not any("Cannot remove" in item for item in errors):
                try:
                    cfg = uvicorn.Config(self._app, uds=self.sock, log_level="error")
                    self._sock_server = uvicorn.Server(cfg)
                    self._sock_thread = threading.Thread(target=self._sock_server.run, daemon=True, name="master-api-sock")
                    self._sock_thread.start()
                    started.append(f"Sock {self.sock}  (docs: curl --unix-socket {self.sock} http://localhost/docs)")
                except Exception as exc:
                    errors.append(f"Socket listener failed: {exc}")
                    self._sock_server = None
                    self._sock_thread = None
        if not started:
            return False, "Master API server failed to start:\n  " + "\n  ".join(errors)

        self._running = True
        self.started_at = _now()
        if self.sock:
            import atexit

            sock_path = self.sock

            def _cleanup_sock():
                try:
                    if os.path.exists(sock_path):
                        os.unlink(sock_path)
                except OSError:
                    pass

            atexit.register(_cleanup_sock)
        self._monitor_stop.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True, name="master-monitor")
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
        self.started_at = None
        self._monitor_stop.set()
        self._monitor_thread = None
        self._online_cache.clear()
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
        parts = []
        if self.tcp:
            parts.append(f"http://{self.host}:{self.port}")
        if self.sock:
            parts.append(f"unix://{self.sock}")
        return " | ".join(parts) if parts else "(none)"

    def agent_count(self) -> Dict[str, int]:
        online = offline = 0
        with self._agents_lock:
            for agent in self._agents.values():
                if _now() - agent["last_seen"] <= self.offline_timeout:
                    online += 1
                else:
                    offline += 1
        return {"online": online, "offline": offline}


class PdbMasterClient:
    """
    Background thread that periodically sends a heartbeat + status snapshot
    to a PdbMasterApiServer via HTTP.
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
        try:
            import requests  # noqa: F401
        except ImportError as exc:
            raise ImportError("'requests' is required for the master client. Install with: pip install requests") from exc

        self.pdb = pdb_instance
        self.master_url = master_url.rstrip("/")
        self.agent_id = agent_id or f"{socket.gethostname()}-{os.getpid()}"
        self.interval = interval
        self.reconnect_interval = reconnect_interval
        self.access_key = access_key

        self._running = False
        self._kicked = False
        self._auth_failed = False
        self._connected = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._force_next = False

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

        current_stage_index = -1
        total_stage_count = 0
        is_mission_complete = False
        current_stage_name = ""
        if task_list:
            tl_inner = task_list.get("task_list") or {}
            stage_list = tl_inner.get("stage_list", [])
            total_stage_count = len(stage_list)
            raw_index = task_list.get("task_index", -1)
            current_stage_index = raw_index
            is_mission_complete = total_stage_count > 0 and raw_index >= total_stage_count
            current_stage_name = tl_inner.get("current_stage_name", "")
            if not current_stage_name and 0 <= raw_index < total_stage_count:
                current_stage_name = stage_list[raw_index].get("title", "")

        run_time = ""
        try:
            from ucagent.util.functions import fmt_time_deta as _fmt_time_deta

            agent_tmp = getattr(pdb, "agent", None)
            if agent_tmp is not None:
                run_time = _fmt_time_deta(agent_tmp.stage_manager.get_time_cost())
            else:
                run_time = "-"
        except Exception as exc:
            warning("Failed to get run_time from agent.stage_manager.get_time_cost(): " + str(exc))
            run_time = "-"

        agent = getattr(pdb, "agent", None)
        mcp_running = False
        if agent is not None:
            mcps = getattr(agent, "_mcps", None)
            mcp_thread = getattr(agent, "_mcp_server_thread", None)
            mcp_running = mcps is not None and (mcp_thread is None or mcp_thread.is_alive())
        is_break = bool(agent.is_break()) if agent is not None else False
        last_cmd = getattr(pdb, "lastcmd", "") or ""

        try:
            mission_info_lines = pdb.api_mission_info()
            mission_info_ansi = "\n".join(str(v) for v in mission_info_lines)
        except Exception as exc:
            warning("Failed to get mission_info_ansi: " + str(exc))
            mission_info_ansi = ""
        try:
            server_info = pdb.api_server_info() or {}
        except Exception as exc:
            warning("Failed to get server_info for master payload: " + str(exc))
            server_info = {}

        return {
            "id": self.agent_id,
            "host": _local_ip(),
            "version": __version__,
            "cmd_api_tcp": tcp_url,
            "cmd_api_sock": sock_path,
            "web_console": server_info.get("web_console") or {},
            "terminal_api": server_info.get("terminal_api") or {},
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

    def _heartbeat_loop(self) -> None:
        import requests

        register_url = f"{self.master_url}/api/register"
        connected = False
        headers = {"X-Access-Key": self.access_key} if self.access_key else {}
        while not self._stop_event.is_set():
            try:
                payload = self._build_payload()
                if self._force_next or not connected:
                    payload["force"] = True
                    self._force_next = False
                resp = requests.post(register_url, json=payload, timeout=10, headers=headers)
                if resp.ok:
                    data = resp.json()
                    if data.get("status") == "removed":
                        self._kicked = True
                        self._running = False
                        return
                    if not connected:
                        _master_log(f"[MasterClient] (Re)connected to master {self.master_url} as '{self.agent_id}'")
                    connected = True
                    self._connected = True
                else:
                    if resp.status_code == 403:
                        self._auth_failed = True
                        self._running = False
                        self._connected = False
                        return
                    connected = False
                    self._connected = False
                    self._stop_event.wait(self.reconnect_interval)
                    continue
            except Exception as exc:
                if connected:
                    _master_log(f"[MasterClient] Connection to {self.master_url} lost: {exc}. Retrying in {self.reconnect_interval}s …")
                connected = False
                self._connected = False
                self._stop_event.wait(self.reconnect_interval)
                continue
            self._stop_event.wait(self.interval)

    def start(self) -> Tuple[bool, str]:
        if self._running:
            return False, f"Already connected to master at {self.master_url}"
        if self._kicked:
            return False, f"This agent was removed from master {self.master_url}. Use a new PdbMasterClient instance to reconnect."
        if self._auth_failed:
            return False, f"Access key was rejected by master {self.master_url} (HTTP 403). Provide the correct --key value and reconnect."
        self._stop_event.clear()
        self._force_next = True
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True, name="master-client")
        self._thread.start()
        self._running = True
        return True, f"Connected to master {self.master_url} as '{self.agent_id}' (interval={self.interval}s, reconnect_interval={self.reconnect_interval}s)"

    def stop(self) -> Tuple[bool, str]:
        if not self._running:
            return False, "Not connected to master"
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
        return self._kicked

    @property
    def is_auth_failed(self) -> bool:
        return self._auth_failed
