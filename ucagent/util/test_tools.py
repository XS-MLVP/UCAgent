#coding=utf-8
"""Framework self-location helpers for the running ucagent installation."""

import os


def ucagent_lib_path():
    """return ucagent lib path"""
    return os.path.abspath(__file__).split(os.sep + "ucagent" + os.sep)[0]
