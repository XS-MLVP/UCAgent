#!/usr/bin/env python3
"""
Subprocess script to inspect random test functions with LD_PRELOAD active.

This script runs in a separate process with LD_PRELOAD set, allowing it to
import test files that transitively load DUT shared libraries (.so) requiring
static TLS allocation.

Usage:
    python run_check_random_funcs.py <target_file> <workspace> <func_pattern>

Output (JSON):
    {
        "success": true,
        "functions": [
            {"name": "test_random_foo", "args": ["env"], "source": "def test_random_foo(env):..."},
            ...
        ]
    }
"""

import sys
import os

# Remove LD_PRELOAD before importing ucagent/git-dependent packages,
# but AFTER the .so has been loaded by the DUT package import below.
# We do this removal in common.remove_ld_preload_for_ucagent() at the right point.

import json
import importlib.util
import inspect
import fnmatch
import builtins


# ---------------------------------------------------------------------------
# Stub import hook – same pattern as get_api_functions.py / run_check_class.py
# Prevents ImportError for packages not needed for function inspection.
# ---------------------------------------------------------------------------

class _StubModule:
    """Stub module that silently absorbs all attribute access."""
    def __getattr__(self, name):
        return _StubModule()
    def __call__(self, *args, **kwargs):
        return _StubModule()
    def __iter__(self):
        return iter([])
    def __len__(self):
        return 0
    def __bool__(self):
        return False
    def __mro_entries__(self, bases):
        return (object,)
    def __getitem__(self, key):
        return _StubModule()


_original_import = builtins.__import__
# Packages that are not needed for function-signature inspection
_stub_packages = {
    'pytest', 'toffee_test', 'toffee', 'ucagent',
    'langchain_core', 'yaml', '_pytest',
    'pytest_asyncio', 'pluggy', 'packaging',
}


def _safe_import(name, *args, **kwargs):
    """Return stub for unwanted packages; re-raise for others."""
    try:
        return _original_import(name, *args, **kwargs)
    except ImportError:
        base_package = name.split('.')[0]
        if base_package in _stub_packages:
            return _StubModule()
        raise


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _get_func_source(source: str, node) -> str:
    """Extract source text for an AST node (fallback-safe)."""
    try:
        import ast
        seg = ast.get_source_segment(source, node)
        if seg:
            return seg
    except Exception:
        pass
    # Fallback: slice by line numbers
    lines = source.splitlines(keepends=True)
    start = node.lineno - 1
    end = getattr(node, 'end_lineno', node.lineno)
    return "".join(lines[start:end])


def inspect_random_funcs(target_file: str, workspace: str, func_pattern: str):
    """
    Import *target_file* (with LD_PRELOAD active in this subprocess) and return
    a list of functions whose names match *func_pattern*.

    Returns a dict suitable for JSON serialisation.
    """
    # Add workspace and target directory to sys.path so relative imports work
    for p in [workspace, os.path.dirname(os.path.abspath(target_file))]:
        if p and os.path.exists(p) and p not in sys.path:
            sys.path.insert(0, p)

    # Install stub hook so missing optional packages don't abort the import
    builtins.__import__ = _safe_import
    try:
        module_name = os.path.splitext(os.path.basename(target_file))[0]
        spec = importlib.util.spec_from_file_location(module_name, target_file)
        if spec is None or spec.loader is None:
            return {"success": False,
                    "error": f"Cannot create module spec for '{target_file}'"}
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except SyntaxError as e:
        return {"success": False,
                "error": f"Syntax error in '{target_file}' line {e.lineno}: {e}"}
    except Exception as e:
        return {"success": False,
                "error": f"Failed to import '{target_file}': {type(e).__name__}: {e}"}
    finally:
        builtins.__import__ = _original_import

    # Read source for getsource() fallback
    try:
        with open(target_file, 'r', encoding='utf-8', errors='replace') as f:
            source_text = f.read()
    except OSError:
        source_text = ""

    functions = []
    for name, obj in inspect.getmembers(module, inspect.isfunction):
        if not fnmatch.fnmatch(name, func_pattern):
            continue
        try:
            args = [p for p in inspect.signature(obj).parameters]
        except (ValueError, TypeError):
            args = []
        try:
            func_src = inspect.getsource(obj)
        except (OSError, TypeError):
            func_src = ""
        functions.append({"name": name, "args": args, "source": func_src})

    return {"success": True, "functions": functions}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 4:
        print(json.dumps({
            "success": False,
            "error": ("Usage: run_check_random_funcs.py "
                      "<target_file> <workspace> <func_pattern>")
        }))
        return 1

    target_file = sys.argv[1]
    workspace   = sys.argv[2]
    func_pattern = sys.argv[3]

    result = inspect_random_funcs(target_file, workspace, func_pattern)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
