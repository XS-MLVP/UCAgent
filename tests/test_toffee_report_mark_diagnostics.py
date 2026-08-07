#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for factual mark_function diagnostics from Toffee report relations."""

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.checkers.toffee_report import check_bug_tc_analysis, check_report


def _write_function_doc(path):
    path.write_text(
        "<FG-A>\n<FC-A>\n<CK-A>\n",
        encoding="utf-8",
    )


def test_check_report_prioritizes_empty_functional_coverage(tmp_path):
    _write_function_doc(tmp_path / "functions.md")
    test_case = "tests/test_a.py:1-2::test_a"
    report = {
        "total_funct_point": 0,
        "total_check_point": 0,
        "test_function_with_no_check_point_mark": 1,
        "test_function_with_no_check_point_mark_list": [test_case],
    }

    passed, message, _ = check_report(
        str(tmp_path),
        report,
        "functions.md",
        "bugs.md",
    )

    assert passed is False
    assert "[Functional Coverage Missing]" in message
    assert "do not duplicate" in message
    assert "[Call missing]" not in message


def test_check_report_describes_unassociated_checkpoint_as_report_state(tmp_path):
    _write_function_doc(tmp_path / "functions.md")
    checkpoint = "FG-A/FC-A/CK-A"
    report = {
        "total_funct_point": 1,
        "total_check_point": 1,
        "test_function_with_no_check_point_mark": 0,
        "all_check_point_list": [checkpoint],
        "unmarked_check_points": 1,
        "unmarked_check_point_list": [checkpoint],
        "tests": {"test_cases": {}},
    }

    passed, message, _ = check_report(
        str(tmp_path),
        report,
        "functions.md",
        "bugs.md",
    )

    assert passed is False
    assert "[Checkpoint Association Missing]" in message
    assert "recorded no associated test execution" in message
    assert "does not prove that `mark_function` is absent" in message


def test_check_report_does_not_rerun_legacy_mark_function_diagnostic(tmp_path):
    _write_function_doc(tmp_path / "functions.md")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(
        "def test_a(env):\n"
        "    env.dut.fc_cover['FG-A'].mark_function('FC-A', test_a, ['CK-A'])\n",
        encoding="utf-8",
    )
    test_case = "tests/test_a.py:1-2::test_a"
    report = {
        "total_funct_point": 1,
        "total_check_point": 1,
        "test_function_with_no_check_point_mark": 1,
        "test_function_with_no_check_point_mark_list": [test_case],
    }
    callback_called = False

    def unexpected_rerun(**kwargs):
        nonlocal callback_called
        callback_called = True
        raise AssertionError(f"diagnostic unexpectedly reran tests: {kwargs}")

    passed, message, _ = check_report(
        str(tmp_path),
        report,
        "functions.md",
        "bugs.md",
        func_RunTestCases=unexpected_rerun,
        timeout_RunTestCases=30,
    )

    assert passed is False
    assert "[Call present, association absent]" in message
    assert "Check/Complete result" in message
    assert "RunTestCases" not in message
    assert callback_called is False


def test_bug_analysis_reports_missing_relation_without_claiming_call_absent(tmp_path):
    checkpoint = "FG-A/FC-A/CK-A"
    test_case = "tests/test_a.py:1-3::test_a"
    (tmp_path / "bugs.md").write_text(
        "<FG-A>\n"
        "<FC-A>\n"
        "<CK-A>\n"
        "<BG-BUG-80>\n"
        "<TC-test_a.py::test_a>\n",
        encoding="utf-8",
    )

    passed, message = check_bug_tc_analysis(
        str(tmp_path),
        [checkpoint],
        "bugs.md",
        "",
        {test_case: ["FG-A/FC-A/CK-OTHER"]},
        [],
        False,
    )

    assert passed is False
    assert "[Bug Checkpoint Association Missing]" in message[0]
    assert "report does not associate" in message[0]
    assert "does not by itself prove" in message[1]
    assert "have not called mark_function" not in " ".join(message)
