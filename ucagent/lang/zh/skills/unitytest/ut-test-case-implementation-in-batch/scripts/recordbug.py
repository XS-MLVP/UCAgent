import argparse
import json
import os
import re

project_root = os.getcwd()
SECTION_TITLE = "## 未测试通过检测点分析"
ROOT_CAUSE_SECTION_TITLE = "## 缺陷根因分析"
bug_analysis_template = '''
{DUT} 缺陷分析文档

{SECTION_TITLE}

{ROOT_CAUSE_SECTION_TITLE}
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
    parser.add_argument(
        "-ROOT",
        required=False,
        default="",
        help="Root cause analysis of bug",
    )
    parser.add_argument("-FILE", required=True, help="Source file path and start, end line numbers, e.g., ALU754_RTL/ALU754.v:13-14")
    parser.add_argument("-FIX", required=True, help="Suggestions for repairing defects")
    return parser.parse_args()


def validate_tag(tag, prefix):
    if not tag.startswith(prefix + "-"):
        raise ValueError(f"Error: {prefix} tag format invalid: {tag}")


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
    # Convert report key like path:48-61::test_xxx to path::test_xxx.
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
        if line.strip() == SECTION_TITLE:
            start = i
            break
    if start < 0:
        raise ValueError(
            f"Error: section '{SECTION_TITLE}' not found in target markdown."
        )

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    return start, end


def locate_section_by_title(lines, title):
    start = -1
    for i, line in enumerate(lines):
        if line.strip() == title:
            start = i
            break
    if start < 0:
        raise ValueError(f"Error: section '{title}' not found in target markdown.")

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    return start, end


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


def make_bg_tc_block(bg, bd, tc, confidence):
    return ensure_trailing_newline_block(
        f"  - <{bg}> Bug 置信度 {confidence}%\n"
        f"    - <{tc}> {bd}\n"
    )


def make_ck_bg_block(ck, bg, bd, tc, confidence):
    return ensure_trailing_newline_block(
        f"- <{ck}> {bd}\n"
        f"{make_bg_tc_block(bg, bd, tc, confidence)}"
    )


def insert_content(lines, fg, fc, ck, bg, tc, bd):
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

        # Only treat BG as duplicate when it already exists under the same CK block.
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

            lines.insert(bg_end, f"    - <{tc}> {bd}\n")
            return "CK/BG exist; appended missing TC entry."

        # Same CK exists but different BG: append another bug item after this CK block.
        lines.insert(ck_end, bg_tc_block)
        return "CK exists; appended new BG/TC under this FC."

    lines.insert(fc_end, ck_bg_block)
    return "Inserted new CK/BG/TC under existing FG/FC."


def _tc_display_for_root_section(tc_tag):
    file_path, class_name, func_name = parse_tc_target(tc_tag)
    short_file = os.path.basename(file_path)
    if class_name:
        return f"{short_file}::{class_name}::{func_name}"
    return f"{short_file}::{func_name}"


def _build_root_cause_block(fg, fc, ck, bg, tc_display, bd, root, file, lang, code_snippet, fix):
    return (
        f"### {fg} / {fc} / {ck}\n"
        f"**Bug标签**: {bg}\n"
        f"**测试用例**: {tc_display}\n"
        f"**问题描述**:{bd}\n"
        f"**根因分析**: \n"
        f"{root}\n"
        f"```{lang}\n"
        f"// {file}\n"
        f"{code_snippet}\n"
        f"```\n"
        f"**修复建议**\n"
        f"{fix}\n"
    )

def get_code_snippet(file_path, start_line, end_line, indent_level=0):
    """Reads a snippet of code from a file."""
    abs_path = os.path.join(project_root, file_path)
    if not os.path.exists(abs_path):
        return [0, f"Error: File {abs_path} not found. Please use the correct path and use `RunSkillScript` tool again."]

    try:
        with open(abs_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        start_index = start_line - 1
        end_index = end_line

        if start_index < 0 or end_index > len(lines):
            return [0, f"Error: Line numbers {start_line}-{end_line} are out of file range. Please use correct line numbers and use `RunSkillScript` tool again."]

        snippet_lines = lines[start_index:end_index]

        formatted_snippet = ""
        indent_str = " " * indent_level
        for i, line in enumerate(snippet_lines):
            line_content = line.rstrip()
            formatted_snippet += f"{indent_str}{start_line + i}:  {line_content}"
            if i < len(snippet_lines) - 1:
                formatted_snippet += "\n"

        return [1, formatted_snippet]

    except Exception as e:
        return [0, f"Error reading file {abs_path}: {e}"]

def insert_root_cause_content(lines, fg, fc, ck, bg, tc, bd, root, file, fix):
    if not root:
        return "ROOT is empty; skipped root cause insertion."
    
    relative_path = ""
    start_line = 0
    end_line = 0
    file_match = re.fullmatch(r'([^:]+):(\d+)(?:-(\d+))?', file)
    relative_path, start_str, end_str = file_match.groups()
    start_line = int(start_str)
    end_line = int(end_str) if end_str else start_line

    correct, code_snippet = get_code_snippet(relative_path, start_line, end_line, indent_level=0)
    if not correct:
        return code_snippet

    lang = ""
    if relative_path.split('.')[-1] in ['v', 'sv']:
        lang = "verilog"
    elif relative_path.split('.')[-1] in ['scala']:
        lang = "scala"

    rc_start, rc_end = locate_section_by_title(lines, ROOT_CAUSE_SECTION_TITLE)
    heading = f"### {fg} / {fc} / {ck}"
    tc_display = _tc_display_for_root_section(tc)

    heading_line = -1
    for i in range(rc_start + 1, rc_end):
        if lines[i].strip() == heading:
            heading_line = i
            break

    if heading_line < 0:
        block = _build_root_cause_block(fg, fc, ck, bg, tc_display, bd, root, file, lang, code_snippet, fix)
        lines.insert(rc_end, block)
        return "Inserted new root cause block."

    block_end = next_boundary(
        lines,
        heading_line + 1,
        rc_end,
        [lambda t: t.startswith("### "), lambda t: t.startswith("## ")],
    )

    root_prefix = "**相关源码位置**:"
    for i in range(heading_line + 1, block_end):
        if lines[i].startswith(root_prefix):
            lines[i] = f"{root_prefix} {root}\n"
            return "Updated ROOT in existing root cause block."

    insert_pos = block_end
    while insert_pos > heading_line + 1 and lines[insert_pos - 1].strip() == "":
        insert_pos -= 1
    lines.insert(insert_pos, f"\n{root_prefix} {root}\n")
    return "Inserted ROOT into existing root cause block."


def main():
    args = parse_args()
    validate_tag(args.BG, "BG")
    validate_tag(args.TC, "TC")

    escaped_bd = escape_markdown_asterisk(args.BD)
    escaped_root = escape_markdown_asterisk(args.ROOT)
    escaped_fix = escape_markdown_asterisk(args.FIX)

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
            SECTION_TITLE=SECTION_TITLE,
            ROOT_CAUSE_SECTION_TITLE=ROOT_CAUSE_SECTION_TITLE,
        ).lstrip()
        with open(target, "w", encoding="utf-8") as f:
            f.write(initial_content)

    with open(target, "r", encoding="utf-8") as f:
        lines = f.readlines()

    msgs = []
    for fg, fc, ck in fg_fc_ck_list:
        msg = insert_content(lines, fg, fc, ck, args.BG, args.TC, escaped_bd)
        root_msg = insert_root_cause_content(
            lines, fg, fc, ck, args.BG, args.TC, escaped_bd, escaped_root, args.FILE, escaped_fix
        )
        msgs.append(f"{msg} {root_msg} (resolved: {fg}/{fc}/{ck})")

    with open(target, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print("; ".join(msgs) + f" -> {target}")


if __name__ == "__main__":
    main()
