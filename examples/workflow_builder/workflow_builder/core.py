# -*- coding: utf-8 -*-
"""Build minimal UCAgent workflow skeletons from a YAML build plan."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .mcp_templates import (
    MCP_TOOL_ADAPTERS as SPEC_DRIVEN_MCP_TOOL_ADAPTERS,
    MCP_TOOL_TEST_RUNNER as SPEC_DRIVEN_MCP_TOOL_TEST_RUNNER,
)


class WorkflowBuildError(RuntimeError):
    """Structured workflow builder error."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class BuildReport:
    workflow_name: str = ""
    version: str = ""
    root_path: str = ""
    build_config_path: str = ""
    created_dirs: list[str] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


REQUIRED_FIELDS: dict[str, type] = {
    "workflow.name": str,
    "workflow.description": str,
    "workflow.version": str,
    "root.path": str,
    "root.overwrite": bool,
    "runtime_contract": dict,
    "directories.public": list,
    "directories.internal": list,
    "files.public": list,
    "files.internal": list,
    "makefile.targets": list,
    "config": dict,
    "workflow_spec": dict,
    "acceptance": dict,
}


REQUIRED_CONFIG_FIELDS = [
    "workflow",
    "paths",
    "model",
    "loop_settings",
    "tools",
    "checkers",
    "guide_docs",
]


REQUIRED_GUIDEDOC_SECTIONS = [
    "# 工作流目标",
    "# 输入输出",
    "# 目录结构",
    "# 运行方式",
    "# 工具说明",
    "# Checker说明",
    "# 异常处理",
]


def load_yaml_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.is_file():
        raise WorkflowBuildError("BUILD-CFG-001", f"workflow_build.yaml 不存在: {config_path}")
    try:
        with config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise WorkflowBuildError("BUILD-CFG-001", f"workflow_build.yaml 无法解析: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkflowBuildError("BUILD-CFG-003", "workflow_build.yaml 顶层必须是 YAML mapping")
    return data


def get_nested(data: dict[str, Any], dotted_key: str) -> Any:
    cur: Any = data
    for part in dotted_key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise WorkflowBuildError("BUILD-CFG-002", f"缺少必需字段 {dotted_key}")
        cur = cur[part]
    return cur


def validate_build_config(data: dict[str, Any]) -> None:
    for key, expected_type in REQUIRED_FIELDS.items():
        value = get_nested(data, key)
        if not isinstance(value, expected_type):
            raise WorkflowBuildError(
                "BUILD-CFG-003",
                f"字段类型错误 {key}: 期望 {expected_type.__name__}, 实际 {type(value).__name__}",
            )

    if not data["workflow"]["name"].strip():
        raise WorkflowBuildError("BUILD-CFG-002", "缺少必需字段 workflow.name")
    if not data["root"]["path"].strip():
        raise WorkflowBuildError("BUILD-CFG-004", "root.path 不合法")
    if not data["makefile"]["targets"]:
        raise WorkflowBuildError("BUILD-CFG-005", "makefile.targets 为空")
    public_dirs = data["directories"]["public"]
    internal_dirs = data["directories"]["internal"]
    if "tmp" not in public_dirs:
        raise WorkflowBuildError("BUILD-CFG-007", "directories.public 必须包含根级 tmp")
    if ".workflow/temp" in public_dirs or ".workflow/temp" in internal_dirs:
        raise WorkflowBuildError(
            "BUILD-CFG-007",
            "临时文件只能使用根级 tmp，禁止声明 .workflow/temp",
        )
    contract = data["runtime_contract"]
    required_input = contract.get("required_input")
    if not isinstance(required_input, list) or not required_input:
        raise WorkflowBuildError(
            "BUILD-CFG-006",
            "runtime_contract.required_input 必须是非空列表",
        )
    for item in required_input:
        path = item.get("path") if isinstance(item, dict) else item
        if not isinstance(path, str) or not path.strip():
            raise WorkflowBuildError(
                "BUILD-CFG-006",
                "runtime_contract.required_input 每项必须是路径字符串或包含 path 的 mapping",
            )
        check_relative_path(path, "BUILD-CFG")
    validate_workflow_spec_contract(data)


def validate_workflow_spec_contract(data: dict[str, Any]) -> None:
    """Require a complete, authoritative stage/checker plan before construction."""
    spec = data["workflow_spec"]
    checkers = spec.get("checkers")
    stages = spec.get("stages")
    if not isinstance(checkers, list) or not checkers:
        raise WorkflowBuildError("BUILD-SPEC-001", "workflow_spec.checkers 必须是非空列表")
    if not isinstance(stages, list) or not stages:
        raise WorkflowBuildError("BUILD-SPEC-002", "workflow_spec.stages 必须是非空列表")

    shape_errors: list[str] = []
    for index, checker in enumerate(checkers):
        location = f"workflow_spec.checkers[{index}]"
        if not isinstance(checker, dict):
            shape_errors.append(f"{location} 必须是 mapping")
            continue
        if not isinstance(checker.get("name"), str) or not checker["name"].strip():
            shape_errors.append(f"{location}.name 缺失")
        if (
            not isinstance(checker.get("description"), str)
            or not checker["description"].strip()
        ):
            shape_errors.append(f"{location}.description 缺失")
        entry = checker.get("entry")
        if not isinstance(entry, dict):
            shape_errors.append(f"{location}.entry 必须是 mapping")
            continue
        for key in ("file", "class_name", "method"):
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                shape_errors.append(f"{location}.entry.{key} 缺失")
    if shape_errors:
        raise WorkflowBuildError(
            "BUILD-SPEC-003",
            "Checker 中心定义存在结构缺项，请一次修复全部条目: "
            + "; ".join(shape_errors),
        )

    checker_names: set[str] = set()
    checker_files: set[str] = set()
    checker_classes: set[str] = set()
    all_fixture_paths: set[str] = set()
    for index, checker in enumerate(checkers):
        location = f"workflow_spec.checkers[{index}]"
        if not isinstance(checker, dict):
            raise WorkflowBuildError("BUILD-SPEC-003", f"{location} 必须是 mapping")
        name = checker.get("name")
        description = checker.get("description")
        entry = checker.get("entry")
        source = checker.get("source")
        fixtures = checker.get("fixtures")
        tests = checker.get("tests")
        if not isinstance(name, str) or not name.strip() or name in checker_names:
            raise WorkflowBuildError("BUILD-SPEC-003", f"{location}.name 缺失或重复")
        if not isinstance(description, str) or not description.strip():
            raise WorkflowBuildError("BUILD-SPEC-003", f"{location}.description 必须详细说明检查内容")
        if not isinstance(entry, dict):
            raise WorkflowBuildError("BUILD-SPEC-003", f"{location}.entry 必须是 mapping")
        for key in ("file", "class_name", "method"):
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                raise WorkflowBuildError("BUILD-SPEC-003", f"{location}.entry.{key} 缺失")
        check_relative_path(entry["file"], "BUILD-SPEC")
        if (
            not entry["file"].startswith("checkers/")
            or entry["file"] in checker_files
            or entry["class_name"] in checker_classes
        ):
            raise WorkflowBuildError(
                "BUILD-SPEC-004",
                f"{location}.entry.file 必须位于 checkers/，且 file/class_name 均不得重复",
            )
        if entry["method"] != "do_check":
            raise WorkflowBuildError("BUILD-SPEC-004", f"{location}.entry.method 必须是 do_check")
        if not isinstance(source, str) or not source.strip():
            raise WorkflowBuildError("BUILD-SPEC-005", f"{location}.source 必须包含完整 Python Checker 源码")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            raise WorkflowBuildError("BUILD-SPEC-005", f"{location}.source Python 语法错误: {exc}") from exc
        class_node = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == entry["class_name"]
            ),
            None,
        )
        inherits_checker = class_node is not None and any(
            (isinstance(base, ast.Name) and base.id == "Checker")
            or (isinstance(base, ast.Attribute) and base.attr == "Checker")
            for base in class_node.bases
        )
        method_node = next(
            (
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == entry["method"]
            ),
            None,
        ) if class_node else None
        if not inherits_checker or method_node is None or not ast.get_docstring(method_node):
            raise WorkflowBuildError(
                "BUILD-SPEC-005",
                f"{location}.source 必须定义继承 Checker 且 do_check 含方法级 docstring 的入口类",
            )
        if not isinstance(fixtures, list) or not fixtures:
            raise WorkflowBuildError("BUILD-SPEC-006", f"{location}.fixtures 必须包含显式测试夹具")
        fixture_prefix = f".workflow/checker_tests/cases/{name}/"
        fixture_paths: set[str] = set()
        for fixture in fixtures:
            if not isinstance(fixture, dict) or not isinstance(fixture.get("path"), str) or not isinstance(fixture.get("content"), str):
                raise WorkflowBuildError("BUILD-SPEC-006", f"{location}.fixtures 每项必须包含 path 与 content")
            check_relative_path(fixture["path"], "BUILD-SPEC")
            if (
                not fixture["path"].startswith(fixture_prefix)
                or fixture["path"] in fixture_paths
                or fixture["path"] in all_fixture_paths
            ):
                raise WorkflowBuildError("BUILD-SPEC-006", f"{location} fixture 必须唯一且位于 {fixture_prefix}")
            fixture_paths.add(fixture["path"])
            all_fixture_paths.add(fixture["path"])
        if not isinstance(tests, list) or not tests:
            raise WorkflowBuildError("BUILD-SPEC-007", f"{location}.tests 必须是非空列表")
        outcomes = {
            test.get("expected_pass")
            for test in tests
            if isinstance(test, dict) and isinstance(test.get("expected_pass"), bool)
        }
        if outcomes != {True, False}:
            raise WorkflowBuildError("BUILD-SPEC-007", f"{location}.tests 至少包含一个 PASS 和一个 FAIL")
        for test in tests:
            if (
                not isinstance(test, dict)
                or not isinstance(test.get("name"), str)
                or not isinstance(test.get("args"), dict)
                or not isinstance(test.get("expected_pass"), bool)
            ):
                raise WorkflowBuildError("BUILD-SPEC-007", f"{location}.tests 每项必须包含 name、args 和 expected_pass")
        checker_names.add(name)
        checker_files.add(entry["file"])
        checker_classes.add(entry["class_name"])

    declared_files = {
        str(item["path"]).removeprefix("./")
        for group in ("public", "internal")
        for item in data["files"][group]
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    declared_dirs = {
        str(path).removeprefix("./").rstrip("/")
        for group in ("public", "internal")
        for path in data["directories"][group]
        if isinstance(path, str)
    }
    runtime_input_files: set[str] = set()
    runtime_input_dirs: set[str] = set()
    for input_path, input_kind, _ in _runtime_required_inputs(data):
        target = f"input/{{DUT}}/{input_path}".removeprefix("./").rstrip("/")
        (runtime_input_files if input_kind == "file" else runtime_input_dirs).add(target)

    def normalize_stage_path(path: str) -> str:
        return path.removeprefix("./").rstrip("/")

    def require_concrete_file(path: str, location: str) -> str:
        normalized = normalize_stage_path(path)
        basename = Path(normalized).name
        known_extensionless_files = {"Makefile", "Dockerfile", "requirements"}
        if (
            path.endswith("/")
            or normalized in declared_dirs
            or normalized in runtime_input_dirs
            or (not Path(basename).suffix and basename not in known_extensionless_files)
        ):
            raise WorkflowBuildError(
                "BUILD-SPEC-013",
                (
                    f"{location} 必须声明具体文件，禁止声明目录或目录形状路径: {path}；"
                    "目录型成果应改用 manifest、summary 或 report 文件作为阶段证据"
                ),
            )
        return normalized

    stage_names: set[str] = set()
    bound_checkers: set[str] = set()
    earliest_output_stage: dict[str, int] = {}
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            continue
        for path in stage.get("output_files", []):
            if isinstance(path, str):
                normalized = require_concrete_file(
                    path,
                    f"workflow_spec.stages[{index}].output_files",
                )
                earliest_output_stage.setdefault(normalized, index)
    for index, stage in enumerate(stages):
        location = f"workflow_spec.stages[{index}]"
        if not isinstance(stage, dict):
            raise WorkflowBuildError("BUILD-SPEC-008", f"{location} 必须是 mapping")
        name = stage.get("name")
        if not isinstance(name, str) or not name.strip() or name in stage_names:
            raise WorkflowBuildError("BUILD-SPEC-008", f"{location}.name 缺失或重复")
        if not isinstance(stage.get("description"), str) or not stage["description"].strip():
            raise WorkflowBuildError("BUILD-SPEC-008", f"{location}.description 不能为空")
        for key in ("reference_files", "output_files", "checker"):
            if not isinstance(stage.get(key), list):
                raise WorkflowBuildError("BUILD-SPEC-009", f"{location}.{key} 必须是列表")
        if not stage["checker"]:
            raise WorkflowBuildError("BUILD-SPEC-009", f"{location}.checker 不得为空")
        for path in stage["reference_files"] + stage["output_files"]:
            check_relative_path(path, "BUILD-SPEC")
        for path in stage["reference_files"]:
            normalized = require_concrete_file(path, f"{location}.reference_files")
            producer_index = earliest_output_stage.get(normalized)
            guaranteed = (
                normalized in declared_files
                or normalized in runtime_input_files
                or (producer_index is not None and producer_index < index)
            )
            if not guaranteed:
                raise WorkflowBuildError(
                    "BUILD-SPEC-014",
                    (
                        f"{location}.reference_files 引用了无法保证存在的文件: {path}；"
                        "reference_files 只能引用固定交付文件、明确的用户输入文件，"
                        "或前序阶段已经声明的具体 output_files"
                    ),
                )
        for binding in stage["checker"]:
            if not isinstance(binding, dict) or binding.get("name") not in checker_names:
                raise WorkflowBuildError("BUILD-SPEC-010", f"{location}.checker 引用了未规划的 Checker")
            if not isinstance(binding.get("args", {}), dict):
                raise WorkflowBuildError("BUILD-SPEC-010", f"{location}.checker.args 必须是 mapping")
            for arg_name, arg_value in binding.get("args", {}).items():
                if (
                    isinstance(arg_value, str)
                    and any(token in str(arg_name).lower() for token in ("path", "file", "dir", "root"))
                ):
                    producer_index = earliest_output_stage.get(arg_value.rstrip("/"))
                    if producer_index is not None and producer_index > index:
                        raise WorkflowBuildError(
                            "BUILD-SPEC-012",
                            (
                                f"{location}.checker.{binding['name']}.{arg_name} "
                                f"引用未来阶段 {stages[producer_index].get('name')} 才生成的产物: "
                                f"{arg_value}"
                            ),
                        )
            bound_checkers.add(binding["name"])
        stage_names.add(name)
    unbound = sorted(checker_names - bound_checkers)
    if unbound:
        raise WorkflowBuildError("BUILD-SPEC-011", f"Checker 未绑定到任何阶段: {', '.join(unbound)}")


def _path_has_parent(path_text: str) -> bool:
    return ".." in Path(path_text).parts


def check_relative_path(path_text: str, code_prefix: str = "PATH") -> None:
    if not isinstance(path_text, str) or not path_text.strip():
        raise WorkflowBuildError(f"{code_prefix}-004", f"路径为空: {path_text!r}")
    path = Path(path_text)
    if path.is_absolute():
        raise WorkflowBuildError("PATH-001", f"不允许绝对路径: {path_text}")
    if _path_has_parent(path_text):
        raise WorkflowBuildError("PATH-002", f"不允许路径中出现 ..: {path_text}")
    if re.match(r"^\s*(?:\./+)?workflow/", path_text):
        raise WorkflowBuildError(
            f"{code_prefix}-012",
            f"不允许把父工作流路径前缀写入子工作流契约: {path_text}",
        )


def _resolve_under(base_dir: Path, rel_path: str) -> Path:
    check_relative_path(rel_path)
    base = base_dir.resolve()
    target = (base / rel_path).resolve()
    if target != base and not str(target).startswith(str(base) + os.sep):
        raise WorkflowBuildError("PATH-003", f"路径超出构建根目录: {rel_path}")
    return target


def check_path_safety(data: dict[str, Any], base_dir: str | Path) -> Path:
    root_path = data["root"]["path"]
    check_relative_path(root_path)
    root = _resolve_under(Path(base_dir), root_path)
    if root in [Path("/").resolve(), Path.home().resolve()]:
        raise WorkflowBuildError("PATH-004", f"危险目标目录: {root}")

    for dir_path in data["directories"]["public"] + data["directories"]["internal"]:
        _resolve_under(root, dir_path)

    for group_name in ("public", "internal"):
        for item in data["files"][group_name]:
            if not isinstance(item, dict) or "path" not in item:
                raise WorkflowBuildError("BUILD-CFG-003", f"files.{group_name} 项必须包含 path")
            _resolve_under(root, item["path"])

    if root.exists() and not data["root"]["overwrite"]:
        raise WorkflowBuildError("PATH-004", "目标目录已存在且 overwrite=false")
    return root


def create_directories(root: Path, data: dict[str, Any], report: BuildReport) -> None:
    all_dirs = ["."] + data["directories"]["public"] + data["directories"]["internal"]
    for rel_dir in all_dirs:
        path = root if rel_dir == "." else _resolve_under(root, rel_dir)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            report.created_dirs.append(rel_dir)


def write_file(root: Path, rel_path: str, content: str, overwrite: bool, report: BuildReport) -> None:
    path = _resolve_under(root, rel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        report.skipped_files.append(rel_path)
        return
    path.write_text(content, encoding="utf-8")
    report.created_files.append(rel_path)


def ensure_runtime_example(root: Path, data: dict[str, Any], overwrite: bool, report: BuildReport) -> None:
    """Materialize the declared input contract under input/<example_target>/."""
    contract = data.get("runtime_contract", {})
    target = str(contract.get("example_target", "example"))
    example_root = _resolve_under(root, f"input/{target}")
    example_root.mkdir(parents=True, exist_ok=True)
    readme = example_root / "README.md"
    if not readme.exists() or overwrite:
        readme.write_text(generate_input_example_readme(data), encoding="utf-8")
        report.created_files.append(f"input/{target}/README.md")
    for rel, kind, content in _runtime_required_inputs(data):
        path = _resolve_under(example_root, rel)
        if kind == "directory":
            path.mkdir(parents=True, exist_ok=True)
            marker = path / "README.md"
            if not marker.exists() or overwrite:
                marker.write_text(
                    f"# Example {rel}\n\nReplace or extend this directory with a realistic runnable fixture.\n",
                    encoding="utf-8",
                )
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not overwrite:
            continue
        if content:
            value = content
        elif path.suffix.lower() == ".json":
            value = "{}\n"
        elif path.suffix.lower() in (".yaml", ".yml"):
            value = "{}\n"
        else:
            value = (
                f"# Example {path.name}\n\n"
                "Replace this placeholder with a realistic runnable example derived from the workflow requirement.\n"
            )
        path.write_text(value, encoding="utf-8")
        report.created_files.append(f"input/{target}/{rel}")


def copy_input_example_tree(
    workspace_root: str | Path,
    workflow_root: str | Path,
    manifest_path: str | Path,
) -> list[str]:
    """Copy a declared input example tree byte-for-byte into the generated workflow."""
    workspace = Path(workspace_root).resolve()
    root = Path(workflow_root).resolve()
    manifest = load_yaml_config(Path(manifest_path))
    if str(manifest.get("copy_mode", "")).strip() != "copy_tree":
        return []

    source_text = str(manifest.get("source_dir", "")).strip()
    target_text = str(manifest.get("target_dir", "")).strip()
    if not source_text or target_text != "input/example":
        raise WorkflowBuildError(
            "BUILD-EXAMPLE-001",
            "copy_tree requires source_dir and target_dir=input/example",
        )
    source = _resolve_under(workspace, source_text)
    target = _resolve_under(root, target_text)
    if not source.is_dir():
        raise WorkflowBuildError("BUILD-EXAMPLE-002", f"example source directory not found: {source}")
    target.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for child in sorted(source.iterdir(), key=lambda item: item.name):
        destination = _resolve_under(target, child.name)
        if destination.is_dir():
            shutil.rmtree(destination)
        elif destination.exists():
            destination.unlink()
        if child.is_dir():
            shutil.copytree(child, destination, copy_function=shutil.copy2)
        elif child.is_file():
            shutil.copy2(child, destination)
        else:
            raise WorkflowBuildError(
                "BUILD-EXAMPLE-003",
                f"unsupported example source entry: {child}",
            )

    for source_file in sorted(path for path in source.rglob("*") if path.is_file()):
        relative = source_file.relative_to(source)
        destination = target / relative
        if not destination.is_file() or source_file.read_bytes() != destination.read_bytes():
            raise WorkflowBuildError(
                "BUILD-EXAMPLE-004",
                f"example copy verification failed: {relative.as_posix()}",
            )
        copied.append(relative.as_posix())
    return copied


def runtime_acceptance(data: dict[str, Any]) -> dict[str, Any]:
    acceptance = {
        key: list(value) if isinstance(value, list) else value
        for key, value in data["acceptance"].items()
    }
    files = acceptance.setdefault("required_public_files", [])
    dirs = acceptance.setdefault("required_public_dirs", [])
    target = str(data.get("runtime_contract", {}).get("example_target", "example"))
    for required in (
        "setup.py",
        "requirements.txt",
        "config/environment.schema.yaml",
        "Guide_Doc/environment_setup.md",
        "input/README.md",
        f"input/{target}/README.md",
        "docs/README.md",
        "docs/01快速启动.md",
        "docs/02输入输出.md",
        "docs/03步骤及检查.md",
        "docs/04开发者文档-tools.md",
        "docs/05开发者文档-checkers.md",
    ):
        if required not in files:
            files.append(required)
    for required in ("input", f"input/{target}", "output", "tmp"):
        if required not in dirs:
            dirs.append(required)
    for rel, kind, _ in _runtime_required_inputs(data):
        target_path = f"input/{target}/{rel}"
        collection = dirs if kind == "directory" else files
        if target_path not in collection:
            collection.append(target_path)
    return acceptance


def yaml_dump(data: Any) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, indent=2)


def _runtime_required_inputs(data: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Return required input paths as (path, kind, example_content)."""
    result = []
    for item in data.get("runtime_contract", {}).get("required_input", []):
        if isinstance(item, dict):
            path = str(item.get("path", "")).strip()
            kind = str(item.get("type", "")).strip().lower()
            content = str(item.get("example_content", ""))
        else:
            path = str(item).strip()
            kind = ""
            content = ""
        if not kind:
            kind = "file" if Path(path).suffix else "directory"
        if kind not in ("file", "directory"):
            raise WorkflowBuildError(
                "BUILD-CFG-006",
                f"required_input.type 必须是 file 或 directory: {path}",
            )
        result.append((path, kind, content))
    return result


def generate_makefile(data: dict[str, Any]) -> str:
    python = data.get("makefile", {}).get("python", "$(UCAGENT_VENV)/bin/python")
    if python in ("python", "python3"):
        python = "$(UCAGENT_VENV)/bin/python"
    session = "ucagent_" + data["workflow"]["name"].replace("-", "_")
    contract = data.get("runtime_contract", {})
    example_target = contract.get("example_target", "example")
    required_inputs = _runtime_required_inputs(data)
    required_checks = "\n".join(
        (
            f'\t@test -d "input/$(TARGET)/{path}" || '
            f'(echo "missing input/$(TARGET)/{path}/" && exit 1)'
            if kind == "directory"
            else f'\t@test -f "input/$(TARGET)/{path}" || '
            f'(echo "missing input/$(TARGET)/{path}" && exit 1)'
        )
        for path, kind, _ in required_inputs
    )
    json_checks = "\n".join(
        f'\t@$(PYTHON) -m json.tool "input/$(TARGET)/{path}" >/dev/null'
        for path, kind, _ in required_inputs
        if kind == "file" and Path(path).suffix.lower() == ".json"
    )
    return f""".PHONY: help configure configure-check check_target prepare_input prepare_runtime check_input check_example check check_config check_inc_config check_layout check_docs check_tool_specs check_tools test_tools check_checker_specs check_checkers test_checkers check_package package test_mcp run run_inc run_tui run_inc_tui smoke session tmux clean

# BEGIN WORKFLOW ENVIRONMENT (generated by setup.py)
UCAGENT_HOME ?= $(error UCAGENT_HOME is required)
UCAGENT_VENV ?= $(error UCAGENT_VENV is required)
PYTHON ?= {python}
MCP_SERVER_PORT ?= -1
# END WORKFLOW ENVIRONMENT (generated by setup.py)

UCAGENT ?= $(PYTHON) $(UCAGENT_HOME)/ucagent.py
OUT ?= output
TARGET ?=
SMOKE_TARGET ?= {example_target}
WORKFLOW_WORKSPACE ?= $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
RUNTIME_DUT := $(OUT)/.runtime_targets/$(TARGET)
SESSION ?= {session}
SETUP_SH ?= ./ucagent_setup.sh
UCAGENT_SETUP_CMD ?= . $(SETUP_SH) && ucagent_env && proxy_on
RUN_MSG ?= Continue current workflow until all stages complete. Write all output files under output/$(TARGET). The variable OUT is the output root (output/) and DUT is the target name ($(TARGET)); use {{OUT}}/{{DUT}} for output paths. Never reuse names or results from unrelated tasks.
SMOKE_MSG ?= Read README.md and Guide_Doc/overview.md, then set current stage journal, complete the only stage, and exit.
INC_MSG ?= Resume from saved state and continue until all stages complete.
GENERATED_TOOLS_CMD := $(PYTHON) -c "from tools.mcp_adapters import ADAPTER_CLASS_NAMES; print(','.join('tools.mcp_adapters.' + name for name in ADAPTER_CLASS_NAMES))"

help:
\t@echo "Available targets:"
\t@echo "  make configure         - Interactively configure this machine"
\t@echo "  make configure-check   - Validate environment configuration"
\t@echo "  make check_target      - Validate TARGET is set and safe"
\t@echo "  make prepare_input     - Validate input/<TARGET> required files"
\t@echo "  make prepare_runtime   - Prepare the hidden UCAgent runtime package"
\t@echo "  make check_input       - Validate one target input"
\t@echo "  make check_example     - Validate the bundled runnable example"
\t@echo "  make check             - Run all workflow checks"
\t@echo "  make check_config      - Check config.yaml syntax"
\t@echo "  make check_inc_config  - Check config/inc.yaml syntax"
\t@echo "  make check_layout      - Check required files and directories"
\t@echo "  make check_docs        - Check Guide_Doc basic coverage"
\t@echo "  make check_tool_specs  - Check tool specs"
\t@echo "  make check_tools       - Check tool source files"
\t@echo "  make test_tools        - Run direct tool tests"
\t@echo "  make check_checker_specs - Check generated checker specs"
\t@echo "  make check_checkers    - Check generated checker source files"
\t@echo "  make test_checkers     - Run generated checker direct tests"
\t@echo "  make check_package     - Check migration installer and prepared packages"
\t@echo "  make package           - Prepare full and partial migration packages"
\t@echo "  make test_mcp          - Start UCAgent and call generated tools through MCP"
\t@echo "  make run               - Run UCAgent for this workflow in stable non-TUI loop mode"
\t@echo "  make run_inc           - Run incremental UCAgent workflow in non-TUI loop mode"
\t@echo "  make run_tui           - Run UCAgent TUI for manual debugging"
\t@echo "  make run_inc_tui       - Run incremental UCAgent workflow in TUI mode"
\t@echo "  make smoke             - Run non-interactive UCAgent smoke workflow"
\t@echo "  make session           - Open a shared tmux shell in this workflow"
\t@echo "  make tmux              - Start UCAgent in a shared tmux session"
\t@echo "  make clean             - Clean temporary files"

configure:
\t@python3 setup.py

configure-check:
\t@python3 setup.py --check

check_target:
\t@case "$(TARGET)" in ""|*[!A-Za-z0-9_]*) echo "unsafe or empty TARGET: $(TARGET)"; exit 2;; esac

prepare_input: check_target
{required_checks}
{json_checks}

prepare_runtime: prepare_input
\t@runtime="$(RUNTIME_DUT)"; \\
\tmkdir -p "$$runtime"; \\
\ttouch "$$runtime/__init__.py"

check_input: prepare_input
\t@echo "[PASS] input/$(TARGET) has required files"

check_example: TARGET := {example_target}
check_example: prepare_input
\t@test -f "input/{example_target}/README.md"
\t@echo "[PASS] bundled example is runnable"

check: check_config check_inc_config check_layout check_docs check_tool_specs check_tools test_tools check_checker_specs check_checkers test_checkers check_package

check_config:
\t$(PYTHON) .workflow/checkers/config_syntax_checker.py config.yaml

check_inc_config:
\t$(PYTHON) .workflow/checkers/config_syntax_checker.py config/inc.yaml

check_layout:
\t$(PYTHON) .workflow/checkers/layout_checker.py .workflow/acceptance_rules.yaml

check_docs:
\t$(PYTHON) .workflow/checkers/guidedoc_basic_checker.py Guide_Doc .workflow/workflow_spec.yaml

check_tool_specs:
\t$(PYTHON) .workflow/checkers/tool_spec_checker.py .workflow/tool_specs

check_tools:
\t$(PYTHON) .workflow/checkers/tool_static_checker.py .workflow/tool_specs tools

test_tools:
\t$(PYTHON) .workflow/checkers/tool_direct_runner.py .workflow/tool_specs

check_checker_specs:
\t$(PYTHON) .workflow/checkers/checker_spec_checker.py .workflow/checker_specs

check_checkers:
\t$(PYTHON) .workflow/checkers/checker_static_checker.py .workflow/checker_specs

test_checkers:
\t$(PYTHON) .workflow/checkers/checker_direct_runner.py .workflow/checker_specs

check_package:
\t$(PYTHON) install.py --check

package:
\t$(PYTHON) install.py --prepare both

test_mcp:
\t@test -f $(SETUP_SH) || (echo "missing $(SETUP_SH); initialize UCAgent setup first" && exit 1)
\t@mkdir -p .workflow/logs .workflow/tool_tests/cases output/mcp_test_agent
\t$(UCAGENT_SETUP_CMD) && $(PYTHON) .workflow/tool_tests/run_mcp_tests.py

run: prepare_runtime
\t@test -f $(SETUP_SH) || (echo "missing $(SETUP_SH); initialize UCAgent setup first" && exit 1)
\t@echo "Starting UCAgent workflow in non-TUI loop mode..."
\t@echo "workspace: $(CURDIR)"
\t@echo "TARGET: $(TARGET)"
\t@echo "output: $(OUT)/$(TARGET)"
\t@mkdir -p $(OUT)
\t$(UCAGENT_SETUP_CMD) && {{ \\
\tgenerated_tools="$$( $(GENERATED_TOOLS_CMD) )"; \\
\t$(UCAGENT) $(WORKFLOW_WORKSPACE) $(TARGET) \\
\t\t--config ./config.yaml \\
\t\t--output $(OUT) \\
\t\t--guid-doc-path ./Guide_Doc/ \\
\t\t--append-py-path . \\
\t\t--ex-tools "$$generated_tools" \\
\t\t--mcp-server-port $(MCP_SERVER_PORT) \\
\t\t-s -hm --loop --loop-msg "$(RUN_MSG)" --no-embed-tools --exit-on-completion; \\
\tstatus=$$?; \\
\t$(PYTHON) -c "import json,sys; sys.exit(0 if json.load(open('.ucagent/ucagent_info.json')).get('all_completed') else 1)" && exit 0; \\
\texit $$status; \\
\t}}

run_tui: prepare_runtime
\t@test -f $(SETUP_SH) || (echo "missing $(SETUP_SH); initialize UCAgent setup first" && exit 1)
\t@echo "Starting UCAgent workflow TUI..."
\t@echo "TARGET: $(TARGET)"
\t@mkdir -p $(OUT)
\t$(UCAGENT_SETUP_CMD) && {{ \\
\tgenerated_tools="$$( $(GENERATED_TOOLS_CMD) )"; \\
\t$(UCAGENT) $(WORKFLOW_WORKSPACE) $(TARGET) \\
\t\t--config ./config.yaml \\
\t\t--output $(OUT) \\
\t\t--guid-doc-path ./Guide_Doc/ \\
\t\t--append-py-path . \\
\t\t--ex-tools "$$generated_tools" \\
\t\t--mcp-server-port $(MCP_SERVER_PORT) \\
\t\t-s -hm --no-embed-tools --tui --no-history; \\
\t}}

smoke: TARGET := $(SMOKE_TARGET)
smoke: prepare_runtime
\t@test -f $(SETUP_SH) || (echo "missing $(SETUP_SH); initialize UCAgent setup first" && exit 1)
\t@echo "Running non-interactive UCAgent smoke workflow..."
\t@echo "SMOKE_TARGET: $(SMOKE_TARGET)"
\t@mkdir -p $(OUT) .workflow/logs
\t$(UCAGENT_SETUP_CMD) && {{ \\
\tgenerated_tools="$$( $(GENERATED_TOOLS_CMD) )"; \\
\t$(UCAGENT) $(WORKFLOW_WORKSPACE) $(TARGET) \\
\t\t--config ./config.yaml \\
\t\t--output $(OUT) \\
\t\t--guid-doc-path ./Guide_Doc/ \\
\t\t--append-py-path . \\
\t\t--ex-tools "$$generated_tools" \\
\t\t--mcp-server-port $(MCP_SERVER_PORT) \\
\t\t-s --loop --loop-msg "$(SMOKE_MSG)" --no-embed-tools --no-history --exit-on-completion 2>&1 \\
\t\t| tee .workflow/logs/smoke.log; \\
\t}}
\t@chmod -R u+w .
\t@grep -E "All stages completed|ToolExit|Verify Agent finished" .workflow/logs/smoke.log >/dev/null

run_inc: prepare_runtime
\t@test -f $(SETUP_SH) || (echo "missing $(SETUP_SH); initialize UCAgent setup first" && exit 1)
\t@echo "Starting incremental UCAgent workflow in non-TUI loop mode..."
\t@echo "TARGET: $(TARGET)"
\t@echo "output: $(OUT)/$(TARGET)"
\t@mkdir -p $(OUT)
\t$(UCAGENT_SETUP_CMD) && {{ \\
\tgenerated_tools="$$( $(GENERATED_TOOLS_CMD) )"; \\
\t$(UCAGENT) $(WORKFLOW_WORKSPACE) $(TARGET) \\
\t\t--config ./config/inc.yaml \\
\t\t--output $(OUT) \\
\t\t--guid-doc-path ./Guide_Doc/ \\
\t\t--append-py-path . \\
\t\t--ex-tools "$$generated_tools" \\
\t\t--mcp-server-port $(MCP_SERVER_PORT) \\
\t\t-s -hm --loop --loop-msg "$(INC_MSG)" --no-embed-tools --exit-on-completion; \\
\tstatus=$$?; \\
\t$(PYTHON) -c "import json,sys; sys.exit(0 if json.load(open('.ucagent/ucagent_info.json')).get('all_completed') else 1)" && exit 0; \\
\texit $$status; \\
\t}}

run_inc_tui: prepare_runtime
\t@test -f $(SETUP_SH) || (echo "missing $(SETUP_SH); initialize UCAgent setup first" && exit 1)
\t@echo "Starting incremental UCAgent workflow TUI..."
\t@echo "TARGET: $(TARGET)"
\t@mkdir -p $(OUT)
\t$(UCAGENT_SETUP_CMD) && {{ \\
\tgenerated_tools="$$( $(GENERATED_TOOLS_CMD) )"; \\
\t$(UCAGENT) $(WORKFLOW_WORKSPACE) $(TARGET) \\
\t\t--config ./config/inc.yaml \\
\t\t--output $(OUT) \\
\t\t--guid-doc-path ./Guide_Doc/ \\
\t\t--append-py-path . \\
\t\t--ex-tools "$$generated_tools" \\
\t\t--mcp-server-port $(MCP_SERVER_PORT) \\
\t\t-s -hm --no-embed-tools --tui --no-history; \\
\t}}

session:
\t@echo "Starting shared tmux shell..."
\t@echo "session: $(SESSION)"
\t@tmux has-session -t $(SESSION) 2>/dev/null && tmux kill-session -t $(SESSION) || true
\t@tmux new-session -d -s $(SESSION) -c $(CURDIR) bash
\t@echo "Attach read-only: tmux attach -t $(SESSION) -r"
\t@echo "Attach writable:  tmux attach -t $(SESSION)"

tmux: check_target
\t@echo "Starting UCAgent in tmux..."
\t@echo "session: $(SESSION)"
\t@tmux has-session -t $(SESSION) 2>/dev/null && tmux kill-session -t $(SESSION) || true
\t@tmux new-session -d -s $(SESSION) -c $(CURDIR) bash
\t@tmux send-keys -t $(SESSION) 'make run TARGET=$(TARGET)' C-m
\t@echo "Attach read-only: tmux attach -t $(SESSION) -r"
\t@echo "Attach writable:  tmux attach -t $(SESSION)"

clean:
\t@mkdir -p tmp
\t@find tmp -mindepth 1 -maxdepth 1 -exec rm -rf -- {{}} +
\trm -rf .workflow/tool_tests/logs/*
\tfind . -name "__pycache__" -type d -exec rm -rf {{}} +
\trm -rf .pytest_cache
"""


def generate_runtime_config(data: dict[str, Any]) -> str:
    workflow = data["workflow"]
    raw_config = data.get("config", {})
    raw_tools = raw_config.get("tools")
    if isinstance(raw_tools, dict):
        tools = raw_tools
    elif isinstance(raw_tools, list):
        tools = {"GeneratedTools": raw_tools}
    else:
        tools = {}
    tools.setdefault("RunTestCases", {"test_dir": ".workflow/tool_tests/cases"})
    config = {
        "workflow": {
            "name": workflow["name"],
            "version": workflow["version"],
            "description": workflow["description"],
        },
        "paths": {
            "tools_dir": "tools",
            "checkers_dir": "checkers",
            "guide_docs_dir": "Guide_Doc",
            "docs_dir": "docs",
            "internal_dir": ".workflow",
            "logs_dir": ".workflow/logs",
            "temp_dir": "tmp",
            "tool_specs_dir": ".workflow/tool_specs",
            "tool_tests_dir": ".workflow/tool_tests",
        },
        "model": raw_config.get("model", {"provider": "openai-compatible", "name": "default-model"}),
        "loop_settings": raw_config.get("loop_settings", {"max_loop_retry": 5, "retry_delay_start": 3}),
        "tools": tools,
        "checkers": raw_config.get("checkers", []),
        "guide_docs": raw_config.get("guide_docs", ["Guide_Doc/overview.md"]),
        "template": "",
        "write_dirs": ["{OUT}/{DUT}"],
        "un_write_dirs": [],
        "mission": {
            "name": f"{workflow['name']} smoke workflow",
            "prompt": {
                "system": (
                    "You are running a minimal generated UCAgent workflow smoke test. "
                    "Only read generated documentation, record a stage journal, complete the stage, and exit."
                )
            },
        },
        "stage": [
            {
                "name": "smoke_read_generated_docs",
                "desc": "Read generated README and Guide_Doc to prove the workflow can start.",
                "task": [
                    "First use ReadTextFile to read README.md and Guide_Doc/overview.md, then compare the documented workflow purpose, input contract, output boundary, environment setup, and available validation commands with the generated project layout.",
                    "Confirm that every referenced document is readable from the workflow root, record the exact files inspected and any inconsistency with SetCurrentStageJournal, and do not create business outputs during this skeleton smoke stage.",
                    "If a document is missing or contradicts the generated layout, report the concrete path and mismatch instead of completing. Otherwise use Complete to finish the stage and then use Exit to terminate the smoke workflow cleanly.",
                ],
                "reference_files": ["README.md", "Guide_Doc/overview.md"],
                "output_files": [],
                "checker": [],
            }
        ],
    }
    return yaml_dump(config)


def generate_workflow_spec(data: dict[str, Any]) -> str:
    spec = {"workflow": dict(data["workflow"])}
    spec.update(data["workflow_spec"])
    spec["runtime_contract"] = dict(data.get("runtime_contract", {}))
    return yaml_dump(spec)


def generate_readme(data: dict[str, Any]) -> str:
    contract = data.get("runtime_contract", {})
    example_target = contract.get("example_target", "example")
    required = "\n".join(
        f"- `{path}/`" if kind == "directory" else f"- `{path}`"
        for path, kind, _ in _runtime_required_inputs(data)
    )
    return f"""# {data['workflow']['name']}

## 1. 工作流目标

{data['workflow']['description']}

## 2. 目录结构

```text
.
├── Makefile
├── setup.py
├── config.yaml
├── config/environment.schema.yaml
├── tools/
├── checkers/
├── Guide_Doc/
├── docs/
├── input/
│   ├── {example_target}/
│   └── <TARGET>/
├── output/
└── .workflow/
```

## 3. 输入契约

每个 `input/<TARGET>/` 必须包含：

{required}

`input/{example_target}/` 是可直接运行的真实示例。用户输入只包含原始材料和必要配置；
分析结果、结构设计、样式方案等派生信息必须由工作流生成。

## 4. 基本命令

```bash
make help
make configure
make configure-check
make check
make check_input TARGET=<TARGET>
make check_example
make run TARGET={example_target}
make package
make clean
```

## 5. 当前状态

该工作流目前处于初始化阶段，已经生成基础目录、配置文件、Makefile、内部质量检查器，
以及 `workflow_build.yaml` 预规划的全部业务 Checker、规格和正反测试夹具。

后续可以继续生成工具、完整运行配置和 Guide_Doc；业务 Checker 契约不得在后续阶段重新设计。

## 6. 迁移

最终交付前运行 `make package`，然后使用 `python install.py -o <target> --mode full`
进行全量迁移，或使用 `--mode partial` 迁移不含工具和 checker 的工作流主体。
详细边界见 `.install/README.md`。

本机非敏感环境值保存在 `.workflow/local/environment.yaml`，不会进入迁移包。迁移到
新系统后应重新执行 `make configure`；Token 和密码只能通过运行时环境变量提供。
"""


def generate_guidedoc_overview(data: dict[str, Any]) -> str:
    inputs = data.get("workflow_spec", {}).get("inputs", [])
    outputs = data.get("workflow_spec", {}).get("outputs", [])
    stages = data.get("workflow_spec", {}).get("stages", [])
    return f"""# 工作流目标

本工作流用于：{data['workflow']['description']}

# 输入输出

## 输入

{_format_named_items(inputs)}

## 输出

{_format_named_items(outputs)}

# 目录结构

```text
tools/      工作流工具目录
checkers/   工作流业务 checker 目录
Guide_Doc/  工作流指导文档目录
docs/       参考文档目录
.workflow/  内部生成与验收目录
```

# 运行方式

```bash
make check
make run
```

# 工具说明

当前尚未生成具体工具。

# Checker说明

预规划业务 Checker 已生成到 `checkers/`，规格和正反 fixture 位于
`.workflow/checker_specs/` 与 `.workflow/checker_tests/cases/`。基础生成质量
Checker 位于 `.workflow/checkers/`。

# 异常处理

如果 `make check` 失败，请查看 `.workflow/logs/` 或 `.workflow/build_report.md`。

## 阶段草案

{_format_named_items(stages)}
"""


def generate_guidedoc_tool_generation(data: dict[str, Any]) -> str:
    return f"""# 工具生成协议

本文件定义 `{data['workflow']['name']}` 后续生成工具时必须遵循的闭环。

## 核心顺序

生成任何新工具时必须按下面顺序执行：

1. 读取 `.workflow/workflow_spec.yaml`、`config.yaml` 和 `Guide_Doc/overview.md`。
2. 先创建 `.workflow/tool_specs/<tool_name>.yaml`，不要先写工具代码。
3. 运行 `make check_tool_specs`，根据错误码修复 tool spec。
4. tool spec 通过后，再创建 `tools/<tool_name>.py`。
5. 运行 `make check_tools`，根据错误码修复工具结构。
6. 运行 `make test_tools`，根据 direct runner 日志修复行为。
7. 运行 `make test_mcp`，启动独立 UCAgent MCP 服务并通过 MCP 调用基础生成工具。
8. 全部通过后，把工具注册到 `config.yaml` 的 `tools.GeneratedTools`。
9. 最后运行 `make check`。

推荐优先使用工具生成器完成第 4 步和第 7 步：

```text
WorkflowToolGenerator(
  workflow_root="<workflow_root>",
  mode="from_spec",
  spec_paths=[".workflow/tool_specs/<tool_name>.yaml"],
  existing_policy="create_only",
  update_config=true
)
```

基础辅助工具可以用：

```text
WorkflowToolGenerator(
  workflow_root="<workflow_root>",
  mode="base",
  tools=["read_text_file_tool", "write_text_file_tool", "run_command_tool"],
  existing_policy="create_only",
  update_config=true
)
```

## 工具接口

工具第一版必须是普通 Python 类，不直接绑定 MCP、LangChain 或 UCAgent。

每个工具类必须包含：

```python
name = "tool_name"
description = "..."
input_schema = {{}}
output_schema = {{}}

def run(self, **kwargs) -> dict:
    ...
```

`run` 方法必须返回统一结构：

```python
{{
    "ok": True,
    "data": {{}},
    "errors": [],
    "warnings": [],
    "meta": {{}},
}}
```

失败时也必须返回同样的 key，并在 `errors` 里放错误码和信息。

## 配置注册

`config.yaml` 的 `tools` 必须保持 mapping，不要改成 list。

正确结构：

```yaml
tools:
  RunTestCases:
    test_dir: .workflow/tool_tests/cases
  GeneratedTools:
    - name: read_text_file_tool
      spec: .workflow/tool_specs/read_text_file_tool.yaml
      file: tools/read_text_file_tool.py
      enabled: true
```

## 日志

工具检查日志位于：

```text
.workflow/logs/tool_spec_check.log
.workflow/logs/tool_static_check.log
.workflow/logs/tool_direct_run.log
.workflow/logs/tool_mcp_run.log
output/mcp_test_result.log
```

修复失败时优先读取这些日志中的错误码。

## MCP 集成测试操作协议

负责构建工作流的 Agent 必须亲自完成下面的验证闭环，不能只确认测试文件存在：

1. 完成 `ucagent_setup.sh` 和 Makefile 初始化后，运行 `make test_mcp`。
2. 确认测试使用动态空闲端口启动子 UCAgent，不与当前 Agent 共用 MCP 端口。
3. 确认 MCP `list_tools` 返回 `read_text_file_tool`、`write_text_file_tool`、`run_command_tool`。
4. 确认测试脚本通过 MCP `call_tool` 分别调用三个工具，并精确检查返回值和文件副作用。
5. 读取 `output/mcp_test_result.log`，确认所有 MCP 测试均为 `[PASS]`。
6. 读取 `.workflow/logs/tool_mcp_run.log`，确认请求确实进入子 UCAgent 的 MCP Server。
7. 确认测试脚本向子 UCAgent 发送 `q` 正常退出，并出现文件权限恢复日志。
8. MCP 测试完成后再次运行 `make check`，确认没有残留只读权限或运行中进程。
9. 如果任一步失败，读取上述日志，修复 adapter、注册、启动参数或工具实现，然后重新执行完整闭环。

这里的职责边界是：构建工作流的 Agent 负责验证工具；未来运行生成工作流的 Agent 只使用已经通过验证的工具。

## 推荐阶段拆分

复杂业务工具不要一次生成到最终形态。推荐拆成下面几个阶段：

1. 只生成 tool_spec 和最小测试输入，并运行 `make check_tool_specs`。
2. 调用 `WorkflowToolGenerator(mode="from_spec")` 生成最小可运行工具代码并注册配置。
3. 运行 `make check_tools` 和 `make test_tools`，根据日志修复结构和行为。
4. 增加更多测试用例，再运行 `make test_tools`。
5. 完成 UCAgent 初始化后，按 MCP 集成测试操作协议运行、读日志、修复并重跑。
6. MCP 测试后再次运行 `make check`，再进入 workflow 集成阶段。
"""


def generate_guidedoc_checker_generation(data: dict[str, Any]) -> str:
    return f"""# Checker 生成协议

本文件说明 `{data['workflow']['name']}` 的业务 Checker 初次生成与后续维护闭环。

## 职责

构建 Agent 必须在 `workflow_build.yaml` 中预先规划并验证全部 Checker，不能把设计或
测试责任留给未来运行该工作流的 Agent。

## 固定顺序

1. 在 `workflow_build.yaml` 的 `workflow_spec.checkers` 中写入中心定义、完整 Python
   source、入口、显式 fixture 和至少一个 PASS/FAIL 测试。
2. 在 `workflow_spec.stages` 中预先声明 reference_files、output_files 和 Checker
   绑定参数；每个 Checker 至少绑定一个阶段。
3. 调用 WorkflowBuilder。Builder 直接写出 `.workflow/checker_specs/*.yaml`、
   `checkers/*.py` 和 `.workflow/checker_tests/cases/`。
4. 运行 `make check_checker_specs`、`make check_checkers` 和 `make test_checkers`。
5. 生成 default/inc 配置时由 WorkflowConfigGenerator 从 workflow_spec 注入 Checker
   注册，不得在 config spec 中重新设计。
6. 后续修改必须同步 workflow_spec、对应 spec、实现与正反 fixture，再重新执行完整闭环。

内联 source 可以实现完整领域检查逻辑，不受声明式规则类型限制。入口类必须继承
UCAgent `Checker`，`do_check` 必须有方法级 docstring；fixture 只能位于
`.workflow/checker_tests/cases/<CheckerName>/`，且正反测试都必须持久化。

## Checker Spec 示例

```yaml
name: JsonResultChecker
description: "检查业务阶段产出的 JSON 文件。"
entry:
  file: checkers/json_result_checker.py
  class_name: JsonResultChecker
  method: do_check
source: |
  from ucagent.checkers.base import Checker
  class JsonResultChecker(Checker):
      def __init__(self, path, **kwargs):
          super().__init__()
          self.path = path

      def do_check(self, **kwargs):
          '''Validate the planned JSON result.'''
          ...
fixtures:
  - path: .workflow/checker_tests/cases/JsonResultChecker/valid.json
    content: '{"status": "ok"}'
tests:
  - name: valid
    args: {path: .workflow/checker_tests/cases/JsonResultChecker/valid.json}
    expected_pass: true
  - name: invalid
    args: {path: .workflow/checker_tests/cases/JsonResultChecker/missing.json}
    expected_pass: false
```
"""


def generate_guidedoc_operation(data: dict[str, Any]) -> str:
    required = "\n".join(
        f"- `{path}/`" if kind == "directory" else f"- `{path}`"
        for path, kind, _ in _runtime_required_inputs(data)
    )
    stages = "\n".join(
        f"{idx}. `{stage.get('name', f'stage_{idx}')}` - {stage.get('description', '')}"
        for idx, stage in enumerate(data.get("workflow_spec", {}).get("stages", []), start=1)
        if isinstance(stage, dict)
    )
    return f"""# 运行指南

## 目的

使用所选 `TARGET` 运行 `{data['workflow']['name']}`。

## 输入

`input/<TARGET>/` 下必须包含：

{required}

`input/example` 是随工作流交付的可运行示例。

## 输出

所有工作流产物写入 `output/`。

## 使用方法

```bash
make check_example
make check_input TARGET=example
make run TARGET=example
```

如需选择其他 `TARGET`，创建包含相同必需文件的 `input/<TARGET>/`。

## 执行步骤

{stages or "- 具体执行阶段由生成的运行配置定义。"}

## 检查

运行 `make check`、`make check_example`，并检查生成的 Checker 结果。

## 失败恢复

补齐 `input/<TARGET>/` 中缺少的文件，重新运行 `make check_input TARGET=<name>`，然后运行 `make run TARGET=<name>`。
"""


def generate_guidedoc_environment_setup(data: dict[str, Any]) -> str:
    return """# 环境配置

## 目的

工作流迁移到其他机器后使用本程序完成环境配置。配置器将可迁移声明与本机值分离，
并且只更新运行文件中受控的配置区块。

## 输入

`config/environment.schema.yaml` 声明支持的设置。已有非敏感值可以从
`.workflow/local/environment.yaml` 加载；敏感信息必须继续使用运行时环境变量。

## 输出

`setup.py` 写入 `.workflow/local/environment.yaml`，并刷新 `Makefile` 与
`ucagent_setup.sh` 中带标记的环境区块。本机值不得进入迁移包。

## 使用方法

```bash
make configure
make configure-check
python setup.py --non-interactive --set ucagent_home=/path/to/UCAgent
python setup.py --config /path/to/environment-values.yaml --dry-run
```

## 执行步骤

程序加载 schema、导入可选配置、应用命令行覆盖，在交互终端中询问用户，并验证路径和
可执行程序，最后通过原子替换更新文件。重复执行相同配置应保持幂等。

## 检查

`make configure-check` 检查 schema 类型、必需值、可执行程序发现、路径存在性和生成区块
标记唯一性。验证失败时不得修改 Makefile 或 setup shell 脚本。

## 失败恢复

修正报告的 schema 或路径错误后重新运行。如果生成区块标记被删除或重复，应先从工作流
包恢复文件再重新配置。Token、密码和代理凭据不得写入本地 YAML。
"""


def generate_resource_template(data: dict[str, Any]) -> str:
    return json.dumps(
        {
            "document_request": {
                "topic": "Example topic",
                "purpose": "Describe the document purpose",
                "audience": "Target readers",
            },
            "resources": [
                {
                    "name": "overview",
                    "type": "text",
                    "path": "textsource/overview.md",
                    "description": "Short description of this resource",
                }
            ],
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def generate_suggestion_template(data: dict[str, Any]) -> str:
    return """# Suggestions

Describe the intended focus, tone, audience, required sections, and any constraints.
Do not predefine generated intermediate artifacts such as final layout JSON or style plans.
"""


def _format_named_items(items: Any) -> str:
    if not items:
        return "待补充。"
    lines: list[str] = []
    for item in items:
        if isinstance(item, dict):
            name = item.get("name", "unnamed")
            desc = item.get("description", "")
            lines.append(f"- {name}: {desc}".rstrip())
        else:
            lines.append(f"- {item}")
    return "\n".join(lines)


def generate_input_example(data: dict[str, Any]) -> str:
    example = {
        "input_file": "input/example/README.md",
        "target_name": "example",
        "description": "This is a placeholder input for testing workflow_builder.",
    }
    return json.dumps(example, ensure_ascii=False, indent=2) + "\n"


def generate_build_report(report: BuildReport) -> str:
    return f"""# Workflow Build Report

## Basic Info

- workflow name: {report.workflow_name}
- version: {report.version}
- root path: {report.root_path}
- build config path: {report.build_config_path}

## Created Directories

{_format_list(report.created_dirs)}

## Created Files

{_format_list(report.created_files)}

## Skipped Files

{_format_list(report.skipped_files)}

## Warnings

{_format_list(report.warnings)}

## Errors

{_format_list(report.errors)}

## Next Step

```bash
cd {report.root_path}
make check
```
"""


def _format_list(items: list[str]) -> str:
    if not items:
        return "- None"
    return "\n".join(f"- {item}" for item in items)


CONFIG_SYNTAX_CHECKER = r'''# -*- coding: utf-8 -*-
import re
import sys
from pathlib import Path
import yaml

REQUIRED_FIELDS = ["workflow", "paths", "model", "loop_settings", "tools", "checkers", "guide_docs", "mission", "stage"]
KNOWN_EXTENSIONLESS_FILES = {"Makefile", "Dockerfile", "requirements"}
PLACEHOLDER_RE = re.compile(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)\}(?!\})")
BUILTIN_PLACEHOLDERS = {"DUT", "OUT", "Version"}

def _is_concrete_file_path(value):
    if not isinstance(value, str) or not value.strip() or value.endswith("/"):
        return False
    basename = Path(value.removeprefix("./").rstrip("/")).name
    return bool(Path(basename).suffix) or basename in KNOWN_EXTENSIONLESS_FILES

def _walk_strings(value, location=""):
    if isinstance(value, str):
        yield location or "<root>", value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_strings(item, f"{location}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(item, f"{location}.{key}" if location else str(key))

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"CFG-001: config.yaml 不存在: {path}")
        return 1
    except yaml.YAMLError as exc:
        print(f"CFG-002: config.yaml 无法解析: {exc}")
        return 1
    if not isinstance(data, dict):
        print("CFG-002: config.yaml 顶层必须是 mapping")
        return 1
    missing = [key for key in REQUIRED_FIELDS if key not in data]
    if missing:
        print(f"CFG-003: config.yaml 缺少必要字段: {', '.join(missing)}")
        return 1
    tools = data.get("tools")
    if not isinstance(tools, dict):
        print("CFG-004: config.tools 必须是 mapping")
        return 1
    generated_tools = tools.get("GeneratedTools", [])
    if not isinstance(generated_tools, list):
        print("CFG-005: config.tools.GeneratedTools 必须是 list")
        return 1
    if not isinstance(data.get("stage"), list) or not data["stage"]:
        print("CFG-006: config.stage 必须是非空 list")
        return 1
    template = data.get("template_overwrite", {})
    if not isinstance(template, dict):
        print("CFG-009: template_overwrite 必须是 mapping")
        return 1
    allowed_symbols = BUILTIN_PLACEHOLDERS | set(template)
    unknown_symbols = []
    for location, text in _walk_strings(data):
        unknown = sorted(set(PLACEHOLDER_RE.findall(text)) - allowed_symbols)
        if unknown:
            unknown_symbols.append(f"{location}={','.join(unknown)}")
    if unknown_symbols:
        print(
            "CFG-009: 存在未声明运行时变量；变量必须是DUT/OUT/Version或在"
            f"template_overwrite中声明: {unknown_symbols[:10]}"
        )
        return 1
    for stage in data["stage"]:
        for field in ("reference_files", "output_files"):
            paths = stage.get(field, []) if isinstance(stage, dict) else []
            if not isinstance(paths, list):
                print(f"CFG-008: {stage.get('name', '?')}.{field} 必须是 list")
                return 1
            invalid = [value for value in paths if not _is_concrete_file_path(value)]
            if invalid:
                print(
                    f"CFG-008: {stage.get('name', '?')}.{field} "
                    f"只能包含具体文件，禁止目录: {invalid}"
                )
                return 1
    mode = data.get("workflow", {}).get("mode")
    if mode != "empty" and path.replace("\\", "/").endswith(("config.yaml", "config/inc.yaml", "eval.yaml")):
        for stage in data.get("stage", []):
            task = stage.get("task", []) if isinstance(stage, dict) else []
            text = "\n".join(item for item in task if isinstance(item, str)) if isinstance(task, list) else str(task)
            length = len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", text))
            if length < 100:
                print(f"CFG-007: stage task 有效正文不足 100 字符: {stage.get('name', '?')}={length}")
                return 1
    print("[config] config.yaml syntax check passed")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''


LAYOUT_CHECKER = r'''# -*- coding: utf-8 -*-
import os
import sys
import yaml

def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("acceptance_rules.yaml 顶层必须是 mapping")
    return data

def _check_files(paths):
    missing = [p for p in paths if not os.path.isfile(p)]
    if missing:
        print("LAYOUT-001: 必需文件不存在: " + ", ".join(missing))
        return False
    return True

def _check_dirs(paths):
    missing = [p for p in paths if not os.path.isdir(p)]
    if missing:
        print("LAYOUT-002: 必需目录不存在: " + ", ".join(missing))
        return False
    return True

def main():
    rules_path = sys.argv[1] if len(sys.argv) > 1 else ".workflow/acceptance_rules.yaml"
    try:
        rules = _load(rules_path)
    except Exception as exc:
        print(f"LAYOUT-000: acceptance_rules.yaml 无法读取: {exc}")
        return 1
    ok = True
    ok = _check_files(rules.get("required_public_files", [])) and ok
    ok = _check_dirs(rules.get("required_public_dirs", [])) and ok
    ok = _check_files(rules.get("required_internal_files", [])) and ok
    ok = _check_dirs(rules.get("required_internal_dirs", [])) and ok
    if not ok:
        return 1
    print("[layout] required files and directories check passed")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''


GUIDEDOC_BASIC_CHECKER = r'''# -*- coding: utf-8 -*-
import os
import re
import sys
from pathlib import Path

REQUIRED_SECTIONS = [
    "# 工作流目标",
    "# 输入输出",
    "# 目录结构",
    "# 运行方式",
    "# 工具说明",
    "# Checker说明",
    "# 异常处理",
]

USER_DOC_RULES = {
    "README.md": ("文档地图", "快速入口"),
    "01快速启动.md": ("make configure", "make check", "make run"),
    "02输入输出.md": ("input/<TARGET>/", "output/<TARGET>/", "metadata/", "checksums.sha256"),
    "03步骤及检查.md": ("阶段", "Checker", "检查"),
    "04开发者文档-tools.md": ("源码", "关键代码分析", "测试"),
    "05开发者文档-checkers.md": ("源码", "关键代码分析", "测试"),
}

def _prose_length(text):
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return len(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", text))

def _check_user_docs(root):
    docs = root / "docs"
    errors = []
    makefile = (root / "Makefile").read_text(encoding="utf-8") if (root / "Makefile").is_file() else ""
    if "input/$(TARGET)/metadata" not in makefile or "input/$(TARGET)/checksums.sha256" not in makefile:
        errors.append("DOC-018: Makefile 未将 metadata/ 和 checksums.sha256 作为必需输入检查")
    for name, markers in USER_DOC_RULES.items():
        path = docs / name
        if not path.is_file():
            errors.append(f"DOC-010: 用户文档缺失: docs/{name}")
            continue
        text = path.read_text(encoding="utf-8")
        if not re.match(r"^# [^#].*\n", text):
            errors.append(f"DOC-011: 用户文档首行必须是一级标题: docs/{name}")
        missing = [marker for marker in markers if marker not in text]
        if missing:
            errors.append(f"DOC-012: docs/{name} 缺少格式/契约标记: {missing}")
        if name == "02输入输出.md":
            if re.search(r"metadata.{0,30}(可选|optional)|(?:可选|optional).{0,30}metadata", text, flags=re.I | re.S):
                errors.append("DOC-016: docs/02输入输出.md 将 metadata/ 描述为可选")
            if re.search(r"checksums\.sha256.{0,30}(可选|optional)|(?:可选|optional).{0,30}checksums\.sha256", text, flags=re.I | re.S):
                errors.append("DOC-017: docs/02输入输出.md 将 checksums.sha256 描述为可选")
        if _prose_length(text) < 200:
            errors.append(f"DOC-013: docs/{name} 有效正文少于 200 字符")
        if re.search(r"TODO|TBD|待补充|待完善", text, flags=re.I):
            errors.append(f"DOC-014: docs/{name} 包含占位词")
    for name in ("04开发者文档-tools.md", "05开发者文档-checkers.md"):
        path = docs / name
        if path.is_file() and "```" not in path.read_text(encoding="utf-8"):
            errors.append(f"DOC-015: {name} 必须包含真实源码代码块")
    return errors

def main():
    guide_dir = sys.argv[1] if len(sys.argv) > 1 else "Guide_Doc"
    if not os.path.isdir(guide_dir):
        print(f"DOC-001: Guide_Doc 目录不存在: {guide_dir}")
        return 1
    overview = os.path.join(guide_dir, "overview.md")
    if not os.path.isfile(overview):
        print(f"DOC-002: overview.md 不存在: {overview}")
        return 1
    with open(overview, "r", encoding="utf-8") as f:
        content = f.read()
    missing = [section for section in REQUIRED_SECTIONS if section not in content]
    if missing:
        print("DOC-003: overview.md 缺少必要章节: " + ", ".join(missing))
        return 1
    guide_path = Path(guide_dir)
    workflow_root = guide_path.parent if guide_path.is_absolute() else Path.cwd()
    errors = _check_user_docs(workflow_root)
    if errors:
        print("\\n".join(errors))
        return 1
    print("[docs] Guide_Doc basic check passed")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''


TOOL_SPEC_CHECKER = r'''# -*- coding: utf-8 -*-
import hashlib
import os
import sys
from pathlib import Path

import yaml

REQUIRED_RETURN_KEYS = ["ok", "data", "errors", "warnings", "meta"]
GENERATION_STATE = Path(".workflow/tool_generation_state.yaml")


def _log(message):
    log_dir = Path(".workflow/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "tool_spec_check.log").open("a", encoding="utf-8") as f:
        f.write(message + "\n")


def _load_yaml(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        return None, f"TOOL-SPEC-001: tool_spec 文件不存在: {path}"
    except yaml.YAMLError as exc:
        return None, f"TOOL-SPEC-002: YAML 解析失败: {path}: {exc}"
    if not isinstance(data, dict):
        return None, f"TOOL-SPEC-002: YAML 顶层必须是 mapping: {path}"
    return data, None


def _spec_paths(target):
    path = Path(target)
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(path.glob("*.yaml"))
    return [path]


def check_one(path):
    data, error = _load_yaml(path)
    if error:
        return False, error
    if not data.get("name"):
        return False, f"TOOL-SPEC-003: 缺少 name: {path}"
    if not data.get("description"):
        return False, f"TOOL-SPEC-003: 缺少 description: {path}"

    entry = data.get("entry")
    if not isinstance(entry, dict):
        return False, f"TOOL-SPEC-004: 缺少 entry: {path}"
    entry_file = entry.get("file")
    if not entry_file:
        return False, f"TOOL-SPEC-004: 缺少 entry.file: {path}"
    if not entry.get("class_name"):
        return False, f"TOOL-SPEC-005: 缺少 entry.class_name: {path}"
    if not entry.get("method"):
        return False, f"TOOL-SPEC-006: 缺少 entry.method: {path}"
    entry_path = Path(entry_file)
    if entry_path.is_absolute() or ".." in entry_path.parts or not entry_path.parts or entry_path.parts[0] != "tools":
        return False, f"TOOL-SPEC-011: entry.file 不在 tools/ 目录下: {entry_file}"
    if entry_path.stem != data["name"]:
        return False, f"TOOL-SPEC-011: 工具名和文件名不一致: {data['name']} vs {entry_path.name}"

    canonical_inputs = data.get("inputs")
    legacy_inputs = data.get("input")
    if canonical_inputs is not None and legacy_inputs is not None and canonical_inputs != legacy_inputs:
        return False, f"TOOL-SPEC-007: input 与 inputs 定义冲突: {path}"
    spec_inputs = canonical_inputs if canonical_inputs is not None else legacy_inputs
    if not isinstance(spec_inputs, list):
        return False, f"TOOL-SPEC-007: input/inputs 格式错误: {path}"
    for item in spec_inputs:
        if not isinstance(item, dict):
            return False, f"TOOL-SPEC-007: input/inputs 条目必须是 mapping: {path}"
        input_name = str(item.get("name", "")).strip()
        input_type = str(item.get("type", "")).strip().lower()
        if input_name == "params" and input_type in {"string", "str"}:
            return False, (
                "TOOL-SPEC-013: params 是 MCP/JSON-RPC 中的结构化参数名，"
                f"不能声明为 string；请改为 dict 或 mapping: {path}"
            )
    outputs = data.get("outputs")
    if not isinstance(outputs, dict):
        return False, f"TOOL-SPEC-008: outputs 格式错误: {path}"
    required_keys = outputs.get("required_keys")
    if not isinstance(required_keys, list):
        return False, f"TOOL-SPEC-008: outputs.required_keys 格式错误: {path}"
    missing = [key for key in REQUIRED_RETURN_KEYS if key not in required_keys]
    if missing:
        return False, f"TOOL-SPEC-012: required_keys 缺少统一返回字段: {', '.join(missing)}"

    tests = data.get("tests")
    if not isinstance(tests, list) or not tests:
        return False, f"TOOL-SPEC-009: tests 为空: {path}"
    for test in tests:
        if not isinstance(test, dict) or not all(key in test for key in ("name", "input", "expected")):
            return False, f"TOOL-SPEC-010: test case 缺少必要字段: {path}"
    state, state_error = _load_yaml(GENERATION_STATE)
    if state_error and GENERATION_STATE.is_file():
        return False, f"TOOL-SPEC-014: 无法读取测试基线: {state_error}"
    baselines = state.get("tool_tests", {}) if isinstance(state, dict) else {}
    baseline = baselines.get(data["name"], {}) if isinstance(baselines, dict) else {}
    if isinstance(baseline, dict) and baseline:
        current = {
            test["name"]: hashlib.sha256(
                yaml.safe_dump(test, allow_unicode=True, sort_keys=True).encode("utf-8")
            ).hexdigest()
            for test in tests
        }
        missing = sorted(set(baseline) - set(current))
        changed = sorted(
            name
            for name, digest in baseline.items()
            if name in current and current[name] != digest
        )
        if missing or changed:
            return False, (
                f"TOOL-SPEC-014: 已冻结测试不得删除或改写: "
                f"missing={missing}, changed={changed}: {path}"
            )
    return True, f"[PASS] {data['name']}"


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else ".workflow/tool_specs"
    paths = _spec_paths(target)
    if not paths:
        msg = f"[PASS] no tool specs declared yet: {target}"
        print(msg)
        _log(msg)
        return 0
    ok = True
    for path in paths:
        passed, message = check_one(path)
        print(message)
        _log(("[PASS] " if passed else "[FAIL] ") + str(path) + " " + message)
        ok = passed and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


TOOL_STATIC_CHECKER = r'''# -*- coding: utf-8 -*-
import importlib.util
import py_compile
import sys
from pathlib import Path

import yaml

REQUIRED_RETURN_KEYS = ["ok", "data", "errors", "warnings", "meta"]


def _log(message):
    log_dir = Path(".workflow/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "tool_static_check.log").open("a", encoding="utf-8") as f:
        f.write(message + "\n")


def _load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"tool_spec 顶层必须是 mapping: {path}")
    return data


def _spec_paths(target):
    path = Path(target)
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(path.glob("*.yaml"))
    return [path]


def _import_module(path):
    module_name = "generated_tool_" + path.stem
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法创建 import spec: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _instantiate(cls):
    try:
        return cls(root_dir=".")
    except TypeError:
        return cls()


def check_one(spec_path):
    try:
        spec = _load_yaml(spec_path)
    except Exception as exc:
        return False, f"TOOL-STATIC-003: 读取 tool_spec 失败: {exc}"
    entry = spec.get("entry", {})
    tool_file = Path(entry.get("file", ""))
    if not tool_file.is_file():
        return False, f"TOOL-STATIC-001: 工具文件不存在: {tool_file}"
    try:
        py_compile.compile(str(tool_file), doraise=True)
    except py_compile.PyCompileError as exc:
        return False, f"TOOL-STATIC-002: Python 语法错误: {tool_file}: {exc.msg}"
    try:
        module = _import_module(tool_file)
    except Exception as exc:
        return False, f"TOOL-STATIC-003: import 失败: {tool_file}: {exc}"
    class_name = entry.get("class_name")
    if not hasattr(module, class_name):
        return False, f"TOOL-STATIC-004: 类不存在: {class_name}"
    cls = getattr(module, class_name)
    try:
        tool = _instantiate(cls)
    except Exception as exc:
        return False, f"TOOL-STATIC-005: 类实例化失败: {class_name}: {exc}"
    method = entry.get("method", "run")
    if not callable(getattr(tool, method, None)):
        return False, f"TOOL-STATIC-006: run 方法不存在: {method}"
    for attr, code in (
        ("name", "TOOL-STATIC-007"),
        ("description", "TOOL-STATIC-008"),
        ("input_schema", "TOOL-STATIC-009"),
        ("output_schema", "TOOL-STATIC-010"),
    ):
        if not hasattr(tool, attr):
            return False, f"{code}: 缺少 {attr}"
    if tool.name != spec.get("name"):
        return False, f"TOOL-STATIC-011: 工具 name 与 tool_spec.name 不一致: {tool.name} vs {spec.get('name')}"
    if not isinstance(tool.input_schema, dict):
        return False, "TOOL-STATIC-009: input_schema 必须是 dict"
    canonical_inputs = spec.get("inputs")
    legacy_inputs = spec.get("input")
    if canonical_inputs is not None and legacy_inputs is not None and canonical_inputs != legacy_inputs:
        return False, f"TOOL-STATIC-012: input 与 inputs 定义冲突: {spec_path}"
    spec_inputs = canonical_inputs if canonical_inputs is not None else legacy_inputs
    spec_input_names = [item.get("name") for item in (spec_inputs or []) if isinstance(item, dict)]
    missing_inputs = [name for name in spec_input_names if name not in tool.input_schema]
    if missing_inputs:
        return False, f"TOOL-STATIC-012: input_schema 与 tool_spec.inputs 不一致: {', '.join(missing_inputs)}"
    if not isinstance(tool.output_schema, dict):
        return False, "TOOL-STATIC-010: output_schema 必须是 dict"
    output_keys = tool.output_schema.get("required_keys", [])
    missing_output_keys = [key for key in REQUIRED_RETURN_KEYS if key not in output_keys]
    if missing_output_keys:
        return False, f"TOOL-STATIC-010: output_schema 缺少统一返回字段: {', '.join(missing_output_keys)}"
    return True, f"[PASS] {spec.get('name')}"


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else ".workflow/tool_specs"
    paths = _spec_paths(target)
    if not paths:
        msg = f"[PASS] no tool specs declared yet: {target}"
        print(msg)
        _log(msg)
        return 0
    ok = True
    for path in paths:
        passed, message = check_one(path)
        print(message)
        _log(("[PASS] " if passed else "[FAIL] ") + str(path) + " " + message)
        ok = passed and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


TOOL_DIRECT_RUNNER = r'''# -*- coding: utf-8 -*-
import importlib.util
import sys
from pathlib import Path

import yaml


def _log(message):
    log_dir = Path(".workflow/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "tool_direct_run.log").open("a", encoding="utf-8") as f:
        f.write(message + "\n")


def _tool_log(tool_name, message):
    log_dir = Path(".workflow/tool_tests/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / f"{tool_name}.log").open("a", encoding="utf-8") as f:
        f.write(message + "\n")


def _load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"tool_spec 顶层必须是 mapping: {path}")
    return data


def _spec_paths(target):
    path = Path(target)
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(path.glob("*.yaml"))
    return [path]


def _import_module(path):
    module_name = "generated_tool_runner_" + path.stem
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法创建 import spec: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _instantiate(cls):
    try:
        return cls(root_dir=".")
    except TypeError:
        return cls()


def _reset_create_artifacts(cases):
    temp_root = Path("tmp").resolve()
    for case in cases:
        inputs = case.get("input", {})
        expected = case.get("expected", {})
        path_value = inputs.get("path")
        if inputs.get("action") != "create" or expected.get("ok") is not True or not path_value:
            continue
        artifact = Path(path_value).resolve()
        if artifact.is_relative_to(temp_root) and artifact.is_file():
            artifact.unlink()


def _check_result(result, expected):
    if not isinstance(result, dict):
        return False, "TOOL-RUN-002: 返回值不是 dict"
    for key in expected.get("required_keys", ["ok", "data", "errors", "warnings", "meta"]):
        if key not in result:
            return False, f"TOOL-RUN-003: 返回值缺少 required key: {key}"
    if "ok" in expected and result.get("ok") != expected["ok"]:
        return False, f"TOOL-RUN-004: ok 字段不符合预期: {result.get('ok')} vs {expected['ok']}"
    data = result.get("data")
    if not isinstance(data, dict):
        return False, "TOOL-RUN-005: data 不是 dict"
    for key in expected.get("data_required_keys", []):
        if key not in data:
            return False, f"TOOL-RUN-005: data 缺少必要字段: {key}"
    if not isinstance(result.get("errors"), list):
        return False, "TOOL-RUN-006: errors 不是 list"
    if not isinstance(result.get("warnings"), list):
        return False, "TOOL-RUN-007: warnings 不是 list"
    if not isinstance(result.get("meta"), dict):
        return False, "TOOL-RUN-008: meta 不是 dict"
    return True, "PASS"


def check_one(spec_path):
    try:
        spec = _load_yaml(spec_path)
        entry = spec.get("entry", {})
        module = _import_module(Path(entry.get("file", "")))
        cls = getattr(module, entry.get("class_name"))
        tool = _instantiate(cls)
    except Exception as exc:
        return False, f"TOOL-RUN-001: 工具运行异常: {exc}"

    ok = True
    tool_name = spec.get("name", Path(spec_path).stem)
    cases = spec.get("tests", [])
    _reset_create_artifacts(cases)
    for case in cases:
        case_name = case.get("name", "unnamed")
        try:
            result = getattr(tool, entry.get("method", "run"))(**case.get("input", {}))
        except Exception as exc:
            message = f"TOOL-RUN-001: 工具运行异常: {tool_name}.{case_name}: {exc}"
            print(message)
            _log("[FAIL] " + message)
            _tool_log(tool_name, "[FAIL] " + message)
            ok = False
            continue
        passed, message = _check_result(result, case.get("expected", {}))
        line = f"{tool_name}.{case_name}: {message}"
        print(("[PASS] " if passed else "[FAIL] ") + line)
        _log(("[PASS] " if passed else "[FAIL] ") + line)
        _tool_log(tool_name, ("[PASS] " if passed else "[FAIL] ") + line)
        ok = passed and ok
    return ok, f"[PASS] {tool_name}" if ok else f"TOOL-RUN-009: 测试用例执行失败: {tool_name}"


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else ".workflow/tool_specs"
    paths = _spec_paths(target)
    if not paths:
        msg = f"[PASS] no tool specs declared yet: {target}"
        print(msg)
        _log(msg)
        return 0
    ok = True
    for path in paths:
        passed, message = check_one(path)
        if not passed:
            print(message)
        ok = passed and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


CHECKER_SPEC_CHECKER = r'''# -*- coding: utf-8 -*-
import ast
import sys
from pathlib import Path

import yaml


def check_one(path):
    try:
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"CHECKER-SPEC-001: cannot parse {path}: {exc}"
    if not isinstance(spec, dict):
        return False, f"CHECKER-SPEC-002: top-level must be mapping: {path}"
    for key in ("name", "description", "entry"):
        if key not in spec:
            return False, f"CHECKER-SPEC-003: missing {key}: {path}"
    entry = spec["entry"]
    if not isinstance(entry, dict) or not all(entry.get(key) for key in ("file", "class_name", "method")):
        return False, f"CHECKER-SPEC-004: invalid entry: {path}"
    entry_path = Path(entry["file"])
    if entry_path.is_absolute() or ".." in entry_path.parts or not entry_path.parts or entry_path.parts[0] != "checkers":
        return False, f"CHECKER-SPEC-005: entry.file must be under checkers/: {path}"
    if "source" in spec:
        try:
            tree = ast.parse(spec["source"])
        except (SyntaxError, TypeError) as exc:
            return False, f"CHECKER-SPEC-006: invalid inline source: {path}: {exc}"
        class_node = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == entry["class_name"]), None)
        method = next((node for node in class_node.body if isinstance(node, ast.FunctionDef) and node.name == entry["method"]), None) if class_node else None
        if class_node is None or method is None or not ast.get_docstring(method):
            return False, f"CHECKER-SPEC-007: inline source requires entry class and documented method: {path}"
        fixtures = spec.get("fixtures")
        if not isinstance(fixtures, list) or not fixtures:
            return False, f"CHECKER-SPEC-007: inline source requires explicit fixtures: {path}"
    else:
        rules = spec.get("rules")
        supported = {"json_required_keys", "json_numeric_range", "file_exists", "command_exit_code"}
        if not isinstance(rules, dict) or rules.get("type") not in supported:
            return False, f"CHECKER-SPEC-006: unsupported rules.type: {path}"
        if rules["type"] == "json_required_keys" and (not isinstance(rules.get("required_keys"), list) or not rules["required_keys"]):
            return False, f"CHECKER-SPEC-007: rules.required_keys must be non-empty: {path}"
        if rules["type"] == "json_numeric_range":
            if not isinstance(rules.get("field"), str) or not rules["field"]:
                return False, f"CHECKER-SPEC-007: rules.field must be non-empty: {path}"
            if not isinstance(rules.get("minimum"), (int, float)) or not isinstance(rules.get("maximum"), (int, float)) or rules["minimum"] > rules["maximum"]:
                return False, f"CHECKER-SPEC-007: invalid numeric range: {path}"
        if rules["type"] == "command_exit_code" and (not isinstance(rules.get("allowed_commands"), list) or not rules["allowed_commands"]):
            return False, f"CHECKER-SPEC-007: rules.allowed_commands must be non-empty: {path}"
    tests = spec.get("tests")
    if not spec.get("auto_tests") and (not isinstance(tests, list) or not tests):
        return False, f"CHECKER-SPEC-008: tests must be non-empty unless auto_tests=true: {path}"
    if tests is not None and not isinstance(tests, list):
        return False, f"CHECKER-SPEC-008: tests must be a list: {path}"
    for case in tests or []:
        if not isinstance(case, dict) or not all(key in case for key in ("name", "args", "expected_pass")):
            return False, f"CHECKER-SPEC-009: invalid test case: {path}"
    if "source" in spec and {case.get("expected_pass") for case in tests or []} != {True, False}:
        return False, f"CHECKER-SPEC-010: inline source requires PASS and FAIL tests: {path}"
    return True, f"[PASS] {spec['name']}"


def main():
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ".workflow/checker_specs")
    paths = [target] if target.is_file() else sorted(target.glob("*.yaml"))
    if not paths:
        print(f"[PASS] no checker specs declared yet: {target}")
        return 0
    ok = True
    for path in paths:
        passed, message = check_one(path)
        print(message)
        ok = passed and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


CHECKER_STATIC_CHECKER = r'''# -*- coding: utf-8 -*-
import importlib.util
import py_compile
import sys
from pathlib import Path

import yaml


def load_module(path):
    spec = importlib.util.spec_from_file_location("generated_checker_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_one(spec_path):
    from ucagent.checkers.base import Checker

    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    entry = spec["entry"]
    source = Path(entry["file"])
    if not source.is_file():
        return False, f"CHECKER-STATIC-001: source missing: {source}"
    try:
        py_compile.compile(str(source), doraise=True)
        cls = getattr(load_module(source), entry["class_name"])
        init_args = spec.get("register", {}).get("args", {})
        if not init_args and spec.get("tests"):
            init_args = spec["tests"][0].get("args", {})
        checker = cls(**init_args)
    except Exception as exc:
        return False, f"CHECKER-STATIC-002: import or instantiate failed: {exc}"
    if not issubclass(cls, Checker):
        return False, f"CHECKER-STATIC-003: class does not inherit Checker: {entry['class_name']}"
    if not callable(getattr(checker, entry["method"], None)):
        return False, f"CHECKER-STATIC-004: method missing: {entry['method']}"
    try:
        str(checker)
    except Exception as exc:
        return False, f"CHECKER-STATIC-005: checker cannot be described by UCAgent: {exc}"
    return True, f"[PASS] {spec['name']}"


def main():
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ".workflow/checker_specs")
    paths = [target] if target.is_file() else sorted(target.glob("*.yaml"))
    if not paths:
        print(f"[PASS] no checker specs declared yet: {target}")
        return 0
    ok = True
    for path in paths:
        passed, message = check_one(path)
        print(message)
        ok = passed and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


CHECKER_DIRECT_RUNNER = r'''# -*- coding: utf-8 -*-
import importlib.util
import sys
from pathlib import Path

import yaml


def load_module(path):
    spec = importlib.util.spec_from_file_location("generated_checker_runner_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_one(spec_path):
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    entry = spec["entry"]
    cls = getattr(load_module(Path(entry["file"])), entry["class_name"])
    ok = True
    for case in spec["tests"]:
        checker = cls(**case.get("args", {}))
        checker.workspace = str(Path.cwd())
        try:
            str(checker)
        except Exception as exc:
            print(f"[FAIL] {spec['name']}.{case['name']}: checker cannot be described by UCAgent: {exc}")
            ok = False
            continue
        passed, result = getattr(checker, entry["method"])(timeout=30)
        expected = bool(case["expected_pass"])
        case_ok = bool(passed) == expected
        print(("[PASS] " if case_ok else "[FAIL] ") + f"{spec['name']}.{case['name']}: pass={passed}, expected={expected}")
        if not case_ok:
            print(result)
        ok = case_ok and ok
    return ok


def main():
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ".workflow/checker_specs")
    paths = [target] if target.is_file() else sorted(target.glob("*.yaml"))
    if not paths:
        print(f"[PASS] no checker specs declared yet: {target}")
        return 0
    return 0 if all(check_one(path) for path in paths) else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


MCP_TOOL_ADAPTERS = r'''# -*- coding: utf-8 -*-
"""UCAgent MCP adapters for the generated plain-Python base tools."""

from __future__ import annotations

import json
import os

from pydantic import BaseModel, Field
from ucagent.tools.uctool import UCTool

from tools.read_text_file_tool import ReadTextFileTool
from tools.run_command_tool import RunCommandTool
from tools.write_text_file_tool import WriteTextFileTool


def _result_text(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


class ReadTextFileMCPArgs(BaseModel):
    path: str = Field(description="Text file path relative to the workflow root.")


class ReadTextFileMCPTool(UCTool):
    name: str = "read_text_file_tool"
    description: str = "Read a text file inside the generated workflow."
    args_schema: type[BaseModel] = ReadTextFileMCPArgs

    def _run(self, path: str, run_manager=None) -> str:
        return _result_text(ReadTextFileTool(root_dir=os.getcwd()).run(path=path))


class WriteTextFileMCPArgs(BaseModel):
    path: str = Field(description="Text file path relative to the workflow root.")
    content: str = Field(description="Text content to write.")
    overwrite: bool = Field(default=False, description="Allow replacing an existing file.")


class WriteTextFileMCPTool(UCTool):
    name: str = "write_text_file_tool"
    description: str = "Write a text file inside the generated workflow."
    args_schema: type[BaseModel] = WriteTextFileMCPArgs

    def _run(self, path: str, content: str, overwrite: bool = False, run_manager=None) -> str:
        return _result_text(
            WriteTextFileTool(root_dir=os.getcwd()).run(path=path, content=content, overwrite=overwrite)
        )


class RunCommandMCPArgs(BaseModel):
    command: str = Field(description="Whitelisted command to run without a shell.")
    cwd: str = Field(default=".", description="Working directory relative to the workflow root.")
    timeout: int = Field(default=30, description="Timeout in seconds.")


class RunCommandMCPTool(UCTool):
    name: str = "run_command_tool"
    description: str = "Run a whitelisted command inside the generated workflow."
    args_schema: type[BaseModel] = RunCommandMCPArgs

    def _run(self, command: str, cwd: str = ".", timeout: int = 30, run_manager=None) -> str:
        return _result_text(
            RunCommandTool(root_dir=os.getcwd()).run(command=command, cwd=cwd, timeout=timeout)
        )
'''


MCP_TOOL_TEST_RUNNER = r'''# -*- coding: utf-8 -*-
"""Start UCAgent MCP, call generated base tools, validate results, and stop it."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


ROOT = Path.cwd().resolve()
LOG_PATH = ROOT / ".workflow/logs/tool_mcp_run.log"
RESULT_LOG_PATH = ROOT / "output/mcp_test_result.log"
ADAPTERS = ",".join(
    [
        "tools.mcp_adapters.ReadTextFileMCPTool",
        "tools.mcp_adapters.WriteTextFileMCPTool",
        "tools.mcp_adapters.RunCommandMCPTool",
    ]
)
REQUIRED_TOOLS = {"read_text_file_tool", "write_text_file_tool", "run_command_tool"}


def _record(message: str) -> None:
    print(message)
    with RESULT_LOG_PATH.open("a", encoding="utf-8") as result_log:
        result_log.write(message + "\n")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _ucagent_command(port: int) -> list[str]:
    ucagent_home = Path(os.environ.get("UCAGENT_HOME", Path.home() / "FDocB/UCAgent"))
    ucagent_py = ucagent_home / "ucagent.py"
    if not ucagent_py.is_file():
        raise RuntimeError(f"UCAgent entry not found: {ucagent_py}")
    return [
        sys.executable,
        str(ucagent_py),
        "./",
        "smoke",
        "--config",
        "./config.yaml",
        "--output",
        "output/mcp_test_agent",
        "--guid-doc-path",
        "./Guide_Doc/",
        "--mcp-server-no-file-tools",
        "--mcp-server-host",
        "127.0.0.1",
        "--mcp-server-port",
        str(port),
        "--ex-tools",
        ADAPTERS,
        "--append-py-path",
        ".",
        "-s",
        "-hm",
        "--no-embed-tools",
        "--no-history",
    ]


def _decode_result(result) -> dict:
    texts = [item.text for item in result.content if hasattr(item, "text")]
    if not texts:
        raise AssertionError("MCP result contains no text")
    value = json.loads(texts[0])
    if not isinstance(value, dict):
        raise AssertionError(f"MCP result is not a dict: {value!r}")
    return value


async def _call_and_check(port: int) -> None:
    url = f"http://127.0.0.1:{port}/mcp"
    deadline = time.monotonic() + 30
    last_error = None
    while time.monotonic() < deadline:
        try:
            async with streamablehttp_client(url, timeout=3) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    names = {tool.name for tool in listed.tools}
                    missing = sorted(REQUIRED_TOOLS - names)
                    if missing:
                        raise AssertionError(f"Generated MCP tools not registered: {missing}")

                    read_result = _decode_result(
                        await session.call_tool("read_text_file_tool", {"path": "input/example/README.md"})
                    )
                    expected_content = (ROOT / "input/example/README.md").read_text(encoding="utf-8")
                    assert read_result["ok"] is True
                    assert read_result["data"]["content"] == expected_content
                    assert read_result["data"]["char_count"] == len(expected_content)

                    write_path = "output/mcp_write_text_file.txt"
                    write_content = "written through UCAgent MCP\n"
                    write_result = _decode_result(
                        await session.call_tool(
                            "write_text_file_tool",
                            {"path": write_path, "content": write_content, "overwrite": True},
                        )
                    )
                    assert write_result["ok"] is True
                    assert (ROOT / write_path).read_text(encoding="utf-8") == write_content

                    run_result = _decode_result(
                        await session.call_tool("run_command_tool", {"command": "pwd", "cwd": ".", "timeout": 10})
                    )
                    assert run_result["ok"] is True
                    assert Path(run_result["data"]["stdout"].strip()).resolve() == ROOT

                    _record("[PASS] MCP list_tools registered generated base tools")
                    _record("[PASS] MCP call read_text_file_tool")
                    _record("[PASS] MCP call write_text_file_tool")
                    _record("[PASS] MCP call run_command_tool")
                    return
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(0.5)
    raise RuntimeError(f"MCP server did not become testable: {last_error}")


def main() -> int:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_LOG_PATH.unlink(missing_ok=True)
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = "127.0.0.1,localhost"
    port = _free_port()
    command = _ucagent_command(port)
    with LOG_PATH.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            asyncio.run(_call_and_check(port))
        finally:
            try:
                if process.poll() is None and process.stdin is not None:
                    process.stdin.write("q\n")
                    process.stdin.flush()
                    process.wait(timeout=15)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


MCP_TOOL_ADAPTERS = SPEC_DRIVEN_MCP_TOOL_ADAPTERS
MCP_TOOL_TEST_RUNNER = SPEC_DRIVEN_MCP_TOOL_TEST_RUNNER


WORKFLOW_INSTALLER = r'''#!/usr/bin/env python3
"""Prepare and deploy portable full or partial snapshots of this workflow."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
INSTALL_ROOT = ROOT / ".install"
PACKAGES_ROOT = INSTALL_ROOT / "packages"
MANIFEST_PATH = INSTALL_ROOT / "manifest.json"
MODES = ("full", "partial")
IGNORED_TOP_LEVEL = {
    ".git",
    ".pytest_cache",
    ".ucagent",
    "GuideDocs",
    "__pycache__",
    "output",
    "reports",
    "tmp",
    "output",
}
IGNORED_PARTS = {"__pycache__", ".pytest_cache", "logs", "temp"}
FORBIDDEN_FILES = {
    "Guide_Doc/tool_generation_guide.md",
    "Guide_Doc/checker_generation_guide.md",
    "Guide_Doc/workflow_build_guide.md",
    "Guide_Doc/workflow_build_yaml_guide.md",
}
PARTIAL_EXCLUDES = (
    "tools",
    "checkers",
    ".workflow/tool_specs",
    ".workflow/tool_tests",
    ".workflow/checker_specs",
    ".workflow/checker_tests",
    ".workflow/checkers",
)


def _preserved_logs_path(rel: Path) -> bool:
    """Keep only explicitly declared example/test fixture logs in packages."""
    parts = rel.parts
    if parts[:3] == ("input", "example", "logs"):
        return True
    for prefix in (Path(".workflow/tool_tests/cases"), Path(".workflow/checker_tests/cases")):
        if len(parts) >= len(prefix.parts) and parts[:len(prefix.parts)] == prefix.parts:
            return True
    return False


def _relative_files(mode: str) -> list[Path]:
    files: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(ROOT)
        rel_text = rel.as_posix()
        if rel_text in FORBIDDEN_FILES:
            continue
        if rel.parts[0] in IGNORED_TOP_LEVEL or (
            any(part in IGNORED_PARTS for part in rel.parts)
            and not _preserved_logs_path(rel)
        ):
            continue
        if rel_text == ".install/packages" or rel_text.startswith(".install/packages/"):
            continue
        if rel_text == ".workflow/local" or rel_text.startswith(".workflow/local/"):
            continue
        if mode == "partial" and any(rel_text == prefix or rel_text.startswith(prefix + "/") for prefix in PARTIAL_EXCLUDES):
            continue
        files.append(rel)
    return files


def _relative_directories(mode: str) -> list[Path]:
    directories: set[Path] = {Path("output"), Path("tmp")}
    for path in sorted(ROOT.rglob("*")):
        if not path.is_dir() or path.is_symlink():
            continue
        rel = path.relative_to(ROOT)
        rel_text = rel.as_posix()
        if rel_text == ".install/packages" or rel_text.startswith(".install/packages/"):
            continue
        if rel_text == ".workflow/local" or rel_text.startswith(".workflow/local/"):
            continue
        if rel.parts[0] in IGNORED_TOP_LEVEL or (
            any(part in IGNORED_PARTS for part in rel.parts)
            and not _preserved_logs_path(rel)
        ):
            continue
        if mode == "partial" and any(rel_text == prefix or rel_text.startswith(prefix + "/") for prefix in PARTIAL_EXCLUDES):
            continue
        directories.add(rel)
    return sorted(directories, key=lambda path: path.as_posix())


def prepare(mode: str) -> dict[str, list[str]]:
    selected = MODES if mode == "both" else (mode,)
    manifest = _load_manifest()
    packages = manifest.setdefault("packages", {})
    package_directories = manifest.setdefault("package_directories", {})
    for selected_mode in selected:
        package_root = PACKAGES_ROOT / selected_mode
        if package_root.exists():
            shutil.rmtree(package_root)
        directories = _relative_directories(selected_mode)
        for rel in directories:
            (package_root / rel).mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        for rel in _relative_files(selected_mode):
            target = package_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, target)
            copied.append(rel.as_posix())
        packages[selected_mode] = copied
        package_directories[selected_mode] = [rel.as_posix() for rel in directories]
    INSTALL_ROOT.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    clean_manifest = json.dumps(
        {"format_version": 1, "packages": {}, "package_directories": {}},
        indent=2,
    ) + "\n"
    for selected_mode in selected:
        packaged_manifest = PACKAGES_ROOT / selected_mode / ".install/manifest.json"
        packaged_manifest.parent.mkdir(parents=True, exist_ok=True)
        packaged_manifest.write_text(clean_manifest, encoding="utf-8")
    return {name: packages[name] for name in selected}


def _load_manifest() -> dict:
    if not MANIFEST_PATH.is_file():
        return {"format_version": 1, "packages": {}, "package_directories": {}}
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("manifest must be a JSON object")
    return data


def check(require_packages: bool = False) -> dict[str, int]:
    missing = [path for path in ("install.py", ".install/README.md", ".install/manifest.json") if not (ROOT / path).is_file()]
    if missing:
        raise RuntimeError("migration infrastructure is incomplete: " + ", ".join(missing))
    manifest = _load_manifest()
    packages = manifest.get("packages", {})
    package_directories = manifest.get("package_directories", {})
    if not isinstance(packages, dict) or not isinstance(package_directories, dict):
        raise RuntimeError("manifest packages and package_directories must be JSON objects")
    if require_packages and any(mode not in packages or mode not in package_directories for mode in MODES):
        raise RuntimeError("both full and partial packages and directories must be prepared")
    counts: dict[str, int] = {}
    for mode, files in packages.items():
        if mode not in MODES or not isinstance(files, list):
            raise RuntimeError(f"invalid package entry: {mode}")
        directories = package_directories.get(mode)
        if not isinstance(directories, list):
            raise RuntimeError(f"invalid package directory entry: {mode}")
        missing_files = [rel for rel in files if not (PACKAGES_ROOT / mode / rel).is_file()]
        if missing_files:
            raise RuntimeError(f"{mode} package files missing: {missing_files[:5]}")
        missing_directories = [rel for rel in directories if not (PACKAGES_ROOT / mode / rel).is_dir()]
        if missing_directories:
            raise RuntimeError(f"{mode} package directories missing: {missing_directories[:5]}")
        if "output" not in directories:
            raise RuntimeError(f"{mode} package must preserve the empty output directory")
        forbidden_files = [rel for rel in files if rel in FORBIDDEN_FILES]
        if forbidden_files:
            raise RuntimeError(f"{mode} package contains WFB reference docs: {forbidden_files[:5]}")
        if mode == "partial":
            forbidden = [rel for rel in files if any(rel == prefix or rel.startswith(prefix + "/") for prefix in PARTIAL_EXCLUDES)]
            forbidden_directories = [
                rel
                for rel in directories
                if any(rel == prefix or rel.startswith(prefix + "/") for prefix in PARTIAL_EXCLUDES)
            ]
            if forbidden or forbidden_directories:
                raise RuntimeError(
                    f"partial package contains tools/checkers: {(forbidden + forbidden_directories)[:5]}"
                )
        counts[mode] = len(files)
    return counts


def deploy(output: Path, mode: str, force: bool) -> int:
    check(require_packages=True)
    source = PACKAGES_ROOT / mode
    manifest = _load_manifest()
    files = manifest["packages"][mode]
    directories = manifest["package_directories"][mode]
    output = output.expanduser().resolve()
    if output == ROOT or ROOT in output.parents:
        raise RuntimeError("output must be outside the source workflow")
    conflicts = [output / rel for rel in files if (output / rel).exists()]
    if conflicts and not force:
        raise RuntimeError(f"target files already exist: {conflicts[:5]}; use --force to overwrite")
    for rel in directories:
        (output / rel).mkdir(parents=True, exist_ok=True)
    for rel in files:
        target = output / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / rel, target)
    return len(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare or deploy this workflow. Full migration includes tools and checkers; "
            "partial migration excludes their implementations, specs, tests, and internal checkers."
        )
    )
    parser.add_argument("-o", "--output", help="Target directory for deployment.")
    parser.add_argument("--mode", choices=MODES, default="full", help="Deployment package to use.")
    parser.add_argument("--prepare", choices=("full", "partial", "both"), help="Refresh migration package snapshots.")
    parser.add_argument("--check", action="store_true", help="Validate migration infrastructure and existing packages.")
    parser.add_argument("--force", action="store_true", help="Overwrite conflicting target files.")
    args = parser.parse_args(argv)
    try:
        if args.prepare:
            result = prepare(args.prepare)
            print("prepared packages: " + ", ".join(f"{name}={len(files)} files" for name, files in result.items()))
        if args.check:
            counts = check()
            print("migration package check passed: " + (", ".join(f"{name}={count}" for name, count in counts.items()) or "no snapshots prepared"))
        if args.output:
            count = deploy(Path(args.output), args.mode, args.force)
            print(f"deployed {args.mode} package to {Path(args.output).expanduser().resolve()}: {count} files")
        if not args.prepare and not args.check and not args.output:
            parser.error("one of --prepare, --check, or --output is required")
    except Exception as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


WORKFLOW_INSTALL_README = r'''# Workflow Migration Package

This directory stores portable snapshots prepared by the workflow's `install.py`.

## Prepare Final Packages

Run this after tools, checkers, runtime config, Guide_Doc, user docs, and
requirements.txt are final:

```bash
python install.py --prepare both
python install.py --check
```

## Deploy

Full migration includes the complete workflow, including `tools/`, `checkers/`, and
their `.workflow` specs, tests, and internal checkers:

```bash
python install.py -o /path/to/target --mode full
```

Partial migration carries the workflow structure, runtime config, Makefile,
Guide_Doc, docs, requirements.txt, input/example, and migration installer, but
excludes tools and checkers:

```bash
python install.py -o /path/to/target --mode partial
```

A partial deployment may still contain registrations in `config.yaml`. Regenerate
or restore the omitted tools and checkers before running that deployed workflow.
Existing target files are protected unless `--force` is supplied.
'''


WORKFLOW_INSTALL_MANIFEST = r'''{
  "format_version": 1,
  "packages": {}
}
'''


READ_TEXT_FILE_TOOL_SPEC = r'''name: read_text_file_tool
description: "读取工作流目录内的文本文件，并返回文件内容、行数和字符数。"

entry:
  file: tools/read_text_file_tool.py
  class_name: ReadTextFileTool
  method: run

inputs:
  - name: path
    type: path
    required: true
    description: "需要读取的文本文件路径，相对于工作流根目录。"

outputs:
  type: dict
  required_keys:
    - ok
    - data
    - errors
    - warnings
    - meta
  data_required_keys:
    - content
    - line_count
    - char_count

tests:
  - name: basic_read
    input:
      path: input/example/README.md
    expected:
      ok: true
      return_type: dict
      required_keys:
        - ok
        - data
        - errors
        - warnings
        - meta
      data_required_keys:
        - content
        - line_count
        - char_count
'''


READ_TEXT_FILE_TOOL = r'''# -*- coding: utf-8 -*-
from pathlib import Path


class ReadTextFileTool:
    name = "read_text_file_tool"
    description = "读取工作流目录内的文本文件，并返回文件内容、行数和字符数。"

    input_schema = {
        "path": {
            "type": "path",
            "required": True,
            "description": "需要读取的文本文件路径，相对于工作流根目录。",
        }
    }

    output_schema = {
        "type": "dict",
        "required_keys": ["ok", "data", "errors", "warnings", "meta"],
        "data_required_keys": ["content", "line_count", "char_count"],
    }

    def __init__(self, root_dir="."):
        self.root_dir = Path(root_dir).resolve()

    def _safe_resolve(self, path):
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"Unsafe path outside workflow root: {path}")
        target = (self.root_dir / candidate).resolve()
        if target != self.root_dir and not str(target).startswith(str(self.root_dir) + "/"):
            raise ValueError(f"Unsafe path outside workflow root: {path}")
        return target

    def run(self, path: str) -> dict:
        try:
            target = self._safe_resolve(path)
            if not target.exists():
                return {
                    "ok": False,
                    "data": {},
                    "errors": [{"code": "READ-FILE-001", "message": f"File not found: {path}"}],
                    "warnings": [],
                    "meta": {"path": path},
                }
            if not target.is_file():
                return {
                    "ok": False,
                    "data": {},
                    "errors": [{"code": "READ-FILE-002", "message": f"Path is not a file: {path}"}],
                    "warnings": [],
                    "meta": {"path": path},
                }
            content = target.read_text(encoding="utf-8")
            return {
                "ok": True,
                "data": {
                    "content": content,
                    "line_count": len(content.splitlines()),
                    "char_count": len(content),
                },
                "errors": [],
                "warnings": [],
                "meta": {"path": path},
            }
        except Exception as exc:
            return {
                "ok": False,
                "data": {},
                "errors": [{"code": "READ-FILE-999", "message": str(exc)}],
                "warnings": [],
                "meta": {"path": path},
            }
'''


def generate_docs_quickstart(data: dict[str, Any]) -> str:
    contract = data.get("runtime_contract", {})
    target = str(contract.get("example_target", "example"))
    input_root = str(contract.get("input_root", "input"))
    output_root = str(contract.get("output_root", "output"))
    required = "\n".join(
        f"- `{path}/`" if kind == "directory" else f"- `{path}`"
        for path, kind, _ in _runtime_required_inputs(data)
    )
    return f"""# 快速启动

The bundled example is ready under `{input_root}/{target}/`.
It contains the same required inputs as every real target:

{required}

```bash
make configure
make configure-check
make check
make check_example
make run TARGET={target}
```

Runtime inputs belong in `{input_root}/<TARGET>/`; generated artifacts belong in
`{output_root}/<TARGET>/`. For automated deployment use
`python setup.py --non-interactive --set KEY=VALUE`. Machine-local values are
stored outside migration packages; credentials must remain in runtime environment
variables.
"""


def generate_ucagent_setup(data: dict[str, Any]) -> str:
    return """#!/usr/bin/env bash

# BEGIN WORKFLOW ENVIRONMENT (generated by setup.py)
export UCAGENT_HOME="${UCAGENT_HOME:-$HOME/FDocB/UCAgent}"
export UCAGENT_VENV="${UCAGENT_VENV:-$UCAGENT_HOME/.venv}"
export WORKFLOW_BUILD_PROXY_ENABLED="${WORKFLOW_BUILD_PROXY_ENABLED:-0}"
export WORKFLOW_BUILD_HTTP_PROXY="${WORKFLOW_BUILD_HTTP_PROXY:-}"
export WORKFLOW_BUILD_HTTPS_PROXY="${WORKFLOW_BUILD_HTTPS_PROXY:-$WORKFLOW_BUILD_HTTP_PROXY}"
# END WORKFLOW ENVIRONMENT (generated by setup.py)

ucagent_env() {
    export PATH="$UCAGENT_VENV/bin:$PATH"
    export PYTHON="$UCAGENT_VENV/bin/python"
    export PYTHON_EXECUTABLE="$UCAGENT_VENV/bin/python"
    export PYTHONPATH="$UCAGENT_HOME${PYTHONPATH:+:$PYTHONPATH}"
}

proxy_on() {
    # httpx/OpenAI clients may reject an inherited socks:// ALL_PROXY even when
    # HTTP(S)_PROXY is otherwise valid. The generated workflow never consumes
    # ALL_PROXY, so sanitize it before either the enabled or disabled branch.
    unset all_proxy ALL_PROXY
    if [ "${WORKFLOW_BUILD_PROXY_ENABLED:-0}" = "0" ]; then
        return
    fi
    if [ -z "${WORKFLOW_BUILD_HTTP_PROXY:-}" ]; then
        echo "proxy is enabled but WORKFLOW_BUILD_HTTP_PROXY is empty" >&2
        return 2
    fi
    export http_proxy="$WORKFLOW_BUILD_HTTP_PROXY"
    export https_proxy="${WORKFLOW_BUILD_HTTPS_PROXY:-$http_proxy}"
    export HTTP_PROXY="$http_proxy"
    export HTTPS_PROXY="$https_proxy"
}
"""


def generate_environment_schema(data: dict[str, Any]) -> str:
    return yaml_dump(
        {
            "format_version": 1,
            "settings": {
                "ucagent_home": {
                    "description": "UCAgent source directory",
                    "type": "path",
                    "required": True,
                    "default": "~/FDocB/UCAgent",
                    "environment": "UCAGENT_HOME",
                    "targets": ["makefile", "shell"],
                    "variable": "UCAGENT_HOME",
                },
                "ucagent_venv": {
                    "description": "UCAgent Python virtual environment",
                    "type": "path",
                    "required": True,
                    "default": "~/FDocB/UCAgent/.venv",
                    "environment": "UCAGENT_VENV",
                    "targets": ["makefile", "shell"],
                    "variable": "UCAGENT_VENV",
                },
                "python": {
                    "description": "Python executable used by the workflow",
                    "type": "executable",
                    "required": True,
                    "default": "python3",
                    "environment": "PYTHON",
                    "targets": ["makefile"],
                    "variable": "PYTHON",
                },
                "tmux": {
                    "description": "tmux executable",
                    "type": "executable",
                    "required": False,
                    "default": "tmux",
                    "targets": [],
                    "variable": "TMUX",
                },
                "mcp_server_port": {
                    "description": "MCP server port; -1 disables the optional MCP server",
                    "type": "integer",
                    "required": True,
                    "default": -1,
                    "targets": ["makefile"],
                    "variable": "MCP_SERVER_PORT",
                },
                "proxy_enabled": {
                    "description": "Enable HTTP/HTTPS proxy export",
                    "type": "boolean",
                    "required": True,
                    "default": False,
                    "environment": "WORKFLOW_BUILD_PROXY_ENABLED",
                    "targets": ["shell"],
                    "variable": "WORKFLOW_BUILD_PROXY_ENABLED",
                },
                "http_proxy": {
                    "description": "HTTP proxy without embedded credentials",
                    "type": "string",
                    "required": False,
                    "default": "",
                    "targets": ["shell"],
                    "variable": "WORKFLOW_BUILD_HTTP_PROXY",
                    "reject_credentials": True,
                },
                "https_proxy": {
                    "description": "HTTPS proxy without embedded credentials",
                    "type": "string",
                    "required": False,
                    "default": "",
                    "targets": ["shell"],
                    "variable": "WORKFLOW_BUILD_HTTPS_PROXY",
                    "reject_credentials": True,
                },
            },
        }
    )


WORKFLOW_ENVIRONMENT_SETUP = r'''#!/usr/bin/env python3
"""Configure machine-local settings for this generated workflow."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import yaml


ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / "config/environment.schema.yaml"
LOCAL_PATH = ROOT / ".workflow/local/environment.yaml"
MAKEFILE_PATH = ROOT / "Makefile"
SETUP_PATH = ROOT / "ucagent_setup.sh"
BEGIN = "# BEGIN WORKFLOW ENVIRONMENT (generated by setup.py)"
END = "# END WORKFLOW ENVIRONMENT (generated by setup.py)"


def load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value}")


def coerce(name: str, value: object, spec: dict) -> object:
    kind = spec.get("type", "string")
    if kind == "boolean":
        return parse_bool(value)
    if kind == "integer":
        return int(value)
    text = str(value).strip()
    if "\n" in text or "\r" in text or "\x00" in text:
        raise ValueError(f"{name} contains forbidden control characters")
    if spec.get("reject_credentials") and text:
        parsed = urlsplit(text)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError(f"{name} must not contain proxy credentials; use runtime environment variables")
    return text


def effective_values(settings: dict, saved: dict) -> dict:
    values = {}
    for name, spec in settings.items():
        if not isinstance(spec, dict):
            raise ValueError(f"schema setting {name} must be a mapping")
        env_name = str(spec.get("environment", "")).strip()
        raw = saved.get(name)
        if raw is None and env_name and env_name in os.environ:
            raw = os.environ[env_name]
        if raw is None:
            raw = spec.get("default", "")
        values[name] = coerce(name, raw, spec)
    unknown = sorted(set(saved) - set(settings))
    if unknown:
        raise ValueError("unknown settings: " + ", ".join(unknown))
    return values


def validate(settings: dict, values: dict) -> list[str]:
    errors = []
    for name, spec in settings.items():
        value = values[name]
        text = str(value).strip()
        if spec.get("required") and text == "":
            errors.append(f"{name}: required value is empty")
            continue
        kind = spec.get("type")
        if kind == "path" and text:
            path = Path(os.path.expandvars(text)).expanduser()
            if not path.exists():
                errors.append(f"{name}: path does not exist: {path}")
        elif kind == "executable" and text:
            candidate = Path(os.path.expandvars(text)).expanduser()
            found = candidate.is_file() if candidate.parent != Path(".") else shutil.which(text) is not None
            if not found and spec.get("required"):
                errors.append(f"{name}: executable not found: {text}")
    if values.get("proxy_enabled"):
        http_proxy = str(values.get("http_proxy", "")).strip()
        https_proxy = str(values.get("https_proxy", "")).strip()
        if not http_proxy:
            errors.append("http_proxy: required when proxy_enabled=true")
        for name, value in (("http_proxy", http_proxy), ("https_proxy", https_proxy)):
            if value and urlsplit(value).scheme not in {"http", "https"}:
                errors.append(f"{name}: proxy URL must use http or https")
    return errors


def make_value(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value).replace("$", "$$").replace("#", r"\#")


def render_blocks(settings: dict, values: dict) -> tuple[str, str]:
    make_lines = [BEGIN]
    shell_lines = [BEGIN]
    for name, spec in settings.items():
        if spec.get("sensitive"):
            if spec.get("targets"):
                raise ValueError(f"{name}: sensitive settings cannot render into files")
            continue
        variable = str(spec.get("variable", name.upper()))
        targets = spec.get("targets", [])
        value = values[name]
        if "makefile" in targets:
            make_lines.append(f"{variable} ?= {make_value(value)}")
        if "shell" in targets:
            shell_value = "1" if value is True else "0" if value is False else str(value)
            escaped = shell_value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
            shell_lines.append(f'export {variable}="${{{variable}:-{escaped}}}"')
    make_lines.append(END)
    shell_lines.append(END)
    return "\n".join(make_lines), "\n".join(shell_lines)


def replace_block(text: str, block: str, path: Path) -> str:
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise ValueError(f"{path} must contain exactly one environment block")
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
    return pattern.sub(lambda _: block, text, count=1)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def parse_assignments(items: list[str]) -> dict:
    result = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--set expects KEY=VALUE: {item}")
        key, value = item.split("=", 1)
        result[key.strip()] = value
    return result


def prompt(settings: dict, values: dict) -> dict:
    updated = dict(values)
    for name, spec in settings.items():
        current = updated[name]
        answer = input(f"{name} - {spec.get('description', '')} [{current}]: ").strip()
        if answer:
            updated[name] = coerce(name, answer, spec)
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Configure this workflow for the current machine.")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--config", help="Import values from a YAML mapping.")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    args = parser.parse_args(argv)
    try:
        schema = load_yaml(SCHEMA_PATH)
        settings = schema.get("settings")
        if not isinstance(settings, dict) or not settings:
            raise ValueError("environment schema must define a non-empty settings mapping")
        saved_data = load_yaml(LOCAL_PATH)
        saved = saved_data.get("values", saved_data)
        if not isinstance(saved, dict):
            raise ValueError("local environment values must be a mapping")
        if args.config:
            imported = load_yaml(Path(args.config))
            imported = imported.get("values", imported)
            if not isinstance(imported, dict):
                raise ValueError("imported environment values must be a mapping")
            saved.update(imported)
        saved.update(parse_assignments(args.set))
        values = effective_values(settings, saved)
        if not args.non_interactive and not args.check and sys.stdin.isatty():
            values = prompt(settings, values)
        errors = validate(settings, values)
        if errors:
            raise ValueError("\n".join(errors))
        make_block, shell_block = render_blocks(settings, values)
        make_text = replace_block(MAKEFILE_PATH.read_text(encoding="utf-8"), make_block, MAKEFILE_PATH)
        setup_text = replace_block(SETUP_PATH.read_text(encoding="utf-8"), shell_block, SETUP_PATH)
        if args.check:
            print("environment configuration is valid")
            return 0
        if args.dry_run:
            print(make_block)
            print(shell_block)
            return 0
        persistable = {
            name: value
            for name, value in values.items()
            if not settings[name].get("sensitive", False)
        }
        atomic_write(LOCAL_PATH, yaml.safe_dump({"format_version": 1, "values": persistable}, sort_keys=False))
        atomic_write(MAKEFILE_PATH, make_text)
        atomic_write(SETUP_PATH, setup_text)
        print(f"environment configured; local values: {LOCAL_PATH.relative_to(ROOT)}")
        return 0
    except Exception as exc:
        print(f"environment setup failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
'''


def generate_input_readme(data: dict[str, Any]) -> str:
    contract = data.get("runtime_contract", {})
    target = str(contract.get("example_target", "example"))
    required = "\n".join(
        f"- `{path}/`" if kind == "directory" else f"- `{path}`"
        for path, kind, _ in _runtime_required_inputs(data)
    )
    return f"""# Input

Create one directory per target. Use `input/{target}/` as the runnable bundled
example. Every target must contain:

{required}

Keep paths referenced by input manifests relative to the target directory.
Do not require users to provide information that the workflow is responsible
for deriving.
"""


def generate_input_example_readme(data: dict[str, Any]) -> str:
    target = str(data.get("runtime_contract", {}).get("example_target", "example"))
    required = "\n".join(
        f"- `{path}/`" if kind == "directory" else f"- `{path}`"
        for path, kind, _ in _runtime_required_inputs(data)
    )
    return f"""# Bundled Example

This directory is a directly runnable input fixture for `make check_example` and
`make run TARGET={target}`.

Required example content:

{required}
"""


def generate_input_example_init(data: dict[str, Any]) -> str:
    return '"""Bundled example package used by the generated workflow."""\n'


def generate_output_readme(data: dict[str, Any]) -> str:
    return """# Output

Generated artifacts are written under `output/<TARGET>/`. Runtime output is not
part of the source input contract or migration history.
"""


def generate_docs_readme(data: dict[str, Any]) -> str:
    return """# 用户文档

本目录保存面向工作流使用者和后续开发者的完整说明。`01快速启动.md` 提供最短可执行
路径，`02输入输出.md` 解释运行契约，`03步骤及检查.md` 说明业务阶段和 Checker，
`04开发者文档-tools.md` 与 `05开发者文档-checkers.md` 分别说明工具和检查器的维护
方式。完整生成阶段会根据实际工作流组件扩展并重写这些初始文档。
首次运行和跨系统迁移还必须说明 `setup.py`、`make configure` 与
`make configure-check` 的环境配置流程。
"""


def generate_docs_input_output(data: dict[str, Any]) -> str:
    required = "\n".join(
        f"- `{path}/`" if kind == "directory" else f"- `{path}`"
        for path, kind, _ in _runtime_required_inputs(data)
    )
    return f"""# 输入输出

每个运行目标的输入位于 `input/<TARGET>/`，必须包含：

{required}

可运行示例位于 `input/example/`。工作流生成的全部业务结果写入
`output/<TARGET>/`，不得修改用户输入。完整生成阶段会补充每项输入格式、输出结构、
错误处理和兼容约束。

系统环境声明位于 `config/environment.schema.yaml`，本机非敏感取值由 `setup.py`
保存到 `.workflow/local/environment.yaml`。该文件不是业务输入，也不会进入迁移包；
Token、密码及带认证信息的代理只能通过运行时环境变量提供。
"""


def generate_docs_stages(data: dict[str, Any]) -> str:
    stages = _format_named_items(data.get("workflow_spec", {}).get("stages", []))
    return f"""# 步骤及检查

以下是骨架阶段清单：

{stages}

完整生成阶段会为每个步骤补充目的、输入、输出、调用工具、Checker 判定条件、失败证据
和恢复方式，确保用户能够定位每一次失败。
"""


def generate_docs_developer(kind: str) -> str:
    noun = "工具" if kind == "tools" else "Checker"
    return f"""# 开发者文档 - {noun}

当前文件是初始化占位说明。完整生成阶段会逐个记录全部业务{noun}的职责、接口、注册
位置、调用阶段、依赖、修改方法、测试夹具和回归命令。每个{noun}必须拥有独立且不少于
三百个有效正文字符的说明，并结合真实实现分析入口、关键代码、调用路径、字段、分支、
异常和扩展点；禁止只列名称或复制实现代码代替设计解释。
"""


def generate_requirements_txt(data: dict[str, Any]) -> str:
    return """# Python dependencies required by the generated workflow.
# The complete generation stage replaces this scaffold with exact packages and versions.
PyYAML>=6.0
pydantic>=2.0

# System prerequisite: UCAgent
# Installation: install the project runtime and create its virtual environment per UCAgent documentation.
"""


def render_file_by_template(path: str, template: str, data: dict[str, Any], report: BuildReport) -> str:
    if path == "README.md" or template == "readme_basic":
        return generate_readme(data)
    if path == "Makefile" or template == "makefile_basic":
        return generate_makefile(data)
    if path == "config.yaml" or template in {"config_basic", "config_inc_basic", "config_empty_basic"}:
        return generate_runtime_config(data)
    if path == "Guide_Doc/overview.md" or template == "guidedoc_overview":
        return generate_guidedoc_overview(data)
    if path == "Guide_Doc/tool_generation.md" or template == "guidedoc_tool_generation":
        return generate_guidedoc_tool_generation(data)
    if path == "Guide_Doc/checker_generation.md" or template == "guidedoc_checker_generation":
        return generate_guidedoc_checker_generation(data)
    if path == "Guide_Doc/operation.md" or template == "guidedoc_operation":
        return generate_guidedoc_operation(data)
    if path == "Guide_Doc/environment_setup.md" or template == "guidedoc_environment_setup":
        return generate_guidedoc_environment_setup(data)
    if template == "resource_template":
        return generate_resource_template(data)
    if template == "suggestion_template":
        return generate_suggestion_template(data)
    if path == "input/example/input_example.json" or template == "json_empty":
        return generate_input_example(data)
    if path == "requirements.txt" or template == "requirements_txt":
        return generate_requirements_txt(data)
    if path == "setup.py" or template == "workflow_environment_setup":
        return WORKFLOW_ENVIRONMENT_SETUP
    if path == "config/environment.schema.yaml" or template == "environment_schema":
        return generate_environment_schema(data)
    if path == "ucagent_setup.sh" or template == "ucagent_setup":
        return generate_ucagent_setup(data)
    if path == "input/README.md" or template == "input_readme":
        return generate_input_readme(data)
    if path == "input/example/README.md" or template == "input_example_readme":
        return generate_input_example_readme(data)
    if path == "input/example/data/__init__.py" or template == "init_py":
        return generate_input_example_init(data)
    if path == "output/README.md" or template == "output_readme":
        return generate_output_readme(data)
    if path == "docs/README.md" or template == "docs_readme":
        return generate_docs_readme(data)
    if path == "docs/01快速启动.md" or template == "docs_quickstart":
        return generate_docs_quickstart(data)
    if path == "docs/02输入输出.md" or template == "docs_input_output":
        return generate_docs_input_output(data)
    if path == "docs/03步骤及检查.md" or template == "docs_stages_checks":
        return generate_docs_stages(data)
    if path == "docs/04开发者文档-tools.md" or template == "docs_developer_tools":
        return generate_docs_developer("tools")
    if path == "docs/05开发者文档-checkers.md" or template == "docs_developer_checkers":
        return generate_docs_developer("checkers")
    if path == ".workflow/tool_specs/read_text_file_tool.yaml" or template == "read_text_file_tool_spec":
        return READ_TEXT_FILE_TOOL_SPEC
    if path == "tools/read_text_file_tool.py" or template == "read_text_file_tool":
        return READ_TEXT_FILE_TOOL
    if path == ".workflow/workflow_spec.yaml" or template == "workflow_spec_basic":
        return generate_workflow_spec(data)
    if path == ".workflow/acceptance_rules.yaml" or template == "acceptance_rules_basic":
        return yaml_dump(runtime_acceptance(data))
    if path == ".workflow/checkers/tool_spec_checker.py" or template == "tool_spec_checker":
        return TOOL_SPEC_CHECKER
    if path == ".workflow/checkers/config_syntax_checker.py" or template == "checker_config_syntax":
        return CONFIG_SYNTAX_CHECKER
    if path == ".workflow/checkers/layout_checker.py" or template == "checker_layout":
        return LAYOUT_CHECKER
    if path == ".workflow/checkers/guidedoc_basic_checker.py" or template == "checker_guidedoc_basic":
        return GUIDEDOC_BASIC_CHECKER
    if path == ".workflow/checkers/tool_static_checker.py" or template == "tool_static_checker":
        return TOOL_STATIC_CHECKER
    if path == ".workflow/checkers/tool_direct_runner.py" or template == "tool_direct_runner":
        return TOOL_DIRECT_RUNNER
    if path == ".workflow/checkers/checker_spec_checker.py" or template == "checker_spec_checker":
        return CHECKER_SPEC_CHECKER
    if path == ".workflow/checkers/checker_static_checker.py" or template == "checker_static_checker":
        return CHECKER_STATIC_CHECKER
    if path == ".workflow/checkers/checker_direct_runner.py" or template == "checker_direct_runner":
        return CHECKER_DIRECT_RUNNER
    if path == "tools/mcp_adapters.py" or template == "mcp_tool_adapters":
        return MCP_TOOL_ADAPTERS
    if path == ".workflow/tool_tests/run_mcp_tests.py" or template == "mcp_tool_test_runner":
        return MCP_TOOL_TEST_RUNNER
    if path == "install.py" or template in {"workflow_installer", "install_basic"}:
        return WORKFLOW_INSTALLER
    if path == ".install/README.md" or template == "workflow_install_readme":
        return WORKFLOW_INSTALL_README
    if path == ".install/manifest.json" or template == "workflow_install_manifest":
        return WORKFLOW_INSTALL_MANIFEST
    if template == "empty":
        return ""
    report.warnings.append(f"Unknown template {template!r} for {path}, generated empty file.")
    return ""


def generate_internal_checkers(root: Path, overwrite: bool, report: BuildReport) -> None:
    tool_log_dir = root / ".workflow/tool_tests/logs"
    if not tool_log_dir.is_dir():
        tool_log_dir.mkdir(parents=True, exist_ok=True)
        report.created_dirs.append(".workflow/tool_tests/logs")
    write_file(root, ".workflow/checkers/config_syntax_checker.py", CONFIG_SYNTAX_CHECKER, overwrite, report)
    write_file(root, ".workflow/checkers/layout_checker.py", LAYOUT_CHECKER, overwrite, report)
    write_file(root, ".workflow/checkers/guidedoc_basic_checker.py", GUIDEDOC_BASIC_CHECKER, overwrite, report)
    write_file(root, ".workflow/checkers/tool_spec_checker.py", TOOL_SPEC_CHECKER, overwrite, report)
    write_file(root, ".workflow/checkers/tool_static_checker.py", TOOL_STATIC_CHECKER, overwrite, report)
    write_file(root, ".workflow/checkers/tool_direct_runner.py", TOOL_DIRECT_RUNNER, overwrite, report)
    write_file(root, ".workflow/checkers/checker_spec_checker.py", CHECKER_SPEC_CHECKER, overwrite, report)
    write_file(root, ".workflow/checkers/checker_static_checker.py", CHECKER_STATIC_CHECKER, overwrite, report)
    write_file(root, ".workflow/checkers/checker_direct_runner.py", CHECKER_DIRECT_RUNNER, overwrite, report)
    write_file(root, "tools/mcp_adapters.py", MCP_TOOL_ADAPTERS, overwrite, report)
    write_file(root, ".workflow/tool_tests/run_mcp_tests.py", MCP_TOOL_TEST_RUNNER, overwrite, report)
    write_file(root, "install.py", WORKFLOW_INSTALLER, overwrite, report)
    write_file(root, ".install/README.md", WORKFLOW_INSTALL_README, overwrite, report)
    write_file(root, ".install/manifest.json", WORKFLOW_INSTALL_MANIFEST, overwrite, report)


def generate_planned_business_checkers(
    root: Path,
    data: dict[str, Any],
    overwrite: bool,
    report: BuildReport,
) -> None:
    """Materialize central checker specs, implementations, fixtures, and tests."""
    try:
        from ..workflow_checker_generator.core import (
            CheckerGenerationError,
            generate_checkers_from_specs,
        )
    except ImportError:
        # Keep standalone execution from examples/workflow_builder working.
        from workflow_checker_generator.core import (
            CheckerGenerationError,
            generate_checkers_from_specs,
        )

    spec_paths: list[str] = []
    for checker in data["workflow_spec"]["checkers"]:
        spec_path = f".workflow/checker_specs/{checker['name']}.yaml"
        write_file(root, spec_path, yaml_dump(checker), overwrite, report)
        spec_paths.append(spec_path)
    try:
        checker_report = generate_checkers_from_specs(
            root,
            spec_paths,
            overwrite=overwrite,
            update_config=False,
        )
    except CheckerGenerationError as exc:
        raise WorkflowBuildError("BUILD-CHECKER-001", str(exc)) from exc
    for path in checker_report.created_files:
        if path not in report.created_files:
            report.created_files.append(path)
    report.skipped_files.extend(
        path for path in checker_report.skipped_files if path not in report.skipped_files
    )


def build_workflow(config_path: str | Path, base_dir: str | Path | None = None) -> BuildReport:
    config_path = Path(config_path)
    if base_dir is None:
        base_dir = Path.cwd()
    base_dir = Path(base_dir)
    data = load_yaml_config(config_path)
    validate_build_config(data)
    root = check_path_safety(data, base_dir)
    report = BuildReport(
        workflow_name=data["workflow"]["name"],
        version=data["workflow"]["version"],
        root_path=str(root),
        build_config_path=str(config_path),
    )

    overwrite = bool(data["root"]["overwrite"])
    try:
        create_directories(root, data, report)
        for group_name in ("public", "internal"):
            for item in data["files"][group_name]:
                rel_path = item["path"]
                if rel_path == ".workflow/build_report.md":
                    continue
                content = render_file_by_template(rel_path, item.get("template", "empty"), data, report)
                write_file(root, rel_path, content, overwrite, report)
        ensure_runtime_example(root, data, overwrite, report)
        generate_internal_checkers(root, overwrite, report)
        generate_planned_business_checkers(root, data, overwrite, report)
        write_file(root, ".workflow/build_report.md", generate_build_report(report), True, report)
    except WorkflowBuildError:
        raise
    except Exception as exc:
        report.errors.append(str(exc))
        raise WorkflowBuildError("FILE-001", f"文件创建失败: {exc}") from exc
    return report


def cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a workflow skeleton from workflow_build.yaml")
    parser.add_argument("config", help="Path to workflow_build.yaml")
    parser.add_argument("--base-dir", default=None, help="Base directory for root.path resolution")
    args = parser.parse_args(argv)
    try:
        report = build_workflow(args.config, args.base_dir)
    except WorkflowBuildError as exc:
        print(str(exc))
        return 1
    print(f"[workflow_builder] generated: {report.root_path}")
    print(f"[workflow_builder] created files: {len(report.created_files)}")
    print(f"[workflow_builder] created dirs: {len(report.created_dirs)}")
    return 0
