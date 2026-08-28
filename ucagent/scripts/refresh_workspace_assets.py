#!/usr/bin/env python3
"""Remove copied UCAgent assets so the next restart installs current versions."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil


def _workspace_path(value: str) -> Path:
    workspace = Path(value).expanduser().resolve(strict=True)
    if not workspace.is_dir():
        raise ValueError(f"workspace is not a directory: {workspace}")
    root = Path(workspace.anchor).resolve()
    home = Path.home().resolve()
    if workspace in {root, home}:
        raise ValueError("workspace must not be the filesystem root or user home directory")
    return workspace


def _relative_cache_path(value: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("guide-doc-cache must be a non-empty relative path")
    path = Path(value.strip())
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(
            "guide-doc-cache must be a normalized relative path without '.' or '..'"
        )
    if "guide" not in path.name.casefold() or path.parts[0] == ".ucagent":
        raise ValueError(
            "guide-doc-cache must identify a Guide_Doc-style cache outside .ucagent"
        )
    return path


def _validate_target(workspace: Path, target: Path) -> None:
    if os.path.commonpath((str(workspace), str(target))) != str(workspace):
        raise ValueError(f"cache target escapes workspace: {target}")
    relative = target.relative_to(workspace)
    current = workspace
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"cache parent must not be a symlink: {current}")


def refresh_workspace_assets(workspace_value: str, guide_doc_cache: str) -> list[str]:
    """Delete only copied Skills and Guide_Doc caches under one workspace."""

    workspace = _workspace_path(workspace_value)
    guide_path = _relative_cache_path(guide_doc_cache)
    targets = (
        workspace / ".ucagent" / "skills",
        workspace.joinpath(*guide_path.parts),
    )
    for target in targets:
        _validate_target(workspace, target)
        if target.exists() and not target.is_symlink() and not target.is_dir():
            raise ValueError(f"cache target is not a directory or symlink: {target}")

    messages = []
    for target in targets:
        relative = target.relative_to(workspace).as_posix()
        if target.is_symlink():
            target.unlink()
            messages.append(f"removed cache symlink: {relative}")
        elif target.is_dir():
            shutil.rmtree(target)
            messages.append(f"removed cache directory: {relative}")
        else:
            messages.append(f"cache already absent: {relative}")
    return messages


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Remove copied UCAgent Skill and Guide_Doc caches while preserving "
            "runtime state, checkpoints, receipts, tests, and verification artifacts."
        )
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--guide-doc-cache", default="Guide_Doc")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        messages = refresh_workspace_assets(args.workspace, args.guide_doc_cache)
    except (OSError, ValueError) as error:
        print(f"Error: {error}")
        return 2
    for message in messages:
        print(message)
    print("Restart UCAgent for this workspace to copy the current assets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
