"""Read-only Git import and repository-relative candidate materialization."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from ..contracts import atomic_json, canonical_json_sha256
from .common import RepoPaths, git_read, inside, relative_path, selected_path, tree_identity
from .evidence import seal, unseal


def export_tree(source: Path, revision: str, destination: Path, *, working: bool,
                submodules: dict, prefix: str = "", source_paths: list[str] | None = None,
                excluded_submodules: dict | None = None, matched: set | None = None) -> None:
    """Export tracked files and recursively pinned submodules without running Git filters."""

    commit = git_read(source, "rev-parse", "--verify", f"{revision}^{{commit}}").decode().strip()
    entries = git_read(source, "ls-tree", "-rz", commit).split(b"\0")
    links, blobs = [], []
    for entry in filter(None, entries):
        meta, raw_name = entry.split(b"\t", 1)
        mode, kind, oid = meta.decode().split()
        name = relative_path(raw_name.decode())
        if not selected_path(prefix + name, source_paths or [], ancestor=kind == "commit"):
            if kind == "commit" and excluded_submodules is not None:
                excluded_submodules[prefix + name] = oid
            continue
        if kind == "commit":
            links.append((name, oid))
        else:
            if matched is not None:
                matched.add(prefix + name)
            blobs.append((mode, name, oid))
    destination.mkdir(parents=True, exist_ok=True)
    # Object reads avoid archive export-ignore/export-subst and checkout smudge
    # filters, both of which can silently change the selected commit's contents.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    with subprocess.Popen(["git", "-C", str(source), "cat-file", "--batch"], env=env,
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        for mode, name, oid in blobs:
            process.stdin.write((oid + "\n").encode())
            process.stdin.flush()
            header = process.stdout.readline().decode().split()
            if len(header) != 3 or header[:2] != [oid, "blob"]:
                raise ValueError(f"Git object is unavailable: {name}")
            remaining = int(header[2])
            target = inside(destination, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            if mode == "120000":
                target.symlink_to(process.stdout.read(remaining).decode())
            else:
                with target.open("wb") as stream:
                    while remaining:
                        chunk = process.stdout.read(min(remaining, 1024 * 1024))
                        if not chunk:
                            raise ValueError(f"Git object ended before its declared size: {name}")
                        stream.write(chunk)
                        remaining -= len(chunk)
                target.chmod(0o755 if mode == "100755" else 0o644)
            process.stdout.read(1)
        process.stdin.close()
        if process.wait(timeout=120):
            raise ValueError("Git object export failed; verify that the selected commit is available")
    if working:
        tracked = git_read(source, "ls-files", "-z").split(b"\0")
        submodule_names = {name for name, _ in links}
        for raw_name in filter(None, tracked):
            name = relative_path(raw_name.decode())
            if name in submodule_names or not selected_path(prefix + name, source_paths or []):
                continue
            if matched is not None:
                matched.add(prefix + name)
            original = source / name
            target = destination / name
            if target.is_symlink() or target.is_file():
                target.unlink()
            if original.is_symlink():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(os.readlink(original))
            elif original.is_file():
                # Parent symlinks must never route reads outside the selected source.
                if not original.resolve().is_relative_to(source.resolve()):
                    raise ValueError(f"Tracked source escapes its repository: {name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, target)
            elif original.exists():
                raise ValueError(f"Tracked source is not a file: {name}")
        # Staged deletions are absent from the tracked set; surviving untracked
        # copies are imported only through include_untracked.
        current = {p.decode() for p in tracked if p}
        for entry in filter(None, entries):
            meta, raw_name = entry.split(b"\t", 1)
            name = raw_name.decode()
            if meta.startswith(b"160000") or name in current:
                continue
            target = destination / name
            if target.is_file() or target.is_symlink():
                target.unlink()
    for name, oid in links:
        child = source / name
        if not (child / ".git").exists():
            raise ValueError(f"Submodule {prefix + name} is unavailable; prepare its pinned objects in a separate checkout")
        selected = git_read(child, "rev-parse", "HEAD").decode().strip() if working else oid
        submodules[prefix + name] = selected
        export_tree(child, selected, destination / name, working=working,
                    submodules=submodules, prefix=prefix + name + "/", source_paths=source_paths,
                    excluded_submodules=excluded_submodules, matched=matched)


def snapshot_repository(paths: RepoPaths) -> dict:
    """Import once atomically, then validate the complete cached snapshot on every use."""

    manifest_path = paths.state / "source.json"
    if manifest_path.exists():
        manifest = unseal(paths, manifest_path)
        if manifest["settings_identity"] != paths.identity():
            raise ValueError("Source settings changed; start a new workspace for this source selection")
        if tree_identity(paths.snapshot) != manifest["files"]:
            raise ValueError("source_snapshot changed; restore it from the imported revision in a new workspace")
        return manifest
    if paths.snapshot.exists():
        raise ValueError("Unowned source_snapshot exists; select an empty workspace")
    root = git_read(paths.source, "rev-parse", "--show-toplevel").decode().strip()
    if Path(root).resolve() != paths.source:
        raise ValueError("SOURCE_PATH must identify the repository root")
    commit = git_read(paths.source, "rev-parse", "--verify",
                      f"{paths.options['source_ref']}^{{commit}}").decode().strip()
    working = paths.options["snapshot_mode"] == "working_tree"
    if working and git_read(paths.source, "rev-parse", "HEAD").decode().strip() != commit:
        raise ValueError("working_tree snapshot requires source_ref to resolve to HEAD")
    if not working and paths.options["include_untracked"]:
        raise ValueError("include_untracked requires snapshot_mode=working_tree")
    dirty = git_read(paths.source, "status", "--porcelain=v1", "-z", "--untracked-files=normal")
    paths.state.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="snapshot-", dir=paths.state))
    try:
        submodules, excluded_submodules, matched = {}, {}, set()
        export_tree(paths.source, commit, temporary, working=working, submodules=submodules,
                    source_paths=paths.options["source_paths"], excluded_submodules=excluded_submodules,
                    matched=matched)
        for name in paths.options["include_untracked"]:
            source = inside(paths.source, name, exists=True)
            target = inside(temporary, name)
            if target.exists() or not source.is_file():
                raise ValueError(f"include_untracked must select an untracked regular file: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            matched.add(name)
        for name in paths.options["source_paths"]:
            if not any(selected_path(p, [name]) for p in matched):
                raise ValueError(f"source_paths entry matched no tracked or explicitly included file: {name}")
        files = tree_identity(temporary)
        if not files:
            raise ValueError("Selected source snapshot contains no files")
        manifest = {"schema_version": 1, "settings_identity": paths.identity(),
                    "selection": paths.options,
                    "commit": commit, "submodules": submodules, "files": files,
                    "excluded_submodules": excluded_submodules,
                    "snapshot_identity": canonical_json_sha256(files),
                    "snapshot_mode": paths.options["snapshot_mode"],
                    "local_changes_excluded": bool(dirty) and not working,
                    "source_status": dirty.decode(errors="replace").split("\0")[:50]}
        os.replace(temporary, paths.snapshot)
        atomic_json(manifest_path, seal(paths, manifest))
        return manifest
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def materialize(snapshot: Path, candidate: Path, changes: list, destination: Path) -> dict:
    """Copy a snapshot and apply only declared add/replace/delete operations."""

    if destination.exists():
        raise ValueError(f"Build destination must be new: {destination}")
    shutil.copytree(snapshot, destination, symlinks=True)
    seen = set()
    for change in changes:
        name, action = change.path, change.action
        if name in seen:
            raise ValueError(f"Duplicate candidate change: {name}")
        seen.add(name)
        target = inside(destination, name)
        if action == "add" and target.exists():
            raise ValueError(f"add requires an absent source path: {name}")
        if action in {"replace", "delete"} and not target.is_file():
            raise ValueError(f"{action} requires an existing regular source file: {name}")
        if action == "delete":
            target.unlink()
        else:
            source = inside(candidate / "files", name, exists=True)
            if not source.is_file():
                raise ValueError(f"Candidate source must be a regular file: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            target.chmod(0o755 if change.executable else 0o644)
    actual = set(tree_identity(candidate / "files"))
    expected = {c.path for c in changes if c.action != "delete"}
    if actual != expected:
        raise ValueError(f"Candidate files must exactly match changes: extra={sorted(actual - expected)}, missing={sorted(expected - actual)}")
    return tree_identity(destination)
