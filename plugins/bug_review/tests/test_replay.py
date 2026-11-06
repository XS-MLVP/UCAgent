"""Verify targeted execution, archived reports, parameter identities and blockers."""

import json
from pathlib import Path
import pytest
from bug_review.tools import CollectReviewCases, CaptureReplayReport, UpdateCaseAnalysis, SubmitReviewDecisions
from bug_review.core.replay import report_outcomes, harvest_waveforms
from bug_review.core.json_io import atomic_write_json
from conftest import NODE, analysis_payload, import_execution, decisions_payload


def test_actual_native_targeted_run_preserves_input(linked):
    """Run real pytest through UCAgent and import only the linked failing test."""
    from ucagent.tools.testops import RunUnityChipTest
    original = (linked.inputs / 'tests/test_demo.py').read_bytes()
    result = CollectReviewCases(workspace=str(linked.workspace), output_dir='results')._run()
    assert result['success'], result
    assert result['case_ids'] == [NODE]
    runner = RunUnityChipTest(workspace=str(linked.workspace), report_dir='results/runs/reports')
    runner.set_report_context({'source': 'RunTestCases', 'stage_name': 'targeted_review'})
    report, _, _ = runner.do('results/runs/work', pytest_ex_args=result['target'], timeout=60)
    assert (linked.work / 'tests/test_demo.py').is_file()
    invocation = runner.last_execution['invocation_id']
    imported = CaptureReplayReport(workspace=str(linked.workspace), output_dir='results')._run(invocation_id=invocation)
    assert imported['success'], (report, imported)
    assert imported['outcomes'] == {NODE: 'failed'}
    assert linked.case(NODE).executions[0].provenance == 'rerun'
    assert original == (linked.inputs / 'tests/test_demo.py').read_bytes()
    assert set(linked.review().cases) == {NODE}


def test_full_regression_is_explicit(linked):
    """The switch includes unrelated tests only when resolved true."""
    review = linked.review(); review.options.full_regression_enabled = True; linked.save(review)
    result = CollectReviewCases(workspace=str(linked.workspace), output_dir='results')._run()
    assert result['success'], result
    assert set(result['case_ids']) == {NODE, 'tests/test_demo.py::test_unrelated'}


def test_parameterized_case_expands_from_actual_collection(linked):
    """Keep each parameter identity and never infer a child pass from a failed parent."""
    source = linked.inputs / 'tests/test_demo.py'
    source.chmod(0o644)
    source.write_text('import pytest\n\n@pytest.mark.parametrize("n", [0, 1])\ndef test_bad(n):\n    assert n == 0\n')
    result = CollectReviewCases(workspace=str(linked.workspace), output_dir='results')._run()
    assert result['success'], result
    nodes = {NODE + '[0]', NODE + '[1]'}
    assert set(linked.review().claims[0].case_ids) == nodes
    assert set(linked.review().cases) == nodes
    p = linked.runs / 'ambiguous.json'
    p.write_text(json.dumps({'report': {'tests': {'test_cases': {NODE: 'FAILED'},
                       'test_case_instances': {NODE: [{'node_id': NODE + '[1]', 'status': 'FAILED'}]}}}}))
    with pytest.raises(ValueError, match='exact raw'):
        report_outcomes(p)


def test_missing_dependency_is_diagnostic_and_allows_unresolved(linked):
    """Failed collection is not a fabricated execution or a permanently blocked review."""
    file = linked.inputs / 'tests/conftest.py'
    file.write_text('import missing_runtime_package_for_review_test\n')
    result = CollectReviewCases(workspace=str(linked.workspace), output_dir='results')._run()
    assert not result['success']
    assert 'missing_runtime_package_for_review_test' in (linked.runs / 'collection.log').read_text()
    a = analysis_payload('', 'unresolved')
    a.update(replay_blocker='Missing native runtime package.', remaining_gap='No execution available.', next_action='Provide package and rerun.')
    assert UpdateCaseAnalysis(workspace=str(linked.workspace), output_dir='results')._run(cases=[{'case_id': NODE, 'analysis': a}])['success']
    d = decisions_payload('inconclusive'); d['decisions'][0].update(remaining_gap='No real run.', next_action='Provide runtime.')
    assert SubmitReviewDecisions(workspace=str(linked.workspace), output_dir='results')._run(**d)['success']


def test_history_is_never_a_fresh_reproduction(linked):
    """Historical data requires an explicit rerun blocker and retains its origin."""
    p = linked.inputs / 'history.json'
    p.write_text(json.dumps({'tests': [{'phases': [{'report': f"<TestReport '{NODE}' when='call' outcome='failed'>"}], 'status': {'category': 'failed'}}]}))
    result = CaptureReplayReport(workspace=str(linked.workspace), output_dir='results')._run(historical_path='inputs/history.json')
    assert result['success'] and result['provenance'] == 'historical'
    a = analysis_payload(result['invocation_id'])
    a['failure_refs'] = ['inputs/history.json:1']
    update = UpdateCaseAnalysis(workspace=str(linked.workspace), output_dir='results')
    submit = SubmitReviewDecisions(workspace=str(linked.workspace), output_dir='results')
    assert update._run(cases=[{'case_id': NODE, 'analysis': a}])['success']
    assert not submit._run(**decisions_payload())['success']
    a['replay_blocker'] = 'Native package unavailable; historical report reviewed instead.'
    assert update._run(cases=[{'case_id': NODE, 'analysis': a}])['success']
    assert submit._run(**decisions_payload())['success']
    assert linked.case(NODE).executions[0].provenance == 'historical'


def test_multiple_runs_remain_distinct_and_import_is_idempotent(linked):
    """Repeated imports do not duplicate execution records or replace another run."""
    import_execution(linked)
    import_execution(linked, status='passed', invocation='b' * 32)
    import_execution(linked)
    assert [(e.invocation_id, e.status) for e in linked.case(NODE).executions] == [('a' * 32, 'failed'), ('b' * 32, 'passed')]


@pytest.mark.parametrize('value', ['../outside', 'x', 'a' * 32])
def test_wrong_or_absent_invocation_is_not_imported(linked, value):
    """An arbitrary ID cannot create a claimed execution."""
    assert not CaptureReplayReport(workspace=str(linked.workspace), output_dir='results')._run(invocation_id=value)['success']
    assert not linked.case(NODE).executions


def test_sessions_are_harvested_with_execution_identity(linked, monkeypatch):
    """Keep toffee-owned files under a durable session and bind them to the exact run."""
    session = linked.work / 'tests/data/toffee_tmp_20261026120000_123'
    session.mkdir(parents=True); (session / 'test_bad.fst').write_bytes(b'fixture')
    monkeypatch.setattr('ucagent.util.config.load_current_test_report', lambda _: {'context': {'invocation_id': 'a' * 32}})
    harvest_waveforms(linked)
    manifest = json.loads(linked.path('runs/waveforms/' + 'a' * 32 + '.json').read_text())
    assert len(manifest['sessions']) == 1
    assert (Path(manifest['sessions'][0]) / 'test_bad.fst').read_bytes() == b'fixture'
    assert not session.exists()


def test_full_collection_cannot_erase_missing_claim_association(linked):
    """A missing test stays reviewable as unresolved even if other tests collect."""
    review = linked.review(); review.options.full_regression_enabled = True; linked.save(review)
    source = linked.inputs / 'tests/test_demo.py'
    source.chmod(0o644)
    source.write_text('def test_unrelated():\n    assert True\n')
    result = CollectReviewCases(workspace=str(linked.workspace), output_dir='results')._run()
    assert not result['success']
    assert linked.review().claims[0].case_ids == [NODE]
    assert set(linked.review().cases) == {NODE}


def test_duplicate_raw_report_nodes_are_rejected(tmp_path):
    """Never silently overwrite one result with another result of the same identity."""
    case = {'phases': [{'report': f"<TestReport '{NODE}' when='call' outcome='failed'>"}],
            'status': {'category': 'failed'}}
    path = tmp_path / 'toffee_report.json'
    path.write_text(json.dumps({'tests': [case, case]}))
    with pytest.raises(ValueError, match='duplicate case identity'):
        report_outcomes(path)
