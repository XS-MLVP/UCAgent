#coding=utf-8

import os
from ucagent.util.log import warning


def ucagent_lib_path():
    """return ucagent lib path"""
    return os.path.abspath(__file__).split(os.sep + "ucagent" + os.sep)[0]


def repeat_count():
    """test repeat count"""
    default_v = 3
    n = os.environ.get("UC_TEST_RCOUNT", f"{default_v}").strip()
    try:
        return int(n)
    except Exception as e:
        warning(f"convert os.env['UC_TEST_RCOUNT']({n}) to Int value fail: {e}, use default 3")
        return default_v
