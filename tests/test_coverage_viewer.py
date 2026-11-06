"""Provider-owned coverage links use the unmodified generic Xpra API."""

import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from ucagent.server.api_cmd import PdbCmdApiServer
from ucagent.util.config import Config
from test_waveform_routes import Sessions


def application(root):
    """Let the VCS provider build a page using its own command and VDB path."""
    from toffee_test.utils.code_coverage import CodeCoverageResult
    from toffee_test.utils.code_coverage.vcs import VcsCoverageProvider
    from urllib.parse import unquote
    database = root / "DUT data.vdb"
    database.mkdir(parents=True)
    report = root / "report"
    result = CodeCoverageResult("vcs", databases=[str(database)])
    details = VcsCoverageProvider().build_details(result, report / "coverage_data")
    link, = [item for item in details if item.href]
    page = report / unquote(link.href)
    payload = json.loads(re.search(r"const coverageRequest = (.*);", page.read_text())[1])
    return page, payload


def test_provider_page_uses_generic_authenticated_xpra_api(tmp_path):
    """Coverage needs no special request schema, routes, config or resolver."""
    server = PdbCmdApiServer(SimpleNamespace(
        agent=SimpleNamespace(workspace=str(tmp_path), cfg=Config({"cmd_api": {"xpra": {}}})),
        stdout=None), sock="", password="coverage-password")
    server._xpra = Sessions()
    client = TestClient(server._app)
    client.auth = ("user", server.password)
    try:
        page, payload = application(tmp_path / "nested")
        assert set(payload) == {"command", "mode", "name", "cwd"}
        assert not server._xpra.created
        response = client.get("/workspace/" + page.relative_to(tmp_path).as_posix())
        assert response.status_code == 200
        assert not server._xpra.created
        assert client.post("/api/xpra/sessions", json=payload, auth=("bad", "bad")).status_code == 401
        response = client.post("/api/xpra/sessions", json=payload)
        assert response.status_code == 201, response.text
        assert shlex.split(server._xpra.created[0]["command"]) == [
            "verdi", "-cov", "-covdir", str(tmp_path / "nested/DUT data.vdb")]
    finally:
        server._running = True
        server.stop()


@pytest.mark.parametrize('prefix', ['', '/task/abc/cmd', '/agent/xyz/cmd'])
def test_browser_bridge_preserves_proxy_prefix(tmp_path, prefix):
    """Execute the launch-page JavaScript through POST and viewer navigation."""
    if not shutil.which('node'):
        pytest.skip('Node.js is required for the browser bridge contract')
    page, payload = application(tmp_path)
    script = re.search(r'<script>(.*?)</script>', page.read_text(), re.S)[1]
    current = 'http://localhost:8765' + prefix + '/workspace/report/' + page.name + '?sub_workspace=child'
    harness = '''
const vm = require('vm');
const assert = require('assert');
const requests = [], navigations = [];
const nodes = {status:{textContent:''}, retry:{hidden:true}};
const location = {href:CURRENT, replace: value => navigations.push(value)};
vm.runInNewContext(SCRIPT, {URL, location,
  document:{getElementById: id => nodes[id]},
  fetch: async (url, options) => {requests.push([String(url), options]);
    return {ok:true, json:async()=>({viewer_path:'sessions/abc/view'})};}});
setTimeout(() => {
  assert.equal(requests.length, 1);
  assert.equal(requests[0][0], BASE + 'sessions?sub_workspace=child');
  assert.equal(requests[0][1].method, 'POST');
  assert.deepEqual(JSON.parse(requests[0][1].body), PAYLOAD);
  assert.equal(navigations[0], BASE + 'sessions/abc/view');
}, 20);
'''
    declarations = '\n'.join('const ' + key + ' = ' + json.dumps(value) + ';' for key, value in {
        'CURRENT': current, 'SCRIPT': script, 'BASE': 'http://localhost:8765' + prefix + '/api/xpra/',
        'PAYLOAD': payload,
    }.items())
    completed = subprocess.run(['node', '-e', declarations + harness], text=True, capture_output=True)
    assert completed.returncode == 0, completed.stderr



def test_test_tool_only_selects_gui_mode(tmp_path):
    """Source-tree and installed runs need only the public Toffee GUI option."""
    from ucagent.tools.testops import RunUnityChipTest
    tool = RunUnityChipTest(workspace=str(tmp_path))
    args = tool.get_pytest_args()
    assert "--report-custom=coverage-gui-xpra" in args
    assert not any(arg.startswith(("--coverage-application-", "--custom-key-value=")) for arg in args)


def test_test_tool_serializes_list_options(tmp_path):
    """List-valued pytest options become repeated flags, not Python list strings."""
    from ucagent.tools.testops import RunUnityChipTest
    tool = RunUnityChipTest(workspace=str(tmp_path))
    tool.set_pytest_args({'report-custom': ['coverage-gui-xpra', 'future-option']})
    args = tool.get_pytest_args()
    assert [arg for arg in args if arg.startswith('--report-custom=')] == [
        '--report-custom=coverage-gui-xpra', '--report-custom=future-option']
