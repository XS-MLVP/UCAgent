"""Shared Master API constants and value, path, configuration, and log helpers."""

from __future__ import annotations

import collections
from datetime import datetime, timezone
import json
import os
import pathlib
import re
import shlex
import socket
import time
from typing import Any, Deque, Dict, List, Optional, Tuple
from ucagent.util.config import load_yaml_with_env_vars
from ucagent.util.functions import find_available_port, is_port_free, replace_bash_var
from ucagent.util.log import echo_g


try:
    from fastapi import Body, Depends, FastAPI, Header as _Header, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.security import HTTPBasic, HTTPBasicCredentials
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover - optional dependency checked at runtime
    Body = Depends = FastAPI = HTTPException = Query = Request = Response = WebSocket = WebSocketDisconnect = None
    _Header = HTMLResponse = JSONResponse = HTTPBasic = HTTPBasicCredentials = BaseModel = Field = None


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
# A task occupies one execution slot from these statuses until it reaches a
# terminal status; waiting tasks are queued and do not consume a slot.
_ACTIVE_TASK_STATUSES = {"pending", "starting", "running", "stopping"}
_WAITING_TASK_STATUS = "waiting"


def _task_queue_seq(task: Dict[str, Any]) -> float:
    """Effective launch-queue sequence of a waiting task record.

    Records enqueued after queue reordering support always carry ``queue_seq``;
    falling back to ``created_at`` keeps legacy hand-made records ordered by
    submission time instead of jumping the queue.
    """
    for key in ("queue_seq", "created_at"):
        try:
            value = float(task.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0.0
_MASTER_SOURCE_CONTAINER_PATH = "/UCAgent"
_K8S_JOB_STATUS_JSONPATH = "{.status.active} {.status.succeeded} {.status.failed}"
_SWARM_SERVICE_PREFIX = "ucagent-"
_SWARM_SERVICE_RETENTION_SECONDS = 3600
_SWARM_SERVICE_RUNNING_STATES = {
    "new",
    "pending",
    "assigned",
    "accepted",
    "ready",
    "preparing",
    "starting",
    "running",
}
_SWARM_SERVICE_EXITED_STATES = {
    "complete",
    "completed",
    "shutdown",
    "failed",
    "rejected",
    "orphaned",
    "remove",
    "removed",
}


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


def _parse_docker_timestamp(value: Any) -> float:
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    match = re.match(r"^(.*\.\d{6})\d+([+-]\d\d:\d\d)$", raw)
    if match:
        raw = match.group(1) + match.group(2)
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _parse_docker_relative_age(value: Any) -> float:
    text = str(value or "").strip().lower()
    if "ago" not in text:
        return -1.0
    if "less than a second ago" in text:
        return 0.0
    units = {
        "second": 1.0,
        "sec": 1.0,
        "minute": 60.0,
        "min": 60.0,
        "hour": 3600.0,
        "day": 86400.0,
        "week": 604800.0,
        "month": 2592000.0,
        "year": 31536000.0,
    }
    match = re.search(
        r"(?:about|around|over|almost)?\s*(?:an?|one|\d+)\s+"
        r"(second|sec|minute|min|hour|day|week|month|year)s?\s+ago",
        text,
    )
    if not match:
        return -1.0
    raw_amount = re.search(r"(?:about|around|over|almost)?\s*(an?|one|\d+)\s+", match.group(0))
    amount_text = raw_amount.group(1) if raw_amount else "1"
    if amount_text in {"a", "an", "one"}:
        amount = 1.0
    else:
        try:
            amount = float(amount_text)
        except ValueError:
            amount = 1.0
    return amount * units.get(match.group(1), 0.0)


def _swarm_task_id_from_service_name(name: str) -> str:
    name = str(name or "").strip()
    if name.startswith(_SWARM_SERVICE_PREFIX):
        return name[len(_SWARM_SERVICE_PREFIX):]
    return ""


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


def _yaml_mapping_node_value(mapping_node: Any, key: str) -> Any:
    if not getattr(mapping_node, "value", None):
        return None
    for key_node, value_node in mapping_node.value:
        if getattr(key_node, "value", None) == key:
            return value_node
    return None


def _config_default_env_keys(config_files: List[str]) -> set:
    keys = set()
    for config_file in config_files or []:
        if not config_file or not os.path.isfile(config_file):
            continue
        try:
            data = load_yaml_with_env_vars(config_file) or {}
        except Exception:
            continue
        configured = data.get("launch", {}).get("default_env", []) if isinstance(data, dict) else []
        if not isinstance(configured, list):
            continue
        keys.clear()
        for entry in configured:
            if isinstance(entry, str):
                key = entry.strip()
            elif isinstance(entry, dict) and len(entry) == 1:
                key = str(next(iter(entry.keys()))).strip()
            else:
                continue
            if key:
                keys.add(key)
    return keys


def _config_default_env_bool_literals(config_files: List[str]) -> Dict[str, str]:
    literals: Dict[str, str] = {}
    try:
        import yaml
    except ImportError:  # pragma: no cover - yaml is a project dependency
        return literals
    configured_keys = _config_default_env_keys(config_files)
    for config_file in config_files or []:
        if not config_file or not os.path.isfile(config_file):
            continue
        try:
            with open(config_file, "r", encoding="utf-8") as fh:
                node = yaml.compose(replace_bash_var(fh.read(), os.environ))
        except Exception:
            continue
        launch_node = _yaml_mapping_node_value(node, "launch")
        default_env_node = _yaml_mapping_node_value(launch_node, "default_env")
        if getattr(default_env_node, "id", "") != "sequence":
            continue
        for item_node in default_env_node.value:
            if getattr(item_node, "id", "") != "mapping" or len(getattr(item_node, "value", [])) != 1:
                continue
            key_node, value_node = item_node.value[0]
            key = str(getattr(key_node, "value", "") or "").strip()
            if not key:
                continue
            literals.pop(key, None)
            if getattr(value_node, "tag", "") != "tag:yaml.org,2002:bool":
                continue
            raw_value = str(getattr(value_node, "value", "") or "").strip()
            if raw_value.lower() in {"true", "false"}:
                literals[key] = raw_value
    if configured_keys:
        literals = {key: value for key, value in literals.items() if key in configured_keys}
    return literals


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


def _launch_env_reference_key(value: Any) -> str:
    match = re.match(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?$", str(value or "").strip())
    return match.group(1) if match else ""


def _resolve_launch_env_references(values: Dict[str, Any], base_env: Dict[str, Any]) -> Dict[str, str]:
    raw_values = {
        str(key): str(value)
        for key, value in (values or {}).items()
        if str(key).strip()
    }
    base_values = {str(key): str(value) for key, value in (base_env or {}).items()}
    resolved: Dict[str, str] = {}

    def resolve_key(key: str, seen: set) -> Optional[str]:
        if key in resolved:
            return resolved[key]
        if key not in raw_values:
            return base_values.get(key)
        value = raw_values[key]
        ref_key = _launch_env_reference_key(value)
        if not ref_key:
            resolved[key] = value
            return value
        if ref_key in seen:
            resolved[key] = value
            return value
        ref_value = resolve_key(ref_key, seen | {key})
        if ref_value is None:
            resolved[key] = value
            return value
        resolved[key] = ref_value
        return ref_value

    for key in raw_values:
        resolve_key(key, set())
    return resolved


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
