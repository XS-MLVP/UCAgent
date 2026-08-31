# -*- coding: utf-8 -*-
"""Regression coverage for generator safety and stable documentation contracts."""

from __future__ import annotations

import tempfile
import subprocess
import sys
from pathlib import Path

import yaml

from examples.workflow_builder.tools.workflow_builder.command_runner import WorkflowCommandError, run_restricted_command
from examples.workflow_builder.tools.workflow_builder.core import TOOL_SPEC_CHECKER
from examples.workflow_builder.tools.workflow_builder.plan_contract import append_record, validate_records
from examples.workflow_builder.tools.workflow_guidedoc_generator.core import generate_guidedocs
from examples.workflow_builder.tools.workflow_tool_generator.core import (
    ToolGenerationError,
    generate_tools,
    generate_tools_from_specs,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _plan_body() -> str:
    detail = (
        "本阶段记录真实决策、输入输出、验证证据和失败处理，并说明对后续阶段的约束。"
        "所有结论都来自实际文件和命令结果，不使用推测替代验证。"
    ) * 6
    return "\n".join(
        [
            "### 阶段目标",
            detail,
            "### 决策与变更",
            detail,
            "### 产物与验证证据",
            detail,
            "### 问题与处理",
            detail,
            "### 后续约束",
            detail,
        ]
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="workflow_builder_stability_") as temp:
        root = Path(temp)
        _write(root / "config.yaml", "tools: {}\nguide_docs: []\n")
        (root / "tmp").mkdir()

        initial = generate_tools(
            root,
            tool_names=["run_command_tool"],
            existing_policy="create_only",
        )
        assert "tools/run_command_tool.py" in initial.created_files
        source = root / "tools/run_command_tool.py"
        pristine = source.read_text(encoding="utf-8")
        source.write_text(pristine + "\n# user implementation\n", encoding="utf-8")

        preserved = generate_tools(
            root,
            tool_names=["run_command_tool"],
            existing_policy="create_only",
        )
        assert "tools/run_command_tool.py" in preserved.skipped_files
        assert source.read_text(encoding="utf-8").endswith("# user implementation\n")

        try:
            generate_tools(
                root,
                tool_names=["run_command_tool"],
                existing_policy="refresh_scaffold",
            )
        except ToolGenerationError as exc:
            assert exc.code == "TOOL-GEN-CONFLICT-001"
        else:
            raise AssertionError("refresh_scaffold replaced a modified implementation")

        replaced = generate_tools(
            root,
            tool_names=["run_command_tool"],
            existing_policy="force_replace",
        )
        assert "tools/run_command_tool.py" in replaced.replaced_files
        assert source.read_text(encoding="utf-8") == pristine
        refreshed = generate_tools(
            root,
            tool_names=["run_command_tool"],
            existing_policy="refresh_scaffold",
        )
        assert "tools/run_command_tool.py" in refreshed.refreshed_files

        tool_spec_path = root / ".workflow/tool_specs/business_tool.yaml"
        tool_spec = {
            "name": "business_tool",
            "description": "验证测试基线保护。",
            "entry": {
                "file": "tools/business_tool.py",
                "class_name": "BusinessTool",
                "method": "run",
            },
            "inputs": [{"name": "path", "type": "path", "required": True}],
            "outputs": {
                "type": "dict",
                "required_keys": ["ok", "data", "errors", "warnings", "meta"],
            },
            "tests": [
                {
                    "name": "basic",
                    "input": {"path": "input/example/data.txt"},
                    "expected": {"ok": True},
                }
            ],
        }
        _write(tool_spec_path, yaml.safe_dump(tool_spec, allow_unicode=True, sort_keys=False))
        generate_tools_from_specs(
            root,
            [".workflow/tool_specs/business_tool.yaml"],
            existing_policy="create_only",
        )
        tool_spec["tests"][0]["expected"]["ok"] = False
        _write(tool_spec_path, yaml.safe_dump(tool_spec, allow_unicode=True, sort_keys=False))
        try:
            generate_tools_from_specs(
                root,
                [".workflow/tool_specs/business_tool.yaml"],
                existing_policy="create_only",
            )
        except ToolGenerationError as exc:
            assert exc.code == "TOOL-GEN-TEST-002"
        else:
            raise AssertionError("generator accepted a rewritten frozen test")
        checker_path = root / ".workflow/checkers/tool_spec_checker.py"
        _write(checker_path, TOOL_SPEC_CHECKER)
        rejected = subprocess.run(
            [sys.executable, str(checker_path), str(tool_spec_path)],
            cwd=root,
            text=True,
            capture_output=True,
        )
        assert rejected.returncode == 1
        assert "TOOL-SPEC-014" in rejected.stdout
        tool_spec["tests"][0]["expected"]["ok"] = True
        _write(tool_spec_path, yaml.safe_dump(tool_spec, allow_unicode=True, sort_keys=False))
        accepted = subprocess.run(
            [sys.executable, str(checker_path), str(tool_spec_path)],
            cwd=root,
            text=True,
            capture_output=True,
        )
        assert accepted.returncode == 0, accepted.stdout + accepted.stderr

        _write(root / "tmp/check.py", "print('restricted-ok')\n")
        command_result = run_restricted_command(root, "python3 tmp/check.py")
        assert command_result["ok"] is True
        assert "restricted-ok" in command_result["stdout"]
        safe_make_targets = (
            "help",
            "clean",
            "plan",
            "package",
            "check_input",
            "check_example",
            "check_package",
        )
        _write(
            root / "Makefile",
            ".PHONY: " + " ".join(safe_make_targets) + "\n"
            + "\n".join(f"{target}:\n\t@true" for target in safe_make_targets)
            + "\n",
        )
        clean_result = run_restricted_command(root, "make clean")
        assert clean_result["ok"] is True
        for target in safe_make_targets:
            make_result = run_restricted_command(root, f"make {target}")
            assert make_result["ok"] is True, (target, make_result)
        _write(root / "outside.py", "print('not-allowed')\n")
        for command in ("python3 outside.py", "make unknown", "python3 -c print(1)"):
            try:
                run_restricted_command(root, command)
            except WorkflowCommandError:
                pass
            else:
                raise AssertionError(f"restricted command unexpectedly passed: {command}")

        spec_path = root / ".workflow/guidedoc_specs/operation.yaml"
        spec = {
            "title": "运行说明",
            "output": "Guide_Doc/operation.md",
            "document_type": "guide_doc",
            "operation_contract": True,
            "sections": [
                {"id": "purpose", "heading": "目的", "content": "说明工作流目的。"},
                {
                    "id": "inputs",
                    "heading": "输入",
                    "content": "输入位于 input/<TARGET>/，示例位于 input/example。",
                },
                {"id": "outputs", "heading": "输出", "content": "产物写入 output/。"},
                {
                    "id": "usage",
                    "heading": "使用方法",
                    "content": (
                        "设置 TARGET，读取 input/<TARGET>/ 和 input/example，结果写入 output/；"
                        "先运行 make check_example，再运行 make run TARGET=example。"
                    ),
                },
                {"id": "execution", "heading": "执行步骤", "content": "依次执行检查与运行。"},
                {"id": "checks", "heading": "检查", "content": "检查命令退出码和产物。"},
                {"id": "failure_recovery", "heading": "失败恢复", "content": "修复错误后重新运行。"},
            ],
        }
        _write(spec_path, yaml.safe_dump(spec, allow_unicode=True, sort_keys=False))
        generate_guidedocs(root, [".workflow/guidedoc_specs/operation.yaml"])
        rendered = (root / "Guide_Doc/operation.md").read_text(encoding="utf-8")
        assert "## 目的" in rendered and "## Failure Recovery" not in rendered

        plan = append_record("# 工作流实现计划\n", "extract_requirements_and_plan", _plan_body())
        assert "## 阶段 00：extract_requirements_and_plan" in plan
        assert not validate_records(plan, "extract_requirements_and_plan")

    print("[PASS] workflow builder stability regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
