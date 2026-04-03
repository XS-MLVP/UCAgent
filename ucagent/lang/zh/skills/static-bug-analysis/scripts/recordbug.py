import argparse
import re
import os

project_root = os.getcwd()
potential_bug_summary = "潜在Bug汇总"
detail_analysis = "详细分析"
batch_analysis = "批次分析"

def parse_md_file(file_path):
    """
    Parse {DUT}_functions_and_checks.md to extract a hierarchical structure of functions.
    Args:
        file_path (str): The path of {DUT}_functions_and_checks.md.
    Returns:
        dict: A dictionary.
    """
    hierarchy = {}
    fg_stack = []
    fc_stack = []
    last_header = ""

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            header_match = re.match(r'^(#+)\s+(.*)', line)
            if header_match:
                last_header = header_match.group(2).strip()
                continue
            fg_match = re.search(r'<FG-([^>]+)>', line)
            fc_match = re.search(r'<FC-([^>]+)>', line)
            ck_match = re.search(r'<CK-([^>]+)>', line)
            if fg_match:
                fg_name = f"FG-{fg_match.group(1)}"
                description = last_header
                new_fg = {fg_name: [description, {}]}
                if not fg_stack or '#' not in line:
                    fg_stack = []
                    fc_stack = []
                    hierarchy.update(new_fg)
                else:
                    parent_fg_dict = fg_stack[-1]
                    parent_fg_children_dict = list(parent_fg_dict.values())[0][1]
                    parent_fg_children_dict.update(new_fg)
                fg_stack.append(new_fg)
                fc_stack = [] # Reset fc_stack for new FG
                last_header = "" # Consume header
            elif fc_match and fg_stack:
                fc_name = f"FC-{fc_match.group(1)}"
                description = last_header
                current_fg_children_dict = list(fg_stack[-1].values())[0][1]
                new_fc = {fc_name: [description, []]}
                current_fg_children_dict.update(new_fc)
                fc_stack.append(new_fc)
                last_header = "" # Consume header
            elif ck_match:
                ck_name = f"CK-{ck_match.group(1)}"
                description_part = line.split('：')[0]
                description = re.sub(r'<[^>]+>', '', description_part).replace('-', '').strip()       
                if fc_stack:
                    current_fc_children_list = list(fc_stack[-1].values())[0][1]
                    new_ck = {ck_name: [description]}
                    current_fc_children_list.append(new_ck)
    return hierarchy

def validate_hierarchy(DUT, f_dict, fg, fc, ck):
    """
    Validates that FG, FC, and CK exist and are properly nested in the feature dictionary.
    """
    if fg.split('-')[0] != 'FG':
        return [0,f"Error: -FG parameter '{fg}' format invalid, should start with 'FG-'. Modify the tag and use `RunSkillScript` tool again."]
    if fc.split('-')[0] != 'FC':
        return [0,f"Error: -FC parameter '{fc}' format invalid, should start with 'FC-'. Modify the tag and use `RunSkillScript` tool again."]
    if ck.split('-')[0] != 'CK':
        return [0,f"Error: -CK parameter '{ck}' format invalid, should start with 'CK-'. Modify the tag and use `RunSkillScript` tool again."]
    
    if fg not in f_dict:
        return [0,f"Error: -FG parameter '{fg}' is not defined in {DUT}_functions_and_checks.md. Use the correct tag and use `RunSkillScript` tool again."]
    
    fg_data = f_dict[fg]
    
    if len(fg_data) < 2 or not isinstance(fg_data[1], dict):
        return [0,f"Error: -FG parameter '{fg}' structure invalid. Use the correct tag and use `RunSkillScript` tool again."]
    
    fg_description = fg_data[0]
    fg_children = fg_data[1]
    if fc not in fg_children:
        return [0,f"Error: -FC parameter '{fc}' not found under function group '{fg}'. Use the correct tag and use `RunSkillScript` tool again."]
    
    fc_data = fg_children[fc]
    # fc_data structure: [description, cks_list]
    if len(fc_data) < 2 or not isinstance(fc_data[1], list):
        return [0,f"Error: -FC parameter '{fc}' structure invalid. Use the correct tag and use `RunSkillScript` tool again."]

    fc_description = fc_data[0]    
    cks_list = fc_data[1]
    ck_found = False
    ck_description = ""
    for item in cks_list:
        if ck in item:
            ck_found = True
            ck_description = item[ck][0]
            break
            
    if not ck_found:
        return [0,f"Error: -CK parameter '{ck}' not found under '{fc}' (in '{fg}'). Use the correct tag and use `RunSkillScript` tool again."]
        
    return [1,[fg_description, fc_description, ck_description]]

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
            # Preserve original indentation of the code line
            formatted_snippet += f"{indent_str}{start_line + i}:  {line_content}"
            if i < len(snippet_lines) - 1:
                formatted_snippet += "\n"

        return [1, formatted_snippet]

    except Exception as e:
        return [0, f"Error reading file {abs_path}: {e}"]

def format_bug_report(dut, fg, fc, ck, bg, file_info, bug_description, confidence, function_dict):
    """
    Generates a formatted bug report in Markdown.
    """
    # Validate Hierarchy first
    correct, descriptions = validate_hierarchy(dut, function_dict, fg, fc, ck)
    if not correct:
        return descriptions

    relative_path = ""
    start_line = 0
    end_line = 0
    if isinstance(file_info, str):
        file_match = re.search(r'([^:]+):(\d+)-?(\d*)', file_info)
        if file_match:
            relative_path, start_str, end_str = file_match.groups()
            start_line = int(start_str)
            end_line = int(end_str) if end_str else start_line
        else:
            return f"Error: -FILE parameter format invalid, should be 'path:start_line-end_line' or 'path:line_number', modify the parameter and use `RunSkillScript` tool again."
    else:
        return f"Error: -FILE parameter format invalid, should be 'path:start_line-end_line' or 'path:line_number', modify the parameter and use `RunSkillScript` tool again."

    fg_desc_str, fc_desc_str, ck_desc_str = descriptions
    correct, code_snippet = get_code_snippet(relative_path, start_line, end_line, indent_level=8)
    if not correct:
        return code_snippet

    lang = ""
    if relative_path.split('.')[-1] in ['v', 'sv']:
        lang = "verilog"
    elif relative_path.split('.')[-1] in ['scala']:
        lang = "scala"
    file_tag = f"<FILE-{relative_path}:{start_line}-{end_line}>"

    output = [f"| {bg.split('-')[2]} | {bg} | {fg}/{fc}/{ck} | {bug_description} | {confidence} | {relative_path} | LINK-BUG-[BG-TBD] |\n",\
              f"### <{fg}> {fg_desc_str}\n",\
              f"#### <{fc}> {fc_desc_str}\n",\
              f"##### <{ck}> {ck_desc_str}\n",\
              f"  - <{bg}> {bug_description}\n"\
              f"    - <LINK-BUG-[BG-TBD]>\n"\
              f"      - {file_tag}\n"\
              f"        ```{lang}\n"\
              f"{code_snippet}\n"\
              f"        ```\n"]

    return output

def update_target_md(target_md_path, formatted_output, fg, fc, ck, bg):
    if not os.path.exists(target_md_path):
        return f"Error: Target file not found at {target_md_path}"

    with open(target_md_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    summary_line = formatted_output[0]
    fg_str = formatted_output[1]
    fc_str = formatted_output[2]
    ck_str = formatted_output[3]
    bg_str = formatted_output[4]
    
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

    found_fg = False
    found_fc = False
    found_ck = False
    
    found_fg_idx = -1
    found_fc_idx = -1
    found_ck_idx = -1

    for i in range(detail_idx, len(lines)):
        if fg_tag in lines[i]:
            found_fg = True
            found_fg_idx = i
        if found_fg and fc_tag in lines[i]:
            found_fc = True
            found_fc_idx = i
        if found_fc and ck_tag in lines[i]:
            found_ck = True
            found_ck_idx = i
            break

    insert_lines = ""
    if found_fg:
        if found_fc:
            if found_ck:
                insert_lines = bg_str
                insert_point = batch_analysis_idx
                for i in range(found_ck_idx + 1, batch_analysis_idx):
                    if re.search(r'<(FG|FC|CK)-', lines[i]):
                        insert_point = i
                        break
                lines.insert(insert_point, insert_lines)
            else:
                insert_lines = ck_str + bg_str
                insert_point = batch_analysis_idx
                for i in range(found_fc_idx + 1, batch_analysis_idx):
                    if re.search(r'<(FG|FC)-', lines[i]):
                        insert_point = i
                        break
                lines.insert(insert_point, insert_lines)
        else:
            insert_lines = fc_str + ck_str + bg_str
            insert_point = batch_analysis_idx
            for i in range(found_fg_idx + 1, batch_analysis_idx):
                if re.search(r'<FG-', lines[i]):
                    insert_point = i
                    break
            lines.insert(insert_point, insert_lines)
    else:
        insert_lines = fg_str + fc_str + ck_str + bg_str
        insert_point = batch_analysis_idx
        lines.insert(insert_point, insert_lines)

    with open(target_md_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
        
    return f"Successfully appended a bug record to file {target_md_path}, continue analyzing potential bugs until the current source file is fully analyzed."

def parse_args():
    parser = argparse.ArgumentParser(description="Format a bug report and append it to the target file.")
    parser.add_argument("-FG", required=True, help="Function Group tag, e.g., FG-BASIC-ARITHMETIC")
    parser.add_argument("-FC", required=True, help="Sub-function tag, e.g., FC-SPECIAL-ADD")
    parser.add_argument("-CK", required=True, help="Check point tag, e.g., CK-ADD-ZERO-INPUT")
    parser.add_argument("-BG", required=True, help="Bug tag, e.g., BG-STATIC-001-CARRY-INPUT")
    parser.add_argument("-FILE", required=True, help="Source file path and start, end line numbers, e.g., ALU754_RTL/ALU754.v:13-14")
    parser.add_argument("-BD", required=True, help="Bug description.")
    parser.add_argument("-CL", required=True, help="Bug confidence, e.g., High, Medium, Low(in Chinese)")
    
    return parser.parse_args()


def main():
    args = parse_args()
    DUT = os.environ.get("DUT")
    OUT = os.environ.get("OUT")

    function_dict_file = os.path.join(project_root, OUT, f'{DUT}_functions_and_checks.md')
    function_dict = parse_md_file(function_dict_file) 
    formatted_output = format_bug_report(
        DUT,
        args.FG,
        args.FC,
        args.CK,
        args.BG,
        args.FILE,
        args.BD,
        args.CL,
        function_dict
    )
    
    if isinstance(formatted_output, str):
        print(formatted_output)
        return

    target_md=os.path.join(project_root, OUT, f'{DUT}_static_bug_analysis.md')
    result = update_target_md(target_md, formatted_output, args.FG, args.FC, args.CK, args.BG)
    print(result)

if __name__ == '__main__':
    main()
