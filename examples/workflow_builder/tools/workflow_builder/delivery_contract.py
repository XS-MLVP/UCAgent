# -*- coding: utf-8 -*-
"""Shared acceptance and release-cleanliness rules for workflow delivery."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


PARTIAL_FORBIDDEN_PREFIXES = (
    "tools",
    "checkers",
    ".workflow/tool_specs",
    ".workflow/tool_tests",
    ".workflow/checker_specs",
    ".workflow/checker_tests",
    ".workflow/checkers",
)
FORBIDDEN_TOP_LEVEL = {".git", ".ucagent", "output", "reports", "tmp", "GuideDocs"}
FORBIDDEN_PARTS = {"__pycache__", ".pytest_cache", "logs", "temp", "runtime"}
FORBIDDEN_SUFFIXES = (".pyc", ".log")
PRESERVED_LOG_PREFIXES = (
    ".workflow/checker_tests/cases",
    ".workflow/tool_tests/cases",
    # Bundled examples are source fixtures.  A fixture may legitimately contain
    # a directory named logs; it is not a runtime log merely because of that name.
    "input/example/logs",
)
OUTPUT_PLACEHOLDER_NAMES = {"README.md", ".gitkeep", ".keep"}


@dataclass(frozen=True)
class AcceptanceContract:
    """Normalized public delivery requirements from acceptance_rules.yaml."""

    required_public_files: tuple[str, ...]
    required_public_dirs: tuple[str, ...]
    required_internal_files: tuple[str, ...]

    @property
    def allowed_output_placeholders(self) -> frozenset[str]:
        return frozenset(
            path
            for path in self.required_public_files
            if len(Path(path).parts) == 2
            and Path(path).parts[0] == "output"
            and Path(path).name in OUTPUT_PLACEHOLDER_NAMES
        )

    def package_files(self, mode: str) -> tuple[str, ...]:
        if mode == "full":
            return self.required_public_files
        if mode != "partial":
            raise ValueError(f"unsupported package mode: {mode}")
        return tuple(
            path
            for path in self.required_public_files
            if not has_prefix(path, PARTIAL_FORBIDDEN_PREFIXES)
        )

    def package_dirs(self, mode: str) -> tuple[str, ...]:
        if mode == "full":
            return self.required_public_dirs
        if mode != "partial":
            raise ValueError(f"unsupported package mode: {mode}")
        return tuple(
            path
            for path in self.required_public_dirs
            if not has_prefix(path, PARTIAL_FORBIDDEN_PREFIXES)
        )


def _normalize_paths(data: dict[str, Any], key: str) -> tuple[str, ...]:
    values = data.get(key, [])
    if not isinstance(values, list):
        raise ValueError(f"{key} must be a list")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} contains a non-string or empty path")
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or path.as_posix() in {".", ""}:
            raise ValueError(f"{key} contains an unsafe path: {value}")
        text = path.as_posix()
        if text not in normalized:
            normalized.append(text)
    return tuple(normalized)


def load_acceptance_contract(root: Path) -> AcceptanceContract:
    path = root / ".workflow/acceptance_rules.yaml"
    if not path.is_file():
        raise ValueError(f"acceptance_rules.yaml not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("acceptance_rules.yaml must contain a mapping")
    return AcceptanceContract(
        required_public_files=_normalize_paths(data, "required_public_files"),
        required_public_dirs=_normalize_paths(data, "required_public_dirs"),
        required_internal_files=_normalize_paths(data, "required_internal_files"),
    )


def has_prefix(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)


def is_release_runtime_artifact(
    relative_path: str,
    allowed_output_placeholders: set[str] | frozenset[str],
) -> bool:
    """Return whether a package file violates the shared release-cleanliness policy."""
    rel = Path(relative_path).as_posix()
    if rel == ".workflow/local/environment.yaml" or rel.startswith(".workflow/local/"):
        return True
    parts = Path(rel).parts
    preserve_log = has_prefix(rel, PRESERVED_LOG_PREFIXES)
    forbidden_top_level = bool(parts and parts[0] in FORBIDDEN_TOP_LEVEL)
    if rel in allowed_output_placeholders:
        forbidden_top_level = False
    return (
        forbidden_top_level
        or (any(part in FORBIDDEN_PARTS for part in parts) and not preserve_log)
        or (rel.endswith(FORBIDDEN_SUFFIXES) and not preserve_log)
        or rel.startswith(".install/packages/")
    )
