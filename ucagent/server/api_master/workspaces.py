"""Launch workspace records, file imports, and YAML launch specifications."""

from __future__ import annotations

import json
import os
import pathlib
import re
import secrets
import shutil
from typing import Any, Dict, List, Optional, Tuple
from ucagent.util.log import warning

from .common import (
    _CATEGORY_DIRS,
    _FILELIST_EXTS,
    _LAUNCH_STATUS_EXPIRE_SECONDS,
    _LAUNCH_STATUS_FILE,
    _LAUNCH_TMP_MARKER_FILE,
    _LAUNCH_TMP_MARKER_MAGIC,
    _LAUNCH_YAML_EXTS,
    _category_label,
    _copy_jsonable,
    _is_picker_f_file,
    _is_text_file,
    _launch_yaml_bucket,
    _now,
    _path_is_under,
    _safe_name,
    _yaml_arg_values,
    _yaml_first_scalar,
    _yaml_mapping,
    _yaml_path_values,
)


class WorkspaceMixin:
    """Launch workspace records, file imports, and YAML launch specifications."""

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
        manual_relaunch = bool(ws.get("manual_relaunch_workspace"))
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
        materialized = bool(has_tmp_marker or (manual_relaunch and root and os.path.isdir(root)))
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
        """Project the persisted compile result, including simulator identity, for API clients."""
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
            "simulator": compile_info.get("simulator", ""),
            "waveform_suffix": compile_info.get("waveform_suffix", ""),
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
            "picker_workspace": ws.get("picker_workspace", ""),
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
                if ws.get("manual_relaunch_workspace"):
                    continue
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
                    if ws.get("manual_relaunch_workspace"):
                        continue
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
        """Resolve a launch specification into imported files and canonical launch fields."""
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
            "simulator",
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

        if "simulator" in top:
            if not isinstance(top["simulator"], str):
                raise ValueError("'simulator' in launch YAML must be a single simulator name, e.g. simulator: vcs")
            fields["simulator"] = self._effective_simulator(top["simulator"])

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
