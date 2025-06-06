#coding=utf-8

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from vagent.util.config import get_config
from vagent.stage.vstage import StageManager


def test_run_stage():
    cfg = get_config()
    cfg.un_freeze()
    cfg.update_template({
        "OUT": "output",
        "DUT": "DualPort"
    })
    cfg.freeze()
    manager = StageManager(current_dir, cfg, None)
    #print(manager.tool_status())
    #print(manager.get_current_tips())
    print(manager.tool_detail())


if __name__ == "__main__":
    test_run_stage()
