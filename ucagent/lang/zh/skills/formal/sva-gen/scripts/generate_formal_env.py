# -*- coding: utf-8 -*-
"""Generate checker/wrapper skeletons for formal environment setup."""

import glob
import os
import re
import sys

# Bootstrap: Add UCAgent project root to sys.path so we can import 'ucagent'.
_root = os.path.dirname(os.path.abspath(__file__))
while _root != os.path.dirname(_root) and not os.path.exists(os.path.join(_root, "ucagent", "__init__.py")):
    _root = os.path.dirname(_root)
if _root not in sys.path:
    sys.path.insert(0, _root)

from ucagent.lang.zh.skills.formal.lib.formal_paths import FormalPaths
from ucagent.lang.zh.skills.formal.lib.formal_tools import (
    load_records,
    get_all_ck_from_records,
    STYLE_PREFIX_MAP,
    incremental_merge_checker,
    get_primary_clock_reset,
    build_whitebox_signal_context,
    build_clock_reset_alias_context,
)
from ucagent.util.log import str_error, str_info
import ucagent.util.functions as fc

from typing import List, Optional, Tuple, Any



def _extract_ports_simple(rtl_file_path: str, dut_name: str) -> List[Tuple[str, str]]:
    with open(rtl_file_path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    m = re.search(rf"module\s+{re.escape(dut_name)}\s*(?:#\s*\(.*?\)\s*)?\((.*?)\)\s*;", text, re.DOTALL)
    if not m:
        raise ValueError(f"Cannot parse module header for {dut_name} in {rtl_file_path}")
    ports_blob = m.group(1)
    port_defs = [p.strip() for p in ports_blob.split(",") if p.strip()]
    port_info: List[Tuple[str, str]] = []
    for p in port_defs:
        cleaned = re.sub(r"\s+", " ", p).strip()
        name_match = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*$", cleaned)
        if not name_match:
            continue
        pname = name_match.group(1)
        if not re.match(r"^(input|output|inout)\b", cleaned):
            cleaned = "input " + cleaned
        port_info.append((pname, cleaned))
    return port_info


# NOTE: _parse_spec_ck_items removed — replaced by JSON records.


def _find_rtl_file(rtl_dir: str, dut_name: str) -> str:
    if not os.path.isdir(rtl_dir):
        raise FileNotFoundError(f"RTL directory does not exist: {rtl_dir}")

    all_files = []
    for ext in ("*.v", "*.sv"):
        all_files.extend(glob.glob(os.path.join(rtl_dir, ext)))

    for file_path in all_files:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if re.search(rf"\bmodule\s+{re.escape(dut_name)}\b", content):
                return file_path
        except OSError:
            continue

    if len(all_files) == 1:
        return all_files[0]

    raise FileNotFoundError(
        f"Could not find RTL source for module '{dut_name}' in '{rtl_dir}'. "
        f"Found files: {all_files if all_files else 'none'}"
    )


def _to_input_decl(port_def: str) -> str:
    return re.sub(r"^(input|output|inout)\s+", "input ", port_def.strip(), count=1)


def _to_internal_decl(port_def: str) -> str:
    core = re.sub(r"^(input|output|inout)\s+", "", port_def.strip(), count=1).strip()
    if re.match(r"^(logic|wire|reg)\b", core):
        return core
    return f"logic {core}"



import jinja2

def _render_to_file(template_name: str, context: dict, output_path: str) -> None:
    try:
        # Templates are now stored privately in lib/templates
        lib_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "lib")
        tp = os.path.join(lib_dir, "templates", template_name + ".j2")
        
        if not os.path.exists(tp):
            print(str_error(f"Template not found at {tp}"))
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
        print(str_error(f"Failed to render template {template_name}: {e}"))


def _render_wrapper(
    dut_name: str,
    port_info: List[Tuple[str, str]],
    wrapper_path: str,
    parameters: dict = None,
    whitebox_signals: list = None,
    clock_signal: str = "clk",
    reset_signal: str = "rst_n",
    actual_clock_signal: str = "clk",
    actual_reset_signal: str = "rst_n",
    clock_reset_aliases: list = None,
) -> None:
    internal_decls = []
    for name, pdef in port_info:
        if name in {clock_signal, reset_signal, actual_clock_signal, actual_reset_signal}:
            continue
        internal_decls.append(_to_internal_decl(pdef))

    dut_conns = [f".{name}({name})" for name, _ in port_info]
    
    checker_conns = []
    if any(alias.get("expr") == clock_signal for alias in (clock_reset_aliases or [])) or actual_clock_signal == clock_signal:
        checker_conns.append(f".{clock_signal}({clock_signal})")
    if any("rst_n" in str(alias.get("expr", "")) for alias in (clock_reset_aliases or [])) or actual_reset_signal == reset_signal:
        checker_conns.append(f".{reset_signal}({reset_signal})")
    for name, _ in port_info:
        if name in {clock_signal, reset_signal, actual_clock_signal, actual_reset_signal}:
            continue
        checker_conns.append(f".{name}({name})")
    whitebox_context = build_whitebox_signal_context(whitebox_signals)
    for sig in whitebox_context:
        checker_conns.append(f".{sig['name']}({sig['name']})")

    context = {
        "DUT": dut_name,
        "internal_decls": internal_decls,
        "dut_connections": dut_conns,
        "checker_connections": checker_conns,
        "parameter_items": list((parameters or {}).items()),
        "whitebox_signals": whitebox_context,
        "clock_signal": clock_signal,
        "reset_signal": reset_signal,
        "has_clock": bool(actual_clock_signal),
        "has_reset": bool(actual_reset_signal),
        "clock_reset_aliases": clock_reset_aliases or [],
    }
    _render_to_file("tests/wrapper.sv", context, wrapper_path)


def _render_tcl(dut_name: str, tcl_path: str, extra_config: dict = None, basic_info: dict = None) -> None:
    context = {"DUT": dut_name, "extra_config": extra_config, "basic_info": basic_info or {}}
    _render_to_file("tests/formal.tcl", context, tcl_path)


import argparse

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate checker/wrapper skeletons.")
    parser.add_argument("--mode", choices=["full", "append"], default="full", 
                        help="Rendering mode: 'full' (overwrite) or 'append' (preserve manual work)")
    args = parser.parse_args()

    paths = FormalPaths()
    if paths.dut == "N/A":
        print(str_error("Cannot determine DUT. Set DUT env var or ensure .formal_records.yaml exists."))
        return

    dut = paths.dut
    rtl_dir_res = paths.rtl_dir
    checker_path = paths.checker
    wrapper_path = paths.wrapper
    tcl_path = paths.tcl

    try:
        lib_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "lib")
        print(str_info(f"[generate_formal_env] workspace={paths.workspace}"))
        print(str_info(f"[generate_formal_env] records={paths.records_yaml}"))
        print(str_info(f"[generate_formal_env] rtl_dir={rtl_dir_res}"))
        print(str_info(f"[generate_formal_env] template_dir={os.path.join(lib_dir, 'templates')}"))
        print(str_info(f"[generate_formal_env] formal_tools={sys.modules['ucagent.lang.zh.skills.formal.lib.formal_tools'].__file__}"))
        rtl_file_path = _find_rtl_file(rtl_dir_res, dut)
        port_info = _extract_ports_simple(rtl_file_path, dut)
        records = load_records(paths.records_yaml)
        
        if not records:
            print(str_error(f"Records file not found: {paths.records_yaml}"))
            return

        cr_ctx = build_clock_reset_alias_context(records)

        # 1. Generate/Update Checker
        os.makedirs(os.path.dirname(checker_path), exist_ok=True)
        # Use incremental_merge_checker with the specified mode
        incremental_merge_checker(records, checker_path, port_info=port_info, mode=args.mode)

        # 2. Generate Wrapper & TCL (only in 'full' mode or if they don't exist)
        if args.mode == "full" or not os.path.exists(wrapper_path):
            os.makedirs(os.path.dirname(wrapper_path), exist_ok=True)
            params = records.spec.parameters if records.spec else None
            wb_sigs = records.spec.whitebox_signals if records.spec else None
            _render_wrapper(
                dut,
                port_info,
                wrapper_path,
                parameters=params,
                whitebox_signals=wb_sigs,
                clock_signal=cr_ctx["env_clock"],
                reset_signal=cr_ctx["env_reset"],
                actual_clock_signal=cr_ctx["actual_clock"],
                actual_reset_signal=cr_ctx["actual_reset"],
                clock_reset_aliases=cr_ctx["aliases"],
            )
            
        if args.mode == "full" or not os.path.exists(tcl_path):
            os.makedirs(os.path.dirname(tcl_path), exist_ok=True)
            _render_tcl(dut, tcl_path, extra_config=records.extra_config, basic_info=records.basic_info)

        mode_str = "Full overwrite" if args.mode == "full" else "Append missing only"
        result = str_info(
            f"✅ Formal environment updated ({mode_str}):\n"
            f"   - Checker: {checker_path}\n"
            f"   - Wrapper: {wrapper_path}\n"
            f"   - TCL Script: {tcl_path}\n"
            f"   (Ports extracted from {rtl_file_path})"
        )


    except FileNotFoundError as e:
        result = str_error(f"RTL file not found: {e}")
    except Exception as e:
        result = str_error(f"Error generating checker/wrapper: {e}")

    print(result)


if __name__ == "__main__":
    main()
