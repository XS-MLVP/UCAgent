#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scope of the infrastructure-only all-Pass checker."""

from ucagent.checkers.unity_test import UnityChipCheckerTestMustPass


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
