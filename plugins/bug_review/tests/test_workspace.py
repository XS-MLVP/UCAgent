"""Check output boundaries, original input preservation and public Make preparation."""

import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

from bug_review.core.layout import Layout, prepare_execution
from bug_review.core.json_io import atomic_write_json
from bug_review.workspace import prepare
from bug_review.tools import PrepareReviewInputs
from bug_review.report_server import ReportHandler
from bug_review.publishing import rebuild_portal
from types import SimpleNamespace


def test_prepare_archives_inputs_without_modifying_source(prepared):
    """Inputs are read-only while execution gets an independent copy with test data."""
    original = prepared.workspace / 'unity_test/tests/test_demo.py'
    before = original.read_bytes()
    asset = prepared.inputs / 'tests/data/lookup.txt'
    asset.parent.mkdir(); asset.write_text('test asset')
    prepare_execution(prepared)
    assert (prepared.work / 'tests/data/lookup.txt').read_text() == 'test asset'
    (prepared.work / 'tests/test_demo.py').write_text('local execution scratch')
    assert original.read_bytes() == before
    assert (prepared.inputs / 'tests/test_demo.py').read_bytes() == before
    assert (prepared.inputs / 'tests/test_demo.py').stat().st_mode & 0o222 == 0


@pytest.mark.parametrize('path', ['../escape', '/tmp/external', 'unity_test', 'unity_test/nested', '.'])
def test_output_cannot_overlap_or_escape(tmp_path, path):
    """Reject invalid outputs before reading or writing any files."""
    with pytest.raises(ValueError): Layout(tmp_path, path)


@pytest.mark.parametrize('reference', ['../outside.py:1', '/tmp/private:1', 'spec.md:999', 'results/review.json:1'])
def test_source_references_do_not_escape_or_self_support(prepared, reference):
    """Source evidence cannot come from private external files or the conclusion itself."""
    with pytest.raises(ValueError): prepared.source(reference)


def test_symlink_input_is_rejected(tmp_path):
    """Source symlinks are not followed into unrelated files."""
    source = tmp_path / 'unity_test';source.mkdir()
    outside = tmp_path / 'secret';outside.write_text('private')
    (source / 'report.md').symlink_to(outside)
    result = PrepareReviewInputs(workspace=str(tmp_path), output_dir='results')._run()
    assert not result['success'] and not (tmp_path / 'results/review.json').exists()


def test_custom_output_and_historical_report_archive(tmp_path):
    """OUT is resolved rather than hardcoded; supplied historic reports remain accessible."""
    (tmp_path / 'unity_test').mkdir(); (tmp_path / 'unity_test/notes.md').write_text('Original report.')
    (tmp_path / 'uc_test_report').mkdir(); (tmp_path / 'uc_test_report/toffee_report.json').write_text('{}')
    result = PrepareReviewInputs(workspace=str(tmp_path), output_dir='custom', module='demo')._run()
    assert result['success'], result
    assert (tmp_path / 'custom/inputs/uc_test_report/toffee_report.json').exists()
    assert not (tmp_path / 'results').exists()


def test_public_make_uses_fresh_workspace(tmp_path):
    """Make preparation does not require launch.yaml, picker or an importable native DUT."""
    source = tmp_path / 'sources/demo/unity_test'; source.mkdir(parents=True)
    (source / 'issues.md').write_text('Unstructured original Bug description.')
    makefile = Path(__file__).resolve().parents[1] / 'Makefile'
    command = ['make', '-f', str(makefile), 'init_demo', f'INPUT_ROOT={source.parent.parent}',
               f'OUTPUT_ROOT={tmp_path / "new-run"}', f'PYTHON={sys.executable}']
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / 'new-run/demo/unity_test/issues.md').exists()
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert (source / 'issues.md').read_text() == 'Unstructured original Bug description.'


def test_portal_and_server_keep_inputs_private(tmp_path):
    """Publishing exposes report pages, not original archives or Case JSON."""
    report = tmp_path / 'demo/custom/report';report.mkdir(parents=True)
    (report / 'index.html').write_text('public')
    atomic_write_json(report / 'manifest.json', {'schema': 'bug_review_report.v6', 'workspace': 'demo',
        'module': 'demo', 'claims': 3, 'confirmed': 2, 'unresolved': 1, 'review_status': 'incomplete'})
    portal = rebuild_portal(tmp_path)
    assert 'demo/custom/report/index.html' in portal.read_text()
    assert (tmp_path / 'serve.py').exists()
    handler = SimpleNamespace(directory=str(tmp_path))
    assert ReportHandler.translate_path(handler, '/demo/custom/report/index.html') == str(report / 'index.html')
    for name in ['inputs/issues.md', 'review.json', 'runs/reports/invocations/id/report.json']:
        assert '__report_path_not_found__' in ReportHandler.translate_path(handler, '/demo/custom/' + name)



def test_native_readonly_input_directories_allow_archive_and_execution(tmp_path):
    """Native Agent source protection must not block report archival or test writes."""
    source = tmp_path / 'unity_test'
    (source / 'tests/data').mkdir(parents=True)
    (source / 'notes.md').write_text('Original Bug report.')
    (source / 'tests/test_demo.py').write_text('def test_demo(): pass\n')
    (tmp_path / 'uc_test_report').mkdir()
    (tmp_path / 'uc_test_report/toffee_report.json').write_text('{}')
    for path in [source, *source.rglob('*')]:
        path.chmod(0o555 if path.is_dir() else 0o444)
    try:
        result = PrepareReviewInputs(workspace=str(tmp_path), output_dir='results')._run()
        assert result['success'], result
        layout = Layout(tmp_path, 'results')
        assert (layout.inputs / 'uc_test_report/toffee_report.json').exists()
        prepare_execution(layout)
        (layout.work / 'tests/data/session').mkdir()
        (layout.work / 'tests/data/session/out.txt').write_text('actual output')
        assert source.stat().st_mode & 0o222 == 0
        assert (source / 'tests/test_demo.py').read_text() == 'def test_demo(): pass\n'
    finally:
        for path in [tmp_path, *tmp_path.rglob('*')]:
            if path.is_dir(): path.chmod(path.stat().st_mode | 0o700)



def test_source_prefix_error_names_exact_canonical_repair(prepared):
    """Reject the wrong source spelling with the precise current-format replacement."""
    with pytest.raises(ValueError, match='use source reference inputs/issues.md:4'):
        prepared.source('results/inputs/issues.md:4')
    assert prepared.source('inputs/issues.md:4')['text']



def test_resumed_execution_copy_restores_fixture_write_access(prepared):
    """A second startup may protect existing paths; collection must repair its copy."""
    prepare_execution(prepared)
    for path in [prepared.work, *prepared.work.rglob('*')]:
        path.chmod(0o555 if path.is_dir() else 0o444)
    prepare_execution(prepared)
    (prepared.work / 'tests/new-session').mkdir()
    assert (prepared.inputs / 'tests/test_demo.py').stat().st_mode & 0o222 == 0
