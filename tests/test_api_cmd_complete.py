#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for CMD API complete-list summary helpers."""

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(current_dir, ".."))
repo_package_root = os.path.join(repo_root, "ucagent")
sys.path.insert(0, repo_root)

loaded_ucagent = sys.modules.get("ucagent")
loaded_ucagent_path = os.path.abspath(getattr(loaded_ucagent, "__file__", "") or "")
if loaded_ucagent is not None and not loaded_ucagent_path.startswith(repo_package_root + os.sep):
    for module_name in list(sys.modules):
        if module_name == "ucagent" or module_name.startswith("ucagent."):
            del sys.modules[module_name]

from ucagent.runtime.workspace.queries import mission_name, workspace_lifecycle


def test_complete_summary_uses_saved_mission_name(tmp_path):
    workspace = tmp_path / "sub-workspace"
    workspace.mkdir()

    assert (
        mission_name(str(workspace), {"mission_name": "Formal Mission"})
        == "Formal Mission"
    )
    assert (
        mission_name(str(workspace), {"mission": {"name": "Dict Mission"}})
        == "Dict Mission"
    )
    assert mission_name(str(workspace), {}) == "sub-workspace"


def test_complete_summary_marks_explicit_exit_as_exited():
    assert workspace_lifecycle({"is_agent_exit": True}) == "exited"
    assert (
        workspace_lifecycle(
            {"is_agent_exit": True, "all_completed": True}
        )
        == "completed"
    )
    assert (
        workspace_lifecycle(
            {"is_wait_human_check": True, "all_completed": False}
        )
        == "waiting"
    )
    assert workspace_lifecycle({"all_completed": True}) == "completed"
    assert workspace_lifecycle({}) == "running"
