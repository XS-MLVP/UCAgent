#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scope of the infrastructure-only all-Pass checker."""

from types import SimpleNamespace

from ucagent.checkers.unity_test import UnityChipCheckerTestMustPass
from ucagent.checkers.unity_test_mock import UnityChipCheckerTestMockTestBatch


class _FailedInfrastructureRunner:
    def set_workspace(self, _workspace):
        return self

    def set_pre_call_back(self, _callback):
        return self

    def do(self, *_args, **_kwargs):
        return (
            {
                "run_test_success": True,
                "tests": {
                    "total": 1,
                    "fails": 1,
                    "test_cases": {"tests/test_mock.py::test_mock": "FAILED"},
                },
            },
            "",
            "",
        )


def test_all_pass_checker_explains_its_infrastructure_only_scope(tmp_path):
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    (test_dir / "test_mock.py").write_text(
        "def test_mock():\n    assert True\n",
        encoding="utf-8",
    )
    checker = UnityChipCheckerTestMustPass(
        target_file="tests/test_mock.py",
        test_dir="tests",
        test_prefix="test_",
    ).set_workspace(str(tmp_path))
    checker.run_test = _FailedInfrastructureRunner()

    passed, message = checker.do_check(timeout=10)

    assert passed is False
    assert "[Infrastructure Self-Test Failure]" in message["error"]
    assert "do not record these failures as DUT Bugs" in message["error"]
    assert "does not apply" in message["error"]
    assert "real DUT design Bugs" in message["error"]


def test_all_pass_checker_returns_all_test_function_contract_issues(tmp_path):
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    (test_dir / "test_env.py").write_text(
        "raise AssertionError('test module must not be imported before contract validation')\n\n"
        "def test_wrong_prefix(other):\n"
        "    assert True\n\n"
        "def test_api_Demo_env_wrong_arg(other):\n"
        "    assert True\n",
        encoding="utf-8",
    )
    checker = UnityChipCheckerTestMustPass(
        target_file="tests/test_env.py",
        test_dir="tests",
        test_prefix="test_api_Demo_env_",
        first_arg="env",
    ).set_workspace(str(tmp_path))

    passed, message = checker.do_check(timeout=10)

    assert passed is False
    diagnostic = message["diagnostic"]
    assert diagnostic["error_code"] == "TEST_FUNCTION_CONTRACT_VIOLATION"
    assert diagnostic["issue_count"] == 3
    assert diagnostic["observed"]["issue_count"] == 3
    assert diagnostic["observed"]["issues"] == message["details"]
    assert any(
        "test_wrong_prefix" in issue
        for issue in diagnostic["observed"]["issues"]
    )
    assert any(
        "test_api_Demo_env_wrong_arg" in issue
        for issue in diagnostic["observed"]["issues"]
    )
    assert any("tests/test_env.py:3-3" in issue for issue in message["details"])
    assert any("tests/test_env.py:6-6" in issue for issue in message["details"])
    assert sum(
        "tests/test_env.py:3-3" in issue for issue in message["details"]
    ) == 2
    assert diagnostic["next_action"].endswith("call `Check` again.")


def test_mock_batch_checker_uses_the_same_explicit_diagnostic_contract(tmp_path):
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    test_file = test_dir / "test_Demo_mock_unit.py"
    test_file.write_text(
        "raise AssertionError('test module must not be imported before contract validation')\n\n"
        "def test_wrong_prefix(mock_dut):\n"
        "    assert True\n",
        encoding="utf-8",
    )
    checker = UnityChipCheckerTestMockTestBatch(
        target_file="tests/Demo_mock_*.py",
        test_file_prefix="test_Demo_mock_",
        test_prefix="test_api_Demo_mock_",
        first_arg="mock_dut",
        cfg={"_temp_cfg": {"DUT": "Demo"}},
    ).set_workspace(str(tmp_path))

    passed, message = checker.do_one_check(
        ["tests/test_Demo_mock_unit.py"],
        str(test_dir),
        timeout=10,
        retry_tool="Complete",
    )

    assert passed is False
    assert message["diagnostic"]["error_code"] == (
        "TEST_FUNCTION_CONTRACT_VIOLATION"
    )
    assert message["diagnostic"]["observed"]["issue_count"] == 1
    assert "tests/test_Demo_mock_unit.py:3-3" in message["details"][0]
    assert message["diagnostic"]["next_action"].endswith(
        "call `Complete` again."
    )


def test_mock_batch_checker_checks_only_current_batch(tmp_path):
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    for name in ("a", "b"):
        (test_dir / f"Demo_mock_{name}.py").write_text("", encoding="utf-8")
        (test_dir / f"test_Demo_mock_{name}.py").write_text(
            "def test_api_Demo_mock_case(mock_dut):\n    assert True\n",
            encoding="utf-8",
        )

    checker = UnityChipCheckerTestMockTestBatch(
        target_file="tests/Demo_mock_*.py",
        test_file_prefix="test_Demo_mock_",
        test_prefix="test_api_Demo_mock_",
        first_arg="mock_dut",
        batch_size=1,
        cfg={"_temp_cfg": {"DUT": "Demo"}},
    ).set_workspace(str(tmp_path)).set_stage(
        SimpleNamespace(name="test_mock_components_in_batch")
    )
    checker.on_init()
    checked_test_files = []

    def pass_current(target_tests, *_args, **_kwargs):
        checked_test_files.extend(target_tests)
        return True, "pass"

    checker.do_one_check = pass_current
    passed, _message = checker.do_check()

    assert passed is False
    assert len(checked_test_files) == 1
    assert len(checker.batch_task.gen_task_list) == 1
    assert len(checker.batch_task.tbd_task_list) == 1

    pending_source = tmp_path / checker.batch_task.tbd_task_list[0]
    pending_source.unlink()
    passed, _message = checker.do_check()

    assert passed is True
    assert checker.batch_task.tbd_task_list == []
