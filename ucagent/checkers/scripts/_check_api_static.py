# -*- coding: utf-8 -*-
"""Isolated checker: DUT API static validation.

Logic extracted from UnityChipCheckerDutApi.do_check — kept exactly
equivalent so that both the direct call and subprocess paths run the same code.
"""

import os
import ucagent.util.functions as fc


def check_api_static(target_file_path, workspace, api_prefix, min_apis=1,
                     checker_class_name="", **kw):
    """Check DUT API functions for correctness.

    Args:
        target_file_path: Absolute path to the API file.
        workspace: Absolute path to the workspace.
        api_prefix: Prefix to match API function names.
        min_apis: Minimum number of APIs expected.
        checker_class_name: Class name for messages.

    Returns:
        Tuple[bool, dict]
    """
    target_file = target_file_path  # for error messages
    if not os.path.exists(target_file_path):
        return False, {"error": f"DUT API file '{target_file}' does not exist."}

    func_list = fc.get_target_from_file(
        target_file_path, f"{api_prefix}*",
        ex_python_path=workspace, dtype="FUNC"
    )

    failed_apis = []
    for func in func_list:
        args = fc.get_func_arg_list(func)
        if not args or len(args) < 2:
            failed_apis.append(func)
            continue
        if not args[0].startswith("env"):
            failed_apis.append(func)
        if not args[-1].startswith("max_cycles"):
            failed_apis.append(func)

    if len(failed_apis) > 0:
        return False, {
            "error": f"The following API functions in file '{target_file}' have invalid or missing arguments. The first arg must be 'env' and the last arg must be 'max_cycles=default_value'",
            "failed_apis": [f"{func}({', '.join(fc.get_func_arg_list(func))})" for func in failed_apis]
        }

    if len(func_list) < min_apis:
        return False, {
            "error": f"Insufficient DUT API coverage: {len(func_list)} API functions found, minimum required is {min_apis}. " +
                     f"You need to define APIs like: 'def {api_prefix}<API_NAME>(env, ...)'. " +
                     f"Review your task details and ensure that the API functions are defined correctly in the target file '{target_file}'.",
        }

    for func in func_list:
        if not func.__doc__ or len(func.__doc__.strip()) == 0:
            return False, {
                "error": f"The API function '{func.__name__}' is missing a docstring. Please provide a clear description of its purpose and usage."
            }
        for doc_key in ["Args:", "Returns:"]:
            if doc_key not in func.__doc__:
                return False, {
                    "error": f"The API function '{func.__name__}' is missing the '{doc_key}' section in its docstring."
                }

    return True, {
        "message": f"{checker_class_name} check for {target_file} passed.",
        "func_names": [f.__name__ for f in func_list],
    }
