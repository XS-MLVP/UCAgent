"""Read-only, bounded Bug-group navigation derived from canonical Case evidence."""

from .validation import case_issues


def case_digest(case):
    """Expose execution identities and brief analysis without waveform or source payloads."""
    a = case.analysis
    selected = [e for e in case.executions if e.invocation_id == a.selected_execution]
    visible = list({e.invocation_id: e for e in [*selected, *case.executions[-2:]]}.values())
    executions = [{'invocation_id': e.invocation_id, 'status': e.status,
                   'provenance': e.provenance, 'report_ref': e.report_ref, 'log_ref': e.log_ref}
                  for e in visible]
    return {'case_id': case.case_id, 'case_key': case.case_key, 'category': a.category,
            'selected_execution': a.selected_execution, 'executions': executions,
            'execution_count': len(case.executions), 'reasoning': a.reasoning[:500],
            'reasoning_truncated': len(a.reasoning) > 500,
            'source_refs': a.source_refs[:8], 'spec_refs': a.spec_refs[:8],
            'rtl_refs': a.rtl_refs[:8], 'failure_refs': a.failure_refs[:8]}


def group_context(layout, review, claim_id, offset=0, limit=5, pending_only=True, issues=None):
    """Page one claim's Cases and reusable citations without assuming equal verdicts."""
    claim = next((c for c in review.claims if c.claim_id == claim_id), None)
    if claim_id and claim is None:
        raise ValueError(f'unknown claim_id: {claim_id}; use ReviewContext overview')
    linked = {node for c in review.claims for node in c.case_ids}
    nodes = list(dict.fromkeys(claim.case_ids)) if claim else [n for n in review.cases if n not in linked]
    missing = [node for node in nodes if node not in review.cases]
    members = [review.cases[node] for node in nodes if node in review.cases]
    if issues is None:
        issues = {case.case_id: case_issues(layout, case) for case in members}
    pending = [case for case in members if issues[case.case_id]]
    selected = pending if pending_only else members
    page = selected[offset:offset + limit]
    ready = [case for case in members if not issues[case.case_id]]
    return {'claim_id': claim_id or None,
            'claim': ({'title': claim.title, 'statement': claim.statement,
                       'source_refs': claim.source_refs, 'mapping_reason': claim.mapping_reason,
                       'missing_information': claim.missing_information} if claim else None),
            'case_progress': {'total': len(members), 'ready': len(ready), 'pending': len(pending)},
            'missing_case_ids': missing[:5], 'missing_case_count': len(missing),
            'cases': [{**case_digest(case), 'missing_fields': list(dict.fromkeys(
                issue.get('field', 'evidence') for issue in issues[case.case_id]))} for case in page],
            'reusable_evidence': [case_digest(case) for case in ready[:2]],
            'reuse_rule': 'Reuse cited sources only after checking applicability; each Case needs its own execution, failure citations and conclusion.',
            'next_offset': offset + limit if len(selected) > offset + limit else None}
