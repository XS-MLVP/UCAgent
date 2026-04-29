# -*- coding: utf-8 -*-
import os
import sys
import importlib.util
import inspect
import fnmatch
import builtins

# Import shared stub infrastructure from common.py
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
from common import make_safe_import

_original_import = builtins.__import__

def _get_func_source(source: str, node) -> str:
    """Extract source text for an AST node (fallback-safe)."""
    try:
        import ast
        seg = ast.get_source_segment(source, node)
        if seg:
            return seg
    except Exception:
        pass
    lines = source.splitlines(keepends=True)
    start = node.lineno - 1
    end = getattr(node, 'end_lineno', node.lineno)
    return "".join(lines[start:end])

def inspect_random_funcs(target_file: str, workspace: str, func_pattern: str):
    for p in [workspace, os.path.dirname(os.path.abspath(target_file))]:
        if p and os.path.exists(p) and p not in sys.path:
            sys.path.insert(0, p)

    builtins.__import__ = make_safe_import(_original_import)
    try:
        module_name = os.path.splitext(os.path.basename(target_file))[0]
        spec = importlib.util.spec_from_file_location(module_name, target_file)
        if spec is None or spec.loader is None:
            return {"success": False, "error": f"Cannot create module spec for '{target_file}'"}
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except SyntaxError as e:
        return {"success": False, "error": f"Syntax error in '{target_file}' line {e.lineno}: {e}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to import '{target_file}': {type(e).__name__}: {e}"}
    finally:
        builtins.__import__ = _original_import

    try:
        with open(target_file, 'r', encoding='utf-8', errors='replace') as f:
            source_text = f.read()
    except OSError:
        source_text = ""

    functions = []
    for name, obj in inspect.getmembers(module, inspect.isfunction):
        if not fnmatch.fnmatch(name, func_pattern):
            continue
        if getattr(obj, "__module__", None) != module_name:
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
