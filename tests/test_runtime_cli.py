"""Real CLI processes run deterministic backends through the default runtime assembly."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

BACKEND = '''"""Deterministic verification backend for real CLI lifecycle tests."""
from pathlib import Path
from ucagent.core.backends.base import AgentBackendBase

class TestBackend(AgentBackendBase):
    """Exercise real human review and completion without contacting a model provider."""
    def init(self):
        """Avoid external model setup."""
        pass
    def get_human_message(self, text):
        """Return the prompt without model-specific wrapping."""
        return text
    def get_system_message(self, text):
        """Return the system prompt unchanged."""
        return text
    def messages_get_raw(self):
        """Supply a deterministic empty conversation."""
        return []
    def do_work_values(self, instructions, config):
        """Run the real stage gate and emit completion only after approval."""
        manager = self.vagent.stage_manager
        if self.config.get_value("test_require_mcp", False):
            endpoint = self.vagent.services.require_endpoint("mcp")
            Path(self.vagent.workspace, "ready-port").write_text(str(endpoint["port"]))
        if manager.stage_index < len(manager.stages):
            manager.set_current_stage_journal("Evidence reviewed by deterministic test backend")
            result = manager.complete(2)
            if not result["complete"]:
                return result
        return manager.exit()
    def do_work_stream(self, instructions, config):
        """Use the same deterministic gate for streaming mode."""
        return self.do_work_values(instructions, config)
'''


def cli_command(tmp_path, *, human=False, backend="test", require_mcp=False):
    """Prepare complete resolved configuration and a genuine importable backend."""
    (tmp_path / "DUT").mkdir(exist_ok=True)
    (tmp_path / "DUT/README.md").write_text("# DUT\nTest configuration\n")
    (tmp_path / "runtime_test_backend.py").write_text(BACKEND)
    config = {"workflow": None, "backend": {"key_name": backend, "test": {"clss": "runtime_test_backend.TestBackend"}},
              "test_require_mcp": require_mcp,
              "langfuse": {"enable": False}, "skill": {"use_skill": False},
              "vmanager": {"llm_suggestion": {"check_fail_refinement": {"enable": False},
                                                "check_pass_refinement": {"enable": False}}},
              "loop_settings": {"max_loop_retry": 1, "retry_delay_start": 0, "retry_delay_end": 0},
              "stage": [{"name": "review", "desc": "Evidence", "task": ["Verify evidence"],
                         "need_human_check": human, "checker": []}]}
    path = tmp_path / "runtime.yaml"
    path.write_text(yaml.safe_dump(config))
    return [sys.executable, str(ROOT / "ucagent.py"), str(tmp_path), "DUT", "--config", str(path),
            "--no-embed-tools", "--no-history", "--append-py-path", str(tmp_path)]


def run_cli(command, *, input=None):
    """Run the installed source entrypoint with a hard failure deadline."""
    return subprocess.run(command, cwd=ROOT, input=input, capture_output=True, text=True, timeout=20)


def test_real_cli_once_completes_and_persists(tmp_path):
    """Default noninteractive startup executes the real domain and closes successfully."""
    result = run_cli(cli_command(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads((tmp_path / ".ucagent/ucagent_info.json").read_text())
    assert state["all_completed"] and state["is_agent_exit"]
    assert state["runtime"]["task_outcome"] == "completed"


def test_real_cli_human_wait_without_control_returns_nonzero(tmp_path):
    """Headless human review persists its blocking reason instead of silently succeeding."""
    result = run_cli(cli_command(tmp_path, human=True))
    assert result.returncode == 2, result.stdout + result.stderr
    state = json.loads((tmp_path / ".ucagent/ucagent_info.json").read_text())
    assert not state["all_completed"]
    assert state["runtime"]["close_reason"] == "human_review_unavailable"


def test_real_cli_initial_commands_work_without_entering_console(tmp_path):
    """User initialization is sequential and runs before the default model action."""
    result = run_cli(cli_command(tmp_path, backend="blank") + ["--icmd", "shell printf ready > initial.txt", "--icmd", "quit"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "initial.txt").read_text() == "ready"


def test_real_cli_console_can_query_and_quit(tmp_path):
    """Human console stdin uses the registry and exits through the common host."""
    result = run_cli(cli_command(tmp_path, backend="blank") + ["--human"], input="pwd\nquit\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "cwd:" in result.stdout


def test_real_cli_mcp_is_ready_before_backend_and_closes_on_completion(tmp_path):
    """External-backend prerequisites use the actual ready port before any model work."""
    command = cli_command(tmp_path, require_mcp=True) + ["--mcp-server", "--mcp-server-port", "0", "--exit-on-completion", "--loop"]
    result = run_cli(command)
    assert result.returncode == 0, result.stdout + result.stderr
    assert int((tmp_path / "ready-port").read_text()) > 0


def test_real_cli_headless_http_review_complete_exit(tmp_path):
    """A headless process waits for revision-checked review, revalidates, then stops cleanly."""
    import socket
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    command = cli_command(tmp_path, human=True) + ["--export-cmd-api", f"127.0.0.1:{port}", "--exit-on-completion", "--loop"]
    logfile = tmp_path / "cli.log"
    with logfile.open("w") as output:
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=output)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=1) as client:
                deadline = time.monotonic() + 12
                while True:
                    assert process.poll() is None, logfile.read_text()
                    assert time.monotonic() < deadline, logfile.read_text()
                    try:
                        response = client.get("/api/runtime/status")
                        if response.status_code == 200 and response.json()["data"]["execution"] == "waiting_human":
                            break
                    except httpx.ConnectError:
                        pass
                    time.sleep(0.05)
                snapshot = client.get("/api/stages/state").json()["data"]
                response = client.post("/api/stages/review", json={"index": snapshot["stage_index"],
                    "expected_revision": snapshot["control_revision"], "approved": True, "message": "Reviewed", "resume": True})
                assert response.status_code == 200, response.text
                assert "operation" in response.json()["data"]
            process.wait(timeout=10)
            assert process.returncode == 0, logfile.read_text()
            saved = json.loads((tmp_path / ".ucagent/ucagent_info.json").read_text())
            assert saved["all_completed"] and saved["runtime"]["task_outcome"] == "completed"
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


def test_real_cli_tui_returns_to_console_and_quits(tmp_path):
    """The default --tui entrypoint detaches into Console and closes through typed quit."""
    import pty
    import select
    master, slave = pty.openpty()
    process = subprocess.Popen(cli_command(tmp_path, backend="blank") + ["--tui"], cwd=ROOT,
        stdin=slave, stdout=slave, stderr=slave, env={**os.environ, "TERM": "xterm-256color"})
    os.close(slave)
    received = bytearray()
    try:
        deadline = time.monotonic() + 12
        while b"tok/s" not in received:
            assert process.poll() is None and time.monotonic() < deadline, received.decode(errors="replace")[-4000:]
            if select.select([master], [], [], 0.1)[0]:
                received.extend(os.read(master, 65536))
        os.write(master, b"\x11")
        while b"\x1b[?1049l" not in received:
            assert time.monotonic() < deadline, received.decode(errors="replace")[-4000:]
            if select.select([master], [], [], 0.1)[0]:
                received.extend(os.read(master, 65536))
        os.write(master, b"quit\n")
        process.wait(timeout=10)
        assert process.returncode == 0, received.decode(errors="replace")[-4000:]
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        os.close(master)


def test_real_cli_initial_single_round_is_not_followed_by_another_model_run(tmp_path):
    """A requested initial single round cannot race the default automatic continuation."""
    command = cli_command(tmp_path)
    backend = tmp_path / "runtime_test_backend.py"
    source = backend.read_text()
    start = source.index('        manager = self.vagent.stage_manager')
    end = source.index('    def do_work_stream', start)
    source = source[:start] + '''        counter = Path(self.vagent.workspace, "round-count")
        count = int(counter.read_text()) if counter.exists() else 0
        counter.write_text(str(count + 1))
        return "round returned"
''' + source[end:]
    backend.write_text(source)
    result = run_cli(command + ["--icmd", "nr"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "round-count").read_text() == "1"


def test_real_cli_tui_streaming_loop_starts_with_output_capture(tmp_path):
    """Use make test_Adder's streaming/human/TUI/loop combination with a local backend."""
    import pty
    import select

    command = cli_command(tmp_path, human=True)
    backend = tmp_path / "runtime_test_backend.py"
    backend.write_text(BACKEND.replace(
        "        manager = self.vagent.stage_manager",
        '        sink = self.vagent.message_echo_handler\n'
        '        assert sink is not None and sink.__self__.message_view_attached, "TUI not attached"\n'
        '        print("FIRST_TUI_OUTPUT", flush=True)\n'
        '        self.vagent.message_echo("FIRST_TUI_MESSAGE")\n'
        '        Path(self.vagent.workspace, "tui-model-started").write_text("ready")\n'
        '        manager = self.vagent.stage_manager'))
    master, slave = pty.openpty()
    process = subprocess.Popen(command + ["-s", "-hm", "--tui", "-l"], cwd=ROOT,
                               stdin=slave, stdout=slave, stderr=slave,
                               env={**os.environ, "TERM": "xterm-256color"})
    os.close(slave)
    received = bytearray()

    def read_until(marker):
        """Drain the real terminal to a bounded visible milestone."""
        deadline = time.monotonic() + 20
        while marker not in received:
            assert process.poll() is None and time.monotonic() < deadline, received.decode(errors="replace")[-6000:]
            if select.select([master], [], [], 0.1)[0]:
                received.extend(os.read(master, 65536))

    try:
        read_until(b"tok/s")
        deadline = time.monotonic() + 10
        while not (tmp_path / "tui-model-started").exists():
            assert process.poll() is None and time.monotonic() < deadline, received.decode(errors="replace")[-6000:]
            if select.select([master], [], [], 0.1)[0]:
                received.extend(os.read(master, 65536))
        assert b"\x1b[?1049h" in received
        os.write(master, b"\x11")
        read_until(b"\x1b[?1049l")
        read_until(b"FIRST_TUI_OUTPUT")
        os.write(master, b"quit\n")
        process.wait(timeout=10)
        assert process.returncode == 0, received.decode(errors="replace")[-6000:]
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        os.close(master)


def test_real_cli_service_queries_do_not_probe_main_model(tmp_path):
    """A real MCP/HTTP process stays usable with an intentionally invalid main-model protocol."""
    import socket
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    command = cli_command(tmp_path, backend="langchain")
    path = tmp_path / "runtime.yaml"
    config = yaml.safe_load(path.read_text())
    config["openai"] = {"api_mode": "invalid-test-protocol"}
    path.write_text(yaml.safe_dump(config))
    logfile = tmp_path / "service.log"
    command += ["--mcp-server", "--mcp-server-port", "0", "--export-cmd-api", f"127.0.0.1:{port}"]
    with logfile.open("w") as output:
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=output)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=1) as client:
                deadline = time.monotonic() + 12
                while True:
                    assert process.poll() is None and time.monotonic() < deadline, logfile.read_text()
                    try:
                        response = client.get("/api/runtime/status")
                        if response.status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    time.sleep(0.05)
                state = response.json()["data"]
                assert state["execution"] == "idle"
                response = client.post("/api/cmd", json={"cmd": "status", "session_id": "operator"})
                assert response.status_code == 200, response.text
                response = client.post("/api/cmd", json={"cmd": "shutdown", "session_id": "operator"})
                assert response.status_code == 200, response.text
            process.wait(timeout=10)
            assert process.returncode == 0, logfile.read_text()
            assert "invalid-test-protocol" not in logfile.read_text()
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
