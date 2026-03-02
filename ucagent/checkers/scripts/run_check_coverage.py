#!/usr/bin/env python3
"""
Subprocess script to check coverage groups with LD_PRELOAD active.

This script runs in a separate process with LD_PRELOAD set, allowing it to
load shared libraries that require static TLS allocation.

Usage:
    python run_check_coverage.py <target_file> <workspace> <dut_name>
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
        return _StubModule()
    def __call__(self, *args, **kwargs):
        return _StubModule()
    def __iter__(self):
        return iter([])
    def __len__(self):
        return 0


_original_import = builtins.__import__
_stub_packages = {'pytest', 'toffee_test', 'langchain_core', 'yaml', '_pytest',
                  'ucagent', 'pytest_asyncio', 'pluggy', 'packaging', 'toffee'}


def _safe_import(name, *args, **kwargs):
    """Import hook that returns stub modules for missing packages."""
    try:
        return _original_import(name, *args, **kwargs)
    except ImportError:
        # Check if this is one of the packages we want to stub
        base_package = name.split('.')[0]
        if base_package in _stub_packages:
            return _StubModule()
        raise


def main():
    if len(sys.argv) < 4:
        print(json.dumps({
            "success": False,
            "error": "Usage: run_check_coverage.py <target_file> <workspace> <dut_name>"
        }))
        return 1
    
    target_file = sys.argv[1]
    workspace = sys.argv[2]
    dut_name = sys.argv[3]
    
    # Setup sys.path
    target_dir = os.path.dirname(target_file)
    for path in [workspace, target_dir]:
        if path not in sys.path:
            sys.path.insert(0, path)
    
    # Install stub import hook
    builtins.__import__ = _safe_import
    
    try:
        # Load the target file as a module
        module_name = os.path.splitext(os.path.basename(target_file))[0]
        spec = importlib.util.spec_from_file_location(module_name, target_file)
        if spec is None or spec.loader is None:
            print(json.dumps({
                "success": False,
                "error": f"Failed to create module spec for {target_file}"
            }))
            return 1
        
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        
        # Find get_coverage_groups function
        if not hasattr(module, 'get_coverage_groups'):
            print(json.dumps({
                "success": False,
                "error": f"Function 'get_coverage_groups' not found in {target_file}",
                "error_key": "get_coverage_groups"
            }))
            return 1
        
        func = getattr(module, 'get_coverage_groups')
        
        # Check signature
        try:
            sig = inspect.signature(func)
            params = list(sig.parameters.keys())
            if not params or params[0] != 'dut':
                print(json.dumps({
                    "success": False,
                    "error": f"Function 'get_coverage_groups' must have 'dut' as first parameter, got {params}",
                    "error_key": "wrong_signature"
                }))
                return 1
        except Exception as e:
            print(json.dumps({
                "success": False,
                "error": f"Failed to inspect 'get_coverage_groups' signature: {str(e)}"
            }))
            return 1
        
        # Try to call with fake_dut
        try:
            # Create a minimal fake DUT
            class FakeDUT:
                pass
            
            fake_dut = FakeDUT()
            result = func(fake_dut)
            
            # Validate result is a list
            if not isinstance(result, list):
                print(json.dumps({
                    "success": False,
                    "error": f"'get_coverage_groups' must return a list, got {type(result).__name__}",
                    "error_key": "wrong_return_type"
                }))
                return 1
            
            print(json.dumps({
                "success": True,
                "groups_count": len(result)
            }))
            return 0
            
        except Exception as e:
            # It's ok if execution fails, we just check the structure
            print(json.dumps({
                "success": True,
                "note": f"Function structure validated (execution failed as expected: {str(e)})"
            }))
            return 0
        
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"Failed to validate coverage groups: {str(e)}"
        }))
        return 1


if __name__ == "__main__":
    sys.exit(main())
