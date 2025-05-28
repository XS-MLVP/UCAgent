#coding=utf-8

from typing import Optional
from vagent.util.log import info
from vagent.util.functions import is_text_file, get_file_size, bytes_to_human_readable

from langchain_core.callbacks import (
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field

import os
import fnmatch


class DirPath(BaseModel):
    path: str = Field(
        default=".",  # Default to current directory
        description="directory path to list files from, relative to the workspace")
    depth: int = Field(
        default=-1, description="depth of subdirectories to list, -1 means to the deepest level, 0 means only the current directory"
    )


class ListPath(BaseTool):
    name: str = "ListPath"
    description: str = "used to list all the files in a directory of the workspace, including subdirectories. "
    args_schema: Optional[ArgsSchema] = DirPath
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
            return f"Path '{path}' is not within the workspace."
        info(f"Listing files in {real_path} with depth {depth}")
        if not os.path.exists(real_path):
            return f"Path {path} does not exist in workspace."
        if not os.path.isdir(real_path):
            return f"Path {path} is not a directory in workspace."
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
            return "\n".join(result)
        return f"No files found in the specified directory({path})."

    def __init__(self, workspace: str, ignore_pattern=None, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        assert os.path.exists(workspace), f"Workspace {workspace} does not exist."
        self.workspace = os.path.abspath(workspace)
        if ignore_pattern is not None:
            self.ignore_pattern = ignore_pattern
        info(f"ListPath tool initialized with workspace: {self.workspace}")


class FilePath(BaseModel):
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
                       "you can specify the start and end position to read a part of the file. "
    args_schema: Optional[ArgsSchema] = FilePath
    return_direct: bool = False

    # custom variables
    workspace: str = Field(
        default=".",  # Default to current directory
        description="the workspace directory to read files from")

    def _run(self,
             path: str, start: int, end:int, run_manager: Optional[CallbackManagerForToolRun] = None
            ) -> str:
        """Read the content of a file in the workspace."""
        real_path = os.path.abspath(os.path.join(self.workspace, path))
        if real_path.startswith(self.workspace) is False:
            return f"File '{path}' is not within the workspace."
        if not os.path.exists(real_path):
            return f"File {path} does not exist in workspace."
        info(f"Reading file {real_path} from position {start} to {end}")
        file_bytes = get_file_size(real_path)
        is_text = is_text_file(real_path)
        with open(real_path, 'rb') as f:
            f.seek(start)
            content = f.read(end - start) if (end != -1) else f.read()
            raw_size = len(content)
            if not content:
                return f"File {path} is empty or the specified range is invalid."
            if is_text:
                content = content.decode('utf-8', errors='ignore')
            else:
                content = str(content)
            tex_size = len(content)
            return f"Read position range: start={start}, end={end}\n" + \
                   f"Read text {tex_size} characters from file {path} " + \
                   f"(raw size: {raw_size} bytes, {file_bytes - raw_size} bytes remain):\n{content}"

    def __init__(self, workspace: str, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        assert os.path.exists(workspace), f"Workspace {workspace} does not exist."
        self.workspace = os.path.abspath(workspace)
        info(f"ReadFile tool initialized with workspace: {self.workspace}")


class TextFilePath(BaseModel):
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
                       "you can specify the start line and count of lines to read a part of the file. "
    args_schema: Optional[ArgsSchema] = TextFilePath
    return_direct: bool = False

    # custom variables
    workspace: str = Field(
        default=".",  # Default to current directory
        description="the workspace directory to read files from")

    def _run(self, path: str, start: int = 0, count: int = -1,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Read the content of a text file in the workspace."""
        real_path = os.path.abspath(os.path.join(self.workspace, path))
        if real_path.startswith(self.workspace) is False:
            return f"File '{path}' is not within the workspace."
        if not os.path.exists(real_path):
            return f"File {path} does not exist in workspace."
        if not is_text_file(real_path):
            return f"File {path} is not a text file."
        info(f"Reading text file {real_path} from line {start} with count {count}")
        if count == 0:
            return f"Count is 0, no lines to read from file {path}."
        with open(real_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            lines_count = len(lines)
            if start < 0 or start >= len(lines):
                return f"Start line {start} is out of range(0-{lines_count}) for file {path}."
            if count == -1 or start + count > len(lines):
                count = len(lines) - start
            content = ''.join(lines[start:start + count])
            return f"Read {count} lines ({start} to {start + count}, remian {lines_count - count - start} tail lines) from file {path}:\n{content}"

    def __init__(self, workspace: str, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        assert os.path.exists(workspace), f"Workspace {workspace} does not exist."
        self.workspace = os.path.abspath(workspace)
        info(f"ReadTextFile tool initialized with workspace: {self.workspace}")
