"""Opt-in real OpenCode sessions with deterministic, local model responses."""

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from jinja2 import Template
import pytest
import ucagent


@pytest.mark.skipif(
    os.environ.get("RTL2SPEC_TEST_OPENCODE") != "1",
    reason="Set RTL2SPEC_TEST_OPENCODE=1 to exercise an installed OpenCode CLI",
)
def test_opencode_denies_shell_and_external_paths(tmp_path):
    """Real native tools reject forbidden calls while workspace file access succeeds."""
    executable = shutil.which("opencode")
    assert executable, "Install OpenCode and add it to PATH before enabling this test"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("PRIVATE_OUTSIDE_FIXTURE")
    inside = workspace / "inside.txt"
    inside.write_text("PUBLIC_INSIDE_FIXTURE")
    marker = workspace / "shell-executed"
    outside_write = tmp_path / "outside-write.txt"
    inside_write = workspace / "inside-write.txt"
    calls = [
        ("bash", {"command": f"touch '{marker}'", "description": "Permission probe"}),
        ("read", {"filePath": str(outside)}),
        ("write", {"filePath": str(outside_write), "content": "forbidden"}),
        ("read", {"filePath": str(inside)}),
        ("write", {"filePath": str(inside_write), "content": "allowed"}),
    ]
    requests = []

    class Provider(BaseHTTPRequestHandler):
        """Serve only fixture tool calls, leaving permission enforcement to OpenCode."""

        def log_message(self, *args):
            """Keep routine HTTP traffic out of pytest output."""

        def do_POST(self):
            """Stream the next tool call, or finish title and completed task requests."""
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            completed = [item for item in body.get("messages", []) if item.get("role") == "tool"]
            step = len(completed)
            if body.get("tools") and step < len(calls):
                name, arguments = calls[step]
                delta = {
                    "role": "assistant",
                    "tool_calls": [{
                        "index": 0, "id": f"probe_{step}", "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }],
                }
                reason = "tool_calls"
            else:
                delta = {"role": "assistant", "content": "Permission probe complete."}
                reason = "stop"
            chunk = {
                "id": "local-probe", "object": "chat.completion.chunk",
                "created": 1, "model": "probe",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            }
            ending = {**chunk, "choices": [{"index": 0, "delta": {}, "finish_reason": reason}]}
            payload = (
                f"data: {json.dumps(chunk)}\n\ndata: {json.dumps(ending)}\n\ndata: [DONE]\n\n"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Reuse the installed UCAgent backend asset; never duplicate its permissions here.
        asset = Path(ucagent.__file__).parent / "assets/mcp_opencode.json"
        config = json.loads(Template(asset.read_text()).render(
            PORT=1, OPENAI_API_BASE=f"http://127.0.0.1:{server.server_port}/v1",
            OPENAI_MODEL="probe",
        ))
        config["mcp"] = {}  # This test exercises native tools, without an MCP server.
        config["provider"]["ucagent"]["options"]["apiKey"] = "local-fixture"
        config.update({
            "model": "ucagent/probe", "small_model": "ucagent/probe",
            "enabled_providers": ["ucagent"], "autoupdate": False, "share": "disabled",
        })
        config_path = workspace / "opencode.json"
        config_path.write_text(json.dumps(config))
        env = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("OPENCODE_", "OPENAI_", "ANTHROPIC_", "UC_ENV_", "XDG_"))
        }
        for name in ("CONFIG", "CACHE", "DATA", "STATE"):
            env[f"XDG_{name}_HOME"] = str(tmp_path / name.lower())
        env.update({
            "OPENCODE_CONFIG": str(config_path), "PWD": str(workspace),
            "OPENCODE_DISABLE_MODELS_FETCH": "true",
            "OPENCODE_DISABLE_AUTOUPDATE": "true",
            "OPENCODE_DISABLE_DEFAULT_PLUGINS": "true",
        })
        result = subprocess.run(
            [executable, "run", "--pure", "--dir", str(workspace), "--model",
             "ucagent/probe", "--format", "json", "Exercise permission probes"],
            cwd=workspace, env=env, text=True, capture_output=True, timeout=60,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.returncode == 0, result.stdout + result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    results = {
        event["part"]["callID"]: event["part"]
        for event in events if event.get("type") == "tool_use"
    }
    assert set(results) == {f"probe_{index}" for index in range(len(calls))}, result.stdout
    shell = results["probe_0"]
    assert shell["state"]["status"] == "error" or shell["tool"] == "invalid"
    assert not marker.exists()
    for index in (1, 2):
        state = results[f"probe_{index}"]["state"]
        assert state["status"] == "error", state
        assert "external_directory" in state["error"], state
    assert not outside_write.exists()
    assert "PRIVATE_OUTSIDE_FIXTURE" not in json.dumps(requests) + result.stdout
    assert "PUBLIC_INSIDE_FIXTURE" in results["probe_3"]["state"]["output"]
    assert results["probe_4"]["state"]["status"] == "completed"
    assert inside_write.read_text() == "allowed"
