"""Master server lifecycle, persistence, task queue, and task coordination."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import pathlib
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import uuid
from typing import Any, Dict, List, Optional, Tuple
from ucagent.util.config import get_config
from ucagent.util.functions import find_available_port, get_abs_path_cwd_ucagent
from ucagent.util.log import warning
from ucagent.util.workspace_archive import create_workspace_archive, extract_workspace_root_archive

from .common import (
    HTTPException,
    BUG_REVIEW_RUN_SYNC_IGNORES,
    _is_bug_review_run_dir,
    _ACTIVE_TASK_STATUSES,
    _CONTAINER_LAUNCH_MODES,
    _K8S_JOB_STATUS_JSONPATH,
    _LAUNCH_CLEANUP_INTERVAL_SECONDS,
    _WAITING_TASK_STATUS,
    _as_bool,
    _config_default_env_bool_literals,
    _default_launch_root,
    _is_picker_f_file,
    _is_pid_alive,
    _mask_secret,
    _master_log,
    _merge_launch_default_args,
    _merge_runtime_service_info,
    _normalize_launch_mode,
    _now,
    _parse_service_spec,
    _parse_web_terminal_spec,
    _plain_config_value,
    _resolve_launch_env_references,
    _resolve_web_console_spec,
    _safe_name,
    _split_master_spec,
    _task_logs_for_display,
    _task_queue_seq,
    _workspace_sync_ignore_patterns_from_cfg,
)

from .workspaces import WorkspaceMixin
from .compilation import CompilationMixin
from .launch_runtime import LaunchRuntimeMixin
from .relaunch import RelaunchMixin
from .routes import RoutesMixin


class PdbMasterApiServer(
    WorkspaceMixin, CompilationMixin, LaunchRuntimeMixin, RelaunchMixin, RoutesMixin,
):
    """FastAPI-based master that aggregates agents and manages launched tasks."""

    PERIODIC_SAVE_INTERVAL: float = 20.0

    MONITOR_INTERVAL: float = 1.0

    CHILD_READY_TIMEOUT: float = 30.0

    _TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")

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
        """Validate Master configuration and initialize persistent records, runtimes, and routes."""
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
        self._simulator_priority()

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
        # Serializes saturation checks with task starts so concurrent launches
        # cannot each grab the last free execution slot. Reentrant because
        # waiting-task dispatch re-enters the launch path while holding it.
        self._launch_lock = threading.RLock()
        # Monotonic sequence for the waiting launch queue. Anchored at process
        # start time so persisted waiting records from an earlier run keep their
        # relative order ahead of everything enqueued by this run.
        self._waiting_seq = _now()

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
                # Heartbeats refresh proxy credentials; keep them out of snapshots.
                agents_snapshot = {
                    k: {field: value for field, value in v.items() if field != "cmd_api_password"}
                    for k, v in self._agents.items()
                }
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

    def _relaunch_workspace_dir(self, ws: Dict[str, Any]) -> str:
        for value in (
            ws.get("picker_workspace"),
            os.path.join(str(ws.get("workspace_dir") or ""), "workspace"),
            ws.get("workspace_dir"),
        ):
            raw = str(value or "").strip()
            if not raw:
                continue
            workspace_root = os.path.abspath(raw)
            if workspace_root and os.path.isdir(workspace_root) and self._is_ucagent_workspace_root(workspace_root):
                return workspace_root
        raise ValueError("Relaunch workspace is missing .ucagent/ucagent_info.json")

    def _launchable_workspace_dir(self, ws: Dict[str, Any]) -> str:
        compile_info = ws.get("compile") or {}
        if compile_info.get("status") != "success":
            return self._relaunch_workspace_dir(ws)
        return self._compiled_workspace_dir(ws)

    def _create_compiled_workspace_archive(self, ws: Dict[str, Any], archive_stem: str = "") -> Tuple[str, str, str]:
        picker_workspace = self._launchable_workspace_dir(ws)
        archive_stem = _safe_name(
            archive_stem or os.path.basename(os.path.abspath(ws.get("workspace_dir", ""))),
            "workspace",
        )
        if _is_bug_review_run_dir(picker_workspace):
            ignore_patterns: List[str] = list(BUG_REVIEW_RUN_SYNC_IGNORES)
        else:
            ignore_patterns = _workspace_sync_ignore_patterns_from_cfg(self.cfg)
        return create_workspace_archive(
            picker_workspace,
            archive_stem=archive_stem,
            root_name="workspace",
            ignore_patterns=ignore_patterns,
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

    def _publish_bug_review_after_sync(self, task: Dict[str, Any], target_dir: str, reason: str) -> str:
        """Publish the canonical Bug Review run after a publishing sync event."""
        if str(reason or "").strip() not in {"stage_complete:publish", "exit"}:
            return ""
        structured = task.get("cli_args_structured") or {}
        if not str(structured.get("plugin_workflow") or "").startswith("bug_review:"):
            return ""
        from bug_review.publishing import publish_run

        run_dir = pathlib.Path(target_dir)
        return str(publish_run(run_dir, run_dir.parent))

    def _sync_workspace_archive_back(self, agent_id: str, archive_path: str, archive_size: int = 0,
                                     reason: str = "") -> Dict[str, Any]:
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
        published_index = self._publish_bug_review_after_sync(task, target_dir, reason)
        if published_index:
            sync_info["published_index"] = published_index
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
        """Build the child Agent CLI command and resolve its environment from launch settings."""
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
            if isinstance(values, str):
                values = [values]
            for value in values or []:
                add_value(flag, value)

        add_value("--config", req.get("config"))
        plugins = req.get("plugin") or []
        if isinstance(plugins, str):
            plugins = [plugins]
        for plugin in plugins:
            plugin = str(plugin).strip()
            if plugin and not os.path.isabs(plugin) and launch_mode == "process":
                # Agent processes run inside their own workspace directory, so a
                # repo-relative plugin selector must be anchored at the Master's
                # source tree before the child resolves it. Container launch
                # modes keep the configured value because the layout inside the
                # container image differs.
                repo_root = os.path.dirname(os.path.dirname(cli_path))
                for base in (os.getcwd(), repo_root):
                    candidate = os.path.join(base, plugin)
                    if os.path.isdir(candidate):
                        plugin = candidate
                        break
            add_value("--plugin", plugin)
        add_value("--plugin-workflow", req.get("plugin_workflow"))
        add_value("--workspace-base", req.get("workspace_base"))
        add_value("--template-dir", req.get("template_dir"))
        add_flag("--template-overwrite", req.get("template_overwrite"))
        add_list("--template-cfg-override", req.get("template_cfg_override", []))
        default_output = ("results"
                          if str(req.get("plugin_workflow") or "").startswith("bug_review:")
                          else "unity_test")
        add_value("--output", req.get("output") or default_output)

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
        if req.get("use_skill") is True:
            argv.append("--use-skill")
        elif req.get("use_skill") is False:
            argv.append("--no-use-skill")
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
        env_updates.update(_resolve_launch_env_references(req.get("env") or {}, {**env, **env_updates}))
        env.update({str(k): str(v) for k, v in env_updates.items()})
        if self.access_key:
            env["UCAGENT_WORKSPACE_ARCHIVE_KEY"] = self.access_key
        if self.password:
            env["UCAGENT_WORKSPACE_ARCHIVE_PASSWORD"] = self.password
        return argv, env

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
            if not resp.ok:
                return False
            if task and svc is task.get("cmd_api"):
                expected = task.get("client_id")
                identity = resp.json().get("identity", {})
                return bool(expected and expected in identity.get("agent_ids", []))
            return True
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
        if task_client_id:
            return next((agent for agent in agents if agent.get("id") == task_client_id), None)
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
                if str(task.get("process_status") or "") == _WAITING_TASK_STATUS:
                    # Waiting tasks have no process, agent, or services to probe;
                    # the dispatch loop starts them when a slot frees up.
                    continue
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
        """Validate a launch request and start it, or queue it when the master is saturated.

        A task occupies one execution slot from creation until it finishes. When
        active tasks already fill ``master_api.max_task_count`` slots, or earlier
        submissions are still waiting, the validated request is stored as a
        ``waiting`` task and started automatically in submission order once a
        slot frees up.
        """
        with self._launch_lock:
            req = self._normalized_launch_request(req)
            ws, prepared, compile_info, picker_status = self._validated_launch_context(req)
            if picker_status == "success" and (
                self._waiting_tasks() or self._active_task_count() >= self._max_task_count()
            ):
                return self._enqueue_waiting_task(req, ws, prepared)
            return self._launch_validated_task(req, ws, prepared, compile_info, picker_status)

    def _normalized_launch_request(self, req: Dict[str, Any]) -> Dict[str, Any]:
        """Merge launch defaults and validate explicit settings without probing compilation tools."""
        req = dict(req)
        default_args = self.cfg.get_value("launch.default_args", {}) or {}
        if hasattr(default_args, "as_dict"):
            default_args = default_args.as_dict()
        if isinstance(default_args, dict):
            # A configured priority list must never become a task's selected simulator.
            default_args = {key: value for key, value in default_args.items() if key != "simulator"}
            req = _merge_launch_default_args(req, default_args)
        if req.get("simulator") is not None:
            req["simulator"] = self._effective_simulator(req["simulator"])
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
        return req

    def _validated_launch_context(
        self, req: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], str]:
        """Validate a launch request against the current workspace state.

        Pin an omitted simulator to the successful compile record before queueing.
        Returns ``(workspace, prepared, compile_info, picker_status)``. Raises
        ``ValueError`` when the request has no usable compiled workspace.
        """
        workspace_id = req.get("workspace_id", "")
        if not workspace_id:
            raise ValueError("'workspace_id' is required for launch")
        ws = self._get_workspace(workspace_id)

        selected_module = (req.get("selected_module") or "").strip()
        if not selected_module:
            raise ValueError("'selected_module' is required")
        effective_dut = (req.get("dut_name") or "").strip() or selected_module
        compile_info = dict((ws.get("compile") or {}))
        compiled_simulator = compile_info.get("simulator")
        requested_simulator = req.get("simulator")
        if requested_simulator is None:
            requested_simulator = compiled_simulator
        allow_ucagent_info_relaunch = bool(req.get("_relaunch_from_ucagent_info")) and compile_info.get("status") != "success"
        ucagent_info: Dict[str, Any] = {}
        info_dut_name = ""
        if allow_ucagent_info_relaunch:
            try:
                info_path = self._relaunch_ucagent_info_path(ws)
                ucagent_info = self._read_json_dict_file(info_path) if info_path else {}
                info_dut_name = self._relaunch_info_dut_name(ucagent_info)
            except Exception:
                ucagent_info = {}
                info_dut_name = ""
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
        # An omitted picker selection reuses the compiled package settings.
        if not requested_picker_args:
            requested_picker_args = list(compile_info.get("picker_extra_args") or [])
        requested_main_verilog = os.path.abspath(str(req.get("main_verilog_path") or ""))
        main_verilog_matches = (
            not req.get("main_verilog_path")
            or os.path.abspath(str(compile_info.get("main_verilog_path") or "")) == requested_main_verilog
        )
        compile_matches = (
            compile_info.get("status") == "success"
            and compile_info.get("dut_name") == _safe_name(effective_dut, "DUT")
            and compile_info.get("selected_module") == selected_module
            and isinstance(compiled_simulator, str)
            and compiled_simulator == self._effective_simulator(requested_simulator)
            and compiled_f_filelists == current_f_filelists
            and list(compile_info.get("picker_extra_args") or []) == requested_picker_args
            and main_verilog_matches
        )
        info_relaunch_matches = bool(
            allow_ucagent_info_relaunch
            and info_dut_name
            and info_dut_name == _safe_name(effective_dut, "DUT")
        )
        if not compile_matches and not info_relaunch_matches:
            mismatches = []
            if compile_info.get("status") != "success":
                mismatches.append(f"compile status is '{compile_info.get('status') or 'none'}' (not success)")
            if compile_info.get("dut_name") != _safe_name(effective_dut, "DUT"):
                mismatches.append(
                    f"DUT is '{compile_info.get('dut_name') or 'none'}' but launch wants '{_safe_name(effective_dut, 'DUT')}'"
                )
            if compile_info.get("selected_module") != selected_module:
                mismatches.append(
                    f"module is '{compile_info.get('selected_module') or 'none'}' but launch wants '{selected_module}'"
                )
            if not isinstance(compiled_simulator, str) or compiled_simulator != self._effective_simulator(requested_simulator):
                mismatches.append(
                    f"compile used simulator '{compiled_simulator or 'none'}' "
                    f"but launch requests '{self._effective_simulator(requested_simulator)}'"
                )
            if compiled_f_filelists != current_f_filelists:
                mismatches.append("the imported .f filelists changed since the compile")
            if list(compile_info.get("picker_extra_args") or []) != requested_picker_args:
                mismatches.append(
                    f"compile used picker args {compile_info.get('picker_extra_args') or []} "
                    f"but launch requests {requested_picker_args}"
                )
            if not main_verilog_matches:
                mismatches.append(
                    f"compile used Main RTL '{compile_info.get('main_verilog_path') or 'none'}' "
                    f"but launch requests '{req.get('main_verilog_path')}'"
                )
            raise ValueError(
                f"Workspace '{workspace_id}' has no successful compile matching the launch request; recompile first. "
                + "; ".join(mismatches)
            )

        if compile_matches:
            # Keep the package's simulator in both immediate and persisted waiting requests.
            req["simulator"] = compiled_simulator
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
            picker_status = compile_info.get("status", "not_started")
        else:
            picker_workspace = os.path.abspath(
                str(ws.get("picker_workspace") or self._compiled_workspace_match_path(ws) or ws["workspace_dir"])
            )
            if not os.path.isdir(picker_workspace):
                raise ValueError(f"Relaunch workspace directory not found: {picker_workspace}")
            if not self._is_ucagent_workspace_root(picker_workspace):
                raise ValueError(f"Relaunch workspace is missing .ucagent/ucagent_info.json: {picker_workspace}")
            doc_dir = os.path.join(picker_workspace, f"{info_dut_name}_Doc")
            dut_dir = os.path.join(picker_workspace, info_dut_name)
            if not os.path.isdir(doc_dir):
                doc_dir = ""
            prepared = {
                "workspace_dir": os.path.abspath(str(ws["workspace_dir"])),
                "picker_workspace": picker_workspace,
                "dut_name": info_dut_name,
                "rtl_dir": os.path.join(picker_workspace, f"{info_dut_name}_RTL"),
                "doc_dir": doc_dir,
                "dut_dir": dut_dir if os.path.isdir(dut_dir) else "",
                "main_verilog_path": "",
                "filelist_path": "",
                "source_f_filelist_paths": [],
                "f_filelist_paths": [],
                "generated_filelist": False,
                "copied_files": [],
                "config_path": "",
                "use_zip_workspace": bool(req.get("use_zip_workspace", True)),
            }
            picker_status = "success"

        compiled_config = str(compile_info.get("config_path") or "").strip()
        current_config = str(req.get("config") or "").strip()
        if compiled_config and (not current_config or current_config == os.path.basename(compiled_config)):
            req["config"] = compiled_config

        return ws, prepared, compile_info, picker_status

    def _max_task_count(self) -> int:
        """Maximum number of tasks the master executes in parallel."""
        raw = self.cfg.get_value("master_api.max_task_count", 100)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return 100
        return value if value > 0 else 100

    def _active_task_count(self) -> int:
        """Number of tasks currently occupying an execution slot."""
        with self._tasks_lock:
            return sum(
                1
                for task in self._tasks.values()
                if str(task.get("process_status") or "") in _ACTIVE_TASK_STATUSES
            )

    def _waiting_tasks(self) -> List[Dict[str, Any]]:
        """Waiting tasks ordered by their launch-queue sequence."""
        with self._tasks_lock:
            waiting = [
                task
                for task in self._tasks.values()
                if str(task.get("process_status") or "") == _WAITING_TASK_STATUS
            ]
        waiting.sort(key=lambda task: (_task_queue_seq(task), str(task.get("task_id") or "")))
        return waiting

    def _reorder_waiting_tasks(self, task_ids: List[Any]) -> List[str]:
        """Reassign the waiting launch-queue order to match ``task_ids``.

        ``task_ids`` must list every currently waiting task exactly once, in
        the desired start order. Returns the ordered task ids. New submissions
        always land after the reordered block.
        """
        normalized = [str(item or "").strip() for item in (task_ids or [])]
        if not normalized:
            raise ValueError("'task_ids' must list every waiting task in the desired start order")
        if len(set(normalized)) != len(normalized):
            raise ValueError("'task_ids' contains duplicate task ids")
        # Held together with the launch lock so a reorder can never interleave
        # with a dispatch decision or a concurrent enqueue.
        with self._launch_lock:
            with self._tasks_lock:
                waiting_by_id = {
                    str(task.get("task_id") or ""): task
                    for task in self._tasks.values()
                    if str(task.get("process_status") or "") == _WAITING_TASK_STATUS
                }
                unknown = [task_id for task_id in normalized if task_id not in waiting_by_id]
                if unknown:
                    raise ValueError(f"Task(s) not in the waiting queue: {', '.join(unknown)}")
                missing = [task_id for task_id in waiting_by_id if task_id not in set(normalized)]
                if missing:
                    raise ValueError(f"'task_ids' is missing waiting task(s): {', '.join(missing)}")
                base = self._waiting_seq
                for index, task_id in enumerate(normalized):
                    waiting_by_id[task_id]["queue_seq"] = base + index
                self._waiting_seq = base + len(normalized)
            self._mark_dirty()
        return normalized

    def _waiting_queue_positions(self) -> Dict[str, int]:
        """Map each waiting task id to its 1-based position in the launch queue."""
        return {
            str(task.get("task_id") or ""): position
            for position, task in enumerate(self._waiting_tasks(), start=1)
        }

    def _enqueue_waiting_task(
        self, req: Dict[str, Any], ws: Dict[str, Any], prepared: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Store a validated launch request as a waiting task record."""
        workspace_id = str(ws.get("workspace_id") or "")
        task = self._create_task_record({
            "task_id": str(ws.get("task_id") or workspace_id).strip(),
            "task_name": req.get("task_name") or (req.get("selected_module") or "").strip(),
            "client_id": req.get("client_id", ""),
            "workspace_id": workspace_id,
            "launch_mode": _normalize_launch_mode(req.get("launch_mode", "process")),
            "workspace_dir": prepared["workspace_dir"],
            "dut_name": prepared["dut_name"],
            "selected_module": (req.get("selected_module") or "").strip(),
            "main_verilog_path": prepared.get("main_verilog_path", ""),
            "env": req.get("env") or {},
            "cli_args_structured": req,
            "cli_args_extra": req.get("extra_args", []),
            "cmd_api": {"enabled": False, "status": _WAITING_TASK_STATUS},
            "terminal_api": {"enabled": False, "status": _WAITING_TASK_STATUS},
            "web_console": {"enabled": False, "status": _WAITING_TASK_STATUS},
        })
        task["process_status"] = _WAITING_TASK_STATUS
        task["queued_at"] = _now()
        task["queue_seq"] = self._waiting_seq
        self._waiting_seq += 1
        task["waiting_request"] = dict(req)
        self._append_task_log(
            task["stderr_log_path"],
            f"Task queued at position {len(self._waiting_tasks())}: "
            f"{self._active_task_count()}/{self._max_task_count()} task slot(s) in use. "
            "It starts automatically in submission order when a slot frees up.",
        )
        self._mark_dirty()
        return task

    def _dispatch_waiting_tasks(self) -> None:
        """Start waiting tasks in submission order while execution slots are free."""
        while True:
            with self._launch_lock:
                waiting = self._waiting_tasks()
                if not waiting or self._active_task_count() >= self._max_task_count():
                    return
                first = waiting[0]
                task_id = str(first.get("task_id") or "")
                req = dict(first.get("waiting_request") or {})
                with self._tasks_lock:
                    current = self._tasks.get(task_id)
                    if current is None or current.get("process_status") != _WAITING_TASK_STATUS:
                        continue
                    del self._tasks[task_id]
                self._mark_dirty()
                if not req:
                    self._record_dispatch_failure(
                        task_id, {}, ValueError("Waiting task record has no launch request")
                    )
                    continue
                try:
                    # Bypass the saturation check: this slot was reserved by the
                    # check above while holding the launch lock.
                    dispatched = self._normalized_launch_request(req)
                    ws, prepared, compile_info, picker_status = self._validated_launch_context(dispatched)
                    self._launch_validated_task(dispatched, ws, prepared, compile_info, picker_status)
                except Exception as exc:
                    self._record_dispatch_failure(task_id, req, exc)

    def _record_dispatch_failure(self, task_id: str, req: Dict[str, Any], exc: Exception) -> None:
        """Keep a failed task record when a dequeued waiting task cannot start."""
        with self._tasks_lock:
            already_recorded = task_id in self._tasks
        if already_recorded:
            return
        task = self._create_task_record({
            "task_id": task_id,
            "task_name": req.get("task_name") or (req.get("selected_module") or "").strip() or task_id,
            "client_id": req.get("client_id", ""),
            "workspace_id": req.get("workspace_id", ""),
            "launch_mode": _normalize_launch_mode(req.get("launch_mode", "process")),
            "cli_args_structured": req,
            "cli_args_extra": req.get("extra_args", []),
            "cmd_api": {"enabled": False, "status": "stopped"},
            "terminal_api": {"enabled": False, "status": "stopped"},
            "web_console": {"enabled": False, "status": "stopped"},
        })
        task["process_status"] = "failed"
        task["finished_at"] = _now()
        self._append_task_log(task["stderr_log_path"], f"Waiting task launch failed: {exc}")
        self._mark_dirty()
        _master_log(f"Waiting task '{task_id}' failed to start: {exc}")

    def _purge_waiting_task_workspace(self, task: Dict[str, Any]) -> str:
        """Remove a cancelled waiting task's workspace record and directory.

        Returns the removed directory path, or an empty string when the
        directory was kept because it failed the launch-workspace safety
        checks (for example a manually registered relaunch workspace).
        """
        workspace_id = str(task.get("workspace_id") or "").strip()
        ws_snapshot: Dict[str, Any] = {}
        if workspace_id:
            with self._workspaces_lock:
                ws_snapshot = dict(self._workspaces.get(workspace_id) or {})
                self._workspaces.pop(workspace_id, None)
            with self._compile_runtime_lock:
                self._compile_runtime.pop(workspace_id, None)
        ws_dir = str(ws_snapshot.get("workspace_dir") or task.get("workspace_dir") or "")
        if not ws_dir or not self._launch_tmp_marker_matches(workspace_id, ws_dir):
            if ws_dir:
                _master_log(
                    f"Kept cancelled waiting task directory '{ws_dir}' (launch workspace safety check failed)"
                )
            self._mark_dirty()
            return ""
        self._remove_path(ws_dir)
        self._mark_dirty()
        return ws_dir

    def _launch_validated_task(
        self,
        req: Dict[str, Any],
        ws: Dict[str, Any],
        prepared: Dict[str, Any],
        compile_info: Dict[str, Any],
        picker_status: str,
    ) -> Dict[str, Any]:
        """Start an already validated launch request as a managed task.

        Allocates the child service ports, creates the task record, starts the
        process/container, and marks the workspace as launched.
        """
        launch_mode = _normalize_launch_mode(req.get("launch_mode", "process"))
        workspace_id = str(req.get("workspace_id") or "")
        selected_module = (req.get("selected_module") or "").strip()
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
        task["picker_status"] = picker_status
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
        if launch_mode == "docker_swarm":
            cleaned = self._cleanup_stale_swarm_services()
            if cleaned:
                _master_log(f"Cleaned {cleaned} stale Docker Swarm service(s)")
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
                self._remove_docker_swarm_service(name, task, reason="task stop requested")
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
        # The stored launch request is internal dispatch state and may carry
        # environment values; never expose it through the API.
        data.pop("waiting_request", None)
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
        loaded_config_files = getattr(self.cfg, "__dict__", {}).get("_loaded_config_files", [])
        bool_literals = _config_default_env_bool_literals(loaded_config_files)
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
                "raw_literal": bool_literals.get(key, ""),
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
            self._dispatch_waiting_tasks()

            if (now - self._last_launch_cleanup) >= _LAUNCH_CLEANUP_INTERVAL_SECONDS:
                self._last_launch_cleanup = now
                cleaned = self._cleanup_stale_workspaces()
                if cleaned:
                    _master_log(f"Cleaned {cleaned} stale launch workspace(s)")

            if self._dirty and (now - self._last_saved) >= self.PERIODIC_SAVE_INTERVAL:
                self._save_db()

    def start(self) -> Tuple[bool, str]:
        if self._running:
            return False, f"Master API server is already running at {self.url()}"

        import uvicorn

        started: List[str] = []
        errors: List[str] = []
        if self.tcp:
            try:
                cfg = uvicorn.Config(self._app, host=self.host, port=self.port,
                                     log_config=None, log_level=None, ws="websockets-sansio")
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
                    cfg = uvicorn.Config(self._app, uds=self.sock, log_config=None, log_level=None,
                                         ws="websockets-sansio")
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
