# -*- coding: utf-8 -*-
"""Isolated checker: test function static validation.

Logic extracted from UnityChipCheckerTestMustPass.do_check (the static
analysis part only) — kept exactly equivalent.  The pytest execution part
remains in unity_test.py since it needs self.run_test.
"""

import os
import ucagent.util.functions as fc


def check_test_must_pass(target_file_list, workspace, test_dir,
                         test_prefix, first_arg="", last_arg="",
                         min_file_tests=1, **kw):
    """Check test functions for correct names and argument signatures.

    This validates the static properties of test functions.  The actual
    pytest execution is handled by the caller (needs self.run_test).

    Args:
        target_file_list: List of test file patterns.
        workspace: Absolute path to workspace.
        test_dir: Relative path to the test directory.
        test_prefix: Required prefix for test function names.
        first_arg: Expected first argument name.
        last_arg: Expected last argument name.
        min_file_tests: Minimum number of test functions per file.

    Returns:
        Tuple[bool, dict]
    """
    if isinstance(target_file_list, str):
        target_file_list = [target_file_list]

    test_dir_full_path = os.path.join(workspace, test_dir) if not os.path.isabs(test_dir) else test_dir
    if not os.path.exists(test_dir_full_path):
        return False, {"error": f"test directory '{test_dir}' does not exist in workspace."}

    test_files = fc.find_files_by_pattern(workspace, target_file_list)
    if len(test_files) == 0:
        tfiles = ', '.join(target_file_list)
        return False, {"error": f"target test files '{tfiles}' does not exist."}

    error_cases = []
    for tfile in test_files:
        abs_tfile = os.path.join(workspace, tfile) if not os.path.isabs(tfile) else tfile
        if test_dir_full_path not in abs_tfile:
            error_cases.append(f"The test file '{tfile}' is not under the test directory '{test_dir}'.")
            continue
        test_func_list = fc.get_target_from_file(
            abs_tfile, "test*",
            ex_python_path=workspace, dtype="FUNC"
        )
        for test_func in test_func_list:
            if test_func.__name__.startswith(test_prefix) is False:
                error_cases.append(f"The '{test_func.__name__}' test function's name must start with '{test_prefix}'.")
                continue
            args = fc.get_func_arg_list(test_func)
            if first_arg and (len(args) < 1 or args[0] != first_arg):
                error_cases.append(f"The '{test_func.__name__}' test function's first arg must be '{first_arg}', but got ({', '.join(args)}).")
            if last_arg and (len(args) < 1 or args[-1] != last_arg):
                error_cases.append(f"The '{test_func.__name__}' test function's last arg must be '{last_arg}', but got ({', '.join(args)}).")
        if len(test_func_list) < min_file_tests:
            error_cases.append(f"Insufficient testcases: {len(test_func_list)} test functions found, minimum required is {min_file_tests} in file '{tfile}'. " +
                               "Please ensure you have implemented enough test cases (need pytest function based not class based).")

    if len(error_cases) > 0:
        return False, {
            "error": "Check test functions failed.",
            "details": error_cases
        }
    return True, {"message": "Test function static check passed."}
