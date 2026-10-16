"""Guard live review records and derive evidence values from measured snapshots."""

import json
from pathlib import Path

import pytest
import yaml

from bug_review.core.records import CaseRecord, load_record
from bug_review.plugin import get_plugin
from bug_review.tools import ResolveReviewCase, UpdateCaseRecords
from bug_review.tools.events import ApplyWaveformEvent
from ucagent.tools.fileops import EditTextFile, CopyFile
from test_failure_evidence import _prepare_batch_output, _reviewed_record
from test_root_reports import example


def test_workflow_file_tools_cannot_overwrite_records_or_reports(tmp_path):
    """The real workflow policy blocks direct edits and copies but permits drafts."""
    cfg = yaml.safe_load(get_plugin().workflows[0].config_file.read_text())
    options = dict(workspace=str(tmp_path), write_dirs=cfg['write_dirs'], un_write_dirs=cfg['un_write_dirs'])
    edit = EditTextFile(**options)
    copy = CopyFile(**options)
    (tmp_path / 'source.json').write_text('{}')
    for name in ['analysis/cases/case_0001.json', 'analysis/review_index.json',
                 'analysis/revisions/r1.json', 'report/index.html', 'run/test_report/report.json']:
        target = tmp_path / 'verification_review' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('original')
        assert 'not allowed to write' in edit._run(path=str(target.relative_to(tmp_path)), content='bad')
        assert 'not allowed to write' in copy._run(source_path='source.json', dest_path=str(target.relative_to(tmp_path)), overwrite=True)
        assert target.read_text() == 'original'
    edit._run(path='verification_review/analysis/drafts/test.json', content='{}')
    assert (tmp_path / 'verification_review/analysis/drafts/test.json').read_text() == '{}'
    edit._run(path='verification_review/notes/review.md', content='notes')
    assert 'notes' in (tmp_path / 'verification_review/notes/review.md').read_text()


def test_case_lookup_isolated_from_unrelated_corrupt_record(tmp_path):
    """Resolve by stable ID even when a different indexed case contains broken JSON."""
    good, bad = 'tests/test_demo.py::test_good', 'tests/test_demo.py::test_bad'
    output, entries = _prepare_batch_output(tmp_path, [bad, good])
    (output / entries[bad].record_path).write_text('broken')
    tool = ResolveReviewCase(workspace=str(tmp_path), output_dir='verification_review/analysis')
    result = tool._run(good)
    assert result['success'] and result['case_id'] == good
    path = output / entries[good].record_path
    record = json.loads(path.read_text());record['case_id'] = bad;path.write_text(json.dumps(record))
    assert not tool._run(good)['success']
    assert not tool._run(entries[good].record_path)['success']


def test_oversized_batch_does_not_write_any_record(tmp_path):
    """The five-case limit is enforced by the tool before validation or mutation."""
    ids = [f'tests/test_demo.py::test_{n}' for n in range(6)]
    output, entries = _prepare_batch_output(tmp_path, ids)
    before = {entry.record_path: (output / entry.record_path).read_bytes() for entry in entries.values()}
    draft = output / 'drafts/batch.json'
    draft.write_text(json.dumps({'cases': {key: _reviewed_record(key).model_dump(mode='json', by_alias=True) for key in ids}}))
    tool = UpdateCaseRecords(workspace=str(tmp_path), output_dir='verification_review/analysis')
    result = tool._run('verification_review/analysis/drafts/batch.json')
    assert not result['success'] and 'limit is 5' in result['error']
    assert all((output / path).read_bytes() == data for path, data in before.items())


def event_fixture(tmp_path, monkeypatch):
    """Bind a two-execution case to real local VCD snapshots through a test receipt store."""
    output, index, cases, _, _, _, waveinfo = example(tmp_path)
    case = next(iter(cases.values()))
    (output / 'cases').mkdir()
    (output / 'review_index.json').write_text(json.dumps(index.model_dump(mode='json', by_alias=True)))
    (output / 'cases/case.json').write_text(json.dumps(case.model_dump(mode='json', by_alias=True)))
    monkeypatch.setattr('bug_review.tools.events.review_waveinfo', lambda _: waveinfo)
    tool = ApplyWaveformEvent(workspace=str(tmp_path), output_dir='verification_review/analysis')
    args = case.events[0].model_dump(exclude={'raw_value', 'source_kind', 'source_ref'})
    args['case_id'] = case.case_id
    return output, case, waveinfo, tool, args


def test_waveform_event_reads_full_width_value_and_is_idempotent(tmp_path, monkeypatch):
    """Never ask the model to transcribe a wide bus value; repeated upserts stay unique."""
    output, case, _, tool, args = event_fixture(tmp_path, monkeypatch)
    args['signal_path'] += '[95:0]'
    result = tool._run(**args)
    assert result['success'], result
    assert result['raw_value'] == case.events[0].raw_value
    assert len(result['raw_value']) == 96
    assert tool._run(**args)['success']
    saved = load_record(output, 'cases/case.json', 'case')
    assert len(saved.events) == 2 and saved.events[0].signal_path == 'TOP.demo.cmsg'


@pytest.mark.parametrize('fault', ['wrong_case', 'unattached', 'outside_window', 'wrong_execution',
                                  'missing_signal', 'stale', 'missing', 'raw_value'])
def test_waveform_event_failure_preserves_record(tmp_path, monkeypatch, fault):
    """Invalid identity, measurement or caller-provided raw values never alter a Case."""
    output, case, waveinfo, tool, args = event_fixture(tmp_path, monkeypatch)
    path = output / 'cases/case.json'; before = path.read_bytes()
    if fault == 'wrong_case':
        waveinfo.get_analysis_receipt(args['receipt_id'])['arguments']['test_case_name'] = 'other'
    elif fault == 'unattached': args['receipt_id'] = 'c' * 32
    elif fault == 'outside_window': args['time'] = 41
    elif fault == 'wrong_execution': args['execution_id'] = 'unknown'
    elif fault == 'missing_signal': args['signal_path'] = 'TOP.demo.absent'
    elif fault == 'raw_value': args['raw_value'] = '0'
    else:
        selection = waveinfo.get_analysis_receipt(args['receipt_id'])['result']['waveform_selection']
        source = tmp_path / selection['waveform_file']
        if fault == 'stale': source.write_text(source.read_text() + '\n')
        else: source.unlink()
    result = tool._run(**args)
    assert not result['success'], result
    assert path.read_bytes() == before


def test_case_draft_preserves_existing_machine_fields(tmp_path):
    """Small drafts are copied from current records without rewriting replay facts."""
    from bug_review.tools import CreateCaseDraft

    ids = ['tests/test_demo.py::test_bad']
    output, entries = _prepare_batch_output(tmp_path, ids)
    tool = CreateCaseDraft(workspace=str(tmp_path), output_dir='verification_review/analysis')
    result = tool._run(ids)
    assert result['success'], result
    draft = json.loads((tmp_path / result['draft_path']).read_text())
    assert draft['cases'][ids[0]] == json.loads((output / entries[ids[0]].record_path).read_text())
    assert not tool._run(ids * 2)['success']
    assert not tool._run(['missing'])['success']
    assert not tool._run(ids * 6)['success']


def test_waveform_event_preserves_unknown_bits(tmp_path, monkeypatch):
    """The measured value retains x/z rather than coercing unknown bits to zero."""
    output, case, waveinfo, tool, args = event_fixture(tmp_path, monkeypatch)
    receipt = waveinfo.get_analysis_receipt(args['receipt_id'])
    selection = receipt['result']['waveform_selection']
    source = tmp_path / selection['waveform_file']
    raw = 'xz' + case.events[0].raw_value[2:]
    source.write_text(source.read_text().replace(case.events[0].raw_value, raw))
    selection.update(size_bytes=source.stat().st_size, modified_time_ns=source.stat().st_mtime_ns)
    result = tool._run(**args)
    assert result['success'], result
    assert result['raw_value'] == raw


def test_stale_generated_draft_cannot_replace_newer_record(tmp_path):
    """A draft prepared before a later update cannot silently erase the new work."""
    from bug_review.tools import CreateCaseDraft

    case_id = 'tests/test_demo.py::test_bad'
    output, entries = _prepare_batch_output(tmp_path, [case_id])
    result = CreateCaseDraft(workspace=str(tmp_path), output_dir='verification_review/analysis')._run([case_id])
    path = output / entries[case_id].record_path
    record = json.loads(path.read_text());record['failure_analysis']['unresolved'] = 'new finding'
    path.write_text(json.dumps(record)); before = path.read_bytes()
    result = UpdateCaseRecords(workspace=str(tmp_path), output_dir='verification_review/analysis')._run(result['draft_path'])
    assert not result['success'] and 'changed since draft creation' in result['error']
    assert path.read_bytes() == before


def test_multiple_bad_values_can_be_repaired_one_event_at_a_time(tmp_path, monkeypatch):
    """A different invalid event must not create a circular dependency for repairs."""
    output, case, _, tool, args = event_fixture(tmp_path, monkeypatch)
    path = output / 'cases/case.json'
    case.events[0].raw_value = '0'
    case.events[1].raw_value = '0'
    path.write_text(json.dumps(case.model_dump(mode='json', by_alias=True)))
    result = tool._run(**args)
    assert result['success'], result
    saved = load_record(output, 'cases/case.json', 'case')
    assert len(saved.events[0].raw_value) == 96 and saved.events[1].raw_value == '0'
    args.update(event_id='message-1', execution_id='rerun-1', receipt_id='b' * 32)
    assert tool._run(**args)['success']
    assert len(load_record(output, 'cases/case.json', 'case').events[1].raw_value) == 96
