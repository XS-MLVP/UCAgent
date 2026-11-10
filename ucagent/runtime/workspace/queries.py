"""Read saved stage/workspace data without constructing Agents or running Checkers."""

import collections
import copy
import os
import time
from typing import Optional, Tuple

from ucagent.core.stage.history import StageHistory
from ucagent.core.workspace.files import WorkspaceAccessError, WorkspaceFiles
from ucagent.runtime.workspace.access import info_path, load_info
from ucagent.util.functions import fmt_time_deta, fmt_time_stamp


def mission_name(workspace_root: str, info: dict) -> str:
    """Read the saved mission display name or use the workspace directory name."""
    for key in ("mission_name", "mission", "misson_name"):
        value = info.get(key)
        if isinstance(value, dict):
            value = value.get("name")
        if value:
            return str(value)
    return os.path.basename(os.path.normpath(workspace_root)) or "Sub Workspace"


def workspace_lifecycle(info: dict) -> str:
    """Project the last saved lifecycle without claiming current process liveness."""
    all_completed = bool(info.get("all_completed", False))
    is_exit = bool(info.get("is_agent_exit", False))
    if all_completed:
        return "completed"
    if is_exit:
        return "exited"
    if bool(info.get("is_wait_human_check", False)) and not all_completed:
        return "waiting"
    return "running"


def saved_stage_items(info: dict) -> list[Tuple[int, dict]]:
    """Read indexed stages in deterministic numeric order."""
    stages_info = info.get("stages_info", {})
    if not isinstance(stages_info, dict):
        return []

    def _stage_key(item) -> int:
        """Sort persisted stage indices numerically."""
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


def format_stage_time_cost(value) -> str:
    """Format a saved duration while preserving unavailable values."""
    if value in (None, "", 0, 0.0):
        return ""
    try:
        return fmt_time_deta(value)
    except Exception:
        return str(value)


def format_timestamp(value) -> str:
    """Format a saved timestamp for workspace inspection."""
    if value in (None, ""):
        return ""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(value)))
    except Exception:
        return str(value)


def safe_int(value, default: int = 0) -> int:
    """Read optional numeric snapshot metadata with an explicit default."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class WorkspaceQueries:
    """Project persisted workspace snapshots and stage history through shared rules."""

    def __init__(self, access):
        """Bind explicit workspace selection without attaching runtime or Agent owners."""
        self.access = access

    def status(self, workspace_root: str, info: dict) -> str:
        """Read saved runtime statistics without querying a live Agent."""
        stage_items = saved_stage_items(info)
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

    def task_list(self, workspace_root: str, info: dict) -> dict:
        """Project saved stages into the task-list response contract."""
        stage_items = saved_stage_items(info)
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
                "time_cost": format_stage_time_cost(detail.get("time_cost")),
                "is_completed": bool(detail.get("is_completed", index < stage_index)),
                "needs_human_check": bool(detail.get("needs_human_check", False)),
                "need_fail_llm_suggestion": bool(detail.get("need_fail_llm_suggestion", False)),
                "need_pass_llm_suggestion": bool(detail.get("need_pass_llm_suggestion", False)),
            })
        current_task = "No stages available"
        if 0 <= stage_index < len(stage_list):
            current_task = stage_list[stage_index]["title"]
        return {
            "mission_name": mission_name(workspace_root, info),
            "task_index": stage_index,
            "task_list": {
                "mission": mission_name(workspace_root, info),
                "all_completed": bool(info.get("all_completed", False)),
                "stage_list": stage_list,
                "process": f"{stage_index}/{len(stage_list)}",
                "current_stage_index": stage_index if stage_index < len(stage_list) else None,
                "current_stage_name": current_task,
                "current_task": current_task,
                "last_check_result": {},
            },
        }

    def summary(self, workspace_root: str, current_root: Optional[str] = None) -> dict:
        """Summarize one saved workspace and its snapshot timestamps."""
        snapshot_path = info_path(workspace_root)
        try:
            info_stat = os.stat(snapshot_path)
            info_ctime = getattr(info_stat, "st_birthtime", info_stat.st_ctime)
            info_mtime = info_stat.st_mtime
        except OSError:
            info_ctime = None
            info_mtime = None

        load_error = ""
        try:
            info = load_info(workspace_root)
        except Exception as exc:
            info = {}
            load_error = str(exc)

        stage_items = saved_stage_items(info)
        total_stages = len(stage_items)
        raw_stage_index = safe_int(info.get("stage_index", 0), 0)
        all_completed = bool(info.get("all_completed", False))
        if all_completed:
            completed_stages = total_stages
            current_stage_index = None
        else:
            completed_stages = 0
            for index, detail in stage_items:
                if bool(detail.get("is_completed", False)) or index < raw_stage_index:
                    completed_stages += 1
            current_stage_index = raw_stage_index if 0 <= raw_stage_index < total_stages else None
        progress_percent = 100 if all_completed and total_stages == 0 else 0
        if total_stages > 0:
            progress_percent = round(min(max(completed_stages, 0), total_stages) * 100 / total_stages)

        current_stage_name = ""
        if current_stage_index is not None:
            stage_map = {index: detail for index, detail in stage_items}
            detail = stage_map.get(current_stage_index, {})
            task = detail.get("task", {}) if isinstance(detail.get("task", {}), dict) else {}
            current_stage_name = task.get("title") or detail.get("title") or f"Stage {current_stage_index}"

        time_begin = info.get("time_begin")
        time_end = info.get("time_end")
        run_time = ""
        if time_begin is not None:
            try:
                run_until = float(time_end) if time_end is not None else time.time()
                run_time = fmt_time_deta(run_until - float(time_begin))
            except Exception:
                run_time = ""

        workspace_stat = None
        try:
            workspace_stat = os.stat(workspace_root)
        except OSError:
            pass

        current_root = current_root or self.access.base
        rel_to_current = os.path.relpath(os.path.abspath(workspace_root), os.path.abspath(current_root))
        if rel_to_current == ".":
            rel_to_current = ""

        lifecycle = workspace_lifecycle(info)
        return {
            "path": self.access.relative(workspace_root),
            "path_in_current": rel_to_current,
            "name": os.path.basename(os.path.normpath(workspace_root)),
            "workspace": workspace_root,
            "info_path": snapshot_path,
            "info_ctime": info_ctime,
            "info_ctime_str": format_timestamp(info_ctime),
            "info_mtime": info_mtime,
            "info_mtime_str": format_timestamp(info_mtime),
            "dir_mtime": workspace_stat.st_mtime if workspace_stat else None,
            "mission_name": mission_name(workspace_root, info),
            "stage_index": raw_stage_index,
            "current_stage_index": current_stage_index,
            "current_stage_name": current_stage_name,
            "completed_stages": completed_stages,
            "total_stages": total_stages,
            "progress_percent": progress_percent,
            "progress_label": f"{completed_stages}/{total_stages}" if total_stages else ("done" if all_completed else "0/0"),
            "all_completed": all_completed,
            "is_agent_exit": bool(info.get("is_agent_exit", False)),
            "is_wait_human_check": bool(info.get("is_wait_human_check", False)),
            "is_running": lifecycle == "running",
            "lifecycle": lifecycle,
            "time_begin": time_begin,
            "time_begin_str": format_timestamp(time_begin),
            "time_end": time_end,
            "time_end_str": format_timestamp(time_end),
            "run_time": run_time,
            "version": info.get("version", ""),
            "seed": info.get("seed", ""),
            "load_error": load_error,
        }

    def stage_detail(self, workspace_root: str, info: dict, index: int):
        """Read a saved stage journal and suggestions without evaluating Checkers."""
        stage_items = saved_stage_items(info)
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

    def mission_info(self, workspace_root: str, info: dict) -> dict:
        """Project saved mission rows and shared stage outcomes."""
        task_data = self.task_list(workspace_root, info)
        current_index = task_data["task_index"]
        stage_list = task_data["task_list"]["stage_list"]
        ret = collections.OrderedDict({
            "mission_name": task_data["mission_name"],
            "current_index": current_index,
            "enable_llm_fail_suggestion": any(s.get("need_fail_llm_suggestion") for s in stage_list),
            "enable_llm_pass_suggestion": any(s.get("need_pass_llm_suggestion") for s in stage_list),
            "stages": [],
        })
        stage_detail_map = {index: detail for index, detail in saved_stage_items(info)}
        for stage in stage_list:
            index = stage["index"]
            title = stage.get("title") or f"Stage {index}"
            fail_count = stage.get("fail_count", 0)
            time_cost = stage.get("time_cost", "")
            is_skipped = bool(stage.get("is_skipped", False))
            is_current = index == current_index and not bool(info.get("all_completed", False))
            is_completed = bool(stage.get("is_completed", False))
            detail = stage_detail_map.get(index, {})
            outcome = None
            if stage.get("reached", False) or is_completed or is_current:
                outcome = self.stage_outcome(workspace_root, detail)
            ret["stages"].append({
                "index": index,
                "fail_count": fail_count,
                "time_cost": time_cost,
                "skill_list": stage.get("skill_list", []),
                "reached": stage.get("reached", False),
                "outcome": outcome,
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

    def stage_outcome(self, workspace, detail):
        """Use the same committed-artifact interpretation as a live VerifyStage."""
        return self.history(workspace, detail).outcome()

    def history(self, workspace, detail):
        """Build a history query only from saved stage data and validated paths."""
        task = detail.get("task", {})
        files = task.get("output_files", [])
        if isinstance(files, str):
            files = [files]
        commit = detail.get("meta_data", {}).get("commit", {})
        return StageHistory(workspace, WorkspaceFiles(workspace).path(".ucagent/history"),
                            files, commit)

    def stage_file(self, workspace, info, index, file_path, *, current=False, sync_history=False):
        """Read saved stage content; explicit history synchronization requires a live owner."""
        detail = self.stage_detail(workspace, info, index)
        if isinstance(detail, str):
            return {"error": detail}
        if sync_history:
            return {"is_text": False, "content": "", "diff": "",
                    "error": "Manual history sync is only available from a running agent dashboard."}
        query = self.history(workspace, detail["detail"])
        if current:
            return query.current_file(file_path)
        return query.historical_file(file_path, require_commit=True)

    def list_subworkspaces(self, raw="", *, page=1, page_size=20, q="", state="all", sort_by="info_mtime", sort_desc=True):
        """Discover, filter and page saved children under the selected workspace."""
        current_root, current_rel, _ = self.access.select(raw)
        items = [
            self.summary(root, current_root=current_root)
            for root in self.access.roots(current_root, max_depth=2)
        ]
        state_counts = collections.Counter(item.get("lifecycle", "unknown") for item in items)
        total_count = len(items)

        q_norm = (q or "").strip().lower()
        if q_norm:
            def _match(item: dict) -> bool:
                """Match the operator search across workspace display fields."""
                haystack = " ".join(str(item.get(key, "")) for key in (
                    "path",
                    "path_in_current",
                    "name",
                    "mission_name",
                    "current_stage_name",
                    "lifecycle",
                )).lower()
                return q_norm in haystack
            items = [item for item in items if _match(item)]

        state_norm = (state or "all").strip().lower()
        valid_states = {"all", "running", "waiting", "completed", "exited"}
        if state_norm not in valid_states:
            state_norm = "all"
        if state_norm != "all":
            items = [item for item in items if item.get("lifecycle") == state_norm]

        valid_sort = {
            "path",
            "mission_name",
            "current_stage_name",
            "lifecycle",
            "info_ctime",
            "info_mtime",
            "progress_percent",
            "completed_stages",
            "total_stages",
            "time_begin",
            "time_end",
        }
        if sort_by not in valid_sort:
            sort_by = "info_mtime"

        def _sort_key(item: dict):
            """Order missing values consistently with the selected field type."""
            value = item.get(sort_by)
            if value is None:
                return -1 if sort_by in {"info_ctime", "info_mtime", "progress_percent", "completed_stages", "total_stages", "time_begin", "time_end"} else ""
            if isinstance(value, str):
                return value.lower()
            return value

        items.sort(key=_sort_key, reverse=bool(sort_desc))
        filtered_count = len(items)
        total_pages = (filtered_count + page_size - 1) // page_size if filtered_count else 0
        if total_pages and page > total_pages:
            page = total_pages
        start = (page - 1) * page_size
        page_items = items[start:start + page_size]
        return {
            "count": filtered_count,
            "data": page_items,
            "summary": {
                "total": total_count,
                "filtered": filtered_count,
                "returned": len(page_items),
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "max_depth": 2,
                "base_workspace": self.access.base,
                "current_workspace": current_root,
                "current_workspace_path": current_rel,
                "state_counts": dict(state_counts),
            },
        }

    def find_subworkspace(self, *, path="", task_id="", workspace_id=""):
        """Resolve a saved child by path or a managed task/workspace reference."""
        raw_path = (path or "").strip()
        if raw_path:
            workspace_root, _, is_sub_workspace = self.access.select(raw_path)
            if not is_sub_workspace:
                raise WorkspaceAccessError("invalid_argument", "The base workspace is not a sub workspace")
            return self.summary(workspace_root)

        refs = []
        for raw_ref in (workspace_id, task_id):
            ref = str(raw_ref or "").strip().strip("/")
            if ref and ref not in refs:
                refs.append(ref)
        if not refs:
            raise WorkspaceAccessError("invalid_argument", "'path' or 'task_id' is required")

        for ref in refs:
            for candidate in (os.path.join(ref, "workspace"), ref):
                try:
                    workspace_root, _, is_sub_workspace = self.access.select(candidate)
                except WorkspaceAccessError:
                    continue
                if is_sub_workspace:
                    return self.summary(workspace_root)

        for workspace_root in self.access.roots(self.access.base, max_depth=2):
            rel = self.access.relative(workspace_root)
            try:
                info = load_info(workspace_root)
            except Exception:
                info = {}
            parent = os.path.basename(os.path.dirname(workspace_root))
            name = os.path.basename(workspace_root)
            if any(
                ref
                and (
                    rel == ref
                    or rel.startswith(ref + os.sep)
                    or parent == ref
                    or name == ref
                    or str(info.get("task_id") or "").strip() == ref
                    or str(info.get("workspace_id") or "").strip() == ref
                )
                for ref in refs
            ):
                return self.summary(workspace_root)

        raise WorkspaceAccessError("not_found", f"Sub workspace for '{refs[0]}' not found")

