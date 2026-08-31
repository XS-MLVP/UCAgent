from __future__ import annotations

import shutil
import subprocess
import tempfile
import importlib.util
import json
import os
from pathlib import Path

import yaml

from examples.workflow_builder.tools.workflow_builder.core import (
    WorkflowBuildError,
    build_workflow,
    copy_input_example_tree,
    validate_build_config,
)
from examples.workflow_builder.tools.workflow_builder.artifact_inspector import inspect_artifacts
from examples.workflow_builder.tools.workflow_builder.delivery_contract import load_acceptance_contract
from examples.workflow_builder.tools.workflow_builder.environment_preflight import inspect_environment
from examples.workflow_builder.tools.workflow_builder.uc_checkers import (
    WorkflowBuildConfigChecker,
    WorkflowBuildOutputChecker,
    WorkflowDependencyChecker,
    WorkflowEnvironmentSetupChecker,
    WorkflowGeneratedGuideDocChecker,
    WorkflowImplementationPlanChecker,
    WorkflowMigrationPackageChecker,
    WorkflowGeneratedToolChecker,
    WorkflowGuideDocSpecChecker,
    WorkflowRequirementCoverageChecker,
    WorkflowRuntimeConfigAuditChecker,
    WorkflowUserDocsChecker,
    find_parent_workflow_path_leaks,
)
from examples.workflow_builder.tools.workflow_config_generator.core import (
    ConfigGenerationError,
    generate_config,
    validate_config_spec,
)
from examples.workflow_builder.tools.workflow_guidedoc_generator.core import generate_guidedocs
from examples.workflow_builder.tools.workflow_tool_generator.core import generate_tools
from examples.workflow_builder.tools.workflow_evaluation_control.uc_checkers import EvaluationEvidenceChecker


ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _checker(checker, workspace: Path) -> tuple[bool, object]:
    checker.workspace = str(workspace)
    return checker.do_check()


def _check_runtime_config_reference_audit() -> None:
    with tempfile.TemporaryDirectory(prefix="workflow_runtime_config_audit_") as temp:
        workspace = Path(temp)
        workflow_root = workspace / "workflow"
        _write(workflow_root / "Guide_Doc/analyze.md", "# Analyze\n")
        stages = [
            {
                "name": "prepare",
                "task": ["读取明确声明的用户需求文件并生成结构化分析证据。"],
                "reference_files": ["input/{DUT}/requirements.md"],
                "output_files": ["{OUT}/{DUT}/analysis.json"],
                "checker": [],
            },
            {
                "name": "analyze",
                "task": ["读取前序结构化证据和固定交付指导文档并生成最终报告。"],
                "reference_files": [
                    "{OUT}/{DUT}/analysis.json",
                    "Guide_Doc/analyze.md",
                ],
                "output_files": ["{OUT}/{DUT}/report.json"],
                "checker": [],
            },
        ]
        config = {"template_overwrite": {}, "tools": {}, "stage": stages}
        workflow_spec = {
            "runtime_contract": {
                "input_root": "input",
                "required_input": [
                    {"path": "requirements.md", "type": "file"},
                    {"path": "rtl", "type": "directory"},
                ],
            },
            "stages": yaml.safe_load(yaml.safe_dump(stages)),
            "checkers": [],
        }
        _write(
            workflow_root / "config.yaml",
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        )
        workflow_spec_path = workflow_root / ".workflow/workflow_spec.yaml"
        _write(
            workflow_spec_path,
            yaml.safe_dump(workflow_spec, allow_unicode=True, sort_keys=False),
        )
        _write(
            workspace / "wfgen/requirements_manifest.yaml",
            yaml.safe_dump(
                {
                    "required_guidedocs": [{"path": "Guide_Doc/analyze.md"}],
                    "required_user_docs": [],
                    "required_templates": [],
                    "required_configs": [{"path": "config.yaml"}],
                    "required_deliverables": [],
                },
                allow_unicode=True,
                sort_keys=False,
            ),
        )
        checker = WorkflowRuntimeConfigAuditChecker(
            workflow_root="workflow",
            manifest_path="wfgen/requirements_manifest.yaml",
        )
        ok, details = _checker(checker, workspace)
        assert ok, details
        assert details["checked_reference_count"] == 3

        config["stage"][0]["reference_files"].append("input/{DUT}/invented.md")
        workflow_spec["stages"][0]["reference_files"].append(
            "input/{DUT}/invented.md"
        )
        _write(
            workflow_root / "config.yaml",
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        )
        _write(
            workflow_spec_path,
            yaml.safe_dump(workflow_spec, allow_unicode=True, sort_keys=False),
        )
        ok, details = _checker(checker, workspace)
        assert not ok
        assert details["unproven_reference_files"][0]["reference"] == (
            "input/{DUT}/invented.md"
        )


def _check_migration_output_placeholders() -> None:
    with tempfile.TemporaryDirectory(prefix="workflow_migration_placeholders_") as temp:
        root = Path(temp)
        _write(
            root / ".workflow/acceptance_rules.yaml",
            yaml.safe_dump(
                {
                    "required_public_files": [
                        "output/README.md",
                        "output/example/result.json",
                    ]
                },
                sort_keys=False,
            ),
        )
        allowed = WorkflowMigrationPackageChecker._allowed_output_placeholders(root)
        assert allowed == {"output/README.md"}
        assert not WorkflowMigrationPackageChecker._is_dirty_package_file(
            "output/README.md",
            allowed,
        )
        assert WorkflowMigrationPackageChecker._is_dirty_package_file(
            "output/example/result.json",
            allowed,
        )
        assert WorkflowMigrationPackageChecker._is_dirty_package_file(
            "reports/summary.json",
            allowed,
        )
        assert WorkflowMigrationPackageChecker._is_dirty_package_file(
            ".workflow/local/environment.yaml",
            allowed,
        )


def _check_shared_inspection_and_environment_preflight() -> None:
    with tempfile.TemporaryDirectory(prefix="workflow_inspection_contract_") as temp:
        root = Path(temp)
        _write(
            root / ".workflow/acceptance_rules.yaml",
            yaml.safe_dump(
                {
                    "required_public_files": [
                        "config.yaml",
                        "output/README.md",
                        "tools/example.py",
                    ],
                    "required_public_dirs": ["output", "tmp", "tools"],
                    "required_internal_files": [
                        ".workflow/acceptance_rules.yaml",
                    ],
                },
                sort_keys=False,
            ),
        )
        _write(
            root / "config.yaml",
            yaml.safe_dump(
                {"mission": {"name": "test"}, "stage": [{"name": "inspect"}]},
                sort_keys=False,
            ),
        )
        _write(root / "output/README.md", "fixed delivery marker\n")
        _write(root / "tools/example.py", "VALUE = 1\n")
        (root / "tmp").mkdir()
        for path in (
            "setup.py",
            "config/environment.schema.yaml",
            "Makefile",
            "ucagent_setup.sh",
        ):
            _write(root / path, "# test\n")

        contract = load_acceptance_contract(root)
        assert ".workflow/acceptance_rules.yaml" in contract.required_internal_files
        assert contract.package_files("partial") == (
            "config.yaml",
            "output/README.md",
        )
        yaml_summary = inspect_artifacts(
            root,
            action="yaml_summary",
            path="config.yaml",
        )
        assert yaml_summary["root_type"] == "dict"
        assert yaml_summary["stage_container_type"] == "list"
        assert yaml_summary["stage_names"] == ["inspect"]
        release_tree = inspect_artifacts(root, action="release_tree")
        assert release_tree["ok"], release_tree
        _write(root / "output/result.json", "{}\n")
        release_tree = inspect_artifacts(root, action="release_tree")
        assert not release_tree["ok"]
        assert "output/result.json" in release_tree["runtime_artifacts"]
        (root / "output/result.json").unlink()

        package_files = {
            "full": [
                "config.yaml",
                "output/README.md",
                "tools/example.py",
            ],
            "partial": ["config.yaml", "output/README.md"],
        }
        package_directories = {
            "full": ["output", "tmp", "tools"],
            "partial": ["output", "tmp"],
        }
        for mode, files in package_files.items():
            package_root = root / ".install/packages" / mode
            for path in files:
                _write(package_root / path, f"{path}\n")
            for path in package_directories[mode]:
                (package_root / path).mkdir(parents=True, exist_ok=True)
        _write(
            root / ".install/manifest.json",
            json.dumps(
                {
                    "packages": package_files,
                    "package_directories": package_directories,
                }
            ),
        )
        manifest_summary = inspect_artifacts(root, action="migration_manifest")
        assert manifest_summary["ok"], manifest_summary

        old_all_proxy = os.environ.get("ALL_PROXY")
        try:
            os.environ["ALL_PROXY"] = "socks://127.0.0.1:1080"
            preflight = inspect_environment(root, include_tmux=False)
            assert not preflight["ok"]
            assert any("unsupported proxy scheme socks" in issue for issue in preflight["proxy_issues"])
            os.environ["ALL_PROXY"] = "http://user:password@127.0.0.1:7897"
            preflight = inspect_environment(root, include_tmux=False)
            assert not preflight["ok"]
            assert "<credentials-redacted>" in preflight["process_proxy_environment"]["ALL_PROXY"]
            assert "password" not in preflight["process_proxy_environment"]["ALL_PROXY"]
        finally:
            if old_all_proxy is None:
                os.environ.pop("ALL_PROXY", None)
            else:
                os.environ["ALL_PROXY"] = old_all_proxy


def main() -> None:
    _check_runtime_config_reference_audit()
    _check_migration_output_placeholders()
    _check_shared_inspection_and_environment_preflight()
    builder_config = (ROOT / "config.yaml").read_text(encoding="utf-8")
    builder_config_data = yaml.safe_load(builder_config)
    initial_stage, build_config_stage = builder_config_data["stage"][:2]
    assert initial_stage["name"] == "extract_requirements_and_plan"
    assert "wfgen/workflow_build.yaml" not in initial_stage["output_files"]
    assert len(initial_stage["task"]) == 5
    assert len(initial_stage["checker"]) == 4
    initial_task_text = "\n".join(initial_stage["task"])
    assert "PathList(path='{TEST_INPUT_DIR}', depth=-1)" in initial_task_text
    assert "禁止调用不存在的 ListFiles" in initial_task_text
    assert "WorkflowPlanAppender" in initial_task_text
    assert "Python 标准库不得列入 required_python_dependencies" in initial_task_text
    assert "Guide_Doc/stages/00_extract_requirements_and_plan.md" in initial_stage["reference_files"]
    assert build_config_stage["name"] == "design_workflow_build_config"
    assert len(build_config_stage["task"]) == 5
    assert build_config_stage["output_files"] == [
        "{WFGEN_DIR}/workflow_implementation_plan.md",
        "{BUILD_CONFIG}",
    ]
    assert len(build_config_stage["checker"]) == 3
    build_config_checker = next(
        checker
        for checker in build_config_stage["checker"]
        if checker["name"] == "workflow_build_config_check"
    )
    assert build_config_checker["args"]["expected_root"] == "{TEST_WORKFLOW_ROOT}"
    assert build_config_checker["args"]["run_planned_checker_tests"] is True
    assert "Guide_Doc/stages/01_design_workflow_build_config.md" in build_config_stage["reference_files"]
    stage_guides = sorted((ROOT / "Guide_Doc/stages").glob("[0-9][0-9]_*.md"))
    assert len(stage_guides) == len(builder_config_data["stage"]) == 24
    for index, stage in enumerate(builder_config_data["stage"]):
        guide = f"Guide_Doc/stages/{index:02d}_{stage['name']}.md"
        assert guide in stage["reference_files"], (index, stage["name"], guide)
        assert any(
            checker.get("clss", "").endswith(".WorkflowLivingPlanChecker")
            for checker in stage["checker"]
        ), stage["name"]
        if index:
            assert "{WFGEN_DIR}/workflow_implementation_plan.md" in stage["reference_files"]
            assert "{WFGEN_DIR}/workflow_implementation_plan.md" in stage["output_files"]
        guide_text = (ROOT / guide).read_text(encoding="utf-8")
        for heading in (
            "## 关键文件的最小可通过版本",
            "## 常见示例",
            "## 常见问题",
            "## FAQ 维护规则",
        ):
            assert heading in guide_text, (guide, heading)
    guidedoc_guide = (ROOT / "Guide_Doc/guidedoc_generation_guide.md").read_text(
        encoding="utf-8"
    )
    stage_guide = (ROOT / "Guide_Doc/stage_check_guide.md").read_text(encoding="utf-8")
    for text in (builder_config, guidedoc_guide, stage_guide):
        assert "至少 300 个有效正文字符" in text
        assert "下一个二级至六级标题" in text
        assert "关键代码分析" in text
    assert "不要直接手工补写生成后的 Markdown" in stage_guide
    assert "TEST_INPUT_DIR: input/test_input" in builder_config
    initial_stage_guide = (
        ROOT / "Guide_Doc/stages/00_extract_requirements_and_plan.md"
    ).read_text(encoding="utf-8")
    assert "相对于 source_dir 的内部路径" in initial_stage_guide
    assert "# 工作流实现计划" in initial_stage_guide
    assert "关键判定分支" in initial_stage_guide
    assert "previous-content SHA256 does not match" in initial_stage_guide
    assert "正文内部禁止使用" in initial_stage_guide
    assert "只完整删除末尾的当前阶段记录" in initial_stage_guide
    config_guide = (ROOT / "Guide_Doc/config_generation_guide.md").read_text(
        encoding="utf-8"
    )
    assert ".//workflow/.workflow/workflow_spec.yaml" in config_guide
    assert "不得只修最终 `config.yaml`" in config_guide
    workflow_build_guide = (
        ROOT / "Guide_Doc/workflow_build_yaml_guide.md"
    ).read_text(encoding="utf-8")
    assert "source_dir: input/test_input" in workflow_build_guide
    assert "source_path: rtl/counter.v" in workflow_build_guide
    assert "不能根据 `workflow.name` 推导目录名" in workflow_build_guide
    test_build_config = ROOT / "tools/workflow_builder/test_data/workflow_build.yaml"
    ok, details = _checker(
        WorkflowBuildConfigChecker(
            build_config_path=str(test_build_config),
            expected_root="test_ref_model_workflow",
            run_planned_checker_tests=True,
        ),
        ROOT,
    )
    assert ok, details
    ok, details = _checker(
        WorkflowBuildConfigChecker(
            build_config_path=str(test_build_config),
            expected_root="workflow",
        ),
        ROOT,
    )
    assert not ok, details
    assert details["configured_root"] == "test_ref_model_workflow"
    assert details["expected_root"] == "workflow"
    assert WorkflowRequirementCoverageChecker._stage_names(
        [{"name": "environment_probe", "label": "环境预检"}]
    ) == ["environment_probe", "环境预检"]
    guidedoc_coverage = WorkflowRequirementCoverageChecker(
        manifest_path="unused.yaml"
    )._validate_guidedoc_manifest_coverage(
        {
            "required_stages": [
                {"name": "analyze"},
                {"name": "simulate"},
                {"name": "report"},
            ],
            "required_guidedocs": [
                {
                    "path": "Guide_Doc/operation.md",
                    "stages": ["analyze", "simulate", "report"],
                },
                {
                    "path": "Guide_Doc/environment_setup.md",
                    "scope": "environment",
                },
            ],
        }
    )
    assert not any(guidedoc_coverage.values()), guidedoc_coverage

    config_spec = yaml.safe_load(
        (ROOT / "tools/workflow_config_generator/test_data/config_spec.yaml").read_text(
            encoding="utf-8"
        )
    )
    config_spec["stages"][0]["reference_files"] = [
        ".//workflow/.workflow/workflow_spec.yaml"
    ]
    try:
        validate_config_spec(config_spec)
    except ConfigGenerationError as exc:
        assert "CONFIG-GEN-SPEC-017" in str(exc)
    else:
        raise AssertionError("parent workflow path prefix must be rejected")
    leaks = find_parent_workflow_path_leaks(
        {"stage": config_spec["stages"]},
        config_path="config.yaml",
        workflow_root_name="workflow",
    )
    assert leaks == [
        "config.yaml:analyze_input.reference_files[0]: "
        ".//workflow/.workflow/workflow_spec.yaml"
    ]
    short_spec = yaml.safe_load(yaml.safe_dump(config_spec))
    short_spec["stages"][0]["reference_files"] = ["input/{DUT}/README.md"]
    short_spec["stages"][0]["task"] = ["a" * 99]
    try:
        validate_config_spec(short_spec)
    except ConfigGenerationError as exc:
        assert "CONFIG-GEN-SPEC-019" in str(exc)
    else:
        raise AssertionError("99 effective task characters must be rejected")
    short_spec["stages"][0]["task"] = ["a" * 100]
    validate_config_spec(short_spec)

    complete_build = yaml.safe_load(
        (ROOT / "tools/workflow_builder/test_data/workflow_build.yaml").read_text(
            encoding="utf-8"
        )
    )
    legacy_build = yaml.safe_load(yaml.safe_dump(complete_build))
    legacy_build["workflow_spec"].pop("checkers")
    for stage in legacy_build["workflow_spec"]["stages"]:
        stage.pop("reference_files")
        stage.pop("output_files")
        stage.pop("checker")
    try:
        validate_build_config(legacy_build)
    except WorkflowBuildError as exc:
        assert "BUILD-SPEC-001" in str(exc)
    else:
        raise AssertionError("legacy workflow_spec without checker planning must be rejected")
    incomplete_checker_build = yaml.safe_load(yaml.safe_dump(complete_build))
    incomplete_checkers = incomplete_checker_build["workflow_spec"]["checkers"]
    incomplete_checkers[0]["entry"].pop("file")
    incomplete_checkers[0]["entry"].pop("class_name")
    try:
        validate_build_config(incomplete_checker_build)
    except WorkflowBuildError as exc:
        message = str(exc)
        assert "BUILD-SPEC-003" in message
        assert "workflow_spec.checkers[0].entry.file 缺失" in message
        assert "workflow_spec.checkers[0].entry.class_name 缺失" in message
    else:
        raise AssertionError("all incomplete Checker entry fields must be reported together")
    future_checker_build = yaml.safe_load(yaml.safe_dump(complete_build))
    future_checker_build["workflow_spec"]["stages"][0]["checker"][0]["args"]["path"] = (
        future_checker_build["workflow_spec"]["stages"][1]["output_files"][0]
    )
    try:
        validate_build_config(future_checker_build)
    except WorkflowBuildError as exc:
        assert "BUILD-SPEC-012" in str(exc)
    else:
        raise AssertionError("a Checker must not read a future stage output")
    directory_output_build = yaml.safe_load(yaml.safe_dump(complete_build))
    directory_output_build["workflow_spec"]["stages"][0]["output_files"] = [
        "{OUT}/{DUT}/generated/tb"
    ]
    try:
        validate_build_config(directory_output_build)
    except WorkflowBuildError as exc:
        assert "BUILD-SPEC-013" in str(exc)
    else:
        raise AssertionError("directory-shaped output_files must be rejected")
    uncertain_reference_build = yaml.safe_load(yaml.safe_dump(complete_build))
    uncertain_reference_build["workflow_spec"]["stages"][0]["reference_files"] = [
        "input/{DUT}/optional.md"
    ]
    try:
        validate_build_config(uncertain_reference_build)
    except WorkflowBuildError as exc:
        assert "BUILD-SPEC-014" in str(exc)
    else:
        raise AssertionError("unproven reference_files must be rejected")

    with tempfile.TemporaryDirectory(prefix="workflow_delivery_contract_") as temp:
        workspace = Path(temp)
        report = build_workflow(
            ROOT / "tools/workflow_builder/test_data/workflow_build.yaml",
            workspace,
        )
        generated = Path(report.root_path)
        assert (generated / "tmp").is_dir()
        generate_tools(
            generated,
            tool_names=["run_command_tool"],
            overwrite=True,
            update_config=True,
        )
        command_module_path = generated / "tools/run_command_tool.py"
        command_spec = importlib.util.spec_from_file_location(
            "delivery_run_command_tool",
            command_module_path,
        )
        assert command_spec is not None and command_spec.loader is not None
        command_module = importlib.util.module_from_spec(command_spec)
        command_spec.loader.exec_module(command_module)
        command_tool = command_module.RunCommandTool(root_dir=generated)
        assert command_tool.run("pwd")["ok"] is True
        assert command_tool.run("python3 -c print(1)")["ok"] is False
        assert command_tool.run("pwd", cwd="../")["ok"] is False
        batch_script = generated / "tmp/batch.py"
        _write(batch_script, "print('batch-ok')\n")
        batch_result = command_tool.run("python3 tmp/batch.py")
        assert batch_result["ok"] is True
        assert "batch-ok" in batch_result["data"]["stdout"]
        clean_result = subprocess.run(
            ["make", "clean"],
            cwd=generated,
            text=True,
            capture_output=True,
        )
        assert clean_result.returncode == 0, clean_result.stderr
        assert (generated / "tmp").is_dir()
        assert not any((generated / "tmp").iterdir())
        source_example = workspace / "input/test_input"
        _write(source_example / "README.md", "# Exact input\n\n")
        _write(source_example / "rtl/dut.sv", "module dut; endmodule\n\n")
        example_manifest = workspace / "wfgen/input_example_manifest.yaml"
        _write(
            example_manifest,
            yaml.safe_dump(
                {
                    "source_dir": "input/test_input",
                    "target_dir": "input/example",
                    "copy_mode": "copy_tree",
                    "required_input": [
                        {"path": "README.md", "type": "file"},
                        {"path": "rtl", "type": "directory"},
                    ],
                },
                sort_keys=False,
            ),
        )
        copied = copy_input_example_tree(
            workspace,
            generated,
            example_manifest,
        )
        assert copied == ["README.md", "rtl/dut.sv"]
        assert (generated / "input/example/README.md").read_bytes() == (
            source_example / "README.md"
        ).read_bytes()
        assert (generated / "input/example/rtl/dut.sv").read_bytes() == (
            source_example / "rtl/dut.sv"
        ).read_bytes()
        assert not (generated / "input/example/rtl/README.md").exists()
        copy_checker = WorkflowBuildOutputChecker(
            build_config_path="tools/workflow_builder/test_data/workflow_build.yaml",
            workflow_root=generated.relative_to(workspace).as_posix(),
            input_example_manifest_path="wfgen/input_example_manifest.yaml",
            run_make_check=False,
        )
        copy_checker.workspace = str(workspace)
        assert copy_checker._check_input_example_copy(generated) is None
        (generated / "input/example/rtl/dut.sv").write_bytes(b"module changed; endmodule\n")
        copy_error = copy_checker._check_input_example_copy(generated)
        assert copy_error
        assert copy_error["content_mismatches"] == ["rtl/dut.sv"]
        shutil.copy2(source_example / "rtl/dut.sv", generated / "input/example/rtl/dut.sv")
        directory_fixture = (
            generated / ".workflow/tool_tests/cases/DirectoryFixtureTool/source_tree"
        )
        _write(directory_fixture / "module.sv", "module fixture; endmodule\n")
        selection_path = workspace / "wfgen/directory_fixture_selection.yaml"
        _write(
            selection_path,
            yaml.safe_dump(
                {
                    "name": "DirectoryFixtureTool",
                    "spec_path": ".workflow/tool_specs/DirectoryFixtureTool.yaml",
                    "fixture_paths": [
                        ".workflow/tool_tests/cases/DirectoryFixtureTool/source_tree"
                    ],
                },
                sort_keys=False,
            ),
        )
        directory_checker = WorkflowGeneratedToolChecker(
            workflow_root=generated.relative_to(workspace).as_posix(),
            tool_selection_file="wfgen/directory_fixture_selection.yaml",
            required_fixture_count=1,
            run_make_targets=False,
        )
        directory_checker.workspace = str(workspace)
        selected_name, _, selected_fixtures = directory_checker._load_tool_selection(
            generated
        )
        assert selected_name == "DirectoryFixtureTool"
        assert selected_fixtures == [
            ".workflow/tool_tests/cases/DirectoryFixtureTool/source_tree"
        ]
        assert (generated / "checkers/planned_artifact_checker.py").is_file()
        assert (generated / ".workflow/checker_specs/PlannedArtifactChecker.yaml").is_file()
        assert (
            generated
            / ".workflow/checker_tests/cases/PlannedArtifactChecker/present.txt"
        ).is_file()
        runtime_spec = {
            "workflow": {
                "name": "test_ref_model_workflow",
                "version": "0.1.0",
                "description": "regression",
            },
            "mode": "default",
            "mission": {"name": "regression", "prompt": {"system": "run"}},
            "write_dirs": ["{OUT}/{DUT}"],
            "stages": [
                {
                    "name": "analyze",
                    "desc": "Analyze input",
                    "task": [
                        "Read every declared input and the workflow specification, invoke the registered analysis tool, write the planned analysis artifact, inspect its semantic fields with the planned Checker, record exact evidence and failure details, repair any invalid result, and complete only after validation succeeds."
                    ],
                }
            ],
        }
        runtime_spec_path = generated / ".workflow/config_specs/main.yaml"
        _write(
            runtime_spec_path,
            yaml.safe_dump(runtime_spec, allow_unicode=True, sort_keys=False),
        )
        generated_default = generate_config(
            generated,
            ".workflow/config_specs/main.yaml",
            "config.yaml",
        )
        default_config = yaml.safe_load(generated_default.read_text(encoding="utf-8"))
        planned_stage = complete_build["workflow_spec"]["stages"][0]
        generated_stage = default_config["stage"][0]
        assert generated_stage["reference_files"] == planned_stage["reference_files"]
        assert generated_stage["output_files"] == planned_stage["output_files"]
        assert generated_stage["checker"] == [
            {
                "name": "PlannedArtifactChecker",
                "clss": "checkers.planned_artifact_checker.PlannedArtifactChecker",
                "args": planned_stage["checker"][0]["args"],
            }
        ]
        generated_config_path = generated / "config.yaml"
        generated_config = yaml.safe_load(generated_config_path.read_text(encoding="utf-8"))
        generated_tools = generated_config.setdefault("tools", {}).setdefault("GeneratedTools", [])
        assert isinstance(generated_tools, list)
        generated_config["tools"]["GeneratedTools"] = {"InvalidTool": {"enabled": True}}
        _write(generated_config_path, yaml.safe_dump(generated_config, sort_keys=False))
        invalid_config = subprocess.run(
            [
                "python3",
                str(generated / ".workflow/checkers/config_syntax_checker.py"),
                str(generated_config_path),
            ],
            text=True,
            capture_output=True,
        )
        assert invalid_config.returncode != 0
        assert "CFG-005" in invalid_config.stdout
        generated_config["tools"]["GeneratedTools"] = generated_tools
        _write(generated_config_path, yaml.safe_dump(generated_config, sort_keys=False))
        portable_environment_files = (
            "setup.py",
            "config/environment.schema.yaml",
            "Guide_Doc/environment_setup.md",
        )
        assert all((generated / path).is_file() for path in portable_environment_files)
        required = (
            "requirements.txt",
            "docs/README.md",
            "docs/01快速启动.md",
            "docs/02输入输出.md",
            "docs/03步骤及检查.md",
            "docs/04开发者文档-tools.md",
            "docs/05开发者文档-checkers.md",
        )
        assert all((generated / path).is_file() for path in required)
        assert not (generated / "quickstart.md").exists()
        assert not (generated / ".workflow/generation_plan.md").exists()
        ok, details = _checker(
            WorkflowEnvironmentSetupChecker(
                workflow_root=generated.relative_to(workspace).as_posix(),
                run_test=True,
            ),
            workspace,
        )
        assert ok, details
        assert "Validate setup.py" in str(
            WorkflowEnvironmentSetupChecker(
                workflow_root=generated.relative_to(workspace).as_posix(),
                run_test=False,
            )
        )

        guide_spec = generated / ".workflow/guidedoc_specs/operation.yaml"
        user_spec = generated / ".workflow/guidedoc_specs/user_extra.yaml"
        common_sections = [
            {"heading": "Purpose", "content": "purpose"},
            {"heading": "Inputs", "content": "input/<TARGET>/ and input/example"},
            {"heading": "Outputs", "content": "output/"},
            {
                "heading": "Usage",
                "content": "TARGET input/<TARGET>/ input/example output/ make check_example make run",
            },
            {"heading": "Execution", "content": "execution"},
            {"heading": "Checks", "content": "checks"},
            {"heading": "Failure Recovery", "content": "recovery"},
        ]
        _write(
            guide_spec,
            yaml.safe_dump(
                {
                    "document_type": "guide_doc",
                    "operation_contract": True,
                    "title": "Operation",
                    "output": "Guide_Doc/operation.md",
                    "sections": common_sections,
                },
                sort_keys=False,
            ),
        )
        _write(
            user_spec,
            yaml.safe_dump(
                {
                    "document_type": "user_doc",
                    "title": "Extra",
                    "output": "docs/06额外说明.md",
                    "sections": [{"heading": "Details", "content": "用户说明" * 120}],
                },
                allow_unicode=True,
                sort_keys=False,
            ),
        )
        generate_guidedocs(
            generated,
            [
                ".workflow/guidedoc_specs/operation.yaml",
                ".workflow/guidedoc_specs/user_extra.yaml",
            ],
        )
        config = yaml.safe_load((generated / "config.yaml").read_text(encoding="utf-8"))
        assert "Guide_Doc/operation.md" in config["guide_docs"]
        assert "docs/06额外说明.md" not in config["guide_docs"]

        manifest = {
            "required_stages": [{"name": "analyze", "config": "config.yaml"}],
            "required_tools": [{"name": "AnalyzeTool"}],
            "required_checkers": [{"name": "AnalyzeChecker"}],
            "required_guidedocs": [{"path": "Guide_Doc/operation.md", "scope": "all"}],
            "required_user_docs": [
                {"path": path, "purpose": "required user documentation"}
                for path in (*required[1:], "docs/06额外说明.md")
            ],
            "required_python_dependencies": [{"package": "PyYAML"}],
            "required_system_dependencies": [
                {"name": "graphviz", "install": "sudo apt-get install graphviz"}
            ],
        }
        manifest_path = workspace / "wfgen/requirements_manifest.yaml"
        _write(manifest_path, yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False))
        ok, details = _checker(
            WorkflowGeneratedGuideDocChecker(
                workflow_root=generated.relative_to(workspace).as_posix(),
                manifest_path="wfgen/requirements_manifest.yaml",
                required_headings=["## Purpose"],
            ),
            workspace,
        )
        assert ok, details
        valid_guide_spec = guide_spec.read_text(encoding="utf-8")
        _write(guide_spec, valid_guide_spec + "\n# provenance regression\n")
        ok, details = _checker(
            WorkflowGeneratedGuideDocChecker(
                workflow_root=generated.relative_to(workspace).as_posix(),
                manifest_path="wfgen/requirements_manifest.yaml",
                required_headings=["## Purpose"],
            ),
            workspace,
        )
        assert not ok
        assert details["stale_generated_documents"], details
        _write(guide_spec, valid_guide_spec)
        generate_guidedocs(
            generated,
            [
                ".workflow/guidedoc_specs/operation.yaml",
                ".workflow/guidedoc_specs/user_extra.yaml",
            ],
        )

        analyze_tool_source = """class AnalyzeTool:
    def run(self, source_path: str) -> dict:
        if not source_path:
            return {"ok": False, "errors": ["source_path is required"]}
        return {"ok": True, "data": {"source_path": source_path}}
"""
        analyze_checker_source = """from ucagent.checkers.base import Checker


class AnalyzeChecker(Checker):
    def do_check(self, timeout=0, **kwargs):
        artifact = kwargs.get("artifact")
        if not isinstance(artifact, dict):
            return False, {"error": "artifact must be a mapping"}
        return bool(artifact.get("ok")), {"artifact": artifact}
"""
        _write(generated / "tools/analyze_tool.py", analyze_tool_source)
        _write(generated / "checkers/analyze_checker.py", analyze_checker_source)
        _write(
            generated / ".workflow/tool_specs/AnalyzeTool.yaml",
            yaml.safe_dump(
                {
                    "name": "AnalyzeTool",
                    "entry": {
                        "file": "tools/analyze_tool.py",
                        "class_name": "AnalyzeTool",
                        "method": "run",
                    },
                },
                sort_keys=False,
            ),
        )
        config = yaml.safe_load((generated / "config.yaml").read_text(encoding="utf-8"))
        config["tools"]["GeneratedTools"].append(
            {
                "name": "AnalyzeTool",
                "spec": ".workflow/tool_specs/AnalyzeTool.yaml",
                "enabled": True,
            }
        )
        _write(
            generated / "config.yaml",
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        )
        workflow_spec_path = generated / ".workflow/workflow_spec.yaml"
        workflow_spec = yaml.safe_load(workflow_spec_path.read_text(encoding="utf-8"))
        workflow_spec["checkers"].append(
            {
                "name": "AnalyzeChecker",
                "entry": {
                    "file": "checkers/analyze_checker.py",
                    "class_name": "AnalyzeChecker",
                    "method": "do_check",
                },
            }
        )
        _write(
            workflow_spec_path,
            yaml.safe_dump(workflow_spec, allow_unicode=True, sort_keys=False),
        )

        names = [
            "analyze",
            "AnalyzeTool",
            "AnalyzeChecker",
            "Guide_Doc/operation.md",
            *required[1:],
            "docs/06额外说明.md",
        ]
        plan = """
## 工作流概述
本工作流根据输入契约完成分析、验证和交付，所有决策都有结构化证据并通过 Checker。

## 输入输出契约
输入是需求和源文件，输出是分析结果、测试证据和用户文档；路径、失败传播及只读边界明确。

## 阶段设计
### analyze
目的：完成输入分析并生成结构化结果。输入：需求文件与源文件。执行时调用 AnalyzeTool，
并绑定 AnalyzeChecker 检查真实结果字段、来源证据和状态。输出：分析 JSON 和日志。
失败处理：缺少输入、工具错误、结果字段缺失或 Checker 失败都阻止阶段完成，并保留诊断信息。
这里继续说明阶段顺序、前置条件、幂等要求、恢复方式和传递给后续阶段的稳定契约，确保正文充分。
技术决策还覆盖输入文件的确定来源、输出文件的命名协议、工具调用前后的字段映射、Checker 失败如何
传播到阶段状态，以及重试时如何避免覆盖已有证据。阶段只引用固定输入或前序具体文件，不使用目录。

## 工具设计
### AnalyzeTool
作用：解析输入并生成结构化分析。使用阶段：analyze。输入参数：需求路径、源文件路径和输出目录。
输出或返回：统一返回 ok、data、errors、warnings、meta，并落盘真实分析结果。失败处理：路径逃逸、
解析异常、超时和字段缺失分别返回稳定错误码，不得用自然语言成功结论代替 artifact。
工具直接测试必须覆盖正常输入、缺失输入、非法路径及错误内容，并保存可复现证据。
实现文件是 tools/analyze_tool.py，入口类 AnalyzeTool 的 run 负责参数校验和统一返回。调用链从 adapter
进入 run，再经过安全路径解析、内容解析、核心逻辑归纳和结果序列化。关键代码必须区分正常解析、
空输入和格式异常分支。扩展点包括解析器注册、字段映射和输出 writer；调整后同步更新 spec、
GeneratedTools 注册、MCP adapter、正常与失败 fixture，并运行 direct、MCP 和 make check 回归测试。
核心逻辑不得返回默认空值，算法需要从真实输入计算摘要、来源哈希和结构化结论。

### run_command_tool
作用：提供受限批处理执行基础设施。使用阶段：工具测试、Checker 回归和发布检查。输入参数包括命令、
工作区内 cwd 与超时，输出或返回统一结构中的退出码、标准输出和标准错误。失败处理拒绝绝对路径、
父目录、inline interpreter、shell 拼接和非白名单目标。实现文件是 tools/run_command_tool.py，
入口类 RunCommandTool 的 run 先解析 cwd，再进入命令解析调用链。关键代码按 python、shell、make、
pytest 和只读命令分支执行，核心逻辑始终使用 shell=False。测试覆盖 pwd 正常路径、工作区内 batch、
python -c 拒绝、cwd 越界和超时。扩展点是 allowed_commands 与 allowed_make_targets，调整时必须同步
spec、adapter、开发者文档和安全回归，不能只扩大字符串白名单。
脚本参数仍可能影响工作区文件，因此调用前需要代码审查，临时脚本与中间结果只能进入根级 tmp，
make clean 必须删除其中普通和隐藏内容。错误码需区分参数拒绝、进程非零与执行异常，meta 保存原始
命令、cwd 和 timeout 供 Checker 追踪。任何新增解释器都必须增加脚本后缀校验、路径解析和负向 fixture。

## Checker设计
### AnalyzeChecker
使用阶段：analyze。检查对象：结构化分析 JSON 和对应输入文件。检查内容：状态、来源路径、哈希、
分析字段、错误数组和证据文件。通过条件：文件真实存在、schema 完整且结论与证据一致。
失败条件：文件缺失、路径逃逸、状态矛盾、空证据或伪造 passed。失败必须阻止阶段完成，并由正反
fixture 的确定性测试证明不会把失败样例误报为通过。
实现文件是 checkers/analyze_checker.py，入口类 AnalyzeChecker 的 do_check 读取 artifact 和输入证据。
检查流程先验证安全路径与普通文件，再解析 JSON schema，随后进入关键分支比较状态、哈希和必需字段。
异常或错误处理必须返回结构化失败并传播到阶段，不得吞掉解析异常。扩展点包括字段规则和证据策略；
调整时同步修改中心 workflow_spec、checker spec、正反 fixture、阶段绑定和 docs，并执行静态、direct
与完整回归测试。判定流程必须明确区分缺失文件、无效结构、证据矛盾和真正通过四类结果。

## GuideDoc设计
Guide_Doc/operation.md 解释 analyze 阶段的输入、输出、检查和恢复方法。

## 用户文档设计
固定用户文档解释快速启动、输入输出、阶段检查和开发者扩展方法。

## 环境配置设计
setup.py、environment.schema.yaml、Makefile 和 shell 受控区块支持迁移配置、隔离本机值和失败恢复。

## 运行模式与依赖
主流程、增量流程和可选评估模式共享稳定契约；Python 与系统依赖分别声明安装方法，不把标准库列为 pip 包。
"""
        plan += "\n" + "\n".join(names) + "\n" + "实现细节" * 300
        plan_path = workspace / "wfgen/workflow_implementation_plan.md"
        _write(plan_path, plan)
        ok, details = _checker(
            WorkflowImplementationPlanChecker(
                plan_path="wfgen/workflow_implementation_plan.md",
                manifest_path="wfgen/requirements_manifest.yaml",
            ),
            workspace,
        )
        assert ok, details
        semantic_alias_plan = (
            plan.replace("Checker设计", "Checker 设计")
            .replace("GuideDoc设计", "GuideDoc 设计")
            .replace("作用", "职责")
            .replace("检查内容", "验证内容")
        )
        _write(plan_path, semantic_alias_plan)
        ok, details = _checker(
            WorkflowImplementationPlanChecker(
                plan_path="wfgen/workflow_implementation_plan.md",
                manifest_path="wfgen/requirements_manifest.yaml",
            ),
            workspace,
        )
        assert ok, details
        assert "Validate implementation-plan" in str(
            WorkflowImplementationPlanChecker(
                plan_path="wfgen/workflow_implementation_plan.md",
                manifest_path="wfgen/requirements_manifest.yaml",
            )
        )

        prose = "本文详细说明工作流的使用边界、执行方法、输入输出和失败恢复。" * 20
        for path in required[1:]:
            _write(generated / path, f"# 文档\n\n{prose}\n")
        _write(
            generated / "docs/README.md",
            "# 文档目录\n\n"
            + "\n".join(f"- {Path(path).name}" for path in required[2:])
            + "\n"
            + prose,
        )
        _write(
            generated / "docs/01快速启动.md",
            "# 快速启动\n\nsetup.py make configure make configure-check input/example output/ make check make check_example make run\n" + prose,
        )
        _write(
            generated / "docs/02输入输出.md",
            "# 输入输出\n\ninput/<TARGET>/ output/<TARGET>/ config/environment.schema.yaml .workflow/local/environment.yaml\n" + prose,
        )
        _write(
            generated / "docs/03步骤及检查.md",
            "# 步骤及检查\n\nanalyze AnalyzeChecker\n" + prose,
        )
        _write(
            generated / "docs/04开发者文档-tools.md",
            "# 工具开发\n\n## AnalyzeTool\n\n"
            + "实现文件 tools/analyze_tool.py，入口类 AnalyzeTool，入口函数 run。"
            + f"\n```python\n{analyze_tool_source}```\n"
            + "源码分析说明参数校验和返回结构。业务逻辑根据真实路径决定成功失败，"
            + "修改影响要求联动修改注册、spec 和 fixture。关键代码和核心逻辑通过调用路径执行。"
            + "输入参数经过校验，返回值包含输出字段。主要分支处理正常和失败，异常与错误处理返回证据。"
            + "扩展点与调整方式必须同步 spec，测试 fixture 和回归命令覆盖修改影响。" * 20
            + "\n\n## run_command_tool\n\n"
            + "实现文件 tools/run_command_tool.py，入口类 RunCommandTool，入口函数 run。"
            + f"\n```python\n{command_module_path.read_text(encoding='utf-8')}```\n"
            + "代码分析说明命令解析、安全边界和返回结构。业务含义是只允许受控批处理，"
            + "影响范围包括白名单、adapter、spec 与安全回归。关键代码和核心逻辑沿调用路径校验命令。"
            + "输入参数包含 command、cwd 和 timeout，返回值包含退出码与输出字段。主要分支处理白名单、脚本和 make，"
            + "异常与错误处理拒绝越界。扩展点与调整方式同步 allowed_commands，测试 fixture 和回归命令验证安全边界。" * 20,
        )
        planned_checker_source = (
            generated / "checkers/planned_artifact_checker.py"
        ).read_text(encoding="utf-8")
        _write(
            generated / "docs/05开发者文档-checkers.md",
            "# Checker 开发\n\n## AnalyzeChecker\n\n"
            + "实现文件 checkers/analyze_checker.py，入口类 AnalyzeChecker 的 do_check 是入口函数。"
            + f"\n```python\n{analyze_checker_source}```\n"
            + "逐行分析说明 artifact 类型检查和通过判定。业务规则要求真实结构决定结果，"
            + "联动修改涉及中心 workflow_spec、checker spec、fixture 和回归命令。"
            + "关键代码和判定流程沿调用链读取输入字段，返回值形成证据产物和输出字段。"
            + "主要分支区分通过失败，异常与错误处理负责失败传播。扩展点与调整方式同步配置，"
            + "测试 fixture 和回归命令验证正反样例。" * 20
            + "\n\n## PlannedArtifactChecker\n\n"
            + "实现文件 checkers/planned_artifact_checker.py，入口类 PlannedArtifactChecker，入口函数 do_check。"
            + f"\n```python\n{planned_checker_source}```\n"
            + "源码分析说明路径解析、普通文件判定和结构化证据返回。业务含义是阻止缺失或非普通文件冒充阶段产物，"
            + "修改影响要求联动中心 workflow_spec、checker spec、正反 fixture、阶段绑定和回归命令。"
            + "关键代码沿调用路径读取输入参数并生成返回值或证据产物，主要分支覆盖存在、缺失和路径异常。"
            + "异常与错误处理必须稳定失败；扩展点与调整方式同步注册和测试 fixture。" * 20,
        )
        fixed_doc_specs = []
        for index, rel in enumerate(WorkflowUserDocsChecker.FIXED_DOCS):
            spec_rel = f".workflow/guidedoc_specs/fixed_user_{index}.yaml"
            fixed_doc_specs.append(spec_rel)
            content = (generated / rel).read_text(encoding="utf-8")
            _write(
                generated / spec_rel,
                yaml.safe_dump(
                    {
                        "document_type": "user_doc",
                        "title": Path(rel).stem,
                        "output": rel,
                        "sections": [{"heading": "Document", "content": content}],
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
            )
        generate_guidedocs(generated, fixed_doc_specs, update_config=False)
        ok, details = _checker(
            WorkflowGuideDocSpecChecker(
                workflow_root=generated.relative_to(workspace).as_posix(),
                manifest_path="wfgen/requirements_manifest.yaml",
            ),
            workspace,
        )
        assert ok, details
        dev_tool_spec_path = generated / fixed_doc_specs[4]
        valid_dev_tool_spec = dev_tool_spec_path.read_text(encoding="utf-8")
        dev_checker_spec_path = generated / fixed_doc_specs[5]
        valid_dev_checker_spec = dev_checker_spec_path.read_text(encoding="utf-8")
        current_config = yaml.safe_load(
            (generated / "config.yaml").read_text(encoding="utf-8")
        )
        source_contracts = WorkflowUserDocsChecker._component_sources(
            generated,
            current_config,
        )

        def design_only_spec(path: Path, key: str) -> None:
            spec = yaml.safe_load(path.read_text(encoding="utf-8"))
            component_sections = []
            for component_name, contract in source_contracts[key].items():
                component_sections.append(
                    f"## {component_name}\n\n"
                    f"实现文件：{contract['file']}\n"
                    f"入口类：{contract['class_name']}\n"
                    f"入口函数：{contract['method']}\n"
                    "设计摘要：本节冻结该组件的身份、职责和上下游契约，并规划最终文档需要分析的"
                    "输入输出、主要判断分支、异常传播、扩展位置、测试方法与联动修改范围。生成阶段"
                    "必须重新读取注册指向的真实源码，补充关键业务代码、逐行解释和变更影响，不能把"
                    "这份设计摘要直接冒充最终开发者文档。这里不嵌入源码围栏，用于验证设计验收与"
                    "最终内容验收确实相互独立。\n"
                )
            spec["sections"] = [
                {
                    "heading": "组件设计",
                    "content": "\n".join(component_sections),
                }
            ]
            _write(
                path,
                yaml.safe_dump(spec, allow_unicode=True, sort_keys=False),
            )

        design_only_spec(dev_tool_spec_path, "required_tools")
        design_only_spec(dev_checker_spec_path, "required_checkers")
        ok, details = _checker(
            WorkflowGuideDocSpecChecker(
                workflow_root=generated.relative_to(workspace).as_posix(),
                manifest_path="wfgen/requirements_manifest.yaml",
            ),
            workspace,
        )
        assert ok, details
        design_tool_spec = dev_tool_spec_path.read_text(encoding="utf-8")
        first_tool_contract = next(iter(source_contracts["required_tools"].values()))
        _write(
            dev_tool_spec_path,
            design_tool_spec.replace(first_tool_contract["file"], "tools/wrong.py", 1),
        )
        ok, details = _checker(
            WorkflowGuideDocSpecChecker(
                workflow_root=generated.relative_to(workspace).as_posix(),
                manifest_path="wfgen/requirements_manifest.yaml",
            ),
            workspace,
        )
        assert not ok
        assert details["developer_doc_spec_errors"]["required_tools"], details
        _write(dev_tool_spec_path, valid_dev_tool_spec)
        _write(dev_checker_spec_path, valid_dev_checker_spec)
        generate_guidedocs(generated, fixed_doc_specs, update_config=False)
        tool_doc_text = (generated / "docs/04开发者文档-tools.md").read_text(encoding="utf-8")
        checker_doc_text = (generated / "docs/05开发者文档-checkers.md").read_text(encoding="utf-8")
        assert WorkflowUserDocsChecker._component_section(tool_doc_text, "AnalyzeTool").strip()
        assert WorkflowUserDocsChecker._component_section(checker_doc_text, "AnalyzeChecker").strip()
        _write(
            generated / "requirements.txt",
            "PyYAML>=6.0\n\n# System dependency: graphviz\n"
            "# Ubuntu/Debian: sudo apt-get install graphviz\n",
        )
        ok, details = _checker(
            WorkflowUserDocsChecker(
                workflow_root=generated.relative_to(workspace).as_posix(),
                manifest_path="wfgen/requirements_manifest.yaml",
            ),
            workspace,
        )
        assert ok, details
        assert WorkflowUserDocsChecker._matching_source_snippet(
            "```python\n"
            "class AnalyzeTool:\n"
            "    def run(self, source_path: str) -> dict:\n"
            "```",
            analyze_tool_source,
        )
        assert not WorkflowUserDocsChecker._matching_source_snippet(
            "```python\n"
            "class AnalyzeTool:\n"
            '        return {"ok": True, "data": {"source_path": source_path}}\n'
            "```",
            analyze_tool_source,
        )
        tool_doc_path = generated / "docs/04开发者文档-tools.md"
        valid_tool_doc = tool_doc_path.read_text(encoding="utf-8")
        _write(
            tool_doc_path,
            valid_tool_doc.replace(
                'return {"ok": True, "data": {"source_path": source_path}}',
                'return {"ok": True, "data": {"source_path": "pseudocode"}}',
                1,
            ),
        )
        ok, details = _checker(
            WorkflowUserDocsChecker(
                workflow_root=generated.relative_to(workspace).as_posix(),
                manifest_path="wfgen/requirements_manifest.yaml",
            ),
            workspace,
        )
        assert not ok
        assert details["short_component_sections"]["required_tools"]["AnalyzeTool"][
            "source_evidence_errors"
        ]
        _write(tool_doc_path, valid_tool_doc)
        ok, details = _checker(
            WorkflowDependencyChecker(
                workflow_root=generated.relative_to(workspace).as_posix(),
                manifest_path="wfgen/requirements_manifest.yaml",
            ),
            workspace,
        )
        assert ok, details
        _write(
            workspace / "evaluation/default_result_evidence.yaml",
            yaml.safe_dump(
                {
                    "stage": "evaluate_default_workflow_results",
                    "status": "passed",
                    "evidence": [{"path": "output/example/result.json", "result": "passed"}],
                },
                sort_keys=False,
            ),
        )
        ok, details = _checker(
            EvaluationEvidenceChecker(
                evidence_path="evaluation/default_result_evidence.yaml",
                stage_name="evaluate_default_workflow_results",
            ),
            workspace,
        )
        assert ok, details

        _write(generated / "docs/README.md", "# Too short\n")
        ok, _ = _checker(
            WorkflowUserDocsChecker(
                workflow_root=generated.relative_to(workspace).as_posix(),
                manifest_path="wfgen/requirements_manifest.yaml",
            ),
            workspace,
        )
        assert not ok

    print("[PASS] delivery contract regression")


if __name__ == "__main__":
    main()
