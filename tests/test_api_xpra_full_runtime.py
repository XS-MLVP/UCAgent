"""Opt-in Xpra acceptance through the real CLI, workflow, PDB and terminals.

Run in Linux with all project requirements, picker, Verilator, Xpra,
xpra-html5, Xvfb, xterm and xclock installed:
UCAGENT_RUN_XPRA_INTEGRATION=1 python -m pytest -q
tests/test_api_xpra_full_runtime.py. No agent or PDB objects are substituted.
"""

import asyncio
import base64
import json
import os
from pathlib import Path
import pty
import signal
import shutil
import socket
import subprocess
import sys
import time
import uuid

import aiohttp
import psutil
import pytest
import requests


pytestmark = pytest.mark.skipif(
    os.environ.get("UCAGENT_RUN_XPRA_INTEGRATION") != "1",
    reason="Requires a complete Linux UCAgent and Xpra server installation",
)


@pytest.mark.parametrize("terminal_mode", ["web-terminal", "web-console"])
def test_cli_cmd_xpra_and_terminals_share_a_complete_agent(tmp_path, terminal_mode):
    """Exercise real CMD wakeups and Xpra with each supported terminal mode."""
    repository = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    dut = workspace / "Adder"
    workspace.mkdir()
    source = tmp_path / "Adder.v"
    source.write_bytes((repository / "examples/Adder/Adder.v").read_bytes())
    # Reserve distinct ports together before the CLI takes over their listeners.
    reservations = [socket.socket() for _ in range(3)]
    try:
        for reservation in reservations:
            reservation.bind(("127.0.0.1", 0))
        cmd_port, terminal_port, master_port = [
            reservation.getsockname()[1] for reservation in reservations
        ]
    finally:
        for reservation in reservations:
            reservation.close()
    picker = shutil.which("picker")
    assert picker, "Install the official XS-MLVP picker and Verilator before enabling this test."
    exported = subprocess.run([
        picker, "export", str(source), "--sname", "Adder",
        "--target_dir", str(workspace) + os.sep, "--lang", "python", "-j", "4",
    ], cwd=tmp_path, capture_output=True, text=True, timeout=180)
    assert exported.returncode == 0, exported.stdout[-8000:] + exported.stderr[-8000:]
    (dut / "README.md").write_bytes((repository / "examples/Adder/README.md").read_bytes())
    password = uuid.uuid4().hex
    master_password = uuid.uuid4().hex
    base = f"http://127.0.0.1:{cmd_port}"
    client = requests.Session()
    client.auth = ("ucagent", password)
    master_client = requests.Session()
    master_client.auth = ("ucagent", master_password)
    proxy = f"http://127.0.0.1:{master_port}/agent/self/cmd"
    log_path = tmp_path / "cli.log"
    command = [
        sys.executable, str(repository / "ucagent.py"), str(workspace), "Adder",
        "--backend", "blank", "--human", "--no-embed-tools",
        "--export-cmd-api", f"127.0.0.1:{cmd_port} {password}",
        "--" + terminal_mode, f"127.0.0.1:{terminal_port} {password}",
        "--icmd", f"master_api_start 127.0.0.1 {master_port} --password {master_password}",
    ]

    def wait_for(predicate, timeout=60):
        """Wait for real runtime state and include CLI output on failure."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if predicate():
                    return
            except requests.ConnectionError:
                pass
            if process.poll() is not None:
                break
            time.sleep(0.2)
        pytest.fail(log_path.read_text(errors="replace")[-16000:])

    def console_contains(text):
        """Read captured runtime output rather than accepting an enqueue alone."""
        response = client.get(base + "/api/console?strip_ansi=true", timeout=5)
        response.raise_for_status()
        return text in "\n".join(response.json()["data"])

    async def check_terminal_input():
        """Prove terminal input still reaches the real PDB while Xpra runs."""
        headers = {"Authorization": "Basic " + base64.b64encode(
            f"ucagent:{password}".encode()).decode()}
        async with aiohttp.ClientSession(headers=headers) as network:
            async with network.ws_connect(f"http://127.0.0.1:{terminal_port}/ws") as connection:
                await connection.send_str("shell printf 'FULL_''TERMINAL_OK\\n'\r")
                output = ""
                async with asyncio.timeout(15):
                    async for message in connection:
                        if message.type == aiohttp.WSMsgType.BINARY:
                            output += message.data.decode(errors="replace")
                        elif message.type == aiohttp.WSMsgType.TEXT:
                            output += message.data
                        if "FULL_TERMINAL_OK" in output:
                            break
                assert "FULL_TERMINAL_OK" in output

    owned = []
    terminal_master, terminal_slave = pty.openpty()
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            command, cwd=repository, stdin=terminal_slave, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            wait_for(lambda: client.get(base + "/api/status", timeout=5).status_code == 200)
            assert requests.get(base + "/", timeout=5).status_code == 401
            assert client.get(base + "/", timeout=5).status_code == 200
            tasks = client.get(base + "/api/tasks", timeout=5).json()["data"]
            assert len(tasks["task_list"]["stage_list"]) > 1
            assert "Adder" in tasks["mission_name"]
            runtime = json.loads((workspace / ".ucagent/runtime_config.json").read_text())
            assert Path(runtime["ucagent_python_path"]).resolve() == repository
            assert client.get(base + "/api/cmds?prefix=status", timeout=5).json()["data"] == ["status"]
            wait_for(lambda: master_client.get(proxy + "/api/xpra/sessions", timeout=5).status_code == 200)
            assert requests.get(proxy + "/api/xpra/sessions", timeout=5).status_code == 401
            response = client.post(base + "/api/cmds/batch", json={"cmds": [
                "status", "help status", "chcwd .", "pwd",
                "shell printf 'FULL_''CMD_OK\\n'",
            ]}, timeout=5)
            assert response.status_code == 200, response.text
            wait_for(lambda: console_contains("FULL_CMD_OK"))
            assert console_contains("Current working directory:")

            for mode, application in (("gui", "xclock"), ("console", "bash -l")):
                marker = "full-runtime-" + uuid.uuid4().hex
                executable = f"{application} -name {marker}" if mode == "gui" else application
                response = client.post(base + "/api/xpra/sessions", json={
                    "name": marker, "mode": mode, "command": executable,
                }, timeout=60)
                assert response.status_code == 201, response.text
                session = response.json()
                assert session["status"] == "running"
                assert client.get(base + "/api/xpra/" + session["viewer_path"], timeout=5).status_code == 200
                if mode == "gui":
                    for candidate in psutil.process_iter(["cmdline"]):
                        args = candidate.info["cmdline"] or []
                        if any(arg.startswith("--start-child=") and marker in arg for arg in args):
                            owned = [candidate, *candidate.children(recursive=True)]
                    assert owned
                else:
                    response = client.delete(base + "/api/xpra/sessions/" + session["id"], timeout=15)
                    assert response.status_code == 200
            asyncio.run(check_terminal_input())
            proxied = master_client.get(proxy + "/api/xpra/sessions", timeout=5)
            assert proxied.status_code == 200
            assert proxied.json()["active_count"] == 1
            assert client.post(base + "/api/interrupt", timeout=5).status_code == 200
            assert client.get(base + "/api/xpra/sessions", timeout=5).json()["active_count"] == 1
            assert client.post(base + "/api/cmd", json={"cmd": "quit"}, timeout=5).status_code == 200
            process.wait(timeout=30)
            assert process.returncode == 0, log_path.read_text(errors="replace")[-16000:]
            for candidate in owned:
                assert not candidate.is_running() or candidate.status() == psutil.STATUS_ZOMBIE
        finally:
            client.close()
            master_client.close()
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            for candidate in reversed(owned):
                try:
                    if candidate.is_running():
                        candidate.kill()
                except psutil.NoSuchProcess:
                    pass
            os.close(terminal_master)
            os.close(terminal_slave)
