# -*- coding: utf-8 -*-
"""Common infrastructure for running checkers in isolated subprocesses.

When LD_PRELOAD is needed (e.g. VCS DUT shared libraries), checkers must
run in a subprocess so that ld.so can preload the .so before Python starts.
This module provides the parent-side launcher that:

1. Derives the correct cwd from the LD_PRELOAD path (VCS needs its
   simulation database in cwd).
2. Sets up PYTHONPATH so the checker can import the target modules.
3. Launches ``run_checker_stub.py`` and parses JSON output.
"""

import json
import os
import re
import subprocess
import sys
from typing import Tuple


def _find_real_python_binary() -> str:
    """Return the Python binary path that is currently running UCAgent."""
    return sys.executable


def _derive_dut_cwd(check_env: dict, workspace: str) -> str:
    """Derive the DUT directory from LD_PRELOAD for use as subprocess cwd.

    VCS simulation databases live next to the .so file, so the subprocess
    must run from that directory for ``synopsys::connect`` to succeed.

    Args:
        check_env: Environment dict potentially containing LD_PRELOAD.
        workspace: Fallback workspace directory.

    Returns:
        Absolute path to use as subprocess cwd.
    """
    ld_preload = check_env.get("LD_PRELOAD", "")
    if ld_preload:
        for part in ld_preload.split(":"):
            part = part.strip()
            if part and os.path.isfile(part):
                return os.path.dirname(os.path.abspath(part))
    return os.path.abspath(workspace)


def _build_pythonpath_parts(workspace: str, target_file: str = None) -> list:
    """Build PYTHONPATH entries for the subprocess."""
    parts = []
    # Add project root so subprocess can import ucagent.*
    # This file is at ucagent/checkers/scripts/common.py
    project_root = os.path.dirname(  # UCAgent/
        os.path.dirname(             # ucagent/
            os.path.dirname(         # checkers/
                os.path.dirname(     # scripts/
                    os.path.abspath(__file__)
                )
            )
        )
    )
    parts.append(project_root)
    ws = os.path.abspath(workspace)
    if os.path.isdir(ws) and ws != project_root:
        parts.append(ws)
    if target_file:
        target_dir = os.path.dirname(os.path.abspath(target_file))
        if target_dir not in parts and os.path.isdir(target_dir):
            parts.append(target_dir)
    return parts


def _parse_json_from_output(stdout: str) -> dict | None:
    """Extract the first JSON object from subprocess stdout.

    The subprocess may emit log lines before the JSON payload.
    We search for lines starting with ``{`` and try to parse them.
    """
    if not stdout:
        return None
    # Try to find a JSON block — look for lines starting with {
    for line in stdout.splitlines():
        line = line.strip()
        # Strip ANSI escape codes
        clean = re.sub(r"\x1b\[[0-9;]*m", "", line)
        if clean.startswith("{"):
            try:
                return json.loads(clean)
            except json.JSONDecodeError:
                continue
    return None


def run_isolated_check_json(
    checker_type: str,
    check_kwargs: dict,
    *,
    workspace: str,
    check_env: dict = None,
    timeout: int = 30,
) -> Tuple[bool, dict]:
    """Run a checker via run_checker_stub.py in an isolated subprocess.

    The subprocess receives exactly two positional arguments:
        sys.argv[1] = checker_type   (e.g. "dut_creation")
        sys.argv[2] = JSON string   (serialized check_kwargs)

    The subprocess runs with LD_PRELOAD in its environment so that the
    DUT shared library is loaded by ld.so before Python import.  The cwd
    is set to the directory containing the .so file.

    Args:
        checker_type: The checker type name for dispatch.
        check_kwargs: Dictionary of arguments to pass to the checker.
        workspace: Absolute path to the workspace directory.
        check_env: Dictionary of environment variables to inject.
        timeout: Maximum execution time in seconds.

    Returns:
        Tuple of (success: bool, result: dict).
    """
    if not check_env:
        return False, {"error": "check_env is required for isolated mode"}

    workspace = os.path.abspath(workspace)
    if not os.path.exists(workspace):
        return False, {"error": f"Invalid workspace: {workspace}"}

    helper_script = os.path.join(os.path.dirname(__file__), "run_checker_stub.py")
    if not os.path.exists(helper_script):
        return False, {"error": f"Helper script not found: {helper_script}"}

    # Build subprocess environment
    env = os.environ.copy()
    env.update(check_env)

    # Derive PYTHONPATH
    target_file = check_kwargs.get("target_file_path") or check_kwargs.get("target_file")
    pythonpath_parts = _build_pythonpath_parts(workspace, target_file)
    if pythonpath_parts:
        existing_path = env.get("PYTHONPATH", "")
        new_path = ":".join(pythonpath_parts)
        env["PYTHONPATH"] = f"{new_path}:{existing_path}" if existing_path else new_path

    # Derive cwd from LD_PRELOAD path (VCS needs .so in cwd)
    cwd = _derive_dut_cwd(check_env, workspace)

    json_str = json.dumps(check_kwargs, ensure_ascii=False)
    cmd = [_find_real_python_binary(), helper_script, checker_type, json_str]

    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
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
            "error": f"No JSON found in output. returncode: {proc.returncode}, stdout: {stdout_info}, stderr: {stderr_info}",
        }

    if proc.stderr and "stderr" not in result:
        result["stderr"] = proc.stderr[:500]
    return result.get("success", False), result
