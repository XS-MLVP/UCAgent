import argparse
import re
import os

project_root = os.getcwd()

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

def generate_templates(DUT, OUT, function_dict):
    out_dir = os.path.join(project_root, OUT, 'tests')
    os.makedirs(out_dir, exist_ok=True)
    
    for fg_name, fg_val in function_dict.items():
        # if fg_name == "FG-API":
        #     continue
        
        fg_desc, fc_dict = fg_val[0], fg_val[1]
        
        fg_suffix = fg_name.split('-', 1)[1].lower().replace('-', '_') if '-' in fg_name else fg_name.lower()
        file_name = f"test_{DUT}_{fg_suffix}.py"
        file_path = os.path.join(out_dir, file_name)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            template = f'''import pytest
from {DUT}_api import *\n'''
            for fc_name, fc_val in fc_dict.items():
                fc_desc, ck_list = fc_val[0], fc_val[1]
                
                for ck_item in ck_list:
                    ck_name = list(ck_item.keys())[0]
                    ck_desc = ck_item[ck_name][0]
                    
                    ck_suffix = ck_name.split('-', 1)[1].lower().replace('-', '_') if '-' in ck_name else ck_name.lower()
                    func_name = f"test_{ck_suffix}"
                    
                    template += f'''def {func_name}(env):
    """测试 {ck_desc}
    
    测试目标:

    测试场景:

    预期结果:

    """

    env.dut.fc_cover["{fg_name}"].mark_function("{fc_name}", {func_name}, ["{ck_name}"])

    # TASK: 实现 {ck_desc} 测试逻辑

    assert False, "Not implemented"\n
'''
            f.write(template + '\n')

def main():
    DUT = os.environ.get("DUT")
    OUT = os.environ.get("OUT")

    function_dict_file = os.path.join(project_root, OUT, f'{DUT}_functions_and_checks.md')
    if not os.path.exists(function_dict_file):
        print(f"File not found: {function_dict_file}")
        return

    function_dict = parse_md_file(function_dict_file) 
    generate_templates(DUT, OUT, function_dict)
    print("Test templates generated successfully, use Tool `Complete` to push stage.")

if __name__ == '__main__':
    main()
