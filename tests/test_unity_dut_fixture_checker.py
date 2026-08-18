#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for DUT fixture functional coverage validation."""

import json
import os
import sys
from types import SimpleNamespace

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

import ucagent.util.functions as fc
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


def test_dut_fixture_rejects_conditional_set_func_coverage(tmp_path):
    passed, message = _check_fixture(tmp_path, [
        "func_coverage_group = []",
        "get_coverage_data_path(request, new_path=False)",
        "yield object()",
        "if False:",
        "    set_func_coverage(request, func_coverage_group)",
    ])

    assert passed is False
    assert "unconditional teardown path" in message["error"]


def test_dut_fixture_accepts_set_func_coverage_in_finally(tmp_path):
    passed, message = _check_fixture(tmp_path, [
        "func_coverage_group = []",
        "get_coverage_data_path(request, new_path=False)",
        "try:",
        "    yield object()",
        "finally:",
        "    set_func_coverage(request, func_coverage_group)",
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


def _api_checker(api_ck_prefix="FG-API/"):
    return UnityChipCheckerDutApiTest(
        "api_Demo_",
        "dut_api.py",
        "test_Demo_api.py",
        "functions_and_checks.md",
        "bug_analysis.md",
        api_ck_prefix=api_ck_prefix,
    )


def _api_association_report(checkpoints, include_mapping=True):
    test_case = "test_Demo_api.py:1-3::test_api_Demo_operate"
    report = {
        "tests": {
            "total": 1,
            "fails": 0,
            "test_cases": {test_case: "PASSED"},
        },
    }
    if include_mapping:
        report["test_case_with_check_point_list"] = {test_case: checkpoints}
    return report


def test_api_checker_rejects_only_non_api_checkpoint_associations():
    message = _api_checker()._missing_api_checkpoint_association_message(
        _api_association_report(["FG-ARITHMETIC/FC-ADD/CK-NORMAL"])
    )

    assert "[API Checkpoint Association Missing]" in message
    assert "FG-ARITHMETIC/FC-ADD/CK-NORMAL" in message
    assert "optional additions" in message
    assert "cannot replace the required API-group relation" in message
    assert "Do not mark unrelated API checkpoints" in message


def test_api_checker_accepts_api_and_optional_other_group_associations():
    message = _api_checker()._missing_api_checkpoint_association_message(
        _api_association_report([
            "FG-API/FC-OPERATE/CK-BASIC",
            "FG-ARITHMETIC/FC-ADD/CK-NORMAL",
        ])
    )

    assert message is None


def test_api_checker_honors_configured_api_checkpoint_prefix():
    report = _api_association_report(["FG-PUBLIC-API/FC-OPERATE/CK-BASIC"])

    assert (
        _api_checker("FG-PUBLIC-API")
        ._missing_api_checkpoint_association_message(report)
        is None
    )
    assert (
        "[API Checkpoint Association Missing]"
        in _api_checker()._missing_api_checkpoint_association_message(report)
    )


def test_api_checker_rejects_report_without_per_test_checkpoint_mapping():
    message = _api_checker()._missing_api_checkpoint_association_message(
        _api_association_report([], include_mapping=False)
    )

    assert "[API Checkpoint Mapping Unavailable]" in message
    assert "Rerun the API tests, then call Check or Complete" in message
    assert "do not infer completion from global checkpoint totals" in message


def test_toffee_report_preserves_all_checkpoint_associations_per_test(tmp_path):
    test_case = "test_Demo_api.py:1-3::test_api_Demo_operate"
    (tmp_path / "test_Demo_api.py").write_text(
        "def test_api_Demo_operate(env):\n    assert True\n",
        encoding="utf-8",
    )
    report_file = tmp_path / "toffee_report.json"
    report_file.write_text(
        json.dumps({
            "test_abstract_info": {test_case: "PASSED"},
            "coverages": {
                "functional": {
                    "point_num_total": 2,
                    "point_num_hints": 2,
                    "bin_num_total": 2,
                    "bin_num_hints": 2,
                    "groups": [
                        {
                            "name": "FG-API",
                            "points": [{
                                "name": "FC-OPERATE",
                                "functions": {"CK-BASIC": [test_case]},
                                "bins": [{"name": "CK-BASIC", "hints": 1}],
                            }],
                        },
                        {
                            "name": "FG-ARITHMETIC",
                            "points": [{
                                "name": "FC-ADD",
                                "functions": {"CK-NORMAL": [test_case]},
                                "bins": [{"name": "CK-NORMAL", "hints": 1}],
                            }],
                        },
                    ],
                },
            },
        }),
        encoding="utf-8",
    )

    report = fc.load_toffee_report(
        str(report_file),
        str(tmp_path),
        run_test_success=True,
        return_all_checks=True,
    )

    assert report["test_case_with_check_point_list"] == {
        test_case: [
            "FG-API/FC-OPERATE/CK-BASIC",
            "FG-ARITHMETIC/FC-ADD/CK-NORMAL",
        ],
    }
    assert "test_case_with_check_point_list" not in fc.clean_report_with_keys(report)


def test_mark_function_diagnostic_treats_comment_as_missing_call(tmp_path):
    (tmp_path / "test_Demo_api.py").write_text(
        "def test_api_Demo_operate(env):\n"
        "    # env.dut.fc_cover['FG-API'].mark_function('FC-OPERATE', test_api_Demo_operate, ['CK-BASIC'])\n"
        "    assert True\n",
        encoding="utf-8",
    )

    message = fc.description_mark_function_doc(
        ["test_Demo_api.py:1-3::test_api_Demo_operate"],
        str(tmp_path),
    )

    assert "[Call missing]" in message
    assert "No executable `mark_function` call" in message
    assert "[Call present, association absent]" not in message


def test_mark_function_diagnostic_explains_unrecorded_call(tmp_path):
    (tmp_path / "test_Demo_api.py").write_text(
        "def test_api_Demo_operate(env):\n"
        "    env.dut.fc_cover['FG-API'].mark_function(\n"
        "        'FC-OPERATE', test_api_Demo_operate, ['CK-BASIC']\n"
        "    )\n"
        "    assert True\n",
        encoding="utf-8",
    )

    callback_called = False

    def unexpected_rerun(**kwargs):
        nonlocal callback_called
        callback_called = True
        raise AssertionError(f"diagnostic unexpectedly reran tests: {kwargs}")

    message = fc.description_mark_function_doc(
        ["test_Demo_api.py:1-5::test_api_Demo_operate"],
        str(tmp_path),
        func_RunTestCases=unexpected_rerun,
        timeout_RunTestCases=30,
    )

    assert "[Call present, association absent]" in message
    assert "Do not add a duplicate call" in message
    assert "FG/FC/CK names exactly match" in message
    assert "set_func_coverage" in message
    assert "Check/Complete result" in message
    assert "`STDERR`" in message
    assert "`STDOUT`" in message
    assert "RunTestCases" not in message
    assert callback_called is False
    assert "encountered errors" not in message


def test_mark_function_diagnostic_preserves_hash_inside_string(tmp_path):
    (tmp_path / "test_Demo_api.py").write_text(
        "def test_api_Demo_operate(env):\n"
        "    note = '# is part of this string'\n"
        "    env.dut.fc_cover['FG-API'].mark_function(\n"
        "        'FC-OPERATE', test_api_Demo_operate, ['CK-BASIC']\n"
        "    )\n"
        "    assert note\n",
        encoding="utf-8",
    )

    message = fc.description_mark_function_doc(
        ["test_Demo_api.py:1-6::test_api_Demo_operate"],
        str(tmp_path),
    )

    assert "[Call present, association absent]" in message
    assert "[Call missing]" not in message


def test_api_checker_reports_checkpoint_association_cause(tmp_path):
    (tmp_path / "dut_api.py").write_text(
        "def api_Demo_operate(env):\n    return None\n",
        encoding="utf-8",
    )
    (tmp_path / "test_Demo_api.py").write_text(
        "def test_api_Demo_operate(env):\n"
        "    env.dut.fc_cover['FG-API'].mark_function(\n"
        "        'FC-OPERATE', test_api_Demo_operate, ['CK-BASIC']\n"
        "    )\n"
        "    assert True\n",
        encoding="utf-8",
    )
    (tmp_path / "functions_and_checks.md").write_text(
        "<FG-API>\n<FC-OPERATE>\n<CK-BASIC>\n",
        encoding="utf-8",
    )
    report = {
        "run_test_success": True,
        "tests": {
            "total": 1,
            "fails": 0,
            "test_cases": {
                "test_Demo_api.py:1-5::test_api_Demo_operate": "PASSED",
            },
        },
        "total_funct_point": 1,
        "total_check_point": 1,
        "test_function_with_no_check_point_mark": 1,
        "test_function_with_no_check_point_mark_list": [
            "test_Demo_api.py:1-5::test_api_Demo_operate",
        ],
    }
    checker = UnityChipCheckerDutApiTest(
        "api_Demo_",
        "dut_api.py",
        "test_Demo_api.py",
        "functions_and_checks.md",
        "bug_analysis.md",
    ).set_workspace(str(tmp_path))
    checker.run_test = SimpleNamespace(
        do=lambda *args, **kwargs: (
            report,
            "original pytest output",
            "original Toffee mark_function warning",
        )
    )

    passed, message = checker.do_check()

    assert passed is False
    assert "[Checkpoint Association Missing]" in message["error"]
    assert "Toffee did not record any checkpoint association" in message["error"]
    assert "[Call present, association absent]" in message["error"]
    assert "Do not add a duplicate call" in message["error"]
    assert message["STDOUT"] == "original pytest output"
    assert message["STDERR"] == "original Toffee mark_function warning"
    assert "RunTestCases" not in message["error"]
