#coding=utf-8

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.util.functions import parse_nested_keys, nested_keys_as_list, get_unity_chip_doc_marks


def test_func_check_points():
    """Test the function points and checkpoints parsing."""
    function_list_file = os.path.join(current_dir, "test_data/dut_bug_analysis.md")
    keynames = ["group", "function", "checkpoint", "bug", "testcase"]
    prefix   = ["<FG-",  "<FC-",     "<CK-",       "<BG-", "<TC-"]
    subfix   = [">"]* len(prefix)
    # Parse the function points and checkpoints
    def parse():
        keydata = parse_nested_keys(
            function_list_file, keynames, prefix, subfix
        )
        # Print the parsed function points and checkpoints
        print("Parsed file:", function_list_file)
        ret_data, broken_mark = nested_keys_as_list(keydata, "testcase", keynames)
        print("Function points and checkpoints:")
        for item in ret_data:
            print(item)
        if broken_mark:
            print("Broken leaf nodes (potential issues):")
            for b in broken_mark:
                print(b)
    #parse()
    print(get_unity_chip_doc_marks(function_list_file, "TC"))


if __name__ == "__main__":
    test_func_check_points()
