"""Keep the portable server aligned with canonical report paths and private boundaries."""

from types import SimpleNamespace

from bug_review.report_server import ReportHandler


def test_canonical_report_and_surfer_resources_are_public(tmp_path):
    """Serve the actual generated layout without opening the private analysis directory."""
    report = tmp_path / 'demo/verification_review/report'
    (report / 'surfer').mkdir(parents=True)
    for filename in ['index.html', 'surfer/report-events.json', 'surfer/surfer.wasm']:
        target = report / filename
        target.write_text('resource')
    handler = SimpleNamespace(directory=str(tmp_path))
    for filename in ['index.html', 'surfer/report-events.json', 'surfer/surfer.wasm']:
        assert ReportHandler.translate_path(handler, '/demo/verification_review/report/' + filename) == str(report / filename)
    for path in ['/demo/report/index.html', '/demo/verification_review/analysis/review_index.json',
                 '/demo/.ucagent/waveinfo_receipts.json', '/demo/verification_review/report/%2e%2e/analysis/private.json']:
        assert ReportHandler.translate_path(handler, path) == str(tmp_path / '__report_path_not_found__')


def test_report_symlinks_cannot_expose_files_outside_the_public_root(tmp_path):
    """Both an escaping resource link and an escaping report root are rejected."""
    root = tmp_path / 'output'
    report = root / 'demo/verification_review/report'
    report.mkdir(parents=True)
    private = tmp_path / 'private.txt'
    private.write_text('private')
    (report / 'leak.txt').symlink_to(private)
    handler = SimpleNamespace(directory=str(root))
    assert ReportHandler.translate_path(handler, '/demo/verification_review/report/leak.txt') == str(root / '__report_path_not_found__')
    external = tmp_path / 'external-report'
    external.mkdir()
    (root / 'other/verification_review').mkdir(parents=True)
    (root / 'other/verification_review/report').symlink_to(external, target_is_directory=True)
    assert ReportHandler.translate_path(handler, '/other/verification_review/report/index.html') == str(root / '__report_path_not_found__')
