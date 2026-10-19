"""Validate CSV-driven RISC-V ISA manual reference discovery for ACT4 suites."""

from __future__ import annotations

import hashlib
import os
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


from ucagent.checkers.base import Checker


def _finding(
    findings: list[dict[str, Any]],
    check: str,
    message: str,
    *,
    file: Path | None = None,
    severity: str = "error",
) -> None:
    item: dict[str, Any] = {
        "severity": severity,
        "check": check,
        "message": message,
    }
    if file is not None:
        item["file"] = str(file)
    findings.append(item)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read YAML {path}: {exc}") from exc


def _rule_names_and_tags(
    data: Any,
    findings: list[dict[str, Any]],
    path: Path,
) -> tuple[set[str], set[str]]:
    if not isinstance(data, dict) or not isinstance(
        data.get("normative_rule_definitions"), list
    ):
        _finding(
            findings,
            "manual_metadata_schema",
            "metadata must contain a normative_rule_definitions list",
            file=path,
        )
        return set(), set()

    names: list[str] = []
    tags: set[str] = set()
    for index, entry in enumerate(data["normative_rule_definitions"]):
        if not isinstance(entry, dict):
            _finding(
                findings,
                "manual_metadata_schema",
                f"normative_rule_definitions[{index}] is not an object",
                file=path,
            )
            continue
        raw_names = entry.get("names", entry.get("name", []))
        if isinstance(raw_names, str):
            entry_names = [raw_names.strip()] if raw_names.strip() else []
        elif isinstance(raw_names, list):
            entry_names = [str(name).strip() for name in raw_names if str(name).strip()]
        else:
            entry_names = []
        if not entry_names:
            _finding(
                findings,
                "manual_metadata_schema",
                f"normative_rule_definitions[{index}] has no name or names",
                file=path,
            )
        names.extend(entry_names)

        raw_tags = entry.get("tags", entry.get("tag", []))
        if isinstance(raw_tags, str):
            entry_tags = [raw_tags.strip()] if raw_tags.strip() else []
        elif isinstance(raw_tags, list):
            entry_tags = [str(tag).strip() for tag in raw_tags if str(tag).strip()]
        else:
            entry_tags = []
        if not entry_tags:
            _finding(
                findings,
                "manual_metadata_tags",
                f"normative rule entry {index} has no source tag",
                file=path,
            )
        tags.update(entry_tags)

    for name, count in Counter(names).items():
        if count > 1:
            _finding(
                findings,
                "manual_metadata_duplicate_rule",
                f"metadata defines rule {name!r} {count} times",
                file=path,
            )
    return set(names), tags


class ACT4ManualReferenceChecker(Checker):
    """Check selected manual sources, exact copies, and discovery provenance."""

    def __init__(
        self,
        suite: str,
        testplan: str,
        manual_root: str,
        spec_copy: str,
        metadata_copy: str,
        provenance_file: str,
        require_git_head: bool = True,
        need_human_check: bool = False,
        cfg: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        if kwargs:
            raise TypeError(
                f"unsupported ACT4ManualReferenceChecker arguments: {sorted(kwargs)}"
            )
        self.suite = suite
        self.testplan = testplan
        self.manual_root = manual_root
        self.spec_copy = spec_copy
        self.metadata_copy = metadata_copy
        self.provenance_file = provenance_file
        self.require_git_head = bool(require_git_head)
        if hasattr(self, "set_human_check_needed"):
            self.set_human_check_needed(need_human_check)

    def _workspace(self) -> Path:
        return Path(getattr(self, "workspace", None) or os.getcwd()).resolve()

    def _resolve(self, value: str) -> Path:
        path = Path(value).expanduser()
        return (
            path.resolve()
            if path.is_absolute()
            else (self._workspace() / path).resolve()
        )

    def _source_path(
        self,
        manual_root: Path,
        section: Any,
        key: str,
        findings: list[dict[str, Any]],
    ) -> Path | None:
        if (
            not isinstance(section, dict)
            or not str(section.get("source_path", "")).strip()
        ):
            _finding(
                findings, "manual_provenance_schema", f"{key}.source_path is required"
            )
            return None
        source = (manual_root / str(section["source_path"])).resolve()
        try:
            source.relative_to(manual_root)
        except ValueError:
            _finding(
                findings,
                "manual_source_scope",
                f"{key}.source_path escapes manual_root",
            )
            return None
        if not source.is_file():
            _finding(
                findings,
                "manual_source_exists",
                f"selected {key} source is missing",
                file=source,
            )
            return None
        return source

    def _check_copy(
        self,
        source: Path | None,
        copy: Path,
        section: Any,
        key: str,
        findings: list[dict[str, Any]],
    ) -> None:
        if not copy.is_file():
            _finding(
                findings, "manual_copy_exists", f"{key} copy is missing", file=copy
            )
            return
        if source is None:
            return
        if source.read_bytes() != copy.read_bytes():
            _finding(
                findings,
                "manual_copy_exact",
                f"{key} copy is not byte-for-byte identical to selected source",
                file=copy,
            )
        actual_hash = _sha256(source)
        declared_hash = section.get("sha256") if isinstance(section, dict) else None
        if declared_hash != actual_hash:
            _finding(
                findings,
                "manual_source_hash",
                f"{key}.sha256 does not match selected source",
                file=source,
            )
        copied_path = section.get("copied_path") if isinstance(section, dict) else None
        if copied_path:
            declared_copy = self._resolve(str(copied_path))
            if declared_copy != copy:
                _finding(
                    findings,
                    "manual_copy_path",
                    f"{key}.copied_path does not match configured copy path",
                    file=copy,
                )

    def _check_candidates(
        self,
        discovery: Any,
        selected: dict[str, Any],
        kind: str,
        findings: list[dict[str, Any]],
    ) -> None:
        key = f"{kind}_candidates"
        candidates = discovery.get(key) if isinstance(discovery, dict) else None
        if not isinstance(candidates, list) or not candidates:
            _finding(
                findings,
                "manual_discovery_candidates",
                f"discovery.{key} must be a non-empty list",
            )
            return
        normalized: list[tuple[str, list[str]]] = []
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                _finding(
                    findings,
                    "manual_discovery_candidates",
                    f"{key}[{index}] is not an object",
                )
                continue
            path = str(candidate.get("path", "")).strip()
            if not path:
                _finding(
                    findings,
                    "manual_discovery_candidates",
                    f"{key}[{index}] has no path",
                )
                continue
            matched_terms = candidate.get("matched_terms")
            if not isinstance(matched_terms, list):
                _finding(
                    findings,
                    "manual_discovery_evidence",
                    f"{key}[{index}] must record matched_terms",
                )
                matched_terms = []
            normalized.append(
                (
                    path,
                    [
                        str(term).strip()
                        for term in matched_terms
                        if str(term).strip()
                    ],
                )
            )
        if not normalized:
            return
        selected_path = str(selected.get("source_path", ""))
        selected_matches = [
            terms for path, terms in normalized if path == selected_path
        ]
        if not selected_matches:
            _finding(
                findings,
                "manual_discovery_selection",
                f"selected {kind} source is absent from candidates",
            )
            return
        if not selected_matches[0]:
            _finding(
                findings,
                "manual_discovery_evidence",
                f"selected {kind} source has no matched terms",
            )

    def do_check(
        self, timeout=0, is_complete=False, **kwargs: Any
    ) -> tuple[bool, object]:
        """Validate manual discovery, copied sources, and provenance evidence."""
        findings: list[dict[str, Any]] = []
        testplan = self._resolve(self.testplan)
        manual_root = self._resolve(self.manual_root)
        spec_copy = self._resolve(self.spec_copy)
        metadata_copy = self._resolve(self.metadata_copy)
        provenance_path = self._resolve(self.provenance_file)

        for path, label in (
            (testplan, "testplan"),
            (manual_root, "manual_root"),
            (provenance_path, "provenance"),
        ):
            if not path.exists():
                _finding(
                    findings,
                    "manual_input_exists",
                    f"{label} does not exist",
                    file=path,
                )
        if findings:
            return False, {
                "summary": {"errors": len(findings), "warnings": 0},
                "findings": findings,
            }

        try:
            provenance = _load_yaml(provenance_path)
        except ValueError as exc:
            _finding(
                findings, "manual_provenance_parse", str(exc), file=provenance_path
            )
            provenance = {}
        if not isinstance(provenance, dict):
            _finding(
                findings,
                "manual_provenance_schema",
                "provenance must be a YAML object",
                file=provenance_path,
            )
            provenance = {}
        if provenance.get("schema_version") != 1:
            _finding(
                findings,
                "manual_provenance_schema",
                "schema_version must be 1",
                file=provenance_path,
            )
        if provenance.get("suite") != self.suite:
            _finding(
                findings,
                "manual_provenance_suite",
                f"suite must be {self.suite!r}",
                file=provenance_path,
            )

        spec_section = provenance.get("specification", {})
        metadata_section = provenance.get("metadata", {})
        spec_source = self._source_path(
            manual_root, spec_section, "specification", findings
        )
        metadata_source = self._source_path(
            manual_root, metadata_section, "metadata", findings
        )
        self._check_copy(
            spec_source, spec_copy, spec_section, "specification", findings
        )
        self._check_copy(
            metadata_source, metadata_copy, metadata_section, "metadata", findings
        )

        testplan_section = provenance.get("testplan", {})
        if not isinstance(testplan_section, dict) or testplan_section.get(
            "sha256"
        ) != _sha256(testplan):
            _finding(
                findings,
                "manual_testplan_hash",
                "testplan.sha256 does not match the input CSV",
                file=testplan,
            )

        discovery = provenance.get("discovery", {})
        terms = discovery.get("csv_terms") if isinstance(discovery, dict) else None
        if not isinstance(terms, list) or not [
            term for term in terms if str(term).strip()
        ]:
            _finding(
                findings,
                "manual_discovery_terms",
                "discovery.csv_terms must record non-empty terms extracted from the CSV",
            )
        else:
            csv_text = testplan.read_text(encoding="utf-8", errors="replace").casefold()
            missing_terms = [
                str(term) for term in terms if str(term).casefold() not in csv_text
            ]
            if missing_terms:
                _finding(
                    findings,
                    "manual_discovery_terms",
                    f"csv_terms are absent from the input CSV: {missing_terms}",
                )
        if (
            not isinstance(discovery, dict)
            or not str(discovery.get("selection_reason", "")).strip()
        ):
            _finding(
                findings,
                "manual_discovery_reason",
                "discovery.selection_reason is required",
            )
        self._check_candidates(discovery, spec_section, "spec", findings)
        self._check_candidates(discovery, metadata_section, "metadata", findings)

        if metadata_copy.is_file():
            try:
                metadata_data = _load_yaml(metadata_copy)
            except ValueError as exc:
                _finding(
                    findings, "manual_metadata_parse", str(exc), file=metadata_copy
                )
                metadata_data = {}
            rule_names, tags = _rule_names_and_tags(
                metadata_data, findings, metadata_copy
            )
        else:
            rule_names, tags = set(), set()
        if spec_copy.is_file() and tags:
            spec_text = spec_copy.read_text(encoding="utf-8", errors="replace")
            missing_tags = sorted(tag for tag in tags if tag not in spec_text)
            matched_count = len(tags) - len(missing_tags)
            if matched_count == 0:
                _finding(
                    findings,
                    "manual_reference_pair",
                    "none of the metadata tags occur in the selected specification",
                    file=spec_copy,
                )
            if missing_tags:
                recorded_tags = discovery.get("unmatched_metadata_tags", [])
                reason = discovery.get("unmatched_metadata_tag_reason", "")
                if (
                    sorted(str(tag) for tag in recorded_tags) != missing_tags
                    or not str(reason).strip()
                ):
                    _finding(
                        findings,
                        "manual_reference_pair_disclosure",
                        "metadata tags absent from the selected specification must "
                        "be recorded exactly with a non-empty reason",
                        file=provenance_path,
                    )
                elif matched_count:
                    _finding(
                        findings,
                        "manual_reference_pair_partial",
                        f"{len(missing_tags)} metadata tags are outside the selected "
                        "specification and are explicitly disclosed",
                        file=spec_copy,
                        severity="warning",
                    )

        declared_head = str(provenance.get("manual_git_head", "")).strip()
        if self.require_git_head and not declared_head:
            _finding(
                findings,
                "manual_git_head",
                "manual_git_head is required",
                file=provenance_path,
            )
        if declared_head:
            try:
                actual_head = subprocess.run(
                    ["git", "-C", str(manual_root), "rev-parse", "HEAD"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                ).stdout.strip()
            except (OSError, subprocess.SubprocessError) as exc:
                if self.require_git_head:
                    _finding(
                        findings,
                        "manual_git_head",
                        f"cannot resolve manual Git HEAD: {exc}",
                        file=manual_root,
                    )
            else:
                if actual_head != declared_head:
                    _finding(
                        findings,
                        "manual_git_head",
                        f"manual_git_head {declared_head!r} does not match current HEAD {actual_head!r}",
                        file=provenance_path,
                    )

        error_count = sum(item["severity"] == "error" for item in findings)
        warning_count = sum(item["severity"] == "warning" for item in findings)
        summary = {"errors": error_count, "warnings": warning_count}
        report = {
            "summary": summary,
            "findings": findings,
            "checks": {
                "rules": len(rule_names),
                "tags": len(tags),
                "specification": str(spec_source) if spec_source else None,
                "metadata": str(metadata_source) if metadata_source else None,
            },
        }
        if error_count:
            return False, report
        return True, {"message": "ACT4 manual reference check passed", **report}


__all__ = ["ACT4ManualReferenceChecker"]
