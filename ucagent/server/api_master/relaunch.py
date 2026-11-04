"""Completed task workspace discovery and relaunch validation."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
from typing import Any, Dict, List, Optional, Tuple

from .common import (
    _config_ref_name,
    _now,
    _path_is_under,
    _safe_name,
)


class RelaunchMixin:
    """Completed task workspace discovery and relaunch validation."""

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

    def _ucagent_info_path_for_root(self, workspace_root: str) -> str:
        return os.path.join(os.path.abspath(workspace_root), ".ucagent", "ucagent_info.json")

    def _is_ucagent_workspace_root(self, workspace_root: str) -> bool:
        return os.path.isfile(self._ucagent_info_path_for_root(workspace_root))

    def _read_json_dict_file(self, path: str) -> Dict[str, Any]:
        path = str(path or "").strip()
        if not path or not os.path.isfile(path) or os.path.getsize(path) == 0:
            return {}
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}

    def _read_ucagent_info_for_root(self, workspace_root: str) -> Dict[str, Any]:
        return self._read_json_dict_file(self._ucagent_info_path_for_root(workspace_root))

    def _relaunch_info_dut_name(self, info: Dict[str, Any]) -> str:
        if not isinstance(info, dict):
            return ""
        for key in ("dut_name", "DUT", "dut", "target_dut"):
            value = str(info.get(key) or "").strip()
            if value:
                return _safe_name(value, "DUT")
        meta = info.get("meta") if isinstance(info.get("meta"), dict) else {}
        for key in ("dut_name", "DUT", "dut", "target_dut"):
            value = str(meta.get(key) or "").strip()
            if value:
                return _safe_name(value, "DUT")
        return ""

    def _relaunch_identity_from_info(self, info: Dict[str, Any]) -> Dict[str, Any]:
        identity: Dict[str, Any] = {}
        if not isinstance(info, dict):
            return identity
        dut_name = self._relaunch_info_dut_name(info)
        if dut_name:
            identity["dut_name"] = dut_name
            identity["DUT"] = dut_name
        for key in ("selected_module", "task_id", "workspace_id"):
            value = str(info.get(key) or "").strip()
            if value:
                identity[key] = value
        return identity

    def _relaunch_identity_from_workspace(self, ws: Dict[str, Any], base_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        identity = self._relaunch_identity_from_info(base_info or {})
        compile_info = ws.get("compile") or {}
        dut_name = str(compile_info.get("dut_name") or "").strip()
        if dut_name and "dut_name" not in identity:
            identity["dut_name"] = _safe_name(dut_name, "DUT")
            identity["DUT"] = identity["dut_name"]
        selected_module = str(compile_info.get("selected_module") or "").strip()
        if selected_module and "selected_module" not in identity:
            identity["selected_module"] = selected_module
        for key in ("task_id", "workspace_id"):
            value = str(ws.get(key) or "").strip()
            if value and key not in identity:
                identity[key] = value
        return identity

    def _ensure_relaunch_info_identity(self, info_path: str, identity: Dict[str, Any]) -> None:
        if not info_path or not identity or not os.path.isfile(info_path) or os.path.getsize(info_path) == 0:
            return
        try:
            data = self._read_json_dict_file(info_path)
        except Exception:
            return
        changed = False
        dut_name = str(identity.get("dut_name") or identity.get("DUT") or "").strip()
        if dut_name:
            if not self._relaunch_info_dut_name(data):
                data["dut_name"] = dut_name
                data["DUT"] = dut_name
                changed = True
            elif not str(data.get("DUT") or "").strip():
                data["DUT"] = self._relaunch_info_dut_name(data)
                changed = True
            elif not str(data.get("dut_name") or "").strip():
                data["dut_name"] = self._relaunch_info_dut_name(data)
                changed = True
        for key in ("selected_module", "task_id", "workspace_id"):
            value = str(identity.get(key) or "").strip()
            if value and not str(data.get(key) or "").strip():
                data[key] = value
                changed = True
        if changed:
            self._write_json_atomic(info_path, data)

    def _load_relaunch_ucagent_info(self, ws: Dict[str, Any]) -> Dict[str, Any]:
        info_path = self._relaunch_ucagent_info_path(ws)
        data: Dict[str, Any] = {}
        load_error = ""
        exists = bool(info_path and os.path.isfile(info_path))
        if exists:
            try:
                data = self._read_json_dict_file(info_path)
            except Exception as exc:
                load_error = str(exc)
        config_file = str(data.get("config_file") or data.get("config_arg") or "").strip()
        dut_name = self._relaunch_info_dut_name(data)
        return {
            "exists": exists,
            "path": info_path,
            "config_file": config_file,
            "config_arg": config_file,
            "dut_name": dut_name,
            "DUT": dut_name,
            "selected_module": str(data.get("selected_module") or "").strip(),
            "task_id": str(data.get("task_id") or "").strip(),
            "workspace_id": str(data.get("workspace_id") or "").strip(),
            "stage_index": data.get("stage_index"),
            "all_completed": data.get("all_completed"),
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
        current_data: Dict[str, Any] = {}
        if os.path.isfile(info_path) and os.path.getsize(info_path) > 0:
            try:
                current_data = self._read_json_dict_file(info_path)
            except Exception:
                current_data = {}
        identity = self._relaunch_identity_from_workspace(ws, current_data)
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
                initialized_info = {
                    "config_file": target_config,
                    "config_arg": target_config,
                    **identity,
                }
                self._write_json_atomic(info_path, initialized_info)
                initialized = True
                cleared = True
            else:
                self._write_empty_file_atomic(info_path)
                cleared = True
        if target_config:
            self._ensure_relaunch_info_identity(info_path, identity)

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

    def _workspace_id_for_relaunch_path(self, workspace_root: str, info: Optional[Dict[str, Any]] = None) -> str:
        root_abs = os.path.abspath(workspace_root)
        base_name = os.path.basename(root_abs)
        if base_name == "workspace":
            base_name = os.path.basename(os.path.dirname(root_abs))
        base = _safe_name(base_name, "")
        if base:
            return base
        digest = hashlib.sha256(os.path.realpath(root_abs).encode("utf-8")).hexdigest()[:16]
        return f"relaunch_{digest}"

    def _validate_relaunch_info_identity(self, workspace_root: str, info: Dict[str, Any], expected_id: str) -> None:
        mismatches = []
        info_path = self._ucagent_info_path_for_root(workspace_root)
        for key in ("workspace_id", "task_id"):
            raw = str((info or {}).get(key) or "").strip()
            if not raw:
                continue
            actual = _safe_name(raw, "")
            if actual and actual != expected_id:
                mismatches.append(f"{key}={raw!r}")
        if mismatches:
            raise ValueError(
                f"Relaunch workspace identity mismatch: {info_path} records "
                f"{', '.join(mismatches)}, but the workspace directory resolves to '{expected_id}'. "
                "Update .ucagent/ucagent_info.json to match the workspace directory before relaunching."
            )

    def _register_relaunch_workspace_from_path(self, workspace_root: str) -> Optional[Dict[str, Any]]:
        workspace_root = os.path.abspath(os.path.expanduser(str(workspace_root or "").strip()))
        base_root = os.path.abspath(self.workspace)
        if not workspace_root or not _path_is_under(base_root, workspace_root):
            return None
        if not self._is_ucagent_workspace_root(workspace_root):
            return None
        try:
            info = self._read_ucagent_info_for_root(workspace_root)
        except Exception:
            info = {}
        workspace_id = self._workspace_id_for_relaunch_path(workspace_root, info)
        self._validate_relaunch_info_identity(workspace_root, info, workspace_id)
        task_id = workspace_id
        picker_workspace = workspace_root
        launch_workspace_dir = os.path.dirname(workspace_root) if os.path.basename(workspace_root) == "workspace" else workspace_root
        now = _now()
        with self._workspaces_lock:
            existing = self._workspaces.get(workspace_id)
            target_picker_real = os.path.realpath(os.path.abspath(picker_workspace))
            target_launch_real = os.path.realpath(os.path.abspath(launch_workspace_dir))
            if existing is not None and not existing.get("manual_relaunch_workspace"):
                existing_picker = os.path.realpath(os.path.abspath(str(existing.get("picker_workspace") or ""))) if existing.get("picker_workspace") else ""
                existing_dir = os.path.realpath(os.path.abspath(str(existing.get("workspace_dir") or ""))) if existing.get("workspace_dir") else ""
                same_target = target_picker_real in {existing_picker, existing_dir} or target_launch_real in {existing_picker, existing_dir}
                if not same_target:
                    digest = hashlib.sha256(target_picker_real.encode("utf-8")).hexdigest()[:8]
                    workspace_id = _safe_name(f"{workspace_id}_{digest}", f"relaunch_{digest}")
                    task_id = workspace_id
                    existing = self._workspaces.get(workspace_id)
            if existing is None:
                ws = {
                    "workspace_id": workspace_id,
                    "workspace_dir": launch_workspace_dir,
                    "picker_workspace": picker_workspace,
                    "base_root": base_root,
                    "created_at": now,
                    "last_seen": now,
                    "materialized": True,
                    "materialized_at": now,
                    "launch_status": "launched",
                    "files": [],
                    "task_id": task_id,
                    "compile": {},
                    "manual_relaunch_workspace": True,
                }
                self._workspaces[workspace_id] = ws
                self._normalize_workspace_locked(ws)
                self._mark_dirty()
                return dict(ws)
            self._normalize_workspace_locked(existing)
            changed = False
            for key, value in (
                ("workspace_dir", launch_workspace_dir),
                ("picker_workspace", picker_workspace),
                ("base_root", base_root),
                ("task_id", task_id),
            ):
                if value and existing.get(key) != value:
                    existing[key] = value
                    changed = True
            existing["manual_relaunch_workspace"] = True
            existing["materialized"] = True
            existing["launch_status"] = "launched"
            existing["last_seen"] = now
            if changed:
                self._mark_dirty()
            return dict(existing)

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
            registered = self._register_relaunch_workspace_from_path(candidate_abs)
            if registered is None and os.path.basename(candidate_abs) != "workspace":
                registered = self._register_relaunch_workspace_from_path(os.path.join(candidate_abs, "workspace"))
            if registered is not None:
                matched = registered
            first_part = sub_workspace.split("/", 1)[0] if sub_workspace else ""
            if matched is None and first_part:
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
            if candidate_abs and matched.get("manual_relaunch_workspace"):
                task_id = resolved_task_id
            else:
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
                if not self._task_is_finished(existing_task):
                    blockers.append(
                        f"Task list still contains running task '{task_id}' (status: {status}). "
                        "Wait for it to exit or stop it before relaunching."
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
        info_dut_name = str(ucagent_info.get("dut_name") or ucagent_info.get("DUT") or "").strip()
        compile_ready = compile_info.get("status") == "success"
        info_ready = bool(ucagent_info.get("exists") and info_dut_name)
        if not compile_ready and not info_ready:
            blockers.append(
                "The relaunch workspace has no successful DUT compile result and .ucagent/ucagent_info.json does not record DUT."
            )
        can_relaunch = not blockers
        return {
            "can_relaunch": can_relaunch,
            "message": "" if can_relaunch else " ".join(blockers),
            "blockers": blockers,
            "task_id": target["task_id"],
            "workspace_id": target["workspace_id"],
            "sub_workspace": sub_workspace,
            "workspace_source": "compile" if compile_ready else ("ucagent_info" if info_ready else ""),
            "workspace": self._workspace_public(ws),
            "compile": self._workspace_compile_public(ws),
            "ucagent_info": ucagent_info,
            "task": self._task_public(target["task"], include_logs=False) if target.get("task") else None,
        }

    def _drop_finished_task_record_for_relaunch(self, task_id: str) -> None:
        task_id = str(task_id or "").strip()
        if not task_id:
            return
        task_snapshot: Optional[Dict[str, Any]] = None
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            if not self._task_is_finished(task):
                raise ValueError(f"Task '{task_id}' is still running and cannot be relaunched")
            task_snapshot = dict(task)
            self._tasks.pop(task_id, None)
        self._remember_task_launch_agent(task_snapshot)
        self._close_task_runtime(task_id)
        self._mark_dirty()
