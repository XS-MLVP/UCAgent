# -*- coding: utf-8 -*-
"""Generate checker/wrapper skeletons for formal environment setup."""

import argparse
import glob
import os
import re
import sys
from typing import List, Optional, Tuple


# Bootstrap: Ensure workspace root is in sys.path so 'examples.Formal' can be imported.
_root = os.path.dirname(os.path.abspath(__file__))
while _root != os.path.dirname(_root) and not os.path.exists(os.path.join(_root, "examples", "Formal")):
    _root = os.path.dirname(_root)
sys.path.insert(0, _root)

from examples.Formal.scripts.formal_tools import get_workspace_root, normalize_output_dir, resolve_formal_paths
from ucagent.util.log import str_error, str_info


def _resolve_paths(dut_name: str, output_dir: str) -> dict:
    workspace = get_workspace_root()
    default_candidate = os.path.abspath(os.path.join(workspace, dut_name))
    default_example = os.path.abspath(os.path.join(workspace, "examples", dut_name))
    if os.path.isdir(default_candidate):
        rtl_dir = default_candidate
    elif os.path.isdir(default_example):
        rtl_dir = default_example
    else:
        rtl_dir = default_candidate
    paths = resolve_formal_paths(
        dut_name,
        output_dir,
        path_specs={
            "checker_file": ("tests", "{dut_name}_checker.sv"),
            "wrapper_file": ("tests", "{dut_name}_wrapper.sv"),
            "spec_file": ("formal", "03_{dut_name}_functions_and_checks.md"),
        },
    )
    paths["rtl_dir"] = rtl_dir
    return paths


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


def _parse_spec_ck_items(content: str) -> List[Tuple[str, str, str]]:
    ck_pattern = re.compile(r"<\s*CK-([^>]+)\s*>")
    style_pattern = re.compile(r"\(\s*Style:\s*([A-Za-z]+)\s*\)")
    items: List[Tuple[str, str, str]] = []
    for line in content.split("\n"):
        m = ck_pattern.search(line)
        if not m:
            continue
        ck_name = m.group(1).replace("-", "_")
        sm = style_pattern.search(line)
        style = sm.group(1) if sm else "Seq"
        items.append((ck_name, style, line.strip()))
    return items


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


def _read_ck_items(spec_file: str) -> List[Tuple[str, str, str]]:
    if not spec_file or not os.path.exists(spec_file):
        return []
    with open(spec_file, "r", encoding="utf-8", errors="ignore") as f:
        return _parse_spec_ck_items(f.read())


def _render_checker(dut_name: str, port_info: List[Tuple[str, str]], ck_items: List[Tuple[str, str, str]]) -> str:
    checker_name = f"{dut_name}_checker"
    has_clk = any(name == "clk" for name, _ in port_info)
    has_rst = any(name == "rst_n" for name, _ in port_info)

    header_ports = []
    if not has_clk:
        header_ports.append("input clk")
    if not has_rst:
        header_ports.append("input rst_n")
    for name, pdef in port_info:
        if name in ("clk", "rst_n"):
            header_ports.append(_to_input_decl(pdef))
            continue
        header_ports.append(_to_input_decl(pdef))

    lines = [
        f"module {checker_name}(",
        "  " + ",\n  ".join(header_ports),
        ");",
        "",
        "  // Auto-generated checker skeleton",
        "  default clocking cb @(posedge clk); endclocking",
        "  default disable iff (!rst_n);",
        "",
    ]

    seen = set()
    if not ck_items:
        ck_items = [("AUTO_TODO", "Seq", "")]

    for ck_name, style, _ in ck_items:
        pname = f"CK_{ck_name}"
        if pname in seen:
            continue
        seen.add(pname)
        kind = "assert"
        if style.lower() == "assume":
            kind = "assume"
        elif style.lower() == "cover":
            kind = "cover"
        lines.extend(
            [
                f"  // Style: {style}",
                f"  property {pname};",
                "    1'b1; // [LLM-TODO] Fill SVA body",
                "  endproperty",
                f"  {kind} property ({pname});",
                "",
            ]
        )

    lines.extend(["endmodule", ""])
    return "\n".join(lines)


def _render_wrapper(dut_name: str, port_info: List[Tuple[str, str]]) -> str:
    wrapper_name = f"{dut_name}_wrapper"
    checker_name = f"{dut_name}_checker"

    lines = [
        f"module {wrapper_name}(",
        "  input clk,",
        "  input rst_n",
        ");",
        "",
        "  // Auto-generated symbolic signals",
    ]

    for name, pdef in port_info:
        if name in ("clk", "rst_n"):
            continue
        decl = _to_internal_decl(pdef)
        lines.append(f"  {decl};")

    lines.extend(["", f"  {dut_name} u_dut ("])
    lines.append("    " + ",\n    ".join([f".{name}({name})" for name, _ in port_info]))
    lines.extend(["  );", "", f"  {checker_name} u_checker ("])

    conns = [".clk(clk)", ".rst_n(rst_n)"]
    for name, _ in port_info:
        if name in ("clk", "rst_n"):
            continue
        conns.append(f".{name}({name})")
    lines.append("    " + ",\n    ".join(conns))
    lines.extend(["  );", "", "endmodule", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate checker.sv and wrapper.sv files")
    parser.add_argument("-dut_name", default=os.environ.get("DUT"), help="Top-level DUT module name")
    args = parser.parse_args()

    if not args.dut_name:
        print(str_error("Missing DUT name. Please provide -dut_name or set DUT environment variable."))
        return
    output_dir_env = os.environ.get("OUT")
    if not output_dir_env:
        print(str_error("Missing OUT environment variable."))
        return

    output_dir = normalize_output_dir(output_dir_env)

    paths = _resolve_paths(
        args.dut_name,
        output_dir=output_dir,
    )
    rtl_dir_res = paths["rtl_dir"]
    checker_path = paths["checker_file"]
    wrapper_path = paths["wrapper_file"]
    spec_path = paths["spec_file"]

    try:
        rtl_file_path = _find_rtl_file(rtl_dir_res, args.dut_name)
        port_info = _extract_ports_simple(rtl_file_path, args.dut_name)
        ck_items = _read_ck_items(spec_path)

        os.makedirs(os.path.dirname(checker_path), exist_ok=True)
        with open(checker_path, "w", encoding="utf-8") as f:
            f.write(_render_checker(args.dut_name, port_info, ck_items))
        with open(wrapper_path, "w", encoding="utf-8") as f:
            f.write(_render_wrapper(args.dut_name, port_info))

        result = str_info(
            f"Checker skeleton created at: {checker_path}\n"
            f"Wrapper created at: {wrapper_path}\n"
            f"(Ports extracted from {rtl_file_path})"
        )
    except FileNotFoundError as e:
        result = str_error(f"RTL file not found: {e}")
    except Exception as e:
        result = str_error(f"Error generating checker/wrapper: {e}")

    print(result)


if __name__ == "__main__":
    main()
