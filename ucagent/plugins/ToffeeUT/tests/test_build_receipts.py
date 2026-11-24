"""Wrapper entry-point regressions using text/ELF-marker assets, never native execution."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys

import pytest
import yaml

from toffee_ut.audit import audit_project
from toffee_ut.build import build_dut
from toffee_ut.paths import digest, write_json
from toffee_ut.project import scaffold


@pytest.fixture(scope='session', autouse=True)
def import_identity():
    """Record the actual interpreter/loaded modules and enforce this command's isolated tree."""
    yield
    expected = Path(os.environ['TOFFEE_UT_EXPECTED_SRC']).resolve()
    modules = {name: module.__file__ for name, module in tuple(sys.modules.items())
               if name == 'toffee_ut' or name.startswith('toffee_ut.')}
    assert modules
    assert all(Path(path).resolve().is_relative_to(expected) for path in modules.values()), modules
    print(json.dumps(dict(python=sys.executable, argv=sys.argv, cwd=os.getcwd(),
                          expected_src=str(expected), imported_modules=modules, all_isolated=True)))


def contract(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n# Synthetic contract\n\n```yaml\n' + yaml.safe_dump(data) + '```\n')


@pytest.fixture
def workspace(tmp_path):
    """Prepare standalone contracts and non-loadable package assets; no DUT implementation."""
    (tmp_path / 'inputs').mkdir()
    (tmp_path / 'inputs/interface.md').write_text('Independent identity requirement.\n')
    (tmp_path / 'inputs/Block.sv').write_text('// synthetic input, never compiled\n')
    scaffold(tmp_path, 'Block')
    root = tmp_path / 'ut_project'
    contract(root / 'docs/spec/design/Block.md', {
        'kind': 'design', 'dut': 'Block', 'requirements': [dict(id='R1', statement='Identity',
        precondition='Legal', observation='Response', timing='On response',
        source='inputs/interface.md', basis='confirmed')]})
    contract(root / 'docs/spec/verification/Block.md', {
        'kind': 'verification', 'dut': 'Block', 'scenarios': [dict(id='S1', requirement='R1',
        stimulus='One input', expected='Identity', oracle='Independent text', completion='Compare', status='active')]})
    package = root / 'dut/Block'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text('class DUTBlock:\n    pass\n')
    (package / 'libUTBlock.so').write_bytes(b'\x7fELF synthetic, NOT loadable\n')
    (package / 'Block_top.sv').write_text('// native output marker only\n')
    (package / 'Block.xscfg').write_text('{"synthetic": true}\n')
    return tmp_path


def files(workspace):
    """Independent fixture output fingerprint, using declared stable identity assets only."""
    package = workspace / 'ut_project/dut/Block'
    return {p.name: digest(p) for p in package.iterdir()
            if p.name == '__init__.py' or p.suffix in {'.so', '.sv', '.xscfg'}}


def receipt(workspace, name='current', *, ok=True, legacy=False, **options):
    """Emit the existing structured producer schema, optionally with candidate output identity."""
    root = workspace / 'ut_project'
    log = root / f'results/build-{name}'
    log.mkdir(parents=True)
    opts = dict(source_file='inputs/Block.sv', filelist=[], include_dirs=[], timing=False,
                rtl_defines=[], top='Block', export_name='Block', jobs=2)
    opts.update(options)
    sources = [workspace / p for p in [opts['source_file'], *opts['filelist']]]
    includes = [workspace / p for p in opts['include_dirs']]
    # Reuse the real snapshot producer, but never the selector under test.
    from toffee_ut.build import _input_snapshot
    snapshot = _input_snapshot(workspace, sources, includes, root)
    extra, generated = [], {}
    if sources[1:] or includes:
        recipe = log / 'inputs.f'
        recipe.write_text(''.join(f'"+incdir+{p}"\n' for p in includes) + ''.join(f'"{p}"\n' for p in sources[1:]))
        generated = {'inputs.f': digest(recipe)}
        extra += ['--fs', str(recipe)]
    if opts['timing']:
        extra += ['-V', '--timing']
    for define in opts['rtl_defines']:
        extra += ['--rtl-define', define]
    record = dict(ok=ok, command=['/controlled/picker', 'export', str(sources[0]), *extra,
        '--sim', 'verilator', '--rw', 'mem_direct', '--sname', opts['top'], '--tname', opts['export_name'],
        '--tdir', str(root / 'dut/Block'), '-c', '-w', str(log / 'layout.fst'), '-j', str(opts['jobs'])],
        returncode=0 if ok else 7, interrupted='' if ok else 'timeout', source_changed=False,
        **snapshot, options=opts, generated_inputs=generated, changed_inputs=[], execution_error='',
        input_error='', top=opts['top'], package='dut/Block', logs=log.relative_to(root).as_posix())
    if not legacy:
        record['package_files'] = files(workspace)
    write_json(log / 'build.json', record)
    (log / 'stdout.log').write_text('original synthetic stdout\n')
    (log / 'stderr.log').write_text('original synthetic stderr\n')
    return log / 'build.json', record


def audit(workspace):
    result = audit_project(workspace, 'Block', phase='wrapper')
    print(json.dumps(result, sort_keys=True))
    return result


def tree_hash(root):
    return {str(p): digest(p) for p in root.rglob('*') if p.is_file()}


def test_historical_failures_then_current_success(workspace):
    """Two preserved historical FAILs are not permanent vetoes; run the real wrapper entry."""
    old = [receipt(workspace, '033256', ok=False, legacy=True)[0],
           receipt(workspace, '062603', ok=False, legacy=True)[0]]
    before = {str(p): tree_hash(p.parent) for p in old}
    receipt(workspace, '094110')
    result = audit(workspace)
    print(json.dumps({'preserved_history_before': before,
                      'preserved_history_after': {str(p): tree_hash(p.parent) for p in old}}, sort_keys=True))
    assert result['ok'], result
    assert {str(p): tree_hash(p.parent) for p in old} == before
    assert len(list((workspace / 'ut_project/results').glob('build-*/build.json'))) == 3


def test_stale_old_success_then_current_success(workspace):
    """Historical source bytes and outputs may be stale; only the current output earns credit."""
    path, _ = receipt(workspace, 'old')
    before = tree_hash(path.parent)
    (workspace / 'inputs/Block.sv').write_text('// changed current source\n')
    (workspace / 'ut_project/dut/Block/libUTBlock.so').write_bytes(b'\x7fELF current marker\n')
    receipt(workspace, 'new')
    assert audit(workspace)['ok']
    assert tree_hash(path.parent) == before


@pytest.mark.parametrize('fault', ['only_fail', 'stale', 'empty_inputs', 'missing_declared', 'missing_header',
    'corrupt', 'nonobject', 'outside_input', 'input_digest', 'input_target', 'generated', 'no_native',
    'wrong_class', 'outside_package', 'output_changed', 'only_legacy', 'cancelled', 'source_changed',
    'nonzero', 'another_dut', 'command', 'export', 'input_error'])
def test_current_package_negative_controls(workspace, tmp_path, fault):
    """A preserved success cannot rescue stale, corrupt, incomplete or unrelated current evidence."""
    package = workspace / 'ut_project/dut/Block'
    options = {}
    if fault in {'missing_declared', 'generated'}:
        (workspace / 'inputs/Dep.sv').write_text('// declared dependency\n')
        options['filelist'] = ['inputs/Dep.sv']
    if fault == 'missing_header':
        (workspace / 'inputs/Block.sv').write_text('`include "config.svh"\n')
        (workspace / 'inputs/config.svh').write_text('// header\n')
    path, record = receipt(workspace, ok=fault != 'only_fail', legacy=fault == 'only_legacy', **options)
    if fault == 'stale':
        (workspace / 'inputs/Block.sv').write_text('// changed after build\n')
    elif fault == 'empty_inputs':
        record['inputs'] = {}
    elif fault in {'missing_declared', 'missing_header'}:
        del record['inputs']['inputs/Dep.sv' if fault == 'missing_declared' else 'inputs/config.svh']
    elif fault == 'corrupt':
        path.write_text('{not JSON')
    elif fault == 'nonobject':
        path.write_text('[]')
    elif fault == 'outside_input':
        record['inputs']['../outside.sv'] = '0' * 64
    elif fault == 'input_digest':
        record['inputs']['inputs/Block.sv'] = '0' * 64
    elif fault == 'input_target':
        record['input_targets']['inputs/Block.sv'] = 'inputs/Other.sv'
    elif fault == 'generated':
        (path.parent / 'inputs.f').write_text('// changed recipe\n')
    elif fault == 'no_native':
        (package / '__init__.py').unlink()
    elif fault == 'wrong_class':
        (package / '__init__.py').write_text('class DUToops:\n    pass\n')
    elif fault == 'outside_package':
        outside = tmp_path.parent / (tmp_path.name + '-outside.py')
        outside.write_text('class DUTBlock:\n    pass\n')
        (package / '__init__.py').unlink()
        (package / '__init__.py').symlink_to(outside)
    elif fault == 'output_changed':
        (package / 'libUTBlock.so').write_bytes(b'different current partial package')
    elif fault == 'cancelled':
        record['interrupted'] = 'cancelled'
    elif fault == 'source_changed':
        record['source_changed'] = True
    elif fault == 'nonzero':
        record['returncode'] = 9
    elif fault == 'another_dut':
        record['ok'] = False
        other = deepcopy(record)
        other.update(package='dut/Other', ok=True, returncode=0)
        write_json(path.parent.parent / 'build-other/build.json', other)
    elif fault == 'command':
        record['command'][record['command'].index('--sname') + 1] = 'UnrecordedTop'
    elif fault == 'export':
        record['options']['export_name'] = 'WrongExport'
    elif fault == 'input_error':
        record['input_error'] = 'input closure failed'
    if fault not in {'corrupt', 'nonobject'}:
        write_json(path, record)
    result = audit(workspace)
    if fault == 'only_legacy':
        # BRG-LEGACY-01: preserve the original input/recipe grade, not output-SHA proof.
        assert result['ok'], result
        assert result['build_evidence']['credit'] == 'legacy-input-recipe'
    else:
        assert not result['ok'], (fault, result)
        assert result['error_code'] == 'UT_STAGE_EVIDENCE_MISSING'


def test_receipt_free_native_adoption_is_unchanged(workspace):
    """Existing native-only adoption does not newly require BuildToffeeDUT or a receipt."""
    assert audit(workspace)['ok']


@pytest.mark.parametrize('difference', ['jobs', 'top', 'rtl_defines', 'timing'])
@pytest.mark.parametrize('same_bytes', [False, True])
def test_multiple_successful_contracts(workspace, difference, same_bytes):
    """Bytes disambiguate recipes; identical bytes with competing semantics are ambiguous."""
    receipt(workspace, 'zzz-old')
    if not same_bytes:
        (workspace / 'ut_project/dut/Block/libUTBlock.so').write_bytes(b'\x7fELF different output marker\n')
    options = {'jobs': 32} if difference == 'jobs' else {
        'top': 'AllowedTopOverride'} if difference == 'top' else {
        'rtl_defines': ['MODE=2']} if difference == 'rtl_defines' else {'timing': True}
    receipt(workspace, 'aaa-new', **options)
    result = audit(workspace)
    assert result['ok'] == (not same_bytes or difference == 'jobs'), result


@pytest.mark.parametrize('replace_package', [False, True])
def test_later_failure_is_not_ignored_by_time(workspace, replace_package):
    """Failure without replacing byte-matched output is history; partial replacement earns no credit."""
    receipt(workspace, '000-success')
    if replace_package:
        (workspace / 'ut_project/dut/Block/libUTBlock.so').write_bytes(b'partial later output\n')
    receipt(workspace, '999-later-failure', ok=False)
    result = audit(workspace)
    assert result['ok'] is (not replace_package), result


def test_build_producer_emits_output_identity_without_loading_it(workspace, monkeypatch):
    """Exercise the actual build producer with an intercepted process and a new output path."""
    original = workspace / 'ut_project/dut/Block'
    original.rename(original.with_name('archived'))
    monkeypatch.setattr('toffee_ut.build.shutil.which', lambda name: '/controlled/picker')

    def execute(command, cwd, stdout, stderr, *args):
        destination = Path(command[command.index('--tdir') + 1])
        destination.mkdir()
        (destination / '__init__.py').write_text('class DUTBlock:\n    pass\n')
        (destination / 'libUTBlock.so').write_bytes(b'\x7fELF non-loadable fixture\n')
        stdout.write_text('controlled stdout\n')
        stderr.write_text('')
        return 0, ''

    monkeypatch.setattr('toffee_ut.build.execute', execute)
    result = build_dut(workspace, 'Block', 'ut_project', 'inputs/Block.sv')
    assert result['ok'] and result['package_files'] == files(workspace)
    assert audit(workspace)['ok']


@pytest.mark.parametrize('fault', ['corrupt', 'empty_inputs'])
def test_malformed_history_is_not_hidden_by_valid_current(workspace, fault):
    """History remains parseable/accountable even when it does not claim current native bytes."""
    old, record = receipt(workspace, 'history', ok=False, legacy=True)
    if fault == 'corrupt':
        old.write_text('{broken')
    else:
        record['inputs'] = {}
        write_json(old, record)
    receipt(workspace)
    result = audit(workspace)
    assert not result['ok'] and str(old) in result['error'], result


@pytest.mark.parametrize('fault', ['added_library', 'metadata', 'library_escape', 'receipt_escape', 'runtime_only'])
def test_output_membership_and_path_guards(workspace, fault):
    """Check library/metadata identities and workspace confinement; runtime files are not build inputs."""
    path, _ = receipt(workspace)
    package = workspace / 'ut_project/dut/Block'
    if fault == 'added_library':
        (package / '_UT_Block.so').write_bytes(b'additional marker')
    elif fault == 'metadata':
        (package / 'Block.xscfg').write_text('{"different": true}\n')
    elif fault in {'library_escape', 'receipt_escape'}:
        target = package / 'libUTBlock.so' if fault == 'library_escape' else path
        outside = workspace.parent / (workspace.name + '-outside-asset')
        outside.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(outside)
    else:
        (package / '__pycache__').mkdir()
        (package / '__pycache__/cached.pyc').write_bytes(b'not identity')
        (package / 'runtime.fst').write_bytes(b'not identity')
        (package / 'coverage.dat').write_bytes(b'not identity')
    result = audit(workspace)
    assert result['ok'] is (fault == 'runtime_only'), result


@pytest.mark.parametrize('fault', ['none', 'add_header', 'delete_header', 'retarget_same_bytes'])
def test_include_tree_freshness_at_wrapper_entry(workspace, fault):
    """Fresh include closure passes; member/target changes fail even with identical header bytes."""
    headers = workspace / 'inputs/headers'
    headers.mkdir()
    (headers / 'one.svh').write_text('// same bytes\n')
    (headers / 'two.svh').write_text('// same bytes\n')
    (headers / 'alias.svh').symlink_to(headers / 'one.svh')
    (workspace / 'inputs/Block.sv').write_text('`include "alias.svh"\n')
    receipt(workspace, include_dirs=['inputs/headers'])
    if fault == 'add_header':
        (headers / 'new.svh').write_text('// new member\n')
    elif fault == 'delete_header':
        (headers / 'two.svh').unlink()
    elif fault == 'retarget_same_bytes':
        (headers / 'alias.svh').unlink()
        (headers / 'alias.svh').symlink_to(headers / 'two.svh')
    result = audit(workspace)
    assert result['ok'] is (fault == 'none'), result


def test_stale_success_with_identical_outputs_can_remain_history(workspace):
    """A known fresh binding is not vetoed by stale provenance for byte-identical native outputs."""
    path, _ = receipt(workspace, 'old')
    before = tree_hash(path.parent)
    (workspace / 'inputs/Block.sv').write_text('// new source, unchanged controlled output\n')
    receipt(workspace, 'new')
    assert audit(workspace)['ok']
    assert before == tree_hash(path.parent)


def test_resource_budgets_and_mtime_are_not_recipe_identity(workspace):
    """Arbitrary names and reversed mtimes cannot decide between two semantically identical builds."""
    old, before = receipt(workspace, 'zzzz-not-a-date', jobs=1)
    new, current = receipt(workspace, 'aaaa-not-a-date', jobs=32)
    before['timeout'], current['timeout'] = 1, 10800
    write_json(old, before)
    write_json(new, current)
    os.utime(old, (2000000000, 2000000000))
    os.utime(new, (1, 1))
    assert audit(workspace)['ok']


def test_legacy_success_does_not_invent_current_output_provenance(workspace):
    """The exact legacy receipt bytes fit both intact-success and later-partial histories."""
    path, _ = receipt(workspace, legacy=True)
    before = tree_hash(path.parent)
    intact = audit(workspace)
    (workspace / 'ut_project/dut/Block/libUTBlock.so').write_bytes(b'later partial replacement\n')
    partial = audit(workspace)
    # BRG-LEGACY-01: these histories are indistinguishable at the original wrapper grade.
    assert intact['ok'] and partial['ok']
    for result in (intact, partial):
        assert result['build_evidence']['credit'] == 'legacy-input-recipe'
        assert any('No build-time output SHA' in text for text in result['build_evidence']['limitations'])
    (workspace / 'inputs/Block.sv').write_text('// actually stale input\n')
    assert not audit(workspace)['ok']
    assert before == tree_hash(path.parent)


@pytest.mark.parametrize('fault', ['cancelled', 'source_changed', 'identity_error'])
def test_failed_producer_cannot_emit_current_package_credit(workspace, monkeypatch, fault):
    """Actual producer cancellation/input-change/fingerprint failures preserve raw logs without credit."""
    package = workspace / 'ut_project/dut/Block'
    package.rename(package.with_name('archived'))
    monkeypatch.setattr('toffee_ut.build.shutil.which', lambda name: '/controlled/picker')

    def execute(command, cwd, stdout, stderr, *args):
        destination = Path(command[command.index('--tdir') + 1])
        destination.mkdir()
        (destination / '__init__.py').write_text('class DUTBlock:\n    pass\n')
        stdout.write_text('preserved original stdout\n')
        stderr.write_text('preserved original stderr\n')
        if fault == 'source_changed':
            (workspace / 'inputs/Block.sv').write_text('// concurrent input change\n')
        return 0, 'cancelled' if fault == 'cancelled' else ''

    def identity_error(*args):
        raise OSError('controlled output fingerprint error')

    monkeypatch.setattr('toffee_ut.build.execute', execute)
    if fault == 'identity_error':
        monkeypatch.setattr('toffee_ut.build.package_files', identity_error)
    result = build_dut(workspace, 'Block', 'ut_project', 'inputs/Block.sv')
    assert not result['ok'] and 'package_files' not in result
    log = workspace / 'ut_project' / result['logs']
    assert (log / 'stdout.log').read_text() == 'preserved original stdout\n'
    assert (log / 'stderr.log').read_text() == 'preserved original stderr\n'
    assert not audit(workspace)['ok']
