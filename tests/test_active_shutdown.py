"""Real network cancellation, one shutdown deadline and a usable terminal during drain."""

from concurrent.futures import ThreadPoolExecutor
import io
import json
import socket
import socketserver
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI

from test_multi_agent import make_agent
from test_runtime_host import make_host
from ucagent.core.backends.langchain.cancellation import ModelRequests, ModelRequestCancelled
from ucagent.runtime.host import RuntimeHost
from ucagent.interfaces.terminal.console import Console


@pytest.fixture
def stalled_http():
    """Accept a real provider request and observe whether cancellation closes its socket."""
    entered, disconnected, release = threading.Event(), threading.Event(), threading.Event()
    state = SimpleNamespace(entered=entered, disconnected=disconnected, connections=0,
                            disconnections=0, lock=threading.Lock(), send_prefix=False)

    class Handler(socketserver.BaseRequestHandler):
        """Consume a small request, then leave the client awaiting HTTP response headers."""

        def handle(self):
            """Observe EOF rather than simulating cancellation with a test-only model flag."""
            self.request.settimeout(0.05)
            data = b""
            while b"\r\n\r\n" not in data:
                data += self.request.recv(65536)
            head, body = data.split(b"\r\n\r\n", 1)
            size = next(int(line.split(b":", 1)[1]) for line in head.split(b"\r\n")
                        if line.lower().startswith(b"content-length:"))
            while len(body) < size:
                body += self.request.recv(65536)
            with state.lock:
                state.connections += 1
            entered.set()
            if state.send_prefix:
                payload = json.dumps({"id": "chatcmpl-local", "object": "chat.completion.chunk",
                    "created": 0, "model": "test-model", "choices": [
                        {"index": 0, "delta": {"role": "assistant", "content": "partial"}, "finish_reason": None}]})
                self.request.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n"
                                     + ("data: " + payload + "\n\n").encode())
            while not release.is_set():
                try:
                    if not self.request.recv(1024):
                        with state.lock:
                            state.disconnections += 1
                        disconnected.set()
                        return
                except socket.timeout:
                    continue
                except ConnectionResetError:
                    with state.lock:
                        state.disconnections += 1
                    disconnected.set()
                    return

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        state.url = f"http://127.0.0.1:{server.server_address[1]}/v1"
        yield state
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(1)


@pytest.mark.parametrize("responses", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
def test_cancellation_closes_real_provider_connection(stalled_http, responses, streaming):
    """Both protocols stop stalled streaming/nonstreaming requests without waiting for timeout."""
    stopped = threading.Event()
    owner = SimpleNamespace(is_break=stopped.is_set)
    requests = ModelRequests(owner)
    model = ChatOpenAI(model="test-model", api_key="test-only", base_url=stalled_http.url,
                       use_responses_api=responses, streaming=streaming, max_retries=0, timeout=30)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(requests.invoke, model, "work")
            assert stalled_http.entered.wait(3)
            assert requests.status()["cancellable"]
            start = time.monotonic()
            stopped.set()
            requests.cancel()
            requests.cancel()
            with pytest.raises(ModelRequestCancelled):
                result.result(timeout=3)
            assert time.monotonic() - start < 2
            assert stalled_http.disconnected.wait(2), "Provider socket stayed open after cancellation"
        assert requests.status() is None
    finally:
        requests.close()
    assert not requests._thread.is_alive()


def test_quit_cancels_actual_worker_graph_and_deduplicates_requests(tmp_path, stalled_http):
    """Runtime shutdown reaches the worker HTTP request and preserves uncompleted stage state."""
    agent = make_agent(tmp_path, config_overrides={
        "openai.api_mode": "chat_completions", "openai.model_name": "test-model",
        "openai.openai_api_key": "test-only", "openai.openai_api_base": stalled_http.url,
        "openai.max_retries": 0})
    host = RuntimeHost(agent, shutdown_timeout=1)
    host.start()
    agent.multi_agent.submit({"plan_id": "waiting", "tasks": [{"id": "read", "instruction": "Wait for model"}]})
    try:
        assert stalled_http.entered.wait(5)
        first_index = agent.stage_manager.stage_index
        start = time.monotonic()
        host.request_shutdown()
        host.request_shutdown()
        state = host.wait(3)
        assert state["instance"] == "closed", host.shutdown_status()
        assert time.monotonic() - start < 2
        assert stalled_http.disconnected.wait(1)
        assert agent.stage_manager.stage_index == first_index
        events = agent.multi_agent._events
        assert sum(e["event"] == "plan_cancel_requested" for e in events) == 1
        assert agent.multi_agent.records["waiting/read"].state == "cancelled"
    finally:
        host.request_shutdown()
        host.wait(3)


@pytest.mark.parametrize("mode", ["auto", "chat_completions"])
def test_super_or_startup_probe_is_cancellable(tmp_path, stalled_http, mode):
    """Quit also interrupts the first protocol probe or a managed Super request."""
    agent = make_agent(tmp_path, config_overrides={
        "backend.key_name": "langchain", "openai.api_mode": mode,
        "openai.model_name": "test-model", "openai.openai_api_key": "test-only",
        "openai.openai_api_base": stalled_http.url, "openai.max_retries": 0})
    host = RuntimeHost(agent, shutdown_timeout=1)
    host.start()
    operation = host.operations.submit("super", lambda ctx: agent.one_loop(), model=True)
    try:
        assert stalled_http.entered.wait(5)
        host.request_shutdown()
        assert host.wait(3)["instance"] == "closed", host.shutdown_status()
        assert stalled_http.disconnected.wait(1)
        assert host.operations.get(operation["id"])["state"] == "cancelled"
        assert agent.multi_agent.records == {}
    finally:
        host.request_shutdown()
        host.wait(3)


def test_sync_fallback_keeps_ownership_until_actual_return():
    """Async adapters around legacy sync code must not claim a thread has stopped early."""
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()

    class SyncModel(BaseChatModel):
        """Model with only the synchronous provider extension point."""

        @property
        def _llm_type(self):
            """Identify a deliberately non-cancellable test provider."""
            return "sync-test"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            """Hold its actual executor thread until released."""
            entered.set()
            assert release.wait(3)
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="late response"))])

    requests = ModelRequests(SimpleNamespace(is_break=stopped.is_set))
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(requests.invoke, SyncModel(), "work")
            assert entered.wait(2)
            stopped.set()
            requests.cancel()
            assert requests.status()["cancellable"] is False
            assert not result.done()
            release.set()
            with pytest.raises(ModelRequestCancelled):
                result.result(timeout=2)
    finally:
        release.set()
        requests.close()


def test_total_grace_deadline_does_not_reset_and_pending_work_is_visible(tmp_path):
    """Repeated q cannot grant more grace or prematurely save while a tool is still writing."""
    host, runtime = make_host(tmp_path, shutdown_timeout=0.04)
    entered, release = threading.Event(), threading.Event()
    runtime.manager.save_stage_info = Mock()

    def write(ctx):
        """Represent a synchronous tool that owns writable state until a safe return."""
        entered.set()
        assert release.wait(3)

    host.start()
    op = host.operations.submit("writing-artifact", write, model=True)
    assert entered.wait(1)
    try:
        host.request_shutdown()
        deadline = host._shutdown_deadline
        assert host.wait(0.1)["instance"] == "closing"
        host.request_shutdown()
        assert host._shutdown_deadline == deadline
        state = host.shutdown_status()
        assert state["grace_expired"] and "writing-artifact" in str(state["pending"])
        runtime.manager.save_stage_info.assert_not_called()
        assert host.operations.get(op["id"])["state"] == "cancelling"
        assert "grace period expired" in "\n".join(host.output.get_lines())
    finally:
        release.set()
    assert host.wait(3)["instance"] == "closed"
    runtime.manager.save_stage_info.assert_called_once()


def test_blocking_cleanup_does_not_hide_grace_expiry_or_disable_force(tmp_path):
    """A slow exporter/cleanup reports its owner and leaves the force action available."""
    forced = Mock()
    host, runtime = make_host(tmp_path, shutdown_timeout=0.04, force_exit=forced)
    entered, release = threading.Event(), threading.Event()

    def slow_exporter():
        """Hold a cleanup callback after all task execution has drained."""
        runtime.agent._cleanup_activity = "Langfuse shutdown"
        entered.set()
        assert release.wait(3)
        runtime.agent._cleanup_activity = None

    host.add_cleanup(slow_exporter)
    host.start()
    try:
        host.request_shutdown()
        assert entered.wait(1)
        assert host.wait(0.1)["instance"] == "closing"
        assert host.shutdown_status()["pending"] == ["Langfuse shutdown"]
        assert "Langfuse shutdown" in "\n".join(host.output.get_lines())
        host.registry.execute("q force", runtime.session)
        forced.assert_called_once_with(130)
    finally:
        release.set()
    assert host.wait(3)["instance"] == "closed"


def test_console_accepts_second_quit_and_force_during_pending_shutdown(tmp_path):
    """The normal terminal loop remains active after q instead of falling into host.wait()."""
    release, entered = threading.Event(), threading.Event()
    forced = Mock(side_effect=lambda code: release.set())
    host, runtime = make_host(tmp_path, shutdown_timeout=0.02, force_exit=forced)
    output = io.StringIO()
    console = Console(host, input_stream=io.StringIO("q\nq\nq force\n"), output_stream=output)

    def pending(ctx):
        """Keep graceful shutdown pending while the console reads force-exit input."""
        entered.set()
        assert release.wait(3)

    host.start()
    host.operations.submit("pending-network", pending, model=True)
    assert entered.wait(1)
    try:
        console.run()
        forced.assert_called_once_with(130)
        assert "closing: q=status" in output.getvalue()
        assert "pending-network" in output.getvalue()
    finally:
        release.set()
        host.request_shutdown()
    assert host.wait(3)["instance"] == "closed"


def test_real_console_keeps_force_exit_available_after_grace(tmp_path):
    """An actual PTY accepts q force after the deadline while an uninterruptible task runs."""
    import os
    from pathlib import Path
    import pty
    import select
    import subprocess
    import sys

    source = '''
import os, sys, threading
from pathlib import Path
sys.path.insert(0, "tests")
from test_runtime_host import make_host
from ucagent.interfaces.terminal.console import Console
root = Path(sys.argv[1])
host, runtime = make_host(root, shutdown_timeout=0.1, force_exit=os._exit)
runtime.manager.save_stage_info = lambda: (root / "saved").write_text("saved")
entered = threading.Event()
def blocked(ctx):
    entered.set()
    threading.Event().wait(30)
host.start()
host.operations.submit("uninterruptible-tool", blocked, model=True)
assert entered.wait(2)
Console(host).run()
host.wait()
'''
    master, slave = pty.openpty()
    process = subprocess.Popen([sys.executable, "-c", source, str(tmp_path)],
                               cwd=Path(__file__).resolve().parents[1], stdin=slave, stdout=slave, stderr=slave)
    os.close(slave)
    transcript = bytearray()

    def read_until(marker):
        """Wait only for observable terminal output and fail with a bounded transcript."""
        deadline = time.monotonic() + 5
        while marker not in transcript:
            assert process.poll() is None, transcript.decode(errors="replace")
            assert time.monotonic() < deadline, transcript.decode(errors="replace")
            if select.select([master], [], [], 0.05)[0]:
                transcript.extend(os.read(master, 65536))

    try:
        read_until(b"(UnityChip)")
        os.write(master, b"q\n")
        read_until(b"grace period expired")
        read_until(b"uninterruptible-tool")
        assert process.poll() is None
        os.write(master, b"q force\n")
        assert process.wait(timeout=3) == 130
        assert not (tmp_path / "saved").exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        os.close(master)


def test_stream_cancellation_closes_connection_after_first_token(stalled_http):
    """Cancel a live SSE body after visible output, not just a request awaiting headers."""
    from langchain_core.callbacks import BaseCallbackHandler
    first_token, stopped = threading.Event(), threading.Event()

    class TokenObserver(BaseCallbackHandler):
        """Observe the actual provider parser delivering the first SSE text token."""

        def on_llm_new_token(self, token, **kwargs):
            """Signal parsed model output without retaining request content."""
            if token:
                first_token.set()

    stalled_http.send_prefix = True
    requests = ModelRequests(SimpleNamespace(is_break=stopped.is_set))
    model = ChatOpenAI(model="test-model", api_key="test-only", base_url=stalled_http.url,
                       use_responses_api=False, streaming=True, max_retries=0, callbacks=[TokenObserver()])
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(requests.invoke, model, "work")
            assert first_token.wait(3)
            stopped.set()
            requests.cancel()
            with pytest.raises(ModelRequestCancelled):
                result.result(timeout=2)
            assert stalled_http.disconnected.wait(1)
    finally:
        requests.close()


def test_quit_cancels_all_parallel_model_connections(tmp_path, stalled_http):
    """All parallel worker requests stop, rather than only the latest model session."""
    agent = make_agent(tmp_path, max_workers=2, config_overrides={
        "openai.api_mode": "chat_completions", "openai.model_name": "test-model",
        "openai.openai_api_key": "test-only", "openai.openai_api_base": stalled_http.url,
        "openai.max_retries": 0})
    host = RuntimeHost(agent, shutdown_timeout=1)
    host.start()
    agent.multi_agent.submit({"plan_id": "parallel", "scope": "task", "tasks": [
        {"id": str(i), "instruction": "Write own result", "outputs": [f"out/{i}.md"]} for i in range(2)]})
    try:
        deadline = time.monotonic() + 5
        while stalled_http.connections < 2:
            assert time.monotonic() < deadline
            threading.Event().wait(0.01)
        host.request_shutdown()
        assert host.wait(3)["instance"] == "closed", host.shutdown_status()
        assert stalled_http.disconnections == 2
        assert all(row.state == "cancelled" for row in agent.multi_agent.records.values())
        assert sum(e["event"] == "plan_cancel_requested" for e in agent.multi_agent._events) == 1
    finally:
        host.request_shutdown()
        host.wait(3)
