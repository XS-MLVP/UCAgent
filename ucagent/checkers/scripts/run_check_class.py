#!/usr/bin/env python3
"""
Subprocess script to check class definitions with LD_PRELOAD active.

This script runs in a separate process with LD_PRELOAD set, allowing it to
load shared libraries that require static TLS allocation.

Usage:
    python run_check_class.py <target_file> <workspace> <class_pattern> <base_class_name>
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
        # Return a stub class for common base classes like Bundle
        if name in ('Bundle', 'Component', 'Mock', 'CovGroup', 'Signal'):
            return _StubBaseClass
        return _StubModule()
    def __call__(self, *args, **kwargs):
        # Return a mock object that can be used in assignments
        return _MockObject()
    def __iter__(self):
        return iter([])
    def __len__(self):
        return 0
    def __mro_entries__(self, bases):
        """Required for using stub as a base class."""
        return (object,)


class _MockObject:
    """Mock object that can be used as any value."""
    def __getattr__(self, name):
        return _MockObject()
    def __call__(self, *args, **kwargs):
        return _MockObject()
    def __iter__(self):
        return iter([])
    def __len__(self):
        return 0
    def __bool__(self):
        return True
    def __int__(self):
        return 0
    def __str__(self):
        return ""


class _StubBaseClass:
    """Stub class that can be used as a base class."""
    def __init_subclass__(cls, **kwargs):
        # Allow subclassing without errors
        super().__init_subclass__(**kwargs)
    
    def __init__(self, *args, **kwargs):
        pass
    
    @classmethod
    def from_dict(cls, *args, **kwargs):
        """Stub for Bundle.from_dict method."""
        return _MockObject()
    
    def bind(self, *args, **kwargs):
        """Stub for Bundle.bind method."""
        pass
    
    def set_all(self, *args, **kwargs):
        """Stub for Bundle.set_all method."""
        pass


_original_import = builtins.__import__
_stub_packages = {'pytest', 'toffee_test', 'langchain_core', 'yaml', '_pytest', 
                  'toffee', 'ucagent', 'pytest_asyncio', 'pluggy', 'packaging'}


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
            "error": "Usage: run_check_class.py <target_file> <workspace> <class_pattern> [base_class_name]"
        }))
        return 1
    
    target_file = sys.argv[1]
    workspace = sys.argv[2]
    class_pattern = sys.argv[3]
    expected_base = sys.argv[4] if len(sys.argv) > 4 else None
    
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
        
        # Execute module with error capture
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            print(json.dumps({
                "success": False,
                "error": f"Failed to execute module {target_file}: {type(e).__name__}: {str(e)}"
            }))
            return 1
        
        # Find classes matching the pattern
        classes = []
        for name, obj in inspect.getmembers(module):
            if inspect.isclass(obj):
                # Check if name matches pattern
                if class_pattern == "*" or name == class_pattern or \
                   (class_pattern.endswith("*") and name.startswith(class_pattern[:-1])) or \
                   (class_pattern.startswith("*") and name.endswith(class_pattern[1:])):
                    classes.append((name, obj))
        
        if not classes:
            print(json.dumps({
                "success": False,
                "error": f"No class matching pattern '{class_pattern}' found in {target_file}",
                "error_key": "class_not_found"
            }))
            return 1
        
        # Validate base class if specified
        if expected_base:
            for cname, cls in classes:
                bases = [b.__name__ for b in cls.__bases__]
                if expected_base not in bases:
                    print(json.dumps({
                        "success": False,
                        "error": f"Class '{cname}' does not inherit from '{expected_base}', bases: {bases}",
                        "error_key": "wrong_base_class"
                    }))
                    return 1
        
        print(json.dumps({
            "success": True,
            "classes_found": len(classes),
            "class_names": [c[0] for c in classes]
        }))
        return 0
        
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"Failed to validate classes: {str(e)}"
        }))
        return 1


if __name__ == "__main__":
    sys.exit(main())
