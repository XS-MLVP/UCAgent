"""Validate signed waveform evidence for reviewed DUT candidates."""

from ...core.validation import ReviewIssues, case_issues


def check(workflow, ctx):
    """Validate the dut evidence stage contract."""
    issues = []
    for case in ctx["cases"].values():
        issues.extend(case_issues(ctx["index"], case, workflow.waveinfo,
                                  require_wave=True))
    if issues:
        raise ReviewIssues(issues)
