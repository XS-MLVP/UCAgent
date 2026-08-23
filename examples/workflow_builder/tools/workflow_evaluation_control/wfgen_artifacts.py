# -*- coding: utf-8 -*-
"""Read-only view models for stable workflow-builder planning artifacts."""

from __future__ import annotations

import re
from typing import Any

from ..workflow_builder.plan_contract import (
    REQUIRED_RECORD_HEADINGS,
    STAGE_ORDER,
    effective_prose_length,
    parse_records,
    validate_records,
)


ARTIFACT_KINDS = {
    "requirements_manifest.yaml": "requirements_manifest",
    "input_example_manifest.yaml": "input_example_manifest",
    "workflow_build.yaml": "workflow_build",
    "workflow_build_schema.yaml": "workflow_build_schema",
    "guidedoc_spec_schema.yaml": "guidedoc_spec_schema",
    "smoke_tool_selection.yaml": "smoke_tool_selection",
    "mcp_baseline_evidence.yaml": "mcp_baseline_evidence",
    "workflow_implementation_plan.md": "workflow_implementation_plan",
    "applied_changes.json": "applied_changes",
    "incremental_report.json": "incremental_report",
}


def artifact_kind(relative: str) -> str:
    """Return the stable renderer identity for one wfgen-relative path."""
    return ARTIFACT_KINDS.get(relative.rsplit("/", 1)[-1], "raw")


def _issue(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _name(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in ("name", "path", "id"):
            if isinstance(item.get(key), str):
                return item[key]
    return ""


def _status(value: Any) -> str:
    normalized = str(value or "unknown").strip().lower()
    return {"pass": "passed", "all_pass": "passed", "fail": "failed"}.get(normalized, normalized)


def _require_fields(data: dict[str, Any], fields: dict[str, type], prefix: str = "") -> list[dict[str, str]]:
    issues = []
    for field, expected in fields.items():
        path = f"{prefix}.{field}" if prefix else field
        if field not in data:
            issues.append(_issue("missing_field", path, "缺少固定格式字段"))
        elif not isinstance(data[field], expected):
            issues.append(_issue("invalid_type", path, f"应为 {expected.__name__}"))
    return issues


def _requirements_manifest(data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    required_lists = (
        "requirement_sections", "required_stages", "required_tools", "required_checkers",
        "required_guidedocs", "required_user_docs", "required_templates", "required_configs",
        "required_make_targets", "required_deliverables", "required_python_dependencies",
        "required_system_dependencies",
    )
    issues = _require_fields(data, {
        "source_requirement": str,
        "section_coverage": dict,
        "runtime_contract": dict,
        "minimum_counts": dict,
        "milestones": dict,
    })
    for field in required_lists:
        issues.extend(_require_fields(data, {field: list}))
    stages = _list(data.get("required_stages"))
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            issues.append(_issue("invalid_item", f"required_stages[{index}]", "阶段必须是包含 name、label、config 的对象"))
            continue
        issues.extend(_require_fields(stage, {"name": str, "label": str, "config": str}, f"required_stages[{index}]"))
    sections = [str(item) for item in _list(data.get("requirement_sections"))]
    coverage = _mapping(data.get("section_coverage"))
    for section in sections:
        if not _list(coverage.get(section)):
            issues.append(_issue("uncovered_section", f"section_coverage.{section}", "需求章节没有覆盖目标"))
    component_keys = (
        "required_stages", "required_tools", "required_checkers", "required_guidedocs",
        "required_user_docs", "required_templates", "required_configs", "required_deliverables",
    )
    return {
        "source_requirement": data.get("source_requirement", ""),
        "counts": {key: len(_list(data.get(key))) for key in component_keys},
        "coverage": [{"section": section, "targets": _list(coverage.get(section))} for section in sections],
        "components": {key: _list(data.get(key)) for key in component_keys},
        "make_targets": _list(data.get("required_make_targets")),
        "python_dependencies": _list(data.get("required_python_dependencies")),
        "system_dependencies": _list(data.get("required_system_dependencies")),
        "runtime_contract": _mapping(data.get("runtime_contract")),
        "minimum_counts": _mapping(data.get("minimum_counts")),
        "milestones": _mapping(data.get("milestones")),
    }, issues


def _input_example_manifest(data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    issues = _require_fields(data, {
        "source_dir": str, "target_dir": str, "copy_mode": str, "required_input": list,
    })
    if data.get("target_dir") not in {None, "input/example"}:
        issues.append(_issue("unexpected_value", "target_dir", "固定目标应为 input/example"))
    if data.get("copy_mode") not in {None, "copy_tree", "self_contained"}:
        issues.append(_issue("unexpected_value", "copy_mode", "只支持 copy_tree 或 self_contained"))
    resource_paths = data.get("resource_paths", [])
    if not isinstance(resource_paths, list):
        issues.append(_issue("invalid_type", "resource_paths", "应为列表"))
        resource_paths = []
    return {
        "source_dir": data.get("source_dir", ""),
        "target_dir": data.get("target_dir", ""),
        "copy_mode": data.get("copy_mode", ""),
        "required_input": _list(data.get("required_input")),
        "resource_paths": resource_paths,
    }, issues


def _workflow_build(data: dict[str, Any], reference: bool = False) -> tuple[dict[str, Any], list[dict[str, str]]]:
    root_fields = {
        "workflow": dict, "root": dict, "runtime_contract": dict, "directories": dict,
        "files": dict, "makefile": dict, "config": dict, "workflow_spec": dict,
        "acceptance": dict,
    }
    issues = _require_fields(data, root_fields)
    workflow = _mapping(data.get("workflow"))
    issues.extend(_require_fields(workflow, {"name": str, "description": str, "version": str}, "workflow"))
    root = _mapping(data.get("root"))
    issues.extend(_require_fields(root, {"path": str, "overwrite": bool}, "root"))
    spec = _mapping(data.get("workflow_spec"))
    for field in ("checkers", "stages"):
        if not isinstance(spec.get(field), list) or not spec.get(field):
            issues.append(_issue("missing_collection", f"workflow_spec.{field}", "必须是非空列表"))
    checkers = []
    for index, checker in enumerate(_list(spec.get("checkers"))):
        if not isinstance(checker, dict):
            issues.append(_issue("invalid_item", f"workflow_spec.checkers[{index}]", "Checker 必须是对象"))
            continue
        entry = _mapping(checker.get("entry"))
        missing = [key for key in ("name", "description", "source", "fixtures", "tests") if key not in checker]
        missing.extend(f"entry.{key}" for key in ("file", "class_name", "method") if key not in entry)
        for field in missing:
            issues.append(_issue("missing_field", f"workflow_spec.checkers[{index}].{field}", "缺少 Checker 中心定义字段"))
        tests = _list(checker.get("tests"))
        outcomes = {test.get("expected_pass") for test in tests if isinstance(test, dict)}
        if tests and outcomes != {True, False}:
            issues.append(_issue("test_coverage", f"workflow_spec.checkers[{index}].tests", "应同时包含 PASS 和 FAIL 测试"))
        checkers.append({
            "name": checker.get("name", ""), "description": checker.get("description", ""),
            "entry": entry, "source": checker.get("source", ""),
            "fixtures": _list(checker.get("fixtures")), "tests": tests,
        })
    stages = []
    for index, stage in enumerate(_list(spec.get("stages"))):
        if not isinstance(stage, dict):
            issues.append(_issue("invalid_item", f"workflow_spec.stages[{index}]", "阶段必须是对象"))
            continue
        for field, expected in {"name": str, "description": str, "reference_files": list, "output_files": list, "checker": list}.items():
            issues.extend(_require_fields(stage, {field: expected}, f"workflow_spec.stages[{index}]"))
        stages.append(stage)
    runtime = _mapping(data.get("runtime_contract"))
    return {
        "reference_template": reference,
        "workflow": workflow,
        "root": root,
        "runtime_contract": runtime,
        "modes": _mapping(runtime.get("modes")),
        "directories": _mapping(data.get("directories")),
        "files": _mapping(data.get("files")),
        "make_targets": _list(_mapping(data.get("makefile")).get("targets")),
        "checkers": checkers,
        "stages": stages,
        "acceptance": _mapping(data.get("acceptance")),
    }, issues


def _smoke_tool_selection(data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    issues = _require_fields(data, {"name": str, "spec_path": str, "fixture_paths": list})
    name = data.get("name", "")
    expected = f".workflow/tool_specs/{name}.yaml" if name else ""
    if expected and data.get("spec_path") != expected:
        issues.append(_issue("spec_path_mismatch", "spec_path", f"应为 {expected}"))
    return {"name": name, "spec_path": data.get("spec_path", ""), "fixture_paths": _list(data.get("fixture_paths"))}, issues


def _mcp_baseline(data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    issues = _require_fields(data, {"stage": str, "status": str, "generated_at": str})
    tools = data.get("configured_generated_tools", data.get("tools"))
    lifecycle = data.get("service_lifecycle", data.get("child_ucagent_exit"))
    static_check = data.get("post_mcp_static_check", data.get("post_test_make_check"))
    logs = _mapping(data.get("logs"))
    mcp_result = data.get("mcp_result")
    if not isinstance(tools, list):
        issues.append(_issue("missing_evidence", "configured_generated_tools|tools", "缺少已验证工具列表"))
        tools = []
    if not isinstance(mcp_result, dict):
        legacy_tools = [item for item in tools if isinstance(item, dict) and "mcp_result" in item]
        if legacy_tools or isinstance(data.get("list_tools"), dict):
            mcp_result = {
                "status": "passed" if all(str(item.get("mcp_result", "")).lower() in {"pass", "passed"} for item in legacy_tools) else "unknown",
                "list_tools": _mapping(data.get("list_tools")),
                "calls": [{"name": item.get("name", ""), "status": _status(item.get("mcp_result"))} for item in legacy_tools],
            }
        else:
            issues.append(_issue("missing_evidence", "mcp_result", "缺少 MCP 注册或调用结果"))
            mcp_result = {}
    if not isinstance(lifecycle, dict):
        issues.append(_issue("missing_evidence", "service_lifecycle|child_ucagent_exit", "缺少子服务退出与权限恢复证据"))
        lifecycle = {}
    if not isinstance(static_check, dict):
        issues.append(_issue("missing_evidence", "post_mcp_static_check|post_test_make_check", "缺少 MCP 后静态检查结果"))
        static_check = {}
    failure_summary = data.get("failure_summary", [])
    summary_note = ""
    if isinstance(failure_summary, str):
        summary_note = failure_summary.strip()
        failure_summary = [] if not summary_note or summary_note.startswith("无失败") else [summary_note]
    elif not isinstance(failure_summary, list):
        issues.append(_issue("invalid_type", "failure_summary", "应为列表或兼容的摘要文本"))
        failure_summary = []
    normalized_tools = []
    for tool in tools:
        if not isinstance(tool, dict):
            normalized_tools.append({"name": str(tool), "direct_result": {"status": "unknown"}})
            continue
        normalized = dict(tool)
        direct_result = tool.get("direct_result")
        if isinstance(direct_result, dict):
            normalized["direct_result"] = {**direct_result, "status": _status(direct_result.get("status"))}
        else:
            normalized["direct_result"] = {"status": _status(direct_result)}
        normalized_tools.append(normalized)
    normalized_mcp = dict(mcp_result)
    normalized_mcp["status"] = _status(mcp_result.get("status"))
    normalized_mcp["calls"] = [
        {**call, "status": _status(call.get("status"))}
        for call in _list(mcp_result.get("calls")) if isinstance(call, dict)
    ]
    return {
        "stage": data.get("stage", ""), "status": _status(data.get("status")),
        "generated_at": data.get("generated_at", ""),
        "tools": normalized_tools,
        "mcp_result": normalized_mcp,
        "service_lifecycle": lifecycle,
        "post_mcp_static_check": static_check,
        "failure_summary": failure_summary,
        "summary_note": summary_note,
        "result_log": data.get("result_log", logs.get("mcp_result_log", "")),
        "service_log": data.get("service_log", logs.get("child_ucagent_log", "")),
    }, issues


def _guidedoc_schema(data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    issues = _require_fields(data, {
        "title": str, "document_type": str, "operation_contract": bool,
        "output": str, "sections": list,
    })
    for index, section in enumerate(_list(data.get("sections"))):
        if not isinstance(section, dict):
            issues.append(_issue("invalid_item", f"sections[{index}]", "章节必须是对象"))
        else:
            issues.extend(_require_fields(section, {"id": str, "heading": str, "content": str}, f"sections[{index}]"))
    return {
        "title": data.get("title", ""), "document_type": data.get("document_type", ""),
        "operation_contract": data.get("operation_contract"), "output": data.get("output", ""),
        "sections": _list(data.get("sections")),
    }, issues


def _markdown_sections(text: str) -> list[dict[str, Any]]:
    matches = list(re.finditer(r"^(#{2,3})\s+(.+?)\s*$", text, re.MULTILINE))
    sections: list[dict[str, Any]] = []
    current_h2: dict[str, Any] | None = None
    for index, match in enumerate(matches):
        level = len(match.group(1))
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        entry = {"heading": match.group(2), "content": text[match.end():end].strip()}
        if level == 2:
            current_h2 = {**entry, "children": []}
            sections.append(current_h2)
        elif current_h2 is not None:
            current_h2["children"].append(entry)
    return sections


def _implementation_plan(text: str, manifest: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    records = parse_records(text)
    first_stage = re.search(r"^##\s+阶段\s+\d{2}：", text, re.MULTILINE)
    architecture_text = text[: first_stage.start()] if first_stage else text
    sections = _markdown_sections(architecture_text)
    issues = []
    required_headings = (
        "工作流概述", "输入输出契约", "阶段设计", "工具设计", "Checker设计",
        "GuideDoc设计", "用户文档设计", "环境配置设计", "运行模式与依赖",
    )
    headings = {section["heading"].replace(" ", "") for section in sections}
    for heading in required_headings:
        if heading.replace(" ", "") not in headings:
            issues.append(_issue("missing_heading", heading, "缺少实现计划固定章节"))
    manifest_groups = {
        "stages": _list(manifest.get("required_stages")),
        "tools": _list(manifest.get("required_tools")),
        "checkers": _list(manifest.get("required_checkers")),
    }
    missing_components = {}
    for group, items in manifest_groups.items():
        names = [name for name in (_name(item) for item in items) if name]
        missing = [name for name in names if name not in architecture_text]
        if missing:
            missing_components[group] = missing
            for name in missing:
                issues.append(_issue("missing_component", f"{group}.{name}", "实现计划没有覆盖 manifest 组件"))
    record_views = []
    for record in records:
        body_sections = _markdown_sections("## record\n" + record.body)[0].get("children", [])
        record_views.append({
            "index": record.index, "name": record.name, "digest": record.digest,
            "sections": body_sections, "prose_length": effective_prose_length(record.body),
        })
    record_validation: dict[str, Any] = {}
    if records:
        if records[-1].name in STAGE_ORDER:
            record_validation = validate_records(text, records[-1].name)
            if record_validation:
                issues.append(_issue("living_plan_contract", "stage_records", "阶段顺序、标题、长度或 SHA 链存在问题"))
        else:
            issues.append(_issue("unknown_stage", "stage_records", "追加记录包含未知阶段"))
    else:
        issues.append(_issue("missing_stage_records", "stage_records", "尚无 WFB-STAGE-PLAN 追加记录"))
    return {
        "sections": sections,
        "records": record_views,
        "record_headings": list(REQUIRED_RECORD_HEADINGS),
        "record_validation": record_validation,
        "missing_components": missing_components,
        "stats": {
            "effective_prose": effective_prose_length(text),
            "architecture_sections": len(sections),
            "stage_records": len(records),
        },
    }, issues


def _applied_changes(data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    issues = _require_fields(data, {"schema_version": int, "revision": int, "entries": list})
    entries = []
    change_count = 0
    for index, entry in enumerate(_list(data.get("entries"))):
        if not isinstance(entry, dict):
            issues.append(_issue("invalid_item", f"entries[{index}]", "部署批次必须是对象"))
            continue
        changes = _list(entry.get("applied_changes"))
        change_count += len(changes)
        entries.append({
            "id": entry.get("id", ""),
            "status": entry.get("status", ""),
            "operation": entry.get("operation", "deploy"),
            "run_id": entry.get("run_id", "legacy"),
            "batch_id": entry.get("batch_id", ""),
            "attempt_id": entry.get("attempt_id", ""),
            "workflow_root": entry.get("workflow_root", "workflow"),
            "approval_ids": _list(entry.get("approval_ids")),
            "approval_provenance": _list(entry.get("approval_provenance")),
            "applied_at": entry.get("applied_at", ""),
            "changes": changes,
        })
    return {
        "schema_version": data.get("schema_version"),
        "revision": data.get("revision"),
        "entry_count": len(entries),
        "change_count": change_count,
        "entries": entries,
    }, issues


def _incremental_report(data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    issues = _require_fields(data, {
        "schema_version": int, "revision": int, "latest_run_id": str, "runs": list,
    })
    runs = [run for run in _list(data.get("runs")) if isinstance(run, dict)]
    latest_id = data.get("latest_run_id", "")
    latest = next((run for run in runs if run.get("run_id") == latest_id), None)
    if latest_id and latest is None:
        issues.append(_issue("missing_latest_run", "latest_run_id", "latest_run_id 没有对应运行记录"))
    return {
        "schema_version": data.get("schema_version"),
        "revision": data.get("revision"),
        "latest_run_id": latest_id,
        "run_count": len(runs),
        "latest": latest,
        "runs": list(reversed(runs)),
    }, issues


def build_artifact_view(
    relative: str,
    content: str,
    parsed: Any,
    manifest: dict[str, Any] | None = None,
    parse_error: str = "",
) -> dict[str, Any]:
    """Return renderer identity, normalized view data, and non-authoritative hints."""
    kind = artifact_kind(relative)
    specialized = kind != "raw"
    if parse_error:
        return {
            "artifact_kind": kind,
            "specialized_view": specialized,
            "structure_issues": [_issue("parse_error", relative, parse_error)],
            "view_model": {},
        }
    data = _mapping(parsed)
    handlers = {
        "requirements_manifest": lambda: _requirements_manifest(data),
        "input_example_manifest": lambda: _input_example_manifest(data),
        "workflow_build": lambda: _workflow_build(data),
        "workflow_build_schema": lambda: _workflow_build(data, reference=True),
        "guidedoc_spec_schema": lambda: _guidedoc_schema(data),
        "smoke_tool_selection": lambda: _smoke_tool_selection(data),
        "mcp_baseline_evidence": lambda: _mcp_baseline(data),
        "workflow_implementation_plan": lambda: _implementation_plan(content, manifest or {}),
        "applied_changes": lambda: _applied_changes(data),
        "incremental_report": lambda: _incremental_report(data),
    }
    if kind == "raw":
        return {"artifact_kind": kind, "specialized_view": False, "structure_issues": [], "view_model": {}}
    view_model, issues = handlers[kind]()
    return {
        "artifact_kind": kind,
        "specialized_view": True,
        "structure_issues": issues,
        "view_model": view_model,
    }
