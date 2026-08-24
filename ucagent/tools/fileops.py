# -*- coding: utf-8 -*-
"""File operations tools for UCAgent."""

from typing import Annotated, Optional, List, Tuple, Union
from ucagent.util.log import info, str_info, str_return, str_error, str_data, warning
from ucagent.util.functions import is_text_file, get_file_size, bytes_to_human_readable
from ucagent.util.functions import get_diff, match_pattern_list
from .uctool import UCTool

from langchain_core.callbacks import (
    CallbackManagerForToolRun,
)
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, ConfigDict, Field, model_validator

import hashlib
import os
import fnmatch
import shutil
import tempfile
from collections import deque
from pathlib import Path, PurePosixPath

try:
    import regex as regex_lib
except ImportError:  # pragma: no cover - exercised through a patched module value
    regex_lib = None


DEFAULT_MAX_DIFF_CHARS = 20000


def _normalize_relative_path(path: str, *, allow_workspace: bool = False) -> str:
    """Return a normalized workspace-relative path without touching the filesystem."""
    if not isinstance(path, str):
        raise ValueError(f"Invalid path: {path}. Path must be a string.")
    if not path.strip():
        if allow_workspace:
            return "."
        raise ValueError("Path must not be empty.")
    normalized_input = path.replace("\\", "/")
    pure_path = PurePosixPath(normalized_input)
    if pure_path.is_absolute():
        raise ValueError(
            f"Path '{path}' must be relative to the workspace; absolute paths are not allowed."
        )
    normalized = os.path.normpath(normalized_input).replace(os.sep, "/")
    if normalized == ".":
        if allow_workspace:
            return normalized
        raise ValueError("The workspace root cannot be used as a file path.")
    if normalized == ".." or normalized.startswith("../"):
        raise ValueError(f"Path '{path}' is not within the workspace.")
    return normalized


def _path_is_at_or_below(path: str, directory: str) -> bool:
    path_parts = PurePosixPath(path).parts
    directory_parts = PurePosixPath(directory).parts
    return path_parts[:len(directory_parts)] == directory_parts


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text_file_metadata(path: str) -> Tuple[str, bool]:
    """Return the file's detected newline label and final-newline state."""
    with open(path, "rb") as file_obj:
        sample = file_obj.read(65536)
        file_obj.seek(0, os.SEEK_END)
        size = file_obj.tell()
        file_obj.seek(max(0, size - 2))
        tail = file_obj.read()
    if b"\r\n" in sample:
        newline = "CRLF"
    elif b"\r" in sample:
        newline = "CR"
    else:
        newline = "LF"
    return newline, tail.endswith((b"\n", b"\r"))


def _read_text_snapshot(path: str) -> Tuple[str, str, str]:
    """Read exact UTF-8 text and return content, SHA-256, and dominant newline."""
    with open(path, "rb") as file_obj:
        raw = file_obj.read()
    content = raw.decode("utf-8")
    if "\r\n" in content:
        newline = "\r\n"
    elif "\r" in content:
        newline = "\r"
    else:
        newline = "\n"
    return content, _sha256_bytes(raw), newline


def _convert_newlines(content: str, newline: str) -> str:
    """Convert caller-provided text to the target file's newline convention."""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    return normalized if newline == "\n" else normalized.replace("\n", newline)


def _atomic_write_text(path: str, content: str, *, existing_mode: Optional[int] = None) -> None:
    """Atomically replace a UTF-8 text file with exact newline preservation."""
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(prefix=".ucagent-edit-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as file_obj:
            file_obj.write(content)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        if existing_mode is not None:
            os.chmod(temporary_path, existing_mode)
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise


def _atomic_create_text(path: str, content: str) -> None:
    """Publish a complete new UTF-8 file without overwriting a racing creator."""
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(prefix=".ucagent-create-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as file_obj:
            file_obj.write(content)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.chmod(temporary_path, 0o644)
        os.link(temporary_path, path)
        os.unlink(temporary_path)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise


def _atomic_copy_file(source_path: str, dest_path: str, *, overwrite: bool) -> None:
    """Publish a complete copy, optionally refusing a racing destination."""
    parent = os.path.dirname(dest_path)
    os.makedirs(parent, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(prefix=".ucagent-copy-", dir=parent)
    os.close(fd)
    try:
        shutil.copy2(source_path, temporary_path)
        if overwrite:
            os.replace(temporary_path, dest_path)
        else:
            os.link(temporary_path, dest_path)
            os.unlink(temporary_path)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise


def _atomic_move_file(source_path: str, dest_path: str, *, overwrite: bool) -> None:
    """Move a file atomically within the workspace filesystem."""
    parent = os.path.dirname(dest_path)
    os.makedirs(parent, exist_ok=True)
    if overwrite:
        os.replace(source_path, dest_path)
        return
    os.link(source_path, dest_path)
    try:
        os.remove(source_path)
    except BaseException:
        os.unlink(dest_path)
        raise


def _bounded_diff(old_content: str, new_content: str, path: str) -> Tuple[str, bool]:
    diff = get_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        path,
    )
    if len(diff) <= DEFAULT_MAX_DIFF_CHARS:
        return diff, False
    omitted = len(diff) - DEFAULT_MAX_DIFF_CHARS
    return (
        diff[:DEFAULT_MAX_DIFF_CHARS]
        + f"\n... [DIFF truncated; {omitted} characters omitted]",
        True,
    )


def is_file_writeable(path: str, un_write_dirs: list=None, write_dirs: list=None) -> Tuple[bool, str]:
    try:
        path = _normalize_relative_path(path)
    except ValueError as exc:
        return False, str(exc)
    if un_write_dirs is None and write_dirs is None:
        return True, "No write restrictions defined."
    if un_write_dirs is not None:
        assert isinstance(un_write_dirs, list), "un_write_dirs must be a list."
        for d in un_write_dirs:
            try:
                directory = _normalize_relative_path(d)
            except ValueError:
                continue
            if _path_is_at_or_below(path, directory):
                return False, f"Path '{path}' is not allowed to write."
        if write_dirs is None:
            return True, f"Path '{path}' is allowed to write as it does not match any no-write directories: {un_write_dirs}."
    if write_dirs is not None:
        assert isinstance(write_dirs, list), "write_dirs must be a list."
        for d in write_dirs:
            try:
                directory = _normalize_relative_path(d)
            except ValueError:
                continue
            if _path_is_at_or_below(path, directory):
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
        description="Deprecated compatibility flag. Path validation never creates files; write tools commit creation explicitly."
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
        workspace_path = Path(workspace).resolve()
        normalized_dirs = []
        for directory in dirs:
            assert isinstance(directory, str)
            candidate = Path(directory)
            if not candidate.is_absolute():
                candidate = workspace_path / directory
            resolved = candidate.resolve(strict=False)
            try:
                relative = resolved.relative_to(workspace_path).as_posix()
            except ValueError as exc:
                raise AssertionError(
                    f"Configured directory {directory} is outside workspace {workspace}."
                ) from exc
            assert relative != ".", "'.' cannot be used as a writable or unwritable directory."
            normalized_dirs.append(relative)
        return normalized_dirs

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

    def get_real_path(self, rpath, *, allow_workspace: bool = False):
        normalized = _normalize_relative_path(rpath, allow_workspace=allow_workspace)
        workspace = Path(self.workspace).resolve()
        lexical_path = workspace / normalized
        real_path = lexical_path.resolve(strict=False)
        try:
            real_path.relative_to(workspace)
        except ValueError as exc:
            raise ValueError(f"Path '{rpath}' is not within the workspace.") from exc
        return str(lexical_path)

    def _has_symlink_component(self, real_path: str) -> bool:
        workspace = Path(self.workspace).resolve()
        candidate = Path(real_path)
        try:
            relative_parts = candidate.relative_to(workspace).parts
        except ValueError:
            return True
        current = workspace
        for part in relative_parts:
            current = current / part
            if current.is_symlink():
                return True
        return False

    def check_file(
        self,
        path: str,
        *,
        for_write: bool = False,
        allow_missing: bool = False,
    ) -> Tuple[bool, str, str]:
        """Resolve and validate a file path without modifying the filesystem."""
        try:
            normalized = _normalize_relative_path(path)
            real_path = self.get_real_path(normalized)
        except ValueError as exc:
            return False, str(exc), ""
        if path.endswith('/'):
            return False, f"Path '{path}' should not end with a slash. Please provide a file path, not a directory.", ""
        if for_write:
            write_able, msg = is_file_writeable(
                normalized, self.un_write_able_dirs, self.write_able_dirs
            )
            if not write_able:
                return False, msg, ""
            if self._has_symlink_component(real_path):
                return False, f"Refusing to modify path '{path}' through a symbolic link.", ""
        if not os.path.exists(real_path):
            if allow_missing:
                return True, "", real_path
            return False, f"File {path} does not exist in workspace. Please create it first.", ""
        if not os.path.isfile(real_path):
            return False, f"Path {path} is not a file in workspace.", ""
        return True, "", real_path

    def check_dir(
        self,
        path: str,
        *,
        for_write: bool = False,
        allow_missing: bool = False,
    ) -> Tuple[bool, str, str]:
        """Check if the directory exists and is accessible."""
        if not path or path == ".":
            path = "."
        try:
            normalized = _normalize_relative_path(path, allow_workspace=True)
            real_path = self.get_real_path(normalized, allow_workspace=True)
        except ValueError as exc:
            return False, str(exc), ""
        if for_write:
            if normalized == ".":
                return False, "The workspace root cannot be modified directly.", ""
            write_able, msg = is_file_writeable(
                normalized, self.un_write_able_dirs, self.write_able_dirs
            )
            if not write_able:
                return False, msg, ""
            if self._has_symlink_component(real_path):
                return False, f"Refusing to modify path '{path}' through a symbolic link.", ""
        if not os.path.exists(real_path):
            if allow_missing:
                return True, "", real_path
            return False, f"Path {path} does not exist in workspace.", ""
        if os.path.isfile(real_path):
            return False, f"Path {path} is a file, need directory.", ""
        if not os.path.isdir(real_path):
            return False, f"Path {path} is not a directory in workspace.", ""
        return True, "", real_path

class StrictToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArgSearchText(StrictToolArgs):
    pattern: str = Field(
        ...,
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
        ge=1,
        description="Maximum number of matching lines to return per file."
    )
    max_match_files: int = Field(
        default=10,
        ge=1,
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
    context_before: int = Field(
        default=1,
        ge=0,
        le=20,
        description="Number of original lines to return before each match (default: 1)."
    )
    context_after: int = Field(
        default=1,
        ge=0,
        le=20,
        description="Number of original lines to return after each match (default: 1)."
    )
    regex_timeout_ms: int = Field(
        default=50,
        ge=1,
        le=1000,
        description="Maximum milliseconds allowed for each regular-expression match."
    )

class SearchText(UCTool, BaseReadWrite):
    """Search for text in files within the workspace directory with advanced pattern matching."""
    name: str = "SearchText"
    description: str = (
        "Search for text in files within the workspace directory with support for plain text, wildcards, and regex patterns. "
        "Each matching file is returned once with a fenced code block containing line-numbered matching lines and optional "
        "context (one line before and after by default). For example: "
        "'path/to/file.py:\\n```text\\n29: matching line\\n30: nearby line\\n```'. "
        "Supports case-sensitive/insensitive search."
    )
    args_schema: Optional[ArgsSchema] = ArgSearchText
    return_direct: bool = False
    ignore_hidden: bool = True
    ignore_pattern_list: list[str] = []

    def _run(self, pattern: str, directory: str = "", max_match_lines: int = 20, max_match_files: int = 10,
             use_regex: bool = False, case_sensitive: bool = False, include_line_numbers: bool = True,
             context_before: int = 1, context_after: int = 1,
             regex_timeout_ms: int = 50,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Search for text in files within a workspace directory."""
        if not pattern:
            self.do_callback(False, directory, "No text pattern provided for search.")
            return str_error("No text pattern provided for search.")
        if not 0 <= context_before <= 20 or not 0 <= context_after <= 20:
            error_msg = (
                "Context line counts must be between 0 and 20: "
                f"context_before={context_before}, context_after={context_after}."
            )
            self.do_callback(False, directory, error_msg)
            return str_error(error_msg)
        
        result = []
        count_files = 0
        count_lines = 0
        
        # Compile regex pattern if needed
        regex_pattern = None
        if use_regex:
            if regex_lib is None:
                error_msg = (
                    "Regular-expression search requires the 'regex' package. Install project "
                    "dependencies or use plain-text search."
                )
                self.do_callback(False, directory, error_msg)
                return str_error(error_msg)
            try:
                flags = 0 if case_sensitive else regex_lib.IGNORECASE
                regex_pattern = regex_lib.compile(pattern, flags)
            except regex_lib.error as e:
                error_msg = f"Invalid regex pattern '{pattern}': {str(e)}"
                self.do_callback(False, directory, error_msg)
                return str_error(error_msg)
        
        def search_in_file(txt, sfile, fname):
            nonlocal count_lines, result
            if not is_text_file(sfile):
                return False
            local_matches = 0
            local_lines = {}
            before_lines = deque(maxlen=context_before)
            include_until = 0
            truncated = False

            def matches(line):
                if use_regex and regex_pattern:
                    return regex_pattern.search(
                        line, timeout=regex_timeout_ms / 1000
                    ) is not None
                candidate = line if case_sensitive else line.lower()
                target = txt if case_sensitive else txt.lower()
                if '*' in txt or '?' in txt:
                    matcher = fnmatch.fnmatchcase if case_sensitive else fnmatch.fnmatch
                    return matcher(candidate, target)
                return target in candidate

            try:
                with open(sfile, 'r', encoding='utf-8') as f:
                    for line_number, line in enumerate(f, start=1):
                        raw_line = line.rstrip("\r\n")
                        try:
                            line_matches = matches(raw_line)
                        except TimeoutError:
                            raise TimeoutError(
                                f"Regular expression timed out after {regex_timeout_ms} ms "
                                f"while searching {fname} at line {line_number}. Use a more "
                                "specific pattern or plain-text search."
                            )
                        if line_matches and local_matches >= max_match_lines:
                            truncated = True
                            if line_number <= include_until:
                                local_lines.setdefault(line_number, (raw_line, False))
                            if line_number >= include_until:
                                break
                            before_lines.append((line_number, raw_line))
                            continue
                        if line_matches:
                            local_matches += 1
                            for previous_number, previous_line in before_lines:
                                local_lines.setdefault(previous_number, (previous_line, False))
                            local_lines[line_number] = (raw_line, True)
                            include_until = max(include_until, line_number + context_after)
                        elif line_number <= include_until:
                            local_lines.setdefault(line_number, (raw_line, False))
                        before_lines.append((line_number, raw_line))
            except TimeoutError:
                raise
            except (UnicodeDecodeError, IOError) as e:
                info(f"Could not read file {sfile}: {str(e)}")
                return False

            if local_lines:
                rendered_lines = []
                previous_line_number = None
                for line_number, (line, _) in sorted(local_lines.items()):
                    if (
                        previous_line_number is not None
                        and line_number > previous_line_number + 1
                    ):
                        rendered_lines.append("...")
                    if include_line_numbers:
                        rendered_lines.append(f"{line_number}: {line}")
                    else:
                        rendered_lines.append(line)
                    previous_line_number = line_number
                if truncated:
                    match_label = "line" if max_match_lines == 1 else "lines"
                    rendered_lines.append(
                        f"... (truncated to {max_match_lines} matching {match_label})"
                    )
                content = "\n".join(rendered_lines)
                longest_backtick_run = 0
                current_backtick_run = 0
                for character in content:
                    if character == "`":
                        current_backtick_run += 1
                        longest_backtick_run = max(
                            longest_backtick_run, current_backtick_run
                        )
                    else:
                        current_backtick_run = 0
                fence = "`" * max(3, longest_backtick_run + 1)
                result.append(
                    f"{fname}:\n{fence}text\n{content}\n{fence}"
                )
            count_lines += local_matches
            return local_matches > 0

        try:
            candidate_path = self.get_real_path(directory, allow_workspace=True)
        except ValueError as exc:
            self.do_callback(False, directory, str(exc))
            return str_error(str(exc))
        if os.path.isfile(candidate_path):
            try:
                search_in_file(pattern, candidate_path, _normalize_relative_path(directory))
            except TimeoutError as exc:
                self.do_callback(False, directory, str(exc))
                return str_error(str(exc))
            if count_lines > 0:
                line_label = "line" if count_lines == 1 else "lines"
                ret_head = str_info(
                    f"\nFound {count_lines} matching {line_label} in 1 file.\n\n"
                )
                self.do_callback(True, directory, result)
                return ret_head + str_return("\n\n".join(result))
        else:
            success, msg, real_path = self.check_dir(directory)
            if not success:
                self.do_callback(False, directory, msg)
                return str_error(msg)
            info(f"Searching for text '{pattern}' in {real_path}")
            resolved_workspace = str(Path(self.workspace).resolve())
            for root, dirs, files in os.walk(real_path):
                relative_root = os.path.relpath(root, resolved_workspace)
                dirs[:] = sorted([
                    directory_name for directory_name in dirs
                    if not (
                        (self.ignore_hidden and directory_name.startswith('.'))
                        or match_pattern_list(
                            os.path.join(relative_root, directory_name),
                            self.ignore_pattern_list,
                        )
                    )
                ])
                for file in sorted(files):
                    if self.ignore_hidden and file.startswith('.'):
                        continue
                    relative_file = os.path.relpath(
                        os.path.join(root, file), resolved_workspace
                    ).replace(os.sep, "/")
                    if match_pattern_list(relative_file, self.ignore_pattern_list):
                        continue
                    file_path = os.path.join(root, file)
                    if not is_text_file(file_path):
                        continue
                    try:
                        if search_in_file(pattern, file_path, relative_file):
                            count_files += 1
                    except TimeoutError as exc:
                        self.do_callback(False, directory, str(exc))
                        return str_error(str(exc))
                    if count_files >= max_match_files:
                        result.append(f"... (truncated to {max_match_files} files)")
                        break
                if count_files >= max_match_files:
                    break
            if result:
                file_label = "file" if count_files == 1 else "files"
                line_label = "line" if count_lines == 1 else "lines"
                ret_head = str_info(
                    f"\nFound {count_lines} matching {line_label} in "
                    f"{count_files} {file_label}.\n\n"
                )
                self.do_callback(True, directory, result)
                return ret_head + str_return("\n\n".join(result))
            self.do_callback(False, directory, None)
        return str_error(f"No matches found for '{pattern}' in the specified directory({directory if directory else '.'}).")

    def __init__(self, workspace: str, ignore_hidden: bool = True,
                 ignore_pattern_list: Optional[list[str]] = None,
                 **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace)
        self.ignore_hidden = ignore_hidden
        self.ignore_pattern_list = ignore_pattern_list or [
            ".git/*", "*/data/*", ".ucagent/*", "uc_test_report/*", "*.dat", "*.fst"
        ]
        info(f"SearchText tool initialized with workspace: {self.workspace}")


class ArgFindFiles(StrictToolArgs):
    pattern: str = Field(
        ...,
        description="File name pattern to search for in the directory. "
    )
    directory: str = Field(
        default="",
        description="Subdirectory path to search in, relative to the workspace. If empty, searches in the entire workspace."
    )
    max_match_files: int = Field(
        default= 10,
        ge=1,
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
    ignore_hidden: bool = True
    ignore_pattern_list: list[str] = []

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
        for root, dirs, files in os.walk(real_path):
            relative_root = os.path.relpath(root, self.workspace)
            dirs[:] = [
                name for name in dirs
                if not (
                    (self.ignore_hidden and name.startswith('.'))
                    or match_pattern_list(
                        os.path.join(relative_root, name), self.ignore_pattern_list
                    )
                )
            ]
            for file in files:
                if self.ignore_hidden and file.startswith('.'):
                    continue
                if match_pattern_list(
                    os.path.join(relative_root, file), self.ignore_pattern_list
                ):
                    continue
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

    def __init__(self, workspace: str, ignore_hidden: bool = True,
                 ignore_pattern_list: Optional[list[str]] = None, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace)
        self.ignore_hidden = ignore_hidden
        self.ignore_pattern_list = ignore_pattern_list or [
            ".git/*", ".ucagent/*", "*.dat", "*.fst"
        ]
        info(f"FindFiles tool initialized with workspace: {self.workspace}")


class ArgPathList(StrictToolArgs):
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


class ArgReadBinFile(StrictToolArgs):
    path: str = Field(
        ...,
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


class ArgReadTextFile(StrictToolArgs):
    path: str = Field(
        ...,
        description="Text file path to read, relative to the workspace.")
    start: int = Field(
        default=1,
        description="Start line index (1-based)."
    )
    count: int = Field(
        default=-1,
        description=(
            "Number of lines to return. -1 means to end of file; 0 validates "
            "the file and records a successful read without returning content."
        )
    )
    include_line_numbers: bool = Field(
        default=True,
        description="Prefix returned lines with their 1-based line numbers. Set false when reusing exact text in an edit."
    )
    structured_output: bool = Field(
        default=False,
        description="Return a dictionary containing raw text, range, SHA-256, and newline metadata instead of formatted text."
    )


class ReadTextFile(UCTool, BaseReadWrite):
    """Read lines from a text file in the workspace. (line index starts from 1)"""
    name: str = "ReadTextFile"
    description: str = (
        "Read lines from a text file in the workspace. Supports start line and line count; "
        "count=0 validates the file and records a successful read without returning content. "
        "Max read size is %d characters. The result includes the file SHA-256 for "
        "conflict-safe editing. Set include_line_numbers=false to receive reusable raw "
        "text without synthetic prefixes, or structured_output=true for raw text and file "
        "metadata in a dictionary. Note: The file content in the default return data is after "
        "prefix '[TXT_DATA]\\n' and, by default, each line has prefix '<index>: '.\n"
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
             include_line_numbers: bool = True,
             structured_output: bool = False,
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
        if count < -1:
            emsg = (
                f"Invalid count {count}. Use -1 for all remaining lines, "
                "0 for confirmation only, or a positive line count."
            )
            self.do_callback(False, path, emsg)
            return str_error(emsg)
        try:
            file_sha256 = _sha256_file(real_path)
            newline, has_final_newline = _text_file_metadata(real_path)
            with open(real_path, 'r', encoding='utf-8', newline='') as f:
                if count == 0:
                    self.do_callback(True, path, "")
                    if structured_output:
                        return {
                            "ok": True,
                            "path": path,
                            "start_line": None,
                            "end_line": None,
                            "line_count": 0,
                            "total_lines": None,
                            "remaining_lines": None,
                            "content": "",
                            "sha256": file_sha256,
                            "newline": newline,
                            "has_final_newline": has_final_newline,
                        }
                    return str_info(
                        f"\nConfirmed text file '{path}'; read 0 lines and returned no content "
                        f"(count=0). SHA256: {file_sha256}.\n\n"
                    ) + str_data("", "TXT_DATA")
                requested_start = max(1, start)
                selected_lines = []
                lines_count = 0
                selected_size = 0
                too_large = False
                for line_number, line in enumerate(f, start=1):
                    lines_count = line_number
                    if line_number < requested_start:
                        continue
                    if count != -1 and len(selected_lines) >= count:
                        continue
                    selected_lines.append((line_number, line))
                    selected_size += len(line) + len(str(line_number)) + 2
                    if selected_size > self.max_read_size:
                        too_large = True
                        break
                # Handle empty file
                if lines_count == 0:
                    self.do_callback(True, path, "")
                    if structured_output:
                        return {
                            "ok": True,
                            "path": path,
                            "start_line": None,
                            "end_line": None,
                            "line_count": 0,
                            "total_lines": 0,
                            "remaining_lines": 0,
                            "content": "",
                            "sha256": file_sha256,
                            "newline": newline,
                            "has_final_newline": has_final_newline,
                        }
                    return str_info(
                        f"\nFile {path} is empty (0 lines). SHA256: {file_sha256}.\n\n"
                    ) + str_data("", "TXT_DATA")
                if requested_start > lines_count:
                    emsg = f"Start line {requested_start} is out of range (file has {lines_count} lines, valid range: 1-{lines_count})."
                    self.do_callback(False, path, emsg)
                    return str_error(emsg)
                if too_large:
                    safe_count = max(1, len(selected_lines) - 1)
                    emsg = (
                        f"Read size exceeds the maximum read size of {self.max_read_size} characters. "
                        f"Retry with start={requested_start}, count={safe_count} or smaller. "
                        f"SHA256: {file_sha256}."
                    )
                    self.do_callback(False, path, emsg)
                    return str_error(emsg)
                if not selected_lines:
                    self.do_callback(True, path, "")
                    return str_info(
                        f"\nNo lines to read from position {requested_start} in file {path}. "
                        f"SHA256: {file_sha256}.\n\n"
                    ) + str_data("", "TXT_DATA")
                # Format line numbers with appropriate padding
                max_line_num = selected_lines[-1][0]
                line_num_width = len(str(max_line_num))
                fmt_index = f"%{line_num_width}d: %s"
                if include_line_numbers:
                    content = ''.join(
                        fmt_index % (line_number, line)
                        for line_number, line in selected_lines
                    )
                else:
                    content = ''.join(line for _, line in selected_lines)
                if len(content) > self.max_read_size:
                    emsg = (
                        f"Read size {len(content)} characters exceeds the maximum read size of "
                        f"{self.max_read_size} characters. Retry with a smaller count. "
                        f"SHA256: {file_sha256}."
                    )
                    self.do_callback(False, path, emsg)
                    return str_error(emsg)

                first_line = selected_lines[0][0]
                last_line = selected_lines[-1][0]
                remaining_lines = lines_count - last_line
                raw_content = ''.join(line for _, line in selected_lines)
                if structured_output:
                    self.do_callback(True, path, raw_content)
                    return {
                        "ok": True,
                        "path": path,
                        "start_line": first_line,
                        "end_line": last_line,
                        "line_count": len(selected_lines),
                        "total_lines": lines_count,
                        "remaining_lines": remaining_lines,
                        "content": raw_content,
                        "sha256": file_sha256,
                        "newline": newline,
                        "has_final_newline": has_final_newline,
                    }
                ret_head = str_info(
                    f"\nRead {len(selected_lines)}/{lines_count} lines from '{path}' "
                    f"(lines {first_line}-{last_line}), {remaining_lines} lines remain after "
                    f"the read position. SHA256: {file_sha256}.\n\n"
                )
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


class ArgEditTextFile(StrictToolArgs):
    path: str = Field(
        ...,
        description="Text file path to create or edit, relative to the workspace."
    )
    content: str = Field(
        ...,
        description="Complete UTF-8 file content. Use an empty string to create or clear an empty file."
    )
    append: bool = Field(
        default=False,
        description="If false, create or overwrite the complete file. If true, append content to the file, creating it when absent."
    )
    expected_sha256: Optional[str] = Field(
        default=None,
        description="Optional SHA-256 returned by ReadTextFile. The edit fails if the file changed since it was read."
    )


class EditTextFile(UCTool, BaseReadWrite):
    """Create, overwrite, or append to one text file in the workspace."""
    name: str = "EditTextFile"
    description: str = (
        "Create or overwrite one UTF-8 text file using the required path and content "
        "arguments. Set append=true only when adding content to the end. The same call "
        "works whether the target file already exists or not. Use ReplaceStringInFile "
        "for a small exact replacement in an existing file. Repeating a successful "
        "create/overwrite call with the same content is treated as success; append calls "
        "always append again."
    )
    args_schema: Optional[ArgsSchema] = ArgEditTextFile
    return_direct: bool = False
    call_lock_arguments: Tuple[str, ...] = ("path",)

    def _run(self, path: str, content: str, append: bool = False,
             expected_sha256: Optional[str] = None,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Create or update a text file with complete content or an append operation."""
        success, msg, real_path = self.check_file(
            path, for_write=True, allow_missing=True
        )
        if not success:
            self.do_callback(False, path, msg)
            return str_error(msg)
        file_exists = os.path.exists(real_path)
        if file_exists and not is_text_file(real_path):
            emsg = f"File {path} is not a text file."
            self.do_callback(False, path, emsg)
            return str_error(emsg)

        try:
            if file_exists:
                original_content, original_sha256, newline = _read_text_snapshot(real_path)
                existing_mode = os.stat(real_path).st_mode & 0o7777
            else:
                original_content = ""
                original_sha256 = _sha256_bytes(b"")
                newline = "\n"
                existing_mode = None
            if expected_sha256 is not None and expected_sha256 != original_sha256:
                emsg = (
                    f"File {path} changed after it was read. Expected SHA256 "
                    f"{expected_sha256}, current SHA256 {original_sha256}. Read it again and retry."
                )
                self.do_callback(False, path, emsg)
                return str_error(emsg)

            normalized_content = (
                _convert_newlines(content, newline) if file_exists else content
            )
            if append:
                new_content = original_content + normalized_content
                operation_desc = f"Appended {len(content)} characters to '{path}'"
            else:
                new_content = normalized_content
                operation_desc = (
                    f"Overwrote '{path}' with {len(content)} characters"
                    if file_exists
                    else f"Created '{path}' with {len(content)} characters"
                )

            if file_exists and new_content == original_content:
                result = {
                    "append": append,
                    "changed": False,
                    "before_sha256": original_sha256,
                    "after_sha256": original_sha256,
                }
                self.do_callback(True, path, result)
                return str_info(
                    f"File '{path}' already has the requested content; no write was needed. "
                    f"SHA256: {original_sha256}."
                )
            if (
                expected_sha256 is not None
                and file_exists
                and _sha256_file(real_path) != original_sha256
            ):
                emsg = f"File {path} changed while the edit was being prepared. Read it again and retry."
                self.do_callback(False, path, emsg)
                return str_error(emsg)
            if file_exists:
                _atomic_write_text(real_path, new_content, existing_mode=existing_mode)
            else:
                _atomic_create_text(real_path, new_content)
            new_sha256 = _sha256_bytes(new_content.encode("utf-8"))
            diff_result, _ = _bounded_diff(original_content, new_content, path)
            self.do_callback(
                True,
                path,
                {
                    "append": append,
                    "changed": True,
                    "before_sha256": original_sha256,
                    "after_sha256": new_sha256,
                },
            )
            return str_info(
                f"{operation_desc}. SHA256: {original_sha256} -> {new_sha256}."
            ) + diff_result

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


class ArgCopyFile(StrictToolArgs):
    source_path: str = Field(
        ...,
        description="Source file path to copy from, relative to the workspace."
    )
    dest_path: str = Field(
        ...,
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
    call_lock_arguments: Tuple[str, ...] = ("source_path", "dest_path")

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
        
        success, msg, dest_real_path = self.check_file(
            dest_path, for_write=True, allow_missing=True
        )
        if not success:
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
            
            _atomic_copy_file(
                real_source_path, dest_real_path, overwrite=overwrite
            )
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


class ArgMoveFile(StrictToolArgs):
    source_path: str = Field(
        ...,
        description="Source file path to move from, relative to the workspace."
    )
    dest_path: str = Field(
        ...,
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
    call_lock_arguments: Tuple[str, ...] = ("source_path", "dest_path")

    def _run(self, source_path: str, dest_path: str, overwrite: bool = False,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Move a file from source to destination."""
        # Check source file
        success, msg, real_source_path = self.check_file(source_path, for_write=True)
        if not success:
            self.do_callback(False, source_path, msg)
            return str_error(f"Source file error: {msg}")
        
        # Check if source file exists
        if not os.path.exists(real_source_path):
            error_msg = f"Source file {source_path} does not exist."
            self.do_callback(False, source_path, error_msg)
            return str_error(error_msg)
        
        success, msg, dest_real_path = self.check_file(
            dest_path, for_write=True, allow_missing=True
        )
        if not success:
            self.do_callback(False, dest_path, msg)
            return str_error(f"Destination file error: {msg}")
        if os.path.normcase(real_source_path) == os.path.normcase(dest_real_path):
            error_msg = "Source and destination resolve to the same file."
            self.do_callback(False, dest_path, error_msg)
            return str_error(error_msg)
        
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
            
            _atomic_move_file(
                real_source_path, dest_real_path, overwrite=overwrite
            )
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


class ArgDeleteFile(StrictToolArgs):
    path: str = Field(
        ...,
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
    expected_sha256: Optional[str] = Field(
        default=None,
        description="Optional expected SHA-256 for file deletion. Ignored for directories."
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
    call_lock_arguments: Tuple[str, ...] = ("path",)

    def _run(self, path: str, is_dir: bool = False, recursive: bool = False,
             expected_sha256: Optional[str] = None,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Delete a file or directory in the workspace."""
        validator = self.check_dir if is_dir else self.check_file
        success, emsg, target_path = validator(path, for_write=True)
        if not success:
            self.do_callback(False, path, emsg)
            return str_error(emsg)
        if not is_dir and expected_sha256 is not None:
            try:
                current_sha256 = _sha256_file(target_path)
            except OSError as exc:
                emsg = f"Failed to verify {path} before deletion: {exc}"
                self.do_callback(False, path, emsg)
                return str_error(emsg)
            if current_sha256 != expected_sha256:
                emsg = (
                    f"File {path} changed after it was read. Expected SHA256 "
                    f"{expected_sha256}, current SHA256 {current_sha256}."
                )
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


class ArgCreateDirectory(StrictToolArgs):
    path: str = Field(
        ...,
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
    call_lock_arguments: Tuple[str, ...] = ("path",)

    def _run(self, path: str, parents: bool = True, exist_ok: bool = True,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Create a directory in the workspace."""
        success, msg, target_path = self.check_dir(
            path, for_write=True, allow_missing=True
        )
        if not success:
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


_LineNumber = Annotated[int, Field(strict=True, ge=1)]
_LineRange = Tuple[_LineNumber, _LineNumber]
_LineBlock = Union[_LineNumber, _LineRange]


class ArgDeleteTextLines(StrictToolArgs):
    path: str = Field(
        ...,
        description="Existing UTF-8 text file path, relative to the workspace."
    )
    line_blocks: List[_LineBlock] = Field(
        ...,
        min_length=1,
        max_length=1000,
        description=(
            "One-based physical lines to delete. Each item is either one positive line "
            "number or a two-number inclusive [start, end] block. Example: "
            "[1, 4, 5, [10, 20], [40, 55]]. Every item refers to the same original file "
            "snapshot; lines are not renumbered between items. Overlapping and adjacent "
            "blocks are merged. To delete only lines 10 through 20, pass [[10, 20]]; "
            "[10, 20] means two single-line items in the outer list."
        ),
    )
    expected_sha256: Optional[str] = Field(
        default=None,
        description=(
            "Optional SHA-256 returned by ReadTextFile. Because line numbers depend on the "
            "file snapshot, provide it when possible; deletion fails if the file changed."
        ),
    )

    @model_validator(mode="after")
    def validate_line_blocks(self):
        for block in self.line_blocks:
            if isinstance(block, tuple) and block[0] > block[1]:
                raise ValueError(
                    f"line block [{block[0]}, {block[1]}] must have start <= end"
                )
        return self


class DeleteTextLines(UCTool, BaseReadWrite):
    """Delete many complete physical lines from an existing UTF-8 text file."""

    name: str = "DeleteTextLines"
    description: str = (
        "Delete multiple complete, one-based physical lines or inclusive line blocks from "
        "one existing UTF-8 text file. Use this tool only for large text modifications "
        "that remove many obsolete lines. For a small or local edit, use "
        "ReplaceStringInFile directly. For a large edit, first read the current file, call "
        "DeleteTextLines once with all obsolete line blocks, then read the shortened file "
        "again and use ReplaceStringInFile for precise content edits or insertions. Each "
        "line_blocks item is an integer or [start, end], for example "
        "[1, 4, 5, [10, 20], [40, 55]]. All items use the original pre-deletion line numbers. "
        "A range must be nested in the outer list: use [[10, 20]] for one range; "
        "[10, 20] deletes two individual lines. "
        "All ranges are validated before writing; overlapping or adjacent blocks are merged, "
        "and any invalid or out-of-range block cancels the entire operation. This tool does "
        "not delete files."
    )
    args_schema: Optional[ArgsSchema] = ArgDeleteTextLines
    return_direct: bool = False
    call_lock_arguments: Tuple[str, ...] = ("path",)

    @staticmethod
    def _normalize_line_blocks(
        line_blocks: List[_LineBlock],
        line_count: int,
    ) -> List[Tuple[int, int]]:
        if not line_blocks:
            raise ValueError("line_blocks must contain at least one line or range")
        ranges = []
        for block in line_blocks:
            if isinstance(block, bool):
                raise ValueError("line blocks must contain integers, not booleans")
            if isinstance(block, int):
                start = end = block
            elif (
                isinstance(block, (list, tuple))
                and len(block) == 2
                and all(
                    isinstance(value, int) and not isinstance(value, bool)
                    for value in block
                )
            ):
                start, end = block
            else:
                raise ValueError(
                    "each line block must be a positive integer or an inclusive "
                    "[start, end] pair"
                )
            if start < 1 or end < 1:
                raise ValueError("line numbers must be positive and one-based")
            if start > end:
                raise ValueError(f"line block [{start}, {end}] must have start <= end")
            if end > line_count:
                raise ValueError(
                    f"line block [{start}, {end}] is out of range for a file with "
                    f"{line_count} physical lines"
                )
            ranges.append((start, end))

        merged = []
        for start, end in sorted(ranges):
            if merged and start <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged

    def _run(
        self,
        path: str,
        line_blocks: List[_LineBlock],
        expected_sha256: Optional[str] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Delete validated line blocks and atomically replace the target text file."""

        del run_manager
        success, msg, real_path = self.check_file(path, for_write=True)
        if not success:
            self.do_callback(False, path, msg)
            return str_error(msg)
        if not is_text_file(real_path):
            error_msg = f"File {path} is not a text file."
            self.do_callback(False, path, error_msg)
            return str_error(error_msg)

        try:
            original_content, original_sha256, _newline = _read_text_snapshot(real_path)
            existing_mode = os.stat(real_path).st_mode & 0o7777
            if expected_sha256 is not None and expected_sha256 != original_sha256:
                error_msg = (
                    f"File {path} changed after it was read. Expected SHA256 "
                    f"{expected_sha256}, current SHA256 {original_sha256}. Read it again "
                    "and recalculate line_blocks."
                )
                self.do_callback(False, path, error_msg)
                return str_error(error_msg)

            original_lines = original_content.splitlines(keepends=True)
            try:
                merged_ranges = self._normalize_line_blocks(
                    line_blocks,
                    len(original_lines),
                )
            except ValueError as error:
                error_msg = (
                    f"Invalid line_blocks for {path}: {error}. No lines were deleted."
                )
                self.do_callback(False, path, error_msg)
                return str_error(error_msg)

            kept_lines = []
            cursor = 0
            for start, end in merged_ranges:
                kept_lines.extend(original_lines[cursor:start - 1])
                cursor = end
            kept_lines.extend(original_lines[cursor:])
            new_content = "".join(kept_lines)
            deleted_line_count = sum(end - start + 1 for start, end in merged_ranges)
            new_sha256 = _sha256_bytes(new_content.encode("utf-8"))
            diff_result, _ = _bounded_diff(original_content, new_content, path)

            if _sha256_file(real_path) != original_sha256:
                error_msg = (
                    f"File {path} changed while line deletion was being prepared. Read it "
                    "again and recalculate line_blocks."
                )
                self.do_callback(False, path, error_msg)
                return str_error(error_msg)
            _atomic_write_text(real_path, new_content, existing_mode=existing_mode)

            normalized_blocks = [list(block) for block in merged_ranges]
            self.do_callback(
                True,
                path,
                {
                    "changed": True,
                    "deleted_line_count": deleted_line_count,
                    "deleted_line_blocks": normalized_blocks,
                    "remaining_line_count": len(original_lines) - deleted_line_count,
                    "before_sha256": original_sha256,
                    "after_sha256": new_sha256,
                },
            )
            blocks_text = ", ".join(
                str(start) if start == end else f"{start}-{end}"
                for start, end in merged_ranges
            )
            line_label = "line" if deleted_line_count == 1 else "lines"
            return str_info(
                f"Deleted {deleted_line_count} physical {line_label} from '{path}' in "
                f"normalized blocks [{blocks_text}]. "
                f"{len(original_lines) - deleted_line_count} lines remain. "
                f"SHA256: {original_sha256} -> {new_sha256}. Read the updated file, "
                "then use ReplaceStringInFile for remaining precise content edits."
            ) + diff_result
        except UnicodeDecodeError as error:
            error_msg = f"Failed to decode file {path} as UTF-8: {error}"
            self.do_callback(False, path, error_msg)
            return str_error(error_msg)
        except (IOError, OSError) as error:
            error_msg = f"Failed to delete text lines from {path}: {error}"
            self.do_callback(False, path, error_msg)
            return str_error(error_msg)

    def __init__(self, workspace: str, write_dirs=None, un_write_dirs=None, **kwargs):
        """Initialize the tool."""
        super().__init__(**kwargs)
        self.init_base_rw(workspace, write_dirs, un_write_dirs)


class ArgReplaceStringInFile(StrictToolArgs):
    path: str = Field(
        ...,
        description="Text file path to modify, relative to the workspace.")
    old_string: str = Field(
        ...,
        min_length=1,
        description="Non-empty exact literal text to replace in an existing file, including enough context to make the match unique.")
    new_string: str = Field(
        ...,
        description="The exact literal text to replace old_string with. Ensure the resulting code is correct and idiomatic.")
    line_blocks: Optional[List[_LineRange]] = Field(
        default=None,
        min_length=1,
        max_length=1000,
        description=(
            "Optional one-based inclusive search blocks. Use [[start, end]] "
            "for one block or [[start1, end1], [start2, end2]] for multiple "
            "blocks; do not pass [start, end]. Omit for the whole file."
        ),
    )
    expected_sha256: Optional[str] = Field(
        default=None,
        description="Optional SHA-256 returned by ReadTextFile. The replacement fails if the file changed since it was read."
    )
    dry_run: bool = Field(
        default=False,
        description="Validate the replacement and return its diff without writing the file."
    )

    @model_validator(mode="after")
    def validate_line_blocks(self):
        for start, end in self.line_blocks or []:
            if start > end:
                raise ValueError(
                    f"line block [{start}, {end}] must have start <= end"
                )
        return self


class ReplaceStringInFile(UCTool, BaseReadWrite):
    """Replace exact string content in a text file with precise string matching."""
    name: str = "ReplaceStringInFile"
    description: str = (
        "Replace one unique occurrence of non-empty old_string in an existing UTF-8 "
        "text file. Both old_string and new_string must match the intended whitespace "
        "and newlines exactly. Include enough surrounding context to make old_string "
        "unique. Optionally pass one-based inclusive line_blocks: use [[10, 20]] "
        "for one block or [[10, 20], [40, 50]] for multiple blocks; do not pass "
        "[10, 20]. Omit line_blocks to search the whole file. Overlapping or "
        "adjacent blocks are merged, and the match must fit fully "
        "inside one normalized block. Use EditTextFile to create, overwrite, or append to "
        "a file. Repeating an already-applied replacement is reported as an actionable "
        "mismatch; calling with identical old_string and new_string is treated as success."
    )
    args_schema: Optional[ArgsSchema] = ArgReplaceStringInFile
    return_direct: bool = False
    call_lock_arguments: Tuple[str, ...] = ("path",)

    def _run(self, path: str, old_string: str, new_string: str,
             expected_sha256: Optional[str] = None, dry_run: bool = False,
             line_blocks: Optional[List[_LineRange]] = None,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Replace exact string content in a text file."""
        success, msg, real_path = self.check_file(path, for_write=True)
        if not success:
            self.do_callback(False, path, msg)
            return str_error(msg)

        file_exists = os.path.exists(real_path)
        if file_exists and not is_text_file(real_path):
            error_msg = f"File {path} is not a text file."
            self.do_callback(False, path, error_msg)
            return str_error(error_msg)
        info(f"Replacing string in file {real_path}")
        try:
            if file_exists:
                original_content, original_sha256, newline = _read_text_snapshot(real_path)
                existing_mode = os.stat(real_path).st_mode & 0o7777
            else:
                original_content = ""
                original_sha256 = _sha256_bytes(b"")
                newline = "\n"
                existing_mode = None
            if expected_sha256 is not None and expected_sha256 != original_sha256:
                error_msg = (
                    f"File {path} changed after it was read. Expected SHA256 "
                    f"{expected_sha256}, current SHA256 {original_sha256}. Read it again and retry."
                )
                self.do_callback(False, path, error_msg)
                return str_error(error_msg)

            old_content = _convert_newlines(old_string, newline)
            replacement_content = _convert_newlines(new_string, newline)
            normalized_blocks = None
            search_ranges = [(0, len(original_content))]
            if line_blocks is not None:
                original_lines = original_content.splitlines(keepends=True)
                try:
                    normalized_blocks = DeleteTextLines._normalize_line_blocks(
                        line_blocks,
                        len(original_lines),
                    )
                except ValueError as error:
                    error_msg = (
                        f"Invalid line_blocks for {path}: {error}. "
                        "No replacement was made."
                    )
                    self.do_callback(False, path, error_msg)
                    return str_error(error_msg)
                line_offsets = [0]
                for line in original_lines:
                    line_offsets.append(line_offsets[-1] + len(line))
                search_ranges = [
                    (line_offsets[start - 1], line_offsets[end])
                    for start, end in normalized_blocks
                ]

            occurrence_count = 0
            match_offset = None
            for range_start, range_end in search_ranges:
                selected_content = original_content[range_start:range_end]
                range_occurrence_count = selected_content.count(old_content)
                occurrence_count += range_occurrence_count
                if range_occurrence_count and match_offset is None:
                    match_offset = range_start + selected_content.find(old_content)

            scope_text = "the whole file"
            if normalized_blocks is not None:
                blocks_text = ", ".join(
                    f"{start}-{end}" for start, end in normalized_blocks
                )
                scope_text = f"line_blocks [{blocks_text}]"
            if occurrence_count == 0:
                error_msg = (
                    f"The specified old_string was not found in {scope_text}. "
                    "Read the current file and "
                    "retry with exact, unique text; if the desired content is already "
                    "present, no further write is needed."
                )
                self.do_callback(False, path, error_msg)
                return str_error(error_msg)
            if occurrence_count > 1:
                error_msg = (
                    f"The specified old_string appears {occurrence_count} times in "
                    f"{scope_text}. Narrow line_blocks or include more surrounding "
                    "context so it matches exactly once."
                )
                self.do_callback(False, path, error_msg)
                return str_error(error_msg)
            assert match_offset is not None
            new_content = (
                original_content[:match_offset]
                + replacement_content
                + original_content[match_offset + len(old_content):]
            )
            if new_content == original_content:
                result = {
                    "changed": False,
                    "line_blocks": (
                        [list(block) for block in normalized_blocks]
                        if normalized_blocks is not None
                        else None
                    ),
                    "before_sha256": original_sha256,
                    "after_sha256": original_sha256,
                }
                self.do_callback(True, path, result)
                return str_info(
                    f"File '{path}' already has the requested content; no write was needed. "
                    f"SHA256: {original_sha256}."
                )

            diff_result, _ = _bounded_diff(original_content, new_content, path)
            new_sha256 = _sha256_bytes(new_content.encode("utf-8"))
            if dry_run:
                return str_info(
                    f"Dry run successful for {path}. SHA256 would change from "
                    f"{original_sha256} to {new_sha256}."
                ) + diff_result
            if (
                expected_sha256 is not None
                and file_exists
                and _sha256_file(real_path) != original_sha256
            ):
                error_msg = f"File {path} changed while the replacement was being prepared. Read it again and retry."
                self.do_callback(False, path, error_msg)
                return str_error(error_msg)
            if file_exists:
                _atomic_write_text(real_path, new_content, existing_mode=existing_mode)
            else:
                _atomic_create_text(real_path, new_content)
            scope_suffix = (
                f" within {scope_text}" if normalized_blocks is not None else ""
            )
            success_msg = (
                f"Successfully replaced 1 occurrence of the specified string in {path}"
                f"{scope_suffix}. "
                f"SHA256: {original_sha256} -> {new_sha256}."
            )
            self.do_callback(
                True,
                path,
                {
                    "old_string": old_string,
                    "new_string": new_string,
                    "line_blocks": (
                        [list(block) for block in normalized_blocks]
                        if normalized_blocks is not None
                        else None
                    ),
                    "before_sha256": original_sha256,
                    "after_sha256": new_sha256,
                },
            )
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


class ArgGetFileInfo(StrictToolArgs):
    path: str = Field(
        ...,
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
        try:
            target_path = self.get_real_path(path, allow_workspace=True)
        except ValueError as exc:
            error_msg = str(exc)
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
                        info_lines.append(f"SHA256: {_sha256_file(target_path)}")
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
