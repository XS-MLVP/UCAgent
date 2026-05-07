import argparse
import json
import os
import re

project_root = os.getcwd()
script_dir = os.path.dirname(os.path.abspath(__file__))
potential_bug_summary = "潜在Bug汇总"
detail_analysis = "详细分析"
batch_analysis = "批次分析进度"
static_bug_analysis_md_template = "# {DUT} RTL 源码静态分析报告\n\n"\
"## 一、潜在Bug汇总\n\n"\
"| 序号 | Bug标签 | 功能路径 | 描述摘要 | 置信度 | 涉及文件 | 动态Bug关联 |\n"\
"|------|---------|----------|----------|--------|----------|-------------|\n\n"\
"## 二、详细分析\n\n"\
"## 三、批次分析进度\n\n"\
"| 源文件 | 发现疑似Bug数 | 状态 |\n"\
"|--------|---------------|------|\n"


def str_remove_blank(text):
    return re.sub(r"\s+", "", text)


def rm_blank_in_str(text):
    return str_remove_blank(text)


def str_replace_to(text, old_list, new_str):
    for old in old_list:
        text = text.replace(old, new_str)
    return text


def escape_md_table_cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def get_sub_str(text, prefix, suffix):
    start = text.find(prefix)
    if start < 0:
        raise ValueError(f"Prefix '{prefix}' not found in '{text}'.")
    start += len(prefix)
    end = text.find(suffix, start)
    if end < 0:
        raise ValueError(f"Suffix '{suffix}' not found in '{text}'.")
    return text[start:end]


def parse_nested_keys(
    target_file,
    keyname_list,
    prefix_list,
    suffix_list,
    ignore_chars=None,
):
    """Parse nested FG/FC/CK tags from a markdown-like file."""
    if ignore_chars is None:
        ignore_chars = ["<", ">"]
    assert os.path.exists(target_file), f"File {target_file} does not exist."
    assert len(keyname_list) > 0, "Prefix must be provided."
    assert "line" not in keyname_list, "'line' is a reserved key name."
    assert len(prefix_list) == len(suffix_list), "Prefix and suffix lists must have the same length."
    assert len(prefix_list) == len(keyname_list), "Prefix and keyname lists must have the same length."

    pre_values = [None] * len(prefix_list)
    key_dict = {}

    def get_parent_node(i):
        next_key = keyname_list[i + 1] if i < len(keyname_list) - 1 else None
        if i == 0:
            return key_dict, next_key
        if pre_values[i - 1] is None:
            return None, next_key
        return pre_values[i - 1][keyname_list[i]], next_key

    with open(target_file, "r", encoding="utf-8") as f:
        for index, line in enumerate(f.readlines(), start=1):
            line = str_remove_blank(line.strip())
            for i, key in enumerate(keyname_list):
                prefix = prefix_list[i]
                suffix = suffix_list[i]
                pre_key = keyname_list[i - 1] if i > 0 else None
                pre_prefix = prefix_list[i - 1] if i > 0 else None
                if prefix not in line:
                    continue
                assert line.count(prefix) == 1, (
                    f"At line ({index}): '{line}' should contain exactly one {key} '{prefix}'"
                )
                current_key = rm_blank_in_str(
                    str_replace_to(get_sub_str(line, prefix, suffix), ignore_chars, "")
                )
                parent_node, next_key = get_parent_node(i)
                if parent_node is None:
                    raise ValueError(
                        f"At line ({index}): Found {key} tag '{prefix}' but its parent {pre_key} "
                        f"tag '{pre_prefix}' was not found in previous lines. Please ensure proper "
                        f"nesting: each '{prefix}' must be preceded by a '{pre_prefix}' tag.\n"
                        f"Current line content: {line}"
                    )
                assert current_key not in parent_node, (
                    f"At line ({index}): '{current_key}' is defined multiple times."
                )
                parent_node[current_key] = {"line": index}
                if next_key is not None:
                    parent_node[current_key][next_key] = {}
                pre_values[i] = parent_node[current_key]

    return key_dict


def build_initial_batch_analysis_rows(DUT):
    rtl_root = os.path.join(project_root, f"{DUT}_RTL")
    if not os.path.isdir(rtl_root):
        return ""

    file_rows = []
    for root, _, files in os.walk(rtl_root):
        for file_name in files:
            if file_name == "filelist.txt":
                continue
            abs_path = os.path.join(root, file_name)
            rel_path = os.path.relpath(abs_path, project_root).replace(os.sep, "/")
            file_rows.append(rel_path)

    file_rows.sort()
    return "".join(f"| <file>{file_path}</file> | 0 | ✅ 完成 |\n" for file_path in file_rows)


def parse_md_file(file_path):
    """
    Parse {DUT}_functions_and_checks.md to extract a hierarchical structure of functions.
    Args:
        file_path (str): The path of {DUT}_functions_and_checks.md.
    Returns:
        dict: A nested dict with FG -> FC -> CK structure.
    """
    keynames = ["FG", "FC", "CK"]
    prefix = ["<FG-", "<FC-", "<CK-"]
    suffix = [">"] * len(prefix)
    raw_data = parse_nested_keys(file_path, keynames, prefix, suffix)

    hierarchy = {}
    for fg_name, fg_value in raw_data.items():
        fg_key = f"FG-{fg_name}"
        hierarchy[fg_key] = {}
        fc_nodes = fg_value.get("FC", {})
        for fc_name, fc_value in fc_nodes.items():
            fc_key = f"FC-{fc_name}"
            hierarchy[fg_key][fc_key] = {}
            ck_nodes = fc_value.get("CK", {})
            for ck_name in ck_nodes.keys():
                ck_key = f"CK-{ck_name}"
                hierarchy[fg_key][fc_key][ck_key] = {}
    return hierarchy


def get_function_dict_json_path(DUT):
    return os.path.join(script_dir, f"{DUT}_functions_and_checks.json")


def load_or_create_function_dict(DUT, OUT):
    function_dict_file = os.path.join(project_root, OUT, f'{DUT}_functions_and_checks.md')
    json_file = get_function_dict_json_path(DUT)

    if os.path.exists(json_file):
        with open(json_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    function_dict = parse_md_file(function_dict_file)
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(function_dict, f, ensure_ascii=False, indent=2)
    return function_dict


def validate_hierarchy(DUT, f_dict, fg, fc, ck, bg, file_info):
    """
    Validates tags and file location format before writing the bug report.
    """
    if fg.split('-')[0] != 'FG':
        return [0, f"Error: -FG parameter '{fg}' format invalid, should start with 'FG-'. Modify the tag and use `RunSkillScript` tool again."]
    if fc.split('-')[0] != 'FC':
        return [0, f"Error: -FC parameter '{fc}' format invalid, should start with 'FC-'. Modify the tag and use `RunSkillScript` tool again."]
    if ck.split('-')[0] != 'CK':
        return [0, f"Error: -CK parameter '{ck}' format invalid, should start with 'CK-'. Modify the tag and use `RunSkillScript` tool again."]

    if fg not in f_dict:
        return [0, f"Error: -FG parameter '{fg}' is not defined in {DUT}_functions_and_checks.md. Use the correct tag and use `RunSkillScript` tool again."]

    fg_children = f_dict[fg]
    if not isinstance(fg_children, dict):
        return [0, f"Error: -FG parameter '{fg}' structure invalid. Use the correct tag and use `RunSkillScript` tool again."]

    if fc not in fg_children:
        return [0, f"Error: -FC parameter '{fc}' not found under function group '{fg}'. Use the correct tag and use `RunSkillScript` tool again."]

    ck_dict = fg_children[fc]
    if not isinstance(ck_dict, dict):
        return [0, f"Error: -FC parameter '{fc}' structure invalid. Use the correct tag and use `RunSkillScript` tool again."]

    if ck not in ck_dict:
        return [0, f"Error: -CK parameter '{ck}' not found under '{fc}' (in '{fg}'). Use the correct tag and use `RunSkillScript` tool again."]

    if not isinstance(bg, str) or not re.fullmatch(r'BG-STATIC-\d{3}-[^-\s]+(?:-[^-\s]+)*', bg):
        return [0, f"Error: -BG parameter '{bg}' format invalid, should be 'BG-STATIC-NNN-NAME'. Modify the tag and use `RunSkillScript` tool again."]

    if not isinstance(file_info, str) or not re.fullmatch(r'[^:]+:\d+(?:-\d+)?', file_info):
        return [0, "Error: -FILE parameter format invalid, should be 'path:start_line-end_line' or 'path:line_number', modify the parameter and use `RunSkillScript` tool again."]

    file_match = re.fullmatch(r'([^:]+):(\d+)(?:-(\d+))?', file_info)
    _, start_str, end_str = file_match.groups()
    if end_str and int(end_str) < int(start_str):
        return [0, f"Error: -FILE parameter '{file_info}' line range invalid, end_line must be greater than or equal to start_line. Modify the parameter and use `RunSkillScript` tool again."]

    return [1, None]


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


def format_bug_report(dut, fg, fgd, fc, fcd, ck, ckd, bg, file_info, bug_description, confidence, function_dict):
    """
    Generates a formatted bug report in Markdown.
    """
    correct, validation_result = validate_hierarchy(dut, function_dict, fg, fc, ck, bg, file_info)
    if not correct:
        return validation_result

    relative_path = ""
    start_line = 0
    end_line = 0
    file_match = re.fullmatch(r'([^:]+):(\d+)(?:-(\d+))?', file_info)
    relative_path, start_str, end_str = file_match.groups()
    start_line = int(start_str)
    end_line = int(end_str) if end_str else start_line

    correct, code_snippet = get_code_snippet(relative_path, start_line, end_line, indent_level=8)
    if not correct:
        return code_snippet

    lang = ""
    if relative_path.split('.')[-1] in ['v', 'sv']:
        lang = "verilog"
    elif relative_path.split('.')[-1] in ['scala']:
        lang = "scala"
    file_tag = f"<FILE-{relative_path}:{start_line}-{end_line}>"

    return {
        "summary_line": (
            f"| {escape_md_table_cell(bg.split('-')[2])} "
            f"| {escape_md_table_cell(bg)} "
            f"| {escape_md_table_cell(f'{fg}/{fc}/{ck}')} "
            f"| {escape_md_table_cell(bug_description)} "
            f"| {escape_md_table_cell(confidence)} "
            f"| {escape_md_table_cell(relative_path)} "
            f"| LINK-BUG-[BG-TBD] |\n"
        ),
        "fg": fg,
        "fgd":fgd,
        "fc": fc,
        "fcd": fcd,
        "ck": ck,
        "ckd": ckd,
        "bg": bg,
        "bug_description": bug_description,
        "relative_path": relative_path,
        "start_line": start_line,
        "end_line": end_line,
        "file_tag": file_tag,
        "lang": lang,
        "code_snippet": code_snippet,
    }


def update_target_md(target_md_path, formatted_output):
    if not os.path.exists(target_md_path):
        os.makedirs(os.path.dirname(target_md_path), exist_ok=True)
        dut_name = os.environ.get("DUT", "{DUT}")
        initial_batch_rows = build_initial_batch_analysis_rows(dut_name)
        with open(target_md_path, 'w', encoding='utf-8') as f:
            f.write(static_bug_analysis_md_template.format(DUT=dut_name))
            f.write(initial_batch_rows)

    with open(target_md_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    bg = formatted_output["bg"]
    bg_table_pattern = re.compile(rf'\|\s*[^|]*\|\s*{re.escape(bg)}\s*\|')
    bg_detail_tag = f"<{bg}>"
    for line in lines:
        if bg_detail_tag in line or bg_table_pattern.search(line):
            return f"Bug {bg} has been recorded"

    summary_line = formatted_output["summary_line"]
    fg = formatted_output["fg"]
    fgd = formatted_output["fgd"]
    fc = formatted_output["fc"]
    fcd = formatted_output["fcd"]
    ck = formatted_output["ck"]
    ckd = formatted_output["ckd"]
    bug_description = formatted_output["bug_description"]
    source_file = formatted_output["relative_path"]
    file_tag = formatted_output["file_tag"]
    lang = formatted_output["lang"]
    code_snippet = formatted_output["code_snippet"]

    fg_str = f"### <{fg}> {fgd}\n"
    fc_str = f"#### <{fc}> {fcd}\n"
    ck_str = f"##### <{ck}> {ckd}\n"
    bg_str = (
        f"  - <{bg}> {bug_description}\n"
        f"    - <LINK-BUG-[BG-TBD]>\n"
        f"      - {file_tag}\n"
        f"        ```{lang}\n"
        f"{code_snippet}\n"
        f"        ```\n"
    )

    summary_idx = -1
    for i, line in enumerate(lines):
        if potential_bug_summary in line:
            summary_idx = i
            break

    if summary_idx != -1:
        table_end_idx = summary_idx
        in_table = False
        for i in range(summary_idx + 1, len(lines)):
            if lines[i].strip().startswith('|'):
                in_table = True
                table_end_idx = i
            elif in_table and not lines[i].strip().startswith('|'):
                break
        lines.insert(table_end_idx + 1, summary_line)
    else:
        return f"Error: '{potential_bug_summary}' section not found in target file {target_md_path}, please ensure the overall format of the target file is correct and use `RunSkillScript` tool again."

    detail_idx = -1
    for i in range(table_end_idx + 1, len(lines)):
        line = lines[i]
        if detail_analysis in line:
            detail_idx = i
            break
    if detail_idx == -1:
        return f"Error: '{detail_analysis}' section not found in target file {target_md_path}, please ensure the overall format of the target file is correct and use `RunSkillScript` tool again."

    batch_analysis_idx = -1
    for i in range(detail_idx + 1, len(lines)):
        if batch_analysis in lines[i]:
            batch_analysis_idx = i
            break
    if batch_analysis_idx == -1:
        return f"Error: '{batch_analysis}' section not found in target file {target_md_path}, please ensure the overall format of the target file is correct and use `RunSkillScript` tool again."

    fg_tag = f"<{fg}>"
    fc_tag = f"<{fc}>"
    ck_tag = f"<{ck}>"

    found_fg_idx = -1
    found_fc_idx = -1
    found_ck_idx = -1
    fg_end_idx = batch_analysis_idx
    fc_end_idx = batch_analysis_idx
    ck_end_idx = batch_analysis_idx

    for i in range(detail_idx + 1, batch_analysis_idx):
        if fg_tag in lines[i]:
            found_fg_idx = i
            break

    if found_fg_idx != -1:
        for i in range(found_fg_idx + 1, batch_analysis_idx):
            if re.search(r'<FG-', lines[i]):
                fg_end_idx = i
                break

        for i in range(found_fg_idx + 1, fg_end_idx):
            if fc_tag in lines[i]:
                found_fc_idx = i
                break

        if found_fc_idx != -1:
            for i in range(found_fc_idx + 1, fg_end_idx):
                if re.search(r'<(FG|FC)-', lines[i]):
                    fc_end_idx = i
                    break
            else:
                fc_end_idx = fg_end_idx

            for i in range(found_fc_idx + 1, fc_end_idx):
                if ck_tag in lines[i]:
                    found_ck_idx = i
                    break

            if found_ck_idx != -1:
                for i in range(found_ck_idx + 1, fc_end_idx):
                    if re.search(r'<(FG|FC|CK)-', lines[i]):
                        ck_end_idx = i
                        break
                else:
                    ck_end_idx = fc_end_idx

    insert_lines = ""
    if found_fg_idx != -1:
        if found_fc_idx != -1:
            if found_ck_idx != -1:
                insert_lines = bg_str
                insert_point = ck_end_idx
                lines.insert(insert_point, insert_lines)
            else:
                insert_lines = ck_str + bg_str
                insert_point = fc_end_idx
                lines.insert(insert_point, insert_lines)
        else:
            insert_lines = fc_str + ck_str + bg_str
            insert_point = fg_end_idx
            lines.insert(insert_point, insert_lines)
    else:
        insert_lines = fg_str + fc_str + ck_str + bg_str
        insert_point = batch_analysis_idx
        lines.insert(insert_point, insert_lines)

    if source_file:
        table_start_idx = -1
        table_end_idx = -1
        for i in range(batch_analysis_idx + 1, len(lines)):
            if lines[i].strip().startswith('|'):
                table_start_idx = i
                break

        if table_start_idx != -1:
            table_end_idx = table_start_idx
            for i in range(table_start_idx + 1, len(lines)):
                if lines[i].strip().startswith('|'):
                    table_end_idx = i
                else:
                    break

            data_start_idx = table_start_idx + 2
            found_file_row = False
            default_status = "✅ 完成"

            for i in range(data_start_idx, table_end_idx + 1):
                row = lines[i]
                cols = [c.strip() for c in row.strip().split('|') if c.strip()]
                if len(cols) < 3:
                    continue

                file_col = re.sub(r'</?file>', '', cols[0]).strip()
                if cols[2]:
                    default_status = cols[2]

                if file_col == source_file:
                    found_file_row = True
                    count_match = re.search(r'\d+', cols[1])
                    current_count = int(count_match.group(0)) if count_match else 0
                    cols[1] = str(current_count + 1)
                    lines[i] = f"| {cols[0]} | {cols[1]} | {cols[2]} |\n"
                    break

            if not found_file_row:
                file_cell = f"<file>{source_file}</file>"
                new_row = f"| {file_cell} | 1 | {default_status} |\n"
                lines.insert(table_end_idx + 1, new_row)

    with open(target_md_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)

    return f"Successfully record bug {bg} to file"


def parse_args():
    parser = argparse.ArgumentParser(description="Format a bug report and append it to the target file.")
    parser.add_argument("-FG", required=True, help="Function Group tag, e.g., FG-BASIC-ARITHMETIC")
    parser.add_argument("-FGD", required=True, help="Description of FG")
    parser.add_argument("-FC", required=True, help="Sub-function tag, e.g., FC-SPECIAL-ADD")
    parser.add_argument("-FCD", required=True, help="Description of FC")
    parser.add_argument("-CK", required=True, help="Check point tag, e.g., CK-ADD-ZERO-INPUT")
    parser.add_argument("-CKD", required=True, help="Description of CK")
    parser.add_argument("-BG", required=True, help="Bug tag, e.g., BG-STATIC-001-CARRY-INPUT")
    parser.add_argument("-FILE", required=True, help="Source file path and start, end line numbers, e.g., ALU754_RTL/ALU754.v:13-14")
    parser.add_argument("-BD", required=True, help="Bug description.")
    parser.add_argument("-CL", required=True, help="Bug confidence, e.g., High, Medium, Low(in Chinese)")

    return parser.parse_args()


def main():
    args = parse_args()
    DUT = os.environ.get("DUT")
    OUT = os.environ.get("OUT")

    function_dict = load_or_create_function_dict(DUT, OUT)
    formatted_output = format_bug_report(
        DUT,
        args.FG,
        args.FGD,
        args.FC,
        args.FCD,
        args.CK,
        args.CKD,
        args.BG,
        args.FILE,
        args.BD,
        args.CL,
        function_dict
    )

    if isinstance(formatted_output, str):
        print(formatted_output)
        return

    target_md = os.path.join(project_root, OUT, f'{DUT}_static_bug_analysis.md')
    result = update_target_md(target_md, formatted_output)
    print(result)


if __name__ == '__main__':
    main()
