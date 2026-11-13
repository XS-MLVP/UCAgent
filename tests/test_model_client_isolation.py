"""Keep-alive reuse across Super, worker cleanup and worker retry on one provider."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from types import SimpleNamespace

import pytest
from openai import InternalServerError

from ucagent.core.backends.langchain.agent import UCAgentLangChainBackend
from ucagent.util.config import Config


@pytest.mark.parametrize("mode", ["auto", "chat_completions"])
def test_super_worker_retry_own_independent_http_clients(mode):
    """Real factory/probes and pooled HTTP requests survive another backend's failure/close."""
    class Handler(BaseHTTPRequestHandler):
        """Serve both protocols over persistent local connections without an online model."""

        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            """Keep expected HTTP failures out of the test's console output."""

        def do_POST(self):
            """Return a valid model response or an intentional worker request failure."""
            body = self.rfile.read(int(self.headers["Content-Length"]))
            failing = b"fail-worker" in body
            if failing:
                payload = {"error": {"message": "worker request failed", "type": "server_error", "code": None}}
            elif self.path.endswith("/responses"):
                payload = {"id": "resp-local", "object": "response", "created_at": 0,
                           "status": "completed", "model": "test-model", "error": None,
                           "output": [{"type": "message", "id": "msg-local", "role": "assistant",
                                       "status": "completed", "content": [
                                           {"type": "output_text", "text": "OK", "annotations": []}]}]}
            else:
                payload = {"id": "chatcmpl-local", "object": "chat.completion", "created": 0,
                           "model": "test-model", "choices": [{"index": 0, "finish_reason": "stop",
                           "message": {"role": "assistant", "content": "OK"}}]}
            data = json.dumps(payload).encode()
            self.send_response(500 if failing else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    cfg = Config({"seed": 0, "model_type": "openai", "rate_limiter": {"enabled": False},
                  "openai": {"model_name": "test-model", "api_key": "local-test-only",
                             "base_url": f"http://127.0.0.1:{server.server_port}/v1", "api_mode": mode,
                             "timeout": 3, "responses_probe_timeout": 2, "max_retries": 0}})
    backends = []

    def backend():
        """Build the production backend with the same settings and its own request loop."""
        owner = SimpleNamespace(is_break=lambda: False, test_tools=[], stream_output=False,
                                context_management_strategy="TrimAndSummaryMiddleware",
                                max_summary_tokens=32, max_keep_msgs=10, max_token=1000, tail_keep_msgs=2)
        value = UCAgentLangChainBackend(owner, cfg)
        backends.append(value)
        value.init()
        value.prepare()
        return value

    try:
        supervisor = backend()
        assert supervisor.requests.invoke(supervisor.model, "super").text == "OK"
        worker = backend()
        assert worker.requests.invoke(worker.model, "worker").text == "OK"
        assert supervisor.model.root_async_client._client is not worker.model.root_async_client._client
        with pytest.raises(InternalServerError, match="worker request failed"):
            worker.requests.invoke(worker.model, "fail-worker")
        worker.exit()
        assert worker.model.root_async_client.is_closed()
        assert not supervisor.model.root_async_client.is_closed()
        assert supervisor.requests.invoke(supervisor.model, "super after worker").text == "OK"
        assert supervisor.requests.invoke(supervisor.sumary_model, "summary", phase="summary").text == "OK"
        retry = backend()
        assert retry.requests.invoke(retry.model, "retry").text == "OK"
        retry.exit()
        assert supervisor.requests.invoke(supervisor.model, "super after retry").text == "OK"
        clients = [model.root_async_client for value in backends for model in value.requests._models]
    finally:
        for value in reversed(backends):
            value.exit()
        server.shutdown()
        server.server_close()
        thread.join(1)
    assert all(client.is_closed() for client in clients)
    assert all(not value.requests._thread.is_alive() for value in backends)
