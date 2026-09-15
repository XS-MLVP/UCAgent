# -*- coding: utf-8 -*-
"""Deterministic stage gate for evaluation workflows."""

from __future__ import annotations

import os
import re
import json
import hashlib
from pathlib import Path
from typing import Any

import yaml

from ucagent.checkers.base import Checker

from .core import EvaluationControlError, evaluation_stage_decision
from .approvals import approval_is_current
from .incremental import IncrementalDeploymentError, verify_incremental_application
from .incremental_runs import (
    IncrementalRunError,
    current_incremental_run,
    latest_command_receipt,
    workflow_fingerprint,
)
from .json_store import JsonStoreError, load_document
from .rules import (
    CONFIDENCES,
    SEVERITIES,
    TERMINAL_STATUSES,
    expected_report_status,
    required_check_ids,
)


class EvaluationJsonReportChecker(Checker):
    """Validate one JSON report and require its latest run to contain auditable evidence."""

    def __init__(
        self,
        report_path: str,
        expected_report_type: str = "",
        required_checks: list[str] | None = None,
        **kwargs,
    ):
        super().__init__()
        self.report_path = report_path
        self.expected_report_type = expected_report_type
        self.required_checks = required_checks or list(required_check_ids(expected_report_type))

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """Check the fixed report envelope, latest-run link, checks, findings, and terminal status."""
        workspace = Path(self.workspace or os.environ.get("UCAGENT_WORKSPACE", os.getcwd())).resolve()
        try:
            value = load_document(workspace, self.report_path)
        except JsonStoreError as exc:
            return False, {"error": str(exc), "report_path": self.report_path}
        if self.expected_report_type and value.get("report_type") != self.expected_report_type:
            return False, {
                "error": "report_type mismatch",
                "expected": self.expected_report_type,
                "actual": value.get("report_type"),
            }
        latest = value.get("latest_run_id")
        run = next((item for item in value.get("runs", []) if item.get("run_id") == latest), None)
        if run is None:
            return False, {"error": "report has no valid latest run", "report_path": self.report_path}
        errors = []
        if self.report_path == "eval/incremental_report.json" and os.environ.get("UCAGENT_INC_RUN_ID"):
            try:
                current_run = current_incremental_run(workspace)
                if latest != current_run["run_id"]:
                    errors.append(
                        f"latest incremental report run_id must equal current run_id {current_run['run_id']}"
                    )
            except IncrementalRunError as exc:
                errors.append(f"cannot validate current incremental run identity: {exc}")
        if run.get("status") not in TERMINAL_STATUSES:
            errors.append("latest run must have a terminal status")
        if not isinstance(run.get("checks"), list) or not run["checks"]:
            errors.append("latest run checks must be a non-empty array")
        if not isinstance(run.get("findings"), list):
            errors.append("latest run findings must be an array")
        if not run.get("started_at") or not run.get("finished_at"):
            errors.append("latest run must include started_at and finished_at")
        checks = run.get("checks", []) if isinstance(run.get("checks"), list) else []
        check_ids = {item.get("id") for item in checks if isinstance(item, dict)}
        missing_checks = sorted(set(self.required_checks) - check_ids)
        if missing_checks:
            errors.append(f"mandatory checks are missing: {', '.join(missing_checks)}")
        for check in checks:
            if not isinstance(check, dict):
                errors.append("every check must be an object")
                continue
            if not check.get("summary"):
                errors.append(f"check {check.get('id')} must explain what was observed")
            if not isinstance(check.get("evidence"), list) or not check["evidence"]:
                errors.append(f"check {check.get('id')} must contain non-empty evidence")
            elif run.get("contract_version", 1) >= 2 and not all(
                isinstance(item, dict) and item.get("kind") and item.get("observation")
                for item in check["evidence"]
            ):
                errors.append(
                    f"check {check.get('id')} contract v2 evidence must be structured with kind and observation"
                )
        findings = run.get("findings", []) if isinstance(run.get("findings"), list) else []
        for finding in findings:
            if not isinstance(finding, dict):
                errors.append("every finding must be an object")
                continue
            for field in (
                "expected",
                "actual",
                "severity_reason",
                "confidence",
                "requirement_refs",
            ):
                if field not in finding:
                    errors.append(f"finding {finding.get('id')} lacks {field}")
                elif finding.get(field) is None or finding.get(field) == "" or finding.get(field) == []:
                    errors.append(f"finding {finding.get('id')} has empty {field}")
            if finding.get("severity") not in SEVERITIES:
                errors.append(f"finding {finding.get('id')} has invalid severity")
            if finding.get("confidence") not in CONFIDENCES:
                errors.append(f"finding {finding.get('id')} has invalid confidence")
            if finding.get("confidence") == "suspected" and finding.get("severity") != "info":
                errors.append(
                    f"finding {finding.get('id')} is suspected and must remain an info observation"
                )
            if not isinstance(finding.get("evidence"), list) or not finding["evidence"]:
                errors.append(f"finding {finding.get('id')} lacks evidence")
            elif run.get("contract_version", 1) >= 2 and not all(
                isinstance(item, dict) and item.get("kind") and item.get("observation")
                for item in finding["evidence"]
            ):
                errors.append(
                    f"finding {finding.get('id')} contract v2 evidence must be structured with kind and observation"
                )
        if self.expected_report_type == "checkers":
            self._validate_checker_evidence(checks, findings, errors)
        if checks and isinstance(run.get("findings"), list) and run.get("status") in {
            "passed",
            "passed_with_findings",
            "failed",
            "blocked",
        }:
            expected = expected_report_status(checks, findings)
            if run.get("status") != expected:
                errors.append(
                    f"status conflicts with checks/findings: expected {expected}, got {run.get('status')}"
                )
        if errors:
            return False, {"error": "latest report run is incomplete", "errors": errors, "run_id": latest}
        return True, {
            "message": "evaluation JSON report is structurally complete",
            "report_path": self.report_path,
            "run_id": latest,
            "status": run["status"],
            "check_count": len(run["checks"]),
            "finding_count": len(run["findings"]),
        }

    @staticmethod
    def _validate_checker_evidence(
        checks: list[dict[str, Any]],
        findings: list[dict[str, Any]],
        errors: list[str],
    ) -> None:
        """Reject circular fixtures and unreachable synthetic Checker findings."""
        positive = next(
            (item for item in checks if isinstance(item, dict) and item.get("id") == "CHECKERS-POSITIVE"),
            None,
        )
        positive_evidence = positive.get("evidence", []) if isinstance(positive, dict) else []
        integration = [
            item
            for item in positive_evidence
            if isinstance(item, dict) and item.get("kind") == "producer_checker"
        ]
        if not integration:
            errors.append(
                "CHECKERS-POSITIVE must contain producer_checker evidence from a real producer artifact"
            )
        for item in integration:
            missing = [
                field
                for field in ("producer", "checker", "artifact", "observation")
                if not item.get(field)
            ]
            if missing:
                errors.append(
                    "CHECKERS-POSITIVE producer_checker evidence lacks " + ", ".join(missing)
                )

        synthetic_kinds = {"fixture", "test", "fuzz", "synthetic"}
        guarded_categories = {"robustness", "negative", "false-result", "exception", "malformed"}
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            evidence = finding.get("evidence", [])
            if not isinstance(evidence, list):
                continue
            category = str(finding.get("category", "")).strip().lower()
            uses_synthetic_input = category in guarded_categories or any(
                isinstance(item, dict)
                and (
                    str(item.get("kind", "")).lower() in synthetic_kinds
                    or str(item.get("path", "")).startswith("tmp/")
                )
                for item in evidence
            )
            if not uses_synthetic_input:
                continue
            reachability = [
                item
                for item in evidence
                if isinstance(item, dict) and item.get("kind") == "reachability"
            ]
            finding_id = finding.get("id")
            if not reachability:
                errors.append(
                    f"finding {finding_id} uses synthetic input but lacks reachability evidence"
                )
                continue
            for item in reachability:
                missing = [field for field in ("producer", "artifact", "observation") if not item.get(field)]
                if missing:
                    errors.append(
                        f"finding {finding_id} reachability evidence lacks {', '.join(missing)}"
                    )
                if not isinstance(item.get("reachable"), bool):
                    errors.append(
                        f"finding {finding_id} reachability evidence requires boolean reachable"
                    )
                    continue
                if not item["reachable"] and (
                    finding.get("severity") != "info" or finding.get("confidence") != "suspected"
                ):
                    errors.append(
                        f"finding {finding_id} is unreachable and must remain info/suspected"
                    )


class EvaluationGuideCoverageChecker(Checker):
    """Require evaluation guides to contain substantial, traceable rule catalogs."""

    def __init__(
        self,
        guide_path: str,
        required_markers: list[str] | None = None,
        min_effective_lines: int = 300,
        **kwargs,
    ):
        super().__init__()
        self.guide_path = guide_path
        self.required_markers = required_markers or []
        self.min_effective_lines = min_effective_lines

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """Check line count, required sections, and stable rule identifiers without executing workflows."""
        workspace = Path(self.workspace or os.environ.get("UCAGENT_WORKSPACE", os.getcwd())).resolve()
        path = (workspace / self.guide_path).resolve()
        if path != workspace and workspace not in path.parents:
            return False, {"error": "guide_path escapes workspace", "guide_path": self.guide_path}
        if not path.is_file():
            return False, {"error": "evaluation guide does not exist", "guide_path": self.guide_path}
        lines = path.read_text(encoding="utf-8").splitlines()
        effective = [line for line in lines if line.strip()]
        missing = [marker for marker in self.required_markers if marker not in "\n".join(lines)]
        errors = []
        if len(effective) < self.min_effective_lines:
            errors.append(
                f"guide has {len(effective)} effective lines; at least {self.min_effective_lines} are required"
            )
        if missing:
            errors.append(f"guide lacks required markers: {', '.join(missing)}")
        normalized = [re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip() for line in effective]
        duplicate_ratio = 1 - (len(set(normalized)) / max(1, len(normalized)))
        if duplicate_ratio > 0.18:
            errors.append(f"guide repeats too many effective lines: duplicate ratio {duplicate_ratio:.2%}")
        if errors:
            return False, {"error": "evaluation guide coverage failed", "errors": errors}
        return True, {
            "message": "evaluation guide has a substantial traceable rule catalog",
            "guide_path": self.guide_path,
            "effective_lines": len(effective),
            "required_markers": self.required_markers,
        }


def _finding_covers_audit(
    report_finding: Any,
    rule_id: str,
    path: str,
) -> bool:
    """Match audit identity fields directly while accepting legacy requirement refs."""
    if not isinstance(report_finding, dict):
        return False
    finding_rule_id = str(
        report_finding.get("rule_id")
        or report_finding.get("id")
        or ""
    )
    refs = report_finding.get("requirement_refs", [])
    if not isinstance(refs, list):
        refs = []
    rule_matches = finding_rule_id == rule_id or rule_id in refs
    finding_path = str(report_finding.get("path", ""))
    serialized = json.dumps(report_finding, ensure_ascii=False, sort_keys=True)
    path_matches = finding_path == path or path in serialized
    return rule_matches and path_matches


class StaticAuditCoverageChecker(Checker):
    """Require every deterministic high-risk audit result to appear in the flow report."""

    def __init__(
        self,
        audit_path: str = "tmp/eval_static_audit/flow.json",
        report_path: str = "eval/flow_report.json",
        **kwargs,
    ):
        super().__init__()
        self.audit_path = audit_path
        self.report_path = report_path

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """Cross-check static audit rule/path evidence against the latest flow findings."""
        workspace = Path(self.workspace or os.environ.get("UCAGENT_WORKSPACE", os.getcwd())).resolve()
        audit_path = (workspace / self.audit_path).resolve()
        allowed = (workspace / "tmp" / "eval_static_audit").resolve()
        if audit_path != allowed and allowed not in audit_path.parents:
            return False, {"error": "audit_path must stay below tmp/eval_static_audit"}
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            report = load_document(workspace, self.report_path)
        except (OSError, json.JSONDecodeError, JsonStoreError) as exc:
            return False, {"error": f"cannot load static audit coverage inputs: {exc}"}
        latest = report.get("latest_run_id")
        run = next((item for item in report.get("runs", []) if item.get("run_id") == latest), None)
        if not run:
            return False, {"error": "flow report has no latest run"}
        report_findings = run.get("findings", [])
        missing = []
        for audit_finding in audit.get("findings", []):
            if audit_finding.get("severity") not in {"critical", "high"}:
                continue
            rule_id = str(audit_finding.get("rule_id", ""))
            path = str(audit_finding.get("path", ""))
            matched = False
            for report_finding in report_findings:
                if _finding_covers_audit(report_finding, rule_id, path):
                    matched = True
                    break
            if not matched:
                missing.append(
                    {
                        "rule_id": rule_id,
                        "path": path,
                        "location": audit_finding.get("location", ""),
                        "expected_identity": (
                            "copy audit rule_id into finding.rule_id and preserve the "
                            "audited path in finding.path or structured evidence"
                        ),
                    }
                )
        if missing:
            return False, {
                "error": "flow report omitted deterministic critical/high audit findings",
                "missing": missing,
            }
        return True, {
            "message": "all deterministic high-risk audit findings are represented in the flow report",
            "audit_path": self.audit_path,
            "covered_count": len(
                [
                    item
                    for item in audit.get("findings", [])
                    if item.get("severity") in {"critical", "high"}
                ]
            ),
        }


class IncrementalAuditCoverageChecker(Checker):
    """Require incremental reports to reflect deterministic semantic audit results."""

    def __init__(
        self,
        audit_path: str = "tmp/eval_static_audit/incremental.json",
        report_path: str = "eval/incremental_report.json",
        **kwargs,
    ):
        super().__init__()
        self.audit_path = audit_path
        self.report_path = report_path

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """Reject omitted audit findings and unverified no-change conclusions."""
        workspace = Path(self.workspace or os.environ.get("UCAGENT_WORKSPACE", os.getcwd())).resolve()
        try:
            if self.audit_path == "tmp/inc_runs/current.json":
                run = current_incremental_run(workspace)
                audit_path = run["path"] / "checks" / "incremental-static-audit.json"
            else:
                audit_path = (workspace / self.audit_path).resolve()
        except IncrementalRunError as exc:
            return False, {"error": f"cannot resolve incremental audit path: {exc}"}
        allowed = (workspace / "tmp" / "eval_static_audit").resolve()
        run_allowed = (workspace / "tmp" / "inc_runs").resolve()
        if (
            audit_path != allowed
            and allowed not in audit_path.parents
            and run_allowed not in audit_path.parents
        ):
            return False, {"error": "audit_path must stay below controlled incremental tmp roots"}
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            report = load_document(workspace, self.report_path)
        except (OSError, json.JSONDecodeError, JsonStoreError) as exc:
            return False, {"error": f"cannot load incremental audit coverage inputs: {exc}"}
        latest = report.get("latest_run_id")
        run = next((item for item in report.get("runs", []) if item.get("run_id") == latest), None)
        if not run:
            return False, {"error": "incremental report has no latest run"}
        high_risk = [
            item
            for item in audit.get("findings", [])
            if item.get("severity") in {"critical", "high"}
        ]
        report_findings = run.get("findings", []) if isinstance(run.get("findings"), list) else []
        missing = []
        invalid_status = []
        for audit_finding in high_risk:
            rule_id = str(audit_finding.get("rule_id", ""))
            path = str(audit_finding.get("path", ""))
            matched = [
                finding
                for finding in report_findings
                if _finding_covers_audit(finding, rule_id, path)
            ]
            if not matched:
                missing.append(
                    {
                        "rule_id": rule_id,
                        "path": path,
                        "location": audit_finding.get("location", ""),
                        "expected_identity": (
                            "copy audit rule_id into finding.rule_id and preserve the "
                            "audited path in finding.path or structured evidence"
                        ),
                    }
                )
            elif not any(finding.get("status", "open") == "open" for finding in matched):
                invalid_status.append(
                    {
                        "rule_id": rule_id,
                        "path": path,
                        "location": audit_finding.get("location", ""),
                        "statuses": sorted(
                            {str(finding.get("status", "open")) for finding in matched}
                        ),
                    }
                )
        errors = []
        if missing:
            errors.append(
                {
                    "error": "incremental report omitted deterministic critical/high audit findings",
                    "missing": missing,
                }
            )
        if invalid_status:
            errors.append(
                {
                    "error": "deterministic findings that still reproduce must remain open",
                    "invalid_status": invalid_status,
                }
            )
        if high_risk and run.get("status") != "failed":
            errors.append(
                {
                    "error": "deterministic critical/high findings require a failed incremental report",
                    "actual_status": run.get("status"),
                }
            )
        verdict = run.get("summary", {}).get("verdict") if isinstance(run.get("summary"), dict) else ""
        if verdict == "no_change" and not high_risk:
            statuses = {
                item.get("id"): item.get("status")
                for item in run.get("checks", [])
                if isinstance(item, dict)
            }
            not_passed = {
                check_id: statuses.get(check_id)
                for check_id in required_check_ids("incremental")
                if statuses.get(check_id) != "passed"
            }
            if not_passed:
                errors.append(
                    {
                        "error": "a clean no_change verdict must revalidate every incremental check",
                        "not_passed": not_passed,
                    }
                )
            if run.get("status") != "passed":
                errors.append(
                    {
                        "error": "a fully revalidated clean no_change verdict must be passed",
                        "actual_status": run.get("status"),
                    }
                )
        if errors:
            return False, {"error": "incremental audit coverage failed", "errors": errors}
        return True, {
            "message": "incremental report covers deterministic semantic audit results",
            "audit_path": audit_path.relative_to(workspace).as_posix(),
            "high_risk_count": len(high_risk),
            "verdict": verdict,
        }


class IncrementalContextReportChecker(Checker):
    """Require a small, fresh architecture baseline before approved incremental repair."""

    def __init__(
        self,
        workflow_root: str = "workflow",
        report_path: str = "tmp/incremental_context_report.json",
        resource_root: str = "res",
        **kwargs,
    ):
        super().__init__()
        self.workflow_root = workflow_root
        self.report_path = report_path
        self.resource_root = resource_root

    @staticmethod
    def _inside(root: Path, path: Path) -> bool:
        return path == root or root in path.parents

    def _required_files(self, workspace: Path, workflow: Path, resource: Path) -> set[Path]:
        """Return only files needed to orient a repair, not every document in the product.

        Deep source/spec/test reading belongs to the individual approved-change batch. Requiring
        complete documentation and resource trees here delayed the first repair candidate and
        repeatedly exhausted model context on larger generated workflows.
        """
        required: set[Path] = set()
        for relative in (
            "config.yaml",
            "config/inc.yaml",
            ".workflow/workflow_spec.yaml",
            ".workflow/acceptance_rules.yaml",
            "Makefile",
            "setup.py",
            "ucagent_setup.sh",
            "requirements.txt",
            "README.md",
            "docs/README.md",
            "docs/02输入输出.md",
            "docs/03步骤及检查.md",
            "docs/04开发者文档-tools.md",
            "docs/05开发者文档-checkers.md",
        ):
            path = (workflow / relative).resolve()
            if path.is_file():
                required.add(path)
        for relative in ("common.json", "index.json"):
            path = (resource / relative).resolve()
            if path.is_file():
                required.add(path)
        return required

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """Cross-check report coverage and hashes against the minimal repair-context baseline."""
        workspace = Path(self.workspace or os.environ.get("UCAGENT_WORKSPACE", os.getcwd())).resolve()
        workflow = (workspace / self.workflow_root).resolve()
        resource = (workspace / self.resource_root).resolve()
        try:
            if self.report_path == "tmp/inc_runs/current.json":
                run = current_incremental_run(workspace)
                report_path = run["path"] / "context" / "incremental_context_report.json"
            else:
                report_path = (workspace / self.report_path).resolve()
        except IncrementalRunError as exc:
            return False, {"error": f"cannot resolve incremental context report: {exc}"}
        if not self._inside(workspace, workflow) or not self._inside(workspace, report_path):
            return False, {"error": "context paths must stay inside workspace"}
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return False, {"error": f"cannot load incremental context report: {exc}"}
        if not isinstance(report, dict):
            return False, {"error": "incremental context report must be a JSON object"}

        errors: list[str] = []
        if report.get("contract_version") != 1:
            errors.append("contract_version must be 1")
        if report.get("workflow_root") != self.workflow_root:
            errors.append(f"workflow_root must be {self.workflow_root}")
        for field in (
            "architecture",
            "runtime_flow",
            "approved_change_impact",
            "cross_file_risks",
        ):
            if not isinstance(report.get(field), str) or len(report[field].strip()) < 40:
                errors.append(f"{field} must contain at least 40 characters of concrete analysis")

        records = report.get("files")
        if not isinstance(records, list):
            return False, {"error": "files must be an array", "errors": errors}
        indexed: dict[str, dict[str, Any]] = {}
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                errors.append(f"files[{index}] must be an object")
                continue
            relative = record.get("path")
            if not isinstance(relative, str) or not relative:
                errors.append(f"files[{index}].path is required")
                continue
            if relative in indexed:
                errors.append(f"duplicate file record: {relative}")
                continue
            indexed[relative] = record
            target = (workspace / relative).resolve()
            if not self._inside(workspace, target) or not target.is_file():
                errors.append(f"reported file is missing or escapes workspace: {relative}")
                continue
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if record.get("sha256") != digest:
                errors.append(f"stale or invalid sha256: {relative}")
            if not isinstance(record.get("category"), str) or not record["category"].strip():
                errors.append(f"category is required: {relative}")
            for field in ("purpose", "contract"):
                value = record.get(field)
                if not isinstance(value, str) or len(value.strip()) < 10:
                    errors.append(f"{field} must contain concrete analysis: {relative}")
            links = record.get("synchronizes_with")
            if not isinstance(links, list) or any(not isinstance(item, str) for item in links):
                errors.append(f"synchronizes_with must be a string array: {relative}")

        required = {
            path.relative_to(workspace).as_posix()
            for path in self._required_files(workspace, workflow, resource)
        }
        missing = sorted(required - set(indexed))
        if missing:
            errors.append(f"required files are missing from context report: {', '.join(missing[:30])}")
            if len(missing) > 30:
                errors.append(f"{len(missing) - 30} additional required files are missing")
        if errors:
            return False, {
                "error": "incremental workflow understanding baseline is incomplete",
                "errors": errors,
                "required_count": len(required),
                "reported_count": len(indexed),
            }
        return True, {
            "message": "incremental workflow understanding baseline covers all current required files",
            "required_count": len(required),
            "reported_count": len(indexed),
            "report_path": report_path.relative_to(workspace).as_posix(),
        }


class IncrementalApprovalChecker(Checker):
    """Require valid deployment authorization and optionally complete approved-item coverage."""

    def __init__(
        self,
        approvals_path: str = "eval/approvals.json",
        changes_path: str = "eval/applied_changes.json",
        require_all_current: bool = False,
        **kwargs,
    ):
        super().__init__()
        self.approvals_path = approvals_path
        self.changes_path = changes_path
        self.require_all_current = require_all_current

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """Cross-check applied-change approval ids against approved records without running child workflows."""
        workspace = Path(self.workspace or os.environ.get("UCAGENT_WORKSPACE", os.getcwd())).resolve()
        try:
            approvals = load_document(workspace, self.approvals_path)
            changes = load_document(workspace, self.changes_path)
        except JsonStoreError as exc:
            return False, {"error": str(exc)}
        approvals_by_id = {
            str(item["id"]): item
            for item in approvals.get("items", [])
            if isinstance(item, dict) and item.get("id")
        }
        provenance_fields = {
            "id",
            "source_kind",
            "source_report",
            "source_id",
            "source_fingerprint",
            "decided_at",
        }

        def valid_provenance(
            cited: list[str],
            snapshots: Any,
            *,
            allow_legacy: bool,
        ) -> bool:
            if isinstance(snapshots, list):
                indexed = {
                    str(item.get("id")): item
                    for item in snapshots
                    if isinstance(item, dict) and item.get("id")
                }
                return set(indexed) == set(cited) and all(
                    item.get("decision") == "approved"
                    and provenance_fields.issubset(item)
                    and all(item.get(field) for field in provenance_fields)
                    and "source_run_id" in item
                    for item in indexed.values()
                ) and len(indexed) == len(snapshots)
            if not allow_legacy:
                return False
            return all(
                item in approvals_by_id
                and approvals_by_id[item].get("decision") == "approved"
                and provenance_fields.issubset(approvals_by_id[item])
                and all(approvals_by_id[item].get(field) for field in provenance_fields)
                and "source_run_id" in approvals_by_id[item]
                for item in cited
            )

        failures = []
        covered_approval_ids: set[str] = set()
        legacy_entries = 0
        for entry in changes.get("entries", []):
            cited = entry.get("approval_ids", [])
            is_restore = entry.get("operation") == "restore"
            authorization = entry.get("user_authorization", {})
            user_authorized = (
                is_restore
                and isinstance(authorization, dict)
                and authorization.get("action") == "restore"
                and authorization.get("reason")
                and authorization.get("authorized_at")
                and authorization.get("source_repair_id")
            )
            if (
                not isinstance(cited, list)
                or not cited
                or (
                    not user_authorized
                    and not valid_provenance(
                        cited,
                        entry.get("approval_provenance"),
                        allow_legacy=True,
                    )
                )
            ):
                failures.append({"id": entry.get("id"), "approval_ids": cited})
                continue
            if not is_restore and entry.get("approval_provenance") is None:
                legacy_entries += 1
            mapping_failures = []
            mapping_citations: set[str] = set()
            for index, change in enumerate(entry.get("applied_changes", [])):
                mapping_ids = change.get("approval_ids", []) if isinstance(change, dict) else []
                rationale = change.get("rationale", "") if isinstance(change, dict) else ""
                if (
                    not isinstance(mapping_ids, list)
                    or not mapping_ids
                    or any(
                        item not in cited
                        for item in mapping_ids
                    )
                    or not isinstance(rationale, str)
                    or len(rationale.strip()) < 20
                    or (
                        not user_authorized
                        and not valid_provenance(
                            mapping_ids,
                            change.get("approval_provenance"),
                            allow_legacy=entry.get("approval_provenance") is None,
                        )
                    )
                ):
                    mapping_failures.append(
                        {"index": index, "approval_ids": mapping_ids, "rationale": rationale}
                    )
                else:
                    mapping_citations.update(mapping_ids)
            if mapping_citations != set(cited):
                mapping_failures.append(
                    {"error": "deployment approvals are not all tied to at least one file"}
                )
            covered_approval_ids.update(mapping_citations)
            if mapping_failures:
                failures.append({"id": entry.get("id"), "mapping_failures": mapping_failures})
        current_approved_ids: set[str] = set()
        if self.require_all_current:
            try:
                current_approved_ids = {
                    approval_id
                    for approval_id, approval in approvals_by_id.items()
                    if approval_is_current(workspace, approval)
                }
            except JsonStoreError as exc:
                return False, {"error": str(exc), "approvals_path": self.approvals_path}
            uncovered = sorted(current_approved_ids - covered_approval_ids)
            if uncovered:
                failures.append(
                    {
                        "error": "current approved items have not been deployed",
                        "uncovered_approval_ids": uncovered,
                    }
                )
        if failures:
            return False, {
                "error": "applied changes lack explicit valid approvals or complete approved-item coverage",
                "failures": failures,
                "current_approved_ids": sorted(current_approved_ids),
                "covered_approval_ids": sorted(covered_approval_ids),
            }
        return True, {
            "message": "all applied changes retain valid deployment-time authorization",
            "applied_count": len(changes["entries"]),
            "legacy_entry_count": legacy_entries,
            "require_all_current": self.require_all_current,
            "current_approved_ids": sorted(current_approved_ids),
            "covered_approval_ids": sorted(covered_approval_ids),
        }


class EvaluationStageGateChecker(Checker):
    """Return the run/skip decision for an evaluation stage without failing skipped stages."""

    def __init__(self, control_path: str, stage_name: str, report_stage: bool = False, **kwargs):
        super().__init__()
        self.control_path = control_path
        self.stage_name = stage_name
        self.report_stage = report_stage

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """
        Read evaluation control state and return a deterministic run/skip decision.
        A skipped stage passes this gate because the skip is intentional; malformed or missing control state fails.
        """
        workspace = Path(self.workspace or os.environ.get("UCAGENT_WORKSPACE", os.getcwd())).resolve()
        path = Path(self.control_path)
        path = path.resolve() if path.is_absolute() else (workspace / path).resolve()
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise EvaluationControlError("control state is not a mapping")
            decision = evaluation_stage_decision(value, self.stage_name, self.report_stage)
        except (OSError, yaml.YAMLError, EvaluationControlError) as exc:
            return False, {"error": str(exc), "control_path": str(path), "stage_name": self.stage_name}
        return True, decision


class EvaluationEvidenceChecker(Checker):
    """Require a structured, non-empty evidence record for an evaluation stage."""

    VALID_STATUSES = {"passed", "failed", "blocked", "skipped"}

    def __init__(self, evidence_path: str, stage_name: str, **kwargs):
        super().__init__()
        self.evidence_path = evidence_path
        self.stage_name = stage_name

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """Validate one evaluation stage's persisted runtime evidence."""
        workspace = Path(self.workspace or os.environ.get("UCAGENT_WORKSPACE", os.getcwd())).resolve()
        path = Path(self.evidence_path)
        path = path.resolve() if path.is_absolute() else (workspace / path).resolve()
        if path != workspace and workspace not in path.parents:
            return False, {"error": "evidence path escapes workspace", "path": str(path)}
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            return False, {"error": str(exc), "evidence_path": str(path)}
        if not isinstance(value, dict):
            return False, {"error": "evaluation evidence must be a mapping", "evidence_path": str(path)}
        evidence = value.get("evidence")
        errors = []
        if value.get("stage") != self.stage_name:
            errors.append(f"stage must be {self.stage_name}")
        if value.get("status") not in self.VALID_STATUSES:
            errors.append("status must be passed, failed, blocked, or skipped")
        if not isinstance(evidence, list) or not evidence:
            errors.append("evidence must be a non-empty list")
        elif any(not isinstance(item, dict) or not item for item in evidence):
            errors.append("every evidence entry must be a non-empty mapping")
        if errors:
            return False, {"error": "evaluation stage evidence is incomplete", "errors": errors}
        return True, {
            "message": "evaluation stage evidence passed",
            "stage": self.stage_name,
            "status": value["status"],
            "evidence_count": len(evidence),
        }


class IncrementalApplicationChecker(Checker):
    """Verify staged incremental fixes were actually applied to the generated workflow."""

    def __init__(
        self,
        workflow_root: str,
        manifest_path: str = "eval/applied_changes.json",
        **kwargs,
    ):
        super().__init__()
        self.workflow_root = workflow_root
        self.manifest_path = manifest_path

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """
        Compare each deployed target with its staged source and recorded SHA256.
        The checker fails when fixes exist only under evaluation/ and were not copied into the generated workflow.
        """
        workspace = Path(self.workspace or os.environ.get("UCAGENT_WORKSPACE", os.getcwd())).resolve()
        try:
            return verify_incremental_application(workspace, self.workflow_root, self.manifest_path)
        except IncrementalDeploymentError as exc:
            return False, {"error": str(exc), "manifest_path": self.manifest_path}


class IncrementalRegressionChecker(IncrementalApplicationChecker):
    """Verify deployed changes, config syntax, and a fingerprint-bound make-check receipt."""

    def __init__(
        self,
        workflow_root: str,
        manifest_path: str = "eval/applied_changes.json",
        run_id: str = "",
        **kwargs,
    ):
        super().__init__(workflow_root, manifest_path, **kwargs)
        self.run_id = run_id

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, Any]:
        """
        Verify deployment evidence, parse generated configs, and validate the tool-produced make-check receipt.
        The receipt is accepted only while its workflow fingerprint matches the current formal files.
        """
        deployed, details = super().do_check(timeout=timeout, **kwargs)
        if not deployed:
            return False, details

        workspace = Path(self.workspace or os.environ.get("UCAGENT_WORKSPACE", os.getcwd())).resolve()
        root = (workspace / self.workflow_root).resolve()
        if root != workspace and workspace not in root.parents:
            return False, {"error": "workflow_root escapes workspace", "workflow_root": self.workflow_root}

        parse_failures: list[dict[str, str]] = []
        for relative in ("config.yaml", "config/inc.yaml"):
            path = root / relative
            try:
                value = yaml.safe_load(path.read_text(encoding="utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("config root must be a mapping")
            except (OSError, ValueError, yaml.YAMLError) as exc:
                parse_failures.append({"path": relative, "error": str(exc)})
        if parse_failures:
            return False, {"error": "generated workflow config syntax check failed", "failures": parse_failures}

        try:
            receipt = latest_command_receipt(workspace, self.run_id, "make_check")
            current_fingerprint = workflow_fingerprint(root)
        except (IncrementalRunError, OSError) as exc:
            return False, {"error": f"cannot validate generated workflow regression receipt: {exc}"}
        if receipt.get("workflow_root") != self.workflow_root:
            return False, {
                "error": "make check receipt targets a different workflow root",
                "receipt_path": receipt.get("receipt_path"),
            }
        if receipt.get("workflow_fingerprint") != current_fingerprint:
            return False, {
                "error": "formal workflow changed after the latest make check receipt",
                "receipt_path": receipt.get("receipt_path"),
                "receipt_fingerprint": receipt.get("workflow_fingerprint"),
                "current_fingerprint": current_fingerprint,
            }
        if receipt.get("returncode") != 0:
            try:
                report = load_document(workspace, "eval/incremental_report.json")
            except JsonStoreError as exc:
                return False, {"error": str(exc), "receipt_path": receipt.get("receipt_path")}
            latest = report.get("latest_run_id")
            run = next(
                (item for item in report.get("runs", []) if item.get("run_id") == latest),
                None,
            )
            summary = run.get("summary", {}) if isinstance(run, dict) else {}
            blocker = summary.get("blocking_reason_code") if isinstance(summary, dict) else ""
            receipt_path = summary.get("make_check_receipt") if isinstance(summary, dict) else ""
            open_findings = [
                item
                for item in (run.get("findings", []) if isinstance(run, dict) else [])
                if isinstance(item, dict) and item.get("status", "open") == "open"
            ]
            if (
                isinstance(run, dict)
                and run.get("status") in {"failed", "blocked"}
                and blocker in {"outside_approved_scope", "external_execution_block"}
                and receipt_path == receipt.get("receipt_path")
                and open_findings
            ):
                return True, {
                    **details,
                    "message": "incremental run truthfully terminated on an external authorization or execution blocker",
                    "repair_succeeded": False,
                    "blocking_reason_code": blocker,
                    "returncode": receipt.get("returncode"),
                    "receipt_path": receipt.get("receipt_path"),
                }
            return False, {
                "error": "generated workflow make check failed",
                "returncode": receipt.get("returncode"),
                "stdout_tail": str(receipt.get("stdout_tail", ""))[-4000:],
                "stderr_tail": str(receipt.get("stderr_tail", ""))[-4000:],
                "receipt_path": receipt.get("receipt_path"),
            }
        return True, {
            **details,
            "message": "incremental changes are applied and generated workflow regression passed",
            "make_target": "check",
            "receipt_path": receipt.get("receipt_path"),
            "workflow_fingerprint": current_fingerprint,
        }
