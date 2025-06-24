#coding=utf-8

from typing import Optional, List, Tuple
from vagent.util.log import info, str_info, str_return, str_error, str_warning, str_data, warning
from vagent.util.functions import is_text_file, get_file_size, bytes_to_human_readable, copy_indent_from
from .uctool import UCTool

from langchain_core.callbacks import (
    CallbackManagerForToolRun,
)
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field

import os
import fnmatch


def is_file_writeable(path: str, un_write_dirs: list=None, write_dirs: list=None) -> Tuple[bool, str]:
    if path.startswith("/"):
        path = path[1:]  # remove leading slash for relative check
    if un_write_dirs is None and write_dirs is None:
        return True, "No write restrictions defined."
    if write_dirs is not None:
        assert isinstance(write_dirs, list), "write_dirs must be a list."
        for d in write_dirs:
            if path.startswith(d):
                return True, f"Path '{path}' is allowed to write in directory '{d}'."
        return False, f"Path '{path}' is not allowed to write in any of the specified directories: {write_dirs}."
    if un_write_dirs is not None:
        assert isinstance(un_write_dirs, list), "un_write_dirs must be a list."
        for d in un_write_dirs:
            if path.startswith(d):
                return False, f"Path '{path}' is not allowed to write in directory '{d}'."
        return True, f"Path '{path}' is allowed to write as it does not match any no-write directories: {un_write_dirs}."
    return True, "Not implemented yet."


class BaseReadWrite:
    """Base class for write operations."""

    # custom variables
    workspace: str = Field(
        default=".",
        description="Workspace directory to modify files in."
    )
    max_read_size: int = Field(
        default=30720,
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

    def init_base_rw(self, workspace: str, write_dirs=None, un_write_dirs=None, max_read_size: int = 30720):
        """Initialize the base write tool."""
        assert os.path.exists(workspace), f"Workspace {workspace} does not exist."
        self.workspace = os.path.abspath(workspace)
        self.write_able_dirs = write_dirs
        self.un_write_able_dirs = un_write_dirs
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

    def check_file(self, path: str) -> Tuple[bool, str]:
        """Check if the file is writable."""
        if path.endswith('/'):
            return False, f"Path '{path}' should not end with a slash. Please provide a file path, not a directory.", ""
        write_able, msg = is_file_writeable(path, self.un_write_able_dirs, self.write_able_dirs)
        if not write_able:
            return False, msg, ""
        real_path = os.path.abspath(os.path.join(self.workspace, path))
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
                return False, f"File {path} does not exist in workspace. Please create it first.", ""
        return True, "", real_path

    def check_dir(self, path: str) -> Tuple[bool, str]:
        """Check if the directory is exist."""
        real_path = os.path.abspath(os.path.join(self.workspace, path))
        if real_path.startswith(self.workspace) is False:
            return False, str_error(f"Path '{path}' is not within the workspace."), ""
        if not os.path.exists(real_path):
            return False, str_error(f"Path {path} does not exist in workspace."), ""
        if not os.path.isdir(real_path):
            return False, str_error(f"Path {path} is not a directory in workspace."), ""
        return True, "", real_path


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
        "Returns a list with index, name, type, and size."
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
                result.append(f"{index}\t{directory}/".strip() + "\t(type: directory, size: N/A, bytes: N/A)")
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
                result.append(f"{index}\t{tfile_path.strip()}" + f"\t(type: {file_type}, size: {file_size}, bytes: {bytes_count})")
                index += 1
                count_files += 1
        if result:
            ret_head = str_info(f"\nFound {count_directories} directories and {count_files} files in workspace.\n\n")
            result.insert(0, f"Index\tName\t(Type, Size, Bytes)")
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

    def __init__(self, workspace: str, max_read_size: int = 30720, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace, max_read_size=max_read_size)
        self.description = self.description % self.max_read_size


class ArgReadTextFile(BaseModel):
    path: str = Field(
        default=None,
        description="Text file path to read, relative to the workspace.")
    start: int = Field(
        default=0,
        description="Start line index (0-based)."
    )
    count: int = Field(
        default=-1,
        description="Number of lines to read. -1 means to end of file."
    )


class ReadTextFile(UCTool, BaseReadWrite):
    """Read lines from a text file in the workspace."""
    name: str = "ReadTextFile"
    description: str = (
        "Read lines from a text file in the workspace. Supports start line and line count. "
        "Max read size is %d characters. Each line is prefixed with its index."
        "Note: The file content in return data is after prefix '[TXT_DATA]\\n' and each line has prefix '<index>: '.\n"
        "For example, the raw data in file is:\n"
        "line 1\nline 2\nline 3\n"
        "while the returned file content is:\n"
        "[TXT_DATA]\n"
        "0: line 1\n1: line 2\n2: line 3\n"
        "The line index starts from 0. "
    )
    args_schema: Optional[ArgsSchema] = ArgReadTextFile
    return_direct: bool = False

    def _run(self, path: str, start: int = 0, count: int = -1,
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
        with open(real_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            lines_count = len(lines)
            if start < 0 or start >= len(lines):
                emsg = f"Start line {start} is out of range(0-{lines_count}) for file {path}."
                self.do_callback(False, path, emsg)
                return str_error(emsg)
            r_count = count
            if r_count == -1 or start + r_count > len(lines):
                r_count = len(lines) - start
            content = ''.join(["%d: %s" % (i + start, l) for i, l in enumerate(lines[start:start + r_count])])
            if len(content) > self.max_read_size:
                emsg = f"Read size {len(content)} characters exceeds the maximum read size of {self.max_read_size} characters. " +\
                                 f"You need to specify a smaller range. current range is ({start}, +{str(count) if count >=0 else 'MAX'})."
                self.do_callback(False, path, emsg)
                return str_error(emsg)
            ret_head = str_info(f"\nRead {r_count}/{lines_count} lines with args (start={start}, count={count}), {lines_count - r_count - start} lines remain after the read position.\n\n")
            self.do_callback(True, path, content)
            return ret_head + str_data(content, "TXT_DATA")

    def __init__(self, workspace: str, max_read_size: int = 30720, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace, max_read_size=max_read_size)
        self.description = self.description % self.max_read_size
        info(f"ReadTextFile tool initialized with workspace: {self.workspace}")


class ArgTextFileReplace(BaseModel):
    path: str = Field(
        default=None,
        description="Text file path to modify, relative to the workspace.")
    start: int = Field(
        default=0,
        description="Start line index (form 0 to file lines - 1) to replace. If index < 0 insert at head, if index >= file lines append at end."
    )
    count: int = Field(
        default=-1,
        description="Number of lines to replace. 0: means insert, -1: means to end of file."
    )
    data: str = Field(
        default=None,
        description="New lines of data to replace the target lines. If None, target `count` of lines from `start` are removed."
    )
    preserve_indent: bool = Field(
        default=False,
        description= "If True, preserve the indentation of the original lines when replacing, "
        "if the new data lines is more than the target lines, the extra lines will preserved the indentation of the last target line."
    )


class TextFileReplace(UCTool, BaseReadWrite):
    """Replace or insert a block of lines in a text file at the target position"""
    name: str = "TextFileReplace"
    description: str = (
        "Replace or insert a block of lines in a text file at the target position. "
        "If file does not exist, creates it. Line index starts from 0."
        "eg:\n "
        "the original file content is:\n"
        "line 1\n" \
        "line 2\n" \
        "line 3\n" \
        "the replace operation with (start=1, count=1, data='new line', preserve_indent=False) will result in:\n"
        "line 1\n" \
        "new line\n" \
        "line 3\n"
        "If you just write all the text to file, you should use 'WriteToFile' tool instead.\n"
        "If you want to replace multiple blocks of lines, use 'TextFileMultiReplace' tool instead.\n"
    )
    args_schema: Optional[ArgsSchema] = ArgTextFileReplace
    return_direct: bool = False

    def _run(self, path: str, start: int = 0, count: int = -1, data: str = None, preserve_indent: bool = False,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Replace the content of a text file in the workspace."""
        success, msg, real_path = self.check_file(path)
        if not success:
            self.do_callback(False, path, msg)
            return str_error(msg)
        if not is_text_file(real_path):
            emsg = f"File {path} is not a text file. Please use 'ReadBinFile' to read binary files."
            self.do_callback(False, path, emsg)
            return str_error(emsg)
        info(f"Replacing text file {real_path} from line {start} with count {count}")
        with open(real_path, 'r+', encoding='utf-8') as f:
            lines = f.readlines()
            lines_pred = lines[:max(0, start)]
            lines_after = []
            if count >= 0:
                lines_after = lines[max(0, start) + count:]
            lines_insert = []
            if data is not None:
                if preserve_indent:
                    lines_insert = ["\n".join(copy_indent_from(lines[start:start + max(1, count)], data.split("\n"))) + "\n"]
                else:
                    lines_insert = [data + "\n"]
            # write the new content
            f.seek(0)
            f.truncate(0)
            f.writelines(lines_pred + lines_insert + lines_after)
            f.flush()
            self.do_callback(True, path, {"start": start, "count": count, "data": data})
            if data is None:
                ret_info = str_info(f"Removed {count} lines starting from line {start} complete.")
            else:
                ret_info = str_info(f"Replaced {count} lines starting from line {start} with new data complete.")
            return str_info(ret_info)

    def __init__(self, workspace: str, write_dirs=None, un_write_dirs=None, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace, write_dirs, un_write_dirs)


class ArgTextFileMultiReplace(BaseModel):
    path: str = Field(
        default=None,
        description="File path to multi-replace, relative to the workspace."
    )
    values: List[Tuple[int, int, str, bool]] = Field(
        default=[],
        description=(
            "List of edits: [(index, count, data, preserve_indent), ...].\n"
            "- index: int, form 0 to file lines - 1. If index < 0 insert at head, if index >= file lines append at end.\n"
            "- count: int, number of lines to replace. 0: insert. `count` must be positive value.\n"
            "- data: str, the new data to replace or insert. If None, delete the `count` lines start from `index`.\n"
            "- preserve_indent: bool, False for direct replace; True for replace with the same indentation as the original line, "
            "if the new data lines is more than the target lines, the extra lines will preserved the indentation of the last target line.\n"
            "Each target block (index, index+count) must be unique, with no intersections.\n"
        )
    )


class TextFileMultiReplace(UCTool, BaseReadWrite):
    """Replace or insert multiple blocks of lines in a text file at target positions"""
    name: str = "TextFileMultiReplace"
    description: str = (
        "Replace or insert multiple blocks of lines in a text file at target positions. The file must exist. \n"
        "Supports direct replacement or preserving original line indentation.\n"
        "eg:\n"
        "the original file content is:\n"
        "line 1\n"
        "    line 2\n"
        "line 3\n"
        "the multi-replace operation with values=[(1, 1, 'new line a\\n  new line b', False), (2, 0, 'inserted line c', True)] will result in:\n"
        "line 1\n"
        "new line a\n"
        "  new line b\n"
        "inserted line c\n"
        "line 3\n"
        "If you just write all the text to file, you should use 'WriteToFile' tool instead.\n"
        "If you want to replace just one block of lines, use 'TextFileReplace' tool instead.\n"
    )
    args_schema: Optional[ArgsSchema] = ArgTextFileMultiReplace
    return_direct: bool = False

    def _run(self, path: str, values: List[Tuple[int, int, str, int]],
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Replace or insert multiple blocks of lines in a text file at target positions.
        The values should be a list of tuples: (index, count, data, preserve_indent).
        """
        success, msg, real_path = self.check_file(path)
        if not success:
            self.do_callback(False, path, msg)
            return str_error(msg)
        if not is_text_file(real_path):
            emsg = f"File {path} is not a text file. Please use 'ReadBinFile' to read binary files."
            self.do_callback(False, path, emsg)
            return str_error(emsg)
        info(f"Editing text file {real_path} with values {values}")
        final_data = []
        with open(real_path, 'r+', encoding='utf-8') as f:
            lines = f.readlines()
            # check overlaped target sections
            values = sorted(values, key=lambda x: x[0])
            for i, (index, count, _, _) in enumerate(values):
                if count < 0:
                    emsg = f"`count` in block-{i} must be postive or zero"
                    self.do_callback(False, path, emsg)
                    return str_error(emsg)
                if i == 0:
                    continue
                p_index, p_count = values[i - 1][0], values[i - 1][1]
                if not (index >= (p_index + p_count)):
                    emsg = f"Target block-{i} ({index}:{index+count}) is overlaped with previous target block-{i-1} ({p_index}:{p_index+p_count}). Please provide unique line indices in ascending order."
                    self.do_callback(False, path, emsg)
                    return str_error(emsg)
            end_index = 0
            for index, count, data, preserve_indent in values:
                if index < 0:
                    if data is not None:
                        final_data.append([data + "\n"])
                    continue
                final_data.append(lines[end_index: index])
                insert_lines = []
                if data is not None:
                    if preserve_indent:
                        src_lines = lines[index:index + max(1, count)]
                        insert_lines = ["\n".join(copy_indent_from(src_lines, data.split("\n"))) + "\n"]
                    else:
                        insert_lines = [data + "\n"]
                end_index = index + count
                final_data.append(insert_lines)
            final_data.append(lines[end_index:])
        # write the new content
        data = [i for sublist in final_data for i in sublist]  # flatten the list
        with open(real_path, 'w', encoding='utf-8') as f:
            f.writelines(data)
            f.flush()
        ret_info = str_info(f"MultiReplace complete.")
        self.do_callback(True, path, ret_info)
        return ret_info

    def __init__(self, workspace: str, write_dirs=None, un_write_dirs=None, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace, write_dirs, un_write_dirs)

class ArgWriteToFile(BaseModel):
    path: str = Field(
        default=None,
        description="File path to write, relative to the workspace. Created if not exists."
    )
    data: str = Field(
        default=None,
        description="String data to write. If not set, file will be cleared."
    )


class WriteToFile(UCTool, BaseReadWrite):
    """Write string data to a file in the workspace."""
    name: str = "WriteToFile"
    description: str = (
        "Write string data to a file in the workspace. Overwrites existing content. "
        "Creates file if it does not exist."
    )
    args_schema: Optional[ArgsSchema] = ArgWriteToFile
    return_direct: bool = False

    def _run(self, path: str, data: str = None,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Write data to a file in the workspace."""
        self.create_file = True  # ensure file is created if not exists
        success, msg, real_path = self.check_file(path)
        if not success:
            self.do_callback(False, path, msg)
            return str_error(msg)
        with open(real_path, 'w', encoding='utf-8') as f:
            if data is None:
                info(f"Clearing file {real_path}.")
                f.truncate(0)
            else:
                info(f"Writing data to file {real_path}.")
                f.write(data)
            f.flush()
            self.do_callback(True, path, data)
            return str_info(f"Write {len(data)} characters complete." if data else f"File({path}) cleared.")

    def __init__(self, workspace: str, write_dirs=None, un_write_dirs=None, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace, write_dirs, un_write_dirs)


class AppendToFile(UCTool, BaseReadWrite):
    """Append string data to a file in the workspace."""
    name: str = "AppendToFile"
    description: str = (
        "Append string data to a file in the workspace. Creates file if it does not exist."
        "If data is None, clears the file content."
    )
    args_schema: Optional[ArgsSchema] = ArgWriteToFile
    return_direct: bool = False

    def _run(self, path: str, data: str = None,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Append data to a file in the workspace."""
        self.create_file = True  # ensure file is created if not exists
        success, msg, real_path = self.check_file(path)
        if not success:
            self.do_callback(False, path, msg)
            return str_error(msg)
        with open(real_path, 'a', encoding='utf-8') as f:
            if data is None:
                info(f"Clearing file {real_path}.")
                f.truncate(0)
            else:
                info(f"Appending data to file {real_path}.")
                f.write(data)
            f.flush()
            self.do_callback(True, path, data)
            return str_info(f"Append {len(data)} characters complete." if data else f"File({path}) cleared.")

    def __init__(self, workspace: str, write_dirs=None, un_write_dirs=None, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace, write_dirs, un_write_dirs)


class ArgDeleteFile(BaseModel):
    path: str = Field(
        default=None,
        description="File path to write, relative to the workspace. Created if not exists."
    )
    is_dir: bool = Field(
        default=False,
        description="If True, means path is a directory to delete, otherwise a file."
    )


class DeleteFile(UCTool, BaseReadWrite):
    """Delete a file in the workspace."""
    name: str = "DeleteFile"
    description: str = (
        "Delete a file in the workspace. "
        "If file does not exist, returns an error message. "
    )
    args_schema: Optional[ArgsSchema] = ArgDeleteFile
    return_direct: bool = False

    def _run(self, path: str, is_dir: bool = False,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Delete a file in the workspace."""
        target_path = os.path.abspath(os.path.join(self.workspace, path))
        if not os.path.exists(target_path):
            emsg = f"File {path} does not exist in workspace"
            self.do_callback(False, path, emsg)
            return str_error(emsg)
        if os.path.isdir(target_path):
            if not is_dir:
                emsg = f"Path {path} is a directory, but 'is_dir' is False. Please set 'is_dir' to True to delete directories."
                self.do_callback(False, path, emsg)
                return str_error(emsg)
            info(f"Deleting directory {target_path}.")
            os.rmdir(target_path)
            self.do_callback(True, path, f"Directory {path} deleted.")
        else:
            if is_dir:
                emsg = f"Path {path} is a file, but 'is_dir' is True. Please set 'is_dir' to False to delete files."
                self.do_callback(False, path, emsg)
                return str_error(emsg)
            info(f"Deleting file {target_path}.")
            os.remove(target_path)
            self.do_callback(True, path, f"File {path} deleted.")
        return str_info(f"File {path} deleted successfully." if not is_dir else f"Directory {path} deleted successfully.")

    def __init__(self, workspace: str, write_dirs=None, un_write_dirs=None, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace, write_dirs, un_write_dirs)
