"""Small current-contract fixtures; no generated user workspaces are modified."""

import json
from pathlib import Path
import pytest
from bug_review.core.layout import Layout
from bug_review.core.records import Options
from bug_review.tools import PrepareReviewInputs, SubmitReviewClaims, CaptureReplayReport, UpdateCaseAnalysis

NODE = 'tests/test_demo.py::test_bad'


@pytest.fixture(autouse=True)
def standards_library(tmp_path, monkeypatch):
    """Use tiny complete-contract sources in unit runs; real bundle is checked separately."""
    import bug_review.core.layout as paths
    library = tmp_path / 'bundled-standards'; library.mkdir()
    sources = []
    for family in ['riscv', 'xiangshan', 'chisel']:
        document = library / (family + '.txt')
        document.write_text('Original upstream requirement.\nA response must belong to its accepted request.\n')
        sources.append({'id': family, 'family': family, 'revision': 'a' * 40,
                        'entry_points': [document.name]})
    (library / 'catalog.json').write_text(json.dumps({'schema': 'bug_review_standards.v1', 'sources': sources}))
    monkeypatch.setattr(paths, 'BUNDLED_STANDARDS', library)
    return library


@pytest.fixture
def prepared(tmp_path):
    """Inventory one free-form original claim plus independent specification and RTL."""
    source = tmp_path / 'unity_test'
    (source / 'tests').mkdir(parents=True)
    (source / 'issues.md').write_text('\n# Original observations\n\nThe accepted request returned 1 instead of 0.\n')
    (source / 'tests/test_demo.py').write_text('"""Small actual failure."""\n\ndef test_bad():\n    assert 1 == 0\n\ndef test_unrelated():\n    assert True\n')
    (tmp_path / 'spec.md').write_text('\n# Requirement\n\nThe output of an accepted request must be zero.\n')
    (tmp_path / 'demo.sv').write_text('module demo(output logic out);\nassign out = 1;\nendmodule\n')
    result = PrepareReviewInputs(workspace=str(tmp_path), output_dir='results', module='demo')._run()
    assert result['success'], result
    return Layout(tmp_path, 'results')


def claim_payload(node=NODE):
    """Return fields supplied by the reviewer, not a parsed BG template."""
    return {'context': context_payload(), 'claims': [{'claim_id': 'B001', 'title': 'Incorrect result',
                       'statement': 'An accepted request returned 1 instead of 0.',
                       'source_refs': ['inputs/issues.md:4'], 'case_ids': [node],
                       'mapping_reason': 'The report and assertion describe the same request.'}],
            'source_reviews': [{'path': 'inputs/issues.md', 'disposition': 'claims', 'reason': 'One stated failure.'}]}


@pytest.fixture
def linked(prepared):
    """Generate one exact Case without executing tests."""
    result = SubmitReviewClaims(workspace=str(prepared.workspace), output_dir='results')._run(**claim_payload())
    assert result['success'], result
    return prepared


def import_execution(layout, status='failed', invocation='a' * 32, node=NODE):
    """Write a minimal tool-originated invocation fixture and import exact facts."""
    directory = layout.path(f'runs/reports/invocations/{invocation}')
    directory.mkdir(parents=True, exist_ok=True)
    payload = {'context': {'source': 'RunTestCases', 'invocation_id': invocation},
               'report': {'tests': {'test_cases': {node: status.upper()}}}}
    (directory / 'report.json').write_text(json.dumps(payload))
    (directory / 'stdout.log').write_text(f'{node}: expected 0, actual 1\n')
    result = CaptureReplayReport(workspace=str(layout.workspace), output_dir='results')._run(invocation_id=invocation)
    assert result['success'], result
    return invocation


def analysis_payload(invocation='a' * 32, category='dut'):
    """Describe reviewed semantics with real independent sources."""
    return {'category': category, 'scenario': 'An accepted request completes.',
            'specification_expected': 'Zero per independent requirement.', 'test_expected': 'Zero.',
            'actual': 'The imported report records failure.', 'test_validity': 'The assertion implements the requirement.',
            'timing_review': 'No sequential sampling in this combinational example.',
            'reasoning': 'The output differs from its required value.',
            'source_refs': ['inputs/tests/test_demo.py:3-4'], 'spec_refs': ['spec.md:4'],
            'rtl_refs': ['demo.sv:1-3'], 'selected_execution': invocation,
            'failure_refs': [f'runs/reports/invocations/{invocation}/stdout.log:1'] if invocation else []}


@pytest.fixture
def analyzed(linked):
    """Import and analyze a failure with no waveform or optional Skill directory."""
    import_execution(linked)
    result = UpdateCaseAnalysis(workspace=str(linked.workspace), output_dir='results')._run(
        cases=[{'case_id': NODE, 'analysis': analysis_payload()}])
    assert result['success'], result
    return linked


def decisions_payload(verdict='confirmed'):
    """Confirm the external failure without inventing an internal observed root."""
    return {'decisions': [{'claim_id': 'B001', 'verdict': verdict,
                          'reasoning': 'Independent specification and the actual failed test agree on the violation.',
                          'narrative': narrative_payload(), 'next_action': 'Correct the output and rerun the exact Case.',
                          'case_ids': [NODE], 'source_refs': ['spec.md:4', 'inputs/tests/test_demo.py:3-4']}],
            'roots': []}



def context_payload():
    """Supply stage-one module purpose and scope without inventing a design revision."""
    return {'description': 'One output is checked against an independent requirement.',
            'scope': 'Module-level combinational test; no full-chip or fix verification.',
            'version': 'Provided RTL; upstream revision unknown.', 'source_refs': ['inputs/issues.md:4']}


def narrative_payload():
    """Provide the complete decision-stage narrative used by the generic templates."""
    return {'title': 'An accepted request returns the wrong result',
            'summary': 'The output is one while the independent requirement expects zero.',
            'expected_behavior': 'The accepted request must produce zero.',
            'trigger_steps': ['Run the original test.', 'Observe the actual assertion failure.'],
            'comparisons': [{'condition': 'Accepted request', 'expected': '0', 'actual': '1',
                             'source_refs': ['spec.md:4', 'inputs/tests/test_demo.py:3-4']}],
            'cause_analysis': 'The provided RTL drives a constant one; this is static inference.',
            'impact': ['The module output violates its stated functional requirement.'],
            'scope': 'One module and the provided configuration. No fix has been tested.'}
