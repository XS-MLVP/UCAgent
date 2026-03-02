#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Subprocess checker for UnityChipCheckerDutCreation.

This script MUST be launched with LD_PRELOAD=<so_file> already set in the
environment before Python starts, so the dynamic linker loads the .so at
process startup (before any Python import). This avoids the static TLS
allocation error that occurs when dlopen() is called at runtime.

Usage (called by UnityChipCheckerDutCreation._do_check_subprocess):
    LD_PRELOAD=/path/to/_tlm_pbsb.so \
    _LD_PRELOAD_HANDLED=1 \
    python run_check_dut_creation.py <target_file> <workspace> <dut_name>

Output:
    Prints a single JSON line to stdout:
      {"success": true,  "message": "..."}
      {"success": false, "error": "...", "error_key": "<optional_key>"}
"""

import sys
import os
import json
import io


def _output(data: dict):
    """Print JSON result to stdout and flush."""
    print(json.dumps(data, ensure_ascii=False))
    sys.stdout.flush()


def main():
    if len(sys.argv) < 4:
        _output({
            "success": False,
            "error": f"Usage: {os.path.basename(sys.argv[0])} <target_file> <workspace> <dut_name>",
        })
        sys.exit(1)

    target_file = os.path.abspath(sys.argv[1])
    workspace   = os.path.abspath(sys.argv[2])
    dut_name    = sys.argv[3]

    # Validate inputs
    if not os.path.exists(target_file):
        _output({"success": False, "error": f"Target file not found: '{target_file}'"})
        sys.exit(1)
    if not os.path.exists(workspace):
        _output({"success": False, "error": f"Workspace not found: '{workspace}'"})
        sys.exit(1)

    # Build sys.path so all imports in the target file can be resolved:
    #   - workspace:   enables "from Adder import DUTAdder"
    #   - target_dir:  enables "from Adder_function_coverage_def import ..."
    target_dir = os.path.dirname(target_file)
    for p in [workspace, target_dir]:
        if p and os.path.exists(p) and p not in sys.path:
            sys.path.insert(0, p)

    # Suppress noisy stderr from module imports (VCS prints a lot)
    _real_stderr = sys.stderr
    sys.stderr = io.StringIO()

    # ── Stub-import hook ─────────────────────────────────────────────────────
    # Many api.py files have top-level 'import pytest', 'from toffee_test …',
    # etc.  Those packages may be absent in this subprocess environment but are
    # NOT needed to execute create_dut(None).  We install a hook that returns a
    # silent stub for any package that fails to import so the module can load.
    import builtins
    import types as _types

    class _StubModule(_types.ModuleType):
        """Silently absorbs attribute access, calls, and iteration."""
        def __getattr__(self, name):
            child = f"{self.__name__}.{name}"
            if child not in sys.modules:
                m = _StubModule(child)
                m.__path__ = []
                sys.modules[child] = m
            return sys.modules[child]
        def __call__(self, *a, **kw): return self
        def __iter__(self):           return iter([])
        def __bool__(self):           return True
        def __repr__(self):           return f"<StubModule '{self.__name__}'>"

    _real_import = builtins.__import__

    def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        try:
            return _real_import(name, globals, locals, fromlist, level)
        except ImportError:
            if name not in sys.modules:
                stub = _StubModule(name)
                stub.__path__ = []
                stub.__spec__ = None
                sys.modules[name] = stub
            mod = sys.modules[name]
            if fromlist:
                for attr in fromlist:
                    if not hasattr(mod, attr):
                        child_name = f"{mod.__name__}.{attr}"
                        child = sys.modules.get(child_name) or _StubModule(child_name)
                        child.__path__ = []
                        sys.modules[child_name] = child
                        setattr(mod, attr, child)
            return mod

    # Dynamically import the target file
    import importlib.util
    import inspect

    try:
        spec = importlib.util.spec_from_file_location("_uc_dut_check_target_", target_file)
        if spec is None:
            sys.stderr = _real_stderr
            _output({"success": False, "error": f"Cannot create module spec for '{target_file}'."})
            sys.exit(1)
        module = importlib.util.module_from_spec(spec)
        builtins.__import__ = _safe_import   # activate stub hook
        try:
            spec.loader.exec_module(module)
        finally:
            builtins.__import__ = _real_import  # always restore
    except Exception as e:
        sys.stderr = _real_stderr
        _output({"success": False, "error": f"Failed to import '{target_file}': {str(e)}"})
        sys.exit(1)
    finally:
        sys.stderr = _real_stderr

    # ── Find create_dut ──────────────────────────────────────────────────────
    create_dut_funcs = [
        obj for name, obj in inspect.getmembers(module, inspect.isfunction)
        if name == "create_dut"
    ]
    if not create_dut_funcs:
        _output({"success": False,
                 "error": f"No 'create_dut' function found in '{target_file}'."})
        sys.exit(1)
    if len(create_dut_funcs) != 1:
        _output({"success": False,
                 "error": f"Multiple 'create_dut' functions found in '{target_file}'. Expected exactly one."})
        sys.exit(1)

    cdut_func = create_dut_funcs[0]

    # ── Check signature ──────────────────────────────────────────────────────
    try:
        params = list(inspect.signature(cdut_func).parameters.keys())
    except Exception as e:
        _output({"success": False,
                 "error": f"Failed to inspect create_dut signature: {str(e)}"})
        sys.exit(1)

    if len(params) != 1 or params[0] != "request":
        _output({"success": False,
                 "error": (f"The 'create_dut' fixture must have exactly one argument named "
                           f"'request', but got ({', '.join(params)}).")})
        sys.exit(1)

    # ── Call create_dut(None) — the step that requires LD_PRELOAD ────────────
    sys.stderr = io.StringIO()
    try:
        dut = cdut_func(None)
    except Exception as e:
        sys.stderr = _real_stderr
        _output({"success": False,
                 "error": f"Failed to call create_dut(None): {str(e)}"})
        sys.exit(1)
    finally:
        sys.stderr = _real_stderr

    # ── Check required DUT methods ───────────────────────────────────────────
    for method_name in ["Step", "StepRis"]:
        if not hasattr(dut, method_name):
            _output({"success": False,
                     "error": (f"DUT instance is missing required method '{method_name}'. "
                               f"Ensure create_dut returns a valid DUT object.")})
            sys.exit(1)

    # ── Check source code requirements ───────────────────────────────────────
    try:
        func_source = inspect.getsource(cdut_func)
    except Exception as e:
        _output({"success": False,
                 "error": f"Failed to read source of create_dut: {str(e)}"})
        sys.exit(1)

    # Keys that must appear in source; parent process provides full error msgs.
    source_keys = [
        "get_coverage_data_path",
        "ucagent.is_imp_test_template",
        "ucagent.get_fake_dut",
    ]
    for key in source_keys:
        if key not in func_source:
            _output({"success": False,
                     "error_key": key,
                     "error": f"'{key}' not found in create_dut source code."})
            sys.exit(1)

    # ── All checks passed ────────────────────────────────────────────────────
    _output({"success": True,
             "message": f"create_dut check passed for '{target_file}'."})
    sys.exit(0)


if __name__ == "__main__":
    main()
