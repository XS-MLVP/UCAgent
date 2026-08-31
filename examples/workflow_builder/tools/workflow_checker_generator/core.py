# -*- coding: utf-8 -*-
"""Generate UCAgent checker implementations from constrained checker specs."""

from __future__ import annotations

import ast
import json
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .templates import render_checker_from_spec


class CheckerGenerationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class CheckerGenerationReport:
    workflow_root: str
    generated_checkers: list[str] = field(default_factory=list)
    source_specs: list[str] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    generated_test_files: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    updated_config: bool = False


def _safe_resolve(root: Path, rel_path: str) -> Path:
    path = Path(rel_path)
    if path.is_absolute() or ".." in path.parts or not rel_path:
        raise CheckerGenerationError("CHECKER-GEN-PATH-001", f"unsafe relative path: {rel_path}")
    resolved_root = root.resolve()
    target = (resolved_root / path).resolve()
    if target != resolved_root and not str(target).startswith(str(resolved_root) + "/"):
        raise CheckerGenerationError("CHECKER-GEN-PATH-002", f"path outside workflow root: {rel_path}")
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


def _write_text(root: Path, target: Path, content: str) -> None:
    try:
        _prepare_write(root, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise CheckerGenerationError("CHECKER-GEN-WRITE-001", f"cannot write {target}: {exc}") from exc


def _load_yaml(path: Path, code: str) -> dict[str, Any]:
    if not path.is_file():
        raise CheckerGenerationError(code, f"file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CheckerGenerationError(code, f"YAML parse failed: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CheckerGenerationError(code, f"top-level must be mapping: {path}")
    return data


def _validate_spec(spec: dict[str, Any], path: Path) -> None:
    if not isinstance(spec.get("name"), str) or not spec["name"].strip():
        raise CheckerGenerationError("CHECKER-GEN-SPEC-001", f"missing name: {path}")
    entry = spec.get("entry")
    if not isinstance(entry, dict):
        raise CheckerGenerationError("CHECKER-GEN-SPEC-002", f"missing entry: {path}")
    for key in ("file", "class_name", "method"):
        if not isinstance(entry.get(key), str) or not entry[key].strip():
            raise CheckerGenerationError("CHECKER-GEN-SPEC-003", f"missing entry.{key}: {path}")
    if not entry["file"].startswith("checkers/"):
        raise CheckerGenerationError("CHECKER-GEN-SPEC-004", f"entry.file must be under checkers/: {entry['file']}")
    source = spec.get("source")
    rules = spec.get("rules")
    if source is not None:
        _validate_inline_source(source, entry, path)
    else:
        if not isinstance(rules, dict) or rules.get("type") not in {
            "json_required_keys",
            "json_numeric_range",
            "file_exists",
            "command_exit_code",
        }:
            raise CheckerGenerationError("CHECKER-GEN-SPEC-005", f"unsupported rules.type: {rules.get('type') if isinstance(rules, dict) else None}")
        rule_type = rules["type"]
        if rule_type == "json_required_keys" and (not isinstance(rules.get("required_keys"), list) or not rules["required_keys"]):
            raise CheckerGenerationError("CHECKER-GEN-SPEC-006", "rules.required_keys must be a non-empty list")
        if rule_type == "json_numeric_range":
            if not isinstance(rules.get("field"), str) or not rules["field"]:
                raise CheckerGenerationError("CHECKER-GEN-SPEC-006", "rules.field must be a non-empty string")
            if not isinstance(rules.get("minimum"), (int, float)) or not isinstance(rules.get("maximum"), (int, float)):
                raise CheckerGenerationError("CHECKER-GEN-SPEC-006", "rules.minimum and rules.maximum must be numeric")
            if rules["minimum"] > rules["maximum"]:
                raise CheckerGenerationError("CHECKER-GEN-SPEC-006", "rules.minimum cannot exceed rules.maximum")
        if rule_type == "command_exit_code":
            allowed = rules.get("allowed_commands")
            if not isinstance(allowed, list) or not allowed or not all(isinstance(item, str) and item for item in allowed):
                raise CheckerGenerationError("CHECKER-GEN-SPEC-006", "rules.allowed_commands must be a non-empty string list")
    tests = spec.get("tests")
    if not spec.get("auto_tests") and (not isinstance(tests, list) or not tests):
        raise CheckerGenerationError("CHECKER-GEN-SPEC-007", "tests must be non-empty unless auto_tests=true")
    if tests is not None and not isinstance(tests, list):
        raise CheckerGenerationError("CHECKER-GEN-SPEC-007", "tests must be a list")
    if source is not None:
        outcomes = {
            test.get("expected_pass")
            for test in tests or []
            if isinstance(test, dict) and isinstance(test.get("expected_pass"), bool)
        }
        if outcomes != {True, False}:
            raise CheckerGenerationError(
                "CHECKER-GEN-SPEC-010",
                "inline-source checker tests must include at least one PASS and one FAIL case",
            )
        fixtures = spec.get("fixtures")
        if not isinstance(fixtures, list) or not fixtures:
            raise CheckerGenerationError("CHECKER-GEN-SPEC-011", "inline-source checker fixtures must be non-empty")
        for fixture in fixtures:
            if not isinstance(fixture, dict) or not isinstance(fixture.get("path"), str) or not isinstance(fixture.get("content"), str):
                raise CheckerGenerationError("CHECKER-GEN-SPEC-011", "each fixture requires string path and content")
            prefix = f".workflow/checker_tests/cases/{spec['name']}/"
            if not fixture["path"].startswith(prefix):
                raise CheckerGenerationError("CHECKER-GEN-SPEC-011", f"fixture path must be under {prefix}")
            _safe_resolve(Path("/tmp/checker-spec-validation"), fixture["path"])


def _validate_inline_source(source: Any, entry: dict[str, Any], path: Path) -> None:
    if not isinstance(source, str) or not source.strip():
        raise CheckerGenerationError("CHECKER-GEN-SOURCE-001", f"source must be a non-empty string: {path}")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise CheckerGenerationError("CHECKER-GEN-SOURCE-002", f"invalid Python source in {path}: {exc}") from exc
    class_node = next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == entry["class_name"]),
        None,
    )
    if class_node is None or not any(
        (isinstance(base, ast.Name) and base.id == "Checker")
        or (isinstance(base, ast.Attribute) and base.attr == "Checker")
        for base in class_node.bases
    ):
        raise CheckerGenerationError(
            "CHECKER-GEN-SOURCE-003",
            f"{entry['class_name']} must exist and inherit Checker",
        )
    method = next(
        (
            node
            for node in class_node.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == entry["method"]
        ),
        None,
    )
    if method is None or not ast.get_docstring(method):
        raise CheckerGenerationError(
            "CHECKER-GEN-SOURCE-004",
            f"{entry['class_name']}.{entry['method']} must exist and have a docstring",
        )


def _auto_test_path(spec: dict[str, Any], filename: str) -> str:
    return f".workflow/checker_tests/cases/{spec['name']}/{filename}"


def _materialize_auto_tests(root: Path, spec_path: Path, spec: dict[str, Any], report: CheckerGenerationReport) -> dict[str, Any]:
    if not spec.get("auto_tests"):
        return spec
    rules = spec["rules"]
    rule_type = rules["type"]
    tests: list[dict[str, Any]]
    fixtures: dict[str, str] = {}
    if rule_type == "json_required_keys":
        valid_path = _auto_test_path(spec, "valid.json")
        invalid_path = _auto_test_path(spec, "invalid.json")
        keys = rules["required_keys"]
        fixtures[valid_path] = json.dumps({key: 0 for key in keys}, indent=2) + "\n"
        fixtures[invalid_path] = json.dumps({key: 0 for key in keys[:-1]}, indent=2) + "\n"
        tests = [
            {"name": "auto_valid_required_keys", "args": {"path": valid_path}, "expected_pass": True},
            {"name": "auto_missing_required_key", "args": {"path": invalid_path}, "expected_pass": False},
        ]
    elif rule_type == "json_numeric_range":
        valid_path = _auto_test_path(spec, "valid.json")
        invalid_path = _auto_test_path(spec, "invalid.json")
        fixtures[valid_path] = json.dumps({rules["field"]: rules["minimum"]}, indent=2) + "\n"
        fixtures[invalid_path] = json.dumps({rules["field"]: rules["maximum"] + 1}, indent=2) + "\n"
        tests = [
            {"name": "auto_value_in_range", "args": {"path": valid_path}, "expected_pass": True},
            {"name": "auto_value_out_of_range", "args": {"path": invalid_path}, "expected_pass": False},
        ]
    elif rule_type == "file_exists":
        present_path = _auto_test_path(spec, "present.txt")
        missing_path = _auto_test_path(spec, "missing.txt")
        fixtures[present_path] = "generated checker fixture\n"
        missing_target = _safe_resolve(root, missing_path)
        if missing_target.exists():
            missing_target.unlink()
        tests = [
            {"name": "auto_file_present", "args": {"path": present_path}, "expected_pass": True},
            {"name": "auto_file_missing", "args": {"path": missing_path}, "expected_pass": False},
        ]
    else:
        command = rules["allowed_commands"][0]
        tests = [
            {"name": "auto_expected_exit_code", "args": {"command": [command, "-c", "raise SystemExit(0)"]}, "expected_pass": True},
            {"name": "auto_unexpected_exit_code", "args": {"command": [command, "-c", "raise SystemExit(1)"]}, "expected_pass": False},
        ]
    for rel_path, content in fixtures.items():
        _write(root, rel_path, content, True, report)
        report.generated_test_files.append(rel_path)
    spec["tests"] = tests
    _write_text(root, spec_path, yaml.safe_dump(spec, allow_unicode=True, sort_keys=False, indent=2))
    return spec


def _materialize_explicit_fixtures(
    root: Path,
    spec: dict[str, Any],
    overwrite: bool,
    report: CheckerGenerationReport,
) -> None:
    for fixture in spec.get("fixtures", []):
        _write(root, fixture["path"], fixture["content"], overwrite, report)
        report.generated_test_files.append(fixture["path"])


def _write(root: Path, rel_path: str, content: str, overwrite: bool, report: CheckerGenerationReport) -> None:
    target = _safe_resolve(root, rel_path)
    if target.exists() and not overwrite:
        report.skipped_files.append(rel_path)
        return
    _write_text(root, target, content)
    report.created_files.append(rel_path)


def _register_checker(root: Path, spec_path: Path, spec: dict[str, Any], report: CheckerGenerationReport) -> None:
    config_path = root / "config.yaml"
    config = _load_yaml(config_path, "CHECKER-GEN-CFG-001")
    stages = config.get("stage")
    if not isinstance(stages, list) or not stages:
        raise CheckerGenerationError("CHECKER-GEN-CFG-002", "config.stage must be a non-empty list")
    stage_name = spec.get("register", {}).get("stage", stages[0].get("name"))
    target_stage = next((stage for stage in stages if isinstance(stage, dict) and stage.get("name") == stage_name), None)
    if target_stage is None:
        raise CheckerGenerationError("CHECKER-GEN-CFG-003", f"registration stage not found: {stage_name}")
    checker_list = target_stage.setdefault("checker", [])
    if not isinstance(checker_list, list):
        raise CheckerGenerationError("CHECKER-GEN-CFG-004", "stage.checker must be a list")
    args = spec.get("register", {}).get("args", {})
    expected = {
        "name": spec["name"],
        "clss": f"{Path(spec['entry']['file']).with_suffix('').as_posix().replace('/', '.')}.{spec['entry']['class_name']}",
        "args": args if isinstance(args, dict) else {},
    }
    existing = next((item for item in checker_list if isinstance(item, dict) and item.get("name") == spec["name"]), None)
    if existing is None:
        checker_list.append(expected)
    else:
        existing.update(expected)
    _write_text(root, config_path, yaml.safe_dump(config, allow_unicode=True, sort_keys=False, indent=2))
    report.updated_config = True


def generate_checkers_from_specs(
    workflow_root: str | Path,
    spec_paths: list[str],
    overwrite: bool = False,
    update_config: bool = True,
) -> CheckerGenerationReport:
    root = Path(workflow_root).resolve()
    if not root.is_dir():
        raise CheckerGenerationError("CHECKER-GEN-ROOT-001", f"workflow root not found: {root}")
    if not spec_paths:
        raise CheckerGenerationError("CHECKER-GEN-SPEC-008", "spec_paths cannot be empty")

    report = CheckerGenerationReport(workflow_root=str(root))
    for spec_text in spec_paths:
        spec_path = _safe_resolve(root, spec_text)
        spec = _load_yaml(spec_path, "CHECKER-GEN-SPEC-009")
        _validate_spec(spec, spec_path)
        spec = _materialize_auto_tests(root, spec_path, spec, report)
        _materialize_explicit_fixtures(root, spec, overwrite, report)
        checker_source = spec["source"] if "source" in spec else render_checker_from_spec(spec)
        if not checker_source.endswith("\n"):
            checker_source += "\n"
        _write(root, spec["entry"]["file"], checker_source, overwrite, report)
        report.generated_checkers.append(spec["name"])
        report.source_specs.append(spec_path.relative_to(root).as_posix())
        if update_config:
            _register_checker(root, spec_path, spec, report)
    return report
