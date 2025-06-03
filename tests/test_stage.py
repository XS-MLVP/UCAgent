#coding=utf-8

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from vagent.util.config import get_config
from vagent.stage.vstage import StageManager


def test_run_stage():
    cfg = get_config()
    cfg.update_template({
        "OUT": "output",
        "DUT": "DualPort"
    })
    print(cfg.dump_str())
    manager = StageManager(cfg, None)
    print(manager)


if __name__ == "__main__":
    test_run_stage()
