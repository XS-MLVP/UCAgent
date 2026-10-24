"""Structured case edits preserve evidence and catch incomplete triage early."""
import hashlib
import json
import pytest
from bug_review.tools import CreateCaseDraft, UpdateCaseRecords
from bug_review.tools.drafts import PatchCaseDraft
from bug_review.tools.investigation import ReviewWorkQueue
from test_failure_evidence import _prepare_batch_output, _reviewed_record


def test_structured_batch_preserves_machine_fields_and_submits(tmp_path):
    """Five independent cases need one structured patch without line-based edits."""
    ids = [f'tests/test_demo.py::test_{i}' for i in range(5)]
    output, entries = _prepare_batch_output(tmp_path, ids)
    options = dict(workspace=str(tmp_path), output_dir='verification_review/analysis')
    draft = CreateCaseDraft(**options)._run(ids)
    original = json.loads((tmp_path / draft['draft_path']).read_text())
    patches = [{'case_id': key, 'fields': {'failure_analysis': _reviewed_record(key).failure_analysis.model_dump()}} for key in ids]
    result = PatchCaseDraft(**options).invoke(dict(draft_path=draft['draft_path'], expected_sha256=draft['draft_sha256'], patches=patches))
    assert result['success'], result
    saved = json.loads((tmp_path / draft['draft_path']).read_text())
    assert saved['base_sha256'] == original['base_sha256']
    for key in ids:
        for field in ('replay', 'waveform', 'events', 'bug_ids', 'case_id'):
            assert saved['cases'][key][field] == original['cases'][key][field]
        assert json.loads((output / entries[key].record_path).read_text()) == original['cases'][key]
    assert UpdateCaseRecords(**options)._run(draft['draft_path'])['success']
    assert ReviewWorkQueue(**options)._run(stage='case_triage')['remaining_count'] == 0
    from ucagent.tools.uctool import to_fastmcp
    converted = to_fastmcp(PatchCaseDraft(**options))
    assert converted.name == 'PatchCaseDraft'
    assert PatchCaseDraft(**options).args_schema.model_json_schema()['properties']['patches']


@pytest.mark.parametrize('fault', ['stale', 'protected', 'unknown', 'overlap', 'wrong_case', 'duplicate', 'invalid_type', 'escape', 'missing_base'])
def test_invalid_patch_never_changes_draft_or_records(tmp_path, fault):
    """Reject malformed, stale and evidence-altering patches before any write."""
    key = 'tests/test_demo.py::test_bad'
    output, entries = _prepare_batch_output(tmp_path, [key])
    options = dict(workspace=str(tmp_path), output_dir='verification_review/analysis')
    created = CreateCaseDraft(**options)._run([key]); path = tmp_path / created['draft_path']
    args = dict(draft_path=created['draft_path'], expected_sha256=created['draft_sha256'], patches=[{'case_id': key, 'fields': {'failure_analysis.unresolved': 'Need input handshake evidence'}}])
    if fault == 'stale': args['expected_sha256'] = '0' * 64
    elif fault == 'protected': args['patches'][0]['fields'] = {'replay.status': 'passed'}
    elif fault == 'unknown': args['patches'][0]['fields'] = {'failure_analysis.fake': 'x'}
    elif fault == 'overlap': args['patches'][0]['fields']['failure_analysis'] = {}
    elif fault == 'wrong_case': args['patches'][0]['case_id'] = 'unknown'
    elif fault == 'duplicate': args['patches'] *= 2
    elif fault == 'invalid_type': args['patches'][0]['fields'] = {'failure_analysis.rationale': 'plain string'}
    elif fault == 'escape': args['draft_path'] = 'verification_review/analysis/drafts/../../outside.json'
    elif fault == 'missing_base':
        payload = json.loads(path.read_text());payload.pop('base_sha256');path.write_text(json.dumps(payload))
        args['expected_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    before = path.read_bytes(); official = (output / entries[key].record_path).read_bytes()
    result = PatchCaseDraft(**options)._run(**args)
    assert not result['success'], result
    assert path.read_bytes() == before
    assert (output / entries[key].record_path).read_bytes() == official


def test_batch_reports_missing_triage_before_writing(tmp_path):
    """A valid schema with missing attribution fails at batch submission."""
    key = 'tests/test_demo.py::test_bad'
    output, entries = _prepare_batch_output(tmp_path, [key])
    options = dict(workspace=str(tmp_path), output_dir='verification_review/analysis')
    draft = CreateCaseDraft(**options)._run([key]);before = (output / entries[key].record_path).read_bytes()
    result = UpdateCaseRecords(**options)._run(draft['draft_path'])
    assert not result['success'] and 'failure_analysis' in json.dumps(result)
    assert (output / entries[key].record_path).read_bytes() == before


def test_triage_queue_does_not_repeat_waveform_work(tmp_path):
    """A reviewed DUT candidate is done for triage and pending for evidence."""
    key = 'tests/test_demo.py::test_bad'
    output, entries = _prepare_batch_output(tmp_path, [key])
    case = _reviewed_record(key)
    case.failure_analysis.category = 'suspected_dut'
    case.test_review.correctness_confirmed = True
    case.failure_analysis.rationale.remaining_gap = 'Need request acceptance waveform'
    (output / entries[key].record_path).write_text(json.dumps(case.model_dump(mode='json', by_alias=True)))
    queue = ReviewWorkQueue(workspace=str(tmp_path), output_dir='verification_review/analysis')
    assert queue._run(stage='case_triage')['remaining_count'] == 0
    result = queue._run(stage='dut_evidence')
    assert result['remaining_count'] == 1
    assert result['items'][0]['gaps'][0]['field'] == 'waveform'
    assert not queue._run(stage='invalid')['success']


def test_batch_returns_all_triage_gaps_in_one_response(tmp_path):
    """A batch must not require a separate submit/retry to discover each invalid case."""
    ids = [f'tests/test_demo.py::test_{i}' for i in range(5)]
    output, entries = _prepare_batch_output(tmp_path, ids)
    options = dict(workspace=str(tmp_path), output_dir='verification_review/analysis')
    draft = CreateCaseDraft(**options)._run(ids)
    result = UpdateCaseRecords(**options)._run(draft['draft_path'])
    assert not result['success']
    assert {issue['case_id'] for issue in result['issues']} == set(ids)
    assert all(json.loads((output / entry.record_path).read_text())['failure_analysis']['category'] == 'unreviewed' for entry in entries.values())


def test_waveform_analysis_is_editable_but_signed_fields_remain_protected(tmp_path):
    key = 'tests/test_demo.py::test_bad'
    _prepare_batch_output(tmp_path, [key])
    options = dict(workspace=str(tmp_path), output_dir='verification_review/analysis')
    draft = CreateCaseDraft(**options)._run([key])
    patch = PatchCaseDraft(**options)
    result = patch._run(draft['draft_path'], draft['draft_sha256'], [{
        'case_id': key, 'fields': {'waveform.observed_behavior': 'Failure occurs before Q write',
                                 'waveform.alignment_evidence': 'response valid at sample',
                                 'waveform.source_correlation': 'test.py:26 assertion stops execution'}}])
    assert result['success']
    for field in ['waveform', 'waveform.receipt_id', 'waveform.analysis_window',
                  'waveform.signal_groups', 'waveform.viewer_url']:
        rejected = patch._run(draft['draft_path'], result['draft_sha256'], [{
            'case_id': key, 'fields': {field: 'forged'}}])
        assert not rejected['success'] and 'protected field' in rejected['error']


def test_insufficient_evidence_does_not_escape_evidence_queue(tmp_path):
    key = 'tests/test_demo.py::test_bad'
    output, entries = _prepare_batch_output(tmp_path, [key])
    case = _reviewed_record(key)
    case.failure_analysis.category = 'insufficient_evidence'
    case.failure_analysis.rationale.remaining_gap = 'Need waveform after assertion'
    case.waveform.diagnostic = 'No evidence yet'
    (output / entries[key].record_path).write_text(json.dumps(case.model_dump(mode='json', by_alias=True)))
    queue = ReviewWorkQueue(workspace=str(tmp_path), output_dir='verification_review/analysis')
    assert queue._run(stage='case_triage')['remaining_count'] == 0
    result = queue._run(stage='dut_evidence')
    assert result['remaining_count'] == 1
    assert any(g['field'] == 'waveform' for g in result['items'][0]['gaps'])


def test_archived_wave_analysis_leaves_editable_but_signed_fields_protected(tmp_path):
    """A precise indexed patch repairs historical narrative without changing evidence."""
    key = 'tests/test_demo.py::test_bad'
    output, entries = _prepare_batch_output(tmp_path, [key])
    path = output / entries[key].record_path
    record = json.loads(path.read_text())
    record['additional_waveforms'] = [record['waveform'].copy()]
    path.write_text(json.dumps(record))
    options = dict(workspace=str(tmp_path), output_dir='verification_review/analysis')
    draft = CreateCaseDraft(**options)._run([key])
    args = dict(draft_path=draft['draft_path'], expected_sha256=draft['draft_sha256'],
                patches=[{'case_id': key, 'fields': {'additional_waveforms.0.observed_behavior': 'Earlier window'}}])
    result = PatchCaseDraft(**options)._run(**args)
    assert result['success'], result
    args['expected_sha256'] = result['draft_sha256']
    for field in ['additional_waveforms', 'additional_waveforms.0.receipt_id', 'additional_waveforms.0',
                  'additional_waveforms.5.observed_behavior', 'additional_waveforms.-1.observed_behavior']:
        args['patches'][0]['fields'] = {field: 'forged'}
        assert not PatchCaseDraft(**options)._run(**args)['success']
