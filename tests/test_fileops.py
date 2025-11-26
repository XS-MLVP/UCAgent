#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import tempfile
import shutil
import unittest

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.tools.fileops import *


class TestFileOpsTools(unittest.TestCase):
    """Test suite for fileops.py tools"""

    def setUp(self):
        """Set up test environment with temporary directory"""
        self.test_dir = tempfile.mkdtemp(prefix="test_fileops_")
        self.workspace = self.test_dir
        
        # Create test directory structure
        os.makedirs(os.path.join(self.test_dir, "subdir"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "nested", "deep"), exist_ok=True)
        
        # Create test files
        self.test_files = {
            "simple.txt": "Line 1\nLine 2\nLine 3\n",
            "empty.txt": "",
            "indented.py": "class TestClass:\n    def method(self):\n        return 42\n    # comment\n",
            "subdir/nested.txt": "Nested file content\nSecond line\n",
            "nested/deep/deep.txt": "Deep nested content\n"
        }
        
        for file_path, content in self.test_files.items():
            full_path = os.path.join(self.test_dir, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
        
        # Create binary test file
        bin_path = os.path.join(self.test_dir, "binary.bin")
        with open(bin_path, 'wb') as f:
            # Write truly binary data that won't be detected as text
            f.write(bytes(range(256)))  # All possible byte values

    def tearDown(self):
        """Clean up test environment"""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_is_file_writeable(self):
        """Test file writeability check function"""
        # Test with no restrictions
        self.assertTrue(is_file_writeable("any/path")[0])
        
        # Test with un_write_dirs restriction
        result, msg = is_file_writeable("restricted/file", un_write_dirs=["restricted"])
        self.assertFalse(result)
        self.assertIn("not allowed to write", msg)
        
        # Test with write_dirs allowlist
        result, msg = is_file_writeable("allowed/file", write_dirs=["allowed"])
        self.assertTrue(result)
        
        result, msg = is_file_writeable("notallowed/file", write_dirs=["allowed"])
        self.assertFalse(result)

    def test_search_text_basic(self):
        """Test basic text search functionality"""
        tool = SearchText(workspace=self.workspace)
        
        # Search for simple text
        result = tool._run(pattern="Line 2", directory="")
        self.assertIn("Found", result)
        self.assertIn("Line 2", result)
        self.assertIn("simple.txt", result)
    
    def test_search_text_regex(self):
        """Test regex search functionality"""
        tool = SearchText(workspace=self.workspace)
        
        # Search with regex
        result = tool._run(pattern="Line [0-9]+", directory="", use_regex=True)
        self.assertIn("Found", result)
        self.assertIn("simple.txt", result)
        
        # Test invalid regex
        result = tool._run(pattern="[invalid", directory="", use_regex=True)
        self.assertIn("Invalid regex pattern", result)

    def test_search_text_case_sensitivity(self):
        """Test case sensitive/insensitive search"""
        tool = SearchText(workspace=self.workspace)
        
        # Case insensitive (default)
        result = tool._run(pattern="line 1", case_sensitive=False)
        self.assertIn("Found", result)
        
        # Case sensitive
        result = tool._run(pattern="line 1", case_sensitive=True)
        self.assertIn("No matches found", result)

    def test_find_files(self):
        """Test file finding functionality"""
        tool = FindFiles(workspace=self.workspace)
        
        # Find all .txt files
        result = tool._run(pattern="*.txt", directory="")
        self.assertIn("Found", result)
        self.assertIn("simple.txt", result)
        self.assertIn("empty.txt", result)
        
        # Find files in specific directory
        result = tool._run(pattern="*.txt", directory="subdir")
        self.assertIn("nested.txt", result)

    def test_path_list(self):
        """Test directory listing functionality"""
        tool = PathList(workspace=self.workspace)
        
        # List all files
        result = tool._run(path=".", depth=-1)
        self.assertIn("Found", result)
        self.assertIn("simple.txt", result)
        self.assertIn("subdir/", result)
        
        # List with depth limit
        result = tool._run(path=".", depth=0)
        self.assertIn("simple.txt", result)
        self.assertNotIn("nested/deep/deep.txt", result)

    def test_read_text_file_basic(self):
        """Test basic text file reading"""
        tool = ReadTextFile(workspace=self.workspace)
        
        # Read entire file
        result = tool._run(path="simple.txt", start=0, count=-1)
        self.assertIn("Read 3/3 lines", result)
        self.assertIn("0: Line 1", result)
        self.assertIn("2: Line 3", result)
        
        # Read partial file
        result = tool._run(path="simple.txt", start=1, count=1)
        self.assertIn("Read 1/3 lines", result)
        self.assertIn("1: Line 2", result)

    def test_read_text_file_edge_cases(self):
        """Test edge cases for text file reading"""
        tool = ReadTextFile(workspace=self.workspace)
        
        # Empty file
        result = tool._run(path="empty.txt", start=0, count=-1)
        self.assertIn("File empty.txt is empty", result)
        
        # Out of range start
        result = tool._run(path="simple.txt", start=10, count=1)
        self.assertIn("out of range", result)
        
        # Negative indexing
        result = tool._run(path="simple.txt", start=-1, count=1)
        self.assertIn("2: Line 3", result)

    def test_read_bin_file(self):
        """Test binary file reading"""
        tool = ReadBinFile(workspace=self.workspace)
        
        result = tool._run(path="binary.bin", start=0, end=-1)
        self.assertIn("Read 256/256 bytes", result)  # Updated to match new binary file size
        self.assertIn("BIN_DATA", result)

    def test_copy_file(self):
        """Test file copying functionality"""
        tool = CopyFile(workspace=self.workspace)
        
        # Copy file
        result = tool._run(source_path="simple.txt", dest_path="copied.txt", overwrite=False)
        self.assertIn("File copied successfully", result)
        
        # Verify copy
        self.assertTrue(os.path.exists(os.path.join(self.workspace, "copied.txt")))
        with open(os.path.join(self.workspace, "copied.txt"), 'r') as f:
            self.assertEqual(f.read(), self.test_files["simple.txt"])

    def test_copy_file_overwrite(self):
        """Test file copying with overwrite"""
        tool = CopyFile(workspace=self.workspace)
        
        # Create destination file first
        with open(os.path.join(self.workspace, "existing.txt"), 'w') as f:
            f.write("existing content")
        
        # Try copy without overwrite (should fail)
        result = tool._run(source_path="simple.txt", dest_path="existing.txt", overwrite=False)
        self.assertIn("already exists", result)
        
        # Copy with overwrite (should succeed)
        result = tool._run(source_path="simple.txt", dest_path="existing.txt", overwrite=True)
        self.assertIn("File copied successfully", result)

    def test_move_file(self):
        """Test file moving functionality"""
        tool = MoveFile(workspace=self.workspace)
        
        # Create temp file to move
        temp_file = os.path.join(self.workspace, "temp_move.txt")
        with open(temp_file, 'w') as f:
            f.write("content to move")
        
        # Move file
        result = tool._run(source_path="temp_move.txt", dest_path="moved.txt", overwrite=False)
        self.assertIn("File moved successfully", result)
        
        # Verify move
        self.assertFalse(os.path.exists(temp_file))
        self.assertTrue(os.path.exists(os.path.join(self.workspace, "moved.txt")))

    def test_delete_file(self):
        """Test file deletion functionality"""
        tool = DeleteFile(workspace=self.workspace)
        
        # Create temp file to delete
        temp_file = os.path.join(self.workspace, "temp_delete.txt")
        with open(temp_file, 'w') as f:
            f.write("content to delete")
        
        # Delete file
        result = tool._run(path="temp_delete.txt", is_dir=False, recursive=False)
        self.assertIn("File temp_delete.txt deleted successfully", result)
        
        # Verify deletion
        self.assertFalse(os.path.exists(temp_file))

    def test_delete_directory(self):
        """Test directory deletion functionality"""
        tool = DeleteFile(workspace=self.workspace)
        
        # Create temp directory
        temp_dir = os.path.join(self.workspace, "temp_dir")
        os.makedirs(temp_dir)
        
        # Delete empty directory
        result = tool._run(path="temp_dir", is_dir=True, recursive=False)
        self.assertIn("Empty directory temp_dir deleted successfully", result)
        
        # Verify deletion
        self.assertFalse(os.path.exists(temp_dir))

    def test_delete_directory_recursive(self):
        """Test recursive directory deletion"""
        tool = DeleteFile(workspace=self.workspace)
        
        # Create temp directory with content
        temp_dir = os.path.join(self.workspace, "temp_dir_recursive")
        os.makedirs(temp_dir)
        with open(os.path.join(temp_dir, "file.txt"), 'w') as f:
            f.write("content")
        
        # Delete recursively
        result = tool._run(path="temp_dir_recursive", is_dir=True, recursive=True)
        self.assertIn("Directory temp_dir_recursive and all its contents deleted successfully", result)
        
        # Verify deletion
        self.assertFalse(os.path.exists(temp_dir))

    def test_create_directory(self):
        """Test directory creation functionality"""
        tool = CreateDirectory(workspace=self.workspace)
        
        # Create simple directory
        result = tool._run(path="new_dir", parents=True, exist_ok=True)
        self.assertIn("Directory new_dir created successfully", result)
        
        # Verify creation
        self.assertTrue(os.path.isdir(os.path.join(self.workspace, "new_dir")))

    def test_create_directory_nested(self):
        """Test nested directory creation"""
        tool = CreateDirectory(workspace=self.workspace)
        
        # Create nested directory
        result = tool._run(path="deeply/nested/new/dir", parents=True, exist_ok=True)
        self.assertIn("Directory deeply/nested/new/dir created successfully", result)
        
        # Verify creation
        self.assertTrue(os.path.isdir(os.path.join(self.workspace, "deeply/nested/new/dir")))

    def test_create_directory_exist_ok(self):
        """Test directory creation with existing directory"""
        tool = CreateDirectory(workspace=self.workspace)
        
        # Create directory first time
        result = tool._run(path="existing_dir", parents=True, exist_ok=True)
        self.assertIn("created successfully", result)
        
        # Try to create again with exist_ok=True
        result = tool._run(path="existing_dir", parents=True, exist_ok=True)
        self.assertIn("already exists", result)
        
        # Try to create again with exist_ok=False
        result = tool._run(path="existing_dir", parents=True, exist_ok=False)
        self.assertIn("already exists", result)

    def test_get_file_info(self):
        """Test file information retrieval"""
        tool = GetFileInfo(workspace=self.workspace)
        
        # Get info for text file
        result = tool._run(path="simple.txt", include_stats=True)
        self.assertIn("Type: File", result)
        self.assertIn("File type: Text", result)
        self.assertIn("Line count: 3", result)
        self.assertIn("Permissions:", result)
        self.assertIn("Modified:", result)

    def test_get_directory_info(self):
        """Test directory information retrieval"""
        tool = GetFileInfo(workspace=self.workspace)
        
        # Get info for directory
        result = tool._run(path="subdir", include_stats=True)
        self.assertIn("Type: Directory", result)
        self.assertIn("Contains:", result)
        self.assertIn("files", result)

    def test_error_handling_nonexistent_file(self):
        """Test error handling for non-existent files"""
        tool = ReadTextFile(workspace=self.workspace)
        
        result = tool._run(path="nonexistent.txt", start=0, count=-1)
        self.assertIn("does not exist", result)

    def test_error_handling_binary_as_text(self):
        """Test error handling when reading binary file as text"""
        tool = ReadTextFile(workspace=self.workspace)
        
        result = tool._run(path="binary.bin", start=0, count=-1)
        self.assertIn("not a text file", result)

    def test_workspace_path_validation(self):
        """Test workspace path validation"""
        tool = ReadTextFile(workspace=self.workspace)
        
        # Try to access file outside workspace (should fail)
        result = tool._run(path="../outside.txt", start=0, count=-1)
        self.assertIn("not within the workspace", result)

    def test_callback_functionality(self):
        """Test callback system"""
        tool = SearchText(workspace=self.workspace)
        
        # Mock callback
        callback_results = []
        def test_callback(success, path, msg):
            callback_results.append((success, path, msg))
        
        tool.append_callback(test_callback)
        
        # Run operation that should trigger callback
        tool._run(pattern="Line 1", directory="")
        
        # Verify callback was called
        self.assertTrue(len(callback_results) > 0)
        self.assertTrue(callback_results[0][0])  # success should be True


class TestBaseReadWrite(unittest.TestCase):
    """Test the BaseReadWrite base class"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_base_")
        
    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_init_base_rw(self):
        """Test base initialization"""
        base = BaseReadWrite()
        base.init_base_rw(self.test_dir)
        
        self.assertEqual(base.workspace, os.path.abspath(self.test_dir))
        self.assertEqual(base.max_read_size, 131072)

    def test_check_file_creation(self):
        """Test file creation in check_file method"""
        base = BaseReadWrite()
        base.init_base_rw(self.test_dir)
        base.create_file = True
        
        # Check non-existent file (should create it)
        success, msg, real_path = base.check_file("new_file.txt")
        self.assertTrue(success)
        self.assertTrue(os.path.exists(real_path))

    def test_check_dir_empty_path(self):
        """Test check_dir with empty path"""
        base = BaseReadWrite()
        base.init_base_rw(self.test_dir)
        
        # Check empty path (should default to current directory)
        success, msg, real_path = base.check_dir("")
        self.assertTrue(success)
        self.assertEqual(real_path, os.path.abspath(self.test_dir))


def run_specific_tests():
    """Run specific tests for debugging"""
    suite = unittest.TestSuite()
    
    # Add specific tests
    suite.addTest(TestFileOpsTools('test_search_text_basic'))
    suite.addTest(TestFileOpsTools('test_read_text_file_basic'))
    suite.addTest(TestFileOpsTools('test_write_text_file_overwrite'))
    suite.addTest(TestFileOpsTools('test_write_text_file_append'))
    suite.addTest(TestFileOpsTools('test_write_text_file_replace_basic'))
    
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)


if __name__ == '__main__':
    # Run all tests
    unittest.main(verbosity=2)
