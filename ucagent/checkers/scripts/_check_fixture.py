#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared check logic for fixture validation — extracted from origin/main do_check."""

import inspect
import ucagent.util.functions as fc
from ucagent.util.log import info


def check_fixtures(target_file_path, workspace, fixture_name,
                   first_arg=None, last_arg=None, scope="function",
                   min_count=1, fix_count=-1,
                   source_code_need=None, source_code_cb=None):
    """Validate fixtures, returns (bool, dict).

    Args:
        target_file_path: Absolute path to the target file.
        workspace: Workspace directory path.
        fixture_name: Pattern to match fixture function names (e.g. "dut", "env*").
        first_arg/last_arg: Expected first/last argument names.
        scope: Expected fixture scope.
        min_count/fix_count: Count constraints.
        source_code_need: Dict {key: (error_msg, tip_func_or_none)}.
        source_code_cb: Optional callback(source_code, func) -> (bool, dict).

    Returns:
        (success: bool, result: dict)
    """
    if source_code_need is None:
        source_code_need = {}

    fixture_func_list = fc.get_target_from_file(target_file_path, fixture_name,
                                                ex_python_path=workspace,
                                                dtype="FUNC")
    for fx_func in fixture_func_list:
        fx_name = getattr(fx_func, "__name__", getattr(fx_func, "name", str(fx_func)))
        args = fc.get_func_arg_list(fx_func)
        if first_arg is not None and (len(args) < 1 or args[0] != first_arg):
            return False, {"error": f"The '{fx_name}' fixture's first arg must be '{first_arg}', but got ({', '.join(args)})."}
        if last_arg is not None and (len(args) < 1 or args[-1] != last_arg):
            return False, {"error": f"The '{fx_name}' fixture's last arg must be '{last_arg}', but got ({', '.join(args)})."}
        if not (hasattr(fx_func, '_is_pytest_fixture') or hasattr(fx_func, '_pytestfixturefunction') or "pytest_fixture" in str(fx_func)):
            return False, {"error": f"The '{fx_name}' fixture in '{target_file_path}' is not decorated with @pytest.fixture()."}
        scope_value = fc.get_fixture_scope(fx_func)
        if isinstance(scope_value, str):
            if scope_value != scope:
                return False, {"error": f"The '{fx_name}' fixture in '{target_file_path}' has invalid scope '{scope_value}'. The expected scope is '{scope}'."}
        func_source = inspect.getsource(fx_func)
        for k, (v, tip_func) in source_code_need.items():
            message = v
            if tip_func:
                message += f" {tip_func()}"
            if k not in func_source:
                info(f"Check source code of fixture '{fx_name}' in file '{target_file_path}': missing '{k}'.")
                return False, {"error": message, "error_key": k}
        if source_code_cb:
            ret, msg = source_code_cb(func_source, fx_func)
            if not ret:
                return False, msg

    if len(fixture_func_list) < min_count:
        return False, {"error": f"Insufficient fixture coverage: {len(fixture_func_list)} fixtures found, minimum required is {min_count}. " +
                                f"You have defined {len(fixture_func_list)} fixtures: {', '.join([getattr(f, '__name__', getattr(f, 'name', str(f))) for f in fixture_func_list])} in file '{target_file_path}'."}
    if fix_count > 0 and len(fixture_func_list) != fix_count:
        return False, {"error": f"Incorrect fixture count: {len(fixture_func_list)} fixtures found, expected exactly {fix_count}. " +
                                f"You have defined {len(fixture_func_list)} fixtures: {', '.join([getattr(f, '__name__', getattr(f, 'name', str(f))) for f in fixture_func_list])} in file '{target_file_path}'."}
    return True, {"message": f"Fixture check for '{target_file_path}' passed.",
                  "fixtures_found": len(fixture_func_list),
                  "fixture_names": [getattr(f, '__name__', getattr(f, 'name', str(f))) for f in fixture_func_list]}
