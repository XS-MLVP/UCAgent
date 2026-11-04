"""Filesystem, command, and configuration contracts for repository development."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import time
from typing import Any

from ..contracts import canonical_json_sha256, resolved_output, sha256_file


def relative_path(value: str) -> str:
    """Validate a portable relative path, including paths of files not yet created."""

    path = PurePosixPath(value)
    if (not value or path.is_absolute() or ".." in path.parts or "\\" in value
            or any(ord(c) < 32 for c in value) or str(path) != value
            or ".git" in path.parts):
        raise ValueError(f"Expected a normalized repository-relative path: {value!r}")
    return value


def inside(root: Path, value: str, *, exists: bool = False) -> Path:
    """Resolve a relative artifact without traversing any symbolic link."""

    relative_path(value)
    path = root / value
    for parent in (path, *path.parents):
        if parent == root.parent:
            break
        if parent.is_symlink():
            raise ValueError(f"Artifact must not traverse a symbolic link: {path}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Artifact escaped its root: {value}")
    if exists and not path.exists():
        raise ValueError(f"Required artifact is missing: {path}")
    return path


def selected_path(name: str, roots: list[str], *, ancestor: bool = False) -> bool:
    """Match explicit source files/directories, optionally including their ancestors."""

    return not roots or any(root == "." or name == root or name.startswith(root + "/")
                            or (ancestor and root.startswith(name + "/")) for root in roots)


def tree_identity(root: Path) -> dict[str, dict[str, Any]]:
    """Describe file contents, executable modes, and safe internal symbolic links."""

    rows = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        relative_path(name)
        if path.is_symlink():
            target = os.readlink(path)
            if Path(target).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError(f"Symbolic link escapes the snapshot: {name} -> {target}")
            rows[name] = {"link": target, "mode": "120000"}
        elif path.is_file():
            rows[name] = {"sha256": sha256_file(path), "mode": (
                "100755" if path.stat().st_mode & 0o111 else "100644"
            )}
        elif not path.is_dir():
            raise ValueError(f"Unsupported repository entry: {name}")
    return rows


def run_command(argv: list[str], cwd: Path, timeout: int, *, env: dict | None = None) -> dict:
    """Execute argv without a shell and terminate descendants on timeout or cancellation."""

    if not argv or any(not isinstance(a, str) or not a or "\0" in a for a in argv):
        raise ValueError("Command argv must be a nonempty list of nonempty strings")
    if env is None:
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("GIT_") and key != "SOURCE_PATH"}
    started = time.monotonic()
    process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise
    result = {"argv": argv, "returncode": process.returncode,
              "duration_seconds": round(time.monotonic() - started, 3),
              "stdout": stdout[-12000:], "stderr": stderr[-12000:]}
    if process.returncode:
        detail = (stderr or stdout).strip()
        if "Traceback (most recent call last):" in detail:
            compiler_output = detail.split("Traceback (most recent call last):", 1)[0].strip()
            frames = re.findall(r'File "([^"\n]+)", line (\d+)', detail)
            location = f"{frames[-1][0]}:{frames[-1][1]}: " if frames else ""
            detail = compiler_output[-2600:] + "\n" + location + detail.splitlines()[-1][-1000:]
        raise ValueError(f"Command failed in {cwd}: executable={argv[0]}, exit={process.returncode}; {detail[-4000:]}")
    return result


def git_read(source: Path, *args: str) -> bytes:
    """Read Git objects/status without index refresh or inherited Git routing variables."""

    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(source), *args],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            check=False, timeout=120)
    if result.returncode:
        raise ValueError(f"Cannot read Git source {source}: {result.stderr.decode(errors='replace')[-2000:]}")
    return result.stdout


class RepoPaths:
    """Resolve one workflow's private state and editable artifacts from resolved config."""

    def __init__(self, workspace: str | Path, cfg: Any):
        """Reject overlapping source/workspace paths before creating any artifact."""

        self.workspace = Path(workspace).resolve()
        self.cfg = cfg
        self.output = inside(self.workspace, resolved_output(cfg))
        self.edit = inside(self.output, "repo")
        self.state = inside(self.workspace, ".ucagent/repo_module")
        self.snapshot = inside(self.workspace, "source_snapshot")
        self.run = inside(self.workspace, "run/repo_module")
        raw = cfg.get_value("design_with_ppa.repo.source_path", "")
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("Set design_with_ppa.repo.source_path (SOURCE_PATH) to a Git repository")
        self.source = Path(raw).expanduser().resolve()
        if self.source.is_relative_to(self.workspace) or self.workspace.is_relative_to(self.source):
            raise ValueError("SOURCE_PATH and workspace must be separate, non-overlapping directories")
        self.options = {
            "source_ref": cfg.get_value("design_with_ppa.repo.source_ref", "HEAD"),
            "snapshot_mode": cfg.get_value("design_with_ppa.repo.snapshot_mode", "commit"),
            "include_untracked": cfg.get_value("design_with_ppa.repo.include_untracked", []),
            "source_paths": cfg.get_value("design_with_ppa.repo.source_paths", []),
            "mode": cfg.get_value("design_with_ppa.repo.mode", "optimize"),
            "interface_policy": cfg.get_value("design_with_ppa.repo.interface_policy", "evolve"),
            "build_recipe": cfg.get_value("design_with_ppa.repo.build_recipe", "recipe.yaml"),
        }
        for key in ("source_paths", "include_untracked"):
            if hasattr(self.options[key], "as_dict"):
                self.options[key] = self.options[key].as_dict()
            if not isinstance(self.options[key], list) or any(not isinstance(p, str) for p in self.options[key]):
                raise ValueError(f"{key} must be an explicit list of relative paths")
            for name in self.options[key]:
                relative_path(name)
            if len(set(self.options[key])) != len(self.options[key]):
                raise ValueError(f"{key} must not contain duplicates")
        for name in self.options["include_untracked"]:
            if not selected_path(name, self.options["source_paths"]):
                raise ValueError(f"include_untracked is outside source_paths: {name}")
        for field, allowed in (("snapshot_mode", ("commit", "working_tree")),
                               ("mode", ("optimize", "add")),
                               ("interface_policy", ("preserve", "evolve"))):
            if self.options[field] not in allowed:
                raise ValueError(f"design_with_ppa.repo.{field} must be one of {allowed}")
        if not isinstance(self.options["source_ref"], str) or not self.options["source_ref"]:
            raise ValueError("source_ref must be a nonempty Git revision")
        relative_path(self.options["build_recipe"])

    def identity(self) -> str:
        """Bind import settings so a resumed workspace cannot silently change its source."""

        return canonical_json_sha256({"source": str(self.source), **self.options})
