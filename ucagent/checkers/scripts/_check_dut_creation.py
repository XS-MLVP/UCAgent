# -*- coding: utf-8 -*-
"""Isolated checker: DUT creation function validation.

Logic extracted from UnityChipCheckerDutCreation.do_check — kept exactly
equivalent so that both the direct call and subprocess paths run the same code.
"""

import os
import inspect
import ucagent.util.functions as fc


def check_create_dut(target_file_path, workspace, source_code_need=None, **kw):
    """Check the create_dut function for correctness.

    Args:
        target_file_path: Absolute path to the file containing create_dut.
        workspace: Absolute path to the workspace.
        source_code_need: Dict of {pattern: (message, tip_func_or_None)}.
            When called from subprocess, tip_func is always None (not serializable).

    Returns:
        Tuple[bool, dict]
    """
    if not os.path.exists(target_file_path):
        return False, {"error": f"file '{target_file_path}' does not exist."}

    func_list = fc.get_target_from_file(
        target_file_path, "create_dut",
        ex_python_path=workspace, dtype="FUNC"
    )
    if not func_list:
        return False, {"error": f"No 'create_dut' functions found in '{target_file_path}'."}
    if len(func_list) != 1:
        return False, {"error": f"Multiple 'create_dut' functions found in '{target_file_path}'. Expected only one."}

    cdut_func = func_list[0]
    args = fc.get_func_arg_list(cdut_func)

    # check args
    if len(args) != 1 or args[0] != "request":
        return False, {"error": f"The 'create_dut' fixture has only one arg named 'request', but got ({', '.join(args)})."}

    dut = func_list[0](None)
    for need_func in ["Step", "StepRis"]:
        if not hasattr(dut, need_func):
            return False, {"error": f"The 'create_dut' function in '{target_file_path}' did not return a valid DUT instance with '{need_func}' method."}

    # check source code patterns
    func_source = inspect.getsource(cdut_func)
    if source_code_need:
        for k, v in source_code_need.items():
            if isinstance(v, (list, tuple)):
                message, tip_func = v[0], v[1] if len(v) > 1 else None
            else:
                message, tip_func = v, None
            if callable(tip_func):
                dut_name = kw.get("dut_name")
                if dut_name:
                    message += f" {tip_func(dut_name)}"
            if k not in func_source:
                return False, {"error": message}

    return True, {"message": f"create_dut check passed for '{target_file_path}'."}
