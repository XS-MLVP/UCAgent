"""Focused DesignWithPPA workflow tests: ppa iteration."""

from __future__ import annotations

import helpers  # noqa: F401  (runs the plugin sys.path bootstrap first)

from helpers import (
    _config,
    _prepare_iteration_workspace,
    _write_candidate_report,
    _write_json,
    _write_yaml,
)

import json
from pathlib import Path
import subprocess
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
from design_with_ppa.contracts import sha256_file




def _base_phase_checker(
    workspace: Path,
    candidate_checker: PPACandidateOptimizationChecker,
) -> PPABaseCharacterizationChecker:
    """Recreate the base-only gate from one initialized candidate fixture."""

    checker = PPABaseCharacterizationChecker(
        test_dir=candidate_checker.test_dir,
        functional_test_glob=candidate_checker.functional_test_glob,
        performance_contract_file=candidate_checker.performance_contract_file,
        performance_manifest_file=candidate_checker.performance_manifest_file,
        ppa_report_file=candidate_checker.ppa_report_file,
        rtl_backend_manifest_file=candidate_checker.rtl_backend_manifest_file,
        ledger_file=candidate_checker.ledger_file,
        base_report_file=candidate_checker.base_report_file,
        iteration_report_dir=candidate_checker.iteration_report_dir,
        timeout=candidate_checker.timeout,
        cfg=candidate_checker.cfg,
        rel_tolerance=candidate_checker.rel_tolerance,
        abs_tolerance=candidate_checker.abs_tolerance,
        ret_std_out=candidate_checker.ret_std_out,
        ret_std_error=candidate_checker.ret_std_error,
        input_manifest_file=candidate_checker.input_manifest_file,
        design_contract_files=candidate_checker.design_contract_files,
    ).set_workspace(str(workspace))
    checker.stage = candidate_checker.stage
    checker.on_init()
    return checker




@pytest.mark.parametrize("artifact", ["base_report", "snapshot_source"])
def test_base_phase_revalidates_immutable_artifacts(
    tmp_path: Path,
    artifact: str,
) -> None:
    """Repeated base checks reject changed report copies and snapshot sources."""

    candidate, _ = _prepare_iteration_workspace(tmp_path, iterations=1)
    checker = _base_phase_checker(tmp_path, candidate)
    if artifact == "base_report":
        base_path = tmp_path / "output" / "reports" / "ppa" / "base.json"
        payload = json.loads(base_path.read_text(encoding="utf-8"))
        payload["summary"]["area"]["total"] = 999.0
        _write_json(base_path, payload)
    else:
        state = json.loads(
            (tmp_path / ".ucagent" / "design_with_ppa" / "state.json").read_text(
                encoding="utf-8"
            )
        )
        snapshot_source = (
            tmp_path / state["best_snapshot"] / "output" / "rtl" / "dut.v"
        )
        snapshot_source.write_text("module damaged; endmodule\n", encoding="ascii")

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "ppa_iteration_rtl_invalid"




def test_best_version_finalization_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated finalization of unchanged evidence must not create a history commit."""

    candidate, _ = _prepare_iteration_workspace(tmp_path, iterations=0)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    passed, result = candidate.do_check()
    assert passed is True, result
    history_calls: list[str] = []
    base_history_check = candidate.stage.hist_has_commit
    final_commit = "9" * 40
    candidate.stage.hist_snapshot = lambda message: (
        history_calls.append(message) or final_commit
    )
    candidate.stage.hist_has_commit = lambda commit: (
        commit == final_commit or base_history_check(commit)
    )
    finalizer = PPABestVersionChecker(
        ledger_file="output/dut_optimization_ledger.yaml",
        final_report_file="output/dut_final_ppa_report.json",
        cfg=candidate.cfg,
    ).set_workspace(str(tmp_path))
    finalizer.stage = candidate.stage

    first_passed, first_result = finalizer.do_check()
    second_passed, second_result = finalizer.do_check()

    assert first_passed is True, first_result
    assert second_passed is True, second_result
    assert len(history_calls) == 1
    assert first_result == second_result




@pytest.mark.parametrize("value", [True, -1, 1001, 1.5, "5", "", None])
def test_optimization_limit_is_rejected_during_checker_construction(value: object) -> None:
    """Invalid candidate limits must fail before any workspace scan or stage work."""

    kwargs = {
        "test_dir": "output/tests",
        "functional_test_glob": "output/tests/test_dut_*.py",
        "performance_contract_file": "output/performance.yaml",
        "performance_manifest_file": "output/manifest.json",
        "ppa_report_file": "output/current.json",
        "rtl_backend_manifest_file": ".ucagent/design_with_ppa/rtl_backend.json",
        "ledger_file": "output/ledger.yaml",
        "base_report_file": "output/base.json",
        "iteration_report_dir": "output/iterations",
        "timeout": 10,
        "cfg": _config(iterations=value),
    }
    with pytest.raises(ValueError, match="min_optimization_iterations"):
        PPAIterationChecker(**kwargs)




@pytest.mark.parametrize("value", [True, 0, -1, 1001, 1.5, "3", "", None])
def test_no_improvement_patience_is_rejected_during_checker_construction(
    value: object,
) -> None:
    """Patience must be a bounded positive integer before workspace access."""

    kwargs = {
        "test_dir": "output/tests",
        "functional_test_glob": "output/tests/test_dut_*.py",
        "performance_contract_file": "output/performance.yaml",
        "performance_manifest_file": "output/manifest.json",
        "ppa_report_file": "output/current.json",
        "rtl_backend_manifest_file": ".ucagent/design_with_ppa/rtl_backend.json",
        "ledger_file": "output/ledger.yaml",
        "base_report_file": "output/base.json",
        "iteration_report_dir": "output/iterations",
        "timeout": 10,
        "cfg": _config(iterations=5, patience=value),
    }
    with pytest.raises(ValueError, match="no_improvement_patience"):
        PPAIterationChecker(**kwargs)




def test_minimum_optimization_limit_cannot_exceed_maximum() -> None:
    """The minimum candidate count must fit inside the safety ceiling."""

    with pytest.raises(ValueError, match="must not exceed"):
        PPAIterationChecker(
            test_dir="output/tests",
            functional_test_glob="output/tests/test_dut_*.py",
            performance_contract_file="output/performance.yaml",
            performance_manifest_file="output/manifest.json",
            ppa_report_file="output/current.json",
            rtl_backend_manifest_file=".ucagent/design_with_ppa/rtl_backend.json",
            ledger_file="output/ledger.yaml",
            base_report_file="output/base.json",
            iteration_report_dir="output/iterations",
            timeout=10,
            cfg=_config(iterations=5, max_iterations=4),
        )




@pytest.mark.parametrize(
    "value",
    [True, 3, ["performance", "area", "timing", "latency"], ["Area"], "area,,", ["area", "area"]],
)
def test_no_regression_scope_is_rejected_during_checker_construction(
    value: object,
) -> None:
    """Invalid no-regression categories must fail before workspace access."""

    with pytest.raises(ValueError, match="no_regression_metrics"):
        PPAIterationChecker(
            test_dir="output/tests",
            functional_test_glob="output/tests/test_dut_*.py",
            performance_contract_file="output/performance.yaml",
            performance_manifest_file="output/manifest.json",
            ppa_report_file="output/current.json",
            rtl_backend_manifest_file=".ucagent/design_with_ppa/rtl_backend.json",
            ledger_file="output/ledger.yaml",
            base_report_file="output/base.json",
            iteration_report_dir="output/iterations",
            timeout=10,
            cfg=_config(iterations=5, no_regression=value),
        )




@pytest.mark.parametrize(
    "value",
    [
        True,
        3,
        ["timing"],
        {"performance": 1.0},
        {"latency": 2.0},
        {"timing": -0.5},
        {"timing": "2"},
        {"timing": None},
        {"timing": float("nan")},
    ],
)
def test_score_weights_are_rejected_during_checker_construction(
    value: object,
) -> None:
    """Invalid selection-score weights must fail before workspace access."""

    with pytest.raises(ValueError, match="score_weights"):
        PPAIterationChecker(
            test_dir="output/tests",
            functional_test_glob="output/tests/test_dut_*.py",
            performance_contract_file="output/performance.yaml",
            performance_manifest_file="output/manifest.json",
            ppa_report_file="output/current.json",
            rtl_backend_manifest_file=".ucagent/design_with_ppa/rtl_backend.json",
            ledger_file="output/ledger.yaml",
            base_report_file="output/base.json",
            iteration_report_dir="output/iterations",
            timeout=10,
            cfg=_config(iterations=5, score_weights=value),
        )




def test_ppa_selection_score_applies_configured_weights() -> None:
    """Score weights exponentiate their dimension and zero removes it."""

    base = {
        "ppa.area.total": {"value": 100.0, "unit": "um2", "direction": "min"},
        "ppa.power.total_w": {"value": 10.0, "unit": "W", "direction": "min"},
        "ppa.timing.maximum_frequency_hz": {
            "value": 100.0,
            "unit": "Hz",
            "direction": "max",
        },
    }
    current = {
        "ppa.area.total": {"value": 50.0, "unit": "um2", "direction": "min"},
        "ppa.power.total_w": {"value": 10.0, "unit": "W", "direction": "min"},
        "ppa.timing.maximum_frequency_hz": {
            "value": 200.0,
            "unit": "Hz",
            "direction": "max",
        },
    }

    default = _ppa_selection_score(base, current)
    assert default["value"] == 4.0
    assert default["formula"] == (
        "timing_efficiency * area_efficiency * power_efficiency"
    )
    assert default["weights"] == {"timing": 1.0, "area": 1.0, "power": 1.0}

    weighted = _ppa_selection_score(
        base, current, weights={"timing": 2.0, "area": 1.0, "power": 1.0}
    )
    assert weighted["value"] == 8.0
    assert weighted["formula"] == (
        "timing_efficiency^2 * area_efficiency * power_efficiency"
    )
    assert weighted["components"]["timing"]["weight"] == 2.0

    focused = _ppa_selection_score(
        base, current, weights={"timing": 1.0, "area": 0.0, "power": 0.0}
    )
    assert focused["value"] == 2.0
    assert focused["formula"] == (
        "timing_efficiency * area_efficiency^0 * power_efficiency^0"
    )

    with pytest.raises(ValueError, match="weights"):
        _ppa_selection_score(base, current, weights={"timing": 1.0})




def test_score_weights_are_persisted_and_used_by_candidate_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Configured weights flow into ledger records and template data."""

    checker, base_id = _prepare_iteration_workspace(
        tmp_path,
        iterations=1,
        max_iterations=1,
        score_weights={"timing": 1.0, "area": 2.0, "power": 1.0},
    )
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    passed, _ = checker.do_check()
    assert passed is False
    _write_candidate_report(tmp_path, base_id, area=9.0)
    passed, result = checker.do_check()
    assert passed is True
    assert result["ppa_score"]["weights"] == {
        "timing": 1.0,
        "area": 2.0,
        "power": 1.0,
    }
    assert result["ppa_score"]["value"] == pytest.approx((10.0 / 9.0) ** 2)
    assert checker.get_template_data()["PPA_SCORE_WEIGHTS"] == (
        "timing=1, area=2, power=1"
    )
    ledger = yaml.safe_load(
        (tmp_path / "output" / "dut_optimization_ledger.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert ledger["score_weights"] == {
        "timing": 1.0,
        "area": 2.0,
        "power": 1.0,
    }
    assert ledger["records"][-1]["score_weights"] == {
        "timing": 1.0,
        "area": 2.0,
        "power": 1.0,
    }




def test_score_weights_change_requires_new_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing selection-score weights after base recording invalidates ranking."""

    checker, _ = _prepare_iteration_workspace(tmp_path, iterations=2)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    passed, result = checker.do_check()
    assert passed is False
    assert result["error_code"] == "ppa_candidate_required"
    restarted = PPACandidateOptimizationChecker(
        test_dir=checker.test_dir,
        functional_test_glob=checker.functional_test_glob,
        performance_contract_file=checker.performance_contract_file,
        performance_manifest_file=checker.performance_manifest_file,
        ppa_report_file=checker.ppa_report_file,
        rtl_backend_manifest_file=checker.rtl_backend_manifest_file,
        ledger_file=checker.ledger_file,
        base_report_file=checker.base_report_file,
        iteration_report_dir=checker.iteration_report_dir,
        timeout=checker.timeout,
        cfg=_config(iterations=2, score_weights={"timing": 2.0}),
        rel_tolerance=checker.rel_tolerance,
        abs_tolerance=checker.abs_tolerance,
        ret_std_out=checker.ret_std_out,
        ret_std_error=checker.ret_std_error,
    ).set_workspace(str(tmp_path))
    restarted.stage = checker.stage
    restarted.on_init()

    passed, result = restarted.do_check()

    assert passed is False
    assert result["error_code"] == "ppa_score_weights_changed"
    assert result["observed"]["score_weights"] == {
        "timing": 1.0,
        "area": 1.0,
        "power": 1.0,
    }
    assert result["expected"]["score_weights"] == {
        "timing": 2.0,
        "area": 1.0,
        "power": 1.0,
    }




def test_unprotected_category_regression_is_accepted_within_configured_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A metric outside no_regression_metrics may regress while another improves."""

    checker, base_id = _prepare_iteration_workspace(
        tmp_path,
        iterations=1,
        max_iterations=1,
        no_regression="performance,timing,power",
    )
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    passed, result = checker.do_check()
    assert passed is False
    assert result["error_code"] == "ppa_candidate_required"
    _write_candidate_report(tmp_path, base_id, area=11.0, power=0.0005)
    passed, result = checker.do_check()
    assert passed is True
    assert result["accepted"] is True
    assert result["stop_reason"] == "max_iterations_reached"
    assert result["accepted_iteration"] == 1
    ledger = yaml.safe_load(
        (tmp_path / "output" / "dut_optimization_ledger.yaml").read_text(
            encoding="utf-8"
        )
    )
    candidate = ledger["records"][-1]
    assert candidate["no_regression_metrics"] == ["performance", "timing", "power"]
    assert candidate["regressed_metrics"] == ["ppa.area.total"]
    assert (
        candidate["metric_changes_to_previous"]["ppa.area.total"]["assessment"]
        == "regressed"
    )
    assert (
        candidate["metric_changes_to_previous"]["ppa.power.total_w"]["assessment"]
        == "improved"
    )
    assert checker.get_template_data()["PPA_NO_REGRESSION_METRICS"] == (
        "performance,timing,power"
    )




def test_empty_no_regression_scope_accepts_any_strict_improvement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With every category unprotected, one improvement suffices for acceptance."""

    checker, base_id = _prepare_iteration_workspace(
        tmp_path,
        iterations=1,
        max_iterations=1,
        no_regression=[],
    )
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    checker.do_check()
    _write_candidate_report(tmp_path, base_id, area=9.0, power=0.002)
    passed, result = checker.do_check()
    assert passed is True
    assert result["accepted"] is True
    ledger = yaml.safe_load(
        (tmp_path / "output" / "dut_optimization_ledger.yaml").read_text(
            encoding="utf-8"
        )
    )
    candidate = ledger["records"][-1]
    assert candidate["no_regression_metrics"] == []
    assert candidate["regressed_metrics"] == ["ppa.power.total_w"]
    assert ledger["best_selection_reason"] == (
        "selected from every complete accepted version by Pareto dominance "
        "over the protected no-regression metrics (none)"
    )




def test_no_regression_scope_change_requires_new_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing the acceptance scope after base recording invalidates comparisons."""

    checker, _ = _prepare_iteration_workspace(tmp_path, iterations=2)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    passed, result = checker.do_check()
    assert passed is False
    assert result["error_code"] == "ppa_candidate_required"
    restarted = PPACandidateOptimizationChecker(
        test_dir=checker.test_dir,
        functional_test_glob=checker.functional_test_glob,
        performance_contract_file=checker.performance_contract_file,
        performance_manifest_file=checker.performance_manifest_file,
        ppa_report_file=checker.ppa_report_file,
        rtl_backend_manifest_file=checker.rtl_backend_manifest_file,
        ledger_file=checker.ledger_file,
        base_report_file=checker.base_report_file,
        iteration_report_dir=checker.iteration_report_dir,
        timeout=checker.timeout,
        cfg=_config(iterations=2, no_regression="performance,area"),
        rel_tolerance=checker.rel_tolerance,
        abs_tolerance=checker.abs_tolerance,
        ret_std_out=checker.ret_std_out,
        ret_std_error=checker.ret_std_error,
    ).set_workspace(str(tmp_path))
    restarted.stage = checker.stage
    restarted.on_init()

    passed, result = restarted.do_check()

    assert passed is False
    assert result["error_code"] == "ppa_no_regression_scope_changed"
    assert result["observed"]["no_regression_metrics"] == [
        "performance",
        "timing",
    ]
    assert result["expected"]["no_regression_metrics"] == ["performance", "area"]




def test_base_only_persists_bound_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N=0 must deliver base PPA and reject later public-ledger tampering."""

    checker, base_id = _prepare_iteration_workspace(tmp_path, iterations=0)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    passed, result = checker.do_check()
    assert passed is True
    assert result["stop_reason"] == "base_only"
    assert result["accepted_iteration"] == 0
    assert "report_id" not in result
    state = json.loads(
        (tmp_path / ".ucagent" / "design_with_ppa" / "state.json").read_text(
            encoding="utf-8"
        )
    )
    ledger = tmp_path / "output" / "dut_optimization_ledger.yaml"
    ledger_data = yaml.safe_load(ledger.read_text(encoding="utf-8"))
    assert ledger_data["records"][0]["ppa_metrics"]["ppa.area.total"][
        "value"
    ] == 10.0
    assert state["ledger_sha256"] == sha256_file(ledger)
    ledger.write_text(ledger.read_text(encoding="utf-8") + "forged: true\n", encoding="utf-8")
    passed, result = checker.do_check()
    assert passed is False
    assert result["error_code"] == "ppa_iteration_state_invalid"




def test_pareto_candidate_is_accepted_at_iteration_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A comparable area improvement with no regression must become final accepted RTL."""

    checker, base_id = _prepare_iteration_workspace(
        tmp_path, iterations=1, max_iterations=1
    )
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    passed, result = checker.do_check()
    assert passed is False
    assert result["error_code"] == "ppa_candidate_required"
    candidate_id = _write_candidate_report(tmp_path, base_id, area=9.0)
    passed, result = checker.do_check()
    assert passed is True
    assert result["accepted"] is True
    assert result["stop_reason"] == "max_iterations_reached"
    assert result["accepted_iteration"] == 1
    assert result["analysis"]["area"]["total"] == 9.0
    assert "accepted_report_id" not in result
    ledger = yaml.safe_load(
        (tmp_path / "output" / "dut_optimization_ledger.yaml").read_text(
            encoding="utf-8"
        )
    )
    candidate = ledger["records"][-1]
    assert candidate["metric_changes_to_previous"]["ppa.area.total"] == {
        "baseline": 10.0,
        "current": 9.0,
        "delta": -1.0,
        "percent_change": -10.0,
        "unit": "library_area",
        "direction": "min",
        "assessment": "improved",
    }
    assert candidate["metric_changes_to_base"] == candidate[
        "metric_changes_to_previous"
    ]




def test_current_tips_projection_advances_without_checker_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Base and accepted candidate transitions must immediately update CurrentTips."""

    checker, base_id = _prepare_iteration_workspace(tmp_path, iterations=2)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    assert checker.get_template_data() == {
        "PPA_MIN_OPTIMIZATION_ITERATIONS": 2,
        "PPA_MAX_OPTIMIZATION_ITERATIONS": 1000,
        "PPA_CANDIDATE_COUNT": 0,
        "PPA_REMAINING_MIN_ITERATIONS": 2,
        "PPA_NO_IMPROVEMENT_PATIENCE": 3,
        "PPA_NO_REGRESSION_METRICS": "performance,timing",
        "PPA_SCORE_WEIGHTS": "timing=1, area=1, power=1",
        "PPA_NO_IMPROVEMENT_COUNT": 0,
        "PPA_REMAINING_NO_IMPROVEMENT": 3,
        "PPA_ACCEPTED_ITERATION": 0,
        "PPA_BEST_ITERATION": 0,
        "PPA_BEST_REPORT_ID": base_id,
        "PPA_NEXT_CANDIDATE": 1,
    }

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "ppa_candidate_required"
    after_base = checker.get_template_data()
    assert after_base["PPA_NEXT_CANDIDATE"] == 1
    assert after_base["PPA_CANDIDATE_COUNT"] == 0
    assert after_base["PPA_ACCEPTED_ITERATION"] == 0

    candidate_id = _write_candidate_report(
        tmp_path, base_id, area=9.0, candidate_index=1
    )
    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "ppa_next_candidate_required"
    after_candidate = checker.get_template_data()
    assert after_candidate["PPA_NEXT_CANDIDATE"] == 2
    assert after_candidate["PPA_CANDIDATE_COUNT"] == 1
    assert after_candidate["PPA_ACCEPTED_ITERATION"] == 1
    assert "PPA_ACCEPTED_REPORT_ID" not in after_candidate

    resumed = PPAIterationChecker(
        test_dir="output/tests",
        functional_test_glob="output/tests/test_dut_*.py",
        performance_contract_file="output/dut_performance_contract.yaml",
        performance_manifest_file="output/performance/performance_manifest.json",
        ppa_report_file="output/reports/ppa/current.json",
        rtl_backend_manifest_file=".ucagent/design_with_ppa/rtl_backend_manifest.json",
        ledger_file="output/dut_optimization_ledger.yaml",
        base_report_file="output/reports/ppa/base.json",
        iteration_report_dir="output/reports/ppa/iterations",
        timeout=30,
        cfg=_config(iterations=2),
    ).set_workspace(str(tmp_path))
    resumed.stage = checker.stage
    resumed.on_init()
    assert resumed.get_template_data() == after_candidate




def test_replayed_hypothesis_cannot_consume_the_next_candidate_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A processed hypothesis must be rewritten for the exact next iteration."""

    checker, base_id = _prepare_iteration_workspace(tmp_path, iterations=2)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    checker.do_check()
    first_id = _write_candidate_report(
        tmp_path, base_id, area=9.0, candidate_index=1
    )
    passed, result = checker.do_check()
    assert passed is False
    assert result["error_code"] == "ppa_next_candidate_required"

    _write_candidate_report(
        tmp_path, first_id, area=8.0, candidate_index=2
    )
    hypothesis = tmp_path / "output" / "reports" / "ppa" / "candidate_hypothesis.yaml"
    stale = yaml.safe_load(hypothesis.read_text(encoding="utf-8"))
    stale["iteration"] = 1
    _write_yaml(hypothesis, stale)

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "ppa_candidate_hypothesis_invalid"
    state = json.loads(
        (tmp_path / ".ucagent" / "design_with_ppa" / "state.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["candidate_count"] == 1
    assert checker.get_template_data()["PPA_NEXT_CANDIDATE"] == 2




def test_no_improvement_patience_requires_three_consecutive_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plateau may stop only after the configured consecutive rejection count."""

    checker, base_id = _prepare_iteration_workspace(tmp_path, iterations=1)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    checker.do_check()
    original = (tmp_path / "output" / "rtl" / "dut.v").read_text(encoding="ascii")
    for candidate_index in range(1, 4):
        _write_candidate_report(
            tmp_path,
            base_id,
            area=10.0,
            candidate_index=candidate_index,
        )
        passed, result = checker.do_check()
        if candidate_index < 3:
            assert passed is False
            assert result["error_code"] == "ppa_next_candidate_required"
            assert result["observed"]["accepted"] is False
        else:
            assert passed is True
            assert result["accepted"] is False
            assert result["rejection_reason"] == "no_pareto_improvement"
            assert result["stop_reason"] == "no_pareto_improvement"
            assert result["no_improvement_count"] == 3
        restored = (tmp_path / "output" / "rtl" / "dut.v").read_text(
            encoding="ascii"
        )
        assert restored == original




def test_regressing_candidates_respect_minimum_and_patience(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Protected regressions restore RTL and cannot stop before patience is met."""

    checker, base_id = _prepare_iteration_workspace(tmp_path, iterations=3)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    checker.do_check()
    original = (tmp_path / "output" / "rtl" / "dut.v").read_text(encoding="ascii")
    for candidate_index in range(1, 4):
        # Area improves but the default-protected timing metric regresses, so
        # every candidate is a protected regression and must be restored.
        _write_candidate_report(
            tmp_path,
            base_id,
            area=9.0,
            delay=1.1,
            candidate_index=candidate_index,
        )
        passed, result = checker.do_check()
        if candidate_index < 3:
            assert passed is False
            assert result["error_code"] == "ppa_next_candidate_required"
        else:
            assert passed is True
            assert result["accepted"] is False
            assert result["rejection_reason"] == "pareto_regression"
            assert result["stop_reason"] == "no_pareto_improvement"
        assert (tmp_path / "output" / "rtl" / "dut.v").read_text(
            encoding="ascii"
        ) == original




def test_improvement_beyond_minimum_resets_patience_and_selects_best(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The search must continue past its minimum and reset the plateau streak."""

    checker, base_id = _prepare_iteration_workspace(
        tmp_path,
        iterations=1,
        max_iterations=10,
        patience=3,
    )
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    checker.do_check()

    first_id = _write_candidate_report(
        tmp_path, base_id, area=9.0, candidate_index=1
    )
    passed, first = checker.do_check()
    assert passed is False
    assert first["observed"]["accepted"] is True
    assert first["observed"]["metric_changes_to_best"]["ppa.area.total"][
        "assessment"
    ] == "improved"
    assert first["observed"]["ppa_score"]["metric_id"] == "ppa.selection_score"
    assert first["observed"]["ppa_score"]["value"] == pytest.approx(10.0 / 9.0)
    assert first["observed"]["best_ppa_score"]["value"] == pytest.approx(10.0 / 9.0)

    _write_candidate_report(tmp_path, first_id, area=9.0, candidate_index=2)
    passed, plateau = checker.do_check()
    assert passed is False
    assert plateau["observed"]["accepted"] is False
    assert checker.get_template_data()["PPA_NO_IMPROVEMENT_COUNT"] == 1

    best_id = _write_candidate_report(
        tmp_path, first_id, area=8.0, candidate_index=3
    )
    passed, improved = checker.do_check()
    assert passed is False
    assert improved["observed"]["accepted"] is True
    assert improved["observed"]["metric_changes_to_best"]["ppa.area.total"][
        "assessment"
    ] == "improved"
    assert checker.get_template_data()["PPA_NO_IMPROVEMENT_COUNT"] == 0

    for candidate_index in range(4, 7):
        _write_candidate_report(
            tmp_path,
            best_id,
            area=8.0,
            candidate_index=candidate_index,
        )
        passed, result = checker.do_check()
    assert passed is True
    assert result["stop_reason"] == "no_pareto_improvement"
    assert result["best_iteration"] == 3
    assert result["no_improvement_count"] == 3
    state = json.loads(
        (tmp_path / ".ucagent" / "design_with_ppa" / "state.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["candidate_count"] == 6
    assert state["best_iteration"] == 3
    assert state["best_report_id"] == best_id
    assert state["accepted_iteration"] == 3
    assert state["no_improvement_count"] == 3




def test_ppa_progress_survives_completed_stage_reconstruction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Persisted stage metadata must prevent a completed loop from showing 0/min."""

    checker, base_id = _prepare_iteration_workspace(
        tmp_path, iterations=1, max_iterations=1
    )
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    checker.do_check()
    _write_candidate_report(tmp_path, base_id, area=9.0, candidate_index=1)
    passed, result = checker.do_check()
    assert passed is True, result
    assert checker.stage.meta_data["design_with_ppa_progress"]["candidate_count"] == 1

    checker._cached_candidate_count = 0
    checker._cached_status = "not_initialized"

    template_data = checker.get_template_data()
    assert template_data["PPA_CANDIDATE_COUNT"] == 1
    assert template_data["PPA_REMAINING_MIN_ITERATIONS"] == 0
    assert template_data["PPA_BEST_ITERATION"] == 1
    assert template_data["PPA_NEXT_CANDIDATE"] is None




@pytest.mark.parametrize(
    ("timing_id", "direction", "base_timing", "current_timing"),
    [
        ("ppa.timing.maximum_frequency_hz", "max", 100.0, 200.0),
        ("ppa.timing.critical_path_delay_ns", "min", 10.0, 5.0),
    ],
)
def test_ppa_selection_score_uses_one_equivalent_timing_metric(
    timing_id: str,
    direction: str,
    base_timing: float,
    current_timing: float,
) -> None:
    """Frequency and inverse delay must produce the same dimensionless PPA score."""

    base = {
        "ppa.area.total": {"value": 100.0, "unit": "um2", "direction": "min"},
        "ppa.power.total_w": {"value": 10.0, "unit": "W", "direction": "min"},
        timing_id: {
            "value": base_timing,
            "unit": "Hz" if direction == "max" else "ns",
            "direction": direction,
        },
    }
    current = {
        "ppa.area.total": {"value": 50.0, "unit": "um2", "direction": "min"},
        "ppa.power.total_w": {"value": 5.0, "unit": "W", "direction": "min"},
        timing_id: {
            "value": current_timing,
            "unit": "Hz" if direction == "max" else "ns",
            "direction": direction,
        },
    }

    score = _ppa_selection_score(base, current)

    assert score["status"] == "available"
    assert score["value"] == 8.0
    assert score["components"]["timing"]["efficiency_ratio"] == 2.0




def test_best_selector_rejects_incomparable_accepted_frontier() -> None:
    """Final selection must not invent a weighted score for a Pareto tie."""

    def record(iteration: int, area: float, frequency: float) -> dict[str, Any]:
        """Return one complete accepted record for the selector contract."""

        return {
            "iteration": iteration,
            "accepted": True,
            "functional_regression": {"pass": True},
            "ppa_metrics": {
                "area": {"value": area, "unit": "um2", "direction": "min"},
                "frequency": {
                    "value": frequency,
                    "unit": "Hz",
                    "direction": "max",
                },
            },
            "performance_metrics": {
                "throughput": {
                    "value": 1.0,
                    "unit": "transaction/cycle",
                    "direction": "max",
                }
            },
        }

    with pytest.raises(ValueError, match="incomparable Pareto frontier"):
        select_best_accepted_record(
            [record(0, 10.0, 100.0), record(1, 9.0, 90.0)]
        )




def test_best_selector_uses_newest_equivalent_accepted_record() -> None:
    """Equivalent accepted metrics choose the newest reproducible version."""

    records = [
        {
            "iteration": iteration,
            "accepted": True,
            "functional_regression": {"pass": True},
            "ppa_metrics": {
                "area": {"value": 10.0, "unit": "um2", "direction": "min"}
            },
            "performance_metrics": {
                "latency": {"value": 2.0, "unit": "cycle", "direction": "min"}
            },
        }
        for iteration in (0, 1)
    ]

    assert select_best_accepted_record(records)["iteration"] == 1




def test_best_selection_scopes_pareto_comparison_to_protected_categories() -> None:
    """Category scoping resolves trade-offs the full metric set cannot order."""

    def record(iteration: int, area: float, delay: float) -> dict[str, Any]:
        """Return one complete accepted record with canonical primary ids."""

        return {
            "iteration": iteration,
            "accepted": True,
            "functional_regression": {"pass": True},
            "ppa_metrics": {
                "ppa.area.total": {
                    "value": area,
                    "unit": "library_area",
                    "direction": "min",
                },
                "ppa.timing.critical_path_delay_ns": {
                    "value": delay,
                    "unit": "ns",
                    "direction": "min",
                },
                "ppa.power.total_w": {
                    "value": 0.001,
                    "unit": "W",
                    "direction": "min",
                },
            },
            "performance_metrics": {
                "latency": {"value": 2.0, "unit": "cycle", "direction": "min"}
            },
        }

    records = [record(0, 10.0, 1.0), record(1, 12.0, 0.9)]
    with pytest.raises(ValueError, match="incomparable Pareto frontier"):
        select_best_accepted_record(records)
    assert (
        select_best_accepted_record(records, categories=("timing",))["iteration"]
        == 1
    )
    # Scoping away both differing metrics leaves an equal protected vector,
    # which the selector resolves deterministically to the newest iteration.
    assert select_best_accepted_record(
        records, categories=("performance", "power")
    )["iteration"] == 1
    assert select_best_accepted_record(records, categories=("performance",))[
        "iteration"
    ] == 1




def test_changed_test_contract_does_not_consume_candidate_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing handwritten tests after base must invalidate evidence, not a candidate."""

    checker, _ = _prepare_iteration_workspace(tmp_path, iterations=2)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    checker.do_check()
    test_file = tmp_path / "output" / "tests" / "test_dut_functional.py"
    test_file.write_text(
        "def test_dut_functional():\n    assert 1 == 1\n", encoding="utf-8"
    )
    passed, result = checker.do_check()
    assert passed is False
    assert result["error_code"] == "ppa_test_contract_changed"
    state = json.loads(
        (tmp_path / ".ucagent" / "design_with_ppa" / "state.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["candidate_count"] == 0




def test_changed_ppa_configuration_invalidates_recorded_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scope or timing-policy change must require a new base before candidates."""

    checker, _ = _prepare_iteration_workspace(tmp_path, iterations=2)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    passed, result = checker.do_check()
    assert passed is False
    assert result["error_code"] == "ppa_candidate_required"
    checker.cfg.un_freeze()
    checker.cfg.set_value("design_with_ppa.ppa.waveform_scope", "tb.changed")

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "ppa_configuration_changed"
    state = json.loads(
        (tmp_path / ".ucagent" / "design_with_ppa" / "state.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["candidate_count"] == 0




def test_incomparable_candidate_does_not_consume_candidate_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A changed Liberty identity is an evidence error, not a design rejection."""

    checker, base_id = _prepare_iteration_workspace(tmp_path, iterations=2)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    checker.do_check()
    candidate_id = _write_candidate_report(tmp_path, base_id, area=9.0)
    current_path = tmp_path / "output" / "reports" / "ppa" / "current.json"
    report = json.loads(current_path.read_text(encoding="utf-8"))
    report["provenance"]["liberty_sha256"] = "f" * 64
    _write_json(current_path, report)
    cache_path = tmp_path / ".ucagent" / "ppa_reports" / f"{candidate_id}.json"
    _write_json(cache_path, report)
    index_path = tmp_path / ".ucagent" / "ppa_reports" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    next(row for row in index["reports"] if row["report_id"] == candidate_id)[
        "sha256"
    ] = sha256_file(cache_path)
    _write_json(index_path, index)

    passed, result = checker.do_check()
    assert passed is False
    assert result["error_code"] == "ppa_candidate_not_comparable"
    state = json.loads(
        (tmp_path / ".ucagent" / "design_with_ppa" / "state.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["candidate_count"] == 0
