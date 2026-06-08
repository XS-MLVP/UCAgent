# -*- coding: utf-8 -*-
"""Helpers for UCAgent workspace ``.tar.gz`` archives."""

from __future__ import annotations

import ntpath
import os
import posixpath
import shutil
import tarfile
import tempfile
from typing import Tuple


class WorkspaceArchiveError(ValueError):
    """Raised when a workspace archive is invalid or cannot be processed."""


def safe_archive_base(name: str, default: str = "workspace") -> str:
    base = os.path.basename(str(name or "").strip())
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in base).strip("._-")
    return cleaned or default


def create_workspace_archive(
    workspace_dir: str,
    archive_stem: str = "workspace",
    root_name: str = "workspace",
) -> Tuple[str, str, str]:
    """Create a ``.tar.gz`` archive whose top-level directory is ``root_name``.

    Returns ``(archive_path, filename, temp_dir)``. The caller owns ``temp_dir``
    and should remove it after the archive has been consumed.
    """

    source_dir = os.path.abspath(os.path.expanduser(workspace_dir))
    if not os.path.isdir(source_dir):
        raise WorkspaceArchiveError(f"Workspace directory not found: {source_dir}")

    archive_stem = safe_archive_base(archive_stem, "workspace")
    root_name = safe_archive_base(root_name, "workspace")
    temp_dir = tempfile.mkdtemp(prefix="ucagent_workspace_archive_")
    archive_path = os.path.join(temp_dir, f"{archive_stem}.tar.gz")
    try:
        with tarfile.open(archive_path, "w:gz") as tf:
            tf.add(source_dir, arcname=root_name, recursive=True)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return archive_path, f"{archive_stem}.tar.gz", temp_dir


def _normalize_archive_member_path(name: str, root_name: str) -> str:
    raw = name or ""
    raw_parts = raw.split("/")
    normalized = posixpath.normpath(raw)
    if (
        "\\" in raw
        or normalized in ("", ".")
        or ".." in raw_parts
        or normalized.startswith("../")
        or normalized == ".."
        or posixpath.isabs(normalized)
        or ntpath.isabs(raw)
    ):
        raise WorkspaceArchiveError(f"Unsafe archive entry path: {name}")
    parts = normalized.split("/")
    if not parts or parts[0] != root_name:
        raise WorkspaceArchiveError(
            f"Invalid workspace archive layout: archive root must contain a direct '{root_name}' directory"
        )
    return normalized


def _validate_archive_symlink(member: tarfile.TarInfo, normalized_name: str, root_name: str) -> None:
    linkname = member.linkname or ""
    if (
        not linkname
        or "\\" in linkname
        or posixpath.isabs(linkname)
        or ntpath.isabs(linkname)
    ):
        raise WorkspaceArchiveError(f"Unsafe archive symlink target: {member.name} -> {linkname}")

    target = posixpath.normpath(posixpath.join(posixpath.dirname(normalized_name), linkname))
    if (
        target in ("", ".", "..")
        or target.startswith("../")
        or posixpath.isabs(target)
        or not (target == root_name or target.startswith(root_name + "/"))
    ):
        raise WorkspaceArchiveError(f"Unsafe archive symlink target: {member.name} -> {linkname}")


def _extractall_workspace_archive(tf: tarfile.TarFile, extract_dir: str) -> None:
    data_filter = getattr(tarfile, "data_filter", None)
    extractall_kwargs = getattr(tarfile.TarFile.extractall, "__kwdefaults__", {}) or {}
    if data_filter is not None and "filter" in extractall_kwargs:
        tf.extractall(extract_dir, filter=data_filter)
    else:
        tf.extractall(extract_dir)


def extract_workspace_root_archive(
    archive_path: str,
    extract_dir: str,
    root_name: str = "workspace",
    required_subdir: str = "",
) -> str:
    """Safely extract a workspace archive and return the extracted root path."""

    archive_path = os.path.abspath(os.path.expanduser(archive_path))
    extract_dir = os.path.abspath(os.path.expanduser(extract_dir))
    root_name = safe_archive_base(root_name, "workspace")
    root_dir = os.path.join(extract_dir, root_name)
    try:
        with tarfile.open(archive_path, "r:gz") as tf:
            members = tf.getmembers()
            if not members:
                raise WorkspaceArchiveError("Workspace archive is empty")
            has_workspace_root = False
            for member in members:
                name = member.name or ""
                normalized = _normalize_archive_member_path(name, root_name)
                if member.islnk():
                    raise WorkspaceArchiveError(f"Unsupported archive hard link entry: {name}")
                if member.issym():
                    _validate_archive_symlink(member, normalized, root_name)
                elif not (member.isdir() or member.isfile()):
                    raise WorkspaceArchiveError(f"Unsupported archive entry type: {name}")
                if normalized == root_name or normalized.startswith(root_name + "/"):
                    has_workspace_root = True
            if not has_workspace_root:
                raise WorkspaceArchiveError(
                    f"Invalid workspace archive layout: missing root '{root_name}' directory"
                )
            os.makedirs(extract_dir, exist_ok=True)
            _extractall_workspace_archive(tf, extract_dir)
    except WorkspaceArchiveError:
        raise
    except tarfile.TarError as exc:
        raise WorkspaceArchiveError(f"Invalid or unreadable .tar.gz workspace archive: {archive_path}: {exc}") from exc
    except OSError as exc:
        raise WorkspaceArchiveError(f"Failed to extract workspace archive to {extract_dir}: {exc}") from exc

    if not os.path.isdir(root_dir):
        raise WorkspaceArchiveError(
            f"Invalid workspace archive layout: extracted directory is missing '{root_dir}'"
        )
    if required_subdir:
        required_path = os.path.join(root_dir, required_subdir)
        if not os.path.isdir(required_path):
            raise WorkspaceArchiveError(
                f"Invalid workspace archive layout: expected directory '{required_subdir}' under '{root_dir}'"
            )
    return root_dir
