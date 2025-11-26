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
    cfg.update_template({
        "OUT": "unity_test",
        "DUT": "Adder"
    })
    cfg.freeze()
    workspace = os.path.join(current_dir, "../output")
    read_text = ReadTextFile(workspace)
    manager = StageManager(workspace, cfg, None, read_text)
    read_text.invoke({"path": "Guide_Doc/dut_bug_analysis.md"})
    read_text.invoke({"path": "Guide_Doc/dut_test_case.md"})
    #print(manager.tool_status())
    #print(manager.get_current_tips())
    #print(manager.tool_detail())
    print("")
    for f in [manager.tool_current_tips,
             manager.tool_detail,
             manager.tool_status,
             manager.tool_check,
             manager.tool_kill_check,
             manager.tool_std_check,
             manager.tool_complete,
             manager.tool_go_to_stage,
             manager.tool_exit]:
        print(f.__name__, ":")
        if f == manager.tool_check:
            f("")
        elif f == manager.tool_go_to_stage:
            f(0)
            f(1)
        else:
            f()


if __name__ == "__main__":
    test_run_stage()
