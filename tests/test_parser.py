#coding=utf-8

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from vagent.util.functions import parse_nested_keys, get_unity_chip_doc_marks


def test_func_check_points():
    """Test the function points and checkpoints parsing."""
    function_list_file = os.path.join(current_dir, "../examples/template/functions_and_checks.md")
    keynames = ["group", "function", "checkpoint", "bug_rate"]
    prefix   = ["<FG-",  "<FC-",     "<CK-",       "<BUG-RATE-"]
    subfix   = [">"]* len(prefix)
    # Parse the function points and checkpoints
    def parse():
        keydata = parse_nested_keys(
            function_list_file, keynames, prefix, subfix
        )
        # Print the parsed function points and checkpoints
        print("Parsed file:", function_list_file)
        def print_dict(d, indent=0):
            for key, value in d.items():
                if isinstance(value, dict):
                    print(" " * indent + f"{key}:")
                    print_dict(value, indent + 2)
                else:
                    print(" " * indent + f"{key}: {value}")
        print_dict(keydata)
        print(get_unity_chip_doc_marks(function_list_file))
    parse()
    function_list_file = os.path.join(current_dir, "../examples/template/bug_func_and_checks.md")
    parse()


def test_load_json():
    """Test loading JSON data from a file."""
    import json
    json_file = os.path.join(current_dir, "../examples/template/toffee_report.json")
    with open(json_file, 'r') as f:
        data = json.load(f)
        print("Loaded JSON data from:", json_file)
        print("Data keys:", list(data.keys()))
        print("Data content:", data)


if __name__ == "__main__":
    test_func_check_points()
