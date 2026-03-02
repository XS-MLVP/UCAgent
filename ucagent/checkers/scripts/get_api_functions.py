#!/usr/bin/env python3
"""
Subprocess script to get API functions from a file.
This runs in a separate process with LD_PRELOAD set to avoid TLS errors.

Usage:
    python get_api_functions.py get_funcs <target_file> <workspace> <api_prefix>
"""
import sys
import os
import json
import importlib.util
import inspect
import builtins


class _StubModule:
    """Stub module that silently absorbs all attribute access."""
    def __getattr__(self, name):
        if name == 'Signals':
            return _signals_stub
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


class _SignalsStub:
    """Special stub for toffee.Signals that returns correct number of signals for unpacking."""
    def __call__(self, n, *args, **kwargs):
        return tuple(_StubModule() for _ in range(n))


_signals_stub = _SignalsStub()


_original_import = builtins.__import__
_stub_packages = {'pytest', 'toffee_test', 'langchain_core', 'yaml', '_pytest',
                  'toffee', 'ucagent', 'pytest_asyncio', 'pluggy', 'packaging'}


def _safe_import(name, *args, **kwargs):
    """Import hook that returns stub modules for packages that aren't needed."""
    try:
        return _original_import(name, *args, **kwargs)
    except ImportError:
        base_package = name.split('.')[0]
        if base_package in _stub_packages:
            return _StubModule()
        raise


def get_api_functions(target_file: str, workspace: str, api_prefix: str):
    """Get API functions matching the prefix from the specified file."""
    # Add workspace and target dir to sys.path
    for p in [workspace, os.path.dirname(target_file)]:
        if p and os.path.exists(p) and p not in sys.path:
            sys.path.insert(0, p)

    # Install safe import hook before loading the target module
    builtins.__import__ = _safe_import
    try:
        spec = importlib.util.spec_from_file_location("api_module", target_file)
        if spec is None or spec.loader is None:
            return {"success": False, "error": f"Failed to load module spec from {target_file}"}
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except ImportError as e:
        return {"success": False, "error": f"Failed to import and process {target_file}: {str(e)}"}
    except SyntaxError as e:
        return {"success": False, "error": f"Syntax error in '{target_file}' line {e.lineno}: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to import and process {target_file}: {str(e)}"}
    finally:
        builtins.__import__ = _original_import

    # Extract functions matching the prefix
    functions = [
        name for name, obj in inspect.getmembers(module)
        if inspect.isfunction(obj) and name.startswith(api_prefix)
    ]
    return {"success": True, "functions": functions}


if __name__ == "__main__":
    if len(sys.argv) < 5 or sys.argv[1] != "get_funcs":
        print(json.dumps({"success": False, "error": "Usage: get_api_functions.py get_funcs <target_file> <workspace> <api_prefix>"}))
        sys.exit(1)

    _, _, target_file, workspace, api_prefix = sys.argv[:5]
    result = get_api_functions(target_file, workspace, api_prefix)
    try:
        print(json.dumps(result, ensure_ascii=False))
    except (TypeError, ValueError):
        print(json.dumps({k: str(v) for k, v in result.items()}, ensure_ascii=False))
    sys.stdout.flush()
    sys.exit(0 if result.get("success", False) else 1)
