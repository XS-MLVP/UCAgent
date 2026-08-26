#!/usr/bin/env python3
"""Execution-state and target-path tests for pytest tools."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ucagent.tools.testops import (
    RunPyTest,
    RunUnityChipTest,
    _classify_pytest_execution,
)
from ucagent.util.functions import load_toffee_report


def test_run_pytest_rejects_repeated_test_directory_prefix(tmp_path):
    test_dir = tmp_path / "unity_test" / "tests"
    test_dir.mkdir(parents=True)
    (test_dir / "test_demo.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    tool = RunPyTest()

    passed, _stdout, stderr = tool.do(
        str(test_dir),
        pytest_ex_args="unity_test/tests/test_demo.py::test_ok",
        return_stderr=True,
    )

    assert passed is False
    assert tool.last_execution["diagnostic_code"] == (
        "PYTEST_TARGET_DIRECTORY_PREFIX"
    )
    diagnostic = json.loads(stderr)
    assert diagnostic["provided_target"] == (
        "unity_test/tests/test_demo.py::test_ok"
    )
    assert diagnostic["correct_target"] == "test_demo.py::test_ok"
    assert diagnostic["pytest_working_directory"] == str(test_dir)


def test_run_pytest_relative_target_executes_without_identity_rewrite(tmp_path):
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    (test_dir / "test_demo.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    tool = RunPyTest()

    passed, stdout, stderr = tool.do(
        str(test_dir),
        pytest_ex_args="test_demo.py::test_ok",
        return_stdout=True,
        return_stderr=True,
    )

    assert passed is True
    assert tool.last_execution["diagnostic_code"] == "OK"
    assert "1 passed" in stdout
    assert stderr == ""


def test_run_pytest_missing_target_preserves_pytest_diagnostic(tmp_path):
    tool = RunPyTest()

    passed, _stdout, stderr = tool.do(
        str(tmp_path),
        pytest_ex_args="missing.py::test_missing",
        return_stderr=True,
    )

    assert passed is False
    assert tool.last_execution["diagnostic_code"] == "PYTEST_TARGET_NOT_FOUND"
    assert "file or directory not found" in stderr


def test_run_pytest_collection_error_is_not_reported_as_a_test_run(tmp_path):
    test_file = tmp_path / "test_broken.py"
    test_file.write_text("def test_broken(:\n    pass\n", encoding="utf-8")
    tool = RunPyTest()

    passed, stdout, stderr = tool.do(
        str(tmp_path),
        pytest_ex_args="test_broken.py",
        return_stdout=True,
        return_stderr=True,
    )

    assert passed is False
    assert tool.last_execution["invocation_success"] is False
    assert tool.last_execution["diagnostic_code"] == "PYTEST_COLLECTION_ERROR"
    assert "SyntaxError" in stdout + stderr


def test_assertion_failure_requires_a_nonempty_report_to_be_usable():
    without_report = _classify_pytest_execution(
        1, "1 failed", "", report_exists=False, report_has_tests=False
    )
    with_report = _classify_pytest_execution(
        1, "1 failed", "", report_exists=True, report_has_tests=True
    )

    assert without_report["diagnostic_code"] == "PYTEST_ASSERTION_FAILURE"
    assert without_report["invocation_success"] is False
    assert with_report["diagnostic_code"] == "PYTEST_ASSERTION_FAILURE"
    assert with_report["invocation_success"] is True


def test_runtime_file_error_is_not_mislabeled_as_a_missing_pytest_target():
    execution = _classify_pytest_execution(
        1,
        "FileNotFoundError: [Errno 2] No such file or directory: 'vectors.json'",
        "",
        report_exists=True,
        report_has_tests=True,
    )

    assert execution["diagnostic_code"] == "PYTEST_ASSERTION_FAILURE"
    assert execution["invocation_success"] is True


@pytest.mark.parametrize(
    ("report_content", "expected_code"),
    [
        (None, "TOFFEE_REPORT_MISSING"),
        ("{invalid json", "TOFFEE_REPORT_INVALID"),
    ],
)
def test_unity_test_reports_missing_or_invalid_toffee_output(
    tmp_path, monkeypatch, report_content, expected_code
):
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    tool = RunUnityChipTest(workspace=str(tmp_path), report_dir="report")

    def fake_run_pytest(self, *_args, **_kwargs):
        self.last_execution = {
            "pytest_returncode": 0,
            "invocation_success": True,
            "diagnostic_code": "OK",
            "report_exists": False,
            "report_has_tests": False,
        }
        self._last_process_stdout = "1 passed"
        self._last_process_stderr = ""
        if report_content is not None:
            report_dir = Path(self.result_dir)
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / self.result_json_path).write_text(
                report_content, encoding="utf-8"
            )
        return True, "1 passed", ""

    monkeypatch.setattr(RunPyTest, "do", fake_run_pytest)

    report, _stdout, _stderr = tool.do("tests")

    assert report["run_test_success"] is False
    assert report["execution"]["diagnostic_code"] == expected_code
    assert report["execution"]["pytest_diagnostic_code"] == "OK"
    assert report["execution"]["invocation_success"] is False


def test_toffee_report_lists_only_failed_parameterized_instances(tmp_path):
    test_file = tmp_path / "unity_test" / "tests" / "test_demo.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "def test_value(value):\n    assert value == 0\n", encoding="utf-8"
    )
    abstract_key = f"{test_file}:1-2::test_value"

    def raw_test(node: str, status: str) -> dict:
        outcome = status.lower()
        return {
            "phases": [
                {
                    "report": (
                        f"<TestReport 'tests/test_demo.py::{node}' "
                        f"when='call' outcome='{outcome}'>"
                    ),
                    "status": {"word": status},
                }
            ],
            "status": {"word": status},
        }

    report_path = tmp_path / "toffee_report.json"
    report_path.write_text(
        json.dumps(
            {
                "test_abstract_info": {abstract_key: "FAILED"},
                "tests": [
                    raw_test("test_value[0]", "PASSED"),
                    raw_test("test_value[1]", "FAILED"),
                ],
                "coverages": {"functional": {}},
            }
        ),
        encoding="utf-8",
    )

    report = load_toffee_report(
        str(report_path), str(tmp_path), True, return_all_checks=False
    )

    assert report["tests"]["test_case_instances"] == {
        "unity_test/tests/test_demo.py::test_value": [
            {
                "node_id": "unity_test/tests/test_demo.py::test_value[1]",
                "status": "FAILED",
            }
        ]
    }
