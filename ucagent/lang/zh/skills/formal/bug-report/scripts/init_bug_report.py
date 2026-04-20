# -*- coding: utf-8 -*-
"""Generate formal bug report scaffold from env analysis."""

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


def _backup_if_exists(filepath: str) -> None:
    if os.path.exists(filepath):
        shutil.copy2(filepath, filepath + ".bak")


def _render_bug_entry(idx: int, fa_id: str, prop_name: str) -> str:
    ck_part = _strip_prop_prefix(prop_name)
    bg_name = f"BG-FORMAL-{idx:03d}-{ck_part.replace('_', '-')}"

    return f"""## Failed Property: `{prop_name}`

### [LLM-TODO: <FG-???> 关联的功能组]

### [LLM-TODO: <FC-???> 关联的功能点]

### <{bg_name}> [LLM-TODO: 缺陷标题]

<CK-{ck_part.replace('_', '-')}>

<TC-FORMAL-{idx:03d}> 形式化验证反例证实（对应 {fa_id}）

**FILE-RTL文件路径**: [LLM-TODO: RTL文件路径:行号]

**问题描述**: [LLM-TODO: 详细描述由于什么原因导致了预期之外的行为]
**根本原因**: [LLM-TODO: 是什么代码逻辑或参数导致了这个问题]
**触发条件**: [LLM-TODO: 什么输入组合或时序状态能够复现该 Bug]
**预期行为**: [LLM-TODO: 预期的正确输出是什么]
**实际行为**: [LLM-TODO: 当前错误的输出是什么]
**修复建议**: [LLM-TODO: 具体的代码修改建议]

**反例波形解读**:
- 触发条件: [LLM-TODO]
- 反例值: [LLM-TODO: e.g. a = 0x..., b = 0x...]
- 预期结果: [LLM-TODO]
- 实际结果: [LLM-TODO]

**影响范围**: [LLM-TODO: 严重 | 中等 | 低]
**置信度**: [LLM-TODO: 高 | 中 | 低]
**优先级**: [LLM-TODO: 最高 | 高 | 中 | 低]

---
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate 04_{DUT}_bug_report.md scaffold")
    parser.add_argument("-dut_name", default=os.environ.get("DUT"), help="Top-level DUT module name")
    args = parser.parse_args()

    dut_name = args.dut_name
    output_dir_env = os.environ.get("OUT")

    if not dut_name:
        print(str_error("Missing DUT environment variable."))
        return
    if not output_dir_env:
        print(str_error("Missing OUT environment variable."))
        return



    paths = FormalPaths(dut=args.dut_name)
    res_analysis_path = paths.analysis
    res_output_path = paths.bug_report

    if not os.path.exists(res_analysis_path):
        print(str_error(f"Error: Analysis doc not found at {res_analysis_path}"))
        return

    rtl_bugs = _extract_rtl_bug_from_analysis_doc(res_analysis_path)
    _backup_if_exists(res_output_path)
    os.makedirs(os.path.dirname(res_output_path), exist_ok=True)

    lines = [f"# {dut_name} 形式化验证缺陷报告\n"]
    if not rtl_bugs:
        lines.append("形式化验证未发现 RTL 设计缺陷，所有属性已通过证明。\n")
    else:
        lines.extend([
            "> **由 InitBugReport 自动生成** — [LLM-TODO] 标记处需要人工填写\n",
            f"本报告记录了 {len(rtl_bugs)} 个 RTL 缺陷。\n",
            "---",
        ])
        lines.extend(_render_bug_entry(i, fa_id, prop_name) for i, (fa_id, prop_name) in enumerate(rtl_bugs, start=1))
        lines.extend([
            "## 缺陷统计汇总\n",
            "| 序号 | BG 标签 | 对应属性 | 来源 | 影响范围 | 优先级 |",
            "|------|---------|----------|------|----------|--------|",
        ])
        for i, (fa_id, prop_name) in enumerate(rtl_bugs, start=1):
            bg_name = f"BG-FORMAL-{i:03d}-{_strip_prop_prefix(prop_name).replace('_', '-')}"
            lines.append(f"| {i} | {bg_name} | {prop_name} | {fa_id} | [LLM-TODO] | [LLM-TODO] |")
        lines.extend([
            "",
            "## 根因分析总结\n",
            "> [LLM-TODO: 如果多个缺陷源于同一个代码错误，请在此总结提炼出根本原因。如果缺陷互不相关，可分别简述。]\n",
            "| 缺陷 | 行号 | 当前代码缺陷 | 修复建议 |",
            "|------|------|----------|----------|",
            "| [LLM-TODO: FA_ID] | [LLM-TODO] | [LLM-TODO] | [LLM-TODO] |",
            "\n**修复方案总结**: [LLM-TODO: 归纳该如何修改代码以修复上述问题]\n",
        ])

    with open(res_output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    msg = [f"✅ Bug report framework generated: {res_output_path}"]
    if rtl_bugs:
        msg.append(f"   - RTL_BUGs found: {len(rtl_bugs)}")
        msg.extend(f"     • {fa_id}: {prop_name}" for fa_id, prop_name in rtl_bugs)
    else:
        msg.append("   - No RTL_BUG found, generated empty defect declaration.")

    result = str_info("\n".join(msg))
    print(result)


if __name__ == "__main__":
    main()
