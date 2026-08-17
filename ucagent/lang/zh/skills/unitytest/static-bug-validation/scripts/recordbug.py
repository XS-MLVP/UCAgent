import argparse
import json
import os
import re

DYNAMIC_BUGS_MARKER = "<DYNAMIC-BUGS>"
TODO_MARKER = "<BUG-TODO>"
OVERVIEW_MARKER = "<BUG-OVERVIEW>"
bug_analysis_template = '''
# {DUT} 动态 Bug 分析

## 未测试通过检测点分析
{DYNAMIC_BUGS_MARKER}
'''

def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Insert one bug entry into {DUT}_bug_analysis.md. "
            "FG/FC/CK are inferred from TC target test function."
        )
    )
    parser.add_argument("-BG", required=True, help="Bug tag, e.g. BG-CIN-OVERFLOW-98")
    parser.add_argument(
        "-TC",
        required=True,
        help=(
            "Test case tag, e.g. "
            "TC-unity_test/tests/test_ALU754_api.py::test_div"
        ),
    )
    parser.add_argument("-BD", required=True, help="Bug description")
    return parser.parse_args()


def validate_tag(tag, prefix):
    if not tag.startswith(prefix + "-"):
        raise ValueError(f"Error: {prefix} tag format invalid: {tag}")


def validate_dynamic_bg_tag(tag):
    validate_tag(tag, "BG")
    if tag.startswith("BG-STATIC-"):
        raise ValueError(
            "Error: -BG is a dynamic Bug tag and cannot use the BG-STATIC-* "
            "namespace. Keep <BG-STATIC-*> in {DUT}_static_bug_analysis.md, "
            "create a distinct BG-NAME-XX tag here, and link it with LINK-BUG."
        )
    if bg_confidence(tag) == 0:
        raise ValueError(
            "Error: -BG confidence must be greater than 0 for a confirmed dynamic Bug."
        )


def parse_tc_target(tc_tag):
    validate_tag(tc_tag, "TC")
    payload = tc_tag[len("TC-") :]
    parts = payload.split("::")
    if len(parts) == 2:
        file_path, func_name = parts
        class_name = None
    elif len(parts) == 3:
        file_path, class_name, func_name = parts
    else:
        raise ValueError(
            "Error: TC format invalid. Expected TC-<path>::<test_func> "
            "or TC-<path>::<ClassName>::<test_func>."
        )
    if not file_path or not func_name:
        raise ValueError("Error: TC path/function is empty.")
    return file_path, class_name, func_name


def _normalize_report_tc_key(key):
    return re.sub(r":\d+-\d+(?=::)", "", key)


def _parse_fg_fc_ck_items(raw_items, source_key):
    parsed = []
    for raw in raw_items:
        if not isinstance(raw, str):
            continue
        parts = raw.split("/")
        if len(parts) != 3:
            raise ValueError(
                f"Error: invalid check point format in report for '{source_key}': {raw}"
            )
        parsed.append((parts[0], parts[1], parts[2]))
    return parsed


def resolve_fg_fc_ck_list_by_tc(tc_tag, out_dir):
    file_path, class_name, func_name = parse_tc_target(tc_tag)
    if class_name:
        tc_target = f"{file_path}::{class_name}::{func_name}"
    else:
        tc_target = f"{file_path}::{func_name}"

    report_path = os.path.join(os.getcwd(), out_dir, ".TEST_TEMPLATE_IMP_REPORT.json")
    if not os.path.exists(report_path):
        raise FileNotFoundError(f"Error: report file not found: {report_path}")

    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    mapping = report.get("failed_test_case_with_check_point_list")
    if not isinstance(mapping, dict):
        raise ValueError(
            "Error: 'failed_test_case_with_check_point_list' missing or invalid in report."
        )

    found = []
    for key, raw_items in mapping.items():
        if _normalize_report_tc_key(key) != tc_target:
            continue
        if not isinstance(raw_items, list):
            raise ValueError(
                f"Error: report entry for '{key}' is not a list: {type(raw_items).__name__}"
            )
        found.extend(_parse_fg_fc_ck_items(raw_items, key))

    uniq = list(dict.fromkeys(found))
    if not uniq:
        raise ValueError(
            "Error: no FG/FC/CK mapping found in report for target TC: "
            f"{tc_target}"
        )
    return uniq


def bg_confidence(bg_tag):
    m = re.match(r"^BG-.+-(\d{1,3})$", bg_tag)
    if not m:
        raise ValueError(
            f"Error: BG tag format invalid: {bg_tag}. Expected BG-<NAME>-<0~100>."
        )
    conf = int(m.group(1))
    if conf < 0 or conf > 100:
        raise ValueError(f"Error: BG confidence out of range 0~100: {conf}")
    return conf


def locate_section(lines):
    start = -1
    for i, line in enumerate(lines):
        if line.strip() == DYNAMIC_BUGS_MARKER:
            start = i
            break
    if start < 0:
        raise ValueError(
            f"Error: marker '{DYNAMIC_BUGS_MARKER}' not found in target markdown."
        )

    return start, len(lines)


def find_tag_line(lines, start, end, tag):
    token = f"<{tag}>"
    for i in range(start, end):
        if token in lines[i]:
            return i
    return -1


def next_boundary(lines, start, end, patterns):
    for i in range(start, end):
        text = lines[i].strip()
        for p in patterns:
            if p(text):
                return i
    return end


def ensure_trailing_newline_block(block):
    if not block.endswith("\n"):
        return block + "\n"
    return block


def escape_markdown_asterisk(text):
    if not text:
        return text
    return re.sub(r"(?<!\\)\*", r"\\*", text)


def make_tc_scaffold(tc, bd):
    return ensure_trailing_newline_block(
        f"    - <{tc}> {bd}\n"
        "      ```yaml\n"
        "      waveform_analysis:\n"
        f"        status: \"{TODO_MARKER}\"\n"
        f"        receipt_id: \"{TODO_MARKER}\"\n"
        "      ```\n"
        f"      <WAVEFORM-VIEWER> [{TODO_MARKER}](/surfer/?wave={TODO_MARKER})\n"
    )


def make_bug_analysis_scaffold(bd):
    return ensure_trailing_newline_block(
        f"    {OVERVIEW_MARKER}\n"
        "    **Bug 概述**\n\n"
        f"    {bd}\n\n"
        "    <BUG-SYMPTOMS>\n"
        "    **现象与等级**\n\n"
        f"    {TODO_MARKER}\n\n"
        "    <BUG-TRIGGER>\n"
        "    **触发条件与影响范围**\n\n"
        f"    {TODO_MARKER}\n\n"
        "    <BUG-ROOT-CAUSE>\n"
        "    **根因分析**\n\n"
        f"    {TODO_MARKER}\n\n"
        "    <BUG-SOURCE-EVIDENCE>\n"
        "    **源码证据与逐行分析**\n\n"
        f"    {TODO_MARKER}\n\n"
        "    <BUG-CAUSAL-CHAIN>\n"
        "    **动态因果链**\n\n"
        f"    {TODO_MARKER}\n\n"
        "    <BUG-FIX>\n"
        "    **修复建议**\n\n"
        f"    {TODO_MARKER}\n\n"
        "    <BUG-RETEST>\n"
        "    **风险与复验计划**\n\n"
        f"    {TODO_MARKER}\n"
    )


def make_bg_tc_block(bg, bd, tc, confidence):
    return ensure_trailing_newline_block(
        f"  - <{bg}> Bug 置信度 {confidence}%\n"
        f"{make_tc_scaffold(tc, bd)}"
        f"{make_bug_analysis_scaffold(bd)}"
    )


def make_ck_bg_block(ck, bg, bd, tc, confidence):
    return ensure_trailing_newline_block(
        f"- <{ck}> {bd}\n"
        f"{make_bg_tc_block(bg, bd, tc, confidence)}"
    )


def insert_content(lines, fg, fc, ck, bg, tc, bd):
    lines[:] = "".join(lines).splitlines(keepends=True)
    confidence = bg_confidence(bg)
    sec_start, sec_end = locate_section(lines)

    fg_line = find_tag_line(lines, sec_start + 1, sec_end, fg)
    ck_bg_block = make_ck_bg_block(ck, bg, bd, tc, confidence)
    bg_tc_block = make_bg_tc_block(bg, bd, tc, confidence)

    if fg_line < 0:
        new_block = (
            f"\n<{fg}>\n\n"
            f"#### <{fc}>\n"
            f"{ck_bg_block}"
        )
        lines.insert(sec_end, new_block)
        return "Inserted new FG/FC/CK/BG/TC block."

    fg_end = next_boundary(
        lines,
        fg_line + 1,
        sec_end,
        [lambda t: t.startswith("<FG-")],
    )

    fc_line = find_tag_line(lines, fg_line + 1, fg_end, fc)
    if fc_line < 0:
        new_fc_block = ensure_trailing_newline_block(
            f"\n#### <{fc}>\n{ck_bg_block}"
        )
        lines.insert(fg_end, new_fc_block)
        return "Inserted new FC/CK/BG/TC block under existing FG."

    fc_end = next_boundary(
        lines,
        fc_line + 1,
        fg_end,
        [lambda t: t.startswith("#### ") and "<FC-" in t],
    )

    ck_line = find_tag_line(lines, fc_line + 1, fc_end, ck)
    if ck_line >= 0:
        ck_end = next_boundary(
            lines,
            ck_line + 1,
            fc_end,
            [lambda t: t.startswith("- <CK-"), lambda t: t.startswith("#### ")],
        )

        bg_line = find_tag_line(lines, ck_line, ck_end, bg)
        if bg_line >= 0:
            bg_end = next_boundary(
                lines,
                bg_line + 1,
                ck_end,
                [lambda t: t.startswith("  - <BG-"), lambda t: t.startswith("- <CK-"), lambda t: t.startswith("#### ")],
            )
            tc_line = find_tag_line(lines, bg_line + 1, bg_end, tc)
            if tc_line >= 0:
                return "CK/BG/TC already exist. Nothing changed."

            details_line = next(
                (
                    i
                    for i in range(bg_line + 1, bg_end)
                    if lines[i].strip() == OVERVIEW_MARKER
                ),
                bg_end,
            )
            lines.insert(details_line, make_tc_scaffold(tc, bd))
            return "CK/BG exist; appended missing TC scaffold."

        lines.insert(ck_end, bg_tc_block)
        return "CK exists; appended new BG/TC under this FC."

    lines.insert(fc_end, ck_bg_block)
    return "Inserted new CK/BG/TC under existing FG/FC."

def main():
    args = parse_args()
    validate_dynamic_bg_tag(args.BG)
    validate_tag(args.TC, "TC")

    escaped_bd = escape_markdown_asterisk(args.BD)

    dut = os.environ.get("DUT")
    out = os.environ.get("OUT")
    if not dut or not out:
        raise ValueError(
            "Error: missing env DUT/OUT. Set -TARGET or export DUT and OUT."
        )

    fg_fc_ck_list = resolve_fg_fc_ck_list_by_tc(args.TC, out)

    target = os.path.join(os.getcwd(), out, f"{dut}_bug_analysis.md")

    if not os.path.isabs(target):
        target = os.path.join(os.getcwd(), target)
    if not os.path.exists(target):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        initial_content = bug_analysis_template.format(
            DUT=dut,
            DYNAMIC_BUGS_MARKER=DYNAMIC_BUGS_MARKER,
        ).lstrip()
        with open(target, "w", encoding="utf-8") as f:
            f.write(initial_content)

    with open(target, "r", encoding="utf-8") as f:
        lines = f.readlines()

    msgs = []
    for fg, fc, ck in fg_fc_ck_list:
        msg = insert_content(lines, fg, fc, ck, args.BG, args.TC, escaped_bd)
        msgs.append(f"{msg} (resolved: {fg}/{fc}/{ck})")

    with open(target, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(
        "; ".join(msgs)
        + f" -> {target}. Incomplete scaffold marker: {TODO_MARKER}."
    )


if __name__ == "__main__":
    main()
