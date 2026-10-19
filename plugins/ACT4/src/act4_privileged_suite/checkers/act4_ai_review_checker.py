"""Validate the cumulative AI review report used by the ACT4 workflow."""

from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - reported by the checker.
    yaml = None  # type: ignore[assignment]

from ucagent.checkers.base import Checker


REVIEW_STATUSES = {"approved", "approved_with_limitations", "blocked"}
CHECK_STATUSES = {"passed", "warning", "blocked", "not_run"}
CONFIDENCE_LEVELS = {"confirmed", "inferred", "unverified"}


class ACT4AIReviewChecker(Checker):
    """Validate one stage section and the existence of its predecessors."""

    def __init__(
        self,
        review_file: str,
        expected_stage: str,
        required_prior_stages: Any = None,
        required_check_names: Any = None,
        required_artifacts: Any = None,
        need_human_check: bool = False,
        cfg: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        if kwargs:
            raise TypeError(
                f"unsupported ACT4AIReviewChecker arguments: {sorted(kwargs)}"
            )
        self.review_file = review_file
        self.expected_stage = expected_stage
        self.required_prior_stages = self._strings(required_prior_stages)
        self.required_check_names = set(self._strings(required_check_names))
        self.required_artifacts = self._strings(required_artifacts)
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

    def _load(self, path: Path, findings: list[dict[str, Any]]) -> Any:
        if not path.is_file():
            self._add(
                findings,
                "error",
                "ai_review_exists",
                f"AI review report is missing: {path}",
            )
            return None
        if yaml is None:
            self._add(
                findings,
                "error",
                "ai_review_parser",
                "PyYAML is required to validate the AI review report",
            )
            return None
        try:
            return yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            self._add(
                findings, "error", "ai_review_parse", str(exc), file=str(path)
            )
            return None

    def _validate_check(
        self,
        item: Any,
        index: int,
        stage: str,
        findings: list[dict[str, Any]],
    ) -> tuple[str, str, str, bool]:
        label = f"stages.{stage}.checks[{index}]"
        if not isinstance(item, dict):
            self._add(
                findings,
                "error",
                "ai_review_check_schema",
                f"{label} must be a mapping",
            )
            return "", "", "", False

        required = (
            "name",
            "status",
            "confidence",
            "evidence",
            "conclusion",
            "workflow_blocking",
        )
        missing = [key for key in required if key not in item]
        if missing:
            self._add(
                findings,
                "error",
                "ai_review_check_schema",
                f"{label} is missing required keys: {missing}",
            )

        name = str(item.get("name", "")).strip()
        status = str(item.get("status", "")).strip().lower()
        confidence = str(item.get("confidence", "")).strip().lower()
        if not name:
            self._add(
                findings,
                "error",
                "ai_review_check_schema",
                f"{label}.name must be non-empty",
            )
        if status not in CHECK_STATUSES:
            self._add(
                findings,
                "error",
                "ai_review_check_status",
                f"{label}.status must be one of {sorted(CHECK_STATUSES)}",
            )
        if confidence not in CONFIDENCE_LEVELS:
            self._add(
                findings,
                "error",
                "ai_review_confidence",
                f"{label}.confidence must be one of {sorted(CONFIDENCE_LEVELS)}",
            )
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not any(
            str(value).strip() for value in evidence
        ):
            self._add(
                findings,
                "error",
                "ai_review_evidence",
                f"{label}.evidence must list files, commands, or checker results",
            )
        if not str(item.get("conclusion", "")).strip():
            self._add(
                findings,
                "error",
                "ai_review_check_schema",
                f"{label}.conclusion must be non-empty",
            )
        limited = status != "passed" or confidence != "confirmed"
        if limited and not str(item.get("limitation", "")).strip():
            self._add(
                findings,
                "error",
                "ai_review_check_limitation",
                f"{label} must explain its non-passed or non-confirmed result",
            )
        workflow_blocking = item.get("workflow_blocking")
        if not isinstance(workflow_blocking, bool):
            self._add(
                findings,
                "error",
                "ai_review_check_schema",
                f"{label}.workflow_blocking must be true or false",
            )
        return name, status, confidence, workflow_blocking is True

    def _validate_stage(
        self,
        stage: str,
        section: Any,
        findings: list[dict[str, Any]],
        required_checks: set[str],
        emit_warning: bool,
    ) -> str | None:
        if not isinstance(section, dict):
            self._add(
                findings,
                "error",
                "ai_review_stage_schema",
                f"stages.{stage} must be a mapping",
            )
            return None

        required = (
            "review_status",
            "summary",
            "checks",
            "limitations",
            "blocking_issues",
            "artifacts",
            "commands",
        )
        missing = [key for key in required if key not in section]
        if missing:
            self._add(
                findings,
                "error",
                "ai_review_stage_schema",
                f"stages.{stage} is missing required keys: {missing}",
            )

        status = str(section.get("review_status", "")).strip().lower()
        if status not in REVIEW_STATUSES:
            self._add(
                findings,
                "error",
                "ai_review_status",
                f"stages.{stage}.review_status must be one of "
                f"{sorted(REVIEW_STATUSES)}",
            )
        if not str(section.get("summary", "")).strip():
            self._add(
                findings,
                "error",
                "ai_review_summary",
                f"stages.{stage}.summary must be non-empty",
            )
        for key in (
            "checks",
            "limitations",
            "blocking_issues",
            "artifacts",
            "commands",
        ):
            if not isinstance(section.get(key), list):
                self._add(
                    findings,
                    "error",
                    "ai_review_stage_schema",
                    f"stages.{stage}.{key} must be a list (use [] when empty)",
                )

        checks = section.get("checks")
        checks = checks if isinstance(checks, list) else []
        if not checks:
            self._add(
                findings,
                "error",
                "ai_review_checks",
                f"stages.{stage}.checks must not be empty",
            )
        names: set[str] = set()
        limited = False
        blocking_check = False
        for index, item in enumerate(checks):
            name, check_status, confidence, workflow_blocking = (
                self._validate_check(item, index, stage, findings)
            )
            if name in names:
                self._add(
                    findings,
                    "error",
                    "ai_review_duplicate_check",
                    f"stages.{stage}.checks contains duplicate name {name!r}",
                )
            names.add(name)
            limited = (
                limited
                or check_status != "passed"
                or confidence != "confirmed"
            )
            blocking_check = (
                blocking_check
                or workflow_blocking
                or check_status == "blocked"
            )

        missing_checks = sorted(required_checks - names)
        if missing_checks:
            self._add(
                findings,
                "error",
                "ai_review_required_checks",
                f"stages.{stage} is missing required checks: {missing_checks}",
            )

        limitations = section.get("limitations")
        limitations = limitations if isinstance(limitations, list) else []
        blocking_issues = section.get("blocking_issues")
        blocking_issues = (
            blocking_issues if isinstance(blocking_issues, list) else []
        )
        artifacts = section.get("artifacts")
        artifacts = artifacts if isinstance(artifacts, list) else []
        if not any(str(value).strip() for value in artifacts):
            self._add(
                findings,
                "error",
                "ai_review_artifacts",
                f"stages.{stage}.artifacts must list produced or reviewed files",
            )

        if status == "approved" and (
            limited or limitations or blocking_issues
        ):
            self._add(
                findings,
                "error",
                "ai_review_status_consistency",
                f"stages.{stage}: approved requires passed/confirmed checks "
                "and no limitations",
            )
        if status == "approved_with_limitations" and not (
            limited or limitations
        ):
            self._add(
                findings,
                "error",
                "ai_review_status_consistency",
                f"stages.{stage}: approved_with_limitations must identify "
                "a limitation",
            )
        blocked = bool(blocking_issues) or blocking_check
        if status == "blocked" and not blocked:
            self._add(
                findings,
                "error",
                "ai_review_status_consistency",
                f"stages.{stage}: blocked must identify a blocking issue",
            )
        if status != "blocked" and blocked:
            self._add(
                findings,
                "error",
                "ai_review_status_consistency",
                f"stages.{stage}: blocking issues require review_status: blocked",
            )
        if status == "blocked":
            self._add(
                findings,
                "error",
                "ai_review_blocked",
                f"stages.{stage} is blocked",
            )
        elif status == "approved_with_limitations" and emit_warning:
            self._add(
                findings,
                "warning",
                "ai_review_limitations_recorded",
                f"stages.{stage} passed with recorded limitations",
            )
        return status or None

    def do_check(
        self, timeout=0, is_complete=False, **kwargs: Any
    ) -> tuple[bool, object]:
        """Validate the configured AI review stage and its prior artifacts."""
        findings: list[dict[str, Any]] = []
        review_path = self._resolve(self.review_file)
        for artifact in self.required_artifacts:
            candidate = Path(artifact).expanduser()
            pattern = str(
                candidate
                if candidate.is_absolute()
                else self._root() / candidate
            )
            if not glob.glob(pattern, recursive=True):
                self._add(
                    findings,
                    "error",
                    "ai_review_required_artifact",
                    f"required stage artifact does not exist: {artifact}",
                    artifact=artifact,
                )

        data = self._load(review_path, findings)
        statuses: dict[str, str | None] = {}
        if data is not None:
            if not isinstance(data, dict):
                self._add(
                    findings,
                    "error",
                    "ai_review_schema",
                    "AI review report must be a YAML mapping",
                )
            else:
                if data.get("schema_version") != 1:
                    self._add(
                        findings,
                        "error",
                        "ai_review_schema_version",
                        "schema_version must be 1",
                    )
                if str(data.get("reviewer", "")).strip().lower() != "ai":
                    self._add(
                        findings,
                        "error",
                        "ai_review_reviewer",
                        "reviewer must be 'ai'; do not claim human approval",
                    )
                stages = data.get("stages")
                if not isinstance(stages, dict):
                    self._add(
                        findings,
                        "error",
                        "ai_review_schema",
                        "stages must be a YAML mapping",
                    )
                else:
                    for prior_stage in self.required_prior_stages:
                        if prior_stage not in stages:
                            self._add(
                                findings,
                                "error",
                                "ai_review_prior_stage",
                                f"required prior stage is missing: {prior_stage}",
                            )
                        else:
                            statuses[prior_stage] = self._validate_stage(
                                prior_stage,
                                stages[prior_stage],
                                findings,
                                set(),
                                False,
                            )
                    if self.expected_stage not in stages:
                        self._add(
                            findings,
                            "error",
                            "ai_review_stage",
                            f"expected stage is missing: {self.expected_stage}",
                        )
                    else:
                        statuses[self.expected_stage] = self._validate_stage(
                            self.expected_stage,
                            stages[self.expected_stage],
                            findings,
                            self.required_check_names,
                            True,
                        )

        errors = sum(item["severity"] == "error" for item in findings)
        warnings = sum(item["severity"] == "warning" for item in findings)
        report = {
            "status": "failed" if errors else "complete",
            "summary": {"errors": errors, "warnings": warnings},
            "checks": {
                "review_file": str(review_path),
                "expected_stage": self.expected_stage,
                "stage_statuses": statuses,
            },
            "findings": findings,
        }
        self._last_report = report
        return errors == 0, report


__all__ = ["ACT4AIReviewChecker"]
