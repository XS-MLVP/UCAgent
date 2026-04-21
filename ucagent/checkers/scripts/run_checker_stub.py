#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Isolated subprocess stub for checker execution.

Protocol (JSON-based):
    sys.argv[1]  = checker_type   (e.g. "test_must_pass")
    sys.argv[2]  = JSON string    (serialized check_kwargs dict)

The stub dispatches to the corresponding _check_xxx function via _REGISTRY,
augments kwargs with subprocess-specific context (LD_PRELOAD, source_code_cb),
and emits JSON output.
"""
import sys
import os
import json
import builtins

_saved_ld_preload_full = os.environ.pop("LD_PRELOAD", None)

# Strip libpython from the saved LD_PRELOAD — pytest has its own Python runtime,
# preloading a second libpython causes double-free corruption.
def _strip_libpython(ld_preload_str):
    if not ld_preload_str:
        return None
    parts = [p for p in ld_preload_str.split(":") if not os.path.basename(p).startswith("libpython")]
    return ":".join(parts) if parts else None

_saved_ld_preload = _strip_libpython(_saved_ld_preload_full)

_original_import = builtins.__import__

# Import shared stub infrastructure from common.py
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
from common import _StubModule, _PytestStub, make_safe_import, safe_output as _output


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    """Safe import hook using shared stubs."""
    try:
        return _original_import(name, globals, locals, fromlist, level)
    except ImportError:
        base_package = name.split('.')[0]
        if base_package == 'pytest':
            return _PytestStub()
        return _StubModule()


# ---------------------------------------------------------------------------
# Registry: checker_type -> (module_name, function_name)
# ---------------------------------------------------------------------------
_REGISTRY = {
    "dut_creation":        ("_check_dut_creation",        "check_create_dut"),
    "fixture":             ("_check_fixture",             "check_fixtures"),
    "class":               ("_check_class",               "check_classes"),
    "api_static":          ("_check_api_static",          "check_dut_api_static"),
    "random_funcs":        ("_check_random_funcs",        "inspect_random_funcs"),
}


def _augment_subprocess_kwargs(checker_type, kw):
    """Add subprocess-specific parameters that cannot be JSON-serialized.

    This handles source_code_need / source_code_cb reconstruction for fixture / dut_creation.
    """
    # --- fixture-specific augmentation ---
    if checker_type == "fixture":
        fixture_name = kw.get("fixture_name", "")
        if fixture_name == "dut":
            kw["source_code_need"] = {"get_coverage_data_path": ("", None)}
            def check_yield(source_code, func):
                import ast
                tree = ast.parse(source_code)
                has_yield = any(isinstance(node, (ast.Yield, ast.YieldFrom)) for node in ast.walk(tree))
                if not has_yield:
                    return False, {"error": "Missing yield", "error_key": "missing_yield"}
                return True, {}
            kw["source_code_cb"] = check_yield
        elif fixture_name == "mock_dut":
            kw["source_code_need"] = {"ucagent.get_mock_dut_from": ("", None)}

    # --- dut_creation source_code_need ---
    if checker_type == "dut_creation":
        kw.setdefault("source_code_need", {
            "get_coverage_data_path": ("", None),
            "ucagent.is_imp_test_template": ("", None),
            "ucagent.get_fake_dut": ("", None),
        })


def main():
    if len(sys.argv) < 3:
        _output({"success": False, "error": "Usage: run_checker_stub.py <checker_type> <json_kwargs>"})
        return 1

    checker_type = sys.argv[1]
    try:
        check_kwargs = json.loads(sys.argv[2])
    except json.JSONDecodeError as e:
        _output({"success": False, "error": f"Invalid JSON kwargs: {e}"})
        return 1

    if checker_type not in _REGISTRY:
        _output({"success": False, "error": f"Unknown checker type: {checker_type}"})
        return 1

    module_name, func_name = _REGISTRY[checker_type]

    # Setup sys.path for imports
    workspace = check_kwargs.get("workspace", "")
    target_file = check_kwargs.get("target_file_path") or check_kwargs.get("target_file", "")
    target_dir = os.path.dirname(os.path.abspath(target_file)) if target_file else ""

    import inspect
    current_dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
    ucagent_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))

    for path in [workspace, target_dir, ucagent_dir]:
        if path and path not in sys.path:
            sys.path.insert(0, path)

    # All remaining checkers rely on safe import hook for static analysis
    builtins.__import__ = _safe_import

    try:
        # Dynamic import of the check function
        mod = __import__(module_name)
        func = getattr(mod, func_name)

        # Augment kwargs with subprocess-specific params
        _augment_subprocess_kwargs(checker_type, check_kwargs)

        # Call the check function
        if checker_type == "random_funcs":
            # random_funcs returns a single dict, not a (bool, dict) tuple
            result = func(**check_kwargs)
            _output(result)
            return 0 if result.get("success") else 1

        ret, result = func(**check_kwargs)
        if ret:
            _output({"success": True, **(result if isinstance(result, dict) else {"result": result})})
        else:
            if isinstance(result, dict):
                result["success"] = False
                _output(result)
            else:
                _output({"success": False, "error": result})
        return 0 if ret else 1

    except Exception as e:
        import traceback
        estack = traceback.format_exc()
        _output({"success": False, "error": f"Failed to run check '{checker_type}': {str(e)}", "traceback": estack})
        return 1
    finally:
        builtins.__import__ = _original_import

if __name__ == "__main__":
    import io
    sys.stderr = io.StringIO()
    sys.exit(main())
