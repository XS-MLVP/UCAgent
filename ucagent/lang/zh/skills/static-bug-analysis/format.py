
import argparse
import re
import json
import os
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../../'))

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
        return [0,f"错误: -FG参数'{fg}'格式无效，应以'FG-'开头,修改标签并重新使用`CallSkillScript`工具。"]
    if fc.split('-')[0] != 'FC':
        return [0,f"错误: -FC参数'{fc}'格式无效，应以'FC-'开头,修改标签并重新使用`CallSkillScript`工具。"]
    if ck.split('-')[0] != 'CK':
        return [0,f"错误: -CK参数'{ck}'格式无效，应以'CK-'开头,修改标签并重新使用`CallSkillScript`工具。"]
    
    if fg not in f_dict:
        return [0,f"错误: -FG参数'{fg}'未在 {DUT}_functions_and_checks.md 中定义, 使用正确的标签并重新使用`CallSkillScript`工具。"]
    
    fg_data = f_dict[fg]
    
    if len(fg_data) < 2 or not isinstance(fg_data[1], dict):
        return [0,f"错误: -FG参数'{fg}'结构无效,使用正确的标签并重新使用`CallSkillScript`工具。"]
    
    fg_description = fg_data[0]
    fg_children = fg_data[1]
    if fc not in fg_children:
        return [0,f"错误: -FC参数'{fc}'未在功能组'{fg}'下找到,使用正确的标签并重新使用`CallSkillScript`工具。"]
    
    fc_data = fg_children[fc]
    # fc_data structure: [description, cks_list]
    if len(fc_data) < 2 or not isinstance(fc_data[1], list):
        return [0,f"错误: -FC参数'{fc}' 结构无效,使用正确的标签并重新使用`CallSkillScript`工具。"]

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
        return [0,f"错误: -CK参数'{ck}' 未在 '{fc}' (位于 '{fg}') 下找到, 使用正确的标签并重新使用`CallSkillScript`工具。"]
        
    return [1,[fg_description, fc_description, ck_description]]

def normalize_file_path(dut, file_path):
    """Normalize file paths to the workspace root under output/."""
    if os.path.isabs(file_path):
        return file_path
    if file_path.startswith('output' + os.sep):
        return os.path.join(project_root, file_path)
    return os.path.join(os.path.join(project_root, f'output/workspace_{dut}'), file_path)

def get_code_snippet(dut, file_path, start_line, end_line, indent_level=0):
    """Reads a snippet of code from a file."""
    # Paths are resolved under output/workspace_ALU754 by default
    abs_path = normalize_file_path(dut, file_path)
    if not os.path.exists(abs_path):
        return f"错误: 未找到文件 {abs_path}, 请使用正确的路径并重新使用`CallSkillScript`工具。"
    
    try:
        with open(abs_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        start_index = start_line - 1
        end_index = end_line
        
        if start_index < 0 or end_index > len(lines):
            return f"错误: 行号 {start_line}-{end_line} 超出文件范围, 请使用正确的行号并重新使用`CallSkillScript`工具。"

        snippet_lines = lines[start_index:end_index]
        
        formatted_snippet = ""
        indent_str = " " * indent_level
        for i, line in enumerate(snippet_lines):
            line_content = line.rstrip()
            # Preserve original indentation of the code line
            formatted_snippet += f"{indent_str}{start_line + i}:  {line_content}"
            if i < len(snippet_lines) - 1:
                formatted_snippet += "\n"

        return formatted_snippet

    except Exception as e:
        return f"读取文件时出错 {abs_path}: {e}"

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
            return f"错误: -FILE 参数格式错误, 应为 '路径:起始行-结束行' 或 '路径:行号', 修改参数并重新使用`CallSkillScript`工具。"
    else:
        return f"错误: -FILE 参数格式错误, 应为 '路径:起始行-结束行' 或 '路径:行号', 修改参数并重新使用`CallSkillScript`工具。"

    fg_desc_str, fc_desc_str, ck_desc_str = descriptions
    code_snippet = get_code_snippet(dut, relative_path, start_line, end_line, indent_level=8)
    
    lang = "verilog"
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
        return f"错误: 目标文件未找到于 {target_md_path}"

    with open(target_md_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    summary_line = formatted_output[0]
    fg_str = formatted_output[1]
    fc_str = formatted_output[2]
    ck_str = formatted_output[3]
    bg_str = formatted_output[4]
    
    summary_idx = -1
    for i, line in enumerate(lines):
        if "潜在Bug汇总" in line:
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
        return f"错误: 在目标文件 {target_md_path} 中未找到 '潜在Bug汇总' 部分, 请确保目标文件整体的格式正确并重新使用`CallSkillScript`工具。"
        
    detail_idx = -1
    for i in range(table_end_idx + 1, len(lines)):
        line = lines[i]
        if "详细分析" in line:
            detail_idx = i
            break    
    if detail_idx == -1:
        return f"错误: 在目标文件 {target_md_path} 中未找到 '详细分析' 部分, 请确保目标文件整体的格式正确并重新使用`CallSkillScript`工具。"

    batch_analysis_idx = -1
    for i in range(detail_idx + 1, len(lines)):
        if "批次分析" in lines[i]:
            batch_analysis_idx = i
            break
    if batch_analysis_idx == -1:
        return f"错误: 在目标文件 {target_md_path} 中未找到 '批次分析' 部分, 请确保目标文件整体的格式正确并重新使用`CallSkillScript`工具。"

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
        
    return f"已将一条Bug记录追加到文件 {target_md_path}, 继续分析潜在Bug直到本RTL源文件分析完毕"

def main():
    parser = argparse.ArgumentParser(description="格式化一个Bug报告并追加到目标Markdown文件。")
    parser.add_argument("-DUT", required=True, help="待测文件的名称")
    parser.add_argument("-TARGET_MD", required=True, help="目标文件的路径，用于直接追加结果")
    parser.add_argument("-FG", required=True, help="功能组标签, 例如, FG-BASIC-ARITHMETIC")
    parser.add_argument("-FC", required=True, help="子功能标签, 例如, FC-SPECIAL-ADD")
    parser.add_argument("-CK", required=True, help="检测点标签, 例如, CK-ADD-ZERO-INPUT")
    parser.add_argument("-BG", required=True, help="Bug标签, 例如, BG-STATIC-001-CARRY-INPUT")
    parser.add_argument("-FILE", required=True, help="源码文件路径以及起始,结束行号, 例如 ALU754_RTL/ALU754.v:13-14")
    parser.add_argument("-Bug_DESCRIPTION", required=True, help="Bug的描述。")
    parser.add_argument("-CONFIDENCE", required=True, help="Bug置信度，例如 高、中、低")
    
    args = parser.parse_args()

    # Path to the function dictionary, relative to project root
    function_dict_file = os.path.join(os.path.join(project_root, f'output/workspace_{args.DUT}'), f'unity_test/{args.DUT}_functions_and_checks.md')
    if not os.path.exists(function_dict_file):
        print(f"错误: 未找到 {function_dict_file} 文件, 请使用正确的路径并重新使用`CallSkillScript`工具。")
        return
        
    function_dict = parse_md_file(function_dict_file)
    
    formatted_output = format_bug_report(
        args.DUT,
        args.FG,
        args.FC,
        args.CK,
        args.BG,
        args.FILE,
        args.Bug_DESCRIPTION,
        args.CONFIDENCE,
        function_dict
    )
    
    if isinstance(formatted_output, str):
        print(formatted_output)
        return

    result = update_target_md(args.TARGET_MD, formatted_output, args.FG, args.FC, args.CK, args.BG)
    print(result)

if __name__ == '__main__':
    main()
