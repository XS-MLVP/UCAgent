"""Path-A compatibility controls through the real wrapper dispatcher, never real native code."""

import os

import pytest

from test_build_receipts import audit, receipt, tree_hash, workspace
from toffee_ut.checkers import ToffeeUTChecker
from toffee_ut.paths import digest, write_json


def grade(result, workspace, expected):
    """Require observable credit, checkable original references and the stated trust ceiling."""
    assert result['ok'], result
    evidence = result['build_evidence']
    assert evidence['credit'] == expected
    assert evidence['package'] == 'dut/Block'
    assert evidence['limitations']
    for row in evidence['receipts']:
        assert digest(workspace / 'ut_project' / row['path']) == row['sha256']
    if expected == 'legacy-input-recipe':
        assert evidence['receipts']
        assert any('No build-time output SHA' in text for text in evidence['limitations'])
        assert any('partial' in text for text in evidence['limitations'])
    return evidence


def test_legacy_intact_compatible_but_stale_inputs_rejected(workspace):
    path, _ = receipt(workspace, legacy=True)
    before = tree_hash(path.parent)
    intact = audit(workspace)
    (workspace / 'inputs/Block.sv').write_text('// source is now stale\n')
    stale = audit(workspace)
    grade(intact, workspace, 'legacy-input-recipe')
    assert not stale['ok'] and 'inputs' in stale['error']
    assert tree_hash(path.parent) == before


def test_legacy_two_fail_stale_success_and_unique_current_keep_raw(workspace):
    paths = [receipt(workspace, 'failed-A', ok=False, legacy=True)[0],
             receipt(workspace, 'failed-B', ok=False, legacy=True)[0],
             receipt(workspace, 'stale-success', legacy=True)[0]]
    before = {str(path): tree_hash(path.parent) for path in paths}
    (workspace / 'inputs/Block.sv').write_text('// current input\n')
    current, _ = receipt(workspace, 'arbitrary-current', legacy=True)
    result = grade(audit(workspace), workspace, 'legacy-input-recipe')
    assert result['receipts'] == [{'path': current.relative_to(workspace / 'ut_project').as_posix(),
                                   'sha256': digest(current)}]
    assert {str(path): tree_hash(path.parent) for path in paths} == before
    assert all(path.is_file() for path in paths)
    assert len(list((workspace / 'ut_project/results').glob('build-*/build.json'))) == 4
    print({'legacy_preserved_raw': before, 'unchanged_at_original_paths': True})


def test_legacy_multi_jobs_optional_timeout_and_time_not_semantics(workspace):
    first, _ = receipt(workspace, 'zzz-not-a-date', legacy=True, jobs=2)
    second, record = receipt(workspace, 'aaa-not-a-date', legacy=True, jobs=32)
    record['timeout'] = 10800
    write_json(second, record)
    os.utime(first, (2000000000, 2000000000))
    os.utime(second, (1, 1))
    result = grade(audit(workspace), workspace, 'legacy-input-recipe')
    assert len(result['receipts']) == 2


@pytest.mark.parametrize('option', [{'top': 'OtherTop'}, {'rtl_defines': ['MODE=2']}, {'timing': True}])
def test_legacy_valid_different_semantics_are_conflicts(workspace, option):
    receipt(workspace, 'one', legacy=True)
    receipt(workspace, 'two', legacy=True, **option)
    result = audit(workspace)
    assert not result['ok']
    assert 'Conflicting current native build contracts' in result['error']
    assert 'legacy-input-recipe' in result['error']
    assert 'build-one/build.json' in result['error'] and 'build-two/build.json' in result['error']


@pytest.mark.parametrize('fault', ['only_fail', 'wrong_class', 'export', 'package', 'escaped_input', 'escaped_package',
    'no_inputs', 'declared_input_missing', 'generated_recipe_bad', 'digest', 'input_target', 'logs', 'command',
    'output_path', 'top', 'options', 'macro', 'duplicate_macro', 'source_type', 'cancelled', 'source_changed', 'nonzero'])
def test_legacy_invalid_contract_is_not_a_success_vote(workspace, fault):
    options = {}
    if fault in {'declared_input_missing', 'generated_recipe_bad'}:
        (workspace / 'inputs/Dep.sv').write_text('// declared dependency\n')
        options['filelist'] = ['inputs/Dep.sv']
    if fault == 'macro':
        options['rtl_defines'] = ['BAD NAME=2']
    if fault == 'duplicate_macro':
        options['rtl_defines'] = ['MODE=1', 'MODE=2']
    if fault == 'source_type':
        (workspace / 'inputs/only.vh').write_text('// not a legal build source file\n')
        options['source_file'] = 'inputs/only.vh'
    path, record = receipt(workspace, legacy=True, ok=fault != 'only_fail', **options)
    package = workspace / 'ut_project/dut/Block'
    if fault == 'wrong_class':
        (package / '__init__.py').write_text('class DUTOther: pass\n')
    elif fault == 'export':
        record['options']['export_name'] = 'WrongExport'
    elif fault == 'package':
        record['package'] = 'dut/Other'
    elif fault == 'escaped_input':
        record['inputs']['../outside.sv'] = '0' * 64
    elif fault == 'escaped_package':
        outside = workspace.parent / (workspace.name + '-outside-init.py')
        outside.write_text('class DUTBlock: pass\n')
        (package / '__init__.py').unlink()
        (package / '__init__.py').symlink_to(outside)
    elif fault == 'no_inputs':
        record['inputs'] = {}
    elif fault == 'declared_input_missing':
        del record['inputs']['inputs/Dep.sv']
    elif fault == 'generated_recipe_bad':
        (path.parent / 'inputs.f').write_text('// false generated recipe\n')
    elif fault == 'digest':
        record['inputs']['inputs/Block.sv'] = '0' * 64
    elif fault == 'input_target':
        record['input_targets']['inputs/Block.sv'] = 'inputs/Other.sv'
    elif fault == 'logs':
        record['logs'] = 'results/build-other'
    elif fault == 'command':
        record['command'][record['command'].index('--sname') + 1] = 'UnrecordedTop'
    elif fault == 'output_path':
        record['command'][record['command'].index('--tdir') + 1] = '/outside/dut/Block'
    elif fault == 'top':
        record['top'] = 'WrongTop'
    elif fault == 'options':
        record['options'] = []
    elif fault == 'cancelled':
        record['interrupted'] = 'cancelled'
    elif fault == 'source_changed':
        record['source_changed'] = True
    elif fault == 'nonzero':
        record['returncode'] = 9
    write_json(path, record)
    result = audit(workspace)
    assert not result['ok'], (fault, result)
    assert result['error_code'] == 'UT_STAGE_EVIDENCE_MISSING'


@pytest.mark.parametrize('fault', ['output_mismatch', 'stale_inputs', 'failed_hashed', 'cancelled',
    'empty_identity', 'later_cancelled_replacement', 'bad_recipe'])
def test_new_format_never_falls_back_to_legacy(workspace, fault):
    path, record = receipt(workspace, 'new-format')
    if fault in {'output_mismatch', 'later_cancelled_replacement'}:
        (workspace / 'ut_project/dut/Block/libUTBlock.so').write_bytes(b'changed partial output\n')
    if fault == 'stale_inputs':
        (workspace / 'inputs/Block.sv').write_text('// changed source\n')
    elif fault == 'failed_hashed':
        record.update(ok=False, returncode=7)
    elif fault == 'cancelled':
        record['interrupted'] = 'cancelled'
    elif fault == 'empty_identity':
        record['package_files'] = {}
    elif fault == 'later_cancelled_replacement':
        receipt(workspace, 'later-cancelled', ok=False, legacy=True)
    elif fault == 'bad_recipe':
        record['command'][record['command'].index('--sname') + 1] = 'WrongTop'
    write_json(path, record)
    receipt(workspace, 'otherwise-valid-legacy', legacy=True)
    result = audit(workspace)
    assert not result['ok'], (fault, result)
    assert 'package-files' in result['error'] or 'Malformed native build receipt' in result['error']


def test_new_mode_legacy_different_recipe_does_not_vote(workspace):
    path, _ = receipt(workspace, 'new')
    receipt(workspace, 'legacy-competing', legacy=True, rtl_defines=['MODE=2'])
    evidence = grade(audit(workspace), workspace, 'package-files')
    assert evidence['receipts'] == [{'path': path.relative_to(workspace / 'ut_project').as_posix(), 'sha256': digest(path)}]


@pytest.mark.parametrize('legacy', [True, False])
def test_wrapper_checker_returns_credit_and_reference_without_loss(workspace, legacy):
    receipt(workspace, legacy=legacy)
    checker = ToffeeUTChecker(phase='wrapper', dut='Block')
    checker.set_workspace(str(workspace))
    ok, result = checker.do_check()
    assert ok
    grade(result, workspace, 'legacy-input-recipe' if legacy else 'package-files')


def test_legacy_does_not_claim_or_require_output_hashes(workspace, monkeypatch):
    receipt(workspace, legacy=True)

    def forbidden(*args):
        raise AssertionError('legacy-only must not claim a new output hash binding')

    monkeypatch.setattr('toffee_ut.build_receipts.package_files', forbidden)
    grade(audit(workspace), workspace, 'legacy-input-recipe')


def test_receipt_free_adoption_with_unrelated_receipt_is_unchanged(workspace):
    path, record = receipt(workspace, 'only-other-dut')
    record['package'] = 'dut/Other'
    record['command'][record['command'].index('--tdir') + 1] = str(workspace / 'ut_project/dut/Other')
    write_json(path, record)
    grade(audit(workspace), workspace, 'receipt-free-adoption')


@pytest.mark.parametrize('fault', ['none', 'add_header', 'delete_header', 'retarget_same_bytes'])
def test_legacy_include_closure_and_links_remain_current_obligations(workspace, fault):
    headers = workspace / 'inputs/headers'
    headers.mkdir()
    (headers / 'one.svh').write_text('// equal bytes\n')
    (headers / 'two.svh').write_text('// equal bytes\n')
    (headers / 'alias.svh').symlink_to(headers / 'one.svh')
    (workspace / 'inputs/Block.sv').write_text('`include "alias.svh"\n')
    receipt(workspace, legacy=True, include_dirs=['inputs/headers'])
    if fault == 'add_header':
        (headers / 'new.svh').write_text('// new member\n')
    elif fault == 'delete_header':
        (headers / 'two.svh').unlink()
    elif fault == 'retarget_same_bytes':
        (headers / 'alias.svh').unlink()
        (headers / 'alias.svh').symlink_to(headers / 'two.svh')
    result = audit(workspace)
    if fault == 'none':
        grade(result, workspace, 'legacy-input-recipe')
    else:
        assert not result['ok'] and 'input_targets or include_directories' in result['error']
