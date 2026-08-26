#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Restart and source-reconciliation tests for markdown batch checkers."""

import os
from pathlib import Path
import sys
from types import SimpleNamespace

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.checkers.file_markdown import BatchFileProcess, WalkFilesOneByOne


class _PassingBatchFileProcess(BatchFileProcess):
    def do_one_file_check(self, file_path):
        return True, file_path


class _MutatingBatchFileProcess(BatchFileProcess):
    def do_one_file_check(self, file_path):
        Path(self.workspace, file_path).write_text(
            "# changed during check\n", encoding="utf-8"
        )
        return True, file_path


def _checker(tmp_path):
    checker = _PassingBatchFileProcess(
        "markdown_files",
        "*.md",
        batch_size=1,
    ).set_workspace(str(tmp_path)).set_stage(
        SimpleNamespace(name="markdown_batch")
    )
    checker.on_init()
    return checker


def test_markdown_batch_restart_drops_deleted_pending_source(tmp_path):
    for name in ("a.md", "b.md"):
        (tmp_path / name).write_text(f"# {name}\n", encoding="utf-8")
    checker = _checker(tmp_path)

    passed, _message = checker.do_check()

    assert passed is False
    assert len(checker.batch_task.gen_task_list) == 1
    pending = checker.batch_task.tbd_task_list[0].split("@sha256=", 1)[0]
    (tmp_path / pending).unlink()

    restored = _checker(tmp_path)
    passed, _message = restored.do_check()

    assert passed is True
    assert restored.batch_task.source_task_list == restored.batch_task.gen_task_list
    assert restored.batch_task.tbd_task_list == []


def test_markdown_batch_requires_configured_minimum_input(tmp_path):
    checker = _checker(tmp_path)

    passed, message = checker.do_check()

    assert passed is False
    assert "No target files" in message["error"]


def test_markdown_batch_reports_corrupt_checkpoint(tmp_path):
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")
    checker = _checker(tmp_path)
    checker.batch_task.savepoint_file()
    Path(checker.batch_task.checkpoint_file).write_text("{", encoding="utf-8")

    restored = _checker(tmp_path)
    passed, message = restored.do_check()

    assert passed is False
    assert message["diagnostic"]["error_code"] == "BATCH_CHECKPOINT_INVALID"
    assert "@sha256=" not in str(message)


def test_markdown_batch_rechecks_completed_file_after_content_change(tmp_path):
    source = tmp_path / "a.md"
    source.write_text("# A\n", encoding="utf-8")
    checker = _checker(tmp_path)

    passed, _message = checker.do_check()

    assert passed is True
    original_task = checker.batch_task.gen_task_list[0]

    source.write_text("# A\n\nchanged\n", encoding="utf-8")
    restored = _checker(tmp_path)

    assert restored.batch_task.gen_task_list == []
    assert len(restored.batch_task.tbd_task_list) == 1
    assert restored.batch_task.tbd_task_list[0] != original_task
    assert restored.get_template_data()["CURRENT_FILES"] == ["a.md"]

    passed, _message = restored.do_check()

    assert passed is True
    assert len(restored.batch_task.gen_task_list) == 1


def test_walk_file_read_evidence_is_invalidated_by_content_change(tmp_path):
    source = tmp_path / "a.md"
    source.write_text("# A\n", encoding="utf-8")
    checker = WalkFilesOneByOne(
        "walk_markdown",
        "*.md",
    ).set_workspace(str(tmp_path))
    checker.stage_manager = SimpleNamespace(
        tool_read_text=SimpleNamespace(name="ReadTextFile")
    )

    checker.on_file_read(True, "a.md", "")
    assert checker.do_one_file_check("a.md")[0] is True

    source.write_text("# A\n\nchanged\n", encoding="utf-8")
    passed, message = checker.do_one_file_check("a.md")

    assert passed is False
    assert "was not read" in message


def test_markdown_batch_does_not_commit_file_changed_during_check(tmp_path):
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")
    checker = _MutatingBatchFileProcess(
        "markdown_files",
        "*.md",
        batch_size=1,
    ).set_workspace(str(tmp_path)).set_stage(
        SimpleNamespace(name="markdown_batch")
    )
    checker.on_init()

    passed, message = checker.do_check()

    assert passed is False
    assert message["diagnostic"]["error_code"] == (
        "MARKDOWN_BATCH_SOURCE_CHANGED_DURING_CHECK"
    )
    assert checker.batch_task.gen_task_list == []
    assert checker.get_template_data()["CURRENT_FILES"] == ["a.md"]
