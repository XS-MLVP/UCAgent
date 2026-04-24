# -*- coding: utf-8 -*-
"""Generate counterexample Python test scaffold from env analysis."""

import argparse
import os
import re
import shutil
import sys

import os
import sys

# Bootstrap: Add UCAgent project root to sys.path so we can import 'ucagent'.
_root = os.path.dirname(os.path.abspath(__file__))
while _root != os.path.dirname(_root) and not os.path.exists(os.path.join(_root, "ucagent", "__init__.py")):
    _root = os.path.dirname(_root)
if _root not in sys.path:
    sys.path.insert(0, _root)

from ucagent.lang.zh.skills.formal.lib import FormalPaths
from ucagent.util.log import str_error, str_info

from typing import Optional




def _strip_prop_prefix(prop_name: str) -> str:
    for prefix in ("A_CK_", "M_CK_", "C_CK_", "CK_", "A_", "M_", "C_"):
        if prop_name.startswith(prefix):
            return prop_name[len(prefix):]
    return prop_name


def _extract_rtl_bug_from_analysis_doc(analysis_path: str):
    if not os.path.exists(analysis_path):
        return []
    with open(analysis_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    fa_pattern = re.compile(
        r"###\s*<(FA-\d+)>\s*(\S+)\s*\n(.*?)(?=###\s*<(?:TT|FA)-\d+>|^---$|^##\s\d+\.|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    bugs = []
    for m in fa_pattern.finditer(content):
        fa_id, prop_name, body = m.group(1), m.group(2), m.group(3)
        res_match = re.search(r"\*\*解决状态\*\*\s*:\s*(.+)", body)
        resolution = res_match.group(1).strip().upper() if res_match else ""
        if resolution == "RTL_BUG":
            bugs.append((fa_id, prop_name))
    return sorted(bugs, key=lambda x: x[0])


def _parse_wrapper_clock_reset(wrapper_path: str):
    if not os.path.exists(wrapper_path):
        return None, None
    with open(wrapper_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    clock_name = None
    reset_name = None
    for cand in ("clk", "clock", "i_clk"):
        if re.search(rf"\b{re.escape(cand)}\b", content):
            clock_name = cand
            break
    for cand in ("rst_n", "reset_n", "rst", "reset"):
        if re.search(rf"\b{re.escape(cand)}\b", content):
            reset_name = cand
            break
    return clock_name, reset_name


def _backup_if_exists(filepath: str) -> None:
    if os.path.exists(filepath):
        shutil.copy2(filepath, filepath + ".bak")


def _render_test_function(
    prop_name: str,
    fa_id: str,
    clock_name: Optional[str],
    reset_name: Optional[str],
    dut_class: str,
) -> str:
    name = _strip_prop_prefix(prop_name).lower()
    func_name = f"test_cex_{name}"

    clock_init = f"    dut.InitClock('{clock_name}')\n    # 复位序列\n" if clock_name else ""
    if clock_name:
        if reset_name:
            clock_init += (
                f"    dut.{reset_name}.value = 0\n"
                "    dut.Step(5)\n"
                f"    dut.{reset_name}.value = 1\n"
            )
        else:
            clock_init += "    # [LLM-TODO]: 复位序列\n    dut.Step(5)\n"
        clock_init += "    dut.Step(1)\n"

    tq = '"""'
    return (
        f"def {func_name}():\n"
        f"    {tq}反例测试: {prop_name} (来源: {fa_id})\n"
        "    [LLM-TODO]: 补充 Bug 描述、反例条件、预期/实际行为\n"
        f"    {tq}\n"
        f"    dut = DUT{dut_class}()\n"
        f"{clock_init}"
        "    # [LLM-TODO]: 按反例时序驱动引脚\n"
        "    dut.Step(1)\n\n"
        "    # [LLM-TODO]: 断言检查\n"
        "    # assert dut.yyy.value == expected\n\n"
        "    dut.Finish()\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate test_{DUT}_counterexample.py scaffold")
    parser.add_argument("-dut_name", default=os.environ.get("DUT"), help="Top-level DUT module name")
    args = parser.parse_args()

    if not args.dut_name:
        print(str_error("Missing DUT name. Please provide -dut_name or set DUT environment variable."))
        return
    output_dir_env = os.environ.get("OUT")
    if not output_dir_env:
        print(str_error("Missing OUT environment variable."))
        return



    paths = FormalPaths(dut=args.dut_name)
    res_analysis_path = paths.analysis
    res_wrapper_path = paths.wrapper
    res_output_path = paths.test_file

    if not os.path.exists(res_analysis_path):
        print(str_error(f"Error: Analysis doc not found at {res_analysis_path}"))
        return

    rtl_bugs = _extract_rtl_bug_from_analysis_doc(res_analysis_path)
    clock_name, reset_name = _parse_wrapper_clock_reset(res_wrapper_path)

    _backup_if_exists(res_output_path)
    os.makedirs(os.path.dirname(res_output_path), exist_ok=True)

    dut_class = args.dut_name[0].upper() + args.dut_name[1:] if args.dut_name else args.dut_name
    lines = ['"""形式化反例测试用例 — 由 InitTestFile 自动生成"""', ""]

    if not rtl_bugs:
        lines.extend(["# 形式化验证未发现 RTL 缺陷，无需生成反例测试用例", ""])
    else:
        lines.extend([f"from {args.dut_name} import DUT{dut_class}", "", ""])
        for fa_id, prop_name in rtl_bugs:
            lines.extend([_render_test_function(prop_name, fa_id, clock_name, reset_name, dut_class), ""])

    with open(res_output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    msg = [f"✅ Test framework generated: {res_output_path}"]
    if rtl_bugs:
        msg.extend([
            f"   - RTL_BUGs found: {len(rtl_bugs)}",
            f"   - Clock: {clock_name or '[Unknown]'}, Reset: {reset_name or '[Unknown]'}",
        ])
        msg.extend(
            f"     • test_cex_{_strip_prop_prefix(prop_name).lower()}() ← {fa_id}"
            for fa_id, prop_name in rtl_bugs
        )
    else:
        msg.append("   - No RTL_BUG found, generated empty test file.")

    result = str_info("\n".join(msg))
    print(result)


if __name__ == "__main__":
    main()
