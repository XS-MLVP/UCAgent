"""Unresolved failures require an actual investigation, including abort boundaries."""
from types import SimpleNamespace

from bug_review.core.validation import case_issues
from bug_review.core.records import ScenarioStep
from test_root_reports import example


def test_archived_exploratory_wave_does_not_block_primary_analysis(tmp_path):
    """A replaced window can be incomplete without blocking the new primary evidence."""
    _, index, cases, _, _, _, waveinfo = example(tmp_path)
    case = next(iter(cases.values()))
    old = case.additional_waveforms[0]
    old.conclusion = 'inconclusive'
    old.observed_behavior = old.alignment_evidence = old.source_correlation = ''
    assert not case_issues(index, case, waveinfo, require_wave=True)
    old.analysis_window = {}
    issues = case_issues(index, case, waveinfo)
    assert any(i['field'] == 'additional_waveforms.0.analysis_window' for i in issues)


def test_inconclusive_receipt_requires_analysis_but_not_future_execution(tmp_path):
    _, index, cases, _, _, _, waveinfo = example(tmp_path)
    case = next(iter(cases.values()))
    case.additional_waveforms = []
    case.events = case.events[:1]
    case.failure_analysis.category = 'insufficient_evidence'
    case.waveform.conclusion = 'inconclusive'
    case.waveform.observed_behavior = ''
    assert any(i['field'] == 'waveform' for i in case_issues(index, case, waveinfo, require_wave=True))
    case.waveform.observed_behavior = 'The first response mismatches; the next transaction was not executed'
    case.scenario_steps[0].status = 'failed'
    case.scenario_steps.append(ScenarioStep(step_id='later', execution_id=case.replay.invocation_id,
        action='Second transaction after the failing assertion', status='not_reached',
        source_refs=['unity_test/tests/test_demo.py:1-2']))
    assert not case_issues(index, case, waveinfo, require_wave=True)


def test_diagnostic_must_be_signed_exact_failed_attempt_and_recovery_recorded(tmp_path):
    _, index, cases, _, _, _, _ = example(tmp_path)
    case = next(iter(cases.values()))
    case.additional_waveforms = []
    case.events = []
    case.failure_analysis.category = 'insufficient_evidence'
    case.waveform = type(case.waveform)(diagnostic='Empty dump; check Finish and replay',
                                       diagnostic_receipt_id='diagnostic')
    receipt = {'arguments': {'test_case_name': case.case_id}, 'result': {'status': 'empty_waveform'}}
    info = SimpleNamespace(get_analysis_receipt=lambda _: receipt,
                           analyze=lambda **_: {"status": "empty_waveform"})
    case.replay.reruns = []
    assert any(i['field'] == 'replay.reruns' for i in case_issues(index, case, info, require_wave=True))
    case.replay.reruns = [{'invocation_id': 'recovery-1'}]
    assert not case_issues(index, case, info, require_wave=True)
    info.analyze = lambda **_: {'status': 'metadata_only'}
    assert any(i['field'] == 'waveform.diagnostic_receipt_id' for i in case_issues(index, case, info, require_wave=True))
    info.analyze = lambda **_: {'status': 'empty_waveform'}
    for status in ['metadata_only', 'invalid_arguments', 'signal_not_found']:
        receipt['result']['status'] = status
        assert any(i['field'] == 'waveform' for i in case_issues(index, case, info, require_wave=True))
    receipt['result']['status'] = 'empty_waveform'
    receipt['arguments']['test_case_name'] = 'another_case'
    assert any(i['field'] == 'waveform' for i in case_issues(index, case, info, require_wave=True))
    info.get_analysis_receipt = lambda _: None
    assert any(i['field'] == 'waveform' for i in case_issues(index, case, info, require_wave=True))


def test_parseable_case_needs_measured_event_but_incremental_edit_is_valid(tmp_path):
    """Saving narrative is allowed; stage completion still requires a real observation."""
    _, index, cases, _, _, _, waveinfo = example(tmp_path)
    case = next(iter(cases.values()))
    case.events = []
    assert not case_issues(index, case, waveinfo)
    assert any(i['field'] == 'events' for i in case_issues(index, case, waveinfo, require_wave=True))


def test_unknown_decision_requires_actual_inquiry_without_forcing_confirmation(tmp_path):
    """An unresolved causal explanation must point to this claim's measured boundary."""
    from bug_review.core.records import DecisionInvestigation
    from bug_review.core.validation import decision_investigation_issues
    _, _, cases, bugs, _, _, _ = example(tmp_path)
    bug = next(iter(bugs.values()))
    bug.decision.verdict = 'inconclusive'
    bug.decision.root_id = bug.decision.review_confidence = None
    assert decision_investigation_issues(bug, cases, tmp_path)
    bug.decision.investigation = DecisionInvestigation(
        question='Was the current message captured at the accepted request?',
        source_refs=['spec.md:1', 'rtl.v:1'], evidence_ids=['e-0'],
        findings='The response carries an old tag at valid/ready; the upstream update is not observed.',
        blocker='causality_unresolved', remaining_gap='The input update boundary is not in this window.',
        next_action='Inspect input request acceptance and the message register update in the same invocation.')
    assert not decision_investigation_issues(bug, cases, tmp_path)
    bug.decision.investigation.evidence_ids = ['e-1']
    assert decision_investigation_issues(bug, cases, tmp_path)
    bug.decision.investigation.evidence_ids = []
    assert decision_investigation_issues(bug, cases, tmp_path)
    bug.decision.investigation.blocker = 'evidence_unavailable'
    assert decision_investigation_issues(bug, cases, tmp_path)
    bug.decision.investigation.blocker = 'claim_not_reproduced'
    assert decision_investigation_issues(bug, cases, tmp_path)
    bug.decision.investigation.blocker = 'specification_missing'
    assert not decision_investigation_issues(bug, cases, tmp_path)
    bug.decision.investigation.source_refs = ['absent.md:1']
    assert decision_investigation_issues(bug, cases, tmp_path)
