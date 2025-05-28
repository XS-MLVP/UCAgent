#coding=utf-8

from typing import Optional
from vagent.util.log import info, str_info, str_return, str_error
from vagent.util.functions import is_text_file, get_file_size, bytes_to_human_readable

from langchain_core.callbacks import (
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field

import os
import fnmatch


class ArgListPath(BaseModel):
    path: str = Field(
        default=".",  # Default to current directory
        description="directory path to list files from, relative to the workspace")
    depth: int = Field(
        default=-1, description="depth of subdirectories to list, -1 means to the deepest level, 0 means only the current directory"
    )


class ListPath(BaseTool):
    name: str = "ListPath"
    description: str = "used to list all the files in a directory of the workspace, including subdirectories. "
    args_schema: Optional[ArgsSchema] = ArgListPath
    return_direct: bool = False

    # custom variables
    workspace: str = Field(
        default=".",  # Default to current directory
        description="the workspace directory to list files from")

    ignore_pattern: list = Field(
        default=["*__pycache__*"],
        description="a pattern to ignore files or directories, e.g., '*.tmp' to ignore temporary files"
    )

    def _run(
        self, path: str, depth: int = -1, run_manager: Optional[CallbackManagerForToolRun] = None
    ) -> str:
        """List all files in a directory of the workspace, including subdirectories."""
        real_path = os.path.abspath(os.path.join(self.workspace, path))
        if real_path.startswith(self.workspace) is False:
            return str_error(f"Path '{path}' is not within the workspace.")
        info(f"Listing files in {real_path} with depth {depth}")
        if not os.path.exists(real_path):
            return str_error(f"Path {path} does not exist in workspace.")
        if not os.path.isdir(real_path):
            return str_error(f"Path {path} is not a directory in workspace.")
        if depth < 0:
            depth = float('inf')
        result = []
        count_directories = 0
        count_files = 0
        for root, _, files in os.walk(real_path):
            level = root.replace(real_path, '').count(os.sep)
            if level > depth:
                continue
            directory =  os.path.relpath(root, self.workspace)
            if any(fnmatch.fnmatch(directory, pattern) for pattern in self.ignore_pattern):
                continue
            if not directory == ".":
                result.append(f"{directory}/".strip())
                count_directories += 1
            for file in files:
                tfile_path = os.path.join(directory, file)
                if tfile_path.startswith("./"):
                    tfile_path = tfile_path[2:]
                if any(fnmatch.fnmatch(tfile_path, pattern) for pattern in self.ignore_pattern):
                    continue
                # get the lines of the file
                # check if the file is a text file
                absolute_file_path = os.path.join(self.workspace, tfile_path)
                file_type = "binary" if not is_text_file(absolute_file_path) else "text"
                bytes_count= get_file_size(absolute_file_path)
                file_size = bytes_to_human_readable(bytes_count)
                result.append(tfile_path.strip() + f"\t(type: {file_type}, size: {file_size}, bytes: {bytes_count})")
                count_files += 1
        if result:
            result.insert(0, f"Found {count_directories} directories and {count_files} files in workspace:")
            return str_return("\n".join(result))
        return str_error(f"No files found in the specified directory({path}).")

    def __init__(self, workspace: str, ignore_pattern=None, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        assert os.path.exists(workspace), f"Workspace {workspace} does not exist."
        self.workspace = os.path.abspath(workspace)
        if ignore_pattern is not None:
            self.ignore_pattern = ignore_pattern
        info(f"ListPath tool initialized with workspace: {self.workspace}")


class ArgReadFile(BaseModel):
    path: str = Field(
        default=None,
        description="file path to read, relative to the workspace")
    start: int = Field(
        default=0,
        description="start position to read the file, default is 0, meaning from the beginning of the file")
    end: int = Field(
        default=-1,
        description="end position to read the file, default is -1, meaning to the end of the file")


class ReadFile(BaseTool):
    name: str = "ReadFile"
    description: str = "used to read the content of a file in the workspace. If you context is limited, "+\
                       "you can specify the start and end position to read a part of the file. The max read size is %d bytes. " +\
                       "Important: the return data prefix '[RETURN]\n' is not included in the returned content."
    args_schema: Optional[ArgsSchema] = ArgReadFile
    return_direct: bool = False

    # custom variables
    workspace: str = Field(
        default=".",  # Default to current directory
        description="the workspace directory to read files from")

    max_read_size: int = Field(
        default=30720, # Default to 30KB
        description="maximum size of the file to read, default is 30KB, if the file is larger than this, it will be truncated"
    )

    def _run(self,
             path: str, start: int, end:int, run_manager: Optional[CallbackManagerForToolRun] = None
            ) -> str:
        """Read the content of a file in the workspace."""
        real_path = os.path.abspath(os.path.join(self.workspace, path))
        if real_path.startswith(self.workspace) is False:
            return str_error(f"File '{path}' is not within the workspace.")
        if not os.path.exists(real_path):
            return str_error(f"File {path} does not exist in workspace.")
        info(f"Reading file {real_path} from position {start} to {end}")
        file_bytes = get_file_size(real_path)
        is_text = is_text_file(real_path)
        with open(real_path, 'rb') as f:
            f.seek(start)
            content = f.read(end - start) if (end != -1) else f.read()
            if not content:
                return str_error(f"File {path} is empty or the specified range is invalid.")
            if is_text:
                content = content.decode('utf-8', errors='ignore')
            else:
                content = str(content)
            tex_size = len(content)
            if tex_size > self.max_read_size:
                return str_error(f"\nRead size {tex_size} characters exceeds the maximum read size of {self.max_read_size} characters. "+\
                                 f"You need to specify a smaller range. current range is {start}-{end}.")
            return str_return(content)

    def __init__(self, workspace: str, max_read_size: int = 30720, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        assert os.path.exists(workspace), f"Workspace {workspace} does not exist."
        self.workspace = os.path.abspath(workspace)
        self.max_read_size = max_read_size
        self.description = self.description % self.max_read_size
        info(f"ReadFile tool initialized with workspace: {self.workspace}")


class ArgReadTextFile(BaseModel):
    path: str = Field(
        default=None,
        description="file path to read, relative to the workspace")
    start: int = Field(
        default=0,
        description="start line to read, default is 0, meaning from the beginning of the file")
    count: int = Field(
        default=-1,
        description="number of lines to read, default is -1, meaning read to the end of the file")


class ReadTextFile(BaseTool):
    name: str = "ReadTextFile"
    description: str = "used to read the content of a text file in the workspace. If you context is limited, "+\
                       "you can specify the start line and count of lines to read a part of the file. The max read size is %d characters. "+\
                       "Note: the line index is start from 0, the return lines are inserted with '<index>: ' prefix, e.g., the raw data is "+\
                        "'this is line 1\nthis is line 2' while this tool returns "+\
                        "'0: this is line 1\n1: this is line2', etc." + \
                        "Important: the return data prefix '[RETURN]\n' is not included in the returned content."
    args_schema: Optional[ArgsSchema] = ArgReadTextFile
    return_direct: bool = False

    # custom variables
    workspace: str = Field(
        default=".",  # Default to current directory
        description="the workspace directory to read files from")

    max_read_size: int = Field(
        default=30720, # Default to 30KB
        description="maximum size of the file to read, default is 1MB, if the file is larger than this, it will be truncated"
    )

    def _run(self, path: str, start: int = 0, count: int = -1,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Read the content of a text file in the workspace."""
        real_path = os.path.abspath(os.path.join(self.workspace, path))
        if real_path.startswith(self.workspace) is False:
            return str_error(f"File '{path}' is not within the workspace.")
        if not os.path.exists(real_path):
            return str_error(f"File {path} does not exist in workspace.")
        if not is_text_file(real_path):
            return str_error(f"File {path} is not a text file.")
        info(f"Reading text file {real_path} from line {start} with count {count}")
        if count == 0:
            return str_error(f"Count is 0, no lines to read from file {path}.")
        with open(real_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            lines_count = len(lines)
            if start < 0 or start >= len(lines):
                return str_error(f"Start line {start} is out of range(0-{lines_count}) for file {path}.")
            r_count = count
            if r_count == -1 or start + r_count > len(lines):
                r_count = len(lines) - start
            content = ''.join(["%d: %s" % (i, l) for i, l in enumerate(lines[start:start + r_count])])
            if len(content) > self.max_read_size:
                return str_error(f"Read size {len(content)} characters exceeds the maximum read size of {self.max_read_size} characters. " +\
                                 f"You need to specify a smaller range. current range is ({start}, +{str(count) if count >=0 else 'MAX'}).")
            return str_return(content)

    def __init__(self, workspace: str, max_read_size: int = 30720, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        assert os.path.exists(workspace), f"Workspace {workspace} does not exist."
        self.workspace = os.path.abspath(workspace)
        self.max_read_size = max_read_size
        self.description = self.description % self.max_read_size
        info(f"ReadTextFile tool initialized with workspace: {self.workspace}")


class ArgReplaceTextFileLines(BaseModel):
    path: str = Field(
        default=None,
        description="textfile path to replace, relative to the workspace")
    start: int = Field(
        default=0,
        description="start line to replace, default is 0, meaning from the beginning of the file")
    count: int = Field(
        default=-1,
        description="count of lines to replace, default is -1, meaning to the end of the file")
    data: str = Field(
        default=None,
        description="string data (char '\\n' is the end of a line) to replace the lines, if not specified, the lines will be removed, if specified, the lines will be replaced with this data"
    )


class ReplaceTextFileLines(BaseTool):
    name: str = "ReplaceTextFileLines"
    description: str = "used to replace the content of a text file in the workspace. "+\
                       "If the target file is not exist, it will create a empty file and ignore the start and count args. "+\
                       "The line index is start from 0. "
    args_schema: Optional[ArgsSchema] = ArgReplaceTextFileLines
    return_direct: bool = False

    # custom variables
    workspace: str = Field(
        default=".",  # Default to current directory
        description="the workspace directory to read files from")

    def _run(self, path: str, start: int = 0, count: int = -1, data: str = None,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Replace the content of a text file in the workspace."""
        if path.endswith('/'):
            return str_error(f"Path '{path}' should not end with a slash. Please provide a file path, not a directory.")
        real_path = os.path.abspath(os.path.join(self.workspace, path))
        if real_path.startswith(self.workspace) is False:
            return str_error(f"File '{path}' is not within the workspace.")
        base_dir = os.path.dirname(real_path)
        if not os.path.exists(base_dir):
            info(f"Base directory {base_dir} does not exist, creating it.")
            os.makedirs(base_dir, exist_ok=True)
        if not os.path.exists(real_path):
            # create an empty file
            info(f"File {real_path} does not exist, creating an empty file.")
            with open(real_path, 'w', encoding='utf-8') as f:
                pass
        if not is_text_file(real_path):
            return str_error(f"File {path} is not a text file.")
        info(f"Replacing text file {real_path} from line {start} with count {count}")
        with open(real_path, 'r+', encoding='utf-8') as f:
            lines = f.readlines()
            if start < 0:
                return str_error(f"Start line {start} need be zero or positive.")
            lines_pred = lines[:start]
            lines_after = []
            if count >= 0:
                lines_after = lines[start + count:]
            lines_insert = []
            if data is not None:
                lines_insert = [data]
            # write the new content
            f.seek(0)
            f.truncate(0)
            f.writelines(lines_pred + lines_insert + lines_after)
            f.flush()
            return str_info(f"Write {len(data)} characters complete.")

    def __init__(self, workspace: str, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        assert os.path.exists(workspace), f"Workspace {workspace} does not exist."
        self.workspace = os.path.abspath(workspace)
        info(f"ReplaceTextLines tool initialized with workspace: {self.workspace}")


class ArgWriteToFile(BaseModel):
    path: str = Field(
        default=None,
        description="file path to write, relative to the workspace, if the file does not exist, it will be created")
    data: str = Field(
        default=None,
        description="string data to write to the file, if not specified, the file will be cleared"
    )


class WriteToFile(BaseTool):
    name: str = "WriteToFile"
    description: str = "used to write str data to a file in the workspace. If the target file is not exist, it will create a empty file and write the data to it."
    args_schema: Optional[ArgsSchema] = ArgWriteToFile
    return_direct: bool = False

    # custom variables
    workspace: str = Field(
    default=".",  # Default to current directory
    description="the workspace directory to write files to")

    def _run(self, path: str, data: str = None,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Write data to a file in the workspace."""
        if path.endswith('/'):
            return str_error(f"Path '{path}' should not end with a slash. Please specify a file path.")
        real_path = os.path.abspath(os.path.join(self.workspace, path))
        if real_path.startswith(self.workspace) is False:
            return str_error(f"File '{path}' is not within the workspace.")
        base_dir = os.path.dirname(real_path)
        if not os.path.exists(base_dir):
            info(f"Base directory {base_dir} does not exist, creating it.")
            os.makedirs(base_dir, exist_ok=True)
        with open(real_path, 'w', encoding='utf-8') as f:
            if data is None:
                info(f"Clearing file {real_path}.")
                f.truncate(0)
            else:
                info(f"Writing data to file {real_path}.")
                f.write(data)
            f.flush()
            return str_info(f"Write {len(data)} characters complete." if data else f"File(path) cleared.")

    def __init__(self, workspace: str, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        assert os.path.exists(workspace), f"Workspace {workspace} does not exist."
        self.workspace = os.path.abspath(workspace)
        info(f"WriteToFile tool initialized with workspace: {self.workspace}")
