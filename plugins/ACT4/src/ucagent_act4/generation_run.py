"""Import selected asset sources and preserve immutable, reproducible generation baselines."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

from .resources import clone_local
from .xiangshan_bundle import safe_path, sha256


def git_source_files(root: Path) -> list[str]:
    """List versioned and nonignored files without stripping significant filename whitespace."""
    names = sorted(set(filter(None, subprocess.run(
        ["git", "--no-optional-locks", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        check=True, capture_output=True, text=True, timeout=30).stdout.split("\0"))))
    result = []
    for name in names:
        path = root / name
        if path.is_dir() and (path / ".git").exists():
            result.extend(f"{name}/{child}" for child in git_source_files(path))
        else:
            result.append(name)
    return result


def copy_source_overlay(source: Path, target: Path) -> None:
    """Overlay a dirty source snapshot on its pinned clone, including additions and deletions."""
    for name in git_source_files(source):
        original, destination = source / name, target / name
        if original.is_dir():
            continue
        if original.is_symlink() and destination.is_symlink() and original.readlink() == destination.readlink():
            continue
        if destination.exists() or destination.is_symlink():
            destination.unlink()
        if original.is_symlink():
            raise ValueError(f"Modified source overlays require regular files: {name}")
        if original.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, destination)


def clone_source_snapshot(source: Path, target: Path, logs: Path, deadline: float, process_started=None) -> None:
    """Rebuild a pinned source plus its explicit uncommitted input overlay, without making commits."""
    clone_local(source, target, logs, deadline, process_started)
    copy_source_overlay(source, target)


def source_inventory(root: Path) -> list[str]:
    """Discover candidate files without exposing their content or treating logs as test assets."""
    excluded = {".git", ".ucagent", ".venv", "__pycache__", "node_modules", "asset-validation", "completion-validation", "native-validation"}
    endings = {".yaml", ".yml", ".csv", ".adoc", ".md", ".py", ".S", ".sv", ".svh", ".h", ".c", ".sail", ".json", ".patch"}
    if (root / ".git").exists():
        names = git_source_files(root)
    else:
        names = []
        for current, children, files in os.walk(root, followlinks=False):
            children[:] = [name for name in children if name not in excluded and not (Path(current) / name).is_symlink()]
            names.extend((Path(current) / name).relative_to(root).as_posix() for name in files if not (Path(current) / name).is_symlink())
    return [name for name in names if not set(Path(name).parts) & excluded and Path(name).suffix in endings]


def accepted_design(workspace: Path, output: str, suite: str, get_value) -> dict:
    """Require the authenticated ISA-only design before exposing existing asset contents."""
    review_dir = f"{output}/intermediate/{suite}/review"
    state = get_value(f"act4_review:{review_dir}:{suite}", {})
    path = safe_path(workspace, review_dir + "/isa-plan-accepted.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
    if state.get("isa_plan") != digest:
        raise ValueError("Complete the independent ISA design before selecting or importing existing assets")
    return document


def import_receipt(workspace: Path, settings: dict, get_value) -> dict:
    """Authenticate imported baselines and original input files before any later gate uses them."""
    from .checkers.act4_asset_checklist_checker import source_state

    directory = safe_path(workspace, f"{settings['output']}/intermediate/{settings['suite']}/asset-inputs")
    path = directory / "receipt.json"
    if get_value(f"act4_generation_run:{directory}", None) != sha256(path):
        raise ValueError("Import assets with Check(action=import); current source provenance is missing or changed")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["settings"] != settings:
        raise ValueError("Run configuration changed; use a new workspace")
    if sha256(directory / "selection.yaml") != data["selection_sha256"]:
        raise ValueError("Source selection changed after import; use a new workspace")
    for record in data["repositories"].values():
        if source_state(safe_path(workspace, record["baseline"])) != record["baseline_state"]:
            raise ValueError("Imported input baseline changed; restore it or start a new run")
    for name, facts in data["local_inputs"].items():
        path = Path(name)
        if any(part.is_symlink() for part in [path, *path.parents]) or sha256(path) != facts["sha256"] or stat.S_IMODE(path.stat().st_mode) != facts["mode"]:
            raise ValueError(f"Original local asset changed after import: {name}")
    return data
