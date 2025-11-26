#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test cases for utility functions."""

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.util.functions import find_files_by_glob, find_files_by_regex, find_files_by_pattern, render_template_dir
import ucagent.util.functions as fc


def test_find_files_by_glob():
    """Test the find_files_by_glob function."""
    # Define the directory and pattern
    test_dir = os.path.join(current_dir, "../examples")
    pattern = "*.md"
    
    # Call the function to find files
    found_files = find_files_by_glob(test_dir, pattern)

    # Print the found files
    print("Found files matching pattern '{}':".format(pattern))
    for file in found_files:
        print(file)
    print("------------------------")


def test_find_files_by_regex():
    """Test the find_files_by_regex function."""
    # Define the directory and pattern
    test_dir = os.path.join(current_dir, "../examples")
    pattern = r".*\.md$"
    
    # Call the function to find files
    found_files = find_files_by_regex(test_dir, pattern)

    # Print the found files
    print("Found files matching regex '{}':".format(pattern))
    for file in found_files:
        print(file)
    print("------------------------")


def test_find_files_by_pattern():
    """Test the find_files_by_pattern function."""
    # Define the directory and pattern
    test_dir = os.path.join(current_dir, "../examples")
    pattern = "*.md"
    
    # Call the function to find files
    found_files = find_files_by_pattern(test_dir, pattern)

    # Print the found files
    print("Found files matching pattern '{}':".format(pattern))
    for file in found_files:
        print(file)

    pattern = r".*\.md$"
    found_files = find_files_by_pattern(test_dir, pattern)
    print("\nFound files matching regex '{}':".format(pattern))
    for file in found_files:
        print(file)

    pattern = ["*.md", r".*\.md$", "alu.md"]
    found_files = find_files_by_pattern(test_dir, pattern)
    print("\nFound files matching patterns '{}':".format(pattern))
    for file in found_files:
        print(file)
    print("------------------------")


def test_render_template_dir():
    """Test the render_template_dir function."""
    # Define the directory and context
    workspace = os.path.join(current_dir, "../output")
    if not os.path.exists(workspace):
        os.makedirs(workspace)
    template = os.path.join(current_dir, "../ucagent/template/unity_test")
    context = {"DUT": "alu"}

    # Call the function to render templates
    rendered_files = render_template_dir(workspace, template, context)

    # Print the rendered files
    print("Rendered files:")
    for file in rendered_files:
        print(file)
    print("------------------------")



def test_parse_marks_from_file():
    """Test the parse_marks_from_file function."""
    test_file = os.path.join(current_dir, "../ucagent/template/unity_test/{{DUT}}_line_coverage_analysis.md")
    marks = fc.parse_marks_from_file(test_file, "LINE_IGNORE")
    print("Parsed marks from file '{}':".format(test_file))
    print("Marks:", marks)
    print("------------------------")


def test_parse_line_ignore_file():
    """Test the parse_line_ignore_file function."""
    test_file = os.path.join(current_dir, "../ucagent/template/unity_test/tests/{{DUT}}.ignore")
    marks = fc.parse_line_ignore_file(test_file)
    print("Parsed line ignore marks from file '{}':".format(test_file))
    print("Marks:", marks)
    print("------------------------")


def test_parse_un_coverage_json():
    """Test the parse_un_coverage_json function."""
    test_file = "uc_test_report/line_dat/code_coverage.json"
    ignore_list = fc.parse_un_coverage_json(test_file, os.path.abspath(os.path.join(current_dir, "../output")))
    print("Parsed ignore list from coverage JSON file '{}':".format(test_file))
    print("Ignore List:\n%s" % fc.yam_str(ignore_list))
    print("------------------------")


def test_replace_bash_var():
    """Test the replace_bash_var function."""
    template_str = "Hello, $(name: Bob )! Welcome to $( place: Wonderland ). Your score is $(score: 100)."
    data = {
        "name": "Alice",
        "place": "Wonderland"
        # 'score' is intentionally left out to test default value
    }
    result = fc.replace_bash_var(template_str, data)
    print("Original string:", template_str)
    print("Data:", data)
    print("Replaced string:", result)
    print("------------------------")


def test_check_file_block():
    """Test the check_file_block function."""
    # Example usage
    print(fc.check_file_block(
        {"test_function.py": {
            "A": [129, 133], "B": [136, 142] # Example line ranges
        }}, current_dir, lambda x: "usage" in x))
    x = ".mark_function('FC-FUNCTION', 'test_function.py:129-133::test_find_files_by_glob', ['CK-CHECK1', 'CK-CHECK2'])"

def test_description_mark_function_doc():
    print(fc.description_mark_function_doc(
        ["test_function.py:129-133::test_find_files_by_glob", "test_function.py:136-143::test_find_files_by_regex"],
        current_dir,
    ))


def test_check_has_assert_in_tc():
    """Test the check_has_assert_in_tc function."""
    has_assert = fc.check_has_assert_in_tc(current_dir,
        {"tests":{"test_cases": {
            "test_function.py:152-162::test_X":False,
            "test_function.py:162-172::test_sample_function":True
            }
            }
        })
    assert True
    print("Function 'test_sample_function' has assert:", has_assert)
    print("------------------------")


def test_markdown_headers():
    """Test function markdown_headers"""
    test_file = "../ucagent/lang/zh/doc/Guide_Doc/dut_spec_template.md"
    headers = fc.markdown_headers(current_dir, test_file, levels=2)
    print("Markdown headers in file '{}':".format(test_file))
    for header in headers:
        print(header)
    print("------------------------")

def test_markdown_get_miss_headers():
    """Test function markdown_get_miss_headers"""
    target_file = "../ucagent/lang/zh/doc/Guide_Doc/dut_spec_template.md"
    source_file = "../ucagent/lang/zh/doc/Guide_Doc/dut_test_template.md"
    miss_headers, message = fc.markdown_get_miss_headers(current_dir, target_file, source_file, levels=2)
    print("Missed Headers", len(miss_headers))
    print(message)


def test_parse_line_CK_map_file():
    """Test the parse_line_CK_map_file function."""
    test_file = os.path.join("test_data/line_ck_maps.md")
    marks = fc.parse_line_CK_map_file(current_dir, test_file)
    print("Parsed CK marks from file '{}':".format(test_file))
    print("Marks:", marks)
    print("------------------------")

    a, b = fc.get_un_mapped_lines(current_dir, test_file, marks, 3)
    print("Unmapped lines:", a)
    print(b)
    print("------------------------")

if __name__ == "__main__":
    #test_find_files_by_glob()
    #test_find_files_by_regex()
    #test_find_files_by_pattern()
    #test_render_template_dir()
    #test_parse_marks_from_file()
    #test_parse_line_ignore_file()
    #test_parse_un_coverage_json()
    #test_replace_bash_var()
    #test_check_file_block()
    #test_description_mark_function_doc()
    #test_check_has_assert_in_tc()
    #test_markdown_headers()
    #test_markdown_get_miss_headers()
    test_parse_line_CK_map_file()
