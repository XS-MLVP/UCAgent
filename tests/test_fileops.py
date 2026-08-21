#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import tempfile
import shutil
import unittest
import hashlib
import asyncio
import threading
from unittest.mock import patch

from pydantic import ValidationError

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.tools.fileops import *
from ucagent.tools import DeleteTextLines as ExportedDeleteTextLines
from ucagent.tools.uctool import to_fastmcp


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

    def test_is_file_writeable_uses_directory_boundaries(self):
        self.assertTrue(is_file_writeable("out/file.txt", write_dirs=["out"])[0])
        self.assertFalse(is_file_writeable("out-other/file.txt", write_dirs=["out"])[0])
        self.assertFalse(is_file_writeable("out/../../outside.txt", write_dirs=["out"])[0])
        self.assertFalse(is_file_writeable("/tmp/out/file.txt", write_dirs=["out"])[0])
        self.assertFalse(is_file_writeable("out/file.txt", write_dirs=[])[0])

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

    def test_search_text_preserves_indent_and_returns_context(self):
        result = SearchText(workspace=self.workspace)._run(
            pattern="return 42",
            directory="indented.py",
            context_before=1,
            context_after=1,
        )

        self.assertIn("Line 2 (context):     def method", result)
        self.assertIn("Line 3:         return 42", result)
        self.assertIn("Line 4 (context):     # comment", result)

    def test_search_text_bounds_regex_execution_time(self):
        target = os.path.join(self.workspace, "regex-timeout.txt")
        with open(target, "w", encoding="utf-8") as file_obj:
            file_obj.write("a" * 20000 + "!\n")

        result = SearchText(workspace=self.workspace)._run(
            pattern="(a|aa)+$",
            directory="regex-timeout.txt",
            use_regex=True,
            regex_timeout_ms=1,
        )

        self.assertIn("Regular expression timed out", result)

    def test_search_text_reports_missing_regex_dependency(self):
        with patch("ucagent.tools.fileops.regex_lib", None):
            result = SearchText(workspace=self.workspace)._run(
                pattern="Line.*",
                directory="simple.txt",
                use_regex=True,
            )

        self.assertIn("requires the 'regex' package", result)

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
        result = tool._run(path="simple.txt", start=1, count=-1)
        self.assertIn("Read 3/3 lines", result)
        self.assertIn("1: Line 1", result)
        self.assertIn("3: Line 3", result)
        
        # Read partial file
        result = tool._run(path="simple.txt", start=2, count=1)
        self.assertIn("Read 1/3 lines", result)
        self.assertIn("2: Line 2", result)
        self.assertIn("SHA256:", result)

    def test_read_text_file_can_return_reusable_raw_text(self):
        result = ReadTextFile(workspace=self.workspace)._run(
            path="indented.py",
            start=2,
            count=2,
            include_line_numbers=False,
        )

        self.assertIn("    def method(self):\n        return 42\n", result)
        self.assertNotIn("2:     def method", result)

    def test_read_text_file_structured_output_has_raw_text_and_metadata(self):
        result = ReadTextFile(workspace=self.workspace)._run(
            path="indented.py",
            start=2,
            count=2,
            structured_output=True,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["start_line"], 2)
        self.assertEqual(result["end_line"], 3)
        self.assertEqual(
            result["content"], "    def method(self):\n        return 42\n"
        )
        self.assertEqual(result["newline"], "LF")
        self.assertTrue(result["has_final_newline"])
        self.assertEqual(len(result["sha256"]), 64)

    def test_read_text_file_zero_count_confirms_without_content(self):
        """A zero-line read should mark an already-known reference as read."""
        tool = ReadTextFile(workspace=self.workspace)
        callback_results = []
        tool.append_callback(
            lambda success, path, content: callback_results.append(
                (success, path, content)
            )
        )

        result = tool._run(path="simple.txt", start=1, count=0)

        self.assertIn("Confirmed text file 'simple.txt'", result)
        self.assertIn("read 0 lines", result)
        self.assertNotIn("1: Line 1", result)
        self.assertEqual(callback_results, [(True, "simple.txt", "")])

    def test_read_text_file_edge_cases(self):
        """Test edge cases for text file reading"""
        tool = ReadTextFile(workspace=self.workspace)
        
        # Empty file
        result = tool._run(path="empty.txt", start=1, count=-1)
        self.assertIn("File empty.txt is empty", result)
        
        # Out of range start
        result = tool._run(path="simple.txt", start=10, count=1)
        self.assertIn("out of range", result)
        
        # A zero start is normalized to the first 1-based line for compatibility.
        result = tool._run(path="simple.txt", start=0, count=1)
        self.assertIn("1: Line 1", result)

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

    def test_copy_file_rejects_destination_outside_allowlist_boundary(self):
        tool = CopyFile(workspace=self.workspace, write_dirs=["subdir"])

        result = tool._run(
            source_path="simple.txt",
            dest_path="subdir-other/copied.txt",
        )

        self.assertIn("not allowed to write", result)
        self.assertFalse(os.path.exists(os.path.join(self.workspace, "subdir-other")))

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

    def test_delete_rejects_traversal_without_touching_outside_file(self):
        outside_dir = tempfile.mkdtemp(
            prefix="test_fileops_outside_", dir=os.path.dirname(self.workspace)
        )
        outside_file = os.path.join(outside_dir, "keep.txt")
        with open(outside_file, "w", encoding="utf-8") as file_obj:
            file_obj.write("keep")
        try:
            relative_outside = os.path.relpath(outside_file, self.workspace)
            result = DeleteFile(workspace=self.workspace)._run(path=relative_outside)
            self.assertIn("not within the workspace", result)
            self.assertTrue(os.path.exists(outside_file))
        finally:
            shutil.rmtree(outside_dir, ignore_errors=True)

    def test_delete_rejects_stale_file_hash(self):
        target = os.path.join(self.workspace, "delete-with-hash.txt")
        with open(target, "w", encoding="utf-8") as file_obj:
            file_obj.write("current")

        result = DeleteFile(workspace=self.workspace)._run(
            path="delete-with-hash.txt",
            expected_sha256=hashlib.sha256(b"stale").hexdigest(),
        )

        self.assertIn("changed after it was read", result)
        self.assertTrue(os.path.exists(target))

    def test_delete_text_lines_merges_blocks_and_preserves_crlf_and_mode(self):
        target = os.path.join(self.workspace, "large-edit.txt")
        original = "".join(f"line {number}\r\n" for number in range(1, 51)).encode(
            "utf-8"
        )
        with open(target, "wb") as file_obj:
            file_obj.write(original)
        os.chmod(target, 0o640)
        callback_results = []
        tool = DeleteTextLines(workspace=self.workspace)
        tool.append_callback(
            lambda success, path, data: callback_results.append((success, path, data))
        )

        result = tool.invoke(
            {
                "path": "large-edit.txt",
                "line_blocks": [1, 4, 5, [10, 20], [4, 40]],
                "expected_sha256": hashlib.sha256(original).hexdigest(),
            }
        )

        expected = "".join(
            f"line {number}\r\n" for number in [2, 3, *range(41, 51)]
        ).encode("utf-8")
        self.assertIn("Deleted 38 physical lines", result)
        self.assertIn("normalized blocks [1, 4-40]", result)
        self.assertIn("use ReplaceStringInFile", result)
        with open(target, "rb") as file_obj:
            self.assertEqual(file_obj.read(), expected)
        self.assertEqual(os.stat(target).st_mode & 0o777, 0o640)
        self.assertTrue(callback_results[0][0])
        self.assertEqual(
            callback_results[0][2]["deleted_line_blocks"],
            [[1, 1], [4, 40]],
        )
        self.assertEqual(callback_results[0][2]["remaining_line_count"], 12)

    def test_delete_text_lines_rejects_any_invalid_block_without_writing(self):
        target = os.path.join(self.workspace, "simple.txt")
        original = self.test_files["simple.txt"].encode("utf-8")
        tool = DeleteTextLines(workspace=self.workspace)

        out_of_range = tool._run(
            path="simple.txt",
            line_blocks=[1, [3, 4]],
        )
        reversed_block = tool.invoke(
            {"path": "simple.txt", "line_blocks": [[3, 2]]}
        )

        self.assertIn("out of range", out_of_range)
        self.assertIn("No lines were deleted", out_of_range)
        self.assertIn("validation error", reversed_block)
        with open(target, "rb") as file_obj:
            self.assertEqual(file_obj.read(), original)

    def test_delete_text_lines_rejects_stale_hash_and_readonly_path(self):
        target = os.path.join(self.workspace, "simple.txt")
        original = self.test_files["simple.txt"].encode("utf-8")

        stale_result = DeleteTextLines(workspace=self.workspace)._run(
            path="simple.txt",
            line_blocks=[1],
            expected_sha256=hashlib.sha256(b"stale").hexdigest(),
        )
        readonly_result = DeleteTextLines(
            workspace=self.workspace,
            write_dirs=["subdir"],
        )._run(path="simple.txt", line_blocks=[1])

        self.assertIn("changed after it was read", stale_result)
        self.assertIn("not allowed to write", readonly_result)
        with open(target, "rb") as file_obj:
            self.assertEqual(file_obj.read(), original)

    def test_delete_text_lines_preserves_missing_final_newline(self):
        target = os.path.join(self.workspace, "delete-no-final-newline.txt")
        with open(target, "wb") as file_obj:
            file_obj.write(b"alpha\r\nbeta\r\ngamma")

        result = DeleteTextLines(workspace=self.workspace)._run(
            path="delete-no-final-newline.txt",
            line_blocks=[[2, 2]],
        )

        self.assertIn("Deleted 1 physical line", result)
        with open(target, "rb") as file_obj:
            self.assertEqual(file_obj.read(), b"alpha\r\ngamma")

    def test_delete_text_lines_can_empty_text_file_but_rejects_binary_file(self):
        text_target = os.path.join(self.workspace, "simple.txt")

        empty_result = DeleteTextLines(workspace=self.workspace)._run(
            path="simple.txt",
            line_blocks=[[1, 3]],
        )
        binary_result = DeleteTextLines(workspace=self.workspace)._run(
            path="binary.bin",
            line_blocks=[1],
        )

        self.assertIn("0 lines remain", empty_result)
        self.assertTrue(os.path.isfile(text_target))
        self.assertEqual(os.path.getsize(text_target), 0)
        self.assertIn("not a text file", binary_result)

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

    def test_workspace_symlink_escape_is_rejected(self):
        outside_dir = tempfile.mkdtemp(
            prefix="test_fileops_symlink_", dir=os.path.dirname(self.workspace)
        )
        outside_file = os.path.join(outside_dir, "outside.txt")
        with open(outside_file, "w", encoding="utf-8") as file_obj:
            file_obj.write("outside")
        link_path = os.path.join(self.workspace, "outside-link.txt")
        os.symlink(outside_file, link_path)
        try:
            read_result = ReadTextFile(workspace=self.workspace)._run(
                path="outside-link.txt"
            )
            edit_result = EditTextFile(workspace=self.workspace)._run(
                path="outside-link.txt", content="changed"
            )
            self.assertIn("not within the workspace", read_result)
            self.assertIn("not within the workspace", edit_result)
            with open(outside_file, "r", encoding="utf-8") as file_obj:
                self.assertEqual(file_obj.read(), "outside")
        finally:
            os.unlink(link_path)
            shutil.rmtree(outside_dir, ignore_errors=True)

    def test_write_rejects_internal_symlink_permission_alias(self):
        readonly_dir = os.path.join(self.workspace, "readonly")
        os.makedirs(readonly_dir)
        target = os.path.join(readonly_dir, "target.txt")
        with open(target, "w", encoding="utf-8") as file_obj:
            file_obj.write("original")
        os.symlink(readonly_dir, os.path.join(self.workspace, "allowed"))

        result = ReplaceStringInFile(
            workspace=self.workspace,
            write_dirs=["allowed"],
            un_write_dirs=["readonly"],
        )._run(
            path="allowed/target.txt",
            old_string="original",
            new_string="changed",
        )

        self.assertTrue(
            "symbolic link" in result or "not allowed to write" in result,
            result,
        )
        with open(target, "r", encoding="utf-8") as file_obj:
            self.assertEqual(file_obj.read(), "original")

    def test_edit_text_file_is_atomic_and_preserves_crlf_and_mode(self):
        target = os.path.join(self.workspace, "crlf.txt")
        with open(target, "wb") as file_obj:
            file_obj.write(b"alpha\r\nbeta\r\n")
        os.chmod(target, 0o640)
        before_sha256 = hashlib.sha256(b"alpha\r\nbeta\r\n").hexdigest()

        result = EditTextFile(workspace=self.workspace)._run(
            path="crlf.txt",
            content="alpha\ngamma\n",
            expected_sha256=before_sha256,
        )

        self.assertIn("SHA256:", result)
        with open(target, "rb") as file_obj:
            self.assertEqual(file_obj.read(), b"alpha\r\ngamma\r\n")
        self.assertEqual(os.stat(target).st_mode & 0o777, 0o640)

    def test_edit_text_file_preserves_missing_final_newline(self):
        target = os.path.join(self.workspace, "no-final-newline.txt")
        with open(target, "wb") as file_obj:
            file_obj.write(b"alpha\nbeta")

        EditTextFile(workspace=self.workspace)._run(
            path="no-final-newline.txt",
            content="alpha\ngamma",
        )

        with open(target, "rb") as file_obj:
            self.assertEqual(file_obj.read(), b"alpha\ngamma")

    def test_edit_text_file_rejects_stale_sha_without_writing(self):
        target = os.path.join(self.workspace, "simple.txt")
        before = self.test_files["simple.txt"].encode("utf-8")
        stale_sha256 = hashlib.sha256(b"older content").hexdigest()

        result = EditTextFile(workspace=self.workspace)._run(
            path="simple.txt",
            content="replacement",
            expected_sha256=stale_sha256,
        )

        self.assertIn("changed after it was read", result)
        with open(target, "rb") as file_obj:
            self.assertEqual(file_obj.read(), before)

    def test_replace_string_failure_does_not_create_file(self):
        result = ReplaceStringInFile(workspace=self.workspace)._run(
            path="missing.txt",
            old_string="not present",
            new_string="replacement",
        )

        self.assertIn("does not exist", result)
        self.assertFalse(os.path.exists(os.path.join(self.workspace, "missing.txt")))

    def test_replace_string_dry_run_preserves_file(self):
        target = os.path.join(self.workspace, "simple.txt")
        result = ReplaceStringInFile(workspace=self.workspace)._run(
            path="simple.txt",
            old_string="Line 2",
            new_string="Changed",
            dry_run=True,
        )

        self.assertIn("Dry run successful", result)
        with open(target, "r", encoding="utf-8") as file_obj:
            self.assertEqual(file_obj.read(), self.test_files["simple.txt"])

    def test_replace_string_preserves_existing_positional_arguments(self):
        target = os.path.join(self.workspace, "simple.txt")
        original = self.test_files["simple.txt"].encode("utf-8")

        result = ReplaceStringInFile(workspace=self.workspace)._run(
            "simple.txt",
            "Line 2",
            "Changed",
            hashlib.sha256(original).hexdigest(),
            True,
        )

        self.assertIn("Dry run successful", result)
        with open(target, "rb") as file_obj:
            self.assertEqual(file_obj.read(), original)

    def test_replace_string_line_blocks_limit_search(self):
        target = os.path.join(self.workspace, "replace-blocks.txt")
        original = "first\ntarget\nmiddle\ntarget\nlast\n"
        with open(target, "w", encoding="utf-8") as file_obj:
            file_obj.write(original)

        whole_file_result = ReplaceStringInFile(workspace=self.workspace)._run(
            path="replace-blocks.txt",
            old_string="target",
            new_string="changed",
        )
        block_result = ReplaceStringInFile(workspace=self.workspace)._run(
            path="replace-blocks.txt",
            old_string="target",
            new_string="changed",
            line_blocks=[[4, 4]],
        )

        self.assertIn("appears 2 times in the whole file", whole_file_result)
        self.assertIn("Successfully replaced 1 occurrence", block_result)
        with open(target, "r", encoding="utf-8") as file_obj:
            self.assertEqual(
                file_obj.read(),
                "first\ntarget\nmiddle\nchanged\nlast\n",
            )

    def test_replace_string_supports_multiple_line_blocks(self):
        target = os.path.join(self.workspace, "replace-multiple-blocks.txt")
        with open(target, "w", encoding="utf-8") as file_obj:
            file_obj.write("one\ntarget\nthree\ntarget\nfive\n")

        tool = ReplaceStringInFile(workspace=self.workspace)
        duplicate_result = tool.invoke(
            {
                "path": "replace-multiple-blocks.txt",
                "old_string": "target",
                "new_string": "changed",
                "line_blocks": [[1, 2], [4, 5]],
            }
        )
        result = tool.invoke(
            {
                "path": "replace-multiple-blocks.txt",
                "old_string": "target",
                "new_string": "changed",
                "line_blocks": [[1, 2], [5, 5]],
            }
        )

        self.assertIn("appears 2 times in line_blocks [1-2, 4-5]", duplicate_result)
        self.assertIn("Successfully replaced 1 occurrence", result)
        self.assertIn("within line_blocks [1-2, 5-5]", result)
        with open(target, "r", encoding="utf-8") as file_obj:
            self.assertEqual(
                file_obj.read(),
                "one\nchanged\nthree\ntarget\nfive\n",
            )

    def test_replace_string_requires_match_inside_one_normalized_block(self):
        target = os.path.join(self.workspace, "replace-boundary.txt")
        original = "one\ntwo\nthree\nfour\n"
        with open(target, "w", encoding="utf-8") as file_obj:
            file_obj.write(original)

        outside_result = ReplaceStringInFile(workspace=self.workspace)._run(
            path="replace-boundary.txt",
            old_string="two\nthree",
            new_string="changed",
            line_blocks=[[2, 2], [4, 4]],
        )
        adjacent_result = ReplaceStringInFile(workspace=self.workspace)._run(
            path="replace-boundary.txt",
            old_string="two\nthree",
            new_string="changed",
            line_blocks=[[2, 2], [3, 3]],
        )

        self.assertIn("was not found in line_blocks [2-2, 4-4]", outside_result)
        self.assertIn("Successfully replaced 1 occurrence", adjacent_result)
        with open(target, "r", encoding="utf-8") as file_obj:
            self.assertEqual(file_obj.read(), "one\nchanged\nfour\n")

    def test_replace_string_line_blocks_validate_before_writing(self):
        target = os.path.join(self.workspace, "replace-invalid-blocks.txt")
        original = "one\ntarget\nthree\n"
        with open(target, "w", encoding="utf-8") as file_obj:
            file_obj.write(original)
        tool = ReplaceStringInFile(workspace=self.workspace)

        reverse_result = tool._run(
            path="replace-invalid-blocks.txt",
            old_string="target",
            new_string="changed",
            line_blocks=[[3, 2]],
        )
        range_result = tool._run(
            path="replace-invalid-blocks.txt",
            old_string="target",
            new_string="changed",
            line_blocks=[[2, 4]],
        )

        self.assertIn("start <= end", reverse_result)
        self.assertIn("out of range", range_result)
        with open(target, "r", encoding="utf-8") as file_obj:
            self.assertEqual(file_obj.read(), original)

    def test_replace_string_line_blocks_preserve_crlf(self):
        target = os.path.join(self.workspace, "replace-blocks-crlf.txt")
        with open(target, "wb") as file_obj:
            file_obj.write(b"one\r\ntarget\r\nthree\r\ntarget\r\n")

        result = ReplaceStringInFile(workspace=self.workspace)._run(
            path="replace-blocks-crlf.txt",
            old_string="target\n",
            new_string="changed\n",
            line_blocks=[[4, 4]],
        )

        self.assertIn("Successfully replaced 1 occurrence", result)
        with open(target, "rb") as file_obj:
            self.assertEqual(
                file_obj.read(),
                b"one\r\ntarget\r\nthree\r\nchanged\r\n",
            )

    def test_edit_text_file_minimal_call_creates_and_overwrites(self):
        target = os.path.join(self.workspace, "created.txt")
        tool = EditTextFile(workspace=self.workspace)

        create_result = tool.invoke({"path": "created.txt", "content": "created\n"})
        overwrite_result = tool.invoke({"path": "created.txt", "content": "updated\n"})

        self.assertIn("Created 'created.txt'", create_result)
        self.assertIn("Overwrote 'created.txt'", overwrite_result)
        with open(target, "r", encoding="utf-8") as file_obj:
            self.assertEqual(file_obj.read(), "updated\n")

    def test_edit_text_file_append_creates_missing_file(self):
        target = os.path.join(self.workspace, "appended.txt")

        result = EditTextFile(workspace=self.workspace)._run(
            path="appended.txt", content="first\n", append=True
        )

        self.assertIn("Appended", result)
        with open(target, "r", encoding="utf-8") as file_obj:
            self.assertEqual(file_obj.read(), "first\n")

    def test_edit_text_file_can_create_empty_file(self):
        target = os.path.join(self.workspace, "new-empty.txt")

        result = EditTextFile(workspace=self.workspace)._run(
            path="new-empty.txt", content=""
        )

        self.assertIn("Created 'new-empty.txt'", result)
        self.assertTrue(os.path.isfile(target))
        self.assertEqual(os.path.getsize(target), 0)

    def test_edit_text_file_identical_content_is_idempotent_success(self):
        callback_results = []
        tool = EditTextFile(workspace=self.workspace)
        tool.append_callback(
            lambda success, path, data: callback_results.append((success, path, data))
        )

        result = tool._run(
            path="simple.txt", content=self.test_files["simple.txt"]
        )

        self.assertIn("already has the requested content", result)
        self.assertNotIn("[ERROR]", result)
        self.assertTrue(callback_results[0][0])
        self.assertFalse(callback_results[0][2]["changed"])

    def test_replace_string_identical_text_is_idempotent_success(self):
        result = ReplaceStringInFile(workspace=self.workspace)._run(
            path="simple.txt",
            old_string="Line 2",
            new_string="Line 2",
        )

        self.assertIn("already has the requested content", result)
        self.assertNotIn("[ERROR]", result)

    def test_file_tool_schemas_require_mutating_arguments(self):
        edit_schema = ArgEditTextFile.model_json_schema()
        delete_lines_schema = ArgDeleteTextLines.model_json_schema()
        replace_schema = ArgReplaceStringInFile.model_json_schema()

        self.assertEqual(set(edit_schema["required"]), {"path", "content"})
        self.assertEqual(
            set(edit_schema["properties"]),
            {"path", "content", "append", "expected_sha256"},
        )
        self.assertEqual(
            set(replace_schema["required"]),
            {"path", "old_string", "new_string"},
        )
        self.assertEqual(
            set(replace_schema["properties"]),
            {
                "path",
                "old_string",
                "new_string",
                "line_blocks",
                "expected_sha256",
                "dry_run",
            },
        )
        self.assertEqual(
            set(delete_lines_schema["required"]),
            {"path", "line_blocks"},
        )
        self.assertEqual(
            set(delete_lines_schema["properties"]),
            {"path", "line_blocks", "expected_sha256"},
        )
        self.assertEqual(
            delete_lines_schema["properties"]["line_blocks"]["minItems"],
            1,
        )
        self.assertEqual(replace_schema["properties"]["old_string"]["minLength"], 1)
        with self.assertRaises(ValidationError):
            ArgDeleteTextLines.model_validate(
                {"path": "x", "line_blocks": [True]}
            )
        with self.assertRaises(ValidationError):
            ArgDeleteTextLines.model_validate(
                {"path": "x", "line_blocks": [[4, 2]]}
            )
        with self.assertRaises(ValidationError):
            ArgReplaceStringInFile.model_validate(
                {"path": "x", "old_string": "a", "new_string": "b", "typo": True}
            )
        with self.assertRaises(ValidationError):
            ArgReplaceStringInFile.model_validate(
                {
                    "path": "x",
                    "old_string": "a",
                    "new_string": "b",
                    "line_blocks": [],
                }
            )
        with self.assertRaises(ValidationError):
            ArgReplaceStringInFile.model_validate(
                {
                    "path": "x",
                    "old_string": "a",
                    "new_string": "b",
                    "line_blocks": [[4, 2]],
                }
            )

    def test_edit_text_file_converts_to_unambiguous_mcp_schema(self):
        mcp_tool = to_fastmcp(EditTextFile(workspace=self.workspace))

        self.assertEqual(set(mcp_tool.parameters["required"]), {"path", "content"})
        self.assertFalse(mcp_tool.parameters.get("additionalProperties", True))
        self.assertEqual(
            set(mcp_tool.parameters["properties"]),
            {"path", "content", "append", "expected_sha256"},
        )

    def test_delete_text_lines_converts_to_unambiguous_mcp_schema(self):
        tool = DeleteTextLines(workspace=self.workspace)
        mcp_tool = to_fastmcp(tool)

        self.assertEqual(
            set(mcp_tool.parameters["required"]),
            {"path", "line_blocks"},
        )
        self.assertFalse(mcp_tool.parameters.get("additionalProperties", True))
        self.assertEqual(
            set(mcp_tool.parameters["properties"]),
            {"path", "line_blocks", "expected_sha256"},
        )
        self.assertIs(ExportedDeleteTextLines, DeleteTextLines)
        self.assertIn(
            "Use this tool only for large text modifications",
            tool.description,
        )
        self.assertIn("then read the shortened file again", tool.description)
        self.assertIn("use ReplaceStringInFile", tool.description)
        self.assertIn("original pre-deletion line numbers", tool.description)
        self.assertIn("use [[10, 20]] for one range", tool.description)

    def test_replace_string_converts_line_blocks_to_mcp_schema(self):
        tool = ReplaceStringInFile(workspace=self.workspace)
        mcp_tool = to_fastmcp(tool)

        self.assertEqual(
            set(mcp_tool.parameters["required"]),
            {"path", "old_string", "new_string"},
        )
        self.assertFalse(mcp_tool.parameters.get("additionalProperties", True))
        self.assertEqual(
            set(mcp_tool.parameters["properties"]),
            {
                "path",
                "old_string",
                "new_string",
                "line_blocks",
                "expected_sha256",
                "dry_run",
            },
        )
        self.assertIn("Omit for the whole file", mcp_tool.parameters[
            "properties"
        ]["line_blocks"]["description"])

    def test_async_validation_error_does_not_leak_tool_lock(self):
        async def run_calls():
            tool = EditTextFile(workspace=self.workspace)
            invalid_result = await asyncio.wait_for(
                tool.ainvoke({"path": "bad.txt", "data": "wrong argument"}),
                timeout=1,
            )
            valid_result = await asyncio.wait_for(
                tool.ainvoke({"path": "good.txt", "content": "written\n"}),
                timeout=1,
            )
            return invalid_result, valid_result

        invalid_result, valid_result = asyncio.run(run_calls())

        self.assertIn("validation error", invalid_result)
        self.assertIn("Created 'good.txt'", valid_result)
        self.assertNotIn("lock timeout", valid_result)

    def test_sync_validation_error_does_not_abort_the_next_write(self):
        tool = EditTextFile(workspace=self.workspace)

        invalid_result = tool.invoke(
            {"path": "bad-sync.txt", "data": "wrong argument"}
        )
        valid_result = tool.invoke(
            {"path": "good-sync.txt", "content": "written\n"}
        )

        self.assertIn("validation error", invalid_result)
        self.assertIn("Created 'good-sync.txt'", valid_result)
        self.assertTrue(os.path.isfile(os.path.join(self.workspace, "good-sync.txt")))

    def test_async_file_locks_are_shared_only_for_the_same_canonical_path(self):
        async def get_locks():
            edit_tool = EditTextFile(workspace=self.workspace)
            delete_lines_tool = DeleteTextLines(workspace=self.workspace)
            replace_tool = ReplaceStringInFile(workspace=self.workspace)
            same_from_edit = edit_tool._get_call_locks(
                {"path": "nested/../simple.txt"}
            )[0]
            same_from_replace = replace_tool._get_call_locks(
                {"path": "simple.txt"}
            )[0]
            same_from_delete_lines = delete_lines_tool._get_call_locks(
                {"path": "./simple.txt"}
            )[0]
            different_file = edit_tool._get_call_locks(
                {"path": "other.txt"}
            )[0]
            return (
                same_from_edit,
                same_from_replace,
                same_from_delete_lines,
                different_file,
            )

        (
            same_from_edit,
            same_from_replace,
            same_from_delete_lines,
            different_file,
        ) = asyncio.run(get_locks())

        self.assertIs(same_from_edit, same_from_replace)
        self.assertIs(same_from_edit, same_from_delete_lines)
        self.assertIsNot(same_from_edit, different_file)

    def test_async_edits_to_different_files_can_run_concurrently(self):
        both_started = threading.Event()
        release_calls = threading.Event()
        state_lock = threading.Lock()
        started_paths = []

        def blocking_edit(tool, path, content, **kwargs):
            with state_lock:
                started_paths.append(path)
                if len(started_paths) == 2:
                    both_started.set()
            release_calls.wait(timeout=1)
            return path

        async def run_calls():
            tool = EditTextFile(workspace=self.workspace)
            first = asyncio.create_task(
                tool.ainvoke({"path": "first.txt", "content": "first"})
            )
            second = asyncio.create_task(
                tool.ainvoke({"path": "second.txt", "content": "second"})
            )
            started_concurrently = await asyncio.to_thread(
                both_started.wait, 0.5
            )
            release_calls.set()
            results = await asyncio.gather(first, second)
            return started_concurrently, results

        try:
            with patch.object(EditTextFile, "_run", blocking_edit):
                started_concurrently, results = asyncio.run(run_calls())
        finally:
            release_calls.set()

        self.assertTrue(started_concurrently)
        self.assertEqual(set(results), {"first.txt", "second.txt"})

    def test_get_diff_reports_identical_content(self):
        self.assertIn(
            "No changes detected",
            get_diff(["unchanged\n"], ["unchanged\n"], "same.txt"),
        )

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

    def test_check_file_validation_has_no_creation_side_effect(self):
        """File validation must not create a missing path."""
        base = BaseReadWrite()
        base.init_base_rw(self.test_dir)
        base.create_file = True

        success, msg, real_path = base.check_file(
            "new_file.txt", allow_missing=True
        )
        self.assertTrue(success)
        self.assertFalse(os.path.exists(real_path))

    def test_check_dir_empty_path(self):
        """Test check_dir with empty path"""
        base = BaseReadWrite()
        base.init_base_rw(self.test_dir)
        
        # Check empty path (should default to current directory)
        success, msg, real_path = base.check_dir("")
        self.assertTrue(success)
        self.assertEqual(real_path, os.path.realpath(self.test_dir))


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
