"""Focused DesignWithPPA workflow tests: rtl line coverage."""

from __future__ import annotations

import helpers  # noqa: F401  (runs the plugin sys.path bootstrap first)

from helpers import (
    _config,
)

import json
from pathlib import Path
from typing import Any
import pytest
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
from ucagent.checkers.unity_test import (  # noqa: E402
    BaseUnityChipCheckerTestCase,
    UnityChipCheckerTestCase,
    UnityChipCheckerTestCaseWithLineCoverage,
)




def test_rtl_line_coverage_refreshes_private_backend_before_core_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verilog coverage must use the refreshed private package in a child run."""

    manifest_path = tmp_path / ".ucagent" / "design_with_ppa" / "rtl.json"
    manifest_path.parent.mkdir(parents=True)
    rtl_path = tmp_path / "output" / "rtl" / "dut.v"
    rtl_path.parent.mkdir(parents=True)
    rtl_path.write_text(
        "\n".join(["// authored"] * 19)
        + "\nmodule dut(input wire a, output wire y); assign y = a; endmodule\n",
        encoding="ascii",
    )
    manifest_path.write_text(
        json.dumps({"rtl_sources": [{"path": "output/rtl/dut.v"}]}),
        encoding="utf-8",
    )
    ignore_path = tmp_path / "output" / "tests" / "dut.ignore"
    ignore_path.parent.mkdir(parents=True)
    ignore_path.write_text("# No exclusions.\n", encoding="utf-8")
    coverage_path = tmp_path / "uc_test_report" / "line_dat" / "code_coverage.json"
    coverage_path.parent.mkdir(parents=True)
    coverage_path.write_text(
        json.dumps(
            {
                "sim": "verilator",
                "overview": {"total": {"line": 20}, "miss": {"line": 1}},
                "uncovered": {
                    "schema": {},
                    "data": {
                        "/private/build/dut.v": {
                            "total": {"line": 20},
                            "miss": {"line": 1},
                            "modules": {
                                "dut": {
                                    "total": {"line": 20},
                                    "miss": {"line": 1},
                                    "line": ["20-20"],
                                }
                            },
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (coverage_path.parent / "merged.info").write_text(
        "SF:/private/build/dut.v\n"
        + "\n".join(
            f"DA:{line},{0 if line == 20 else 1}" for line in range(1, 21)
        )
        + "\nend_of_record\n",
        encoding="utf-8",
    )
    observed: dict[str, Any] = {}

    def fake_build(checker, is_complete=False, **kwargs):
        del is_complete, kwargs
        observed["build_workspace"] = checker.workspace
        return True, {"message": "built"}

    def fake_runtime_validation(workspace, manifest):
        observed["validated"] = (workspace, manifest)
        return "dut", "DUTdut"

    def fake_core_gate(checker, timeout=0, **kwargs):
        del kwargs
        observed["timeout"] = timeout
        observed["python_paths"] = list(checker.run_test.extra_python_paths)
        return True, {"message": "functional regression passed"}

    monkeypatch.setattr(RTLBackendBuildChecker, "do_check", fake_build)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._validate_workspace_python_dut",
        fake_runtime_validation,
    )
    monkeypatch.setattr(
        UnityChipCheckerTestCase,
        "do_check",
        fake_core_gate,
    )
    checker = RTLLineCoverageChecker(
        rtl_architecture_file="output/dut_architecture.md",
        rtl_manifest_file=".ucagent/design_with_ppa/rtl.json",
        cfg=_config(),
        doc_func_check="output/dut_functions_and_checks.md",
        doc_bug_analysis="output/dut_bug_analysis.md",
        test_dir="output/tests",
        coverage_ignore="output/tests/dut.ignore",
        coverage_analysis="output/dut_line_coverage.md",
        timeout=37,
    ).set_workspace(str(tmp_path))
    # The stage manager merges the plugin import roots when it attaches; the
    # checker must keep them so the shared conftest can import design_with_ppa.
    checker.run_test.set_extra_python_paths(["/plugin/src/root"])

    passed, result = checker.do_check()

    assert passed is True
    assert "Line coverage check passed" in result
    assert observed["build_workspace"] == str(tmp_path)
    assert observed["validated"] == (
        tmp_path.resolve(),
        {"rtl_sources": [{"path": "output/rtl/dut.v"}]},
    )
    assert observed["timeout"] == 0
    assert observed["python_paths"] == [
        str(_workspace_python_dut_root(tmp_path.resolve())),
        "/plugin/src/root",
    ]
    assert (tmp_path / "output" / "dut_line_coverage.md").is_file()




def test_rtl_line_coverage_forwards_call_time_timeout_to_private_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Check call-time timeout must raise the private build's budget."""

    manifest_path = tmp_path / ".ucagent" / "design_with_ppa" / "rtl.json"
    manifest_path.parent.mkdir(parents=True)
    rtl_path = tmp_path / "output" / "rtl" / "dut.v"
    rtl_path.parent.mkdir(parents=True)
    rtl_path.write_text(
        "\n".join(["// authored"] * 19)
        + "\nmodule dut(input wire a, output wire y); assign y = a; endmodule\n",
        encoding="ascii",
    )
    manifest_path.write_text(
        json.dumps({"rtl_sources": [{"path": "output/rtl/dut.v"}]}),
        encoding="utf-8",
    )
    ignore_path = tmp_path / "output" / "tests" / "dut.ignore"
    ignore_path.parent.mkdir(parents=True)
    ignore_path.write_text("# No exclusions.\n", encoding="utf-8")
    coverage_path = tmp_path / "uc_test_report" / "line_dat" / "code_coverage.json"
    coverage_path.parent.mkdir(parents=True)
    coverage_path.write_text(
        json.dumps(
            {
                "sim": "verilator",
                "overview": {"total": {"line": 20}, "miss": {"line": 1}},
                "uncovered": {
                    "schema": {},
                    "data": {
                        "/private/build/dut.v": {
                            "total": {"line": 20},
                            "miss": {"line": 1},
                            "modules": {
                                "dut": {
                                    "total": {"line": 20},
                                    "miss": {"line": 1},
                                    "line": ["20-20"],
                                }
                            },
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (coverage_path.parent / "merged.info").write_text(
        "SF:/private/build/dut.v\n"
        + "\n".join(
            f"DA:{line},{0 if line == 20 else 1}" for line in range(1, 21)
        )
        + "\nend_of_record\n",
        encoding="utf-8",
    )
    observed: dict[str, Any] = {}

    def fake_build(checker, is_complete=False, **kwargs):
        del checker, is_complete
        observed["build_timeout"] = kwargs.get("timeout")
        return True, {"message": "built"}

    monkeypatch.setattr(RTLBackendBuildChecker, "do_check", fake_build)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._validate_workspace_python_dut",
        lambda workspace, manifest: ("dut", "DUTdut"),
    )
    monkeypatch.setattr(
        UnityChipCheckerTestCase,
        "do_check",
        lambda checker, timeout=0, **kwargs: (
            True,
            {"message": "functional regression passed"},
        ),
    )
    checker = RTLLineCoverageChecker(
        rtl_architecture_file="output/dut_architecture.md",
        rtl_manifest_file=".ucagent/design_with_ppa/rtl.json",
        cfg=_config(),
        doc_func_check="output/dut_functions_and_checks.md",
        doc_bug_analysis="output/dut_bug_analysis.md",
        test_dir="output/tests",
        coverage_ignore="output/tests/dut.ignore",
        coverage_analysis="output/dut_line_coverage.md",
        timeout=37,
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check(timeout=5000)

    assert passed is True, result
    assert observed["build_timeout"] == 5000




@pytest.mark.parametrize(
    ("ignore_line", "expected_reason"),
    [
        (
            "<LINE_IGNORE>*/dut.v:10-20</LINE_IGNORE>: uncovered path",
            "LINE_IGNORE tags",
        ),
        ("*/dut.v:20-10", "range start"),
        ("*/dut.v:0-10", "positive start-end"),
        ("*/dut.v:10", "positive start-end"),
        ("*/dut.v:10-20:reason", "exactly one range delimiter"),
        ('"*/dut.v:10-20"', "quotes and markup"),
        ("*/dut.v", "complete authored source file"),
        (":10-20", "source glob must start"),
        ("dut.v:10-20", "source glob must start"),
    ],
)
def test_rtl_line_coverage_rejects_invalid_raw_ignore_before_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ignore_line: str,
    expected_reason: str,
) -> None:
    """Malformed raw ignores must fail with a source location before RTL execution."""

    ignore_path = tmp_path / "output" / "tests" / "dut.ignore"
    ignore_path.parent.mkdir(parents=True)
    ignore_path.write_text(f"# retained comment\n{ignore_line}\n", encoding="utf-8")
    monkeypatch.setattr(
        RTLBackendBuildChecker,
        "do_check",
        lambda *_args, **_kwargs: pytest.fail("invalid ignore must not build RTL"),
    )
    checker = RTLLineCoverageChecker(
        rtl_architecture_file="output/dut_architecture.md",
        rtl_manifest_file=".ucagent/design_with_ppa/rtl.json",
        cfg=_config(),
        doc_func_check="output/dut_functions_and_checks.md",
        doc_bug_analysis="output/dut_bug_analysis.md",
        test_dir="output/tests",
        coverage_ignore="output/tests/dut.ignore",
        coverage_analysis="output/dut_line_coverage.md",
        timeout=37,
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "rtl_line_coverage_ignore_invalid"
    assert result["artifact"] == "output/tests/dut.ignore"
    assert result["location"] == "output/tests/dut.ignore:2"
    assert expected_reason in result["observed"][0]["reason"]
    assert "output/dut_line_coverage.md" in result["next_action"]




def test_rtl_line_coverage_accepts_canonical_raw_ignore_syntax(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Canonical file globs, positive ranges, and comment lines reach RTL build."""

    ignore_path = tmp_path / "output" / "tests" / "dut.ignore"
    ignore_path.parent.mkdir(parents=True)
    ignore_path.write_text(
        "# exact exclusions\n"
        "*/rtl/submodule.v:10-20,30-30\n",
        encoding="utf-8",
    )
    spec_path = tmp_path / "dut" / "spec" / "design.md"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text("WIDTH is fixed to 8.\n", encoding="utf-8")
    analysis_path = tmp_path / "output" / "dut_line_coverage.md"
    analysis_path.write_text(
        "\n# DUT Coverage\n\n## Exclusions\n\n"
        "<LINE_IGNORE>*/rtl/submodule.v:10-20,30-30</LINE_IGNORE>: "
        "[proof=parameter_unreachable; evidence=dut/spec/design.md:1-1] "
        "The fixed WIDTH domain cannot select the guarded branch.\n",
        encoding="utf-8",
    )
    observed = {"build": False}

    def fake_build(checker, is_complete=False, **kwargs):
        """Prove prevalidation delegated canonical syntax to the RTL build gate."""

        del checker, is_complete, kwargs
        observed["build"] = True
        return False, {"error_code": "expected_build_stop"}

    monkeypatch.setattr(RTLBackendBuildChecker, "do_check", fake_build)
    checker = RTLLineCoverageChecker(
        rtl_architecture_file="output/dut_architecture.md",
        rtl_manifest_file=".ucagent/design_with_ppa/rtl.json",
        cfg=_config(),
        doc_func_check="output/dut_functions_and_checks.md",
        doc_bug_analysis="output/dut_bug_analysis.md",
        test_dir="output/tests",
        coverage_ignore="output/tests/dut.ignore",
        coverage_analysis="output/dut_line_coverage.md",
        timeout=37,
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result == {"error_code": "expected_build_stop"}
    assert observed["build"] is True




@pytest.mark.parametrize(
    ("analysis_entry", "expected_reason"),
    [
        (
            "<LINE_IGNORE>*/dut.v:10-20</LINE_IGNORE>: old free-form reason",
            "canonical proof and evidence",
        ),
        (
            "<LINE_IGNORE>*/dut.v:10-20</LINE_IGNORE>: "
            "[proof=parameter_unreachable; evidence=dut/spec/missing.md:1-1] "
            "The parameter domain cannot select this branch.",
            "workspace artifact was not found",
        ),
        (
            "<LINE_IGNORE>*/dut.v:10-20</LINE_IGNORE>: "
            "[proof=parameter_unreachable; evidence=dut/spec/design.md:1-1] "
            "This behavior is reachable but current tests do not exercise it.",
            "reason admits reachable behavior",
        ),
        (
            "<LINE_IGNORE>*/other.v:10-20</LINE_IGNORE>: "
            "[proof=parameter_unreachable; evidence=dut/spec/design.md:1-1] "
            "The parameter domain cannot select this branch.",
            "no matching raw ignore pattern",
        ),
    ],
)
def test_rtl_line_coverage_rejects_untraced_or_contradictory_proofs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    analysis_entry: str,
    expected_reason: str,
) -> None:
    """Exclusions must have one traced proof and cannot admit missing validation."""

    spec_path = tmp_path / "dut" / "spec" / "design.md"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text("Legal parameter domain.\n", encoding="utf-8")
    ignore_path = tmp_path / "output" / "tests" / "dut.ignore"
    ignore_path.parent.mkdir(parents=True)
    ignore_path.write_text("*/dut.v:10-20\n", encoding="utf-8")
    analysis_path = tmp_path / "output" / "dut_line_coverage.md"
    analysis_path.write_text(
        f"\n# DUT Coverage\n\n## Exclusions\n\n{analysis_entry}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        RTLBackendBuildChecker,
        "do_check",
        lambda *_args, **_kwargs: pytest.fail("invalid proof must not build RTL"),
    )
    checker = RTLLineCoverageChecker(
        rtl_architecture_file="output/dut_architecture.md",
        rtl_manifest_file=".ucagent/design_with_ppa/rtl.json",
        cfg=_config(),
        doc_func_check="output/dut_functions_and_checks.md",
        doc_bug_analysis="output/dut_bug_analysis.md",
        test_dir="output/tests",
        coverage_ignore="output/tests/dut.ignore",
        coverage_analysis="output/dut_line_coverage.md",
        timeout=37,
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "rtl_line_coverage_proof_invalid"
    assert result["artifact"] == "output/dut_line_coverage.md"
    assert expected_reason in json.dumps(result["observed"])




def test_rtl_line_coverage_filters_generated_files_and_applies_exact_ranges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Coverage totals and diagnostics must contain only current authored Verilog."""

    rtl_path = tmp_path / "output" / "rtl" / "dut.v"
    rtl_path.parent.mkdir(parents=True)
    rtl_path.write_text("\n".join(["// source"] * 20) + "\n", encoding="ascii")
    spec_path = tmp_path / "dut" / "spec" / "design.md"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text("WIDTH is fixed to 8.\n", encoding="utf-8")
    manifest_path = tmp_path / ".ucagent" / "design_with_ppa" / "rtl.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps({"rtl_sources": [{"path": "output/rtl/dut.v"}]}),
        encoding="utf-8",
    )
    ignore_path = tmp_path / "output" / "tests" / "dut.ignore"
    ignore_path.parent.mkdir(parents=True)
    ignore_path.write_text("*/dut.v:10-10\n", encoding="utf-8")
    analysis_path = tmp_path / "output" / "dut_line_coverage.md"
    analysis_path.write_text(
        "\n# DUT Coverage\n\n## Exclusions\n\n"
        "<LINE_IGNORE>*/dut.v:10-10</LINE_IGNORE>: "
        "[proof=parameter_unreachable; evidence=dut/spec/design.md:1-1] "
        "The fixed WIDTH domain cannot select the guarded branch.\n",
        encoding="utf-8",
    )
    coverage_path = tmp_path / "uc_test_report" / "line_dat" / "code_coverage.json"
    coverage_path.parent.mkdir(parents=True)
    metric_zero = {"line": 0, "toggle": 0, "branch": 0, "expr": 0}
    coverage_path.write_text(
        json.dumps(
            {
                "sim": "verilator",
                "overview": {
                    "total": {**metric_zero, "line": 120},
                    "miss": {**metric_zero, "line": 5},
                },
                "uncovered": {
                    "schema": {},
                    "data": {
                        "/private/build/dut.v": {
                            "total": {**metric_zero, "line": 20},
                            "miss": {**metric_zero, "line": 3},
                            "modules": {
                                "dut": {
                                    "total": {**metric_zero, "line": 20},
                                    "miss": {**metric_zero, "line": 3},
                                    "line": ["10-14"],
                                    "toggle": [],
                                    "branch": [],
                                    "expr": [],
                                }
                            },
                        },
                        "/private/build/dut_top.sv": {
                            "total": {**metric_zero, "line": 100},
                            "miss": metric_zero,
                            "modules": {
                                "dut_top": {
                                    "total": {**metric_zero, "line": 100},
                                    "miss": metric_zero,
                                    "line": [],
                                    "toggle": [],
                                    "branch": [],
                                    "expr": [],
                                }
                            },
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (coverage_path.parent / "merged.info").write_text(
        "SF:/private/build/dut.v\n"
        + "\n".join(
            f"DA:{line},{0 if line in {10, 12, 14} else 1}"
            for line in range(1, 21)
        )
        + "\nend_of_record\n"
        "SF:/private/build/dut_top.sv\n"
        + "\n".join(f"DA:{line},1" for line in range(1, 101))
        + "\nend_of_record\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        RTLBackendBuildChecker,
        "do_check",
        lambda *_args, **_kwargs: (True, {"message": "built"}),
    )
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._validate_workspace_python_dut",
        lambda *_args: ("dut", "DUTdut"),
    )
    monkeypatch.setattr(
        UnityChipCheckerTestCase,
        "do_check",
        lambda *_args, **_kwargs: (True, {"message": "functional pass"}),
    )
    checker = RTLLineCoverageChecker(
        rtl_architecture_file="output/dut_architecture.md",
        rtl_manifest_file=".ucagent/design_with_ppa/rtl.json",
        cfg=_config(),
        doc_func_check="output/dut_functions_and_checks.md",
        doc_bug_analysis="output/dut_bug_analysis.md",
        test_dir="output/tests",
        coverage_ignore="output/tests/dut.ignore",
        coverage_analysis="output/dut_line_coverage.md",
        timeout=37,
        min_line_coverage=0.9,
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "rtl_line_coverage_below_threshold"
    assert result["observed"] == {
        "coverage": pytest.approx(17 / 19),
        "uncovered": [
            {
                "module_name": "dut",
                "lines_uncovered": "output/rtl/dut.v:12-12,14-14",
            }
        ],
    }
    sanitized = json.loads(coverage_path.read_text(encoding="utf-8"))
    assert sanitized["overview"]["total"]["line"] == 19
    assert sanitized["overview"]["miss"]["line"] == 2
    assert list(sanitized["uncovered"]["data"]) == ["output/rtl/dut.v"]
    assert "private" not in json.dumps(sanitized).lower()
    assert "top.sv" not in json.dumps(result).lower()




def test_rtl_line_coverage_resolves_relative_test_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The coverage gate must inspect core-provided workspace-relative test paths."""

    test_path = tmp_path / "output" / "tests" / "test_dut_functional.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "def test_dut_result(env):\n"
        "    result = api_dut_run(env, 3, max_cycles=4)\n"
        "    assert result is not None\n",
        encoding="ascii",
    )
    monkeypatch.setattr(
        RTLBackendBuildChecker,
        "do_check",
        lambda *_args, **_kwargs: pytest.fail("weak assertions must fail before build"),
    )
    checker = RTLLineCoverageChecker(
        rtl_architecture_file="output/dut_architecture.md",
        rtl_manifest_file=".ucagent/design_with_ppa/rtl.json",
        cfg=_config(),
        doc_func_check="output/dut_functions_and_checks.md",
        doc_bug_analysis="output/dut_bug_analysis.md",
        test_dir="output/tests",
        coverage_ignore="output/tests/dut.ignore",
        coverage_analysis="output/dut_line_coverage.md",
        timeout=37,
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "rtl_line_coverage_weak_api_assertion"
    assert result["observed"]["violations"] == [
        {
            "file": "output/tests/test_dut_functional.py",
            "line": 1,
            "test": "test_dut_result",
            "reason": "public_api_result_has_no_independent_exact_equality",
        }
    ]




def test_rtl_line_coverage_surfaces_toffee_generation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing coverage JSON must expose the bounded Toffee line error."""

    manifest_path = tmp_path / ".ucagent" / "design_with_ppa" / "rtl.json"
    manifest_path.parent.mkdir(parents=True)
    rtl_path = tmp_path / "output" / "rtl" / "dut.v"
    rtl_path.parent.mkdir(parents=True)
    rtl_path.write_text(
        "module dut(input wire a, output wire y); assign y = a; endmodule\n",
        encoding="ascii",
    )
    manifest_path.write_text(
        json.dumps({"rtl_sources": [{"path": "output/rtl/dut.v"}]}),
        encoding="utf-8",
    )
    ignore_path = tmp_path / "output" / "tests" / "dut.ignore"
    ignore_path.parent.mkdir(parents=True)
    ignore_path.write_text("# No exclusions.\n", encoding="utf-8")
    report_path = tmp_path / "uc_test_report" / "toffee_report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "coverages": {
                    "line": {
                        "error": "ValueError('invalid line coverage ignore input')"
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        RTLBackendBuildChecker,
        "do_check",
        lambda *_args, **_kwargs: (True, {"message": "built"}),
    )
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._validate_workspace_python_dut",
        lambda *_args: ("dut", "DUTdut"),
    )
    monkeypatch.setattr(
        UnityChipCheckerTestCase,
        "do_check",
        lambda *_args, **_kwargs: (True, {"message": "functional pass"}),
    )
    checker = RTLLineCoverageChecker(
        rtl_architecture_file="output/dut_architecture.md",
        rtl_manifest_file=".ucagent/design_with_ppa/rtl.json",
        cfg=_config(),
        doc_func_check="output/dut_functions_and_checks.md",
        doc_bug_analysis="output/dut_bug_analysis.md",
        test_dir="output/tests",
        coverage_ignore="output/tests/dut.ignore",
        coverage_analysis="output/dut_line_coverage.md",
        timeout=37,
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "rtl_line_coverage_generation_failed"
    assert result["artifact"] == "uc_test_report/toffee_report.json"
    assert result["location"] == "coverages.line.error"
    assert "invalid line coverage ignore input" in result["observed"]
    assert "output/tests/dut.ignore" in result["next_action"]




def test_rtl_line_coverage_fixture_requires_finalization_before_registration(
    tmp_path: Path,
) -> None:
    """The fixture contract must finalize native coverage before Toffee registration."""

    valid = tmp_path / "conftest.py"
    valid.write_text(
        "def env(request):\n"
        "    adapter.bind_coverage(groups)\n"
        "    adapter.configure_test_artifacts('coverage.dat', 'trace.vcd')\n"
        "    adapter.reset()\n"
        "    yield object()\n"
        "    set_func_coverage(request, [])\n"
        "    adapter.finish()\n"
        "    set_line_coverage(request, 'coverage.dat')\n",
        encoding="utf-8",
    )
    invalid = tmp_path / "invalid_conftest.py"
    invalid.write_text(
        "def env(request):\n"
        "    yield object()\n"
        "    set_line_coverage(request, 'coverage.dat')\n"
        "    adapter.finish()\n",
        encoding="utf-8",
    )

    assert _coverage_fixture_lifecycle_violations(valid) == []
    violations = _coverage_fixture_lifecycle_violations(invalid)
    assert any("after adapter.finish" in message for message in violations)
    assert any("set_func_coverage" in message for message in violations)

    no_env = tmp_path / "no_env_conftest.py"
    no_env.write_text("def other_fixture():\n    return object()\n", encoding="ascii")
    assert any(
        "required env fixture" in message
        for message in _coverage_fixture_lifecycle_violations(no_env)
    )




def test_rtl_line_coverage_title_reports_pending_until_measured(tmp_path: Path) -> None:
    """An unmeasured stage must not display a fabricated zero-percent result."""

    checker = RTLLineCoverageChecker(
        rtl_architecture_file="output/dut_architecture.md",
        rtl_manifest_file=".ucagent/design_with_ppa/rtl.json",
        cfg=_config(),
        test_dir="output/tests",
        coverage_ignore="output/tests/dut.ignore",
        coverage_analysis="output/dut_line_coverage.md",
        rtl_regression_file="output/reports/dut_rtl_regression.json",
        timeout=30,
        min_line_coverage=0.9,
    ).set_workspace(str(tmp_path))

    assert checker.get_template_data() == {
        "COVERAGE_COMPLETE": "pending/90.00% minimum"
    }
    checker.cur_line_coverage = 0.95
    assert checker.get_template_data() == {"COVERAGE_COMPLETE": "95.00/90.00"}
