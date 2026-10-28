"""Cover single-record rendering, bounded evidence and optional raw waveform previews."""

import builtins
import json
import pytest
from bug_review.core.reporting import render_report
from bug_review.core.records import Review
from bug_review.tools import SubmitReviewDecisions, UpdateCaseAnalysis
from conftest import NODE, decisions_payload, analysis_payload


def test_single_record_drives_all_pages_and_detects_stale_views(analyzed):
    """Render complete generic pages from one table without a separate Case file tree."""
    layout = analyzed
    assert not (layout.out / 'cases').exists()
    record = json.loads((layout.out / 'review.json').read_text())
    assert record['cases'][NODE]['analysis']['failure_refs']
    assert record['context']['description']
    assert SubmitReviewDecisions(workspace=str(layout.workspace), output_dir='results')._run(**decisions_payload())['success']
    before = (layout.out / 'review.json').read_bytes()
    result = render_report(layout)
    assert result['manifest']['categories']['dut'] == 1
    assert result['manifest']['confirmed'] == 1
    bug = (layout.report / 'B001.html').read_text()
    assert 'An accepted request returns the wrong result' in bug
    assert 'expected 0, actual 1' in bug
    assert 'review.css' in bug
    assert before == (layout.out / 'review.json').read_bytes()
    render_report(layout, verify_only=True)
    (layout.report / 'B001.html').write_text('stale')
    with pytest.raises(ValueError, match='page missing or stale'):
        render_report(layout, verify_only=True)


def test_raw_waveform_available_with_analysis_disabled(analyzed):
    """Raw viewing does not manufacture a signed receipt or require the waveform stage."""
    layout = analyzed
    review = layout.review()
    raw = layout.work / 'session/test_bad.fst'
    raw.parent.mkdir(parents=True); raw.write_bytes(b'raw-fixture')
    review.cases[NODE].executions[0].waveform_files = [raw.relative_to(layout.out).as_posix()]
    layout.save(review)
    assert SubmitReviewDecisions(workspace=str(layout.workspace), output_dir='results')._run(**decisions_payload())['success']
    render_report(layout)
    assert layout.review().options.waveform_enabled is False
    assert not layout.review().cases[NODE].waveforms
    assert (layout.report / 'assets/waveform-entry.html').is_file()
    assert 'load_url' in (layout.report / 'assets/waveform-entry.html').read_text()
    assert 'waveform-entry.html' in (layout.report / 'index.html').read_text()
    raw.unlink()
    render_report(layout, verify_only=True)


def test_failure_citations_must_belong_to_selected_execution(analyzed):
    """A claim source cannot masquerade as the actual failed execution excerpt."""
    payload = analysis_payload(); payload['failure_refs'] = ['inputs/issues.md:4']
    result = UpdateCaseAnalysis(workspace=str(analyzed.workspace), output_dir='results')._run(
        cases=[{'case_id': NODE, 'analysis': payload}])
    assert result['success']
    from bug_review.core.validation import case_issues
    assert any(i['field'] == 'failure_refs' for i in case_issues(analyzed, analyzed.case(NODE)))


def test_markdown_reader_tables_images_and_missing_dependency(analyzed, monkeypatch):
    """Source readers retain exact line anchors and readable safe Markdown."""
    layout = analyzed
    (layout.workspace / 'plot.png').write_bytes(b'image-fixture')
    (layout.workspace / 'spec.md').write_text('\n# Requirement\n\nThe output must be zero.\n\n| Expected | Actual |\n| --- | --- |\n| 0 | 1 |\n\n![Figure](plot.png)\n\n<script>alert(1)</script>\n')
    assert SubmitReviewDecisions(workspace=str(layout.workspace), output_dir='results')._run(**decisions_payload())['success']
    render_report(layout)
    readers = [p.read_text() for p in (layout.report / 'assets').glob('source-*.html')]
    reader = next(s for s in readers if '&lt;script&gt;alert(1)' in s)
    assert '<table' in reader and 'id="L4"' in reader
    assert '<script>alert(1)</script>' not in reader
    assert 'source-media/plot.png' in reader
    original_import = builtins.__import__
    def without_markdown(name, *args, **kwargs):
        """Simulate a missing optional renderer dependency without uninstalling packages."""
        if name == 'markdown_it':
            raise ImportError('unavailable')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', without_markdown)
    with pytest.raises(ValueError, match='install the Bug Review plugin dependencies'):
        render_report(layout)


def test_narrative_and_machine_fields_have_distinct_write_contracts(analyzed):
    """Decision prose is mandatory; analysis submissions cannot rewrite execution facts."""
    payload = decisions_payload(); del payload['decisions'][0]['narrative']
    assert not SubmitReviewDecisions(workspace=str(analyzed.workspace), output_dir='results')._run(**payload)['success']
    payload = analysis_payload(); payload['executions'] = []
    assert not UpdateCaseAnalysis(workspace=str(analyzed.workspace), output_dir='results')._run(
        cases=[{'case_id': NODE, 'analysis': payload}])['success']
    Review.model_validate(json.loads((analyzed.out / 'review.json').read_text()))


def test_environment_abort_preserves_valid_case_results(analyzed):
    """A failed launch is visible separately and cannot replace the selected real failure."""
    from bug_review.tools import CaptureReplayReport
    invocation = 'b' * 32
    folder = analyzed.path(f'runs/reports/invocations/{invocation}')
    folder.mkdir(parents=True)
    (folder / 'report.json').write_text(json.dumps({'context': {'source': 'RunTestCases', 'invocation_id': invocation},
        'report': {'run_test_success': False, 'execution': {'diagnostic_code': 'PYTEST_PROCESS_ERROR'}}}))
    (folder / 'stderr.log').write_text('The native package cannot be loaded.\n')
    assert CaptureReplayReport(workspace=str(analyzed.workspace), output_dir='results')._run(invocation_id=invocation)['success']
    assert len(analyzed.case(NODE).executions) == 1
    assert analyzed.case(NODE).analysis.selected_execution == 'a' * 32
    assert analyzed.review().execution_issues[0].diagnostic == 'PYTEST_PROCESS_ERROR'
    assert SubmitReviewDecisions(workspace=str(analyzed.workspace), output_dir='results')._run(**decisions_payload())['success']
    result = render_report(analyzed)
    assert result['manifest']['failed_cases'] == 1
    assert 'PYTEST_PROCESS_ERROR' in (analyzed.report / 'index.html').read_text()
