#coding=utf-8

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from vagent.util.config import get_config
from vagent.stage.vstage import StageManager
from vagent.tools import ReadTextFile

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
    for stage in manager.stages:
        print(stage.name)

    s_run_test = manager.stages[-1]
    print(s_run_test.do_check())

if __name__ == "__main__":
    test_run_stage()
