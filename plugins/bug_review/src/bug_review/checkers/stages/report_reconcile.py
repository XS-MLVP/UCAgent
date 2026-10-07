"""Validate committed claim mapping and reconciliation."""
from ...core.attribution import claim_mapping_issues
from ...core.json_io import read_object
from ...core.records import AttributionDraft, load_record, source_lines, within_output
from ...core.validation import ReviewIssues

def check(workflow, ctx):
    """Validate the report reconcile stage contract."""
    self = workflow
    index = ctx["index"]
    source = ctx["source"]
    source_root = ctx["source_root"]
    expected_ids = ctx["expected_ids"]
    manifest = ctx["manifest"]
    cases = ctx["cases"]
    if not index.claim_mapping_path:
        raise ReviewIssues([{
            "error_code": "BUG_REVIEW_ATTRIBUTION_NOT_COMMITTED",
            "field": "claim_mapping_path",
            "artifact": "analysis/review_index.json",
            "observed": {"claim_mapping_path": None,
                          "draft_exists": (self.out / "drafts/attribution.json").is_file()},
            "expected": {"claim_mapping_path": "attributions/<revision>/claim_mapping.json"},
            "next_action": (
                "Call CommitAttribution(draft_path='analysis/drafts/attribution.json', "
                "dry_run=true), fix every returned issue, then call it again with "
                "dry_run=false. Only run Check after claim_mapping_path is written.")
        }])
    mapping = AttributionDraft.model_validate(read_object(within_output(self.out, index.claim_mapping_path)))
    mapping_issues = claim_mapping_issues(source, index.workspace["name"], index, mapping.bugs)
    for item in mapping.bugs:
        if item.bug_id not in index.bugs:
            continue
        entry = index.bugs[item.bug_id]
        for field, expected in (("analysis_refs", item.claim_refs), ("case_ids", item.case_ids),
                                ("bg_ids", item.bg_ids), ("fg_ids", item.fg_ids),
                                ("fc_ids", item.fc_ids), ("ck_ids", item.ck_ids),
                                ("source_labels", item.source_labels),
                                ("attribution_rationale", item.rationale),
                                ("spec_candidates", item.spec_candidates),
                                ("rtl_candidates", item.rtl_candidates)):
            if getattr(entry, field) != expected:
                mapping_issues.append({"bug_id": item.bug_id, "field": field,
                                       "expected": expected, "actual": getattr(entry, field),
                                       "next_action": "Restore the committed claim mapping"})
    if mapping_issues:
        raise ReviewIssues(mapping_issues)
    reconcile = load_record(self.out, index.reconciliation_path, "reconciliation")
    if set(reconcile.original_bug_ids) != expected_ids:
        raise ValueError("report_reconciliation.json does not list all original Bugs")
    discovered = {bug_id for bug_id, entry in index.bugs.items() if entry.origin == "discovered"}
    if set(reconcile.discovered_bug_ids) != discovered:
        raise ValueError("report_reconciliation.json discovered Bugs differ from index")
    uncovered = {case_id for case_id in manifest.collected
                 if cases[case_id].replay.status in {"failed", "error", "xpassed"}
                 and not cases[case_id].bug_ids}
    if set(reconcile.unreported_failed_cases) != uncovered:
        raise ValueError("report_reconciliation.json must list all failures without a Bug association")
    reported_now_passed = {case_id for bug_id in expected_ids
                           for case_id in index.bugs[bug_id].case_ids
                           if case_id in cases and cases[case_id].replay.status == "passed"}
    previous_failures = set(reconcile.previously_failed_now_passed)
    if (not previous_failures.issubset(reported_now_passed)
            or set(reconcile.original_failure_refs) != previous_failures):
        raise ValueError("previously_failed_now_passed needs a prior failure ref for each currently passing case")
    for reference in reconcile.original_failure_refs.values():
        source_lines(source_root, reference, 1)
    if not reconcile.statistics_review.strip():
        raise ValueError("report_reconciliation.json needs the source/current statistics comparison")
    for bug_id in discovered:
        if not any(cases[case_id].failure_analysis.category in {"suspected_dut", "confirmed_dut"}
                   for case_id in index.bugs[bug_id].case_ids):
            raise ValueError(f"{bug_id} discovered Bug has no independently suspected DUT case")
    for case_id in manifest.collected:
        case = cases[case_id]
        if (case.replay.status in {"failed", "error", "xpassed"}
                and case.failure_analysis.category in {"suspected_dut", "confirmed_dut"}
                and case.waveform.receipt_id and not case.bug_ids):
            raise ValueError(f"{case_id} has DUT evidence but no reported or discovered Bug")
