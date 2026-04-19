# -*- coding: utf-8 -*-
"""Formal verification tools for the Formal workflow example."""
import os
import re
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple, Set
import psutil
from ucagent.util.log import str_error, str_info, warning, info
from examples.Formal.scripts.formal_adapter import get_adapter
__all__ = [
    "parse_avis_log",
    "parse_env_analysis_doc",
    "extract_rtl_bug_from_analysis_doc",
    "extract_python_test_functions",
    "run_formal_command_sync",
    "resolve_paths",
    "resolve_formal_paths",
    "normalize_output_dir",
    "get_workspace_root",
    "get_formal_test_dir",
    "get_formal_tests_dir",
    "strip_prop_prefix",
    "extract_property_code",
    "extract_property_details",
    "parse_bug_report_properties",
    "extract_static_bugs",
    "extract_formal_bug_tags",
    "analyze_signal_coverage_usage",
    "run_formal_verification",
    "summarize_execution",
]
# =============================================================================
# Shared Utilities
# =============================================================================
def parse_avis_log(log_path: str) -> Dict[str, list]:
    adapter = get_adapter()
    return adapter.parse_log(log_path)
def _extract_field(field_name: str, text: str) -> Optional[str]:
    pat = re.compile(
        rf'[-*]*\s*\*\*{re.escape(field_name)}\*\*\s*:\s*(.*?)(?=\n\s*[-*]*\s*\*\*|\n```|\Z)',
        re.DOTALL
    )
    m = pat.search(text)
    return m.group(1).strip() if m else None
def parse_env_analysis_doc(doc_path: str) -> dict:
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
        entry["prop_name_field"] = _extract_field("属性名", body) or _extract_field("Property", body)
        if is_tt:
            entry["root_cause"] = _extract_field("根因分类", body) or _extract_field("Root Cause", body) or ""
            entry["related_assume"] = _extract_field("关联 Assume", body) or _extract_field("Related Assume", body) or ""
            entry["action"] = _extract_field("修复动作", body) or _extract_field("Fix Action", body) or ""
            entry["action_detail"] = _extract_field("修复说明", body) or _extract_field("Fix Detail", body) or ""
        else:
            entry["resolution"] = _extract_field("解决状态", body) or _extract_field("Resolution", body) or _extract_field("判定结果", body) or _extract_field("Judgment", body) or ""
            entry["action_detail"] = _extract_field("修复说明", body) or _extract_field("Fix Detail", body) or ""
            entry["prop_type"] = _extract_field("属性类型", body) or _extract_field("Property Type", body) or ""
        entry["analysis"] = _extract_field("分析", body) or _extract_field("Analysis", body) or _extract_field("反例/分析", body) or ""
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
    doc = parse_env_analysis_doc(analysis_path)
    rtl_bugs = []
    for prop_name, entry in doc.get("fa_entries", {}).items():
        if entry.get("resolution", "").strip().upper() == "RTL_BUG":
            rtl_bugs.append((entry["id"], prop_name))
    rtl_bugs.sort(key=lambda x: str(x[0]))
    return rtl_bugs
def extract_python_test_functions(test_path: str) -> dict:
    functions = {}
    if not os.path.exists(test_path):
        return functions
    with open(test_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    func_pattern = re.compile(r'^def\s+(test_cex_\w+)\s*\(', re.MULTILINE)
    func_matches = list(func_pattern.finditer(content))
    for idx, match in enumerate(func_matches):
        func_name = match.group(1)
        start = match.start()
        end = func_matches[idx + 1].start() if idx + 1 < len(func_matches) else len(content)
        func_body = content[start:end]
        functions[func_name] = {
            'has_assert': 'assert ' in func_body,
            'has_finish': 'Finish()' in func_body,
        }
    return functions
def _terminate_process_tree(proc: subprocess.Popen, timeout: int = 5) -> None:
    try:
        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        try:
            parent.terminate()
        except psutil.NoSuchProcess:
            pass
        gone, alive = psutil.wait_procs(children + [parent], timeout=timeout)
        for p in alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
def run_formal_command_sync(cmd: List[str], exec_dir: str, timeout: int = 300, on_start=None) -> Tuple[bool, str, str, str]:
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
            stdout_log, stderr_log = worker.communicate()
            return False, stdout_log, stderr_log, f"Timeout after {timeout} seconds"
        if worker.returncode != 0:
            return False, stdout_log, stderr_log, f"Return code {worker.returncode}"
        return True, stdout_log, stderr_log, ""
    except FileNotFoundError:
        return False, "", "", f"Command '{cmd[0]}' not found"
    except Exception as e:
        return False, "", "", f"Execution error: {e}"
def run_formal_verification(tcl_path: str, timeout: int = 300, on_start=None) -> dict:
    """Executes formal verification script and returns structured results."""
    adapter = get_adapter()
    exec_dir = os.path.dirname(tcl_path)
    log_path = os.path.join(exec_dir, adapter.log_filename())
    cmd = adapter.build_command(tcl_path, exec_dir)
    success, stdout, stderr, err_msg = run_formal_command_sync(cmd, exec_dir, timeout, on_start)
    if not success:
        return {
            "success": False, "error": err_msg, "log_path": log_path,
            "parsed_log": None, "blackbox_count": 0, "has_results": False,
            "stdout": stdout, "stderr": stderr
        }
    if not os.path.exists(log_path):
        return {
            "success": False, "error": "Log not generated", "log_path": log_path,
            "parsed_log": None, "blackbox_count": 0, "has_results": False,
            "stdout": stdout, "stderr": stderr
        }
    with open(log_path, 'r', encoding='utf-8') as f:
        log_content = f.read()
    blackbox_count = adapter.extract_blackbox_count(log_content)
    has_results = adapter.validate_log_has_results(log_content)
    parsed_log = parse_avis_log(log_path) if has_results else None
    return {
        "success": has_results,
        "error": None if has_results else "No valid results in log",
        "log_path": log_path,
        "parsed_log": parsed_log,
        "blackbox_count": blackbox_count,
        "has_results": has_results,
        "stdout": stdout,
        "stderr": stderr
    }
def summarize_execution(stdout: str, stderr: str, max_chars: int = 1500) -> str:
    """Summarizes stdout and stderr into a single string for LLM consumption, truncating if necessary."""
    def trunc(txt: str) -> str:
        if not txt: return ""
        if len(txt) <= max_chars: return txt
        half = max_chars // 2
        return txt[:half] + "\n\n... [LOG TRUNCATED, SHOWING START AND END] ...\n\n" + txt[-half:]
    res = []
    if stderr:
        res.append(f"--- STDERR ---\n{trunc(stderr)}")
    if stdout and "Return code" not in stdout: # just sanity
        # if stdout is extremely long we truncate it as well
        res.append(f"--- STDOUT ---\n{trunc(stdout)}")
    return "\n".join(res) if res else "(empty)"
def resolve_paths(dut_name: str, output_dir: str = "formal_test", **kwargs) -> dict:
    workspace = os.environ.get("UCAGENT_WORKSPACE", os.getcwd())
    formal_test_dir = os.path.join(workspace, output_dir)
    tests_dir = os.path.join(formal_test_dir, "tests")
    adapter = get_adapter()
    rtl_dir = kwargs.get("rtl_dir")
    if not rtl_dir:
        rtl_dir = os.path.abspath(os.path.join(workspace, dut_name))
    elif not os.path.isabs(rtl_dir):
        rtl_dir = os.path.abspath(os.path.join(workspace, rtl_dir))
    return {
        "workspace":      workspace,
        "rtl_dir":        rtl_dir,
        "checker_file":   kwargs.get("checker_file")   or os.path.join(tests_dir, f"{dut_name}_checker.sv"),
        "wrapper_file":   kwargs.get("wrapper_file")   or os.path.join(tests_dir, f"{dut_name}_wrapper.sv"),
        "spec_file":      kwargs.get("spec_file")      or os.path.join(formal_test_dir, f"03_{dut_name}_functions_and_checks.md"),
        "tcl_script":     kwargs.get("tcl_script")     or os.path.join(tests_dir, f"{dut_name}_formal.tcl"),
        "log_file":       kwargs.get("log_file")       or os.path.join(tests_dir, adapter.log_filename()),
        "fanin_rep":      kwargs.get("fanin_rep")      or adapter.coverage_report_path(tests_dir),
        "docs_dir":       kwargs.get("docs_dir")       or formal_test_dir,
        "analysis_doc":   kwargs.get("analysis_doc")   or os.path.join(formal_test_dir, f"07_{dut_name}_env_analysis.md"),
        "bug_report_doc": kwargs.get("bug_report_doc") or os.path.join(formal_test_dir, f"04_{dut_name}_bug_report.md"),
        "static_doc":     kwargs.get("static_doc")     or os.path.join(formal_test_dir, f"04_{dut_name}_static_bug_analysis.md"),
        "test_file":      kwargs.get("test_file")      or os.path.join(tests_dir, f"test_{dut_name}_counterexample.py"),
        "rtl_path":       kwargs.get("rtl_path")       or os.path.join(workspace, dut_name, f"{dut_name}.v"),
    }

def get_workspace_root() -> str:
    return os.environ.get("UCAGENT_WORKSPACE", os.getcwd())

def normalize_output_dir(output_dir: str) -> str:
    out = output_dir.rstrip("/")
    if out.endswith("/tests"):
        return out[:-6]
    return out

def get_formal_test_dir(output_dir: str) -> str:
    return os.path.join(get_workspace_root(), output_dir)

def get_formal_tests_dir(output_dir: str) -> str:
    return os.path.join(get_formal_test_dir(output_dir), "tests")

from typing import Mapping
def resolve_formal_paths(
    dut_name: str,
    output_dir: str,
    path_specs: Mapping[str, Tuple[str, str]],
    overrides: Optional[Mapping[str, Optional[str]]] = None,
) -> Dict[str, str]:
    """Build common formal artifact paths from templates.

    path_specs value is a tuple: (base_dir_kind, filename_template).
    base_dir_kind supports: workspace | formal | tests.
    filename_template supports {dut_name} placeholder.
    """
    dirs = {
        "workspace": get_workspace_root(),
        "formal": get_formal_test_dir(output_dir),
        "tests": get_formal_tests_dir(output_dir),
    }
    resolved: Dict[str, str] = {}
    overrides = overrides or {}

    for key, (base_kind, filename_tmpl) in path_specs.items():
        override = overrides.get(key)
        if override:
            resolved[key] = override
            continue

        base_dir = dirs.get(base_kind)
        if base_dir is None:
            raise ValueError(f"Unsupported base dir kind: {base_kind}")
            
        resolved[key] = os.path.join(base_dir, filename_tmpl.format(dut_name=dut_name))

    return resolved

def strip_prop_prefix(prop_name: str) -> str:
    for prefix in ("A_CK_", "M_CK_", "C_CK_", "CK_", "A_", "M_", "C_"):
        if prop_name.startswith(prefix):
            return prop_name[len(prefix):]
    return prop_name

def extract_property_details(content: str) -> dict:
    """Extract property details ``{name: {body, type}}`` from checker.sv content.

    Args:
        content: Raw SystemVerilog source text (NOT a file path).

    Returns:
        Dict mapping ``CK_*`` property names to ``{'body': str, 'type': str|None}``.
    """
    details = {}
    if not content:
        return details
    try:
        prop_blocks = re.findall(r'property\s+(CK_[A-Za-z0-9_]+)\s*;(.*?)\bendproperty', content, re.DOTALL)
        for name, body in prop_blocks:
            details[name] = {'body': body, 'type': None}
        stmt_matches = re.findall(r'(\w+)\s*:\s*(assert|assume|cover)\s+property\s*\((CK_[A-Za-z0-9_]+)\)', content)
        for inst_label, p_type, prop_name in stmt_matches:
            if prop_name in details:
                details[prop_name]['type'] = p_type
        return details
    except Exception as e:
        warning(f"Failed to extract property details: {e}")
        return {}

def extract_property_code(checker_content: str, prop_name: str) -> str:
    if not checker_content:
        return f"  // Property code unavailable for {prop_name}"
    pattern = re.compile(
        rf"(property\s+(?:(?:A|M|C)_)?{re.escape(prop_name)}[\s;].*?endproperty)",
        re.DOTALL,
    )
    match = pattern.search(checker_content)
    if match:
        return "\n".join("  " + line for line in match.group(1).split("\n"))
    pattern_inline = re.compile(
        rf"(?:assert|assume|cover)\s+property\s*\([^;]*{re.escape(prop_name)}[^;]*\)\s*;"
    )
    match = pattern_inline.search(checker_content)
    if match:
        return f"  {match.group(0)}"
    core_name = strip_prop_prefix(prop_name)
    if core_name != prop_name:
        pattern_core = re.compile(
            rf"(property\s+.*?{re.escape(core_name)}.*?;.*?endproperty)",
            re.DOTALL,
        )
        match = pattern_core.search(checker_content)
        if match:
            return "\n".join("  " + line for line in match.group(1).split("\n"))
    lines = checker_content.split("\n")
    for i, line in enumerate(lines):
        if prop_name in line and ("assert" in line or "property" in line or ":" in line):
            return "\n".join(lines[max(0, i - 3):min(len(lines), i + 6)])
    for i, line in enumerate(lines):
        if prop_name in line:
            return "\n".join(lines[max(0, i - 2):min(len(lines), i + 4)])
    return f"  // Property definition not found for {prop_name}"
def parse_bug_report_properties(content: str) -> Set[str]:
    report_sections = re.split(r'##\s*❌?\s*Failed Property:\s*`?([\w.]+)`?', content)
    reported_props = set()
    for i in range(1, len(report_sections), 2):
        prop_name = report_sections[i].strip()
        short_name = prop_name.split('.')[-1] if '.' in prop_name else prop_name
        reported_props.add(short_name)
    return reported_props
def extract_static_bugs(static_path: str) -> dict:
    result = {"pending": [], "confirmed": [], "false_positive": []}
    if not os.path.exists(static_path): return result
    with open(static_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    bg_pattern = re.compile(r'(<BG-STATIC-[A-Za-z0-9_-]+>)')
    bg_matches = bg_pattern.findall(content)
    link_pattern = re.compile(r'(<LINK-BUG-\[([^\]]+)\]>)')
    for bg_id in bg_matches:
        bg_pos = content.find(bg_id)
        if bg_pos == -1: continue
        search_range = content[bg_pos:bg_pos + 500]
        link_matches = link_pattern.findall(search_range)
        if link_matches:
            for full_tag, link_value in link_matches:
                if link_value == "BG-TBD": result["pending"].append((bg_id, full_tag))
                elif link_value == "BG-NA": result["false_positive"].append((bg_id, full_tag))
                else: result["confirmed"].append((bg_id, full_tag))
    return result
def extract_formal_bug_tags(bug_report_path: str) -> Set[str]:
    formal_bugs = set()
    if os.path.exists(bug_report_path):
        with open(bug_report_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        bg_pattern = re.compile(r'<(BG-[A-Za-z0-9_-]+)>')
        formal_bugs.update(bg_pattern.findall(content))
    return formal_bugs
def analyze_signal_coverage_usage(checker_content: str, uncovered: List[str]) -> List[str]:
    cover_only_signals = []
    for sig in uncovered[:10]:
        base_name = re.sub(r'\[.*\]', '', sig).strip()
        base_name = base_name.replace("checker_inst.", "")
        if not base_name: continue
        in_assert = bool(re.search(rf'\bassert\s+property\b.*?{re.escape(base_name)}', checker_content, re.DOTALL)) or \
                    bool(re.search(rf'{re.escape(base_name)}.*?\bassert\s+property\b', checker_content, re.DOTALL))
        in_cover = bool(re.search(rf'\bcover\s+property\b.*?{re.escape(base_name)}', checker_content, re.DOTALL))
        if in_cover and not in_assert:
            cover_only_signals.append(base_name)
    if cover_only_signals:
        unique_sigs = list(dict.fromkeys(cover_only_signals))
        return [
            f"⚠️  These uncovered signals appear in cover but NOT in any assert:\n"
            + "\n".join(f"    - {s}" for s in unique_sigs[:10]) + "\n"
            f"  Cover properties provide WEAK COI contribution.\n"
            f"  → Write assert properties that verify the behavioral correctness of these signals."
        ]
    return []
