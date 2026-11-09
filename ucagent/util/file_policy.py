"""Shared workspace path and write-policy decisions independent of tools and runtime owners."""

import fnmatch
import glob as glob_module
import os
from pathlib import PurePosixPath
from typing import Optional, Tuple


def normalize_relative_path(path: str, *, allow_workspace: bool = False) -> str:
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


_WILDCARD_CHARACTERS = ("*", "?", "[")


def write_entry_has_wildcards(entry: str) -> bool:
    """Whether a write-policy entry contains glob wildcard characters."""
    return isinstance(entry, str) and any(
        character in entry for character in _WILDCARD_CHARACTERS
    )


def _entry_parts_match_prefix(path_parts: tuple, entry_parts: tuple) -> bool:
    """Whether path parts sit at or below entry parts, matching per segment.

    ``*``, ``?``, and ``[...]`` stay inside a single path segment; a dedicated
    ``**`` segment matches zero or more whole segments.
    """
    if not entry_parts:
        return True
    if entry_parts[0] == "**":
        return any(
            _entry_parts_match_prefix(path_parts[index:], entry_parts[1:])
            for index in range(len(path_parts) + 1)
        )
    if not path_parts:
        return False
    if not fnmatch.fnmatchcase(path_parts[0], entry_parts[0]):
        return False
    return _entry_parts_match_prefix(path_parts[1:], entry_parts[1:])


def path_is_at_or_below(path: str, entry: str) -> bool:
    """Whether a workspace-relative path is at or below a configured entry.

    Entries without wildcard characters keep exact component comparison; a
    wildcard entry covers every path it matches and everything below it.
    """
    path_parts = PurePosixPath(path).parts
    entry_parts = PurePosixPath(entry).parts
    if not write_entry_has_wildcards(entry):
        return path_parts[: len(entry_parts)] == entry_parts
    return _entry_parts_match_prefix(path_parts, entry_parts)


def wildcard_entry_overlaps(entry: str, directory: str) -> bool:
    """Whether a wildcard entry may match a directory, its subtree, or an ancestor.

    The check is lexical and conservative: overlap exists whenever the entry's
    segments agree with the directory's segments until one side is exhausted or
    a ``**`` segment appears, because the entry can then match a path that
    covers the directory in either direction.
    """
    directory_parts = PurePosixPath(directory).parts
    entry_parts = PurePosixPath(entry).parts
    for directory_part, entry_part in zip(directory_parts, entry_parts):
        if entry_part == "**":
            return True
        if not fnmatch.fnmatchcase(directory_part, entry_part):
            return False
    return True


def write_entry_matches_anything(workspace: str, entry: str) -> bool:
    """Whether a write-policy entry matches any existing path in the workspace.

    Literal entries require the exact path to exist; wildcard entries use glob
    expansion with recursive ``**`` support.
    """
    if not write_entry_has_wildcards(entry):
        return os.path.exists(os.path.join(workspace, entry))
    return bool(glob_module.glob(os.path.join(workspace, entry), recursive=True))


def deepest_matching_write_entry(path: str, entries) -> Tuple[int, Optional[str]]:
    """Return the segment depth and configured value of the deepest matching entry.

    Depth is the number of path segments in the entry (a ``**`` segment counts
    as one); ``(-1, None)`` means no entry matches the path.
    """
    best_depth, best_entry = -1, None
    for entry in entries:
        try:
            normalized = normalize_relative_path(entry)
        except ValueError:
            continue
        if path_is_at_or_below(path, normalized):
            depth = len(PurePosixPath(normalized).parts)
            if depth > best_depth:
                best_depth, best_entry = depth, entry
    return best_depth, best_entry


def is_file_writeable(path: str, un_write_dirs: list=None, write_dirs: list=None) -> Tuple[bool, str]:
    """Decide whether a workspace-relative path may be written.

    A path matching entries from both lists is decided by the deepest entry:
    a write entry strictly below a no-write entry carves that subtree back out
    as writable, while an equal-depth conflict keeps the path protected.
    """
    try:
        path = normalize_relative_path(path)
    except ValueError as exc:
        return False, str(exc)
    if un_write_dirs is None and write_dirs is None:
        return True, "No write restrictions defined."
    if un_write_dirs is not None:
        assert isinstance(un_write_dirs, list), "un_write_dirs must be a list."
    if write_dirs is not None:
        assert isinstance(write_dirs, list), "write_dirs must be a list."
    write_depth, write_entry = deepest_matching_write_entry(path, write_dirs or [])
    un_write_depth, un_write_entry = deepest_matching_write_entry(
        path, un_write_dirs or []
    )
    if write_entry is not None and write_depth > un_write_depth:
        if un_write_depth >= 0:
            return True, (
                f"Path '{path}' is allowed to write: it matches the write entry "
                f"'{write_entry}' inside a no-write area."
            )
        return True, f"Path '{path}' is allowed to write: it matches the write entry '{write_entry}'."
    if un_write_entry is not None:
        return False, (
            f"Path '{path}' is not allowed to write: it matches the "
            f"no-write entry '{un_write_entry}'."
        )
    if write_dirs is None:
        return True, f"Path '{path}' is allowed to write as it does not match any no-write directories: {un_write_dirs}."
    return False, f"Path '{path}' is not allowed to write, except in: {write_dirs}."


