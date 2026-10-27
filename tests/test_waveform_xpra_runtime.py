"""Opt-in real Xpra/Xvfb acceptance with the graphical fake_verdi application.

Run UCAGENT_RUN_WAVE_XPRA_INTEGRATION=1 python -m pytest -q
tests/test_waveform_xpra_runtime.py on Linux with Xpra, HTML5 assets and Tk.
Run this file with --serve to expose the same fixture for browser acceptance.
The marked JSON fixture is not a proprietary FSDB recording.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
import uuid

import psutil
import pytest
import requests

from ucagent.server.api_cmd import PdbCmdApiServer
from ucagent.util.config import Config
from ucagent.util import waveform_viewer


pytestmark = pytest.mark.skipif(
    os.environ.get('UCAGENT_RUN_WAVE_XPRA_INTEGRATION') != '1',
    reason='Requires real Linux Xpra, Xvfb, HTML5 assets and Tk',
)


def wait_for(predicate, diagnostic, timeout=30):
    """Wait for observed runtime state and include bounded service logs on failure."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError(diagnostic())


@contextmanager
def waveform_service(root, host='127.0.0.1', port=0):
    """Serve signed waveform metadata through the actual CMD and Xpra implementation."""
    assert sys.platform.startswith('linux'), 'Real Xpra acceptance requires Linux/X11.'
    assert shutil.which('xpra') and shutil.which('Xvfb'), 'Install Xpra and Xvfb.'
    import tkinter  # noqa: F401 -- fail explicitly if the opt-in runtime lacks Tk.

    root = Path(root).resolve()
    workspace = root / 'workspace'
    workspace.mkdir(parents=True)
    profile = root / 'profile'
    profile.mkdir()
    state = workspace / 'fake-state.json'
    binary = root / 'fake verdi'
    fixture_script = Path(__file__).resolve().parent / 'fixtures/fake_verdi.py'
    binary.write_text('#!/bin/sh\nexec ' + shlex.join([sys.executable, str(fixture_script)]) +
                      ' "$@"\n', encoding='utf-8')
    binary.chmod(0o755)
    files = {'Demo/Demo.sv': 'module Demo; endmodule\n',
             'rtl/design [unit].sv': 'module Related; endmodule\n',
             'src/Demo.scala': '// Associated design source\n',
             'Demo/__init__.py': '"""Test DUT entry."""\n',
             'tests/test_demo.py': '"""Test association fixture."""\n'}
    for name, content in files.items():
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    start = 9007199254740993
    signals = ['TOP.dut.clk', 'TOP.dut.result[3:0]', 'TOP.dut.escaped}name']
    wave = workspace / 'waves/波形 a } $[exec].fsdb'
    wave.parent.mkdir()
    wave.write_text(json.dumps(dict(fake_verdi_fixture=1, native_unit='10fs', end=str(start + 200),
        signals={name: [[str(start), 0], [str(start + 60), 1], [str(start + 140), 0]]
                 for name in signals})), encoding='utf-8')
    password = uuid.uuid4().hex
    cfg = Config(dict(cmd_api=dict(xpra=dict(executable=shutil.which('xpra'), max_sessions=1,
        startup_timeout=30, shutdown_timeout=5), waveform_viewers=dict(fsdb=dict(kind='xpra',
        script='verdi/launch_verdi.py', args=['--meta', '{wave_meta}', '--verdi', str(binary),
        '--', '--fake-state', str(state)], env={'HOME': str(profile)}, idle_timeout=-1)))))
    if not port:
        with socket.socket() as reservation:
            reservation.bind((host, 0))
            port = reservation.getsockname()[1]
    client = requests.Session()
    client.auth = ('ucagent', password)
    base = f'http://127.0.0.1:{port}'
    server = None
    # The parent and configured launcher share one private profile outside served files.
    with patch.object(waveform_viewer, '_METADATA_KEY_DIRECTORY', profile / '.ucagent/waveform_keys'):
        meta, payload, _ = waveform_viewer.build_waveform_metadata(workspace,
            wave.relative_to(workspace).as_posix(), dut_name='Demo',
            test_case='tests/test_demo.py::test_saturation',
            source_files=['rtl/design [unit].sv', 'src/Demo.scala'])
        payload.update(signals=signals, start=str(start), end=str(start + 200), cursor=str(start + 100))
        waveform_viewer.write_waveform_metadata(workspace, meta, payload)
        manifest = dict(meta=meta, state_file=state.name, waveform=str(wave), signals=signals,
            sources=[str(workspace / name) for name in ('Demo/Demo.sv', 'rtl/design [unit].sv')],
            native_unit='10fs', start=payload['start'], end=payload['end'], cursor=payload['cursor'])
        (workspace / 'test-fixture.json').write_text(json.dumps(manifest), encoding='utf-8')
        try:
            pdb = SimpleNamespace(agent=SimpleNamespace(workspace=str(workspace), cfg=cfg, dut_name='Demo'),
                                  stdout=None)
            server = PdbCmdApiServer(pdb, host=host, port=port, sock='', password=password)
            ok, message = server.start()
            assert ok, message
            wait_for(lambda: server._tcp_server.started, lambda: message)
            yield SimpleNamespace(server=server, client=client, base=base, password=password,
                workspace=workspace, meta=meta, payload=payload, manifest=manifest, state=state,
                wave=wave, cfg=cfg)
        finally:
            if server is not None:
                thread = server._tcp_thread
                server.stop()
                if thread is not None:
                    thread.join(timeout=5)
            client.close()


@pytest.fixture
def runtime(tmp_path):
    """Create isolated signed fixtures and clean every real server/application process."""
    with waveform_service(tmp_path) as service:
        yield service


def test_real_xpra_launch_restore_reuse_quota_and_reopen(runtime):
    """Restore exact Tcl arguments in a real graphical child and enforce session ownership."""
    service = runtime
    client, base = service.client, service.base
    assert client.get(base + '/api/xpra/status').json()['available']
    assert requests.get(base + '/wave/', params={'meta': service.meta}, timeout=5).status_code == 401
    assert requests.post(base + '/api/xpra/sessions', json={'wave_meta': service.meta}, timeout=5).status_code == 401
    assert client.get(base + '/wave/', params={'meta': service.meta}, timeout=5).status_code == 200
    assert client.get(base + '/api/xpra/sessions').json()['sessions'] == []

    def open_wave(_):
        """Send a separate authenticated request as simultaneous browser tabs would."""
        response = requests.post(base + '/api/xpra/sessions', auth=client.auth,
                                 json={'wave_meta': service.meta}, timeout=45)
        assert response.status_code == 201, response.text
        return response.json()['id']

    with ThreadPoolExecutor(max_workers=4) as pool:
        session_ids = set(pool.map(open_wave, range(4)))
    assert len(session_ids) == 1
    session_id = session_ids.pop()
    details = lambda: client.get(base + '/api/xpra/sessions/' + session_id).text
    wait_for(service.state.exists, details)
    observed = json.loads(service.state.read_text())
    for key in ('waveform', 'sources', 'signals', 'native_unit', 'start', 'end', 'cursor'):
        assert observed[key] == service.manifest[key]
    assert observed['display_unit'] == '10fs'
    assert observed['display'].startswith(':') and observed['window_id'] > 0
    assert observed['reviewed'] == 0
    assert psutil.pid_exists(observed['pid'])
    # A distinct configured view consumes another slot instead of bypassing the quota.
    service.cfg.cmd_api.waveform_viewers.fsdb.idle_timeout = 60
    response = client.post(base + '/api/xpra/sessions', json={'wave_meta': service.meta}, timeout=10)
    assert response.status_code == 409, response.text
    assert response.json()['detail']['error_code'] == 'XPRA_SESSION_LIMIT'
    assert client.delete(base + '/api/xpra/sessions/' + session_id, timeout=15).status_code == 200
    wait_for(lambda: not psutil.pid_exists(observed['pid']), lambda: 'GUI child survived session deletion')
    service.state.unlink()
    reopened = open_wave(0)
    assert reopened != session_id
    wait_for(service.state.exists, lambda: client.get(base + '/api/xpra/sessions/' + reopened).text)
    current = json.loads(service.state.read_text())
    assert current['pid'] != observed['pid']
    # Application exit also invalidates reuse, independently of explicit REST deletion.
    psutil.Process(current['pid']).terminate()
    wait_for(lambda: client.get(base + '/api/xpra/sessions/' + reopened).json()['status']
             in ('exited', 'failed'), lambda: client.get(base + '/api/xpra/sessions/' + reopened).text)
    assert client.get(base + '/api/xpra/sessions').json()['active_count'] == 0
    service.state.unlink()
    restarted = open_wave(0)
    assert restarted not in (reopened, session_id)
    wait_for(service.state.exists, lambda: client.get(base + '/api/xpra/sessions/' + restarted).text)
    assert json.loads(service.state.read_text())['pid'] != current['pid']


def test_real_xpra_rejects_tampered_metadata_before_launch(runtime):
    """Valid-shape unsigned edits cannot launch a real application or overwrite evidence."""
    target = runtime.workspace / runtime.meta
    stored = json.loads(target.read_text())
    stored['signals'] = ['TOP.forged']
    target.write_text(json.dumps(stored))
    for method, path, kwargs in (
        ('get', '/wave/', {'params': {'meta': runtime.meta}}),
        ('post', '/api/xpra/sessions', {'json': {'wave_meta': runtime.meta}}),
    ):
        response = getattr(runtime.client, method)(runtime.base + path, timeout=5, **kwargs)
        assert response.status_code == 422, response.text
        assert response.json()['detail']['error_code'] == 'WAVEFORM_METADATA_INTEGRITY_FAILED'
    assert runtime.client.get(runtime.base + '/api/xpra/sessions').json()['sessions'] == []
    assert not runtime.state.exists()


@pytest.mark.parametrize('failure,diagnostic', [
    ('signal', 'Cannot add waveform signal'),
    ('unit', 'Cannot determine waveform native time unit'),
])
def test_real_xpra_reports_graphical_application_startup_failure(runtime, failure, diagnostic):
    """Real Xpra logs retain Tcl restoration errors and release the failed child."""
    if failure == 'signal':
        runtime.payload['signals'] = ['TOP.missing']
        waveform_viewer.write_waveform_metadata(runtime.workspace, runtime.meta, runtime.payload)
    else:
        fixture = json.loads(runtime.wave.read_text())
        fixture['native_unit'] = 'unknown'
        runtime.wave.write_text(json.dumps(fixture))
    response = runtime.client.post(runtime.base + '/api/xpra/sessions',
                                   json={'wave_meta': runtime.meta}, timeout=45)
    assert response.status_code in (201, 503), response.text
    result = response.json()
    session_id = result['id'] if response.status_code == 201 else result['detail']['session_id']

    def exited_with_diagnostic():
        """Require a terminal session state and the launcher's specific error message."""
        details = runtime.client.get(runtime.base + '/api/xpra/sessions/' + session_id).json()
        return details['status'] in ('failed', 'exited') and diagnostic in '\n'.join(details['log_tail'])

    wait_for(exited_with_diagnostic, lambda: runtime.client.get(
        runtime.base + '/api/xpra/sessions/' + session_id).text)
    assert not runtime.state.exists()
    assert runtime.client.get(runtime.base + '/api/xpra/sessions').json()['active_count'] == 0


def main():
    """Keep a real fixture server alive until interrupted for external browser tests."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true', required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--info', type=Path, required=True)
    args = parser.parse_args()
    stopped = threading.Event()
    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, lambda signum, frame: stopped.set())
    with tempfile.TemporaryDirectory(prefix='ucagent-wave-xpra-') as directory:
        with waveform_service(Path(directory), args.host, args.port) as service:
            descriptor = os.open(args.info, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
                    json.dump(dict(base=service.base, password=service.password,
                                   workspace=str(service.workspace), meta=service.meta), handle)
                print('WAVE_XPRA_READY ' + str(args.info), flush=True)
                while not stopped.wait(0.5):
                    pass
            finally:
                args.info.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
