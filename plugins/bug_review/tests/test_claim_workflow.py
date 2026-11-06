"""Exercise arbitrary original report formats and independent no-wave decisions."""

import json
from pathlib import Path
import pytest
from bug_review.core.validation import validate, ReviewIssues
from bug_review.tools import (SubmitReviewClaims, UpdateCaseAnalysis, SubmitReviewDecisions,
                              RenderBugReviewReport, ReviewContext, ReviewWorkQueue, ReviewRefCheck)
from conftest import NODE, claim_payload, analysis_payload, decisions_payload, import_execution, context_payload, narrative_payload


def tool(cls, layout):
    """Bind the current output path for public tool tests."""
    return cls(workspace=str(layout.workspace), output_dir='results')


def test_no_wave_no_skill_complete_end_to_end(analyzed):
    """Every required stage and publication completes without any waveform dependency."""
    assert not (analyzed.workspace / '.ucagent/skills').exists()
    for stage in ('input_inventory', 'claim_inventory', 'targeted_review', 'waveform_review'):
        assert validate(analyzed, stage)['cases'] == 1
    result = tool(SubmitReviewDecisions, analyzed)._run(**decisions_payload())
    assert result['success'], result
    assert tool(RenderBugReviewReport, analyzed)._run()['success']
    assert tool(RenderBugReviewReport, analyzed)._run(verify_only=True)['success']
    assert not (analyzed.report / 'assets/surfer').exists()
    assert '<iframe' not in (analyzed.report / 'index.html').read_text()
    assert set(p.name for p in analyzed.out.iterdir()) == {'inputs', 'review.json', 'runs', 'report'}
    assert 'stage_status' not in analyzed.review().model_dump()
    assert not list(analyzed.out.rglob('*draft*'))


def test_claims_merge_multiple_source_occurrences(prepared):
    """A repeated statement can keep multiple source locations under one identity."""
    payload = claim_payload()
    payload['claims'][0]['source_refs'] = ['inputs/issues.md:2', 'inputs/issues.md:4']
    payload['claims'][0]['source_labels'] = ['different-heading', 'same-BG']
    result = tool(SubmitReviewClaims, prepared)._run(**payload)
    assert result['success'] and result['claims'] == 1
    assert len(prepared.review().claims[0].source_refs) == 2


@pytest.mark.parametrize('fault', ['duplicate', 'bad_ref', 'unaccounted', 'missing_case', 'extra_field', 'empty_parse'])
def test_invalid_claims_do_not_create_records(prepared, fault):
    """Malformed input or missing source coverage cannot masquerade as no Bugs."""
    payload = claim_payload()
    if fault == 'duplicate': payload['claims'] *= 2
    elif fault == 'bad_ref': payload['claims'][0]['source_refs'] = ['inputs/issues.md:999']
    elif fault == 'unaccounted': payload['source_reviews'] = []
    elif fault == 'missing_case': payload['claims'][0]['case_ids'] = ['tests/missing.py::test_bad']
    elif fault == 'extra_field': payload['claims'][0]['verdict'] = 'confirmed'
    else: payload['claims'] = []
    original = (prepared.out / 'review.json').read_bytes()
    assert not tool(SubmitReviewClaims, prepared)._run(**payload)['success']
    assert (prepared.out / 'review.json').read_bytes() == original


def test_explicit_no_claim_input_can_publish(prepared):
    """No reported Bugs needs source accounting but no fabricated tests or roots."""
    result = tool(SubmitReviewClaims, prepared)._run(context=context_payload(), claims=[], source_reviews=[{
        'path': 'inputs/issues.md', 'disposition': 'no_claims', 'reason': 'Reviewer found no actionable Bug statements.'}])
    assert result['success']
    assert tool(SubmitReviewDecisions, prepared)._run(decisions=[], roots=[])['success']
    assert tool(RenderBugReviewReport, prepared)._run()['success']


def test_unlinked_statement_remains_unresolved(prepared):
    """Retain a statement whose associated test cannot be identified."""
    payload = claim_payload()
    payload['claims'][0].update(case_ids=[], missing_information='No exact test is named.')
    assert tool(SubmitReviewClaims, prepared)._run(**payload)['success']
    decision = {'claim_id': 'B001', 'verdict': 'inconclusive', 'reasoning': 'Only the original statement is available.',
                'narrative': narrative_payload(), 'remaining_gap': 'No test association.', 'next_action': 'Provide the reproducing test.'}
    assert tool(SubmitReviewDecisions, prepared)._run(decisions=[decision], roots=[])['success']
    assert tool(RenderBugReviewReport, prepared)._run()['manifest']['review_status'] == 'incomplete'


def test_confirmed_does_not_require_located_root(analyzed):
    """Root uncertainty is independent of observed functional failure."""
    assert tool(SubmitReviewDecisions, analyzed)._run(**decisions_payload())['success']
    assert analyzed.review().decisions[0].root_id is None


@pytest.mark.parametrize('fault', ['passing_only', 'claim_as_spec', 'no_real_run', 'unknown_execution', 'missing_gap'])
def test_evidence_boundaries(linked, fault):
    """No-wave review still rejects false confirmation and self-supporting claims."""
    import_execution(linked, status='passed' if fault == 'passing_only' else 'failed')
    a = analysis_payload()
    if fault == 'claim_as_spec': a['spec_refs'] = ['inputs/issues.md:4']
    elif fault == 'no_real_run': a.update(selected_execution='', replay_blocker='Runtime missing.')
    elif fault == 'unknown_execution': a['selected_execution'] = 'b' * 32
    elif fault == 'missing_gap': a.update(category='unresolved', remaining_gap='', next_action='')
    updated = tool(UpdateCaseAnalysis, linked)._run(cases=[{'case_id': NODE, 'analysis': a}])
    if fault == 'unknown_execution':
        assert not updated['success']
    else:
        assert updated['success']
        assert not tool(SubmitReviewDecisions, linked)._run(**decisions_payload())['success']


def test_passing_rerun_alone_cannot_refute(analyzed):
    """Final verdict must explain concrete counterevidence rather than a pass count."""
    assert not tool(SubmitReviewDecisions, analyzed)._run(**decisions_payload('refuted'))['success']


def test_shared_static_root_is_defined_once(analyzed):
    """Roots cite actual RTL and do not duplicate shared text into decisions."""
    payload = decisions_payload()
    payload['decisions'][0]['root_id'] = 'R001'
    payload['roots'] = [{'root_id': 'R001', 'title': 'Constant output', 'explanation': 'RTL drives one.',
                         'rtl_refs': ['demo.sv:2'], 'basis': 'static_inference',
                         'alternatives': 'Test expectation matches the independent requirement.'}]
    assert tool(SubmitReviewDecisions, analyzed)._run(**payload)['success']
    assert tool(RenderBugReviewReport, analyzed)._run()['success']
    assert (analyzed.report / 'R001.html').exists()
    payload['roots'][0]['basis'] = 'waveform_observation'
    assert not tool(SubmitReviewDecisions, analyzed)._run(**payload)['success']


def test_direct_updates_preserve_machine_evidence_and_bound_output(analyzed):
    """No draft hashes are needed; analysis writes cannot change executions."""
    before = analyzed.case(NODE).executions
    a = analysis_payload(); a['reasoning'] = 'Updated interpretation.'
    result = tool(UpdateCaseAnalysis, analyzed)._run(cases=[{'case_id': NODE, 'analysis': a}])
    assert result['success'] and result['stage_completion_checked'] is False
    assert analyzed.case(NODE).executions == before
    bad = {'case_id': NODE, 'analysis': a, 'executions': []}
    assert not tool(UpdateCaseAnalysis, analyzed)._run(cases=[bad])['success']
    assert tool(ReviewContext, analyzed)._run(case_id=NODE)['case_id'] == NODE
    assert tool(ReviewWorkQueue, analyzed)._run(stage='targeted_review')['success']
    assert tool(ReviewRefCheck, analyzed)._run(refs=['spec.md:4'])['success']


def test_report_escapes_content_and_detects_stale_records(analyzed):
    """Generated HTML escapes reviewer text and verification catches stale output."""
    payload = decisions_payload(); payload['decisions'][0]['reasoning'] = '<script>alert(1)</script>'
    assert tool(SubmitReviewDecisions, analyzed)._run(**payload)['success']
    assert tool(RenderBugReviewReport, analyzed)._run()['success']
    html = (analyzed.report / 'B001.html').read_text()
    assert '&lt;script&gt;' in html and '<script>alert' not in html
    (analyzed.report / 'C0001.html').write_text('stale')
    assert not tool(RenderBugReviewReport, analyzed)._run(verify_only=True)['success']
