# -*- coding: utf-8 -*-
"""Controlled structured editing for workflow-builder planning artifacts."""

from __future__ import annotations

import copy
import hashlib
import os
import re
import shutil
import stat
import tempfile
import threading
from pathlib import Path
from typing import Any

import yaml

from ..workflow_builder.core import WorkflowBuildError, validate_build_config
from ..workflow_builder.plan_contract import (
    MIN_RECORD_PROSE,
    REQUIRED_RECORD_HEADINGS,
    effective_prose_length,
    parse_records,
    validate_records,
)
from .design_monitor import ucagent_progress
from .json_store import JsonStoreError


EDITABLE_FILES = (
    "wfgen/input_example_manifest.yaml",
    "wfgen/workflow_build.yaml",
    "wfgen/requirements_manifest.yaml",
    "wfgen/workflow_implementation_plan.md",
)

REQUIREMENT_LISTS = (
    "requirement_sections",
    "required_stages",
    "required_tools",
    "required_checkers",
    "required_guidedocs",
    "required_user_docs",
    "required_templates",
    "required_configs",
    "required_make_targets",
    "required_deliverables",
    "required_python_dependencies",
    "required_system_dependencies",
)

FIXED_USER_DOCS = (
    "docs/README.md", "docs/01快速启动.md", "docs/02输入输出.md",
    "docs/03步骤及检查.md", "docs/04开发者文档-tools.md", "docs/05开发者文档-checkers.md",
)
FIXED_CONFIGS = ("config.yaml", "config/inc.yaml")
FIXED_MAKE_TARGETS = (
    "help", "configure", "configure-check", "check", "check_example",
    "test_tools", "test_checkers", "test_mcp", "plan", "run", "run_inc",
    "clean", "package", "check_config", "check_inc_config",
)
FIXED_DELIVERABLES = (
    "README.md", "setup.py", "config/environment.schema.yaml", "requirements.txt",
    "ucagent_setup.sh", "Makefile", "install.py", ".install/README.md",
    ".install/manifest.json", *FIXED_USER_DOCS, *FIXED_CONFIGS,
)
FIXED_REQUIREMENT_ITEMS = {
    "required_user_docs": set(FIXED_USER_DOCS),
    "required_configs": set(FIXED_CONFIGS),
    "required_make_targets": set(FIXED_MAKE_TARGETS),
    "required_deliverables": set(FIXED_DELIVERABLES),
}
MINIMUM_COUNT_ALIASES = {
    "stages": "required_stages", "tools": "required_tools",
    "checkers": "required_checkers", "guidedocs": "required_guidedocs",
    "user_docs": "required_user_docs", "templates": "required_templates",
    "configs": "required_configs", "make_targets": "required_make_targets",
    "deliverables": "required_deliverables",
}
_SAVE_LOCK = threading.Lock()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _path(workspace: Path, relative: str) -> Path:
    if relative not in EDITABLE_FILES:
        raise JsonStoreError(f"file is not editable: {relative}")
    workspace = workspace.resolve()
    path = (workspace / relative).resolve()
    if workspace not in path.parents or path.is_symlink() or not path.is_file():
        raise JsonStoreError(f"editable file is unavailable: {relative}")
    return path


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise JsonStoreError(f"cannot parse {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise JsonStoreError(f"{path.name} root must be a mapping")
    return value


def _item_name(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("name", "path"):
            if isinstance(value.get(key), str):
                return value[key]
    return ""


def _minimum_counts(manifest: dict[str, Any]) -> dict[str, int]:
    return {
        alias: len(manifest.get(list_key, []))
        for alias, list_key in MINIMUM_COUNT_ALIASES.items()
        if isinstance(manifest.get(list_key), list)
    }


def _plan_draft(text: str) -> dict[str, Any]:
    records = parse_records(text)
    if not records:
        raise JsonStoreError("implementation plan has no editable stage record")
    latest = records[-1]
    sections: dict[str, str] = {}
    for index, heading in enumerate(REQUIRED_RECORD_HEADINGS):
        match = re.search(
            rf"^###\s+{re.escape(heading)}\s*$\n(?P<body>.*?)"
            rf"(?=^###\s+(?:{'|'.join(map(re.escape, REQUIRED_RECORD_HEADINGS[index + 1:]))})\s*$|\Z)"
            if index + 1 < len(REQUIRED_RECORD_HEADINGS)
            else rf"^###\s+{re.escape(heading)}\s*$\n(?P<body>.*)\Z",
            latest.body,
            re.MULTILINE | re.DOTALL,
        )
        sections[heading] = match.group("body").strip() if match else ""
    return {
        "stage_index": latest.index,
        "stage_name": latest.name,
        "sections": sections,
    }


def _editor_schema(relative: str) -> dict[str, Any]:
    if relative.endswith("input_example_manifest.yaml"):
        return {
            "kind": "input_example",
            "labels": {"source_dir": "示例来源目录", "required_input": "必需输入", "resource_paths": "资源路径"},
            "list_templates": {
                "required_input": {"path": "", "type": "file"},
                "resource_paths": {"declared_path": "", "source_path": ""},
            },
            "enums": {"required_input.*.type": ["file", "directory"]},
            "closed_objects": [""],
        }
    if relative.endswith("requirements_manifest.yaml"):
        return {
            "kind": "requirements",
            "list_templates": {
                "requirement_sections": "",
                "required_stages": {"name": "", "label": "", "config": "config.yaml"},
                "required_tools": {"name": ""},
                "required_checkers": {"name": ""},
                "required_guidedocs": {"path": "", "scope": "all"},
                "required_user_docs": {"path": ""},
                "required_templates": {"path": ""},
                "required_configs": {"path": ""},
                "required_make_targets": "",
                "required_deliverables": {"path": ""},
                "required_python_dependencies": {"package": "", "version": ""},
                "required_system_dependencies": {"name": "", "install": ""},
            },
            "fixed_items": {key: sorted(value) for key, value in FIXED_REQUIREMENT_ITEMS.items()},
            "closed_objects": [""],
        }
    if relative.endswith("workflow_build.yaml"):
        return {
            "kind": "workflow_build",
            "list_templates": {
                "runtime_contract.required_input": {"path": "", "type": "file"},
                "files.public": {"path": "", "template": "empty"},
                "workflow_spec.stages": {
                    "name": "", "description": "", "reference_files": [],
                    "output_files": [], "checker": [],
                },
                "workflow_spec.checkers.*.fixtures": {"path": "", "content": ""},
                "workflow_spec.checkers.*.tests": {
                    "name": "", "args": {}, "expected_pass": True,
                },
            },
            "read_only": [
                "root", "directories", "files.internal", "makefile", "config",
                "workflow_spec.checkers.*.name", "workflow_spec.checkers.*.entry",
                "workflow_spec.checkers.*.source",
            ],
            "closed_objects": [""],
        }
    return {
        "kind": "implementation_plan",
        "minimum_effective_prose": MIN_RECORD_PROSE,
        "required_sections": list(REQUIRED_RECORD_HEADINGS),
        "read_only": ["stage_index", "stage_name"],
        "closed_objects": ["", "sections"],
    }


def _draft_for(relative: str, path: Path) -> dict[str, Any]:
    if relative.endswith("workflow_implementation_plan.md"):
        return _plan_draft(path.read_text(encoding="utf-8"))
    value = _load_yaml(path)
    if relative.endswith("input_example_manifest.yaml"):
        return {
            "source_dir": value.get("source_dir", "input/test_input"),
            "required_input": copy.deepcopy(value.get("required_input", [])),
            "resource_paths": copy.deepcopy(value.get("resource_paths", [])),
        }
    if relative.endswith("requirements_manifest.yaml"):
        keys = ("source_requirement", "section_coverage", *REQUIREMENT_LISTS)
        return {key: copy.deepcopy(value.get(key, [] if key in REQUIREMENT_LISTS else "")) for key in keys}
    spec = value.get("workflow_spec", {})
    checkers = []
    for checker in spec.get("checkers", []) if isinstance(spec, dict) else []:
        if not isinstance(checker, dict):
            continue
        checkers.append({
            "name": checker.get("name", ""),
            "description": checker.get("description", ""),
            "entry": copy.deepcopy(checker.get("entry", {})),
            "source": checker.get("source", ""),
            "fixtures": copy.deepcopy(checker.get("fixtures", [])),
            "tests": copy.deepcopy(checker.get("tests", [])),
        })
    return {
        "workflow": copy.deepcopy(value.get("workflow", {})),
        "runtime_contract": {
            "required_input": copy.deepcopy(value.get("runtime_contract", {}).get("required_input", [])),
            "modes": copy.deepcopy(value.get("runtime_contract", {}).get("modes", {})),
        },
        "files": {"public": copy.deepcopy(value.get("files", {}).get("public", []))},
        "workflow_spec": {
            "checkers": checkers,
            "stages": copy.deepcopy(spec.get("stages", [])) if isinstance(spec, dict) else [],
        },
        "acceptance": copy.deepcopy(value.get("acceptance", {})),
    }


def editable_document(workspace: Path, relative: str) -> dict[str, Any]:
    """Return a controlled form model rather than editable source text."""
    path = _path(workspace, relative)
    progress = ucagent_progress(workspace)
    blocked = progress.get("state") in {"running", "invalid"}
    draft = _draft_for(relative, path)
    if relative.endswith("input_example_manifest.yaml"):
        source = str(draft.get("source_dir", ""))
        derived = {
            "target_dir": "input/example",
            "copy_mode": "copy_tree" if source and (workspace / source).is_dir() else "self_contained",
            "required_input_count": len(draft.get("required_input", [])),
            "resource_count": len(draft.get("resource_paths", [])),
        }
    elif relative.endswith("requirements_manifest.yaml"):
        derived = {"minimum_counts": _minimum_counts(draft)}
    elif relative.endswith("workflow_build.yaml"):
        derived = {
            "stage_count": len(draft.get("workflow_spec", {}).get("stages", [])),
            "checker_count": len(draft.get("workflow_spec", {}).get("checkers", [])),
            "public_file_count": len(draft.get("files", {}).get("public", [])),
        }
    else:
        derived = {
            "effective_prose": effective_prose_length(
                "\n".join(str(value) for value in draft.get("sections", {}).values())
            ),
            "minimum": MIN_RECORD_PROSE,
        }
    return {
        "path": relative,
        "fingerprint": _sha256(path),
        "draft": draft,
        "derived": derived,
        "schema": _editor_schema(relative),
        "save_allowed": not blocked,
        "save_block_reason": (
            "UCAgent 正在运行，停止后刷新才能保存"
            if progress.get("state") == "running"
            else "UCAgent 状态无法确认，修复状态文件并刷新后才能保存"
            if progress.get("state") == "invalid"
            else ""
        ),
    }


def _apply_draft(workspace: Path, relative: str, original: str, draft: dict[str, Any]) -> str:
    if relative.endswith("workflow_implementation_plan.md"):
        records = parse_records(original)
        if not records:
            raise JsonStoreError("implementation plan has no stage record")
        latest = records[-1]
        if draft.get("stage_index") != latest.index or draft.get("stage_name") != latest.name:
            raise JsonStoreError("implementation plan stage identity is read-only")
        sections = draft.get("sections")
        if not isinstance(sections, dict):
            raise JsonStoreError("implementation plan sections must be an object")
        body = "\n\n".join(
            f"### {heading}\n\n{str(sections.get(heading, '')).strip()}"
            for heading in REQUIRED_RECORD_HEADINGS
        )
        begin = f"<!-- WFB-STAGE-PLAN:{latest.index:02d}:{latest.name}:BEGIN -->"
        return original[: latest.start] + begin + "\n" + f"前序内容SHA256: `{latest.digest}`\n" + body + "\n" + f"<!-- WFB-STAGE-PLAN:{latest.index:02d}:{latest.name}:END -->" + original[latest.end:]

    value = yaml.safe_load(original)
    if not isinstance(value, dict):
        raise JsonStoreError(f"{relative} root must be a mapping")
    if relative.endswith("input_example_manifest.yaml"):
        source = str(draft.get("source_dir", "")).strip()
        value["source_dir"] = source
        value["target_dir"] = "input/example"
        value["copy_mode"] = "copy_tree" if source and (workspace / source).is_dir() else "self_contained"
        value["required_input"] = copy.deepcopy(draft.get("required_input", []))
        value["resource_paths"] = copy.deepcopy(draft.get("resource_paths", []))
    elif relative.endswith("requirements_manifest.yaml"):
        for key in ("source_requirement", "section_coverage", *REQUIREMENT_LISTS):
            if key in draft:
                value[key] = copy.deepcopy(draft[key])
        value["minimum_counts"] = _minimum_counts(value)
    else:
        workflow = draft.get("workflow", {})
        if isinstance(workflow, dict):
            value.setdefault("workflow", {}).update({
                key: copy.deepcopy(workflow.get(key, value.get("workflow", {}).get(key)))
                for key in ("name", "description", "version")
            })
        if isinstance(draft.get("acceptance"), dict):
            value["acceptance"] = copy.deepcopy(draft["acceptance"])
        runtime = draft.get("runtime_contract", {})
        if isinstance(runtime, dict):
            value.setdefault("runtime_contract", {})["required_input"] = copy.deepcopy(runtime.get("required_input", []))
            value["runtime_contract"]["modes"] = copy.deepcopy(runtime.get("modes", {}))
        public = draft.get("files", {}).get("public") if isinstance(draft.get("files"), dict) else None
        if isinstance(public, list):
            value.setdefault("files", {})["public"] = copy.deepcopy(public)
        spec_draft = draft.get("workflow_spec", {})
        if isinstance(spec_draft, dict):
            value.setdefault("workflow_spec", {})["stages"] = copy.deepcopy(spec_draft.get("stages", []))
            current = {item.get("name"): item for item in value["workflow_spec"].get("checkers", []) if isinstance(item, dict)}
            edited = spec_draft.get("checkers", [])
            if not isinstance(edited, list) or {item.get("name") for item in edited if isinstance(item, dict)} != set(current):
                raise JsonStoreError("Checker names and membership are read-only")
            for item in edited:
                target = current[item["name"]]
                target["description"] = str(item.get("description", ""))
                target["fixtures"] = copy.deepcopy(item.get("fixtures", []))
                target["tests"] = copy.deepcopy(item.get("tests", []))
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True, width=120)


def _checker_result(checker: Any, workspace: Path) -> tuple[bool, Any]:
    checker.workspace = str(workspace)
    return checker.do_check()


def _cross_file_errors(paths: dict[str, Path]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    try:
        manifest = _load_yaml(paths["wfgen/requirements_manifest.yaml"])
        build = _load_yaml(paths["wfgen/workflow_build.yaml"])
        example = _load_yaml(paths["wfgen/input_example_manifest.yaml"])
    except JsonStoreError as exc:
        return [{"path": "wfgen", "message": str(exc)}]

    declared: dict[str, set[str]] = {}
    for prefix, key in (
        ("stage", "required_stages"),
        ("tool", "required_tools"),
        ("checker", "required_checkers"),
        ("deliverable", "required_deliverables"),
    ):
        declared[prefix] = {
            name for item in manifest.get(key, [])
            if (name := _item_name(item))
        }
    declared.update({
        "config": {_item_name(item) for item in manifest.get("required_configs", [])},
        "guidedoc": {_item_name(item) for item in manifest.get("required_guidedocs", [])},
        "user_doc": {_item_name(item) for item in manifest.get("required_user_docs", [])},
        "make_target": {_item_name(item) for item in manifest.get("required_make_targets", [])},
        "required_make_targets": {_item_name(item) for item in manifest.get("required_make_targets", [])},
    })
    declared["doc"] = declared["guidedoc"] | declared["user_doc"]
    coverage = manifest.get("section_coverage", {})
    if isinstance(coverage, dict):
        for section, targets in coverage.items():
            if not isinstance(targets, list):
                continue
            for target in targets:
                if not isinstance(target, str) or ":" not in target:
                    errors.append({
                        "path": f"wfgen/requirements_manifest.yaml:section_coverage.{section}",
                        "message": f"coverage target must use type:name syntax: {target!r}",
                    })
                    continue
                prefix, name = target.split(":", 1)
                if prefix in declared and name not in declared[prefix]:
                    errors.append({
                        "path": f"wfgen/requirements_manifest.yaml:section_coverage.{section}",
                        "message": f"coverage target does not identify a declared component: {target}",
                    })

    def input_contract(value: Any) -> list[tuple[str, str]]:
        output = []
        for item in value if isinstance(value, list) else []:
            if isinstance(item, str):
                output.append((item, "file"))
            elif isinstance(item, dict):
                output.append((str(item.get("path", "")), str(item.get("type", "file"))))
        return output

    example_inputs = input_contract(example.get("required_input"))
    build_inputs = input_contract(build.get("runtime_contract", {}).get("required_input"))
    if example_inputs != build_inputs:
        errors.append({
            "path": "wfgen/input_example_manifest.yaml",
            "message": "required_input must exactly match workflow_build.runtime_contract.required_input in order and type",
        })
    return errors


def _validate_candidates(workspace: Path, candidates: dict[str, str]) -> list[dict[str, str]]:
    from ..workflow_builder.uc_checkers import (
        WorkflowBuildConfigChecker,
        WorkflowImplementationPlanChecker,
        WorkflowInputExampleManifestChecker,
        WorkflowRequirementCoverageChecker,
    )

    errors: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="design-editor-", dir=workspace / "tmp") as temporary:
        temp = Path(temporary)
        paths: dict[str, Path] = {}
        for relative in EDITABLE_FILES:
            target = temp / Path(relative).name
            target.write_text(candidates.get(relative, _path(workspace, relative).read_text(encoding="utf-8")), encoding="utf-8")
            paths[relative] = target
        errors.extend(_cross_file_errors(paths))
        try:
            build = _load_yaml(paths["wfgen/workflow_build.yaml"])
            validate_build_config(build)
        except (JsonStoreError, WorkflowBuildError) as exc:
            errors.append({"path": "wfgen/workflow_build.yaml", "message": str(exc)})
        checks = (
            ("wfgen/input_example_manifest.yaml", WorkflowInputExampleManifestChecker(str(paths["wfgen/input_example_manifest.yaml"]))),
            ("wfgen/workflow_build.yaml", WorkflowBuildConfigChecker(str(paths["wfgen/workflow_build.yaml"]), expected_root="workflow")),
            ("wfgen/requirements_manifest.yaml", WorkflowRequirementCoverageChecker(str(paths["wfgen/requirements_manifest.yaml"]), mode="manifest")),
            ("wfgen/requirements_manifest.yaml", WorkflowRequirementCoverageChecker(str(paths["wfgen/requirements_manifest.yaml"]), build_config_path=str(paths["wfgen/workflow_build.yaml"]), mode="build")),
        )
        for relative, checker in checks:
            passed, result = _checker_result(checker, workspace)
            if not passed:
                errors.append({"path": relative, "message": str(result)})
        plan_text = paths["wfgen/workflow_implementation_plan.md"].read_text(encoding="utf-8")
        records = parse_records(plan_text)
        if not records:
            errors.append({"path": "wfgen/workflow_implementation_plan.md", "message": "没有可校验的阶段记录"})
        else:
            problems = validate_records(plan_text, records[-1].name)
            if problems:
                errors.append({"path": "wfgen/workflow_implementation_plan.md", "message": str(problems)})
            checker = WorkflowImplementationPlanChecker(str(paths["wfgen/workflow_implementation_plan.md"]), str(paths["wfgen/requirements_manifest.yaml"]))
            passed, result = _checker_result(checker, workspace)
            if not passed:
                errors.append({"path": "wfgen/workflow_implementation_plan.md", "message": str(result)})
    return errors


def validate_edits(workspace: Path, edits: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate a multi-file structured draft without changing workspace files."""
    if not isinstance(edits, list) or not edits:
        raise JsonStoreError("at least one edited document is required")
    candidates: dict[str, str] = {}
    fingerprints: dict[str, str] = {}
    for edit in edits:
        if not isinstance(edit, dict) or not isinstance(edit.get("draft"), dict):
            raise JsonStoreError("each edit requires path, fingerprint, and structured draft")
        relative = str(edit.get("path", ""))
        path = _path(workspace, relative)
        expected = str(edit.get("fingerprint", ""))
        actual = _sha256(path)
        if expected != actual:
            raise JsonStoreError(f"revision conflict for {relative}; refresh before saving")
        fingerprints[relative] = actual
        candidates[relative] = _apply_draft(workspace, relative, path.read_text(encoding="utf-8"), edit["draft"])
    errors = _validate_candidates(workspace, candidates)
    metrics = {}
    plan = candidates.get("wfgen/workflow_implementation_plan.md")
    if plan:
        records = parse_records(plan)
        metrics["plan_effective_prose"] = effective_prose_length(records[-1].body) if records else 0
    return {"valid": not errors, "errors": errors, "metrics": metrics, "candidates": candidates, "fingerprints": fingerprints}


def save_edits(workspace: Path, edits: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate and atomically replace all edited planning files."""
    with _SAVE_LOCK:
        return _save_edits_locked(workspace, edits)


def _save_edits_locked(workspace: Path, edits: list[dict[str, Any]]) -> dict[str, Any]:
    """Serialize fingerprint validation and replacement within the review server."""
    progress = ucagent_progress(workspace)
    if progress.get("state") in {"running", "invalid"}:
        raise JsonStoreError("UCAgent state does not permit saving; stop it or repair its state file, then refresh")
    result = validate_edits(workspace, edits)
    if not result["valid"]:
        raise JsonStoreError("draft validation failed: " + "; ".join(item["message"] for item in result["errors"]))
    candidates = result.pop("candidates")
    result.pop("fingerprints", None)
    snapshots: dict[str, tuple[bytes, int]] = {}
    temp_root = workspace / "tmp" / "design_editor"
    temp_root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    try:
        for relative, content in candidates.items():
            path = _path(workspace, relative)
            snapshots[relative] = (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
            fd, temporary = tempfile.mkstemp(prefix="draft-", suffix=path.suffix, dir=temp_root)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                path.chmod(path.stat().st_mode | stat.S_IWUSR)
                os.replace(temporary, path)
                path.chmod(snapshots[relative][1])
                written.append(relative)
            finally:
                Path(temporary).unlink(missing_ok=True)
    except OSError as exc:
        for relative in written:
            path = _path(workspace, relative)
            data, mode = snapshots[relative]
            path.write_bytes(data)
            path.chmod(mode)
        raise JsonStoreError(f"design save failed and was rolled back: {exc}") from exc
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
    return {
        "saved": written,
        "fingerprints": {relative: _sha256(_path(workspace, relative)) for relative in written},
        "metrics": result.get("metrics", {}),
    }
