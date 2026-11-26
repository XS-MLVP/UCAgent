"""Verify missing-capability planning and real, tamper-evident completion validation offline."""

import json
import os
import sys
from types import SimpleNamespace

import pytest
import yaml

from ucagent_act4.checkers import act4_generation_completion_checker as completion
from ucagent_act4.finding_acceptance import instruction_sequence
from ucagent_act4.xiangshan_bundle import sha256


@pytest.fixture
def scope(tmp_path, monkeypatch):
    """Build a complete plan that validates real generated files without external tools."""
    for name in ("inputs", "environment"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "receipt.json").write_text("{}")
    (tmp_path / "artifact.txt").write_text("verified behavior")
    (tmp_path / "check.py").write_text("from pathlib import Path\nassert Path('artifact.txt').read_text() == 'verified behavior'\n")
    plan = {"schema_version": 1, "suite": "Example", "requested_scope": "RV32/RV64 architecture",
            "items": [{"id": area, "area": area, "action": "generate", "scope": "Declared architecture behavior",
                       "rationale": "Derive missing assets from the pinned original specification",
                       "artifacts": ["artifact.txt", "check.py"],
                       "checks": [{"argv": [sys.executable, "check.py"], "cwd": ".", "inputs": ["check.py"]}]} for area in sorted(completion.AREAS)]}
    path = tmp_path / "completion.yaml"
    path.write_text(yaml.safe_dump(plan))
    state = {}
    manager = SimpleNamespace(get_data=state.get, set_data=state.__setitem__)
    monkeypatch.setattr(completion, "read_generation_inputs", lambda *args: {"suite": "Example", "limitations": []})
    monkeypatch.setattr(completion, "prepared_environment", lambda *args: dict(os.environ))

    def checker(phase="plan", final_report=None, review_dir=None, cfg=None):
        """Bind a checker instance to the authenticated fixture state."""
        return completion.ACT4GenerationCompletionChecker("Example", "completion.yaml", "inputs", "validation",
                                                          "environment", phase=phase, final_report=final_report, review_dir=review_dir, cfg=cfg).set_workspace(str(tmp_path)).set_stage_manager(manager)

    return SimpleNamespace(root=tmp_path, plan=plan, path=path, checker=checker, state=state)


@pytest.mark.parametrize("steps,body,expected", [
    (["vsse32.v *", "RVTEST_SIGUPD(*)"], "vlse32.v v0, (x6), x7\nRVTEST_SIGUPD(x2)", False),
    (["vsse32.v *", "RVTEST_SIGUPD(*)"], "vsse32.v v0, (x6), x7\nRVTEST_SIGUPD(x2)", True),
    (["sspopchk x1", "ssrdp x8", "RVTEST_SIGUPD(*x8*)"], "sspopchk x1\nother:\nssrdp x8\nRVTEST_SIGUPD(x8)", False),
    (["sspopchk x1", "ssrdp x8"], "sspopchk x1\n# ssrdp x8\n.word 0 # ssrdp x8", False),
    (["sspopchk x1", "ssrdp x8"], "#if 0\nsspopchk x1\n#endif\nssrdp x8", False),
    (["sspopchk x1", "ssrdp x8"], "#ifdef HAS_SS\nsspopchk x1\n#else\nssrdp x8\n#endif", False),
    (["sspopchk x1", "ssrdp x8", "RVTEST_SIGUPD(*x8*)"], "sspopchk x1\nssrdp x8\nRVTEST_SIGUPD(x2, x8)", True),
])
def test_same_case_behavior(steps, body, expected):
    """Distinguish real ordered behavior from similar instructions, comments or neighboring cases."""
    assert instruction_sequence("case_label:\n" + body, "case_label", steps) is expected


def test_finding_contract_across_generation_and_delivery(scope):
    """Bind the audited IDs and native cases; refuse silent downgrades, stale evidence and false closure."""
    review = scope.root / "review"
    review.mkdir()
    accepted = review / "review-accepted.json"
    accepted.write_text(json.dumps({"review": {"findings": [{"id": "F8", "classification": "confirmed_defect"},
        {"id": "F9", "classification": "not_a_defect"}]}}))
    state = {"audit_snapshot": sha256(accepted)}
    scope.state["act4_review:review:Example"] = state
    plan = scope.checker(review_dir="review")
    generated = scope.checker("generated", review_dir="review")
    config = "config/sail/rv64/test_config.yaml"
    source = "riscv-arch-test/tests/rv64i/Example/example.S"
    case = {"source": source, "label": "vector_store", "stimulus": ["vsse32.v *"], "observation": ["RVTEST_SIGUPD(*)"]}
    assert not plan.do_check(is_complete=True)[0]
    scope.plan["finding_checks"] = {"F8": {"item": "stimulus", "kind": "behavior", "configs": [config], "cases": [case]}}
    scope.path.write_text(yaml.safe_dump(scope.plan))
    assert plan.do_check(is_complete=True)[0]
    (scope.root / "asset_contract.yaml").write_text(yaml.safe_dump({"suite": "Example", "validation_configs": [config]}))
    assembly = scope.root / source
    assembly.parent.mkdir(parents=True)
    assembly.write_text("vector_store:\nvlse32.v v1, (x6), x7\nRVTEST_SIGUPD(x2)\n")
    assert "F8" in generated.do_check()[1]["error"]
    case["stimulus"] = ["vlse32.v *"]
    scope.path.write_text(yaml.safe_dump(scope.plan))
    assert "changed after planning" in generated.do_check()[1]["error"]
    case["stimulus"] = ["vsse32.v *"]
    scope.path.write_text(yaml.safe_dump(scope.plan))
    partial = {"act4_run": {"accepted_partial_findings": ["F8"]}}
    verifier = scope.checker("verify", review_dir="review", cfg=partial)
    passed, result = verifier.do_check(action="validate")
    assert passed and not result["scope_complete"] and result["missing_witnesses"] == ["F8"]
    final = review / "final-accepted.json"
    final.write_text(json.dumps({"findings": [{"id": "F8", "status": "fixed"}]}))
    state["final_snapshot"] = sha256(final)
    assert "cannot be reported as closed" in scope.checker("verify", "final.md", "review", partial).do_check()[1]["error"]
    assembly.write_text(assembly.read_text().replace("vlse32", "vsse32"))
    assert generated.do_check()[0]
    assert "changed" in verifier.do_check()[1]["error"]
    assert verifier.do_check(action="validate")[0]
    accepted.write_text("{}")
    assert not generated.do_check()[0]


def test_artifact_and_execution_acceptance_preserve_dedicated_checks(scope):
    """Allow new validation without replacing accepted metadata and execution checks or inventing configurations."""
    review = scope.root / "review"
    review.mkdir()
    accepted = review / "review-accepted.json"
    accepted.write_text(json.dumps({"review": {"findings": [{"id": identity, "classification": "confirmed_defect"} for identity in ("F1", "F3")]}}))
    scope.state["act4_review:review:Example"] = {"audit_snapshot": sha256(accepted)}
    config = "config/sail/rv64/test_config.yaml"
    scope.plan["finding_checks"] = {"F3": {"item": "norm_mapping", "kind": "artifact", "cases": [], "configs": []},
                                    "F1": {"item": "norm_mapping", "kind": "execution", "cases": [], "configs": [config]}}
    scope.path.write_text(yaml.safe_dump(scope.plan))
    checker = scope.checker(review_dir="review")
    assert "dedicated" in checker.do_check()[1]["error"]
    scope.plan["finding_checks"]["F1"]["item"] = "build"
    scope.path.write_text(yaml.safe_dump(scope.plan))
    assert checker.do_check(is_complete=True)[0]
    native = scope.root / "asset_contract.yaml"
    native.write_text(yaml.safe_dump({"suite": "Example", "validation_configs": []}))
    generated = scope.checker("generated", review_dir="review")
    assert "configuration is not" in generated.do_check()[1]["error"]
    native.write_text(yaml.safe_dump({"suite": "Example", "validation_configs": [config]}))
    checks = next(item["checks"] for item in scope.plan["items"] if item["id"] == "norm_mapping")
    checks.append({"argv": [sys.executable, "check.py", "--rule"], "cwd": ".", "inputs": ["check.py"]})
    scope.path.write_text(yaml.safe_dump(scope.plan))
    assert generated.do_check()[0]
    checks.pop(0)
    scope.path.write_text(yaml.safe_dump(scope.plan))
    assert "Restore the accepted" in generated.do_check()[1]["error"]


def test_missing_assets_become_work_then_require_actual_validation(scope):
    """Planning allows absent outputs, but final completion requires artifacts and executed checks."""
    (scope.root / "artifact.txt").unlink()
    assert scope.checker().do_check(is_complete=True)[0]
    verifier = scope.checker("verify")
    assert not verifier.do_check(is_complete=True)[0]
    (scope.root / "artifact.txt").write_text("verified behavior")
    assert not verifier.do_check(is_complete=True)[0]
    passed, report = verifier.do_check(action="validate", timeout=30)
    assert passed, report
    assert report["validated_commands"] == len(completion.AREAS)
    assert verifier.do_check(is_complete=True)[0]


@pytest.mark.parametrize("mutation", ["artifact", "plan", "log", "receipt", "environment"])
def test_completion_evidence_cannot_be_reused_after_changes(scope, mutation):
    """Any mutation of a validation dependency or evidence requires a fresh check."""
    verifier = scope.checker("verify")
    assert verifier.do_check(action="validate")[0]
    paths = {"artifact": "artifact.txt", "plan": "completion.yaml", "log": "validation/build-0.log",
             "receipt": "validation/receipt.json", "environment": "environment/receipt.json"}
    path = scope.root / paths[mutation]
    path.write_text(path.read_text() + "\n")
    assert not verifier.do_check(is_complete=True)[0]


def test_completion_receipt_binds_scripts_called_by_argv(scope):
    """A validation script is bound even when omitted from authored inputs and artifacts."""
    for item in scope.plan["items"]:
        item["artifacts"] = ["artifact.txt"]
        for check in item["checks"]:
            check["inputs"] = ["artifact.txt"]
    scope.path.write_text(yaml.safe_dump(scope.plan))
    verifier = scope.checker("verify")
    passed, report = verifier.do_check(action="validate")
    assert passed, report
    (scope.root / "check.py").write_text("raise SystemExit(1)\n")
    assert not verifier.do_check(is_complete=True)[0]


@pytest.mark.parametrize("mutation", ["missing_area", "duplicate", "missing_output", "missing_check", "skip_all", "escape", "fake_commercial", "software_blocker"])
def test_missing_work_cannot_be_disguised_as_unsupported(scope, mutation):
    """Reject empty work, implicit skip paths and software availability classified as external input."""
    item = scope.plan["items"][0]
    if mutation == "missing_area":
        scope.plan["items"].pop()
    elif mutation == "duplicate":
        scope.plan["items"].append(dict(item))
    elif mutation == "missing_output":
        item["artifacts"] = []
    elif mutation == "missing_check":
        item["checks"] = []
    elif mutation == "skip_all":
        for entry in scope.plan["items"]:
            entry.update(action="not_applicable", artifacts=[], checks=[])
    elif mutation == "escape":
        item["artifacts"] = ["../outside"]
    elif mutation == "fake_commercial":
        item.update(action="commercial_optional", tool="compiler", checks=[])
    else:
        item.update(action="external_input", reason_code="missing_generator", request="Please write testgen")
    scope.path.write_text(yaml.safe_dump(scope.plan))
    passed, report = scope.checker().do_check()
    assert not passed and report["error_code"] == "act4_generation_completion"


def test_commercial_optional_does_not_skip_generation(scope):
    """A real commercial simulator may be optional while every source-generation area remains checked."""
    scope.plan["items"].append({"id": "licensed_coverage", "area": "coverage", "action": "commercial_optional",
                                "tool": "questa", "scope": "Measured SV coverage", "rationale": "No simulator license available",
                                "artifacts": [], "checks": []})
    scope.path.write_text(yaml.safe_dump(scope.plan))
    passed, report = scope.checker("verify").do_check(action="validate")
    assert passed, report
    assert report["scope_complete"]
    assert report["limitations"][0]["reason"] == "commercial_license"


def test_failed_or_unavailable_free_checks_are_not_a_pass(scope):
    """Both a failing model assertion and a missing free executable keep the task unfinished."""
    verifier = scope.checker("verify")
    (scope.root / "artifact.txt").write_text("incorrect result")
    assert not verifier.do_check(action="validate")[0]
    (scope.root / "artifact.txt").write_text("verified behavior")
    scope.plan["items"][0]["checks"][0]["argv"] = ["/missing/open_source_tool"]
    scope.path.write_text(yaml.safe_dump(scope.plan))
    assert not verifier.do_check(action="validate")[0]


def test_external_help_is_precise_and_final_report_preserves_partial_scope(scope):
    """An actual unprovided device parameter produces a bounded limitation, not fabricated completeness."""
    item = scope.plan["items"][0]
    item.update(action="external_input", reason_code="target_information", request="Provide the target MMIO base address", checks=[])
    scope.path.write_text(yaml.safe_dump(scope.plan))
    verifier = scope.checker("verify")
    passed, report = verifier.do_check(action="validate")
    assert passed and not report["scope_complete"]
    summary = json.loads((scope.root / "validation/receipt.json").read_text())["summary"]
    (scope.root / "final.md").write_text("\n# Result\n\n```yaml\n" + yaml.safe_dump({"scope_completion": summary}) + "```\n")
    final = scope.checker("verify", "final.md")
    assert final.do_check(is_complete=True)[0]
    summary["scope_complete"] = True
    (scope.root / "final.md").write_text("```yaml\n" + yaml.safe_dump({"scope_completion": summary}) + "```\n")
    assert not final.do_check(is_complete=True)[0]


@pytest.mark.parametrize("area,allowed", [("reference_model", True), ("generator", False)])
def test_upstream_gap_is_a_limitation_not_a_suite_exemption(scope, area, allowed):
    """Record an unavailable shared dependency honestly without waiving suite implementation."""
    item = next(item for item in scope.plan["items"] if item["area"] == area)
    item.update(action="external_input", reason_code="upstream_coordination", request="Confirm missing upstream support", checks=[])
    scope.path.write_text(yaml.safe_dump(scope.plan))
    passed, report = scope.checker().do_check()
    assert passed is allowed
    if allowed:
        assert not report["scope_complete"] and report["limitations"][0]["reason"] == "upstream_coordination"


def test_generation_plans_do_not_require_skills(scope):
    """The same artifact gate works with no copied skill directory and with one present."""
    for enabled in (False, True):
        if enabled:
            (scope.root / ".ucagent/skills").mkdir(parents=True)
        assert scope.checker().do_check(is_complete=True)[0]
        assert scope.checker("verify").do_check(action="validate")[0]


def test_validation_dependencies_are_bound_separately_from_generated_artifacts(scope):
    """A check script is part of validation provenance even when it is not a generated asset."""
    for item in scope.plan["items"]:
        item["artifacts"] = ["artifact.txt"]
    scope.path.write_text(yaml.safe_dump(scope.plan))
    verifier = scope.checker("verify")
    assert verifier.do_check(action="validate")[0]
    (scope.root / "check.py").write_text("raise SystemExit(0)\n")
    assert not verifier.do_check(is_complete=True)[0]


def test_checks_cannot_modify_sources_and_then_claim_the_original_evidence(scope):
    """Validation receipts describe final immutable sources, not a pre-check version of modified code."""
    (scope.root / "check.py").write_text("from pathlib import Path\nPath('artifact.txt').write_text('changed')\n")
    passed, report = scope.checker("verify").do_check(action="validate")
    assert not passed and "changed completion sources" in report["error"]
