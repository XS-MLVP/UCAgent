# -*- coding: utf-8 -*-
"""Generate or incrementally update formal environment analysis document."""

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
from ucagent.lang.zh.skills.formal.lib import formal_adapter





def _parse_avis_log(log_path: str) -> dict:
    return formal_adapter.parse_log(log_path)


def _extract_property_code(checker_content: str, prop_name: str) -> str:
    if not checker_content:
        return f"  // Property code unavailable for {prop_name}"
    pattern = re.compile(
        rf"(property\s+(?:(?:A|M|C)_)?{re.escape(prop_name)}[\s;].*?endproperty)",
        re.DOTALL,
    )
    match = pattern.search(checker_content)
    if match:
        return "\n".join("  " + line for line in match.group(1).split("\n"))
    for i, line in enumerate(checker_content.split("\n")):
        if prop_name in line:
            return "\n".join(checker_content.split("\n")[max(0, i - 2):i + 4])
    return f"  // Property definition not found for {prop_name}"


def _backup_if_exists(filepath: str) -> None:
    if os.path.exists(filepath):
        shutil.copy2(filepath, filepath + ".bak")


def _render_tt_entry(idx: int, prop_name: str, checker_content: str) -> str:
    sva_code = _extract_property_code(checker_content, prop_name)
    return f"""### <TT-{idx:03d}> {prop_name}
- **属性名**: {prop_name}
- **SVA 代码**:
  ```systemverilog
{sva_code}
  ```
- **根因分类**: [LLM-TODO: ASSUME_TOO_STRONG | SIGNAL_CONSTANT | WRAPPER_ERROR | DESIGN_EXPECTED]
- **关联 Assume**: [LLM-TODO: M_CK_YYY 或 N/A]
- **分析**: [LLM-TODO: 具体描述为何此属性 trivially true]
- **修复动作**: [LLM-TODO: FIXED | ACCEPTED]
- **修复说明**: [LLM-TODO: 描述修改内容或接受理由]
"""


def _render_fa_entry(idx: int, prop_name: str, prop_type: str, checker_content: str) -> str:
    sva_code = _extract_property_code(checker_content, prop_name)
    return f"""### <FA-{idx:03d}> {prop_name}
- **属性名**: {prop_name}
- **属性类型**: {prop_type}
- **SVA 代码**:
  ```systemverilog
{sva_code}
  ```
- **解决状态**: [LLM-TODO: RTL_BUG | ENV_FIXED | ENV_PENDING | COVER_EXPECTED_FAIL]
- **反例/分析**: [LLM-TODO: 描述反例中的信号值和时序关系]
- **修复说明**: [LLM-TODO: 具体描述修复内容或缺陷现象]
"""


def _run_init(dut_name: str, output_dir: str, log_path: str = None, output_path: str = None) -> str:
    paths = FormalPaths(dut=dut_name)
    res_log_path = paths.log
    res_output_path = paths.analysis
    checker_path = paths.checker

    if not os.path.exists(res_log_path):
        return str_error(f"Error: log file not found at {res_log_path}")

    log_result = _parse_avis_log(res_log_path)
    _backup_if_exists(res_output_path)
    os.makedirs(os.path.dirname(res_output_path), exist_ok=True)

    checker_content = ""
    if os.path.exists(checker_path):
        with open(checker_path, "r", encoding="utf-8", errors="ignore") as f:
            checker_content = f.read()

    n_pass = len(log_result["pass"])
    n_tt = len(log_result["trivially_true"])
    n_false = len(log_result["false"])
    n_cover_pass = len(log_result["cover_pass"])
    n_cover_fail = len(log_result["cover_fail"])
    n_total = n_pass + n_tt + n_false + n_cover_pass + n_cover_fail

    lines = [
        f"# {dut_name} 形式化验证环境分析报告\n",
        "> **由 InitEnvAnalysis 自动生成** — [LLM-TODO] 标记处需要人工填写\n",
        "---",
    ]
    lines.extend([
        "## 1. 验证结果概览\n",
        "| 类型 | 数量 |",
        "|------|------|",
        f"| Assert Pass | {n_pass} |",
        f"| Assert TRIVIALLY_TRUE | {n_tt} |",
        f"| Assert Fail | {n_false} |",
        f"| Cover Pass | {n_cover_pass} |",
        f"| Cover Fail | {n_cover_fail} |",
        f"| **Total** | **{n_total}** |",
        "",
        "---",
    ])

    lines.append("## 2. TRIVIALLY_TRUE 属性分析\n")
    if n_tt == 0:
        lines.append("> 无 TRIVIALLY_TRUE 属性，验证环境约束健康。\n")
    else:
        lines.append(f"> 共 {n_tt} 个 TRIVIALLY_TRUE 属性需要分析。\n")
        lines.extend(
            _render_tt_entry(i, prop, checker_content)
            for i, prop in enumerate(log_result["trivially_true"], start=1)
        )
    lines.append("---")

    lines.append("## 3. FALSE 属性分析\n")
    false_props = [(p, "assert") for p in log_result["false"]] + [(p, "cover") for p in log_result["cover_fail"]]
    n_fa = len(false_props)
    if n_fa == 0:
        lines.append("> 无 FALSE 属性，所有断言和覆盖属性均已通过。\n")
    else:
        lines.append(f"> 共 {n_fa} 个 FALSE 属性需要分析。\n")
        lines.extend(
            _render_fa_entry(i, prop, ptype, checker_content)
            for i, (prop, ptype) in enumerate(false_props, start=1)
        )

    with open(res_output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return str_info(
        f"✅ Document generated at: {res_output_path}\n"
        f"   - TRIVIALLY_TRUE entries: {n_tt}\n"
        f"   - FALSE entries: {n_fa}\n"
        f"   - Total [LLM-TODO] remaining: {n_tt + n_fa}"
    )


def _run_update(dut_name: str, output_dir: str) -> str:
    paths = FormalPaths(dut=dut_name)
    log_path = paths.log
    doc_path = paths.analysis
    checker_path = paths.checker

    if not os.path.exists(log_path):
        return str_error(f"Error: log file not found at {log_path}")
    if not os.path.exists(doc_path):
        return str_error(f"Error: document not found at {doc_path}. Use init mode first.")

    log_result = _parse_avis_log(log_path)
    current_tt = set(log_result["trivially_true"])
    current_fa = set(log_result["false"]).union(set(log_result["cover_fail"]))

    with open(doc_path, "r", encoding="utf-8", errors="ignore") as f:
        doc_content = f.read()

    existing_tt = set(re.findall(r"###\s*<TT-\d+>\s+(\S+)", doc_content))
    existing_fa = set(re.findall(r"###\s*<FA-\d+>\s+(\S+)", doc_content))

    new_tt = current_tt - existing_tt
    new_fa = current_fa - existing_fa

    if not new_tt and not new_fa:
        return str_info(
            f"ℹ️ No new abnormal properties found in log. Doc is up-to-date.\n"
            f"   - Log TT count: {len(current_tt)}, FA count: {len(current_fa)}\n"
            f"   - Doc TT count: {len(existing_tt)}, FA count: {len(existing_fa)}"
        )

    checker_content = ""
    if os.path.exists(checker_path):
        with open(checker_path, "r", encoding="utf-8", errors="ignore") as f:
            checker_content = f.read()

    def _max_id(prefix: str) -> int:
        ids = [int(x) for x in re.findall(rf"###\s*<{prefix}-(\d+)>", doc_content)]
        return max(ids) if ids else 0

    next_tt_id = _max_id("TT") + 1
    next_fa_id = _max_id("FA") + 1

    tt_additions = []
    for prop in sorted(new_tt):
        tt_additions.append(_render_tt_entry(next_tt_id, prop, checker_content))
        next_tt_id += 1

    fa_additions = []
    for prop in sorted(new_fa):
        ptype = "cover" if prop in log_result["cover_fail"] else "assert"
        fa_additions.append(_render_fa_entry(next_fa_id, prop, ptype, checker_content))
        next_fa_id += 1

    _backup_if_exists(doc_path)
    with open(doc_path, "a", encoding="utf-8") as f:
        f.write("\n\n")
        if tt_additions:
            f.write(f"<!-- {len(tt_additions)} NEW TT ENTRIES ADDED BY UpdateEnvAnalysis -->\n")
            f.write("\n".join(tt_additions))
        if fa_additions:
            f.write(f"<!-- {len(fa_additions)} NEW FA ENTRIES ADDED BY UpdateEnvAnalysis -->\n")
            f.write("\n".join(fa_additions))

    return str_info(
        f"✅ Document incrementally updated at: {doc_path}\n"
        f"   - New TT entries appended: {len(new_tt)}\n"
        f"   - New FA entries appended: {len(new_fa)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Init/Update 07_{DUT}_env_analysis.md")
    parser.add_argument("-mode", choices=["init", "update"], required=True, help="init or update analysis doc")
    parser.add_argument("-dut_name", default=os.environ.get("DUT"), help="Top-level DUT module name")
    args = parser.parse_args()

    if not args.dut_name:
        print(str_error("Missing DUT name. Please provide -dut_name or set DUT environment variable."))
        return
    output_dir_env = os.environ.get("OUT")
    if not output_dir_env:
        print(str_error("Missing OUT environment variable."))
        return



    if args.mode == "init":
        result = _run_init(
            dut_name=args.dut_name,
            output_dir=output_dir_env,
        )
    else:
        result = _run_update(dut_name=args.dut_name, output_dir=output_dir_env)

    print(result)


if __name__ == "__main__":
    main()
