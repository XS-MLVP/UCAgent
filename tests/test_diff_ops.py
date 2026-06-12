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


def test_get_worktree_changed_files_includes_modified_untracked_and_deleted(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    diff_ops.init_git_repo(str(repo_dir))
    tracked_file = repo_dir / "tracked.txt"
    deleted_file = repo_dir / "deleted.txt"
    tracked_file.write_text("v1\n", encoding="utf-8")
    deleted_file.write_text("gone\n", encoding="utf-8")
    diff_ops.git_add_and_commit(str(repo_dir), "init")

    tracked_file.write_text("v2\n", encoding="utf-8")
    deleted_file.unlink()
    (repo_dir / "new.txt").write_text("hello\n", encoding="utf-8")

    changed_files = diff_ops.get_worktree_changed_files(str(repo_dir))

    assert changed_files == ["deleted.txt", "new.txt", "tracked.txt"]


def test_get_worktree_file_content_and_diff_for_untracked_file(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    diff_ops.init_git_repo(str(repo_dir))
    (repo_dir / "tracked.txt").write_text("base\n", encoding="utf-8")
    diff_ops.git_add_and_commit(str(repo_dir), "init")

    (repo_dir / "new.txt").write_text("hello\nworld\n", encoding="utf-8")

    payload = diff_ops.get_worktree_file_content_and_diff(str(repo_dir), "new.txt")

    assert payload["is_text"] is True
    assert payload["content"] == "hello\nworld\n"
    assert payload["error"] is None
    assert "--- a/new.txt" in payload["diff"]
    assert "+++ b/new.txt" in payload["diff"]
    assert "+hello" in payload["diff"]


def test_get_current_file_content_and_diff_from_commit_for_untracked_file(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    diff_ops.init_git_repo(str(repo_dir))
    (repo_dir / "tracked.txt").write_text("base\n", encoding="utf-8")
    commit_hash = diff_ops.git_add_and_commit(str(repo_dir), "init")

    (repo_dir / "new.txt").write_text("fresh\n", encoding="utf-8")

    payload = diff_ops.get_current_file_content_and_diff_from_commit(
        str(repo_dir),
        commit_hash,
        "new.txt",
    )

    assert payload["is_text"] is True
    assert payload["content"] == "fresh\n"
    assert payload["error"] is None
    assert "--- a/new.txt" in payload["diff"]
    assert "+++ b/new.txt" in payload["diff"]
    assert "+fresh" in payload["diff"]


def test_get_current_file_content_and_diff_from_commit_for_deleted_file(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    diff_ops.init_git_repo(str(repo_dir))
    deleted_file = repo_dir / "deleted.txt"
    deleted_file.write_text("gone\n", encoding="utf-8")
    commit_hash = diff_ops.git_add_and_commit(str(repo_dir), "init")

    deleted_file.unlink()

    payload = diff_ops.get_current_file_content_and_diff_from_commit(
        str(repo_dir),
        commit_hash,
        "deleted.txt",
    )

    assert payload["is_text"] is True
    assert payload["content"] == ""
    assert payload["error"] is None
    assert "--- a/deleted.txt" in payload["diff"]
    assert "+++ /dev/null" in payload["diff"]
    assert "-gone" in payload["diff"]


def test_get_commit_changed_file_statuses_marks_deleted_file(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    diff_ops.init_git_repo(str(repo_dir))
    deleted_file = repo_dir / "deleted.txt"
    deleted_file.write_text("gone\n", encoding="utf-8")
    diff_ops.git_add_and_commit(str(repo_dir), "init")

    deleted_file.unlink()
    commit_hash = diff_ops.git_add_and_commit(str(repo_dir), "delete file")

    assert diff_ops.get_commit_changed_file_statuses(str(repo_dir), commit_hash) == {"deleted.txt": "deleted"}
    assert diff_ops.get_commit_changed_files(str(repo_dir), commit_hash) == ["deleted.txt"]


def test_get_commit_file_content_and_diff_for_deleted_file(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    diff_ops.init_git_repo(str(repo_dir))
    deleted_file = repo_dir / "deleted.txt"
    deleted_file.write_text("gone\n", encoding="utf-8")
    diff_ops.git_add_and_commit(str(repo_dir), "init")

    deleted_file.unlink()
    commit_hash = diff_ops.git_add_and_commit(str(repo_dir), "delete file")

    payload = diff_ops.get_commit_file_content_and_diff(str(repo_dir), commit_hash, "deleted.txt")

    assert payload["is_text"] is True
    assert payload["content"] == ""
    assert payload["error"] is None
    assert payload["exists"] is False
    assert payload["status"] == "deleted"
    assert "--- a/deleted.txt" in payload["diff"]
    assert "+++ /dev/null" in payload["diff"]
    assert "-gone" in payload["diff"]


def test_git_add_and_commit_without_changes_keeps_previous_commit_message(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    diff_ops.init_git_repo(str(repo_dir))
    (repo_dir / "tracked.txt").write_text("v1\n", encoding="utf-8")
    first_hash = diff_ops.git_add_and_commit(str(repo_dir), "stage 1")
    second_hash = diff_ops.git_add_and_commit(str(repo_dir), "stage 2 no changes")

    assert second_hash == first_hash
    assert diff_ops.get_commit_message(str(repo_dir), second_hash).strip() == "stage 1"
