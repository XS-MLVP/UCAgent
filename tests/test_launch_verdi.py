"""Exercise the default Verdi launcher with a Tcl-aware subprocess substitute."""

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from ucagent.scripts.verdi.launch_verdi import launch
from ucagent.util.waveform_viewer import build_waveform_metadata, load_waveform_metadata, write_waveform_metadata


@pytest.fixture(autouse=True)
def signing_profile(tmp_path, monkeypatch):
    """Use private test keys that remain available to standalone launcher processes."""
    profile = tmp_path.parent / (tmp_path.name + '-profile')
    monkeypatch.setenv('HOME', str(profile))
    monkeypatch.setattr('ucagent.util.waveform_viewer._METADATA_KEY_DIRECTORY',
                        profile / '.ucagent' / 'waveform_keys')


def _metadata(root):
    """Create real related files and an exact native timestamp window."""
    for name in ('waves/a } $[exec].fsdb','rtl/design [a].sv','src/Design.scala'):
        path = root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture')
    meta, payload, _ = build_waveform_metadata(root, 'waves/a } $[exec].fsdb',
        source_files=['rtl/design [a].sv', 'src/Design.scala'])
    payload.update(signals=['TOP.dut.data[7:0]', 'TOP.dut.valid', 'TOP.dut.escaped}name'],
                   start='100', end='200', cursor='150')
    write_waveform_metadata(root, meta, payload)
    return root/meta


@pytest.mark.parametrize('unit', ['1ps', '10fs', '0.1ns'])
def test_verdi_argv_and_tcl_use_real_native_time_units(tmp_path, unit):
    """Execute startup Tcl against a fake Verdi command set at multiple actual scales."""
    tclsh = shutil.which('tclsh')
    if tclsh is None:
        pytest.skip('Tcl interpreter unavailable')
    meta = _metadata(tmp_path)
    binary = tmp_path/'fake verdi'
    capture = tmp_path/'captured.json'
    # This executable validates the complete command boundary, including Tcl quoting.
    binary.write_text('#!'+sys.executable+'\n'+'''
import json, pathlib, subprocess, sys
argv=sys.argv[1:]
script=pathlib.Path(argv[argv.index("-play")+1]).read_text()
prelude = """
set recorded {}
set opened ""
proc wvCreateWindow {} {return wave1}
proc wvOpenFile {args} {set ::opened [lindex $args end]; lappend ::recorded [linsert $args 0 open]; return $::opened}
proc wvAddSignal {args} {lappend ::recorded [linsert $args 0 signal]; return 1}
proc wvGetFileTimeUnit {args} {return UNIT_VALUE}
proc wvSetWindowTimeUnit {args} {lappend ::recorded [linsert $args 0 unit]; return 1}
proc wvZoom {args} {lappend ::recorded [linsert $args 0 zoom]; return 1}
proc wvSetCursor {args} {lappend ::recorded [linsert $args 0 cursor]; return 1}
"""
result=subprocess.run([TCL_BINARY],input=prelude+script+"\\nputs $opened\\nputs $recorded\\n",text=True,capture_output=True)
pathlib.Path(CAPTURE).write_text(json.dumps(dict(argv=argv,script=script,out=result.stdout,error=result.stderr)))
sys.exit(result.returncode)
'''.replace('UNIT_VALUE',unit).replace('TCL_BINARY',repr(tclsh)).replace('CAPTURE',repr(str(capture))))
    binary.chmod(0o755)
    assert launch(meta, str(binary), ['-nologo'], workspace=tmp_path) == 0
    result = json.loads(capture.read_text())
    assert result['error'] == ''
    assert '-nologo' in result['argv'] and '-sv' in result['argv']
    assert str((tmp_path/'rtl/design [a].sv').resolve()) in result['argv']
    assert not any('scala' in value for value in result['argv'])
    assert str((tmp_path/'waves/a } $[exec].fsdb').resolve()) == result['out'].splitlines()[0]
    assert '{signal -win wave1 -delim . {TOP.dut.data[7:0]}}' in result['out']
    assert '{zoom -win wave1 100 200}' in result['out']
    assert '{cursor -win wave1 150}' in result['out']
    assert 'wvGetFileTimeUnit' in result['script']
    assert 'wvSetWindowTimeUnit -win' in result['script']
    assert not Path(result['argv'][-1]).exists()


def test_launcher_preserves_exit_status_and_reports_invalid_inputs(tmp_path, monkeypatch):
    """A missing application, malformed metadata or invalid time cannot appear successful."""
    meta = _metadata(tmp_path)
    with pytest.raises(FileNotFoundError):
        launch(meta, str(tmp_path/'missing-verdi'), [], workspace=tmp_path)
    executable = tmp_path/'exit'
    executable.write_text('#!'+sys.executable+'\nraise SystemExit(17)\n')
    executable.chmod(0o755)
    assert launch(meta,str(executable),[], workspace=tmp_path) == 17
    payload = load_waveform_metadata(tmp_path, meta.relative_to(tmp_path).as_posix())[1]
    payload['cursor'] = 'nan'
    with pytest.raises(ValueError,match='decimal string'):
        write_waveform_metadata(tmp_path, meta.relative_to(tmp_path).as_posix(), payload)
    stored = json.loads(meta.read_text())
    stored['cursor'] = 'nan'
    meta.write_text(json.dumps(stored))
    script = Path(__file__).resolve().parents[1]/'ucagent/scripts/verdi/launch_verdi.py'
    result = subprocess.run([sys.executable,str(script),'--meta',str(meta),'--verdi',str(executable)],
        capture_output=True,text=True,cwd=tmp_path)
    assert result.returncode == 1 and 'Cannot open waveform in Verdi' in result.stderr


def test_launcher_rechecks_signature_after_server_validation(tmp_path, monkeypatch):
    """An on-disk edit between dispatch and process startup must never reach Verdi."""
    meta = _metadata(tmp_path)
    load_waveform_metadata(tmp_path, meta.relative_to(tmp_path).as_posix())
    stored = json.loads(meta.read_text())
    stored['signals'] = ['TOP.forged']
    meta.write_text(json.dumps(stored))

    def unexpected(*args, **kwargs):
        """Fail if signature rejection launches any external process."""
        pytest.fail('Verdi must not launch with modified metadata')

    monkeypatch.setattr(subprocess, 'run', unexpected)
    with pytest.raises(ValueError, match='signature'):
        launch(meta, 'verdi', [], workspace=tmp_path)


def test_standalone_launcher_loads_exact_package_and_persisted_key(tmp_path, monkeypatch):
    """A child launched from the selected workspace can verify the parent's signed JSON."""
    meta = _metadata(tmp_path)
    binary = tmp_path / 'fake-verdi'
    binary.write_text('#!' + sys.executable + '\nraise SystemExit(17)\n')
    binary.chmod(0o755)
    script = Path(__file__).resolve().parents[1] / 'ucagent/scripts/verdi/launch_verdi.py'
    monkeypatch.delenv('PYTHONPATH', raising=False)
    result = subprocess.run([sys.executable, str(script), '--meta', str(meta), '--verdi', str(binary)],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 17, result.stderr
    assert result.stderr == ''


@pytest.mark.parametrize('command,diagnostic', [
    ('wvCreateWindow', 'Cannot create waveform window'),
    ('wvOpenFile', 'Cannot load waveform file'),
    ('wvAddSignal', 'Cannot add waveform signal'),
    ('wvGetFileTimeUnit', 'Cannot determine waveform native time unit'),
    ('wvSetWindowTimeUnit', 'Cannot set waveform native display time unit'),
    ('wvZoom', 'Cannot restore waveform time range'),
    ('wvSetCursor', 'Cannot restore waveform cursor'),
])
def test_launcher_reports_tcl_zero_return_failures(tmp_path, monkeypatch, command, diagnostic):
    """Verdi commands returning failure must abort restoration with a useful error."""
    tclsh = shutil.which('tclsh')
    if tclsh is None:
        pytest.skip('Tcl interpreter unavailable')
    meta = _metadata(tmp_path)
    run = subprocess.run
    results = []

    def execute_startup(argv, check):
        """Evaluate the generated script with one failed Verdi command."""
        script = Path(argv[argv.index('-play') + 1]).read_text()
        prelude = '\n'.join(
            'proc ' + name + ' {args} {return ' + (
                '0' if name == command else '1ps' if name == 'wvGetFileTimeUnit' else '1'
            ) + '}'
            for name in ('wvCreateWindow', 'wvOpenFile', 'wvAddSignal', 'wvGetFileTimeUnit',
                         'wvSetWindowTimeUnit', 'wvZoom', 'wvSetCursor')
        )
        result = run([tclsh], input=prelude + '\n' + script, text=True, capture_output=True)
        results.append(result)
        return result

    monkeypatch.setattr(subprocess, 'run', execute_startup)
    assert launch(meta, 'verdi', [], workspace=tmp_path) == 1
    assert diagnostic in results[0].stderr
