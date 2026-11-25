"""Workspace-safe paths, immutable input fingerprints and atomic JSON files."""

import hashlib
import json
import os
from pathlib import Path
import tempfile


def local_path(workspace, relative, *, allow_root=False):
    """Resolve a relative path without permitting lexical or symlink escapes."""
    root = Path(workspace).resolve()
    if not isinstance(relative, str) or not relative.strip() or "\x00" in relative or "\\" in relative:
        raise ValueError(f"Expected a workspace-relative path: {relative!r}")
    part = Path(relative)
    if part.is_absolute() or ".." in part.parts:
        raise ValueError(f"Expected a workspace-relative path: {relative!r}")
    target = root / part
    try:
        resolved = target.resolve()
    except (OSError, RuntimeError) as error:
        raise ValueError(f"Cannot resolve workspace path: {relative}") from error
    if not resolved.is_relative_to(root) or (resolved == root and not allow_root):
        raise ValueError(f"Path escapes the allowed workspace: {relative}")
    return target


def digest(path):
    """Hash actual file bytes, including empty files."""
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, data):
    """Replace a JSON file atomically without leaving a partially written record."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(handle, "w") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def source_identity(project, workspace=None, extra_paths=()):
    """Hash source assets and declared input bytes, following only workspace-local links."""
    project = Path(project).resolve()
    workspace = Path(workspace or project).resolve()
    files = {}
    for folder in ("testbenches", "docs/spec", "rtl", "dut", "tools"):
        root = project / folder
        if not root.exists():
            continue
        visited = set()
        for directory, dirs, names in os.walk(root, followlinks=True):
            resolved = Path(directory).resolve()
            if not resolved.is_relative_to(workspace) or resolved in visited:
                raise ValueError(f"Source directory escapes the workspace or repeats through a link: {directory}")
            visited.add(resolved)
            dirs[:] = sorted(name for name in dirs if name not in {"__pycache__", ".pytest_cache"})
            for name in sorted(names):
                path = Path(directory) / name
                if not path.resolve().is_relative_to(workspace):
                    raise ValueError(f"Source file escapes the workspace: {path}")
                if path.suffix not in {".pyc", ".pyo"}:
                    files[path.relative_to(project).as_posix()] = digest(path)
    for name in ("__init__.py", "conftest.py", "pytest.ini", "workspace.json", "ucv.json", "requirements.txt",
                 "results/input_inventory.json"):
        path = project / name
        if path.is_file():
            if not path.resolve().is_relative_to(workspace):
                raise ValueError(f"Project input escapes the workspace: {name}")
            files[name] = digest(path)
    inventory = project / "results/input_inventory.json"
    if inventory.is_file():
        value = json.loads(inventory.read_text())
        for key in ("documents", "rtl"):
            for relative in value[key]:
                files["workspace:" + relative] = digest(local_path(workspace, relative))
    for relative in extra_paths:
        files["workspace:" + relative] = digest(local_path(workspace, relative))
    return files
