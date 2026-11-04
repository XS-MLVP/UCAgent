"""Exercise repair design, accountable stopping, and review-only execution contracts."""

from pathlib import Path
import copy
import json
import os
import sys
import time

import pytest
import yaml

from act4_privileged_suite.checkers.act4_review_checker import ACT4ReviewChecker, execute_command, resolve_validation_plan
from act4_privileged_suite.checkers import act4_review_checker
from act4_privileged_suite.review_tools import ACT4ReviewDocument
from ucagent.tools.uctool import to_mcp_tool

from test_act4_review_checker import ReviewHarness
from test_act4_review_checker import isolate_optional_simulators as isolate_optional_simulators


@pytest.mark.parametrize("field", ["repair_plan", "expected_behavior", "stimulus", "observation", "resources", "restoration", "next_action", "basis", "paths", "validation_jobs"])
def test_confirmed_findings_require_actionable_design(tmp_path: Path, field: str) -> None:
    """Reject an absent design or incomplete ready plan instead of accepting prose deferral."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    finding = review["findings"][0]
    if field == "repair_plan":
        finding.pop(field)
    else:
        finding["repair_plan"].pop(field)
    harness.write("review.yaml", review)
    passed, result = harness.checker("audit").do_check(is_complete=True)
    assert not passed, result


def test_unfinished_design_can_enter_repair_without_formal_changes(tmp_path: Path) -> None:
    """Keep the investigation path open without authorizing speculative source edits."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    finding = review["findings"][0]
    finding["diagnosis"] = "cause_identified"
    finding["repair_plan"].update(paths=[], validation_jobs=[])
    review["changes"] = []
    harness.write("review.yaml", review)
    assert harness.checker("audit").do_check(is_complete=True)[0]
    assert harness.checker("repair").do_check()[0]
    (harness.output / "candidate/generators/H.py").write_text("VALUE = 2\n")
    passed, result = harness.checker("repair").do_check()
    assert not passed and "outside review.changes" in result["error"]


@pytest.mark.parametrize("stop", ["unfinished_work", "external_dependency", "budget_exhausted"])
@pytest.mark.parametrize("valid", [True, False])
def test_stop_reasons_require_distinct_evidence(tmp_path: Path, stop: str, valid: bool) -> None:
    """Separate external dependencies, incomplete agent work and evidenced budget exhaustion."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    review["changes"] = []
    harness.write("review.yaml", review)
    assert harness.checker("repair").do_check(run_commands=True)[0]
    final = {"schema_version": 1, "suite": "H", "summary": "Repair remains unfinished", "findings": [
        {"id": "F1", "status": "deferred", "reason": "The fixture is incomplete", "evidence": ["evidence-after.json"],
         "next_action": "Continue the declared minimal experiment"}], "ci_passed": True,
        "remaining_risks": ["Synthetic evidence only"], "coverage_changes": [], "traceability": []}
    harness.write_final(final)
    finding = final["findings"][0]
    blocker = finding["blocker"]
    blocker["stop_reason"] = stop
    basis = finding["investigation"][0]["basis"]
    if stop == "external_dependency":
        blocker.update(owner="upstream", alternatives=[{"route": route, "status": "ruled_out", "result": "Required fixture dependency is absent", "basis": basis}
            for route in ("suite_local", "positive_subset", "native_entrypoint", "validation_only")])
        if not valid:
            blocker["alternatives"][0]["status"] = "pending"
    elif stop == "budget_exhausted":
        blocker["budget"] = {"resource": "tokens", "limit": 2, "consumed": 2 if valid else 1, "basis": basis}
    elif not valid:
        blocker["owner"] = "upstream"
    harness.write("final.yaml", final)
    passed, result = harness.checker("final").do_check(is_complete=True)
    assert passed is valid, result


@pytest.mark.parametrize("case", ["native", "native_template", "wrong_runner", "excluded_target", "excluded_extension", "disabled", "wrong_config", "diagnostic", "unknown_target"])
def test_native_validation_alignment(tmp_path: Path, case: str) -> None:
    """Reject known CI deviations unless explicitly diagnostic, without guessing unknown layouts."""
    target = tmp_path / "config/qemu/rv64"
    target.mkdir(parents=True)
    (target / "test_config.yaml").write_text("ref_model_exe: sail_riscv_sim\n")
    (target / "run_cmd.txt").write_text("qemu-system-riscv64 {debug:-d in_asm} -bios\n")
    policy = {"ci_enabled": case != "disabled", "exclude_configs": ["rv64"] if case == "excluded_target" else [],
              "exclude_extensions": ["H"] if case == "excluded_extension" else []}
    (target.parent / "ci.yaml").write_text(yaml.safe_dump(policy))
    (tmp_path / "Makefile").write_text("lint:\n\truff check .\n")
    runner = "sail_riscv_sim" if case in {"wrong_runner", "diagnostic"} else "qemu-system-riscv64 -bios"
    if case == "native_template":
        runner = (target / "run_cmd.txt").read_text().strip()
    job = {"id": "model", "target": "rv64", "purpose": "reference_model", "source": "Makefile", "disposition": "run",
           "argv": ["./run_tests.py", runner, "work/rv64/elfs"]}
    if case == "wrong_config":
        job.update(purpose="build", argv=["make", "elfs", "CONFIG_FILES=config/wrong/test_config.yaml"])
    if case == "diagnostic":
        job["diagnostic_reason"] = "Additional runner compatibility experiment, not QEMU CI"
    if case == "unknown_target":
        job["target"] = "rv32"
    plan = resolve_validation_plan(tmp_path, {"suite": "H", "targets": [job["target"]], "jobs": [job]})
    assert bool(plan["errors"]) is (case not in {"native", "native_template", "diagnostic", "unknown_target"})
    if case in {"native", "native_template", "diagnostic", "unknown_target"}:
        assert plan["jobs"]["model"]["kind"] == {"native": "native_subset", "native_template": "native_subset", "diagnostic": "diagnostic", "unknown_target": "unverified"}[case]
    assert plan["full_matrix"] is False


def test_local_lint_does_not_claim_full_ci(tmp_path: Path) -> None:
    """Keep make lint separate from the workflow's complete prek checks."""
    (tmp_path / "Makefile").write_text("lint:\n\truff check .\n")
    scope = {"suite": "H", "targets": ["rv64"], "jobs": [{"id": "lint", "target": "rv64", "source": "Makefile", "purpose": "lint", "disposition": "run", "argv": ["make", "lint"]}]}
    assert resolve_validation_plan(tmp_path, scope)["jobs"]["lint"]["kind"] == "local_only"


@pytest.fixture
def experiment_harness(tmp_path: Path) -> tuple[ReviewHarness, dict]:
    """Prepare an unresolved finding and an explicit, dependency-scoped experimental plan."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    review["changes"] = []
    review["findings"][0]["diagnosis"] = "cause_identified"
    review["experiments"] = [{"id": "E1", "findings": ["F1"], "question": "Can this fixture emit a missing case?",
        "success_criterion": "Inspect emitted fixture output without asserting ISA correctness",
        "paths": ["generators/H.py"], "jobs": ["reference_model"], "assets": copy.deepcopy(harness.scope["assets"])}]
    harness.write("review.yaml", review)
    return harness, review


def test_experiment_isolation_dependencies_receipts_and_context(experiment_harness) -> None:
    """Run real fixture commands in isolation and expose exact, replayable experimental citations."""
    harness, review = experiment_harness
    checker = harness.checker("audit")
    assert checker.do_check(experiment={"action": "prepare", "id": "E1"})[0]
    source = harness.output / "experiments/E1/candidate/generators/H.py"
    source.write_text('"""Experimental boundary."""\nVALUE = 2\n')
    passed, result = checker.do_check(experiment={"action": "run", "id": "E1"})
    assert passed, result
    assert set(result["jobs"]) == {"environment", "generation", "build", "reference_model"}
    assert all(status == "passed" for status in result["jobs"].values())
    assert not (harness.output / "candidate").exists()
    assert "VALUE = 1" in (harness.source / "generators/H.py").read_text()
    assert not checker.do_check(is_complete=True, experiment={"action": "run", "id": "E1"})[0]
    assert not checker.do_check(experiment={"action": "run", "id": "E1"})[0]
    assert harness.checker("final").do_check(experiment={"action": "status", "id": "E1"})[1]["final_review"] == "not_checked"
    tool = ACT4ReviewDocument(workspace=str(harness.root), review_dir="reports/H/review", suite="H", write_dirs=["reports"])
    context = tool.invoke({"action": "context", "finding_id": "F1"})
    assert context["ok"] and "experiments/E1/candidate/generators/H.py" in context["source_candidates"]
    quote = tool.invoke({"action": "quote", "citations": [{"path": "experiments/E1/candidate/generators/H.py", "lines": [2, 2], "observation": "Experimental fixture changed VALUE"}]})
    assert quote["ok"] and quote["citations"][0]["quote"] == "VALUE = 2"
    review["findings"][0]["investigation"].append({"action": "Run E1", "result": "Fixture output retained; real semantics still unverified", "basis": quote["citations"]})
    harness.write("review.yaml", review)
    assert checker.do_check()[0]
    assert "context" in to_mcp_tool(tool).parameters["properties"]["action"]["enum"]
    source.write_text("Forged after the run\n")
    passed, result = checker.do_check()
    assert not passed and "Experiment source or artifact changed" in result["error"]


@pytest.mark.parametrize("defect", ["unknown", "traversal", "protected", "generated", "undeclared", "changed_plan", "forged_receipt"])
def test_experiment_rejects_unsafe_or_stale_work(experiment_harness, defect: str) -> None:
    """Do not turn experimental execution into unscoped editing or forged acceptance."""
    harness, review = experiment_harness
    checker = harness.checker("audit")
    if defect in {"traversal", "protected", "generated"}:
        review["experiments"][0]["paths"] = [{"traversal": "../secret", "protected": "tests/env/signature.h", "generated": "tests/priv/H.S"}[defect]]
        harness.write("review.yaml", review)
    if defect in {"unknown", "traversal", "protected", "generated"}:
        assert not checker.do_check(experiment={"action": "prepare", "id": "E2" if defect == "unknown" else "E1"})[0]
        return
    assert checker.do_check(experiment={"action": "prepare", "id": "E1"})[0]
    if defect == "undeclared":
        (harness.output / "experiments/E1/candidate/README.md").write_text("Unapproved change\n")
    elif defect == "changed_plan":
        review["experiments"][0]["question"] = "A different question"
        harness.write("review.yaml", review)
    else:
        assert checker.do_check(experiment={"action": "run", "id": "E1"})[0]
        (harness.output / "evidence-experiment-E1.json").write_text("{}")
        assert not checker.do_check()[0]
        return
    assert not checker.do_check(experiment={"action": "run", "id": "E1"})[0]


def test_experiment_budget_survives_checker_reconstruction(experiment_harness) -> None:
    """Count completed attempts across Check instances rather than resetting a local counter."""
    harness, review = experiment_harness
    checker = ACT4ReviewChecker("audit", "H", "reports/H/review", max_experiments=1).set_workspace(str(harness.root)).set_stage_manager(harness.manager)
    assert checker.do_check(experiment={"action": "prepare", "id": "E1"})[0]
    assert checker.do_check(experiment={"action": "run", "id": "E1"})[0]
    review["experiments"].append({**copy.deepcopy(review["experiments"][0]), "id": "E2"})
    harness.write("review.yaml", review)
    checker = ACT4ReviewChecker("audit", "H", "reports/H/review", max_experiments=1).set_workspace(str(harness.root)).set_stage_manager(harness.manager)
    assert checker.do_check(experiment={"action": "prepare", "id": "E2"})[0]
    passed, result = checker.do_check(experiment={"action": "run", "id": "E2"})
    assert not passed and "budget exhausted" in result["error"]


def test_expired_experiment_budget_never_starts_command(tmp_path: Path) -> None:
    """An expired shared deadline prevents subsequent commands from spending another timeout."""
    result = execute_command([sys.executable, "-c", "raise RuntimeError('must not run')"], tmp_path,
                             dict(os.environ), tmp_path / "budget.log", 10, deadline=time.monotonic() - 1)
    assert result["status"] == "budget_exhausted"
    assert "RuntimeError" not in (tmp_path / "budget.log").read_text()


@pytest.mark.parametrize("change", ["none", "source", "outcome", "snapshot"])
def test_final_reuse_is_bound_to_accepted_dependency_inputs(tmp_path: Path, change: str, monkeypatch) -> None:
    """Reuse unchanged source judgments only, and invalidate changed or forged dependencies."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    if change != "source":
        review["changes"] = []
    harness.write("review.yaml", review)
    assert harness.checker("audit").do_check(is_complete=True)[0]
    assert harness.checker("repair").do_check()[0]
    if change == "source":
        (harness.output / "candidate/generators/H.py").write_text('"""Changed fixture."""\nVALUE = 2\n')
    if change == "outcome":
        original = act4_review_checker.execute_command

        def changed_outcome(argv, cwd, env, log, timeout, **kwargs):
            """Simulate a changed execution result without changing any declared input."""
            result = original(argv, cwd, env, log, timeout, **kwargs)
            if log.name == "after-coverage.log":
                result.update(status="failed", exit_code=1, reason="Coverage execution changed")
            return result

        monkeypatch.setattr(act4_review_checker, "execute_command", changed_outcome)
    assert harness.checker("repair").do_check(run_commands=True)[0]
    final = {"schema_version": 1, "suite": "H", "summary": "Unchanged facts are candidates for explicit reuse", "findings": [
        {"id": "F1", "status": "deferred", "reason": "Fixture implementation pending", "evidence": ["evidence-after.json"],
         "next_action": "Implement the remaining fixture boundary"}], "ci_passed": change != "outcome",
        "remaining_risks": ["Synthetic semantics only"], "coverage_changes": [], "traceability": []}
    harness.write_final(final)
    if change == "snapshot":
        (harness.output / "review-accepted.json").write_text("{}")
    passed, result = harness.checker("final").do_check(is_complete=True)
    if change == "snapshot":
        assert not passed and "snapshot changed" in result["error"]
        return
    assert passed, result
    reuse = json.loads((harness.output / "reuse-final.json").read_text())
    if change != "none":
        assert reuse["judgments"] == {}
        return
    assert reuse["judgments"] and not any(identity.startswith(("finding:", "change:", "obligation:")) for identity in reuse["judgments"])
    fresh = [item for item in final["semantic_review"]["judgments"] if not set(item["tasks"]) <= set(reuse["judgments"])]
    final["semantic_review"]["judgments"] = fresh
    harness.write("final.yaml", final)
    tool = ACT4ReviewDocument(workspace=str(harness.root), review_dir="reports/H/review", suite="H", write_dirs=["reports"])
    status = tool.invoke({"action": "status", "document": "final"})
    updated = tool.invoke({"action": "reuse", "document": "final", "expected_sha256": status["sha256"]})
    assert updated["ok"], updated
    assert harness.checker("final").do_check(is_complete=True)[0]
    persisted = yaml.safe_load((harness.output / "final.yaml").read_text())
    assert persisted["semantic_review"]["reused_tasks"]
    persisted["semantic_review"]["reused_tasks"].append("finding:F1")
    harness.write("final.yaml", persisted)
    passed, result = harness.checker("final").do_check(is_complete=True)
    assert not passed and "ineligible" in result["error"]


@pytest.mark.parametrize("progress, valid", [("not_started", True), ("designing", True), ("implemented", False), ("validated", False), ("not_applicable", False), ("", False)])
def test_report_progress_cannot_overclaim_implementation(tmp_path: Path, progress: str, valid: bool) -> None:
    """Separately gate repair progress and disposition instead of accepting an authored success label."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    review["changes"] = []
    review["findings"][0]["root_cause_key"] = "fixture.missing_boundary"
    harness.write("review.yaml", review)
    assert harness.checker("repair").do_check(run_commands=True)[0]
    final = {"schema_version": 1, "suite": "H", "summary": "The boundary is missing; implementation is unfinished and needs no user input.", "findings": [
        {"id": "F1", "status": "deferred", "repair_progress": progress, "reason": "Fixture boundary not implemented", "evidence": ["evidence-after.json"],
         "next_action": "Implement the declared boundary"}], "ci_passed": True,
        "remaining_risks": ["Synthetic evidence only"], "coverage_changes": [], "traceability": []}
    harness.write_final(final)
    passed, result = harness.checker("final").do_check(is_complete=True)
    assert passed is valid, result
    if valid:
        report = (harness.output / "final.md").read_text()
        assert report.index(final["summary"]) < report.index("## Repair summary") < report.index("## Help requested") < report.index("## Findings and outcomes")
        assert "Agent work unfinished" in report and "Upstream full CI: **not certified**" in report
        assert "fixture.missing_boundary" in report and "local_only" in report
        assert "not a claim that repair is impossible" in report


@pytest.mark.parametrize("attempt", ["none", "invented_experiment"])
def test_unfinished_confirmed_repair_requires_actual_investigation(tmp_path: Path, attempt: str) -> None:
    """A detailed plan must not serve as evidence of work that was never attempted."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    review["changes"] = []
    harness.write("review.yaml", review)
    assert harness.checker("repair").do_check(run_commands=True)[0]
    final = {"schema_version": 1, "suite": "H", "summary": "Work is not finished", "findings": [
        {"id": "F1", "status": "deferred", "reason": "No implementation", "evidence": ["evidence-after.json"], "next_action": "Run E1"}],
        "ci_passed": True, "remaining_risks": ["Unfinished"], "coverage_changes": [], "traceability": []}
    harness.write_final(final)
    alternatives = final["findings"][0]["blocker"]["alternatives"]
    if attempt == "none":
        alternatives.clear()
    else:
        alternatives[0].update(status="tried", experiment_id="E999")
    harness.write("final.yaml", final)
    passed, result = harness.checker("final").do_check(is_complete=True)
    assert not passed, result


def test_authored_reuse_provenance_is_not_accepted(tmp_path: Path) -> None:
    """Only current, source-validated reuse references can acquire machine provenance."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    review["semantic_review"]["judgments"][0]["reused_from"] = {"artifact": "invented.json"}
    harness.write("review.yaml", review)
    passed, result = harness.checker("audit").do_check(is_complete=True)
    assert not passed and "Do not author reused_from" in result["error"]
