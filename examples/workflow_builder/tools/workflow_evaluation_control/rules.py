# -*- coding: utf-8 -*-
"""Stable rule identifiers and report gates for workflow evaluation."""

from __future__ import annotations

from typing import Final


SEVERITIES: Final = ("critical", "high", "medium", "low", "info")
CONFIDENCES: Final = ("confirmed", "probable", "suspected")
TERMINAL_STATUSES: Final = (
    "passed",
    "passed_with_findings",
    "failed",
    "blocked",
    "skipped",
    "no_change",
)

REQUIRED_CHECK_IDS: Final[dict[str, tuple[str, ...]]] = {
    "tools": (
        "TOOLS-INVENTORY",
        "TOOLS-REGISTRATION",
        "TOOLS-CONTRACT",
        "TOOLS-POSITIVE",
        "TOOLS-NEGATIVE",
        "TOOLS-OUTPUT",
        "TOOLS-FAILURE",
        "TOOLS-SAFETY",
        "TOOLS-SEMANTICS",
        "TOOLS-CHALLENGE",
    ),
    "checkers": (
        "CHECKERS-INVENTORY",
        "CHECKERS-REGISTRATION",
        "CHECKERS-SIGNATURE",
        "CHECKERS-POSITIVE",
        "CHECKERS-NEGATIVE",
        "CHECKERS-BINDING",
        "CHECKERS-TIMING",
        "CHECKERS-SEMANTICS",
        "CHECKERS-FALSE-RESULT",
        "CHECKERS-CHALLENGE",
    ),
    "flow": (
        "FLOW-PARSE",
        "FLOW-PLACEHOLDERS",
        "FLOW-PATHS",
        "FLOW-DAG",
        "FLOW-PROVENANCE",
        "FLOW-TOOLS",
        "FLOW-CHECKERS",
        "FLOW-OUTPUTS",
        "FLOW-RETRY",
        "FLOW-DOCUMENTATION",
        "FLOW-SEMANTICS",
        "FLOW-CHALLENGE",
    ),
    "env": (
        "ENV-MAKE",
        "ENV-SETUP",
        "ENV-SHELL",
        "ENV-DEPENDENCIES",
        "ENV-TOOLCHAIN",
        "ENV-PATHS",
        "ENV-TEMP",
        "ENV-CLEAN",
        "ENV-PORTABILITY",
        "ENV-SECRETS",
        "ENV-CHALLENGE",
    ),
    "run": (
        "RUN-PREFLIGHT",
        "RUN-START",
        "RUN-PROGRESS",
        "RUN-RETRY",
        "RUN-STALL",
        "RUN-TIMEOUT",
        "RUN-CLEANUP",
        "RUN-OUTPUTS",
        "RUN-RESULT",
        "RUN-SEMANTICS",
        "RUN-CHALLENGE",
    ),
    "incremental": (
        "INC-AUTHORIZATION",
        "INC-PROVENANCE",
        "INC-FRESHNESS",
        "INC-SCOPE",
        "INC-CANDIDATE",
        "INC-SOURCE-SYNC",
        "INC-REGRESSION",
        "INC-DEPLOYMENT",
        "INC-RECHECK",
        "INC-CHALLENGE",
    ),
}


def required_check_ids(report_type: str) -> tuple[str, ...]:
    """Return the mandatory checklist for one report type."""
    return REQUIRED_CHECK_IDS.get(report_type, ())


def expected_report_status(checks: list[dict], findings: list[dict]) -> str:
    """Compute the only valid terminal status for substantive evaluation results."""
    if any(check.get("status") == "blocked" for check in checks):
        return "blocked"
    if any(check.get("status") in {"failed", "skipped"} for check in checks):
        return "failed"
    open_findings = [
        finding
        for finding in findings
        if finding.get("status", "open") not in {"resolved", "accepted"}
        and finding.get("severity") != "info"
    ]
    if any(finding.get("severity") in {"critical", "high"} for finding in open_findings):
        return "failed"
    if open_findings:
        return "passed_with_findings"
    return "passed"
