"""Validate the prepared source, replay manifest, and indexed case baseline."""
from pathlib import Path
from ...core.inventory import build_inventory
from ...core.json_io import read_object
from ...core.layout import unity_test_root, workspace_node
from ...core.records import load_record, source_lines, source_root as prepared_source_root, within_output
from ...core.validation import ReviewIssues, case_issues


def check(workflow, ctx):
    """Validate the complete replay baseline and cache its parsed records."""
    self = workflow
    source = ctx["source"]
    index = ctx["index"]
    if len(index.bug_order) != len(set(index.bug_order)) or set(index.bug_order) != set(index.bugs):
        raise ValueError("review_index.json bug_order and bugs identities differ")
    original, _ = build_inventory(source, self.label)
    expected_ids = {bug["bug_id"] for bug in original["bugs"]}
    if not expected_ids.issubset(index.bugs):
        raise ValueError(f"original Bug identities missing: {sorted(expected_ids - set(index.bugs))[:10]}")
    source_root = prepared_source_root(self.out)
    original_issues = []
    for reported in original["bugs"]:
        bug_id = reported["bug_id"]
        entry = index.bugs[bug_id]
        location = reported["source"]
        path = Path(location["path"])
        if path.is_absolute():
            path = path.resolve().relative_to(source)
        start = location.get("line", location.get("line_start"))
        end = location.get("line_end", start)
        summary_ref = f"{path.as_posix()}:{start}" + (f"-{end}" if end != start else "")
        expected_fields = {
            "origin": "reported", "summary_ref": summary_ref,
            "reported_confidence": reported["reported_confidence"],
            "check_points": set(reported["ck"]),
            "aggregate_case_ids": {workspace_node(node) for node in reported["aggregate_tests"]},
            "aggregate_refs": set(reported["aggregate_refs"]),
        }
        for field, expected in expected_fields.items():
            actual = getattr(entry, field)
            actual_set = set(actual) if isinstance(expected, set) else actual
            invalid = (not expected.issubset(actual_set) if field == "check_points"
                       else actual_set != expected)
            if invalid:
                original_issues.append({"bug_id": bug_id, "field": field,
                                        "expected": sorted(expected) if isinstance(expected, set) else expected,
                                        "actual": sorted(actual_set) if isinstance(expected, set) else actual,
                                        "missing": sorted(expected - actual_set) if isinstance(expected, set) else [],
                                        "extra": sorted(actual_set - expected) if isinstance(expected, set) else [],
                                        "next_action": "Restore the original summary fact; reviewed associations belong in the attribution draft"})
    if original_issues:
        raise ReviewIssues(original_issues)
    for bug_id, entry in index.bugs.items():
        if any(case_id not in index.cases for case_id in entry.case_ids):
            raise ValueError(f"{bug_id} refers to an unindexed case")
        for ref in [entry.summary_ref, *entry.analysis_refs]:
            if ref:
                source_lines(source_root, ref, 1)
    coverage = load_record(self.out, index.coverage_path, "coverage")
    if not {"line", "functional"}.issubset(coverage.metrics):
        raise ValueError("coverage.json needs line and functional metrics")
    for metric in coverage.metrics.values():
        if metric.status == "unavailable" and not metric.reason.strip():
            raise ValueError("unavailable coverage needs a reason")
        if metric.status == "available":
            if not metric.source_ref or not metric.basis or metric.run_scope == "unknown":
                raise ValueError("available coverage needs source_ref, basis and run_scope")
            source_lines(source_root, metric.source_ref, 1)
    manifest = load_record(self.out, index.manifest_path, "manifest")
    if not manifest.collected and not manifest.collection_errors:
        raise ValueError("test_manifest.json has no collected tests or collection error")
    if len(set(manifest.collected)) != len(manifest.collected):
        raise ValueError("test_manifest.json contains duplicate node IDs")
    if manifest.collection_exit_code != 0 and not manifest.collection_errors:
        raise ValueError("collection failure needs recorded diagnostics")
    if not set(manifest.collected).issubset(index.cases):
        raise ValueError("review_index.json omits collected test nodes")
    if len({entry.record_path for entry in index.cases.values()}) != len(index.cases):
        raise ValueError("multiple cases share one record path")
    summary = load_record(self.out, index.replay_summary_path, "replay_summary")
    if summary.baseline_id != manifest.baseline_id:
        raise ValueError("replay_summary.json baseline differs from test_manifest.json")
    if set(summary.outcomes) != set(manifest.collected):
        missing = sorted(set(manifest.collected) - set(summary.outcomes))[:10]
        extra = sorted(set(summary.outcomes) - set(manifest.collected))[:10]
        raise ValueError(f"replay_summary.json does not account for collected nodes: missing={missing}, extra={extra}")
    if manifest.collected and (not summary.commands or not summary.report_ref):
        raise ValueError("replay_summary.json needs baseline commands and saved report references")
    if summary.report_ref and not within_output(self.out, summary.report_ref).is_file():
        raise ValueError("replay_summary.json report_ref does not locate a saved report")
    from ...core.replay import report_outcomes
    observed = {}
    for position, reference in enumerate(summary.batch_refs):
        batch = read_object(within_output(self.out, reference))
        context = batch.get("context", {})
        if context.get("source") != "RunTestCases" or context.get("stage_name") != "full_replay":
            raise ValueError(f"{reference} is not a full_replay RunTestCases report")
        if position >= len(summary.commands) or summary.commands[position] != [
                "RunTestCases", str(context.get("pytest_ex_args", ""))]:
            raise ValueError(f"{reference} command differs from the saved RunTestCases context")
        for case_id, finding in report_outcomes(batch["report"], set(manifest.collected)).items():
            if case_id in observed:
                raise ValueError(f"{case_id} appears in more than one baseline batch")
            observed[case_id] = finding
    if manifest.collected and (not summary.batch_refs or summary.report_ref not in summary.batch_refs
                               or len(summary.commands) != len(summary.batch_refs)):
        raise ValueError("replay_summary.json needs saved baseline batch references")
    cases = {}
    issues = []
    for case_id, entry in index.cases.items():
        case = load_record(self.out, entry.record_path, "case")
        if case.case_id != case_id or set(case.bug_ids) != {
                bug_id for bug_id, bug in index.bugs.items() if case_id in bug.case_ids}:
            raise ValueError(f"{case_id} case identity or Bug links differ from index")
        cases[case_id] = case
        target = (unity_test_root(self.root) / entry.replay_target.split("::", 1)[0]).resolve()
        if not target.is_relative_to(unity_test_root(self.root).resolve()):
            raise ValueError(f"{case_id} replay_target escapes the prepared test root")
        if case_id in manifest.collected and not target.is_file():
            raise ValueError(f"{case_id} collected replay_target file is missing")
        if case_id not in manifest.collected and not case.replay.not_run_reason.strip():
            raise ValueError(f"{case_id} is report-only and needs a not_run reason")
        if case_id in manifest.collected:
            if case.replay.status != summary.outcomes[case_id]:
                raise ValueError(f"{case_id} replay status differs from baseline summary")
            finding = observed.get(case_id)
            if case.replay.status != "not_run" and (finding is None or finding[0] != case.replay.status):
                raise ValueError(f"{case_id} replay status has no matching RunTestCases report outcome")
            if case.replay.status == "not_run" and finding is not None:
                raise ValueError(f"{case_id} was reported by RunTestCases but marked not_run")
            if case.replay.status != "not_run" and case.replay.baseline_id != manifest.baseline_id:
                raise ValueError(f"{case_id} replay baseline_id differs from manifest")
            if finding and finding[1] and entry.waveform_test_case_name != finding[1]:
                raise ValueError(f"{case_id} waveform identity differs from saved report")
        elif case.replay.status != "not_run":
            raise ValueError(f"{case_id} was absent from collection but marked executed")
        issues.extend(case_issues(index, case, self.waveinfo,
                                  require_replay=case_id in manifest.collected,
                                  source_root=source_root))
    if issues:
        raise ReviewIssues(issues)
    ctx.update(expected_ids=expected_ids, manifest=manifest, summary=summary, cases=cases)
