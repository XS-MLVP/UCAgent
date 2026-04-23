#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import ucagent.util.functions as fc

def check_dut_api_static(
    workspace: str,
    target_file: str,
    api_prefix: str,
    min_apis: int,
) -> tuple[bool, dict]:
    """Check the DUT API implementation for correctness (arguments and docstrings)."""
    
    if not os.path.isabs(target_file):
        target_file_full = os.path.join(workspace, target_file)
    else:
        target_file_full = target_file
        
    if not os.path.exists(target_file_full):
        return False, {"error": f"DUT API file '{target_file}' does not exist."}
        
    func_list = fc.get_target_from_file(target_file_full, f"{api_prefix}*",
                                     ex_python_path=workspace,
                                     dtype="FUNC")
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
            "error": f"Insufficient DUT API coverage: {len(func_list)} API functions found, minimum required is {min_apis}. " + \
                     f"You need to define APIs like: 'def {api_prefix}<API_NAME>(env, ...)'. " + \
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
                
    return True, {"message": f"UnityChipCheckerDutApi check for {target_file} passed."}
