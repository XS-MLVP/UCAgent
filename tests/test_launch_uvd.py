"""Exercise the default UVD launcher: stubs for its boundaries, real UVS/UVD/Xvfb when installed.

The time scale is 10ps on purpose: a 1ps waveform would pass even if the native unit were ignored.
"""

import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time

import pytest

import ucagent
from ucagent.scripts.uvd.launch_uvd import find_database, startup_script, tcl_word
from ucagent.util.waveform_viewer import write_waveform_metadata

LAUNCHER = Path(ucagent.__file__).resolve().parent / 'scripts/uvd/launch_uvd.py'
TESTBENCH = """`timescale 1ns/10ps
module tb;
  reg clk = 0; reg [7:0] cnt = 0;
  wire \\esc$name = clk;
  always #5 clk = ~clk;
  always @(posedge clk) cnt <= cnt + 1;
  initial begin $usdbDumpfile("t.usdb"); #100 $finish; end
endmodule
"""
SIGNALS = ['tb.clk', 'tb.cnt[7:0]', 'tb.esc$name']
real_tools = pytest.mark.skipif(not all(map(shutil.which, ('uvs', 'uvd', 'Xvfb'))) or not os.environ.get('UVD_HOME'),
                                reason='Requires UVS, UVD, UVD_HOME and Xvfb')


@pytest.fixture(autouse=True)
def signing_profile(tmp_path, monkeypatch):
    """Use private test keys that remain available to standalone launcher processes."""
    profile = tmp_path.parent / (tmp_path.name + '-profile')
    monkeypatch.setenv('HOME', str(profile))
    monkeypatch.setattr('ucagent.util.waveform_viewer._METADATA_KEY_DIRECTORY',
                        profile / '.ucagent' / 'waveform_keys')


def sign(root, **fields):
    """Publish metadata the way WaveInfo does, then return its path."""
    payload = dict(schema_version=1, waveform_file='t.usdb', signals=SIGNALS, source_files=[],
                   dut_python_path='../Demo/__init__.py', start='1000', end='7000', cursor='2500') | fields
    write_waveform_metadata(root, 'waves/t.usdb.json', payload)
    return root / 'waves/t.usdb.json'


def run_launcher(root, meta, *args, env=None):
    """Run the launcher as Xpra does, from the workspace with the meta path as an argument."""
    return subprocess.run([sys.executable, str(LAUNCHER), '--meta', str(meta), *args], cwd=root,
                          env=env, capture_output=True, text=True, timeout=120)


def stub_uvd(tmp_path, body='printf "%s\\n" "$@" > "$RECORD"'):
    """Create a uvd replacement for tests about what happens before or around the real one."""
    stub = tmp_path / 'uvd-stub'
    stub.write_text('#!/bin/sh\nRECORD=' + str(tmp_path / 'argv') + '\n' + body + '\n')
    stub.chmod(0o755)
    return stub


@pytest.fixture
def fake_workspace(tmp_path, monkeypatch):
    """A workspace with a fake usdbaccess, so these tests also run without UVS installed."""
    root = tmp_path / 'ws'
    for path in ('Demo/__init__.py', 'waves/t.usdb'):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).touch()
    (root / 'Demo/demo.db/ddb.db').mkdir(parents=True)
    home = tmp_path / 'uv'
    (home / 'bin').mkdir(parents=True)
    tool = home / 'bin/usdbaccess'
    tool.write_text('#!/bin/sh\ncase "$3" in\n'
                    '  --info) echo "start time: 0"; echo "end time: 10000"; echo "time scale: 10ps" ;;\n'
                    '  --hier) echo "Var:tb.clk Bits:1 Idcode:1 Type:Reg"\n'
                    '          echo "Var:tb.cnt P:[7:0] Bits:8 Idcode:2 Type:Reg"\n'
                    '          echo "Var:tb.esc\\$name Bits:1 Idcode:3 Type:Wire" ;;\n'
                    'esac\n')
    tool.chmod(0o755)
    monkeypatch.setenv('UVD_HOME', str(home))
    monkeypatch.delenv('UVS_HOME', raising=False)
    return root


def test_uvd_argv_loads_waveform_and_design_by_absolute_path(fake_workspace, tmp_path):
    """uvd runs in a temporary cwd, so relative paths would not resolve."""
    meta = sign(fake_workspace)
    done = run_launcher(fake_workspace, meta, '--uvd', str(stub_uvd(tmp_path)))
    assert done.returncode == 0, done.stderr
    argv = (tmp_path / 'argv').read_text().split('\n')
    assert argv[argv.index('-u') + 1] == str(fake_workspace / 'waves/t.usdb')
    assert argv[argv.index('-d') + 1] == str(fake_workspace / 'Demo/demo.db')
    assert not list(fake_workspace.parent.glob('ucagent-uvd-*'))


def test_metadata_without_a_window_needs_no_time_unit(fake_workspace, tmp_path):
    """The file browser creates metadata with no signals and no window."""
    write_waveform_metadata(fake_workspace, 'waves/t.usdb.json', dict(schema_version=1, waveform_file='t.usdb',
                            signals=[], source_files=[], dut_python_path='../Demo/__init__.py'))
    meta = fake_workspace / 'waves/t.usdb.json'
    assert run_launcher(fake_workspace, meta, '--uvd', str(stub_uvd(tmp_path))).returncode == 0
    assert 'addSignals' not in startup_script(json.loads(meta.read_text()), None, Path('/f'))


def test_absent_signal_rejected_before_uvd_starts(fake_workspace, tmp_path):
    """addSignals would block on a modal dialog, so uvd must never see this name."""
    meta = sign(fake_workspace, signals=['tb.clk', 'tb.nosuch'])
    done = run_launcher(fake_workspace, meta, '--uvd', str(stub_uvd(tmp_path)))
    assert done.returncode == 1 and 'tb.nosuch' in done.stderr
    assert not (tmp_path / 'argv').exists()


def test_tampered_metadata_rejected(fake_workspace, tmp_path):
    """The JSON chooses what is loaded, so it is checked again at launch."""
    meta = sign(fake_workspace)
    meta.write_text(meta.read_text().replace('"cursor": "2500"', '"cursor": "2501"'))
    done = run_launcher(fake_workspace, meta, '--uvd', str(stub_uvd(tmp_path)))
    assert done.returncode == 1 and 'signature' in done.stderr
    assert not (tmp_path / 'argv').exists()


def test_startup_script_failure_stops_uvd_and_fails(fake_workspace, tmp_path):
    """A Tcl error only reaches the launcher through the failure file; uvd itself keeps running."""
    meta = sign(fake_workspace)
    stub = stub_uvd(tmp_path, 'for a; do [ "$p" = -s ] && script=$a; p=$a; done\n'
                              'file=$(sed -n \'s/.*open "\\(.*\\)" w.*/\\1/p\' "$script")\n'
                              'echo "invalid command name" > "$file"\nexec sleep 60')
    done = run_launcher(fake_workspace, meta, '--uvd', str(stub))
    assert done.returncode == 1 and 'Cannot restore waveform view: invalid command name' in done.stderr


def test_startup_script_zooms_after_the_queued_default_zoom():
    """addSignals queues UVD's own zoom, so ours must run from the event loop to take effect."""
    script = startup_script(dict(signals=['a'], start='1', end='9', cursor='5'), '10ps', Path('/f'))
    assert 'zoomRange' not in script.split('after idle')[0]
    assert 'zoomRange -timeRange 1-9' in script.split('after idle')[1]
    assert 'setTimeUnit -value 10ps' in script and 'setMarkerValue -value 5/10ps' in script


def database_layout(root, *names):
    """Create the minimal directories that find_database looks at."""
    (root / 'Demo').mkdir(exist_ok=True)
    (root / 'Demo/__init__.py').touch()
    for name in names:
        (root / 'Demo' / name).mkdir(parents=True)
    return dict(source_files=[], dut_python_path='Demo/__init__.py')


def test_database_selection(tmp_path):
    """One candidate is used; none means waveform only; several must be disambiguated by --dbdir."""
    root = tmp_path.resolve()
    payload = database_layout(root, 'no_ddb.db/debug.db')
    assert find_database(root, root, payload, None) is None
    with pytest.raises(ValueError, match='ddb.db'):
        find_database(root, root, payload, Path('Demo/no_ddb.db'))
    database_layout(root, 'a.db/ddb.db')
    assert find_database(root, root, payload, None) == root / 'Demo/a.db'
    database_layout(root, 'b.db/ddb.db')
    with pytest.raises(ValueError, match='Multiple'):
        find_database(root, root, payload, None)
    assert find_database(root, root, payload, Path('Demo/b.db')) == root / 'Demo/b.db'


def test_database_symlink_escape_rejected(tmp_path):
    """Files reachable through the database must stay inside the workspace."""
    root = tmp_path.resolve()
    payload = database_layout(root, 'a.db/ddb.db')
    (root / 'Demo/a.db/escape').symlink_to('/etc')
    with pytest.raises(ValueError, match='escapes'):
        find_database(root, root, payload, None)


def test_tcl_word_keeps_special_characters_literal():
    """Signal names come from the design, including escaped identifiers."""
    assert tcl_word('a[3:0]') == r'"a\[3:0\]"'
    assert tcl_word('$b"{c}\\') == r'"\$b\"\{c\}\\"'


@pytest.fixture(scope='module')
def real_workspace(tmp_path_factory):
    """Build one DUT layout like picker's: the design database sits beside the Python entry."""
    root = tmp_path_factory.mktemp('ws').resolve()
    (root / 'Demo').mkdir()
    (root / 'Demo/__init__.py').touch()
    (root / 'waves').mkdir()
    (root / 'waves/tb.sv').write_text(TESTBENCH)
    subprocess.run(['uvs', '-sv', 'tb.sv', '-ddb', '-usdbon', '-debug', 'r', '-o', '../Demo/demo'],
                   cwd=root / 'waves', check=True, capture_output=True)
    subprocess.run(['../Demo/demo'], cwd=root / 'waves', check=True, capture_output=True)
    return root


@pytest.fixture(scope='module')
def display():
    """Keep test GUIs off the user's desktop."""
    server = subprocess.Popen(['Xvfb', '-displayfd', '1', '-screen', '0', '1600x1000x24'],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    yield ':' + server.stdout.readline().strip()
    server.terminate()
    server.wait(timeout=10)


def uvd_mcp(port, tool, arguments):
    """Ask the running UVD about its own state; retries cover the time it takes to start listening."""
    import anyio
    from mcp import ClientSession
    from mcp.client.sse import sse_client
    from mcp.client.streamable_http import streamable_http_client

    async def call(client):
        async with client(f'http://127.0.0.1:{port}/mcp') as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments)
                return ''.join(getattr(item, 'text', '') for item in result.content)
    deadline = time.monotonic() + 45
    client = streamable_http_client
    while True:
        try:
            return anyio.run(call, client)
        except Exception:
            assert time.monotonic() < deadline, 'UVD MCP never answered'
            # UVD releases expose either Streamable HTTP or legacy HTTP+SSE at /mcp.
            client = sse_client if client is streamable_http_client else streamable_http_client
            time.sleep(1)


@real_tools
def test_real_uvd_restores_view_and_stops_on_sigterm(real_workspace, display, tmp_path):
    """Signals, window and cursor land in native ticks, and SIGTERM takes uvd and its temp files along."""
    pytest.importorskip('mcp')
    meta = sign(real_workspace)
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    before = set(real_workspace.rglob('*'))
    log = open(tmp_path / 'launcher.log', 'w+')
    launcher = subprocess.Popen([sys.executable, str(LAUNCHER), '--meta', str(meta), '--', '--mcp', str(port)],
                                cwd=real_workspace, env=os.environ | {'DISPLAY': display, 'TMPDIR': str(tmp_path)},
                                stdout=log, stderr=subprocess.STDOUT)
    try:
        items = ('execute_tcl', {'cmd_name': 'util_wave_item', 'args': ['-id', 'primary', '-action', 'dumpItems']})
        uvd_mcp(port, *items)
        # after idle runs once the event loop is free, so give it a moment after MCP first answers.
        time.sleep(3)
        report = uvd_mcp(port, 'get_all_wave_windows_info', {}) + uvd_mcp(port, *items)
        for expected in ('"timeUnit":"10ps"', '"timeScale":"10ps"', '"cursorTime":"2500"',
                         '"visibleStartTime":"1000"', '"visibleEndTime":"7000"',
                         'name: clk', 'name: cnt[7:0]', 'name: esc$name'):
            assert expected in report, report
        log.seek(0)
        assert 'Loaded Debug Database' in log.read()
    finally:
        launcher.send_signal(signal.SIGTERM)
        assert launcher.wait(timeout=20) == 128 + signal.SIGTERM
        log.close()
    assert not list(tmp_path.glob('ucagent-uvd-*')), 'temporary directory left behind'
    time.sleep(1)
    assert subprocess.run(['pgrep', '-f', f'--mcp {port}'], capture_output=True).stdout == b'', 'uvd survived'
    assert set(real_workspace.rglob('*')) == before, 'uvd wrote into the workspace'


@real_tools
def test_real_uvd_startup_error_reaches_exit_code(real_workspace, display, tmp_path):
    """A fresh HOME makes exit prompt to save signals, which must not leave the launcher waiting."""
    meta = sign(real_workspace)
    wrapper = stub_uvd(tmp_path, 'for a; do [ "$p" = -s ] && sed -i s/util_wave_time/no_such_command/ "$a"; p=$a; done\n'
                                 'exec uvd "$@"')
    done = run_launcher(real_workspace, meta, '--uvd', str(wrapper), env=os.environ | {'DISPLAY': display})
    assert done.returncode == 1, done.stderr
    assert 'Cannot restore waveform view' in done.stderr and 'no_such_command' in done.stderr
