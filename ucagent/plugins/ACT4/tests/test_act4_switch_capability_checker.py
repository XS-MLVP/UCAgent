from pathlib import Path

import yaml

from act4_privileged_suite.checkers.act4_switch_capability_checker import ACT4SwitchCapabilityChecker


def _write(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _audit(control: dict) -> dict:
    return {
        "schema_version": 1,
        "suite": "H",
        "act4_git_head": "abc123",
        "audited_sources": [
            {"kind": "file", "value": "tests/env/riscv_arch_test.h"}
        ],
        "required_capabilities": [],
        "controls": [control],
        "decision_summary": {
            "allowed_controls": [control["name"]] if control["decision"] == "allowed" else [],
            "limited_controls": [],
            "blocked_capabilities": [],
        },
    }


def _control(**overrides) -> dict:
    control = {
        "name": "RVTEST_HYPERVISOR",
        "class": "suite_opt_in",
        "defined_by": "new_suite_generator",
        "effective_state": "included before framework header",
        "supported_entrypoint": "extra_defines",
        "permitted_action": "define in new suite generator",
        "baseline_edit_required": False,
        "decision": "allowed",
        "evidence": ["registry.py extra_defines"],
        "affected_profiles": [],
        "limitations": [],
        "blocked_reason": None,
    }
    control.update(overrides)
    return control


def test_valid_suite_opt_in_and_matching_head_pass(tmp_path: Path) -> None:
    _write(tmp_path / "audit.yaml", _audit(_control()))
    _write(tmp_path / "manifest.yaml", {"baseline": {"git_head": "abc123"}})
    checker = ACT4SwitchCapabilityChecker(
        "audit.yaml", baseline_manifest="manifest.yaml"
    ).set_workspace(str(tmp_path))

    passed, report = checker.do_check()

    assert passed
    assert report["summary"] == {"errors": 0, "warnings": 0}


def test_allowed_control_cannot_require_baseline_edit(tmp_path: Path) -> None:
    _write(tmp_path / "audit.yaml", _audit(_control(baseline_edit_required=True)))
    checker = ACT4SwitchCapabilityChecker("audit.yaml").set_workspace(str(tmp_path))

    passed, report = checker.do_check()

    assert not passed
    assert any(item["check"] == "switch_allowed_baseline" for item in report["findings"])


def test_supported_capability_cannot_be_suite_defined(tmp_path: Path) -> None:
    control = _control(
        name="H_SUPPORTED",
        defined_by="new_suite_generator",
        **{"class": "suite_opt_in"},
    )
    _write(tmp_path / "audit.yaml", _audit(control))
    checker = ACT4SwitchCapabilityChecker("audit.yaml").set_workspace(str(tmp_path))

    passed, report = checker.do_check()

    assert not passed
    checks = {item["check"] for item in report["findings"]}
    assert "switch_capability_class" in checks
    assert "switch_capability_owner" in checks


def test_framework_blocked_requires_scope_and_reason(tmp_path: Path) -> None:
    control = _control(
        decision="framework_blocked",
        supported_entrypoint=None,
        permitted_action="none",
        affected_profiles=[],
        blocked_reason=None,
    )
    audit = _audit(control)
    audit["decision_summary"] = {
        "allowed_controls": [],
        "limited_controls": [],
        "blocked_capabilities": ["RVTEST_HYPERVISOR"],
    }
    _write(tmp_path / "audit.yaml", audit)
    checker = ACT4SwitchCapabilityChecker("audit.yaml").set_workspace(str(tmp_path))

    passed, report = checker.do_check()

    assert not passed
    checks = {item["check"] for item in report["findings"]}
    assert "switch_blocked_reason" in checks
    assert "switch_blocked_scope" in checks


def test_summary_must_match_control_decisions(tmp_path: Path) -> None:
    audit = _audit(_control())
    audit["decision_summary"]["allowed_controls"] = []
    _write(tmp_path / "audit.yaml", audit)
    checker = ACT4SwitchCapabilityChecker("audit.yaml").set_workspace(str(tmp_path))

    passed, report = checker.do_check()

    assert not passed
    assert any(item["check"] == "switch_summary_consistency" for item in report["findings"])


def test_expected_suite_and_required_capability_schema_are_checked(tmp_path: Path) -> None:
    audit = _audit(_control())
    audit["required_capabilities"] = [{"name": "guest entry", "required_by": [], "evidence": []}]
    _write(tmp_path / "audit.yaml", audit)
    checker = ACT4SwitchCapabilityChecker(
        "audit.yaml", expected_suite="S"
    ).set_workspace(str(tmp_path))

    passed, report = checker.do_check()

    assert not passed
    checks = {item["check"] for item in report["findings"]}
    assert "switch_audit_suite" in checks
    assert "required_capability_scope" in checks
    assert "required_capability_evidence" in checks


def test_git_head_must_match_baseline_manifest(tmp_path: Path) -> None:
    _write(tmp_path / "audit.yaml", _audit(_control()))
    _write(tmp_path / "manifest.yaml", {"baseline": {"git_head": "different"}})
    checker = ACT4SwitchCapabilityChecker(
        "audit.yaml", baseline_manifest="manifest.yaml"
    ).set_workspace(str(tmp_path))

    passed, report = checker.do_check()

    assert not passed
    assert any(item["check"] == "switch_audit_git_head" for item in report["findings"])


def test_audited_workspace_source_paths_must_exist(tmp_path: Path) -> None:
    audit = _audit(_control())
    audit["audited_sources"] = [
        {"kind": "file", "value": "riscv-arch-test/README.md"},
        {
            "kind": "command",
            "value": "command -v sail_riscv_sim => /tools/sail_riscv_sim",
        },
    ]
    _write(tmp_path / "audit.yaml", audit)
    checker = ACT4SwitchCapabilityChecker(
        "audit.yaml", verify_audited_source_paths=True
    ).set_workspace(str(tmp_path))

    passed, report = checker.do_check()

    assert not passed
    assert any(
        item["check"] == "switch_audited_source_path"
        for item in report["findings"]
    )


def test_command_evidence_is_not_mistaken_for_workspace_path(
    tmp_path: Path,
) -> None:
    source = tmp_path / "riscv-arch-test/README.md"
    source.parent.mkdir(parents=True)
    source.write_text("source\n", encoding="utf-8")
    audit = _audit(_control())
    audit["audited_sources"] = [
        {"kind": "file", "value": "riscv-arch-test/README.md"},
        {
            "kind": "command",
            "value": "command -v sail_riscv_sim => /tools/sail_riscv_sim",
        },
    ]
    _write(tmp_path / "audit.yaml", audit)
    checker = ACT4SwitchCapabilityChecker(
        "audit.yaml", verify_audited_source_paths=True
    ).set_workspace(str(tmp_path))

    passed, report = checker.do_check()

    assert passed
    assert report["checks"]["verified_source_paths"] == 1


def test_typed_audited_sources_distinguish_files_and_commands(
    tmp_path: Path,
) -> None:
    source = tmp_path / "riscv-arch-test/README.md"
    source.parent.mkdir(parents=True)
    source.write_text("source\n", encoding="utf-8")
    audit = _audit(_control())
    audit["audited_sources"] = [
        {"kind": "file", "value": "riscv-arch-test/README.md"},
        {"kind": "command", "value": "sail_riscv_sim --version"},
        {"kind": "tool_result", "value": "sail_riscv_sim version output"},
    ]
    _write(tmp_path / "audit.yaml", audit)
    checker = ACT4SwitchCapabilityChecker(
        "audit.yaml",
        verify_audited_source_paths=True,
    ).set_workspace(str(tmp_path))

    passed, report = checker.do_check()

    assert passed
    assert report["checks"]["verified_source_paths"] == 1


def test_typed_source_schema_is_checked_without_path_verification(
    tmp_path: Path,
) -> None:
    audit = _audit(_control())
    audit["audited_sources"] = ["untyped source"]
    _write(tmp_path / "audit.yaml", audit)
    checker = ACT4SwitchCapabilityChecker("audit.yaml").set_workspace(
        str(tmp_path)
    )

    passed, report = checker.do_check()

    assert not passed
    assert any(
        item["check"] == "switch_audited_source_schema"
        for item in report["findings"]
    )


def test_typed_file_evidence_rejects_globs(tmp_path: Path) -> None:
    audit = _audit(_control())
    audit["audited_sources"] = [
        {"kind": "file", "value": "riscv-arch-test/work/**/*.sig.log"}
    ]
    _write(tmp_path / "audit.yaml", audit)
    checker = ACT4SwitchCapabilityChecker(
        "audit.yaml",
        verify_audited_source_paths=True,
    ).set_workspace(str(tmp_path))

    passed, report = checker.do_check()

    assert not passed
    assert any(
        item["check"] == "switch_audited_source_glob"
        for item in report["findings"]
    )


def test_workflow_required_capabilities_must_be_present(tmp_path: Path) -> None:
    _write(tmp_path / "audit.yaml", _audit(_control()))
    checker = ACT4SwitchCapabilityChecker(
        "audit.yaml", required_capability_names=["reference_model_executable"]
    ).set_workspace(str(tmp_path))

    passed, report = checker.do_check()

    assert not passed
    assert any(
        item["check"] == "required_capability_missing"
        for item in report["findings"]
    )
