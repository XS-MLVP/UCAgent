"""Focused DesignWithPPA workflow tests: final delivery."""

from __future__ import annotations

import helpers  # noqa: F401  (runs the plugin sys.path bootstrap first)

from helpers import (
    PLUGIN_SOURCE,
    _documentation_sync_fixture,
    _prepare_iteration_workspace,
    _template_context,
    _write_candidate_report,
    _write_json,
    _write_yaml,
)

import json
from pathlib import Path
import re
import shutil
import subprocess
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
from ucagent.util.functions import render_template_dir




def _write_final_summary(workspace: Path) -> None:
    """Write the public final summary from the verified optimization outcome."""

    state = json.loads(
        (workspace / ".ucagent" / "design_with_ppa" / "state.json").read_text(
            encoding="utf-8"
        )
    )
    content = (
        "\n# dut design summary\n\n"
        "## Machine summary\n\n"
        "```yaml\n"
        "design_summary:\n"
        '  schema_version: "1.2"\n'
        "  dut: dut\n"
        "  top_module: dut\n"
        f"  accepted_iteration: {state['accepted_iteration']}\n"
        f"  stop_reason: {state['stop_reason']}\n"
        f"  min_optimization_iterations: {state['min_optimization_iterations']}\n"
        f"  max_optimization_iterations: {state['max_optimization_iterations']}\n"
        f"  no_improvement_patience: {state['no_improvement_patience']}\n"
        f"  no_regression_metrics: {json.dumps(state['no_regression_metrics'])}\n"
        f"  no_improvement_count: {state['no_improvement_count']}\n"
        f"  best_iteration: {state['best_iteration']}\n"
        f"  best_report_id: {state['best_report_id']}\n"
        "  performance_curve_json: output/dut_performance_curve.json\n"
        "  final_ppa_report: output/dut_final_ppa_report.json\n"
        "```\n"
        "\n## Performance curve\n\n"
        "See the performance curve JSON and result dashboard.\n"
        "\n## Result dashboard\n\n"
        "[Open dashboard](dut_ppa_dashboard.html)\n"
    )
    (workspace / "output" / "dut_design_summary.md").write_text(
        content, encoding="utf-8"
    )




def _final_delivery_checker(
    workspace: Path,
    iteration_checker: PPACandidateOptimizationChecker,
    *,
    iterations: int,
    dashboard: bool = False,
) -> DesignFinalDeliveryChecker:
    """Finalize the best version and build the canonical final delivery gate."""

    finalizer = PPABestVersionChecker(
        ledger_file="output/dut_optimization_ledger.yaml",
        final_report_file="output/dut_final_ppa_report.json",
        cfg=iteration_checker.cfg,
    ).set_workspace(str(workspace))
    finalizer.stage = iteration_checker.stage
    passed, result = finalizer.do_check()
    assert passed is True, result

    checker = DesignFinalDeliveryChecker(
        ledger_file="output/dut_optimization_ledger.yaml",
        final_report_file="output/dut_final_ppa_report.json",
        design_summary_file="output/dut_design_summary.md",
        performance_curve_json_file="output/dut_performance_curve.json",
        dashboard_file="output/dut_ppa_dashboard.html" if dashboard else None,
        cfg=iteration_checker.cfg,
    ).set_workspace(str(workspace))
    checker.stage = iteration_checker.stage
    return checker




def test_design_documentation_sync_writes_final_rtl_identity_and_manifest(
    tmp_path: Path,
) -> None:
    """The final documentation gate derives synchronization metadata from real evidence."""

    workspace, cfg, documents = _documentation_sync_fixture(tmp_path)
    checker = DesignDocumentationSyncChecker(
        documentation_files=[path.relative_to(workspace).as_posix() for path in documents],
        rtl_manifest_file=".ucagent/design_with_ppa/rtl_backend_manifest.json",
        final_validation_file="output/reports/dut_final_all_tc_validation.json",
        sync_manifest_file="output/reports/dut_documentation_sync.json",
        cfg=cfg,
    ).set_workspace(str(workspace))

    passed, result = checker.do_check()

    assert passed is True, result
    assert result["test_case_count"] == 2
    for document in documents:
        text = document.read_text(encoding="utf-8")
        assert "## Final RTL synchronization" in text
        assert "rtl_source_sha256:" in text
        assert "all_test_cases_passed: true" in text
        assert "status: pass" in text
    sync = json.loads(
        (workspace / "output" / "reports" / "dut_documentation_sync.json").read_text(
            encoding="utf-8"
        )
    )
    assert sync["status"] == "pass"
    assert len(sync["documents"]) == 5
    assert sync["rtl"]["source_files"][0]["path"] == "output/rtl/dut.v"




def test_design_documentation_sync_rejects_changed_final_rtl(
    tmp_path: Path,
) -> None:
    """A source change after the final receipt cannot be hidden by stale documents."""

    workspace, cfg, documents = _documentation_sync_fixture(tmp_path)
    checker = DesignDocumentationSyncChecker(
        documentation_files=[path.relative_to(workspace).as_posix() for path in documents],
        rtl_manifest_file=".ucagent/design_with_ppa/rtl_backend_manifest.json",
        final_validation_file="output/reports/dut_final_all_tc_validation.json",
        sync_manifest_file="output/reports/dut_documentation_sync.json",
        cfg=cfg,
    ).set_workspace(str(workspace))
    assert checker.do_check()[0] is True
    (workspace / "output" / "rtl" / "dut.v").write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n",
        encoding="utf-8",
    )

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "design_documentation_sync_invalid"




def test_design_documentation_sync_rejects_bug_analysis_documents(
    tmp_path: Path,
) -> None:
    """Pure design delivery must not retain verification Bug-analysis artifacts."""

    workspace, cfg, documents = _documentation_sync_fixture(tmp_path)
    unwanted = workspace / "output" / "dut_bug_analysis.md"
    unwanted.write_text("# no bugs\n", encoding="utf-8")
    checker = DesignDocumentationSyncChecker(
        documentation_files=[path.relative_to(workspace).as_posix() for path in documents],
        rtl_manifest_file=".ucagent/design_with_ppa/rtl_backend_manifest.json",
        final_validation_file="output/reports/dut_final_all_tc_validation.json",
        sync_manifest_file="output/reports/dut_documentation_sync.json",
        cfg=cfg,
    ).set_workspace(str(workspace))

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "design_documentation_sync_invalid"




def test_final_delivery_rejects_tampered_final_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Final delivery must reject a report that differs from immutable cache evidence."""

    checker, _ = _prepare_iteration_workspace(tmp_path, iterations=0)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    passed, _ = checker.do_check()
    assert passed is True
    _write_final_summary(tmp_path)
    final_checker = _final_delivery_checker(tmp_path, checker, iterations=0)
    passed, _ = final_checker.do_check()
    assert passed is True
    curve = json.loads(
        (tmp_path / "output" / "dut_performance_curve.json").read_text(
            encoding="utf-8"
        )
    )
    assert curve["accepted_iteration"] == 0
    assert [row["iteration"] for row in curve["iterations"]] == [0]
    assert [row["version"] for row in curve["iterations"]] == [0]
    assert "svg" not in curve
    final_path = tmp_path / "output" / "dut_final_ppa_report.json"
    final = json.loads(final_path.read_text(encoding="utf-8"))
    final["summary"]["area"]["total"] = 999.0
    _write_json(final_path, final)
    passed, result = final_checker.do_check()
    assert passed is False
    assert result["error_code"] == "design_final_delivery_invalid"
    assert result["error"] == (
        "The final PPA report no longer matches the verified best accepted version."
    )
    assert result["artifact"] == "output/dut_final_ppa_report.json"
    assert result["location"] == "ppa_result_artifacts"
    assert "Do not edit" in result["next_action"]
    assert "cache" not in json.dumps(result).lower()




def test_final_delivery_rejects_forged_history_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Final delivery must reject ledger commit IDs absent from stage history."""

    checker, _ = _prepare_iteration_workspace(tmp_path, iterations=0)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    passed, _ = checker.do_check()
    assert passed is True
    _write_final_summary(tmp_path)
    ledger_path = tmp_path / "output" / "dut_optimization_ledger.yaml"
    ledger = yaml.safe_load(ledger_path.read_text(encoding="utf-8"))
    ledger["records"][0]["internal_history_commit"] = "0" * 40
    _write_yaml(ledger_path, ledger)
    state_path = tmp_path / ".ucagent" / "design_with_ppa" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["ledger_sha256"] = sha256_file(ledger_path)
    _write_json(state_path, state)
    final_checker = _final_delivery_checker(tmp_path, checker, iterations=0)

    passed, result = final_checker.do_check()

    assert passed is False
    assert result["error_code"] == "design_final_delivery_invalid"
    assert result["error"] == (
        "The finalized optimization evidence cannot prove one contiguous, "
        "untampered best-version selection."
    )
    assert "Do not edit" in result["next_action"]
    assert "internal_history_commit" not in json.dumps(result).lower()




def test_final_delivery_allows_score_ranking_divergence_under_scoped_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scoped-acceptance best below the score maximum must still deliver."""

    checker, base_id = _prepare_iteration_workspace(
        tmp_path, iterations=1, max_iterations=1
    )
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    passed, _ = checker.do_check()
    assert passed is False
    # Timing (protected) improves while area and power (unprotected) regress,
    # so the candidate is accepted under the default performance+timing scope
    # while its multiplicative score drops below the base's 1.0.
    _write_candidate_report(
        tmp_path, base_id, area=20.0, power=0.002, delay=0.9
    )
    passed, result = checker.do_check()
    assert passed is True, result
    assert result["accepted"] is True
    assert result["ppa_score"]["value"] == pytest.approx(
        (1.0 / 0.9) * (10.0 / 20.0) * (0.001 / 0.002)
    )
    _write_final_summary(tmp_path)

    final_checker = _final_delivery_checker(tmp_path, checker, iterations=1)
    passed, result = final_checker.do_check()

    assert passed is True, result
    curve = json.loads(
        (tmp_path / "output" / "dut_performance_curve.json").read_text(
            encoding="utf-8"
        )
    )
    assert curve["best_iteration"] == 1
    assert [row["best"] for row in curve["iterations"]] == [False, True]
    assert curve["selection_metric"]["best_iteration"] == 0
    assert curve["selection_metric"]["best_value"] == 1.0
    assert "diagnostic ranking only" in curve["selection_metric"][
        "selection_policy"
    ]




def test_final_delivery_directs_modified_rtl_to_best_version_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Authored RTL left different from the best version must point at stage 29."""

    checker, _ = _prepare_iteration_workspace(tmp_path, iterations=0)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    passed, _ = checker.do_check()
    assert passed is True
    _write_final_summary(tmp_path)
    final_checker = _final_delivery_checker(tmp_path, checker, iterations=0)
    passed, _ = final_checker.do_check()
    assert passed is True
    (tmp_path / "output" / "rtl" / "dut.v").write_text(
        "module dut(input a, output y); assign y = ~a; endmodule\n",
        encoding="ascii",
    )

    passed, result = final_checker.do_check()

    assert passed is False
    assert result["error_code"] == "design_final_delivery_invalid"
    assert result["error"] == (
        "The authored RTL files on disk are not the finalized best accepted version."
    )
    assert result["observed"]["reason"] == (
        "final RTL file provenance differs from the last accepted record"
    )
    assert "ppa_best_version_finalization" in result["next_action"]
    assert "Do not hand-copy" in result["next_action"]




def test_final_delivery_curve_contains_accepted_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The generated curve must retain raw and normalized data for accepted versions."""

    checker, base_id = _prepare_iteration_workspace(
        tmp_path, iterations=1, max_iterations=1
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
    passed, _ = checker.do_check()
    assert passed is True
    _write_final_summary(tmp_path)

    final_checker = _final_delivery_checker(tmp_path, checker, iterations=1)
    passed, result = final_checker.do_check()

    assert passed is True, result
    curve = json.loads(
        (tmp_path / "output" / "dut_performance_curve.json").read_text(
            encoding="utf-8"
        )
    )
    assert curve["accepted_iteration"] == 1
    assert [row["accepted"] for row in curve["iterations"]] == [True, True]
    assert [row["version"] for row in curve["iterations"]] == [0, 1]
    area_series = next(
        row for row in curve["series"] if row["metric_id"] == "ppa.area.total"
    )
    assert [point["value"] for point in area_series["points"]] == [10.0, 9.0]
    assert [
        point["normalized_improvement_percent"] for point in area_series["points"]
    ] == [0.0, 10.0]
    assert curve["schema_version"] == "1.3"
    assert curve["selection_metric"]["metric_id"] == "ppa.selection_score"
    assert curve["selection_metric"]["weights"] == {
        "timing": 1.0,
        "area": 1.0,
        "power": 1.0,
    }
    assert curve["selection_metric"]["formula"] == (
        "timing_efficiency * area_efficiency * power_efficiency"
    )
    assert curve["no_regression_metrics"] == [
        "performance",
        "timing",
    ]
    assert curve["selection_metric"]["best_iteration"] == 1
    assert curve["selection_metric"]["best_value"] == pytest.approx(10.0 / 9.0)
    assert [
        point["eligible"] for point in curve["selection_metric"]["points"]
    ] == [True, True]




def test_final_delivery_curve_marks_rejected_candidate_and_zero_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rejected complete candidates stay visible and zero baselines remain finite JSON."""

    checker, base_id = _prepare_iteration_workspace(
        tmp_path,
        iterations=1,
        patience=1,
        base_area=0.0,
        no_regression=["performance", "area", "timing", "power"],
    )
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    checker.do_check()
    _write_candidate_report(tmp_path, base_id, area=1.0)
    passed, _ = checker.do_check()
    assert passed is True
    _write_final_summary(tmp_path)

    final_checker = _final_delivery_checker(tmp_path, checker, iterations=1)
    passed, result = final_checker.do_check()

    assert passed is True, result
    curve_path = tmp_path / "output" / "dut_performance_curve.json"
    curve_text = curve_path.read_text(encoding="utf-8")
    assert "NaN" not in curve_text
    assert "Infinity" not in curve_text
    curve = json.loads(curve_text)
    assert [row["accepted"] for row in curve["iterations"]] == [True, False]
    candidate_area = curve["iterations"][1]["metrics"]["ppa.area.total"]
    assert candidate_area["normalized_improvement_percent"] is None
    assert candidate_area["normalization_status"] == "zero_baseline"
    rejection = curve["iterations"][1]["rejection"]
    assert rejection["code"] == "pareto_regression"
    assert rejection["compared_to_iteration"] == 0
    assert rejection["evidence_status"] == "complete"
    assert rejection["metrics"] == [
        {
            "metric_id": "ppa.area.total",
            "assessment": "regressed",
            "previous_value": 0.0,
            "current_value": 1.0,
            "delta": 1.0,
            "percent_change": None,
            "unit": "library_area",
            "direction": "min",
        }
    ]
    artifacts = curve["iterations"][1]["artifacts"]
    assert artifacts["snapshot_manifest"] == (
        ".ucagent/design_with_ppa/candidates/iteration-001/snapshot.json"
    )
    assert artifacts["iteration_report"] == (
        "output/reports/ppa/iterations/iteration-001.json"
    )
    assert len(artifacts["rtl_sources"]) == 1
    artifact_source = artifacts["rtl_sources"][0]
    assert artifact_source["path"] == (
        ".ucagent/design_with_ppa/candidates/iteration-001/output/rtl/dut.v"
    )
    assert artifact_source["original_path"] == "output/rtl/dut.v"
    assert re.fullmatch(r"[0-9a-f]{64}", artifact_source["sha256"])

    candidate_source = tmp_path / artifact_source["path"]
    candidate_source.write_text(
        candidate_source.read_text(encoding="utf-8") + "\n// tampered\n",
        encoding="utf-8",
    )
    passed, result = final_checker.do_check()
    assert passed is False
    assert result["error_code"] == "design_final_delivery_invalid"




def test_final_delivery_regenerates_curve_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Curve JSON is derived evidence and is regenerated from the machine ledger."""

    checker, _ = _prepare_iteration_workspace(tmp_path, iterations=0)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    passed, _ = checker.do_check()
    assert passed is True
    _write_final_summary(tmp_path)
    final_checker = _final_delivery_checker(tmp_path, checker, iterations=0)
    passed, _ = final_checker.do_check()
    assert passed is True
    curve_path = tmp_path / "output" / "dut_performance_curve.json"
    curve_path.write_text('{"forged": true}\n', encoding="utf-8")

    passed, result = final_checker.do_check()

    assert passed is True, result
    curve = json.loads(curve_path.read_text(encoding="utf-8"))
    assert curve["schema_version"] == "1.3"
    assert "ledger" not in curve
    assert all("report_id" not in row for row in curve["iterations"])




def test_final_delivery_validates_dashboard_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Final delivery must require the rendered relative, read-only dashboard."""

    template = PLUGIN_SOURCE / "design_with_ppa" / "templates" / "unit_design"
    render_workspace = tmp_path / "rendered"
    render_workspace.mkdir()
    render_template_dir(
        str(render_workspace),
        str(template),
        _template_context("output", str(render_workspace)),
        target_dir="output",
    )
    checker, _ = _prepare_iteration_workspace(tmp_path, iterations=0)
    shutil.copy2(
        render_workspace / "output" / "dut_ppa_dashboard.html",
        tmp_path / "output" / "dut_ppa_dashboard.html",
    )
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    passed, result = checker.do_check()
    assert passed is True, result
    _write_final_summary(tmp_path)
    final_checker = _final_delivery_checker(
        tmp_path, checker, iterations=0, dashboard=True
    )

    passed, result = final_checker.do_check()

    assert passed is True, result
    assert result["design_dashboard"] == "output/dut_ppa_dashboard.html"
    dashboard_path = tmp_path / "output" / "dut_ppa_dashboard.html"
    dashboard_text = dashboard_path.read_text(encoding="utf-8")
    snapshot_match = re.search(
        r'<script id="design-with-ppa-snapshot" type="application/json">(.*?)</script>',
        dashboard_text,
        flags=re.DOTALL,
    )
    assert snapshot_match is not None
    snapshot = json.loads(snapshot_match.group(1))
    assert snapshot["state"]["candidate_count"] == 0
    assert snapshot["curve"]["schema_version"] == "1.3"
    assert snapshot["curve"]["selection_metric"]["best_value"] == 1.0
    dashboard_path.write_text(
        dashboard_text.replace(
            "deriveToffeeReportPath", "deriveTestReportPath"
        ),
        encoding="utf-8",
    )

    passed, result = final_checker.do_check()

    assert passed is False
    assert result["error_code"] == "design_final_delivery_invalid"
    assert "required contracts" in result["error"]
