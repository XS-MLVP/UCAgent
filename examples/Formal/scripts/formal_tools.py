# -*- coding: utf-8 -*-
"""Formal verification tools for the Formal workflow example."""

import glob
import math
import os
import re
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple

import psutil
import pyslang
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field

from ucagent.tools.fileops import BaseReadWrite
from ucagent.tools.uctool import UCTool
from ucagent.util.log import str_error, str_info

from examples.Formal.scripts.formal_adapter import get_adapter

__all__ = [
    "parse_avis_log",
    "parse_env_analysis_doc",
    "extract_rtl_bug_from_analysis_doc",
    "extract_python_test_functions",
    "_terminate_process_tree",
    "run_formal_command_sync",
]


# =============================================================================
# Shared Utilities
# =============================================================================


def parse_avis_log(log_path: str) -> Dict[str, list]:
    """Parse formal log and return property result statistics.

    This is the single source of truth for log parsing, shared by
    ``RunFormalVerification`` and all Checker classes that need to
    inspect verification results.

    Returns a dict with the following keys:
        pass            – list of assert properties that passed
        trivially_true  – list of assert TRIVIALLY_TRUE properties
        false           – list of assert properties that failed
        cover_pass      – list of cover properties that passed
        cover_fail      – list of cover properties that failed
    """
    adapter = get_adapter()
    return adapter.parse_log(log_path)




def parse_env_analysis_doc(doc_path: str) -> dict:
    """Parse analysis document.
    
    Returns a dictionary with:
    - tt_entries: Output of TT blocks.
    - fa_entries: Output of FA blocks.
    - raw_content: Raw str.
    """
    result = {"tt_entries": {}, "fa_entries": {}, "raw_content": ""}
    if not os.path.exists(doc_path):
        return result
        
    with open(doc_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    result["raw_content"] = content

    tt_pattern = re.compile(
        r'###\s*<(TT-\d+)>\s*(\S+)\s*\n(.*?)(?=###\s*<(?:TT|FA)-\d+>|^---$|^## \d+\.|\Z)',
        re.DOTALL | re.MULTILINE
    )
    fa_pattern = re.compile(
        r'###\s*<(FA-\d+)>\s*(\S+)\s*\n(.*?)(?=###\s*<(?:TT|FA)-\d+>|^---$|^## \d+\.|\Z)',
        re.DOTALL | re.MULTILINE
    )
    
    def _parse_entry_body(body: str, is_tt: bool) -> dict:
        entry = {}
        def _ext(field_name, text):
            pat = re.compile(
                rf'[-*]*\s*\*\*{re.escape(field_name)}\*\*\s*:\s*(.*?)(?=\n\s*[-*]*\s*\*\*|\n```|\Z)',
                re.DOTALL
            )
            m = pat.search(text)
            return m.group(1).strip() if m else None

        entry["prop_name_field"] = _ext("属性名", body) or _ext("Property", body)
        if is_tt:
            entry["root_cause"] = _ext("根因分类", body) or _ext("Root Cause", body) or ""
            entry["related_assume"] = _ext("关联 Assume", body) or _ext("Related Assume", body) or ""
            entry["action"] = _ext("修复动作", body) or _ext("Fix Action", body) or ""
            entry["action_detail"] = _ext("修复说明", body) or _ext("Fix Detail", body) or ""
        else:
            entry["resolution"] = _ext("解决状态", body) or _ext("Resolution", body) or _ext("判定结果", body) or _ext("Judgment", body) or ""
            entry["action_detail"] = _ext("修复说明", body) or _ext("Fix Detail", body) or ""
            entry["prop_type"] = _ext("属性类型", body) or _ext("Property Type", body) or ""

        entry["analysis"] = _ext("分析", body) or _ext("Analysis", body) or _ext("反例/分析", body) or ""
        return entry

    for match in tt_pattern.finditer(content):
        tt_id = match.group(1).strip()
        prop_name = match.group(2).strip()
        entry = _parse_entry_body(match.group(3), is_tt=True)
        entry["prop_name"] = prop_name
        entry["id"] = tt_id
        result["tt_entries"][prop_name] = entry

    for match in fa_pattern.finditer(content):
        fa_id = match.group(1).strip()
        prop_name = match.group(2).strip()
        entry = _parse_entry_body(match.group(3), is_tt=False)
        entry["prop_name"] = prop_name
        entry["id"] = fa_id
        result["fa_entries"][prop_name] = entry

    return result

def extract_rtl_bug_from_analysis_doc(analysis_path: str) -> List[Tuple[str, str]]:
    """Extract RTL_BUG property names and FA IDs from the analysis document.

    This is the single source of truth for RTL bug identification.
    Returns a list of (fa_id, prop_name) tuples,
    e.g. ``[('FA-001', 'A_CK_SUM_WIDTH'), ...]``.
    """
    doc = parse_env_analysis_doc(analysis_path)
    rtl_bugs = []
    
    # We iterate properly checking resolution
    for prop_name, entry in doc.get("fa_entries", {}).items():
        if entry.get("resolution", "").strip().upper() == "RTL_BUG" or "RTL_BUG" in entry.get("resolution", "").strip().upper():
            rtl_bugs.append((entry["id"], prop_name))
            
    # Sort to remain consistent behavior
    rtl_bugs.sort(key=lambda x: str(x[0]))
    return rtl_bugs


def extract_python_test_functions(test_path: str) -> dict:
    """Extract test function details from the Python test file.
    Returns: { 'test_cex_A_CK_XXX': {'has_assert': bool, 'has_finish': bool}, ... }
    """
    functions = {}
    if not os.path.exists(test_path):
        return functions

    with open(test_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    func_pattern = re.compile(r'^def\s+(test_cex_\w+)\s*\(', re.MULTILINE)
    func_matches = list(func_pattern.finditer(content))

    for idx, match in enumerate(func_matches):
        func_name = match.group(1)
        # Get the function body (until the next def or end of file)
        start = match.start()
        if idx + 1 < len(func_matches):
            end = func_matches[idx + 1].start()
        else:
            end = len(content)
        func_body = content[start:end]

        functions[func_name] = {
            'has_assert': 'assert ' in func_body,
            'has_finish': 'Finish()' in func_body,
        }

    return functions


def _terminate_process_tree(proc: subprocess.Popen, timeout: int = 5) -> None:
    """Gracefully terminate a process and all its children."""
    try:
        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)
        # Terminate children first, then parent
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        try:
            parent.terminate()
        except psutil.NoSuchProcess:
            pass
        # Wait for all to exit
        gone, alive = psutil.wait_procs(children + [parent], timeout=timeout)
        # Force-kill any survivors
        for p in alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass
    except Exception:
        # Last resort
        try:
            proc.kill()
        except Exception:
            pass


def run_formal_command_sync(cmd: List[str], exec_dir: str, timeout: int = 300, on_start=None) -> Tuple[bool, str, str, str]:
    """Execute formal command synchronously with timeout and cleanup.
    
    Args:
        cmd: Command list to execute
        exec_dir: Working directory
        timeout: Execution timeout in seconds
        on_start: Optional callback function triggered immediately after Popen with the worker instance.
        
    Returns:
        (success, stdout, stderr, error_msg)
    """
    stdout_log = ""
    stderr_log = ""
    try:
        worker = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=exec_dir
        )
        if on_start:
            on_start(worker)
            
        try:
            stdout_log, stderr_log = worker.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _terminate_process_tree(worker, timeout=5)
            # Fetch any remaining output after termination
            stdout_log, stderr_log = worker.communicate()
            return False, stdout_log, stderr_log, f"Timeout after {timeout} seconds"

        if worker.returncode != 0:
            return False, stdout_log, stderr_log, f"Return code {worker.returncode}"
            
        return True, stdout_log, stderr_log, ""

    except FileNotFoundError:
        return False, "", "", f"Command '{cmd[0]}' not found"
    except Exception as e:
        return False, "", "", f"Execution error: {e}"



