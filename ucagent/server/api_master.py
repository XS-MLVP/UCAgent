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
import hashlib
import json
import mimetypes
import os
import pathlib
import re
import secrets
import queue
import shutil
import shlex
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
from ucagent.util.functions import find_available_port, get_abs_path_cwd_ucagent, is_port_free, load_ucagent_info
from ucagent.util.log import echo_g, warning
from ucagent.util.workspace_archive import (
    WorkspaceArchiveError,
    create_workspace_archive,
    extract_workspace_root_archive,
)

if TYPE_CHECKING:
    from ucagent.verify_pdb import VerifyPDB

_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_MODULE_RE = re.compile(r"^\s*module\s+([A-Za-z_][A-Za-z0-9_$]*)\b", re.MULTILINE)
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}
_TEXT_EXTS = {
    ".txt", ".md", ".rst", ".py", ".js", ".ts", ".css", ".html", ".htm",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".sh",
    ".bash", ".zsh", ".fish", ".v", ".sv", ".svh", ".vh", ".f", ".vhd", ".vhdl",
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
_LAUNCH_TMP_MARKER_FILE = ".ucagent_launch_tmp"
_LAUNCH_TMP_MARKER_MAGIC = "ucagent.launch.tmp-workspace.v1"
_LAUNCH_STATUS_EXPIRE_SECONDS = 600
_LAUNCH_CLEANUP_INTERVAL_SECONDS = 30
_CATEGORY_LABELS = {
    "main_verilog": "Main RTL",
    "rtl_extra": "Extra RTL",
    "source_extra": "Other Source",
    "spec": "Spec",
    "requirement": "Verification Needs",
    "config": "Config",
    "misc": "Unassigned",
}
_LAUNCH_YAML_EXTS = {".yaml", ".yml"}
_RTL_SOURCE_EXTS = {".v", ".sv", ".vh", ".svh", ".scala"}
_FILELIST_EXTS = {".v", ".sv", ".vh", ".svh"}
_PICKER_F_EXTS = {".f"}
_RTL_SPECIAL_FILES = {"filelist.txt"}
_PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
_LAUNCH_MODES = ("process", "docker", "docker_swarm", "k8s")
_LAUNCH_MODE_ALIASES = {
    "": "process",
    "local": "process",
    "subprocess": "process",
    "process": "process",
    "docker": "docker",
    "container": "docker",
    "swarm": "docker_swarm",
    "docker-swarm": "docker_swarm",
    "docker_swarm": "docker_swarm",
    "docker swarm": "docker_swarm",
    "k8s": "k8s",
    "kubernetes": "k8s",
}
_LAUNCH_MODE_LABELS = {
    "process": "Process",
    "docker": "Docker",
    "docker_swarm": "Docker Swarm",
    "k8s": "Kubernetes",
}
_CONTAINER_LAUNCH_MODES = {"docker", "docker_swarm", "k8s"}
_MASTER_SOURCE_CONTAINER_PATH = "/UCAgent"
_K8S_JOB_STATUS_JSONPATH = "{.status.active} {.status.succeeded} {.status.failed}"


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


def _config_ref_name(config_ref: str) -> str:
    raw = str(config_ref or "").strip().rstrip("/\\")
    if not raw:
        return ""
    parts = [part for part in re.split(r"[\\/]+", raw) if part]
    return parts[-1] if parts else raw


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _tail_file(path: str, max_lines: int = 200) -> str:
    if not path or not os.path.isfile(path):
        return ""
    dq: Deque[str] = collections.deque(maxlen=max_lines)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            dq.append(line)
    return "".join(dq)


def _tail_files(paths: List[str], max_lines: int = 200) -> str:
    dq: Deque[str] = collections.deque(maxlen=max_lines)
    for path in paths:
        if not path or not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                dq.append(line)
    return "".join(dq)


def _file_contains_any(path: str, markers: Tuple[str, ...]) -> bool:
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if any(marker in line for marker in markers):
                    return True
    except OSError:
        return False
    return False


def _task_stderr_tail(task: Dict[str, Any], max_lines: int = 200) -> str:
    stderr_log = task.get("stderr_log_path", "")
    web_console_log = task.get("web_console_log_path", "")
    if _file_contains_any(web_console_log, (
        "Traceback (most recent call last)",
        "UCAgent encountered an error:",
        "Failed to start Web UI:",
        "AssertionError",
    )):
        return _tail_files([stderr_log, web_console_log], max_lines=max_lines)
    return _tail_file(stderr_log, max_lines=max_lines)


def _task_logs_for_display(task: Dict[str, Any]) -> Dict[str, str]:
    return {
        "stdout": _tail_file(task.get("stdout_log_path", "")),
        "stderr": _task_stderr_tail(task),
    }


def _mask_secret(value: str) -> str:
    if value is None:
        return ""
    raw = str(value)
    if len(raw) <= 4:
        return "*" * len(raw)
    return raw[:2] + "*" * min(8, max(4, len(raw) - 4)) + raw[-2:]


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


def _plain_config_value(obj: Any) -> Any:
    if hasattr(obj, "as_dict"):
        obj = obj.as_dict()
    if isinstance(obj, dict):
        return {k: _plain_config_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plain_config_value(v) for v in obj]
    return obj


def _workspace_sync_ignore_patterns_from_cfg(cfg: Any) -> List[str]:
    if cfg is None:
        return []
    try:
        value = cfg.get_value("master_api.sync_workspace.ignore_patterns", [])
    except AttributeError:
        return []
    value = _plain_config_value(value)
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        return []
    return [pattern for pattern in (str(item).strip() for item in items) if pattern]


def _normalize_cluster_master_ip_config(value: Any) -> Any:
    env_host = str(os.environ.get("UCAGENT_LAUNCH_MASTER_IP") or "").strip()
    if env_host:
        return env_host
    default_hosts = {
        "process": "127.0.0.1",
        "docker": "host.docker.internal",
        "docker_swarm": "ucagent_master",
        "k8s": "ucagent_master",
    }
    if isinstance(value, dict):
        hosts = dict(default_hosts)
        for key, host in value.items():
            try:
                mode = _normalize_launch_mode(key)
            except ValueError:
                continue
            host = str(host or "").strip()
            if host:
                hosts[mode] = host
        return hosts
    if isinstance(value, list):
        hosts = dict(default_hosts)
        for item in value:
            if not isinstance(item, dict):
                continue
            for key, host in item.items():
                try:
                    mode = _normalize_launch_mode(key)
                except ValueError:
                    continue
                host = str(host or "").strip()
                if host:
                    hosts[mode] = host
        return hosts
    host = str(value or "").strip()
    return host or default_hosts


def _normalize_launch_mode(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_")
    mode = _LAUNCH_MODE_ALIASES.get(raw, raw)
    if mode not in _LAUNCH_MODES:
        raise ValueError(
            f"Unsupported launch_mode '{value}'. Supported values: {', '.join(_LAUNCH_MODES)}"
        )
    return mode


def _normalize_launch_mode_list(value: Any) -> List[str]:
    if value in (None, ""):
        raw_items: List[Any] = ["process"]
    elif isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = [value]
    modes: List[str] = []
    for item in raw_items:
        mode = _normalize_launch_mode(item)
        if mode not in modes:
            modes.append(mode)
    return modes or ["process"]


def _valid_env_name(name: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", str(name or "")))


def _parse_web_terminal_spec(spec: str) -> Tuple[str, int, str]:
    return _parse_service_spec(spec, "127.0.0.1", 8818)


def _resolve_web_console_spec(spec: Any) -> Tuple[str, int, str]:
    raw = "" if spec in (None, True, "__default__", "__bare__", "__enabled__") else str(spec).strip()
    if not raw or raw == "-1":
        host = "localhost"
        port = 8000
        password = ""
    else:
        addr_part = raw
        password = ""
        # Support format: [ip[:port]] [password] (space separated)
        if " " in addr_part:
            addr_part, password = addr_part.split(" ", 1)
            password = password.strip()
            addr_part = addr_part.strip()
        
        # Parse address part
        parts = addr_part.split(":", 1)
        if len(parts) < 2:
            raise ValueError(
                f"Invalid --web-console value '{raw}'. Expected format: [host[:port]] [password]"
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


def _fix_reported_tcp_url(url: str, client_ip: str) -> str:
    if not url or not client_ip:
        return url
    raw = str(url).strip()

    def _port_and_tail(netloc: str, tail: str) -> str:
        if netloc.startswith("["):
            end = netloc.find("]")
            rest = netloc[end + 1:] if end >= 0 else ""
            return rest + tail if rest.startswith(":") else tail
        if ":" in netloc:
            return ":" + netloc.rsplit(":", 1)[1] + tail
        return tail

    m = re.match(r"^(https?://)([^/?#]+)(.*)$", raw)
    if m:
        return m.group(1) + client_ip + _port_and_tail(m.group(2), m.group(3))
    m = re.match(r"^([^/?#]+)(.*)$", raw)
    if m:
        return client_ip + _port_and_tail(m.group(1), m.group(2))
    return raw


def _sync_reported_service_tcp_url(service: Dict[str, Any], client_ip: str) -> Dict[str, Any]:
    service = _copy_jsonable(service or {})
    if service.get("tcp_url"):
        service["tcp_url"] = _fix_reported_tcp_url(str(service["tcp_url"]), client_ip)
    if service.get("base_url_internal"):
        service["base_url_internal"] = _fix_reported_tcp_url(str(service["base_url_internal"]), client_ip)
    if service.get("host") and client_ip:
        service["host"] = client_ip
    if service.get("host") and service.get("port") and not service.get("tcp_url"):
        service["tcp_url"] = f"{service['host']}:{service['port']}"
    return service


def _is_text_file(path: str) -> bool:
    ext = pathlib.Path(path).suffix.lower()
    return ext in _TEXT_EXTS


def _is_picker_f_file(path: str) -> bool:
    return pathlib.Path(path or "").suffix.lower() in _PICKER_F_EXTS


def _path_is_under(root: str, path: str) -> bool:
    if not root or not path:
        return False
    root_abs = os.path.abspath(root)
    path_abs = os.path.abspath(path)
    return path_abs == root_abs or path_abs.startswith(root_abs + os.sep)


def _category_label(category: str) -> str:
    return _CATEGORY_LABELS.get(category, _CATEGORY_LABELS["misc"])


def _parse_module_names(text: str) -> List[str]:
    seen: List[str] = []
    for name in _MODULE_RE.findall(text):
        if name not in seen:
            seen.append(name)
    return seen


def _yaml_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _yaml_mapping(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {_yaml_key(key): item for key, item in value.items()}


def _yaml_scalar(value: Any) -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value).strip()


def _yaml_first_scalar(mapping: Dict[str, Any], aliases: List[str]) -> str:
    normalized = _yaml_mapping(mapping)
    for alias in aliases:
        value = _yaml_scalar(normalized.get(_yaml_key(alias)))
        if value:
            return value
    return ""


def _yaml_path_values(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        mapping = _yaml_mapping(value)
        for key in ("path", "paths", "file", "files", "filename", "name"):
            if key in mapping:
                return _yaml_path_values(mapping[key])
        return []
    if isinstance(value, (list, tuple, set)):
        result: List[str] = []
        for item in value:
            result.extend(_yaml_path_values(item))
        return result
    text = str(value).strip()
    return [text] if text else []


def _yaml_arg_values(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    try:
        return shlex.split(text)
    except ValueError:
        return [text]


def _launch_yaml_bucket(value: Any) -> str:
    key = _yaml_key(value)
    if key in {"main", "main_rtl", "main_verilog", "top", "top_rtl"}:
        return "main"
    if key in {"filelist", "filelists", "f", "f_filelist", "f_filelists", "picker_filelist", "picker_filelists"}:
        return "filelist"
    if key in {"rtl", "rtls", "rtl_extra", "verilog", "verilog_files", "source_rtl"}:
        return "rtl"
    if key in {"source_extra", "other_source", "sources_extra", "extra_source"}:
        return "source_extra"
    if key in {"requirement", "requirements", "verification", "verification_need", "verification_needs", "needs"}:
        return "requirement"
    if key in {"doc", "docs", "document", "documents", "documentation"}:
        return "doc"
    if key in {"spec", "specs", "specification", "specifications"}:
        return "spec"
    if key in {"config", "configs", "cfg", "config_file", "config_files"}:
        return "config"
    if key in {"misc", "other", "unassigned"}:
        return "misc"
    return ""


def _is_rtl_workspace_file(name: str, category: str) -> bool:
    lower_name = os.path.basename(name or "").lower()
    suffix = pathlib.Path(lower_name).suffix.lower()
    if category in {"main_verilog", "rtl_extra", "source_extra"}:
        return True
    if lower_name in _RTL_SPECIAL_FILES:
        return True
    return suffix in _RTL_SOURCE_EXTS or suffix in _FILELIST_EXTS or suffix in _PICKER_F_EXTS


def _normalize_arg_list(value: Any) -> List[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            return [item for item in shlex.split(value) if item]
        except ValueError:
            return [item.strip() for item in value.split() if item.strip()]
    if isinstance(value, (list, tuple)):
        result: List[str] = []
        for item in value:
            if item in (None, ""):
                continue
            if isinstance(item, (list, tuple)):
                result.extend(_normalize_arg_list(item))
            else:
                text = str(item).strip()
                if text:
                    result.append(text)
        return result
    text = str(value).strip()
    return [text] if text else []


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
        cfg: Any = None,
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

        self.cfg = cfg if cfg is not None else get_config(workspace=self.workspace)

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
        self._workspace_cleanup_lock = threading.Lock()

        self._running = False
        self.started_at: Optional[float] = None
        self._tcp_server = None
        self._tcp_thread: Optional[threading.Thread] = None
        self._sock_server = None
        self._sock_thread: Optional[threading.Thread] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_stop = threading.Event()
        self._online_cache: Dict[str, bool] = {}
        self._proxy_session = None
        self._dirty = False
        self._last_saved = 0.0
        self._last_launch_cleanup = 0.0

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

    def _agent_is_online(self, agent: Dict[str, Any]) -> bool:
        return not bool(agent.get("client_exit")) and (_now() - agent.get("last_seen", 0)) <= self.offline_timeout

    def _agent_status(self, agent: Dict[str, Any]) -> str:
        if bool(agent.get("client_exit")):
            return "exit"
        return "online" if self._agent_is_online(agent) else "offline"

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

    def _compiled_workspace_dir(self, ws: Dict[str, Any]) -> str:
        compile_info = ws.get("compile") or {}
        if compile_info.get("status") != "success":
            raise ValueError("DUT workspace is not ready. Compile DUT successfully before downloading.")
        workspace_dir = os.path.abspath(ws.get("workspace_dir", ""))
        picker_workspace = os.path.abspath(
            compile_info.get("picker_workspace") or ws.get("picker_workspace") or os.path.join(workspace_dir, "workspace")
        )
        if not (picker_workspace == workspace_dir or picker_workspace.startswith(workspace_dir + os.sep)):
            raise ValueError("Compiled workspace path is outside the launch workspace")
        if not os.path.isdir(picker_workspace):
            raise ValueError("Compiled workspace directory not found")
        return picker_workspace

    def _create_compiled_workspace_archive(self, ws: Dict[str, Any], archive_stem: str = "") -> Tuple[str, str, str]:
        picker_workspace = self._compiled_workspace_dir(ws)
        archive_stem = _safe_name(
            archive_stem or os.path.basename(os.path.abspath(ws.get("workspace_dir", ""))),
            "workspace",
        )
        return create_workspace_archive(
            picker_workspace,
            archive_stem=archive_stem,
            root_name="workspace",
            ignore_patterns=_workspace_sync_ignore_patterns_from_cfg(self.cfg),
        )

    def _workspace_archive_download_url(self, archive_ref: str, launch_mode: str, master_host: str = "") -> str:
        if not self.tcp:
            raise ValueError("Current master has no TCP listener; cannot provide workspace archive URL")
        host = str(master_host or "").strip() or self._cluster_master_ip(launch_mode)
        return f"http://{host}:{self.port}/api/workspace/{archive_ref}.tar.gz"

    def _sync_workspace_back_enabled(self) -> bool:
        default_args = _plain_config_value(self.cfg.get_value("launch.default_args", {}) or {})
        if isinstance(default_args, dict) and "use_zip_workspace" in default_args:
            return _as_bool(default_args.get("use_zip_workspace"), True)
        return _as_bool(self.cfg.get_value("launch.default_args.use_zip_workspace", True), True)

    def _task_uses_zip_workspace(self, task: Dict[str, Any]) -> bool:
        structured = task.get("cli_args_structured") or {}
        if isinstance(structured, dict) and "use_zip_workspace" in structured:
            return _as_bool(structured.get("use_zip_workspace"), True)
        return True

    def _resolve_workspace_sync_target(self, agent_id: str) -> Dict[str, Any]:
        agent_id = str(agent_id or "").strip()
        if not agent_id:
            raise ValueError("'agent_id' is required")
        with self._agents_lock:
            agents = list(self._agents.values())
            agent = next((item for item in agents if str(item.get("id") or "").strip() == agent_id), None)
        with self._tasks_lock:
            tasks = list(self._tasks.values())

        def task_sort_key(task: Dict[str, Any]) -> float:
            try:
                return float(task.get("started_at") or task.get("created_at") or 0)
            except (TypeError, ValueError):
                return 0.0

        matched_tasks: List[Dict[str, Any]] = []
        for task in sorted(tasks, key=task_sort_key, reverse=True):
            if str(task.get("client_id") or "").strip() == agent_id:
                matched_tasks.append(task)
                continue
            if str(task.get("registered_agent_id") or "").strip() == agent_id:
                matched_tasks.append(task)
                continue
            if agent is not None and self._agent_for_task_unlocked(task, [agent]) is not None:
                matched_tasks.append(task)
        if not matched_tasks:
            raise ValueError(f"No managed task is associated with agent '{agent_id}'")

        task = matched_tasks[0]
        if not self._task_uses_zip_workspace(task):
            raise ValueError("The matched task was launched with a shared workspace; sync-back is not needed")
        workspace_id = str(task.get("workspace_id") or "").strip()
        if not workspace_id:
            raise ValueError(f"Task '{task.get('task_id')}' has no workspace_id")
        ws = self._get_workspace(workspace_id)
        target_dir = self._compiled_workspace_dir(ws)
        return {
            "agent": agent,
            "task": task,
            "workspace": ws,
            "target_dir": target_dir,
        }

    def _workspace_sync_status(self, agent_id: str = "") -> Dict[str, Any]:
        agent_id = str(agent_id or "").strip()
        data: Dict[str, Any] = {
            "enabled": False,
            "use_zip_workspace": self._sync_workspace_back_enabled(),
            "agent_id": agent_id,
            "reason": "",
        }
        if not data["use_zip_workspace"]:
            data["reason"] = "Disabled because launch.default_args.use_zip_workspace is false"
            return data
        if not agent_id:
            data["enabled"] = True
            data["reason"] = "Sync-back is globally available for zip workspace launches"
            return data
        try:
            target = self._resolve_workspace_sync_target(agent_id)
        except (KeyError, ValueError) as exc:
            data["reason"] = str(exc)
            return data
        task = target["task"]
        ws = target["workspace"]
        data.update({
            "enabled": True,
            "reason": "Sync-back is available",
            "task_id": task.get("task_id", ""),
            "workspace_id": ws.get("workspace_id", ""),
            "target_dir": target["target_dir"],
            "dut_name": task.get("dut_name", ""),
            "selected_module": task.get("selected_module", ""),
        })
        return data

    def _remove_path(self, path: str) -> None:
        if os.path.islink(path) or os.path.isfile(path):
            os.unlink(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)

    def _replace_directory(self, source_dir: str, target_dir: str) -> None:
        source_dir = os.path.abspath(source_dir)
        target_dir = os.path.abspath(target_dir)
        if not os.path.isdir(source_dir):
            raise ValueError(f"Source directory not found: {source_dir}")
        if os.path.exists(target_dir) and not os.path.isdir(target_dir):
            raise ValueError(f"Sync target exists but is not a directory: {target_dir}")
        parent = os.path.dirname(target_dir)
        os.makedirs(parent, exist_ok=True)
        base = os.path.basename(target_dir.rstrip(os.sep)) or "workspace"
        token = secrets.token_hex(6)
        tmp_target = os.path.join(parent, f".{base}.sync-{token}.new")
        backup_target = os.path.join(parent, f".{base}.sync-{token}.bak")
        moved_old = False
        try:
            if os.path.exists(tmp_target):
                self._remove_path(tmp_target)
            shutil.move(source_dir, tmp_target)
            if os.path.exists(target_dir) or os.path.islink(target_dir):
                os.rename(target_dir, backup_target)
                moved_old = True
            os.rename(tmp_target, target_dir)
        except Exception:
            if os.path.exists(tmp_target) or os.path.islink(tmp_target):
                self._remove_path(tmp_target)
            if moved_old and not (os.path.exists(target_dir) or os.path.islink(target_dir)) and (
                os.path.exists(backup_target) or os.path.islink(backup_target)
            ):
                os.rename(backup_target, target_dir)
            raise
        else:
            if moved_old and (os.path.exists(backup_target) or os.path.islink(backup_target)):
                self._remove_path(backup_target)

    def _restore_workspace_archive_to_target(self, archive_path: str, target_dir: str) -> None:
        staging_dir = tempfile.mkdtemp(prefix="ucagent_workspace_sync_")
        try:
            extracted_root = extract_workspace_root_archive(archive_path, staging_dir, root_name="workspace")
            self._replace_directory(extracted_root, target_dir)
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    def _sync_workspace_archive_back(self, agent_id: str, archive_path: str, archive_size: int = 0) -> Dict[str, Any]:
        if not self._sync_workspace_back_enabled():
            raise ValueError("Workspace sync-back is disabled because launch.default_args.use_zip_workspace is false")
        target = self._resolve_workspace_sync_target(agent_id)
        task = target["task"]
        ws = target["workspace"]
        target_dir = target["target_dir"]
        self._restore_workspace_archive_to_target(archive_path, target_dir)
        sync_info = {
            "agent_id": str(agent_id or "").strip(),
            "task_id": task.get("task_id", ""),
            "workspace_id": ws.get("workspace_id", ""),
            "target_dir": target_dir,
            "archive_size": int(archive_size or 0),
            "synced_at": _now(),
        }
        with self._workspaces_lock:
            ws_locked = self._workspaces.get(ws.get("workspace_id"))
            if ws_locked is not None:
                ws_locked["last_sync_back"] = dict(sync_info)
        with self._tasks_lock:
            task_locked = self._tasks.get(task.get("task_id"))
            if task_locked is not None:
                task_locked["workspace_sync_back"] = dict(sync_info)
        self._mark_dirty()
        _master_log(
            f"Workspace sync-back from agent '{agent_id}' restored task '{sync_info['task_id']}' "
            f"to {target_dir}"
        )
        return sync_info

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

    def _get_workspace_by_id_or_dirname(self, workspace_ref: str) -> Dict[str, Any]:
        try:
            return self._get_workspace(workspace_ref)
        except KeyError:
            pass
        with self._workspaces_lock:
            for ws in self._workspaces.values():
                if (
                    os.path.basename(os.path.abspath(ws.get("workspace_dir", ""))) == workspace_ref
                    or str(ws.get("task_id") or "").strip() == workspace_ref
                ):
                    if self._normalize_workspace_locked(ws):
                        self._mark_dirty()
                    return ws
        raise KeyError(f"Workspace '{workspace_ref}' not found")

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
        workspace_id = str(ws.get("workspace_id") or "").strip()
        has_tmp_marker = bool(root and os.path.isdir(root) and self._launch_tmp_marker_matches(workspace_id, root))
        status_data = self._read_launch_status(root) if has_tmp_marker else {}
        if "compile" not in ws:
            ws["compile"] = {}
            changed = True
        if "picker_workspace" not in ws and root:
            ws["picker_workspace"] = os.path.join(root, "workspace")
            changed = True
        if not ws.get("base_root"):
            ws["base_root"] = self.workspace
            changed = True
        if not ws.get("task_id") and workspace_id:
            ws["task_id"] = workspace_id
            changed = True
        file_status = str(status_data.get("status") or "").strip()
        launch_status = str(ws.get("launch_status") or ws.get("status") or file_status or "").strip()
        if file_status == "launched":
            launch_status = "launched"
        if launch_status == "created":
            launch_status = "active"
        if launch_status not in {"reserved", "active", "released", "launched"}:
            launch_status = "active" if files or ws.get("compile") else "reserved"
        if ws.get("launch_status") != launch_status:
            ws["launch_status"] = launch_status
            changed = True
        materialized = bool(has_tmp_marker)
        if ws.get("materialized") != materialized:
            ws["materialized"] = materialized
            changed = True
        if "materialized_at" not in ws:
            ws["materialized_at"] = ws.get("created_at", 0) if materialized else 0
            changed = True
        if not ws.get("last_seen"):
            ws["last_seen"] = status_data.get("updated_at") or ws.get("created_at") or _now()
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
                relpath = os.path.relpath(stored_path, root) if stored_path and _path_is_under(root, stored_path) else ""
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
            "source_f_filelist_paths": list(compile_info.get("source_f_filelist_paths") or []),
            "f_filelist_paths": list(compile_info.get("f_filelist_paths") or []),
            "generated_filelist": bool(compile_info.get("generated_filelist")),
            "config_path": compile_info.get("config_path", ""),
            "readme_path": compile_info.get("readme_path", ""),
            "compiled_at": compile_info.get("compiled_at", 0),
            "copied_files": list(compile_info.get("copied_files") or []),
            "picker_command": list(compile_info.get("picker_command") or []),
            "picker_extra_args": list(compile_info.get("picker_extra_args") or []),
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
        workspace_dir = ws.get("workspace_dir", "")
        stored_relpath = item.get("stored_relpath", "")
        if not stored_relpath and stored_path and _path_is_under(workspace_dir, stored_path):
            stored_relpath = os.path.relpath(stored_path, workspace_dir)
        return {
            "item_id": item.get("item_id", ""),
            "name": name,
            "original_name": name,
            "category": item.get("category", "misc"),
            "tag_label": _category_label(item.get("category", "misc")),
            "source": item.get("source", ""),
            "source_path": item.get("source_path", ""),
            "stored_path": stored_path,
            "stored_relpath": stored_relpath,
            "created_at": item.get("created_at", 0),
            "size": size,
            "exists": exists,
            "file_type": suffix or "file",
            "is_text": _is_text_file(stored_path) if exists else False,
            "external_ref": bool(stored_path and not _path_is_under(workspace_dir, stored_path)),
        }

    def _workspace_public(self, ws: Dict[str, Any]) -> Dict[str, Any]:
        files = [self._workspace_file_public(ws, item) for item in ws.get("files", [])]
        files.sort(key=lambda item: (item.get("created_at", 0), item.get("name", "")), reverse=True)
        return {
            "workspace_id": ws.get("workspace_id", ""),
            "workspace_dir": ws.get("workspace_dir", ""),
            "base_root": ws.get("base_root", ""),
            "created_at": ws.get("created_at", 0),
            "materialized": bool(ws.get("materialized")),
            "materialized_at": ws.get("materialized_at", 0),
            "launch_status": ws.get("launch_status", ""),
            "last_seen": ws.get("last_seen", 0),
            "task_id": ws.get("task_id", ""),
            "files": files,
            "compile": self._workspace_compile_public(ws),
            "launch_yaml": _copy_jsonable(ws.get("launch_yaml", {})) if isinstance(ws.get("launch_yaml"), dict) else {},
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

    def _create_workspace(self) -> Dict[str, Any]:
        base_root = self.workspace
        with self._workspaces_lock:
            existing_workspace_ids = set(self._workspaces.keys())
        with self._tasks_lock:
            existing_task_ids = set(self._tasks.keys())
        while True:
            workspace_id = secrets.token_hex(8)
            if workspace_id in existing_workspace_ids or workspace_id in existing_task_ids:
                continue
            ws_dir = os.path.join(base_root, workspace_id)
            if not os.path.exists(ws_dir):
                break
        picker_workspace = os.path.join(ws_dir, "workspace")
        now = _now()
        ws = {
            "workspace_id": workspace_id,
            "workspace_dir": ws_dir,
            "picker_workspace": picker_workspace,
            "base_root": base_root,
            "created_at": now,
            "last_seen": now,
            "materialized": False,
            "materialized_at": 0,
            "launch_status": "reserved",
            "files": [],
            "task_id": workspace_id,
            "compile": {},
        }
        with self._workspaces_lock:
            self._workspaces[workspace_id] = ws
        self._mark_dirty()
        return ws

    def _safe_launch_workspace_dir(self, workspace_id: str, ws_dir: str) -> bool:
        if not ws_dir:
            return False
        base_root = os.path.abspath(self.workspace)
        root = os.path.abspath(ws_dir)
        if root == base_root or not _path_is_under(base_root, root):
            return False
        name = os.path.basename(root)
        workspace_id = str(workspace_id or "").strip()
        if workspace_id:
            return name == workspace_id
        return bool(name.startswith("ucagent_launch_") or re.fullmatch(r"[0-9a-f]{16}", name))

    def _launch_tmp_marker_path(self, ws_dir: str) -> str:
        return os.path.join(ws_dir, _LAUNCH_TMP_MARKER_FILE)

    def _read_launch_tmp_marker(self, ws_dir: str) -> Dict[str, Any]:
        marker_file = self._launch_tmp_marker_path(ws_dir)
        try:
            with open(marker_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_launch_tmp_marker(self, ws_dir: str, workspace_id: str, task_id: str = "") -> None:
        workspace_id = str(workspace_id or "").strip()
        task_id = str(task_id or workspace_id or "").strip()
        now = _now()
        existing = self._read_launch_tmp_marker(ws_dir)
        created_at = existing.get("created_at") if existing.get("magic") == _LAUNCH_TMP_MARKER_MAGIC else None
        if not isinstance(created_at, (int, float)) or created_at <= 0:
            created_at = now
        marker_data = {
            "magic": _LAUNCH_TMP_MARKER_MAGIC,
            "version": 1,
            "temporary": True,
            "workspace_id": workspace_id,
            "task_id": task_id,
            "base_root": os.path.abspath(self.workspace),
            "workspace_dir": os.path.abspath(ws_dir),
            "created_at": created_at,
            "updated_at": now,
        }
        marker_file = self._launch_tmp_marker_path(ws_dir)
        tmp_file = f"{marker_file}.tmp-{secrets.token_hex(6)}"
        try:
            with open(tmp_file, "w", encoding="utf-8") as fh:
                json.dump(marker_data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_file, marker_file)
        finally:
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass

    def _launch_tmp_marker_matches(self, workspace_id: str, ws_dir: str) -> bool:
        workspace_id = str(workspace_id or "").strip()
        if not self._safe_launch_workspace_dir(workspace_id, ws_dir):
            return False
        marker = self._read_launch_tmp_marker(ws_dir)
        if marker.get("magic") != _LAUNCH_TMP_MARKER_MAGIC or marker.get("temporary") is not True:
            return False
        marker_workspace_id = str(marker.get("workspace_id") or "").strip()
        if not marker_workspace_id:
            return False
        if workspace_id and marker_workspace_id != workspace_id:
            return False
        if os.path.basename(os.path.abspath(ws_dir)) != marker_workspace_id:
            return False
        marker_base_root = str(marker.get("base_root") or "").strip()
        if not marker_base_root or os.path.realpath(os.path.abspath(marker_base_root)) != os.path.realpath(os.path.abspath(self.workspace)):
            return False
        marker_workspace_dir = str(marker.get("workspace_dir") or "").strip()
        if marker_workspace_dir and os.path.realpath(os.path.abspath(marker_workspace_dir)) != os.path.realpath(os.path.abspath(ws_dir)):
            return False
        return True

    def _touch_workspace_launch_session(self, workspace_id: str, status: str = "") -> Dict[str, Any]:
        with self._workspace_cleanup_lock:
            now = _now()
            ws_dir = ""
            status_val = ""
            task_id = ""
            materialized = False
            with self._workspaces_lock:
                ws = self._workspaces.get(workspace_id)
                if ws is None:
                    raise KeyError(f"Workspace '{workspace_id}' not found")
                self._normalize_workspace_locked(ws)
                status_val = str(status or ws.get("launch_status") or "active").strip()
                if status_val == "release":
                    status_val = "released"
                if ws.get("launch_status") == "launched" and status_val != "launched":
                    status_val = "launched"
                if status_val == "created":
                    status_val = "active"
                if status_val not in {"reserved", "active", "released", "launched"}:
                    status_val = "active"
                ws["launch_status"] = status_val
                ws["last_seen"] = now
                if status_val == "released" and not ws.get("released_at"):
                    ws["released_at"] = now
                ws_dir = str(ws.get("workspace_dir") or "")
                task_id = str(ws.get("task_id") or "")
                materialized = bool(ws_dir and os.path.isdir(ws_dir) and self._launch_tmp_marker_matches(workspace_id, ws_dir))
                ws["materialized"] = materialized
            if materialized:
                if self._launch_tmp_marker_matches(workspace_id, ws_dir):
                    self._write_launch_status(ws_dir, status_val, workspace_id=workspace_id, task_id=task_id)
                else:
                    warning(f"Skip launch status update for unmarked launch workspace path '{ws_dir}'")
        self._mark_dirty()
        return self._get_workspace(workspace_id)

    def _ensure_workspace_materialized(self, workspace_id: str, status: str = "active") -> Dict[str, Any]:
        with self._workspace_cleanup_lock:
            with self._workspaces_lock:
                ws = self._workspaces.get(workspace_id)
                if ws is None:
                    raise KeyError(f"Workspace '{workspace_id}' not found")
                self._normalize_workspace_locked(ws)
                ws_dir = str(ws.get("workspace_dir") or "")
                picker_workspace = str(ws.get("picker_workspace") or os.path.join(ws_dir, "workspace"))
                task_id = str(ws.get("task_id") or workspace_id)
            if not self._safe_launch_workspace_dir(workspace_id, ws_dir):
                raise ValueError(f"Refusing to create unsafe launch workspace directory: {ws_dir}")
            if os.path.exists(ws_dir) and not self._launch_tmp_marker_matches(workspace_id, ws_dir):
                raise ValueError(f"Refusing to use unmarked launch workspace directory: {ws_dir}")
            os.makedirs(picker_workspace, exist_ok=True)
            self._write_launch_tmp_marker(ws_dir, workspace_id=workspace_id, task_id=task_id)
            now = _now()
            with self._workspaces_lock:
                ws = self._workspaces.get(workspace_id)
                if ws is None:
                    raise KeyError(f"Workspace '{workspace_id}' not found")
                ws["workspace_dir"] = ws_dir
                ws["picker_workspace"] = picker_workspace
                ws["materialized"] = True
                if not ws.get("materialized_at"):
                    ws["materialized_at"] = now
                ws["last_seen"] = now
                if ws.get("launch_status") != "launched":
                    ws["launch_status"] = status if status in {"reserved", "active", "released", "launched"} else "active"
                status_val = str(ws.get("launch_status") or "active")
                task_id = str(ws.get("task_id") or task_id)
            self._write_launch_status(ws_dir, status_val, workspace_id=workspace_id, task_id=task_id)
        self._mark_dirty()
        return self._get_workspace(workspace_id)

    def _mark_workspace_launched(self, workspace_id: str, task_id: str) -> None:
        try:
            ws = self._touch_workspace_launch_session(workspace_id, status="launched")
        except KeyError:
            return
        ws_dir = str(ws.get("workspace_dir") or "")
        if ws_dir and os.path.isdir(ws_dir):
            if self._launch_tmp_marker_matches(workspace_id, ws_dir):
                self._write_launch_status(ws_dir, "launched", workspace_id=workspace_id, task_id=task_id)
            else:
                warning(f"Skip launch status update for unmarked launched workspace path '{ws_dir}'")

    def _cleanup_stale_workspaces(self) -> int:
        base_root = self.workspace
        cleaned = 0
        now = _now()
        with self._tasks_lock:
            task_ids = set(self._tasks.keys())
            task_workspace_ids = {
                str(task.get("workspace_id") or "").strip()
                for task in self._tasks.values()
                if str(task.get("workspace_id") or "").strip()
            }
        with self._compile_runtime_lock:
            running_compile_ids = {
                workspace_id
                for workspace_id, runtime in self._compile_runtime.items()
                if runtime.get("status") == "running"
            }
        stale_workspace_ids: List[Tuple[str, str]] = []
        with self._workspaces_lock:
            for workspace_id, ws in list(self._workspaces.items()):
                self._normalize_workspace_locked(ws)
                task_id = str(ws.get("task_id") or "").strip()
                launched = (
                    ws.get("launch_status") == "launched"
                    or workspace_id in task_workspace_ids
                    or task_id in task_ids
                )
                if launched or workspace_id in running_compile_ids:
                    continue
                last_seen = float(ws.get("last_seen") or ws.get("created_at") or 0)
                released = ws.get("launch_status") == "released"
                if not released and now - last_seen <= _LAUNCH_STATUS_EXPIRE_SECONDS:
                    continue
                stale_workspace_ids.append((workspace_id, str(ws.get("workspace_dir") or "")))
        for workspace_id, ws_dir in stale_workspace_ids:
            with self._workspace_cleanup_lock:
                with self._tasks_lock:
                    task_ids = set(self._tasks.keys())
                    task_workspace_ids = {
                        str(task.get("workspace_id") or "").strip()
                        for task in self._tasks.values()
                        if str(task.get("workspace_id") or "").strip()
                    }
                with self._compile_runtime_lock:
                    running_compile_ids = {
                        wid
                        for wid, runtime in self._compile_runtime.items()
                        if runtime.get("status") == "running"
                    }
                with self._workspaces_lock:
                    ws = self._workspaces.get(workspace_id)
                    if ws is None:
                        continue
                    self._normalize_workspace_locked(ws)
                    task_id = str(ws.get("task_id") or "").strip()
                    launched = (
                        ws.get("launch_status") == "launched"
                        or workspace_id in task_workspace_ids
                        or task_id in task_ids
                    )
                    last_seen = float(ws.get("last_seen") or ws.get("created_at") or 0)
                    released = ws.get("launch_status") == "released"
                    if (
                        launched
                        or workspace_id in running_compile_ids
                        or (not released and now - last_seen <= _LAUNCH_STATUS_EXPIRE_SECONDS)
                    ):
                        continue
                    ws_dir = str(ws.get("workspace_dir") or ws_dir)
                removed = False
                if ws_dir and os.path.isdir(ws_dir):
                    if not self._launch_tmp_marker_matches(workspace_id, ws_dir):
                        warning(f"Skip unmarked stale launch workspace cleanup path '{ws_dir}'")
                        continue
                    try:
                        shutil.rmtree(ws_dir)
                        removed = True
                    except OSError as exc:
                        warning(f"Failed to clean stale launch workspace '{ws_dir}': {exc}")
                        continue
                else:
                    removed = True
                if removed:
                    with self._workspaces_lock:
                        self._workspaces.pop(workspace_id, None)
                    with self._compile_runtime_lock:
                        self._compile_runtime.pop(workspace_id, None)
                    cleaned += 1
                    self._mark_dirty()
        if os.path.isdir(base_root):
            known_dirs = set()
            with self._workspaces_lock:
                known_dirs = {
                    os.path.abspath(str(ws.get("workspace_dir") or ""))
                    for ws in self._workspaces.values()
                    if ws.get("workspace_dir")
                }
            with self._tasks_lock:
                known_dirs.update(
                    os.path.abspath(str(task.get("workspace_dir") or ""))
                    for task in self._tasks.values()
                    if task.get("workspace_dir")
                )
            for entry in os.listdir(base_root):
                ws_dir = os.path.abspath(os.path.join(base_root, entry))
                if ws_dir in known_dirs or not os.path.isdir(ws_dir):
                    continue
                marker = self._read_launch_tmp_marker(ws_dir)
                marker_workspace_id = str(marker.get("workspace_id") or "").strip()
                if not marker_workspace_id or not self._launch_tmp_marker_matches(marker_workspace_id, ws_dir):
                    continue
                status = self._read_launch_status(ws_dir)
                status_val = status.get("status", "unknown")
                updated_at = status.get("updated_at", 0)
                if status_val == "launched":
                    continue
                if status_val == "released" or now - updated_at > _LAUNCH_STATUS_EXPIRE_SECONDS:
                    try:
                        shutil.rmtree(ws_dir)
                        cleaned += 1
                    except OSError as exc:
                        warning(f"Failed to clean stale launch workspace '{ws_dir}': {exc}")
        return cleaned

    def _write_launch_status(self, ws_dir: str, status: str, workspace_id: str = "", task_id: str = "") -> None:
        status_file = os.path.join(ws_dir, _LAUNCH_STATUS_FILE)
        status_data = {
            "status": status,
            "updated_at": _now(),
            "workspace_id": workspace_id,
            "task_id": task_id,
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
        workspace_dir = self._get_workspace(workspace_id)["workspace_dir"]
        stored_relpath = (
            os.path.relpath(stored_path, workspace_dir)
            if _path_is_under(workspace_dir, stored_path)
            else ""
        )
        item = {
            "item_id": secrets.token_hex(8),
            "category": category,
            "source": source,
            "source_path": src_path,
            "stored_path": stored_path,
            "stored_relpath": stored_relpath,
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
        ws = self._ensure_workspace_materialized(workspace_id, status="active")
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
        self._ensure_workspace_materialized(workspace_id, status="active")
        if _is_picker_f_file(source_path):
            return self._record_workspace_file(
                workspace_id,
                category=category,
                source="server",
                src_path=source_path,
                stored_path=os.path.abspath(source_path),
                original_name=os.path.basename(source_path),
            )
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

    def _find_workspace_item_by_source_path(self, ws: Dict[str, Any], source_path: str) -> Optional[Dict[str, Any]]:
        wanted = os.path.abspath(source_path)
        for item in ws.get("files", []):
            source = item.get("source_path") or item.get("stored_path") or ""
            if source and os.path.abspath(source) == wanted:
                return item
        return None

    def _resolve_launch_yaml_ref(self, yaml_path: str, raw_path: str, *, require_file: bool = True) -> str:
        raw = str(raw_path or "").strip()
        if not raw:
            raise ValueError("YAML file path entry is empty")
        expanded = os.path.expanduser(raw)
        if os.path.isabs(expanded):
            resolved = os.path.abspath(expanded)
        else:
            resolved = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(yaml_path)), expanded))
        if require_file and not os.path.isfile(resolved):
            raise ValueError(f"YAML referenced file does not exist: {raw} -> {resolved}")
        return resolved

    def _append_launch_yaml_import(
        self,
        imports: List[Dict[str, Any]],
        seen: set,
        *,
        yaml_path: str,
        category: str,
        raw_path: str,
        source_key: str,
    ) -> None:
        if category not in _CATEGORY_DIRS:
            category = "misc"
        resolved = self._resolve_launch_yaml_ref(yaml_path, raw_path)
        if category == "main_verilog" and pathlib.Path(resolved).suffix.lower() not in _FILELIST_EXTS:
            raise ValueError(f"main_rtl must be a Verilog/SystemVerilog file: {raw_path}")
        identity = os.path.realpath(resolved)
        if identity in seen:
            return
        seen.add(identity)
        imports.append({
            "category": category,
            "path": resolved,
            "raw_path": raw_path,
            "source_key": source_key,
        })

    def _load_launch_yaml_spec(self, yaml_path: str) -> Dict[str, Any]:
        if pathlib.Path(yaml_path).suffix.lower() not in _LAUNCH_YAML_EXTS:
            raise ValueError("Launch spec must be a .yaml or .yml file")
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - yaml is a project dependency
            raise ValueError("PyYAML is required to read launch YAML files") from exc
        try:
            with open(yaml_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except Exception as exc:
            raise ValueError(f"Failed to read launch YAML file: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Launch YAML root must be a mapping")
        return data

    def _normalize_launch_yaml_spec(self, yaml_path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        top = _yaml_mapping(data)
        buckets: Dict[str, List[str]] = {
            "main": [],
            "filelist": [],
            "rtl": [],
            "source_extra": [],
            "requirement": [],
            "doc": [],
            "spec": [],
            "config": [],
            "misc": [],
        }

        def add_to_bucket(bucket: str, value: Any) -> None:
            if not bucket:
                return
            buckets.setdefault(bucket, []).extend(_yaml_path_values(value))

        files_node = top.get("files")
        if isinstance(files_node, dict):
            for key, value in _yaml_mapping(files_node).items():
                add_to_bucket(_launch_yaml_bucket(key), value)
        elif isinstance(files_node, list):
            for entry in files_node:
                if isinstance(entry, dict):
                    entry_map = _yaml_mapping(entry)
                    bucket = _launch_yaml_bucket(
                        entry_map.get("type")
                        or entry_map.get("category")
                        or entry_map.get("tag")
                        or entry_map.get("kind")
                    )
                    add_to_bucket(bucket or "misc", entry)
                else:
                    add_to_bucket("misc", entry)
        elif files_node is not None:
            raise ValueError("'files' in launch YAML must be a mapping or list")

        field_keys = {
            "files",
            "task",
            "task_name",
            "dut",
            "dut_name",
            "target_dut",
            "module",
            "top_module",
            "selected_module",
            "main_module",
            "dut_module",
            "config",
            "config_path",
            "cfg",
            "backend",
            "output",
            "launch_mode",
            "workspace_base",
            "master",
            "picker_args",
            "picker_extra_args",
        }
        for key, value in top.items():
            if key in field_keys:
                continue
            add_to_bucket(_launch_yaml_bucket(key), value)

        fields: Dict[str, Any] = {}
        scalar_fields = {
            "task_name": ["task_name", "task"],
            "dut_name": ["dut_name", "dut", "target_dut"],
            "selected_module": ["selected_module", "module", "top_module", "main_module", "dut_module"],
            "backend": ["backend"],
            "output": ["output"],
            "launch_mode": ["launch_mode"],
            "workspace_base": ["workspace_base"],
            "master": ["master"],
        }
        for target, aliases in scalar_fields.items():
            value = _yaml_first_scalar(data, aliases)
            if value:
                fields[target] = value

        picker_args = _yaml_arg_values(top.get("picker_args", top.get("picker_extra_args")))
        if picker_args:
            fields["picker_args"] = picker_args

        raw_config = _yaml_first_scalar(data, ["config", "config_path", "cfg"])
        if raw_config:
            config_candidate = self._resolve_launch_yaml_ref(yaml_path, raw_config, require_file=False)
            if os.path.isfile(config_candidate):
                buckets["config"].append(raw_config)
                fields["config"] = os.path.basename(config_candidate)
            else:
                fields["config"] = raw_config
        elif buckets["config"]:
            try:
                fields["config"] = os.path.basename(self._resolve_launch_yaml_ref(yaml_path, buckets["config"][0]))
            except ValueError:
                pass

        imports: List[Dict[str, Any]] = []
        seen: set = set()
        for index, raw_path in enumerate(buckets["main"]):
            self._append_launch_yaml_import(
                imports,
                seen,
                yaml_path=yaml_path,
                category="main_verilog" if index == 0 else "rtl_extra",
                raw_path=raw_path,
                source_key="main_rtl",
            )
        for raw_path in buckets["filelist"]:
            self._append_launch_yaml_import(
                imports,
                seen,
                yaml_path=yaml_path,
                category="rtl_extra",
                raw_path=raw_path,
                source_key="filelist",
            )
        for index, raw_path in enumerate(buckets["rtl"]):
            category = "rtl_extra"
            if not buckets["main"] and not buckets["filelist"] and index == 0:
                resolved = self._resolve_launch_yaml_ref(yaml_path, raw_path)
                if pathlib.Path(resolved).suffix.lower() in _FILELIST_EXTS:
                    category = "main_verilog"
            self._append_launch_yaml_import(
                imports,
                seen,
                yaml_path=yaml_path,
                category=category,
                raw_path=raw_path,
                source_key="rtl",
            )
        for raw_path in buckets["source_extra"]:
            self._append_launch_yaml_import(
                imports,
                seen,
                yaml_path=yaml_path,
                category="source_extra",
                raw_path=raw_path,
                source_key="source_extra",
            )
        for index, raw_path in enumerate(buckets["requirement"]):
            self._append_launch_yaml_import(
                imports,
                seen,
                yaml_path=yaml_path,
                category="requirement" if index == 0 else "spec",
                raw_path=raw_path,
                source_key="requirement",
            )
        for raw_path in buckets["spec"]:
            self._append_launch_yaml_import(
                imports,
                seen,
                yaml_path=yaml_path,
                category="spec",
                raw_path=raw_path,
                source_key="spec",
            )
        doc_category_first = "spec" if buckets["requirement"] else "requirement"
        for index, raw_path in enumerate(buckets["doc"]):
            self._append_launch_yaml_import(
                imports,
                seen,
                yaml_path=yaml_path,
                category=doc_category_first if index == 0 else "spec",
                raw_path=raw_path,
                source_key="doc",
            )
        for raw_path in buckets["config"]:
            self._append_launch_yaml_import(
                imports,
                seen,
                yaml_path=yaml_path,
                category="config",
                raw_path=raw_path,
                source_key="config",
            )
        for raw_path in buckets["misc"]:
            self._append_launch_yaml_import(
                imports,
                seen,
                yaml_path=yaml_path,
                category="misc",
                raw_path=raw_path,
                source_key="misc",
            )

        return {
            "yaml_path": os.path.abspath(yaml_path),
            "fields": fields,
            "imports": imports,
        }

    def _import_or_update_launch_yaml_file(self, workspace_id: str, category: str, abs_path: str) -> Dict[str, Any]:
        ws = self._get_workspace(workspace_id)
        existing = self._find_workspace_item_by_source_path(ws, abs_path)
        if existing is not None:
            if existing.get("category") != category or category in {"main_verilog", "requirement"}:
                self._update_workspace_item_category(workspace_id, existing.get("item_id", ""), category)
                ws = self._get_workspace(workspace_id)
                existing = self._find_workspace_item_by_id(ws, existing.get("item_id", "")) or existing
            return existing
        item = self._store_existing_file(workspace_id, category, abs_path)
        if category in {"main_verilog", "requirement"}:
            self._update_workspace_item_category(workspace_id, item.get("item_id", ""), category)
            ws = self._get_workspace(workspace_id)
            item = self._find_workspace_item_by_id(ws, item.get("item_id", "")) or item
        return item

    def _apply_launch_yaml_spec(self, workspace_id: str, yaml_path: str) -> Dict[str, Any]:
        self._get_workspace(workspace_id)
        data = self._load_launch_yaml_spec(yaml_path)
        spec = self._normalize_launch_yaml_spec(yaml_path, data)
        imported: List[Dict[str, Any]] = []
        for item in spec["imports"]:
            imported.append(
                self._import_or_update_launch_yaml_file(
                    workspace_id,
                    str(item.get("category") or "misc"),
                    str(item.get("path") or ""),
                )
            )
        stored_spec = {
            "path": spec["yaml_path"],
            "applied_at": _now(),
            "fields": _copy_jsonable(spec.get("fields") or {}),
            "imports": _copy_jsonable(spec.get("imports") or []),
        }
        with self._workspaces_lock:
            ws = self._workspaces.get(workspace_id)
            if ws is None:
                raise KeyError(f"Workspace '{workspace_id}' not found")
            ws["launch_yaml"] = stored_spec
        self._mark_dirty()
        ws = self._get_workspace(workspace_id)
        return {
            "yaml_path": spec["yaml_path"],
            "fields": spec["fields"],
            "imports": spec["imports"],
            "files": [self._workspace_file_public(ws, item) for item in imported],
            "workspace": self._workspace_public(ws),
        }

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

    def _select_main_item(self, ws: Dict[str, Any], main_verilog_path: str = "") -> Optional[Dict[str, Any]]:
        if main_verilog_path:
            item = self._find_workspace_item(ws, main_verilog_path)
            if item is None:
                raise ValueError("Main Verilog file not found in workspace")
            return item
        for item in reversed(ws.get("files", [])):
            if item.get("category") == "main_verilog":
                return item
        return None

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
        selected_module: str = "",
        picker_extra_args: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        ws = self._ensure_workspace_materialized(workspace_id, status="active")
        root = ws["workspace_dir"]
        picker_workspace = ws.get("picker_workspace") or os.path.join(root, "workspace")
        dut = _safe_name(effective_dut, "DUT")
        rtl_dir, doc_dir, dut_dir = self._reset_compiled_workspace_dirs(picker_workspace, dut)

        main_item = self._select_main_item(ws, main_verilog_path)
        f_items = [
            item for item in ws.get("files", [])
            if _is_picker_f_file(item.get("stored_path") or item.get("original_name") or "")
        ]
        if main_item is None and not f_items:
            raise ValueError("No main Verilog file or .f file found in workspace")
        if not str(selected_module or "").strip():
            raise ValueError("'selected_module' is required")
        copied: List[str] = []
        main_target = ""
        filelist_path = ""
        source_f_filelist_paths: List[str] = []
        f_filelist_paths: List[str] = []
        rtl_sources: List[str] = []
        config_path = ""
        for item in ws.get("files", []):
            src = item["stored_path"]
            cat = item.get("category", "misc")
            filename = os.path.basename(src)
            is_f_file = _is_picker_f_file(filename)
            if is_f_file:
                source_f_abs = os.path.abspath(src)
                if os.path.isfile(source_f_abs) and source_f_abs not in source_f_filelist_paths:
                    source_f_filelist_paths.append(source_f_abs)
            if is_f_file and item.get("source") == "server":
                f_abs = os.path.abspath(src)
                if os.path.isfile(f_abs) and f_abs not in f_filelist_paths:
                    f_filelist_paths.append(f_abs)
                continue
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
            if is_f_file:
                f_abs = os.path.abspath(target)
                if f_abs not in f_filelist_paths:
                    f_filelist_paths.append(f_abs)
            if main_item is not None and os.path.abspath(src) == os.path.abspath(main_item["stored_path"]):
                main_target = target
            if filename.lower() == "filelist.txt":
                filelist_path = target
            if cat == "config" and not config_path:
                config_path = os.path.relpath(target, root)

        if main_item is not None and not main_target:
            raise ValueError("Failed to locate copied main Verilog file")
        generated_filelist = False
        if main_target and not filelist_path:
            deps = [path for path in rtl_sources if os.path.abspath(path) != os.path.abspath(main_target)]
            if deps:
                filelist_path = os.path.join(rtl_dir, "filelist.txt")
                with open(filelist_path, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(sorted(os.path.abspath(path) for path in deps)) + "\n")
                copied.append(filelist_path)
                generated_filelist = True
        picker_command = self._build_picker_command(
            workspace_dir=root,
            picker_workspace=picker_workspace,
            dut_name=dut,
            selected_module=selected_module,
            main_verilog_path=main_target,
            filelist_path=filelist_path,
            f_filelist_paths=f_filelist_paths,
            picker_extra_args=picker_extra_args or [],
        )
        return {
            "workspace_dir": root,
            "picker_workspace": picker_workspace,
            "dut_name": dut,
            "rtl_dir": rtl_dir,
            "dut_dir": dut_dir,
            "doc_dir": doc_dir,
            "source_main_verilog_path": main_item["stored_path"] if main_item is not None else "",
            "main_verilog_path": main_target,
            "filelist_path": filelist_path,
            "source_f_filelist_paths": source_f_filelist_paths,
            "f_filelist_paths": f_filelist_paths,
            "generated_filelist": generated_filelist,
            "copied_files": copied,
            "config_path": config_path,
            "picker_extra_args": list(picker_extra_args or []),
            "picker_command": picker_command,
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

    def _default_picker_args(self) -> List[str]:
        default_args = _plain_config_value(self.cfg.get_value("launch.default_args", {}) or {})
        if not isinstance(default_args, dict):
            return []
        picker_args = _normalize_arg_list(default_args.get("picker_args"))
        if picker_args:
            return picker_args
        return _normalize_arg_list(default_args.get("picker_extra_args"))

    def _effective_picker_args(self, picker_extra_args: Any = None) -> List[str]:
        if picker_extra_args is None:
            return self._default_picker_args()
        return _normalize_arg_list(picker_extra_args)

    def _compile_workspace_dut(
        self,
        workspace_id: str,
        *,
        effective_dut: str,
        selected_module: str,
        main_verilog_path: str = "",
        picker_extra_args: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        ws = self._get_workspace(workspace_id)
        picker_args = self._effective_picker_args(picker_extra_args)
        prepared = self._prepare_workspace_layout(
            workspace_id,
            effective_dut=effective_dut,
            selected_module=selected_module,
            main_verilog_path=main_verilog_path,
            picker_extra_args=picker_args,
        )
        picker = self._run_picker(
            workspace_dir=prepared["workspace_dir"],
            picker_workspace=prepared["picker_workspace"],
            dut_name=prepared["dut_name"],
            selected_module=selected_module,
            main_verilog_path=prepared["main_verilog_path"],
            filelist_path=prepared["filelist_path"],
            f_filelist_paths=prepared["f_filelist_paths"],
            picker_extra_args=prepared["picker_extra_args"],
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
            "source_f_filelist_paths": prepared["source_f_filelist_paths"],
            "f_filelist_paths": prepared["f_filelist_paths"],
            "generated_filelist": prepared["generated_filelist"],
            "config_path": prepared.get("config_path", ""),
            "readme_path": readme_path,
            "compiled_at": _now(),
            "copied_files": prepared["copied_files"],
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
        f_filelist_paths: Optional[List[str]] = None,
        picker_extra_args: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        cmd = self._build_picker_command(
            workspace_dir=workspace_dir,
            picker_workspace=picker_workspace,
            dut_name=dut_name,
            selected_module=selected_module,
            main_verilog_path=main_verilog_path,
            filelist_path=filelist_path,
            f_filelist_paths=f_filelist_paths or [],
            picker_extra_args=picker_extra_args or [],
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
        f_filelist_paths: Optional[List[str]] = None,
        picker_extra_args: Optional[List[str]] = None,
    ) -> List[str]:
        fst_path = os.path.join(picker_workspace, dut_name, f"{dut_name}.fst")
        cmd = ["picker", "export"]
        if main_verilog_path:
            cmd.append(main_verilog_path)
        cmd.extend([
            "--rw",
            "1",
            "--sname",
            selected_module,
            "--tdir",
            os.path.join(picker_workspace, ""),
            "-c",
            "-w",
            fst_path,
        ])
        if filelist_path and os.path.isfile(filelist_path):
            cmd.extend(["--fs", filelist_path])
        for f_path in f_filelist_paths or []:
            if f_path and os.path.isfile(f_path):
                cmd.extend(["--filelist", os.path.abspath(f_path)])
        cmd.extend([arg for arg in (picker_extra_args or []) if str(arg).strip()])
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

    def _run_compile_job(
        self,
        workspace_id: str,
        effective_dut: str,
        selected_module: str,
        main_verilog_path: str,
        picker_extra_args: Optional[List[str]] = None,
    ) -> None:
        prepared: Dict[str, Any] = {}
        picker: Dict[str, Any] = {"command": [], "exit_code": None, "stdout": "", "stderr": "", "success": False}
        try:
            picker_args = self._effective_picker_args(picker_extra_args)
            prepared = self._prepare_workspace_layout(
                workspace_id,
                effective_dut=effective_dut,
                selected_module=selected_module,
                main_verilog_path=main_verilog_path,
                picker_extra_args=picker_args,
            )
            self._append_compile_log(
                workspace_id,
                (
                    f"Prepared workspace layout:\n"
                    f"  RTL: {prepared['rtl_dir']}\n"
                    f"  DOC: {prepared['doc_dir']}\n"
                    f"  DUT: {prepared['dut_dir']}\n"
                    f"  Picker: {shlex.join(prepared['picker_command'])}\n"
                ),
                "info",
            )

            def _run_once() -> Dict[str, Any]:
                cmd = list(prepared["picker_command"])
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
                "source_f_filelist_paths": prepared["source_f_filelist_paths"],
                "f_filelist_paths": prepared["f_filelist_paths"],
                "generated_filelist": prepared["generated_filelist"],
                "config_path": prepared.get("config_path", ""),
                "readme_path": readme_path,
                "compiled_at": _now(),
                "copied_files": prepared["copied_files"],
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

    def _start_compile_job(
        self,
        workspace_id: str,
        effective_dut: str,
        selected_module: str,
        main_verilog_path: str,
        picker_extra_args: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
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
            args=(workspace_id, effective_dut, selected_module, main_verilog_path, picker_extra_args),
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
        f_filelist_paths: Optional[List[str]] = None,
        picker_extra_args: Optional[List[str]] = None,
        command: Optional[List[str]] = None,
    ):
        cmd = list(command or self._build_picker_command(
            workspace_dir=workspace_dir,
            picker_workspace=picker_workspace,
            dut_name=dut_name,
            selected_module=selected_module,
            main_verilog_path=main_verilog_path,
            filelist_path=filelist_path,
            f_filelist_paths=f_filelist_paths or [],
            picker_extra_args=picker_extra_args or [],
        ))
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
        task_id = _safe_name(str(data.get("task_id") or "").strip(), "")
        requested_task_id = bool(task_id)
        with self._tasks_lock:
            if requested_task_id and task_id in self._tasks:
                raise ValueError(f"Task '{task_id}' already exists")
            while not task_id:
                candidate = secrets.token_hex(8)
                if candidate not in self._tasks:
                    task_id = candidate
        stdout_log = os.path.join(self._logs_dir, f"{task_id}.stdout.log")
        stderr_log = os.path.join(self._logs_dir, f"{task_id}.stderr.log")
        web_console_log = os.path.join(self._logs_dir, f"{task_id}.web_console.log")
        launch_mode = _normalize_launch_mode(data.get("launch_mode", "process"))
        task = {
            "task_id": task_id,
            "task_name": data.get("task_name", "") or task_id,
            "client_id": data.get("client_id", ""),
            "workspace_id": data.get("workspace_id", ""),
            "launch_mode": launch_mode,
            "cluster": data.get("cluster", {}),
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
            "stdout_log_path": stdout_log,
            "stderr_log_path": stderr_log,
            "web_console_log_path": web_console_log,
            "cmd_api": data.get("cmd_api", {}),
            "terminal_api": data.get("terminal_api", {}),
            "web_console": data.get("web_console", {}),
        }
        pathlib.Path(stdout_log).touch()
        pathlib.Path(stderr_log).touch()
        pathlib.Path(web_console_log).touch()
        with self._tasks_lock:
            if task_id in self._tasks:
                if requested_task_id:
                    raise ValueError(f"Task '{task_id}' already exists")
                raise ValueError("Generated duplicate task id")
            self._tasks[task_id] = task
        if task["workspace_id"]:
            with self._workspaces_lock:
                ws = self._workspaces.get(task["workspace_id"])
                if ws is not None:
                    ws["task_id"] = task_id
        self._mark_dirty()
        return task

    def _build_ucagent_command(
        self,
        req: Dict[str, Any],
        prepared: Dict[str, Any],
        cmd_api: Dict[str, Any],
        master_host: str = "",
    ) -> Tuple[List[str], Dict[str, str]]:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        cli_path = self._master_source_cli_path() or os.path.normpath(os.path.join(current_dir, "..", "cli.py"))
        picker_workspace = prepared.get("picker_workspace") or prepared["workspace_dir"]
        launch_mode = _normalize_launch_mode(req.get("launch_mode", "process"))
        if req.get("use_zip_workspace", True):
            archive_ref = str(req.get("task_id") or req.get("workspace_id") or "").strip()
            workspace_arg = self._workspace_archive_download_url(archive_ref, launch_mode, master_host)
        else:
            workspace_arg = picker_workspace
        argv = [sys.executable, cli_path, workspace_arg, prepared["dut_name"]]

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
        add_value("--workspace-base", req.get("workspace_base"))
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
        if req.get("use_skill"):
            argv.append("--use-skill")
        if req.get("extra_skill_path"):
            add_value("--extra-skill-path", req.get("extra_skill_path"))
        add_value("--seed", req.get("seed"))
        add_flag("--tui", req.get("tui"))
        web_console = req.get("web_console")
        if web_console in (True, "__default__", "__bare__", "__enabled__"):
            # Use cmd_api password when web console is enabled without explicit config
            argv.append("--web-console")
        elif isinstance(web_console, str) and web_console.strip():
            # Check if password is already provided in the web_console spec (format: [ip[:port]] [password])
            web_console_spec = web_console.strip()
            if " " not in web_console_spec:  # no password provided, add cmd_api password
                web_console_spec = f"{web_console_spec} {cmd_api['password']}"
            add_value("--web-console", web_console_spec)
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
        raw_meta = req.get("meta") or {}
        if isinstance(raw_meta, dict):
            for key, value in raw_meta.items():
                meta_key = str(key or "").strip()
                if not meta_key:
                    continue
                if isinstance(value, (dict, list, tuple)):
                    meta_value = json.dumps(value, ensure_ascii=False)
                elif value is None:
                    meta_value = ""
                else:
                    meta_value = str(value)
                add_value("--meta", f"{meta_key}={meta_value}")
        elif isinstance(raw_meta, list):
            for item in raw_meta:
                text = str(item or "").strip()
                if "=" in text:
                    add_value("--meta", text)

        master_spec = (req.get("master") or "").strip()
        if not master_spec:
            if not self.tcp:
                raise ValueError("Current master has no TCP listener; cannot auto-connect launched task")
            launch_mode = _normalize_launch_mode(req.get("launch_mode", "process"))
            master_host_for_task = str(master_host or "").strip() or self._cluster_master_ip(launch_mode)
            host_port = f"{master_host_for_task}:{self.port}"
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
        add_value("--web-console-capture-path", req.get("web_console_capture_path"))

        argv.extend([str(v) for v in req.get("extra_args", []) if str(v).strip()])

        env = os.environ.copy()
        env_updates = self._launch_default_env_updates()
        env_updates.update(req.get("env") or {})
        env.update({str(k): str(v) for k, v in env_updates.items()})
        if self.access_key:
            env["UCAGENT_WORKSPACE_ARCHIVE_KEY"] = self.access_key
        if self.password:
            env["UCAGENT_WORKSPACE_ARCHIVE_PASSWORD"] = self.password
        return argv, env

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

    def _run_control_command(self, cmd: List[str], timeout: float = 10.0) -> Tuple[int, str, str]:
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )
            return proc.returncode, proc.stdout or "", proc.stderr or ""
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            return 124, stdout, stderr or f"Command timed out after {timeout}s"
        except OSError as exc:
            return 127, "", str(exc)

    def _docker_cli_available(self) -> bool:
        return shutil.which("docker") is not None

    def _docker_sdk_client(self) -> Any:
        try:
            import docker
        except ImportError as exc:
            raise RuntimeError("docker CLI was not found and Docker SDK for Python is not installed") from exc
        try:
            return docker.from_env()
        except Exception as exc:
            raise RuntimeError(f"failed to initialize Docker SDK client: {exc}") from exc

    def _docker_sdk_network_attachment(self, network: str) -> Any:
        try:
            from docker.types import NetworkAttachmentConfig
        except ImportError:
            return network
        return NetworkAttachmentConfig(target=network)

    def _docker_swarm_local_state(self) -> str:
        if self._docker_cli_available():
            code, stdout, _stderr = self._run_control_command(
                ["docker", "info", "--format", "{{.Swarm.LocalNodeState}}"],
                timeout=3.0,
            )
            return stdout.strip().lower() if code == 0 else ""
        try:
            info = self._docker_sdk_client().info()
            return str(((info.get("Swarm") or {}).get("LocalNodeState")) or "").strip().lower()
        except Exception:
            return ""

    def _docker_network_inspect_data(self, network: str) -> Tuple[Dict[str, Any], str]:
        network = str(network or "").strip()
        if not network:
            return {}, "network name is empty"
        if self._docker_cli_available():
            code, stdout, stderr = self._run_control_command(
                ["docker", "network", "inspect", network],
                timeout=5.0,
            )
            if code != 0:
                return {}, (stderr or stdout or f"Docker network '{network}' was not found").strip()
            try:
                data = json.loads(stdout)
                if isinstance(data, list) and data:
                    return data[0], ""
                if isinstance(data, dict):
                    return data, ""
            except json.JSONDecodeError as exc:
                return {}, f"failed to parse docker network inspect output for '{network}': {exc}"
            return {}, f"docker network inspect returned no data for '{network}'"
        try:
            network_obj = self._docker_sdk_client().networks.get(network)
            return dict(network_obj.attrs or {}), ""
        except Exception as exc:
            return {}, str(exc)

    def _ensure_docker_task_network(self, mode: str, network: str) -> Dict[str, Any]:
        network = str(network or "").strip()
        if not network:
            return {}
        info, error = self._docker_network_inspect_data(network)
        if not info:
            create_overlay = mode == "docker_swarm" or self._docker_swarm_local_state() == "active"
            if self._docker_cli_available():
                cmd = ["docker", "network", "create"]
                if create_overlay:
                    cmd.extend(["--driver", "overlay", "--attachable"])
                cmd.append(network)
                code, stdout, stderr = self._run_control_command(cmd, timeout=15.0)
                if code != 0:
                    raise ValueError(f"failed to create Docker network '{network}': {(stderr or stdout).strip() or error}")
            else:
                try:
                    kwargs = {"driver": "overlay", "attachable": True} if create_overlay else {"driver": "bridge"}
                    self._docker_sdk_client().networks.create(network, **kwargs)
                except Exception as exc:
                    raise ValueError(f"failed to create Docker network '{network}' via Docker SDK: {exc}") from exc
            info, error = self._docker_network_inspect_data(network)
            if not info:
                raise ValueError(f"Docker network '{network}' is unavailable after create: {error}")
        if mode == "docker_swarm":
            driver = str(info.get("Driver") or "").lower()
            scope = str(info.get("Scope") or "").lower()
            if driver != "overlay" or scope != "swarm":
                raise ValueError(
                    f"Docker network '{network}' is {driver or 'unknown'}/{scope or 'unknown'}, "
                    "expected overlay/swarm for Docker Swarm launch mode"
                )
        return info

    def _docker_inspect_container_id(self, candidate: str) -> str:
        candidate = str(candidate or "").strip().lstrip("/")
        if not candidate:
            return ""
        if self._docker_cli_available():
            code, stdout, _stderr = self._run_control_command(
                ["docker", "inspect", "--type", "container", "-f", "{{.Id}}", candidate],
                timeout=3.0,
            )
            return stdout.strip() if code == 0 else ""
        try:
            container = self._docker_sdk_client().containers.get(candidate)
            return str(container.id or (container.attrs or {}).get("Id") or "").strip()
        except Exception:
            return ""

    def _running_inside_container(self) -> bool:
        if os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv"):
            return True
        for path in ("/proc/self/cgroup", "/proc/self/mountinfo"):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            if re.search(r"(?<![0-9a-f])([0-9a-f]{64})(?![0-9a-f])", text):
                return True
            if any(marker in text for marker in ("/docker/", "/kubepods/", "/containerd/")):
                return True
        return False

    def _current_docker_container_id(self) -> str:
        explicit = [
            os.environ.get("UCAGENT_MASTER_CONTAINER_ID", ""),
            os.environ.get("UCAGENT_MASTER_CONTAINER", ""),
        ]
        candidates: List[str] = [str(item).strip() for item in explicit if str(item or "").strip()]
        cgroup_candidates: List[str] = []
        for path in ("/proc/self/cgroup", "/proc/self/mountinfo"):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            cgroup_candidates.extend(re.findall(r"(?<![0-9a-f])([0-9a-f]{64})(?![0-9a-f])", text))
        if self._running_inside_container():
            candidates.extend(cgroup_candidates)
            candidates.append(os.environ.get("HOSTNAME", ""))
            try:
                with open("/etc/hostname", "r", encoding="utf-8", errors="replace") as fh:
                    candidates.append(fh.read().strip())
            except OSError:
                pass
        seen = set()
        for candidate in candidates:
            candidate = str(candidate or "").strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            container_id = self._docker_inspect_container_id(candidate)
            if container_id:
                return container_id
        return ""

    def _docker_container_networks(self, container_id: str) -> Tuple[Dict[str, Any], str]:
        container_id = str(container_id or "").strip()
        if not container_id:
            return {}, "container id is empty"
        if self._docker_cli_available():
            code, stdout, stderr = self._run_control_command(
                ["docker", "inspect", "-f", "{{json .NetworkSettings.Networks}}", container_id],
                timeout=5.0,
            )
            if code != 0:
                return {}, (stderr or stdout or f"failed to inspect Docker container '{container_id}'").strip()
            try:
                data = json.loads(stdout or "{}")
                return data if isinstance(data, dict) else {}, ""
            except json.JSONDecodeError as exc:
                return {}, f"failed to parse Docker container network data: {exc}"
        try:
            container = self._docker_sdk_client().containers.get(container_id)
            networks = (((container.attrs or {}).get("NetworkSettings") or {}).get("Networks") or {})
            return dict(networks), ""
        except Exception as exc:
            return {}, str(exc)

    def _docker_network_aliases_for_master(self, mode: str) -> List[str]:
        aliases: List[str] = ["ucagent_master"]
        host = self._cluster_master_ip(mode).strip()
        host_l = host.lower()
        if (
            host
            and host_l not in {"host.docker.internal", "localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}
            and not re.match(r"^\d+(?:\.\d+){3}$", host)
            and re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", host)
        ):
            aliases.insert(0, host)
        deduped: List[str] = []
        for alias in aliases:
            if alias not in deduped:
                deduped.append(alias)
        return deduped

    def _docker_master_network_host(self, mode: str, container_id: str, network_data: Dict[str, Any]) -> str:
        aliases = [
            str(item).strip()
            for item in (network_data.get("Aliases") or [])
            if str(item or "").strip()
        ]
        preferred = self._docker_network_aliases_for_master(mode)
        for alias in preferred:
            if alias in aliases:
                return alias
        container_id = str(container_id or "").strip()
        short_id = container_id[:12]
        for alias in aliases:
            if alias and alias not in {container_id, short_id}:
                return alias
        return aliases[0] if aliases else short_id

    def _ensure_master_on_docker_network(self, mode: str, network: str, task: Optional[Dict[str, Any]] = None) -> str:
        network = str(network or "").strip()
        if not network:
            return ""
        container_id = self._current_docker_container_id()
        if not container_id:
            if self._running_inside_container():
                raise ValueError(
                    "master appears to be running inside a container, but its Docker container id could not be resolved. "
                    "Set UCAGENT_MASTER_CONTAINER_ID or run the master container with Docker socket access so task "
                    f"containers can join the same Docker network '{network}'."
                )
            if task is not None:
                self._append_task_log(
                    task["stdout_log_path"],
                    f"Master is not running inside a Docker container; task will use configured master address {self._cluster_master_ip(mode)}.",
                )
            return ""
        networks, error = self._docker_container_networks(container_id)
        if network in networks:
            aliases = set(str(item) for item in ((networks.get(network) or {}).get("Aliases") or []))
            missing_aliases = [alias for alias in self._docker_network_aliases_for_master(mode) if alias not in aliases]
            if missing_aliases and task is not None:
                self._append_task_log(
                    task["stdout_log_path"],
                    f"Master container is already on Docker network '{network}' but is missing preferred aliases: {', '.join(missing_aliases)}.",
                )
            return self._docker_master_network_host(mode, container_id, networks.get(network) or {})
        aliases = self._docker_network_aliases_for_master(mode)
        if self._docker_cli_available():
            cmd = ["docker", "network", "connect"]
            for alias in aliases:
                cmd.extend(["--alias", alias])
            cmd.extend([network, container_id])
            code, stdout, stderr = self._run_control_command(cmd, timeout=15.0)
            if code != 0:
                raise ValueError(
                    f"failed to connect master container to Docker network '{network}': "
                    f"{(stderr or stdout).strip() or error}"
                )
        else:
            try:
                network_obj = self._docker_sdk_client().networks.get(network)
                network_obj.connect(container_id, aliases=aliases)
            except Exception as exc:
                raise ValueError(f"failed to connect master container to Docker network '{network}' via Docker SDK: {exc}") from exc
        if task is not None:
            self._append_task_log(
                task["stdout_log_path"],
                f"Connected master container to Docker network '{network}' with aliases: {', '.join(aliases)}.",
            )
        return aliases[0] if aliases else container_id[:12]

    def _prepare_docker_task_network(self, mode: str, network: str, task: Optional[Dict[str, Any]] = None) -> str:
        network = str(network or "").strip()
        if not network:
            return ""
        self._ensure_docker_task_network(mode, network)
        return self._ensure_master_on_docker_network(mode, network, task)

    def _k8s_cli_available(self) -> bool:
        return shutil.which("kubectl") is not None

    def _k8s_sdk_clients(self) -> Tuple[Any, Any]:
        try:
            from kubernetes import client as k8s_client
            from kubernetes import config as k8s_config
        except ImportError as exc:
            raise RuntimeError("kubectl CLI was not found and Kubernetes Python client is not installed") from exc
        try:
            try:
                k8s_config.load_incluster_config()
            except Exception:
                k8s_config.load_kube_config()
            return k8s_client, k8s_client.CoreV1Api()
        except Exception as exc:
            raise RuntimeError(f"failed to initialize Kubernetes Python client: {exc}") from exc

    def _append_task_log(self, path: str, message: str) -> None:
        if not path:
            return
        try:
            with open(path, "a", encoding="utf-8", errors="replace") as fh:
                fh.write(message)
                if message and not message.endswith("\n"):
                    fh.write("\n")
        except OSError as exc:
            warning(f"Failed to append task log '{path}': {exc}")

    def _launch_cluster_config(self) -> Dict[str, Any]:
        cfg = _plain_config_value(self.cfg.get_value("launch.cluster", {}) or {})
        if not isinstance(cfg, dict):
            cfg = {}
        return {
            "image": str(cfg.get("image") or os.environ.get("UCAGENT_LAUNCH_IMAGE") or "ucagent:latest"),
            "container_command": cfg.get("container_command") or "ucagent",
            "master_ip": _normalize_cluster_master_ip_config(cfg.get("master_ip")),
            "docker_network": str(cfg.get("docker_network") or ""),
            "docker_extra_args": cfg.get("docker_extra_args") if isinstance(cfg.get("docker_extra_args"), list) else [],
            "swarm_extra_args": cfg.get("swarm_extra_args") if isinstance(cfg.get("swarm_extra_args"), list) else [],
            "k8s_namespace": str(cfg.get("k8s_namespace") or "default"),
            "k8s_image_pull_policy": str(cfg.get("k8s_image_pull_policy") or "IfNotPresent"),
            "k8s_service_account": str(cfg.get("k8s_service_account") or ""),
            "k8s_node_selector": cfg.get("k8s_node_selector") if isinstance(cfg.get("k8s_node_selector"), dict) else {},
            "k8s_tolerations": cfg.get("k8s_tolerations") if isinstance(cfg.get("k8s_tolerations"), list) else [],
            "k8s_resources": cfg.get("k8s_resources") if isinstance(cfg.get("k8s_resources"), dict) else {},
            "extra_mounts": cfg.get("extra_mounts") if isinstance(cfg.get("extra_mounts"), list) else [],
        }

    def _docker_available(self) -> Tuple[bool, str]:
        if self._docker_cli_available():
            code, stdout, stderr = self._run_control_command(["docker", "info"], timeout=3.0)
            if code != 0:
                return False, (stderr or stdout or "docker daemon is not reachable").strip()
            return True, "Docker daemon is reachable via docker CLI"
        try:
            client = self._docker_sdk_client()
            client.ping()
            return True, "Docker daemon is reachable via Docker SDK"
        except Exception as exc:
            return False, str(exc)

    def _docker_swarm_available(self) -> Tuple[bool, str]:
        docker_ok, docker_msg = self._docker_available()
        if not docker_ok:
            return False, docker_msg
        if self._docker_cli_available():
            code, stdout, stderr = self._run_control_command(
                ["docker", "info", "--format", "{{.Swarm.LocalNodeState}}"],
                timeout=3.0,
            )
            if code != 0:
                return False, (stderr or stdout or "failed to inspect Docker Swarm state").strip()
            state = stdout.strip().lower()
        else:
            try:
                info = self._docker_sdk_client().info()
                state = str(((info.get("Swarm") or {}).get("LocalNodeState")) or "").strip().lower()
            except Exception as exc:
                return False, f"failed to inspect Docker Swarm state via Docker SDK: {exc}"
        if state != "active":
            return False, f"Docker Swarm is not active (state: {state or 'unknown'})"
        return True, "Docker Swarm is active"

    def _k8s_available(self) -> Tuple[bool, str]:
        if self._k8s_cli_available():
            code, stdout, stderr = self._run_control_command(
                ["kubectl", "cluster-info", "--request-timeout=3s"],
                timeout=5.0,
            )
            if code != 0:
                return False, (stderr or stdout or "Kubernetes cluster is not reachable").strip()
            return True, "Kubernetes cluster is reachable via kubectl"
        try:
            _k8s_client, core = self._k8s_sdk_clients()
            core.list_namespace(limit=1)
            return True, "Kubernetes cluster is reachable via Kubernetes Python client"
        except Exception as exc:
            return False, str(exc)

    def _launch_mode_options(self) -> List[Dict[str, Any]]:
        docker_ok, docker_msg = self._docker_available()
        swarm_ok, swarm_msg = self._docker_swarm_available() if docker_ok else (False, docker_msg)
        k8s_ok, k8s_msg = self._k8s_available()
        raw_options = [
            {"value": "process", "name": _LAUNCH_MODE_LABELS["process"], "enabled": True, "reason": "Always available"},
            {"value": "docker", "name": _LAUNCH_MODE_LABELS["docker"], "enabled": docker_ok, "reason": docker_msg},
            {"value": "docker_swarm", "name": _LAUNCH_MODE_LABELS["docker_swarm"], "enabled": swarm_ok, "reason": swarm_msg},
            {"value": "k8s", "name": _LAUNCH_MODE_LABELS["k8s"], "enabled": k8s_ok, "reason": k8s_msg},
        ]
        enabled_modes = self._enabled_launch_modes()
        enabled_set = set(enabled_modes)
        options_by_value = {item["value"]: item for item in raw_options}
        ordered_values = [mode for mode in enabled_modes if mode in options_by_value]
        ordered_values.extend([item["value"] for item in raw_options if item["value"] not in ordered_values])
        options = []
        for value in ordered_values:
            item = dict(options_by_value[value])
            item["configured"] = value in enabled_set
            if not item["configured"]:
                item["enabled"] = False
                item["reason"] = "Not enabled by launch.default_args.launch_mode"
            options.append(item)
        return options

    def _enabled_launch_modes(self) -> List[str]:
        default_args = _plain_config_value(self.cfg.get_value("launch.default_args", {}) or {})
        raw_modes: Any = ["process"]
        if isinstance(default_args, dict):
            raw_modes = default_args.get("launch_mode", ["process"])
        return _normalize_launch_mode_list(raw_modes)

    def _ensure_launch_mode_supported(self, launch_mode: str) -> None:
        if launch_mode == "process":
            return
        for item in self._launch_mode_options():
            if item["value"] == launch_mode:
                if item["enabled"]:
                    return
                raise ValueError(f"Launch mode '{launch_mode}' is not available: {item['reason']}")
        raise ValueError(f"Launch mode '{launch_mode}' is not configured")

    def _cluster_master_ip(self, launch_mode: str) -> str:
        master_ip = self._launch_cluster_config().get("master_ip") or "127.0.0.1"
        if isinstance(master_ip, dict):
            mode = _normalize_launch_mode(launch_mode)
            master_ip = master_ip.get(mode) or master_ip.get("process") or "127.0.0.1"
        if str(master_ip).strip().lower() in {"0.0.0.0", "::", "[::]"}:
            return "127.0.0.1"
        return str(master_ip).strip() or "127.0.0.1"

    def _launch_bind_host(self, launch_mode: str, host: str) -> str:
        raw = str(host or "").strip() or "127.0.0.1"
        if launch_mode in _CONTAINER_LAUNCH_MODES and raw.lower() in _LOCAL_HOSTS:
            return "0.0.0.0"
        return raw

    def _service_base_url(self, launch_mode: str, bind_host: str, port: int) -> str:
        host = bind_host
        if str(host).strip().lower() in {"0.0.0.0", "::", "[::]", ""}:
            host = "127.0.0.1"
        return f"http://{host}:{port}"

    def _master_source_host_path(self) -> str:
        raw = str(os.environ.get("UCAGENT_MASTER_SOURCE", "") or "").strip()
        if not raw:
            return ""
        return os.path.abspath(raw)

    def _master_source_cli_path(self) -> str:
        source_host_path = self._master_source_host_path()
        if not source_host_path:
            return ""
        return os.path.join(source_host_path, "ucagent", "cli.py")

    def _master_source_container_cli_path(self) -> str:
        return os.path.join(_MASTER_SOURCE_CONTAINER_PATH, "ucagent", "cli.py")

    def _container_command(self, resolved_command: List[str]) -> List[str]:
        cfg = self._launch_cluster_config()
        configured = cfg.get("container_command") or "ucagent"
        if self._master_source_host_path():
            configured = ["python3", self._master_source_container_cli_path()]
        if isinstance(configured, list):
            prefix = [str(item) for item in configured if str(item).strip()]
        else:
            prefix = shlex.split(str(configured)) if str(configured).strip() else ["ucagent"]
        if len(resolved_command) >= 2:
            return prefix + [str(item) for item in resolved_command[2:]]
        return prefix + [str(item) for item in resolved_command]

    def _cluster_mounts(self, prepared: Dict[str, Any]) -> List[Tuple[str, str]]:
        cfg = self._launch_cluster_config()
        mounts: List[Tuple[str, str]] = []
        seen = set()

        def add_mount(source: Any, target: Any = None, *, require_exists: bool = True) -> None:
            src = os.path.abspath(str(source or "").strip())
            dst = str(target or source or "").strip()
            if not src or not dst:
                return
            if require_exists and not os.path.exists(src):
                return
            key = (src, dst)
            if key in seen:
                return
            seen.add(key)
            mounts.append((src, dst))

        if not (prepared.get("use_zip_workspace") is True):
            add_mount(prepared.get("workspace_dir"))
        source_host_path = self._master_source_host_path()
        if source_host_path:
            add_mount(source_host_path, _MASTER_SOURCE_CONTAINER_PATH, require_exists=False)
        for item in cfg.get("extra_mounts") or []:
            if isinstance(item, dict):
                add_mount(item.get("source") or item.get("src"), item.get("target") or item.get("dst"))
            elif isinstance(item, str) and ":" in item:
                source, target = item.split(":", 1)
                add_mount(source, target)
        return mounts

    def _cluster_launch_context(
        self,
        task: Dict[str, Any],
        env: Dict[str, str],
        prepared: Dict[str, Any],
        mode: str,
    ) -> Dict[str, Any]:
        cfg = self._launch_cluster_config()
        use_zip_workspace = prepared.get("use_zip_workspace") is True
        context = {
            "cfg": cfg,
            "name": f"ucagent-{task['task_id']}",
            "env": self._cluster_env(env, task.get("env") or {}),
            "mounts": self._cluster_mounts(prepared),
            "network": str(cfg.get("docker_network") or "").strip() if mode in {"docker", "docker_swarm"} else "",
            "picker_workspace": "/tmp" if use_zip_workspace else (prepared.get("picker_workspace") or prepared["workspace_dir"]),
            "command": self._container_command(task["resolved_command"]),
        }
        self._append_cluster_launch_debug(
            task,
            mode,
            context["name"],
            cfg["image"],
            context["command"],
            context["mounts"],
            context["network"],
        )
        return context

    def _set_cluster_record(
        self,
        task: Dict[str, Any],
        mode: str,
        kind: str,
        name: str,
        image: Any,
        cluster_id: str = "",
        **extra: Any,
    ) -> Dict[str, Any]:
        cluster = {
            "mode": mode,
            "kind": kind,
            "name": name,
            "image": image,
        }
        if cluster_id:
            cluster["id"] = cluster_id
        cluster.update(extra)
        task["cluster"] = cluster
        return cluster

    def _cluster_ports(
        self,
        cmd_api: Dict[str, Any],
        terminal_api: Dict[str, Any],
        web_console: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        ports = []
        seen = set()

        def add(name: str, svc: Dict[str, Any]) -> None:
            if not svc.get("enabled"):
                return
            try:
                port = int(svc.get("port"))
            except (TypeError, ValueError):
                return
            if port in seen:
                return
            seen.add(port)
            ports.append({"name": name, "host_port": port, "container_port": port})

        add("cmd-api", cmd_api)
        add("terminal-api", terminal_api)
        add("web-console", web_console)
        return ports

    def _published_ports(
        self,
        cmd_api: Dict[str, Any],
        terminal_api: Dict[str, Any],
        web_console: Dict[str, Any],
        launch_mode: str = "docker",
        master_host_for_task: str = "",
    ) -> List[Dict[str, Any]]:
        if launch_mode != "docker":
            return []
        if master_host_for_task:
            return []
        return self._cluster_ports(cmd_api, terminal_api, web_console)

    def _docker_extra_args(self, cfg: Dict[str, Any]) -> List[str]:
        args = [str(item) for item in cfg.get("docker_extra_args") or [] if str(item).strip()]
        if self._cluster_master_ip("docker") == "host.docker.internal":
            has_host_mapping = any(
                arg == "--add-host=host.docker.internal:host-gateway"
                or (
                    arg == "--add-host"
                    and index + 1 < len(args)
                    and args[index + 1] == "host.docker.internal:host-gateway"
                )
                for index, arg in enumerate(args)
            )
            if not has_host_mapping:
                args.insert(0, "--add-host=host.docker.internal:host-gateway")
        return args

    def _write_docker_env_file(self, task: Dict[str, Any], env: Dict[str, str]) -> str:
        path = os.path.join(self._logs_dir, f"{task['task_id']}.docker.env")
        lines = []
        for key, value in sorted((env or {}).items()):
            key = str(key)
            if not _valid_env_name(key):
                continue
            escaped = str(value).replace("\\", "\\\\").replace("\n", "\\n")
            lines.append(f"{key}={escaped}")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
            fh.write("\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return path

    def _cluster_env(self, env: Dict[str, str], requested_env: Dict[str, Any]) -> Dict[str, str]:
        selected: Dict[str, str] = {}
        configured = self.cfg.get_value("launch.default_env", []) or []
        if hasattr(configured, "as_dict"):
            configured = configured.as_dict()
        for entry in configured if isinstance(configured, list) else []:
            if hasattr(entry, "as_dict"):
                entry = entry.as_dict()
            if isinstance(entry, str):
                key = entry.strip()
            elif isinstance(entry, dict) and len(entry) == 1:
                key = str(next(iter(entry.keys()))).strip()
            else:
                continue
            if key and key in env:
                selected[key] = str(env[key])
        for key, value in (requested_env or {}).items():
            selected[str(key)] = str(value)
        selected.setdefault("PYTHONUNBUFFERED", "1")
        return selected

    def _start_external_log_capture(self, task: Dict[str, Any], cmd: List[str]) -> None:
        stdout_log = open(task["stdout_log_path"], "a", encoding="utf-8", buffering=1)
        stderr_log = open(task["stderr_log_path"], "a", encoding="utf-8", buffering=1)
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            self._append_task_log(task["stderr_log_path"], f"Failed to start log capture: {exc}")
            try:
                stdout_log.close()
                stderr_log.close()
            except OSError:
                pass
            return
        runtime = self._task_runtime.setdefault(task["task_id"], {})
        runtime.update({
            "log_process": proc,
            "stdout_log": stdout_log,
            "stderr_log": stderr_log,
            "stdout_thread": threading.Thread(
                target=self._pipe_task_log,
                args=(task["task_id"], proc.stdout, stdout_log, "stdout"),
                daemon=True,
                name=f"task-{task['task_id']}-external-stdout",
            ),
            "stderr_thread": threading.Thread(
                target=self._pipe_task_log,
                args=(task["task_id"], proc.stderr, stderr_log, "stderr"),
                daemon=True,
                name=f"task-{task['task_id']}-external-stderr",
            ),
        })
        runtime["stdout_thread"].start()
        runtime["stderr_thread"].start()

    def _start_stream_log_capture(self, task: Dict[str, Any], stream_factory: Any, label: str) -> None:
        stdout_log = open(task["stdout_log_path"], "a", encoding="utf-8", buffering=1)
        stderr_log = open(task["stderr_log_path"], "a", encoding="utf-8", buffering=1)
        stop_event = threading.Event()

        def run() -> None:
            try:
                for chunk in stream_factory():
                    if stop_event.is_set():
                        break
                    if chunk is None:
                        continue
                    if isinstance(chunk, bytes):
                        text = chunk.decode("utf-8", errors="replace")
                    else:
                        text = str(chunk)
                    stdout_log.write(text)
                    if text and not text.endswith("\n"):
                        stdout_log.write("\n")
            except Exception as exc:
                stderr_log.write(f"{label} log capture failed: {exc}\n")
            finally:
                try:
                    stdout_log.flush()
                    stderr_log.flush()
                except Exception:
                    pass

        thread = threading.Thread(
            target=run,
            daemon=True,
            name=f"task-{task['task_id']}-{label}-logs",
        )
        runtime = self._task_runtime.setdefault(task["task_id"], {})
        runtime.update({
            "log_stop_event": stop_event,
            "stdout_log": stdout_log,
            "stderr_log": stderr_log,
            "stdout_thread": thread,
        })
        thread.start()

    def _docker_sdk_log_capture(self, task: Dict[str, Any], kind: str, name: str) -> None:
        def stream_factory() -> Any:
            client = self._docker_sdk_client()
            if kind == "container":
                return client.containers.get(name).logs(stream=True, follow=True, stdout=True, stderr=True)
            return client.api.service_logs(name, follow=True, stdout=True, stderr=True)

        self._start_stream_log_capture(task, stream_factory, f"docker-{kind}")

    def _k8s_sdk_log_capture(self, task: Dict[str, Any], namespace: str, pod_name: str) -> None:
        def stream_factory() -> Any:
            _k8s_client, core = self._k8s_sdk_clients()
            name = pod_name
            deadline = time.time() + 60.0
            while not name and time.time() < deadline:
                name = self._k8s_pod_name_for_job(namespace, str((task.get("cluster") or {}).get("name") or ""))
                if not name:
                    time.sleep(1.0)
            if not name:
                raise RuntimeError("Kubernetes job did not create a pod within 60s")
            return core.read_namespaced_pod_log(
                name=name,
                namespace=namespace,
                follow=True,
                _preload_content=False,
            ).stream()

        self._start_stream_log_capture(task, stream_factory, "k8s")

    def _k8s_pod_name_for_job(self, namespace: str, job_name: str) -> str:
        _k8s_client, core = self._k8s_sdk_clients()
        pods = core.list_namespaced_pod(namespace=namespace, label_selector=f"job-name={job_name}")
        items = pods.items or []
        if not items:
            return ""
        return str(items[0].metadata.name or "")

    def _append_cluster_launch_debug(
        self,
        task: Dict[str, Any],
        mode: str,
        name: str,
        image: Any,
        command: List[str],
        mounts: List[Tuple[str, str]],
        network: str = "",
    ) -> None:
        self._append_task_log(
            task["stdout_log_path"],
            (
                f"Cluster launch debug: mode={mode} name={name} image={image}\n"
                f"  command={shlex.join([str(item) for item in command])}\n"
                f"  mounts={json.dumps([{'source': s, 'target': t} for s, t in mounts], ensure_ascii=False)}\n"
                f"  network={network or '<none>'}"
            ),
        )

    def _append_docker_connectivity_debug(
        self,
        task: Dict[str, Any],
        launch_mode: str,
        master_host_for_task: str,
        cmd_api: Dict[str, Any],
        terminal_api: Dict[str, Any],
        web_console: Dict[str, Any],
    ) -> None:
        published = self._published_ports(cmd_api, terminal_api, web_console, launch_mode, master_host_for_task)
        self._append_task_log(
            task["stdout_log_path"],
            (
                "Docker connectivity debug: "
                f"master_host_for_task={master_host_for_task or self._cluster_master_ip(launch_mode)} "
                f"published_ports={json.dumps(published, ensure_ascii=False)}"
            ),
        )

    def _docker_swarm_task_detail(self, name: str) -> str:
        if not name:
            return ""
        if self._docker_cli_available():
            code, stdout, stderr = self._run_control_command(
                [
                    "docker", "service", "ps", name, "--no-trunc",
                    "--format", "ID={{.ID}} Name={{.Name}} Node={{.Node}} Desired={{.DesiredState}} Current={{.CurrentState}} Error={{.Error}} Image={{.Image}}",
                ],
                timeout=5.0,
            )
            return (stdout or stderr).strip() if code == 0 else (stderr or stdout).strip()
        try:
            service = self._docker_sdk_client().services.get(name)
            lines = []
            for item in service.tasks():
                status = item.get("Status") or {}
                spec = item.get("Spec") or {}
                container = spec.get("ContainerSpec") or {}
                lines.append(
                    "ID={id} Node={node} Desired={desired} State={state} Message={message} Error={error} Image={image}".format(
                        id=item.get("ID", ""),
                        node=item.get("NodeID", ""),
                        desired=item.get("DesiredState", ""),
                        state=status.get("State", ""),
                        message=status.get("Message", ""),
                        error=status.get("Err", ""),
                        image=container.get("Image", ""),
                    )
                )
            return "\n".join(lines)
        except Exception as exc:
            return str(exc)

    def _cluster_job_status(self, active: int, succeeded: int, failed: int) -> Tuple[bool, Optional[int], str]:
        detail = f"active={active} succeeded={succeeded} failed={failed}"
        if active > 0:
            return True, None, detail
        if succeeded > 0:
            return False, 0, detail
        if failed > 0:
            return False, 1, detail
        return True, None, detail

    def _int_or_zero(self, value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _start_task_docker(
        self,
        task: Dict[str, Any],
        env: Dict[str, str],
        prepared: Dict[str, Any],
        cmd_api: Dict[str, Any],
        terminal_api: Dict[str, Any],
        web_console: Dict[str, Any],
        master_host_for_task: str = "",
    ) -> Dict[str, Any]:
        context = self._cluster_launch_context(task, env, prepared, "docker")
        cfg = context["cfg"]
        name = context["name"]
        if not self._docker_cli_available():
            client = self._docker_sdk_client()
            network = str(cfg.get("docker_network") or "").strip() or None
            volumes = {
                source: {"bind": target, "mode": "rw"}
                for source, target in context["mounts"]
            }
            ports = {
                f"{port['container_port']}/tcp": port["host_port"]
                for port in self._published_ports(cmd_api, terminal_api, web_console, "docker", master_host_for_task)
            } or None
            container = client.containers.run(
                image=str(cfg["image"]),
                command=context["command"],
                name=name,
                detach=True,
                environment=context["env"],
                network=network,
                volumes=volumes,
                working_dir=context["picker_workspace"],
                ports=ports,
                remove="--rm" in self._docker_extra_args(cfg),
            )
            self._set_cluster_record(task, "docker", "container", name, cfg["image"], cluster_id=container.id)
            self._append_task_log(task["stdout_log_path"], f"Started Docker container {name} {container.id}")
            self._docker_sdk_log_capture(task, "container", name)
            return task["cluster"]

        env_file = self._write_docker_env_file(task, context["env"])
        cmd = ["docker", "run", "-d", "--name", name, "--env-file", env_file]
        network = str(cfg.get("docker_network") or "").strip()
        if network:
            cmd.extend(["--network", network])
        for source, target in context["mounts"]:
            cmd.extend(["-v", f"{source}:{target}"])
        cmd.extend(["--workdir", context["picker_workspace"]])
        for port in self._published_ports(cmd_api, terminal_api, web_console, "docker", master_host_for_task):
            cmd.extend(["-p", f"{port['host_port']}:{port['container_port']}"])
        cmd.extend(self._docker_extra_args(cfg))
        cmd.append(str(cfg["image"]))
        cmd.extend(context["command"])
        code, stdout, stderr = self._run_control_command(cmd, timeout=30.0)
        if code != 0:
            raise ValueError(f"docker run failed: {(stderr or stdout).strip()}")
        container_id = stdout.strip()
        self._set_cluster_record(task, "docker", "container", name, cfg["image"], cluster_id=container_id)
        self._append_task_log(task["stdout_log_path"], f"Started Docker container {name} {container_id}")
        self._start_external_log_capture(task, ["docker", "logs", "-f", name])
        return task["cluster"]

    def _start_task_docker_swarm(
        self,
        task: Dict[str, Any],
        env: Dict[str, str],
        prepared: Dict[str, Any],
        cmd_api: Dict[str, Any],
        terminal_api: Dict[str, Any],
        web_console: Dict[str, Any],
    ) -> Dict[str, Any]:
        context = self._cluster_launch_context(task, env, prepared, "docker_swarm")
        cfg = context["cfg"]
        name = context["name"]
        if not self._docker_cli_available():
            client = self._docker_sdk_client()
            mounts = [
                {"Type": "bind", "Source": source, "Target": target}
                for source, target in context["mounts"]
            ]
            task_template = {
                "ContainerSpec": {
                    "Image": str(cfg["image"]),
                    "Command": context["command"],
                    "Env": [
                        f"{key}={value}"
                        for key, value in sorted(context["env"].items())
                        if _valid_env_name(str(key))
                    ],
                    "Mounts": mounts,
                    "Dir": context["picker_workspace"],
                },
                "RestartPolicy": {"Condition": "none"},
            }
            network = context["network"]
            if network:
                task_template["Networks"] = [self._docker_sdk_network_attachment(network)]
            service_data = client.api.create_service(
                task_template=task_template,
                name=name,
                mode={"ReplicatedJob": {"TotalCompletions": 1, "MaxConcurrent": 1}},
            )
            service_id = str(service_data.get("ID") or "")
            if network:
                inspect_data = client.api.inspect_service(service_id)
                attached_networks = [
                    str(item.get("Target") or item.get("NetworkID") or "")
                    for item in ((inspect_data.get("Spec") or {}).get("TaskTemplate") or {}).get("Networks", [])
                ]
                if not attached_networks:
                    raise ValueError(f"Docker Swarm service {name} was created without configured network '{network}'")
            self._set_cluster_record(task, "docker_swarm", "job", name, cfg["image"], cluster_id=service_id)
            self._append_task_log(task["stdout_log_path"], f"Started Docker Swarm service {name} {service_id}")
            self._docker_sdk_log_capture(task, "service", name)
            return task["cluster"]

        cmd = [
            "docker", "service", "create",
            "--name", name,
            "--detach=true",
            "--mode", "replicated-job",
            "--replicas", "1",
            "--restart-condition", "none",
        ]
        network = context["network"]
        if network:
            cmd.extend(["--network", network])
        for source, target in context["mounts"]:
            cmd.extend(["--mount", f"type=bind,source={source},target={target}"])
        cmd.extend(["--workdir", context["picker_workspace"]])
        for key, value in sorted(context["env"].items()):
            key = str(key)
            if _valid_env_name(key):
                cmd.extend(["--env", f"{key}={value}"])
        cmd.extend([str(item) for item in cfg.get("swarm_extra_args") or [] if str(item).strip()])
        cmd.append(str(cfg["image"]))
        cmd.extend(context["command"])
        code, stdout, stderr = self._run_control_command(cmd, timeout=30.0)
        if code != 0:
            raise ValueError(f"docker service create failed: {(stderr or stdout).strip()}")
        service_id = stdout.strip()
        self._set_cluster_record(task, "docker_swarm", "job", name, cfg["image"], cluster_id=service_id)
        self._append_task_log(task["stdout_log_path"], f"Started Docker Swarm service {name} {service_id}")
        self._start_external_log_capture(task, ["docker", "service", "logs", "-f", "--raw", name])
        return task["cluster"]

    def _k8s_manifest(
        self,
        task: Dict[str, Any],
        env: Dict[str, str],
        prepared: Dict[str, Any],
        cmd_api: Dict[str, Any],
        terminal_api: Dict[str, Any],
        web_console: Dict[str, Any],
    ) -> Dict[str, Any]:
        context = self._cluster_launch_context(task, env, prepared, "k8s")
        cfg = context["cfg"]
        name = context["name"]
        command = context["command"]
        ports = [
            {"name": item["name"][:15], "containerPort": item["container_port"]}
            for item in self._published_ports(cmd_api, terminal_api, web_console, "k8s")
        ]
        volume_mounts = []
        volumes = []
        for index, (source, target) in enumerate(context["mounts"], start=1):
            vol_name = f"workspace-{index}"
            volumes.append({"name": vol_name, "hostPath": {"path": source, "type": "Directory"}})
            volume_mounts.append({"name": vol_name, "mountPath": target})
        container = {
            "name": "ucagent",
            "image": cfg["image"],
            "imagePullPolicy": cfg["k8s_image_pull_policy"],
            "command": command[:1],
            "args": command[1:],
            "env": [
                {"name": str(key), "value": str(value)}
                for key, value in sorted(context["env"].items())
                if _valid_env_name(str(key))
            ],
            "volumeMounts": volume_mounts,
        }
        if ports:
            container["ports"] = ports
        if cfg.get("k8s_resources"):
            container["resources"] = cfg["k8s_resources"]
        pod_spec: Dict[str, Any] = {
            "restartPolicy": "Never",
            "containers": [container],
        }
        if volumes:
            pod_spec["volumes"] = volumes
        if cfg.get("k8s_service_account"):
            pod_spec["serviceAccountName"] = cfg["k8s_service_account"]
        if cfg.get("k8s_node_selector"):
            pod_spec["nodeSelector"] = cfg["k8s_node_selector"]
        if cfg.get("k8s_tolerations"):
            pod_spec["tolerations"] = cfg["k8s_tolerations"]
        return {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": name,
                "labels": {
                    "app": "ucagent",
                    "ucagent-task-id": task["task_id"],
                },
            },
            "spec": {
                "backoffLimit": 0,
                "template": {
                    "metadata": {
                        "labels": {
                            "app": "ucagent",
                            "ucagent-task-id": task["task_id"],
                        },
                    },
                    "spec": pod_spec,
                },
            },
        }

    def _start_k8s_port_forwards(self, task: Dict[str, Any]) -> None:
        cluster = task.get("cluster") or {}
        if task.get("launch_mode") != "k8s" or not cluster.get("name"):
            return
        if not self._k8s_cli_available():
            self._append_task_log(
                task["stderr_log_path"],
                "kubectl was not found; Kubernetes Python client fallback does not start local port-forward processes.",
            )
            return
        runtime = self._task_runtime.setdefault(task["task_id"], {})
        existing = runtime.get("port_forward_processes") or []
        if existing and any(proc.poll() is None for proc in existing):
            return
        cfg = self._launch_cluster_config()
        namespace = cluster.get("namespace") or cfg["k8s_namespace"]
        name = str(cluster.get("name") or "").strip()
        pod_ref = f"pod/{name}"
        if cluster.get("kind") == "job":
            code, stdout, stderr = self._run_control_command(
                ["kubectl", "get", "pods", "-n", namespace, "-l", f"job-name={name}", "-o", "jsonpath={.items[0].metadata.name}"],
                timeout=4.0,
            )
            if code != 0 or not stdout.strip():
                self._append_task_log(task["stderr_log_path"], f"Failed to find pod for Kubernetes job {namespace}/{name}: {(stderr or stdout).strip()}")
                return
            pod_ref = f"pod/{stdout.strip()}"
        processes = []
        for port in cluster.get("ports") or []:
            host_port = int(port["host_port"])
            container_port = int(port["container_port"])
            cmd = [
                "kubectl", "port-forward",
                "-n", namespace,
                pod_ref,
                f"{host_port}:{container_port}",
                "--address", "127.0.0.1",
            ]
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                processes.append(proc)
            except OSError as exc:
                self._append_task_log(task["stderr_log_path"], f"Failed to start kubectl port-forward: {exc}")
        runtime["port_forward_processes"] = processes

    def _start_task_k8s(
        self,
        task: Dict[str, Any],
        env: Dict[str, str],
        prepared: Dict[str, Any],
        cmd_api: Dict[str, Any],
        terminal_api: Dict[str, Any],
        web_console: Dict[str, Any],
    ) -> Dict[str, Any]:
        cfg = self._launch_cluster_config()
        manifest = self._k8s_manifest(task, env, prepared, cmd_api, terminal_api, web_console)
        manifest_path = os.path.join(self._logs_dir, f"{task['task_id']}.k8s-job.json")
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)
        namespace = cfg["k8s_namespace"]
        if not self._k8s_cli_available():
            _k8s_client, _core = self._k8s_sdk_clients()
            batch = _k8s_client.BatchV1Api()
            try:
                batch.create_namespaced_job(namespace=namespace, body=manifest)
            except Exception as exc:
                raise ValueError(f"Kubernetes Python client job create failed: {exc}") from exc
            name = manifest["metadata"]["name"]
            self._set_cluster_record(
                task,
                "k8s",
                "job",
                name,
                cfg["image"],
                namespace=namespace,
                manifest_path=manifest_path,
                ports=self._published_ports(cmd_api, terminal_api, web_console, "k8s"),
            )
            self._append_task_log(task["stdout_log_path"], f"Started Kubernetes job {namespace}/{name}")
            self._k8s_sdk_log_capture(task, namespace, "")
            return task["cluster"]

        cmd = ["kubectl", "apply", "-n", namespace, "-f", manifest_path]
        code, stdout, stderr = self._run_control_command(cmd, timeout=30.0)
        if code != 0:
            raise ValueError(f"kubectl apply failed: {(stderr or stdout).strip()}")
        name = manifest["metadata"]["name"]
        self._set_cluster_record(
            task,
            "k8s",
            "job",
            name,
            cfg["image"],
            namespace=namespace,
            manifest_path=manifest_path,
            ports=self._published_ports(cmd_api, terminal_api, web_console, "k8s"),
        )
        self._append_task_log(task["stdout_log_path"], f"Started Kubernetes job {namespace}/{name}")
        self._start_k8s_port_forwards(task)
        self._start_external_log_capture(task, [
            "kubectl", "logs", "-f", "-n", namespace, f"job/{name}", "--all-containers=true"
        ])
        return task["cluster"]

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

    def _close_task_runtime(self, task_id: str, join_timeout: float = 5.0) -> None:
        runtime = self._task_runtime.pop(task_id, None)
        if not runtime:
            return
        for key in ("log_process",):
            proc = runtime.get(key)
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    try:
                        proc.kill()
                    except OSError:
                        pass
                except OSError:
                    pass
        stop_event = runtime.get("log_stop_event")
        if stop_event is not None:
            try:
                stop_event.set()
            except Exception:
                pass
        for proc in runtime.get("port_forward_processes") or []:
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    try:
                        proc.kill()
                    except OSError:
                        pass
                except OSError:
                    pass
        current_thread = threading.current_thread()
        for key in ("stdout_thread", "stderr_thread"):
            thread = runtime.get(key)
            if thread is not None and thread is not current_thread:
                try:
                    thread.join(timeout=join_timeout)
                except RuntimeError:
                    pass
        for key in ("stdout_log", "stderr_log"):
            fh = runtime.get(key)
            try:
                fh.flush()
            except Exception:
                pass
            try:
                fh.close()
            except Exception:
                pass

    def _cluster_alive_status(self, task: Dict[str, Any]) -> Tuple[bool, Optional[int], str]:
        mode = task.get("launch_mode", "process")
        cluster = task.get("cluster") or {}
        name = str(cluster.get("name") or "").strip()
        if mode == "docker":
            if not name:
                return False, None, "missing docker container name"
            if not self._docker_cli_available():
                try:
                    container = self._docker_sdk_client().containers.get(name)
                    container.reload()
                    state = container.attrs.get("State") or {}
                    running = bool(state.get("Running"))
                    exit_code = state.get("ExitCode")
                    return running, int(exit_code) if exit_code is not None else None, str(state.get("Status") or "")
                except Exception as exc:
                    return False, None, str(exc)
            code, stdout, stderr = self._run_control_command(
                ["docker", "inspect", "-f", "{{.State.Running}} {{.State.ExitCode}}", name],
                timeout=3.0,
            )
            if code != 0:
                return False, None, (stderr or stdout).strip()
            parts = stdout.strip().split()
            running = bool(parts and parts[0].lower() == "true")
            exit_code = None
            if len(parts) > 1:
                try:
                    exit_code = int(parts[1])
                except ValueError:
                    exit_code = None
            return running, exit_code, stdout.strip()
        if mode == "docker_swarm":
            if not name:
                return False, None, "missing docker service name"
            if not self._docker_cli_available():
                try:
                    service = self._docker_sdk_client().services.get(name)
                    tasks = service.tasks()
                    states = [str(((item.get("Status") or {}).get("State")) or "").lower() for item in tasks]
                    detail = ", ".join(states)
                    if any(state in {"running", "preparing", "starting", "pending", "assigned"} for state in states):
                        return True, None, detail
                    if any(state in {"failed", "rejected"} for state in states):
                        return False, 1, detail
                    if any(state in {"complete", "shutdown"} for state in states):
                        return False, 0, detail
                    return False, None, detail
                except Exception as exc:
                    return False, None, str(exc)
            code, stdout, stderr = self._run_control_command(
                ["docker", "service", "ps", name, "--no-trunc", "--format", "{{.CurrentState}}"],
                timeout=3.0,
            )
            if code != 0:
                return False, None, (stderr or stdout).strip()
            current = stdout.strip().lower()
            if "running" in current or "preparing" in current or "starting" in current:
                return True, None, stdout.strip()
            if "complete" in current or "shutdown" in current:
                return False, 0, stdout.strip()
            if "failed" in current or "rejected" in current:
                return False, 1, stdout.strip()
            return False, None, stdout.strip()
        if mode == "k8s":
            if not name:
                return False, None, "missing Kubernetes job name"
            namespace = str(cluster.get("namespace") or self._launch_cluster_config()["k8s_namespace"])
            if not self._k8s_cli_available():
                try:
                    _k8s_client, _core = self._k8s_sdk_clients()
                    job = _k8s_client.BatchV1Api().read_namespaced_job(name=name, namespace=namespace)
                    status = job.status
                    return self._cluster_job_status(
                        self._int_or_zero(status.active if status else 0),
                        self._int_or_zero(status.succeeded if status else 0),
                        self._int_or_zero(status.failed if status else 0),
                    )
                except Exception as exc:
                    return False, None, str(exc)
            code, stdout, stderr = self._run_control_command(
                [
                    "kubectl", "get", "job", name,
                    "-n", namespace,
                    "-o", f"jsonpath={_K8S_JOB_STATUS_JSONPATH}",
                ],
                timeout=4.0,
            )
            if code != 0:
                return False, None, (stderr or stdout).strip()
            parts = stdout.strip().split()
            return self._cluster_job_status(
                self._int_or_zero(parts[0] if len(parts) > 0 else 0),
                self._int_or_zero(parts[1] if len(parts) > 1 else 0),
                self._int_or_zero(parts[2] if len(parts) > 2 else 0),
            )
        return False, None, ""

    def _flush_task_runtime_logs(self, task_id: str) -> None:
        runtime = self._task_runtime.get(task_id)
        if not runtime:
            return
        for key in ("stdout_log", "stderr_log"):
            fh = runtime.get(key)
            try:
                fh.flush()
            except Exception:
                pass

    def _drain_finished_task_runtime(self, task: Dict[str, Any]) -> None:
        runtime = self._task_runtime.get(task.get("task_id"))
        if not runtime:
            return
        proc = runtime.get("process")
        if proc is not None and proc.poll() is not None:
            self._close_task_runtime(task["task_id"])
            task["exit_code"] = proc.returncode
            task["finished_at"] = task.get("finished_at") or _now()
            task["process_status"] = (
                "stopped"
                if task.get("process_status") == "stopping" or proc.returncode == 0
                else "failed"
            )
            task["cmd_api"]["status"] = "stopped"
            task["terminal_api"]["status"] = "stopped"
            self._mark_dirty()
        else:
            self._flush_task_runtime_logs(task["task_id"])

    def _probe_child_service(self, svc: Dict[str, Any], task: Optional[Dict[str, Any]] = None) -> bool:
        if not svc.get("enabled"):
            return False
        try:
            import requests

            kwargs: Dict[str, Any] = {"timeout": 1.5}
            if svc.get("password"):
                kwargs["auth"] = ("", svc["password"])
            base = self._task_service_base_url(task, svc) if task else str(svc.get("base_url_internal") or "").strip()
            if not base:
                return False
            url = base.rstrip("/") + "/api/status"
            resp = requests.get(url, **kwargs)
            return resp.ok
        except Exception:
            return False

    def _task_swarm_service_base_url(self, task: Dict[str, Any], svc: Dict[str, Any]) -> str:
        if task.get("launch_mode") != "docker_swarm":
            return ""
        cluster = task.get("cluster") or {}
        name = str(cluster.get("name") or "").strip()
        if not name:
            return ""
        try:
            port = int(svc.get("port"))
        except (TypeError, ValueError):
            return ""
        return f"http://{name}:{port}"

    def _task_service_base_url(self, task: Dict[str, Any], svc: Dict[str, Any]) -> str:
        base = self._task_swarm_service_base_url(task, svc)
        if not base:
            base = str(svc.get("base_url_internal") or svc.get("tcp_url") or "").strip()
        if not base and svc.get("host") and svc.get("port"):
            base = f"{svc['host']}:{svc['port']}"
        if base and not base.startswith("http"):
            base = f"http://{base}"
        return base.rstrip("/")

    def _agent_for_task_unlocked(self, task: Dict[str, Any], agents: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        task_client_id = str(task.get("client_id") or "").strip()
        pid = task.get("pid")
        pid_str = str(pid) if pid not in (None, "") else ""
        task_workspace = os.path.abspath(task.get("workspace_dir", "")) if task.get("workspace_dir") else ""
        for agent in agents:
            agent_id = str(agent.get("id") or "").strip()
            if task_client_id and agent_id == task_client_id:
                return agent
            extra = agent.get("extra") or {}
            agent_pid = extra.get("pid")
            agent_pid_str = str(agent_pid) if agent_pid not in (None, "") else ""
            agent_workspace = str(extra.get("workspace") or "").strip()
            agent_workspace_abs = os.path.abspath(agent_workspace) if agent_workspace else ""
            if (pid_str and agent_pid_str == pid_str) or (task_workspace and agent_workspace_abs == task_workspace):
                return agent
        return None

    def _remember_agent_launch_task_id(self, agent_id: str, task_id: str) -> bool:
        agent_id = str(agent_id or "").strip()
        task_id = str(task_id or "").strip()
        if not agent_id or not task_id:
            return False
        with self._agents_lock:
            agent = self._agents.get(agent_id)
            if agent is None or agent.get("last_launch_task_id") == task_id:
                return False
            agent["last_launch_task_id"] = task_id
        self._mark_dirty()
        return True

    def _remember_task_launch_agent(self, task: Dict[str, Any]) -> None:
        task_id = str((task or {}).get("task_id") or "").strip()
        if not task_id:
            return
        for key in ("registered_agent_id", "client_id"):
            if self._remember_agent_launch_task_id(str((task or {}).get(key) or ""), task_id):
                return
        with self._agents_lock:
            agents = list(self._agents.values())
        matched_agent = self._agent_for_task_unlocked(task or {}, agents)
        matched_agent_id = str((matched_agent or {}).get("id") or "").strip()
        self._remember_agent_launch_task_id(matched_agent_id, task_id)

    def _merge_task_agent_runtime_info(self, task: Dict[str, Any], agent: Dict[str, Any]) -> bool:
        changed = False
        cmd_api_tcp = str(agent.get("cmd_api_tcp") or "").strip()
        if cmd_api_tcp:
            reported_cmd_api = {"tcp_url": cmd_api_tcp}
            if task.get("launch_mode") != "docker_swarm":
                reported_cmd_api["base_url_internal"] = cmd_api_tcp
            merged_cmd_api = _merge_runtime_service_info(task.get("cmd_api"), reported_cmd_api)
            if merged_cmd_api != (task.get("cmd_api") or {}):
                task["cmd_api"] = merged_cmd_api
                changed = True
        reported_terminal_api = agent.get("terminal_api") or {}
        merged_terminal_api = _merge_runtime_service_info(task.get("terminal_api"), reported_terminal_api)
        if merged_terminal_api != (task.get("terminal_api") or {}):
            task["terminal_api"] = merged_terminal_api
            changed = True
        reported_web_console = agent.get("web_console") or {}
        merged_web_console = _merge_runtime_service_info(task.get("web_console"), reported_web_console)
        if merged_web_console != (task.get("web_console") or {}):
            task["web_console"] = merged_web_console
            changed = True
        return changed

    def _refresh_task_runtime_info_from_agent(self, task: Dict[str, Any]) -> None:
        with self._agents_lock:
            agent = self._agent_for_task_unlocked(task, list(self._agents.values()))
        if agent and self._merge_task_agent_runtime_info(task, agent):
            self._mark_dirty()

    def _refresh_task_states(self) -> None:
        now = _now()
        agents = self._snapshot_agents()
        remembered_launch_agents: List[Tuple[str, str]] = []
        with self._tasks_lock:
            for task_id, task in list(self._tasks.items()):
                launch_mode = task.get("launch_mode", "process")
                pid = task.get("pid")
                runtime = self._task_runtime.get(task_id)
                matched_agent = self._agent_for_task_unlocked(task, agents)
                matched_agent_id = str((matched_agent or {}).get("id") or "").strip()
                matched_agent_online = bool(matched_agent and self._agent_is_online(matched_agent))
                matched_agent_exited = bool(matched_agent and matched_agent.get("client_exit"))
                if matched_agent_id:
                    remembered_launch_agents.append((matched_agent_id, task_id))
                if matched_agent and self._merge_task_agent_runtime_info(task, matched_agent):
                    self._mark_dirty()
                registered = matched_agent_online
                if task.get("registered_to_master") != registered:
                    task["registered_to_master"] = registered
                    self._mark_dirty()
                if task.get("registered_agent_id") != matched_agent_id:
                    task["registered_agent_id"] = matched_agent_id
                    self._mark_dirty()

                if (
                    task.get("process_status") == "starting"
                    and not task.get("started_at")
                    and not task.get("finished_at")
                    and (
                        (launch_mode == "process" and not runtime and not pid)
                        or (
                            launch_mode in _CONTAINER_LAUNCH_MODES
                            and not str((task.get("cluster") or {}).get("name") or "").strip()
                        )
                    )
                ):
                    continue

                alive = False
                runtime_exit_detected = False
                cluster_state_unknown = False
                exit_code = task.get("exit_code")
                if launch_mode in _CONTAINER_LAUNCH_MODES:
                    alive, cluster_exit_code, _cluster_detail = self._cluster_alive_status(task)
                    if cluster_exit_code is not None:
                        exit_code = cluster_exit_code
                    cluster_state_unknown = not alive and cluster_exit_code is None
                    runtime_exit_detected = not alive and cluster_exit_code is not None
                    if launch_mode == "k8s" and alive:
                        self._start_k8s_port_forwards(task)
                elif runtime and runtime.get("process") is not None:
                    code = runtime["process"].poll()
                    alive = code is None
                    if code is not None:
                        exit_code = code
                        runtime_exit_detected = True
                else:
                    alive = _is_pid_alive(pid)
                    runtime_exit_detected = bool(pid) and not alive

                if task["process_status"] in {"starting", "running", "stopping"}:
                    cmd_ok = self._probe_child_service(task["cmd_api"], task)
                    term_ok = self._probe_child_service(task["terminal_api"], task)
                    term_enabled = bool((task.get("terminal_api") or {}).get("enabled"))
                    if cluster_state_unknown:
                        started_at = float(task.get("started_at") or task.get("created_at") or 0)
                        if task["process_status"] == "starting" and started_at and (now - started_at) < 15:
                            continue
                        runtime_exit_detected = True
                    if not runtime_exit_detected and (matched_agent_online or cmd_ok):
                        alive = True
                    if not alive:
                        task["finished_at"] = task.get("finished_at") or now
                        task["exit_code"] = exit_code
                        task["process_status"] = (
                            "stopped"
                            if task["process_status"] == "stopping" or exit_code in (None, 0)
                            else "failed"
                        )
                        if launch_mode == "docker_swarm" and not task.get("cluster_debug_logged"):
                            cluster_name = str((task.get("cluster") or {}).get("name") or "").strip()
                            detail = self._docker_swarm_task_detail(cluster_name)
                            if detail:
                                self._append_task_log(
                                    task["stderr_log_path"],
                                    f"Docker Swarm task detail for {cluster_name}:\n{detail}",
                                )
                            task["cluster_debug_logged"] = True
                        task["cmd_api"]["status"] = "stopped"
                        task["terminal_api"]["status"] = "stopped"
                        self._close_task_runtime(task_id)
                        self._mark_dirty()
                    else:
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
                if matched_agent_exited and task.get("process_status") in {"stopped", "failed"} and not alive:
                    self._close_task_runtime(task_id)
                    self._tasks.pop(task_id, None)
                    self._mark_dirty()
                    _master_log(
                        f"Task '{task_id}' removed after client '{matched_agent_id}' exited "
                        "and its runtime stopped"
                    )
        for agent_id, task_id in remembered_launch_agents:
            self._remember_agent_launch_task_id(agent_id, task_id)

    def _run_task_launch(self, req: Dict[str, Any]) -> Dict[str, Any]:
        req = dict(req)
        default_args = self.cfg.get_value("launch.default_args", {}) or {}
        if hasattr(default_args, "as_dict"):
            default_args = default_args.as_dict()
        if isinstance(default_args, dict):
            req = _merge_launch_default_args(req, default_args)
        enabled_launch_modes = self._enabled_launch_modes()
        requested_launch_mode = req.get("launch_mode", req.get("launch_type", req.get("runtime", None)))
        if isinstance(requested_launch_mode, (list, tuple, set)):
            requested_launch_mode = next(iter(requested_launch_mode), None)
        launch_mode = (
            _normalize_launch_mode(requested_launch_mode)
            if requested_launch_mode not in (None, "")
            else enabled_launch_modes[0]
        )
        if launch_mode not in enabled_launch_modes:
            raise ValueError(
                f"Launch mode '{launch_mode}' is not enabled. Enabled launch modes: {', '.join(enabled_launch_modes)}"
        )
        req["launch_mode"] = launch_mode
        self._ensure_launch_mode_supported(launch_mode)
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
        current_f_filelists = sorted(
            os.path.abspath(item.get("stored_path", ""))
            for item in ws.get("files", [])
            if _is_picker_f_file(item.get("stored_path") or item.get("original_name") or "")
        )
        compiled_f_filelists = sorted(
            os.path.abspath(str(path))
            for path in (compile_info.get("source_f_filelist_paths") or compile_info.get("f_filelist_paths") or [])
            if str(path or "").strip()
        )
        requested_picker_args = self._effective_picker_args(req.get("picker_args", req.get("picker_extra_args", None)))
        compile_matches = (
            compile_info.get("status") == "success"
            and compile_info.get("dut_name") == _safe_name(effective_dut, "DUT")
            and compile_info.get("selected_module") == selected_module
            and compiled_f_filelists == current_f_filelists
            and list(compile_info.get("picker_extra_args") or []) == requested_picker_args
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
            "source_f_filelist_paths": list(compile_info.get("source_f_filelist_paths") or []),
            "f_filelist_paths": list(compile_info.get("f_filelist_paths") or []),
            "generated_filelist": bool(compile_info.get("generated_filelist")),
            "copied_files": list(compile_info.get("copied_files") or []),
            "config_path": compile_info.get("config_path", ""),
            "use_zip_workspace": bool(req.get("use_zip_workspace", True)),
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
            "host": self._launch_bind_host(launch_mode, cmd_api_host),
            "port": cmd_api_port,
            "password": cmd_api_password or secrets.token_hex(8),
            "base_url_internal": self._service_base_url(launch_mode, cmd_api_host, cmd_api_port),
            "status": "starting",
        }
        req["export_cmd_api"] = f"{cmd_api['host']}:{cmd_api['port']} {cmd_api['password']}"

        terminal_api = {"enabled": False, "status": "stopped"}
        web_terminal_spec = req.get("web_terminal")
        if web_terminal_spec is not None:
            term_host, term_port, term_password = _parse_web_terminal_spec(str(web_terminal_spec))
            # Use cmd_api password if web terminal password is not provided
            if not term_password:
                term_password = cmd_api["password"]
            req["web_terminal"] = f"{self._launch_bind_host(launch_mode, term_host)}:{term_port} {term_password}"
            terminal_api = {
                "enabled": True,
                "host": self._launch_bind_host(launch_mode, term_host),
                "port": term_port,
                "password": term_password,
                "base_url_internal": self._service_base_url(launch_mode, term_host, term_port),
                "status": "starting",
            }
        web_console = {"enabled": False, "status": "stopped"}
        web_console_spec = req.get("web_console")
        if web_console_spec not in (None, False, ""):
            wc_host, wc_port, wc_password = _resolve_web_console_spec(web_console_spec)
            # Use cmd_api password if web console password is not provided
            if not wc_password:
                wc_password = cmd_api["password"]
            # Build command line argument with space-separated format
            req["web_console"] = f"{self._launch_bind_host(launch_mode, wc_host)}:{wc_port} {wc_password}"
            web_console = {
                "enabled": True,
                "host": self._launch_bind_host(launch_mode, wc_host),
                "port": wc_port,
                "password": wc_password,
                "base_url_internal": self._service_base_url(launch_mode, wc_host, wc_port),
                "status": "starting",
            }

        task = self._create_task_record({
            "task_id": str(ws.get("task_id") or workspace_id).strip(),
            "task_name": req.get("task_name") or selected_module,
            "client_id": req.get("client_id", ""),
            "workspace_id": workspace_id,
            "launch_mode": launch_mode,
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

        with self._workspaces_lock:
            ws_locked = self._workspaces.get(workspace_id)
            if ws_locked is not None:
                ws_locked["last_launch_client_id"] = str(req.get("client_id") or "").strip()

        task["picker_command"] = list(compile_info.get("picker_command") or [])
        task["picker_exit_code"] = compile_info.get("picker_exit_code")
        task["picker_status"] = compile_info.get("status", "not_started")
        req["task_id"] = task["task_id"]
        self._mark_dirty()

        if task["picker_status"] != "success":
            task["process_status"] = "failed"
            task["finished_at"] = _now()
            return task

        if web_console.get("enabled"):
            req["web_console_capture_path"] = task["web_console_log_path"]

        master_host_for_task = ""
        if launch_mode in {"docker", "docker_swarm"}:
            network = str(self._launch_cluster_config().get("docker_network") or "").strip()
            network_master_host = self._prepare_docker_task_network(launch_mode, network, task)
            if launch_mode == "docker" and network_master_host:
                master_host_for_task = network_master_host
            self._append_docker_connectivity_debug(
                task,
                launch_mode,
                master_host_for_task,
                cmd_api,
                terminal_api,
                web_console,
            )

        resolved_command, env = self._build_ucagent_command(req, prepared, cmd_api, master_host_for_task)
        task["resolved_command"] = resolved_command
        task["process_status"] = "starting"
        try:
            if launch_mode == "process":
                proc = self._start_task_process(task, env)
                task["pid"] = proc.pid
            elif launch_mode == "docker":
                self._start_task_docker(task, env, prepared, cmd_api, terminal_api, web_console, master_host_for_task)
                proc = None
            elif launch_mode == "docker_swarm":
                self._start_task_docker_swarm(task, env, prepared, cmd_api, terminal_api, web_console)
                proc = None
            elif launch_mode == "k8s":
                self._start_task_k8s(task, env, prepared, cmd_api, terminal_api, web_console)
                proc = None
            else:
                raise ValueError(f"Unsupported launch mode '{launch_mode}'")
        except Exception as exc:
            task["process_status"] = "failed"
            task["exit_code"] = task.get("exit_code")
            task["finished_at"] = _now()
            task["cmd_api"]["status"] = "stopped"
            task["terminal_api"]["status"] = "stopped"
            self._append_task_log(task["stderr_log_path"], f"Launch failed in {launch_mode} mode: {exc}")
            self._mark_dirty()
            raise
        task["started_at"] = _now()
        code = proc.poll() if proc is not None else None
        if proc is not None and code is not None:
            self._close_task_runtime(task["task_id"])
            task["process_status"] = "failed" if code != 0 else "stopped"
            task["exit_code"] = code
            task["finished_at"] = _now()
            task["cmd_api"]["status"] = "stopped"
            task["terminal_api"]["status"] = "stopped"
        else:
            task["cmd_api"]["status"] = "starting"
            if not task["terminal_api"].get("enabled"):
                task["terminal_api"]["status"] = "stopped"
        self._mark_workspace_launched(workspace_id, task["task_id"])
        self._mark_dirty()
        return task

    def _terminate_task(self, task: Dict[str, Any], force: bool = False) -> None:
        launch_mode = task.get("launch_mode", "process")
        if launch_mode == "docker":
            name = str((task.get("cluster") or {}).get("name") or "").strip()
            if name:
                if self._docker_cli_available():
                    cmd = ["docker", "rm", "-f", name] if force else ["docker", "stop", name]
                    self._run_control_command(cmd, timeout=15.0)
                else:
                    try:
                        container = self._docker_sdk_client().containers.get(name)
                        if force:
                            container.remove(force=True)
                        else:
                            container.stop(timeout=15)
                    except Exception as exc:
                        self._append_task_log(task["stderr_log_path"], f"Failed to stop Docker container via SDK: {exc}")
            return
        if launch_mode == "docker_swarm":
            name = str((task.get("cluster") or {}).get("name") or "").strip()
            if name:
                if self._docker_cli_available():
                    self._run_control_command(["docker", "service", "rm", name], timeout=15.0)
                else:
                    try:
                        self._docker_sdk_client().services.get(name).remove()
                    except Exception as exc:
                        self._append_task_log(task["stderr_log_path"], f"Failed to remove Docker Swarm service via SDK: {exc}")
            return
        if launch_mode == "k8s":
            cluster = task.get("cluster") or {}
            name = str(cluster.get("name") or "").strip()
            namespace = str(cluster.get("namespace") or self._launch_cluster_config()["k8s_namespace"])
            if name:
                grace = "0" if force else "30"
                if self._k8s_cli_available():
                    self._run_control_command(
                        ["kubectl", "delete", "job", name, "-n", namespace, "--grace-period", grace, "--ignore-not-found=true"],
                        timeout=20.0,
                    )
                else:
                    try:
                        _k8s_client, _core = self._k8s_sdk_clients()
                        body = _k8s_client.V1DeleteOptions(
                            grace_period_seconds=int(grace),
                            propagation_policy="Background",
                        )
                        _k8s_client.BatchV1Api().delete_namespaced_job(name=name, namespace=namespace, body=body)
                    except Exception as exc:
                        self._append_task_log(task["stderr_log_path"], f"Failed to delete Kubernetes job via SDK: {exc}")
            self._close_task_runtime(task["task_id"], join_timeout=1.0)
            return
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
            logs = _task_logs_for_display(task)
            data["stdout_tail"] = logs["stdout"]
            data["stderr_tail"] = logs["stderr"]
        else:
            data.pop("stdout_log_path", None)
            data.pop("stderr_log_path", None)
            data.pop("web_console_log_path", None)
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

    def _launch_default_env_updates(self) -> Dict[str, str]:
        configured = self.cfg.get_value("launch.default_env", []) or []
        if hasattr(configured, "as_dict"):
            configured = configured.as_dict()
        if not isinstance(configured, list):
            configured = []
        current = {str(k): str(v) for k, v in (os.environ or {}).items()}
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
            raw_value = str(raw).strip()
            if not key:
                continue
            match = raw_value.startswith("$")
            if match:
                ref_key = raw_value[1:].strip()
                ref_val = str(current.get(ref_key, "")).strip()
                if ref_val:
                    default_updates[key] = ref_val
                    current[key] = ref_val
                    warning(f"Launch default env: set '{key}' from reference '{ref_key}' with value '{_mask_secret(ref_val)}'")
                else:
                    warning(f"Launch default env: reference '{ref_key}' for key '{key}' is not set in environment; skipping")
                continue
            if raw_value:
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

    def _agent_cached_launch_task_id(self, agent: Dict[str, Any]) -> str:
        if not agent:
            return ""
        for key in ("launch_task_id", "last_launch_task_id", "managed_task_id"):
            value = str(agent.get(key) or "").strip()
            if value:
                return value
        extra = agent.get("extra") or {}
        if isinstance(extra, dict):
            for key in ("launch_task_id", "task_id", "ucagent_task_id"):
                value = str(extra.get(key) or "").strip()
                if value:
                    return value
        agent_id = str(agent.get("id") or "").strip()
        if not agent_id:
            return ""
        agent_workspace = str(extra.get("workspace") or "").strip() if isinstance(extra, dict) else ""
        agent_workspace_real = os.path.realpath(os.path.abspath(agent_workspace)) if agent_workspace else ""
        agent_workspace_parent = os.path.basename(os.path.dirname(agent_workspace_real)) if agent_workspace_real else ""

        def _num(value: Any) -> float:
            try:
                return float(value or 0)
            except (TypeError, ValueError):
                return 0.0

        candidates: List[Tuple[float, str]] = []
        with self._workspaces_lock:
            workspaces = [dict(ws) for ws in self._workspaces.values()]
        for ws in workspaces:
            ws_id = str(ws.get("workspace_id") or "").strip()
            ws_task_id = str(ws.get("task_id") or "").strip()
            if not ws_task_id:
                continue
            last_client_id = str(ws.get("last_launch_client_id") or "").strip()
            sync_info = ws.get("last_sync_back") or {}
            sync_agent_id = str(sync_info.get("agent_id") or "").strip() if isinstance(sync_info, dict) else ""
            related = bool(last_client_id and last_client_id == agent_id)
            related = related or bool(sync_agent_id and sync_agent_id == agent_id)
            if agent_workspace_parent:
                related = related or agent_workspace_parent in {ws_id, ws_task_id}
            if not related:
                continue
            recency = max(
                _num(ws.get("last_seen")),
                _num(ws.get("created_at")),
                _num(sync_info.get("synced_at") if isinstance(sync_info, dict) else 0),
            )
            candidates.append((recency, ws_task_id))
        if not candidates:
            return ""
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _task_completed_sub_workspace(self, task: Optional[Dict[str, Any]]) -> str:
        if not task:
            return ""
        candidate = ""
        sync_info = task.get("workspace_sync_back") or {}
        if isinstance(sync_info, dict):
            candidate = str(sync_info.get("target_dir") or "").strip()
        if not candidate:
            workspace_id = str(task.get("workspace_id") or "").strip()
            if workspace_id:
                try:
                    with self._workspaces_lock:
                        ws = self._workspaces.get(workspace_id)
                        ws = dict(ws) if ws else None
                    if ws:
                        candidate = self._compiled_workspace_dir(ws)
                except (KeyError, ValueError, OSError):
                    candidate = ""
        return self._completed_sub_workspace_from_path(candidate)

    def _completed_sub_workspace_from_path(self, path: str) -> str:
        candidate = str(path or "").strip()
        if not candidate:
            return ""
        candidate = os.path.abspath(candidate)
        info_path = os.path.join(candidate, ".ucagent", "ucagent_info.json")
        if not os.path.isfile(info_path):
            return ""
        base = os.path.abspath(self.workspace)
        if not _path_is_under(base, candidate):
            return ""
        rel = os.path.relpath(candidate, base)
        return "" if rel == "." else rel

    def _agent_completed_sub_workspace(self, agent: Dict[str, Any], launch_task: Optional[Dict[str, Any]] = None) -> str:
        completed = self._task_completed_sub_workspace(launch_task)
        if completed:
            return completed
        agent_id = str((agent or {}).get("id") or "").strip()
        if not agent_id:
            return ""
        extra = (agent or {}).get("extra") or {}
        agent_workspace = str(extra.get("workspace") or "").strip()
        agent_workspace_real = os.path.realpath(os.path.abspath(agent_workspace)) if agent_workspace else ""
        agent_workspace_parent = os.path.basename(os.path.dirname(agent_workspace_real)) if agent_workspace_real else ""

        def _num(value: Any) -> float:
            try:
                return float(value or 0)
            except (TypeError, ValueError):
                return 0.0

        candidates: List[Tuple[int, float, str]] = []
        with self._workspaces_lock:
            workspaces = [dict(ws) for ws in self._workspaces.values()]
        for ws in workspaces:
            ws_id = str(ws.get("workspace_id") or "").strip()
            ws_task_id = str(ws.get("task_id") or "").strip()
            last_client_id = str(ws.get("last_launch_client_id") or "").strip()
            sync_info = ws.get("last_sync_back") or {}
            sync_agent_id = str(sync_info.get("agent_id") or "").strip() if isinstance(sync_info, dict) else ""
            related = bool(last_client_id and last_client_id == agent_id)
            related = related or bool(sync_agent_id and sync_agent_id == agent_id)
            if agent_workspace_parent:
                related = related or agent_workspace_parent in {ws_id, ws_task_id}
            try:
                compiled_path = self._compiled_workspace_match_path(ws)
            except Exception:
                compiled_path = ""
            compiled_real = os.path.realpath(os.path.abspath(compiled_path)) if compiled_path else ""
            if agent_workspace_real and compiled_real and agent_workspace_real == compiled_real:
                related = True
            if not related:
                continue
            recency = max(_num(ws.get("last_seen")), _num(ws.get("created_at")), _num(sync_info.get("synced_at") if isinstance(sync_info, dict) else 0))
            sync_target = str(sync_info.get("target_dir") or "").strip() if isinstance(sync_info, dict) else ""
            if sync_target:
                candidates.append((0, -recency, sync_target))
            if compiled_path:
                candidates.append((1, -recency, compiled_path))
        candidates.sort()
        for _priority, _recency, candidate in candidates:
            completed = self._completed_sub_workspace_from_path(candidate)
            if completed:
                return completed
        return ""

    def _task_is_finished(self, task: Optional[Dict[str, Any]]) -> bool:
        if not task:
            return False
        status = str(task.get("process_status") or "").strip().lower()
        return status in {"stopped", "failed"} or bool(task.get("finished_at"))

    def _compiled_workspace_match_path(self, ws: Dict[str, Any]) -> str:
        try:
            return os.path.abspath(self._compiled_workspace_dir(dict(ws)))
        except Exception:
            compile_info = ws.get("compile") or {}
            for value in (
                compile_info.get("picker_workspace"),
                ws.get("picker_workspace"),
                os.path.join(str(ws.get("workspace_dir") or ""), "workspace"),
            ):
                if value:
                    return os.path.abspath(str(value))
        return ""

    def _relaunch_ucagent_info_path(self, ws: Dict[str, Any]) -> str:
        workspace_root = self._compiled_workspace_match_path(ws)
        if not workspace_root:
            return ""
        return os.path.join(workspace_root, ".ucagent", "ucagent_info.json")

    def _relaunch_ucagent_info_backup_path(self, info_path: str, config_ref: str) -> str:
        config_name = _config_ref_name(config_ref) or "default"
        safe_config_name = _safe_name(config_name, "config")
        digest = hashlib.sha256(config_name.encode("utf-8")).hexdigest()[:12]
        return os.path.join(os.path.dirname(info_path), f"ucagent_info_{safe_config_name}_{digest}.json")

    def _copy_file_atomic(self, source_path: str, target_path: str) -> None:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        tmp_path = f"{target_path}.tmp-{secrets.token_hex(6)}"
        try:
            shutil.copy2(source_path, tmp_path)
            os.replace(tmp_path, target_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _write_empty_file_atomic(self, target_path: str) -> None:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        tmp_path = f"{target_path}.tmp-{secrets.token_hex(6)}"
        try:
            with open(tmp_path, "w", encoding="utf-8"):
                pass
            os.replace(tmp_path, target_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _write_json_atomic(self, target_path: str, data: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        tmp_path = f"{target_path}.tmp-{secrets.token_hex(6)}"
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, target_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _load_relaunch_ucagent_info(self, ws: Dict[str, Any]) -> Dict[str, Any]:
        info_path = self._relaunch_ucagent_info_path(ws)
        data: Dict[str, Any] = {}
        load_error = ""
        exists = bool(info_path and os.path.isfile(info_path))
        if exists:
            try:
                with open(info_path, "r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, dict):
                    data = loaded
            except Exception as exc:
                load_error = str(exc)
        config_file = str(data.get("config_file") or data.get("config_arg") or "").strip()
        return {
            "exists": exists,
            "path": info_path,
            "config_file": config_file,
            "config_arg": config_file,
            "load_error": load_error,
        }

    def _config_refs_match(self, left: str, right: str) -> bool:
        left = str(left or "").strip()
        right = str(right or "").strip()
        if not left or not right:
            return left == right
        if left == right:
            return True
        left_base = _config_ref_name(left)
        right_base = _config_ref_name(right)
        return bool(left_base and right_base and left_base == right_base)

    def _switch_relaunch_ucagent_info_config(
        self,
        ws: Dict[str, Any],
        target_config: str = "",
    ) -> Dict[str, Any]:
        info = self._load_relaunch_ucagent_info(ws)
        info_path = str(info.get("path") or "")
        if not info_path:
            raise ValueError("Unable to determine .ucagent/ucagent_info.json path for relaunch workspace")

        os.makedirs(os.path.dirname(info_path), exist_ok=True)
        target_config = str(target_config or "").strip()
        current_config = str(info.get("config_file") or info.get("config_arg") or "").strip()
        backup_path = ""
        backed_up = False
        restored = False
        cleared = False
        initialized = False
        target_backup_path = self._relaunch_ucagent_info_backup_path(info_path, target_config) if target_config else ""

        if current_config and os.path.isfile(info_path) and os.path.getsize(info_path) > 0:
            backup_path = self._relaunch_ucagent_info_backup_path(info_path, current_config)
            self._copy_file_atomic(info_path, backup_path)
            backed_up = True

        needs_target_switch = not target_config or not self._config_refs_match(current_config, target_config)
        if needs_target_switch:
            if target_backup_path and os.path.isfile(target_backup_path):
                self._copy_file_atomic(target_backup_path, info_path)
                restored = True
            elif target_config:
                self._write_json_atomic(info_path, {
                    "config_file": target_config,
                    "config_arg": target_config,
                })
                initialized = True
                cleared = True
            else:
                self._write_empty_file_atomic(info_path)
                cleared = True

        switched_info = self._load_relaunch_ucagent_info(ws)
        switched_info.update({
            "previous_config_file": current_config,
            "target_config_file": target_config,
            "backup_path": backup_path,
            "target_backup_path": target_backup_path,
            "backed_up": backed_up,
            "restored": restored,
            "cleared": cleared,
            "initialized": initialized,
            "switched": needs_target_switch,
        })
        return {
            "cleared": cleared,
            "deleted": False,
            "backed_up": backed_up,
            "restored": restored,
            "initialized": initialized,
            "switched": needs_target_switch,
            "backup_path": backup_path,
            "target_backup_path": target_backup_path,
            "ucagent_info": switched_info,
        }

    def _clear_relaunch_ucagent_info(
        self,
        *,
        task_id: str = "",
        workspace_id: str = "",
        sub_workspace: str = "",
        target_config: str = "",
    ) -> Dict[str, Any]:
        target = self._resolve_relaunch_target(
            task_id=task_id,
            workspace_id=workspace_id,
            sub_workspace=sub_workspace,
        )
        blockers = self._relaunch_blockers(target["task_id"], target["workspace"])
        if blockers:
            raise ValueError(" ".join(blockers))
        switch_info = self._switch_relaunch_ucagent_info_config(target["workspace"], target_config)
        return {
            **switch_info,
            "task_id": target["task_id"],
            "workspace_id": target["workspace_id"],
        }

    def _resolve_relaunch_target(
        self,
        *,
        task_id: str = "",
        workspace_id: str = "",
        sub_workspace: str = "",
    ) -> Dict[str, Any]:
        task_id = str(task_id or "").strip()
        workspace_id = str(workspace_id or "").strip()
        sub_workspace = str(sub_workspace or "").strip().strip("/")
        task_snapshot: Optional[Dict[str, Any]] = None
        if task_id:
            with self._tasks_lock:
                existing_task = self._tasks.get(task_id)
                task_snapshot = dict(existing_task) if existing_task else None
            if task_snapshot and not workspace_id:
                workspace_id = str(task_snapshot.get("workspace_id") or "").strip()

        candidate_abs = ""
        if sub_workspace:
            expanded = os.path.expanduser(sub_workspace)
            candidate_abs = (
                os.path.abspath(expanded)
                if os.path.isabs(expanded)
                else os.path.abspath(os.path.join(self.workspace, expanded))
            )
            if not _path_is_under(self.workspace, candidate_abs):
                raise ValueError("Sub workspace must be under the master workspace")

        workspaces: List[Dict[str, Any]] = []
        with self._workspaces_lock:
            for ws in self._workspaces.values():
                self._normalize_workspace_locked(ws)
                workspaces.append(dict(ws))

        def _matches(ws: Dict[str, Any]) -> bool:
            ws_id = str(ws.get("workspace_id") or "").strip()
            ws_task_id = str(ws.get("task_id") or "").strip()
            if workspace_id and ws_id == workspace_id:
                return True
            if task_id and (ws_task_id == task_id or ws_id == task_id):
                return True
            if candidate_abs:
                paths = [
                    self._compiled_workspace_match_path(ws),
                    str((ws.get("compile") or {}).get("picker_workspace") or ""),
                    str(ws.get("picker_workspace") or ""),
                    os.path.join(str(ws.get("workspace_dir") or ""), "workspace"),
                ]
                for path in paths:
                    if path and os.path.realpath(os.path.abspath(path)) == os.path.realpath(candidate_abs):
                        return True
                    if path and _path_is_under(os.path.abspath(path), candidate_abs) and os.path.realpath(os.path.abspath(path)) == os.path.realpath(candidate_abs):
                        return True
            return False

        matched = next((ws for ws in workspaces if _matches(ws)), None)
        if matched is None and candidate_abs:
            first_part = sub_workspace.split("/", 1)[0] if sub_workspace else ""
            if first_part:
                matched = next(
                    (
                        ws for ws in workspaces
                        if str(ws.get("workspace_id") or "").strip() == first_part
                        or str(ws.get("task_id") or "").strip() == first_part
                    ),
                    None,
                )
        if matched is None:
            ref = task_id or workspace_id or sub_workspace
            raise KeyError(f"Relaunch workspace for '{ref}' not found")

        resolved_task_id = str(matched.get("task_id") or matched.get("workspace_id") or "").strip()
        if task_id and resolved_task_id and resolved_task_id != task_id:
            raise ValueError(f"Sub workspace belongs to task '{resolved_task_id}', not '{task_id}'")
        if not task_id:
            task_id = resolved_task_id
        if not task_id:
            raise ValueError("Unable to determine relaunch task id")

        with self._tasks_lock:
            latest_task = self._tasks.get(task_id)
            task_snapshot = dict(latest_task) if latest_task else task_snapshot

        return {
            "task_id": task_id,
            "workspace_id": str(matched.get("workspace_id") or "").strip(),
            "workspace": matched,
            "task": task_snapshot,
            "sub_workspace": sub_workspace,
        }

    def _relaunch_blockers(self, task_id: str, ws: Dict[str, Any]) -> List[str]:
        task_id = str(task_id or "").strip()
        blockers: List[str] = []
        self._refresh_task_states()
        with self._tasks_lock:
            existing_task = self._tasks.get(task_id)
            if existing_task is not None:
                status = str(existing_task.get("process_status") or "unknown")
                blockers.append(
                    f"Task list still contains task '{task_id}' (status: {status}). "
                    "Stop/delete the old task record before relaunching."
                )

        compiled_path = self._compiled_workspace_match_path(ws)
        compiled_real = os.path.realpath(compiled_path) if compiled_path else ""
        workspace_id = str(ws.get("workspace_id") or "").strip()
        last_client_id = str(ws.get("last_launch_client_id") or "").strip()
        with self._agents_lock:
            for agent in self._agents.values():
                agent_id = str(agent.get("id") or "").strip()
                extra = agent.get("extra") or {}
                agent_workspace = str(extra.get("workspace") or "").strip()
                agent_workspace_real = os.path.realpath(os.path.abspath(agent_workspace)) if agent_workspace else ""
                parent_name = os.path.basename(os.path.dirname(agent_workspace_real)) if agent_workspace_real else ""
                related = False
                if last_client_id and agent_id == last_client_id:
                    related = True
                if task_id and (agent_id == task_id or parent_name == task_id):
                    related = True
                if workspace_id and parent_name == workspace_id:
                    related = True
                if compiled_real and agent_workspace_real == compiled_real:
                    related = True
                if related:
                    status = self._agent_status(agent)
                    if status == "exit":
                        continue
                    blockers.append(
                        f"Client list still contains agent '{agent_id}' related to task '{task_id}' "
                        f"(status: {status}). Wait for it to exit or remove it from the client list before relaunching."
                    )
        return blockers

    def _relaunch_status(
        self,
        *,
        task_id: str = "",
        workspace_id: str = "",
        sub_workspace: str = "",
    ) -> Dict[str, Any]:
        target = self._resolve_relaunch_target(
            task_id=task_id,
            workspace_id=workspace_id,
            sub_workspace=sub_workspace,
        )
        ws = target["workspace"]
        compile_info = ws.get("compile") or {}
        ucagent_info = self._load_relaunch_ucagent_info(ws)
        blockers = self._relaunch_blockers(target["task_id"], ws)
        if compile_info.get("status") != "success":
            blockers.append("The previous launch workspace does not contain a successful DUT compile result.")
        can_relaunch = not blockers
        return {
            "can_relaunch": can_relaunch,
            "message": "" if can_relaunch else " ".join(blockers),
            "blockers": blockers,
            "task_id": target["task_id"],
            "workspace_id": target["workspace_id"],
            "sub_workspace": sub_workspace,
            "workspace": self._workspace_public(ws),
            "compile": self._workspace_compile_public(ws),
            "ucagent_info": ucagent_info,
            "task": self._task_public(target["task"], include_logs=False) if target.get("task") else None,
        }

    def _cmd_proxy_url(self, task: Dict[str, Any], subpath: str) -> str:
        self._refresh_task_runtime_info_from_agent(task)
        cmd_api = task.get("cmd_api") or {}
        base = self._task_service_base_url(task, cmd_api)
        if not base:
            raise ValueError("CMD API base URL not available")
        return f"{base}/{subpath.lstrip('/')}" if subpath else f"{base}/"

    def _terminal_proxy_url(self, task: Dict[str, Any], subpath: str) -> str:
        self._refresh_task_runtime_info_from_agent(task)
        terminal_api = task.get("terminal_api") or {}
        base = self._task_service_base_url(task, terminal_api)
        if not base:
            raise ValueError("Terminal API base URL not available")
        return f"{base}/{subpath.lstrip('/')}" if subpath else f"{base}/"

    def _web_console_proxy_url(self, task: Dict[str, Any], subpath: str) -> str:
        self._refresh_task_runtime_info_from_agent(task)
        web_console = task.get("web_console") or {}
        base = self._task_service_base_url(task, web_console)
        if not base:
            raise ValueError("Web console base URL not available")
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
        proxy_timeout = aiohttp.ClientTimeout(total=120, connect=3, sock_connect=3, sock_read=120)

        async def _proxy_http_request(
            request: Request,
            target_url: str,
            headers: Dict[str, str],
            html_rewrites: Dict[str, str],
            failure_label: str,
        ) -> Response:
            body = await request.body()
            session = self._proxy_session
            if session is None or session.closed:
                connector = aiohttp.TCPConnector(limit=256, limit_per_host=64, ttl_dns_cache=30, keepalive_timeout=30)
                session = aiohttp.ClientSession(connector=connector, timeout=proxy_timeout)
                self._proxy_session = session
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
                        return Response(content=raw, status_code=resp.status, headers=response_headers, media_type=None)
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
            return {
                "status": "ok",
                "default_args": default_args,
                "backend_key_name": backend_key_name,
                "backend_options": backend_options,
                "launch_modes": launch_modes,
                "default_launch_mode": default_launch_mode,
                "cluster": self._launch_cluster_config(),
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
            picker_extra_args = self._effective_picker_args(body.get("picker_args", body.get("picker_extra_args", None)))

            def emit(event: Dict[str, Any]) -> bytes:
                return (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")

            def stream():
                try:
                    prepared = self._prepare_workspace_layout(
                        workspace_id,
                        effective_dut=effective_dut,
                        selected_module=selected_module,
                        main_verilog_path=main_verilog_path,
                        picker_extra_args=picker_extra_args,
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
                body.get("picker_args", body.get("picker_extra_args", None)),
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
                requested_config = str(req.get("config") or "").strip()
                if requested_config:
                    target = self._resolve_relaunch_target(
                        task_id=status["task_id"],
                        workspace_id=status["workspace_id"],
                        sub_workspace=str(req.get("sub_worspace") or req.get("sub_workspace") or ""),
                    )
                    self._switch_relaunch_ucagent_info_config(target["workspace"], requested_config)
                req["task_id"] = status["task_id"]
                req["task_name"] = status["task_id"]
                req["workspace_id"] = status["workspace_id"]
                req["dut_name"] = str(compile_info.get("dut_name") or "")
                req["selected_module"] = str(compile_info.get("selected_module") or "")
                req["main_verilog_path"] = compile_info.get("main_verilog_path") or ""
                req["picker_args"] = list(compile_info.get("picker_extra_args") or [])
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
            self._refresh_task_states()
            try:
                task = self._get_task(task_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return {"status": "ok", "task": self._task_public(task, include_logs=True)}

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
                    is_online = self._agent_is_online(agent)
                    was_online = self._online_cache.get(aid, True)
                    if was_online and not is_online:
                        if agent.get("client_exit"):
                            _master_log(
                                f"Agent '{aid}' is offline after exit "
                                f"(reason={agent.get('exit_reason') or 'exit'}, host={agent.get('host', '?')})"
                            )
                        else:
                            elapsed = int(now - agent["last_seen"])
                            _master_log(
                                f"Agent '{aid}' went offline (no heartbeat for {elapsed}s, host={agent.get('host', '?')})"
                            )
                    self._online_cache[aid] = is_online
            for aid in list(self._online_cache):
                if aid not in current_ids:
                    del self._online_cache[aid]

            self._refresh_task_states()

            if (now - self._last_launch_cleanup) >= _LAUNCH_CLEANUP_INTERVAL_SECONDS:
                self._last_launch_cleanup = now
                cleaned = self._cleanup_stale_workspaces()
                if cleaned:
                    _master_log(f"Cleaned {cleaned} stale launch workspace(s)")

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
        session = self._proxy_session
        self._proxy_session = None
        if session is not None and not session.closed:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(session.close())
                else:
                    loop.run_until_complete(session.close())
            except Exception:
                pass
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
                if self._agent_is_online(agent):
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
        self._last_capabilities: Dict[str, Any] = {}

    def _headers(self) -> Dict[str, str]:
        return {"X-Access-Key": self.access_key} if self.access_key else {}

    @staticmethod
    def _response_detail(resp: Any) -> str:
        try:
            data = resp.json()
            detail = data.get("detail") or data.get("message") or data
            return detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
        except Exception:
            return (getattr(resp, "text", "") or "").strip()[:500]

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
        meta = {}
        if agent is not None:
            try:
                workspace = getattr(agent, "workspace", "")
                if workspace:
                    saved_info = load_ucagent_info(workspace)
                    saved_meta = saved_info.get("meta") if isinstance(saved_info, dict) else {}
                    if isinstance(saved_meta, dict):
                        meta.update(_copy_jsonable(saved_meta))
            except Exception:
                pass
            agent_meta = getattr(agent, "meta", {})
            if isinstance(agent_meta, dict):
                meta.update(_copy_jsonable(agent_meta))

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
            "meta": meta,
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
        headers = self._headers()
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
                    if isinstance(data.get("capabilities"), dict):
                        self._last_capabilities = data["capabilities"]
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

    def send_exit_heartbeat(self, reason: str = "exit") -> Tuple[bool, str]:
        import requests

        self._stop_event.set()
        payload = self._build_payload()
        payload["client_exit"] = True
        payload["exited_at"] = _now()
        payload["exit_reason"] = str(reason or "exit")
        register_url = f"{self.master_url}/api/register"
        try:
            resp = requests.post(register_url, json=payload, timeout=10, headers=self._headers())
        except Exception as exc:
            self._connected = False
            return False, f"Failed to send exit heartbeat to master {self.master_url}: {exc}"
        if resp.ok:
            data = resp.json()
            if data.get("status") == "removed":
                self._kicked = True
                self._running = False
                self._connected = False
                return False, f"This agent was removed from master {self.master_url}."
            if isinstance(data.get("capabilities"), dict):
                self._last_capabilities = data["capabilities"]
            self._running = False
            self._connected = False
            return True, f"Exit heartbeat sent to master {self.master_url} as '{self.agent_id}'."
        if resp.status_code == 403:
            self._auth_failed = True
            self._running = False
            self._connected = False
            return False, f"Access key was rejected by master {self.master_url} (HTTP 403)."
        self._connected = False
        return False, f"Exit heartbeat failed for master {self.master_url}: HTTP {resp.status_code} {self._response_detail(resp)}"

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

    def workspace_sync_status(self) -> Tuple[bool, str, Dict[str, Any]]:
        if self._kicked:
            return False, f"This agent was removed from master {self.master_url}", {}
        if self._auth_failed:
            return False, f"Access key was rejected by master {self.master_url}", {}
        if not self._running:
            return False, "Not connected to master", {}
        import requests

        url = f"{self.master_url}/api/workspace-sync/status"
        try:
            resp = requests.get(
                url,
                params={"agent_id": self.agent_id},
                timeout=15,
                headers=self._headers(),
            )
        except Exception as exc:
            self._connected = False
            return False, f"Failed to query workspace sync-back status from {self.master_url}: {exc}", {}
        if resp.status_code == 403:
            self._auth_failed = True
            self._running = False
            self._connected = False
            return False, f"Access key was rejected by master {self.master_url} (HTTP 403)", {}
        if not resp.ok:
            return False, f"Master returned HTTP {resp.status_code}: {self._response_detail(resp)}", {}
        try:
            data = resp.json()
        except Exception as exc:
            return False, f"Invalid workspace sync-back status response: {exc}", {}
        self._connected = True
        status = data.get("data") or {}
        if not isinstance(status, dict):
            return False, "Invalid workspace sync-back status payload", {}
        self._last_capabilities["workspace_sync_back"] = status
        if not status.get("enabled"):
            return False, str(status.get("reason") or "Workspace sync-back is not available"), status
        return True, str(status.get("reason") or "Workspace sync-back is available"), status

    def _sync_workspace_ignore_patterns(self) -> List[str]:
        agent = getattr(self.pdb, "agent", None)
        return _workspace_sync_ignore_patterns_from_cfg(getattr(agent, "cfg", None))

    def sync_workspace_back(self, workspace_dir: str = "", reason: str = "manual") -> Tuple[bool, str]:
        ok, msg, status = self.workspace_sync_status()
        if not ok:
            return False, msg
        agent = getattr(self.pdb, "agent", None)
        workspace = os.path.abspath(workspace_dir or getattr(agent, "workspace", "") or "")
        if not workspace or not os.path.isdir(workspace):
            return False, f"Workspace directory not found: {workspace or '<empty>'}"

        import requests

        archive_stem = _safe_name(str(status.get("task_id") or self.agent_id or "workspace"), "workspace")
        temp_dir = ""
        try:
            archive_path, filename, temp_dir = create_workspace_archive(
                workspace,
                archive_stem=archive_stem,
                root_name="workspace",
                ignore_patterns=self._sync_workspace_ignore_patterns(),
            )
            url = f"{self.master_url}/api/workspace-sync/back"
            with open(archive_path, "rb") as fh:
                resp = requests.post(
                    url,
                    data={"agent_id": self.agent_id, "reason": reason},
                    files={"archive": (filename, fh, "application/gzip")},
                    timeout=(15, 600),
                    headers=self._headers(),
                )
        except Exception as exc:
            return False, f"Failed to upload workspace archive to {self.master_url}: {exc}"
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
        if resp.status_code == 403:
            self._auth_failed = True
            self._running = False
            self._connected = False
            return False, f"Access key was rejected by master {self.master_url} (HTTP 403)"
        if not resp.ok:
            return False, f"Master returned HTTP {resp.status_code}: {self._response_detail(resp)}"
        try:
            data = resp.json()
        except Exception:
            data = {}
        sync = data.get("sync") if isinstance(data, dict) else {}
        if isinstance(sync, dict) and sync.get("workspace_id"):
            return (
                True,
                f"Workspace synced back to master {self.master_url} "
                f"(task={sync.get('task_id')}, workspace={sync.get('workspace_id')})",
            )
        return True, f"Workspace synced back to master {self.master_url}"

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_kicked(self) -> bool:
        return self._kicked

    @property
    def is_auth_failed(self) -> bool:
        return self._auth_failed
