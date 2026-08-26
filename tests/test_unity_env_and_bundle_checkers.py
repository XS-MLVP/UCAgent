#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for Bundle wrappers and environment fixture self-tests."""

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.checkers.unity_test import (
    UnityChipCheckerBundleWrapper,
    UnityChipCheckerTestMustPass,
)


def wpath(rel):
    return os.path.abspath(os.path.join(current_dir, rel))


def test_bundle_wrapper_success():
    workspace = wpath(".")
    target_file = "test_data/bundle_wrappers/good_bundle.py"
    checker = UnityChipCheckerBundleWrapper(target_file, min_bundles=1).set_workspace(workspace)
    p, m = checker.do_check()
    assert p is True
    assert "passed" in m.get("message", "").lower()


def test_bundle_wrapper_insufficient():
    workspace = wpath(".")
    target_file = "test_data/bundle_wrappers/bad_bundle.py"
    checker = UnityChipCheckerBundleWrapper(target_file, min_bundles=1).set_workspace(workspace)
    p, m = checker.do_check()
    assert p is False
    assert "Insufficient Bundle wrapper coverage" in m.get("error", "")


def test_env_fixture_test_success(tmp_path):
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    (test_dir / "test_Demo_env_fixture.py").write_text(
        "def test_api_Demo_env_basic(env):\n"
        "    assert env is not None\n",
        encoding="utf-8",
    )

    class _StubRunner:
        def set_pre_call_back(self, _callback):
            return self

        def do(self, *args, **kwargs):
            return (
                {
                    "run_test_success": True,
                    "tests": {
                        "total": 1,
                        "fails": 0,
                        "test_cases": {
                            "tests/test_Demo_env_fixture.py:1-2::"
                            "test_api_Demo_env_basic": "PASSED",
                        },
                    },
                },
                "",
                "",
            )

    checker = UnityChipCheckerTestMustPass(
        target_file="tests/test_Demo_env_fixture.py",
        test_dir="tests",
        test_prefix="test_api_Demo_env_",
        first_arg="env",
    ).set_workspace(str(tmp_path))
    checker.run_test = _StubRunner()

    p, m = checker.do_check(timeout=10)

    assert p is True
    assert "passed" in m.get("message", "").lower()


def test_env_fixture_test_wrong_prefix(tmp_path):
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    (test_dir / "test_Demo_env_fixture.py").write_text(
        "def test_env_wrong(env):\n"
        "    assert True\n",
        encoding="utf-8",
    )

    class _StubRunner:
        def set_pre_call_back(self, _callback):
            return self

        def do(self, *args, **kwargs):
            raise AssertionError("test execution must not start before validation")

    checker = UnityChipCheckerTestMustPass(
        target_file="tests/test_Demo_env_fixture.py",
        test_dir="tests",
        test_prefix="test_api_Demo_env_",
        first_arg="env",
    ).set_workspace(str(tmp_path))
    checker.run_test = _StubRunner()

    p, m = checker.do_check(timeout=10)

    assert p is False
    assert m["diagnostic"]["error_code"] == "TEST_FUNCTION_CONTRACT_VIOLATION"
    assert any("must start with 'test_api_Demo_env_'" in item for item in m["details"])
