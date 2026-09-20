"""Focused DesignWithPPA workflow tests: shared tests."""

from __future__ import annotations

import helpers  # noqa: F401  (runs the plugin sys.path bootstrap first)

from helpers import (
    _design_batch_checker,
)

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
from ucagent.checkers.unity_test import (  # noqa: E402
    BaseUnityChipCheckerTestCase,
    UnityChipCheckerTestCase,
    UnityChipCheckerTestCaseWithLineCoverage,
)
import ucagent.util.functions as uc_functions




def _design_batch_report(
    checker: DesignAllPassBatchTestsChecker,
    *,
    status: str = "PASSED",
    hit_checkpoint: bool = True,
    associate_checkpoint: bool = True,
) -> dict[str, Any]:
    """Build one current-batch Toffee report for the plugin all-Pass contract."""

    checkpoint = "FG-DESIGN/FC-CORE/CK-RESULT"
    report_nodes = [
        node.replace("::", f":{index * 3 + 1}-{index * 3 + 2}::", 1)
        for index, node in enumerate(checker.current_test_cases)
    ]
    return {
        "run_test_success": True,
        "tests": {
            "total": len(report_nodes),
            "fails": len(report_nodes) if status != "PASSED" else 0,
            "test_cases": {node: status for node in report_nodes},
        },
        "total_funct_point": 1,
        "total_check_point": 1,
        "all_check_point_list": [checkpoint],
        "unhit_check_point_list": [] if hit_checkpoint else [checkpoint],
        "failed_test_case_with_check_point_list": (
            {node: [checkpoint] for node in report_nodes}
            if status == "FAILED" else {}
        ),
        "test_case_with_check_point_list": (
            {node: [checkpoint] for node in report_nodes}
            if associate_checkpoint else {}
        ),
        "unmarked_check_points": int(not associate_checkpoint),
        "unmarked_check_point_list": [] if associate_checkpoint else [checkpoint],
        "test_function_with_no_check_point_mark": int(not associate_checkpoint),
        "test_function_with_no_check_point_mark_list": (
            [] if associate_checkpoint else report_nodes
        ),
    }




@pytest.mark.parametrize(
    ("status", "hit_checkpoint", "associate_checkpoint", "error_code"),
    [
        ("FAILED", True, True, "design_batch_tests_not_all_pass"),
        ("PASSED", False, True, "design_batch_checkpoint_not_hit"),
        ("PASSED", True, False, "design_batch_checkpoint_association_missing"),
    ],
)
def test_design_batch_checker_rejects_nonpassing_current_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    hit_checkpoint: bool,
    associate_checkpoint: bool,
    error_code: str,
) -> None:
    """Design generation must repair tests and coverage instead of recording Bugs."""

    checker, _manager = _design_batch_checker(tmp_path, ["test_result"])
    monkeypatch.setattr(
        uc_functions,
        "get_unity_chip_doc_marks",
        lambda *_args, **_kwargs: ["FG-DESIGN/FC-CORE/CK-RESULT"],
    )
    monkeypatch.setattr(
        uc_functions,
        "check_has_assert_in_tc",
        lambda *_args, **_kwargs: (True, "ok"),
    )

    passed, result, _validation = checker._validate_current_batch_report(
        _design_batch_report(
            checker,
            status=status,
            hit_checkpoint=hit_checkpoint,
            associate_checkpoint=associate_checkpoint,
        )
    )

    assert passed is False
    assert result["error_code"] == error_code




@pytest.mark.parametrize(
    (
        "unhit_checkpoints",
        "associated_checkpoints",
        "expected_pass",
        "expected_error_code",
    ),
    [
        # An unhit CK from a directed scope is irrelevant to the random run.
        (["FG-OTHER/FC-OTHER/CK-DIRECTED"], [], True, None),
        # A current-batch CK that is unhit but carries no random mark is the
        # stage_args.generated reason path and must not fail the run.
        (["FG-RANDOM/FC-RANDOM/CK-CURRENT"], [], True, None),
        # A random test claiming a CK its sampling never hits is a false
        # coverage claim and must fail with the repair fork.
        (
            ["FG-RANDOM/FC-RANDOM/CK-CURRENT"],
            ["FG-RANDOM/FC-RANDOM/CK-CURRENT"],
            False,
            "design_random_checkpoint_not_hit",
        ),
    ],
)
def test_random_checker_rejects_only_unhit_marked_coverage_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unhit_checkpoints: list[str],
    associated_checkpoints: list[str],
    expected_pass: bool,
    expected_error_code: str | None,
) -> None:
    """Random coverage is judged by mark_function claims, not batch membership."""

    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    (test_dir / "test_dut_random.py").write_text(
        "def test_random_current(env):\n"
        "    ucagent.repeat_count()\n"
        "    env.mark_function('FC-RANDOM', test_random_current, ['CK-CURRENT'])\n"
        "    assert True\n",
        encoding="utf-8",
    )
    node = "tests/test_dut_random.py:1-4::test_random_current"
    report = {
        "run_test_success": True,
        "tests": {
            "total": 1,
            "fails": 0,
            "test_cases": {node: "PASSED"},
        },
        "unhit_check_point_list": unhit_checkpoints,
        "test_case_with_check_point_list": (
            {node: associated_checkpoints} if associated_checkpoints else {}
        ),
    }
    monkeypatch.setattr(
        BaseUnityChipCheckerTestCase,
        "do_check",
        lambda self, **kwargs: (report, "1 passed", ""),
    )
    monkeypatch.setattr(
        uc_functions,
        "is_run_report_pass",
        lambda current_report, stdout, stderr: (True, "pass"),
    )
    monkeypatch.setattr(
        uc_functions,
        "check_has_assert_in_tc",
        lambda workspace, current_report: (True, "pass"),
    )
    checker = DesignRandomTestCasesChecker(
        target_test_file="tests/test_dut_random.py",
        doc_func_check="functions.md",
        test_dir="tests",
        batch_size=1,
        args_check=False,
    ).set_workspace(str(tmp_path))
    checker.batch_task.tbd_task_list = ["FG-RANDOM/FC-RANDOM/CK-CURRENT"]

    passed, result = checker.test_check()

    assert passed is expected_pass, result
    if expected_pass:
        assert "Bug" not in str(result)
    else:
        assert result["error_code"] == expected_error_code
        observed_claims = result["observed"]["unhit_marked_checkpoints"]
        assert [claim["CK"] for claim in observed_claims] == unhit_checkpoints
        assert observed_claims[0]["marked_by"] == [node]
        assert "mark_function association" in result["next_action"]
        assert "stage_args.generated" in result["next_action"]




def test_design_batch_checker_advances_only_an_all_pass_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plugin gate must retain batch progress without reading a Bug document."""

    checker, _manager = _design_batch_checker(
        tmp_path,
        ["test_first", "test_second"],
        batch_size=1,
    )
    (tmp_path / "tests" / "test_demo.py").write_text(
        "def test_first(env):\n"
        "    assert env is not None\n\n\n"
        "def test_second(env):\n"
        '    assert False, "Not implemented"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        uc_functions,
        "get_unity_chip_doc_marks",
        lambda *_args, **_kwargs: ["FG-DESIGN/FC-CORE/CK-RESULT"],
    )
    monkeypatch.setattr(
        uc_functions,
        "check_has_assert_in_tc",
        lambda *_args, **_kwargs: (True, "ok"),
    )
    monkeypatch.setattr(
        uc_functions,
        "is_run_report_pass",
        lambda *_args, **_kwargs: (True, ""),
    )

    def run_current_batch(current_checker: Any, **_kwargs: Any):
        """Return an all-Pass report for only the current batch."""

        return _design_batch_report(current_checker), "", ""

    monkeypatch.setattr(BaseUnityChipCheckerTestCase, "do_check", run_current_batch)

    passed, message = checker.do_check()

    assert passed is False
    assert "1/2" in message["success"]
    assert checker.batch_task.gen_task_list == ["tests/test_demo.py::test_first"]
    assert checker.current_test_cases == ["tests/test_demo.py::test_second"]
    assert not (tmp_path / "bugs.md").exists()




def test_design_batch_checker_counts_passing_future_implementations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One Check validates and counts correctly implemented later templates."""

    checker, _manager = _design_batch_checker(
        tmp_path,
        ["test_first", "test_second"],
        batch_size=1,
    )
    monkeypatch.setattr(
        uc_functions,
        "get_unity_chip_doc_marks",
        lambda *_args, **_kwargs: ["FG-DESIGN/FC-CORE/CK-RESULT"],
    )
    monkeypatch.setattr(
        uc_functions,
        "check_has_assert_in_tc",
        lambda *_args, **_kwargs: (True, "ok"),
    )
    monkeypatch.setattr(
        uc_functions,
        "is_run_report_pass",
        lambda *_args, **_kwargs: (True, ""),
    )
    monkeypatch.setattr(
        BaseUnityChipCheckerTestCase,
        "do_check",
        lambda current_checker, **_kwargs: (
            _design_batch_report(current_checker),
            "",
            "",
        ),
    )

    passed, result = checker.do_check()

    assert passed is True, result
    assert checker.batch_task.gen_task_list == [
        "tests/test_demo.py::test_first",
        "tests/test_demo.py::test_second",
    ]
    assert checker.current_test_cases == []




def test_design_batch_checker_rejects_failing_future_implementation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later authored test is counted only after its executable evidence passes."""

    checker, _manager = _design_batch_checker(
        tmp_path,
        ["test_first", "test_second"],
        batch_size=1,
    )
    monkeypatch.setattr(
        uc_functions,
        "is_run_report_pass",
        lambda *_args, **_kwargs: (True, ""),
    )
    monkeypatch.setattr(
        BaseUnityChipCheckerTestCase,
        "do_check",
        lambda current_checker, **_kwargs: (
            _design_batch_report(current_checker, status="FAILED"),
            "",
            "",
        ),
    )

    passed, result = checker.do_check()

    assert passed is False
    assert result["diagnostic"]["error_code"] == "design_batch_tests_not_all_pass"
    assert "If the Python reference implements that contract incorrectly" in result[
        "diagnostic"
    ]["next_action"]
    assert "merely to match the observed failure" in result["diagnostic"][
        "next_action"
    ]
    assert checker.batch_task.gen_task_list == []




def test_design_batch_checker_keeps_tips_guidance_scoped_to_current_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CurrentTips guidance must not absorb opportunistically validated future tests."""

    checker, _manager = _design_batch_checker(
        tmp_path,
        ["test_first", "test_second"],
        batch_size=1,
    )
    monkeypatch.setattr(
        uc_functions,
        "get_unity_chip_doc_marks",
        lambda *_args, **_kwargs: ["FG-DESIGN/FC-CORE/CK-RESULT"],
    )
    monkeypatch.setattr(
        uc_functions,
        "check_has_assert_in_tc",
        lambda *_args, **_kwargs: (True, "ok"),
    )
    monkeypatch.setattr(
        uc_functions,
        "is_run_report_pass",
        lambda *_args, **_kwargs: (True, ""),
    )
    monkeypatch.setattr(
        BaseUnityChipCheckerTestCase,
        "do_check",
        lambda current_checker, **_kwargs: (
            _design_batch_report(current_checker, status="FAILED"),
            "",
            "",
        ),
    )

    passed, _result = checker.do_check()

    assert passed is False
    # One Check still runs both authored tests for evidence and accounting.
    assert checker.current_test_cases == [
        "tests/test_demo.py::test_first",
        "tests/test_demo.py::test_second",
    ]
    data = checker.get_template_data()
    # Guidance stays scoped to the canonical batch instead of the run scope.
    assert data["LIST_CURRENT_CASES"] == ["tests/test_demo.py::test_first"]
    assert "test_first" in data["TEST_BATCH_RUN_ARGS"]
    assert "test_second" not in data["TEST_BATCH_RUN_ARGS"]




def test_design_batch_checker_allows_public_adapter_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Public env methods must reach executable validation like shared API calls."""

    checker, _manager = _design_batch_checker(tmp_path, ["test_direct"])
    (tmp_path / "tests" / "test_demo.py").write_text(
        "def test_direct(env):\n"
        "    env.reset()\n"
        "    result = env.add(1, 2, max_cycles=4)\n"
        "    assert result == 3\n",
        encoding="ascii",
    )

    monkeypatch.setattr(
        uc_functions,
        "get_unity_chip_doc_marks",
        lambda *_args, **_kwargs: ["FG-DESIGN/FC-CORE/CK-RESULT"],
    )
    monkeypatch.setattr(
        uc_functions,
        "check_has_assert_in_tc",
        lambda *_args, **_kwargs: (True, "ok"),
    )
    monkeypatch.setattr(
        uc_functions,
        "is_run_report_pass",
        lambda *_args, **_kwargs: (True, ""),
    )
    monkeypatch.setattr(
        BaseUnityChipCheckerTestCase,
        "do_check",
        lambda current_checker, **_kwargs: (
            _design_batch_report(current_checker),
            "",
            "",
        ),
    )

    passed, result = checker.do_check()

    assert passed is True, result




def test_api_assertion_quality_rejects_weak_result_checks(tmp_path: Path) -> None:
    """Public API results require an independent exact equality assertion."""

    source = tmp_path / "test_dut.py"
    source.write_text(
        "def test_dut_exact(env):\n"
        "    expected = 7\n"
        "    result = api_dut_run(env, 3, max_cycles=4)\n"
        "    assert result == expected\n\n"
        "def test_dut_none(env):\n"
        "    result = api_dut_run(env, 3, max_cycles=4)\n"
        "    assert result is not None\n\n"
        "def test_dut_nonzero(env):\n"
        "    result = api_dut_run(env, 3, max_cycles=4)\n"
        "    assert result != 0\n\n"
        "def test_dut_self(env):\n"
        "    result = api_dut_run(env, 3, max_cycles=4)\n"
        "    assert result == result\n\n"
        "def test_dut_invalid(env):\n"
        "    with pytest.raises(ValueError):\n"
        "        api_dut_run(env, -1, max_cycles=4)\n",
        encoding="ascii",
    )

    violations = _api_assertion_quality_violations(source, "dut")

    assert [violation["test"] for violation in violations] == [
        "test_dut_none",
        "test_dut_nonzero",
        "test_dut_self",
    ]




def test_api_assertion_quality_accepts_exact_sequence_result(tmp_path: Path) -> None:
    """A collected sequence of API results may be checked against exact expected data."""

    source = tmp_path / "test_dut.py"
    source.write_text(
        "def test_dut_sequence(env):\n"
        "    results = []\n"
        "    for value in (1, 2):\n"
        "        results.append(api_dut_run(env, value, max_cycles=4))\n"
        "    assert results == [2, 4]\n",
        encoding="ascii",
    )

    assert _api_assertion_quality_violations(source, "dut") == []




def test_api_assertion_quality_accepts_none_reset_result(tmp_path: Path) -> None:
    """The command-style reset API may be asserted to return None."""

    source = tmp_path / "test_dut.py"
    source.write_text(
        "def test_dut_reset(env):\n"
        "    result = api_dut_reset(env)\n"
        "    assert result is None\n",
        encoding="ascii",
    )

    assert _api_assertion_quality_violations(source, "dut") == []




def test_api_assertion_quality_allows_public_environment_actions(
    tmp_path: Path,
) -> None:
    """Public env methods may be used alongside the shared DUT API."""

    source = tmp_path / "test_dut.py"
    source.write_text(
        "def test_dut_direct(env):\n"
        "    env.reset()\n"
        "    result = env.add(1, 2, max_cycles=4)\n"
        "    assert result == 3\n",
        encoding="ascii",
    )

    assert _api_assertion_quality_violations(source, "dut") == []


def test_api_assertion_quality_accepts_accumulation_and_walrus(tmp_path: Path) -> None:
    """AugAssign accumulation and walrus bindings still count as API-derived."""

    source = tmp_path / "test_dut.py"
    source.write_text(
        "def test_dut_accumulate(env):\n"
        "    total = 0\n"
        "    for _ in range(3):\n"
        "        total += api_dut_run(env, 5, max_cycles=4)\n"
        "    assert total == 15\n\n"
        "def test_dut_walrus(env):\n"
        "    assert (result := api_dut_run(env, 7, max_cycles=4)) == 7\n",
        encoding="ascii",
    )

    violations = _api_assertion_quality_violations(source, "dut")

    assert violations == []
