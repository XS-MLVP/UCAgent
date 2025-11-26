#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for UnityChipCheckerMockComponent."""

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

import pytest
from ucagent.checkers.unity_test import UnityChipCheckerMockComponent


def wpath(rel):
    return os.path.abspath(os.path.join(current_dir, rel))


def test_mock_checker_success():
    workspace = wpath(".")
    target_file = "test_data/mock_components/good_mocks.py"
    checker = UnityChipCheckerMockComponent(target_file, min_mock=2).set_workspace(workspace)
    p, m = checker.do_check()
    assert p is True
    assert "passed" in m.get("message", "").lower()


def test_mock_checker_file_not_exists():
    workspace = wpath(".")
    target_file = "test_data/mock_components/not_exists.py"
    checker = UnityChipCheckerMockComponent(target_file, min_mock=1).set_workspace(workspace)
    p, m = checker.do_check()
    assert p is False
    assert "does not exist" in m.get("error", "")


def test_mock_checker_bad_prefix():
    workspace = wpath(".")
    target_file = "test_data/mock_components/bad_prefix.py"
    checker = UnityChipCheckerMockComponent(target_file, min_mock=1).set_workspace(workspace)
    p, m = checker.do_check()
    assert p is False
    # Since classes are filtered by pattern 'Mock*', a file without any Mock* classes
    # should trigger insufficient coverage instead of bad prefix message.
    assert "Insufficient Mock component coverage" in m.get("error", "")


def test_mock_checker_missing_method():
    workspace = wpath(".")
    target_file = "test_data/mock_components/missing_method.py"
    checker = UnityChipCheckerMockComponent(target_file, min_mock=1).set_workspace(workspace)
    p, m = checker.do_check()
    assert p is False
    assert "missing the required method 'on_clock_edge" in m.get("error", "")


def test_mock_checker_wrong_signature():
    workspace = wpath(".")
    target_file = "test_data/mock_components/wrong_signature.py"
    checker = UnityChipCheckerMockComponent(target_file, min_mock=1).set_workspace(workspace)
    p, m = checker.do_check()
    assert p is False
    assert "must have exactly two arguments" in m.get("error", "")


def test_mock_checker_insufficient_mocks():
    workspace = wpath(".")
    target_file = "test_data/mock_components/good_mocks.py"
    checker = UnityChipCheckerMockComponent(target_file, min_mock=3).set_workspace(workspace)
    p, m = checker.do_check()
    assert p is False
    assert "Insufficient Mock component coverage" in m.get("error", "")
