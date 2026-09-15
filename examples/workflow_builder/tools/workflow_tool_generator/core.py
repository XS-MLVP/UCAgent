# -*- coding: utf-8 -*-
"""Generate workflow tools and register them in config.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import stat
from typing import Any

import yaml

from .templates import BUILTIN_TOOLS, render_tool_from_spec


class ToolGenerationError(RuntimeError):
    """Structured tool generation error."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class ToolGenerationReport:
    workflow_root: str
    generated_tools: list[str] = field(default_factory=list)
    source_specs: list[str] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    refreshed_files: list[str] = field(default_factory=list)
    replaced_files: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    updated_config: bool = False
    warnings: list[str] = field(default_factory=list)

GENERATION_STATE_PATH = ".workflow/tool_generation_state.yaml"
EXISTING_POLICIES = {"create_only", "refresh_scaffold", "force_replace"}


def _safe_resolve(root: Path, rel_path: str) -> Path:
    path = Path(rel_path)
    if path.is_absolute() or ".." in path.parts or not rel_path:
        raise ToolGenerationError("TOOL-GEN-PATH-001", f"unsafe relative path: {rel_path}")
    resolved_root = root.resolve()
    target = (resolved_root / path).resolve()
    if target != resolved_root and not str(target).startswith(str(resolved_root) + "/"):
        raise ToolGenerationError("TOOL-GEN-PATH-002", f"path outside workflow root: {rel_path}")
    return target


def _prepare_write(root: Path, target: Path) -> None:
    current = target.parent
    while True:
        if current.exists():
            current.chmod(current.stat().st_mode | stat.S_IWUSR | stat.S_IXUSR)
        if current == root:
            break
        current = current.parent
    if target.exists():
        target.chmod(target.stat().st_mode | stat.S_IWUSR)


def _sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _load_generation_state(root: Path) -> dict[str, Any]:
    path = _safe_resolve(root, GENERATION_STATE_PATH)
    if not path.is_file():
        return {"version": 1, "files": {}}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ToolGenerationError(
            "TOOL-GEN-STATE-001",
            f"cannot read generation state: {exc}",
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("files", {}), dict):
        raise ToolGenerationError(
            "TOOL-GEN-STATE-001",
            f"invalid generation state: {GENERATION_STATE_PATH}",
        )
    data.setdefault("version", 1)
    data.setdefault("files", {})
    return data


def _save_generation_state(root: Path, state: dict[str, Any]) -> None:
    path = _safe_resolve(root, GENERATION_STATE_PATH)
    try:
        _prepare_write(root, path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(state, allow_unicode=True, sort_keys=True),
            encoding="utf-8",
        )
    except OSError as exc:
        raise ToolGenerationError(
            "TOOL-GEN-STATE-002",
            f"cannot update generation state: {exc}",
        ) from exc


def _record_test_baseline(state: dict[str, Any], spec: dict[str, Any]) -> None:
    """Freeze existing test cases while allowing later cases to be appended."""
    tool_name = spec["name"]
    baselines = state.setdefault("tool_tests", {})
    tool_baseline = baselines.setdefault(tool_name, {})
    tests = spec.get("tests", [])
    current: dict[str, str] = {}
    for test in tests:
        name = test.get("name") if isinstance(test, dict) else None
        if not isinstance(name, str) or not name or name in current:
            raise ToolGenerationError(
                "TOOL-GEN-TEST-001",
                f"tool {tool_name} has a missing or duplicate test name",
            )
        current[name] = _sha256_text(
            yaml.safe_dump(test, allow_unicode=True, sort_keys=True)
        )
    missing = sorted(set(tool_baseline) - set(current))
    changed = sorted(
        name
        for name, digest in tool_baseline.items()
        if name in current and digest != current[name]
    )
    if missing or changed:
        raise ToolGenerationError(
            "TOOL-GEN-TEST-002",
            f"tool {tool_name} changed its frozen test baseline; "
            f"missing={missing}, changed={changed}; append new tests instead",
        )
    tool_baseline.update(current)


def _normalize_existing_policy(existing_policy: str | None, overwrite: bool) -> str:
    if existing_policy is None or not str(existing_policy).strip():
        return "force_replace" if overwrite else "create_only"
    policy = str(existing_policy).strip().lower()
    if policy not in EXISTING_POLICIES:
        raise ToolGenerationError(
            "TOOL-GEN-POLICY-001",
            f"existing_policy must be one of {sorted(EXISTING_POLICIES)}; got {existing_policy}",
        )
    if overwrite and policy != "force_replace":
        raise ToolGenerationError(
            "TOOL-GEN-POLICY-002",
            "overwrite=true conflicts with existing_policy; remove overwrite or use force_replace",
        )
    return policy


def _write_generated_file(
    root: Path,
    rel_path: str,
    content: str,
    policy: str,
    report: ToolGenerationReport,
    state: dict[str, Any],
) -> None:
    target = _safe_resolve(root, rel_path)
    files = state.setdefault("files", {})
    previous = files.get(rel_path, {}) if isinstance(files.get(rel_path), dict) else {}
    previous_hash = previous.get("generated_sha256")
    existed = target.exists()
    if existed:
        try:
            current_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError as exc:
            raise ToolGenerationError(
                "TOOL-GEN-WRITE-001",
                f"cannot inspect {rel_path}: {exc}",
            ) from exc
        if policy == "create_only":
            report.skipped_files.append(rel_path)
            return
        if policy == "refresh_scaffold" and (
            not isinstance(previous_hash, str) or current_hash != previous_hash
        ):
            report.conflicts.append(rel_path)
            raise ToolGenerationError(
                "TOOL-GEN-CONFLICT-001",
                f"refusing to replace modified or untracked implementation: {rel_path}; "
                "use create_only to preserve it or force_replace only after explicit review",
            )
    try:
        _prepare_write(root, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise ToolGenerationError("TOOL-GEN-WRITE-001", f"cannot write {rel_path}: {exc}") from exc
    files[rel_path] = {"generated_sha256": _sha256_text(content)}
    if not existed:
        report.created_files.append(rel_path)
    elif policy == "refresh_scaffold":
        report.refreshed_files.append(rel_path)
    else:
        report.replaced_files.append(rel_path)


def _load_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ToolGenerationError("TOOL-GEN-CFG-001", f"config.yaml not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ToolGenerationError("TOOL-GEN-CFG-002", f"config.yaml parse failed: {exc}") from exc
    if not isinstance(data, dict):
        raise ToolGenerationError("TOOL-GEN-CFG-003", "config.yaml top-level must be mapping")
    return data


def _dump_config(path: Path, data: dict[str, Any]) -> None:
    try:
        _prepare_write(path.parent, path)
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, indent=2), encoding="utf-8")
    except OSError as exc:
        raise ToolGenerationError("TOOL-GEN-WRITE-002", f"cannot update config: {exc}") from exc


def _relative_to_root(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ToolGenerationError("TOOL-GEN-PATH-003", f"path outside workflow root: {path}") from exc


def _resolve_existing_under_root(root: Path, path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        target = path.resolve()
        _relative_to_root(root, target)
        return target
    return _safe_resolve(root, path_text)


def _load_tool_spec(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ToolGenerationError("TOOL-GEN-SPEC-001", f"tool_spec not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ToolGenerationError("TOOL-GEN-SPEC-002", f"tool_spec parse failed: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ToolGenerationError("TOOL-GEN-SPEC-003", f"tool_spec top-level must be mapping: {path}")
    return data


def _validate_tool_spec(spec: dict[str, Any], spec_path: Path) -> None:
    name = spec.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ToolGenerationError("TOOL-GEN-SPEC-004", f"tool_spec missing name: {spec_path}")
    entry = spec.get("entry")
    if not isinstance(entry, dict):
        raise ToolGenerationError("TOOL-GEN-SPEC-005", f"tool_spec missing entry: {spec_path}")
    for key in ("file", "class_name", "method"):
        if not isinstance(entry.get(key), str) or not entry[key].strip():
            raise ToolGenerationError("TOOL-GEN-SPEC-006", f"tool_spec missing entry.{key}: {spec_path}")
    if not entry["file"].startswith("tools/"):
        raise ToolGenerationError("TOOL-GEN-SPEC-007", f"entry.file must be under tools/: {entry['file']}")
    if not isinstance(spec.get("inputs"), list):
        raise ToolGenerationError("TOOL-GEN-SPEC-008", f"tool_spec inputs must be list: {spec_path}")
    outputs = spec.get("outputs")
    if not isinstance(outputs, dict):
        raise ToolGenerationError("TOOL-GEN-SPEC-009", f"tool_spec outputs must be mapping: {spec_path}")
    required_keys = outputs.get("required_keys", [])
    missing = [key for key in ("ok", "data", "errors", "warnings", "meta") if key not in required_keys]
    if missing:
        raise ToolGenerationError("TOOL-GEN-SPEC-010", f"tool_spec outputs.required_keys missing: {', '.join(missing)}")
    if not isinstance(spec.get("tests"), list) or not spec["tests"]:
        raise ToolGenerationError("TOOL-GEN-SPEC-011", f"tool_spec tests must be non-empty list: {spec_path}")


def _tool_record_from_spec(root: Path, spec_path: Path, spec: dict[str, Any]) -> dict[str, Any]:
    entry = spec["entry"]
    tool_path = entry["file"]
    _safe_resolve(root, tool_path)
    return {
        "name": spec["name"],
        "spec": _relative_to_root(root, spec_path),
        "file": tool_path,
        "enabled": True,
    }


def _register_tool_records(root: Path, records: list[dict[str, Any]], report: ToolGenerationReport) -> None:
    config_path = root / "config.yaml"
    config = _load_config(config_path)
    tools = config.get("tools")
    if tools is None:
        tools = {}
        config["tools"] = tools
    if isinstance(tools, list):
        generated_tools = tools
    elif isinstance(tools, dict):
        generated_tools = tools.setdefault("GeneratedTools", [])
    else:
        raise ToolGenerationError("TOOL-GEN-CFG-004", "config.tools must be a list or mapping for tool registration")
    if not isinstance(generated_tools, list):
        raise ToolGenerationError("TOOL-GEN-CFG-005", "config.tools.GeneratedTools must be a list")

    by_name: dict[str, dict[str, Any]] = {
        item.get("name"): item for item in generated_tools if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    changed = False
    for expected in records:
        tool_name = expected["name"]
        existing = by_name.get(tool_name)
        if existing is None:
            generated_tools.append(expected)
            changed = True
        else:
            for key, value in expected.items():
                if existing.get(key) != value:
                    existing[key] = value
                    changed = True
    if changed:
        _dump_config(config_path, config)
        report.updated_config = True


def _register_tools(root: Path, tool_names: list[str], report: ToolGenerationReport) -> None:
    records = []
    for tool_name in tool_names:
        template = BUILTIN_TOOLS[tool_name]
        records.append(
            {
                "name": tool_name,
                "spec": template["spec_path"],
                "file": template["tool_path"],
                "enabled": True,
            }
        )
    _register_tool_records(root, records, report)


def generate_tools(
    workflow_root: str | Path,
    tool_names: list[str] | None = None,
    overwrite: bool = False,
    existing_policy: str | None = None,
    update_config: bool = True,
) -> ToolGenerationReport:
    """Generate built-in tool specs/code into an existing workflow root."""
    root = Path(workflow_root).resolve()
    if not root.is_dir():
        raise ToolGenerationError("TOOL-GEN-ROOT-001", f"workflow root not found: {root}")
    selected = tool_names or list(BUILTIN_TOOLS)
    unknown = [name for name in selected if name not in BUILTIN_TOOLS]
    if unknown:
        raise ToolGenerationError("TOOL-GEN-NAME-001", "unknown built-in tool(s): " + ", ".join(unknown))

    policy = _normalize_existing_policy(existing_policy, overwrite)
    report = ToolGenerationReport(workflow_root=str(root))
    if overwrite:
        report.warnings.append(
            "overwrite is deprecated; use existing_policy='force_replace' after explicit review"
        )
    state = _load_generation_state(root)
    for tool_name in selected:
        template = BUILTIN_TOOLS[tool_name]
        _write_generated_file(root, template["spec_path"], template["spec"], policy, report, state)
        _write_generated_file(root, template["tool_path"], template["tool"], policy, report, state)
        report.generated_tools.append(tool_name)

    _save_generation_state(root, state)
    if update_config:
        _register_tools(root, selected, report)
    return report


def generate_tools_from_specs(
    workflow_root: str | Path,
    spec_paths: list[str],
    overwrite: bool = False,
    existing_policy: str | None = None,
    update_config: bool = True,
) -> ToolGenerationReport:
    """Generate tool implementations from existing tool_spec.yaml files."""
    root = Path(workflow_root).resolve()
    if not root.is_dir():
        raise ToolGenerationError("TOOL-GEN-ROOT-001", f"workflow root not found: {root}")
    if not spec_paths:
        raise ToolGenerationError("TOOL-GEN-SPEC-012", "spec_paths cannot be empty")

    policy = _normalize_existing_policy(existing_policy, overwrite)
    report = ToolGenerationReport(workflow_root=str(root))
    if overwrite:
        report.warnings.append(
            "overwrite is deprecated; use existing_policy='force_replace' after explicit review"
        )
    state = _load_generation_state(root)
    records: list[dict[str, Any]] = []
    for spec_path_text in spec_paths:
        spec_path = _resolve_existing_under_root(root, spec_path_text)
        spec = _load_tool_spec(spec_path)
        _validate_tool_spec(spec, spec_path)
        _record_test_baseline(state, spec)
        record = _tool_record_from_spec(root, spec_path, spec)
        code = render_tool_from_spec(spec)
        _write_generated_file(root, record["file"], code, policy, report, state)
        report.generated_tools.append(record["name"])
        report.source_specs.append(record["spec"])
        records.append(record)

    _save_generation_state(root, state)
    if update_config:
        _register_tool_records(root, records, report)
    return report
