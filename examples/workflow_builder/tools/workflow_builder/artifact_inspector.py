# -*- coding: utf-8 -*-
"""Read-only structured inspection helpers for generated workflow artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .delivery_contract import (
    is_release_runtime_artifact,
    load_acceptance_contract,
)


def _inside(root: Path, candidate: Path) -> bool:
    return candidate == root or root in candidate.parents


def safe_path(root: Path, value: str, *, must_be_file: bool = False) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or not value:
        raise ValueError(f"unsafe workflow-relative path: {value}")
    path = (root / relative).resolve()
    if not _inside(root, path):
        raise ValueError(f"path escapes workflow root: {value}")
    if must_be_file and not path.is_file():
        raise ValueError(f"file does not exist: {value}")
    return path


def inspect_yaml(root: Path, path_text: str) -> dict[str, Any]:
    path = safe_path(root, path_text, must_be_file=True)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    result: dict[str, Any] = {
        "action": "yaml_summary",
        "path": path.relative_to(root).as_posix(),
        "root_type": type(data).__name__,
    }
    if isinstance(data, dict):
        result["top_level_keys"] = sorted(str(key) for key in data)
        stages = data.get("stage", data.get("stages"))
        if stages is not None:
            result["stage_container_type"] = type(stages).__name__
            if isinstance(stages, list):
                result["stage_count"] = len(stages)
                result["stage_names"] = [
                    item.get("name", f"<index:{index}>")
                    if isinstance(item, dict)
                    else f"<invalid:{index}:{type(item).__name__}>"
                    for index, item in enumerate(stages)
                ]
            elif isinstance(stages, dict):
                result["stage_count"] = len(stages)
                result["stage_names"] = [str(key) for key in stages]
    elif isinstance(data, list):
        result["item_count"] = len(data)
    return result


def inspect_release_tree(root: Path) -> dict[str, Any]:
    contract = load_acceptance_contract(root)
    files = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and ".install/packages" not in path.relative_to(root).as_posix()
    )
    directories = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_dir() and ".install/packages" not in path.relative_to(root).as_posix()
    )
    missing_files = [
        path for path in contract.required_public_files if not (root / path).is_file()
    ]
    missing_dirs = [
        path for path in contract.required_public_dirs if not (root / path).is_dir()
    ]
    runtime_artifacts = [
        path
        for path in files
        if is_release_runtime_artifact(path, contract.allowed_output_placeholders)
    ]
    return {
        "action": "release_tree",
        "file_count": len(files),
        "directory_count": len(directories),
        "missing_required_files": missing_files,
        "missing_required_directories": missing_dirs,
        "runtime_artifacts": runtime_artifacts,
        "ok": not (missing_files or missing_dirs or runtime_artifacts),
    }


def inspect_migration_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / ".install/manifest.json"
    if not manifest_path.is_file():
        raise ValueError(".install/manifest.json does not exist")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(".install/manifest.json must contain an object")
    packages = manifest.get("packages")
    package_directories = manifest.get("package_directories")
    if not isinstance(packages, dict) or not isinstance(package_directories, dict):
        raise ValueError("manifest packages and package_directories must be objects")

    modes: dict[str, Any] = {}
    for mode in ("full", "partial"):
        declared_files = packages.get(mode, [])
        declared_dirs = package_directories.get(mode, [])
        if not isinstance(declared_files, list) or not isinstance(declared_dirs, list):
            raise ValueError(f"manifest mode {mode} must use lists")
        package_root = root / ".install/packages" / mode
        actual_files = sorted(
            path.relative_to(package_root).as_posix()
            for path in package_root.rglob("*")
            if path.is_file()
        ) if package_root.is_dir() else []
        actual_dirs = sorted(
            path.relative_to(package_root).as_posix()
            for path in package_root.rglob("*")
            if path.is_dir()
        ) if package_root.is_dir() else []
        modes[mode] = {
            "declared_file_count": len(declared_files),
            "actual_file_count": len(actual_files),
            "missing_files": sorted(set(declared_files) - set(actual_files)),
            "unexpected_files": sorted(set(actual_files) - set(declared_files)),
            "declared_directory_count": len(declared_dirs),
            "actual_directory_count": len(actual_dirs),
            "missing_directories": sorted(set(declared_dirs) - set(actual_dirs)),
            "unexpected_directories": sorted(set(actual_dirs) - set(declared_dirs)),
        }
    return {
        "action": "migration_manifest",
        "modes": modes,
        "ok": all(
            not details[key]
            for details in modes.values()
            for key in (
                "missing_files",
                "unexpected_files",
                "missing_directories",
                "unexpected_directories",
            )
        ),
    }


def inspect_artifacts(root: Path, action: str, path: str = "") -> dict[str, Any]:
    if action == "yaml_summary":
        return inspect_yaml(root, path or "config.yaml")
    if action == "release_tree":
        return inspect_release_tree(root)
    if action == "migration_manifest":
        return inspect_migration_manifest(root)
    raise ValueError(
        "unsupported action; expected yaml_summary, release_tree, or migration_manifest"
    )
