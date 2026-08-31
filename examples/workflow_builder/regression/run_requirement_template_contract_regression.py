from __future__ import annotations

import copy
import tempfile
from pathlib import Path

import yaml

from examples.workflow_builder.tools.workflow_builder.uc_checkers import WorkflowRequirementCoverageChecker


def _write_yaml(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _check(workspace: Path) -> tuple[bool, object]:
    checker = WorkflowRequirementCoverageChecker(
        manifest_path="wfgen/requirements_manifest.yaml",
        build_config_path="wfgen/workflow_build.yaml",
        mode="build",
    )
    checker.workspace = str(workspace)
    return checker.do_check()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="requirement_template_contract_") as temp:
        workspace = Path(temp)
        guide = workspace / "input/guide.md"
        guide.parent.mkdir(parents=True)
        guide.write_text("# Requirement\n", encoding="utf-8")
        fixed_docs = [
            {"path": path}
            for path in WorkflowRequirementCoverageChecker.FIXED_USER_DOCS
        ]
        fixed_configs = [
            {"path": path}
            for path in WorkflowRequirementCoverageChecker.FIXED_CONFIGS
        ]
        fixed_deliverables = [
            {"path": path}
            for path in WorkflowRequirementCoverageChecker.FIXED_DELIVERABLES
        ]
        manifest = {
            "source_requirement": "input/guide.md",
            "requirement_sections": ["Requirement"],
            "section_coverage": {"Requirement": ["stage and deliverables"]},
            "required_stages": [
                {"name": "analyze", "label": "Analyze", "config": "config.yaml"}
            ],
            "required_tools": ["AnalyzeTool"],
            "required_checkers": ["AnalyzeChecker"],
            "required_guidedocs": [{"path": "Guide_Doc/analyze.md", "stage": "analyze"}],
            "required_user_docs": fixed_docs,
            "required_templates": [],
            "required_configs": fixed_configs,
            "required_make_targets": list(
                WorkflowRequirementCoverageChecker.FIXED_MAKE_TARGETS
            ),
            "required_deliverables": fixed_deliverables,
            "required_python_dependencies": [],
            "required_system_dependencies": [],
            "minimum_counts": {
                "user_docs": len(WorkflowRequirementCoverageChecker.FIXED_USER_DOCS),
                "configs": len(WorkflowRequirementCoverageChecker.FIXED_CONFIGS),
                "make_targets": len(WorkflowRequirementCoverageChecker.FIXED_MAKE_TARGETS),
                "deliverables": len(WorkflowRequirementCoverageChecker.FIXED_DELIVERABLES),
            },
        }
        declared_paths = list(
            dict.fromkeys(
                [
                    "Guide_Doc/analyze.md",
                    *WorkflowRequirementCoverageChecker.FIXED_DELIVERABLES,
                ]
            )
        )
        build = {
            "workflow": {"name": "sample"},
            "root": {"path": "./sample"},
            "directories": {"public": [], "internal": []},
            "files": {
                "public": [
                    {"path": path, "template": "empty"}
                    for path in declared_paths
                ],
                "internal": [],
            },
            "workflow_spec": {
                "checkers": [{"name": "AnalyzeChecker"}],
                "stages": [{"name": "analyze"}],
            },
        }
        manifest_path = workspace / "wfgen/requirements_manifest.yaml"
        build_path = workspace / "wfgen/workflow_build.yaml"
        _write_yaml(manifest_path, manifest)
        _write_yaml(build_path, build)

        weakened = copy.deepcopy(manifest)
        weakened["required_user_docs"] = [
            "docs/README.md",
            "docs/QUICKSTART.md",
        ]
        weakened["required_configs"] = [
            {"path": "config/default.yaml"},
            {"path": "config/inc.yaml"},
            {"path": "config/empty.yaml"},
        ]
        weakened["required_deliverables"] = [
            "完整工作流代码和配置",
            "所有 Checker 及其正反测试",
        ]
        weakened["minimum_counts"] = {
            "user_docs": 2,
            "configs": 3,
            "make_targets": 1,
            "deliverables": 2,
        }
        manifest_checker = WorkflowRequirementCoverageChecker(
            manifest_path="wfgen/requirements_manifest.yaml",
            mode="manifest",
        )
        manifest_checker.workspace = str(workspace)
        _write_yaml(manifest_path, weakened)
        passed, result = manifest_checker.do_check()
        assert not passed, result
        assert result["fixed_contract_errors"], result
        assert result["item_shape_errors"], result
        assert result["forbidden_user_docs"] == ["docs/QUICKSTART.md"], result
        assert result["understated_minimums"], result

        stdlib_manifest = copy.deepcopy(manifest)
        stdlib_manifest["required_python_dependencies"] = [
            {"name": "json", "version": "stdlib"}
        ]
        _write_yaml(manifest_path, stdlib_manifest)
        passed, result = manifest_checker.do_check()
        assert not passed, result
        assert any(
            "standard-library" in error
            for error in result["dependency_errors"]
        ), result

        missing_stage_config = copy.deepcopy(manifest)
        del missing_stage_config["required_stages"][0]["config"]
        _write_yaml(manifest_path, missing_stage_config)
        passed, result = manifest_checker.do_check()
        assert not passed, result
        assert any(
            ".config must name the concrete runtime config" in error
            for error in result["required_stage_config_errors"]
        ), result

        undeclared_stage_config = copy.deepcopy(manifest)
        undeclared_stage_config["required_stages"][0]["config"] = "config/eval.yaml"
        _write_yaml(manifest_path, undeclared_stage_config)
        passed, result = manifest_checker.do_check()
        assert not passed, result
        assert any(
            "is not declared in required_configs" in error
            for error in result["required_stage_config_errors"]
        ), result

        _write_yaml(manifest_path, manifest)
        passed, result = _check(workspace)
        assert passed, result

        build["files"]["public"].append(
            {"path": "docs/quickstart.md", "template": "empty"}
        )
        _write_yaml(build_path, build)
        passed, result = _check(workspace)
        assert not passed, result
        assert result["forbidden_quickstart_paths"] == [
            "docs/quickstart.md"
        ], result
        build["files"]["public"].pop()
        _write_yaml(build_path, build)

        manifest["required_templates"] = ["templates/request.yaml"]
        _write_yaml(manifest_path, manifest)
        passed, result = _check(workspace)
        assert not passed and "templates/request.yaml" in result["missing_declared_paths"], result

        build["files"]["public"].append(
            {"path": "templates/request.yaml", "template": "empty"}
        )
        _write_yaml(build_path, build)
        passed, result = _check(workspace)
        assert passed, result

    print("[PASS] requirement reusable-template contract")


if __name__ == "__main__":
    main()
