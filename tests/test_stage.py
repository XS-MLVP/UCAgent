#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test cases for stage modules."""

import os

current_dir = os.path.dirname(os.path.abspath(__file__))
import sys

sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.util.config import get_config
from ucagent.stage import StageManager
from ucagent.tools import ReadTextFile


def test_run_stage():
    cfg = get_config()
    cfg.un_freeze()
    template_dict = {"OUT": "unity_test", "DUT": "Adder"}
    cfg._temp_cfg = template_dict
    cfg.update_template(template_dict)
    workspace = os.path.join(current_dir, "../output")
    read_text = ReadTextFile(workspace)
    manager = StageManager(workspace, cfg, None, read_text, {}, tool_inspect_file=[])
    read_text.invoke({"path": "Guide_Doc/dut_bug_analysis.md"})
    read_text.invoke({"path": "Guide_Doc/dut_test_case.md"})
    # print(manager.tool_status())
    # print(manager.get_current_tips())
    # print(manager.tool_detail())
    print("")
    for f in [
        manager.tool_current_tips,
        manager.tool_detail,
        manager.tool_status,
        manager.tool_check,
        manager.tool_kill_check,
        manager.tool_std_check,
        manager.tool_complete,
        manager.tool_go_to_stage,
        manager.tool_exit,
    ]:
        print(f.__name__, ":")
        if f == manager.tool_check:
            f("")
        elif f == manager.tool_go_to_stage:
            f(0)
            f(1)
        else:
            f()


def test_init_stage_restores_completed_state():
    """Test that completed state is properly restored on re-entry."""
    cfg = get_config()
    cfg.un_freeze()
    template_dict = {"OUT": "unity_test", "DUT": "Adder"}
    cfg._temp_cfg = template_dict
    cfg.update_template(template_dict)
    workspace = os.path.join(current_dir, "../output")
    read_text = ReadTextFile(workspace)

    # First, create a temp manager to determine actual stage count
    temp_manager = StageManager(
        workspace, cfg, None, read_text, {}, force_stage_index=0, tool_inspect_file=[]
    )
    temp_manager.init_stage()
    num_stages = len(temp_manager.stages)

    # Create ucagent_info dict indicating all stages completed
    ucagent_info = {
        "all_completed": True,
        "stage_index": num_stages,
        "is_agent_exit": True,
        "stages_info": {},
    }

    manager = StageManager(
        workspace,
        cfg,
        None,
        read_text,
        ucagent_info,
        force_stage_index=num_stages,
        tool_inspect_file=[],
    )
    manager.init_stage()

    # Assert completed state is preserved
    assert manager.all_completed == True, "all_completed should be restored to True"
    assert manager.stage_index == len(manager.stages), (
        f"stage_index should equal {len(manager.stages)}, got {manager.stage_index}"
    )

    # Assert the "mission completed" message appears
    tips = manager.get_current_tips()
    assert "completed" in tips.lower() or "finish" in tips.lower(), (
        f"Should show completion message, got: {tips}"
    )


def test_init_stage_normal_resume():
    """Test that normal partial resume still works correctly."""
    cfg = get_config()
    cfg.un_freeze()
    template_dict = {"OUT": "unity_test", "DUT": "Adder"}
    cfg._temp_cfg = template_dict
    cfg.update_template(template_dict)
    workspace = os.path.join(current_dir, "../output")
    read_text = ReadTextFile(workspace)

    ucagent_info = {
        "all_completed": False,
        "stage_index": 1,
        "is_agent_exit": False,
        "stages_info": {},
    }

    manager = StageManager(
        workspace,
        cfg,
        None,
        read_text,
        ucagent_info,
        force_stage_index=1,
        tool_inspect_file=[],
    )
    manager.init_stage()

    # Assert normal resume behavior
    assert manager.stage_index == 1, (
        f"stage_index should be 1, got {manager.stage_index}"
    )
    assert manager.all_completed == False, (
        "all_completed should be False for partial resume"
    )

    # Assert NOT showing completion message
    tips = manager.get_current_tips()
    assert "mission is completed" not in tips.lower(), (
        f"Should NOT show completion message for partial resume, got: {tips}"
    )


def test_init_stage_no_oob_on_completed():
    """Regression test: Ensure no IndexError at boundary when all stages completed."""
    cfg = get_config()
    cfg.un_freeze()
    template_dict = {"OUT": "unity_test", "DUT": "Adder"}
    cfg._temp_cfg = template_dict
    cfg.update_template(template_dict)
    workspace = os.path.join(current_dir, "../output")
    read_text = ReadTextFile(workspace)

    # Determine actual stage count
    temp_manager = StageManager(
        workspace, cfg, None, read_text, {}, force_stage_index=0, tool_inspect_file=[]
    )
    temp_manager.init_stage()
    num_stages = len(temp_manager.stages)

    ucagent_info = {
        "all_completed": True,
        "stage_index": num_stages,
        "is_agent_exit": True,
        "stages_info": {},
    }

    manager = StageManager(
        workspace,
        cfg,
        None,
        read_text,
        ucagent_info,
        force_stage_index=num_stages,
        tool_inspect_file=[],
    )

    # This should NOT raise IndexError
    try:
        manager.init_stage()
        assert True, "init_stage completed without IndexError"
    except IndexError as e:
        raise AssertionError(
            f"IndexError raised during init_stage with completed state: {e}"
        )


def test_init_stage_defensive_large_index():
    """Test defensive bounds checking for malformed saved state with absurdly large index."""
    cfg = get_config()
    cfg.un_freeze()
    template_dict = {"OUT": "unity_test", "DUT": "Adder"}
    cfg._temp_cfg = template_dict
    cfg.update_template(template_dict)
    workspace = os.path.join(current_dir, "../output")
    read_text = ReadTextFile(workspace)

    # Determine actual stage count
    temp_manager = StageManager(
        workspace, cfg, None, read_text, {}, force_stage_index=0, tool_inspect_file=[]
    )
    temp_manager.init_stage()
    num_stages = len(temp_manager.stages)

    # Malformed state with absurdly large stage_index
    ucagent_info = {
        "all_completed": True,
        "stage_index": 999,
        "is_agent_exit": True,
        "stages_info": {},
    }

    manager = StageManager(
        workspace,
        cfg,
        None,
        read_text,
        ucagent_info,
        force_stage_index=999,
        tool_inspect_file=[],
    )
    manager.init_stage()

    # Should clamp to len(stages), not crash
    assert manager.stage_index == num_stages, (
        f"stage_index should be clamped to {num_stages}, got {manager.stage_index}"
    )
    assert manager.all_completed == True, "all_completed should still be True"


if __name__ == "__main__":
    test_run_stage()
