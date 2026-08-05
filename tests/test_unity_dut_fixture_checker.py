#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for DUT fixture functional coverage validation."""

import os
import sys
from types import SimpleNamespace

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.checkers.unity_test import (
    UnityChipCheckerDutApiTest,
    UnityChipCheckerDutFixture,
)


def _check_fixture(tmp_path, fixture_body):
    source = "\n".join([
        "import pytest",
        "from toffee_test.reporter import set_func_coverage",
        "",
        "@pytest.fixture(scope='function')",
        "def dut(request):",
        *[f"    {line}" for line in fixture_body],
        "",
    ])
    (tmp_path / "dut_api.py").write_text(source, encoding="utf-8")
    checker = UnityChipCheckerDutFixture(
        "dut_api.py",
        cfg={"_temp_cfg": {"DUT": "Demo"}},
    ).set_workspace(str(tmp_path))
    return checker.do_check()


def test_dut_fixture_requires_set_func_coverage_call(tmp_path):
    passed, message = _check_fixture(tmp_path, [
        "func_coverage_group = []",
        "get_coverage_data_path(request, new_path=False)",
        "yield object()",
        "# set_func_coverage is imported but not called",
    ])

    assert passed is False
    assert "must call 'set_func_coverage" in message["error"]
    assert "every test appears unmarked" in message["error"]


def test_dut_fixture_requires_set_func_coverage_after_yield(tmp_path):
    passed, message = _check_fixture(tmp_path, [
        "func_coverage_group = []",
        "get_coverage_data_path(request, new_path=False)",
        "set_func_coverage(request, func_coverage_group)",
        "yield object()",
    ])

    assert passed is False
    assert "after 'yield'" in message["error"]


def test_dut_fixture_rejects_set_func_coverage_without_groups(tmp_path):
    passed, message = _check_fixture(tmp_path, [
        "get_coverage_data_path(request, new_path=False)",
        "yield object()",
        "set_func_coverage(request)",
    ])

    assert passed is False
    assert "must pass both" in message["error"]


def test_dut_fixture_accepts_set_func_coverage_during_teardown(tmp_path):
    passed, message = _check_fixture(tmp_path, [
        "func_coverage_group = []",
        "get_coverage_data_path(request, new_path=False)",
        "yield object()",
        "set_func_coverage(request, func_coverage_group)",
    ])

    assert passed is True
    assert "passed" in message["message"]


def test_api_checker_reports_missing_functional_coverage_before_mark_errors():
    message = UnityChipCheckerDutApiTest._missing_functional_coverage_message({
        "total_funct_point": 0,
        "total_check_point": 0,
        "test_function_with_no_check_point_mark": 12,
    })

    assert "Functional coverage data is missing or empty" in message
    assert "may already call mark_function correctly" in message
    assert "set_func_coverage" in message


def test_api_checker_do_check_prioritizes_missing_coverage_diagnostic(tmp_path):
    (tmp_path / "dut_api.py").write_text(
        "def api_Demo_operate(env, max_cycles=1):\n    return None\n",
        encoding="utf-8",
    )
    (tmp_path / "test_Demo_api.py").write_text(
        "def test_api_Demo_operate(env):\n    assert True\n",
        encoding="utf-8",
    )
    (tmp_path / "functions_and_checks.md").write_text("<FG-API>\n", encoding="utf-8")

    report = {
        "run_test_success": True,
        "tests": {
            "total": 1,
            "fails": 0,
            "test_cases": {
                "test_Demo_api.py:1-2::test_api_Demo_operate": "PASSED",
            },
        },
        "total_funct_point": 0,
        "total_check_point": 0,
        "test_function_with_no_check_point_mark": 1,
        "test_function_with_no_check_point_mark_list": [
            "test_Demo_api.py:1-2::test_api_Demo_operate",
        ],
    }
    checker = UnityChipCheckerDutApiTest(
        "api_Demo_",
        "dut_api.py",
        "test_Demo_api.py",
        "functions_and_checks.md",
        "bug_analysis.md",
    ).set_workspace(str(tmp_path))
    checker.run_test = SimpleNamespace(do=lambda *args, **kwargs: (report, "", ""))
    checker._check_test_func_args = lambda current_report, stdout, stderr: (
        current_report,
        stdout,
        stderr,
    )

    passed, message = checker.do_check()

    assert passed is False
    assert "Functional coverage data is missing or empty" in message["error"]
    assert "set_func_coverage" in message["error"]
    assert "already called 'mark_function' but encountered errors" not in message["error"]


def test_api_checker_accepts_nonempty_functional_coverage():
    message = UnityChipCheckerDutApiTest._missing_functional_coverage_message({
        "total_funct_point": 3,
        "total_check_point": 7,
    })

    assert message is None
