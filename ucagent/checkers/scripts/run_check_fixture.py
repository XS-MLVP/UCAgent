#!/usr/bin/env python3
"""
Subprocess script to check pytest fixture validity with LD_PRELOAD active.

This script runs in a separate process with LD_PRELOAD set, allowing it to
load shared libraries that require static TLS allocation.

Usage:
    python run_check_fixture.py <target_file> <workspace> <fixture_pattern> <first_arg>
"""

import sys
import os
import json
import importlib.util
import inspect
import ast
import io
import builtins


class _StubModule:
    """Stub module that silently absorbs all attribute access."""
    def __getattr__(self, name):
        # Special handling for Signals class
        if name == 'Signals':
            return _signals_stub
        return _StubModule()
    def __call__(self, *args, **kwargs):
        # Return a StubTuple that can handle unpacking gracefully
        return _StubTuple()
    def __mro_entries__(self, bases):
        """Required for using stub as a base class."""
        return (object,)
    def __iter__(self):
        """Support unpacking operations like a, b = stub()."""
        return iter([])
    def __len__(self):
        """Support len() operations."""
        return 0
    def __bool__(self):
        """Support boolean operations."""
        return False
    def __getitem__(self, key):
        """Support indexing and slicing."""
        return _StubModule()


class _SignalsStub:
    """Special stub for toffee.Signals that returns correct number of signals."""
    def __call__(self, n):
        """Return n stub modules for unpacking."""
        return tuple(_StubModule() for _ in range(n))


# Create a singleton instance
_signals_stub = _SignalsStub()


class _StubTuple:
    """Special stub that behaves like a tuple for unpacking."""
    def __iter__(self):
        # Return empty iterator to avoid unpacking issues
        return iter([])
    def __len__(self):
        return 0
    def __getitem__(self, key):
        return _StubModule()
    def __bool__(self):
        return False


# Special pytest stub with working fixture decorator
class _PytestStub:
    """Special stub for pytest that provides a working fixture decorator."""
    @staticmethod
    def fixture(*args, **kwargs):
        """Stub fixture decorator that returns the function unchanged."""
        def decorator(func):
            # Mark the function so we can identify it later
            func._is_pytest_fixture = True
            return func
        
        # Handle both @pytest.fixture and @pytest.fixture()
        if len(args) == 1 and callable(args[0]) and not kwargs:
            # Direct decoration: @pytest.fixture
            func = args[0]
            func._is_pytest_fixture = True
            return func
        else:
            # Parametrized decoration: @pytest.fixture(...)
            return decorator
    
    def __getattr__(self, name):
        return _StubModule()


_original_import = builtins.__import__
_stub_packages = {'toffee_test', 'langchain_core', 'yaml', '_pytest',
                  'ucagent', 'pytest_asyncio', 'pluggy', 'packaging', 'toffee'}


def _safe_import(name, *args, **kwargs):
    """Import hook that returns stub modules for missing packages."""
    try:
        return _original_import(name, *args, **kwargs)
    except ImportError:
        # Check if this is one of the packages we want to stub
        base_package = name.split('.')[0]
        
        # Special handling for pytest
        if base_package == 'pytest':
            return _PytestStub()
        
        if base_package in _stub_packages:
            return _StubModule()
        raise


def main():
    if len(sys.argv) < 5:
        print(json.dumps({
            "success": False,
            "error": "Usage: run_check_fixture.py <target_file> <workspace> <fixture_pattern> <first_arg>"
        }))
        return 1
    
    target_file = sys.argv[1]
    workspace = sys.argv[2]
    fixture_pattern = sys.argv[3]
    expected_first_arg = sys.argv[4]
    
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
        
        # Capture stdout/stderr during module load to debug
        import io
        old_stdout, old_stderr = sys.stdout, sys.stderr
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        sys.stdout, sys.stderr = captured_stdout, captured_stderr
        
        try:
            spec.loader.exec_module(module)
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            load_stdout = captured_stdout.getvalue()
            load_stderr = captured_stderr.getvalue()
        
        # Find fixtures matching the pattern
        fixtures = []
        all_members = []
        for name, obj in inspect.getmembers(module):
            all_members.append(name)
            # Check if it's callable (function or decorated function)
            if not callable(obj):
                continue
            
            # Check if name matches pattern
            if fixture_pattern == "*" or name == fixture_pattern or \
               (fixture_pattern.endswith("*") and name.startswith(fixture_pattern[:-1])):
                fixtures.append((name, obj))
        
        if not fixtures:
            print(json.dumps({
                "success": False,
                "error": f"No fixture matching pattern '{fixture_pattern}' found in {target_file}. " + 
                         f"Found members: {', '.join(all_members[:20])}{'...' if len(all_members) > 20 else ''}. " +
                         f"Load stderr: {load_stderr[:200] if load_stderr else 'none'}",
                "error_key": "ucagent.is_imp_test_template"
            }))
            return 1
        
        # Validate each fixture
        for fname, func in fixtures:
            # Check signature (func should now be a plain function)
            try:
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())
                
                if expected_first_arg and (not params or params[0] != expected_first_arg):
                    print(json.dumps({
                        "success": False,
                        "error": f"Fixture '{fname}' first argument must be '{expected_first_arg}', got {params}",
                        "error_key": "fixture_signature"
                    }))
                    return 1
            except Exception as e:
                print(json.dumps({
                    "success": False,
                    "error": f"Failed to inspect fixture '{fname}' signature: {str(e)}"
                }))
                return 1
            
            # Check source for yield (for dut fixtures)
            if fixture_pattern in ["dut", "mock_dut"]:
                try:
                    source = inspect.getsource(func)
                    tree = ast.parse(source)
                    has_yield = any(isinstance(node, (ast.Yield, ast.YieldFrom)) 
                                   for node in ast.walk(tree))
                    if not has_yield:
                        print(json.dumps({
                            "success": False,
                            "error": f"Fixture '{fname}' must contain 'yield' statement for proper setup/teardown",
                            "error_key": "missing_yield"
                        }))
                        return 1
                    
                    # Check for get_coverage_data_path (dut fixture specific)
                    if fixture_pattern == "dut" and "get_coverage_data_path" not in source:
                        print(json.dumps({
                            "success": False,
                            "error": f"Fixture '{fname}' must call 'get_coverage_data_path(request, new_path=False)'",
                            "error_key": "get_coverage_data_path"
                        }))
                        return 1
                    
                    # Check for ucagent.get_mock_dut_from (mock_dut fixture specific)
                    if fixture_pattern == "mock_dut" and "ucagent.get_mock_dut_from" not in source:
                        print(json.dumps({
                            "success": False,
                            "error": f"Fixture '{fname}' must call 'ucagent.get_mock_dut_from'",
                            "error_key": "ucagent.get_mock_dut_from"
                        }))
                        return 1
                        
                except Exception as e:
                    print(json.dumps({
                        "success": False,
                        "error": f"Failed to check source of fixture '{fname}': {str(e)}"
                    }))
                    return 1
        
        print(json.dumps({
            "success": True,
            "fixtures_found": len(fixtures),
            "fixture_names": [f[0] for f in fixtures]
        }))
        return 0
        
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"Failed to validate fixtures: {str(e)}"
        }))
        return 1


if __name__ == "__main__":
    sys.exit(main())
