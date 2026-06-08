import argparse
import re
import os

project_root = os.getcwd()


def str_remove_blank(text):
    return re.sub(r"\s+", "", text)


def str_replace_to(text, old_list, new_str):
    for old in old_list:
        text = text.replace(old, new_str)
    return text


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
    """Parse nested FG/FC/CK tags from a markdown file."""
    if ignore_chars is None:
        ignore_chars = ["<", ">"]
    assert os.path.exists(target_file), f"File {target_file} does not exist."
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
        for index, raw_line in enumerate(f.readlines(), start=1):
            line = str_remove_blank(raw_line.strip())
            for i, key in enumerate(keyname_list):
                prefix = prefix_list[i]
                suffix = suffix_list[i]
                pre_key = keyname_list[i - 1] if i > 0 else None
                pre_prefix = prefix_list[i - 1] if i > 0 else None
                if prefix not in line:
                    continue

                current_key = str_replace_to(get_sub_str(line, prefix, suffix), ignore_chars, "")
                parent_node, next_key = get_parent_node(i)
                if parent_node is None:
                    raise ValueError(
                        f"At line ({index}): Found {key} tag '{prefix}' but its parent {pre_key} "
                        f"tag '{pre_prefix}' was not found in previous lines."
                    )
                if current_key in parent_node:
                    raise ValueError(f"At line ({index}): '{current_key}' is defined multiple times.")

                parent_node[current_key] = {"line": index}
                if next_key is not None:
                    parent_node[current_key][next_key] = {}
                pre_values[i] = parent_node[current_key]

    return key_dict

def parse_function_md(file_path):
    """
    Parse {DUT}_functions_and_checks.md to extract FG/FC/CK hierarchy only.
    Args:
        file_path (str): The path of {DUT}_functions_and_checks.md.
    Returns:
        dict: A nested dict with FG -> FC -> CK structure.
    """
    keynames = ["FG", "FC", "CK"]
    prefixes = ["<FG-", "<FC-", "<CK-"]
    suffixes = [">"] * len(prefixes)
    raw_data = parse_nested_keys(file_path, keynames, prefixes, suffixes)

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


def generate_templates(DUT, OUT, function_dict):
    out_dir = os.path.join(project_root, OUT, 'tests')
    os.makedirs(out_dir, exist_ok=True)
    
    for fg_name, fc_dict in function_dict.items():
        # if fg_name == "FG-API":
        #     continue

        fg_suffix = fg_name.split('-', 1)[1].lower().replace('-', '_') if '-' in fg_name else fg_name.lower()
        file_name = f"test_{DUT}_{fg_suffix}.py"
        file_path = os.path.join(out_dir, file_name)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            template = f'''import pytest
from {DUT}_api import *\n'''
            for fc_name, ck_dict in fc_dict.items():
                for ck_name in ck_dict.keys():
                    ck_suffix = ck_name.split('-', 1)[1].lower().replace('-', '_') if '-' in ck_name else ck_name.lower()
                    func_name = f"test_{ck_suffix}"
                    
                    template += f'''def {func_name}(env):
    env.dut.fc_cover["{fg_name}"].mark_function("{fc_name}", {func_name}, ["{ck_name}"])

    # TASK: 实现 {ck_name} 测试逻辑
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

    function_dict = parse_function_md(function_dict_file)
    generate_templates(DUT, OUT, function_dict)
    print("Test templates generated successfully, use Tool `Complete` to push stage.")

if __name__ == '__main__':
    main()
