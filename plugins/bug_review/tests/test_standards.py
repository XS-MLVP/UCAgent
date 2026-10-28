"""Verify separately downloaded standards, provenance and clause-based review."""

import importlib.util
import json
from pathlib import Path
import subprocess
import pytest

from bug_review.core.layout import Layout, prepare_execution
from bug_review.tools import PrepareReviewInputs, UpdateCaseAnalysis, SubmitReviewDecisions
from conftest import NODE, analysis_payload, import_execution, decisions_payload

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not (ROOT / 'src/bug_review/references/catalog.json').is_file(),
                    reason='Optional upstream snapshots have not been downloaded')
def test_complete_downloaded_library_has_every_attributed_source():
    """Real downloaded trees include full documentation/assets and pinned provenance."""
    library = ROOT / 'src/bug_review/references'
    catalog = json.loads((library / 'catalog.json').read_text())
    assert {s['family'] for s in catalog['sources']} == {'riscv', 'xiangshan', 'chisel'}
    for source in catalog['sources']:
        assert len(source['revision']) == 40
        assert source['retrieved_at'] and source['commit_time']
        assert (library / source['license']).is_file()
        for entry in source['entry_points']:
            assert (library / entry).exists()
        files = list((library / source['snapshot']).rglob('*'))
        assert sum(p.is_file() for p in files) == source['file_count']
        assert not any(p.name == '.git' for p in files)
    assert (library / 'riscv/src/priv/supervisor.adoc').exists()
    assert (library / 'riscv/docs-resources').is_dir()
    interfaces = library / 'chisel/docs/src/explanations/interfaces-and-connections.md'
    text = interfaces.read_text()
    assert 'DecoupledIO' in text and 'IrrevocableIO' in text


def test_missing_library_has_setup_action_without_creating_review(tmp_path, monkeypatch):
    """A clean source checkout explains the explicit download prerequisite."""
    import bug_review.core.layout as paths
    monkeypatch.setattr(paths, 'BUNDLED_STANDARDS', tmp_path / 'not-downloaded')
    source = tmp_path / 'unity_test'; source.mkdir()
    (source / 'issue.md').write_text('Original claim.')
    result = PrepareReviewInputs(workspace=str(tmp_path), output_dir='results')._run()
    assert not result['success']
    assert 'scripts/download_standards.py' in str(result)
    assert not (tmp_path / 'results').exists()


def test_reference_archive_is_not_claim_input_or_test_copy(prepared):
    """Every run can cite standards offline without expanding claim scope or pytest inputs."""
    catalog = prepared.inputs / 'review_standards/catalog.json'
    assert catalog.is_file()
    assert prepared.review().source_documents == ['inputs/issues.md']
    assert prepared.source('inputs/review_standards/chisel.txt:1-2')['text']
    assert (prepared.inputs / 'review_standards/chisel.txt').stat().st_mode & 0o222 == 0
    prepare_execution(prepared)
    assert not (prepared.work / 'review_standards').exists()


def test_applicable_standard_can_confirm_without_project_spec(linked):
    """A local upstream clause is valid independent evidence for a real reviewed failure."""
    invocation = import_execution(linked)
    analysis = analysis_payload(invocation)
    analysis['spec_refs'] = ['inputs/review_standards/riscv.txt:1-2']
    assert UpdateCaseAnalysis(workspace=str(linked.workspace), output_dir='results')._run(
        cases=[{'case_id': NODE, 'analysis': analysis}])['success']
    result = SubmitReviewDecisions(workspace=str(linked.workspace), output_dir='results')._run(**decisions_payload())
    assert result['success'], result
    assert linked.review().decisions[0].verdict == 'confirmed'


def test_catalog_is_provenance_not_a_normative_clause(linked):
    """A family name or revision cannot substitute for an actual applicable requirement."""
    invocation = import_execution(linked)
    analysis = analysis_payload(invocation)
    analysis['spec_refs'] = ['inputs/review_standards/catalog.json:1']
    update = UpdateCaseAnalysis(workspace=str(linked.workspace), output_dir='results')
    assert update._run(cases=[{'case_id': NODE, 'analysis': analysis}])['success']
    result = SubmitReviewDecisions(workspace=str(linked.workspace), output_dir='results')._run(**decisions_payload())
    assert not result['success'] and 'original standard clause' in str(result)


def test_missing_family_fails_before_creating_review(tmp_path, standards_library):
    """Never silently reduce the required reference families when packaging is incomplete."""
    source = tmp_path / 'unity_test'; source.mkdir(); (source / 'issue.md').write_text('Original claim.')
    path = standards_library / 'catalog.json'; value = json.loads(path.read_text())
    value['sources'] = value['sources'][:2]; path.write_text(json.dumps(value))
    result = PrepareReviewInputs(workspace=str(tmp_path), output_dir='results')._run()
    assert not result['success'] and not (tmp_path / 'results/review.json').exists()


def test_download_copies_full_trees_and_refreshes_branch_tip(tmp_path, monkeypatch):
    """Use a real local Git upstream to test nested assets, provenance and latest updates."""
    spec = importlib.util.spec_from_file_location('download_standards', ROOT / 'scripts/download_standards.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    upstream = tmp_path / 'upstream'; upstream.mkdir()
    subprocess.run(['git', 'init', '-b', 'main', str(upstream)], check=True, capture_output=True)
    (upstream / 'docs/nested').mkdir(parents=True)
    (upstream / 'LICENSE').write_text('Original license.')
    (upstream / 'docs/nested/image.bin').write_bytes(bytes(range(256)))
    (upstream / 'docs/requirements.txt').write_text('First requirement.\n')
    for command in [['add', '.'], ['-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'Initial docs']]:
        subprocess.run(['git', '-C', str(upstream), *command], check=True, capture_output=True)
    sources = [{'id': family, 'family': family, 'title': family, 'repository': str(upstream),
                'branch': 'main', 'paths': None, 'entry_points': ['docs'], 'applicability': 'Test clauses.'}
               for family in ['riscv', 'xiangshan', 'chisel']]
    monkeypatch.setattr(module, 'SOURCES', sources)
    destination = tmp_path / 'snapshots'; cache = tmp_path / 'cache'
    first = module.download(destination, cache)
    for family in ['riscv', 'xiangshan', 'chisel']:
        assert (destination / family / 'docs/nested/image.bin').read_bytes() == bytes(range(256))
        assert not (destination / family / '.git').exists()
    (upstream / 'docs/requirements.txt').write_text('Updated requirement.\n')
    subprocess.run(['git', '-C', str(upstream), 'add', '.'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(upstream), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'Update docs'], check=True, capture_output=True)
    second = module.download(destination, cache)
    assert second['sources'][0]['revision'] != first['sources'][0]['revision']
    assert (destination / 'riscv/docs/requirements.txt').read_text() == 'Updated requirement.\n'
    # A changed upstream layout must leave the last complete library intact.
    before = (destination / 'catalog.json').read_bytes()
    sources[0]['entry_points'] = ['missing']
    with pytest.raises(ValueError, match='entry point missing'):
        module.download(destination, cache)
    assert (destination / 'catalog.json').read_bytes() == before
    sources[0]['entry_points'] = ['docs']
    (cache / 'riscv/docs/requirements.txt').write_text('Uncommitted local edits.\n')
    with pytest.raises(ValueError, match='cache contains local changes'):
        module.download(destination, cache)
    assert (destination / 'catalog.json').read_bytes() == before
