#coding=utf-8

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from vagent.util.functions import find_files_by_glob, find_files_by_regex, find_files_by_pattern



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


if __name__ == "__main__":
    test_find_files_by_glob()
    test_find_files_by_regex()
    test_find_files_by_pattern()
