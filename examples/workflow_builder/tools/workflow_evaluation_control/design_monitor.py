# -*- coding: utf-8 -*-
"""Read-only workspace design monitoring for the local review console."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .json_store import JsonStoreError
from .wfgen_artifacts import artifact_kind, build_artifact_view


MONITORED_FILES = (
    "wfgen/input_example_manifest.yaml",
    "wfgen/workflow_build.yaml",
    "wfgen/requirements_manifest.yaml",
    "wfgen/workflow_implementation_plan.md",
    "eval/applied_changes.json",
    "eval/incremental_report.json",
)
MAX_PREVIEW_BYTES = 2 * 1024 * 1024
MAX_TREE_NODES = 10_000
RUNTIME_DIRECTORIES = {".install", ".ucagent", "tmp", "output"}


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _timestamp(stat_result: os.stat_result) -> str:
    return datetime.fromtimestamp(stat_result.st_mtime, timezone.utc).isoformat()


def _metadata(path: Path, relative: str) -> dict[str, Any]:
    if not path.exists() and not path.is_symlink():
        return {
            "path": relative,
            "exists": False,
            "kind": "missing",
            "size": 0,
            "modified_at": "",
            "mtime_ns": 0,
            "fingerprint": "missing",
        }
    stat_result = path.lstat()
    kind = "symlink" if path.is_symlink() else "directory" if path.is_dir() else "file"
    size = stat_result.st_size if kind != "directory" else 0
    return {
        "path": relative,
        "exists": True,
        "kind": kind,
        "size": size,
        "modified_at": _timestamp(stat_result),
        "mtime_ns": stat_result.st_mtime_ns,
        "fingerprint": f"{kind}:{size}:{stat_result.st_mtime_ns}",
    }


def monitored_file_catalog(workspace: Path) -> list[dict[str, Any]]:
    """Return metadata for the exact six design files exposed by the console."""
    files = []
    for relative in MONITORED_FILES:
        metadata = _metadata(workspace / relative, relative)
        suffix = Path(relative).suffix.lower().lstrip(".")
        metadata.update({
            "format": suffix,
            "artifact_kind": artifact_kind(relative),
            "specialized_view": artifact_kind(relative) != "raw",
            "group": "incremental" if relative.startswith("eval/") else "planning",
        })
        files.append(metadata)
    return files


def workflow_tree(workspace: Path) -> dict[str, Any]:
    """Return a bounded flat tree without following symlinks."""
    root = workspace / "workflow"
    if not root.is_dir():
        return {"root": "workflow", "exists": False, "nodes": [], "truncated": False, "counts": {}}
    nodes: list[dict[str, Any]] = []
    truncated = False

    def visit(directory: Path) -> None:
        nonlocal truncated
        try:
            children = sorted(
                directory.iterdir(),
                key=lambda item: (not item.is_dir() if not item.is_symlink() else True, item.name.lower()),
            )
        except (FileNotFoundError, PermissionError, OSError):
            return
        for path in children:
            if len(nodes) >= MAX_TREE_NODES:
                truncated = True
                return
            try:
                relative = path.relative_to(root).as_posix()
                node = _metadata(path, f"workflow/{relative}")
            except (FileNotFoundError, PermissionError, OSError, ValueError):
                continue
            node.update({
                "relative": relative,
                "name": path.name,
                "parent": Path(relative).parent.as_posix() if "/" in relative else "",
                "depth": len(Path(relative).parts) - 1,
                "runtime": Path(relative).parts[0] in RUNTIME_DIRECTORIES,
            })
            nodes.append(node)
            if node["kind"] == "directory":
                visit(path)
            if truncated:
                return

    visit(root)
    counts = {
        "files": sum(node["kind"] == "file" for node in nodes),
        "directories": sum(node["kind"] == "directory" for node in nodes),
        "symlinks": sum(node["kind"] == "symlink" for node in nodes),
    }
    return {
        "root": "workflow",
        "exists": True,
        "nodes": nodes,
        "truncated": truncated,
        "limit": MAX_TREE_NODES,
        "counts": counts,
    }


def _checker_summary(stage: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = stage.get("meta_data") if isinstance(stage.get("meta_data"), dict) else {}
    values = metadata.get("llm_pass_suggestion")
    if not isinstance(values, list):
        failure = metadata.get("llm_fail_suggestion")
        values = failure.get("check_info", []) if isinstance(failure, dict) else []
    output = []
    for item in values[-12:]:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        output.append({
            "name": item.get("name", ""),
            "passed": item.get("count_pass", 0),
            "failed": item.get("count_fail", 0),
            "checks": item.get("count_check", 0),
        })
    return output


def ucagent_progress(workspace: Path) -> dict[str, Any]:
    """Normalize the root UCAgent state file for a compact read-only status rail."""
    path = workspace / ".ucagent/ucagent_info.json"
    if not path.is_file():
        return {"state": "not_started", "exists": False, "path": ".ucagent/ucagent_info.json"}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {
            "state": "invalid",
            "exists": True,
            "path": ".ucagent/ucagent_info.json",
            "error": str(exc),
            "modified_at": _timestamp(path.stat()),
        }
    if not isinstance(value, dict):
        return {"state": "invalid", "exists": True, "path": ".ucagent/ucagent_info.json", "error": "root value must be an object"}
    stages = value.get("stages_info") if isinstance(value.get("stages_info"), dict) else {}
    ordered = sorted(
        ((int(key), stage) for key, stage in stages.items() if str(key).isdigit() and isinstance(stage, dict)),
        key=lambda item: item[0],
    )
    stage_index = value.get("stage_index") if isinstance(value.get("stage_index"), int) else 0
    current = stages.get(str(stage_index)) if isinstance(stages.get(str(stage_index)), dict) else None
    completed = sum(bool(stage.get("is_completed")) for _, stage in ordered)
    all_completed = bool(value.get("all_completed"))
    if all_completed:
        state = "completed"
    elif value.get("is_agent_exit") or value.get("time_end") is not None:
        state = "exited"
    else:
        state = "running"
    if current is None and all_completed and ordered:
        current = ordered[-1][1]
    current = current or {}
    task = current.get("task") if isinstance(current.get("task"), dict) else {}
    begin = value.get("time_begin") if isinstance(value.get("time_begin"), (int, float)) else None
    end = value.get("time_end") if isinstance(value.get("time_end"), (int, float)) else None
    elapsed = max(0, (end or time.time()) - begin) if begin else None
    recent = []
    for index, stage in ordered[-5:]:
        stage_task = stage.get("task") if isinstance(stage.get("task"), dict) else {}
        recent.append({
            "index": index,
            "title": stage_task.get("title", ""),
            "completed": bool(stage.get("is_completed")),
            "check_pass": bool(stage.get("check_pass")),
            "fail_count": stage.get("fail_count", 0),
            "time_cost": stage.get("time_cost", 0),
        })
    metadata = current.get("meta_data") if isinstance(current.get("meta_data"), dict) else {}
    return {
        "state": state,
        "exists": True,
        "path": ".ucagent/ucagent_info.json",
        "version": value.get("version", ""),
        "stage_index": stage_index,
        "stage_title": task.get("title", ""),
        "stage_completed": bool(current.get("is_completed")),
        "stage_check_pass": bool(current.get("check_pass")),
        "stage_fail_count": _integer(current.get("fail_count")),
        "failure_count_total": sum(_integer(stage.get("fail_count")) for _, stage in ordered),
        "completed_stages": completed,
        "total_stages": len(ordered),
        "all_completed": all_completed,
        "elapsed_seconds": round(elapsed, 1) if elapsed is not None else None,
        "journal": metadata.get("journal", ""),
        "checkers": _checker_summary(current),
        "recent_stages": recent,
        "modified_at": _timestamp(path.stat()),
    }


def design_state(workspace: Path) -> dict[str, Any]:
    """Build the complete design monitoring snapshot."""
    return {
        "monitored_files": monitored_file_catalog(workspace),
        "workflow_tree": workflow_tree(workspace),
        "ucagent": ucagent_progress(workspace),
    }


def _safe_workflow_path(workspace: Path, relative: str) -> Path:
    if not relative.startswith("workflow/") or relative == "workflow/":
        raise JsonStoreError("workflow preview path must identify a file below workflow/")
    root = (workspace / "workflow").resolve()
    candidate = workspace / relative
    if candidate.is_symlink():
        raise JsonStoreError(f"symlink preview is not allowed: {relative}")
    resolved = candidate.resolve()
    if root not in resolved.parents or not resolved.is_file():
        raise JsonStoreError(f"workflow file is unavailable: {relative}")
    return resolved


def _safe_monitored_path(workspace: Path, relative: str) -> Path:
    path = workspace / relative
    if path.is_symlink():
        raise JsonStoreError(f"symlink preview is not allowed: {relative}")
    resolved_workspace = workspace.resolve()
    resolved = path.resolve()
    if resolved_workspace not in resolved.parents or not resolved.is_file():
        raise JsonStoreError(f"monitored file is unavailable: {relative}")
    return resolved


def _text_preview(path: Path, relative: str) -> dict[str, Any]:
    metadata = _metadata(path, relative)
    metadata["format"] = path.suffix.lower().lstrip(".") or path.name.lower()
    if metadata["size"] > MAX_PREVIEW_BYTES:
        return {**metadata, "previewable": False, "reason": f"文件超过 {MAX_PREVIEW_BYTES} 字节预览上限", "content": ""}
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise JsonStoreError(f"cannot read {relative}: {exc}") from exc
    if b"\0" in raw:
        return {**metadata, "previewable": False, "reason": "检测到二进制内容", "content": ""}
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {**metadata, "previewable": False, "reason": "文件不是 UTF-8 文本", "content": ""}
    return {**metadata, "previewable": True, "reason": "", "content": content}


def design_file(workspace: Path, relative: str) -> dict[str, Any]:
    """Read one monitored design file or one safe workflow text preview."""
    if relative.startswith("workflow/"):
        preview = _text_preview(_safe_workflow_path(workspace, relative), relative)
        return {
            **preview,
            "artifact_kind": "workflow_source",
            "specialized_view": False,
            "parse_error": "",
            "structure_issues": [],
            "view_model": {},
        }
    if relative not in MONITORED_FILES:
        raise JsonStoreError(f"file is not part of the design monitor: {relative}")
    path = _safe_monitored_path(workspace, relative)
    preview = _text_preview(path, relative)
    if not preview["previewable"]:
        return {
            **preview,
            "artifact_kind": artifact_kind(relative),
            "specialized_view": False,
            "parse_error": "",
            "structure_issues": [],
            "view_model": {},
        }
    content = preview["content"]
    parsed: Any = None
    parse_error = ""
    try:
        if path.suffix.lower() == ".json":
            parsed = json.loads(content)
        elif path.suffix.lower() in {".yaml", ".yml"}:
            parsed = yaml.safe_load(content)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        parse_error = str(exc)
    manifest: dict[str, Any] = {}
    if relative == "wfgen/workflow_implementation_plan.md":
        try:
            manifest_path = _safe_monitored_path(workspace, "wfgen/requirements_manifest.yaml")
            loaded = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            manifest = loaded if isinstance(loaded, dict) else {}
        except (JsonStoreError, OSError, UnicodeError, yaml.YAMLError):
            pass
    view = build_artifact_view(relative, content, parsed, manifest=manifest, parse_error=parse_error)
    return {**preview, "parsed": parsed, "parse_error": parse_error, **view}
