#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Performance and stress tests for fileops.py tools
"""

import os
import sys
import tempfile
import shutil
import time
import unittest
from pathlib import Path

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from vagent.tools.fileops import (
    SearchText, FindFiles, PathList, ReadTextFile, 
    WriteToFile, TextFileReplace, CopyFile
)


class TestFileOpsPerformance(unittest.TestCase):
    """Performance tests for fileops.py tools"""

    def setUp(self):
        """Set up test environment"""
        self.test_dir = tempfile.mkdtemp(prefix="test_fileops_perf_")
        self.workspace = self.test_dir

    def tearDown(self):
        """Clean up test environment"""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_large_file_read_performance(self):
        """Test reading large text files"""
        print("\n=== Testing large file read performance ===")
        
        # Create a smaller test file to avoid character limits
        large_file_path = os.path.join(self.test_dir, "large_file.txt")
        lines_count = 1000  # Reduced to avoid exceeding character limit
        with open(large_file_path, 'w') as f:
            for i in range(lines_count):
                f.write(f"This is line {i:06d}\n")  # Shorter lines

        tool = ReadTextFile(workspace=self.workspace)
        
        # Test reading entire file
        start_time = time.time()
        result = tool._run(path="large_file.txt", start=0, count=-1)
        read_time = time.time() - start_time
        
        print(f"Read {lines_count} lines in {read_time:.3f} seconds")
        print(f"Performance: {lines_count/read_time:.0f} lines/second")
        
        self.assertIn(f"Read {lines_count}/{lines_count} lines", result)
        self.assertLess(read_time, 5.0, "Reading should complete within 5 seconds")

    def test_search_performance_large_files(self):
        """Test search performance on large files"""
        print("\n=== Testing search performance on large files ===")
        
        # Create multiple files with searchable content
        num_files = 20
        lines_per_file = 1000
        
        for i in range(num_files):
            file_path = os.path.join(self.test_dir, f"file_{i:03d}.txt")
            with open(file_path, 'w') as f:
                for j in range(lines_per_file):
                    if j % 100 == 0:  # Add searchable content every 100 lines
                        f.write(f"SPECIAL_PATTERN in file {i} line {j}\n")
                    else:
                        f.write(f"Normal content line {j} in file {i}\n")

        tool = SearchText(workspace=self.workspace)
        
        # Test search performance
        start_time = time.time()
        result = tool._run(pattern="SPECIAL_PATTERN", directory="", max_match_files=num_files)
        search_time = time.time() - start_time
        
        print(f"Searched {num_files} files with {lines_per_file} lines each in {search_time:.3f} seconds")
        print(f"Total lines processed: {num_files * lines_per_file}")
        
        self.assertIn("Found", result)
        self.assertLess(search_time, 10.0, "Search should complete within 10 seconds")

    def test_regex_search_performance(self):
        """Test regex search performance"""
        print("\n=== Testing regex search performance ===")
        
        # Create file with various patterns
        file_path = os.path.join(self.test_dir, "regex_test.txt")
        with open(file_path, 'w') as f:
            for i in range(10000):
                f.write(f"email{i}@example.com line {i}\n")
                f.write(f"phone: +1-{i:03d}-{i:03d}-{i:04d}\n")
                f.write(f"date: 2024-{(i%12)+1:02d}-{(i%28)+1:02d}\n")
                f.write(f"normal content line {i}\n")

        tool = SearchText(workspace=self.workspace)
        
        # Test complex regex pattern
        start_time = time.time()
        result = tool._run(
            pattern=r"email\d+@\w+\.\w+", 
            directory="", 
            use_regex=True,
            max_match_lines=50
        )
        regex_time = time.time() - start_time
        
        print(f"Regex search completed in {regex_time:.3f} seconds")
        
        self.assertIn("Found", result)
        self.assertLess(regex_time, 5.0, "Regex search should complete within 5 seconds")

    def test_directory_listing_performance(self):
        """Test directory listing performance with many files"""
        print("\n=== Testing directory listing performance ===")
        
        # Create many directories and files
        num_dirs = 50
        files_per_dir = 100
        
        for i in range(num_dirs):
            dir_path = os.path.join(self.test_dir, f"dir_{i:03d}")
            os.makedirs(dir_path)
            for j in range(files_per_dir):
                file_path = os.path.join(dir_path, f"file_{j:03d}.txt")
                with open(file_path, 'w') as f:
                    f.write(f"Content of file {j} in directory {i}\n")

        tool = PathList(workspace=self.workspace)
        
        # Test listing performance
        start_time = time.time()
        result = tool._run(path=".", depth=-1)
        list_time = time.time() - start_time
        
        total_files = num_dirs * files_per_dir
        print(f"Listed {total_files} files in {num_dirs} directories in {list_time:.3f} seconds")
        
        self.assertIn("Found", result)
        self.assertLess(list_time, 10.0, "Directory listing should complete within 10 seconds")

    def test_file_operations_batch_performance(self):
        """Test batch file operations performance"""
        print("\n=== Testing batch file operations performance ===")
        
        # Create source files
        num_files = 200
        for i in range(num_files):
            file_path = os.path.join(self.test_dir, f"source_{i:03d}.txt")
            with open(file_path, 'w') as f:
                f.write(f"Content of source file {i}\n" * 50)  # 50 lines each

        copy_tool = CopyFile(workspace=self.workspace)
        write_tool = WriteToFile(workspace=self.workspace)
        
        # Test copying files
        start_time = time.time()
        for i in range(num_files):
            copy_tool._run(
                source_path=f"source_{i:03d}.txt",
                dest_path=f"copy_{i:03d}.txt",
                overwrite=True
            )
        copy_time = time.time() - start_time
        
        print(f"Copied {num_files} files in {copy_time:.3f} seconds")
        print(f"Performance: {num_files/copy_time:.1f} files/second")
        
        # Test writing files
        content = "New content\n" * 20
        start_time = time.time()
        for i in range(100):  # Fewer writes as they're more expensive
            write_tool._run(path=f"new_{i:03d}.txt", data=content)
        write_time = time.time() - start_time
        
        print(f"Created 100 new files in {write_time:.3f} seconds")
        
        self.assertLess(copy_time, 30.0, "Copying should complete within 30 seconds")
        self.assertLess(write_time, 10.0, "Writing should complete within 10 seconds")

    def test_text_replacement_performance(self):
        """Test text replacement performance on large files"""
        print("\n=== Testing text replacement performance ===")
        
        # Create a large file
        file_path = os.path.join(self.test_dir, "large_replace_file.txt")
        lines_count = 10000
        with open(file_path, 'w') as f:
            for i in range(lines_count):
                f.write(f"Line {i:05d}: This is original content\n")

        tool = TextFileReplace(workspace=self.workspace)
        
        # Test multiple replacements
        start_time = time.time()
        
        # Replace content at different positions
        positions = [100, 2000, 5000, 8000]
        for pos in positions:
            tool._run(
                path="large_replace_file.txt",
                start=pos,
                count=1,
                data=f"REPLACED LINE AT POSITION {pos}"
            )
        
        replace_time = time.time() - start_time
        
        print(f"Performed 4 replacements in {lines_count}-line file in {replace_time:.3f} seconds")
        
        # Verify replacements
        with open(file_path, 'r') as f:
            content = f.read()
            for pos in positions:
                self.assertIn(f"REPLACED LINE AT POSITION {pos}", content)
        
        self.assertLess(replace_time, 5.0, "Replacements should complete within 5 seconds")

    def test_memory_usage_large_operations(self):
        """Test memory usage with large operations"""
        print("\n=== Testing memory usage with large operations ===")
        
        # Create a very large file (about 10MB)
        large_file = os.path.join(self.test_dir, "huge_file.txt")
        with open(large_file, 'w') as f:
            for i in range(500000):  # 500K lines
                f.write(f"Line {i:06d}: Some content to make the line longer and test memory usage\n")

        file_size = os.path.getsize(large_file)
        print(f"Created test file of size: {file_size / (1024*1024):.1f} MB")

        # Test reading in chunks to avoid memory issues
        tool = ReadTextFile(workspace=self.workspace, max_read_size=1024*1024)  # 1MB limit
        
        # Try to read a large portion (should hit size limit)
        result = tool._run(path="huge_file.txt", start=0, count=100000)
        self.assertIn("exceeds the maximum read size", result)
        
        # Read smaller chunks (should work)
        result = tool._run(path="huge_file.txt", start=0, count=1000)
        self.assertIn("Read 1000/500000 lines", result)
        
        print("Memory usage test completed - size limits working correctly")


def run_performance_tests():
    """Run performance tests individually with timing"""
    suite = unittest.TestSuite()
    
    # Add performance tests
    suite.addTest(TestFileOpsPerformance('test_large_file_read_performance'))
    suite.addTest(TestFileOpsPerformance('test_search_performance_large_files'))
    suite.addTest(TestFileOpsPerformance('test_regex_search_performance'))
    suite.addTest(TestFileOpsPerformance('test_directory_listing_performance'))
    suite.addTest(TestFileOpsPerformance('test_file_operations_batch_performance'))
    suite.addTest(TestFileOpsPerformance('test_text_replacement_performance'))
    suite.addTest(TestFileOpsPerformance('test_memory_usage_large_operations'))
    
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)


if __name__ == '__main__':
    print("Running FileOps Performance Tests...")
    print("=" * 60)
    
    start_time = time.time()
    result = run_performance_tests()
    total_time = time.time() - start_time
    
    print("=" * 60)
    print(f"Performance tests completed in {total_time:.2f} seconds")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
