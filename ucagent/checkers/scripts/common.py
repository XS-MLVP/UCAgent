#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Common infrastructure for checker scripts.

This module provides:
1. Stub modules for safe import hooks (_StubModule, _PytestStub, safe_import_hook)
2. Isolated subprocess execution with LD_PRELOAD (run_check, run_isolated_check)
3. JSON output utilities
"""

import glob
import json
import os
import re
import subprocess
import sys
import sysconfig
from typing import Any, Iterable, Optional, Tuple


# ---------------------------------------------------------------------------
# Stub modules — shared by run_checker_stub.py and legacy standalone scripts.
# ---------------------------------------------------------------------------

class _StubModule:
    """Stub module that silently absorbs all attribute access."""
    def __init__(self, name='Stub'):
        self.__name__ = name

    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        return _StubModule(name)
    def __call__(self, *args, **kwargs):
        return _StubModule()
    def __iter__(self):
        return iter([])
    def __len__(self):
        return 0
    def __bool__(self):
        return False
    def __mro_entries__(self, bases):
        class _DynamicStubClass:
            pass
        _DynamicStubClass.__name__ = getattr(self, '__name__', 'Stub')
        return (_DynamicStubClass,)
    def __getitem__(self, key):
        return _StubModule()


class _PytestStub:
    """Special stub for pytest that provides a working fixture decorator."""
    @staticmethod
    def fixture(*args, **kwargs):
        """Stub fixture decorator that returns the function unchanged."""
        fixture_scope = kwargs.get("scope", "function")

        def decorator(func):
            func._is_pytest_fixture = True
            func._fixture_scope = fixture_scope
            return func

        # Handle both @pytest.fixture and @pytest.fixture()
        if len(args) == 1 and callable(args[0]) and not kwargs:
            func = args[0]
            func._is_pytest_fixture = True
            func._fixture_scope = "function"
            return func
        else:
            return decorator

    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        return _StubModule()


def make_safe_import(original_import):
    """Create a safe import hook that returns stub modules for missing packages."""
    def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        try:
            return original_import(name, globals, locals, fromlist, level)
        except ImportError:
            base_package = name.split('.')[0]
            if base_package == 'pytest':
                return _PytestStub()
            return _StubModule()
    return _safe_import


# ---------------------------------------------------------------------------
# JSON output utility
# ---------------------------------------------------------------------------

def safe_output(data: dict):
    """Output JSON data to stdout, fallback to str if serialization fails."""
    try:
        print(json.dumps(data, ensure_ascii=False))
    except (TypeError, ValueError):
        try:
            print(json.dumps({k: str(v) for k, v in data.items()}, ensure_ascii=False))
        except Exception:
            print(str(data))
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# LD_PRELOAD isolated subprocess execution
# (merged from ld_preload_runner.py)
# ---------------------------------------------------------------------------

def _find_real_python_binary() -> str:
    """Find the real Python ELF binary, not a shell wrapper."""

    def _is_elf(path: str) -> bool:
        try:
            with open(path, "rb") as f:
                return f.read(4) == b"\x7fELF"
        except OSError:
            return False

    resolved = os.path.realpath(sys.executable)
    if _is_elf(resolved):
        return resolved

    bin_dir = os.path.dirname(resolved)
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    candidates = [
        os.path.join(bin_dir, f"python{version}"),
        os.path.join(bin_dir, f"python{sys.version_info.major}"),
        os.path.join(bin_dir, "python"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate) and _is_elf(candidate):
            return candidate
    return sys.executable


def _find_libpython() -> str:
    """Find libpython for the running interpreter."""
    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    lib_names = [
        f"libpython{ver}.so.1.0",
        f"libpython{ver}.so",
        f"libpython{ver}m.so.1.0",
        f"libpython{ver}m.so",
    ]
    search_dirs = []
    libdir = sysconfig.get_config_var("LIBDIR")
    if libdir:
        search_dirs.append(libdir)
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    search_dirs.append(os.path.join(os.path.dirname(exe_dir), "lib"))
    search_dirs.append(exe_dir)
    for directory in search_dirs:
        for name in lib_names:
            path = os.path.join(directory, name)
            if os.path.exists(path):
                return path
        matches = sorted(glob.glob(os.path.join(directory, f"libpython{ver}*.so*")))
        if matches:
            return matches[0]
    return ""


def _build_ld_preload(so_file: str) -> str:
    # We DO NOT prepend libpython anymore. Preloading libpython into a
    # Python executable causes two libpythons to be loaded, which leads to
    # double free or corruption (fasttop) upon process exit/destructor call.
    so_path = os.path.abspath(so_file)
    return so_path


def _build_pythonpath_parts(workspace: str, target_file: Optional[str]) -> list[str]:
    parts: list[str] = []
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if os.path.exists(os.path.join(project_root, "ucagent")):
        parts.append(project_root)
    if workspace and os.path.exists(workspace):
        parts.append(os.path.abspath(workspace))
    if target_file:
        target_dir = os.path.dirname(os.path.abspath(target_file))
        if target_dir and os.path.exists(target_dir):
            parts.append(target_dir)

    for p in sys.path:
        if p and os.path.exists(p) and p not in parts:
            parts.append(p)

    return list(dict.fromkeys(parts))


def _stringify_args(args: Iterable[Any]) -> list[str]:
    return [str(arg) for arg in args]


def run_isolated_check(
    helper_script_name: str,
    script_args: Iterable[Any],
    *,
    workspace: str,
    target_file: Optional[str] = None,
    so_file: str,
    timeout: int = 30,
) -> Tuple[bool, dict]:
    """Run a checker helper script inside a fresh process with LD_PRELOAD."""
    workspace = os.path.abspath(workspace)
    if not os.path.exists(workspace):
        return False, {"error": f"Invalid workspace: {workspace}"}
    if not so_file:
        return False, {"error": "check_script_env is empty, cannot run isolated_ld_preload mode"}

    so_file = os.path.abspath(so_file)
    if not os.path.exists(so_file):
        return False, {"error": f"Shared library not found: {so_file}"}

    helper_script = os.path.join(os.path.dirname(__file__), helper_script_name)
    if not os.path.exists(helper_script):
        return False, {"error": f"Helper script not found: {helper_script}"}

    env = os.environ.copy()
    env["LD_PRELOAD"] = _build_ld_preload(so_file)
    env["_LD_PRELOAD_HANDLED"] = "1"

    pythonpath_parts = _build_pythonpath_parts(workspace, target_file)
    if pythonpath_parts:
        existing_path = env.get("PYTHONPATH", "")
        new_path = ":".join(pythonpath_parts)
        env["PYTHONPATH"] = f"{new_path}:{existing_path}" if existing_path else new_path

    cmd = [_find_real_python_binary(), helper_script] + _stringify_args(script_args)

    try:
        proc = subprocess.run(
            cmd,
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, {"error": f"Check timed out after {timeout} seconds."}
    except Exception as exc:
        return False, {"error": f"Failed to run isolated checker: {exc}"}

    result = _parse_json_from_output(proc.stdout)
    if result is None:
        stdout_info = proc.stdout[:500] if proc.stdout else ""
        stderr_info = proc.stderr[:500] if proc.stderr else ""
        return False, {
            "error": f"No JSON found in output. stdout: {stdout_info}, stderr: {stderr_info}",
        }

    if proc.stderr and "stderr" not in result:
        result["stderr"] = proc.stderr[:500]
    return result.get("success", False), result


def run_check(
    workspace: str,
    target_file: str,
    helper_script_name: str,
    *args: Any,
    timeout: int = 30,
    so_file: Optional[str] = None,
) -> Tuple[bool, dict]:
    """Compatibility wrapper for isolated checker extensions."""
    if so_file is None:
        return False, {"error": "so_file is required for run_check in isolated_ld_preload mode"}
    return run_isolated_check(
        helper_script_name,
        [target_file, workspace, *args],
        workspace=workspace,
        target_file=target_file,
        so_file=so_file,
        timeout=timeout,
    )


run_with_ld_preload = run_check


def run_isolated_check_json(
    checker_type: str,
    check_kwargs: dict,
    *,
    workspace: str,
    so_file: str,
    timeout: int = 30,
) -> Tuple[bool, dict]:
    """Run a checker via run_checker_stub.py with JSON-serialized kwargs.

    This is the preferred way to invoke isolated checkers.  The subprocess
    receives exactly two positional arguments:
        sys.argv[1] = checker_type   (e.g. "test_must_pass")
        sys.argv[2] = JSON string   (serialized check_kwargs)

    run_checker_stub.py deserializes the JSON and dispatches to the
    corresponding _check_xxx function via its internal registry.
    """
    workspace = os.path.abspath(workspace)
    if not os.path.exists(workspace):
        return False, {"error": f"Invalid workspace: {workspace}"}
    if not so_file:
        return False, {"error": "check_script_env is empty, cannot run isolated mode"}

    so_file = os.path.abspath(so_file)
    if not os.path.exists(so_file):
        return False, {"error": f"Shared library not found: {so_file}"}

    helper_script = os.path.join(os.path.dirname(__file__), "run_checker_stub.py")
    if not os.path.exists(helper_script):
        return False, {"error": f"Helper script not found: {helper_script}"}

    env = os.environ.copy()
    env["LD_PRELOAD"] = _build_ld_preload(so_file)
    env["_LD_PRELOAD_HANDLED"] = "1"

    # Derive a target_file for PYTHONPATH from check_kwargs when available.
    target_file = check_kwargs.get("target_file_path") or check_kwargs.get("target_file")
    pythonpath_parts = _build_pythonpath_parts(workspace, target_file)
    if pythonpath_parts:
        existing_path = env.get("PYTHONPATH", "")
        new_path = ":".join(pythonpath_parts)
        env["PYTHONPATH"] = f"{new_path}:{existing_path}" if existing_path else new_path

    json_str = json.dumps(check_kwargs, ensure_ascii=False)
    cmd = [_find_real_python_binary(), helper_script, checker_type, json_str]

    try:
        proc = subprocess.run(
            cmd,
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, {"error": f"Check timed out after {timeout} seconds."}
    except Exception as exc:
        return False, {"error": f"Failed to run isolated checker: {exc}"}

    result = _parse_json_from_output(proc.stdout)
    if result is None:
        stdout_info = proc.stdout[:500] if proc.stdout else ""
        stderr_info = proc.stderr[:500] if proc.stderr else ""
        return False, {
            "error": f"No JSON found in output. stdout: {stdout_info}, stderr: {stderr_info}",
        }

    if proc.stderr and "stderr" not in result:
        result["stderr"] = proc.stderr[:500]
    return result.get("success", False), result


def _parse_json_from_output(output: str) -> Optional[dict]:
    """Parse JSON from subprocess output."""
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    json_pattern = r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
    matches = re.findall(json_pattern, output, re.DOTALL)
    for match in matches:
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue
    return None

# ---------------------------------------------------------------------------
# PyTest Execution Helpers
# ---------------------------------------------------------------------------

def run_isolated_pytest(
    workspace: str,
    test_dir: str,
    pytest_ex_args: str = "",
    pytest_ex_env: dict = None,
    timeout: int = 15,
):
    """Execute pytest comprehensively and return unpacked results.
    
    Returns:
        (success, report, error_msg, stdout, stderr, env_used)
    """
    from ucagent.tools.testops import RunUnityChipTest
    import ucagent.util.functions as fc
    
    run_test = RunUnityChipTest()
    run_test.set_workspace(workspace)

    effective_timeout = timeout if timeout > 0 else 15
    env = {}
    if pytest_ex_env:
        env.update(pytest_ex_env)

    report, str_out, str_err = run_test.do(
        test_dir,
        pytest_ex_args=pytest_ex_args,
        return_stdout=True, return_stderr=True, return_all_checks=True,
        timeout=effective_timeout,
        pytest_ex_env=env
    )

    test_pass, test_msg = fc.is_run_report_pass(report, str_out, str_err)
    error_ret = test_msg.get("error", test_msg) if isinstance(test_msg, dict) else test_msg
    
    return test_pass, report, error_ret, str_out, str_err, env

def build_run_test_cases_wrapper(workspace: str, test_dir: str, env: dict):
    def _run_test_cases_wrapper(pytest_args, timeout_val, **kwargs):
        from ucagent.tools.testops import RunUnityChipTest
        run_test = RunUnityChipTest()
        run_test.set_workspace(workspace)
        _, cout, cerr = run_test.do(
            test_dir, pytest_ex_args=pytest_args, timeout=timeout_val, 
            return_stdout=True, return_stderr=True, pytest_ex_env=env
        )
        return True, {"STDOUT": cout, "STDERR": cerr}
    return _run_test_cases_wrapper