#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Universal checker script runner with optional LD_PRELOAD support."""

import os
import sys
import json
import subprocess
import re


def run_check(workspace, target_file, helper_script_name, check_mode, *args, 
              timeout=30, dut_name=None, so_file=None):
    """
    Unified checker execution function.

    Execution modes:
    - so_file is None: Direct Python import (faster, no subprocess)
    - so_file provided: Subprocess with LD_PRELOAD set BEFORE Python starts

    Args:
        workspace: Workspace directory path
        target_file: Path to the file to check (absolute path)
        helper_script_name: Name of the helper script
        check_mode: Mode to pass to helper script
        *args: Additional arguments to pass to helper script
        timeout: Timeout in seconds for subprocess mode
        dut_name: Optional DUT name
        so_file: Path to .so file for LD_PRELOAD (None = direct import)

    Returns:
        Tuple[bool, dict]: (success, result_dict)
    """
    # Validate basic inputs
    if not os.path.exists(workspace):
        return False, {"error": f"Invalid workspace: {workspace}"}
    if not os.path.exists(target_file):
        return False, {"error": f"Invalid target_file: {target_file}"}
    
    try:
        # Path 1: Direct import execution (no LD_PRELOAD needed)
        if so_file is None:
            module_name = helper_script_name.replace('.py', '')
            function_name_map = {'check_dut_creation': 'check_create_dut'}
            function_name = function_name_map.get(module_name, module_name)
            
            import importlib
            checker_module = importlib.import_module(f'ucagent.checkers.scripts.{module_name}')
            
            if not hasattr(checker_module, function_name):
                return False, {"error": f"Function '{function_name}' not found in module '{module_name}'"}
            
            checker_func = getattr(checker_module, function_name)
            result = checker_func(target_file, workspace, *args)
            return result.get("success", False), result
        
        # Path 2: Subprocess execution with LD_PRELOAD set before Python starts
        else:
            if not os.path.exists(so_file):
                return False, {"error": f"Shared library not found: {so_file}"}
            
            helper_script = os.path.join(os.path.dirname(__file__), helper_script_name)
            if not os.path.exists(helper_script):
                return False, {"error": f"Helper script not found: {helper_script}"}
            
            # Setup environment with LD_PRELOAD
            env = os.environ.copy()
            env['LD_PRELOAD'] = so_file
            
            # Build PYTHONPATH
            from .path_manager import PathManager
            path_mgr = PathManager(workspace, dut_name)
            target_dir = os.path.dirname(target_file)
            pythonpath_parts = path_mgr.build_python_paths(target_dir)
            
            if workspace not in pythonpath_parts:
                pythonpath_parts.insert(0, workspace)
            
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(script_dir)))
            if project_root not in pythonpath_parts and os.path.exists(os.path.join(project_root, 'ucagent')):
                pythonpath_parts.insert(0, project_root)
            
            if pythonpath_parts:
                existing_path = env.get('PYTHONPATH', '')
                new_path = ':'.join(pythonpath_parts)
                env['PYTHONPATH'] = f"{new_path}:{existing_path}" if existing_path else new_path
            
            # Execute subprocess with LD_PRELOAD set
            cmd = [sys.executable, helper_script, check_mode, target_file, workspace] + list(args)
            cwd = os.path.dirname(so_file) or workspace
            result = subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True, timeout=timeout)
            
            # Parse JSON output
            json_data = _parse_json_from_output(result.stdout)
            if json_data is None:
                stderr_info = result.stderr[:500] if result.stderr else ""
                stdout_info = result.stdout[:500] if result.stdout else ""
                return False, {"error": f"No JSON found in output. stdout: {stdout_info}, stderr: {stderr_info}"}
            
            success = json_data.get("success", False)
            return (True, {"message": json_data.get("message", "Check passed.")}) if success else \
                   (False, {"error": json_data.get("error", "Unknown error during check.")})
    
    except subprocess.TimeoutExpired:
        return False, {"error": f"Check timed out after {timeout} seconds."}
    except Exception as e:
        import traceback
        return False, {"error": f"Failed to run check: {str(e)}", "traceback": traceback.format_exc()}


# Backward compatibility alias
run_with_ld_preload = run_check


def _parse_json_from_output(output: str):
    """Parse JSON from subprocess output."""
    # Try to find JSON object in output
    for line in output.splitlines():
        line = line.strip()
        if line.startswith('{'):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    # Try regex pattern to find JSON
    json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
    matches = re.findall(json_pattern, output, re.DOTALL)
    for match in matches:
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue

    return None
