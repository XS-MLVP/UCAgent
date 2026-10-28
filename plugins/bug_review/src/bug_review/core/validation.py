"""Validate claim coverage and evidence without requiring optional waveforms."""

from pathlib import Path

from .records import STAGES


class ReviewIssues(ValueError):
    """Carry bounded task-oriented diagnostics for tools and stage gates."""

    def __init__(self, issues):
        """Keep exact failures and show only a bounded repair queue."""
        self.issues = issues
        super().__init__(f'{len(issues)} review issues')

    def result(self):
        """Describe the artifacts to fix without dumping complete records."""
        return {'error_code': 'REVIEW_INCOMPLETE', 'error': str(self), 'issues': self.issues[:20],
                'remaining': max(0, len(self.issues) - 20),
                'next_action': 'Read ReviewContext for the named item and submit the missing analysis or evidence'}


def references(layout, refs, field):
    """Check actual cited sources without rehashing immutable inputs."""
    issues = []
    for ref in refs:
        try:
            layout.source(ref, 1)
        except (ValueError, OSError) as error:
            issues.append({'field': field, 'reference': ref, 'error': str(error)})
    return issues


def case_issues(layout, case):
    """Require analysis of the selected execution or an explicit replay blocker."""
    a = case.analysis
    issues = []
    for field in ('scenario', 'actual', 'reasoning', 'test_validity', 'timing_review'):
        if not getattr(a, field).strip():
            issues.append({'case_id': case.case_id, 'field': field, 'error': 'explain this part of the test review'})
    if a.category == 'unreviewed':
        issues.append({'case_id': case.case_id, 'field': 'category', 'error': 'classify the reviewed evidence'})
    execution = next((item for item in case.executions if item.invocation_id == a.selected_execution), None)
    if execution is None and not a.replay_blocker:
        issues.append({'case_id': case.case_id, 'field': 'selected_execution', 'error': 'import a real execution or record replay_blocker'})
    if execution is not None and execution.provenance == 'historical' and not a.replay_blocker:
        issues.append({'case_id': case.case_id, 'field': 'replay_blocker', 'error': 'historical evidence is not a rerun; explain why rerun is blocked'})
    if a.category in {'dut', 'specification'} and (not a.spec_refs or not a.specification_expected):
        issues.append({'case_id': case.case_id, 'field': 'spec_refs', 'error': 'state and cite an independent applicable requirement'})
    if a.category == 'dut' and (not a.test_expected or not execution or execution.status != 'failed'):
        issues.append({'case_id': case.case_id, 'field': 'category', 'error': 'DUT attribution needs a real failed test and reviewed expectation'})
    if a.category == 'unresolved' and not (a.remaining_gap and a.next_action):
        issues.append({'case_id': case.case_id, 'field': 'remaining_gap', 'error': 'name the missing evidence and next action'})
    if not a.source_refs:
        issues.append({'case_id': case.case_id, 'field': 'source_refs', 'error': 'cite inspected test or execution lines'})
    issues.extend(references(layout, [*a.source_refs, *a.spec_refs, *a.rtl_refs, *a.failure_refs], case.case_id))
    if execution is not None and execution.status in {'failed', 'error'}:
        if not a.failure_refs:
            issues.append({'case_id': case.case_id, 'field': 'failure_refs',
                           'error': 'cite exact failure lines in the selected execution report or log',
                           'expected': [execution.report_ref, execution.log_ref]})
        if any(ref.rsplit(':', 1)[0] not in {execution.report_ref, execution.log_ref} for ref in a.failure_refs):
            issues.append({'case_id': case.case_id, 'field': 'failure_refs',
                           'error': 'failure excerpts must belong to selected_execution report/log'})
    if any(ref.rsplit(':', 1)[0] == 'inputs/review_standards/catalog.json' for ref in a.spec_refs):
        issues.append({'case_id': case.case_id, 'field': 'spec_refs',
                       'error': 'cite the applicable original standard clause; catalog.json only records provenance'})
    # A reported claim cannot serve as its own independent specification.
    original = {ref.rsplit(':', 1)[0] for claim in layout.review().claims for ref in claim.source_refs}
    if any(ref.rsplit(':', 1)[0] in original for ref in a.spec_refs):
        issues.append({'case_id': case.case_id, 'field': 'spec_refs', 'error': 'original Bug claims are not independent specifications'})
    return issues


def validate(layout, stage, waveinfo=None):
    """Check current and preceding artifacts, deriving progress from content only."""
    if stage not in STAGES:
        raise ValueError(f'unknown review stage: {stage}')
    review = layout.review()
    level = STAGES.index(stage)
    issues = []
    if not layout.inputs.is_dir() or not review.source_documents:
        issues.append({'field': 'inputs', 'error': 'original report input is missing'})
    keys = [case.case_key for case in review.cases.values()]
    if len(set(keys)) != len(keys) or any(node != case.case_id for node, case in review.cases.items()):
        issues.append({'field': 'cases', 'error': 'Case keys must be unique and dictionary keys must equal exact case_id'})
    if level >= 1:
        if review.context is None:
            issues.append({'field': 'context', 'error': 'submit module purpose and scope with SubmitReviewClaims'})
        else:
            issues.extend(references(layout, review.context.source_refs, 'context'))
        if not review.claims_submitted:
            issues.append({'field': 'claims', 'error': 'use SubmitReviewClaims, including an explicitly empty claim set'})
        expected = set(review.source_documents)
        seen = {item.path for item in review.source_reviews}
        if expected != seen:
            issues.append({'field': 'source_reviews', 'missing': sorted(expected - seen), 'extra': sorted(seen - expected)})
        for claim in review.claims:
            issues.extend(references(layout, claim.source_refs, claim.claim_id))
            if not claim.case_ids and not claim.missing_information:
                issues.append({'field': claim.claim_id, 'error': 'link exact Case IDs or explain missing association'})
    cases = review.cases
    if level >= 2:
        for case in cases.values():
            issues.extend(case_issues(layout, case))
    if level >= 3 and review.options.waveform_enabled:
        for case in cases.values():
            if not case.waveforms and not case.waveform_note:
                issues.append({'case_id': case.case_id, 'field': 'waveform_note',
                               'error': 'attach useful evidence or explain why this Case needs no waveform or is blocked'})
            if case.waveforms:
                from .evidence import waveform_issues
                issues.extend(waveform_issues(layout, case, waveinfo))
    if level >= 4:
        ids = {claim.claim_id for claim in review.claims}
        decisions = {item.claim_id: item for item in review.decisions}
        roots = {item.root_id: item for item in review.roots}
        if not review.decisions_submitted or set(decisions) != ids or len(decisions) != len(review.decisions):
            issues.append({'field': 'decisions', 'error': 'submit exactly one decision for every claim'})
        if len(roots) != len(review.roots):
            issues.append({'field': 'roots', 'error': 'duplicate root_id'})
        used_roots = set()
        for claim in review.claims:
            decision = decisions.get(claim.claim_id)
            if decision is None:
                continue
            narrative_refs = [ref for row in decision.narrative.comparisons for ref in row.source_refs]
            issues.extend(references(layout, [*decision.source_refs, *narrative_refs], claim.claim_id))
            if not set(decision.case_ids).issubset(claim.case_ids):
                issues.append({'field': claim.claim_id, 'error': 'decision uses cases outside this claim'})
            selected = [cases[node] for node in decision.case_ids if node in cases]
            if decision.verdict == 'confirmed':
                if not any(case.analysis.category == 'dut' and not case.analysis.remaining_gap for case in selected):
                    issues.append({'field': claim.claim_id, 'error': 'confirmation needs its own reviewed DUT failure without an unresolved validity gap'})
            elif decision.verdict == 'refuted':
                if not decision.source_refs or not any(case.analysis.category in {'test', 'environment', 'specification'} for case in selected):
                    issues.append({'field': claim.claim_id, 'error': 'refutation needs concrete sourced counterevidence, not just a passing rerun'})
            elif not (decision.remaining_gap and decision.next_action):
                issues.append({'field': claim.claim_id, 'error': 'inconclusive requires a concrete gap and next action'})
            if decision.root_id:
                if decision.verdict != 'confirmed' or decision.root_id not in roots:
                    issues.append({'field': claim.claim_id, 'error': 'only confirmed claims can refer to an existing root'})
                used_roots.add(decision.root_id)
        if used_roots != set(roots):
            issues.append({'field': 'roots', 'error': 'each root must be referenced by a confirmed claim'})
        for root in review.roots:
            issues.extend(references(layout, root.rtl_refs, root.root_id))
            if any(Path(ref.rsplit(':', 1)[0]).suffix.lower() not in {'.sv', '.v', '.vhd', '.vhdl', '.svh', '.vh'} for ref in root.rtl_refs):
                issues.append({'field': root.root_id, 'error': 'cite actual RTL source, not the original Bug analysis'})
            linked = {case_id for d in review.decisions if d.root_id == root.root_id for case_id in d.case_ids}
            receipts = {w.receipt_id for node in linked if node in cases for w in cases[node].waveforms}
            if root.basis == 'waveform_observation' and (not review.options.waveform_enabled or not root.receipt_ids or not set(root.receipt_ids).issubset(receipts)):
                issues.append({'field': root.root_id, 'error': 'observed cause needs its own linked waveform receipts'})
    if issues:
        raise ReviewIssues(issues)
    return {'stage': stage, 'claims': len(review.claims), 'cases': len(cases),
            'unresolved': sum(d.verdict == 'inconclusive' for d in review.decisions),
            'historical_only': sum(not any(e.provenance == 'rerun' for e in c.executions) for c in cases.values())}
