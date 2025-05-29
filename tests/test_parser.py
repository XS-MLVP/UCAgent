#coding=utf-8

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from vagent.tools.testops import parse_function_points_and_checkpoints


def test_func_check_points():
    """Test the function points and checkpoints parsing."""
    function_list_file = os.path.join(current_dir, "../examples/template/functions_and_checks.md")
    func_prefix = "<FC-"
    func_subfix = ">"
    check_prefix = "<CK-"
    check_subfix = ">"

    # Parse the function points and checkpoints
    def parse():
        function_points = parse_function_points_and_checkpoints(
            function_list_file, func_prefix, func_subfix, check_prefix, check_subfix
        )
        # Print the parsed function points and checkpoints
        print("Parsed file:", function_list_file)
        for func, details in function_points.items():
            print(f"Function: {func}, Line: {details['line']}")
            for check, line in details["checkpoints"].items():
                print(f"  Checkpoint: {check}, Line: {line}")
    parse()
    function_list_file = os.path.join(current_dir, "../examples/template/bug_func_and_checks.md")
    parse()

if __name__ == "__main__":
    test_func_check_points()
