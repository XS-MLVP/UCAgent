"""Validate LLM-authored claim ownership and activate one attribution revision."""

from __future__ import annotations

from pathlib import Path
import secrets

from pydantic import ValidationError

from .analysis_core.task_manifest import atomic_write_json
from .json_io import read_object
from .review_claims import report_claim_blocks
from .review_store import (AttributionDraft, ReconciliationRecord, load_record,
                           source_lines, within_output)
from .review_validation import ReviewIssues, case_issues
from .workflow import Workflow


def create_attribution_draft(output: Path) -> dict:
    """Create an empty attribution format without inferring concrete relationships."""
    load_record(output, "review_index.json", "index")
    target = output / "drafts/attribution.json"
    if target.exists():
        raise ValueError("drafts/attribution.json already exists; edit the current draft")
    atomic_write_json(target, AttributionDraft(
        bugs=[], reconciliation=ReconciliationRecord()).model_dump(mode="json", by_alias=True))
    return {"draft_path": str(target.relative_to(output.parent)),
            "next_action": "Read source reports and case evidence, then fill every Bug assignment"}


def claim_mapping_issues(source: Path, name: str, index, assignments) -> list[dict]:
    """Check exact block coverage and record consistency without judging semantics."""
    issues: list[dict] = []
    blocks = {block["ref"]: block for block in report_claim_blocks(source, name)}
    assigned = set()
    ids = [item.bug_id for item in assignments]
    if len(ids) != len(set(ids)) or set(ids) != set(index.bugs):
        issues.append({"field": "bugs", "expected": sorted(index.bugs), "actual": ids,
                       "missing": sorted(set(index.bugs) - set(ids)),
                       "extra": sorted(set(ids) - set(index.bugs)),
                       "next_action": "Fill exactly one assignment for every indexed Bug"})
    for item in assignments:
        for field in ("claim_refs", "bg_ids", "fg_ids", "fc_ids", "ck_ids", "case_ids",
                      "source_labels", "spec_candidates", "rtl_candidates"):
            values = getattr(item, field)
            if len(values) != len(set(values)) or any(not value.strip() for value in values):
                issues.append({"bug_id": item.bug_id, "field": field,
                               "next_action": "Remove duplicate or empty entries"})
        if not item.rationale.strip():
            issues.append({"bug_id": item.bug_id, "field": "rationale",
                           "next_action": "Explain the reviewed source and case ownership"})
        if item.claim_refs and not item.bg_ids:
            issues.append({"bug_id": item.bug_id, "field": "bg_ids",
                           "next_action": "Name the reviewed BG relationship for assigned source blocks"})
        unknown_cases = set(item.case_ids) - set(index.cases)
        if unknown_cases:
            issues.append({"bug_id": item.bug_id, "field": "case_ids",
                           "extra": sorted(unknown_cases), "next_action": "Use exact indexed case IDs"})
        labels = set()
        for ref in item.claim_refs:
            if ref not in blocks:
                issues.append({"bug_id": item.bug_id, "field": "claim_refs", "actual": ref,
                               "next_action": "Use an exact source ref from ReportClaimBlocks"})
                continue
            assigned.add(ref)
            labels.add(blocks[ref]["source_label"])
        if set(item.source_labels) != labels:
            issues.append({"bug_id": item.bug_id, "field": "source_labels",
                           "expected": sorted(labels), "actual": item.source_labels,
                           "next_action": "Preserve the original BG labels separately from reviewed BG IDs"})
        for field in ("spec_candidates", "rtl_candidates"):
            for ref in getattr(item, field):
                try:
                    source_lines(source, ref, 1)
                except (ValueError, OSError) as error:
                    issues.append({"bug_id": item.bug_id, "field": field, "actual": ref,
                                   "next_action": str(error)})
    missing = set(blocks) - assigned
    if missing:
        issues.append({"field": "claim_refs", "missing": sorted(missing)[:30],
                       "missing_count": len(missing),
                       "next_action": "Account for every original BG block"})
    return issues


def commit_attribution(workspace: Path, output: Path, draft_path: str, dry_run: bool,
                       waveinfo) -> dict:
    """Validate a complete attribution draft and switch its active index pointer."""
    relative = Path(draft_path)
    if relative.parts[:1] != (output.name,):
        raise ValueError("draft_path must be workspace-relative under {OUT}/drafts")
    draft = within_output(output, Path(*relative.parts[1:]).as_posix())
    if draft.relative_to(output).parts[:1] != ("drafts",):
        raise ValueError("draft_path must be under {OUT}/drafts")
    try:
        payload = AttributionDraft.model_validate(read_object(draft))
    except ValidationError as error:
        raise ReviewIssues([{"field": "/".join(map(str, item["loc"])),
                             "problem": item["msg"], "next_action": "Fill the attribution schema"}
                            for item in error.errors()]) from error
    index = load_record(output, "review_index.json", "index")
    if (index.stage_status.get("dut_evidence") != "complete"
            or index.stage_status.get("root_correlation") == "complete"):
        raise ValueError("CommitAttribution belongs between dut_evidence and root_correlation")
    source = Path(index.workspace["source_path"])
    issues = claim_mapping_issues(source, index.workspace["name"], index, payload.bugs)
    if issues:
        raise ReviewIssues(issues)
    assignments = {item.bug_id: item for item in payload.bugs}
    proposed = {bug_id: set(item.case_ids) for bug_id, item in assignments.items()}
    cases = {}
    for case_id, entry in index.cases.items():
        case = load_record(output, entry.record_path, "case")
        case.bug_ids = [bug_id for bug_id in index.bug_order if case_id in proposed[bug_id]]
        cases[case_id] = case
    reconciliation = payload.reconciliation.model_copy(deep=True)
    reconciliation.original_bug_ids = sorted(bug_id for bug_id, entry in index.bugs.items()
                                              if entry.origin == "reported")
    reconciliation.discovered_bug_ids = sorted(bug_id for bug_id, entry in index.bugs.items()
                                                if entry.origin == "discovered")
    reconciliation.unreported_failed_cases = sorted(
        case_id for case_id, case in cases.items()
        if case.replay.status in {"failed", "error", "xpassed"} and not case.bug_ids)
    passed = {case_id for bug_id in reconciliation.original_bug_ids for case_id in proposed[bug_id]
              if cases[case_id].replay.status == "passed"}
    previous = set(reconciliation.previously_failed_now_passed)
    if not previous.issubset(passed) or set(reconciliation.original_failure_refs) != previous:
        issues.append({"field": "previously_failed_now_passed", "expected": sorted(passed),
                       "actual": sorted(previous), "extra": sorted(previous - passed),
                       "next_action": "List only proven earlier failures now passing with source refs"})
    if not reconciliation.statistics_review.strip():
        issues.append({"field": "statistics_review", "next_action": "Explain report and replay counting scopes"})
    source_root = output / "inputs" / index.workspace["name"]
    for case_id, ref in reconciliation.original_failure_refs.items():
        try:
            source_lines(source_root, ref, 1)
        except (ValueError, OSError) as error:
            issues.append({"case_id": case_id, "field": "original_failure_refs",
                           "actual": ref, "next_action": str(error)})
    candidate = index.model_copy(deep=True)
    for bug_id, item in assignments.items():
        entry = candidate.bugs[bug_id]
        for field, value in (("analysis_refs", item.claim_refs), ("case_ids", item.case_ids),
                             ("bg_ids", item.bg_ids), ("fg_ids", item.fg_ids),
                             ("fc_ids", item.fc_ids), ("ck_ids", item.ck_ids),
                             ("source_labels", item.source_labels),
                             ("attribution_rationale", item.rationale),
                             ("spec_candidates", item.spec_candidates),
                             ("rtl_candidates", item.rtl_candidates)):
            setattr(entry, field, value)
        if entry.origin == "discovered" and not any(
                cases[case_id].failure_analysis.category in {"suspected_dut", "confirmed_dut"}
                for case_id in item.case_ids):
            issues.append({"bug_id": bug_id, "field": "case_ids",
                           "next_action": "Link an independently reviewed DUT candidate"})
    for case_id, case in cases.items():
        issues.extend(case_issues(candidate, case, waveinfo, source_root=source_root))
        if (case.replay.status in {"failed", "error", "xpassed"}
                and case.failure_analysis.category in {"suspected_dut", "confirmed_dut"}
                and case.waveform.receipt_id and not case.bug_ids):
            issues.append({"case_id": case_id, "field": "bug_ids",
                           "next_action": "Associate the independently evidenced DUT case"})
    if issues:
        raise ReviewIssues(issues)
    changed = {bug_id: {"removed": sorted(set(index.bugs[bug_id].case_ids) - proposed[bug_id]),
                        "kept": sorted(set(index.bugs[bug_id].case_ids) & proposed[bug_id]),
                        "added": sorted(proposed[bug_id] - set(index.bugs[bug_id].case_ids))}
               for bug_id in index.bug_order}
    if dry_run:
        return {"valid": True, "committed": False, "case_changes": changed,
                "claim_blocks": len(report_claim_blocks(source, index.workspace["name"])),
                "unreported_failed_cases": reconciliation.unreported_failed_cases}
    revision = f"attributions/rev-{secrets.token_hex(6)}"
    before = index.model_dump(mode="json", by_alias=True)
    atomic_write_json(output / revision / "previous_index.json", before)
    for position, (case_id, case) in enumerate(cases.items(), 1):
        record_path = f"{revision}/cases/case_{position:04d}.json"
        atomic_write_json(output / record_path, case.model_dump(mode="json", by_alias=True))
        candidate.cases[case_id].record_path = record_path
    candidate.reconciliation_path = f"{revision}/report_reconciliation.json"
    atomic_write_json(output / candidate.reconciliation_path,
                      reconciliation.model_dump(mode="json", by_alias=True))
    candidate.claim_mapping_path = f"{revision}/claim_mapping.json"
    atomic_write_json(output / candidate.claim_mapping_path,
                      payload.model_dump(mode="json", by_alias=True))
    candidate.attribution_revision = revision
    candidate.stage_status["report_reconcile"] = "complete"
    atomic_write_json(output / revision / "manifest.json", {
        "revision": revision, "previous_revision": index.attribution_revision,
        "case_changes": changed, "affected_cases": len(cases)})
    atomic_write_json(output / "review_index.json", candidate.model_dump(mode="json", by_alias=True))
    try:
        Workflow(workspace).check("report_reconcile")
    except Exception:
        atomic_write_json(output / "review_index.json", before)
        raise
    return {"committed": True, "revision": revision, "case_changes": changed,
            "updated_files": ["review_index.json", candidate.reconciliation_path,
                              candidate.claim_mapping_path,
                              *(entry.record_path for entry in candidate.cases.values())]}
