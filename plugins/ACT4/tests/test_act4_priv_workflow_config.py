"""Regression contracts for privileged generation without weakening its existing gates."""

from pathlib import Path

import pytest
import yaml

from ucagent_act4.checkers.act4_ai_review_checker import ACT4AIReviewChecker
from ucagent_act4.plugin import get_plugin

WORKFLOW = get_plugin().workflows[0].config_file


class UniqueKeyLoader(yaml.SafeLoader):
    """Load workflow YAML without allowing later keys to hide earlier requirements."""


def _construct_unique_mapping(loader, node, deep=False):
    """Reject repeated YAML keys at their original source location."""
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _load_workflow():
    """Read the privileged workflow while checking mapping uniqueness."""
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)


def _checker(stage, name):
    """Select the exact stage gate whose contract a regression test exercises."""
    return next(item for item in stage["checker"] if item["name"] == name)


def test_priv_workflow_has_unique_keys_and_environment_preparation_first() -> None:
    """Require resource/environment/input preparation before asset work."""
    workflow = _load_workflow()
    stages = workflow["stage"]

    assert len(stages) == 17
    assert stages[0]["name"] == "prepare_resources"
    assert stages[3]["name"] == "prepare_environment"
    stages = stages[3:]
    checker_names = [
        checker["name"] for stage in stages for checker in stage["checker"]
    ]
    assert len(checker_names) == len(set(checker_names))
    assert stages[-1]["name"] == "generate_final_human_report"


def test_stall_budget_is_scoped_to_generation_workflows() -> None:
    """Stop unproductive generation promptly without overriding review or handoff loop behavior."""
    for workflow in get_plugin().workflows:
        data = yaml.load(workflow.config_file.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
        if workflow.name.endswith("suite-generation"):
            assert data["loop_settings"]["max_stalled_rounds"] == 3
            assert "source-plan.yaml" not in workflow.config_file.read_text()
        else:
            assert data.get("loop_settings", {}).get("max_stalled_rounds") != 3


def test_composite_generation_has_no_single_filename_completion_gate() -> None:
    """The input scope and native validator, not a fabricated aggregate YAML, define completion."""
    for stage in _load_workflow()["stage"]:
        for checker in stage["checker"]:
            assert "riscv-arch-test/testplans/priv/{DUT}.yaml" not in checker["args"].get("required_artifacts", [])


def test_priv_workflow_checkers_accept_ucagent_cfg_injection() -> None:
    """UCAgent injects cfg into every checker constructor at stage startup."""
    workflow = _load_workflow()

    registry = {checker.__name__: checker for checker in get_plugin().checkers}
    for stage in workflow["stage"]:
        for checker in stage["checker"]:
            checker_class = registry[checker["clss"]]
            checker_class(**{key: value.replace("{DUT}", "ExampleSuite") if isinstance(value, str) else value for key, value in checker["args"].items()}, cfg=workflow)


def test_priv_workflow_enables_review_regression_gates() -> None:
    """Retain privileged coverage, VM, signature and model-scope safeguards."""
    stages = [stage for stage in _load_workflow()["stage"][3:]
              if stage["name"] not in {"prepare_environment", "prepare_generation_inputs", "review_audit", "review_repair", "plan_missing_capabilities", "verify_completed_capabilities"}]
    norm_args = _checker(stages[1], "act4_norm_mapping_asset_check")["args"]
    generator_args = _checker(stages[3], "act4_generator_asset_check")["args"]
    build_args = _checker(stages[4], "act4_generated_test_asset_check")["args"]
    contribution_args = _checker(
        stages[5], "act4_contribution_readiness_check"
    )["args"]
    manifest_args = _checker(
        stages[5], "act4_file_manifest_completeness_check"
    )["args"]

    metadata = "{OUT}/intermediate/{DUT}/inputs/norm-rules.json"
    for args in (norm_args, generator_args):
        assert args["require_norm_rules"] is True
        assert args["norm_rules"] == metadata
        for redundant in (
            "require_ctp",
            "exact_sheet_rules",
            "exact_sheet_coverpoints",
            "strict_ownership",
            "require_suite_group",
            "allow_cross_suite_groups",
            "fail_on_warning",
        ):
            assert redundant not in args
    assert generator_args["require_priv_coverage_semantics"] is True
    assert generator_args["require_standalone_generator"] is True
    intent = "{OUT}/intermediate/{DUT}/{DUT}_coverage_intent.yaml"
    assert generator_args["coverage_intent_contract"] == intent
    assert _checker(stages[0], "act4_coverage_asset_check")["args"][
        "coverage_intent_contract"
    ] == intent
    for args in (build_args, contribution_args):
        assert args["require_reference_model_logs"] is True
        assert args["require_reference_model_evaluation"] is True
        assert args["require_signature_completeness"] is True
        assert args["signature_progress_mode"] == "warning"
        assert args["require_generation_scope"] is True
        assert args["derive_priv_testcase_limit"] is True
        assert args["check_testcase_reachability"] is True
        assert "max_testcases_per_source" not in args
        assert "require_sail_coverage" not in args
        assert "require_matching_stems" not in args
        assert "require_nonempty" not in args
    assert "require_contribution_ready" not in build_args
    assert contribution_args["require_contribution_ready"] is True
    assert manifest_args["require_contribution_set"] is True
    assert _checker(stages[-1], "act4_final_report_manifest_completeness_check")["args"]["require_contribution_set"] is True
    assert _checker(stages[4], "act4_build_file_manifest_check")["args"][
        "inventory_patterns"
    ]
    switch_checkers = [
        checker
        for stage in stages
        for checker in stage["checker"]
        if "switch_capability_check" in checker["name"]
    ]
    assert switch_checkers
    assert all(
        checker["args"]["verify_audited_source_paths"] is True
        for checker in switch_checkers
    )
    required_runtime_capabilities = {
        "reference_model_executable",
        "signature_self_checking_execution",
        "sail_rvvi_coverage_backend",
    }
    for checker in switch_checkers[1:]:
        assert set(checker["args"]["required_capability_names"]) == (
            required_runtime_capabilities
        )

    final_args = _checker(
        stages[-1], "act4_final_human_report_check"
    )["args"]
    assert "{OUT}/intermediate/{DUT}/environment/summary.md" in final_args["required_reports"]
    assert "{OUT}/intermediate/{DUT}/reports/**/*" not in final_args["required_reports"]
    assert "required_phrases" not in final_args


@pytest.mark.parametrize(
    ("ci_state", "expected_pass"),
    [("missing", False), ("asset_error", False), ("tool_unavailable", True), ("passed", True)],
)
def test_contribution_gate_requires_ci_review_without_blocking_tool_limits(
    tmp_path: Path, ci_state: str, expected_pass: bool,
) -> None:
    """Separate genuine asset failures from explicitly unexecuted optional checks."""
    args = _checker(
        next(stage for stage in _load_workflow()["stage"] if stage["name"] == "prepare_to_contribute"), "act4_contribution_ai_review"
    )["args"]
    names = args["required_check_names"]
    assert "local_ci_reproduction" in names
    checks = [
        {
            "name": name,
            "status": "passed",
            "confidence": "confirmed",
            "evidence": ["test fixture evidence"],
            "conclusion": "test fixture passed",
            "workflow_blocking": False,
        }
        for name in names
        if name != "local_ci_reproduction" or ci_state != "missing"
    ]
    section = {
        "review_status": "approved",
        "summary": "test fixture contribution review",
        "checks": checks,
        "limitations": [],
        "blocking_issues": [],
        "artifacts": ["fixture.py"],
        "commands": [],
    }
    if ci_state in ("asset_error", "tool_unavailable"):
        ci_check = next(c for c in checks if c["name"] == "local_ci_reproduction")
        blocking = ci_state == "asset_error"
        ci_check.update(
            status="blocked" if blocking else "not_run",
            workflow_blocking=blocking,
            limitation=ci_state,
        )
        section["review_status"] = (
            "blocked" if blocking else "approved_with_limitations"
        )
        section["limitations"] = [ci_state]
        section["blocking_issues"] = [ci_state] if blocking else []
    review = {
        "schema_version": 1,
        "reviewer": "ai",
        "stages": {args["expected_stage"]: section},
    }
    (tmp_path / "review.yaml").write_text(yaml.safe_dump(review), encoding="utf-8")
    checker = ACT4AIReviewChecker(
        review_file="review.yaml",
        expected_stage=args["expected_stage"],
        required_check_names=names,
    ).set_workspace(str(tmp_path))

    passed, report = checker.do_check()

    assert passed is expected_pass, report
    if ci_state == "missing":
        assert any(
            finding["check"] == "ai_review_required_checks"
            and "local_ci_reproduction" in finding["message"]
            for finding in report["findings"]
        )

def test_priv_workflow_prevents_reference_model_scope_degradation() -> None:
    """Require scope-preserving diagnosis before using a fallback reference model."""
    stages = [stage for stage in _load_workflow()["stage"][3:]
              if stage["name"] not in {"prepare_environment", "prepare_generation_inputs", "review_audit", "review_repair", "plan_missing_capabilities", "verify_completed_capabilities"}]
    vm_text = "\n".join(stages[2]["task"])
    build_text = "\n".join(stages[4]["task"])

    assert "blocked 和 experimental profile 都必须包含 alternative_analysis" in vm_text
    assert "reference_model_evaluation" in build_text
    assert "fallback.scope_reduction" in build_text
    assert "换模型只能改变验证后端" in build_text
    assert "common_cause_evidence" in build_text
    assert "至少两个 target" in build_text
    assert "suite_local_resources" in build_text
    assert "positive_subset" in build_text
    assert "native_entrypoint" in build_text
    assert "generation_vs_validation_scope" in build_text


def test_native_inputs_and_validation_are_gated():
    """Native plans and rule snapshots replace brittle external spreadsheet discovery."""
    workflow = _load_workflow()
    stages = workflow["stage"]
    assert stages[4]["name"] == "prepare_generation_inputs"
    assert stages[4]["checker"][0]["clss"] == "ACT4GenerationInputsChecker"
    assert stages[-3]["checker"][0]["clss"] == "ACT4NativeValidationChecker"
    assert stages[-1]["checker"][0]["args"]["final_report"] == "{OUT}/final.md"
    plan_stage = next(stage for stage in stages if stage["name"] == "coverpoints file generation and testplan optimization")
    assert _checker(plan_stage, "act4_native_plan_check")["args"]["phase"] == "plan"
    assert _checker(stages[-4], "act4_native_contribution_assets")["args"]["kind"] == "privileged"
    for stage in stages:
        for reference in stage["reference_files"]:
            assert not any(token in reference for token in ("http://", "https://", "..", "*", "{OUT}", "{DUT}"))
        for checker in stage["checker"]:
            assert not any("coverpoints/param/" in path for path in checker["args"].get("required_artifacts", []))
