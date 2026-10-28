"""Verify Bug-group navigation, bounded reuse and atomic shared-field submissions."""

import json
import pytest
from bug_review.core.records import Case, Claim, Execution
from bug_review.tools import ReviewContext, ReviewWorkQueue, UpdateCaseAnalysis
from conftest import NODE, analysis_payload, import_execution


def add_group(layout, count=7):
    """Create overlapping canonical claim memberships without executing fixture code."""
    review = layout.review()
    nodes = [NODE] + [f'tests/test_demo.py::test_bad[p{i}]' for i in range(1, count)]
    for index, node in enumerate(nodes[1:], 2):
        review.cases[node] = Case(case_id=node, case_key=f'C{index:04}', waveform_test_case_name=node)
    review.claims[0].case_ids = nodes
    review.claims.append(Claim(**{**review.claims[0].model_dump(), 'claim_id': 'B002', 'case_ids': nodes[-2:]}))
    layout.save(review)
    return nodes


def test_queue_groups_by_claim_and_pages_without_source_payloads(linked):
    """One Bug returns up to five pending members with bounded task diagnostics."""
    nodes = add_group(linked)
    before = (linked.out / 'review.json').read_bytes()
    result = ReviewWorkQueue(workspace=str(linked.workspace), output_dir='results')._run()
    group = result['next_group']
    assert group['claim_id'] == 'B001'
    assert [c['case_id'] for c in group['cases']] == nodes[:5]
    assert group['next_offset'] == 5
    assert len(result['issues']) == 5 and result['remaining'] > 0
    assert 'source_context' not in json.dumps(result)
    page = ReviewContext(workspace=str(linked.workspace), output_dir='results')._run(claim_id='B001', offset=5)
    assert [c['case_id'] for c in page['cases']] == nodes[5:]
    assert page['next_offset'] is None
    assert (linked.out / 'review.json').read_bytes() == before


def test_completed_overlap_is_reused_without_repeating_work(analyzed):
    """Ready overlapping members stay ready while group reuse points to original sources."""
    nodes = add_group(analyzed, 3)
    review = analyzed.review()
    review.claims[0].case_ids = [NODE]
    review.claims[1].case_ids = [NODE, *nodes[1:]]
    analyzed.save(review)
    tool = ReviewWorkQueue(workspace=str(analyzed.workspace), output_dir='results')
    result = tool._run()
    assert result['next_group']['claim_id'] == 'B002'
    assert [c['case_id'] for c in result['next_group']['cases']] == nodes[1:]
    assert result['next_group']['reusable_evidence'][0]['spec_refs'] == ['spec.md:4']
    context = ReviewContext(workspace=str(analyzed.workspace), output_dir='results')._run(claim_id='B002', pending_only=False)
    assert len(context['cases']) == 3


@pytest.mark.parametrize('args', [{'claim_id': 'B999'}, {'claim_id': 'B001', 'case_id': NODE}, {'claim_id': 'B001', 'limit': 6}])
def test_group_lookup_errors_are_explicit(linked, args):
    """Invalid group identity or unbounded requests cannot silently select another task."""
    result = ReviewContext(workspace=str(linked.workspace), output_dir='results')._run(**args)
    assert not result['success'] and result['next_action']


def test_shared_fields_expand_without_sharing_verdicts_or_machine_evidence(linked):
    """Merge common citations and text while retaining each Case's own classification."""
    nodes = add_group(linked, 2)
    for node in nodes:
        import_execution(linked, node=node)
    a = analysis_payload(); shared = {key: a.pop(key) for key in (
        'specification_expected', 'test_validity', 'timing_review', 'source_refs', 'spec_refs', 'rtl_refs')}
    b = {**a, 'category': 'test', 'reasoning': 'This member has a different assertion problem.',
         'test_validity': 'Case-specific review overrides the common statement.',
         'source_refs': ['inputs/tests/test_demo.py:3-4']}
    before = [linked.case(n).executions for n in nodes]
    result = UpdateCaseAnalysis(workspace=str(linked.workspace), output_dir='results')._run(
        shared=shared, cases=[{'case_id': n, 'analysis': item} for n, item in zip(nodes, [a, b])])
    assert result['success'], result
    first, second = [linked.case(n) for n in nodes]
    assert first.analysis.category == 'dut' and second.analysis.category == 'test'
    assert first.analysis.test_validity == shared['test_validity']
    assert second.analysis.test_validity == b['test_validity']
    assert second.analysis.source_refs == shared['source_refs']
    assert first.analysis.spec_refs == shared['spec_refs']
    assert [linked.case(n).executions for n in nodes] == before
    assert 'shared' not in json.loads((linked.out / 'review.json').read_text())


@pytest.mark.parametrize('fault', ['bad_shared_ref', 'unknown_member', 'duplicate', 'shared_outcome', 'missing_failure'])
def test_shared_batch_is_atomic_and_does_not_weaken_case_validation(linked, fault):
    """A failed batch never replaces records; shared text cannot create execution evidence."""
    import_execution(linked)
    before = (linked.out / 'review.json').read_bytes()
    a = analysis_payload(); args = {'shared': {'spec_refs': ['spec.md:4']}, 'cases': [{'case_id': NODE, 'analysis': a}]}
    if fault == 'bad_shared_ref': args['shared']['rtl_refs'] = ['demo.sv:999']
    elif fault == 'unknown_member': args['cases'].append({'case_id': 'unknown', 'analysis': a})
    elif fault == 'duplicate': args['cases'] *= 2
    elif fault == 'shared_outcome': args['shared']['selected_execution'] = 'forged'
    else: a['failure_refs'] = []
    result = UpdateCaseAnalysis(workspace=str(linked.workspace), output_dir='results')._run(**args)
    if fault == 'missing_failure':
        assert result['success']
        queue = ReviewWorkQueue(workspace=str(linked.workspace), output_dir='results')._run()
        assert queue['case_progress']['ready'] == 0
        assert 'failure_refs' in queue['next_group']['cases'][0]['missing_fields']
    else:
        assert not result['success']
        assert (linked.out / 'review.json').read_bytes() == before


def test_group_digest_bounds_long_analysis_and_keeps_selected_execution(analyzed):
    """Context growth follows the page size rather than source/history volume."""
    case = analyzed.case(NODE); selected = case.executions[0]
    case.analysis.reasoning = 'x' * 100000
    for i in range(10):
        case.executions.append(Execution(**{**selected.model_dump(), 'invocation_id': f'{i:032}'}))
    analyzed.save_case(case)
    result = ReviewContext(workspace=str(analyzed.workspace), output_dir='results')._run(claim_id='B001', pending_only=False)
    member = result['cases'][0]
    assert len(member['reasoning']) == 500 and member['reasoning_truncated']
    assert member['execution_count'] == 11 and len(member['executions']) <= 3
    assert member['selected_execution'] in [e['invocation_id'] for e in member['executions']]
    assert len(json.dumps(result)) < 6000


def test_reference_reader_bounds_generated_long_lines(linked):
    """Line-limited citations must also cap a generated source's character volume."""
    from bug_review.tools import ReviewRefCheck
    (linked.workspace / 'long.sv').write_text('x' * 30000 + '\nshort line\n')
    tool = ReviewRefCheck(workspace=str(linked.workspace), output_dir='results')
    result = tool._run(refs=['long.sv:1-2', 'long.sv:2'])
    assert result['success']
    assert len(result['sources'][0]['text']) == 2000
    assert result['sources'][0]['truncated']
    assert not result['sources'][1]['truncated']
    assert 'short line' in result['sources'][1]['text']
