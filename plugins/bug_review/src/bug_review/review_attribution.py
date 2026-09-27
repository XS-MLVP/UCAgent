"""Stage and activate one complete Bug-to-case attribution revision."""

from __future__ import annotations

from pathlib import Path
import secrets

from .analysis_core.task_manifest import atomic_write_json
from .json_io import read_object
from .review_store import ReconciliationRecord, load_record, source_lines, within_output
from .review_validation import ReviewIssues, case_issues
from .workflow import Workflow, _inventory, _workspace_node


def create_attribution_draft(output: Path) -> dict:
    """Prefill one editable draft with BG links and parsed source candidates."""
    index = load_record(output, "review_index.json", "index")
    target = output / "drafts/attribution.json"
    if target.exists():
        raise ValueError("drafts/attribution.json already exists; edit the current draft")
    reconciliation = load_record(output, index.reconciliation_path, "reconciliation")
    original, _ = _inventory(Path(index.workspace["source_path"]), index.workspace["name"])
    reported = {item["bug_id"]: item for item in original["bugs"]}
    candidates = {}
    for bug_id, entry in index.bugs.items():
        item = reported.get(bug_id, {})
        candidates[bug_id] = {
            "spec_candidates": sorted(set(entry.spec_candidates) | set(item.get("spec_refs", []))),
            "rtl_candidates": sorted(set(entry.rtl_candidates) | set(item.get("rtl_refs", []))),
        }
    atomic_write_json(target, {
        "bug_case_ids": {bug_id: entry.case_ids for bug_id, entry in index.bugs.items()},
        "bug_candidates": candidates,
        "reconciliation": reconciliation.model_dump(mode="json", by_alias=True),
    })
    return {"draft_path": str(target.relative_to(output.parent)), "bug_count": len(index.bugs),
            "prefilled_spec_refs": sum(len(item["spec_candidates"]) for item in candidates.values()),
            "prefilled_rtl_refs": sum(len(item["rtl_candidates"]) for item in candidates.values())}


def commit_attribution(workspace: Path, output: Path, draft_path: str, dry_run: bool,
                       waveinfo) -> dict:
    """Validate a complete mapping, then switch only the active index pointer."""
    relative = Path(draft_path)
    if relative.parts[:1] != (output.name,):
        raise ValueError("draft_path must be workspace-relative under {OUT}/drafts")
    draft = within_output(output, Path(*relative.parts[1:]).as_posix())
    if draft.relative_to(output).parts[:1] != ("drafts",):
        raise ValueError("draft_path must be under {OUT}/drafts")
    payload = read_object(draft)
    if (set(payload) != {"bug_case_ids", "bug_candidates", "reconciliation"}
            or not isinstance(payload["bug_case_ids"], dict)
            or not isinstance(payload["bug_candidates"], dict)):
        raise ValueError("draft requires bug_case_ids, bug_candidates and reconciliation objects")
    index = load_record(output, "review_index.json", "index")
    if (index.stage_status.get("dut_evidence") != "complete"
            or index.stage_status.get("root_correlation") == "complete"):
        raise ValueError("CommitAttribution belongs between dut_evidence and root_correlation")
    proposed = payload["bug_case_ids"]
    candidate_inputs = payload["bug_candidates"]
    issues = []
    if set(proposed) != set(index.bugs):
        issues.append({"field": "bug_case_ids", "expected": sorted(index.bugs),
                       "actual": sorted(proposed), "missing": sorted(set(index.bugs) - set(proposed)),
                       "extra": sorted(set(proposed) - set(index.bugs)),
                       "next_action": "Include every indexed Bug ID exactly once"})
    if set(candidate_inputs) != set(index.bugs):
        issues.append({"field": "bug_candidates", "expected": sorted(index.bugs),
                       "actual": sorted(candidate_inputs),
                       "missing": sorted(set(index.bugs) - set(candidate_inputs)),
                       "extra": sorted(set(candidate_inputs) - set(index.bugs)),
                       "next_action": "Include candidates for every indexed Bug ID"})
    source = Path(index.workspace["source_path"])
    original, _ = _inventory(source, index.workspace["name"])
    original_by_id = {bug["bug_id"]: bug for bug in original["bugs"]}
    for bug_id, case_ids in proposed.items():
        if not isinstance(case_ids, list) or any(not isinstance(item, str) for item in case_ids):
            issues.append({"bug_id": bug_id, "field": "case_ids", "expected": "list of exact case IDs",
                           "actual": type(case_ids).__name__, "next_action": "Use indexed case IDs"})
            continue
        actual = set(case_ids)
        expected = {_workspace_node(node) for node in original_by_id.get(bug_id, {}).get("tests", [])}
        missing = expected - actual
        unknown = actual - set(index.cases)
        if len(actual) != len(case_ids) or missing or unknown:
            aggregate = {_workspace_node(node) for node in original_by_id.get(bug_id, {}).get("aggregate_tests", [])}
            issues.append({"bug_id": bug_id, "field": "case_ids", "expected": sorted(expected),
                           "actual": sorted(actual), "missing": sorted(missing),
                           "extra": sorted(unknown), "bg_required": sorted(expected),
                           "aggregate_only": sorted(aggregate - expected),
                           "draft_added": sorted(actual - expected),
                           "next_action": "Keep BG-level original cases and use only indexed case IDs"})
    for bug_id, fields in candidate_inputs.items():
        if (not isinstance(fields, dict) or set(fields) != {"spec_candidates", "rtl_candidates"}
                or any(not isinstance(fields.get(field), list)
                       or any(not isinstance(value, str) for value in fields[field])
                       or len(fields[field]) != len(set(fields[field]))
                       for field in ("spec_candidates", "rtl_candidates"))):
            issues.append({"bug_id": bug_id, "field": "bug_candidates",
                           "expected": "unique spec_candidates[] and rtl_candidates[] strings",
                           "actual": fields, "next_action": "Correct the candidate draft fields"})
    if issues:
        raise ReviewIssues(issues)
    proposed_sets = {bug_id: set(case_ids) for bug_id, case_ids in proposed.items()}
    cases = {}
    for case_id, entry in index.cases.items():
        case = load_record(output, entry.record_path, "case")
        case.bug_ids = [bug_id for bug_id in index.bug_order if case_id in proposed_sets[bug_id]]
        cases[case_id] = case
    reconciliation = ReconciliationRecord.model_validate(payload["reconciliation"])
    reconciliation.original_bug_ids = sorted(original_by_id)
    reconciliation.discovered_bug_ids = sorted(
        bug_id for bug_id, entry in index.bugs.items() if entry.origin == "discovered")
    reconciliation.unreported_failed_cases = sorted(
        case_id for case_id, case in cases.items()
        if case.replay.status in {"failed", "error", "xpassed"} and not case.bug_ids)
    reported_now_passed = {case_id for bug_id in original_by_id
                           for case_id in proposed_sets[bug_id]
                           if cases[case_id].replay.status == "passed"}
    previous_failures = set(reconciliation.previously_failed_now_passed)
    if (not previous_failures.issubset(reported_now_passed)
            or set(reconciliation.original_failure_refs) != previous_failures):
        issues.append({"field": "previously_failed_now_passed", "expected": sorted(reported_now_passed),
                       "actual": sorted(previous_failures),
                       "extra": sorted(previous_failures - reported_now_passed),
                       "next_action": "List only proven earlier failures now passing, with one original_failure_ref each"})
    if not reconciliation.statistics_review.strip():
        issues.append({"field": "statistics_review", "expected": "source/current comparison",
                       "actual": reconciliation.statistics_review,
                       "next_action": "Explain the report and replay counting scopes"})
    source_root = output / "inputs" / index.workspace["name"]
    for case_id, reference in reconciliation.original_failure_refs.items():
        try:
            source_lines(source_root, reference, 1)
        except (ValueError, OSError) as error:
            issues.append({"case_id": case_id, "field": "original_failure_refs",
                           "actual": reference, "expected": "existing source-relative path:line",
                           "next_action": str(error)})
    candidate = index.model_copy(deep=True)
    for bug_id, case_ids in proposed.items():
        candidate.bugs[bug_id].case_ids = case_ids
        for field in ("spec_candidates", "rtl_candidates"):
            setattr(candidate.bugs[bug_id], field, candidate_inputs[bug_id][field])
    for reported in original["bugs"]:
        bug_id = reported["bug_id"]
        entry = candidate.bugs[bug_id]
        for field, expected in (("spec_candidates", set(reported["spec_refs"])),
                                ("rtl_candidates", set(reported["rtl_refs"]))):
            actual = set(getattr(entry, field))
            if not expected.issubset(actual):
                issues.append({"bug_id": bug_id, "field": field,
                               "expected": sorted(expected), "actual": sorted(actual),
                               "missing": sorted(expected - actual), "extra": sorted(actual - expected),
                               "next_action": "Reconcile the original Spec/RTL candidates before committing"})
    for bug_id, entry in candidate.bugs.items():
        if entry.origin == "discovered" and not any(
                cases[case_id].failure_analysis.category in {"suspected_dut", "confirmed_dut"}
                for case_id in entry.case_ids):
            issues.append({"bug_id": bug_id, "field": "case_ids",
                           "expected": "at least one independently suspected DUT case",
                           "actual": entry.case_ids,
                           "next_action": "Link an independently reviewed DUT candidate"})
    for case_id, case in cases.items():
        issues.extend(case_issues(candidate, case, waveinfo,
                                  source_root=source_root))
        if (case.replay.status in {"failed", "error", "xpassed"}
                and case.failure_analysis.category in {"suspected_dut", "confirmed_dut"}
                and case.waveform.receipt_id and not case.bug_ids):
            issues.append({"case_id": case_id, "field": "bug_ids",
                           "expected": "a reported or discovered Bug association",
                           "actual": [], "next_action": "Associate the independently evidenced DUT case"})
    if issues:
        raise ReviewIssues(issues)
    changed = {bug_id: {"before": index.bugs[bug_id].case_ids, "after": case_ids}
               for bug_id, case_ids in proposed.items()
               if index.bugs[bug_id].case_ids != case_ids}
    changed_candidates = {bug_id: {field: {"before": getattr(index.bugs[bug_id], field),
                                           "after": candidate_inputs[bug_id][field]}
                                   for field in ("spec_candidates", "rtl_candidates")
                                   if getattr(index.bugs[bug_id], field) != candidate_inputs[bug_id][field]}
                          for bug_id in proposed}
    changed_candidates = {bug_id: fields for bug_id, fields in changed_candidates.items() if fields}
    if dry_run:
        return {"valid": True, "committed": False, "changed_bugs": changed,
                "changed_candidates": changed_candidates, "affected_cases": len(cases),
                "unreported_failed_cases": reconciliation.unreported_failed_cases}
    revision = f"attributions/rev-{secrets.token_hex(6)}"
    previous = index.model_dump(mode="json", by_alias=True)
    atomic_write_json(output / revision / "previous_index.json", previous)
    for position, (case_id, case) in enumerate(cases.items(), 1):
        record_path = f"{revision}/cases/case_{position:04d}.json"
        atomic_write_json(output / record_path, case.model_dump(mode="json", by_alias=True))
        candidate.cases[case_id].record_path = record_path
    candidate.reconciliation_path = f"{revision}/report_reconciliation.json"
    atomic_write_json(output / candidate.reconciliation_path,
                      reconciliation.model_dump(mode="json", by_alias=True))
    candidate.attribution_revision = revision
    candidate.stage_status["report_reconcile"] = "complete"
    atomic_write_json(output / revision / "manifest.json", {
        "revision": revision, "previous_revision": index.attribution_revision,
        "changed_bugs": changed, "changed_candidates": changed_candidates,
        "affected_cases": len(cases)})
    atomic_write_json(output / "review_index.json", candidate.model_dump(mode="json", by_alias=True))
    try:
        Workflow(workspace).check("report_reconcile")
    except Exception:
        atomic_write_json(output / "review_index.json", previous)
        raise
    return {"committed": True, "revision": revision, "changed_bugs": changed,
            "changed_candidates": changed_candidates,
            "updated_files": ["review_index.json", candidate.reconciliation_path,
                              *(entry.record_path for entry in candidate.cases.values())]}
