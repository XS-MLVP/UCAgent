import hashlib
from pathlib import Path

import pytest
import yaml

from act4_privileged_suite.checkers.act4_ai_review_checker import ACT4AIReviewChecker
from act4_privileged_suite.checkers.act4_manual_reference_checker import ACT4ManualReferenceChecker
from act4_privileged_suite.plugin import get_plugin

WORKFLOW = get_plugin().workflows[0].config_file


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader, node, deep=False):
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
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)


def _checker(stage, name):
    return next(item for item in stage["checker"] if item["name"] == name)


def test_priv_workflow_has_unique_keys_and_seven_ordered_stages() -> None:
    workflow = _load_workflow()
    stages = workflow["stage"]

    assert len(stages) == 7
    checker_names = [
        checker["name"] for stage in stages for checker in stage["checker"]
    ]
    assert len(checker_names) == len(set(checker_names))
    assert stages[-1]["name"] == "generate_final_human_report"


def test_priv_workflow_checkers_accept_ucagent_cfg_injection() -> None:
    """UCAgent injects cfg into every checker constructor at stage startup."""
    workflow = _load_workflow()

    registry = {checker.__name__: checker for checker in get_plugin().checkers}
    for stage in workflow["stage"]:
        for checker in stage["checker"]:
            checker_class = registry[checker["clss"]]
            checker_class(**checker["args"], cfg=workflow)


def test_priv_workflow_enables_review_regression_gates() -> None:
    stages = _load_workflow()["stage"]
    norm_args = _checker(stages[1], "act4_norm_mapping_asset_check")["args"]
    generator_args = _checker(stages[3], "act4_generator_asset_check")["args"]
    build_args = _checker(stages[4], "act4_generated_test_asset_check")["args"]
    contribution_args = _checker(
        stages[5], "act4_contribution_readiness_check"
    )["args"]
    manifest_args = _checker(
        stages[5], "act4_file_manifest_completeness_check"
    )["args"]

    metadata = "{OUT}/{DUT}/references/{DUT}_normative_rule_defs.yaml"
    for args in (norm_args, generator_args):
        assert args["require_norm_metadata"] is True
        assert args["normative_metadata"] == metadata
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
    intent = "{OUT}/{DUT}/{DUT}_coverage_intent.yaml"
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
    assert _checker(stages[6], "act4_final_report_manifest_completeness_check")["args"]["require_contribution_set"] is True
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
    assert "{OUT}/{DUT}/reports/**/*" not in final_args["required_reports"]
    assert "required_phrases" not in final_args


@pytest.mark.parametrize(
    ("ci_state", "expected_pass"),
    [("missing", False), ("asset_error", False), ("tool_unavailable", True), ("passed", True)],
)
def test_contribution_gate_requires_ci_review_without_blocking_tool_limits(
    tmp_path: Path, ci_state: str, expected_pass: bool,
) -> None:
    args = _checker(
        _load_workflow()["stage"][5], "act4_contribution_ai_review"
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
    stages = _load_workflow()["stage"]
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


def test_priv_workflow_discovers_ctp_sheet_and_manual_references() -> None:
    workflow = _load_workflow()
    stages = workflow["stage"]
    first = stages[0]
    ctp_args = _checker(first, "act4_ctp_reference_check")["args"]
    manual_args = _checker(first, "act4_manual_reference_check")["args"]
    specification = "{OUT}/{DUT}/references/{DUT}_specification.adoc"
    metadata = "{OUT}/{DUT}/references/{DUT}_normative_rule_defs.yaml"
    assert ctp_args["require_request_regions"] is True
    assert ctp_args["require_full_boundary_review"] is True
    manual_provenance = (
        "{OUT}/{DUT}/reports/{DUT}_manual_reference_provenance.yaml"
    )
    ctp_provenance = "{OUT}/{DUT}/reports/{DUT}_ctp_reference_provenance.yaml"
    normative_table = "{OUT}/{DUT}/{DUT}_normative_rules.csv"
    raw_testplan = "{OUT}/{DUT}/references/{DUT}_ctp_raw.csv"

    native_references = [
        [path for path in stage["reference_files"] if not path.startswith("Guide_Doc/")]
        for stage in stages
    ]
    assert native_references[0] == [
        "riscv-arch-test/docs/DeveloperGuide.md",
        "riscv-arch-test/README.md",
        "riscv-arch-test/coverpoints/priv/ExceptionsSm_coverage.svh",
        "riscv-arch-test/coverpoints/priv/ExceptionsSm_coverage_init.svh",
    ]
    assert ctp_args == {
        "suite": "{DUT}",
        "ctp_snapshot": "{OUT}/{DUT}/references/ctp.html",
        "provenance_file": ctp_provenance,
        "raw_testplan": raw_testplan,
        "optimized_testplan": "{OUT}/{DUT}/{DUT}.csv",
        "human_readable_testplan": "{OUT}/{DUT}/{DUT}_testplan.md",
        "normative_table": normative_table,
        "normative_metadata": metadata,
        "ctp_url": "https://riscv.github.io/riscv-arch-test/ctp.html",
        "require_request_regions": True,
        "require_full_boundary_review": True,
    }
    assert manual_args == {
        "suite": "{DUT}",
        "testplan": raw_testplan,
        "manual_root": "{ACT4_MANUAL_ROOT}",
        "spec_copy": specification,
        "metadata_copy": metadata,
        "provenance_file": manual_provenance,
        "require_git_head": True,
    }
    assert {
        specification,
        metadata,
        manual_provenance,
        ctp_provenance,
        normative_table,
        raw_testplan,
        "{OUT}/{DUT}/{DUT}_testplan.md",
    }.issubset(first["output_files"])
    assert workflow["guide_doc"]["enable"] is True
    assert workflow["guide_doc"]["core_copy_policy"]["default_action"] == "ignore"
    forbidden_tokens = ("http://", "https://", "..", "*", "{OUT}", "{DUT}")
    for stage in stages:
        for reference in stage["reference_files"]:
            assert not any(token in reference for token in forbidden_tokens)

    assert native_references[1] == [
        "riscv-arch-test/docs/DeveloperGuide.md"
    ]
    assert native_references[2] == [
        "riscv-arch-test/tests/env/rvtest_setup.h",
        "riscv-arch-test/tests/env/rvtest_macros.h",
        "riscv-arch-test/tests/env/rvtest_trap_handler.h",
    ]
    assert native_references[3][-1] == (
        "riscv-arch-test/generators/testgen/src/testgen/priv/extensions/ExceptionsSm.py"
    )
    assert native_references[4] == ["riscv-arch-test/README.md"]
    assert native_references[5] == []
    assert native_references[6] == []

    assert all(
        "need_human_check" not in checker["args"]
        for stage in stages
        for checker in stage["checker"]
    )
    assert not any(
        checker["name"] == "act4_final_report_protected_integrity_check"
        for checker in stages[-1]["checker"]
    )

    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    assert "norm-rules.json" not in workflow_text
    assert "Table 246" not in workflow_text
    assert "262865576" not in workflow_text
    assert "1DWBEoprndjQzLTXQTzPI8jW1HydtkYRR3tg58q59fdk" not in workflow_text
    for h_specific in ("TNAME=H", "VGEIN", "vscause", "vsstatus", "HLVX", "HSV"):
        assert h_specific not in workflow_text


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manual_reference_fixture(tmp_path: Path) -> dict:
    testplan = tmp_path / "Guide_Doc/H.csv"
    manual = tmp_path / "manual"
    specification = manual / "src/priv/hypervisor.adoc"
    other_specification = manual / "src/priv/machine.adoc"
    other_specification = manual / "src/priv/machine.adoc"
    metadata = manual / "normative_rule_defs/hypervisor.yaml"
    spec_copy = tmp_path / "out/H/references/H_specification.adoc"
    metadata_copy = tmp_path / "out/H/references/H_normative_rule_defs.yaml"
    provenance = tmp_path / "out/H/reports/H_manual_reference_provenance.yaml"
    for path in (
        testplan,
        specification,
        other_specification,
        metadata,
        spec_copy,
        metadata_copy,
        provenance,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)

    testplan.write_text("feature,csr\nH extension,hstatus\n", encoding="utf-8")
    other_specification.write_text("= Machine\n", encoding="utf-8")
    other_specification.write_text("= Machine\n", encoding="utf-8")
    specification.write_text(
        "= Hypervisor Extension\n[#norm:hstatus_op]#hstatus is accessible.#\n",
        encoding="utf-8",
    )
    metadata.write_text(
        yaml.safe_dump(
            {
                "chapter_name": "H Extension",
                "normative_rule_definitions": [
                    {"name": "hstatus_op", "tags": ["norm:hstatus_op"]}
                ],
            }
        ),
        encoding="utf-8",
    )
    spec_copy.write_bytes(specification.read_bytes())
    metadata_copy.write_bytes(metadata.read_bytes())
    provenance.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "suite": "H",
                "manual_git_head": None,
                "testplan": {
                    "source_path": "Guide_Doc/H.csv",
                    "sha256": _sha256(testplan),
                },
                "discovery": {
                    "csv_terms": ["H extension", "hstatus"],
                    "spec_candidates": [
                        {
                            "path": "src/priv/hypervisor.adoc",
                            "score": 10,
                            "matched_terms": ["H extension", "hstatus"],
                        },
                        {
                            "path": "src/priv/machine.adoc",
                            "score": 1,
                            "matched_terms": [],
                        },
                    ],
                    "metadata_candidates": [
                        {
                            "path": "normative_rule_defs/hypervisor.yaml",
                            "score": 10,
                            "matched_terms": ["H extension", "hstatus"],
                        }
                    ],
                    "selection_reason": "unique best CSV term and tag match",
                    "unmatched_metadata_tags": [],
                    "unmatched_metadata_tag_reason": "none",
                },
                "specification": {
                    "source_path": "src/priv/hypervisor.adoc",
                    "copied_path": "out/H/references/H_specification.adoc",
                    "sha256": _sha256(specification),
                },
                "metadata": {
                    "source_path": "normative_rule_defs/hypervisor.yaml",
                    "copied_path": "out/H/references/H_normative_rule_defs.yaml",
                    "sha256": _sha256(metadata),
                },
            }
        ),
        encoding="utf-8",
    )
    return {
        "testplan": testplan,
        "manual": manual,
        "spec_copy": spec_copy,
        "metadata_copy": metadata_copy,
        "provenance": provenance,
    }


def _manual_checker(tmp_path: Path, fixture: dict) -> ACT4ManualReferenceChecker:
    return ACT4ManualReferenceChecker(
        suite="H",
        testplan=str(fixture["testplan"]),
        manual_root=str(fixture["manual"]),
        spec_copy=str(fixture["spec_copy"]),
        metadata_copy=str(fixture["metadata_copy"]),
        provenance_file=str(fixture["provenance"]),
        require_git_head=False,
    ).set_workspace(str(tmp_path))


def test_manual_reference_checker_accepts_exact_csv_driven_pair(
    tmp_path: Path,
) -> None:
    fixture = _manual_reference_fixture(tmp_path)

    passed, report = _manual_checker(tmp_path, fixture).do_check()

    assert passed
    assert report["summary"] == {"errors": 0, "warnings": 0}
    assert report["checks"]["rules"] == 1


def test_manual_reference_checker_rejects_non_exact_copy(tmp_path: Path) -> None:
    fixture = _manual_reference_fixture(tmp_path)
    fixture["spec_copy"].write_text("changed\n", encoding="utf-8")

    passed, report = _manual_checker(tmp_path, fixture).do_check()

    assert not passed
    assert any(
        finding["check"] == "manual_copy_exact"
        for finding in report["findings"]
    )


def test_manual_reference_checker_requires_selected_candidate_evidence(
    tmp_path: Path,
) -> None:
    fixture = _manual_reference_fixture(tmp_path)
    provenance = yaml.safe_load(fixture["provenance"].read_text(encoding="utf-8"))
    provenance["discovery"]["spec_candidates"][0]["matched_terms"] = []
    fixture["provenance"].write_text(
        yaml.safe_dump(provenance),
        encoding="utf-8",
    )

    passed, report = _manual_checker(tmp_path, fixture).do_check()

    assert not passed
    assert any(
        finding["check"] == "manual_discovery_evidence"
        for finding in report["findings"]
    )
