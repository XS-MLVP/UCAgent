# -*- coding: utf-8 -*-
"""Formal verification tools for the Formal workflow example.
Merges utilities, parsing, execution and stage context.
"""
import os
import re
import shutil
import subprocess
import json
import time
from typing import Dict, List, Optional, Tuple, Set
import psutil

from ucagent.util.log import str_error, str_info, warning, info
from .formal_paths import FormalPaths

__all__ = [
    "tool_display_name",
    "log_filename",
    "coverage_report_path",
    "build_formal_command",
    "required_script_commands",
    "parse_avis_log",
    "validate_log_has_results",
    "extract_blackbox_count",
    "parse_coverage",
    "parse_env_analysis_doc",
    "extract_rtl_bug_from_analysis_doc",
    "extract_python_test_functions",
    "run_formal_command_sync",
    "strip_prop_prefix",
    "extract_property_code",
    "extract_property_details",
    "parse_bug_report_properties",
    "extract_static_bugs",
    "extract_formal_bug_tags",
    "analyze_signal_coverage_usage",
    "run_formal_verification",
    "summarize_execution",
    "backup_if_exists",
    "FormalStageContext",
    "IterationTracker"
]

# =============================================================================
# Tool Configuration (FormalMC)
# =============================================================================

def tool_display_name() -> str:
    return "FormalMC (华大九天)"

def log_filename() -> str:
    return "avis.log"

def coverage_report_path(tests_dir: str) -> Optional[str]:
    return os.path.join(tests_dir, "avis", "fanin.rep")

def build_formal_command(tcl_path: str, exec_dir: str) -> List[str]:
    return ["FormalMC", "-f", tcl_path, "-override", "-work_dir", exec_dir]

def required_script_commands() -> List[str]:
    return ["read_design", "prove", "def_clk", "def_rst"]

# =============================================================================
# Shared Utilities
# =============================================================================

def backup_if_exists(filepath: str) -> None:
    """Backup file to .bak if it exists."""
    if os.path.exists(filepath):
        shutil.copy2(filepath, filepath + ".bak")

def strip_prop_prefix(prop_name: str) -> str:
    for prefix in ("A_CK_", "M_CK_", "C_CK_", "CK_", "A_", "M_", "C_"):
        if prop_name.startswith(prefix):
            return prop_name[len(prefix):]
    return prop_name

# =============================================================================
# Execution & Subprocess
# =============================================================================

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
    exec_dir = os.path.dirname(tcl_path)
    log_path = os.path.join(exec_dir, log_filename())
    cmd = build_formal_command(tcl_path, exec_dir)
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
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        log_content = f.read()
    blackbox_count = extract_blackbox_count(log_content)
    has_results = validate_log_has_results(log_content)
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
        return txt[:half] + "\\n\\n... [LOG TRUNCATED, SHOWING START AND END] ...\\n\\n" + txt[-half:]
    res = []
    if stderr:
        res.append(f"--- STDERR ---\\n{trunc(stderr)}")
    if stdout and "Return code" not in stdout:
        res.append(f"--- STDOUT ---\\n{trunc(stdout)}")
    return "\\n".join(res) if res else "(empty)"


# =============================================================================
# EDA Tool Parsing (Logs & Coverage)
# =============================================================================

def validate_log_has_results(log_content: str) -> bool:
    return bool(re.search(
        r"Info-P016:\\s*property .* is (?:TRIVIALLY_)?(?:TRUE|FALSE)", 
        log_content,
        re.IGNORECASE
    ))

def extract_blackbox_count(log_content: str) -> int:
    blackbox_stats = re.search(r"blackboxes\\s*:\\s*(\\d+)", log_content, re.IGNORECASE)
    if blackbox_stats:
        return int(blackbox_stats.group(1))
    return 0

def parse_avis_log(log_path: str) -> Dict[str, list]:
    result: Dict[str, list] = {
        "pass": [],
        "trivially_true": [],
        "false": [],
        "cover_pass": [],
        "cover_fail": [],
    }

    if not os.path.exists(log_path):
        return result

    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    def _is_cover(name: str) -> bool:
        return name.startswith("C_") or "COVER" in name.upper()

    def _record(prop: str, status: str) -> None:
        is_cov = _is_cover(prop)
        if status == "TrivT" or status == "TRIVIALLY_TRUE":
            if not is_cov:
                result["trivially_true"].append(prop)
        elif status in ("Fail", "FALSE"):
            (result["cover_fail"] if is_cov else result["false"]).append(prop)
        elif status in ("Pass", "TRUE"):
            (result["cover_pass"] if is_cov else result["pass"]).append(prop)

    # Strategy 1: summary table (show_prop -summary output)
    table_re = re.compile(
        r"^\\s*\\d+\\s+([\\w.]+\\.[\\w.]+)\\s*:\\s*(TrivT|Fail|Pass|Undec)",
        re.MULTILINE,
    )
    for m in table_re.finditer(content):
        prop = m.group(1).split(".")[-1]
        _record(prop, m.group(2))

    # Strategy 2: fallback to Info-P016 per-line messages
    if not any(result[k] for k in ("pass", "trivially_true", "false")):
        p016_re = re.compile(
            r"Info-P016:\\s*property\\s+([\\w.]+)\\s+is\\s+"
            r"(TRIVIALLY_TRUE|TRUE|FALSE)",
            re.IGNORECASE,
        )
        for m in p016_re.finditer(content):
            prop = m.group(1).split(".")[-1]
            _record(prop, m.group(2).upper())

    # Strategy 3: fallback to Info-P014 intermediate results
    if not any(result[k] for k in ("pass", "trivially_true", "false")):
        p014_re = re.compile(
            r"Info-P014:\\s*property\\s+(false|true):\\s+([\\w.]+)",
            re.IGNORECASE,
        )
        for m in p014_re.finditer(content):
            prop = m.group(2).split(".")[-1]
            status = "FALSE" if m.group(1).lower() == "false" else "TRUE"
            _record(prop, status)

    return result

def parse_coverage(tests_dir: str) -> dict:
    empty = {"covered": 0, "total": 0, "pct": 0.0}
    result = {
        "inputs": dict(empty), "outputs": dict(empty),
        "dffs": dict(empty), "nets": dict(empty),
        "uncovered": [],
        "overall_pct": 0.0
    }
    fanin_path = coverage_report_path(tests_dir)
    if not fanin_path or not os.path.exists(fanin_path):
        return result

    with open(fanin_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    _METRIC_RE = re.compile(
        r'(Inputs?|Outputs?|Dffs?|Nets?)\\s*:\\s*(\\d+)\\s*/\\s*(\\d+)\\s+(\\d+(?:\\.\\d+)?)%',
        re.IGNORECASE
    )
    _NAME_MAP = {
        'input': 'inputs', 'inputs': 'inputs',
        'output': 'outputs', 'outputs': 'outputs',
        'dff': 'dffs', 'dffs': 'dffs',
        'net': 'nets', 'nets': 'nets',
    }

    for m in _METRIC_RE.finditer(content):
        key = _NAME_MAP.get(m.group(1).lower())
        if key:
            pct = float(m.group(4))
            result[key] = {
                "covered": int(m.group(2)),
                "total":   int(m.group(3)),
                "pct":     pct
            }
            if key == "nets":
                result["overall_pct"] = pct

    result["uncovered"] = re.findall(r'^\\s*-\\s+(\\S+)', content, re.MULTILINE)
    return result

# =============================================================================
# Document & Python Parsing
# =============================================================================

def _extract_field(field_name: str, text: str) -> Optional[str]:
    pat = re.compile(
        rf'[-*]*\\s*\\*\\*{re.escape(field_name)}\\*\\*\\s*:\\s*(.*?)(?=\\n\\s*[-*]*\\s*\\*\\*|\\n```|\\Z)',
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
        r'###\\s*<(TT-\\d+)>\\s*(\\S+)\\s*\\n(.*?)(?=###\\s*<(?:TT|FA)-\\d+>|^---$|^## \\d+\\.|\\Z)',
        re.DOTALL | re.MULTILINE
    )
    fa_pattern = re.compile(
        r'###\\s*<(FA-\\d+)>\\s*(\\S+)\\s*\\n(.*?)(?=###\\s*<(?:TT|FA)-\\d+>|^---$|^## \\d+\\.|\\Z)',
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
    func_pattern = re.compile(r'^def\\s+(test_cex_\\w+)\\s*\\(', re.MULTILINE)
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

def parse_bug_report_properties(content: str) -> Set[str]:
    report_sections = re.split(r'##\\s*❌?\\s*Failed Property:\\s*`?([\\w.]+)`?', content)
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
    link_pattern = re.compile(r'(<LINK-BUG-\\[([^]]+)\\]>)')
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

# =============================================================================
# SystemVerilog Parsing
# =============================================================================

def extract_property_details(content: str) -> dict:
    details = {}
    if not content:
        return details
    try:
        prop_blocks = re.findall(r'property\\s+(CK_[A-Za-z0-9_]+)\\s*;(.*?)\\bendproperty', content, re.DOTALL)
        for name, body in prop_blocks:
            details[name] = {'body': body, 'type': None}
        stmt_matches = re.findall(r'(\\w+)\\s*:\\s*(assert|assume|cover)\\s+property\\s*\\((CK_[A-Za-z0-9_]+)\\)', content)
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
        rf"(property\\s+(?:(?:A|M|C)_)?{re.escape(prop_name)}[\\s;].*?endproperty)",
        re.DOTALL,
    )
    match = pattern.search(checker_content)
    if match:
        return "\\n".join("  " + line for line in match.group(1).split("\\n"))
    pattern_inline = re.compile(
        rf"(?:assert|assume|cover)\\s+property\\s*\\([^;]*{re.escape(prop_name)}[^;]*\\)\\s*;"
    )
    match = pattern_inline.search(checker_content)
    if match:
        return f"  {match.group(0)}"
    core_name = strip_prop_prefix(prop_name)
    if core_name != prop_name:
        pattern_core = re.compile(
            rf"(property\\s+.*?{re.escape(core_name)}.*?;.*?endproperty)",
            re.DOTALL,
        )
        match = pattern_core.search(checker_content)
        if match:
            return "\\n".join("  " + line for line in match.group(1).split("\\n"))
    lines = checker_content.split("\\n")
    for i, line in enumerate(lines):
        if prop_name in line and ("assert" in line or "property" in line or ":" in line):
            return "\\n".join(lines[max(0, i - 3):min(len(lines), i + 6)])
    for i, line in enumerate(lines):
        if prop_name in line:
            return "\\n".join(lines[max(0, i - 2):min(len(lines), i + 4)])
    return f"  // Property definition not found for {prop_name}"

def analyze_signal_coverage_usage(checker_content: str, uncovered: List[str]) -> List[str]:
    cover_only_signals = []
    for sig in uncovered[:10]:
        base_name = re.sub(r'\\[.*?\\]', '', sig).strip()
        base_name = base_name.replace("checker_inst.", "")
        if not base_name: continue
        in_assert = bool(re.search(rf'\\bassert\\s+property\\b.*?{re.escape(base_name)}', checker_content, re.DOTALL)) or \
                    bool(re.search(rf'{re.escape(base_name)}.*?\\bassert\\s+property\\b', checker_content, re.DOTALL))
        in_cover = bool(re.search(rf'\\bcover\\s+property\\b.*?{re.escape(base_name)}', checker_content, re.DOTALL))
        if in_cover and not in_assert:
            cover_only_signals.append(base_name)
    if cover_only_signals:
        unique_sigs = list(dict.fromkeys(cover_only_signals))
        return [
            f"⚠️  These uncovered signals appear in cover but NOT in any assert:\\n"
            + "\\n".join(f"    - {s}" for s in unique_sigs[:10]) + "\\n"
            f"  Cover properties provide WEAK COI contribution.\\n"
            f"  → Write assert properties that verify the behavioral correctness of these signals."
        ]
    return []

# =============================================================================
# Stage Context & Iteration Tracker
# =============================================================================

class FormalStageContext:
    """Caches parsed verification data and shares it across checkers."""
    _SMANAGER_KEY = "_formal_stage_context"

    def __init__(self):
        self._log_cache = {}
        self._checker_cache = {}
        self._doc_cache = {}

    def get_analysis_doc_parsed(self, doc_path: str) -> dict:
        if self._is_stale(self._doc_cache, doc_path):
            result = parse_env_analysis_doc(doc_path)
            self._doc_cache[doc_path] = {
                "mtime": os.path.getmtime(doc_path) if os.path.exists(doc_path) else 0,
                "data": result,
            }
        return self._doc_cache[doc_path]["data"]

    @classmethod
    def get_or_create(cls, checker_instance, *_args):
        if getattr(checker_instance, 'stage_manager', None) is not None:
            try:
                ctx = checker_instance.smanager_get_value(cls._SMANAGER_KEY)
                if ctx is not None:
                    return ctx
            except (RuntimeError, AttributeError):
                pass
        ctx = cls()
        if getattr(checker_instance, 'stage_manager', None) is not None:
            try:
                checker_instance.smanager_set_value(cls._SMANAGER_KEY, ctx)
            except (RuntimeError, AttributeError):
                pass
        return ctx

    def _is_stale(self, cache_dict: dict, path: str) -> bool:
        if path not in cache_dict: return True
        if not os.path.exists(path): return True
        return os.path.getmtime(path) > cache_dict[path]["mtime"]

    def get_parsed_log(self, log_path: str) -> dict:
        if self._is_stale(self._log_cache, log_path):
            self._log_cache[log_path] = {
                "mtime": os.path.getmtime(log_path) if os.path.exists(log_path) else 0,
                "data": parse_avis_log(log_path),
            }
        return self._log_cache[log_path]["data"]

    def get_checker_content(self, checker_path: str) -> str:
        if self._is_stale(self._checker_cache, checker_path):
            content = ""
            if os.path.exists(checker_path):
                with open(checker_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            self._checker_cache[checker_path] = {
                "mtime": os.path.getmtime(checker_path) if os.path.exists(checker_path) else 0,
                "content": content,
            }
        return self._checker_cache[checker_path]["content"]

    def invalidate(self, path: str = None):
        if path is None:
            self._log_cache.clear()
            self._checker_cache.clear()
            self._doc_cache.clear()
        else:
            self._log_cache.pop(path, None)
            self._checker_cache.pop(path, None)
            self._doc_cache.pop(path, None)

    def get_rtl_bug_properties(self, analysis_path: str) -> list:
        try:
            return [prop for _, prop in extract_rtl_bug_from_analysis_doc(analysis_path)]
        except Exception:
            return []

class IterationTracker:
    """Tracks verification iterations and checks for convergence."""
    def __init__(self, dut_name, log_file):
        self.dut_name = dut_name
        self.log_file = log_file

    def get_log_path(self) -> str:
        return os.path.join(os.path.dirname(self.log_file), f".{self.dut_name}_iteration_history.json")

    def record_iteration(self, stats: dict) -> list:
        log_path = self.get_log_path()
        history = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as f:
                    history = json.load(f)
            except Exception: pass
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "pass_count": stats.get("pass_count", 0),
            "fail_count": stats.get("fail_count", 0),
            "tt_count": stats.get("tt_count", 0),
            "cover_pass": stats.get("cover_pass", 0),
            "cover_fail": stats.get("cover_fail", 0),
        }
        history.append(entry)
        try:
            with open(log_path, "w") as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
        except Exception: pass
        return history

    def check_convergence(self, history: list) -> tuple:
        if len(history) < 2: return True, ""
        prev, curr = history[-2], history[-1]
        prev_fail = prev.get("fail_count", 0) + prev.get("cover_fail", 0)
        curr_fail = curr.get("fail_count", 0) + curr.get("cover_fail", 0)
        prev_pass = prev.get("pass_count", 0) + prev.get("cover_pass", 0)
        curr_pass = curr.get("pass_count", 0) + curr.get("cover_pass", 0)
        curr_tt, prev_tt = curr.get("tt_count", 0), prev.get("tt_count", 0)

        msgs = []
        if curr_pass < prev_pass: msgs.append(f"⚠️  REGRESSION: Pass count decreased ({prev_pass} → {curr_pass}). Consider reverting the last modification.")
        if curr_fail >= prev_fail and curr_tt >= prev_tt and len(history) >= 3:
            prev2_fail = history[-3].get("fail_count", 0) + history[-3].get("cover_fail", 0)
            if prev2_fail <= prev_fail: msgs.append(f"⚠️  STAGNATION: Fail count has not decreased for 3 consecutive iterations. Try a different fix strategy.")
        if curr_fail > prev_fail: msgs.append(f"⚠️  DEGRADATION: Fail count increased ({prev_fail} → {curr_fail}). The last modification may have introduced new failures.")

        is_ok = not any("REGRESSION" in m for m in msgs)
        return is_ok, "\\n".join(msgs)
