#coding=utf-8

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from vagent.util.functions import parse_nested_keys, get_unity_chip_doc_marks


def test_func_check_points():
    """Test the function points and checkpoints parsing."""
    function_list_file = os.path.join(current_dir, "test_data/dut_bug_analysis.md")
    keynames = ["group", "function", "checkpoint", "bug", "func"]
    prefix   = ["<FG-",  "<FC-",     "<CK-",       "<BUG-", "<TEST-"]
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
    parse()


if __name__ == "__main__":
    test_func_check_points()
