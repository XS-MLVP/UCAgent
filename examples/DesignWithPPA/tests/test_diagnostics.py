"""Focused DesignWithPPA workflow tests: diagnostics."""

from __future__ import annotations

import helpers  # noqa: F401  (runs the plugin sys.path bootstrap first)

import ast
import json
from pathlib import Path
import subprocess
import sys
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
    _exception_contract_diagnostic,
    _pytest_evidence,
    _rtl_regression_failure_evidence,
    _run_pytest,
    _run_workflow_ppa,
    select_best_accepted_record,
)




def test_actionable_checker_failure_normalizes_and_bounds_inherited_results() -> None:
    """Inherited failures must retain evidence in one bounded actionable contract."""

    normalized = _actionable_checker_failure(
        {"error": "first concrete failure", "details": [str(index) for index in range(30)]},
        error_code="example_invalid",
        error="Fallback error.",
        next_action="Open output/example.md, repair the first reported item, then call Check.",
        artifact="output/example.md",
        location="output/example.md:7",
        expected="One valid example.",
        current_batch=[f"CK-{index}" for index in range(30)],
    )

    assert normalized["error_code"] == "example_invalid"
    assert normalized["error"] == "first concrete failure"
    assert normalized["artifact"] == "output/example.md"
    assert normalized["location"] == "output/example.md:7"
    assert normalized["observed"]["current_batch_count"] == 30
    assert normalized["observed"]["current_batch_truncated"] is True
    assert len(normalized["observed"]["checker_result"]["details"]) == 21
    assert normalized["expected"] == "One valid example."

    progress = {"success": "batch complete", "next": ["CK-next"]}
    assert _actionable_checker_failure(
        progress,
        error_code="unused",
        error="unused",
        next_action="unused",
        artifact="unused",
        expected="unused",
    ) is progress
    assert len(_bounded_checker_value("x" * 5000)) == 4000




@pytest.mark.parametrize(
    ("base_checker", "checker", "expected_code", "artifact"),
    [
        (
            "UnityChipCheckerMarkdownFileFormat",
            DesignMarkdownFileFormatChecker(["output/design.md"]),
            "design_markdown_invalid",
            "output/design.md",
        ),
        (
            "UnityChipCheckerLabelStructure",
            DesignLabelStructureChecker(
                "output/functions.md", "CK", must_have_prefix=""
            ),
            "design_label_structure_invalid",
            "output/functions.md",
        ),
        (
            "UnityChipCheckerDutApi",
            DesignDutApiChecker("api_dut_", "output/tests/dut_api.py"),
            "design_public_api_invalid",
            "output/tests/dut_api.py",
        ),
        (
            "UnityChipCheckerTestMustPass",
            DesignPythonAllPassChecker(
                "output/tests/test_dut_*.py", "output/tests", "test_dut_"
            ),
            "design_python_all_pass_failed",
            "output/tests/test_dut_*.py",
        ),
    ],
)
def test_design_checker_wrappers_make_core_failures_actionable(
    monkeypatch: pytest.MonkeyPatch,
    base_checker: str,
    checker: object,
    expected_code: str,
    artifact: str,
) -> None:
    """Workflow wrappers must convert broad core failures into repairable tasks."""

    monkeypatch.setattr(
        f"ucagent.checkers.unity_test.{base_checker}.do_check",
        lambda self, **kwargs: (False, {"error": "specific inherited failure"}),
    )

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == expected_code
    assert result["error"] == "specific inherited failure"
    assert result["artifact"] == artifact
    assert result["location"]
    assert result["observed"]
    assert result["expected"]
    assert "Check" in result["next_action"]




def test_direct_plugin_checker_diagnostics_have_location_and_repair_contract() -> None:
    """Every direct plugin diagnostic must preserve the full failure contract."""

    checker_source = Path(
        sys.modules[DesignInputContractChecker.__module__].__file__
    ).read_text(encoding="utf-8")
    tree = ast.parse(checker_source)
    missing: list[tuple[str, int, list[str]]] = []
    for class_node in (
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and "Checker" in node.name
    ):
        for call in ast.walk(class_node):
            if not (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "diagnostic"
            ):
                continue
            keywords = {keyword.arg for keyword in call.keywords}
            absent = [
                field
                for field in ("artifact", "location", "observed", "expected")
                if field not in keywords
            ]
            if absent:
                missing.append((class_node.name, call.lineno, absent))
    assert missing == []




def test_final_toffee_cases_normalize_raw_phase_nodes(tmp_path: Path) -> None:
    """Raw Toffee phase identities are normalized to the selected source set."""

    from design_with_ppa.checkers import _extract_final_toffee_cases

    test_file = tmp_path / "output" / "tests" / "test_dut_functional.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_dut_functional():\n    assert True\n", encoding="utf-8")
    report = {
        "tests": [
            {
                "status": {"word": "PASSED"},
                "phases": [
                    {
                        "report": (
                            "<TestReport 'output/tests/test_dut_functional.py::"
                            "test_dut_functional' when='call' outcome='passed'>"
                        )
                    }
                ],
            }
        ]
    }
    assert _extract_final_toffee_cases(
        report, tmp_path, [test_file]
    ) == {
        "output/tests/test_dut_functional.py::test_dut_functional": "PASSED"
    }




def test_public_pytest_failure_keeps_node_but_hides_import_traceback() -> None:
    """RTL diagnostics expose the failing node without generated identities."""

    completed = subprocess.CompletedProcess(
        args=["pytest"],
        returncode=1,
        stdout=(
            "Traceback (most recent call last):\n"
            "  File \"/private/tmp/design_with_ppa/python_dut.py\", line 1\n"
            "FAILED output/tests/test_dut.py::test_add - AttributeError: "
            "module 'dut' has no attribute 'DUTdut'\n"
            "================ 1 failed in 0.12s ================\n"
        ),
        stderr="",
    )

    result = _public_pytest_failure(completed)

    assert result["failed_nodes"] == [
        "FAILED output/tests/test_dut.py::test_add - "
        "RTL test runtime initialization failed"
    ]
    serialized = json.dumps(result)
    assert "python_dut.py" not in serialized
    assert "DUTdut" not in serialized
    assert "/private/" not in serialized




def test_public_pytest_failure_includes_sanitized_assertion_summary() -> None:
    """Useful assertion differences are retained without private runtime identities."""

    completed = subprocess.CompletedProcess(
        args=["pytest"],
        returncode=1,
        stdout=(
            "FAILED output/tests/test_dut.py::test_add\n"
            "E       AssertionError: assert 0 == 7\n"
            "E       from generated Python-DUT runtime /tmp/secret\n"
            "================ 1 failed in 0.12s ================\n"
        ),
        stderr="",
    )

    result = _public_pytest_failure(completed)

    assert result["assertion_diagnostics"] == [
        "E AssertionError: assert 0 == 7"
    ]
    assert "/tmp/secret" not in json.dumps(result)




def test_pytest_evidence_captures_bounded_streams_and_success_summary() -> None:
    """Checker evidence keeps useful pytest output while bounding both streams."""

    completed = subprocess.CompletedProcess(
        args=["pytest"],
        returncode=0,
        stdout="2 passed in 0.03s\n",
        stderr="warning: optional backend\n",
    )

    result = _pytest_evidence(completed)

    assert result["summary"] == "2 passed in 0.03s"
    assert result["stdout_tail"] == "2 passed in 0.03s\n"
    assert result["stderr_tail"] == "warning: optional backend\n"
    hidden = _pytest_evidence(
        completed, ret_std_out=False, ret_std_error=False
    )
    assert "stdout_tail" not in hidden
    assert "stderr_tail" not in hidden




def test_line_range_diagnostic_preserves_gaps() -> None:
    """Coverage diagnostics must not imply covered gaps are one invalid range."""

    from design_with_ppa.checkers import _line_ranges_text

    assert _line_ranges_text({96, 97, 103, 105, 106, 184}) == (
        "96-97,103-103,105-106,184-184"
    )




def test_rtl_regression_failure_evidence_contains_phase_and_checkpoint_context(
    tmp_path: Path,
) -> None:
    """RTL failure diagnostics retain actionable Toffee and pytest evidence."""

    node = "output/tests/test_dut_functional.py::test_dut_result"
    report = {
        "tests": {
            "test_cases": {node: "FAILED"},
            "test_case_details": {
                node: {
                    "status": "FAILED",
                    "phase": "call",
                    "exception_type": "AssertionError",
                    "exception": "AssertionError: assert 1 == 2",
                }
            },
        },
        "test_case_with_check_point_list": {
            node: ["FG-1/FC-1/CK-RESULT"]
        },
        "unhit_check_point_list": ["FG-1/FC-1/CK-RESULT"],
    }

    evidence = _rtl_regression_failure_evidence(
        report,
        "FAILED output/tests/test_dut_functional.py::test_dut_result - AssertionError: assert 1 == 2\n1 failed in 0.01s\n",
        "",
        1,
        workspace=tmp_path,
        ret_std_out=True,
        ret_std_error=True,
    )

    assert evidence["failed_cases"] == [
        {
            "test": node,
            "status": "FAILED",
            "checkpoints": ["FG-1/FC-1/CK-RESULT"],
            "phase": "call",
            "exception_type": "AssertionError",
            "exception": "AssertionError: assert 1 == 2",
        }
    ]
    assert evidence["unhit_checkpoints"] == ["FG-1/FC-1/CK-RESULT"]
    assert evidence["failed_nodes"] == [
        "FAILED output/tests/test_dut_functional.py::test_dut_result - AssertionError: assert 1 == 2"
    ]




def test_private_regression_cleanup_is_limited_to_toffee_run_directories(
    tmp_path: Path,
) -> None:
    """Private backend cleanup must retain user-authored data directories."""

    data = tmp_path / "tests" / "data"
    transient = data / "toffee_tmp_20260903220013_683"
    retained = data / "vectors"
    transient.mkdir(parents=True)
    retained.mkdir()
    (transient / "coverage.dat").write_bytes(b"coverage")
    (retained / "input.json").write_text("{}\n", encoding="utf-8")

    _cleanup_transient_coverage_data(tmp_path / "tests")

    assert not transient.exists()
    assert (retained / "input.json").is_file()


def test_public_pytest_failure_relabels_only_runtime_imports() -> None:
    """Authored-test import typos keep their real message; runtime ones do not."""

    completed = subprocess.CompletedProcess(
        [],
        1,
        "FAILED tests/test_dut_fp.py::test_one - ImportError: cannot import name"
        " 'api_dut_wrong' from 'dut_api'\n"
        "FAILED tests/test_dut_fp.py::test_two - ModuleNotFoundError:"
        " No module named 'DUTdut_shim'\n"
        "1 failed in 0.01s\n",
        "",
    )
    result = _public_pytest_failure(completed)
    joined = "\n".join(result["failed_nodes"])
    assert "cannot import name 'api_dut_wrong'" in joined
    assert "RTL test runtime initialization failed" in joined


def test_exception_diagnostic_keeps_tail_of_long_reasons() -> None:
    """Root causes at the end of long exception texts survive inline cropping."""

    long_prefix = "x" * 2000
    exc = ValueError(f"{long_prefix} >>> ModuleNotFoundError: No module named 'dut_shim'")
    result = _exception_contract_diagnostic(
        error_code="demo_invalid",
        error="Demo contract failed.",
        exc=exc,
        artifact="output/demo.yaml",
        guide="Guide_Doc/demo.md",
        expected="A valid demo contract.",
    )
    assert "No module named 'dut_shim'" in result["error"]
    assert "No module named 'dut_shim'" in result["observed"]["reason"]


def test_consistency_failure_diagnostic_bounds_and_structures() -> None:
    """The consistency fallback bounds text and keeps exception identity."""

    from design_with_ppa.consistency import consistency_failure_diagnostic

    huge = "y" * 20000 + " >>> final python regression failed"
    result = consistency_failure_diagnostic(ValueError(huge), "output/tests/test_*.py")
    assert result["error_code"] == "design_consistency_failed"
    assert len(result["error"]) <= 1200
    assert "final python regression failed" in result["error"]
    assert result["observed"]["exception_type"] == "ValueError"
    assert len(result["observed"]["reason"]) <= 4000


def test_inline_reason_is_tail_aligned() -> None:
    """Inline excerpts keep the decisive tail instead of cropping it."""

    from design_with_ppa.checkers.common import _inline_reason

    long_reason = "x" * 2000 + " >>> root cause line"
    excerpt = _inline_reason(long_reason)
    assert "root cause line" in excerpt
    assert excerpt.startswith("...")
    assert len(excerpt) <= 1203
    assert _inline_reason("short reason") == "short reason"
