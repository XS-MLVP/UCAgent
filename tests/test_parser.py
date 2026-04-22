#coding=utf-8

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.util.functions import parse_nested_keys, nested_keys_as_list, get_unity_chip_doc_marks, yam_str, merge_file_blocks


def test_func_check_points(tfile=None):
    """Test the function points and checkpoints parsing."""
    function_list_file = tfile or os.path.join(current_dir, "test_data/dut_bug_analysis.md")
    a, b = get_unity_chip_doc_marks(function_list_file, "CK", return_line_block=True)
    b = [{k:v} for k, v in b.items()]
    print(yam_str(merge_file_blocks(b)))


if __name__ == "__main__":
    tfile = None
    if len(sys.argv) > 1:
        tfile = sys.argv[1]
    test_func_check_points(tfile)
