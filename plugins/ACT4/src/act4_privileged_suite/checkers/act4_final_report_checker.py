"""Validate the human-facing final report for an ACT4 contribution workflow."""

from __future__ import annotations

import glob
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

try:
    import yaml
except ImportError:  # pragma: no cover - reported by the checker.
    yaml = None  # type: ignore[assignment]

from ucagent.checkers.base import Checker


_MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


class ACT4FinalReportChecker(Checker):
    """Check that the final report is a complete, navigable review entry point."""

    def __init__(
        self,
        report_file: str,
        required_reports: Any = None,
        required_sections: Any = None,
        required_phrases: Any = None,
        validation_state: str | None = None,
        need_human_check: bool = False,
        cfg: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        if kwargs:
            raise TypeError(
                f"unsupported ACT4FinalReportChecker arguments: {sorted(kwargs)}"
            )
        self.report_file = report_file
        self.required_reports = self._strings(required_reports)
        self.required_sections = self._strings(required_sections)
        self.required_phrases = self._strings(required_phrases)
        self.validation_state = validation_state
        self._last_report: dict[str, Any] = {}
        if hasattr(self, "set_human_check_needed"):
            self.set_human_check_needed(need_human_check)

    @staticmethod
    def _strings(value: Any) -> list[str]:
        if value is None:
            return []
        values = value if isinstance(value, (list, tuple, set)) else [value]
        return [str(item).strip() for item in values if str(item).strip()]

    def _root(self) -> Path:
        return Path(getattr(self, "workspace", None) or os.getcwd()).resolve()

    def _resolve(self, value: str) -> Path:
        path = Path(value).expanduser()
        return path.resolve() if path.is_absolute() else (self._root() / path).resolve()

    @staticmethod
    def _add(
        findings: list[dict[str, Any]],
        severity: str,
        check: str,
        message: str,
        **details: Any,
    ) -> None:
        findings.append(
            {"severity": severity, "check": check, "message": message, **details}
        )

    @staticmethod
    def _link_targets(text: str, report_path: Path) -> set[Path]:
        targets: set[Path] = set()
        for raw_target in _MARKDOWN_LINK.findall(text):
            target = unquote(raw_target.strip().split("#", 1)[0].strip("<>"))
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            path = Path(target).expanduser()
            if not path.is_absolute():
                path = report_path.parent / path
            targets.add(path.resolve())
        return targets

    def _required_files(
        self, findings: list[dict[str, Any]]
    ) -> tuple[list[Path], dict[str, int]]:
        files: list[Path] = []
        counts: dict[str, int] = {}
        for pattern in self.required_reports:
            candidate = Path(pattern).expanduser()
            absolute_pattern = str(
                candidate if candidate.is_absolute() else self._root() / candidate
            )
            matches = sorted(
                Path(item).resolve()
                for item in glob.glob(absolute_pattern, recursive=True)
                if Path(item).is_file()
            )
            counts[pattern] = len(matches)
            if not matches:
                self._add(
                    findings,
                    "error",
                    "final_report_required_input",
                    f"required report pattern matched no files: {pattern}",
                )
            files.extend(matches)
        return list(dict.fromkeys(files)), counts

    def _validate_state(
        self,
        text: str,
        findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        state_checks: dict[str, Any] = {}
        if not self.validation_state:
            return state_checks
        state_path = self._resolve(self.validation_state)
        if not state_path.is_file():
            self._add(
                findings,
                "error",
                "final_report_validation_state",
                f"validation state is missing: {state_path}",
            )
            return state_checks
        if yaml is None:
            self._add(
                findings,
                "error",
                "final_report_validation_state",
                "PyYAML is required to validate the final report state",
            )
            return state_checks
        try:
            state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            self._add(
                findings,
                "error",
                "final_report_validation_state",
                str(exc),
            )
            return state_checks
        if not isinstance(state, dict):
            self._add(
                findings,
                "error",
                "final_report_validation_state",
                "validation state must be a YAML mapping",
            )
            return state_checks

        contribution_ready = state.get("contribution_ready")
        generation_scope = state.get("generation_scope")
        if not isinstance(contribution_ready, bool):
            self._add(
                findings,
                "error",
                "final_report_validation_state",
                "validation state contribution_ready must be boolean",
            )
        if not isinstance(generation_scope, dict) or generation_scope.get(
            "status"
        ) not in {"complete", "partial"}:
            self._add(
                findings,
                "error",
                "final_report_validation_state",
                "validation state generation_scope.status must be complete or partial",
            )
        scope_status = (
            generation_scope.get("status")
            if isinstance(generation_scope, dict)
            else None
        )
        state_checks = {
            "contribution_ready": contribution_ready,
            "generation_scope": scope_status,
        }
        heading = re.search(
            r"(?ms)^#{1,6}\s+Final validation state\s*$\n"
            r"(.*?)(?=^#{1,6}\s+|\Z)",
            text,
        )
        block = (
            re.search(r"(?ms)```ya?ml\s*\n(.*?)```", heading.group(1))
            if heading
            else None
        )
        if not block:
            self._add(
                findings,
                "error",
                "final_report_state_summary",
                "Final validation state must contain a fenced YAML state block",
            )
            return state_checks
        try:
            declared = yaml.safe_load(block.group(1))
        except yaml.YAMLError as exc:
            self._add(
                findings,
                "error",
                "final_report_state_summary",
                f"cannot parse final validation state block: {exc}",
            )
            return state_checks
        if not isinstance(declared, dict):
            self._add(
                findings,
                "error",
                "final_report_state_summary",
                "final validation state block must be a YAML mapping",
            )
            return state_checks
        expected = {
            "source_contribution_ready": contribution_ready,
            "generation_scope_status": scope_status,
        }
        for key, value in expected.items():
            if value is not None and declared.get(key) != value:
                self._add(
                    findings,
                    "error",
                    "final_report_state_summary",
                    f"final validation state {key} does not match validation state",
                    expected=value,
                    actual=declared.get(key),
                )
        return state_checks

    def do_check(
        self, timeout=0, is_complete=False, **kwargs: Any
    ) -> tuple[bool, object]:
        """Validate the final report index, explanations, and final-state summary."""
        findings: list[dict[str, Any]] = []
        report_path = self._resolve(self.report_file)
        if not report_path.is_file():
            self._add(
                findings,
                "error",
                "final_report_exists",
                f"final report is missing: {report_path}",
            )
            text = ""
        else:
            try:
                text = report_path.read_text(encoding="utf-8")
            except OSError as exc:
                self._add(findings, "error", "final_report_read", str(exc))
                text = ""
        if report_path.is_file() and not text.strip():
            self._add(
                findings,
                "error",
                "final_report_nonempty",
                "final report must not be empty",
            )

        required_files, pattern_counts = self._required_files(findings)
        linked_files = self._link_targets(text, report_path)
        for required_file in required_files:
            if required_file == report_path:
                continue
            if required_file not in linked_files:
                self._add(
                    findings,
                    "error",
                    "final_report_index",
                    f"required report is not linked: {required_file}",
                )

        headings = {
            match.group(1).strip().lower()
            for match in re.finditer(r"^#{1,6}\s+(.+?)\s*$", text, re.MULTILINE)
        }
        for section in self.required_sections:
            if not any(section.lower() in heading for heading in headings):
                self._add(
                    findings,
                    "error",
                    "final_report_section",
                    f"required section is missing: {section}",
                )
        lowered = text.lower()
        for phrase in self.required_phrases:
            if phrase.lower() not in lowered:
                self._add(
                    findings,
                    "error",
                    "final_report_explanation",
                    f"required explanation is missing: {phrase}",
                )

        state_checks = self._validate_state(text, findings)
        errors = sum(item["severity"] == "error" for item in findings)
        warnings = sum(item["severity"] == "warning" for item in findings)
        report = {
            "status": "failed" if errors else "complete",
            "summary": {"errors": errors, "warnings": warnings},
            "checks": {
                "report_file": str(report_path),
                "required_report_patterns": pattern_counts,
                "required_files": len(required_files),
                "linked_local_files": len(linked_files),
                "required_sections": self.required_sections,
                "validation_state": state_checks,
            },
            "findings": findings,
        }
        self._last_report = report
        return errors == 0, report


__all__ = ["ACT4FinalReportChecker"]
