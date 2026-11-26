"""Validate the human-facing final report for an ACT4 contribution workflow."""

from __future__ import annotations

import glob
import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import unquote

try:
    import yaml
except ImportError:  # pragma: no cover - reported by the checker.
    yaml = None  # type: ignore[assignment]

from ucagent.checkers.base import Checker
from ..xiangshan_bundle import safe_path


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
        contribution_manifest: str | None = None,
        patch_file: str | None = None,
        act4_root: str | None = None,
        need_human_check: bool = False,
        cfg: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.cfg = cfg
        if any((contribution_manifest, patch_file, act4_root)) and not all((contribution_manifest, patch_file, act4_root)):
            raise ValueError("Patch publication requires contribution_manifest, patch_file and act4_root")
        self.contribution_manifest, self.patch_file, self.act4_root = contribution_manifest, patch_file, act4_root
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
            actual = declared.get(key)
            if value is not None and (type(actual) is not type(value) or actual != value):
                self._add(
                    findings,
                    "error",
                    "final_report_state_summary",
                    f"final validation state {key} does not match validation state",
                    expected=value,
                    actual=actual,
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
        from ..run_config import run_settings

        if not any(item["severity"] == "error" for item in findings) and self.patch_file and not run_settings(getattr(self, "cfg", None)):
            try:
                workspace = Path(self.workspace).resolve()
                checkout = safe_path(workspace, self.act4_root)
                manifest_path = safe_path(workspace, self.contribution_manifest)
                patch_path = safe_path(workspace, self.patch_file)
                if patch_path.is_relative_to(checkout) or patch_path in {manifest_path, report_path}:
                    raise ValueError("Publish the patch separately from source files, the manifest and the final report")
                manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
                baseline = manifest["baseline"]["git_head"]
                if baseline is not None and (not isinstance(baseline, str) or not re.fullmatch(r"[0-9a-f]{40,64}", baseline)):
                    raise ValueError("Use the exact Git baseline commit or null for a non-Git new-source contribution")
                records = {item["path"]: item for item in manifest["files"]}
                pieces = []
                for name in manifest["contribution_set"]:
                    source = safe_path(workspace, name)
                    relative = source.relative_to(checkout).as_posix()
                    record = records[name]
                    if record["category"] != "contribution_source":
                        raise ValueError(f"Not a contribution source: {name}")
                    original = (subprocess.run(["git", "-C", str(checkout), "show", f"{baseline}:{relative}"], capture_output=True, timeout=30)
                                if baseline else None)
                    if record["existed_before"]:
                        if original is None or original.returncode or hashlib.sha256(original.stdout).hexdigest() != record["sha256_before"]:
                            raise ValueError(f"Git baseline differs from preexisting user content: {name}; retain the candidate and supply its exact original source")
                        command = ["git", "diff", "--binary", baseline, "--", relative]
                    else:
                        if original is not None and original.returncode == 0:
                            raise ValueError(f"Manifest calls a baseline file new: {name}")
                        command = ["git", "diff", "--no-index", "--binary", "--", "/dev/null", relative]
                    if source.exists() and hashlib.sha256(source.read_bytes()).hexdigest() != record["sha256_after"]:
                        raise ValueError(f"Contribution changed since its manifest snapshot: {name}")
                    diff = subprocess.run(command, cwd=checkout, capture_output=True, timeout=60)
                    if diff.returncode not in {0, 1}:
                        raise ValueError(f"Cannot produce the declared contribution patch: {name}")
                    pieces.append(diff.stdout)
                patch_path.write_bytes(b"".join(pieces))
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
                self._add(findings, "error", "contribution_patch", str(error))
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
