"""Select operator workspaces and confine file management to their actual roots."""

import json
import os
from pathlib import Path
from typing import NamedTuple

from ucagent.core.workspace.files import WorkspaceAccessError, WorkspaceFiles


class WorkspaceTarget(NamedTuple):
    """Identify a selected workspace without inferring whether its Agent is running."""

    root: str
    relative: str
    is_sub: bool


def is_under(root, candidate):
    """Check real filesystem containment, including symlink parents."""
    try:
        return Path(candidate).resolve().is_relative_to(Path(root).resolve())
    except (ValueError, OSError, RuntimeError):
        return False


def info_path(workspace):
    """Resolve the saved snapshot without following it outside its workspace."""
    return WorkspaceFiles(workspace).path(".ucagent/ucagent_info.json")


def is_workspace(workspace):
    """Recognize a workspace by an in-root saved snapshot file."""
    try:
        return os.path.isfile(info_path(workspace))
    except WorkspaceAccessError:
        return False


def load_info(workspace):
    """Read one saved snapshot without starting or updating an Agent."""
    path = info_path(workspace)
    if not os.path.isfile(path) or not os.path.getsize(path):
        return {}
    with open(path, encoding="utf-8") as stream:
        data = json.load(stream)
    return data if isinstance(data, dict) else {}


class WorkspaceAccess:
    """Own operator workspace selection; LLM task write policies remain tool-owned."""

    def __init__(self, base):
        """Bind the runtime's base workspace without filesystem side effects."""
        self.base = os.path.abspath(base)

    def relative(self, path):
        """Return a workspace's display path relative to this runtime."""
        relative = os.path.relpath(os.path.abspath(path), self.base)
        return "" if relative == "." else relative

    def select(self, raw=""):
        """Select the base or a recognized child, rejecting any real path escape."""
        raw = (raw or "").strip()
        if not raw:
            return WorkspaceTarget(self.base, "", False)
        expanded = os.path.expanduser(raw)
        candidate = os.path.abspath(expanded if os.path.isabs(expanded) else os.path.join(self.base, expanded))
        if not is_under(self.base, candidate):
            raise WorkspaceAccessError("invalid_path", "Sub workspace must be under the current workspace")
        if os.path.realpath(candidate) == os.path.realpath(self.base):
            return WorkspaceTarget(self.base, "", False)
        if not os.path.isdir(candidate):
            raise WorkspaceAccessError("not_found", f"Sub workspace '{raw}' not found")
        if not is_workspace(candidate):
            raise WorkspaceAccessError("invalid_argument", f"'{self.relative(candidate)}' is not a UCAgent workspace")
        return WorkspaceTarget(candidate, self.relative(candidate), True)

    def roots(self, current_root, max_depth=2):
        """Discover saved children within two levels, without escaping the selected root."""
        self.select(current_root)
        current_root = os.path.abspath(current_root)
        roots, seen = [], set()
        pending = [(current_root, 0)]
        while pending:
            parent, depth = pending.pop()
            if depth >= max(1, min(int(max_depth or 2), 2)):
                continue
            try:
                names = sorted(os.listdir(parent))
            except OSError:
                continue
            for name in names:
                full = os.path.join(parent, name)
                if not os.path.isdir(full) or not is_under(current_root, full) or not is_under(self.base, full):
                    continue
                real = os.path.realpath(full)
                if real in seen or real == os.path.realpath(self.base):
                    continue
                seen.add(real)
                if is_workspace(full):
                    roots.append(full)
                pending.append((full, depth + 1))
        return sorted(roots)

    def delete_subworkspace(self, raw, *, cleanup_parents=True):
        """Delete the selected child and reclaim only empty, non-workspace parents."""
        target = self.select(raw)
        if not target.is_sub:
            raise WorkspaceAccessError("invalid_argument", "The base workspace cannot be deleted")
        WorkspaceFiles(self.base).delete(target.relative)
        cleaned = []
        parent = os.path.dirname(target.root)
        # rmdir is deliberately nonrecursive: concurrent/new ordinary files must survive.
        while cleanup_parents and os.path.realpath(parent) != os.path.realpath(self.base):
            if not is_under(self.base, parent) or is_workspace(parent) or os.path.islink(parent):
                break
            try:
                os.rmdir(parent)
            except OSError:
                break
            cleaned.append(self.relative(parent))
            parent = os.path.dirname(parent)
        return {"deleted_path": target.relative, "deleted_paths": [target.relative, *cleaned],
                "cleaned_parent_paths": cleaned}

    def directory(self, target, relative=""):
        """List selected files with saved-workspace identity and navigation metadata."""
        files = WorkspaceFiles(target.root)
        path = files.path(relative)
        entries = files.list_directory(relative)
        for entry in entries:
            full = os.path.join(target.root, entry["path"])
            child = entry["is_dir"] and is_workspace(full) and os.path.realpath(full) != os.path.realpath(self.base)
            entry.update(is_ucagent_workspace=child, sub_workspace_path=self.relative(full) if child else "")
        child = is_workspace(path) and os.path.realpath(path) != os.path.realpath(self.base)
        return {"path": "" if path == files.root else os.path.relpath(path, files.root),
                "workspace": target.root, "base_workspace": self.base,
                "sub_workspace": target.relative, "is_sub_workspace": target.is_sub,
                "current_is_ucagent_workspace": child,
                "current_sub_workspace": self.relative(path) if child else "", "data": entries}

    def delete_file(self, target, relative):
        """Keep workspace deletion explicit while allowing recursive ordinary directories."""
        files = WorkspaceFiles(target.root)
        path = files.path(relative, allow_root=False)
        if is_workspace(path):
            raise WorkspaceAccessError("invalid_argument", "Use the sub-workspace deletion operation for a workspace directory.")
        files.delete(relative)
