"""Configured waveform routes and Xpra launch identity without desktop dependencies."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shlex
import sys
import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from ucagent.server.api_cmd import PdbCmdApiServer
from ucagent.server.api_cmd.xpra import XpraError
from ucagent.util.config import Config
from ucagent.util.waveform_viewer import build_waveform_metadata, load_waveform_metadata, write_waveform_metadata


class Sessions:
    """Model owned session liveness and quota while capturing exact argv."""

    def __init__(self):
        """Start an empty bounded manager."""
        self.created = []
        self.live = set()
        self.max_sessions = 5
        self.lock = threading.Lock()

    def create(self, **kwargs):
        """Reserve capacity and return an owned, live session."""
        with self.lock:
            if len(self.live) >= self.max_sessions:
                raise XpraError(429, 'XPRA_QUOTA_EXCEEDED', 'Quota reached.', 'Close an existing session.')
            self.created.append(kwargs)
            session_id = str(len(self.created))
            self.live.add(session_id)
            return self.get(session_id)

    def socket_path(self, session_id):
        """Reject exited sessions so reopening creates another session."""
        if session_id not in self.live:
            raise XpraError(503, 'XPRA_SESSION_UNAVAILABLE', 'Exited.', 'Reopen the waveform.')
        return '/owned/' + session_id

    def get(self, session_id):
        """Return the existing API response shape."""
        return dict(id=session_id, status='running', viewer_path=f'sessions/{session_id}/view')

    def close(self):
        """Clean the fake service on shutdown."""
        self.live.clear()


@pytest.fixture
def service(tmp_path):
    """Serve canonical wave metadata with an authenticated, fake Xpra owner."""
    cfg = Config(dict(cmd_api=dict(xpra={}, waveform_viewers=dict(
        fst=dict(kind='web', url='/surfer/'), vcd=dict(kind='web', url='/surfer/'),
        fsdb=dict(kind='xpra', script='verdi/launch_verdi.py', args=['--meta','{wave_meta}','--verdi','verdi'], env={'EXAMPLE':'a b'}, idle_timeout=30)))))
    server = PdbCmdApiServer(SimpleNamespace(agent=SimpleNamespace(workspace=str(tmp_path), cfg=cfg), stdout=None),
        sock='', password='wave-password')
    server._xpra = Sessions()
    client = TestClient(server._app)
    client.auth = ('user', server.password)
    yield server, client
    server._running = True
    server.stop()


def _meta(root, name='wave 空格.fsdb'):
    """Create an ordinary metadata file that pins exactly one waveform."""
    wave = root / name
    wave.parent.mkdir(parents=True, exist_ok=True)
    wave.write_bytes(b'wave')
    meta, payload, _ = build_waveform_metadata(root, name)
    write_waveform_metadata(root, meta, payload)
    return meta


def test_configured_python_launch_reuse_concurrency_and_exit(tmp_path, service):
    """Concurrent REST opens share a live session; content/config changes start another."""
    server, client = service
    meta = _meta(tmp_path)
    assert client.get('/wave/', params={'meta':meta}).status_code == 200
    assert server._xpra.created == []
    def open_wave(_):
        """Open one tab through the public REST API."""
        response = client.post('/api/xpra/sessions', json={'wave_meta':meta})
        assert response.status_code == 201, response.text
        return response.json()['id']
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert set(pool.map(open_wave, range(6))) == {'1'}
    captured = server._xpra.created[0]
    argv = shlex.split(captured['command'])
    assert argv[:2] == [sys.executable, str(Path(__file__).resolve().parents[1] / 'ucagent/scripts/verdi/launch_verdi.py')]
    assert argv[2:] == ['--meta', str((tmp_path/meta).resolve()), '--verdi', 'verdi']
    assert captured['env'] == {'EXAMPLE':'a b'} and captured['idle_timeout'] == 30
    payload = load_waveform_metadata(tmp_path, meta)[1]
    payload['signals'] = ['TOP.dut.result']
    write_waveform_metadata(tmp_path, meta, payload)
    assert open_wave(0) == '2'
    server.pdb.agent.cfg.cmd_api.waveform_viewers.fsdb.args.append('--extra')
    assert open_wave(0) == '3'
    server._xpra.live.remove('3')
    assert open_wave(0) == '4'
    server._xpra.max_sessions = len(server._xpra.live)
    server.pdb.agent.cfg.cmd_api.waveform_viewers.fsdb.args.append('change')
    assert client.post('/api/xpra/sessions', json={'wave_meta':meta}).status_code == 429


@pytest.mark.parametrize('script,code', [('missing.py','WAVEFORM_SCRIPT_MISSING'),
    ('../launch_verdi.py','WAVEFORM_SCRIPT_INVALID'), ('sub/../../launch.py','WAVEFORM_SCRIPT_INVALID')])
def test_relative_scripts_never_search_cwd_or_path(tmp_path, service, script, code):
    """Only the actual running package's scripts directory supplies relative scripts."""
    server, client = service
    (tmp_path / 'missing.py').write_text('pass')
    meta = _meta(tmp_path)
    server.pdb.agent.cfg.cmd_api.waveform_viewers.fsdb.script = script
    result = client.post('/api/xpra/sessions', json={'wave_meta':meta})
    assert result.status_code == 503
    assert result.json()['detail']['error_code'] == code
    assert not server._xpra.created


def test_absolute_and_nested_package_scripts(tmp_path, service, monkeypatch):
    """Absolute paths are explicit; nested relative scripts resolve in the running package."""
    server, client = service
    meta = _meta(tmp_path)
    script = tmp_path / 'launcher absolute.py'
    script.write_text('pass')
    viewer = server.pdb.agent.cfg.cmd_api.waveform_viewers.fsdb
    viewer.script = str(script)
    assert client.post('/api/xpra/sessions', json={'wave_meta':meta}).status_code == 201
    assert shlex.split(server._xpra.created[-1]['command'])[1] == str(script.resolve())
    package = tmp_path / 'installed/ucagent'
    nested = package / 'scripts/nested/launch.py'
    nested.parent.mkdir(parents=True)
    nested.write_text('pass')
    monkeypatch.setattr('ucagent.server.api_cmd.waveform_routes.inspect.getfile', lambda obj: str(package/'__init__.py'))
    viewer.script = 'nested/launch.py'
    assert client.post('/api/xpra/sessions', json={'wave_meta':meta}).status_code == 201
    assert shlex.split(server._xpra.created[-1]['command'])[1] == str(nested.resolve())
    outside = tmp_path / 'external.py'
    outside.write_text('pass')
    (package/'scripts/escape.py').symlink_to(outside)
    viewer.script = 'escape.py'
    assert client.post('/api/xpra/sessions', json={'wave_meta':meta}).status_code == 503
    (tmp_path / 'loop.py').symlink_to('loop.py')
    viewer.script = str(tmp_path / 'loop.py')
    response = client.post('/api/xpra/sessions', json={'wave_meta':meta})
    assert response.status_code == 503
    assert response.json()['detail']['error_code'] == 'WAVEFORM_SCRIPT_INVALID'


@pytest.mark.parametrize('value', [dict(kind='web',url='https://example.test/'),
    dict(kind='web',url='/wave/'),dict(kind='web',url='/surfer/?x=1'),
    dict(kind='web',url='/%2e%2e/'),dict(kind='xpra',script='a.py',args='--meta'),
    dict(kind='xpra',script='a\0.py'), dict(kind='xpra',script='a.py',args=['a\0b']),
    dict(kind='xpra',script='a.py',env={'TEST':'a\0b'}),
    dict(kind='xpra',script='a.py',idle_timeout=0)])
def test_malformed_configuration_has_bounded_diagnostics(tmp_path, service, value):
    """A broken viewer cannot launch an arbitrary fallback or leak configured secrets."""
    server, client = service
    server.pdb.agent.cfg.cmd_api.waveform_viewers.fsdb = Config(value)
    response = client.get('/wave/', params={'meta':_meta(tmp_path)})
    assert response.status_code == 503
    assert response.json()['detail']['next_action']
    assert server._xpra.created == []


@pytest.mark.parametrize('extension', ['other', 'usdb'])
def test_custom_format_and_missing_mapping(tmp_path, service, extension):
    """USDB and other extensions need explicit viewer configuration before opening."""
    server, client = service
    meta = _meta(tmp_path, 'trace.' + extension)
    assert client.get('/wave/',params={'meta':meta}).status_code == 415
    setattr(server.pdb.agent.cfg.cmd_api.waveform_viewers, extension, Config(dict(kind='web',url='/custom/')))
    assert extension in client.get('/api/waveform/viewers').json()['formats']
    response = client.get('/wave/',params={'meta':meta},follow_redirects=False)
    assert response.headers['location'] == '../custom/?meta=trace.' + extension + '.json'
    assert client.post('/api/xpra/sessions',json={'wave_meta':meta}).status_code == 422


@pytest.mark.parametrize('path', ['/wave/?meta=a.fsdb.json', '/api/waveform/metadata?meta=a.fsdb.json',
    '/api/waveform/viewers', '/api/xpra/sessions'])
def test_waveform_surfaces_preserve_authentication(service, path):
    """Metadata and launch APIs have the same CMD authentication policy as sessions."""
    _, client = service
    assert client.get(path, auth=('user','wrong')).status_code == 401


def test_tampered_metadata_is_rejected_on_all_viewing_surfaces(tmp_path, service):
    """Dispatch, Surfer and Xpra reject a valid-shape edit without re-signing it."""
    server, client = service
    meta = _meta(tmp_path)
    stored = json.loads((tmp_path / meta).read_text())
    stored['signals'] = ['TOP.forged']
    modified = json.dumps(stored)
    (tmp_path / meta).write_text(modified)
    for endpoint in ('/wave/', '/api/waveform/metadata'):
        result = client.get(endpoint, params={'meta': meta})
        assert result.status_code == 422
        assert result.json()['detail']['error_code'] == 'WAVEFORM_METADATA_INTEGRITY_FAILED'
    result = client.post('/api/xpra/sessions', json={'wave_meta': meta})
    assert result.status_code == 422
    assert result.json()['detail']['error_code'] == 'WAVEFORM_METADATA_INTEGRITY_FAILED'
    result = client.post('/api/waveform/metadata', json={'waveform_file': meta[:-5]})
    assert result.status_code == 422
    assert result.json()['detail']['error_code'] == 'WAVEFORM_METADATA_INTEGRITY_FAILED'
    assert 'WaveInfo' in result.json()['detail']['next_action']
    assert (tmp_path / meta).read_text() == modified
    assert server._xpra.created == []


def test_subworkspace_creation_containment_and_command_injection(tmp_path, service, monkeypatch):
    """Subworkspace paths, script arguments and protected files remain service-controlled."""
    server, client = service
    child = tmp_path/'child'
    (child/'.ucagent').mkdir(parents=True)
    (child/'.ucagent/ucagent_info.json').write_text('{}')
    monkeypatch.setattr('ucagent.util.config.load_runtime_config', lambda workspace: {'DUT':'Demo'})
    (child/'a.fsdb').write_bytes(b'child')
    response = client.post('/api/waveform/metadata?sub_worspace=child',json={'waveform_file':'a.fsdb'})
    assert response.status_code == 200, response.text
    response = client.post('/api/xpra/sessions?sub_workspace=child',json={'wave_meta':'a.fsdb.json'})
    assert response.status_code == 201
    assert server._xpra.created[-1]['cwd'] == 'child'
    assert shlex.split(server._xpra.created[-1]['command'])[3] == str((child/'a.fsdb.json').resolve())
    for body in ({'wave_meta':'a.fsdb.json','command':'sh'}, {'wave_meta':'a.fsdb.json','env':{'X':'Y'}}):
        assert client.post('/api/xpra/sessions?sub_worspace=child',json=body).status_code == 422
    server.pdb.agent.cfg.un_write_dirs=['child/protected']
    (child/'protected').mkdir()
    (child/'protected/a.vcd').write_bytes(b'wave')
    assert client.post('/api/waveform/metadata?sub_worspace=child',json={'waveform_file':'protected/a.vcd'}).status_code == 422
    assert not (child/'protected/a.vcd.json').exists()
    (child/'escape.vcd').symlink_to(tmp_path/'outside.vcd')
    (tmp_path/'outside.vcd').write_bytes(b'outside')
    assert client.post('/api/waveform/metadata?sub_worspace=child',json={'waveform_file':'escape.vcd'}).status_code == 422


@pytest.mark.parametrize('enabled', [False, True])
def test_viewer_config_environment_and_template_resolution(monkeypatch, enabled):
    """Resolved YAML preserves launch placeholders under representative boolean defaults."""
    from ucagent.util.config import load_yaml_with_env_vars
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv('NEED_REF_MODEL', str(enabled).lower())
    monkeypatch.setenv('ENABLE_SKILL', str(enabled).lower())
    monkeypatch.setenv('IGNORE_LLM_CALL', str(enabled).lower())
    cfg = Config(load_yaml_with_env_vars(str(root/'ucagent/setting.yaml')))
    cfg.update_template({'DUT':'Demo','OUT':'out','GUIDE_DOC':'Guide_Doc'})
    viewer = cfg.cmd_api.waveform_viewers.fsdb
    assert viewer.args == ['--meta','{wave_meta}','--verdi','verdi']
    assert viewer.script == 'verdi/launch_verdi.py' and viewer.idle_timeout == -1
    localized = load_yaml_with_env_vars(str(root/'ucagent/lang/zh/config/default.yaml'))
    assert 'source_files' in localized['mission']['prompt']['system']
