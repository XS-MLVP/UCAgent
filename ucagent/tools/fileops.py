# -*- coding: utf-8 -*-
"""File operations tools for UCAgent."""

from typing import Optional, List, Tuple
from ucagent.util.log import info, str_info, str_return, str_error, str_data, warning
from ucagent.util.functions import is_text_file, get_file_size, bytes_to_human_readable, copy_indent_from, rm_workspace_prefix
from ucagent.util.functions import get_diff
from .uctool import UCTool

from langchain_core.callbacks import (
    CallbackManagerForToolRun,
)
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field

import os
import fnmatch
import re
import shutil


def is_file_writeable(path: str, un_write_dirs: list=None, write_dirs: list=None) -> Tuple[bool, str]:
    if path.startswith("/"):
        path = path[1:]  # remove leading slash for relative check
    if un_write_dirs is None and write_dirs is None:
        return True, "No write restrictions defined."
    if un_write_dirs is not None:
        assert isinstance(un_write_dirs, list), "un_write_dirs must be a list."
        for d in un_write_dirs:
            if path.startswith(d):
                return False, f"Path '{path}' is not allowed to write."
        if write_dirs is None or len(write_dirs) == 0:
            return True, f"Path '{path}' is allowed to write as it does not match any no-write directories: {un_write_dirs}."
    if write_dirs is not None:
        assert isinstance(write_dirs, list), "write_dirs must be a list."
        for d in write_dirs:
            if path.startswith(d):
                return True, f"Path '{path}' is allowed to write."
        return False, f"Path '{path}' is not allowed to write, except in: {write_dirs}."
    return True, "Not implemented yet."


class BaseReadWrite:
    """Base class for write operations."""

    # custom variables
    workspace: str = Field(
        default=".",
        description="Workspace directory to modify files in."
    )
    max_read_size: int = Field(
        default=131072,
        description="Maximum file size to read (in bytes)."
    )
    write_able_dirs: List[str] = Field(
        default=None,
        description="List of directories where files can be modified. If empty, all directories are writable."
    )
    un_write_able_dirs: List[str] = Field(
        default=None,
        description="List of directories where files cannot be modified. If empty, no directories are restricted."
    )
    create_file: bool = Field(
        default=False,
        description="If True, creates the file if it does not exist. If False, raises an error if the file does not exist."
    )
    call_backs: List = Field(
        default=[],
        description="List of callbacks to use for tool run management."
    )

    def append_callback(self, callback):
        """Append a callback to the tool run callbacks."""
        if callback not in self.call_backs:
            self.call_backs.append(callback)
            info(f"Callback {callback} added to {self.__class__.__name__} tool.")

    def remove_callback(self, callback):
        """Remove a callback from the tool run callbacks."""
        if callback in self.call_backs:
            self.call_backs.remove(callback)
            info(f"Callback {callback} removed from {self.__class__.__name__} tool.")

    def do_callback(self, *args, **kwargs):
        """Run all callbacks with the provided arguments."""
        for cb in self.call_backs:
            # func(success, path, msg)
            cb(*args, **kwargs)

    def refine_dirs(self, workspace, dirs):
        if not dirs:
            return dirs
        if not isinstance(dirs, list):
            dirs = [dirs]
        dirs = [rm_workspace_prefix(workspace,d) for d in dirs]
        assert any([a != "." for a in dirs]), "'.' cannot be used as a writable or unwritable directory."
        return  dirs

    def init_base_rw(self, workspace: str, write_dirs=None, un_write_dirs=None, max_read_size: int = 131072):
        """Initialize the base write tool."""
        assert os.path.exists(workspace), f"Workspace {workspace} does not exist."
        self.workspace = os.path.abspath(workspace)
        self.write_able_dirs = self.refine_dirs(self.workspace, write_dirs)
        self.un_write_able_dirs = self.refine_dirs(self.workspace, un_write_dirs)
        self.max_read_size = max_read_size
        if write_dirs is not None:
            if len(write_dirs) == 0:
                self.description += "\n\nNote: All directories are read only."
            else:
                self.description += f"\n\nNote: Only directories in {write_dirs} are writable."
            for d in write_dirs:
                if not os.path.exists(os.path.join(self.workspace, d)):
                    warning(f"Writable directory {d} does not exist in workspace {workspace}.")
                assert isinstance(d, str)
        if un_write_dirs is not None:
            if len(un_write_dirs) == 0:
                self.description += "\n\nNote: No directories are restricted."
            else:
                self.description += f"\n\nNote: Directories in {un_write_dirs} are not writable."
            for d in un_write_dirs:
                if not os.path.exists(os.path.join(self.workspace, d)):
                    warning(f"Unwritable directory {d} does not exist in workspace {workspace}.")
                assert isinstance(d, str)
        info(f"{self.__class__.__name__} tool initialized with workspace: {self.workspace}")

    def get_real_path(self, rpath):
        return os.path.abspath(self.workspace+"/"+rpath)

    def check_file(self, path: str) -> Tuple[bool, str]:
        """Check if the file is writable."""
        if path.endswith('/'):
            return False, f"Path '{path}' should not end with a slash. Please provide a file path, not a directory.", ""
        write_able, msg = is_file_writeable(path, self.un_write_able_dirs, self.write_able_dirs)
        if not write_able:
            return False, msg, ""
        real_path = self.get_real_path(path)
        if real_path.startswith(self.workspace) is False:
            return False, f"File '{path}' is not within the workspace.", ""
        if not os.path.exists(real_path):
            if self.create_file:
                info(f"File {real_path} does not exist, creating it.")
                base_dir = os.path.dirname(real_path)
                if not os.path.exists(base_dir):
                    info(f"Base directory {base_dir} does not exist, creating it.")
                    os.makedirs(base_dir, exist_ok=True)
                with open(real_path, 'w', encoding='utf-8') as f:
                    pass
            else:
                ex_msg = ""
                if path.startswith("/"):
                    ex_msg = " Note: Leading '/' indicates an absolute path. Please provide a relative path within the workspace."
                return False, f"File {path} does not exist in workspace. Please create it first.{ex_msg}", ""
        return True, "", real_path

    def check_dir(self, path: str) -> Tuple[bool, str, str]:
        """Check if the directory exists and is accessible."""
        # Handle empty path (current directory)
        if not path or path == ".":
            path = "."
        
        real_path = os.path.abspath(os.path.join(self.workspace, path))
        if not real_path.startswith(self.workspace):
            return False, str_error(f"Path '{path}' is not within the workspace."), ""
        if not os.path.exists(real_path):
            return False, str_error(f"Path {path} does not exist in workspace."), ""
        if os.path.isfile(real_path):
            return False, str_error(f"Path {path} is a file, need directory."), ""
        if not os.path.isdir(real_path):
            return False, str_error(f"Path {path} is not a directory in workspace."), ""
        return True, "", real_path

class ArgSearchText(BaseModel):
    pattern: str = Field(
        default="",
        description="Text pattern to search for in the files. Supports plain text, wildcards (*?), and regex patterns. "
                   "Examples: 'class My*' (wildcard), 'def .*function.*:' (regex), or plain text 'hello world'."
    )
    directory: str = Field(
        default="",
        description="Subdirectory path to search in, relative to the workspace. If empty, searches in the entire workspace. "
                   "If it is a text file, it will search in the file only."
    )
    max_match_lines: int = Field(
        default=20,
        description="Maximum number of matching lines to return per file."
    )
    max_match_files: int = Field(
        default=10,
        description="Maximum number of matching files to return."
    )
    use_regex: bool = Field(
        default=False,
        description="If True, treat pattern as regular expression. If False, use wildcard/plain text matching."
    )
    case_sensitive: bool = Field(
        default=False,
        description="If True, perform case-sensitive search. If False, ignore case."
    )
    include_line_numbers: bool = Field(
        default=True,
        description="If True, include line numbers in results. If False, show only the matching content."
    )

class SearchText(UCTool, BaseReadWrite):
    """Search for text in files within the workspace directory with advanced pattern matching."""
    name: str = "SearchText"
    description: str = (
        "Search for text in files within the workspace directory with support for plain text, wildcards, and regex patterns. "
        "Returns a list of matching files with line numbers and content. Supports case-sensitive/insensitive search."
    )
    args_schema: Optional[ArgsSchema] = ArgSearchText
    return_direct: bool = False

    def _run(self, pattern: str, directory: str = "", max_match_lines: int = 20, max_match_files: int = 10,
             use_regex: bool = False, case_sensitive: bool = False, include_line_numbers: bool = True,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Search for text in files within a workspace directory."""
        if not pattern:
            self.do_callback(False, directory, "No text pattern provided for search.")
            return str_error("No text pattern provided for search.")
        
        result = []
        count_files = 0
        count_lines = 0
        
        # Compile regex pattern if needed
        regex_pattern = None
        if use_regex:
            try:
                flags = 0 if case_sensitive else re.IGNORECASE
                regex_pattern = re.compile(pattern, flags)
            except re.error as e:
                error_msg = f"Invalid regex pattern '{pattern}': {str(e)}"
                self.do_callback(False, directory, error_msg)
                return str_error(error_msg)
        
        def search_in_file(txt, sfile, fname):
            nonlocal count_lines, result
            _find = False
            if not is_text_file(sfile):
                return False
            
            try:
                with open(sfile, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    for i, line in enumerate(lines):
                        line_matches = False
                        
                        if use_regex and regex_pattern:
                            line_matches = regex_pattern.search(line) is not None
                        else:
                            # Use wildcard or plain text matching
                            if case_sensitive:
                                if '*' in txt or '?' in txt:
                                    line_matches = fnmatch.fnmatchcase(line, txt)
                                else:
                                    line_matches = txt in line
                            else:
                                if '*' in txt or '?' in txt:
                                    line_matches = fnmatch.fnmatch(line.lower(), txt.lower())
                                else:
                                    line_matches = txt.lower() in line.lower()
                        
                        if line_matches:
                            if include_line_numbers:
                                result.append(f"{fname}: Line {i + 1}: {line.strip()}")
                            else:
                                result.append(f"{fname}: {line.strip()}")
                            count_lines += 1
                            _find = True
                            if count_lines >= max_match_lines:
                                result.append(f"... (truncated to {max_match_lines} lines)")
                                break
            except (UnicodeDecodeError, IOError) as e:
                info(f"Could not read file {sfile}: {str(e)}")
                return False
            
            return _find
        real_path = os.path.join(self.workspace, directory)
        if os.path.isfile(real_path):
            search_in_file(pattern, os.path.join(self.workspace, directory), directory)
            if len(result) > 0:
                ret_head = str_info(f"\nFound {len(result)} matching lines in file {directory}.\n\n")
                self.do_callback(True, directory, result)
                return ret_head + str_return("\n".join(result))
        else:
            success, msg, real_path = self.check_dir(directory)
            if not success:
                self.do_callback(False, directory, msg)
                return str_error(msg)
            info(f"Searching for text '{pattern}' in {real_path}")
            for root, _, files in os.walk(real_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    if not is_text_file(file_path):
                        continue
                    if search_in_file(pattern, file_path, os.path.relpath(file_path, self.workspace)):
                        count_files += 1
                    if count_files >= max_match_files:
                        result.append(f"... (truncated to {max_match_files} files)")
                        break
                if count_files >= max_match_files:
                    break
            if result:
                ret_head = str_info(f"\nFound {count_files} files with {count_lines} matching lines.\n\n")
                self.do_callback(True, directory, result)
                return ret_head + str_return("\n".join(result))
            self.do_callback(False, directory, None)
        return str_error(f"No matches found for '{pattern}' in the specified directory({directory if directory else '.'}).")

    def __init__(self, workspace: str, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace)
        info(f"SearchText tool initialized with workspace: {self.workspace}")


class ArgFindFiles(BaseModel):
    pattern: str = Field(
        default="",
        description="File name pattern to search for in the directory. "
    )
    directory: str = Field(
        default="",
        description="Subdirectory path to search in, relative to the workspace. If empty, searches in the entire workspace."
    )
    max_match_files: int = Field(
        default= 10,
        description="Maximum number of matching files to return. "
    )


class FindFiles(UCTool, BaseReadWrite):
    """Find files in a workspace directory matching a specific pattern."""
    name: str = "FindFiles"
    description: str = (
        "Find files in a workspace directory matching a specific pattern. "
        "Returns a list of matching file paths."
    )
    args_schema: Optional[ArgsSchema] = ArgFindFiles
    return_direct: bool = False

    def _run(self, pattern: str, directory: str = "", max_match_files: int = 10,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Find files in a directory of the workspace."""
        if not pattern:
            self.do_callback(False, directory, "No file pattern provided for search.")
            return str_error("No file pattern provided for search.")
        success, msg, real_path = self.check_dir(directory)
        if not success:
            self.do_callback(False, directory, msg)
            return str_error(msg)
        result = []
        count_files = 0
        info(f"Finding files with pattern '{pattern}' in {real_path}")
        for root, _, files in os.walk(real_path):
            for file in files:
                if fnmatch.fnmatch(file, pattern):
                    file_path = os.path.join(root, file)
                    result.append(os.path.relpath(file_path, self.workspace))
                    count_files += 1
                    if count_files >= max_match_files:
                        result.append(f"... (truncated to {max_match_files} files)")
                        break
            if count_files >= max_match_files:
                break
        if result:
            ret_head = str_info(f"\nFound {count_files} matching files.\n\n")
            self.do_callback(True, directory, result)
            return ret_head + str_return("\n".join(result))
        self.do_callback(False, directory, None)
        return str_error(f"No matches found for '{pattern}' in the specified directory({directory}).")

    def __init__(self, workspace: str, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace)
        info(f"FindFiles tool initialized with workspace: {self.workspace}")


class ArgPathList(BaseModel):
    path: str = Field(
        default=".",
        description="Directory path to list files from, relative to the workspace.")
    depth: int = Field(
        default=-1,
        description="Subdirectory depth to list. -1: all levels, 0: only current directory."
    )


class PathList(UCTool, BaseReadWrite):
    """List all files and directories in a workspace directory, recursively."""
    name: str = "PathList"
    description: str = (
        "List all files and directories in a workspace directory, including subdirectories. "
        "Returns a list with: Index    Name    (Type, Size, Bytes)."
    )
    args_schema: Optional[ArgsSchema] = ArgPathList
    return_direct: bool = False

    # custom variables
    ignore_pattern: list = Field(
        default=["*__pycache__*"],
        description="Patterns to ignore files/directories, e.g., '*.tmp'."
    )

    ignore_dirs_files: list = Field(
        default=[],
        description="List of subdirectory names and files to ignore when listing files. "
    )

    def _run(
        self, path: str = ".", depth: int = -1, run_manager: Optional[CallbackManagerForToolRun] = None
    ) -> str:
        """List all files in a directory of the workspace, including subdirectories."""
        success, msg, real_path = self.check_dir(path)
        if not success:
            self.do_callback(False, path, msg)
            return str_error(msg)
        info(f"Listing files in {real_path} with depth {depth}")
        if depth < 0:
            depth = float('inf')
        result = []
        count_directories = 0
        count_files = 0
        index = 0
        for root, _, files in os.walk(real_path):
            level = root.replace(real_path, '').count(os.sep)
            if level > depth:
                continue
            directory =  os.path.relpath(root, self.workspace)
            if any(fnmatch.fnmatch(directory, pattern) for pattern in self.ignore_pattern):
                continue
            if any(directory.startswith(p) for p in self.ignore_dirs_files):
                continue
            if not directory == ".":
                result.append(f"{index}    {directory}/".strip() + "    (type: directory, size: N/A, bytes: N/A)")
                index += 1
                count_directories += 1
            for file in files:
                tfile_path = os.path.join(directory, file)
                if tfile_path.startswith("./"):
                    tfile_path = tfile_path[2:]
                if any(fnmatch.fnmatch(tfile_path, pattern) for pattern in self.ignore_pattern):
                    continue
                if any(tfile_path.startswith(p) for p in self.ignore_dirs_files):
                    continue
                # get the lines of the file
                # check if the file is a text file
                absolute_file_path = os.path.join(self.workspace, tfile_path)
                file_type = "binary" if not is_text_file(absolute_file_path) else "text"
                bytes_count= get_file_size(absolute_file_path)
                file_size = bytes_to_human_readable(bytes_count)
                result.append(f"{index}    {tfile_path.strip()}" + f"    (type: {file_type}, size: {file_size}, bytes: {bytes_count})")
                index += 1
                count_files += 1
        if result:
            ret_head = str_info(f"\nFound {count_directories} directories and {count_files} files in workspace.\n\n")
            result.insert(0, f"Index    Name    (Type, Size, Bytes)")
            self.do_callback(True, path, result)
            return ret_head + str_return("\n".join(result))
        self.do_callback(False, path, None)
        return str_error(f"No files found in the specified directory({path}).")

    def __init__(self, workspace: str, ignore_pattern=None, ignore_dirs_files=None, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace)
        if ignore_pattern is not None:
            self.ignore_pattern += ignore_pattern
        if ignore_dirs_files is not None:
            self.ignore_dirs_files = ignore_dirs_files


class ArgReadBinFile(BaseModel):
    path: str = Field(
        default=None,
        description="File path to read, relative to the workspace.")
    start: int = Field(
        default=0,
        description="Start byte position to read from."
    )
    end: int = Field(
        default=-1,
        description="End byte position to read to. -1 means end of file."
    )


class ReadBinFile(UCTool, BaseReadWrite):
    """Read binary content of a file in the workspace."""
    name: str = "ReadBinFile"
    description: str = (
        "Read binary content of a file in the workspace. Supports partial reads via bytes postion start/end. "
        "If file is text type, suggests to use tool 'ReadTextFile'. "
        "Max read size is %d bytes. If not text, returns python bytes format: eg b'\\x00\\x01\\x02...'. "
        "Note: The file content in return data is after prefix '[BIN_DATA]\\n'."
    )
    args_schema: Optional[ArgsSchema] = ArgReadBinFile
    return_direct: bool = False

    def _run(self,
             path: str, start: int, end:int, run_manager: Optional[CallbackManagerForToolRun] = None
            ) -> str:
        """Read the content of a file in the workspace."""
        success, msg, real_path = self.check_file(path)
        if not success:
            self.do_callback(False, path, msg)
            return str_error(msg)
        info(f"Reading file {real_path} from position {start} to {end}")
        file_bytes = get_file_size(real_path)
        is_text = is_text_file(real_path)
        with open(real_path, 'rb') as f:
            f.seek(start)
            content = f.read(end - start) if (end != -1) else f.read()
            read_bytes = len(content)
            remm_bytes = file_bytes - start - read_bytes
            if not content:
                self.do_callback(False, path, None)
                return str_error(f"File {path} is empty or the specified range is invalid.")
            tex_size = len(content)
            if tex_size > self.max_read_size:
                self.do_callback(False, path, f"read size {tex_size} characters exceeds the maximum read size of {self.max_read_size} characters. ")
                return str_error(f"\nRead size {tex_size} characters exceeds the maximum read size of {self.max_read_size} characters. "
                                 f"You need to specify a smaller range. current range is (start={start}, end={end}). "
                                  "If the file type is not text, the size of characters will be more then the raw bytes after python convert." if not is_text else "")
            ret_head = str_info(f"\nRead {read_bytes}/{file_bytes} bytes with (start={start}, end={end}), {remm_bytes} bytes remain after the read position.\n\n")
            self.do_callback(True, path, content)
            return ret_head + str_data(content, "BIN_DATA")

    def __init__(self, workspace: str, max_read_size: int = 131072, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace, max_read_size=max_read_size)
        self.description = self.description % self.max_read_size


class ArgReadTextFile(BaseModel):
    path: str = Field(
        default=None,
        description="Text file path to read, relative to the workspace.")
    start: int = Field(
        default=1,
        description="Start line index (1-based)."
    )
    count: int = Field(
        default=-1,
        description="Number of lines to read. -1 means to end of file."
    )


class ReadTextFile(UCTool, BaseReadWrite):
    """Read lines from a text file in the workspace. (line index starts from 1)"""
    name: str = "ReadTextFile"
    description: str = (
        "Read lines from a text file in the workspace. Supports start line and line count. "
        "Max read size is %d characters. Each line is prefixed with its index."
        "Note: The file content in return data is after prefix '[TXT_DATA]\\n' and each line has prefix '<index>: '.\n"
        "For example, the raw data in file is:\n"
        "line 1\nline 2\nline 3\n"
        "while the returned file content is:\n"
        "[TXT_DATA]\n"
        "1: line 1\n2: line 2\n3: line 3\n"
        "The line index starts from 1. "
    )
    args_schema: Optional[ArgsSchema] = ArgReadTextFile
    return_direct: bool = False

    def _run(self, path: str, start: int = 1, count: int = -1,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Read the content of a text file in the workspace."""
        success, msg, real_path = self.check_file(path)
        if not success:
            self.do_callback(False, path, msg)
            return str_error(msg)
        if not is_text_file(real_path):
            emsg = f"File {path} is not a text file. Please use 'ReadBinFile' to read binary files."
            self.do_callback(False, path, emsg)
            return str_error(emsg)
        info(f"Reading text file {real_path} from line {start} with count {count}")
        if count == 0:
            self.do_callback(False, path, None)
            return str_error(f"Count is 0, no lines to read from file {path}.")
        try:
            with open(real_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                lines_count = len(lines)
                # Handle empty file
                if lines_count == 0:
                    self.do_callback(True, path, "")
                    return str_info(f"\nFile {path} is empty (0 lines).\n\n") + str_data("", "TXT_DATA")
                # Validate start parameter
                start = max(0, start - 1)  # Convert to 0-based index
                if start >= lines_count:
                    emsg = f"Start line {start + 1} is out of range (file has {lines_count} lines, valid range: 1-{lines_count})."
                    self.do_callback(False, path, emsg)
                    return str_error(emsg)
                r_count = count
                if r_count == -1 or start + r_count > lines_count:
                    r_count = lines_count - start
                # Ensure we don't read negative count
                r_count = max(0, r_count)
                if r_count == 0:
                    self.do_callback(True, path, "")
                    return str_info(f"\nNo lines to read from position {start + 1} in file {path}.\n\n") + str_data("", "TXT_DATA")
                # Format line numbers with appropriate padding
                max_line_num = start + r_count - 1
                line_num_width = len(str(max_line_num))
                fmt_index = f"%{line_num_width}d: %s"
                content = ''.join([fmt_index % (i + start + 1, line) for i, line in enumerate(lines[start:start + r_count])])
                # Check size limit
                if len(content) > self.max_read_size:
                    emsg = f"Read size {len(content)} characters exceeds the maximum read size of {self.max_read_size} characters. " +\
                                     f"You need to specify a smaller range. Current range is (start={start+1}, count={count if count >= 0 else 'ALL'})."
                    self.do_callback(False, path, emsg)
                    return str_error(emsg)

                remaining_lines = lines_count - start - r_count
                ret_head = str_info(f"\nRead {r_count}/{lines_count} lines from '{path}' (lines {start + 1}-{start + r_count}), "
                                   f"{remaining_lines} lines remain after the read position.\n\n")
                self.do_callback(True, path, content)
                return ret_head + str_data(content, "TXT_DATA")

        except UnicodeDecodeError as e:
            emsg = f"Failed to decode file {path} as UTF-8: {str(e)}. File might be binary or use different encoding."
            self.do_callback(False, path, emsg)
            return str_error(emsg)
        except IOError as e:
            emsg = f"Failed to read file {path}: {str(e)}"
            self.do_callback(False, path, emsg)
            return str_error(emsg)

    def __init__(self, workspace: str, max_read_size: int = 131072, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace, max_read_size=max_read_size)
        self.description = self.description % self.max_read_size
        info(f"ReadTextFile tool initialized with workspace: {self.workspace}")


class ArgEditTextFile(BaseModel):
    path: str = Field(
        default=None,
        description="Text file path to edit or create, relative to the workspace."
    )
    data: str = Field(
        default=None,
        description="String data to edit or to write. If None, clear the content."
    )
    mode: str = Field(
        default="replace",
        description="Edit mode: 'write' (write to a new file), 'append' (append data to the end), or 'replace' (replace lines by index)."
    )
    start: int = Field(
        default=1,
        description="Start line index (1-based) for 'replace' mode. If index < 1, insert at head; if index > file lines, append at end."
    )
    count: int = Field(
        default=-1,
        description="Number of lines to replace for 'replace' mode. 0: insert, -1: to end of file, positive: replace n lines."
    )
    preserve_indent: bool = Field(
        default=False,
        description="For 'replace' mode: if True, preserve indentation of original lines when replacing."
    )


class EditTextFile(UCTool, BaseReadWrite):
    """Edit or create a text file in the workspace with multiple modes."""
    name: str = "EditTextFile"
    description: str = (
        "Edit or create a text file in the workspace. Supports multiple modes:\n"
        "- 'replace': Replace/insert lines at specific line indices (default)\n"
        "- 'write': Write data to a new file (cannot be used to edit existing files)\n"
        "- 'append': Add data to the end of the file\n"
        "For 'replace' mode, supports preserving indentation.\n"
        "When success, returns the difference summary, otherwise returns error message.\n"
    )
    args_schema: Optional[ArgsSchema] = ArgEditTextFile
    return_direct: bool = False

    def _run(self, path: str, data: str = None, mode: str = "replace", start: int = 1, count: int = -1, preserve_indent: bool = False,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Edit or create a text file in the workspace with specified mode."""
        start = start - 1 # Convert to 0-based index
        self.create_file = True  # ensure file is created if not exists
        # Validate mode parameter
        valid_modes = ["write", "append", "replace"]
        if mode not in valid_modes:
            emsg = f"Invalid mode '{mode}'. Valid modes are: {valid_modes}"
            self.do_callback(False, path, emsg)
            return str_error(emsg)
        rpath = self.get_real_path(path)
        if os.path.isdir(rpath):
            emsg = f"Path '{path}' is a directory, cannot edit directory."
            self.do_callback(False, path, emsg)
            return str_error(emsg)
        if os.path.isfile(rpath):
            if mode in ["write"]:
                emsg = f"File '{path}' already exists, cannot use 'write' mode on existing files. Please check if this file is a template you need to fill."
                self.do_callback(False, path, emsg)
                return str_error(emsg)
        else:
            if mode in ["append", "replace"]:
                emsg = f"File '{path}' does not exist, cannot use '{mode}' mode on non-existing file. Please use the 'write' mode to create it first."
                self.do_callback(False, path, emsg)
                return str_error(emsg)
        success, msg, real_path = self.check_file(path)

        if not success:
            self.do_callback(False, path, msg)
            return str_error(msg)

        # Check if it's a text file (only if file exists)
        if os.path.exists(real_path) and not is_text_file(real_path):
            emsg = f"File {path} is not a text file."
            self.do_callback(False, path, emsg)
            return str_error(emsg)

        try:
            if mode == "write":
                # WriteToFile functionality
                is_existed_file = os.path.exists(real_path)
                with open(real_path, 'w', encoding='utf-8') as f:
                    if data is None:
                        info(f"Clearing file {real_path}.")
                        f.truncate(0)
                    else:
                        info(f"Writing data to file {real_path}.")
                        f.write(data)
                    f.flush()
                msg = f"Write {len(data) if data else 0} characters to '{path}' complete."
                self.do_callback(True, path, msg)
                return str_info(msg)

            elif mode == "append":
                # AppendToFile functionality
                with open(real_path, 'a', encoding='utf-8') as f:
                    if data is None:
                        info(f"Clearing file {real_path}.")
                        f.truncate(0)
                    else:
                        info(f"Appending data to file {real_path}.")
                        f.write(data)
                    f.flush()
                self.do_callback(True, path, data)
                return str_info(f"Append {len(data) if data else 0} characters complete." if data else f"File({path}) cleared.")

            elif mode == "replace":
                # ReplaceLinesByIndex functionality
                info(f"Replacing text file {real_path} from line {start+1} with count {count}")
                # Validate count parameter
                if count < -1:
                    emsg = f"Invalid count {count}. Count must be -1 (to end of file), 0 (insert), or positive (replace n lines)."
                    self.do_callback(False, path, emsg)
                    return str_error(emsg)
                # Read existing content or create empty if file doesn't exist
                if os.path.exists(real_path):
                    with open(real_path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                else:
                    lines = []
                    info(f"File {real_path} doesn't exist, creating new file.")
                lines_count = len(lines)
                # Handle negative start (insert at beginning if start < 0)
                if start < 0:
                    start = 0
                # Prepare replacement data
                lines_pred = lines[:min(start, lines_count)]
                lines_after = []
                if count == -1:
                    # Replace from start to end of file
                    lines_after = []
                elif count == 0:
                    # Insert mode - don't remove any lines
                    lines_after = lines[min(start, lines_count):]
                else:
                    # Replace 'count' lines starting from 'start'
                    end_pos = min(start + count, lines_count)
                    lines_after = lines[end_pos:]
                # Prepare new content
                lines_insert = []
                if data is not None:
                    if preserve_indent and start < lines_count:
                        # Use existing lines for indentation reference
                        ref_lines = lines[start:min(start + max(1, count if count > 0 else 1), lines_count)]
                        if ref_lines:
                            indented_content = copy_indent_from(ref_lines, data.split("\n"))
                            lines_insert = ["\n".join(indented_content)]
                            if not lines_insert[0].endswith('\n'):
                                lines_insert[0] += '\n'
                        else:
                            lines_insert = [data + ('\n' if not data.endswith('\n') else '')]
                    else:
                        lines_insert = [data + ('\n' if not data.endswith('\n') else '')]

                # Construct new file content
                lines_new = lines_pred + lines_insert + lines_after
                # Write the new content
                with open(real_path, 'w', encoding='utf-8') as f:
                    f.writelines(lines_new)
                    f.flush()

                # Prepare result message
                operation_desc = ""
                if count == 0:
                    operation_desc = f"Inserted new content at line {start+1}"
                elif count == -1:
                    operation_desc = f"Replaced content from line {start+1} to end of file"
                elif data is None:
                    operation_desc = f"Removed {min(count, lines_count - start)} lines starting from line {start+1}"
                else:
                    actual_replaced = min(count, max(0, lines_count - start))
                    operation_desc = f"Replaced {actual_replaced} lines starting from line {start+1}"
                if data is not None:
                    data_lines = len(data.split('\n'))
                    operation_desc += f" with {data_lines} new line(s)"
                self.do_callback(True, path, {"start": start+1, "count": count, "data": data})
                # Generate diff for better understanding
                diff_result = ""
                if data is not None:
                    if count != -1:
                        diff_result = get_diff(lines, lines_new, path) if lines != lines_new else ""
                    elif mode == "replace":
                        diff_result = " (Warning: difference summary is ignored. You are replacing to end of file, it is not the best practice" + \
                                      " if you just want to edit part of the file content. And diff is not generated for this case.)"
                return str_info(f"{operation_desc}.") + diff_result

        except UnicodeDecodeError as e:
            emsg = f"Failed to decode file {path} as UTF-8: {str(e)}"
            self.do_callback(False, path, emsg)
            return str_error(emsg)
        except IOError as e:
            emsg = f"Failed to modify file {path}: {str(e)}"
            self.do_callback(False, path, emsg)
            return str_error(emsg)

    def __init__(self, workspace: str, write_dirs=None, un_write_dirs=None, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace, write_dirs, un_write_dirs)


class ArgCopyFile(BaseModel):
    source_path: str = Field(
        default=None,
        description="Source file path to copy from, relative to the workspace."
    )
    dest_path: str = Field(
        default=None,
        description="Destination file path to copy to, relative to the workspace. Created if not exists."
    )
    overwrite: bool = Field(
        default=False,
        description="If True, overwrite destination file if it exists. If False, return error if destination exists."
    )


class CopyFile(UCTool, BaseReadWrite):
    """Copy a file from source to destination within the workspace."""
    name: str = "CopyFile"
    description: str = (
        "Copy a file from source to destination within the workspace. "
        "Creates destination directory if it doesn't exist. Optionally overwrites existing files."
    )
    args_schema: Optional[ArgsSchema] = ArgCopyFile
    return_direct: bool = False

    def _run(self, source_path: str, dest_path: str, overwrite: bool = False,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Copy a file from source to destination."""
        # Check source file
        success, msg, real_source_path = self.check_file(source_path)
        if not success:
            self.do_callback(False, source_path, msg)
            return str_error(f"Source file error: {msg}")
        
        # Check if source file exists
        if not os.path.exists(real_source_path):
            error_msg = f"Source file {source_path} does not exist."
            self.do_callback(False, source_path, error_msg)
            return str_error(error_msg)
        
        # Check destination path
        dest_real_path = os.path.abspath(os.path.join(self.workspace, dest_path))
        if not dest_real_path.startswith(self.workspace):
            error_msg = f"Destination path '{dest_path}' is not within the workspace."
            self.do_callback(False, dest_path, error_msg)
            return str_error(error_msg)
        
        # Check write permissions for destination
        write_able, msg = is_file_writeable(dest_path, self.un_write_able_dirs, self.write_able_dirs)
        if not write_able:
            self.do_callback(False, dest_path, msg)
            return str_error(f"Destination file error: {msg}")
        
        # Check if destination exists
        if os.path.exists(dest_real_path) and not overwrite:
            error_msg = f"Destination file {dest_path} already exists. Use overwrite=True to replace it."
            self.do_callback(False, dest_path, error_msg)
            return str_error(error_msg)
        
        try:
            # Create destination directory if needed
            dest_dir = os.path.dirname(dest_real_path)
            if not os.path.exists(dest_dir):
                os.makedirs(dest_dir, exist_ok=True)
                info(f"Created destination directory: {dest_dir}")
            
            # Copy the file
            shutil.copy2(real_source_path, dest_real_path)
            info(f"Copied file from {real_source_path} to {dest_real_path}")
            
            # Get file sizes for confirmation
            source_size = get_file_size(real_source_path)
            dest_size = get_file_size(dest_real_path)
            
            self.do_callback(True, dest_path, f"File copied successfully: {source_size} bytes")
            return str_info(f"File copied successfully from '{source_path}' to '{dest_path}' ({bytes_to_human_readable(source_size)})")
            
        except (IOError, OSError) as e:
            error_msg = f"Failed to copy file: {str(e)}"
            self.do_callback(False, dest_path, error_msg)
            return str_error(error_msg)

    def __init__(self, workspace: str, write_dirs=None, un_write_dirs=None, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace, write_dirs, un_write_dirs)


class ArgMoveFile(BaseModel):
    source_path: str = Field(
        default=None,
        description="Source file path to move from, relative to the workspace."
    )
    dest_path: str = Field(
        default=None,
        description="Destination file path to move to, relative to the workspace."
    )
    overwrite: bool = Field(
        default=False,
        description="If True, overwrite destination file if it exists. If False, return error if destination exists."
    )


class MoveFile(UCTool, BaseReadWrite):
    """Move/rename a file from source to destination within the workspace."""
    name: str = "MoveFile"
    description: str = (
        "Move or rename a file from source to destination within the workspace. "
        "Creates destination directory if it doesn't exist. Optionally overwrites existing files."
    )
    args_schema: Optional[ArgsSchema] = ArgMoveFile
    return_direct: bool = False

    def _run(self, source_path: str, dest_path: str, overwrite: bool = False,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Move a file from source to destination."""
        # Check source file
        success, msg, real_source_path = self.check_file(source_path)
        if not success:
            self.do_callback(False, source_path, msg)
            return str_error(f"Source file error: {msg}")
        
        # Check if source file exists
        if not os.path.exists(real_source_path):
            error_msg = f"Source file {source_path} does not exist."
            self.do_callback(False, source_path, error_msg)
            return str_error(error_msg)
        
        # Check destination path
        dest_real_path = os.path.abspath(os.path.join(self.workspace, dest_path))
        if not dest_real_path.startswith(self.workspace):
            error_msg = f"Destination path '{dest_path}' is not within the workspace."
            self.do_callback(False, dest_path, error_msg)
            return str_error(error_msg)
        
        # Check write permissions for both source and destination
        write_able_src, msg_src = is_file_writeable(source_path, self.un_write_able_dirs, self.write_able_dirs)
        if not write_able_src:
            self.do_callback(False, source_path, msg_src)
            return str_error(f"Source file error: {msg_src}")
            
        write_able_dest, msg_dest = is_file_writeable(dest_path, self.un_write_able_dirs, self.write_able_dirs)
        if not write_able_dest:
            self.do_callback(False, dest_path, msg_dest)
            return str_error(f"Destination file error: {msg_dest}")
        
        # Check if destination exists
        if os.path.exists(dest_real_path) and not overwrite:
            error_msg = f"Destination file {dest_path} already exists. Use overwrite=True to replace it."
            self.do_callback(False, dest_path, error_msg)
            return str_error(error_msg)
        
        try:
            # Create destination directory if needed
            dest_dir = os.path.dirname(dest_real_path)
            if not os.path.exists(dest_dir):
                os.makedirs(dest_dir, exist_ok=True)
                info(f"Created destination directory: {dest_dir}")
            
            # Move the file
            shutil.move(real_source_path, dest_real_path)
            info(f"Moved file from {real_source_path} to {dest_real_path}")
            
            # Get file size for confirmation
            dest_size = get_file_size(dest_real_path)
            
            self.do_callback(True, dest_path, f"File moved successfully: {dest_size} bytes")
            return str_info(f"File moved successfully from '{source_path}' to '{dest_path}' ({bytes_to_human_readable(dest_size)})")
            
        except (IOError, OSError) as e:
            error_msg = f"Failed to move file: {str(e)}"
            self.do_callback(False, dest_path, error_msg)
            return str_error(error_msg)

    def __init__(self, workspace: str, write_dirs=None, un_write_dirs=None, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace, write_dirs, un_write_dirs)


class ArgDeleteFile(BaseModel):
    path: str = Field(
        default=None,
        description="File path to delete, relative to the workspace."
    )
    is_dir: bool = Field(
        default=False,
        description="If True, means path is a directory to delete, otherwise a file."
    )
    recursive: bool = Field(
        default=False,
        description="If True and is_dir is True, recursively delete directory and all its contents. Use with caution!"
    )


class DeleteFile(UCTool, BaseReadWrite):
    """Delete a file or directory in the workspace with optional recursive deletion."""
    name: str = "DeleteFile"
    description: str = (
        "Delete a file or directory in the workspace. "
        "Supports recursive deletion for directories with all their contents. "
        "If file/directory does not exist, returns an error message."
    )
    args_schema: Optional[ArgsSchema] = ArgDeleteFile
    return_direct: bool = False

    def _run(self, path: str, is_dir: bool = False, recursive: bool = False,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Delete a file or directory in the workspace."""
        target_path = os.path.abspath(os.path.join(self.workspace, path))
        if not os.path.exists(target_path):
            emsg = f"Path {path} does not exist in workspace"
            self.do_callback(False, path, emsg)
            return str_error(emsg)
        
        ok, emsg = is_file_writeable(path, self.un_write_able_dirs, self.write_able_dirs)
        if not ok:
            self.do_callback(False, path, emsg)
            return str_error(emsg)
        
        try:
            if os.path.isdir(target_path):
                if not is_dir:
                    emsg = f"Path {path} is a directory, but 'is_dir' is False. Please set 'is_dir' to True to delete directories."
                    self.do_callback(False, path, emsg)
                    return str_error(emsg)
                
                # Check if directory is empty (unless recursive is True)
                if not recursive and os.listdir(target_path):
                    emsg = f"Directory {path} is not empty. Use 'recursive=True' to delete non-empty directories."
                    self.do_callback(False, path, emsg)
                    return str_error(emsg)
                
                if recursive:
                    info(f"Recursively deleting directory {target_path} and all its contents.")
                    shutil.rmtree(target_path)
                    self.do_callback(True, path, f"Directory {path} and all contents deleted recursively.")
                    return str_info(f"Directory {path} and all its contents deleted successfully.")
                else:
                    info(f"Deleting empty directory {target_path}.")
                    os.rmdir(target_path)
                    self.do_callback(True, path, f"Empty directory {path} deleted.")
                    return str_info(f"Empty directory {path} deleted successfully.")
            else:
                if is_dir:
                    emsg = f"Path {path} is a file, but 'is_dir' is True. Please set 'is_dir' to False to delete files."
                    self.do_callback(False, path, emsg)
                    return str_error(emsg)
                
                info(f"Deleting file {target_path}.")
                os.remove(target_path)
                self.do_callback(True, path, f"File {path} deleted.")
                return str_info(f"File {path} deleted successfully.")
        
        except (IOError, OSError) as e:
            error_msg = f"Failed to delete {path}: {str(e)}"
            self.do_callback(False, path, error_msg)
            return str_error(error_msg)

    def __init__(self, workspace: str, write_dirs=None, un_write_dirs=None, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace, write_dirs, un_write_dirs)


class ArgCreateDirectory(BaseModel):
    path: str = Field(
        default=None,
        description="Directory path to create, relative to the workspace."
    )
    parents: bool = Field(
        default=True,
        description="If True, create parent directories as needed. If False, fail if parent doesn't exist."
    )
    exist_ok: bool = Field(
        default=True,
        description="If True, don't raise an error if directory already exists. If False, fail if directory exists."
    )


class CreateDirectory(UCTool, BaseReadWrite):
    """Create a directory in the workspace with optional parent directory creation."""
    name: str = "CreateDirectory"
    description: str = (
        "Create a directory in the workspace. "
        "Optionally creates parent directories and handles existing directories gracefully."
    )
    args_schema: Optional[ArgsSchema] = ArgCreateDirectory
    return_direct: bool = False

    def _run(self, path: str, parents: bool = True, exist_ok: bool = True,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Create a directory in the workspace."""
        target_path = os.path.abspath(os.path.join(self.workspace, path))
        
        # Check if path is within workspace
        if not target_path.startswith(self.workspace):
            error_msg = f"Directory path '{path}' is not within the workspace."
            self.do_callback(False, path, error_msg)
            return str_error(error_msg)
        
        # Check write permissions
        write_able, msg = is_file_writeable(path, self.un_write_able_dirs, self.write_able_dirs)
        if not write_able:
            self.do_callback(False, path, msg)
            return str_error(f"Directory creation error: {msg}")
        
        # Check if directory already exists
        if os.path.exists(target_path):
            if os.path.isfile(target_path):
                error_msg = f"Path {path} already exists as a file, cannot create directory."
                self.do_callback(False, path, error_msg)
                return str_error(error_msg)
            elif os.path.isdir(target_path):
                if exist_ok:
                    self.do_callback(True, path, f"Directory {path} already exists.")
                    return str_info(f"Directory {path} already exists.")
                else:
                    error_msg = f"Directory {path} already exists. Use exist_ok=True to ignore this error."
                    self.do_callback(False, path, error_msg)
                    return str_error(error_msg)
        
        try:
            # Create the directory
            if parents:
                os.makedirs(target_path, exist_ok=exist_ok)
                info(f"Created directory {target_path} with parents.")
            else:
                os.mkdir(target_path)
                info(f"Created directory {target_path}.")
            
            self.do_callback(True, path, f"Directory {path} created successfully.")
            return str_info(f"Directory {path} created successfully.")
        
        except FileExistsError:
            error_msg = f"Directory {path} already exists."
            self.do_callback(False, path, error_msg)
            return str_error(error_msg)
        except FileNotFoundError:
            error_msg = f"Parent directory does not exist for {path}. Use parents=True to create parent directories."
            self.do_callback(False, path, error_msg)
            return str_error(error_msg)
        except (IOError, OSError) as e:
            error_msg = f"Failed to create directory {path}: {str(e)}"
            self.do_callback(False, path, error_msg)
            return str_error(error_msg)

    def __init__(self, workspace: str, write_dirs=None, un_write_dirs=None, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace, write_dirs, un_write_dirs)


class ArgReplaceStringInFile(BaseModel):
    path: str = Field(
        default=None,
        description="Text file path to modify, relative to the workspace.")
    old_string: str = Field(
        default=None,
        description="The exact literal text to replace. Must include at least 3 lines of context BEFORE and AFTER the target text, matching whitespace and indentation precisely. If this string does not match exactly, the tool will fail.")
    new_string: str = Field(
        default=None,
        description="The exact literal text to replace old_string with. Ensure the resulting code is correct and idiomatic.")


class ReplaceStringInFile(UCTool, BaseReadWrite):
    """Replace exact string content in a text file with precise string matching."""
    name: str = "ReplaceStringInFile"
    description: str = (
        "Replace exact string content in a text file. This tool performs precise string matching and replacement. "
        "The old_string must match exactly (including whitespace, indentation, newlines, and surrounding code), if empty will replace the whole file content. "
        "Include at least 3-5 lines of context BEFORE and AFTER the target text to ensure unique identification. "
        "Each use of this tool replaces exactly ONE occurrence of old_string. "
        "If this target file not exists, the tool will create it and write the new_string into it. "
        "If the string matches multiple locations or does not match exactly, the tool will fail. "
        "Example usage:\n"
        "old_string: 'def old_function():\\n    # TODO: implement\\n    pass\\n    return 0'\n"
        "new_string: 'def new_function():\\n    \"\"\"New implementation\"\"\"\\n    result = calculate()\\n    return result'\n"
        "Critical: old_string must uniquely identify the single instance to change and match precisely."
    )
    args_schema: Optional[ArgsSchema] = ArgReplaceStringInFile
    return_direct: bool = False

    def _run(self, path: str, old_string: str, new_string: str,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Replace exact string content in a text file."""
        self.create_file = True
        # Validate inputs
        if new_string is None:
            error_msg = "new_string cannot be None. Use empty string if you want to delete the content."
            self.do_callback(False, path, error_msg)
            return str_error(error_msg)

        success, msg, real_path = self.check_file(path)
        if not success:
            self.do_callback(False, path, msg)
            return str_error(msg)

        if new_string == old_string:
            error_msg = f"new_string is identical to old_string ({old_string}). No changes made."
            self.do_callback(False, path, error_msg)
            return str_error(error_msg)
        
        # Check if it's a text file
        if not is_text_file(real_path):
            error_msg = f"File {path} is not a text file."
            self.do_callback(False, path, error_msg)
            return str_error(error_msg)
        info(f"Replacing string in file {real_path}")
        try:
            # Read file content
            with open(real_path, 'r', encoding='utf-8') as f:
                original_content = f.read()
            new_content = new_string
            if old_string:
                # Check if old_string exists in the file
                if old_string not in original_content:
                    error_msg = f"The specified old_string was not found in the file. The string must match exactly including all whitespace, indentation, and newlines."
                    self.do_callback(False, path, error_msg)
                    return str_error(error_msg)
                # Count occurrences to ensure uniqueness
                occurrence_count = original_content.count(old_string)
                if occurrence_count == 0:
                    error_msg = f"The specified old_string was not found in the file."
                    self.do_callback(False, path, error_msg)
                    return str_error(error_msg)
                elif occurrence_count > 1:
                    error_msg = f"The specified old_string appears {occurrence_count} times in the file. The string must be unique. Include more context to make it unique."
                    self.do_callback(False, path, error_msg)
                    return str_error(error_msg)
                # Perform the replacement
                new_content = original_content.replace(old_string, new_string, 1)

            # Write the new content back to the file
            with open(real_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
                f.flush()

            # Generate diff for better understanding
            original_lines = original_content.splitlines(keepends=True)
            new_lines = new_content.splitlines(keepends=True)
            diff_result = get_diff(original_lines, new_lines, path)

            success_msg = f"Successfully replaced 1 occurrence of the specified string in {path}."
            self.do_callback(True, path, {"old_string": old_string, "new_string": new_string})

            return str_info(success_msg) + diff_result

        except UnicodeDecodeError as e:
            error_msg = f"Failed to decode file {path} as UTF-8: {str(e)}"
            self.do_callback(False, path, error_msg)
            return str_error(error_msg)
        except IOError as e:
            error_msg = f"Failed to modify file {path}: {str(e)}"
            self.do_callback(False, path, error_msg)
            return str_error(error_msg)

    def __init__(self, workspace: str, write_dirs=None, un_write_dirs=None, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace, write_dirs, un_write_dirs)


class ArgGetFileInfo(BaseModel):
    path: str = Field(
        default=None,
        description="File or directory path to get information about, relative to the workspace."
    )
    include_stats: bool = Field(
        default=True,
        description="If True, include detailed file statistics (size, modification time, permissions, etc.)."
    )


class GetFileInfo(UCTool, BaseReadWrite):
    """Get detailed information about a file or directory in the workspace."""
    name: str = "GetFileInfo"
    description: str = (
        "Get detailed information about a file or directory including size, type, "
        "modification time, permissions, and other metadata."
    )
    args_schema: Optional[ArgsSchema] = ArgGetFileInfo
    return_direct: bool = False

    def _run(self, path: str, include_stats: bool = True,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Get information about a file or directory."""
        target_path = os.path.abspath(os.path.join(self.workspace, path))
        
        # Check if path is within workspace
        if not target_path.startswith(self.workspace):
            error_msg = f"Path '{path}' is not within the workspace."
            self.do_callback(False, path, error_msg)
            return str_error(error_msg)
        
        # Check if path exists
        if not os.path.exists(target_path):
            error_msg = f"Path {path} does not exist in workspace."
            self.do_callback(False, path, error_msg)
            return str_error(error_msg)
        
        try:
            info_lines = []
            info_lines.append(f"Path: {path}")
            info_lines.append(f"Absolute path: {target_path}")
            
            if os.path.isfile(target_path):
                info_lines.append("Type: File")
                
                # File size
                file_size = get_file_size(target_path)
                info_lines.append(f"Size: {bytes_to_human_readable(file_size)} ({file_size} bytes)")
                
                # File type detection
                is_text = is_text_file(target_path)
                info_lines.append(f"File type: {'Text' if is_text else 'Binary'}")
                
                if is_text:
                    # Line count for text files
                    try:
                        with open(target_path, 'r', encoding='utf-8') as f:
                            line_count = sum(1 for _ in f)
                        info_lines.append(f"Line count: {line_count}")
                    except (UnicodeDecodeError, IOError):
                        info_lines.append("Line count: Unable to determine (encoding error)")
                
            elif os.path.isdir(target_path):
                info_lines.append("Type: Directory")
                
                # Count contents
                try:
                    contents = os.listdir(target_path)
                    file_count = sum(1 for item in contents if os.path.isfile(os.path.join(target_path, item)))
                    dir_count = sum(1 for item in contents if os.path.isdir(os.path.join(target_path, item)))
                    info_lines.append(f"Contains: {file_count} files, {dir_count} directories")
                except (IOError, OSError):
                    info_lines.append("Contents: Unable to list (permission error)")
            
            if include_stats:
                import stat
                import time
                
                stat_info = os.stat(target_path)
                
                # Permissions
                mode = stat_info.st_mode
                permissions = stat.filemode(mode)
                info_lines.append(f"Permissions: {permissions}")
                
                # Timestamps
                mod_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat_info.st_mtime))
                access_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat_info.st_atime))
                create_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat_info.st_ctime))
                
                info_lines.append(f"Modified: {mod_time}")
                info_lines.append(f"Accessed: {access_time}")
                info_lines.append(f"Created/Changed: {create_time}")
                
                # Owner and group (on Unix-like systems)
                if hasattr(stat_info, 'st_uid') and hasattr(stat_info, 'st_gid'):
                    info_lines.append(f"Owner UID: {stat_info.st_uid}")
                    info_lines.append(f"Group GID: {stat_info.st_gid}")
            
            result = "\n".join(info_lines)
            self.do_callback(True, path, result)
            return str_info(f"\nFile information for '{path}':\n\n") + str_return(result)
            
        except (IOError, OSError) as e:
            error_msg = f"Failed to get file information for {path}: {str(e)}"
            self.do_callback(False, path, error_msg)
            return str_error(error_msg)

    def __init__(self, workspace: str, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace)
