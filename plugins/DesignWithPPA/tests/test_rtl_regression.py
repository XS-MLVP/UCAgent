"""Focused DesignWithPPA workflow tests: rtl regression."""

from __future__ import annotations

import helpers  # noqa: F401  (runs the plugin sys.path bootstrap first)

from helpers import (
    _config,
)

from pathlib import Path
import subprocess
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
from ucagent.checkers.unity_test import (  # noqa: E402
    BaseUnityChipCheckerTestCase,
    UnityChipCheckerTestCase,
    UnityChipCheckerTestCaseWithLineCoverage,
)




def test_rtl_regression_refreshes_private_backend_before_child_pytest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RTL regression must rebuild stale generated code before running tests."""

    rtl = tmp_path / "output" / "rtl" / "dut.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(
        "module dut(input wire a, output wire y); assign y = a; endmodule\n",
        encoding="ascii",
    )
    tests = tmp_path / "output" / "tests"
    tests.mkdir(parents=True)
    test_file = tests / "test_dut_functional.py"
    test_file.write_text("def test_dut():\n    assert True\n", encoding="ascii")
    events: list[str] = []

    def fake_build(self, is_complete=False, **kwargs):
        """Record the private build without invoking external tools."""

        del self, is_complete, kwargs
        events.append("build")
        return True, {"message": "current"}

    def fake_pytest(*args, **kwargs):
        """Record isolated pytest after the private build gate."""

        del kwargs
        if "--collect-only" in args[4]:
            events.append("collect")
            return subprocess.CompletedProcess(
                [], 0, "output/tests/test_dut_functional.py::test_dut\n", ""
            )
        events.append(f"{args[2]}-pytest")
        return subprocess.CompletedProcess([], 0, "1 passed", "")

    monkeypatch.setattr(RTLBackendBuildChecker, "do_check", fake_build)
    monkeypatch.setattr("design_with_ppa.checkers.runtime._run_pytest", fake_pytest)
    manifest_path = (
        tmp_path / ".ucagent" / "design_with_ppa" / "rtl_backend_manifest.json"
    )
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._validate_workspace_python_dut",
        lambda workspace, manifest: ("dut", "DUTdut"),
    )
    checker = RTLAllPassRegressionChecker(
        test_dir="output/tests",
        test_glob="output/tests/test_*.py",
        summary_file="output/reports/rtl.json",
        markdown_summary_file=None,
        timeout=30,
        cfg=_config(),
        rtl_architecture_file="output/dut_architecture.md",
        rtl_manifest_file=".ucagent/design_with_ppa/rtl_backend_manifest.json",
    ).set_workspace(str(tmp_path))

    assert checker.get_template_data() == {
        "RTL_TESTS_PASSED": 0,
        "RTL_TESTS_TOTAL": 0,
    }

    passed, result = checker.do_check()

    assert passed is True, result
    assert events == ["build", "collect", "python-pytest", "rtl-pytest"]
    assert checker.get_template_data() == {
        "RTL_TESTS_PASSED": 1,
        "RTL_TESTS_TOTAL": 1,
    }




def test_rtl_regression_description_reports_partial_pass_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed RTL run must retain its real passed-node count and full target total."""

    rtl = tmp_path / "output" / "rtl" / "dut.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(
        "module dut(input wire a, output wire y); assign y = a; endmodule\n",
        encoding="ascii",
    )
    tests = tmp_path / "output" / "tests"
    tests.mkdir(parents=True)
    test_file = tests / "test_dut_functional.py"
    test_file.write_text(
        "\n".join(
            f"def test_case_{index}():\n    assert True\n"
            for index in range(1, 6)
        ),
        encoding="ascii",
    )

    monkeypatch.setattr(
        RTLBackendBuildChecker,
        "do_check",
        lambda *_args, **_kwargs: (True, {"message": "current"}),
    )
    manifest_path = (
        tmp_path / ".ucagent" / "design_with_ppa" / "rtl_backend_manifest.json"
    )
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._validate_workspace_python_dut",
        lambda workspace, manifest: ("dut", "DUTdut"),
    )
    run_result = {"returncode": 1}

    def fake_pytest(*args, **kwargs):
        """Return a stable collection followed by the configured run result."""

        del kwargs
        if "--collect-only" in args[4]:
            nodes = "\n".join(
                f"output/tests/test_dut_functional.py::test_case_{index}"
                for index in range(1, 6)
            )
            return subprocess.CompletedProcess([], 0, nodes, "")
        if args[2] == "python":
            return subprocess.CompletedProcess([], 0, "5 passed in 0.02s\n", "")
        if run_result["returncode"]:
            return subprocess.CompletedProcess(
                [],
                1,
                "FAILED output/tests/test_dut_functional.py::test_case_4\n"
                "3 passed, 1 failed in 0.03s\n",
                "",
            )
        return subprocess.CompletedProcess([], 0, "5 passed in 0.03s\n", "")

    monkeypatch.setattr("design_with_ppa.checkers.runtime._run_pytest", fake_pytest)
    checker = RTLAllPassRegressionChecker(
        test_dir="output/tests",
        test_glob="output/tests/test_*.py",
        summary_file="output/reports/rtl.json",
        markdown_summary_file=None,
        timeout=30,
        cfg=_config(),
        rtl_architecture_file="output/dut_architecture.md",
        rtl_manifest_file=".ucagent/design_with_ppa/rtl_backend_manifest.json",
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result["observed"]["progress"] == {
        "passed": 3,
        "selected": 5,
        "total": 5,
    }
    assert result["observed"]["backend_comparison"] == {
        "python_reference": "pass",
        "rtl": "fail",
        "same_target_tests": 5,
        "full_target_tests": 5,
    }
    assert result["observed"]["rtl_debug"] == {
        "test_target": "test_dut_functional.py::test_case_4",
        "targeted_check": {
            "stage_args": {
                "test_target": "test_dut_functional.py::test_case_4"
            }
        },
        "waveform_test_case_name": "test_dut_functional.py::test_case_4",
        "waveform_retained": False,
    }
    assert "fix the selected RTL implementation" in result["next_action"]
    assert "RunTestCases validates Python only" in result["next_action"]
    assert "byte-to-element table" in result["next_action"]
    assert "A[i][0]*B[0][j] + A[i][1]*B[1][j]" in result["next_action"]
    assert "enough signed width" in result["next_action"]
    assert "Spec is authoritative" in result["next_action"]
    assert checker.get_template_data() == {
        "RTL_TESTS_PASSED": 3,
        "RTL_TESTS_TOTAL": 5,
    }

    run_result["returncode"] = 0
    passed, result = checker.do_check()

    assert passed is True, result
    assert checker.get_template_data() == {
        "RTL_TESTS_PASSED": 5,
        "RTL_TESTS_TOTAL": 5,
    }




def test_rtl_regression_requires_current_python_pass_before_rtl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changed shared tests must still pass the Python reference before RTL runs."""

    rtl = tmp_path / "output" / "rtl" / "dut.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(
        "module dut(input wire a, output wire y); assign y = a; endmodule\n",
        encoding="ascii",
    )
    tests = tmp_path / "output" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_dut_functional.py").write_text(
        "def test_dut():\n    assert True\n", encoding="ascii"
    )
    monkeypatch.setattr(
        RTLBackendBuildChecker,
        "do_check",
        lambda *_args, **_kwargs: (True, {"message": "current"}),
    )
    manifest_path = (
        tmp_path / ".ucagent" / "design_with_ppa" / "rtl_backend_manifest.json"
    )
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._validate_workspace_python_dut",
        lambda workspace, manifest: ("dut", "DUTdut"),
    )
    backends: list[str] = []

    def fake_pytest(*args, **kwargs):
        """Skip a Python node and prove that RTL is not dispatched."""

        del kwargs
        if "--collect-only" in args[4]:
            return subprocess.CompletedProcess(
                [], 0, "output/tests/test_dut_functional.py::test_dut\n", ""
            )
        backends.append(args[2])
        assert args[2] == "python"
        return subprocess.CompletedProcess(
            [],
            0,
            "1 skipped in 0.02s\n",
            "",
        )

    monkeypatch.setattr("design_with_ppa.checkers.runtime._run_pytest", fake_pytest)
    checker = RTLAllPassRegressionChecker(
        test_dir="output/tests",
        test_glob="output/tests/test_*.py",
        summary_file="output/reports/rtl.json",
        markdown_summary_file=None,
        timeout=30,
        cfg=_config(),
        rtl_architecture_file="output/dut_architecture.md",
        rtl_manifest_file=".ucagent/design_with_ppa/rtl_backend_manifest.json",
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "rtl_shared_python_regression_failed"
    assert "The Python reference is not frozen" in result["next_action"]
    assert "Do not edit the reference or expected merely to match" in result[
        "next_action"
    ]
    assert backends == ["python"]
    assert checker.get_template_data() == {
        "RTL_TESTS_PASSED": 0,
        "RTL_TESTS_TOTAL": 1,
    }




def test_rtl_regression_targeted_check_runs_same_node_without_full_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Targeted Check compares one exact node while Complete remains full-suite only."""

    rtl = tmp_path / "output" / "rtl" / "dut.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(
        "module dut(input wire a, output wire y); assign y = a; endmodule\n",
        encoding="ascii",
    )
    tests = tmp_path / "output" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_dut_functional.py").write_text(
        "def test_case_1():\n    assert True\n\n"
        "def test_case_2():\n    assert True\n",
        encoding="ascii",
    )
    monkeypatch.setattr(
        RTLBackendBuildChecker,
        "do_check",
        lambda *_args, **_kwargs: (True, {"message": "current"}),
    )
    manifest_path = (
        tmp_path / ".ucagent" / "design_with_ppa" / "rtl_backend_manifest.json"
    )
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._validate_workspace_python_dut",
        lambda workspace, manifest: ("dut", "DUTdut"),
    )
    calls: list[tuple[str, list[str] | None]] = []
    collected_nodes = (
        "output/tests/test_dut_functional.py::test_case_1\n"
        "output/tests/test_dut_functional.py::test_case_2\n"
    )

    def fake_pytest(*args, **kwargs):
        """Return a stable collection and record both targeted backend runs."""

        if "--collect-only" in args[4]:
            return subprocess.CompletedProcess([], 0, collected_nodes, "")
        calls.append((args[2], kwargs.get("pytest_targets")))
        return subprocess.CompletedProcess([], 0, "1 passed in 0.01s\n", "")

    monkeypatch.setattr("design_with_ppa.checkers.runtime._run_pytest", fake_pytest)
    summary = tmp_path / "output" / "reports" / "rtl.json"
    checker = RTLAllPassRegressionChecker(
        test_dir="output/tests",
        test_glob="output/tests/test_*.py",
        summary_file="output/reports/rtl.json",
        markdown_summary_file=None,
        timeout=30,
        cfg=_config(),
        rtl_architecture_file="output/dut_architecture.md",
        rtl_manifest_file=".ucagent/design_with_ppa/rtl_backend_manifest.json",
    ).set_workspace(str(tmp_path))

    target = "test_dut_functional.py::test_case_2"
    passed, result = checker.do_check(test_target=target)

    expected_node = "output/tests/test_dut_functional.py::test_case_2"
    assert passed is True, result
    assert calls == [
        ("python", [expected_node]),
        ("rtl", [expected_node]),
    ]
    assert result == {
        "message": "The targeted shared test passed against both implementations.",
        "test_target": target,
        "passed": 1,
        "total": 2,
        "next_action": "Fix another failing target with Check, or call Complete without test_target for the full regression.",
    }
    assert checker.get_template_data() == {
        "RTL_TESTS_PASSED": 1,
        "RTL_TESTS_TOTAL": 2,
    }
    assert not summary.exists()

    passed, result = checker.do_check(is_complete=True, test_target=target)
    assert passed is False
    assert result["error_code"] == "rtl_targeted_complete_forbidden"

    passed, result = checker.do_check(test_target="test_dut_functional.py::missing")
    assert passed is False
    assert result["error_code"] == "rtl_test_target_unknown"
    assert result["observed"]["available_targets"] == [
        "test_dut_functional.py::test_case_1",
        "test_dut_functional.py::test_case_2",
    ]




def test_core_checker_passes_private_backend_option_to_pytest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The line-coverage gate must be able to select the internal RTL backend."""

    test_dir = tmp_path / "output" / "tests"
    test_dir.mkdir(parents=True)
    doc = tmp_path / "output" / "dut_functions_and_checks.md"
    doc.write_text("\n# Contract\n", encoding="utf-8")
    checker = BaseUnityChipCheckerTestCase(
        doc_func_check="output/dut_functions_and_checks.md",
        test_dir="output/tests",
        test_func_rules=[],
        pytest_options=["--design-backend=rtl"],
    ).set_workspace(str(tmp_path))
    observed: dict[str, object] = {}

    def fake_do(self, *args, **kwargs):
        """Capture the exact pytest argument list from the core Checker."""

        del self, args
        observed["pytest_ex_args"] = kwargs["pytest_ex_args"]
        return {"run_test_success": True}, "", ""

    monkeypatch.setattr(type(checker.run_test), "do", fake_do)
    checker.do_check()
    assert observed["pytest_ex_args"] == ["--design-backend=rtl"]




def test_backend_regression_excludes_unimplemented_performance_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Functional regression must not collect the later performance template."""

    test_dir = tmp_path / "output" / "tests"
    test_dir.mkdir(parents=True)
    functional = test_dir / "test_dut_functional.py"
    performance = test_dir / "test_dut_performance.py"
    functional.write_text("def test_dut_ok():\n    assert True\n", encoding="utf-8")
    performance.write_text(
        'def test_dut_performance():\n    assert False, "Not implemented"\n',
        encoding="utf-8",
    )
    observed: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        """Capture the exact functional selection passed to pytest."""

        observed["test_files"] = kwargs["test_files"]
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="1 passed", stderr="")

    monkeypatch.setattr("design_with_ppa.checkers.runtime._run_pytest", fake_run)
    checker = PythonReferenceRegressionChecker(
        test_dir="output/tests",
        test_glob="output/tests/test_dut_*.py",
        exclude_test_globs=["output/tests/test_dut_performance*.py"],
        summary_file="output/reports/python.json",
        markdown_summary_file=None,
        timeout=10,
        cfg=_config(),
    ).set_workspace(str(tmp_path))
    passed, _ = checker.do_check()
    assert passed is True
    assert observed["test_files"] == [functional.resolve()]


def test_rtl_regression_reports_native_abort_without_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A silent RTL abort must surface as an infrastructure diagnostic."""

    rtl = tmp_path / "output" / "rtl" / "dut.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(
        "module dut(input wire a, output wire y); assign y = a; endmodule\n",
        encoding="ascii",
    )
    tests = tmp_path / "output" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_dut_functional.py").write_text(
        "def test_dut():\n    assert True\n", encoding="ascii"
    )
    monkeypatch.setattr(
        RTLBackendBuildChecker,
        "do_check",
        lambda *_args, **_kwargs: (True, {"message": "current"}),
    )
    manifest_path = (
        tmp_path / ".ucagent" / "design_with_ppa" / "rtl_backend_manifest.json"
    )
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._validate_workspace_python_dut",
        lambda workspace, manifest: ("dut", "DUTdut"),
    )

    def fake_pytest(*args, **kwargs):
        """Emit a healthy Python run, then the silent native-abort signature."""

        del kwargs
        if "--collect-only" in args[4]:
            return subprocess.CompletedProcess(
                [], 0, "output/tests/test_dut_functional.py::test_dut\n", ""
            )
        if args[2] == "python":
            return subprocess.CompletedProcess([], 0, "1 passed in 0.02s\n", "")
        return subprocess.CompletedProcess([], 1, "F", "")

    monkeypatch.setattr("design_with_ppa.checkers.runtime._run_pytest", fake_pytest)
    checker = RTLAllPassRegressionChecker(
        test_dir="output/tests",
        test_glob="output/tests/test_*.py",
        summary_file="output/reports/rtl.json",
        markdown_summary_file=None,
        timeout=30,
        cfg=_config(),
        rtl_architecture_file="output/dut_architecture.md",
        rtl_manifest_file=".ucagent/design_with_ppa/rtl_backend_manifest.json",
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "rtl_regression_aborted_before_summary"
    assert "prepare_native_artifact_path" in result["next_action"]
    assert "cannot write an artifact file" in result["next_action"]
    assert result["observed"]["stdout_tail"] == "F"


def test_pytest_died_before_summary_detects_silent_termination() -> None:
    """Only runs that end without any summary line count as native aborts."""

    from design_with_ppa.checkers.runtime import pytest_died_before_summary

    aborted = subprocess.CompletedProcess([], 1, "F", "")
    assert pytest_died_before_summary(aborted) is True
    dots_then_death = subprocess.CompletedProcess([], 1, "..F", "")
    assert pytest_died_before_summary(dots_then_death) is True
    healthy = subprocess.CompletedProcess([], 1, "F\n1 failed in 0.03s\n", "")
    assert pytest_died_before_summary(healthy) is False
    short_summary = subprocess.CompletedProcess(
        [], 1, "F\n=== short summary ===\nFAILED a::b\n1 failed in 0.1s\n", ""
    )
    assert pytest_died_before_summary(short_summary) is False
    passing = subprocess.CompletedProcess([], 0, "1 passed\n", "")
    assert pytest_died_before_summary(passing) is False
    empty = subprocess.CompletedProcess([], 1, "", "")
    assert pytest_died_before_summary(empty) is False
