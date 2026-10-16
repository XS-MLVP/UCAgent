"""Exercise bounded investigation, measured catalogs and unchanged-failure pauses."""

import json
from types import SimpleNamespace

from bug_review.core.evidence import read_event_value, _cached_event_value
from bug_review.core.progress import validation_status
from bug_review.checkers.analysis import BugReviewStageChecker
from bug_review.tools.investigation import ReviewWorkQueue, ReviewCaseContext, ReviewSignalCatalog
from test_record_safety import event_fixture


def test_real_catalog_filters_and_pages_full_signal_paths(tmp_path, monkeypatch):
    """Catalog contents come from the selected real waveform, not suggested names."""
    output, case, waveinfo, _, _ = event_fixture(tmp_path, monkeypatch)
    receipt = waveinfo.get_analysis_receipt(case.waveform.receipt_id)
    waveinfo.analyze = lambda **_: {'status': 'metadata_only', 'waveform_selection': receipt['result']['waveform_selection']}
    monkeypatch.setattr('bug_review.tools.investigation.review_waveinfo', lambda _: waveinfo)
    tool = ReviewSignalCatalog(workspace=str(tmp_path), output_dir='verification_review/analysis')
    result = tool._run(case.case_id, contains='cmsg', limit=1)
    assert result['success'] and result['status'] == 'metadata_only'
    assert result['signals'] == [{'path': 'TOP.demo.cmsg[95:0]', 'width': 96}]
    assert result['raw_time_bounds'] == [0, 40]
    assert tool._run(case.case_id, contains='missing')['signal_count'] == 0
    assert not tool._run('wrong case')['success']
    page = tool._run(case.case_id, limit=1)
    assert page['next_offset'] == 1 and page['signal_count'] == 3


def test_queue_keeps_case_gaps_and_context_small(tmp_path, monkeypatch):
    """An attached receipt cannot hide missing analysis or make a case complete."""
    output, case, waveinfo, _, _ = event_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr('bug_review.tools.investigation.review_waveinfo', lambda _: waveinfo)
    queue = ReviewWorkQueue(workspace=str(tmp_path), output_dir='verification_review/analysis')
    result = queue._run()
    assert result['success'] and result['remaining_count'] == 1
    assert result['items'][0]['case_id'] == case.case_id
    assert result['items'][0]['gaps']
    context = ReviewCaseContext(workspace=str(tmp_path), output_dir='verification_review/analysis')._run(case.case_id)
    assert context['success'] and 'viewer_url' not in json.dumps(context)
    assert not context['source_excerpts']
    assert not any('raw_value' in event for event in context['events'])
    (output / 'cases/case.json').write_text('bad JSON')
    assert queue._run()['remaining_count'] == 1


def test_unchanged_check_failure_pauses_and_record_change_resets(tmp_path):
    """Only repeated identical failures on unchanged inputs trigger a pause."""
    output = tmp_path / 'verification_review/analysis';output.mkdir(parents=True)
    record = output / 'review_index.json';record.write_text('{}')
    paused = []
    checker = BugReviewStageChecker('dut_evidence')
    checker.workflow = SimpleNamespace(out=output, check=lambda _: (False, {'error_code': 'FIELD_INVALID'}))
    checker.stage_manager = SimpleNamespace(agent=SimpleNamespace(set_break=lambda value: paused.append(value)))
    for _ in range(2): assert 'no_progress' not in checker.do_check()[1]
    assert checker.do_check()[1]['no_progress']
    assert paused == [True]
    assert validation_status(output)['dut_evidence'] == 'failed'
    record.write_text('{"changed":true}')
    assert validation_status(output)['dut_evidence'] == 'stale'
    assert 'no_progress' not in checker.do_check()[1]
    checker.workflow.check = lambda _: (True, {'stage': 'dut_evidence'})
    assert checker.do_check()[0]
    assert validation_status(output)['dut_evidence'] == 'passed'
    assert validation_status(output)['full_replay'] == 'passed'
    assert validation_status(output)['case_triage'] == 'passed'


def test_measurement_cache_invalidates_on_snapshot_change(tmp_path, monkeypatch):
    """Unchanged measurements are reused, but changed source bytes are measured again."""
    _, case, waveinfo, _, _ = event_fixture(tmp_path, monkeypatch)
    path = tmp_path / waveinfo.get_analysis_receipt(case.waveform.receipt_id)['result']['waveform_selection']['waveform_file']
    event = case.events[0]
    _cached_event_value.cache_clear()
    original = read_event_value(path, event)
    assert read_event_value(path, event) == original
    assert _cached_event_value.cache_info().hits == 1
    replacement = '1' + original[1:]
    path.write_text(path.read_text().replace(original, replacement))
    assert read_event_value(path, event) == replacement
    assert _cached_event_value.cache_info().misses == 2
