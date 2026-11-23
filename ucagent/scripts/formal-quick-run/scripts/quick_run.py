"""Quick local Formal smoke runs and service-only restoration; no proof audit or source edits."""

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote, urlsplit
from urllib.request import ProxyHandler, build_opener
import uuid

RECEIPT = '.formal-quick-run.json'
OPENER = build_opener(ProxyHandler({}))


def get_json(url):
    """Read one local task endpoint without inherited HTTP proxies."""
    with OPENER.open(url, timeout=1) as response:
        return json.load(response)


def alive(pid, workspace):
    """Recognize this task process without trusting a reused numeric PID."""
    try:
        parts = Path(f'/proc/{int(pid)}/cmdline').read_bytes().split(b'\0')
        return b'ucagent' in parts and os.fsencode(str(workspace)) in parts
    except (OSError, ValueError, TypeError):
        return False


def port_number(requested):
    """Select or check a free local port immediately before launching."""
    with socket.socket() as sock:
        sock.bind(('0.0.0.0', requested or 0))
        return sock.getsockname()[1]


def master_address(value):
    """Require a reachable existing Master; never start an unnecessary second Master."""
    if not value:
        return None
    parsed = urlsplit(value if '://' in value else 'http://' + value)
    if parsed.scheme != 'http' or not parsed.hostname or not parsed.port or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('--master must be http://host:port or host:port without credentials or path')
    authority = parsed.netloc
    get_json('http://' + authority + '/api/agents')
    return authority


def prepare_source(source, destination):
    """Copy only raw design/requirement inputs; never bring old task state into a smoke run."""
    source = source.resolve(strict=True)
    if not source.is_dir() or not (source / 'README.md').is_file():
        raise ValueError('--source must be a raw DUT directory containing README.md')
    selected = []
    for folder, dirs, files in os.walk(source):
        dirs[:] = [name for name in dirs if not name.startswith('.') and name not in {'formal_test', 'unit_test', 'unity_test', 'output', 'build', 'obj_dir'}]
        for name in files:
            path = Path(folder) / name
            if name not in {'README.md', 'filelist.txt'} and path.suffix.lower() not in {'.v', '.sv', '.vh', '.svh', '.hex', '.mem'}:
                continue
            if any(part.is_symlink() for part in [path, *path.parents] if part.is_relative_to(source)):
                raise ValueError(f'Raw input must not be a symlink: {path}')
            selected.append(path)
    if not any(path.suffix.lower() in {'.v', '.sv'} for path in selected):
        raise ValueError('No .v or .sv design sources in --source')
    for path in selected:
        if destination is None:
            continue
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def links(meta):
    """Return concise direct and optional Master links using the caller-specified browser host."""
    direct = f"http://{meta['public_host']}:{meta['port']}/"
    result = {'workspace': meta['workspace'], 'url': direct, 'log': meta['log'], 'agent_id': meta['agent_id']}
    if meta.get('master'):
        master = meta['master']
        # A loopback Master registration address still needs a remotely reachable browser link.
        parsed = urlsplit('http://' + master)
        browser_master = f"{meta['public_host']}:{parsed.port}" if parsed.hostname in {'localhost', '127.0.0.1', '0.0.0.0'} else master
        result['url'] = f"http://{browser_master}/agent/{quote(meta['agent_id'], safe='')}/cmd/"
        result['direct_url'] = direct
    return result


def launch(args):
    """Start a fresh smoke task, or revive the same task identity without a loop."""
    checkout = Path(args.checkout).resolve(strict=True)
    plugin = checkout / 'ucagent/plugins/Formal'
    if not (checkout / 'ucagent/__init__.py').is_file() or not (plugin / 'pyproject.toml').is_file():
        raise ValueError('--checkout must contain UCAgent and the Formal plugin')
    if args.action == 'start':
        source = Path(args.source or checkout / 'examples/Adder').resolve(strict=True)
        dut = args.dut or source.name
        if not dut or Path(dut).name != dut or dut in {'.', '..'}:
            raise ValueError('--dut must be one directory name')
        # Check the design before allocating a run directory.
        if not (source / 'README.md').is_file():
            raise ValueError('The raw DUT source needs README.md')
        prepare_source(source, None)
        if args.config:
            Path(args.config).resolve(strict=True)
        master = master_address(args.master)
        port = port_number(args.port)
        runs = Path(args.runs_dir).resolve() if args.runs_dir else checkout / 'output/quick-formal'
        runs.mkdir(parents=True, exist_ok=True)
        workspace = Path(tempfile.mkdtemp(prefix=dut + '-', dir=runs))
        prepare_source(source, workspace / dut)
        config = workspace / 'quick-config.yaml'
        if args.config:
            shutil.copy2(Path(args.config).resolve(strict=True), config)
        else:
            config.write_text('langfuse:\n  enable: false\nembed:\n  enable: false\nvmanager:\n  llm_suggestion:\n    check_fail_refinement:\n      enable: false\n    check_pass_refinement:\n      enable: false\n')
        meta = {'workspace': str(workspace), 'dut': dut, 'config': str(config), 'output': 'formal_test',
                'backend': args.backend, 'seed': args.seed, 'master': master, 'port': port,
                'agent_id': 'quick-' + uuid.uuid4().hex[:12], 'public_host': args.public_host,
                'checkout': str(checkout)}
    else:
        workspace = Path(args.workspace).resolve(strict=True)
        saved = workspace / RECEIPT
        meta = json.loads(saved.read_text()) if saved.is_file() else {}
        if meta.get('pid') and alive(meta['pid'], workspace):
            return {'status': 'already_running', **links(meta)}
        info = json.loads((workspace / '.ucagent/ucagent_info.json').read_text())
        snapshot = json.loads((workspace / '.ucagent/runtime_config.json').read_text())
        dut = snapshot['DUT']
        if not isinstance(dut, str) or Path(dut).name != dut or dut in {'.', '..'} or not (workspace / dut).is_dir():
            raise ValueError('Saved DUT must name one existing workspace directory')
        config_value = args.config or meta.get('config') or info.get('config_file')
        if not isinstance(config_value, str) or not config_value:
            raise ValueError('Saved config unavailable; pass --config with the original task config')
        config = Path(config_value)
        if not config.is_absolute():
            config = workspace / config
        config = config.resolve(strict=True)
        master = master_address(args.master or meta.get('master'))
        agent_id = args.agent_id or meta.get('agent_id')
        if master and not agent_id:
            raise ValueError('Pass --agent-id from Master to restore the same offline entry')
        port = port_number(args.port or meta.get('port'))
        meta = {**meta, 'workspace': str(workspace), 'dut': dut, 'config': str(config),
                'output': snapshot['OUT'], 'backend': meta.get('backend', args.backend),
                'seed': info.get('seed', args.seed), 'master': master, 'port': port,
                'agent_id': agent_id or 'quick-' + uuid.uuid4().hex[:12],
                'public_host': args.public_host, 'checkout': str(checkout)}
    meta['mode'] = args.action
    meta['log'] = str(workspace / ('quick-start.log' if args.action == 'start' else 'quick-online.log'))
    cmd = [sys.executable, '-m', 'ucagent', str(workspace), meta['dut'], '--plugin', str(plugin),
           '--plugin-workflow', 'formal:formal', '--output', meta['output'], '--backend', meta['backend'],
           '--config', meta['config'], '--seed', str(meta['seed']), '--no-embed-tools', '--mcp-server',
           '--mcp-server-port', '-1', '--export-cmd-api', f"0.0.0.0:{meta['port']}",
           '--client-id', meta['agent_id'], '--stream-output']
    if master:
        cmd.extend(['--master', master])
    if args.action == 'start':
        cmd.extend(['--loop', '--exit-on-completion'])
    if args.dry_run:
        return {'status': 'prepared', 'mode': args.action, 'command': cmd, **links(meta)}
    env = dict(os.environ)
    env['PYTHONPATH'] = str(checkout) + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    with open(meta['log'], 'a') as log:
        process = subprocess.Popen(cmd, cwd=workspace, env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    meta['pid'] = process.pid
    receipt = workspace / RECEIPT
    receipt.write_text(json.dumps(meta, indent=2))
    deadline = time.monotonic() + args.wait
    while time.monotonic() < deadline:
        code = process.poll()
        if code is not None:
            raise ValueError(f"Task exited with code {code}; inspect {meta['log']}")
        try:
            get_json(f"http://127.0.0.1:{meta['port']}/api/mission")
            return {'status': 'online', 'mode': args.action, **links(meta)}
        except (OSError, ValueError):
            time.sleep(0.25)
    return {'status': 'starting', 'mode': args.action, 'next_action': 'Open the link shortly; inspect the log if startup fails.', **links(meta)}


def main():
    """Expose one command per user intent, with automatic ports and concise JSON output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'online'])
    parser.add_argument('--checkout', default=str(Path(__file__).resolve().parents[4]))
    parser.add_argument('--source', help='Raw DUT input directory; default examples/Adder')
    parser.add_argument('--dut')
    parser.add_argument('--workspace', help='Existing task workspace for online')
    parser.add_argument('--config')
    parser.add_argument('--backend', default='claude')
    parser.add_argument('--seed', type=int, default=11020)
    parser.add_argument('--master', help='Existing Master address; omit for a direct task page')
    parser.add_argument('--agent-id', help='Existing Master agent ID for online when no receipt exists')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--public-host', default='127.0.0.1')
    parser.add_argument('--runs-dir')
    parser.add_argument('--wait', type=float, default=15)
    parser.add_argument('--dry-run', action='store_true', help='Prepare inputs and print command without starting a task')
    args = parser.parse_args()
    if args.action == 'online' and not args.workspace:
        parser.error('online requires --workspace')
    try:
        if not 0 <= args.port <= 65535 or not 0 <= args.wait <= 30:
            raise ValueError('--port must be 0..65535 and --wait must be 0..30 seconds')
        result = launch(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({'status': 'error', 'error': str(error)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
