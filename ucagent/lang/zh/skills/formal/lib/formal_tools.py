# -*- coding: utf-8 -*-
"""Formal verification tools for the Formal workflow example.
Merges utilities, parsing, execution and stage context.
"""
import os
import re
import shutil
import subprocess
import yaml
import time
import hashlib
from typing import Dict, List, Optional, Tuple, Set, Union
import psutil

from ucagent.util.log import str_error, str_info, warning, info
from ucagent.util import diff_ops, functions as fc
from .formal_paths import FormalPaths
from .models import (
    FormalRecords, CheckPoint, FunctionGroup, FunctionPoint, 
    AnalysisEntry, BugEntry, RunResults, IterationEntry, AnalysisData
)

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
    "extract_rtl_bug_from_analysis_doc",
    "extract_python_test_functions",
    "run_formal_command_sync",
    "strip_prop_prefix",
    "extract_property_code",
    "extract_property_details",
    "extract_static_bugs",
    "analyze_signal_coverage_usage",
    "run_formal_verification",
    "summarize_execution",
    "backup_if_exists",
    "FormalStageContext",
    # YAML-based utilities
    "load_records",
    "save_records",
    "get_all_ck_from_records",
    "generate_spec_doc",
    "generate_planning_doc",
    "generate_basic_info_doc",
    "generate_env_analysis_doc",
    "generate_bug_report_doc",
    "generate_summary_doc",
    "get_primary_clock_reset",
    "set_nested_value",
    "append_nested_value",
    "incremental_merge_checker",
    "auto_scaffold_analysis_entries",
    "auto_scaffold_bug_entries",
    "parse_signal_declaration",
    "whitebox_decl_to_input_decl",
    "build_whitebox_signal_context",
    "build_clock_reset_alias_context",
    "validate_extra_config_against_design",
    "STYLE_PREFIX_MAP",
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
    if os.path.exists(filepath): shutil.copy2(filepath, filepath + ".bak")

def strip_prop_prefix(prop_name: str) -> str:
    for prefix in ("A_CK_", "M_CK_", "C_CK_", "CK_", "A_", "M_", "C_"):
        if prop_name.startswith(prefix): return prop_name[len(prefix):]
    return prop_name

def get_file_hash(filepath: str) -> str:
    if not os.path.exists(filepath): return ""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""): sha256.update(chunk)
    return sha256.hexdigest()

# =============================================================================
# Execution & Subprocess
# =============================================================================

def _terminate_process_tree(proc: subprocess.Popen, timeout: int = 5) -> None:
    try:
        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)
        for child in children:
            try: child.terminate()
            except psutil.NoSuchProcess: pass
        try: parent.terminate()
        except psutil.NoSuchProcess: pass
        gone, alive = psutil.wait_procs(children + [parent], timeout=timeout)
        for p in alive:
            try: p.kill()
            except psutil.NoSuchProcess: pass
    except psutil.NoSuchProcess: pass
    except Exception:
        try: proc.kill()
        except Exception: pass

def run_formal_command_sync(cmd: List[str], exec_dir: str, timeout: int = 300, on_start=None) -> Tuple[bool, str, str, str]:
    stdout_log, stderr_log = "", ""
    try:
        worker = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=exec_dir)
        if on_start: on_start(worker)
        try: stdout_log, stderr_log = worker.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _terminate_process_tree(worker, timeout=5)
            stdout_log, stderr_log = worker.communicate()
            return False, stdout_log, stderr_log, f"Timeout after {timeout} seconds"
        if worker.returncode != 0: return False, stdout_log, stderr_log, f"Return code {worker.returncode}"
        return True, stdout_log, stderr_log, ""
    except FileNotFoundError: return False, "", "", f"Command '{cmd[0]}' not found"
    except Exception as e: return False, "", "", f"Execution error: {e}"

def update_records_run_results(records: FormalRecords, log_result: dict, log_path: str) -> None:
    stats = {"pass_count": len(log_result.get("pass", [])), "tt_count": len(log_result.get("trivially_true", [])), "fail_count": len(log_result.get("false", [])), "cover_pass_count": len(log_result.get("cover_pass", [])), "cover_fail_count": len(log_result.get("cover_fail", []))}
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    iteration = IterationEntry(timestamp=timestamp, pass_count=stats["pass_count"], fail_count=stats["fail_count"], tt_count=stats["tt_count"], cover_pass=stats["cover_pass_count"], cover_fail=stats["cover_fail_count"])
    if records.run_results:
        records.run_results.timestamp, records.run_results.log_hash, records.run_results.stats = timestamp, get_file_hash(log_path), stats
        records.run_results.failing_properties = log_result.get("false", []) + log_result.get("cover_fail", [])
        records.run_results.tt_properties = log_result.get("trivially_true", [])
        records.run_results.iteration_history.append(iteration)
    else:
        records.run_results = RunResults(timestamp=timestamp, log_hash=get_file_hash(log_path), stats=stats, failing_properties=log_result.get("false", []) + log_result.get("cover_fail", []), tt_properties=log_result.get("trivially_true", []), iteration_history=[iteration])

def run_formal_verification(tcl_path: str, timeout: int = 300, on_start=None, records_path: str = None) -> dict:
    exec_dir = os.path.dirname(tcl_path)
    log_path = os.path.join(exec_dir, log_filename())
    cmd = build_formal_command(tcl_path, exec_dir)
    success, stdout, stderr, err_msg = run_formal_command_sync(cmd, exec_dir, timeout, on_start)
    if not success: return {"success": False, "error": err_msg, "log_path": log_path, "parsed_log": None, "blackbox_count": 0, "has_results": False, "stdout": stdout, "stderr": stderr}
    if not os.path.exists(log_path): return {"success": False, "error": "Log not generated", "log_path": log_path, "stdout": stdout, "stderr": stderr}
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f: log_content = f.read()
    blackbox_count, has_results = extract_blackbox_count(log_content), validate_log_has_results(log_content)
    parsed_log = parse_avis_log(log_path) if has_results else None
    if records_path and parsed_log:
        try:
            records = load_records(records_path)
            if records: update_records_run_results(records, parsed_log, log_path); save_records(records_path, records); info(f"📊 Proactively updated run_results in {os.path.basename(records_path)}")
        except Exception as e: warning(f"Failed to proactively update records: {e}")
    return {"success": has_results, "error": None if has_results else "No valid results in log", "log_path": log_path, "parsed_log": parsed_log, "blackbox_count": blackbox_count, "has_results": has_results, "stdout": stdout, "stderr": stderr}

def summarize_execution(stdout: str, stderr: str, max_chars: int = 1500) -> str:
    def trunc(txt: str) -> str:
        if not txt or len(txt) <= max_chars: return txt
        return txt[:max_chars//2] + "\n\n... [TRUNCATED] ...\n\n" + txt[-max_chars//2:]
    res = []
    if stderr: res.append(f"--- STDERR ---\n{trunc(stderr)}")
    if stdout and "Return code" not in stdout: res.append(f"--- STDOUT ---\n{trunc(stdout)}")
    return "\n".join(res) if res else "(empty)"

# =============================================================================
# EDA Tool Parsing
# =============================================================================

def validate_log_has_results(log_content: str) -> bool:
    return bool(re.search(r"Info-P016:\s*property .* is (?:TRIVIALLY_)?(?:TRUE|FALSE)", log_content, re.IGNORECASE))

def extract_blackbox_count(log_content: str) -> int:
    m = re.search(r"blackboxes\s*:\s*(\d+)", log_content, re.IGNORECASE)
    return int(m.group(1)) if m else 0

def parse_avis_log(log_path: str) -> Dict[str, list]:
    res: Dict[str, list] = {"pass": [], "trivially_true": [], "false": [], "cover_pass": [], "cover_fail": []}
    if not os.path.exists(log_path): return res
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f: content = f.read()
    def _is_cover(n: str) -> bool: return n.startswith("C_") or "COVER" in n.upper()
    def _record(p: str, s: str) -> None:
        ic = _is_cover(p)
        if s in ("TrivT", "TRIVIALLY_TRUE"): (res["trivially_true"].append(p) if not ic else None)
        elif s in ("Fail", "FALSE"): (res["cover_fail"] if ic else res["false"]).append(p)
        elif s in ("Pass", "TRUE"): (res["cover_pass"] if ic else res["pass"]).append(p)
    for m in re.finditer(r"^\s*\d+\s+([\w.]+\.[\w.]+)\s*:\s*(TrivT|Fail|Pass|Undec)", content, re.MULTILINE): _record(m.group(1).split(".")[-1], m.group(2))
    if not any(res[k] for k in ("pass", "trivially_true", "false")):
        for m in re.finditer(r"Info-P016:\s*property\s+([\w.]+)\s+is\s+(TRIVIALLY_TRUE|TRUE|FALSE)", content, re.IGNORECASE): _record(m.group(1).split(".")[-1], m.group(2).upper())
    return res

def parse_coverage(tests_dir: str) -> dict:
    empty = {"covered": 0, "total": 0, "pct": 0.0}
    res = {"inputs": dict(empty), "outputs": dict(empty), "dffs": dict(empty), "nets": dict(empty), "uncovered": [], "overall_pct": 0.0}
    fp = coverage_report_path(tests_dir)
    if not fp or not os.path.exists(fp): return res
    with open(fp, 'r', encoding='utf-8', errors='ignore') as f: content = f.read()
    _NAME_MAP = {'input': 'inputs', 'inputs': 'inputs', 'output': 'outputs', 'outputs': 'outputs', 'dff': 'dffs', 'dffs': 'dffs', 'net': 'nets', 'nets': 'nets'}
    for m in re.finditer(r'(Inputs?|Outputs?|Dffs?|Nets?)\s*:\s*(\d+)\s*/\s*(\d+)\s+(\d+(?:\.\d+)?)%', content, re.IGNORECASE):
        key = _NAME_MAP.get(m.group(1).lower())
        if key:
            pct = float(m.group(4)); res[key] = {"covered": int(m.group(2)), "total": int(m.group(3)), "pct": pct}
            if key == "nets": res["overall_pct"] = pct
    res["uncovered"] = re.findall(r'^\s*-\s+(\S+)', content, re.MULTILINE)
    return res

# =============================================================================
# Document & SV Parsing
# =============================================================================

def extract_rtl_bug_from_analysis_doc(analysis_path: str) -> List[Tuple[str, str]]:
    records = load_records(os.path.join(os.path.dirname(analysis_path), ".formal_records.yaml"))
    if not records or not records.analysis: return []
    res = [(e.id, e.prop_name) for e in records.analysis.fa_entries if e.resolution and e.resolution.upper() == "RTL_BUG"]
    res.sort(key=lambda x: str(x[0])); return res

def extract_python_test_functions(tp: str) -> dict:
    fns = {}
    if not os.path.exists(tp): return fns
    with open(tp, 'r', encoding='utf-8', errors='ignore') as f: content = f.read()
    ms = list(re.finditer(r'^def\s+(test_cex_\w+)\s*\(', content, re.MULTILINE))
    for i, m in enumerate(ms):
        n, s = m.group(1), m.start(); e = ms[i+1].start() if i+1 < len(ms) else len(content)
        b = content[s:e]; fns[n] = {'has_assert': 'assert ' in b, 'has_finish': 'Finish()' in b}
    return fns

def extract_static_bugs(sp: str) -> dict:
    res = {"pending": [], "confirmed": [], "false_positive": []}
    if not os.path.exists(sp): return res
    with open(sp, 'r', encoding='utf-8', errors='ignore') as f: content = f.read()
    for bid in re.findall(r'(<BG-STATIC-[A-Za-z0-9_-]+>)', content):
        p = content.find(bid); lm = re.findall(r'(<LINK-BUG-\[([^]]+)\]>)', content[p:p+500])
        for ft, lv in lm:
            if lv == "BG-TBD": res["pending"].append((bid, ft))
            elif lv == "BG-NA": res["false_positive"].append((bid, ft))
            else: res["confirmed"].append((bid, ft))
    return res

def extract_property_details(content: str) -> dict:
    details = {}
    if not content: return details
    try:
        for n, b in re.findall(r'property\s+(CK_[A-Za-z0-9_]+)\s*;(.*?)\bendproperty', content, re.DOTALL): details[n] = {'body': b, 'type': None}
        for il, pt, pn in re.findall(r'(\w+)\s*:\s*(assert|assume|cover)\s+property\s*\((CK_[A-Za-z0-9_]+)\)', content):
            if pn in details: details[pn]['type'] = pt
        return details
    except Exception as e: warning(f"Failed to extract property details: {e}"); return {}

def extract_property_code(cc: str, pn: str) -> str:
    if not cc: return f"  // Property code unavailable for {pn}"
    m = re.search(rf"(property\s+(?:(?:A|M|C)_)?{re.escape(pn)}[\s;].*?endproperty)", cc, re.DOTALL)
    if m: return "\n".join("  " + l for l in m.group(1).split("\n"))
    m = re.search(rf"(?:assert|assume|cover)\s+property\s*\([^;]*{re.escape(pn)}[^;]*\)\s*;", cc)
    return f"  {m.group(0)}" if m else f"  // Property definition not found for {pn}"

def analyze_signal_coverage_usage(cc: str, unc: List[str]) -> List[str]:
    co = []
    for s in unc[:10]:
        b = re.sub(r'\[.*?\]', '', s).strip().replace("checker_inst.", "")
        if b and not re.search(rf'\bassert\s+property\b.*?{re.escape(b)}', cc, re.DOTALL) and re.search(rf'\bcover\s+property\b.*?{re.escape(b)}', cc, re.DOTALL): co.append(b)
    return [f"⚠️  These signals appear in cover but NOT in any assert:\n" + "\n".join(f"    - {s}" for s in list(dict.fromkeys(co))[:10]) + "\n  Cover properties provide WEAK COI. Write asserts."] if co else []

# =============================================================================
# YAML Records
# =============================================================================

def load_records(rp: str) -> Optional[FormalRecords]:
    if os.path.exists(rp):
        with open(rp, 'r', encoding='utf-8') as f:
            try:
                data = yaml.safe_load(f)
                return FormalRecords.model_validate(data) if data else None
            except Exception as e: warning(f"Failed to load records from {rp}: {e}")
    return None

def save_records(rp: str, records: Union[FormalRecords, dict]) -> None:
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    d = records.model_dump(exclude_none=True) if isinstance(records, FormalRecords) else records
    with open(rp, 'w', encoding='utf-8') as f: yaml.safe_dump(d, f, indent=2, allow_unicode=True, sort_keys=False, default_flow_style=False)

def get_all_ck_from_records(records: FormalRecords) -> list:
    items = []
    if records.spec:
        for fg in records.spec.function_groups:
            for fc in fg.functions:
                for ck in fc.check_points: items.append((ck.id, ck.style, ck.description))
    return items

def set_nested_value(data: dict, dotted_path: str, value) -> dict:
    cur = data
    keys = [k for k in dotted_path.split(".") if k]
    if not keys:
        raise ValueError("Empty path")
    for key in keys[:-1]:
        if key not in cur or not isinstance(cur[key], dict):
            cur[key] = {}
        cur = cur[key]
    cur[keys[-1]] = value
    return data

def append_nested_value(data: dict, dotted_path: str, value) -> dict:
    cur = data
    keys = [k for k in dotted_path.split(".") if k]
    if not keys:
        raise ValueError("Empty path")
    for key in keys[:-1]:
        if key not in cur or not isinstance(cur[key], dict):
            cur[key] = {}
        cur = cur[key]
    leaf = cur.get(keys[-1])
    if leaf is None:
        cur[keys[-1]] = [value]
    elif isinstance(leaf, list):
        leaf.append(value)
    else:
        raise ValueError(f"Target at '{dotted_path}' is not a list")
    return data


def parse_signal_declaration(decl: str) -> dict:
    """Parse a simple SV signal declaration and preserve unpacked array suffixes.

    Supported shapes:
    - logic token
    - logic [W-1:0] token
    - logic [W-1:0] token [N-1:0]
    """
    original = decl.rstrip(";").strip()
    if not original:
        raise ValueError("Empty signal declaration")

    base = re.split(r"\s*=\s*", original, maxsplit=1)[0].strip()
    match = re.match(
        r"(?P<prefix>.*?)(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<suffix>(?:\s*\[[^\]]+\])*)\s*$",
        base,
    )
    if not match:
        raise ValueError(f"Unsupported signal declaration: {decl}")

    prefix = match.group("prefix").rstrip()
    name = match.group("name")
    suffix = match.group("suffix") or ""
    normalized_decl = " ".join(part for part in [prefix, name] if part).strip() + suffix

    return {
        "declaration": normalized_decl.strip(),
        "name": name,
        "prefix": prefix,
        "unpacked_suffix": suffix,
    }


def whitebox_decl_to_input_decl(decl: str) -> str:
    parsed = parse_signal_declaration(decl)
    body = parsed["declaration"]
    for keyword in ("logic ", "wire ", "reg ", "bit ", "var "):
        if body.startswith(keyword):
            body = body[len(keyword):]
            break
    return f"input {body}"


def build_whitebox_signal_context(decls: Optional[List[str]]) -> List[dict]:
    context = []
    for decl in decls or []:
        parsed = parse_signal_declaration(decl)
        context.append(
            {
                "declaration": parsed["declaration"],
                "name": parsed["name"],
            }
        )
    return context


def build_clock_reset_alias_context(records: FormalRecords) -> dict:
    clock_cfg, reset_cfg = get_primary_clock_reset(records)
    env_clock = "clk"
    env_reset = "rst_n"
    has_clock = bool(clock_cfg.get("signal"))
    has_reset = bool(reset_cfg.get("signal"))
    actual_clock = str(clock_cfg.get("signal", "")).strip()
    actual_reset = str(reset_cfg.get("signal", "")).strip()
    reset_active_level = str(reset_cfg.get("active_level", "low")).strip().lower() or "low"
    reset_expr = env_reset if reset_active_level == "low" else f"~{env_reset}"

    aliases = []
    if has_clock and actual_clock != env_clock:
        aliases.append({"name": actual_clock, "declaration": f"logic {actual_clock}", "expr": env_clock})
    if has_reset and actual_reset != env_reset:
        aliases.append({"name": actual_reset, "declaration": f"logic {actual_reset}", "expr": reset_expr})

    return {
        "env_clock": env_clock,
        "env_reset": env_reset,
        "actual_clock": actual_clock,
        "actual_reset": actual_reset,
        "has_clock": has_clock,
        "has_reset": has_reset,
        "clock_edge": clock_cfg.get("edge", "posedge") if has_clock else "",
        "reset_active_level": reset_active_level,
        "reset_disable_expr": f"!{env_reset}" if has_reset else "",
        "aliases": aliases,
    }


def _normalize_port_decl(port_decl: str) -> str:
    return " ".join(port_decl.strip().rstrip(",;").split())


def _find_basic_info_input_ports(records: FormalRecords) -> List[dict]:
    basic_info = records.basic_info or {}
    ports = basic_info.get("ports", {}) if isinstance(basic_info, dict) else {}
    inputs = ports.get("inputs", []) if isinstance(ports, dict) else []
    return [port for port in inputs if isinstance(port, dict)]


def validate_extra_config_against_design(records: FormalRecords, port_info: Optional[List[Tuple[str, str]]] = None) -> List[str]:
    mismatches: List[str] = []
    clock_cfg, reset_cfg = get_primary_clock_reset(records)

    basic_info = records.basic_info or {}
    clock_reset = basic_info.get("clock_reset", {}) if isinstance(basic_info, dict) else {}
    normalized_ports = {name: _normalize_port_decl(decl) for name, decl in (port_info or [])}

    def _meaningful_text(value) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text in {"无", "不适用", "N/A", "None"}:
            return None
        return text

    expected_clock = _meaningful_text(clock_reset.get("clock_signal"))
    expected_reset = _meaningful_text(clock_reset.get("reset_signal"))

    clock_count = _meaningful_text(clock_reset.get("clock_count"))
    has_design_clock = expected_clock is not None or (clock_count not in {None, "0"})
    has_design_reset = expected_reset is not None

    configured_clock = str(clock_cfg.get("signal", "")).strip()
    configured_reset = str(reset_cfg.get("signal", "")).strip()

    if has_design_clock and expected_clock and configured_clock and configured_clock != expected_clock:
        mismatches.append(
            f"clock signal mismatch: basic_info.clock_reset.clock_signal declares '{expected_clock}' but renderer resolved '{configured_clock}'"
        )
    if has_design_reset and expected_reset and configured_reset and configured_reset != expected_reset:
        mismatches.append(
            f"reset signal mismatch: basic_info.clock_reset.reset_signal declares '{expected_reset}' but renderer resolved '{configured_reset}'"
        )

    reset_type = _meaningful_text(clock_reset.get("reset_type"))
    configured_style = str(reset_cfg.get("style", "")).strip().lower()
    if reset_type and configured_style:
        if "同步" in reset_type and configured_style != "sync":
            mismatches.append(
                f"reset style mismatch: extra_config uses '{configured_style}' but basic_info reset_type is '{reset_type}'"
            )
        if "异步" in reset_type and configured_style != "async":
            mismatches.append(
                f"reset style mismatch: extra_config uses '{configured_style}' but basic_info reset_type is '{reset_type}'"
            )

    configured_active_level = str(reset_cfg.get("active_level", "")).strip().lower()
    inferred_active_level = None
    if has_design_reset and expected_reset:
        inferred_active_level = "low" if expected_reset.lower().endswith("_n") else "high"
    if inferred_active_level and configured_active_level and configured_active_level != inferred_active_level:
        mismatches.append(
            f"reset polarity mismatch: extra_config uses '{configured_active_level}' but reset signal '{expected_reset}' implies '{inferred_active_level}'"
        )

    return list(dict.fromkeys(mismatches))

def auto_scaffold_analysis_entries(records: FormalRecords, lr: dict, cc: str) -> bool:
    if not records.analysis: records.analysis = AnalysisData(); ch = True
    else: ch = False
    ct, cf = set(lr.get("trivially_true", [])), set(lr.get("false", [])) | set(lr.get("cover_fail", []))
    et, ef = {e.prop_name for e in records.analysis.tt_entries}, {e.prop_name for e in records.analysis.fa_entries}
    nt, nf = sorted(ct - et), sorted(cf - ef)
    if nt:
        next_id = max((int(e.id.split("-")[1]) for e in records.analysis.tt_entries), default=0) + 1
        for p in nt: records.analysis.tt_entries.append(AnalysisEntry(id=f"TT-{next_id:03d}", prop_name=p, sva_code=extract_property_code(cc, p), root_cause="[LLM-TODO]", action="[LLM-TODO]")); next_id += 1; ch = True
    if nf:
        next_id = max((int(e.id.split("-")[1]) for e in records.analysis.fa_entries), default=0) + 1
        for p in nf: records.analysis.fa_entries.append(AnalysisEntry(id=f"FA-{next_id:03d}", prop_name=p, prop_type="cover" if p in lr.get("cover_fail", []) else "assert", sva_code=extract_property_code(cc, p), resolution="[LLM-TODO]")); next_id += 1; ch = True
    return ch

def auto_scaffold_bug_entries(records: FormalRecords) -> bool:
    if not records.analysis: return False
    rtl_bugs = [e for e in records.analysis.fa_entries if e.resolution and e.resolution.upper() == "RTL_BUG"]
    if not rtl_bugs: return False
    if records.bugs is None: records.bugs = []; ch = True
    else: ch = False
    ex = {b.property for b in records.bugs}
    for e in rtl_bugs:
        if e.prop_name not in ex: records.bugs.append(BugEntry(id=f"BG-FORMAL-{len(records.bugs) + 1:03d}", property=e.prop_name, ck_id=f"CK-{strip_prop_prefix(e.prop_name).replace('_', '-')}")); ch = True
    return ch

import jinja2

def _indent_string(s: str, width: int, first: bool = False) -> str:
    lines = s.split('\n')
    res = []
    for i, line in enumerate(lines):
        if i == 0 and not first:
            res.append(line)
        else:
            res.append(' ' * width + line)
    return '\n'.join(res)

# =============================================================================
# YAML → Markdown
# =============================================================================

STYLE_PREFIX_MAP = {"assume": "M_CK_", "comb": "A_CK_", "seq": "A_CK_", "cover": "C_CK_"}

def _render_to_file(template_name: str, context: dict, output_path: str) -> None:
    try:
        # Templates are now stored privately in lib/templates
        lib_dir = os.path.dirname(os.path.abspath(__file__))
        tp = os.path.join(lib_dir, "templates", template_name + ".j2")
        
        if not os.path.exists(tp):
            from ucagent.util.log import error
            error(f"Template not found at {tp}")
            return

        with open(tp, 'r', encoding='utf-8') as f:
            template_content = f.read()
        
        env = jinja2.Environment(keep_trailing_newline=True)
        # Add indent filter for SV code
        def indent_filter(s, width, first=False):
            lines = s.split('\n')
            res = []
            for i, line in enumerate(lines):
                if i == 0 and not first:
                    res.append(line)
                else:
                    res.append(' ' * width + line)
            return '\n'.join(res)
        env.filters['indent'] = indent_filter
        
        template = env.from_string(template_content)
        rendered = template.render(**context)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(rendered)
    except Exception as e:
        from ucagent.util.log import error
        error(f"Failed to render template {template_name}: {e}")

def generate_spec_doc(records: FormalRecords, op: str) -> None:
    context = {
        "DUT": records.dut,
        "function_groups": records.spec.function_groups if records.spec else []
    }
    _render_to_file("functions_and_checks.md", context, op)

def generate_planning_doc(records: FormalRecords, op: str) -> None:
    context = {
        "DUT": records.dut,
        "planning": records.planning or {},
    }
    _render_to_file("verification_needs_and_plan.md", context, op)

def generate_basic_info_doc(records: FormalRecords, op: str) -> None:
    context = {
        "DUT": records.dut,
        "basic_info": records.basic_info or {},
    }
    _render_to_file("basic_info.md", context, op)

def generate_env_analysis_doc(records: FormalRecords, lp: dict, op: str) -> None:
    summary_items = [
        ("Assert Pass", len(lp.get("pass", []))),
        ("Assert TRIVIALLY_TRUE", len(lp.get("trivially_true", []))),
        ("Assert Fail", len(lp.get("false", []))),
        ("Cover Pass", len(lp.get("cover_pass", []))),
        ("Cover Fail", len(lp.get("cover_fail", [])))
    ]
    a = records.analysis
    context = {
        "DUT": records.dut,
        "summary_items": summary_items,
        "tt_entries": a.tt_entries if a else [],
        "fa_entries": a.fa_entries if a else []
    }
    _render_to_file("env_analysis.md", context, op)

def generate_bug_report_doc(records: FormalRecords, op: str) -> None:
    context = {
        "DUT": records.dut,
        "bugs": records.bugs or []
    }
    _render_to_file("bug_report.md", context, op)

def generate_summary_doc(records: FormalRecords, op: str, coverage: Optional[dict] = None) -> None:
    stats = {
        "assume_total": 0,
        "sva_total": 0,
        "cover_total": 0,
        "assert_pass": 0,
        "assert_fail": 0,
        "assert_tt": 0,
        "cover_pass": 0,
    }
    if records.spec:
        for fg in records.spec.function_groups:
            for fc in fg.functions:
                for ck in fc.check_points:
                    style = (ck.style or "").lower()
                    if style == "assume":
                        stats["assume_total"] += 1
                    elif style == "cover":
                        stats["cover_total"] += 1
                    else:
                        stats["sva_total"] += 1
    if records.run_results:
        rs = records.run_results.stats or {}
        stats["assert_pass"] = rs.get("pass_count", 0)
        stats["assert_fail"] = rs.get("fail_count", 0)
        stats["assert_tt"] = rs.get("tt_count", 0)
        stats["cover_pass"] = rs.get("cover_pass_count", 0)
    if records.summary and isinstance(records.summary.get("stats_override"), dict):
        stats.update(records.summary["stats_override"])

    cov = coverage or {"nets": {}, "dffs": {}}
    cov_ctx = {
        "nets": {
            "total": cov.get("nets", {}).get("total", 0),
            "covered": cov.get("nets", {}).get("covered", 0),
            "uncovered": max(cov.get("nets", {}).get("total", 0) - cov.get("nets", {}).get("covered", 0), 0),
            "pct": cov.get("nets", {}).get("pct", 0.0),
        },
        "dffs": {
            "total": cov.get("dffs", {}).get("total", 0),
            "covered": cov.get("dffs", {}).get("covered", 0),
            "uncovered": max(cov.get("dffs", {}).get("total", 0) - cov.get("dffs", {}).get("covered", 0), 0),
            "pct": cov.get("dffs", {}).get("pct", 0.0),
        },
    }
    summary = dict(records.summary or {})
    summary["stats"] = stats
    summary["coverage"] = cov_ctx
    context = {
        "DUT": records.dut,
        "summary": summary,
    }
    _render_to_file("formal_summary.md", context, op)

def get_primary_clock_reset(records: FormalRecords) -> tuple[dict, dict]:
    basic_info = records.basic_info or {}
    clock_reset = basic_info.get("clock_reset", {}) if isinstance(basic_info, dict) else {}
    clock_port = str(clock_reset.get("clock_signal", "") or "").strip()
    reset_port = str(clock_reset.get("reset_signal", "") or "").strip()

    reset_type = str(clock_reset.get("reset_type", "") or "").strip()
    active_level = "low" if reset_port.lower().endswith("_n") else "high"
    if "低" in reset_type:
        active_level = "low"
    elif "高" in reset_type:
        active_level = "high"

    style = ""
    if "同步" in reset_type:
        style = "sync"
    elif "异步" in reset_type:
        style = "async"

    clock = {"signal": clock_port, "edge": "posedge", "period": 10} if clock_port else {}
    reset = {"signal": reset_port, "active_level": active_level, "style": style, "init_cycles": 1} if reset_port else {}
    return clock, reset

# =============================================================================
# YAML → SV Merging
# =============================================================================

def _ck_to_sv_names(ck_id: str, style: str) -> tuple:
    pn = ck_id.replace("-", "_")
    p = STYLE_PREFIX_MAP.get(style.lower(), "A_CK_")
    l = p + (pn[3:] if pn.startswith("CK_") else pn)
    k = {"assume": "assume", "cover": "cover"}.get(style.lower(), "assert")
    return pn, l, k

def update_records_sva_body(records: FormalRecords, im: dict) -> bool:
    c = False
    if not records.spec: return False
    for fg in records.spec.function_groups:
        for fc in fg.functions:
            for ck in fc.check_points:
                n = ck.id.replace("-", "_")
                if n in im:
                    b = im[n]["body"].strip()
                    if ck.sva_body != b: ck.sva_body = b; c = True
    return c

def incremental_merge_checker(records: FormalRecords, sv_path: str, port_info: Optional[List[Tuple[str, str]]] = None, mode: str = "full") -> str:
    # 1. Prepare common data
    check_points_data = []
    if records.spec:
        for fg in records.spec.function_groups:
            for fc in fg.functions:
                for ck in fc.check_points:
                    pn, l, k = _ck_to_sv_names(ck.id, ck.style)
                    check_points_data.append({
                        "id": ck.id,
                        "prop_name": pn,
                        "label": l,
                        "kind": k,
                        "style": ck.style,
                        "description": ck.description,
                        "sva_body": ck.sva_body if ck.sva_body else "    1'b1; // [LLM-TODO] Fill SVA body",
                    })

    cr_ctx = build_clock_reset_alias_context(records)
    clock_signal = cr_ctx["env_clock"]
    reset_signal = cr_ctx["env_reset"]
    actual_clock = cr_ctx["actual_clock"]
    actual_reset = cr_ctx["actual_reset"]

    # 2. Case: Full Rendering (Stages 3-5)
    if mode == "full" or not os.path.exists(sv_path):
        hp = []
        if cr_ctx["has_clock"]:
            hp.append(f"input {clock_signal}")
        if cr_ctx["has_reset"]:
            hp.append(f"input {reset_signal}")
        if port_info:
            for n, pd in port_info:
                if n not in {clock_signal, reset_signal, actual_clock, actual_reset}:
                    hp.append(re.sub(r"^(input|output|inout)\s+", "input ", pd.strip()))
        whitebox_context = build_whitebox_signal_context(records.spec.whitebox_signals if records.spec else None)
        if whitebox_context:
            hp.extend(whitebox_decl_to_input_decl(sig["declaration"]) for sig in whitebox_context)

        context = {
            "DUT": records.dut,
            "header_ports": hp,
            "check_points": check_points_data,
            "parameter_items": list((records.spec.parameters or {}).items()) if records.spec and records.spec.parameters else [],
            "whitebox_signals": whitebox_context,
            "extra_config": records.extra_config,
            "clock_signal": clock_signal,
            "clock_edge": cr_ctx["clock_edge"],
            "reset_signal": reset_signal,
            "reset_disable_expr": cr_ctx["reset_disable_expr"],
            "clock_reset_aliases": cr_ctx["aliases"],
        }
        _render_to_file("tests/checker.sv", context, sv_path)
        with open(sv_path, 'r', encoding='utf-8') as f: return f.read()

    # 3. Case: Append Mode (Stages 6-7)
    with open(sv_path, 'r', encoding='utf-8') as f: 
        sc = f.read()

    # Identify existing properties to avoid duplication
    exi = set(re.findall(r'property\s+([A-Za-z0-9_]+)\s*;', sc))

    new_nbs = []
    for ck in check_points_data:
        if ck["prop_name"] not in exi:
            snippet = f"\n  // {ck['description']}\n" \
                      f"  // Style: {ck['style']}  [AUTO-ADDED]\n" \
                      f"  property {ck['prop_name']};\n" \
                      f"{_indent_string(ck['sva_body'], 4, first=True)}\n" \
                      f"  endproperty\n" \
                      f"  {ck['label']}: {ck['kind']} property ({ck['prop_name']});\n"
            new_nbs.append(snippet)

    if new_nbs:
        # Insert before the last endmodule
        if "endmodule" in sc:
            parts = sc.rsplit("endmodule", 1)
            sc = parts[0] + "\n" + "\n".join(new_nbs) + "\nendmodule" + parts[1]
            with open(sv_path, 'w', encoding='utf-8') as f: 
                f.write(sc)
            info(f"Append mode: Added {len(new_nbs)} new properties to {sv_path}")
        else:
            warning(f"Could not find 'endmodule' in {sv_path}, skipping append.")

    return sc




# =============================================================================
# Stage Context
# =============================================================================

class FormalStageContext:
    """Caches parsed verification data and shares it across checkers."""
    _SMANAGER_KEY = "_formal_stage_context"
    def __init__(self, workspace: str = None):
        self._checker_cache = {}
        self._workspace = workspace

    @classmethod
    def get_or_create(cls, ci, *_args):
        ws = getattr(ci, 'workspace', None)
        if getattr(ci, 'stage_manager', None):
            try:
                ctx = ci.smanager_get_value(cls._SMANAGER_KEY)
                if ctx:
                    if ws and ctx._workspace is None: ctx._workspace = ws
                    return ctx
            except (RuntimeError, AttributeError): pass
        ctx = cls(workspace=ws)
        if getattr(ci, 'stage_manager', None):
            try: ci.smanager_set_value(cls._SMANAGER_KEY, ctx)
            except (RuntimeError, AttributeError): pass
        return ctx

    def _is_stale(self, p: str) -> bool:
        if not self._workspace or not os.path.exists(p): return True
        try: return os.path.relpath(p, self._workspace) in set(diff_ops.get_dirty_files(self._workspace))
        except Exception: return True

    def get_checker_content(self, cp: str) -> str:
        if cp not in self._checker_cache or self._is_stale(cp):
            c = ""
            if os.path.exists(cp):
                with open(cp, 'r', encoding='utf-8', errors='ignore') as f: c = f.read()
            self._checker_cache[cp] = c
        return self._checker_cache[cp]

    def invalidate(self, p: str = None):
        if p is None: self._checker_cache.clear()
        else: self._checker_cache.pop(p, None)

    def get_rtl_bug_properties(self, ap: str) -> list:
        try: return [p for _, p in extract_rtl_bug_from_analysis_doc(ap)]
        except Exception: return []
