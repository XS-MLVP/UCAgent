"""Validate indexed Bug Review evidence and source backed decisions."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ucagent.util.waveform_viewer import decode_waveform_viewer_token

from .review_store import BugRecord, CaseRecord, ReviewIndex, RootsRecord, source_lines


class ReviewIssues(ValueError):
    """Carry bounded field level problems to tools and Checkers."""

    def __init__(self, issues: list[dict]):
        """Preserve the complete count and a bounded actionable sample."""
        self.issues = issues
        super().__init__(f"{len(issues)} review field errors")

    def result(self) -> dict:
        """Return concise diagnostics for the current repair step."""
        return {"error_code": "BUG_REVIEW_FIELD_INVALID", "error": str(self),
                "issues": self.issues[:20], "truncated_count": max(0, len(self.issues) - 20),
                "next_action": "Correct the listed record fields and submit or Check again"}


def review_incomplete(manifest, cases: dict[str, CaseRecord], environment) -> bool:
    """Identify explicit collection, execution or evidence gaps in one module."""
    if (manifest.collection_errors or environment.unresolved
            or any(finding.status == "unresolved" for finding in environment.findings)):
        return True
    return any(case.replay.status == "not_run" or (
        case.replay.status in {"failed", "error", "xpassed"} and (
            case.failure_analysis.category in {"insufficient_evidence", "spec_ambiguous", "suspected_dut"}
            or (case.failure_analysis.category == "confirmed_dut" and not case.waveform.receipt_id)))
        for case in cases.values())


def case_issues(index: ReviewIndex, case: CaseRecord, waveinfo,
                require_replay: bool = False, require_triage: bool = False,
                require_wave: bool = False, source_root: Path | None = None) -> list[dict]:
    """Check one case's execution, attribution and signed machine evidence."""
    issues: list[dict] = []
    case_id = case.case_id

    def add(field: str, problem: str) -> None:
        """Record one repairable case field error."""
        issues.append({"case_id": case_id, "field": field, "problem": problem})

    entry = index.cases.get(case_id)
    if entry is None:
        add("case_id", "case is not indexed")
        return issues
    linked = {bug_id for bug_id, bug in index.bugs.items() if case_id in bug.case_ids}
    actual_links = set(case.bug_ids)
    if actual_links != linked or len(case.bug_ids) != len(actual_links):
        issues.append({"case_id": case_id, "field": "bug_ids",
                       "expected": sorted(linked), "actual": case.bug_ids,
                       "missing": sorted(linked - actual_links),
                       "extra": sorted(actual_links - linked),
                       "next_action": "Update all Bug-to-case links with CommitAttribution"})
    if case.replay.status == "not_run":
        if require_replay and not case.replay.not_run_reason.strip():
            add("replay.not_run_reason", "record an explicit exclusion or blocking reason")
    elif require_replay:
        if not case.replay.baseline_id or not case.replay.report_node_id:
            add("replay", "baseline_id and exact report_node_id are required")
        if not case.replay.invocation_success and case.replay.status not in {"error"}:
            add("replay.invocation_success", "successful invocation or error status required")
    failed = case.replay.status in {"failed", "error", "xpassed"}
    analysis = case.failure_analysis
    if require_triage and failed:
        if analysis.category == "unreviewed" or not analysis.rationale.strip():
            add("failure_analysis", "failed case needs a reasoned category or an explicit evidence gap")
        if (not analysis.scenario.strip() or not analysis.actual.strip()) and not analysis.unresolved.strip():
            add("failure_analysis", "failed case needs scenario and actual behavior or an explicit gap")
        if analysis.phase == "unknown" and not analysis.unresolved.strip():
            add("failure_analysis.phase", "name the failure phase or explain why it is unknown")
        if analysis.category == "spec_misread" and not analysis.evidence_refs:
            add("failure_analysis.evidence_refs", "spec_misread requires the conflicting Spec line")
        if analysis.category in {"suspected_dut", "confirmed_dut"} and not all((
                analysis.spec_expected.strip(), analysis.test_expected.strip(), analysis.actual.strip())):
            add("failure_analysis", "DUT candidate needs Spec, test and actual behavior")
        if analysis.category in {"suspected_dut", "confirmed_dut"} and not case.test_review.correctness_confirmed:
            add("test_review.correctness_confirmed", "DUT attribution requires a correct test")
        if analysis.category == "insufficient_evidence" and not analysis.unresolved.strip():
            add("failure_analysis.unresolved", "name the missing evidence")
    if source_root is not None:
        for reference in analysis.evidence_refs:
            try:
                source_lines(source_root, reference, 1)
            except (ValueError, OSError) as error:
                add("failure_analysis.evidence_refs", str(error))
    wave = case.waveform
    if wave.conclusion != "inconclusive" and not wave.receipt_id:
        add("waveform.receipt_id", "decisive waveform conclusion needs a signed receipt")
    if require_wave and failed and analysis.category in {"suspected_dut", "confirmed_dut"}:
        if not wave.receipt_id and not wave.diagnostic.strip():
            add("waveform", "DUT candidate needs a receipt or concrete diagnostic")
    if wave.receipt_id:
        receipt = waveinfo.get_analysis_receipt(wave.receipt_id)
        if receipt is None:
            add("waveform.receipt_id", "signed receipt is unavailable")
            return issues
        if receipt.get("arguments", {}).get("test_case_name") != entry.waveform_test_case_name:
            add("waveform.receipt_id", "receipt identity differs from indexed waveform_test_case_name")
        signed = receipt.get("result", {})
        viewer = signed.get("waveform_viewer") or {}
        signed_url = viewer.get("url", "") if isinstance(viewer, dict) else ""
        if wave.analysis_window != signed.get("analysis_window"):
            add("waveform.analysis_window", "window differs from signed receipt")
        if wave.signal_groups != signed.get("signal_groups"):
            add("waveform.signal_groups", "signal groups differ from signed receipt")
        if wave.viewer_url != signed_url:
            add("waveform.viewer_url", "URL differs from signed receipt")
        if wave.viewer_url:
            try:
                encoded = parse_qs(urlparse(wave.viewer_url).query)["wave"][0]
                decode_waveform_viewer_token(encoded)
            except (KeyError, ValueError):
                add("waveform.viewer_url", "viewer wave payload is not decodable JSON")
        if wave.conclusion == "dut_bug":
            if not all((wave.observed_behavior.strip(), wave.alignment_evidence.strip(),
                        wave.source_correlation.strip())):
                add("waveform", "DUT conclusion needs observed, alignment and source analysis")
            if waveinfo.get_bug_document_evidence(wave.receipt_id).get("success") is not True:
                add("waveform.receipt_id", "receipt is not usable final evidence")
    return issues


def validate_correlation(index: ReviewIndex, cases: dict[str, CaseRecord],
                         bugs: dict[str, BugRecord], roots: RootsRecord,
                         source_root: Path, waveinfo) -> None:
    """Validate complete decisions, source references and root membership."""
    issues: list[dict] = []

    def issue(location: str, problem: str) -> None:
        """Append one exact failing location."""
        issues.append({"field": location, "problem": problem})

    expected = set(index.bug_order)
    if set(bugs) != expected:
        issue("bugs", f"missing={sorted(expected - set(bugs))[:10]}, extra={sorted(set(bugs) - expected)[:10]}")
    root_by_id = {root.root_id: root for root in roots.roots}
    if len(root_by_id) != len(roots.roots):
        issue("root_causes", "duplicate root_id")
    signatures = [(root.rtl_ref, root.first_error, root.causal_chain) for root in roots.roots]
    if len(set(signatures)) != len(signatures):
        issue("root_causes", "one cause signature is split across root groups")
    membership: dict[str, str] = {}
    for root in roots.roots:
        if not root.bug_ids or any(not getattr(root, field).strip()
                                   for field in ("rtl_ref", "first_error", "causal_chain")):
            issue(f"roots/{root.root_id}", "root needs members and nonempty shared cause fields")
        for bug_id in root.bug_ids:
            if bug_id in membership:
                issue(f"roots/{root.root_id}/bug_ids", f"duplicate member {bug_id}")
            membership[bug_id] = root.root_id
    for bug_id, bug in bugs.items():
        base = f"bugs/{bug_id}"
        if bug.bug_id != bug_id:
            issue(f"{base}/bug_id", "does not match index identity")
        if bug_id not in index.bugs:
            continue
        if set(bug.case_ids) != set(index.bugs[bug_id].case_ids):
            expected_cases = set(index.bugs[bug_id].case_ids)
            actual_cases = set(bug.case_ids)
            issues.append({"bug_id": bug_id, "field": f"{base}/case_ids",
                           "problem": "does not match index associations",
                           "expected": sorted(expected_cases), "actual": sorted(actual_cases),
                           "missing": sorted(expected_cases - actual_cases),
                           "extra": sorted(actual_cases - expected_cases),
                           "next_action": "Refresh decisions.json case_ids from the active index"})
        for field in ("spec_refs", "rtl_refs"):
            for reference in getattr(bug, field):
                try:
                    source_lines(source_root, reference, max_lines=1)
                except (ValueError, OSError) as error:
                    issue(f"{base}/{field}", str(error))
        decision = bug.decision
        if not decision.rationale.strip():
            issue(f"{base}/decision/rationale", "nonempty reasoning required")
        if decision.verdict == "refuted":
            if (type(decision.review_confidence) not in {int, float}
                    or decision.review_confidence != 0 or decision.root_id is not None):
                issue(f"{base}/decision", "refuted requires confidence 0 and no root")
        elif decision.verdict == "inconclusive":
            if decision.review_confidence is not None or decision.root_id is not None:
                issue(f"{base}/decision", "inconclusive requires null confidence and no root")
        else:
            if (type(decision.review_confidence) not in {int, float}
                    or not 0 < decision.review_confidence <= 1):
                issue(f"{base}/decision/review_confidence", "confirmed requires 0 < confidence <= 1")
            if decision.root_id not in root_by_id or membership.get(bug_id) != decision.root_id:
                issue(f"{base}/decision/root_id", "root membership must be bidirectional")
            root = root_by_id.get(decision.root_id)
            if root:
                for field in ("rtl_ref", "first_error", "causal_chain"):
                    expected, actual = getattr(root, field), getattr(decision, field)
                    if expected != actual:
                        issues.append({"bug_id": bug_id, "field": f"{base}/decision/{field}",
                                       "problem": "decision field must match assigned root exactly",
                                       "expected": expected, "actual": actual,
                                       "next_action": "Copy the exact root field into the LLM-authored decision draft"})
            for field in ("spec_ref", "rtl_ref"):
                reference = getattr(decision, field)
                try:
                    source_lines(source_root, reference, max_lines=1)
                except (ValueError, OSError) as error:
                    issue(f"{base}/decision/{field}", str(error))
            if not all((bug.validation_scenario.strip(), bug.expected_behavior.strip(),
                        bug.observed_behavior.strip(), decision.first_error.strip(),
                        decision.causal_chain.strip())):
                issue(base, "confirmed Bug needs scenario, expected, observed, first_error and causal_chain")
            valid_case = False
            for case_id in bug.case_ids:
                case = cases.get(case_id)
                if not case or case_id not in index.cases or bug_id not in case.bug_ids:
                    continue
                if (case.replay.status == "failed"
                        and case.test_review.correctness_confirmed
                        and case.failure_analysis.category in {"suspected_dut", "confirmed_dut"}
                        and case.waveform.conclusion == "dut_bug"
                        and case.waveform.receipt_id):
                    receipt = waveinfo.get_analysis_receipt(case.waveform.receipt_id)
                    if (receipt and receipt.get("arguments", {}).get("test_case_name")
                            == index.cases[case_id].waveform_test_case_name
                            and waveinfo.get_bug_document_evidence(case.waveform.receipt_id).get("success") is True):
                        valid_case = True
            if not valid_case:
                issue(f"{base}/case_ids", "no correct reproduced case with usable signed DUT waveform")
    for bug_id, root_id in membership.items():
        if bug_id not in bugs or bugs[bug_id].decision.verdict != "confirmed":
            issue(f"roots/{root_id}/bug_ids", f"unknown or nonconfirmed member {bug_id}")
    if issues:
        raise ReviewIssues(issues)
