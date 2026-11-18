"""Exercise the FC implement/run/review loop with authentic artifact-bound result receipts."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from formal.baseline import batch_context, function_batch_progress, phase_six, shared_contract
from formal.data import FormalDataStore
from formal.execution import FormalExecution
from formal.fc_review import matching_reviews, review_fc
from formal.skills.lib.models import FormalRecords
from formal.tools import RunFormal, RunFormalArgs
from ucagent.util.config import Config


@pytest.fixture
def task(tmp_path, monkeypatch):
    """Create two planned FCs and a current phase-six task without starting any worker."""
    (tmp_path / 'DUT').mkdir()
    (tmp_path / 'DUT/dut.sv').write_text('module DUT(input a,output y);assign y=a;endmodule')
    out = tmp_path / 'output'
    (out / 'tests').mkdir(parents=True)
    for suffix in ['checker.sv', 'wrapper.sv', 'formal.tcl']:
        (out / 'tests' / ('DUT_' + suffix)).write_text('fixture')
    tool = tmp_path / 'bin/FormalMC'
    tool.parent.mkdir()
    tool.write_text('#!/bin/sh\nexit 0\n')
    tool.chmod(0o755)
    monkeypatch.setenv('PATH', str(tool.parent))
    (tmp_path / '.ucagent').mkdir()
    (tmp_path / '.ucagent/ucagent_info.json').write_text(json.dumps({'stage_index': 5, 'current_stage_name': 'environment_debugging_iteration'}))
    cfg = Config({'runtime_options': {'formal_batched_sva': True}})
    records = {'dut': 'DUT', 'spec': {'function_groups': [{'id': 'FG-TEST', 'functions': [
        {'id': 'FC-FIRST', 'review_order': 1, 'check_points': [{'id': 'CK-FIRST', 'style': 'Comb', 'description': 'first behavior'}]},
        {'id': 'FC-SECOND', 'review_order': 2, 'check_points': [{'id': 'CK-SECOND', 'style': 'Comb', 'description': 'second behavior'}]},
    ]}]}}
    path = out / '.formal_records.yaml'
    path.write_text(yaml.safe_dump(records))
    return FormalExecution(str(tmp_path), 'output', 'DUT', cfg), records, path, cfg


def publish(execution, records, ck_id='CK-FIRST', result='FALSIFIED', number=1, deferred=False):
    """Seal a small native result block so normal receipt verification remains active."""
    model = FormalRecords.model_validate(records)
    target, root, executable, files, _ = execution._inputs()
    run_id = f'{number:032x}'
    directory = root / run_id
    directory.mkdir()
    name = 'u_checker.A_' + ck_id.replace('-', '_')
    native = {'PROVEN': 'Pass', 'FALSIFIED': 'Fail', 'TRIVIALLY_TRUE': 'TrivT', 'UNPROVEN': 'Undet'}[result]
    text = f'UCAGENT_RESULT_BEGIN\n 1 {name} : {native}\tpdrx\t0.01\t(-)\nUCAGENT_RESULT_END\n'
    console = directory / 'attempts/000001/console.log'
    console.parent.mkdir(parents=True)
    console.write_text(text)
    item = {'kind': 'assert', 'result': result, 'raw_status': native,
            'state': 'REVIEW' if deferred else 'RESOLVED', 'disposition': 'DEFERRED' if deferred else None,
            'attempts': [{'console': 'attempts/000001/console.log', 'console_hash': hashlib.sha256(console.read_bytes()).hexdigest(),
                          'running': False, 'returncode': 0, 'witness_hash': None, 'trace_hash': None}]}
    state = {'run_id': run_id, 'workspace': str(execution.workspace), 'fingerprint': str(number) * 64,
             'scope': 'selected', 'status': 'AWAITING_REVIEW' if deferred else 'COMPLETED', 'created_at': number,
             'properties': {name: item}, 'semantic_inputs': model.model_dump(exclude_none=True),
             'batch_context': batch_context(files, 'output/tests/DUT_checker.sv', executable, execution.policy,
                                            shared_contract(model.model_dump(exclude_none=True))),
             'decisions': [{'property': name, 'action': 'defer', 'reason': 'Budget exhausted without proof',
                            'next_action': 'Try an independently justified invariant'}] if deferred else []}
    (directory / 'state.json').write_text(json.dumps(state))
    return run_id


def first(records):
    """Return the first planned CK for concise semantic-change tests."""
    return records['spec']['function_groups'][0]['functions'][0]['check_points'][0]


def test_fc_cannot_advance_after_implementation_or_failure_without_review(task):
    """An implemented body or failed attempt cannot unlock the next FC."""
    execution, records, path, cfg = task
    store = FormalDataStore(str(execution.workspace), 'output', 'DUT', cfg=cfg)
    assert store.prepare('sva')['fc_id'] == 'FC-FIRST'
    first(records)['sva_body'] = 'a;'
    path.write_text(yaml.safe_dump(records))
    assert store.prepare('sva')['current_fc']['phase'] == 'run'
    with pytest.raises(ValueError, match='Close current FC'):
        store.prepare('sva', function='FC-SECOND')
    run_id = publish(execution, records)
    prepared = store.prepare('sva')
    assert prepared['fc_id'] == 'FC-FIRST' and prepared['ready_update'] is None
    assert prepared['review_call']['reviews'][0]['run_id'] == run_id
    assert prepared['current_fc']['needs_review'][0]['evidence_call'] == {
        'action': 'evidence', 'run_id': run_id, 'property_names': ['u_checker.A_CK_FIRST'],
    }
    with pytest.raises(ValueError, match='exact matching run_id'):
        review_fc(execution, FormalRecords.model_validate(records), 'FC-FIRST', [
            {'ck_id': 'CK-FIRST', 'run_id': 'f' * 32, 'classification': 'RTL_BUG', 'reason': 'output disagrees'}])
    review_fc(execution, FormalRecords.model_validate(records), 'FC-FIRST', [
        {'ck_id': 'CK-FIRST', 'run_id': run_id, 'classification': 'ENV_PENDING', 'reason': 'Need to correct the expected behavior'}])
    assert store.prepare('sva')['fc_id'] == 'FC-FIRST'
    review_fc(execution, FormalRecords.model_validate(records), 'FC-FIRST', [
        {'ck_id': 'CK-FIRST', 'run_id': run_id, 'classification': 'RTL_BUG', 'reason': 'Original input violates the documented output behavior'}])
    assert store.prepare('sva')['fc_id'] == 'FC-SECOND'
    assert matching_reviews(execution, FormalRecords.model_validate(records))['u_checker.A_CK_FIRST']['classification'] == 'RTL_BUG'
    assert not (path.parent / 'formal_runs/current.json').exists()


@pytest.mark.parametrize('change', ['classification_missing', 'classification_unknown', 'blank_reason', 'evidence', 'run', 'result'])
def test_tampered_local_review_never_closes_fc(task, change):
    """Persisted metadata must retain every validated field, not only an equal binding string."""
    execution, records, path, cfg = task
    first(records)['sva_body'] = 'a;'
    path.write_text(yaml.safe_dump(records))
    run_id = publish(execution, records)
    review_fc(execution, FormalRecords.model_validate(records), 'FC-FIRST', [
        {'ck_id': 'CK-FIRST', 'run_id': run_id, 'classification': 'RTL_BUG', 'reason': 'Documented output discrepancy'}])
    artifact = path.parent / 'formal_runs/fc_reviews.json'
    saved = json.loads(artifact.read_text()); row = saved['reviews']['CK-FIRST']
    if change == 'classification_missing': row.pop('classification')
    if change == 'classification_unknown': row['classification'] = 'DONE'
    if change == 'blank_reason': row['reason'] = ' '
    if change == 'evidence': row['evidence_ref']['report_sha256'] = 'f' * 64
    if change == 'run': row['run_id'] = 'f' * 32
    if change == 'result': row['result'] = 'PROVEN'
    artifact.write_text(json.dumps(saved))
    assert function_batch_progress(execution, FormalRecords.model_validate(records))['current_fc']['fc_id'] == 'FC-FIRST'
    assert not matching_reviews(execution, FormalRecords.model_validate(records))


def test_changed_shared_environment_reopens_all_but_local_body_only_its_fc(task):
    """Receipt reuse depends on actual shared assumptions and the exact target body."""
    execution, records, path, cfg = task
    functions = records['spec']['function_groups'][0]['functions']
    for f in functions:f['check_points'][0]['sva_body'] = 'a;'
    functions[0]['check_points'].append({'id': 'CK-ASSUME', 'style': 'Assume', 'description': 'legal input', 'sva_body': 'a;'})
    path.write_text(yaml.safe_dump(records))
    publish(execution, records, result='PROVEN')
    publish(execution, records, ck_id='CK-SECOND', result='PROVEN', number=2)
    assert function_batch_progress(execution, FormalRecords.model_validate(records))['current_fc'] is None
    first(records)['sva_body'] = '!a;'
    path.write_text(yaml.safe_dump(records))
    assert function_batch_progress(execution, FormalRecords.model_validate(records))['pending'] == ['CK-FIRST']
    functions[0]['check_points'][1]['sva_body'] = '!a;'
    path.write_text(yaml.safe_dump(records))
    assert function_batch_progress(execution, FormalRecords.model_validate(records))['pending'] == ['CK-FIRST', 'CK-SECOND']


def test_deferred_target_closes_with_gap_never_pass(task):
    """The existing tool's explicit deferral permits progress while preserving UNPROVEN."""
    execution, records, path, cfg = task
    first(records)['sva_body'] = 'a;';path.write_text(yaml.safe_dump(records))
    run_id = publish(execution, records, result='UNPROVEN', deferred=True)
    progress = function_batch_progress(execution, FormalRecords.model_validate(records))
    assert progress['current_fc']['fc_id'] == 'FC-SECOND'
    state = json.loads((path.parent / 'formal_runs' / run_id / 'state.json').read_text())
    assert state['properties']['u_checker.A_CK_FIRST']['result'] == 'UNPROVEN'


def test_stage6_update_cannot_fill_later_fc_and_full_run_cannot_bypass(task, monkeypatch):
    """Data updates and public run actions share the same stage-local work boundary."""
    execution, records, path, cfg = task
    store = FormalDataStore(str(execution.workspace), 'output', 'DUT', cfg=cfg)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='only the current FC'):
        store.update('spec', None, {'CK-FIRST': 'a;', 'CK-SECOND': 'a;'}, digest)
    assert path.read_bytes() == yaml.safe_dump(records).encode()
    monkeypatch.setattr('formal.tools.render_environment', lambda *a, **k: None)
    tool = RunFormal(str(execution.workspace), 'output', 'DUT', cfg)
    with pytest.raises(ValueError, match='phase 6'):
        tool.invoke({'action': 'run'})
    with pytest.raises(ValueError, match='phase 6'):
        tool.invoke({'action': 'run', 'scope': 'selected', 'fc_id': 'FC-SECOND'})
    assert 'reviews' in RunFormalArgs.model_json_schema()['properties']
    # Stage 7 may locally repair any FC without a stage rewind.
    (execution.workspace / '.ucagent/ucagent_info.json').write_text(json.dumps({'stage_index': 6, 'current_stage_name': 'coverage_analysis_and_optimization'}))
    assert not phase_six(execution.workspace)
    assert store.update('spec', None, {'CK-SECOND': 'a;'}, digest)['status'] == 'updated'


def test_invalid_classification_corrupt_evidence_and_stale_review_cannot_close(task):
    """Original evidence, current author inputs and interpretation shape all remain mandatory."""
    execution, records, path, cfg = task
    first(records)['sva_body'] = 'a;';path.write_text(yaml.safe_dump(records))
    run_id = publish(execution, records)
    row = {'ck_id': 'CK-FIRST', 'run_id': run_id, 'classification': 'DESIGN_EXPECTED', 'reason': 'claimed expected'}
    with pytest.raises(ValueError, match='requires one of'):
        review_fc(execution, FormalRecords.model_validate(records), 'FC-FIRST', [row])
    row['classification'] = 'RTL_BUG';row['reason'] = ' '
    with pytest.raises(ValueError, match='specification basis'):
        review_fc(execution, FormalRecords.model_validate(records), 'FC-FIRST', [row])
    row['reason'] = 'Documented output behavior disagrees'
    stale = FormalRecords.model_validate(records)
    first(records)['description'] = 'changed current goal'
    path.write_text(yaml.safe_dump(records))
    with pytest.raises(ValueError, match='Task inputs changed'):
        review_fc(execution, stale, 'FC-FIRST', [row])
    first(records)['description'] = 'first behavior';path.write_text(yaml.safe_dump(records))
    console = path.parent / 'formal_runs' / run_id / 'attempts/000001/console.log'
    console.write_text('edited report')
    progress = function_batch_progress(execution, FormalRecords.model_validate(records))
    assert progress['current_fc']['phase'] == 'run'
    with pytest.raises(ValueError, match='finish the current FC'):
        review_fc(execution, FormalRecords.model_validate(records), 'FC-FIRST', [row])


def test_explicit_other_stage_name_overrides_numeric_index(task):
    """Other workflows may also have an index five without adopting FC ordering."""
    execution, records, path, cfg = task
    (execution.workspace / '.ucagent/ucagent_info.json').write_text(json.dumps({'stage_index': 5, 'current_stage_name': 'other_workflow_stage'}))
    assert not phase_six(execution.workspace)


def test_empty_or_assumption_only_plan_cannot_close(task):
    """A syntactically valid but empty functional plan cannot finish phase six."""
    execution, records, path, cfg = task
    records['spec']['function_groups'] = []
    path.write_text(yaml.safe_dump(records))
    with pytest.raises(ValueError, match='at least one official'):
        function_batch_progress(execution, FormalRecords.model_validate(records))


def test_new_attempt_invalidates_old_local_review_even_when_new_evidence_is_damaged(task):
    """A prior interpretation must not silently substitute for a newer failed evidence check."""
    execution, records, path, cfg = task
    first(records)['sva_body'] = 'a;';path.write_text(yaml.safe_dump(records))
    old = publish(execution, records)
    review_fc(execution, FormalRecords.model_validate(records), 'FC-FIRST', [
        {'ck_id': 'CK-FIRST', 'run_id': old, 'classification': 'RTL_BUG', 'reason': 'Original behavior disagrees'}])
    new = publish(execution, records, result='PROVEN', number=2)
    (path.parent / 'formal_runs' / new / 'attempts/000001/console.log').write_text('broken report')
    progress = function_batch_progress(execution, FormalRecords.model_validate(records))
    assert progress['current_fc']['fc_id'] == 'FC-FIRST'
    assert progress['current_fc']['phase'] == 'run'
    assert not matching_reviews(execution, FormalRecords.model_validate(records))



def test_pending_uses_the_existing_solver_review_and_runs_only_uncovered_ck(task, monkeypatch):
    """A slow CK has an exact review path; a resolved sibling stays out of the next run."""
    execution, records, path, cfg = task
    first(records)['sva_body'] = 'a;'
    records['spec']['function_groups'][0]['functions'][0]['check_points'].append(
        {'id': 'CK-SIBLING', 'style': 'Comb', 'description': 'sibling behavior', 'sva_body': 'y == a;'})
    path.write_text(yaml.safe_dump(records))
    publish(execution, records, ck_id='CK-SIBLING', result='PROVEN')
    run_id = publish(execution, records, result='UNPROVEN', number=2)
    state_path = path.parent / 'formal_runs' / run_id / 'state.json'
    state = json.loads(state_path.read_text())
    state['status'] = 'AWAITING_REVIEW'
    state['fingerprint'] = execution._inputs()[-1]
    state['properties']['u_checker.A_CK_FIRST']['state'] = 'REVIEW'
    state_path.write_text(json.dumps(state))
    tool = RunFormal(str(execution.workspace), 'output', 'DUT', cfg)
    monkeypatch.setattr('formal.tools.render_environment', lambda *args, **kw: {'warning_total': 0})
    current = tool.invoke({'action': 'pending'})['current_fc']
    assert current['phase'] == 'solver_review'
    assert current['closed_ck_ids'] == ['CK-SIBLING']
    assert current['run_call'] is None
    assert current['solver_review'][0]['status_call'] == {'action': 'status', 'run_id': run_id, 'wait_s': 0}
    with pytest.raises(ValueError, match='existing run'):
        tool.invoke({'action': 'run', 'scope': 'selected', 'fc_id': 'FC-FIRST'})

    first(records)['sva_body'] = 'y;'
    path.write_text(yaml.safe_dump(records))
    current = tool.invoke({'action': 'pending'})['current_fc']
    assert current['closed_ck_ids'] == ['CK-SIBLING']
    assert current['run_call'] == {'action': 'run', 'scope': 'selected', 'ck_ids': ['CK-FIRST']}
    monkeypatch.setattr(FormalExecution, 'run', lambda self, **options: options)
    assert tool.invoke({'action': 'run', 'scope': 'selected', 'fc_id': 'FC-FIRST'}) == {'ck_ids': ['CK-FIRST']}
