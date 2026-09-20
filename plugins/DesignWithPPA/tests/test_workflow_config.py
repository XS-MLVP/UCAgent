"""Focused DesignWithPPA workflow tests: workflow config."""

from __future__ import annotations

import helpers  # noqa: F401  (runs the plugin sys.path bootstrap first)

from helpers import (
    PLUGIN_SOURCE,
    _template_context,
    _write_yaml,
)

import json
from pathlib import Path
import shutil
from typing import Any
import pytest
import yaml
from design_with_ppa.checkers import (  # noqa: E402
    DesignAllPassBatchTestsChecker,
    DesignArchitectureChecker,
    DesignCoverageGroupBatchChecker,
    DesignCoverageStructureChecker,
    DesignDocumentationSyncChecker,
    DesignFinalDeliveryChecker,
    DesignFunctionalContractChecker,
    DesignInputContractChecker,
    DesignDutApiChecker,
    DesignLabelStructureChecker,
    DesignLineMapReferenceChecker,
    DesignMarkdownFileFormatChecker,
    DesignObservationContractChecker,
    DesignObservationInstrumentationChecker,
    DesignRandomTestCasesChecker,
    DesignRefineTestCasesChecker,
    DesignLabelStructureRefineChecker,
    DesignSpecLineMapBatchChecker,
    DesignTestTemplateChecker,
    DesignPythonAllPassChecker,
    PPABaseCharacterizationChecker,
    PPABestVersionChecker,
    PPACandidateOptimizationChecker,
    PPAIterationChecker,
    PPAResultArtifactsChecker,
    PerformanceArtifactChecker,
    PerformanceContractChecker,
    PerformanceTestContractChecker,
    PythonAdapterContractChecker,
    PythonEnvFixtureContractChecker,
    PythonExecutableSpecChecker,
    PythonReferenceContractChecker,
    PythonReferenceRegressionChecker,
    RTLAllPassRegressionChecker,
    RTLBackendBuildChecker,
    RTLLineCoverageChecker,
    RTLSourceEvidenceChecker,
    _api_assertion_quality_violations,
    _actionable_checker_failure,
    _bounded_checker_value,
    _cleanup_transient_coverage_data,
    _coverage_fixture_lifecycle_violations,
    _hash_rows,
    _ppa_selection_score,
    _public_pytest_failure,
    _pytest_evidence,
    _rtl_regression_failure_evidence,
    _run_pytest,
    _run_workflow_ppa,
    select_best_accepted_record,
)
from design_with_ppa.plugin import get_plugin
from design_with_ppa.contracts import (
    no_regression_metric_categories,
    ppa_score_weights,
)
from design_with_ppa.rtl import (  # noqa: E402
    CHISEL_MILL_VERSION,
    CHISEL_SCALA_VERSION,
    CHISEL_VERSION,
    ChiselLanguageBackend,
    PreparedRTL,
    RTLLanguageBackend,
    RTLLanguageError,
    RTLPreparationRequest,
    RTLSourceTemplate,
    RTLSourceValidation,
    available_rtl_languages,
    build_rtl_template_context,
    discover_rtl_libraries,
    discover_rtl_sources,
    _workspace_python_dut_root,
    register_rtl_language,
    resolve_rtl_config,
    unregister_rtl_language,
)
from ucagent.stage.vstage import parse_vstage
from ucagent.plugins import resolve_plugin_guide_doc_copy_policy
from ucagent.util.config import (  # noqa: E402
    Config,
    build_runtime_config,
    get_config,
    load_yaml_with_env_vars,
    save_runtime_config,
)




@pytest.mark.parametrize(
    ("environment_value", "expected"),
    [(None, 5), ("0", 0), ("8", 8)],
)
def test_workflow_environment_default_is_an_integer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    environment_value: str | None,
    expected: int,
) -> None:
    """The workflow minimum default must resolve before strict validation."""

    workflow = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    monkeypatch.chdir(tmp_path)
    if environment_value is None:
        monkeypatch.delenv(
            "DESIGN_WITH_PPA_MIN_OPTIMIZATION_ITERATIONS", raising=False
        )
    else:
        monkeypatch.setenv(
            "DESIGN_WITH_PPA_MIN_OPTIMIZATION_ITERATIONS", environment_value
        )
    cfg = get_config(None, None, str(tmp_path), workflow_config_file=str(workflow))
    assert cfg.get_value("design_with_ppa.min_optimization_iterations") == expected
    assert type(cfg.get_value("design_with_ppa.min_optimization_iterations")) is int
    assert cfg.get_value("design_with_ppa.max_optimization_iterations") == 1000
    assert cfg.get_value("design_with_ppa.no_improvement_patience") == 3




def test_workflow_environment_resolves_all_optimization_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Environment defaults must resolve minimum, ceiling, and patience as integers."""

    workflow = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DESIGN_WITH_PPA_MIN_OPTIMIZATION_ITERATIONS", "7")
    monkeypatch.setenv("DESIGN_WITH_PPA_MAX_OPTIMIZATION_ITERATIONS", "23")
    monkeypatch.setenv("DESIGN_WITH_PPA_NO_IMPROVEMENT_PATIENCE", "4")

    cfg = get_config(None, None, str(tmp_path), workflow_config_file=str(workflow))

    assert cfg.get_value("design_with_ppa.min_optimization_iterations") == 7
    assert cfg.get_value("design_with_ppa.max_optimization_iterations") == 23
    assert cfg.get_value("design_with_ppa.no_improvement_patience") == 4




def test_workflow_environment_resolves_no_regression_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The no-regression scope resolves from the environment or defaults to all."""

    workflow = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DESIGN_WITH_PPA_NO_REGRESSION_METRICS", raising=False)
    cfg = get_config(None, None, str(tmp_path), workflow_config_file=str(workflow))
    assert no_regression_metric_categories(cfg) == ("performance", "timing")

    monkeypatch.setenv("DESIGN_WITH_PPA_NO_REGRESSION_METRICS", "area, timing")
    cfg = get_config(None, None, str(tmp_path), workflow_config_file=str(workflow))
    assert no_regression_metric_categories(cfg) == ("area", "timing")

    monkeypatch.setenv("DESIGN_WITH_PPA_NO_REGRESSION_METRICS", "")
    cfg = get_config(None, None, str(tmp_path), workflow_config_file=str(workflow))
    assert no_regression_metric_categories(cfg) == ()




def test_workflow_config_resolves_default_score_weights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Score weights default to 1.0 per dimension and partial overrides fill in."""

    workflow = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    monkeypatch.chdir(tmp_path)
    cfg = get_config(None, None, str(tmp_path), workflow_config_file=str(workflow))
    assert ppa_score_weights(cfg) == {"timing": 1.0, "area": 1.0, "power": 1.0}

    cfg = get_config(
        None,
        [{"design_with_ppa.score_weights": {"timing": 2.0}}],
        str(tmp_path),
        workflow_config_file=str(workflow),
    )
    assert ppa_score_weights(cfg) == {"timing": 2.0, "area": 1.0, "power": 1.0}




@pytest.mark.parametrize("environment_value", ["true", "-1", "1001", "1.5", "", '"5"'])
def test_invalid_environment_limit_rejects_full_workflow_initialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    environment_value: str,
) -> None:
    """Invalid environment defaults must fail while workflow Checkers initialize."""

    workflow = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "DESIGN_WITH_PPA_MIN_OPTIMIZATION_ITERATIONS", environment_value
    )
    cfg = get_config(None, None, str(tmp_path), workflow_config_file=str(workflow))
    cfg.un_freeze()
    cfg.set_value("skill.use_skill", False)
    cfg._temp_cfg = _template_context("output", str(tmp_path))
    cfg.update_template(cfg._temp_cfg)
    plugin = get_plugin()
    registry = {checker.__name__: checker for checker in plugin.checkers}

    with pytest.raises((ValueError, yaml.YAMLError), match="min_optimization_iterations|invalid literal"):
        parse_vstage(
            cfg,
            cfg.stage,
            str(tmp_path),
            None,
            checker_registry=registry,
        )




@pytest.mark.parametrize(
    ("environment_name", "environment_value", "error_fragment"),
    [
        (
            "DESIGN_WITH_PPA_MAX_OPTIMIZATION_ITERATIONS",
            "1001",
            "max_optimization_iterations",
        ),
        (
            "DESIGN_WITH_PPA_NO_IMPROVEMENT_PATIENCE",
            "0",
            "no_improvement_patience",
        ),
        (
            "DESIGN_WITH_PPA_NO_IMPROVEMENT_PATIENCE",
            "1.5",
            "no_improvement_patience",
        ),
        (
            "DESIGN_WITH_PPA_NO_REGRESSION_METRICS",
            "performance,latency",
            "no_regression_metrics",
        ),
    ],
)
def test_invalid_environment_optimization_control_rejects_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
    environment_value: str,
    error_fragment: str,
) -> None:
    """Every environment-backed optimization control uses strict checker validation."""

    workflow = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(environment_name, environment_value)
    cfg = get_config(None, None, str(tmp_path), workflow_config_file=str(workflow))
    cfg.un_freeze()
    cfg.set_value("skill.use_skill", False)
    cfg._temp_cfg = _template_context("output", str(tmp_path))
    cfg.update_template(cfg._temp_cfg)
    plugin = get_plugin()
    registry = {checker.__name__: checker for checker in plugin.checkers}

    with pytest.raises((ValueError, yaml.YAMLError), match=error_fragment):
        parse_vstage(
            cfg,
            cfg.stage,
            str(tmp_path),
            None,
            checker_registry=registry,
        )




def test_workflow_config_precedence_and_runtime_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Workspace, explicit config, and override must supersede the workflow layer."""

    workflow = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    workspace_setting = tmp_path / ".ucagent" / "setting.yaml"
    _write_yaml(
        workspace_setting,
        {"design_with_ppa": {"min_optimization_iterations": 6}},
    )
    explicit = tmp_path / "explicit.yaml"
    _write_yaml(
        explicit,
        {"design_with_ppa": {"min_optimization_iterations": 7}},
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DESIGN_WITH_PPA_MIN_OPTIMIZATION_ITERATIONS", "5")
    cfg = get_config(
        str(explicit),
        [{"design_with_ppa.min_optimization_iterations": 9}],
        str(tmp_path),
        workflow_config_file=str(workflow),
    )
    assert cfg.get_value("design_with_ppa.min_optimization_iterations") == 9
    loaded = cfg._loaded_config_files
    assert loaded.index(str(workflow)) < loaded.index(str(workspace_setting))
    assert loaded.index(str(workspace_setting)) < loaded.index(str(explicit))
    cfg.un_freeze()
    cfg._temp_cfg = {"DUT": "dut", "OUT": "output"}
    cfg.freeze()
    runtime = build_runtime_config(
        cfg,
        runtime_config_keys=["design_with_ppa.min_optimization_iterations"],
        launch_context={
            "config_file": str(explicit),
            "plugin_selectors": ["design-with-ppa"],
            "plugin_workflow": "design-with-ppa:unit-design-tdd",
            "workflow_config_file": str(workflow),
        },
    )
    assert runtime["plugin_options"] == {
        "design_with_ppa.min_optimization_iterations": 9
    }
    assert runtime["launch_context"] == {
        "config_file": str(explicit),
        "plugin_selectors": ["design-with-ppa"],
        "plugin_workflow": "design-with-ppa:unit-design-tdd",
        "workflow_config_file": str(workflow),
    }

    # The rendered shared conftest is workflow-protected: the raw workflow
    # layer declares it un-writable and template resolution expands {OUT}
    # before the write guard and read-only chmod consume the list.
    cfg.un_freeze()
    cfg.update_template({"DUT": "dut", "OUT": "output"})
    cfg.freeze()
    assert cfg.get_value("un_write_dirs") == ["output/tests/conftest.py"]

    # The plugin must teach its agent the reserved full_output escalation:
    # compact diagnostics by default, complete output only on request.
    workflow = load_yaml_with_env_vars(
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    tips = workflow["mission"]["prompt"]["tips"]["always"]
    assert any("full_output" in tip and "默认不要开启" in tip for tip in tips)
    assert "full_output" in workflow["mission"]["prompt"]["system"]




def test_all_declared_runtime_config_keys_export_as_scalars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every plugin-declared runtime config key must export as a finite scalar."""

    workflow = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    monkeypatch.chdir(tmp_path)
    for name in (
        "DESIGN_WITH_PPA_MIN_OPTIMIZATION_ITERATIONS",
        "DESIGN_WITH_PPA_MAX_OPTIMIZATION_ITERATIONS",
        "DESIGN_WITH_PPA_NO_IMPROVEMENT_PATIENCE",
        "DESIGN_WITH_PPA_NO_REGRESSION_METRICS",
    ):
        monkeypatch.delenv(name, raising=False)
    cfg = get_config(None, None, str(tmp_path), workflow_config_file=str(workflow))
    cfg.un_freeze()
    cfg._temp_cfg = {"DUT": "dut", "OUT": "output"}
    cfg.freeze()
    plugin = get_plugin()
    declared = [
        key
        for workflow_entry in plugin.workflows
        for key in workflow_entry.runtime_config_keys
    ]
    assert declared, "plugin must declare runtime config keys"
    runtime = build_runtime_config(cfg, runtime_config_keys=declared)
    options = runtime["plugin_options"]
    assert set(declared) <= set(options)
    for key, value in options.items():
        assert value is None or isinstance(
            value, (bool, str, int, float)
        ), f"{key} must export as a finite JSON scalar, got {type(value)}"
    assert options["design_with_ppa.no_regression_metrics"] == "performance,timing"
    assert options["design_with_ppa.score_weights.timing"] == 1.0
    assert options["design_with_ppa.score_weights.area"] == 1.0
    assert options["design_with_ppa.score_weights.power"] == 1.0




def test_workflow_uses_ordered_tdd_substages_without_exposing_builder() -> None:
    """The workflow must reuse core gates while hiding internal RTL build details."""

    workflow_path = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    workflow = load_yaml_with_env_vars(workflow_path)
    plugin_workflow = get_plugin().workflows[0]
    assert plugin_workflow.template_context_factory is build_rtl_template_context
    assert "design_observation_contract.md" in workflow["guide_doc"][
        "plugin_copy_policy"
    ]["retain"]
    assert [stage["name"] for stage in workflow["stage"]] == [
        "design_contract",
        "python_executable_spec_and_ut",
        "rtl_preliminary_design",
        "rtl_tdd_implementation",
        "performance_contract",
        "performance_test_authoring",
        "performance_evidence",
        "ppa_optimization",
        "final_documentation_sync",
    ]
    ppa_stages = workflow["stage"][7]["stage"]
    assert [stage["name"] for stage in ppa_stages] == [
        "ppa_base_characterization",
        "ppa_candidate_optimization",
        "ppa_best_version_finalization",
        "ppa_result_artifacts",
    ]
    assert [stage["checker"][-1]["clss"] for stage in ppa_stages] == [
        "PPABaseCharacterizationChecker",
        "PPACandidateOptimizationChecker",
        "RTLBackendBuildChecker",
        "PPAResultArtifactsChecker",
    ]
    result_stage = ppa_stages[-1]
    assert "{OUT}/{DUT}_ppa_dashboard.html" in result_stage["output_files"]
    assert "{OUT}/{DUT}_performance_curve.svg" not in result_stage["output_files"]
    result_checker = result_stage["checker"][0]
    assert result_checker["args"]["dashboard_file"] == (
        "{OUT}/{DUT}_ppa_dashboard.html"
    )
    assert "performance_curve_svg_file" not in result_checker["args"]
    assert "test_dir" not in result_checker["args"]
    assert "test_glob" not in result_checker["args"]
    documentation_stage = workflow["stage"][-1]
    assert documentation_stage["name"] == "final_documentation_sync"
    documentation_stages = documentation_stage["stage"]
    assert [stage["name"] for stage in documentation_stages] == [
        "final_interface_and_architecture_docs",
        "final_requirement_and_function_docs",
        "final_design_summary",
        "final_documentation_and_delivery_validation",
    ]
    final_validation = documentation_stages[-1]
    assert any(
        checker["clss"] == "DesignDocumentationSyncChecker"
        for checker in final_validation["checker"]
    )
    final_delivery = final_validation["checker"][0]
    assert final_delivery["clss"] == "DesignFinalDeliveryChecker"
    assert final_delivery["args"]["test_dir"] == "{OUT}/tests"
    assert final_delivery["args"]["test_glob"] == "{OUT}/tests/test_{DUT}_*.py"
    assert "design_contract_files" not in final_delivery["args"]
    all_test_gates = [
        (parent["name"], child["name"], checker)
        for parent in workflow["stage"]
        for child in parent.get("stage", [parent])
        for checker in child.get("checker", [])
        if checker["clss"] == "DesignFinalDeliveryChecker"
        and "test_dir" in checker.get("args", {})
    ]
    assert all_test_gates == [
        (
            "final_documentation_sync",
            "final_documentation_and_delivery_validation",
            final_delivery,
        )
    ]
    documentation_text = json.dumps(documentation_stage, ensure_ascii=False)
    assert "不得创建、保留或引用 Bug 分析文档" in documentation_text
    python_stages = workflow["stage"][1]["stage"]
    assert [stage["name"] for stage in python_stages] == [
        "python_reference_model",
        "shared_environment_adapter",
        "shared_environment_fixture",
        "shared_test_api",
        "python_executable_spec_smoke",
        "functional_observation_contract",
        "functional_observation_instrumentation",
        "functional_coverage_structure",
        "functional_coverage_checkpoints",
        "shared_test_templates",
        "shared_test_implementation",
        "shared_test_refinement",
        "deterministic_random_tests",
        "python_reference_all_pass",
    ]
    configured_checkers = {
        checker["clss"]
        for stage in workflow["stage"]
        for child in stage.get("stage", [stage])
        for checker in child.get("checker", [])
    }
    assert {
        "DesignLabelStructureRefineChecker",
        "DesignCoverageStructureChecker",
        "DesignCoverageGroupBatchChecker",
        "DesignTestTemplateChecker",
        "DesignAllPassBatchTestsChecker",
        "DesignRefineTestCasesChecker",
        "{RTL_SOURCE_VALIDATION_CHECKER}",
        "DesignRandomTestCasesChecker",
        "DesignObservationContractChecker",
        "DesignObservationInstrumentationChecker",
        "DesignLineMapReferenceChecker",
        "PPABaseCharacterizationChecker",
        "PPACandidateOptimizationChecker",
        "PPABestVersionChecker",
        "PPAResultArtifactsChecker",
        "DesignDocumentationSyncChecker",
        "DesignPythonAllPassChecker",
    } <= configured_checkers
    assert DesignAllPassBatchTestsChecker in get_plugin().checkers
    assert DesignMarkdownFileFormatChecker in get_plugin().checkers
    assert DesignLabelStructureChecker in get_plugin().checkers
    assert DesignDutApiChecker in get_plugin().checkers
    assert DesignPythonAllPassChecker in get_plugin().checkers
    assert DesignCoverageStructureChecker in get_plugin().checkers
    assert DesignCoverageGroupBatchChecker in get_plugin().checkers
    assert DesignTestTemplateChecker in get_plugin().checkers
    assert PythonReferenceContractChecker in get_plugin().checkers
    assert PythonAdapterContractChecker in get_plugin().checkers
    assert PythonEnvFixtureContractChecker in get_plugin().checkers
    assert PythonExecutableSpecChecker in get_plugin().checkers
    assert DesignObservationContractChecker in get_plugin().checkers
    assert DesignObservationInstrumentationChecker in get_plugin().checkers
    assert DesignLineMapReferenceChecker in get_plugin().checkers
    assert PPABaseCharacterizationChecker in get_plugin().checkers
    assert PPACandidateOptimizationChecker in get_plugin().checkers
    assert PPABestVersionChecker in get_plugin().checkers
    assert PPAResultArtifactsChecker in get_plugin().checkers
    assert DesignDocumentationSyncChecker in get_plugin().checkers
    design_stages = workflow["stage"][0]["stage"]
    assert [stage["name"] for stage in design_stages] == [
        "design_needs_and_plan",
        "design_basic_information",
        "design_function_contract",
        "design_spec_line_mapping",
        "design_function_contract_refinement",
        "design_architecture_contract",
    ]
    design_stage_by_name = {stage["name"]: stage for stage in design_stages}
    assert design_stage_by_name["design_needs_and_plan"]["output_files"] == [
        "{OUT}/{DUT}_design_needs_and_plan.md"
    ]
    assert design_stage_by_name["design_basic_information"]["output_files"] == [
        "{OUT}/{DUT}_basic_info.md"
    ]
    assert design_stage_by_name["design_function_contract"]["output_files"] == [
        "{OUT}/{DUT}_functions_and_checks.md"
    ]
    assert design_stage_by_name["design_spec_line_mapping"]["output_files"] == [
        "{OUT}/line_map/*_line_func_map.txt"
    ]
    assert design_stage_by_name["design_function_contract_refinement"][
        "output_files"
    ] == [
        "{OUT}/{DUT}_functions_and_checks.md",
        "{OUT}/line_map/*_line_func_map.txt",
    ]
    assert [
        checker["name"]
        for checker in design_stage_by_name["design_needs_and_plan"]["checker"]
    ] == ["design_inputs", "contract_markdown"]
    assert [
        checker["name"]
        for checker in design_stage_by_name["design_basic_information"]["checker"]
    ] == ["basic_info_markdown"]
    assert [
        checker["name"]
        for checker in design_stage_by_name["design_function_contract"]["checker"]
    ] == ["function_contract_markdown", "portable_label_ids", "functional_labels"]
    refinement_checker = design_stage_by_name[
        "design_function_contract_refinement"
    ]["checker"][0]
    assert refinement_checker["clss"] == "DesignLabelStructureRefineChecker"
    assert refinement_checker["args"]["must_have_prefix"] == ""
    functional_test_stages = {
        stage["name"]: stage
        for stage in python_stages
    }
    assert functional_test_stages["python_reference_model"]["output_files"] == [
        "{OUT}/tests/{DUT}_reference.py"
    ]
    assert functional_test_stages["shared_environment_adapter"]["output_files"] == [
        "{OUT}/tests/{DUT}_adapter.py"
    ]
    assert functional_test_stages["shared_environment_fixture"]["output_files"] == [
        "{OUT}/tests/conftest.py"
    ]
    assert functional_test_stages["shared_test_api"]["output_files"] == [
        "{OUT}/tests/{DUT}_api.py"
    ]
    assert functional_test_stages["python_executable_spec_smoke"]["output_files"] == [
        "{OUT}/tests/test_{DUT}_smoke.py",
        "{OUT}/reports/{DUT}_python_smoke.json",
        "{OUT}/tests/{DUT}_reference.py",
        "{OUT}/tests/{DUT}_adapter.py",
        "{OUT}/tests/{DUT}_api.py",
        "{OUT}/tests/conftest.py",
    ]
    assert functional_test_stages["functional_observation_contract"][
        "output_files"
    ] == ["{OUT}/{DUT}_observation_contract.yaml"]
    assert functional_test_stages["functional_observation_instrumentation"][
        "output_files"
    ] == ["{OUT}/tests/{DUT}_adapter.py", "{OUT}/tests/{DUT}_api.py"]
    assert functional_test_stages["functional_coverage_checkpoints"][
        "output_files"
    ] == ["{OUT}/tests/{DUT}_function_coverage_def.py"]
    assert functional_test_stages["shared_test_implementation"]["output_files"] == [
        "{OUT}/tests/test_{DUT}_*.py",
        "{OUT}/{DUT}_observation_contract.yaml",
        "{OUT}/tests/{DUT}_reference.py",
        "{OUT}/tests/{DUT}_adapter.py",
        "{OUT}/tests/{DUT}_api.py",
        "{OUT}/tests/{DUT}_function_coverage_def.py",
        "{OUT}/tests/conftest.py",
    ]
    assert [
        functional_test_stages[name]["checker"][0]["clss"]
        for name in (
            "python_reference_model",
            "shared_environment_adapter",
            "shared_environment_fixture",
            "shared_test_api",
            "python_executable_spec_smoke",
        )
    ] == [
        "PythonReferenceContractChecker",
        "PythonAdapterContractChecker",
        "PythonEnvFixtureContractChecker",
        "DesignDutApiChecker",
        "PythonExecutableSpecChecker",
    ]
    assert functional_test_stages["functional_coverage_structure"][
        "reference_files"
    ][-2:] == [
        "{OUT}/tests/{DUT}_adapter.py",
        "{OUT}/tests/conftest.py",
    ]
    for stage_name in (
        "shared_test_templates",
        "shared_test_implementation",
        "shared_test_refinement",
        "deterministic_random_tests",
    ):
        assert functional_test_stages[stage_name]["checker"][0]["args"][
            "ignore_ck_prefix"
        ] == ["FG-PPA/", "FG-PPA-"]
    for stage_name in (
        "shared_test_templates",
        "shared_test_implementation",
        "shared_test_refinement",
    ):
        assert functional_test_stages[stage_name]["checker"][0]["args"][
            "ignore_tc_prefix"
        ] == [
            "test_{DUT}_smoke",
            "test_{DUT}_performance",
            "test_{DUT}_ppa",
        ]
    python_receipt = functional_test_stages["python_reference_all_pass"]["checker"][1]
    assert python_receipt["args"]["exclude_test_globs"] == [
        "{OUT}/tests/test_{DUT}_performance*.py",
        "{OUT}/tests/test_{DUT}_ppa*.py",
    ]
    rtl_stages = {
        stage["name"]: stage
        for stage in workflow["stage"][3]["stage"]
    }
    assert "rtl_implementation_and_validation" in rtl_stages
    assert "rtl_implementation_and_backend_sync" not in rtl_stages
    rtl_receipt = rtl_stages["rtl_shared_regression"]["checker"][0]
    assert rtl_stages["rtl_shared_regression"]["desc"] == (
        "RTL 同套测试回归 [Pass {RTL_TESTS_PASSED}/{RTL_TESTS_TOTAL} TC]"
    )
    rtl_regression_task = "\n".join(rtl_stages["rtl_shared_regression"]["task"])
    assert "先对当前同一目标 TC 集复验 Python executable specification" in (
        rtl_regression_task
    )
    assert "不要把测试期望改成 RTL 的错误输出" in rtl_regression_task
    assert "RunTestCases 只验证 Python" in rtl_regression_task
    assert rtl_stages["rtl_shared_regression"]["skill_list"] == [
        "ext/design-with-ppa/rtl-tdd-backend"
    ]
    assert rtl_stages["rtl_shared_regression"]["force_use_skill"] is False
    assert "output_files" not in rtl_stages["rtl_shared_regression"]
    assert rtl_receipt["args"]["exclude_test_globs"] == [
        "{OUT}/tests/test_{DUT}_performance*.py",
        "{OUT}/tests/test_{DUT}_ppa*.py",
    ]
    rtl_line_coverage = rtl_stages["rtl_line_coverage"]["checker"][0]
    assert rtl_line_coverage["args"]["ignore_ck_prefix"] == [
        "FG-PPA/",
        "FG-PPA-",
    ]
    assert rtl_line_coverage["args"]["ignore_tc_prefix"] == [
        "test_{DUT}_performance",
        "test_{DUT}_ppa",
    ]
    rtl_line_coverage_stage = rtl_stages["rtl_line_coverage"]
    assert "doc_bug_analysis" not in rtl_line_coverage["args"]
    assert "{RTL_SOURCE_VALIDATION_GUIDE}" in rtl_line_coverage_stage[
        "reference_files"
    ]
    rtl_line_task = "\n".join(rtl_line_coverage_stage["task"])
    assert "{RTL_SOURCE_VALIDATION_TASK}" in rtl_line_task
    assert "{RTL_SOURCE_VALIDATION_REPORT}" in rtl_line_task
    assert "中间源码" not in rtl_line_task
    assert rtl_line_coverage_stage["output_files"] == [
        "{RTL_SOURCE_VALIDATION_REPORT}",
        "{OUT}/tests/{DUT}.ignore",
        "{RTL_SOURCE_GLOB}",
        "{OUT}/tests/test_{DUT}_*.py",
    ]
    runtime_roots = [
        PLUGIN_SOURCE / "design_with_ppa" / "workflows",
        PLUGIN_SOURCE / "design_with_ppa" / "Guide_Doc",
        PLUGIN_SOURCE / "design_with_ppa" / "templates",
        PLUGIN_SOURCE / "design_with_ppa" / "skills",
    ]
    for root in runtime_roots:
        for path in root.rglob("*"):
            if path.is_file():
                content = path.read_text(encoding="utf-8", errors="ignore")
                assert "picker" not in content.lower(), path
                assert "--design-backend" not in content, path




def test_workflow_keeps_ppa_tool_available_and_requires_selected_language_only() -> None:
    """The workflow keeps the plugin PPA tool available without exposing private plumbing."""

    workflow_path = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    workflow = load_yaml_with_env_vars(workflow_path)
    assert "AnalyzePPA" not in workflow["tools"]["ignore_tools"]
    llm_contract = json.dumps(
        {
            "mission": workflow["mission"],
            "stage": workflow["stage"],
        },
        ensure_ascii=False,
    )
    assert "AnalyzePPA" not in llm_contract
    assert "baseline_report_id" not in llm_contract
    assert "自动" in llm_contract

    def public_stage_text(stage: dict[str, Any]) -> str:
        """Project only stage fields rendered into the LLM task contract."""

        fields = {
            key: stage.get(key)
            for key in ("name", "desc", "task", "reference_files", "output_files")
        }
        return json.dumps(fields, ensure_ascii=False) + "".join(
            public_stage_text(child) for child in stage.get("stage", [])
        )

    public_contract = json.dumps(
        workflow["mission"], ensure_ascii=False
    ) + "".join(public_stage_text(stage) for stage in workflow["stage"])
    for private_term in (
        "Picker",
        "baseline_report_id",
        "PPA report_id",
        "转换命令",
        "中间源码",
        "自动生成的测试 DUT",
        "private manifest",
        "Checker",
        "WorkCommit",
        "GoToStage",
        ".ucagent",
        "内部快照",
        "内部历史",
        "隔离测试进程",
        "RTL backend 是",
        "其他 RTL 语言中间文件",
        "PPA_ACCEPTED_REPORT_ID",
        "PPA_ITERATION_STATUS",
        "record_base",
        "author_candidate",
        "finalize_delivery",
        "恢复被拒绝",
        "reports/design_input_manifest.json",
    ):
        assert private_term.lower() not in public_contract.lower()
    assert "使用 `{RTL_LANGUAGE}` 设计并优化 `{DUT}` 单元电路" in workflow["mission"][
        "prompt"
    ]["system"]
    assert "`{RTL_SOURCE_GLOB}`" in workflow["mission"]["prompt"]["system"]
    line_map_stage = next(
        stage
        for stage in workflow["stage"][0]["stage"]
        if stage["name"] == "design_spec_line_mapping"
    )
    assert "Guide_Doc/dut_line_func_map.md" in line_map_stage["reference_files"]
    assert "单行也写成 `10-10`" in "\n".join(line_map_stage["task"])
    python_stage_by_name = {
        stage["name"]: stage for stage in workflow["stage"][1]["stage"]
    }
    api_task = "\n".join(python_stage_by_name["shared_test_api"]["task"])
    assert "每个公开 API" in api_task
    assert "`Args:` 和 `Returns:`" in api_task
    implementation_stage = python_stage_by_name["shared_test_implementation"]
    implementation_task = "\n".join(
        str(item) for item in implementation_stage["task"]
    )
    assert "禁止追加同名 `def`" in implementation_task
    assert "顶层测试函数名唯一" in implementation_task
    assert "应直接修正 reference" in implementation_task
    assert "不得把 reference/expected 改成当前失败结果" in implementation_task
    assert workflow["skill"]["general_skill_list"] == []
    runtime_tips = json.dumps(
        workflow["mission"]["prompt"]["tips"], ensure_ascii=False
    )
    assert "dynamic-bug-recording" not in runtime_tips
    assert "static_bug_analysis" not in runtime_tips
    assert "ref_model fixture" not in runtime_tips




def test_workflow_keeps_reference_repairable_without_following_wrong_rtl() -> None:
    """Every later phase must distinguish a repairable reference from frozen behavior."""

    workflow_path = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    workflow = load_yaml_with_env_vars(workflow_path)
    mission_text = json.dumps(workflow["mission"], ensure_ascii=False)
    assert "不是永久冻结或不可修改的 oracle" in mission_text
    assert "不得为了迁就" in mission_text
    assert "重新运行受影响的 Python 测试" in mission_text
    assert "对应 FG/FC/CK 的功能覆盖" in mission_text
    assert "TC 可以与 reference 一同完善，也可以单独完善" in mission_text

    python_stages = {
        stage["name"]: stage for stage in workflow["stage"][1]["stage"]
    }
    shared_implementation = "\n".join(
        str(item) for item in python_stages["shared_test_implementation"]["task"]
    )
    assert "应直接修正 reference" in shared_implementation
    assert "不得把 reference/expected 改成当前失败结果" in shared_implementation
    assert "对应 FG/FC/CK 的功能覆盖" in shared_implementation
    assert "TC 可以与 reference 一同完善，也可以单独完善" in shared_implementation

    python_gate = python_stages["python_reference_all_pass"]
    assert "{OUT}/tests/{DUT}_reference.py" in python_gate["output_files"]
    assert "Python reference 在本门禁仍可修改" in "\n".join(python_gate["task"])
    python_gate_task = "\n".join(python_gate["task"])
    assert "对应 FG/FC/CK 的功能覆盖" in python_gate_task
    assert "TC 可以与 reference 一同完善，也可以单独完善" in python_gate_task

    rtl_stages = {
        stage["name"]: stage for stage in workflow["stage"][3]["stage"]
    }
    rtl_task = "\n".join(rtl_stages["rtl_shared_regression"]["task"])
    assert "reference 不是永久冻结文件" in rtl_task
    assert "Python reference 通过而 RTL 失败" in rtl_task

    performance_task = "\n".join(workflow["stage"][5]["task"])
    assert "可以修正 reference" in performance_task
    assert "不得为了得到更好性能数据" in performance_task
    ppa_task = "\n".join(workflow["stage"][7]["task"])
    assert "reference 即使进入本阶段也不是永久不可修改" in ppa_task
    assert "重建 base" in ppa_task

    final_validation = workflow["stage"][-1]["stage"][-1]
    final_task = "\n".join(final_validation["task"])
    assert "reference 与权威功能合同不一致时仍可修正" in final_task
    assert "reference 已按合同通过而 RTL 失败时不得改" in final_task

    guide_dir = PLUGIN_SOURCE / "design_with_ppa" / "Guide_Doc"
    guide_text = "\n".join(
        (guide_dir / name).read_text(encoding="utf-8")
        for name in (
            "python_executable_spec.md",
            "python_dut_interface.md",
            "design_ut_contract.md",
            "rtl_backend.md",
        )
    )
    assert "Python reference" in guide_text
    assert "不是创建后永久冻结的 oracle" in guide_text
    assert "不能为了迁就错误" in guide_text

    skill_dir = PLUGIN_SOURCE / "design_with_ppa" / "skills"
    skill_text = "\n".join(
        (skill_dir / name / "SKILL.md").read_text(encoding="utf-8")
        for name in (
            "shared-ut-structure",
            "rtl-tdd-backend",
            "performance-tc-scaffold",
            "ppa-iteration-analysis",
        )
    )
    assert "not permanently frozen" in skill_text
    assert "Never change reference behavior" in skill_text




def test_workflow_overrides_unrelated_core_unitytest_tips(tmp_path: Path) -> None:
    """Resolved plugin prompts must not inherit Bug-verification-only guidance."""

    workflow_path = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    cfg = get_config(
        None,
        [],
        str(tmp_path),
        workflow_config_file=str(workflow_path),
    )
    tips = json.dumps(cfg.mission.prompt.tips.as_dict(), ensure_ascii=False)

    assert cfg.skill.general_skill_list == []
    assert "dynamic-bug-recording" not in tips
    assert "static_bug_analysis" not in tips
    assert "ref_model fixture" not in tips
    assert "{RTL_LANGUAGE}" in tips




@pytest.mark.parametrize(
    ("language", "overrides", "expected_language", "unexpected_language", "source_glob"),
    [
        ("verilog", [], "Verilog", "Chisel", "output/rtl/*.v"),
        (
            "chisel",
            [
                {"design_with_ppa.rtl.language": "chisel"},
                {"design_with_ppa.rtl.source_glob": "output/rtl/*.scala"},
                {"design_with_ppa.rtl.source_template": "chisel-7"},
            ],
            "Chisel",
            "Verilog",
            "output/rtl/*.scala",
        ),
    ],
)
def test_rendered_workflow_exposes_only_selected_rtl_language(
    tmp_path: Path,
    language: str,
    overrides: list[dict[str, str]],
    expected_language: str,
    unexpected_language: str,
    source_glob: str,
) -> None:
    """Rendered LLM guidance must describe only the selected source language."""

    workflow_path = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    cfg = get_config(
        None,
        overrides,
        str(tmp_path),
        workflow_config_file=str(workflow_path),
    )
    base_context = {"DUT": "dut", "OUT": "output", "WORKSPACE": str(tmp_path)}
    cfg.un_freeze()
    cfg.set_value("skill.use_skill", False)
    cfg._temp_cfg = base_context
    cfg.update_template(base_context)
    cfg.update_template(build_rtl_template_context(cfg, base_context))
    plugin = get_plugin()
    stages = parse_vstage(
        cfg,
        cfg.stage,
        str(tmp_path),
        None,
        checker_registry={checker.__name__: checker for checker in plugin.checkers},
    )
    public_contract = json.dumps(
        {
            "mission": cfg.mission.as_dict(),
            "stages": [
                child.public_detail()
                for parent in stages
                for child in parent.get_substages()
            ],
        },
        ensure_ascii=False,
    )

    assert f"使用 `{expected_language}` 设计并优化 `dut` 单元电路" in public_contract
    assert source_glob in public_contract
    assert expected_language in public_contract
    assert unexpected_language not in public_contract
    assert f'"language": "{language}"' not in public_contract
    for private_term in (
        "Picker",
        "FIRRTL",
        "Mill",
        "report_id",
        "baseline_report_id",
        "python_dut_import",
        "rtl_backend_manifest",
        ".ucagent",
        "WorkCommit",
        "snapshot",
        "Checker",
        "转换命令",
        "中间 Verilog",
    ):
        assert private_term.lower() not in public_contract.lower()




def test_coding_standard_verilog_is_advisory_and_referenced_by_rtl_stage() -> None:
    """Verilog guidance must be complete and advisory, without a style gate."""

    guide = (
        PLUGIN_SOURCE
        / "design_with_ppa"
        / "Guide_Doc"
        / "coding_standard_verilog.md"
    ).read_text(encoding="utf-8")
    workflow = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    ).read_text(encoding="utf-8")
    assert "IEEE 1364-2005" in guide
    assert "RTL-GUIDE-DEVIATION" in guide
    for required in (
        "## 注释结构（建议）",
        "文件级注释",
        "module/参数注释",
        "端口注释",
        "时序注释",
        "核心逻辑注释",
        "Module: Example",
        "Interface: list every port",
    ):
        assert required in guide
    assert "建议" in guide
    assert "Guide_Doc/coding_standard_verilog.md" in workflow
    for required in (
        "每个源码文件开头写与实际实现一致的模块/类功能说明",
        "为每个端口写方向、位宽、signedness",
        "RTL-GUIDE-DEVIATION",
        "不是独立风格门禁",
    ):
        assert required in workflow
    assert "VerilogCodingStyleChecker" not in workflow
    assert _template_context()["RTL_SOURCE_VALIDATION_CHECKER"] == (
        "RTLLineCoverageChecker"
    )
    assert _template_context()["RTL_SOURCE_VALIDATION_GUIDE"] == (
        "Guide_Doc/rtl_line_coverage.md"
    )
    assert "reasons in the configured" not in _template_context()[
        "RTL_SOURCE_VALIDATION_TASK"
    ]
    assert "line_coverage_analysis.md" in _template_context()[
        "RTL_SOURCE_VALIDATION_TASK"
    ]




def test_rtl_template_context_uses_initialization_base_output(tmp_path: Path) -> None:
    """Dynamic context must work before VerifyAgent persists its template cache."""

    workflow = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    cfg = get_config(
        None,
        [],
        str(tmp_path),
        workflow_config_file=str(workflow),
    )
    base_context = {
        "DUT": "dut",
        "OUT": "output/runtime-verilog",
        "WORKSPACE": str(tmp_path),
    }
    cfg.update_template(base_context)

    assert cfg.get_value("_temp_cfg", None) is None
    context = build_rtl_template_context(cfg, base_context)

    assert context["RTL_SOURCE_GLOB"] == "output/runtime-verilog/rtl/*.v"
    assert context["RTL_SOURCE_FILE"] == "dut.v"




def test_workflow_default_has_no_rtl_library_append_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An absent library-path environment variable must resolve to no library."""

    monkeypatch.delenv("DESIGN_WITH_PPA_RTL_LIBRARY_PATHS", raising=False)
    workflow = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    cfg = get_config(
        None,
        [],
        str(tmp_path),
        workflow_config_file=str(workflow),
    )
    base_context = {
        "DUT": "dut",
        "OUT": "output/runtime-verilog",
        "WORKSPACE": str(tmp_path),
    }
    cfg.update_template(base_context)

    resolved, _ = resolve_rtl_config(cfg, output_dir=base_context["OUT"])

    assert cfg.get_value("design_with_ppa.rtl.library_path_append") == ""
    assert resolved.library_paths == ()




def test_workflow_routes_python_execution_without_exposing_process_details() -> None:
    """Public contracts must require test tools without describing isolation internals."""

    runtime_files = [
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml",
        PLUGIN_SOURCE / "design_with_ppa" / "Guide_Doc" / "python_executable_spec.md",
        PLUGIN_SOURCE / "design_with_ppa" / "Guide_Doc" / "design_ut_contract.md",
        PLUGIN_SOURCE / "design_with_ppa" / "Guide_Doc" / "rtl_backend.md",
        PLUGIN_SOURCE / "design_with_ppa" / "Guide_Doc" / "performance_measurement.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)

    assert "RunTestCases" in combined
    assert "target 相对 `{OUT}/tests`" in combined
    assert "`python -c`" in combined
    assert "不得直接 import" in combined
    assert "隔离测试进程" not in combined




@pytest.mark.parametrize("skills_enabled", [False, True])
def test_workflow_constructs_with_optional_skills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    skills_enabled: bool,
) -> None:
    """All workflow Checker constructors must work with Skills disabled or installed."""

    workflow_path = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    (tmp_path / "dut" / "spec").mkdir(parents=True)
    (tmp_path / "dut" / "README.md").write_text("README\n", encoding="utf-8")
    (tmp_path / "dut" / "spec" / "design.md").write_text(
        "Design spec.\n", encoding="utf-8"
    )
    if skills_enabled:
        source = PLUGIN_SOURCE / "design_with_ppa" / "skills"
        destination = (
            tmp_path / ".ucagent" / "skills" / "ext" / "design-with-ppa"
        )
        shutil.copytree(source, destination)
    monkeypatch.chdir(tmp_path)
    cfg = get_config(
        None,
        None,
        str(tmp_path),
        workflow_config_file=str(workflow_path),
    )
    cfg.un_freeze()
    cfg.set_value("skill.use_skill", skills_enabled)
    cfg._temp_cfg = _template_context("output", str(tmp_path))
    cfg.update_template(cfg._temp_cfg)
    plugin = get_plugin()
    registry = {checker.__name__: checker for checker in plugin.checkers}
    stages = parse_vstage(
        cfg,
        cfg.stage,
        str(tmp_path),
        None,
        checker_registry=registry,
    )
    flattened = [child for stage in stages for child in stage.get_substages()]
    assert len(flattened) == 35
    functional_stage = next(
        stage for stage in flattened if stage.name == "shared_test_implementation"
    )
    functional_checker = next(
        checker
        for checker in functional_stage.checker
        if isinstance(checker, DesignAllPassBatchTestsChecker)
    )
    assert functional_checker.cfg is cfg
    assert functional_checker.extra_kwargs["cfg"] is cfg
    required_stage_skills = {
        "design_spec_line_mapping": "ext/design-with-ppa/spec-line-mapping",
        "functional_coverage_structure": "ext/design-with-ppa/shared-ut-structure",
        "functional_coverage_checkpoints": "ext/design-with-ppa/shared-ut-structure",
        "shared_test_templates": "ext/design-with-ppa/shared-ut-structure",
        "performance_test_authoring": "ext/design-with-ppa/performance-tc-scaffold",
    }
    optional_stage_skills = {
        "rtl_implementation_and_validation": "ext/design-with-ppa/rtl-tdd-backend",
        "rtl_shared_regression": "ext/design-with-ppa/rtl-tdd-backend",
        "ppa_candidate_optimization": "ext/design-with-ppa/ppa-iteration-analysis",
    }
    observed_stage_skills = {
        stage.name: list(stage.skill_list)
        for stage in flattened
        if stage.skill_list
    }
    expected_stage_skills = {
        name: [skill]
        for name, skill in {**required_stage_skills, **optional_stage_skills}.items()
    }
    assert observed_stage_skills == (expected_stage_skills if skills_enabled else {})
    for stage_name, skill_name in required_stage_skills.items():
        stage = next(item for item in flattened if item.name == stage_name)
        assert list(stage.skill_list) == ([skill_name] if skills_enabled else [])
        assert stage.force_use_skill is True
    for stage_name in optional_stage_skills:
        stage = next(item for item in flattened if item.name == stage_name)
        assert stage.force_use_skill is False




def test_workflow_constructs_chisel_specific_source_gate(tmp_path: Path) -> None:
    """Final Chisel config must render its guide, template, and private-safe gate."""

    workflow_path = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    cfg = get_config(
        None,
        [
            {"design_with_ppa.rtl.language": "chisel"},
            {"design_with_ppa.rtl.source_glob": "output/rtl/*.scala"},
            {"design_with_ppa.rtl.source_template": "chisel-7"},
        ],
        str(tmp_path),
        workflow_config_file=str(workflow_path),
    )
    base_context = {"DUT": "dut", "OUT": "output", "WORKSPACE": str(tmp_path)}
    cfg.un_freeze()
    cfg.set_value("skill.use_skill", False)
    cfg._temp_cfg = base_context
    cfg.update_template(base_context)
    language_context = build_rtl_template_context(cfg, base_context)
    cfg.update_template(language_context)
    plugin = get_plugin()
    registry = {checker.__name__: checker for checker in plugin.checkers}

    stages = parse_vstage(
        cfg,
        cfg.stage,
        str(tmp_path),
        None,
        checker_registry=registry,
    )
    flattened = [child for stage in stages for child in stage.get_substages()]
    implementation = next(
        stage
        for stage in flattened
        if stage.name == "rtl_implementation_and_validation"
    )
    source_gate = next(
        stage for stage in flattened if stage.name == "rtl_line_coverage"
    )

    assert implementation.output_files == ["output/rtl/*.scala"]
    assert isinstance(source_gate.checker[0], RTLSourceEvidenceChecker)
    assert source_gate.output_files == [
        "output/dut_chisel_source_validation.md",
        "output/tests/dut.ignore",
        "output/rtl/*.scala",
        "output/tests/test_dut_*.py",
    ]
    public_text = json.dumps(
        {
            "desc": source_gate.desc,
            "task": source_gate.task_list,
            "outputs": source_gate.output_files,
        },
        ensure_ascii=False,
    )
    assert "Verilog" not in public_text
    assert "Picker" not in public_text
    assert "build.sc" not in public_text
    assert "Guide_Doc/source_validation_chisel.md" in public_text
    guide_policy = resolve_plugin_guide_doc_copy_policy(cfg)
    assert guide_policy.action_for("coding_standard_chisel.md") == "retain"
    assert guide_policy.action_for("coding_standard_verilog.md") == "ignore"
    assert guide_policy.action_for("rtl_line_coverage.md") == "ignore"
    assert guide_policy.action_for("source_validation_chisel.md") == "retain"


def test_plugin_checkers_declare_consumed_stage_args() -> None:
    """Every stage_args key the prompts document must be declared by its gate."""

    from design_with_ppa.checkers import (
        DesignLabelStructureRefineChecker,
        DesignRandomTestCasesChecker,
        DesignRefineTestCasesChecker,
        RTLAllPassRegressionChecker,
    )

    assert set(DesignRandomTestCasesChecker.accepted_stage_args) == {"generated"}
    assert set(DesignRefineTestCasesChecker.accepted_stage_args) == {"refined"}
    assert set(DesignLabelStructureRefineChecker.accepted_stage_args) == {"refined"}
    assert set(RTLAllPassRegressionChecker.accepted_stage_args) == {"test_target"}


def test_rtl_preliminary_design_stage_is_lenient_and_positioned() -> None:
    """The pre-RTL conception stage only demands its design artifact."""

    workflow = load_yaml_with_env_vars(
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    names = [stage["name"] for stage in workflow["stage"]]
    rtl_index = names.index("rtl_tdd_implementation")
    design_index = names.index("rtl_preliminary_design")
    assert design_index == rtl_index - 1

    design_stage = workflow["stage"][design_index]
    assert design_stage["task"][0].startswith("目标：")
    assert [checker["clss"] for checker in design_stage["checker"]] == [
        "DesignMarkdownFileFormatChecker"
    ]
    assert design_stage["checker"][0]["args"]["markdown_file_list"] == (
        "{OUT}/{DUT}_rtl_design.md"
    )
    assert design_stage["output_files"] == ["{OUT}/{DUT}_rtl_design.md"]

    implementation = workflow["stage"][rtl_index]
    implementation_task = "\n".join(implementation["task"])
    assert "{OUT}/{DUT}_rtl_design.md" in implementation_task
    implementation_refs = implementation["stage"][0]["reference_files"]
    assert "{OUT}/{DUT}_rtl_design.md" in implementation_refs
