"""Validate protected paths and restore original permissions across the instance lifetime."""

from dataclasses import dataclass, field
from pathlib import Path
import os
import stat

import ucagent.util.functions as fc
from ucagent.util.file_policy import write_entry_has_wildcards

@dataclass
class PermissionChanges:
    """Remember original modes before changing them and restore exactly once."""

    workspace: str
    modes: dict[str, int] = field(default_factory=dict)

    def remember(self, paths):
        """Snapshot canonical workspace targets, including targets reached through links."""
        root = Path(self.workspace).resolve()
        for value in paths:
            path = Path(value)
            if not path.exists():
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                raise ValueError(f"File protection target must remain inside the workspace: {path}")
            # chmod follows links; aliases must share the target's original mode.
            self.modes.setdefault(str(resolved), stat.S_IMODE(resolved.stat().st_mode))

    def restore(self):
        """Restore acquired permission changes while retaining generated content."""
        failures = []
        for name, mode in reversed(tuple(self.modes.items())):
            path = Path(name)
            try:
                if path.exists() and not path.is_symlink():
                    if not path.resolve().is_relative_to(Path(self.workspace).resolve()):
                        raise ValueError(f"Permission restore target escaped the workspace: {path}")
                    path.chmod(mode)
                del self.modes[name]
            except (OSError, ValueError) as error:
                failures.append(error)
        if failures:
            raise ExceptionGroup("Workspace permission restoration failed", failures)


def apply_file_protection(cfg, workspace, no_write_targets, permissions):
    """Apply resolved file policy after recording the modes needed for cleanup."""
    if no_write_targets is not None:
        if not isinstance(no_write_targets, list):
            raise TypeError("no_write_targets must be a list of directories or files")
        for value in no_write_targets:
            path = Path(os.path.abspath(value))
            if not path.resolve().is_relative_to(Path(workspace).resolve()):
                raise ValueError(f"Specified no-write target {path} must be under the workspace {workspace}")
            if not write_entry_has_wildcards(value) and not path.exists():
                raise ValueError(f"Specified no-write target {path} does not exist")
            cfg.un_write_dirs.append(fc.rm_workspace_prefix(workspace, str(path)))
    try:
        for pattern in cfg.get_value("un_write_dirs", []):
            for name in fc.find_files_by_pattern(workspace, pattern):
                path = Path(workspace) / name
                permissions.remember([path])
                if path.is_dir():
                    # Match the chmod traversal: enter a selected directory link,
                    # but do not recurse through links discovered beneath it.
                    for directory, dirs, files in os.walk(path, followlinks=False):
                        permissions.remember(Path(directory) / child for child in [*dirs, *files])
        return fc.chmode_ro_by_pattern(workspace, cfg.get_value("un_write_dirs", []),
                                      write_dirs=cfg.get_value("write_dirs", None))
    except BaseException:
        permissions.restore()
        raise
