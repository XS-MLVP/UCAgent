"""Quick launch must stay small and never turn service restoration into verification work."""
import argparse
import importlib.util
import json
from pathlib import Path
import socket

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'ucagent/scripts/formal-quick-run/scripts/quick_run.py'
spec = importlib.util.spec_from_file_location('quick_run', SCRIPT)
quick = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quick)


@pytest.fixture
def setup(tmp_path):
    """Build isolated source/task roots rather than modifying repository outputs."""
    root = tmp_path / 'checkout'
    (root / 'ucagent/plugins/Formal').mkdir(parents=True)
    (root / 'ucagent/__init__.py').write_text('')
    (root / 'ucagent/plugins/Formal/pyproject.toml').write_text('')
    source = root / 'examples/Adder'
    source.mkdir(parents=True)
    (source / 'README.md').write_text('Adder requirement')
    (source / 'Adder.v').write_text('module Adder; endmodule')
    (source / 'config.v').write_text('`define DEMO')
    (source / 'formal_test').mkdir()
    (source / 'formal_test/old_checker.sv').write_text('must not copy')
    (source / '.ucagent').mkdir()
    (source / '.ucagent/state.json').write_text('{}')
    args = argparse.Namespace(action='start', checkout=str(root), source=str(source), dut=None,
                              workspace=None, config=None, backend='claude', seed=11020,
                              master=None, agent_id=None, port=0, public_host='192.0.2.1',
                              runs_dir=str(tmp_path / 'runs'), wait=1, dry_run=True)
    return root, source, args


def test_start_defaults_and_dry_run_keep_only_raw_inputs(setup, monkeypatch):
    """One invocation builds the command; no audit, previous outputs or model run is needed."""
    _, source, args = setup
    monkeypatch.setattr(quick.subprocess, 'Popen', lambda *a, **k: pytest.fail('dry run spawned a model'))
    result = quick.launch(args)
    w = Path(result['workspace'])
    assert (w / 'Adder/Adder.v').read_bytes() == (source / 'Adder.v').read_bytes()
    assert not (w / 'Adder/formal_test').exists()
    assert not (w / 'Adder/.ucagent').exists()
    cmd = result['command']
    assert '--loop' in cmd and '--exit-on-completion' in cmd and '--master' not in cmd
    assert cmd[0] == quick.sys.executable
    assert (w / 'quick-config.yaml').exists()
    assert not (w / quick.RECEIPT).exists()
    assert result['url'].startswith('http://192.0.2.1:')


def test_bad_inputs_fail_before_creating_workspace_or_process(setup, monkeypatch):
    """Missing RTL and symlinked raw inputs cannot silently import old or unrelated data."""
    _, source, args = setup
    (source / 'Adder.v').unlink()
    (source / 'config.v').unlink()
    with pytest.raises(ValueError, match='No .v'):
        quick.launch(args)
    assert not Path(args.runs_dir).exists()
    (source / 'Adder.v').symlink_to(source / 'README.md')
    with pytest.raises(ValueError, match='symlink'):
        quick.launch(args)


def test_occupied_port_is_not_reused_or_killed():
    """User processes are never stopped to satisfy the requested preview port."""
    with socket.socket() as sock:
        sock.bind(('0.0.0.0', 0))
        sock.listen()
        with pytest.raises(OSError):
            quick.port_number(sock.getsockname()[1])


def test_actual_start_records_small_receipt_and_returns_master_link(setup, monkeypatch):
    """Managed background lifetime is explicit and the ready check is bounded."""
    _, _, args = setup
    args.dry_run = False
    args.master = '127.0.0.1:8800'
    seen = []

    class Process:
        """Represent the one service created by this launch."""
        pid = 1234

        def poll(self):
            """Remain alive during readiness polling."""
            return None

    def spawn(cmd, **kwargs):
        """Capture executable argument arrays without invoking a shell."""
        seen.append((cmd, kwargs))
        return Process()

    monkeypatch.setattr(quick.subprocess, 'Popen', spawn)
    monkeypatch.setattr(quick, 'get_json', lambda url: {'status': 'ok'})
    result = quick.launch(args)
    assert result['status'] == 'online'
    assert result['url'].startswith('http://192.0.2.1:8800/agent/quick-')
    receipt = json.loads((Path(result['workspace']) / quick.RECEIPT).read_text())
    assert receipt['pid'] == 1234
    assert len(list(Path(result['workspace']).iterdir())) == 4  # input, config, log, receipt
    assert seen[0][1]['start_new_session'] is True
    assert seen[0][1]['env']['PYTHONPATH'].startswith(args.checkout)


def test_service_restoration_never_loops_or_rewinds(setup, tmp_path):
    """Existing stage/proof files stay byte-identical during command preparation."""
    _, _, args = setup
    w = tmp_path / 'existing'
    (w / '.ucagent').mkdir(parents=True)
    (w / 'Adder').mkdir()
    cfg = w / 'original.yaml'
    cfg.write_text('langfuse: {enable: false}')
    info = {'seed': 123, 'config_file': str(cfg), 'all_completed': True, 'is_agent_exit': True, 'stage_index': 9}
    p = w / '.ucagent/ucagent_info.json'
    p.write_text(json.dumps(info))
    (w / '.ucagent/runtime_config.json').write_text(json.dumps({'DUT': 'Adder', 'OUT': 'proofs'}))
    before = p.read_bytes()
    args.action = 'online'
    args.workspace = str(w)
    result = quick.launch(args)
    cmd = result['command']
    for flag in ['--loop', '--exit-on-completion', '--no-history', '--force-stage-index']:
        assert flag not in cmd
    assert cmd[cmd.index('--output') + 1] == 'proofs'
    assert cmd[cmd.index('--seed') + 1] == '123'
    assert p.read_bytes() == before


def test_online_existing_identity_and_duplicate_process(setup, monkeypatch, tmp_path):
    """Rerunning online returns the prior URL rather than starting a duplicate."""
    _, _, args = setup
    w = tmp_path / 'existing'
    w.mkdir()
    meta = {'workspace': str(w), 'pid': 42, 'agent_id': 'original-id', 'public_host': '192.0.2.1',
            'port': 12345, 'master': '127.0.0.1:8800', 'log': str(w / 'quick-start.log')}
    (w / quick.RECEIPT).write_text(json.dumps(meta))
    args.action = 'online'
    args.workspace = str(w)
    monkeypatch.setattr(quick, 'alive', lambda pid, workspace: True)
    monkeypatch.setattr(quick.subprocess, 'Popen', lambda *a, **k: pytest.fail('duplicate process'))
    r = quick.launch(args)
    assert r['status'] == 'already_running'
    assert r['url'] == 'http://192.0.2.1:8800/agent/original-id/cmd/'


def test_missing_master_identity_is_actionable(setup, monkeypatch, tmp_path):
    """Manual old tasks require their recorded Master identity rather than creating a ghost entry."""
    _, _, args = setup
    w = tmp_path / 'manual'
    (w / '.ucagent').mkdir(parents=True)
    (w / 'Adder').mkdir()
    cfg = w / 'cfg.yaml'
    cfg.write_text('{}')
    (w / '.ucagent/ucagent_info.json').write_text(json.dumps({'config_file': str(cfg)}))
    (w / '.ucagent/runtime_config.json').write_text(json.dumps({'DUT': 'Adder', 'OUT': 'formal_test'}))
    args.action = 'online'
    args.workspace = str(w)
    args.master = '127.0.0.1:8800'
    monkeypatch.setattr(quick, 'get_json', lambda url: {})
    with pytest.raises(ValueError, match='--agent-id'):
        quick.launch(args)


def test_readiness_timeout_returns_starting_without_duplicate_launch(setup, monkeypatch):
    """Slow initialization returns promptly rather than starting another process."""
    _, _, args = setup
    args.dry_run = False
    args.wait = 0
    spawned = []

    class Process:
        """Represent a service still starting at the bounded deadline."""
        pid = 1234

    def spawn(*arguments, **kwargs):
        """Record one launch only."""
        spawned.append(arguments)
        return Process()

    monkeypatch.setattr(quick.subprocess, 'Popen', spawn)
    result = quick.launch(args)
    assert result['status'] == 'starting'
    assert len(spawned) == 1
    assert Path(result['log']).exists()


def test_child_failure_reports_log_and_does_not_repeat_launch(setup, monkeypatch):
    """Immediate failure stays an error rather than being called online."""
    _, _, args = setup
    args.dry_run = False

    class Process:
        """Represent an immediately failed startup."""
        pid = 1234

        def poll(self):
            """Return the actual child failure."""
            return 2

    monkeypatch.setattr(quick.subprocess, 'Popen', lambda *a, **k: Process())
    with pytest.raises(ValueError, match='exited with code 2; inspect'):
        quick.launch(args)
