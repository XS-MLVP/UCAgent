#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for UnityChipCheckerBundleWrapper and UnityChipCheckerEnvFixtureTest."""

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

import pytest
from ucagent.checkers.unity_test import UnityChipCheckerBundleWrapper, UnityChipCheckerEnvFixtureTest


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


def test_env_fixture_test_success():
    workspace = wpath(".")
    # Use the good env test file and directory
    target_file = "test_data/env_tests/test_api_dummy_env_basic.py"
    test_dir = "test_data/env_tests"
    checker = UnityChipCheckerEnvFixtureTest(target_file=target_file, test_dir=test_dir, min_env_tests=1)
    # set dut_name to match the required prefix test_api_<dut>_env_
    checker.dut_name = "dummy"
    checker.set_workspace(workspace)
    # Inject a stub RunUnityChipTest to simulate a passing test run
    class _StubRunner:
        def do(self, *args, **kwargs):
            # Return a report with 1 total and 0 fails
            return ({"tests": {"total": 1, "fails": 0}}, "", "")
    checker.run_test = _StubRunner()
    p, m = checker.do_check(timeout=10)
    assert p is True
    assert "passed" in m.get("message", "").lower()


def test_env_fixture_test_wrong_prefix():
    workspace = wpath(".")
    # This file has a test function that does not match the required prefix
    target_file = "test_data/env_tests/test_wrong_name.py"
    test_dir = "test_data/env_tests"
    checker = UnityChipCheckerEnvFixtureTest(target_file=target_file, test_dir=test_dir, min_env_tests=1)
    checker.dut_name = "dummy"
    checker.set_workspace(workspace)
    # Inject stub to avoid calling real runner if code ever reaches it
    class _StubRunner:
        def do(self, *args, **kwargs):
            return ({"tests": {"total": 1, "fails": 0}}, "", "")
    checker.run_test = _StubRunner()
    p, m = checker.do_check(timeout=10)
    assert p is False
    assert "name must start with" in m.get("error", "")
