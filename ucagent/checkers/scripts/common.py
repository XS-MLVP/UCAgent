#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Common utilities for checker scripts.

This module provides helper functions for checker scripts that run in subprocesses.
It reuses ucagent.util.functions where possible to avoid code duplication:
- fc.append_python_path: Add paths to sys.path
- fc.import_python_file: Dynamically import Python modules
- fc.get_func_arg_list: Extract function argument names
- fc.get_target_from_file: Find functions/classes matching patterns (used in check_dut_api.py)
"""

# NOTE: LD_PRELOAD handling is done selectively:
# - Keep LD_PRELOAD during target file import (to prevent TLS errors)
# - Remove it before importing ucagent modules (to avoid git conflicts)
import os
import sys
import json
import io
import inspect
from typing import Any, Optional, List, Tuple, Callable

# NOTE: Do NOT import ucagent here at module level!
# Import ucagent.util.functions as fc only inside functions to avoid
# triggering git package imports

import ctypes


def init_helper_script():
    """
    Initialize helper script environment.

    Redirects stderr to suppress warnings.
    Note: LD_PRELOAD handling is done in remove_ld_preload_for_ucagent().
    """
    sys.stderr = io.StringIO()


def remove_ld_preload_for_ucagent():
    """
    Remove LD_PRELOAD environment variable before importing ucagent modules.
    
    This prevents conflicts with git package but should be called AFTER
    target module has been loaded (to avoid TLS errors in target modules).
    """
    if 'LD_PRELOAD' in os.environ:
        del os.environ['LD_PRELOAD']


def run_checker_main(check_func: Callable, expected_mode: str, min_args: int = 4, usage_hint: str = "", extra_args: bool = True):
    """
    Generic main function wrapper for checker scripts.
    
    Args:
        check_func: The check function to call
        expected_mode: Expected mode/check_type value
        min_args: Minimum number of command line arguments
        usage_hint: Optional usage hint string
        extra_args: If True, pass all args after min_args to check_func
    """
    try:
        if len(sys.argv) < min_args:
            error_msg = f"Usage: {sys.argv[0]} <mode> <target_file> <workspace>"
            if usage_hint:
                error_msg += f" {usage_hint}"
            safe_output({"success": False, "error": error_msg})
            sys.exit(1)

        mode = sys.argv[1]
        if mode != expected_mode:
            safe_output({"success": False, "error": f"Unknown mode: {mode}, expected: {expected_mode}"})
            sys.exit(1)

        # Call check function with arguments
        # argv[0] = script name, argv[1] = mode, argv[2] = target_file, argv[3] = workspace, argv[4+] = extra
        if extra_args:
            result = check_func(*sys.argv[2:])
        else:
            result = check_func(*sys.argv[2:min_args])
        safe_output(result)
        sys.exit(0 if result.get("success", False) else 1)
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        safe_output({"success": False, "error": f"Fatal error in main: {str(e)}", "traceback": traceback.format_exc()})
        sys.exit(1)


def safe_output(data: dict):
    """Output JSON data, fallback to str if serialization fails."""
    try:
        print(json.dumps(data, ensure_ascii=False))
    except (TypeError, ValueError):
        try:
            print(json.dumps({k: str(v) for k, v in data.items()}, ensure_ascii=False))
        except:
            print(str(data))
    sys.stdout.flush()


def preload_so_if_needed(workspace: str, target_file: str):
    """
    Preload shared library (.so) files using ctypes to avoid TLS allocation errors.
    
    This must be called BEFORE load_module_from_file to ensure the .so is loaded
    early enough in the Python process lifecycle.
    
    Args:
        workspace: Workspace directory path
        target_file: Target file path being checked
    """
    # Check if we're in a context where .so files need preloading
    # Look for _tlm_pbsb.so in output/Adder directory
    target_dir = os.path.dirname(target_file)
    
    # Common patterns for finding .so files
    possible_so_locations = [
        os.path.join(target_dir, '..', 'Adder', '_tlm_pbsb.so'),
        os.path.join(workspace, 'output', 'Adder', '_tlm_pbsb.so'),
        os.path.join(workspace, 'examples', 'back', 'output', 'Adder', '_tlm_pbsb.so'),
    ]
    
    # Also check via environment variable if set
    env_so = os.environ.get('UCAGENT_PRELOAD_SO')
    if env_so:
        possible_so_locations.insert(0, env_so)
    
    for so_path in possible_so_locations:
        if so_path and os.path.exists(so_path):
            try:
                # Use RTLD_GLOBAL to make symbols available globally
                # Use RTLD_NOW to resolve all symbols immediately  
                ctypes.CDLL(so_path, mode=ctypes.RTLD_GLOBAL)
                # Success - only preload once
                return
            except Exception:
                # Continue trying other locations
                pass


def setup_python_paths(workspace: str, target_file: str):
    """Add workspace, target directory and output directories to sys.path."""
    import ucagent.util.functions as fc
    
    paths_to_add = [workspace, os.path.dirname(target_file)]
    output_dir = os.path.join(workspace, "examples", "back", "output")
    if os.path.exists(output_dir):
        paths_to_add.append(output_dir)
    
    fc.append_python_path([p for p in paths_to_add if p and os.path.exists(p)])


def load_module_from_file(target_file: str):
    """
    Dynamically load a Python module from file.
    
    Returns:
        Tuple[bool, Any, Optional[str]]: (success, module, error_message)
    """
    import ucagent.util.functions as fc
    
    try:
        module = fc.import_python_file(target_file)
        return True, module, None
    except ImportError as e:
        return False, None, f"Import error in '{target_file}': {str(e)}"
    except SyntaxError as e:
        return False, None, f"Syntax error in '{target_file}' line {e.lineno}: {str(e)}"
    except Exception as e:
        return False, None, f"Failed to load module '{target_file}': {str(e)}"


def get_actual_function(obj):
    """Get the actual function from a pytest fixture wrapper."""
    if hasattr(obj, '_pytestfixturefunction'):
        return getattr(obj._pytestfixturefunction, 'func', obj)
    if type(obj).__name__ == 'FixtureFunctionDefinition':
        return getattr(obj, 'func', getattr(obj, '_pytestfixturefunction', obj))
    return obj


def is_pytest_fixture(obj) -> bool:
    """Check if an object is a pytest fixture."""
    return (hasattr(obj, '_pytestfixturefunction') or
            type(obj).__name__ == 'FixtureFunctionDefinition' or
            "pytest_fixture" in str(obj))


def get_fixture_scope(obj) -> Optional[str]:
    """Get the scope of a pytest fixture."""
    if hasattr(obj, '_pytestfixturefunction'):
        return getattr(obj._pytestfixturefunction, 'scope', None)
    return getattr(obj, 'scope', None)


def check_function_signature(func: Any, expected_args: List[str]) -> Tuple[bool, Optional[str]]:
    """
    Check if a function has the expected signature.
    
    Args:
        func: The function to check
        expected_args: List of expected argument names
    
    Returns:
        Tuple[bool, Optional[str]]: (success, error_message)
    """
    import ucagent.util.functions as fc
    
    try:
        actual_args = fc.get_func_arg_list(func)
        
        if actual_args != expected_args:
            return False, f"Expected args ({', '.join(expected_args)}), got ({', '.join(actual_args)})"
        
        return True, None
    except Exception as e:
        return False, f"Failed to check function signature: {str(e)}"