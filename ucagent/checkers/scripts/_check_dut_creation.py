#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared check logic for DUT creation — extracted from origin/main do_check."""

import inspect
import ucagent.util.functions as fc


def check_create_dut(target_file_path, workspace, source_code_need):
    """Validate create_dut, returns (bool, dict).

    Args:
        target_file_path: Absolute path to the target file.
        workspace: Workspace directory path.
        source_code_need: Dict {key: (error_msg, tip_func)} for source checks.

    Returns:
        (success: bool, result: dict)
    """
    func_list = fc.get_target_from_file(target_file_path, "create_dut",
                                        ex_python_path=workspace,
                                        dtype="FUNC")
    if not func_list:
        return False, {"error": f"No 'create_dut' functions found in '{target_file_path}'."}
    if len(func_list) != 1:
        return False, {"error": f"Multiple 'create_dut' functions found in '{target_file_path}'. Expected only one."}
    cdut_func = func_list[0]
    args = fc.get_func_arg_list(cdut_func)
    if len(args) != 1 or args[0] != "request":
        return False, {"error": f"The 'create_dut' fixture has only one arg named 'request', but got ({', '.join(args)})."}
    dut = cdut_func(None)
    for need_func in ["Step", "StepRis"]:
        if not hasattr(dut, need_func):
            return False, {"error": f"The 'create_dut' function in '{target_file_path}' did not return a valid DUT instance with '{need_func}' method."}
    func_source = inspect.getsource(cdut_func)
    for k, (v, tip_func) in source_code_need.items():
        message = v
        if tip_func:
            message += f" {tip_func()}"
        if k not in func_source:
            return False, {"error": message, "error_key": k}
    return True, {"message": f"create_dut check passed for '{target_file_path}'."}
