#!/usr/bin/env python3
"""Validate the maintained Workflow Builder documentation tree."""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
DOCS = REPO_ROOT / "docs" / "content" / "04_case" / "03_workflow_builder"

REQUIRED = [
    "00_index.md",
    "01_quickstart/00_overview.md",
    "01_quickstart/01_build_workflow.md",
    "01_quickstart/02_evaluate_workflow.md",
    "01_quickstart/03_incremental_workflow.md",
    "01_quickstart/04_console.md",
    "03_develop/00_overview.md",
    "03_develop/01_workflow.md",
    "03_develop/02_tools.md",
    "03_develop/03_checkers.md",
    "03_develop/04_guide_docs.md",
    "03_develop/05_evaluation_and_incremental_control.md",
    "03_develop/06_testing.md",
    "03_develop/07_generated_workflow_development.md",
    "02_usage/00_overview.md",
    "02_usage/01_input_contract.md",
    "02_usage/02_outputs_and_workspace.md",
    "02_usage/03_build_workflow.md",
    "02_usage/04_evaluation_and_approval.md",
    "02_usage/05_incremental_updates.md",
    "02_usage/06_prompt_usage.md",
    "02_usage/07_agent_prompts.md",
    "04_q_and_experience/00_overview.md",
    "04_q_and_experience/01_installation_and_environment.md",
    "04_q_and_experience/02_runtime_and_stage_failures.md",
    "04_q_and_experience/03_evaluation_and_incremental_updates.md",
    "04_q_and_experience/04_console_and_ports.md",
    "04_q_and_experience/05_performance_and_stability.md",
    "04_q_and_experience/06_workflow_design_quality.md",
]

LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
FENCED_CODE = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)
YAML_FRONT_MATTER = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)

DEVELOPER_REQUIREMENTS = {
    "00_overview.md": {
        "minimum_prose": 4482,
        "sources": ("tools/workflow_builder/core.py", "Makefile", "setup.py"),
    },
    "01_workflow.md": {
        "minimum_prose": 5004,
        "sources": (
            "tools/workflow_builder/core.py",
            "tools/workflow_config_generator/core.py",
            "tools/workflow_evaluation_control/core.py",
            "tools/workflow_evaluation_control/incremental.py",
        ),
    },
    "02_tools.md": {
        "minimum_prose": 5025,
        "sources": (
            "tools/workflow_tool_generator/core.py",
            "tools/workflow_tool_generator/templates.py",
            "tools/workflow_tool_generator/uc_tools.py",
        ),
    },
    "03_checkers.md": {
        "minimum_prose": 5166,
        "sources": (
            "tools/workflow_checker_generator/core.py",
            "tools/workflow_checker_generator/templates.py",
        ),
    },
    "04_guide_docs.md": {
        "minimum_prose": 3732,
        "sources": (
            "tools/workflow_guidedoc_generator/contract.py",
            "tools/workflow_guidedoc_generator/core.py",
        ),
    },
    "05_evaluation_and_incremental_control.md": {
        "minimum_prose": 3717,
        "sources": (
            "tools/workflow_evaluation_control/json_store.py",
            "tools/workflow_evaluation_control/approvals.py",
            "tools/workflow_evaluation_control/incremental.py",
        ),
    },
    "06_testing.md": {
        "minimum_prose": 3780,
        "sources": ("regression/Makefile", "run_delivery_contract_regression.py"),
    },
    "07_generated_workflow_development.md": {
        "minimum_prose": 6000,
        "sources": (
            "tools/workflow_builder/core.py",
            "tools/workflow_tool_generator/core.py",
            "tools/workflow_checker_generator/core.py",
        ),
    },
}

DOCUMENTED_MAKE_TARGETS = {
    "configure",
    "configure-check",
    "configure-show",
    "run",
    "run_cli",
    "run_inc",
    "run_eval",
    "run_eval_tools",
    "run_eval_checkers",
    "run_eval_flow",
    "run_eval_env",
    "run_eval_runtime_default",
    "run_eval_runtime_inc",
    "aggregate_eval",
    "eval-list",
    "eval-approve",
    "eval-suggest",
    "eval-ui",
    "session",
}


def effective_prose_length(content: str) -> int:
    """Count maintained explanation while excluding fenced source examples."""
    prose = FENCED_CODE.sub("", content)
    prose = re.sub(r"<!--.*?-->", "", prose, flags=re.DOTALL)
    return len(re.sub(r"\s+", "", prose))


def markdown_body(content: str) -> str:
    """Remove optional document metadata before checking the visible Markdown body."""
    return YAML_FRONT_MATTER.sub("", content, count=1)


def make_targets() -> set[str]:
    result = subprocess.run(
        ["make", "-prRn", "-f", str(ROOT / "Makefile")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise AssertionError(f"unable to inspect Make targets: {result.stderr}")
    return {
        match.group(1)
        for line in result.stdout.splitlines()
        if (match := re.match(r"^([A-Za-z0-9_.%-]+):(?:\s|$)", line))
    }


def load_yaml(relative: str) -> dict:
    """Load one maintained workflow config as a mapping."""
    value = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{relative}: expected a YAML mapping")
    return value


def configured_stage_names(relative: str) -> set[str]:
    """Return stage names from UCAgent's singular `stage` collection."""
    stages = load_yaml(relative).get("stage", [])
    if not isinstance(stages, list):
        raise AssertionError(f"{relative}: stage must be a list")
    return {
        name
        for item in stages
        if isinstance(item, dict)
        and isinstance((name := item.get("name")), str)
        and name
    }


def configured_checker_aliases(relative: str) -> set[str]:
    """Return every stage-local checker alias in one config."""
    aliases: set[str] = set()
    stages = load_yaml(relative).get("stage", [])
    for stage in stages if isinstance(stages, list) else []:
        if not isinstance(stage, dict):
            continue
        checkers = stage.get("checker", [])
        for checker in checkers if isinstance(checkers, list) else []:
            if isinstance(checker, dict) and isinstance(checker.get("name"), str):
                aliases.add(checker["name"])
    return aliases


def ast_classes(paths: list[Path], *, base: str | None = None, suffix: str = "") -> set[str]:
    """Inventory real class definitions without matching comments or templates."""
    names: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not node.name.endswith(suffix):
                continue
            base_names = {
                candidate.id
                for candidate in node.bases
                if isinstance(candidate, ast.Name)
            }
            if base is None or base in base_names:
                names.add(node.name)
    return names


def require_inventory(
    failures: list[str], relative: str, expected: set[str], inventory_name: str
) -> None:
    """Require a maintained document to name every source-derived item."""
    content = (DOCS / relative).read_text(encoding="utf-8")
    missing = sorted(item for item in expected if item not in content)
    if missing:
        failures.append(
            f"{relative}: missing {inventory_name} inventory entries: {missing}"
        )


def main() -> int:
    missing = [relative for relative in REQUIRED if not (DOCS / relative).is_file()]
    assert not missing, f"missing required documentation: {missing}"
    assert not (ROOT / "docs").exists(), "legacy local documentation directory was not removed"

    failures: list[str] = []
    documents = sorted(DOCS.rglob("*.md"))
    for document in documents:
        content = document.read_text(encoding="utf-8")
        if not markdown_body(content).lstrip().startswith("# "):
            failures.append(f"{document.relative_to(REPO_ROOT)}: missing H1")
        linkable_content = FENCED_CODE.sub("", content)
        for raw_target in LINK.findall(linkable_content):
            target = raw_target.split("#", 1)[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = (document.parent / target).resolve()
            try:
                resolved.relative_to(REPO_ROOT.resolve())
            except ValueError:
                failures.append(
                    f"{document.relative_to(REPO_ROOT)}: link escapes repository area: {raw_target}"
                )
                continue
            if not resolved.exists():
                failures.append(
                    f"{document.relative_to(REPO_ROOT)}: missing link target: {raw_target}"
                )

    for filename, requirement in DEVELOPER_REQUIREMENTS.items():
        path = DOCS / "03_develop" / filename
        content = path.read_text(encoding="utf-8")
        prose_length = effective_prose_length(content)
        if prose_length < requirement["minimum_prose"]:
            failures.append(
                f"{path.relative_to(REPO_ROOT)}: effective prose {prose_length} is below "
                f"the three-times baseline {requirement['minimum_prose']}"
            )
        if len(FENCED_CODE.findall(content)) < 2:
            failures.append(
                f"{path.relative_to(REPO_ROOT)}: requires at least two real source excerpts"
            )
        for source in requirement["sources"]:
            if source not in content:
                failures.append(
                    f"{path.relative_to(REPO_ROOT)}: missing required source analysis for {source}"
                )
        for topic in ("代码分析", "失败", "扩展", "回归"):
            if topic not in content:
                failures.append(
                    f"{path.relative_to(REPO_ROOT)}: missing developer analysis topic {topic}"
                )
        for heading in ("## 二次开发目标", "## 母工作流修改入口"):
            if heading not in content:
                failures.append(
                    f"{path.relative_to(REPO_ROOT)}: missing mother-workflow development section {heading}"
                )
        if "母工作流" not in content[:1200]:
            failures.append(
                f"{path.relative_to(REPO_ROOT)}: audience is not clearly identified as mother-workflow developers"
            )

    require_inventory(
        failures,
        "03_develop/01_workflow.md",
        configured_stage_names("config.yaml"),
        "main-stage",
    )

    tool_sources = [
        ROOT / "tools/workflow_builder/uc_tools.py",
        ROOT / "tools/workflow_tool_generator/uc_tools.py",
        ROOT / "tools/workflow_checker_generator/uc_tools.py",
        ROOT / "tools/workflow_child_supervisor/uc_tools.py",
        ROOT / "tools/workflow_config_generator/uc_tools.py",
        ROOT / "tools/workflow_guidedoc_generator/uc_tools.py",
        ROOT / "tools/workflow_evaluation_control/uc_tools.py",
        ROOT / "tools/workflow_builder/core.py",
    ]
    require_inventory(
        failures,
        "03_develop/02_tools.md",
        ast_classes(tool_sources, base="UCTool"),
        "UCTool-class",
    )

    checker_sources = [
        ROOT / "tools/workflow_builder/uc_checkers.py",
        ROOT / "tools/workflow_evaluation_control/uc_checkers.py",
    ]
    checker_inventory = ast_classes(checker_sources, suffix="Checker")
    config_files = [
        "config.yaml",
        "inc.yaml",
        "eval_tools.yaml",
        "eval_checkers.yaml",
        "eval_flow.yaml",
        "eval_env.yaml",
        "eval_run.yaml",
    ]
    checker_aliases = set().union(
        *(configured_checker_aliases(relative) for relative in config_files)
    )
    require_inventory(
        failures,
        "03_develop/03_checkers.md",
        checker_inventory | checker_aliases,
        "Checker-class-or-alias",
    )

    guide_inventory = {
        path.relative_to(ROOT / "Guide_Doc").as_posix()
        for path in (ROOT / "Guide_Doc").rglob("*.md")
    }
    require_inventory(
        failures,
        "03_develop/04_guide_docs.md",
        guide_inventory,
        "Guide_Doc-file",
    )

    evaluation_configs = config_files[1:]
    evaluation_inventory = set(evaluation_configs)
    evaluation_inventory.update(
        name
        for relative in evaluation_configs
        for name in configured_stage_names(relative)
    )
    require_inventory(
        failures,
        "03_develop/05_evaluation_and_incremental_control.md",
        evaluation_inventory,
        "evaluation-or-incremental-stage",
    )

    regression_inventory = {
        path.name for path in (ROOT / "regression").glob("run_*regression.py")
    }
    require_inventory(
        failures,
        "03_develop/06_testing.md",
        regression_inventory,
        "regression-script",
    )

    require_inventory(
        failures,
        "03_develop/07_generated_workflow_development.md",
        {
            "config.yaml",
            "config/inc.yaml",
            "tools/",
            "Guide_Doc/",
            "docs/",
            "knowledge_base/",
            "requirements.txt",
            "input/<TARGET>/",
            "output/",
            "tmp/",
            "make check",
            "IncrementalChangeDeployer",
        },
        "generated-workflow-component",
    )

    missing_targets = sorted(DOCUMENTED_MAKE_TARGETS - make_targets())
    if missing_targets:
        failures.append(f"documented Make targets do not exist: {missing_targets}")
    assert not failures, "\n".join(failures)
    print(f"[PASS] validated {len(documents)} documentation files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
