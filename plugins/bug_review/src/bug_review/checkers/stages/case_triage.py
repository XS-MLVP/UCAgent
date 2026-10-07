"""Validate independent case analysis and environment findings."""
from ...core.records import load_record, source_lines
from ...core.validation import ReviewIssues, case_issues

def check(workflow, ctx):
    """Validate the case triage stage contract."""
    self = workflow
    index = ctx["index"]
    source_root = ctx["source_root"]
    cases = ctx["cases"]
    environment = load_record(self.out, index.environment_path, "environment")
    if any(not getattr(environment, field).strip() for field in (
            "collection_review", "execution_review", "fixture_reset_review",
            "driver_sampling_review", "reference_model_review",
            "seed_reproducibility_review")):
        raise ValueError("environment_review.json needs all six quality reviews or explicit gaps")
    for position, finding in enumerate(environment.findings):
        if not finding.observation.strip() or not finding.impact.strip():
            raise ValueError(f"environment finding {position} needs observation and impact")
        if any(case_id not in index.cases for case_id in finding.case_ids):
            raise ValueError(f"environment finding {position} refers to an unindexed case")
        if finding.source_ref:
            source_lines(source_root, finding.source_ref, 1)
    issues = []
    for case in cases.values():
        issues.extend(case_issues(index, case, self.waveinfo,
                                  require_triage=True, source_root=source_root))
    if issues:
        raise ReviewIssues(issues)
