from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from act4_privileged_suite.checkers.act4_test_asset_checker import ACT4TestAssetChecker


def _write_state(path: Path, **overrides) -> None:
    state = {
        "source_generated": True,
        "supported_xlens": [64],
        "self_checking": {
            "model": "other-reference",
            "passed": True,
            "command": "make self-check",
        },
        "sail_coverage": {
            "passed": False,
            "command": "",
            "blocked_reason": "Sail coverage backend unavailable",
        },
        "generation_scope": {
            "status": "complete",
            "generated_targets": [],
            "partial_targets": [],
            "blocked_targets": [],
        },
        "contribution_ready": True,
    }
    state.update(overrides)
    path.write_text(yaml.safe_dump(state), encoding="utf-8")


def _check(tmp_path: Path, allow_blocked: bool = True):
    checker = ACT4TestAssetChecker(
        validation_state="validation.yaml",
        require_self_checking_status=True,
        require_contribution_ready=True,
        allow_sail_coverage_blocked=allow_blocked,
    ).set_workspace(str(tmp_path))
    findings = []
    state = checker._check_validation_state(tmp_path, findings)
    return state, findings


def test_coverage_model_is_independent_from_signature_model(tmp_path):
    _write_state(
        tmp_path / "validation.yaml",
        self_checking={"model": "spike", "passed": True, "command": "make spike"},
        sail_coverage={"passed": True, "command": "make coverage", "blocked_reason": None},
    )
    _, findings = _check(tmp_path)
    assert findings == []


def _reference_model_evaluation(*, scope_reduction: bool = False) -> dict:
    return {
        "preferred": {
            "model": "sail",
            "executable": "sail_riscv_sim",
            "config_file": "config/sail/test_config.yaml",
            "selection_basis": ["ACT4 config and UDB declare the required extension"],
        },
        "attempts": [
            {
                "model": "sail",
                "executable": "sail_riscv_sim",
                "config_file": "config/sail/test_config.yaml",
                "command": "make CONFIG_FILES=config/sail/test_config.yaml",
                "status": "failed",
                "tested_targets": ["cp_host", "cp_guest"],
                "passed_targets": ["cp_host"],
                "failed_targets": ["cp_guest"],
                "failure_class": "model_capability_gap",
                "evidence": ["guest run failed after host run passed"],
                "diagnoses": [
                    {
                        "target": "cp_guest",
                        "first_failure": "guest entry trapped",
                        "alternatives_evaluated": [
                            "suite_local_resources",
                            "positive_subset",
                            "native_entrypoint",
                            "generation_vs_validation_scope",
                        ],
                        "outcome": "retained",
                        "evidence": ["bounded guest-only reproducer"],
                    }
                ],
            },
            {
                "model": "spike",
                "executable": "spike",
                "config_file": "config/spike/test_config.yaml",
                "command": "make CONFIG_FILES=config/spike/test_config.yaml",
                "status": "passed",
                "tested_targets": ["cp_host", "cp_guest"],
                "passed_targets": ["cp_host", "cp_guest"],
                "failed_targets": [],
                "failure_class": "none",
                "evidence": ["complete Spike reference run logs"],
                "diagnoses": [],
            },
        ],
        "fallback": {
            "used": True,
            "model": "spike",
            "reason": "cross-model diagnosis for the failing guest target",
            "scope_reduction": scope_reduction,
            "affected_targets": ["cp_guest"],
            "evidence": ["Spike reference run log"],
        },
    }


def test_other_passing_reference_model_can_be_contribution_ready(
    tmp_path: Path,
) -> None:
    _write_state(tmp_path / "validation.yaml")

    state, findings = _check(tmp_path)

    assert state is not None
    assert not [item for item in findings if item["severity"] == "error"]


def test_reference_model_evaluation_is_required_when_enabled(
    tmp_path: Path,
) -> None:
    _write_state(tmp_path / "validation.yaml")
    checker = ACT4TestAssetChecker(
        validation_state="validation.yaml",
        require_reference_model_evaluation=True,
    ).set_workspace(str(tmp_path))
    findings: list[dict] = []

    checker._check_validation_state(tmp_path, findings)

    assert any(
        item["check"] == "validation_state_schema"
        and "reference_model_evaluation" in item["message"]
        for item in findings
    )


def test_reference_model_fallback_cannot_reduce_generation_scope(
    tmp_path: Path,
) -> None:
    _write_state(
        tmp_path / "validation.yaml",
        self_checking={
            "model": "spike",
            "passed": True,
            "command": "make self-check",
        },
        generation_scope={
            "status": "complete",
            "generated_targets": ["cp_host", "cp_guest"],
            "partial_targets": [],
            "blocked_targets": [],
        },
        reference_model_evaluation=_reference_model_evaluation(
            scope_reduction=True
        ),
    )
    checker = ACT4TestAssetChecker(
        validation_state="validation.yaml",
        require_reference_model_evaluation=True,
    ).set_workspace(str(tmp_path))
    findings: list[dict] = []

    checker._check_validation_state(tmp_path, findings)

    assert any(
        item["check"] == "reference_model_fallback_scope_reduction"
        for item in findings
    )


def test_reference_model_fallback_preserves_preferred_passing_targets(
    tmp_path: Path,
) -> None:
    _write_state(
        tmp_path / "validation.yaml",
        self_checking={
            "model": "spike",
            "passed": True,
            "command": "make CONFIG_FILES=config/spike/test_config.yaml",
        },
        generation_scope={
            "status": "partial",
            "generated_targets": ["cp_guest"],
            "partial_targets": [],
            "blocked_targets": ["cp_host"],
        },
        reference_model_evaluation=_reference_model_evaluation(),
        contribution_ready=False,
    )
    checker = ACT4TestAssetChecker(
        validation_state="validation.yaml",
        require_reference_model_evaluation=True,
    ).set_workspace(str(tmp_path))
    findings: list[dict] = []

    checker._check_validation_state(tmp_path, findings)

    assert any(
        item["check"] == "reference_model_passing_scope_preserved"
        for item in findings
    )


def test_reference_model_fallback_requires_per_target_diagnosis(
    tmp_path: Path,
) -> None:
    evaluation = _reference_model_evaluation()
    evaluation["attempts"][0]["diagnoses"] = []
    _write_state(
        tmp_path / "validation.yaml",
        self_checking={
            "model": "spike",
            "passed": True,
            "command": "make CONFIG_FILES=config/spike/test_config.yaml",
        },
        generation_scope={
            "status": "complete",
            "generated_targets": ["cp_host", "cp_guest"],
            "partial_targets": [],
            "blocked_targets": [],
        },
        reference_model_evaluation=evaluation,
    )
    checker = ACT4TestAssetChecker(
        validation_state="validation.yaml",
        require_reference_model_evaluation=True,
    ).set_workspace(str(tmp_path))
    findings: list[dict] = []

    checker._check_validation_state(tmp_path, findings)

    assert any(
        item["check"] == "reference_model_failure_diagnosis"
        for item in findings
    )


def test_reference_model_fallback_requires_a_passing_fallback_attempt(
    tmp_path: Path,
) -> None:
    evaluation = _reference_model_evaluation()
    evaluation["attempts"] = evaluation["attempts"][:1]
    _write_state(
        tmp_path / "validation.yaml",
        self_checking={
            "model": "spike",
            "passed": True,
            "command": "make self-check",
        },
        generation_scope={
            "status": "complete",
            "generated_targets": ["cp_host", "cp_guest"],
            "partial_targets": [],
            "blocked_targets": [],
        },
        reference_model_evaluation=evaluation,
        contribution_ready=False,
    )
    checker = ACT4TestAssetChecker(
        validation_state="validation.yaml",
        require_reference_model_evaluation=True,
    ).set_workspace(str(tmp_path))
    findings: list[dict] = []

    checker._check_validation_state(tmp_path, findings)

    assert any(
        item["check"] == "reference_model_fallback_attempt"
        for item in findings
    )


def _grouped_model_capability_evaluation() -> dict:
    evaluation = _reference_model_evaluation()
    sail_attempt = evaluation["attempts"][0]
    spike_attempt = evaluation["attempts"][1]
    sail_attempt.update(
        {
            "tested_targets": ["cp_host", "cp_guest", "cp_vm"],
            "passed_targets": ["cp_host"],
            "failed_targets": ["cp_guest", "cp_vm"],
            "diagnoses": [
                {
                    "capability": "Sail guest address-translation support",
                    "affected_targets": ["cp_guest", "cp_vm"],
                    "common_cause_evidence": [
                        "same Sail configuration and identical guest translation failure"
                    ],
                    "first_failure": "guest translation entry trapped",
                    "alternatives_evaluated": [
                        "suite_local_resources",
                        "positive_subset",
                        "native_entrypoint",
                        "generation_vs_validation_scope",
                    ],
                    "outcome": "retained",
                    "evidence": ["bounded guest profile reproducer"],
                }
            ],
        }
    )
    spike_attempt.update(
        {
            "tested_targets": ["cp_host", "cp_guest", "cp_vm"],
            "passed_targets": ["cp_host", "cp_guest", "cp_vm"],
        }
    )
    evaluation["fallback"]["affected_targets"] = ["cp_guest", "cp_vm"]
    return evaluation


def test_model_capability_gap_allows_evidence_backed_grouped_diagnosis(
    tmp_path: Path,
) -> None:
    _write_state(
        tmp_path / "validation.yaml",
        self_checking={"model": "spike", "passed": True, "command": "make self-check"},
        generation_scope={
            "status": "complete",
            "generated_targets": ["cp_host", "cp_guest", "cp_vm"],
            "partial_targets": [],
            "blocked_targets": [],
        },
        reference_model_evaluation=_grouped_model_capability_evaluation(),
        contribution_ready=False,
    )
    checker = ACT4TestAssetChecker(
        validation_state="validation.yaml",
        require_reference_model_evaluation=True,
    ).set_workspace(str(tmp_path))
    findings: list[dict] = []

    checker._check_validation_state(tmp_path, findings)

    assert not [item for item in findings if item["severity"] == "error"]


def test_grouped_diagnosis_requires_common_capability_evidence(
    tmp_path: Path,
) -> None:
    evaluation = _grouped_model_capability_evaluation()
    evaluation["attempts"][0]["diagnoses"][0].pop("common_cause_evidence")
    _write_state(
        tmp_path / "validation.yaml",
        self_checking={"model": "spike", "passed": True, "command": "make self-check"},
        generation_scope={
            "status": "complete",
            "generated_targets": ["cp_host", "cp_guest", "cp_vm"],
            "partial_targets": [],
            "blocked_targets": [],
        },
        reference_model_evaluation=evaluation,
        contribution_ready=False,
    )
    checker = ACT4TestAssetChecker(
        validation_state="validation.yaml",
        require_reference_model_evaluation=True,
    ).set_workspace(str(tmp_path))
    findings: list[dict] = []

    checker._check_validation_state(tmp_path, findings)

    assert any(
        item["check"] == "reference_model_capability_group"
        for item in findings
    )


def test_grouped_diagnosis_is_only_valid_for_model_capability_gap(
    tmp_path: Path,
) -> None:
    evaluation = _grouped_model_capability_evaluation()
    evaluation["attempts"][0]["failure_class"] = "framework_gap"
    _write_state(
        tmp_path / "validation.yaml",
        self_checking={"model": "spike", "passed": True, "command": "make self-check"},
        generation_scope={
            "status": "complete",
            "generated_targets": ["cp_host", "cp_guest", "cp_vm"],
            "partial_targets": [],
            "blocked_targets": [],
        },
        reference_model_evaluation=evaluation,
        contribution_ready=False,
    )
    checker = ACT4TestAssetChecker(
        validation_state="validation.yaml",
        require_reference_model_evaluation=True,
    ).set_workspace(str(tmp_path))
    findings: list[dict] = []

    checker._check_validation_state(tmp_path, findings)

    assert any(
        item["check"] == "reference_model_capability_group"
        for item in findings
    )


def test_single_target_must_not_use_grouped_capability_diagnosis(
    tmp_path: Path,
) -> None:
    evaluation = _grouped_model_capability_evaluation()
    sail_attempt = evaluation["attempts"][0]
    diagnosis = sail_attempt["diagnoses"][0]
    sail_attempt["failed_targets"] = ["cp_guest"]
    diagnosis["affected_targets"] = ["cp_guest"]
    evaluation["fallback"]["affected_targets"] = ["cp_guest"]
    _write_state(
        tmp_path / "validation.yaml",
        self_checking={"model": "spike", "passed": True, "command": "make self-check"},
        generation_scope={
            "status": "complete",
            "generated_targets": ["cp_host", "cp_guest", "cp_vm"],
            "partial_targets": [],
            "blocked_targets": [],
        },
        reference_model_evaluation=evaluation,
        contribution_ready=False,
    )
    checker = ACT4TestAssetChecker(
        validation_state="validation.yaml",
        require_reference_model_evaluation=True,
    ).set_workspace(str(tmp_path))
    findings: list[dict] = []

    checker._check_validation_state(tmp_path, findings)

    assert any(
        item["check"] == "reference_model_capability_group"
        for item in findings
    )


@pytest.mark.parametrize("initial_model", ["sail", "spike"])
@pytest.mark.parametrize("initial_outcome", ["fixed", "blocked"])
def test_diagnosis_outcomes_can_change_between_attempts(
    tmp_path: Path, initial_model: str, initial_outcome: str,
) -> None:
    evaluation = _reference_model_evaluation()
    initial = deepcopy(evaluation["attempts"][0])
    initial.update(model=initial_model, failure_class="test_asset_defect")
    initial["diagnoses"][0].update(
        first_failure="suite setup failed before testing model capability",
        outcome=initial_outcome,
    )
    evaluation["attempts"].insert(0, initial)
    findings: list[dict] = []

    ACT4TestAssetChecker()._check_reference_model_evaluation(
        evaluation, "spike",
        {"generated_targets": ["cp_host", "cp_guest"], "blocked_targets": []},
        findings, tmp_path / "validation.yaml",
    )

    assert not [item for item in findings if item["severity"] == "error"]


def test_conflicting_diagnoses_within_one_attempt_are_rejected(
    tmp_path: Path,
) -> None:
    evaluation = _reference_model_evaluation()
    conflict = deepcopy(evaluation["attempts"][0]["diagnoses"][0])
    conflict["outcome"] = "fixed"
    evaluation["attempts"][0]["diagnoses"].append(conflict)
    findings: list[dict] = []

    ACT4TestAssetChecker()._check_reference_model_evaluation(
        evaluation, "spike",
        {"generated_targets": ["cp_host", "cp_guest"], "blocked_targets": []},
        findings, tmp_path / "validation.yaml",
    )

    assert any(item["check"] == "reference_model_diagnosis_conflict" for item in findings)


def test_narrow_reference_model_fallback_is_accepted(tmp_path: Path) -> None:
    _write_state(
        tmp_path / "validation.yaml",
        self_checking={
            "model": "spike",
            "passed": True,
            "command": "make self-check",
        },
        generation_scope={
            "status": "complete",
            "generated_targets": ["cp_host", "cp_guest"],
            "partial_targets": [],
            "blocked_targets": [],
        },
        reference_model_evaluation=_reference_model_evaluation(),
        contribution_ready=False,
    )
    checker = ACT4TestAssetChecker(
        validation_state="validation.yaml",
        require_reference_model_evaluation=True,
    ).set_workspace(str(tmp_path))
    findings: list[dict] = []

    checker._check_validation_state(tmp_path, findings)

    assert not [item for item in findings if item["severity"] == "error"]


def test_blocked_sail_coverage_requires_explicit_policy(tmp_path: Path) -> None:
    _write_state(tmp_path / "validation.yaml")

    _, findings = _check(tmp_path, allow_blocked=False)

    assert any(
        item["check"] == "validation_contribution_sail"
        for item in findings
    )


def test_validation_booleans_reject_strings(tmp_path: Path) -> None:
    _write_state(
        tmp_path / "validation.yaml",
        source_generated="true",
        contribution_ready="false",
        self_checking={
            "model": "spike",
            "passed": "true",
            "command": "make self-check",
        },
        sail_coverage={
            "passed": "false",
            "command": "",
            "blocked_reason": "Sail unavailable",
        },
    )

    _, findings = _check(tmp_path)

    schema_errors = [
        item
        for item in findings
        if item["check"]
        in {
            "validation_state_schema",
            "validation_self_check_schema",
            "validation_sail_coverage_schema",
        }
    ]
    assert len(schema_errors) == 4


def test_partial_generation_scope_is_valid_for_contribution(tmp_path: Path) -> None:
    _write_state(
        tmp_path / "validation.yaml",
        generation_scope={
            "status": "partial",
            "generated_targets": ["cp_access", "cp_mixed"],
            "partial_targets": ["cp_mixed"],
            "blocked_targets": ["cp_guest"],
        },
    )
    checker = ACT4TestAssetChecker(
        validation_state="validation.yaml",
        require_generation_scope=True,
        allow_sail_coverage_blocked=True,
    ).set_workspace(str(tmp_path))
    findings = []

    checker._check_validation_state(tmp_path, findings)

    assert not [item for item in findings if item["severity"] == "error"]


def test_generation_scope_is_canonical_for_new_runs(tmp_path: Path) -> None:
    _write_state(
        tmp_path / "validation.yaml",
        supported_xlens=[64],
        generation_scope={
            "status": "complete",
            "generated_targets": ["cp_access"],
            "partial_targets": [],
            "blocked_targets": [],
        },
    )
    checker = ACT4TestAssetChecker(
        validation_state="validation.yaml",
        require_generation_scope=True,
        require_matching_xlen=True,
        allow_sail_coverage_blocked=True,
    ).set_workspace(str(tmp_path))
    findings: list[dict] = []

    checker._check_validation_state(tmp_path, findings)

    assert not [item for item in findings if item["severity"] == "error"]


def test_vm_contract_reads_selected_target_xlen(tmp_path: Path) -> None:
    contract = tmp_path / "contract.yaml"
    contract.write_text(
        """schema_version: 1
suite: H
supported_xlens: [64]
selected_target:
  name: sail-rv64
  test_config: config/test.yaml
  XLEN: 64
decision: no_vm
""",
        encoding="utf-8",
    )
    checker = ACT4TestAssetChecker(
        vm_resource_contract="contract.yaml",
        validate_vm_contract=True,
    ).set_workspace(str(tmp_path))
    findings: list[dict] = []

    summary = checker._check_vm_contract(tmp_path, findings)

    assert summary["target_xlen"] == {64}
    assert summary["supported_xlens"] == {64}
    assert findings == []


def test_required_scoped_vm_contract_must_exist(tmp_path: Path) -> None:
    checker = ACT4TestAssetChecker(
        vm_resource_contract="missing.yaml",
        validate_vm_contract=True,
        require_scoped_vm_contract=True,
    ).set_workspace(str(tmp_path))
    findings: list[dict] = []

    checker._check_vm_contract(tmp_path, findings)

    assert findings[0]["check"] == "vm_contract_absent"
    assert findings[0]["severity"] == "error"


def test_complete_scope_rejects_blocked_targets(tmp_path: Path) -> None:
    _write_state(
        tmp_path / "validation.yaml",
        generation_scope={
            "status": "complete",
            "generated_targets": ["cp_access"],
            "partial_targets": [],
            "blocked_targets": ["cp_guest"],
        },
    )
    checker = ACT4TestAssetChecker(
        validation_state="validation.yaml",
        require_generation_scope=True,
    ).set_workspace(str(tmp_path))
    findings = []

    checker._check_validation_state(tmp_path, findings)

    assert any(item["check"] == "validation_generation_scope" for item in findings)


def test_single_stage_vm_contract_does_not_require_hypervisor_stages(
    tmp_path: Path,
) -> None:
    contract = {
        "schema_version": 1,
        "suite": "H",
        "supported_xlens": [64],
        "selected_target": {
            "name": "test-target",
            "test_config": "config/test.yaml",
            "XLEN": 64,
        },
        "profiles": [
            {
                "profile_id": "supervisor_translation",
                "coverage_targets": ["cp_satp"],
                "decision": "allowed",
                "resource_mode": "single_stage",
                "execution_context": "host_execution",
                "requires_page_tables": True,
                "capability_dependencies": [],
                "translation": {
                    "s_stage": {},
                    "activation_order": ["build tables", "write satp"],
                    "bare_restore_order": ["clear satp"],
                },
                "fences": ["sfence.vma"],
            }
        ]
    }
    (tmp_path / "contract.yaml").write_text(
        yaml.safe_dump(contract), encoding="utf-8"
    )
    checker = ACT4TestAssetChecker(
        vm_resource_contract="contract.yaml",
        validate_vm_contract=True,
        require_scoped_vm_contract=True,
    ).set_workspace(str(tmp_path))
    findings = []

    checker._check_vm_contract(tmp_path, findings)

    assert findings == []


def test_vm_contract_requires_translation_stage_matching_resource_mode(
    tmp_path: Path,
) -> None:
    contract = {
        "profiles": [
            {
                "profile_id": "g_stage_access",
                "coverage_targets": ["cp_g_stage"],
                "decision": "allowed",
                "resource_mode": "g_stage_only",
                "execution_context": "host_execution",
                "requires_page_tables": True,
                "capability_dependencies": [],
                "translation": {
                    "s_stage": {},
                    "activation_order": ["write translation control"],
                    "bare_restore_order": ["restore translation control"],
                },
                "fences": ["required fence"],
            }
        ]
    }
    (tmp_path / "contract.yaml").write_text(
        yaml.safe_dump(contract), encoding="utf-8"
    )
    checker = ACT4TestAssetChecker(
        vm_resource_contract="contract.yaml",
        validate_vm_contract=True,
        require_scoped_vm_contract=True,
    ).set_workspace(str(tmp_path))
    findings = []

    checker._check_vm_contract(tmp_path, findings)

    assert any(item["check"] == "vm_profile_translation" for item in findings)


def test_experimental_vm_profile_requires_bounded_alternative_analysis(
    tmp_path: Path,
) -> None:
    contract = {
        "schema_version": 1,
        "suite": "H",
        "supported_xlens": [64],
        "selected_target": {
            "name": "sail-rv64",
            "test_config": "config/sail/test_config.yaml",
            "XLEN": 64,
        },
        "profiles": [
            {
                "profile_id": "guest_candidate",
                "coverage_targets": ["cp_guest"],
                "decision": "experimental",
                "resource_mode": "bare_or_csr_only",
                "execution_context": "guest_execution",
                "requires_page_tables": False,
                "capability_dependencies": ["reference_model_executable"],
                "validation_status": "runtime_blocked",
                "limitations": ["guest run failed on the selected model"],
                "promotion_requirements": ["complete bounded diagnosis"],
            }
        ],
    }
    (tmp_path / "contract.yaml").write_text(
        yaml.safe_dump(contract), encoding="utf-8"
    )
    checker = ACT4TestAssetChecker(
        vm_resource_contract="contract.yaml",
        validate_vm_contract=True,
        require_scoped_vm_contract=True,
    ).set_workspace(str(tmp_path))
    findings: list[dict] = []

    checker._check_vm_contract(tmp_path, findings)

    assert any(
        item["check"] == "vm_profile_experimental_alternative_analysis"
        for item in findings
    )


def test_generation_scope_matches_allowed_and_blocked_profiles(tmp_path: Path) -> None:
    checker = ACT4TestAssetChecker(require_generation_scope=True)
    state = {
        "generation_scope": {
            "status": "partial",
            "generated_targets": ["cp_allowed", "cp_partial"],
            "partial_targets": ["cp_partial"],
            "blocked_targets": ["cp_blocked"],
        }
    }
    contract = {
        "no_vm": False,
        "allowed_targets": {"cp_allowed", "cp_partial"},
        "blocked_targets": {"cp_partial", "cp_blocked"},
    }
    findings = []

    checker._check_generation_scope_consistency(state, contract, findings)

    assert findings == []


def test_xlen_template_uses_contract_and_elf_evidence(tmp_path: Path) -> None:
    source = tmp_path / "test_H.S"
    checker = ACT4TestAssetChecker(require_matching_xlen=True)
    findings = []

    resolved, evidence = checker._resolve_source_xlen(
        source,
        "# MARCH: rv${XLEN}imafdh\n",
        {64},
        {64},
        findings,
    )

    assert resolved == {64}
    assert evidence["source_uses_xlen_template"] is True
    assert findings == []


def test_xlen_conflict_is_blocking(tmp_path: Path) -> None:
    checker = ACT4TestAssetChecker(require_matching_xlen=True)
    findings = []

    checker._resolve_source_xlen(
        tmp_path / "test_H.S",
        "# MARCH: rv32imafd\n",
        {64},
        {64},
        findings,
    )

    assert any(item["check"] == "source_xlen_conflict" for item in findings)


def test_experimental_manifest_is_isolated_and_non_gating(tmp_path: Path) -> None:
    experimental = tmp_path / "unity_test" / "H" / "experimental"
    experimental.mkdir(parents=True)
    (experimental / "candidate.S").write_text("candidate\n", encoding="utf-8")
    manifest = experimental / "H_experimental_assets.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "suite": "H",
                "assets": [
                    {
                        "id": "candidate",
                        "path": "unity_test/H/experimental/candidate.S",
                        "kind": "assembly_candidate",
                        "validation_status": "runtime_blocked",
                        "limitations": ["reference model unavailable"],
                        "promotion_requirements": ["pass self-checking run"],
                        "affected_targets": ["cp_candidate"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    checker = ACT4TestAssetChecker(
        experimental_manifest=str(manifest),
        validate_experimental_assets=True,
    )
    findings = []

    summary = checker._check_experimental_manifest(tmp_path, findings)

    assert summary == {"assets": 1, "unverified": 1, "missing_files": 0}
    assert not [item for item in findings if item["severity"] == "error"]
    assert [item for item in findings if item["check"] == "experimental_assets_limited"]


def test_explicit_elf_scope_does_not_include_stale_work_tree(tmp_path: Path) -> None:
    source = tmp_path / "tests" / "priv" / "H" / "H-00.S"
    selected = tmp_path / "work_itgen_H" / "config" / "elfs" / "H-00.elf"
    stale = tmp_path / "riscv-arch-test" / "work_old" / "config" / "elfs" / "old.elf"
    source.parent.mkdir(parents=True)
    selected.parent.mkdir(parents=True)
    stale.parent.mkdir(parents=True)
    source.write_text("generated source\n", encoding="utf-8")
    elf_header = b"\x7fELF\x02" + b"\x00" * 59
    selected.write_bytes(elf_header)
    stale.write_bytes(elf_header)
    checker = ACT4TestAssetChecker(
        source_files=[str(source.relative_to(tmp_path))],
        elf_files=[str(selected.relative_to(tmp_path))],
        act4_root="riscv-arch-test",
        validate_test_config=False,
        require_matching_stems=True,
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is True
    report = result["report"]
    assert report["checks"]["elf_files"] == 1
    assert report["checks"]["elf_stems"] == ["H-00"]


@pytest.mark.parametrize(
    ("selected_present", "command", "config_name", "selection_valid"),
    [
        (True, "make CONFIG_FILES=selected.yaml WORKDIR=work_itgen_H", "a-selected", True),
        (False, "make CONFIG_FILES=selected.yaml WORKDIR=work_itgen_H", "a-selected", True),
        (True, "make CONFIG_FILES=selected.yaml", "a-selected", False),
        (True, "make WORKDIR=work_itgen_H", "a-selected", False),
        (True, "make CONFIG_FILES=selected.yaml WORKDIR=work_itgen_H", "../a-selected", False),
    ],
)
def test_selected_config_keeps_reference_chains_separate(
    tmp_path: Path, selected_present: bool, command: str,
    config_name: str, selection_valid: bool,
) -> None:
    source = tmp_path / "H-00.S"
    source.write_text("generated\n")
    (tmp_path / "selected.yaml").write_text(f"name: {config_name}\nref_model_exe: spike\n")
    _write_state(tmp_path / "validation.yaml", self_checking={
        "model": "spike", "passed": True,
        "executable": "spike", "config_file": "selected.yaml",
        "command": command,
    })
    for name in ["z-primary", *(["a-selected"] if selected_present else [])]:
        folder = tmp_path / "work_itgen_H" / name
        folder.mkdir(parents=True)
        (folder / "H-00.elf").write_bytes(b"\x7fELF\x02" + b"\x00" * 59)
        (folder / "H-00.sig").write_text("0000000000000000\n")
        (folder / "H-00.results").write_text(".quad 0x0\n")
        (folder / "H-00.sig.log").write_text(
            'RVCP-SUMMARY: TEST SIGRUN - Test File "H-00.S"\n'
            "setting signature-granularity to 8 bytes\n"
            "begin_signature: 0x1000\nend_signature: 0x1008\nSUCCESS\n"
            if name == "a-selected" else "FAILURE\n"
        )
    checker = ACT4TestAssetChecker(
        source_files=[str(source)], elf_patterns=["work_itgen_H/**/*.elf"],
        signature_patterns=["work_itgen_H/**/*.sig"],
        result_patterns=["work_itgen_H/**/*.results"],
        reference_model_log_patterns=["work_itgen_H/**/*.sig.log"],
        validation_state="validation.yaml", validate_test_config=False,
        act4_root=str(tmp_path), allow_sail_coverage_blocked=True,
        require_signature=True, require_results=True,
        require_reference_model_logs=True, require_signature_completeness=True,
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    expected_pass = selected_present and selection_valid
    assert passed is expected_pass
    assert result["report"]["checks"]["reference_model_logs"] == int(expected_pass)
    assert result["report"]["checks"]["complete_reference_runs"] == int(expected_pass)
    if not selection_valid:
        checks = {item["check"] for item in result["error"]}
        assert "validation_self_check_build_root" in checks
        assert "reference_model_log_match" not in checks
    elif not selected_present:
        assert any(item["check"] == "reference_model_log_match" for item in result["error"])


def test_reference_model_signature_region_must_be_complete(
    tmp_path: Path,
) -> None:
    source = tmp_path / "H-00.S"
    signature = tmp_path / "H-00.sig"
    results = tmp_path / "H-00.results"
    log = tmp_path / "H-00.sig.log"
    source.write_text("generated\n", encoding="utf-8")
    signature.write_text("0001\n0002\n", encoding="utf-8")
    results.write_text(".quad 0x1\n.quad 0x2\n", encoding="utf-8")
    log.write_text(
        """setting signature-granularity to 8 bytes
RVCP-SUMMARY: TEST SIGRUN - Test File "H-00.S"
begin_signature: 0x1000
end_signature: 0x1020
SUCCESS
""",
        encoding="utf-8",
    )
    checker = ACT4TestAssetChecker(
        require_reference_model_logs=True,
        require_signature_completeness=True,
    )
    findings = []

    summary = checker._check_reference_model_outputs(
        [source], [signature], [results], [log], findings
    )

    checks = {item["check"] for item in findings}
    assert "signature_record_count" in checks
    assert "signature_results_record_count" in checks
    assert summary["runs_checked"] == 1
    assert summary["complete_runs_checked"] == 0


def test_reference_model_complete_signature_region_passes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "H-00.S"
    signature = tmp_path / "H-00.sig"
    results = tmp_path / "H-00.results"
    log = tmp_path / "H-00.sig.log"
    source.write_text("generated\n", encoding="utf-8")
    signature.write_text("0001\n0002\n0003\n0004\n", encoding="utf-8")
    results.write_text(
        ".quad 0x1\n.quad 0x2\n.quad 0x3\n.quad 0x4\n",
        encoding="utf-8",
    )
    log.write_text(
        """setting signature-granularity to 8 bytes
RVCP-SUMMARY: TEST SIGRUN - Test File "H-00.S"
begin_signature: 0x1000
end_signature: 0x1020
SUCCESS
""",
        encoding="utf-8",
    )
    checker = ACT4TestAssetChecker(
        require_reference_model_logs=True,
        require_signature_completeness=True,
    )
    findings = []

    summary = checker._check_reference_model_outputs(
        [source], [signature], [results], [log], findings
    )

    assert findings == []
    assert summary["runs_checked"] == 1
    assert summary["complete_runs_checked"] == 1


@pytest.mark.parametrize("xlen,logged_width,records,error", [
    (32, None, 2, None), (64, None, 2, None), (64, 8, 2, None),
    (None, None, 2, "signature_region_evidence"),
    (64, None, 1, "signature_record_count"),
    (32, 8, 2, "signature_granularity_conflict"),
])
def test_native_elf_supplies_missing_log_granularity(tmp_path, xlen, logged_width, records, error):
    source, sig, results, log, elf = [tmp_path / ("H-00" + suffix) for suffix in (
        ".S", ".sig", ".results", ".sig.log", ".elf",
    )]
    source.write_text("generated\n")
    sig.write_text("1\n" * records)
    results.write_text(".quad 0x1\n" * records)
    if xlen:
        elf.write_bytes(b"\x7fELF" + bytes([1 if xlen == 32 else 2]) + b"\0" * 59)
    region_bytes = 2 * (xlen or 64) // 8
    log.write_text(
        'RVCP-SUMMARY: TEST SIGRUN - Test File "H-00.S"\n'
        + (f"setting signature-granularity to {logged_width} bytes\n" if logged_width else "")
        + f"begin_signature: 0x1000\nend_signature: {0x1000 + region_bytes:#x}\nSUCCESS\n"
    )
    checker = ACT4TestAssetChecker(require_reference_model_logs=True, require_signature_completeness=True)
    findings = []
    summary = checker._check_reference_model_outputs(
        [source], [sig], [results], [log], findings, native_elfs=[elf] if xlen else [],
    )
    assert summary["complete_runs_checked"] == int(error is None)
    if error:
        assert error in {f["check"] for f in findings}
    else:
        assert findings == []
        evidence = summary["signature_granularity"]["H-00"]
        assert evidence["bytes"] == xlen // 8
        assert evidence["source"] == ("log" if logged_width else "native_elf_xlen")


@pytest.mark.parametrize(
    ("signature_text", "result_text", "ending", "expected_check"),
    [
        (" A\n\n02 \n", ".quad 0xA\n.quad 0x2\n", "SUCCESS\n", None),
        ("1\n2\n", ".word 0x3, 0x4\n", "SUCCESS\n", None),
        (
            "1\n2\n",
            "# header\n label: .quad 0x1 /* first */\n\t.word 0X2 // second\nend:\n",
            "  SUCCESS \ncycles: 42\n",
            None,
        ),
        ("1\n2\n", ".quad -1, 0b10\n", "SUCCESS\n", None),
        ("1\ngarbage\n", ".quad 0x1, 0x2\n", "SUCCESS\n", "signature_record_format"),
        ("1\n10000000000000000\n", ".quad 0x1, 0x2\n", "SUCCESS\n", "signature_record_format"),
        ("1\n2\n", ".quad 0x1\n.quad 0xZZ\n", "SUCCESS\n", "signature_results_record_format"),
        ("1\n2\n", ".quad 0x1\n.quad\n", "SUCCESS\n", "signature_results_record_format"),
        ("1\n2\n", ".quad 0x1, 0x2\n", "", "reference_model_log_success"),
        ("1\n2\n", ".quad 0x1, 0x2\n", "SUCCESS\nSUCCESS\n", "reference_model_log_success"),
        ("1\n2\n", ".quad 0x1, 0x2\n", "SUCCESS\nFAILURE\n", "reference_model_log_failure"),
    ],
)
def test_reference_evidence_format_and_pass_count(
    tmp_path: Path, signature_text: str, result_text: str,
    ending: str, expected_check: str | None,
) -> None:
    source = tmp_path / "H-00.S"
    signature = tmp_path / "H-00.sig"
    results = tmp_path / "H-00.results"
    log = tmp_path / "H-00.sig.log"
    source.write_text("generated\n", encoding="utf-8")
    signature.write_text(signature_text, encoding="utf-8")
    results.write_text(result_text, encoding="utf-8")
    log.write_text(
        'RVCP-SUMMARY: TEST SIGRUN - Test File "H-00.S"\n'
        "setting signature-granularity to 8 bytes\n"
        "begin_signature: 0x1000\nend_signature: 0x1010\n" + ending,
        encoding="utf-8",
    )
    checker = ACT4TestAssetChecker(
        require_reference_model_logs=True,
        require_signature_completeness=True,
    )
    findings = []

    summary = checker._check_reference_model_outputs(
        [source], [signature], [results], [log], findings
    )

    assert {item["check"] for item in findings} == ({expected_check} if expected_check else set())
    assert summary["runs_checked"] == 1
    assert summary["complete_runs_checked"] == int(expected_check is None)


def test_signature_progress_rejects_early_success(tmp_path: Path) -> None:
    source = tmp_path / "H-00.S"
    results = tmp_path / "H-00.results"
    source.write_text(
        """H_cg_cp_one_a_str: .string \"test: 1; cg: H_cg; cp: cp_one; bin: a\"
H_cg_cp_one_b_str: .string \"test: 2; cg: H_cg; cp: cp_one; bin: b\"
""",
        encoding="utf-8",
    )
    results.write_text(
        ".quad 0x1\n.quad 0xdeadbeefdeadbeef\nfinal_trap_sig_offset:\n.quad 0x0\n",
        encoding="utf-8",
    )
    checker = ACT4TestAssetChecker(signature_progress_mode="error")
    findings: list[dict] = []

    summary = checker._check_signature_progress(source, results, findings)

    assert summary == {
        "testcases": 2,
        "completed_prefix": 1,
        "main_region_records": 2,
    }
    assert [item["check"] for item in findings] == ["signature_progress"]


def test_signature_progress_accepts_testcase_lower_bound(tmp_path: Path) -> None:
    source = tmp_path / "H-00.S"
    results = tmp_path / "H-00.results"
    source.write_text(
        "H_cg_cp_one_a_str: .string \"test: 1; cg: H_cg; cp: cp_one; bin: a\"\n",
        encoding="utf-8",
    )
    results.write_text(
        ".quad 0x1\n.quad 0x2\n.quad 0xdeadbeefdeadbeef\nfinal_trap_sig_offset:\n.quad 0x0\n",
        encoding="utf-8",
    )
    checker = ACT4TestAssetChecker(signature_progress_mode="error")
    findings: list[dict] = []

    summary = checker._check_signature_progress(source, results, findings)

    assert summary["testcases"] == 1
    assert summary["completed_prefix"] == 2
    assert findings == []


def test_signature_progress_warning_does_not_claim_slot_proof(
    tmp_path: Path,
) -> None:
    source = tmp_path / "H-00.S"
    results = tmp_path / "H-00.results"
    source.write_text(
        'H_cg_cp_a_str: .string "test: 1; cg: H_cg; cp: cp; bin: a"\n',
        encoding="utf-8",
    )
    results.write_text(
        ".quad 0xdeadbeefdeadbeef\nfinal_trap_sig_offset:\n.quad 0x0\n",
        encoding="utf-8",
    )
    checker = ACT4TestAssetChecker(signature_progress_mode="warning")
    findings: list[dict] = []

    checker._check_signature_progress(
        source,
        results,
        findings,
        severity=checker.signature_progress_mode,
    )

    assert findings[0]["check"] == "signature_progress"
    assert findings[0]["severity"] == "warning"


def test_reference_model_identity_comes_from_selected_config(
    tmp_path: Path,
) -> None:
    config = tmp_path / "riscv-arch-test" / "config" / "test" / "test_config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("ref_model_exe: sail_riscv_sim\n", encoding="utf-8")
    _write_state(
        tmp_path / "validation.yaml",
        self_checking={
            "model": "spike",
            "passed": True,
            "command": "make CONFIG_FILES=config/test/test_config.yaml",
        },
    )
    checker = ACT4TestAssetChecker(
        validation_state="validation.yaml",
    ).set_workspace(str(tmp_path))
    findings = []

    checker._check_validation_state(tmp_path, findings)

    assert any(
        item["check"] == "validation_self_check_model_mismatch"
        for item in findings
    )


def test_strict_reference_model_state_matches_config_and_command(
    tmp_path: Path,
) -> None:
    config = tmp_path / "riscv-arch-test/config/test/test_config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("ref_model_exe: sail_riscv_sim\n", encoding="utf-8")
    _write_state(
        tmp_path / "validation.yaml",
        self_checking={
            "model": "sail",
            "executable": "spike",
            "config_file": "config/other/test_config.yaml",
            "passed": True,
            "command": "make CONFIG_FILES=config/test/test_config.yaml",
        },
    )
    checker = ACT4TestAssetChecker(
        validation_state="validation.yaml",
        act4_root="riscv-arch-test",
        require_reference_model_logs=True,
    ).set_workspace(str(tmp_path))
    findings = []

    checker._check_validation_state(tmp_path, findings)

    checks = {item["check"] for item in findings}
    assert "validation_self_check_executable_mismatch" in checks
    assert "validation_self_check_config_file_mismatch" in checks


def test_reference_model_executable_path_preserves_case(tmp_path: Path) -> None:
    executable = "/opt/SailModel/bin/Sail_RISCV_Sim"
    config = tmp_path / "riscv-arch-test/config/test/test_config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(f"ref_model_exe: {executable}\n", encoding="utf-8")
    _write_state(
        tmp_path / "validation.yaml",
        self_checking={
            "model": "sail",
            "executable": executable,
            "config_file": "config/test/test_config.yaml",
            "passed": True,
            "command": "make CONFIG_FILES=config/test/test_config.yaml",
        },
    )
    checker = ACT4TestAssetChecker(
        validation_state="validation.yaml",
        act4_root="riscv-arch-test",
        require_reference_model_logs=True,
    ).set_workspace(str(tmp_path))
    findings: list[dict] = []

    checker._check_validation_state(tmp_path, findings)

    assert not any(
        item["check"] == "validation_self_check_executable_mismatch"
        for item in findings
    )


def test_generated_source_split_limit_is_checked_on_actual_output(
    tmp_path: Path,
) -> None:
    source = tmp_path / "tests" / "priv" / "H" / "H-00.S"
    elf = tmp_path / "elfs" / "H-00.elf"
    source.parent.mkdir(parents=True)
    elf.parent.mkdir(parents=True)
    source.write_text(
        'one_str: .string "one"\ntwo_str: .string "two"\n',
        encoding="utf-8",
    )
    elf.write_bytes(b"\x7fELF\x02" + b"\x00" * 59)
    checker = ACT4TestAssetChecker(
        source_files=[str(source.relative_to(tmp_path))],
        elf_files=[str(elf.relative_to(tmp_path))],
        validate_test_config=False,
        require_matching_stems=True,
        max_testcases_per_source=1,
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert any(
        item["check"] == "test_source_split_limit"
        for item in result["report"]["findings"]
    )


def test_generated_source_split_limit_is_derived_from_current_act4(
    tmp_path: Path,
) -> None:
    source = tmp_path / "tests" / "priv" / "H" / "H-00.S"
    elf = tmp_path / "elfs" / "H-00.elf"
    constants = (
        tmp_path
        / "riscv-arch-test/generators/testgen/src/testgen/constants.py"
    )
    source.parent.mkdir(parents=True)
    elf.parent.mkdir(parents=True)
    constants.parent.mkdir(parents=True)
    source.write_text(
        'one_str: .string "one"\ntwo_str: .string "two"\n',
        encoding="utf-8",
    )
    elf.write_bytes(b"\x7fELF\x02" + b"\x00" * 59)
    constants.write_text("TESTCASES_PER_PRIV_FILE = 1\n", encoding="utf-8")
    checker = ACT4TestAssetChecker(
        source_files=[str(source.relative_to(tmp_path))],
        elf_files=[str(elf.relative_to(tmp_path))],
        act4_root="riscv-arch-test",
        validate_test_config=False,
        require_matching_stems=True,
        derive_priv_testcase_limit=True,
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is True
    assert result["report"]["checks"]["max_testcases_per_source"] == 1
    assert any(
        item["check"] == "test_source_split_limit" and item["severity"] == "warning"
        for item in result["report"]["findings"]
    )
