#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Subprocess entry point for isolated checker execution.

This script is launched by ``common.run_isolated_check_json`` with
LD_PRELOAD already set in the environment by ld.so.  It dispatches to
the appropriate ``_check_*.py`` module based on the checker_type argument.

Usage:
    python run_checker_stub.py <checker_type> <json_kwargs>

Output:
    A single JSON object on stdout with at least {"success": bool}.
"""

import sys
import os
import io
import json


def _output(data: dict):
    """Write JSON to stdout (the only communication channel with parent)."""
    sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
    sys.stdout.flush()


# ---- Checker registry ----
# Maps checker_type -> (module_name, function_name)

_REGISTRY = {
    "dut_creation":  ("_check_dut_creation",    "check_create_dut"),
    "fixture":       ("_check_fixture",          "check_fixture"),
    "api_static":    ("_check_api_static",       "check_api_static"),
    "mock":          ("_check_class",            "check_mock"),
    "bundle":        ("_check_class",            "check_bundle"),
    "test_must_pass":("_check_test_must_pass",   "check_test_must_pass"),
}


# ---- Main ----

def main():
    if len(sys.argv) < 3:
        _output({"success": False, "error": "Usage: run_checker_stub.py <checker_type> <json_kwargs>"})
        return 1

    checker_type = sys.argv[1]
    try:
        check_kwargs = json.loads(sys.argv[2])
    except json.JSONDecodeError as e:
        _output({"success": False, "error": f"Invalid JSON in argv[2]: {e}"})
        return 1

    if checker_type not in _REGISTRY:
        _output({"success": False, "error": f"Unknown checker type: '{checker_type}'. Available: {list(_REGISTRY.keys())}"})
        return 1

    module_name, func_name = _REGISTRY[checker_type]

    # Suppress stderr to prevent SWIG/VCS noise from polluting output
    saved_stderr = sys.stderr
    sys.stderr = io.StringIO()

    try:
        # Import the checker module (LD_PRELOAD is already active)
        mod = __import__(module_name)
        func = getattr(mod, func_name)
        ret, result = func(**check_kwargs)
        _output({"success": ret, **result})
        return 0 if ret else 1
    except Exception as exc:
        _output({"success": False, "error": f"Failed to run check '{checker_type}': {exc}"})
        return 1
    finally:
        sys.stderr = saved_stderr


if __name__ == "__main__":
    # Add scripts directory to path for _check_*.py imports
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    sys.exit(main())
