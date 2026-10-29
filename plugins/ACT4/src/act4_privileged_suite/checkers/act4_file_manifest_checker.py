"""Validate ACT4 manifests while protecting critical framework code."""

from __future__ import annotations

import ast
import fnmatch
import glob
import hashlib
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

from .act4_asset_consistency import (
    _generator_workspace_dependencies,
    is_itgen_private_path,
)

try:
    import yaml
except ImportError:  # pragma: no cover - reported by the checker.
    yaml = None  # type: ignore[assignment]

from ucagent.checkers.base import Checker


ACTIONS = {"created", "generated", "copied", "modified", "deleted"}
CATEGORIES = {
    "contribution_source",
    "generated_test",
    "build_artifact",
    "tool_artifact",
    "internal_asset",
    "report",
    "checker_output",
    "auxiliary_config",
    "unclassified",
}
STAGES = {
    "01_coverpoints",
    "02_norm_mapping",
    "03_vm_resources",
    "04_generator",
    "05_build",
    "06_contribution",
    "07_final_report",
}
EVENTS = {
    "created",
    "generated",
    "copied",
    "modified",
    "restored",
    "deleted",
    "policy_violation",
}
DEFAULT_PROTECTED_ACT4_PATTERNS = [
    "framework/**",
    "generators/testgen/src/testgen/**",
    "generators/testgen/scripts/**",
    "generators/coverage/**",
    "generators/ctp/**",
    "tests/env/**",
    "Makefile",
    "run_tests.py",
    "pyproject.toml",
    "uv.lock",
    ".mise.toml",
    "config/**",
    "**/link.ld",
    "**/rvmodel_macros.h",
    "**/sail.json",
]
DEFAULT_ARTIFACT_ACT4_PATTERNS = [
    ".venv/**",
    "work*/**",
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "**/.mypy_cache/**",
    "**/.ruff_cache/**",
    "**/.cache/**",
    "**/*.log",
    "**/*.stamp",
]
INVENTORY_NOISE_PATTERNS = [
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "**/.mypy_cache/**",
    "**/.ruff_cache/**",
    "**/*.pyc",
]


class ACT4FileManifestChecker(Checker):
    """Check manifests, output completeness, and protected ACT4 integrity."""

    def __init__(
        self,
        manifest_file: str,
        expected_suite: str | None = None,
        act4_root: str = "riscv-arch-test",
        inventory_patterns: Any = None,
        protected_act4_patterns: Any = None,
        protected_act4_exclude_patterns: Any = None,
        artifact_act4_patterns: Any = None,
        integrity_only: bool = False,
        require_contribution_set: bool = False,
        need_human_check: bool = False,
        cfg: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        if kwargs:
            raise TypeError(
                f"unsupported ACT4FileManifestChecker arguments: {sorted(kwargs)}"
            )
        self.manifest_file = manifest_file
        self.expected_suite = expected_suite
        self.act4_root = act4_root
        self.inventory_patterns = list(inventory_patterns or [])
        suite_generator = (
            f"generators/testgen/src/testgen/priv/extensions/{expected_suite}.py"
            if expected_suite
            else None
        )
        self.protected_act4_patterns = list(
            protected_act4_patterns or DEFAULT_PROTECTED_ACT4_PATTERNS
        )
        self.protected_act4_exclude_patterns = list(
            dict.fromkeys(
                ([suite_generator] if suite_generator else [])
                + list(protected_act4_exclude_patterns or [])
            )
        )
        self.artifact_act4_patterns = list(
            artifact_act4_patterns or DEFAULT_ARTIFACT_ACT4_PATTERNS
        )
        self.integrity_only = bool(integrity_only)
        self.require_contribution_set = bool(require_contribution_set)
        if hasattr(self, "set_human_check_needed"):
            self.set_human_check_needed(need_human_check)

    def _root(self) -> Path:
        return Path(getattr(self, "workspace", None) or os.getcwd()).resolve()

    def _resolve(self, value: str) -> Path:
        path = Path(value).expanduser()
        absolute = path if path.is_absolute() else self._root() / path
        return Path(os.path.abspath(absolute))

    @staticmethod
    def _add(findings: list[dict[str, Any]], check: str, message: str, **details: Any) -> None:
        findings.append({"severity": "error", "check": check, "message": message, **details})

    @staticmethod
    def _sha256(path: Path) -> str:
        if path.is_symlink():
            return hashlib.sha256(os.readlink(path).encode("utf-8")).hexdigest()
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _nonempty(value: Any) -> bool:
        return bool(str(value).strip()) if value is not None else False

    def _workspace_relative(self, path: Path) -> str | None:
        try:
            # Manifest identity is the link itself; dependency checks inspect its target.
            return Path(os.path.abspath(path)).relative_to(self._root()).as_posix()
        except ValueError:
            return None

    def _validate_file_entries(
        self, entries: Any, manifest_path: Path, findings: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        if not isinstance(entries, list):
            self._add(findings, "manifest_schema", "files must be a list")
            return {}
        files: dict[str, dict[str, Any]] = {}
        manifest_relative = self._workspace_relative(manifest_path)
        required = (
            "path", "action", "category", "stage", "content_summary", "origin", "reason",
            "diff_summary", "diff_evidence", "existed_before", "sha256_before", "sha256_after",
            "hash_note",
        )
        for index, entry in enumerate(entries):
            label = f"files[{index}]"
            if not isinstance(entry, dict):
                self._add(findings, "manifest_file_schema", f"{label} must be a mapping")
                continue
            missing = [key for key in required if key not in entry]
            if missing:
                self._add(findings, "manifest_file_schema", f"{label} is missing {missing}")
            raw_path = str(entry.get("path", "")).strip()
            resolved = self._resolve(raw_path) if raw_path else None
            relative = self._workspace_relative(resolved) if resolved else None
            if not raw_path or relative is None:
                self._add(findings, "manifest_file_path", f"{label}.path must remain inside the workspace")
                continue
            if relative in files:
                self._add(findings, "manifest_file_duplicate", f"duplicate file entry: {relative}")
            files[relative] = entry

            action = entry.get("action")
            if action not in ACTIONS:
                self._add(findings, "manifest_file_action", f"{label}.action is invalid")
            if entry.get("category") not in CATEGORIES:
                self._add(findings, "manifest_file_category", f"{label}.category is invalid")
            if entry.get("stage") not in STAGES:
                self._add(findings, "manifest_file_stage", f"{label}.stage is invalid")
            for key in ("content_summary", "origin", "reason"):
                if not self._nonempty(entry.get(key)):
                    self._add(findings, "manifest_file_schema", f"{label}.{key} must be non-empty")
            if not isinstance(entry.get("existed_before"), bool):
                self._add(findings, "manifest_file_schema", f"{label}.existed_before must be boolean")
            if entry.get("existed_before") is True and not self._nonempty(entry.get("sha256_before")):
                self._add(findings, "manifest_before_hash", f"{label} requires sha256_before")
            if action in {"modified", "deleted"}:
                if not self._nonempty(entry.get("diff_summary")) or not self._nonempty(entry.get("diff_evidence")):
                    self._add(findings, "manifest_diff_evidence", f"{label} requires diff_summary and diff_evidence")

            exists = bool(resolved and (resolved.is_file() or resolved.is_symlink()))
            if action == "deleted":
                if exists:
                    self._add(findings, "manifest_deleted_exists", f"deleted path still exists: {relative}")
                if entry.get("sha256_after") is not None:
                    self._add(findings, "manifest_deleted_hash", f"{label}.sha256_after must be null")
            elif not exists:
                self._add(findings, "manifest_missing_file", f"manifested file does not exist: {relative}")
            else:
                expected_hash = entry.get("sha256_after")
                if expected_hash is None:
                    if not self._nonempty(entry.get("hash_note")):
                        self._add(findings, "manifest_hash_note", f"{label} needs hash_note when sha256_after is null")
                elif resolved and self._sha256(resolved) != str(expected_hash):
                    self._add(findings, "manifest_hash_mismatch", f"sha256_after mismatch: {relative}")

            if relative == manifest_relative:
                if entry.get("sha256_after") is not None:
                    self._add(findings, "manifest_self_hash", "manifest sha256_after must be null")
                if "self" not in str(entry.get("hash_note", "")).lower():
                    self._add(findings, "manifest_self_hash", "manifest hash_note must explain self-reference")
        if manifest_relative not in files:
            self._add(findings, "manifest_self_entry", "manifest must list itself in files")
        return files

    def _act4_relative(self, raw_path: str) -> str | None:
        path = Path(raw_path).expanduser()
        absolute = path if path.is_absolute() else self._root() / path
        absolute = Path(os.path.abspath(absolute))
        act4_root = Path(os.path.abspath(self._resolve(self.act4_root)))
        try:
            return absolute.relative_to(act4_root).as_posix()
        except ValueError:
            return None

    def _validate_contribution_set(
        self,
        value: Any,
        manifested: dict[str, dict[str, Any]],
        findings: list[dict[str, Any]],
    ) -> int:
        """Keep PR sources inside ACT4 and independent of local run artifacts."""
        if not isinstance(value, list) or not value:
            self._add(
                findings,
                "manifest_contribution_set",
                "contribution_set must be a non-empty list",
            )
            return 0
        contribution_set: set[str] = set()
        forbidden_patterns = [
            ".git/**",
            "**/*.S",
            "**/*.elf",
            "**/*.sig",
            "**/*.results",
            "**/*.sig.elf",
            *self.artifact_act4_patterns,
        ]
        for index, raw in enumerate(value):
            path = str(raw).strip()
            resolved = self._resolve(path) if path else None
            relative = self._workspace_relative(resolved) if resolved else None
            if not path or relative is None:
                self._add(
                    findings,
                    "manifest_contribution_path",
                    f"contribution_set[{index}] must remain inside the workspace",
                )
                continue
            if relative in contribution_set:
                self._add(
                    findings,
                    "manifest_contribution_duplicate",
                    f"duplicate contribution path: {relative}",
                )
            contribution_set.add(relative)
            act4_relative = self._act4_relative(path)
            if act4_relative is None:
                self._add(
                    findings,
                    "manifest_contribution_path",
                    f"contribution source must be inside configured act4_root: {relative}",
                )
            entry = manifested.get(relative)
            if entry is None:
                self._add(
                    findings,
                    "manifest_contribution_missing",
                    f"contribution path is not present in files: {relative}",
                )
            elif entry.get("category") != "contribution_source":
                self._add(
                    findings,
                    "manifest_contribution_category",
                    f"contribution path must use contribution_source: {relative}",
                )
            if act4_relative is not None and self._matches(act4_relative, forbidden_patterns):
                self._add(
                    findings,
                    "manifest_generated_contribution",
                    f"generated/build evidence cannot be a PR contribution source: {relative}",
                )
        categorized = {
            path
            for path, entry in manifested.items()
            if entry.get("category") == "contribution_source"
        }
        if categorized != contribution_set:
            self._add(
                findings,
                "manifest_contribution_consistency",
                "contribution_set must exactly match files categorized as contribution_source",
                missing=sorted(categorized - contribution_set),
                extra=sorted(contribution_set - categorized),
            )
        self._validate_contribution_dependencies(contribution_set, manifested, findings)
        return len(contribution_set)

    def _validate_contribution_dependencies(
        self,
        contributions: set[str],
        manifested: dict[str, dict[str, Any]],
        findings: list[dict[str, Any]],
    ) -> None:
        """Inspect explicit dependency sites, never arbitrary prose or local tools.

        This bounded static check complements generation in a clean ACT4 copy.
        It does not execute contributed code or prove dynamic dependency closure.
        """
        act4 = self._resolve(self.act4_root)
        local_files = {
            self._resolve(path) for path, entry in manifested.items()
            if entry.get("category") != "contribution_source"
        }

        def local_target(path: Path) -> bool:
            absolute = Path(os.path.abspath(path))
            if absolute in local_files:
                return True
            try:
                if absolute.resolve() in local_files:
                    return True
            except OSError:
                return False  # A literal may be ordinary text, not a filesystem path.
            relative = self._act4_relative(str(absolute))
            return relative is not None and self._matches(relative, self.artifact_act4_patterns)

        for relative in sorted(contributions):
            source = self._resolve(relative)
            if self._act4_relative(relative) is None or not (source.exists() or source.is_symlink()):
                continue  # Location/existence errors are reported by the manifest checks.
            try:
                target = source.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                self._add(findings, "manifest_contribution_dependency", str(exc), file=relative)
                continue
            if not target.is_relative_to(act4.resolve()) or local_target(target):
                self._add(
                    findings, "manifest_contribution_dependency",
                    f"contribution source resolves to a local/external artifact: {relative}",
                    file=relative, target=str(target),
                )
                continue
            if source.suffix not in {".py", ".sv", ".svh", ".v", ".vh", ".h", ".c", ".adoc", ".asciidoc"}:
                continue

            def path_is_local(value: str, source_dir: Path = source.parent) -> bool:
                if is_itgen_private_path(value):
                    return True
                if not value or "\n" in value or "\x00" in value:
                    return False
                path = Path(value)
                candidates = [path] if path.is_absolute() else [
                    source_dir / path, act4 / path, self._root() / path,
                ]
                return any(local_target(candidate) for candidate in candidates)

            def module_is_local(name: str, source_dir: Path = source.parent) -> bool:
                level = len(name) - len(name.lstrip("."))
                stem = name.lstrip(".").replace(".", "/")
                if level:
                    base = source_dir
                    for _ in range(level - 1):
                        base = base.parent
                    bases = [base]
                else:
                    bases = [source_dir, act4, act4 / "generators/testgen/src"]
                return any(local_target(base / path) for base in bases for path in (
                    f"{stem}.py", f"{stem}/__init__.py",
                ))

            try:
                text = source.read_text(encoding="utf-8")
                if source.suffix == ".py":
                    dependencies = _generator_workspace_dependencies(
                        ast.parse(text, filename=relative),
                        path_is_local=path_is_local, module_is_local=module_is_local,
                    )
                else:
                    dependencies = [
                        {"line": line, "kind": "include_or_file_access", "references": [reference]}
                        for line, reference in self._source_file_references(source, text)
                        if path_is_local(reference)
                    ]
            except (OSError, UnicodeError, SyntaxError) as exc:
                self._add(findings, "manifest_contribution_parse", str(exc), file=relative)
                continue
            if dependencies:
                self._add(
                    findings, "manifest_contribution_dependency",
                    f"ACT4 contribution depends on local generation/validation inputs: {relative}",
                    file=relative, dependencies=dependencies,
                )

    @staticmethod
    def _source_file_references(source: Path, text: str) -> list[tuple[int, str]]:
        """Extract literal includes/file operations from coverage and CTP sources."""
        if source.suffix in {".sv", ".svh", ".v", ".vh", ".h", ".c"}:
            # Preserve strings and line numbers while removing C/SV comments.
            text = re.sub(
                r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/',
                lambda m: m.group(1) or "\n" * m.group(0).count("\n"),
                text, flags=re.DOTALL,
            )
            pattern = r'^[ \t]*[`#]include\s*["<]([^">]+)[">]|\$(?:readmem[hb]|fopen)\s*\(\s*"([^"]+)"'
        elif source.suffix in {".adoc", ".asciidoc"}:
            text = re.sub(r"(?ms)^////\s*\n.*?^////[^\n]*", lambda m: "\n" * m.group(0).count("\n"), text)
            pattern = r"^[ \t]*(?:include::|image::?)([^\[\n]+)\["
        else:
            # ACT4 norm YAML contains rule/coverpoint identifiers, not file imports.
            return []
        return [
            (text.count("\n", 0, match.start()) + 1, next(g for g in match.groups() if g))
            for match in re.finditer(pattern, text, flags=re.MULTILINE)
        ]

    @staticmethod
    def _matches(path: str, patterns: list[Any]) -> bool:
        for configured_pattern in patterns:
            pattern = str(configured_pattern)
            if fnmatch.fnmatchcase(path, pattern):
                return True
            if pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:]):
                return True
        return False

    def _is_protected_act4_path(self, path: str) -> bool:
        return (
            self._matches(path, self.protected_act4_patterns)
            and not self._matches(path, self.protected_act4_exclude_patterns)
            and not self._matches(path, self.artifact_act4_patterns)
            and not self._is_artifact_tree(path)
        )

    def _is_artifact_tree(self, path: str) -> bool:
        for configured_pattern in self.artifact_act4_patterns:
            pattern = str(configured_pattern)
            if not pattern.endswith("/**"):
                continue
            root_pattern = pattern[:-3]
            if fnmatch.fnmatchcase(path, root_pattern):
                return True
            if root_pattern.startswith("**/") and fnmatch.fnmatchcase(
                path, root_pattern[3:]
            ):
                return True
        return False

    def _validate_events(
        self,
        events: Any,
        _files: dict[str, dict[str, Any]],
        findings: list[dict[str, Any]],
    ) -> int:
        if not isinstance(events, list):
            self._add(findings, "manifest_schema", "change_events must be a list")
            return 0
        required = (
            "path", "event", "stage", "timestamp", "sha256_before", "sha256_after",
            "content_summary", "reason", "evidence",
        )
        event_count = 0
        for index, event in enumerate(events):
            label = f"change_events[{index}]"
            if not isinstance(event, dict):
                self._add(findings, "manifest_event_schema", f"{label} must be a mapping")
                continue
            event_count += 1
            missing = [key for key in required if key not in event]
            if missing:
                self._add(findings, "manifest_event_schema", f"{label} is missing {missing}")
            if event.get("event") not in EVENTS:
                self._add(findings, "manifest_event_type", f"{label}.event is invalid")
            if event.get("stage") not in STAGES:
                self._add(findings, "manifest_event_stage", f"{label}.stage is invalid")
            if event.get("event") == "policy_violation":
                self._add(findings, "manifest_policy_violation", f"recorded policy violation: {event.get('path')}")
            for key in ("path", "content_summary", "reason", "evidence"):
                if not self._nonempty(event.get(key)):
                    self._add(findings, "manifest_event_schema", f"{label}.{key} must be non-empty")

        return event_count

    def _validate_inventory(self, manifested: set[str], findings: list[dict[str, Any]]) -> int:
        actual: set[str] = set()
        for pattern in self.inventory_patterns:
            candidate = str(pattern)
            absolute_pattern = candidate if os.path.isabs(candidate) else str(self._root() / candidate)
            for match in glob.glob(absolute_pattern, recursive=True):
                path = Path(match)
                if not (path.is_file() or path.is_symlink()):
                    continue
                relative = self._workspace_relative(path)
                if (
                    relative is not None
                    and not self._matches(relative, INVENTORY_NOISE_PATTERNS)
                    and not self._is_intermediate_work_file(relative)
                ):
                    actual.add(relative)
        for missing in sorted(actual - manifested):
            self._add(findings, "manifest_inventory_missing", f"actual output is absent from files: {missing}")
        return len(actual)

    @staticmethod
    def _is_intermediate_work_file(relative: str) -> bool:
        """Broad report globs may contain native build trees from local validation."""
        path = Path(relative)
        if not any(part == "work" or part.startswith("work_") for part in path.parts[:-1]):
            return False
        # These are the workflow's actual delivery/evidence types, at any depth.
        evidence = relative.endswith((".S", ".sig", ".results", ".sig.log")) or (
            relative.endswith(".elf") and not relative.endswith(".sig.elf")
        )
        return not evidence

    def _scan_act4_objects(self) -> dict[str, Path]:
        root = self._resolve(self.act4_root)
        if not root.is_dir():
            return {}
        objects: dict[str, Path] = {}
        for directory, dirnames, filenames in os.walk(root, followlinks=False):
            directory_path = Path(directory)
            relative_directory = directory_path.relative_to(root)
            symlink_dirs = [
                name for name in dirnames if (directory_path / name).is_symlink()
            ]
            dirnames[:] = [
                name
                for name in dirnames
                if name not in symlink_dirs
                and not self._is_artifact_tree(
                    (relative_directory / name).as_posix()
                )
            ]
            for name in sorted(symlink_dirs + filenames):
                path = directory_path / name
                objects[path.relative_to(root).as_posix()] = path
        return objects

    def _validate_framework(
        self, baseline: Any, integrity: Any, findings: list[dict[str, Any]]
    ) -> dict[str, int]:
        stats = {
            "protected_changes": 0,
        }
        if not isinstance(baseline, dict):
            self._add(findings, "manifest_baseline_schema", "baseline must be a mapping")
            return stats
        required = (
            "method",
            "git_head",
            "preexisting_changes",
            "baseline_inventory",
            "status_command",
            "status_recorded",
        )
        missing = [key for key in required if key not in baseline]
        if missing:
            self._add(findings, "manifest_baseline_schema", f"baseline is missing {missing}")
        if baseline.get("method") not in {"git", "sha256_snapshot"}:
            self._add(findings, "manifest_baseline_method", "baseline.method is invalid")
        if not isinstance(baseline.get("preexisting_changes"), list):
            self._add(findings, "manifest_baseline_schema", "baseline.preexisting_changes must be a list")
        status_command = baseline.get("status_command")
        status_recorded = baseline.get("status_recorded")
        if not self._nonempty(status_command) or not self._nonempty(baseline.get("baseline_inventory")):
            self._add(findings, "manifest_baseline_schema", "baseline command and inventory must be non-empty")
        if status_recorded is not True:
            self._add(findings, "manifest_baseline_status", "baseline status must be recorded before writes")

        if not isinstance(integrity, dict):
            self._add(findings, "manifest_integrity_schema", "framework_integrity must be a mapping")
            return stats
        required_integrity = (
            "protected_files_modified",
            "protected_files_deleted",
            "protected_type_or_mode_changed",
            "policy_violations",
            "verification_command",
            "passed",
        )
        missing = [key for key in required_integrity if key not in integrity]
        if missing:
            self._add(findings, "manifest_integrity_schema", f"framework_integrity is missing {missing}")
        protected_fields = (
            "protected_files_modified",
            "protected_files_deleted",
            "protected_type_or_mode_changed",
            "policy_violations",
        )
        if any(integrity.get(key) != [] for key in protected_fields) or integrity.get("passed") is not True:
            self._add(findings, "manifest_framework_integrity", "protected framework integrity is not clean and passed")
        if not self._nonempty(integrity.get("verification_command")):
            self._add(findings, "manifest_integrity_schema", "verification_command must be non-empty")

        inventory_path = self._resolve(str(baseline.get("baseline_inventory", "")))
        if not inventory_path.is_file() or yaml is None:
            self._add(findings, "manifest_snapshot_inventory", "baseline inventory is missing")
            return stats
        try:
            inventory = yaml.safe_load(inventory_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            self._add(findings, "manifest_snapshot_inventory", f"cannot read baseline inventory: {exc}")
            return stats
        entries = inventory.get("files") if isinstance(inventory, dict) else inventory
        if not isinstance(entries, list):
            self._add(findings, "manifest_snapshot_inventory", "baseline inventory must be a list or contain files")
            return stats

        baseline_paths: set[str] = set()
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict) or not self._nonempty(entry.get("path")):
                self._add(findings, "manifest_snapshot_inventory", f"snapshot entry {index} is invalid")
                continue
            raw_path = str(entry["path"])
            act4_relative = self._act4_relative(raw_path)
            if act4_relative is None:
                self._add(findings, "manifest_snapshot_inventory", f"snapshot path is outside act4_root: {raw_path}")
                continue
            if act4_relative in baseline_paths:
                self._add(findings, "manifest_snapshot_inventory", f"duplicate snapshot path: {raw_path}")
            baseline_paths.add(act4_relative)
            if (
                entry.get("type") not in ("file", "symlink")
                or not isinstance(entry.get("mode"), str)
                or not re.fullmatch(r"[0-7]{1,4}", entry["mode"])
                or not isinstance(entry.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
            ):
                self._add(
                    findings, "manifest_snapshot_inventory",
                    f"snapshot entry {index} requires type=file|symlink, octal mode and SHA-256: {raw_path}",
                )
                continue
            if self.expected_suite and act4_relative == (
                f"generators/testgen/src/testgen/priv/extensions/{self.expected_suite}.py"
            ):
                self._add(
                    findings, "manifest_suite_generator_exists",
                    f"suite generator already exists in the frozen baseline: {raw_path}; "
                    "select a new suite without overwriting the existing generator",
                )
            if not self._is_protected_act4_path(act4_relative):
                continue
            path = self._resolve(raw_path)
            relative = self._workspace_relative(path) or raw_path
            errors: list[str] = []
            if not (path.is_file() or path.is_symlink()):
                errors.append("deleted")
            else:
                expected_type = entry.get("type")
                actual_type = "symlink" if path.is_symlink() else "file"
                if expected_type and expected_type != actual_type:
                    errors.append("type")
                expected_mode = entry.get("mode")
                if expected_mode is not None:
                    try:
                        parsed_mode = int(str(expected_mode), 8)
                    except ValueError:
                        self._add(findings, "manifest_snapshot_inventory", f"invalid mode for {relative}")
                    else:
                        if stat.S_IMODE(path.lstat().st_mode) != parsed_mode:
                            errors.append("mode")
                if str(entry.get("sha256", "")) != self._sha256(path):
                    errors.append("content")
            if not errors:
                continue
            stats["protected_changes"] += 1
            self._add(
                findings,
                "manifest_protected_framework_change",
                f"protected ACT4 object changed: {relative}",
                changed_fields=errors,
            )

        current = self._scan_act4_objects()
        for act4_relative in sorted(set(current) - baseline_paths):
            if self._is_protected_act4_path(act4_relative):
                stats["protected_changes"] += 1
                self._add(
                    findings,
                    "manifest_protected_framework_addition",
                    f"new object shadows a protected ACT4 path: {act4_relative}",
                )

        if baseline.get("method") == "git":
            act4_root = self._resolve(self.act4_root)
            try:
                head = subprocess.run(
                    ["git", "-C", str(act4_root), "rev-parse", "HEAD"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                ).stdout.strip()
            except (OSError, subprocess.SubprocessError) as exc:
                self._add(findings, "manifest_git_check", f"unable to verify ACT4 Git HEAD: {exc}")
            else:
                if head != str(baseline.get("git_head", "")):
                    self._add(findings, "manifest_git_head", "current ACT4 HEAD differs from frozen baseline")
        return stats

    def do_check(self, timeout=0, is_complete=False, **kwargs: Any) -> tuple[bool, object]:
        """Validate outputs and prove that protected ACT4 code is unchanged."""
        findings: list[dict[str, Any]] = []
        manifest_path = self._resolve(self.manifest_file)
        manifest: Any = None
        if yaml is None:
            self._add(findings, "manifest_parser", "PyYAML is required")
        elif not manifest_path.is_file():
            self._add(findings, "manifest_exists", f"missing manifest: {manifest_path}")
        else:
            try:
                manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as exc:
                self._add(findings, "manifest_parse", str(exc))

        manifested: dict[str, dict[str, Any]] = {}
        inventory_count = 0
        event_count = 0
        contribution_count = 0
        framework_stats = {
            "protected_changes": 0,
        }
        if isinstance(manifest, dict):
            version = manifest.get("schema_version")
            required = (
                "schema_version",
                "suite",
                "workspace_root",
                "baseline",
                "framework_integrity",
            )
            if not self.integrity_only:
                required += ("files", "change_events")
            missing = [key for key in required if key not in manifest]
            if missing:
                self._add(findings, "manifest_schema", f"manifest is missing {missing}")
            if version != 2:
                self._add(findings, "manifest_version", "schema_version must be 2")
            if self.expected_suite and manifest.get("suite") != self.expected_suite:
                self._add(findings, "manifest_suite", "manifest suite does not match configured suite")
            if not self._nonempty(manifest.get("workspace_root")):
                self._add(findings, "manifest_schema", "workspace_root must be non-empty")
            if not self.integrity_only:
                manifested = self._validate_file_entries(
                    manifest.get("files"), manifest_path, findings
                )
                if self.require_contribution_set:
                    contribution_count = self._validate_contribution_set(
                        manifest.get("contribution_set"),
                        manifested,
                        findings,
                    )
                event_count = self._validate_events(
                    manifest.get("change_events"), manifested, findings
                )
                inventory_count = self._validate_inventory(set(manifested), findings)
            framework_stats = self._validate_framework(
                manifest.get("baseline"),
                manifest.get("framework_integrity"),
                findings,
            )
        elif manifest is not None:
            self._add(findings, "manifest_schema", "manifest must be a YAML mapping")

        error_count = sum(item.get("severity") == "error" for item in findings)
        warning_count = sum(item.get("severity") == "warning" for item in findings)
        report = {
            "status": (
                "failed"
                if error_count
                else "review_required"
                if warning_count
                else "complete"
            ),
            "summary": {"errors": error_count, "warnings": warning_count},
            "checks": {
                "manifested_files": len(manifested),
                "inventory_files": inventory_count,
                "change_events": event_count,
                "contribution_sources": contribution_count,
                **framework_stats,
            },
            "findings": findings,
        }
        return error_count == 0, report


__all__ = ["ACT4FileManifestChecker"]
