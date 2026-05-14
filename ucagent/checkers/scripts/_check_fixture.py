# -*- coding: utf-8 -*-
"""Isolated checker: fixture function validation.

Logic extracted from UnityChipCheckerBaseFixture.do_check — kept exactly
equivalent so that both the direct call and subprocess paths run the same code.
"""

import os
import inspect
import ucagent.util.functions as fc
from ucagent.util.log import info


def check_fixture(target_file_path, workspace, fixture_name,
                  first_arg=None, last_arg=None, scope="function",
                  min_count=1, fix_count=-1,
                  source_code_need=None, source_code_cb=None,
                  dut_name=None, checker_class_name="", **kw):
    """Check fixture functions for correctness.

    Args:
        target_file_path: Absolute path to the file containing fixtures.
        workspace: Absolute path to the workspace.
        fixture_name: Pattern to match fixture names (e.g. "dut", "env*").
        first_arg: Expected name of the first argument.
        last_arg: Expected name of the last argument.
        scope: Expected fixture scope.
        min_count: Minimum number of fixtures expected.
        fix_count: Exact number expected (-1 = no constraint).
        source_code_need: Dict of {pattern: (message, tip_func_or_None)}.
        source_code_cb: Optional callable(source_code, func) -> (bool, dict).
            Not available in subprocess mode (not serializable).
        dut_name: DUT name for tip function evaluation.
        checker_class_name: Class name for error messages.

    Returns:
        Tuple[bool, dict]
    """
    target_file = target_file_path  # for error messages
    if not os.path.exists(target_file_path):
        return False, {"error": f"fixture file '{target_file}' does not exist."}

    fixture_func_list = fc.get_target_from_file(
        target_file_path, fixture_name,
        ex_python_path=workspace, dtype="FUNC"
    )

    for fx_func in fixture_func_list:
        args = fc.get_func_arg_list(fx_func)
        if first_arg is not None and (len(args) < 1 or args[0] != first_arg):
            return False, {"error": f"The '{fx_func.__name__}' fixture's first arg must be '{first_arg}', but got ({', '.join(args)})."}
        if last_arg is not None and (len(args) < 1 or args[-1] != last_arg):
            return False, {"error": f"The '{fx_func.__name__}' fixture's last arg must be '{last_arg}', but got ({', '.join(args)})."}
        if not (hasattr(fx_func, '_pytestfixturefunction') or "pytest_fixture" in str(fx_func)):
            return False, {"error": f"The '{fx_func.__name__}' fixture in '{target_file}' is not decorated with @pytest.fixture()."}
        scope_value = fc.get_fixture_scope(fx_func)
        if isinstance(scope_value, str):
            if scope_value != scope:
                return False, {"error": f"The '{fx_func.__name__}' fixture in '{target_file}' has invalid scope '{scope_value}'. The expected scope is '{scope}'."}

        func_source = inspect.getsource(fx_func)
        if source_code_need:
            for k, v in source_code_need.items():
                if isinstance(v, (list, tuple)):
                    message, tip_func = v[0], v[1] if len(v) > 1 else None
                else:
                    message, tip_func = v, None
                if callable(tip_func) and dut_name:
                    message += f" {tip_func(dut_name)}"
                if k not in func_source:
                    info(f"[{checker_class_name}]Check source code of fixture '{fx_func.__name__}' in file '{target_file}': missing '{k}' in source:\n{func_source}\n.")
                    return False, {"error": message}

        if source_code_cb:
            ret, msg = source_code_cb(func_source, fx_func)
            if not ret:
                return False, msg

    if len(fixture_func_list) < min_count:
        return False, {"error": f"Insufficient fixture coverage: {len(fixture_func_list)} fixtures found, minimum required is {min_count}. " +
                                f"You have defined {len(fixture_func_list)} fixtures: {', '.join([f.__name__ for f in fixture_func_list])} in file '{target_file}'."}
    if fix_count > 0 and len(fixture_func_list) != fix_count:
        return False, {"error": f"Incorrect fixture count: {len(fixture_func_list)} fixtures found, expected exactly {fix_count}. " +
                                f"You have defined {len(fixture_func_list)} fixtures: {', '.join([f.__name__ for f in fixture_func_list])} in file '{target_file}'."}

    return True, {"message": f"{checker_class_name} fixture check for {target_file} passed."}
