"""Minimal recoverable directory publication using an atomic symlink switch."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional
import uuid

from .task_manifest import utc_now


def version_store_for(target: Path) -> Path:
    target = Path(target)
    # Stable legacy paths are symlinks to one directory under a sibling
    # ``.<name>.versions`` store.  Do not follow that symlink and mistake an
    # active version's own ``.versions`` directory for the publication store.
    if target.is_symlink():
        return target.parent / f".{target.name}.versions"
    if target.is_dir() and (target / ".versions").is_dir():
        return target / ".versions"
    return target.parent / f".{target.name}.versions"


def active_stable_target(version_dir: Path) -> Optional[Path]:
    """Return the stable symlink selecting this sealed version, if active."""
    version_dir = Path(version_dir).resolve()
    store = version_dir.parent
    if store.name == ".versions":
        stable = store.parent
        current = stable / "current"
        if current.is_symlink() and current.resolve() == version_dir:
            return stable
        return None
    if not (store.name.startswith(".") and store.name.endswith(".versions")):
        return None
    stable = store.parent / store.name[1:-len(".versions")]
    if stable.is_symlink() and stable.resolve() == version_dir:
        return stable
    return None


def unpublished_version_dir(target: Path, version_id: str) -> Path:
    if not version_id or "/" in version_id or version_id in {".", ".."}:
        raise ValueError("invalid report version id")
    target = Path(target)
    if not target.exists():
        target.mkdir(parents=True)
        (target / ".versions").mkdir()
    store = version_store_for(target)
    store.mkdir(parents=True, exist_ok=True)
    temporary = store / f".{version_id}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir(parents=False, exist_ok=False)
    return temporary


def seal_version(temporary: Path, target: Path, version_id: str) -> Path:
    store = version_store_for(target)
    final = store / version_id
    if final.exists():
        raise ValueError(f"report version already exists: {final}")
    os.replace(str(temporary), str(final))
    return final


def publish_version(target: Path, version_dir: Path) -> Dict[str, object]:
    """Atomically point ``target`` at one sealed version.

    A legacy real directory is moved into the version store first and remains
    recoverable.  No directory is deleted or overwritten recursively.
    """
    # Preserve symlink identity, but normalize relative CLI paths before
    # comparing them with the resolved version store.
    target, version_dir = Path(target).absolute(), Path(version_dir).resolve()
    store = version_store_for(target).resolve()
    if version_dir.parent != store:
        raise ValueError("version directory is outside the target version store")
    if store.name == ".versions" and store.parent == target:
        current = target / "current"
        temporary_link = target / f".current.publish-{uuid.uuid4().hex}"
        os.symlink(os.path.relpath(version_dir, target), temporary_link)
        os.replace(str(temporary_link), str(current))
        for child in version_dir.iterdir():
            link = target / child.name
            if link.name in {".versions", "current"}:
                continue
            if link.exists() or link.is_symlink():
                link.unlink()
            os.symlink(f"current/{child.name}", link)
        return {
            "target": str(target.absolute()), "version_dir": str(version_dir),
            "version_id": version_dir.name, "migrated_legacy_dir": "",
        }

    migrated = ""
    if target.exists() and not target.is_symlink():
        legacy = store / ("legacy-" + utc_now().replace(":", "").replace("+", "_"))
        os.replace(str(target), str(legacy))
        migrated = str(legacy)
    temporary_link = target.parent / f".{target.name}.publish-{uuid.uuid4().hex}"
    relative = os.path.relpath(version_dir, target.parent)
    os.symlink(relative, temporary_link)
    os.replace(str(temporary_link), str(target))
    return {
        "target": str(target.absolute()),
        "version_dir": str(version_dir),
        "version_id": version_dir.name,
        "migrated_legacy_dir": migrated,
    }
