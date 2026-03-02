#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Helper script for checking create_dut function."""

import os
import sys

from ucagent.checkers.scripts.common import (
    init_helper_script,
    run_checker_main,
    setup_python_paths,
    load_module_from_file,
    check_function_signature,
    remove_ld_preload_for_ucagent,
)

init_helper_script()

import inspect


def check_create_dut(target_file, workspace, dut_name):
    """Check create_dut function in target file."""
    try:
        # Setup paths
        setup_python_paths(workspace, target_file)

        # Load module (LD_PRELOAD is active in this subprocess if needed)
        success, module, error = load_module_from_file(target_file)
        if not success:
            return {"success": False, "error": error}
        
        # NOW remove LD_PRELOAD before importing ucagent (to avoid git conflicts)
        remove_ld_preload_for_ucagent()
        
        import ucagent.util.functions as fc

        # Find create_dut function
        create_dut_funcs = [obj for name, obj in inspect.getmembers(module, inspect.isfunction)
                           if name == "create_dut"]

        if not create_dut_funcs:
            return {"success": False, "error": f"No 'create_dut' functions found in '{target_file}'."}

        if len(create_dut_funcs) != 1:
            return {"success": False, "error": f"Multiple 'create_dut' functions found. Expected only one."}

        cdut_func = create_dut_funcs[0]

        # Check signature
        success, error = check_function_signature(cdut_func, ["request"])
        if not success:
            return {"success": False, "error": f"The 'create_dut' fixture must have one arg named 'request'. {error}"}

        # Try to call function
        try:
            dut = cdut_func(None)
        except Exception as e:
            return {"success": False, "error": f"Failed to call create_dut(None): {str(e)}"}

        # Check required methods
        for need_func in ["Step", "StepRis"]:
            if not hasattr(dut, need_func):
                return {"success": False, "error": f"DUT instance missing required method '{need_func}'."}

        # Check get_coverage_data_path in source
        func_source = inspect.getsource(cdut_func)
        if "get_coverage_data_path" not in func_source:
            error_msg = f"The 'create_dut' function must call 'get_coverage_data_path(request, new_path=True)'."
            # Enhance error message with tips
            error_msg += f" {fc.tips_of_get_coverage_data_path(dut_name)}"
            return {"success": False, "error": error_msg}

        return {"success": True, "message": f"UnityChipCheckerDutCreation check for {target_file} passed."}

    except Exception as e:
        return {"success": False, "error": f"Exception during check: {str(e)}"}


def main():
    run_checker_main(
        check_func=check_create_dut,
        expected_mode="create_dut",
        min_args=5,  # target_file, workspace, mode, dut_name
        extra_args=False
    )


if __name__ == "__main__":
    main()
