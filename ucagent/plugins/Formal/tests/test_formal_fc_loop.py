"""Exercise the FC implement/run/review loop with authentic artifact-bound result receipts."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from formal.baseline import batch_context, function_batch_progress, phase_six, shared_contract
from formal.checkers.formal import FormalBatchPlanChecker, PropertyStructureChecker
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


def publish(execution, records, ck_id='CK-FIRST', result='FALSIFIED', number=1, deferred=False, trace=None):
    """Seal a small native result block so normal receipt verification remains active."""
    model = FormalRecords.model_validate(records)
    target, root, executable, files, fingerprint = execution._inputs()
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
            'state': 'REVIEW' if result == 'UNPROVEN' else 'RESOLVED', 'disposition': 'DEFERRED' if deferred else None,
            'execution_elapsed_s': 1200 if result == 'UNPROVEN' else 0.01, 'review_round': 0,
            'attempts': [{'console': 'attempts/000001/console.log', 'console_hash': hashlib.sha256(console.read_bytes()).hexdigest(),
                          'proof_started_at': number,
                          'active_s': 1200 if result == 'UNPROVEN' else 0.01,
                          'running': False, 'returncode': 0, 'witness_hash': None, 'trace_hash': None}]}
    if trace is not None:
        vcd = console.parent / 'avis' / name / (name + '.vcd')
        vcd.parent.mkdir(parents=True)
        vcd.write_bytes(trace)
        item['attempts'][0]['trace_hash'] = hashlib.sha256(trace).hexdigest()
    state = {'run_id': run_id, 'workspace': str(execution.workspace), 'fingerprint': fingerprint,
             'dut': execution.dut, 'output_dir': execution.output_dir, 'files': files,
             'scope': 'selected', 'status': 'AWAITING_REVIEW' if result == 'UNPROVEN' else 'COMPLETED', 'created_at': number,
             'policy': {}, 'checkpoints': [],
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


def test_stage_four_scope_retains_original_goals_across_fc_and_full_runs(task):
    """Permit local repairs and linked additions while rejecting removal of the original goal."""
    execution, records, path, cfg = task
    planning = FormalBatchPlanChecker('DUT', cfg=cfg)
    planning.set_workspace(str(execution.workspace))
    planning.on_init()
    other_checks = records['spec']['function_groups'][0]['functions'][1]['check_points']
    other_checks.append({'id': 'CK-ASSUME', 'style': 'Assume', 'description': 'Proposed environment constraint'})
    path.write_text(yaml.safe_dump(records))
    receipt = path.parent / 'formal_runs/plan_scope.json'
    assert planning.do_check()[0] and not receipt.exists()
    assert planning.do_check(is_complete=True)[0]
    sealed = json.loads(receipt.read_bytes())['checkpoints']
    original = sealed['CK-FIRST']
    assert original['description'] == 'first behavior' and 'sva_body' not in original
    assert sealed['CK-ASSUME']['kind'] == 'assume'

    other_checks.pop()
    checks = records['spec']['function_groups'][0]['functions'][0]['check_points']
    checks[0].update(style='Seq', description='first behavior, clarified', sva_body='a;')
    checks.append({'id': 'CK-CHILD', 'style': 'Comb', 'description': 'a supporting clause', 'parent_ck_id': 'CK-FIRST'})
    path.write_text(yaml.safe_dump(records))
    progress = function_batch_progress(execution, FormalRecords.model_validate(records))
    assert progress['current_fc']['ready_ck_ids'] == ['CK-FIRST']
    assert progress['current_fc']['unimplemented_ck_ids'] == ['CK-CHILD']

    del checks[0]
    del checks[0]['parent_ck_id']
    path.write_text(yaml.safe_dump(records))
    with pytest.raises(ValueError, match=r'Missing: \[\x27CK-FIRST\x27\]'):
        function_batch_progress(execution, FormalRecords.model_validate(records))
    with pytest.raises(ValueError, match='Original Stage 4 checkpoint scope changed'):
        execution.run()
    final = PropertyStructureChecker('DUT', cfg=cfg)
    final.set_workspace(str(execution.workspace))
    final.on_init()
    passed, diagnostic = final.do_check()
    assert not passed and 'CK-FIRST' in diagnostic['details']


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
    assert prepared['check_points']['items'][0]['sva_body'] == 'a;'
    assert prepared['repair_update']['bodies'] == {'CK-FIRST': ''}
    assert prepared['repair_update']['expected_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert prepared['review_call']['reviews'][0]['run_id'] == run_id
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


@pytest.mark.parametrize("changed", ["environment", "body", "archived_report"])
def test_stale_exception_reason_is_available_only_as_a_verified_draft(task, changed):
    """Matching old reasoning can help a new review, without closing its current receipt."""
    execution, records, path, cfg = task
    check = first(records)
    check['sva_body'] = 'a;'
    assumption = {'id': 'CK-ENV', 'style': 'Assume', 'description': 'Legal stimulus', 'sva_body': 'a;'}
    records['spec']['function_groups'][0]['functions'][0]['check_points'].append(assumption)
    path.write_text(yaml.safe_dump(records))
    tool = RunFormal(str(execution.workspace), 'output', 'DUT', cfg)
    old = publish(execution, records, result='TRIVIALLY_TRUE')
    reason = 'Combinational structure by the named design contract'
    follow_up = 'Recheck the response coverage in the complete batch'
    command = {'action': 'review_fc', 'fc_id': 'FC-FIRST', 'reviews': [
        {'ck_id': 'CK-FIRST', 'run_id': old, 'classification': 'DESIGN_EXPECTED',
         'reason': reason, 'next_action': follow_up}]}
    assert tool.invoke(command)['current_fc']['fc_id'] == 'FC-SECOND'
    artifact = path.parent / 'formal_runs/fc_reviews.json'
    unchanged = artifact.read_bytes()
    moved = tool.invoke({**command, 'reviews': [{**command['reviews'][0], 'classification': 'ENV_PENDING'}]})
    assert moved['status'] == 'action_required' and moved['error_code'] == 'formal_fc_already_reviewed'
    assert moved['current_fc']['fc_id'] == 'FC-SECOND'
    assert moved['applied_reviews'][0]['classification'] == 'DESIGN_EXPECTED'
    assert artifact.read_bytes() == unchanged
    assumption['sva_body'] = '!a;'
    if changed == "body":
        check['sva_body'] = '!a;'
    elif changed == "archived_report":
        (path.parent / 'formal_runs' / old / 'attempts/000001/console.log').write_text('changed archive')
    path.write_text(yaml.safe_dump(records))
    current = publish(execution, records, result='TRIVIALLY_TRUE', number=2)
    progress = tool.invoke({'action': 'pending'})
    assert progress['fc_closed'] == 0
    fc = progress['current_fc']
    assert fc['phase'] == 'review' and fc['fc_id'] == 'FC-FIRST'
    row, = fc['needs_review']
    assert row['classification'] is None and row['run_id'] == current
    assert fc['review_call']['reviews'] == [{'ck_id': 'CK-FIRST', 'run_id': current, 'classification': '', 'reason': ''}]
    if changed == "environment":
        draft = row['prior_review_draft']
        assert draft['run_id'] == old and draft['reason'] == reason
        assert draft['review_follow_up'] == follow_up
    else:
        assert 'prior_review_draft' not in row
    with pytest.raises(ValueError, match='exact matching run_id'):
        tool.invoke(command)
    command['reviews'][0]['run_id'] = current
    assert tool.invoke(command)['fc_closed'] == 1


@pytest.mark.parametrize("changed_sample", [False, True])
def test_review_draft_detects_native_date_only_change(task, changed_sample):
    """New raw evidence always needs a fresh submission, even when waveform data match."""
    execution, records, path, cfg = task
    first(records)['sva_body'] = 'a;'
    path.write_text(yaml.safe_dump(records))
    tool = RunFormal(str(execution.workspace), 'output', 'DUT', cfg)
    trace = b'$date\n Mon Nov 16 13:28:37 2026\n$end\n$timescale 1ns $end\n#0\n1!\n'
    old = publish(execution, records, trace=trace)
    old_request = {'action': 'review_fc', 'fc_id': 'FC-FIRST', 'reviews': [
        {'ck_id': 'CK-FIRST', 'run_id': old, 'classification': 'RTL_BUG', 'reason': 'Observed output differs from the named requirement'}]}
    assert tool.invoke(old_request)['fc_closed'] == 1
    new_trace = trace.replace(b'13:28:37', b'13:28:39')
    if changed_sample:
        new_trace = new_trace.replace(b'1!', b'0!')
    current = publish(execution, records, number=2, trace=new_trace)
    progress = tool.invoke({'action': 'pending'})
    assert progress['fc_closed'] == 0
    row, = progress['current_fc']['needs_review']
    assert row['run_id'] == current and row['classification'] is None
    if changed_sample:
        assert 'prior_review_draft' not in row
    else:
        assert row['prior_review_draft']['trace_payload'] == 'same_except_export_date'


def test_shared_assume_update_returns_the_reopened_targets_and_next_run(task):
    """A Stage 6 author can submit the exact recheck without asking pending again."""
    execution, records, path, cfg = task
    functions = records['spec']['function_groups'][0]['functions']
    for fc in functions:
        fc['check_points'][0]['sva_body'] = 'a;'
    functions[0]['check_points'].append({'id': 'CK-ASSUME', 'style': 'Assume', 'description': 'External input', 'sva_body': 'a;'})
    path.write_text(yaml.safe_dump(records))
    publish(execution, records, result='PROVEN')
    publish(execution, records, ck_id='CK-SECOND', result='PROVEN', number=2)
    store = FormalDataStore(str(execution.workspace), 'output', 'DUT', cfg=cfg)
    reply = store.update('spec', None, {'CK-ASSUME': '!a;'}, hashlib.sha256(path.read_bytes()).hexdigest())
    pending = RunFormal(str(execution.workspace), 'output', 'DUT', cfg).invoke({'action': 'pending'})
    assert reply['shared_environment_changed']
    assert reply['reopened_ck_ids']['items'] == ['CK-FIRST', 'CK-SECOND']
    assert reply['fc_progress']['fc_closed'] == 0
    assert reply['fc_progress']['current_fc']['fc_id'] == 'FC-FIRST'
    assert reply['run_call'] == pending['current_fc']['run_call']
    assert reply['run_call']['ck_ids'] == ['CK-FIRST']
    assert reply['after_update_command'] is None


def test_active_selected_batch_blocks_formal_data_input_edits(task):
    """A pinned full-run pointer cannot hide an active Stage 6 proof."""
    execution, records, path, cfg = task
    first(records)['sva_body'] = 'a;'
    path.write_text(yaml.safe_dump(records))
    run = publish(execution, records, result='PROVEN')
    root = path.parent / 'formal_runs'
    (root / 'selected.json').write_text(json.dumps({'run_id': run}))
    state_path = root / run / 'state.json'
    state = json.loads(state_path.read_bytes())
    state['status'] = 'RUNNING'
    state_path.write_text(json.dumps(state))
    store = FormalDataStore(str(execution.workspace), 'output', 'DUT', cfg=cfg)
    original = path.read_bytes()
    with pytest.raises(ValueError, match=f'Proof batch {run} is active'):
        store.update('spec', None, {'CK-FIRST': '!a;'}, hashlib.sha256(original).hexdigest())
    assert path.read_bytes() == original


def test_reset_release_evidence_expires_when_the_shared_assume_changes(task):
    """An earlier healthy reset diagnostic cannot release an FC in a new environment."""
    execution, records, path, _ = task
    records['basic_info'] = {'clock_reset': {'clock_signal': 'clk', 'reset_signal': 'rst_n', 'reset_release': 'sync'}}
    checks = records['spec']['function_groups'][0]['functions'][0]['check_points']
    checks[0]['sva_body'] = 'a;'
    checks.append({'id': 'CK-ENV', 'style': 'Assume', 'description': 'External inputs', 'sva_body': 'a;'})
    path.write_text(yaml.safe_dump(records))
    run = publish(execution, records, result='PROVEN')
    root = path.parent / 'formal_runs' / run
    log = root / ('diagnostic-' + 'a' * 32) / 'console.log'
    log.parent.mkdir()
    log.write_text("UCAGENT_DIAG_BEGIN_reset_release\n"
                   " 1 u_checker.C_UCAGENT_DIAGNOSTIC_RESET_RELEASE : Pass\tpdrx\t0.01\t(-)\n"
                   "UCAGENT_DIAG_END_reset_release\n")
    state = json.loads((root / 'state.json').read_bytes())
    (root / 'reset_release.json').write_text(json.dumps({
        'input_fingerprint': state['fingerprint'], 'log': log.relative_to(root).as_posix(),
        'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest(),
    }))
    progress = function_batch_progress(execution, FormalRecords.model_validate(records))
    assert progress['fc_closed'] == 1 and progress['environment_check']['status'] == 'reachable'
    checks[1]['sva_body'] = '!a;'
    path.write_text(yaml.safe_dump(records))
    current = publish(execution, records, result='PROVEN', number=2)
    progress = function_batch_progress(execution, FormalRecords.model_validate(records))
    assert progress['fc_closed'] == 0
    assert progress['environment_check']['analyze_call']['run_id'] == current


def test_deferred_target_closes_with_gap_never_pass(task):
    """The existing tool's explicit deferral permits progress while preserving UNPROVEN."""
    execution, records, path, cfg = task
    first(records)['sva_body'] = 'a;';path.write_text(yaml.safe_dump(records))
    run_id = publish(execution, records, result='UNPROVEN', deferred=True)
    progress = function_batch_progress(execution, FormalRecords.model_validate(records))
    assert progress['current_fc']['fc_id'] == 'FC-SECOND'
    state = json.loads((path.parent / 'formal_runs' / run_id / 'state.json').read_text())
    assert state['properties']['u_checker.A_CK_FIRST']['result'] == 'UNPROVEN'


def test_slow_review_counts_stale_and_split_solver_time_without_reusing_proof(task):
    """Family costs survive context changes, while preflight and old receipts stay separate."""
    execution, records, path, _ = task
    first(records)['sva_body'] = 'a;'
    path.write_text(yaml.safe_dump(records))
    publish(execution, records, result='UNPROVEN', deferred=True)
    checks = records['spec']['function_groups'][0]['functions'][0]['check_points']
    checks.append({'id': 'CK-SPLIT', 'style': 'Comb', 'description': 'case split', 'sva_body': 'a;',
                   'parent_ck_id': 'CK-FIRST'})
    records['extra_config'] = {'tcl': {'timeout': '30s'}}
    path.write_text(yaml.safe_dump(records))
    publish(execution, records, ck_id='CK-SPLIT', result='UNPROVEN', number=2)
    root = path.parent / 'formal_runs'
    for number, scope in ((3, 'preflight'), (4, 'full')):
        directory = root / publish(execution, records, ck_id='CK-SPLIT', result='UNPROVEN', number=number)
        state_path = directory / 'state.json'
        state = json.loads(state_path.read_text())
        state['scope'] = scope
        if scope == 'full':
            state['properties']['u_checker.A_CK_SPLIT']['attempts'].insert(0, {'running': False, 'active_s': 0})
        state_path.write_text(json.dumps(state))
    expected = {'root_ck_id': 'CK-FIRST', 'solver_seconds': {'selected': 2400, 'full': 1200},
                'attempts': {'selected': 2, 'full': 1}}
    progress = function_batch_progress(execution, FormalRecords.model_validate(records))
    assert progress['current_fc']['ready_ck_ids'] == ['CK-FIRST']
    assert progress['current_fc']['slow_review'][0]['proof_history'] == expected
    assert progress['deferred_ck_ids'] == []
    archive = directory / 'inputs/output/.formal_records.yaml'
    archive.parent.mkdir(parents=True)
    archive.write_bytes(path.read_bytes())
    summary = execution.status(run_id=state['run_id'])
    assert summary['review_queue'][0]['proof_history'] == expected
    assert summary['review_queue'][0]['remaining_s'] == 2400
    assert summary['counts'] == {'UNPROVEN': 1}
    # An older interrupted retry records cumulative active time on the target.
    # Count its measured part once and retain that provenance across property splits.
    from formal.baseline import proof_history
    item = state['properties']['u_checker.A_CK_SPLIT']
    item.update(state='CANCELLED', execution_elapsed_s=1260)
    item['attempts'].append({'running': False, 'proof_started_at': 12})
    state_path.write_text(json.dumps(state))
    cost = proof_history(root, FormalRecords.model_validate(records), {'CK-FIRST'})['CK-FIRST']
    assert cost['solver_seconds'] == {'selected': 2400, 'full': 1260}
    assert cost['partial_attempts'] == {'full': 1}



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


def test_pending_checks_only_the_superseding_attempt(task, monkeypatch):
    """Validate only the latest matching artifact and never fall back after corruption."""
    from formal import execution as execution_module

    execution, records, path, _ = task
    first(records)['sva_body'] = 'a;'
    path.write_text(yaml.safe_dump(records))
    for number in range(1, 8):
        run_id = publish(execution, records, result='PROVEN', number=number)
    observed = []
    original = execution_module.property_evidence

    def observe(run_dir, *args, **kwargs):
        observed.append(run_dir.name)
        return original(run_dir, *args, **kwargs)

    monkeypatch.setattr(execution_module, 'property_evidence', observe)
    model = FormalRecords.model_validate(records)
    assert function_batch_progress(execution, model)['current_fc']['fc_id'] == 'FC-SECOND'
    assert observed == [run_id]
    (path.parent / 'formal_runs' / run_id / 'attempts/000001/console.log').write_text('Changed output')
    observed.clear()
    assert function_batch_progress(execution, model)['current_fc']['ready_ck_ids'] == ['CK-FIRST']
    assert observed == [run_id]


def test_explicit_other_stage_name_overrides_numeric_index(task):
    """Other workflows may also have an index five without adopting FC ordering."""
    execution, records, path, cfg = task
    (execution.workspace / '.ucagent/ucagent_info.json').write_text(json.dumps({'stage_index': 5, 'current_stage_name': 'other_workflow_stage'}))
    assert not phase_six(execution.workspace)


def test_persisted_stage_name_survives_workflow_reordering(task):
    """A composed workflow can place the Formal FC loop at a different index."""
    execution, _, _, _ = task
    info = execution.workspace / '.ucagent/ucagent_info.json'
    info.write_text(json.dumps({'stage_index': 7, 'stages_info': {'7': {'stage_name': 'environment_debugging_iteration'}}}))
    assert phase_six(execution.workspace)
    info.write_text(json.dumps({'stage_index': 5, 'stages_info': {'5': {'stage_name': 'another_stage'}}}))
    assert not phase_six(execution.workspace)


def test_empty_or_assumption_only_plan_cannot_close(task):
    """A syntactically valid but empty functional plan cannot finish phase six."""
    execution, records, path, cfg = task
    records['spec']['function_groups'] = []
    path.write_text(yaml.safe_dump(records))
    with pytest.raises(ValueError, match='at least one official'):
        function_batch_progress(execution, FormalRecords.model_validate(records))


def test_pending_exposes_unproven_review_instead_of_resubmitting(task):
    """A first slow proof keeps the FC open until a real disposition is recorded."""
    execution, records, path, cfg = task
    first(records)['sva_body'] = 'a;'
    path.write_text(yaml.safe_dump(records))
    run_id = publish(execution, records, result='UNPROVEN')
    tool = RunFormal(str(execution.workspace), 'output', 'DUT', cfg)
    pending = tool.invoke({'action': 'pending'})
    current = pending['current_fc']
    assert current['fc_id'] == 'FC-FIRST' and current['phase'] == 'slow_review'
    assert current['run_call'] is None and current['ready_ck_ids'] == []
    slow, = current['slow_review']
    assert slow['run_id'] == run_id and slow['active_s'] == 1200
    assert 'defer' in slow['actions']
    run = tool.invoke({'action': 'review', 'run_id': slow['run_id'],
                       'property_names': [slow['property']], 'disposition': 'defer',
                       'reason': 'Current proof budget exhausted with an unresolved output obligation',
                       'next_action': 'Review the induction invariant with the specification owner'})
    assert run['counts'] == {'UNPROVEN': 1}
    assert tool.invoke({'action': 'pending'})['current_fc']['fc_id'] == 'FC-SECOND'


def test_selected_status_hands_off_to_next_fc(task):
    """A stopped current selected proof directs the model to the next planned FC."""
    execution, records, path, cfg = task
    first(records)['sva_body'] = 'a;'
    path.write_text(yaml.safe_dump(records))
    run_id = publish(execution, records, result='PROVEN')
    tool = RunFormal(str(execution.workspace), 'output', 'DUT', cfg)
    reply = tool.invoke({'action': 'status', 'run_id': run_id, 'scope': 'selected', 'wait_s': 0})
    assert reply['counts'] == {'PROVEN': 1}
    assert reply['fc_progress']['current_fc']['fc_id'] == 'FC-SECOND'
    assert (reply['fc_progress']['fc_closed'], reply['fc_progress']['fc_total']) == (1, 2)
    first(records)['sva_body'] = '!a;'
    path.write_text(yaml.safe_dump(records))
    stale = tool.invoke({'action': 'status', 'run_id': run_id, 'scope': 'selected', 'wait_s': 0})
    assert not stale['current_inputs'] and 'fc_progress' not in stale


def test_unavailable_optional_sanity_returns_current_review_handoff(task, monkeypatch):
    """Missing the native vacuity feature leaves the first eligible FC review visible."""
    import formal.tools as tools

    execution, records, path, cfg = task
    first(records)['sva_body'] = 'a;'
    path.write_text(yaml.safe_dump(records))
    run_id = publish(execution, records, result='TRIVIALLY_TRUE')
    fault = {'status': 'unavailable', 'error_code': 'formal_diagnostic_license_unavailable',
             'required_feature': 'FormalVac'}
    monkeypatch.setattr(tools, 'analyze', lambda *args: fault.copy())
    diagnostic = tools.AnalyzeFormal(workspace=str(execution.workspace), output_dir='output', dut='DUT', cfg=cfg)
    result = diagnostic.invoke({'mode': 'sanity', 'run_id': run_id, 'property_name': 'u_checker.A_CK_FIRST'})
    assert result['required_feature'] == 'FormalVac'
    current = result['fc_progress']['current_fc']
    assert current['phase'] == 'review' and current['review_call']['reviews'][0]['run_id'] == run_id
    assert current['review_call']['reviews'][0]['classification'] == ''
    assert not matching_reviews(execution, FormalRecords.model_validate(records))


def test_planned_transaction_balance_requires_exact_body(task):
    """The current FC can render its recipe and cannot replace it with a DUT assertion."""
    execution, records, path, cfg = task
    records['basic_info'] = {'clock_reset': {'clock_signal': 'clk', 'reset_signal': 'rst_n'}}
    first(records).update(style='Seq', transaction_balance=[{
        'command_valid': 'req', 'command_ready': 'ready',
        'response_valid': 'rsp', 'response_ready': 'take',
    }])
    path.write_text(yaml.safe_dump(records))
    store = FormalDataStore(str(execution.workspace), 'output', 'DUT', cfg=cfg)
    ready = store.prepare('sva')['ready_update']
    planned = RunFormal(str(execution.workspace), 'output', 'DUT', cfg).invoke({'action': 'pending'})
    assert planned['current_fc']['planned_bodies'] == ready['bodies']
    assert '_pending' in ready['bodies']['CK-FIRST']
    with pytest.raises(ValueError, match='use the generated transaction_balance body'):
        store.update('spec', None, {'CK-FIRST': '@(posedge clk) !a |-> !y;'}, ready['expected_sha256'])
    changed = copy.deepcopy(records)
    first(changed).pop('transaction_balance')
    with pytest.raises(ValueError, match='preserve the planned transaction_balance'):
        store.update('spec', changed['spec'], None, ready['expected_sha256'])
    assert store.update(data=None, **ready)['status'] == 'updated'


def test_pending_selects_only_targets_without_current_evidence(task, monkeypatch):
    """Repairing a goal in the current FC leaves a matching sibling proof reusable."""
    execution, records, path, cfg = task
    first(records)['sva_body'] = 'a;'
    records['spec']['function_groups'][0]['functions'][0]['check_points'].append(
        {'id': 'CK-SIBLING', 'style': 'Comb', 'description': 'sibling behavior', 'sva_body': 'a;'})
    path.write_text(yaml.safe_dump(records))
    publish(execution, records, result='PROVEN')
    tool = RunFormal(str(execution.workspace), 'output', 'DUT', cfg)
    current = tool.invoke({'action': 'pending'})['current_fc']
    assert current['closed_ck_ids'] == ['CK-FIRST']
    assert current['run_call'] == {'action': 'run', 'scope': 'selected', 'ck_ids': ['CK-SIBLING'], 'wait_s': 5}
    monkeypatch.setattr('formal.tools.render_environment', lambda *args, **kwargs: {'warning_total': 0})
    monkeypatch.setattr(FormalExecution, 'run', lambda self, **options: options)
    assert tool.invoke({'action': 'run', 'scope': 'selected', 'fc_id': 'FC-FIRST'}) == {'ck_ids': ['CK-SIBLING']}
    scoped = {'action': 'run', 'scope': 'selected', 'fc_id': 'FC-FIRST', 'ck_ids': ['CK-SIBLING']}
    assert tool.invoke(scoped) == {'ck_ids': ['CK-SIBLING']}
    with pytest.raises(ValueError, match='Outside this FC'):
        tool.invoke({**scoped, 'ck_ids': ['CK-SIBLING', 'CK-SECOND']})


def test_current_fc_authoring_returns_exact_followup(task):
    """Partial writes hand off remaining bodies, and whole-FC proof waits for implementation."""
    execution, records, path, cfg = task
    points = records['spec']['function_groups'][0]['functions'][0]['check_points']
    points.append({'id': 'CK-SIBLING', 'style': 'Comb', 'description': 'sibling behavior'})
    path.write_text(yaml.safe_dump(records))
    store = FormalDataStore(str(execution.workspace), 'output', 'DUT', cfg=cfg)
    tool = RunFormal(str(execution.workspace), 'output', 'DUT', cfg)
    run = {'action': 'run', 'scope': 'selected', 'fc_id': 'FC-FIRST'}
    stopped = tool.invoke(run)
    assert stopped['error_code'] == 'formal_fc_action_required'
    prepare = stopped['current_fc']['prepare_call']
    spec = tool.invoke({'action': 'pending'})['current_fc']['prepare_call']
    assert prepare == spec == {'request': {'action': 'prepare', 'section': 'sva', 'function': 'FC-FIRST'}}
    partial = store.update('spec', None, {'CK-FIRST': 'a;'}, hashlib.sha256(path.read_bytes()).hexdigest())
    assert partial['prepare_call'] == prepare and 'run_call' not in partial
    finished = store.update('spec', None, {'CK-SIBLING': 'a;'}, partial['sha256'])
    assert finished['run_call'] == tool.invoke({'action': 'pending'})['current_fc']['run_call']
    assert finished['run_call']['ck_ids'] == ['CK-FIRST', 'CK-SIBLING']


def test_prepare_shared_assumptions_across_function_groups(task):
    """A shared environment page covers all groups while respecting explicit group filters."""
    execution, records, path, cfg = task
    groups = records['spec']['function_groups']
    groups[0]['functions'][0]['check_points'].append({'id': 'CK-A', 'style': 'Assume', 'description': 'first input'})
    groups.append({'id': 'FG-OTHER', 'functions': [{'id': 'FC-OTHER', 'check_points': [
        {'id': 'CK-B', 'style': 'Assume', 'description': 'second input'}]}]})
    path.write_text(yaml.safe_dump(records))
    store = FormalDataStore(str(execution.workspace), 'output', 'DUT', cfg=cfg)
    first_page = store.prepare('sva', limit=1, assumptions=True)
    assert first_page['check_points']['next_offset'] == 1
    assert first_page['ready_update']['bodies'] == {'CK-A': ''}
    rest = store.prepare('sva', offset=1, limit=20, assumptions=True)
    assert rest['ready_update']['bodies'] == {'CK-B': ''}
    all_assumptions = store.prepare('sva', limit=20, assumptions=True)
    assert all_assumptions['ready_update']['bodies'] == {'CK-A': '', 'CK-B': ''}
    grouped = store.prepare('sva', group='FG-OTHER', assumptions=True)
    assert grouped['ready_update']['bodies'] == {'CK-B': ''}


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


def test_case_templates_and_ten_check_implementation_across_fcs(task):
    from formal.checkers.formal import FormalCaseTemplateChecker
    from formal.data import FormalDataStore
    execution, records, path, cfg = task
    functions = records['spec']['function_groups'][0]['functions']
    functions[0]['check_points'][0]['description'] = 'Observe y for input a; a_pending is a distinct signal.'
    functions[1]['check_points'].extend(
        {'id': f'CK-EXTRA-{n}', 'style': 'Comb', 'description': f'Required observation {n}'} for n in range(11))
    path.write_text(yaml.safe_dump(records))
    for cls in (FormalBatchPlanChecker, FormalCaseTemplateChecker):
        checker = cls('DUT', cfg=cfg)
        checker.set_workspace(str(execution.workspace))
        checker.on_init()
        ok, details = checker.do_check(is_complete=True)
        assert ok, details
    (execution.workspace / '.ucagent/ucagent_info.json').write_text(json.dumps({'current_stage_name': 'implement_formal_case_batches'}))
    data = FormalDataStore(str(execution.workspace), 'output', 'DUT', cfg=cfg)
    plan = json.loads((path.parent / 'formal_runs/case_templates.json').read_bytes())
    assert len(plan['templates']) == 13
    assert all(t['sva_body'] == '[LLM-TODO]' for t in plan['templates'])
    before = data.prepare(section='sva', limit=10)
    page = before['case_batch']
    assert before['progress'] == {'implemented': 0, 'total': 13}
    pins = {entry['name']: entry for entry in before['signal_bindings']['items']}
    assert set(pins) == {'a', 'y'} and pins['y']['direction'] == 'output' and pins['a']['width'] == 1
    assert pins['y']['source'] == 'DUT/dut.sv' and pins['y']['line'] == 1
    assert before['check_points']['items'][0]['named_signals'] == ['y', 'a']
    assert page['fc_ids'] == ['FC-FIRST', 'FC-SECOND']
    assert len(page['ck_ids']) == 10 and set(before['ready_update']['bodies']) == set(page['ck_ids'])
    assert all(row['template']['requirement'] == row['description'] for row in before['check_points']['items'])
    early = RunFormal(str(execution.workspace), 'output', 'DUT', cfg).invoke(
        {'action': 'run', 'scope': 'selected', 'fc_id': 'FC-FIRST'})
    assert early['error_code'] == 'formal_case_batch_incomplete'
    assert early['prepare_call'] == page['prepare_call']
    update = before['ready_update'].copy()
    update['bodies'] = dict.fromkeys(page['ck_ids'], 'a;')
    result = data.update(data=None, **update)
    assert result['run_call']['ck_ids'] == page['ck_ids']
    after = function_batch_progress(execution, FormalRecords.model_validate(yaml.safe_load(path.read_bytes())))
    assert after['case_batch']['run_call']['ck_ids'] == page['ck_ids']


def test_archived_ck_signal_view_preserves_trace_and_full_witness(task):
    execution, records, path, cfg = task
    first(records)['sva_body'] = 'a; // ignore noise'
    path.write_text(yaml.safe_dump(records))
    vcd = b"""$timescale 1ns $end
$scope module top $end
$var wire 1 ! a $end
$var wire 1 % noise $end
$upscope $end
$enddefinitions $end
#0
x!
1%
#2
z!
"""
    rid = publish(execution, records, trace=vcd)
    tool = RunFormal(str(execution.workspace), 'output', 'DUT', cfg)
    call = {'action': 'evidence', 'run_id': rid, 'evidence_view': 'property_signals',
            'property_names': ['u_checker.A_CK_FIRST']}
    focused = tool.invoke(call)
    assert focused['current_inputs']
    ck = focused['items'][0]
    assert ck['ck_id'] == 'CK-FIRST'
    visible = ck['trace_observations']
    assert visible['omitted_signals'] == 1 and visible['signals'][0]['name'] == 'top.a'
    assert visible['signals'][0]['z_mask'] == '0x1'
    first(records)['sva_body'] = 'noise;'
    path.write_text(yaml.safe_dump(records))
    archived = tool.invoke(call)
    assert not archived['current_inputs'] and archived['items'][0]['sva_body'] == 'a; // ignore noise'
    full = tool.invoke(ck['all_observations_call'])['items'][0]
    assert len(full['trace_observations']['signals']) == 2
    assert full['trace_sha256'] == ck['trace_sha256']
    assert full['evidence_ref'] == ck['evidence_ref']


def test_summary_keeps_changed_historical_failures_separate_from_current_proofs(tmp_path, monkeypatch):
    from formal.baseline import superseded_counterexamples
    from formal import execution as executor

    name = "u_checker.A_CK_SAMPLE"
    def state(identity, created, body, result, scope):
        ck = {"id": "CK-SAMPLE", "style": "Seq", "description": body, "sva_body": body}
        return {"run_id": identity, "created_at": created, "scope": scope,
                "semantic_inputs": {"spec": {"function_groups": [{"id": "FG-X", "functions": [{"id": "FC-X", "check_points": [ck]}]}]}},
                "properties": {name: {"result": result}}}

    old = state("a" * 32, 1, "accepted |=> delivered;", "FALSIFIED", "selected")
    current = state("b" * 32, 2, "accepted |-> delivered;", "PROVEN", "full")
    later = state("c" * 32, 3, "different;", "FALSIFIED", "selected")
    for run in (old, current, later):
        target = tmp_path / run["run_id"]
        target.mkdir()
        (target / "state.json").write_text(json.dumps(run))
    def verified(directory, run, prop, item, *, observations):
        assert directory == tmp_path / old["run_id"] and prop == name and not observations
        return {"evidence_ref": {"report_sha256": "e" * 64}}
    monkeypatch.setattr(executor, "property_evidence", verified)
    result = superseded_counterexamples(tmp_path, current)
    row, = result["observations"]
    assert row["current_result"] == "PROVEN" and row["previous_run"] == old["run_id"]
    assert row["changed"] == ["sva_body", "description"]
    assert row["previous_description"] != row["current_description"]
    assert row["evidence_ref"]["report_sha256"] == "e" * 64
    assert not result["unreadable_batches"]
    old["semantic_inputs"] = current["semantic_inputs"]
    (tmp_path / old["run_id"] / "state.json").write_text(json.dumps(old))
    assert superseded_counterexamples(tmp_path, current)["observations"] == []


def test_summary_discloses_post_plan_assumptions_without_counting_normal_implementation():
    from formal.baseline import planned_assumption_changes, planned_checkpoints
    from formal.skills.lib.models import FormalRecords

    rows = [{"id": "CK-RST", "style": "Assume", "description": "Start in reset."},
            {"id": "CK-HOLD", "style": "Assume", "description": "Hold a stalled input."}]
    records = {"dut": "Port", "spec": {"function_groups": [{"id": "FG-P", "functions": [
        {"id": "FC-P", "check_points": rows}]}]}}
    plan = planned_checkpoints(FormalRecords.model_validate(records))
    rows[0]["sva_body"] = "!rst_n;"
    assert planned_assumption_changes(plan, FormalRecords.model_validate(records)) == []
    rows.pop()
    rows.append({"id": "CK-REPLY", "style": "Assume", "description": "A response follows an accepted request."})
    changes = planned_assumption_changes(plan, FormalRecords.model_validate(records))
    assert changes == [{"ck_id": "CK-HOLD", "previous": "Hold a stalled input.", "current": None},
                       {"ck_id": "CK-REPLY", "previous": None, "current": rows[1]["description"]}]
    assert planned_assumption_changes({}, FormalRecords.model_validate(records)) == []

def test_original_scope_flag_discloses_changed_assert_even_without_local_failure():
    from formal.baseline import planned_checkpoints, summary_scope_review
    from formal.skills.lib.models import FormalRecords

    ck = {"id": "CK-DELAY", "style": "Seq", "description": "Next cycle."}
    data = {"dut": "Port", "spec": {"function_groups": [{"id": "FG-P", "functions": [{"id": "FC-P", "check_points": [ck]}]}]}}
    records = FormalRecords.model_validate(data)
    plan = planned_checkpoints(records)
    history = {"observations": [], "unreadable_batches": []}
    assert summary_scope_review(plan, records, history)["status"] == "no_recorded_changes"
    ck["description"] = "Same cycle."
    review = summary_scope_review(plan, FormalRecords.model_validate(data), history)
    assert review["status"] == "review_required" and review["rewritten_targets"][0]["previous"] == "Next cycle."
