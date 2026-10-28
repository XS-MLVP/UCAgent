"""Test optional receipt binding and actual VCD measurements without forged raw values."""

from types import SimpleNamespace
import json
from pathlib import Path
import pytest
from bug_review.tools import ApplyReceiptToCase, ApplyWaveformEvent, SetWaveformReviewNote, SubmitReviewDecisions, RenderBugReviewReport
from bug_review.core.validation import validate, ReviewIssues
from bug_review.core.json_io import atomic_write_json
from ucagent.util.waveform_viewer import build_waveform_viewer_url
from conftest import NODE, decisions_payload


@pytest.fixture
def wave(analyzed):
    """Create one real VCD and a simulated trusted native receipt store."""
    review = analyzed.review(); review.options.waveform_enabled = True; analyzed.save(review)
    session = analyzed.work / 'data/toffee_tmp_20261026120000_123'
    session.mkdir(parents=True)
    path = session / 'test_bad.vcd'
    path.write_text('$timescale 1ns $end\n$scope module TOP $end\n$var wire 4 ! value $end\n$upscope $end\n$enddefinitions $end\n#0\nb0000 !\n#5\nb10xz !\n#10\nb0011 !\n')
    atomic_write_json(analyzed.path('runs/waveforms/' + 'a' * 32 + '.json'), {'sessions': [str(session)]})
    url = build_waveform_viewer_url({'v': 2, 'test_dir': 'results/runs/work', 'test_case': 'test_bad',
                                   'start': '0', 'end': '10', 'cursor': '5', 'signals': ['TOP.value[3:0]']})
    receipt = {'arguments': {'test_case_name': NODE}, 'result': {
        'waveform_selection': {'waveform_file': path.relative_to(analyzed.workspace).as_posix()},
        'waveform_viewer': {'url': url}, 'signal_groups': {'key_signals': ['TOP.value[3:0]']},
        'analysis_window': {'start': 0, 'end': 10}}}
    store = SimpleNamespace(get_analysis_receipt=lambda rid: receipt if rid == 'c' * 32 else None,
                            get_bug_document_evidence=lambda _: {'success': True})
    return analyzed, path, receipt, store


def attach(layout, store):
    """Attach a measured receipt with reviewer-supplied sourced explanation."""
    return ApplyReceiptToCase(workspace=str(layout.workspace), output_dir='results', waveinfo=store)._run(
        case_id=NODE, invocation_id='a' * 32, receipt_id='c' * 32,
        observation='An actual value changes in the selected window.', alignment='Raw time is not a software cycle.',
        source_refs=['demo.sv:2'])


def test_optional_stage_can_select_no_cases(analyzed):
    """Enabling the stage does not require waveforms for already sufficient Cases."""
    review = analyzed.review(); review.options.waveform_enabled = True; analyzed.save(review)
    with pytest.raises(ReviewIssues): validate(analyzed, 'waveform_review')
    note = SetWaveformReviewNote(workspace=str(analyzed.workspace), output_dir='results')
    assert note._run(case_id=NODE, reason='Combinational output and log prove the failure; no timing dispute.')['success']
    assert validate(analyzed, 'waveform_review')['cases'] == 1
    assert SubmitReviewDecisions(workspace=str(analyzed.workspace), output_dir='results')._run(**decisions_payload())['success']


def test_measured_bits_keep_xz_and_no_manual_raw_value(wave):
    """Read the actual trace and reject caller-written machine values."""
    layout, _, _, store = wave
    assert attach(layout, store)['success']
    tool = ApplyWaveformEvent(workspace=str(layout.workspace), output_dir='results', waveinfo=store)
    args = dict(case_id=NODE, event_id='observed', receipt_id='c' * 32, time=5,
                signal_path='TOP.value', description='Measured value, not a conclusion.')
    result = tool._run(**args)
    assert result['success'], result
    assert result['raw_value'] == '10xz'
    assert tool._run(**args)['success'] and len(layout.case(NODE).events) == 1
    assert not tool._run(**args, raw_value='0000')['success']
    assert validate(layout, 'waveform_review', store)['cases'] == 1


@pytest.mark.parametrize('fault', ['wrong_case', 'wrong_run', 'disabled', 'exploratory', 'unknown_receipt'])
def test_receipt_ownership_boundaries(wave, fault):
    """File existence alone cannot prove Case or invocation ownership."""
    layout, _, receipt, store = wave
    if fault == 'wrong_case': receipt['arguments']['test_case_name'] = 'tests/other.py::test_bad'
    elif fault == 'wrong_run': atomic_write_json(layout.path('runs/waveforms/' + 'a' * 32 + '.json'), {'sessions': []})
    elif fault == 'disabled':
        review = layout.review(); review.options.waveform_enabled = False; layout.save(review)
    elif fault == 'exploratory': store.get_bug_document_evidence = lambda _: {'success': False}
    else: store.get_analysis_receipt = lambda _: None
    assert not attach(layout, store)['success']
    assert not layout.case(NODE).waveforms


@pytest.mark.parametrize('time,path', [(11, 'TOP.value'), (5, 'TOP.absent')])
def test_event_must_use_signed_signal_and_window(wave, time, path):
    """An arbitrary signal or timestamp cannot become signed evidence."""
    layout, _, _, store = wave
    assert attach(layout, store)['success']
    result = ApplyWaveformEvent(workspace=str(layout.workspace), output_dir='results', waveinfo=store)._run(
        case_id=NODE, event_id='bad', receipt_id='c' * 32, time=time,
        signal_path=path, description='Invalid selection.')
    assert not result['success']
    assert not layout.case(NODE).events


def test_waveform_publication_retains_original_token(wave):
    """Enabled reports bundle a static snapshot and native viewer without re-signing."""
    layout, _, receipt, store = wave
    assert attach(layout, store)['success']
    assert SubmitReviewDecisions(workspace=str(layout.workspace), output_dir='results', waveinfo=store)._run(**decisions_payload())['success']
    tool = RenderBugReviewReport(workspace=str(layout.workspace), output_dir='results', waveinfo=store)
    result = tool._run()
    assert result['success'], result
    assert (layout.report / ('assets/waveforms/' + 'c' * 32 + '.vcd')).is_file()
    assert (layout.report / 'assets/surfer/report-surfer.js').is_file()
    assert tool._run(verify_only=True)['success']
