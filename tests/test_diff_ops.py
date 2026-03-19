#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for diff_ops repository resource cleanup."""

import os
import sys

import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.util import diff_ops


def _num_fds() -> int | None:
    fd_dir = "/dev/fd"
    if not os.path.isdir(fd_dir):
        return None
    return len(os.listdir(fd_dir))


def test_get_commit_changed_files_releases_repo_handles(tmp_path):
    baseline = _num_fds()
    if baseline is None:
        pytest.skip("/dev/fd is not available on this platform")

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    diff_ops.init_git_repo(str(repo_dir))

    tracked_file = repo_dir / "tracked.txt"
    tracked_file.write_text("v1\n", encoding="utf-8")
    diff_ops.git_add_and_commit(str(repo_dir), "init")

    tracked_file.write_text("v2\n", encoding="utf-8")
    commit_hash = diff_ops.git_add_and_commit(str(repo_dir), "update")

    for _ in range(80):
        changed_files = diff_ops.get_commit_changed_files(str(repo_dir), commit_hash)
        assert changed_files == ["tracked.txt"]

    after = _num_fds()
    assert after is not None
    assert after - baseline < 5
