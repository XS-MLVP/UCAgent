"""Managed CLI adapter tests with real subprocesses and authenticated MCP transport."""

import json
from pathlib import Path
import sys

import pytest

from test_multi_agent import make_agent, stage
from ucagent.interfaces.server.worker_mcp import worker_endpoint


@pytest.mark.parametrize("backend_name", ["codex", "opencode", "client_a"])
def test_managed_cli_super_and_subtree_resume_without_langchain(tmp_path, monkeypatch, backend_name):
    """One factory controls Super/Sub; ordinary child replies preserve the worker session."""
    import ucagent.core.backends.langchain.agent as langchain

    def forbidden(*args, **kwargs):
        """Fail if CLI execution tries to construct a LangChain model."""
        pytest.fail("CLI mode tried to construct a LangChain model")

    monkeypatch.setattr(langchain, "get_chat_model", forbidden)
    import ucagent.core.agent.session as sessions
    factory = sessions.get_backend
    created = []

    def record_backend(owner, cfg):
        """Record actual factory-created instances without replacing their execution."""
        backend = factory(owner, cfg)
        created.append(backend)
        return backend

    monkeypatch.setattr(sessions, "get_backend", record_backend)
    helper = Path(__file__).parent / "helpers" / "session_cli.py"
    launcher = tmp_path / "fixture-cli"
    launcher.write_text(f"#!{sys.executable}\nimport runpy\nrunpy.run_path({str(helper)!r}, run_name='__main__')\n")
    launcher.chmod(0o700)
    overrides = {"backend.key_name": backend_name, f"backend.{backend_name}.args.executable": str(launcher)}
    if backend_name == "client_a":
        overrides.pop("backend.client_a.args.executable")
        overrides["backend.client_a"] = {
            "clss": "ucagent.core.backends.cmdline.SessionCommandBackend",
            "args": {"argv": [str(launcher), "--dialect-simple"],
                     "resume_args": ["--resume-id", "{{ session_id }}"],
                     "output": {"format": "jsonl", "events": [
                         {"match": {"event": "start"}, "session": "conversation"},
                         {"match": {"event": "message"}, "text": "body.text"},
                         {"match": {"event": "done"}, "done": True}]}}}
    agent = make_agent(tmp_path, stages=[stage("root", stage=[
        stage("first", output_files=["out/first.txt"]), stage("second", output_files=["out/second.txt"])]),
        stage("next", output_files=["out/next.txt"])], config_overrides=overrides)
    agent.multi_agent.endpoint_factory = worker_endpoint
    try:
        agent.multi_agent.start_workflow()
        agent.multi_agent.workflow_thread.join(20)
        assert agent.multi_agent.workflow_state == "completed", agent.multi_agent.status()
        records = list(agent.multi_agent.records.values())
        assert len(records) == 2 and all(r.attempt == 1 for r in records)
        calls = [json.loads(line) for line in (created[0].vagent.session_dir / "invocations.jsonl").read_text().splitlines()]
        assert len(calls) == 2 and [call["resumed"] for call in calls] == [False, True]
        assert calls[0]["session_id"] == calls[1]["session_id"]
        assert calls[0]["pid"] != calls[1]["pid"]
        assert len({agent.backend.cli_session_id, *(backend.cli_session_id for backend in created)}) == 3
        assert all(backend.vagent.closed for backend in created)
        assert agent.get_tool_by_name("SubAgentTool").call_count == 2
        assert agent.backend._call_count == 3
        assert agent.backend.get_statistics()["model_rounds"] is None
        assert all((tmp_path / f"out/{name}.txt").exists() for name in ("first", "second", "next"))
    finally:
        agent.set_break(True)
        agent._startup_cleanup.close()


def test_cli_events_do_not_leak_raw_structures_or_switch_identity(tmp_path):
    """Render only message text and reject an unexpected session after resume."""
    from types import SimpleNamespace
    from uuid import uuid4
    from ucagent.core.backends import get_backend
    from ucagent.util.config import Config, load_yaml_with_env_vars
    messages = []
    owner = SimpleNamespace(workspace=str(tmp_path), message_echo=messages.append)
    cfg = Config(load_yaml_with_env_vars(Path(__file__).parents[1] / "ucagent/setting.yaml"))
    cfg.set_value("backend.key_name", "codex")
    backend = get_backend(owner, cfg)
    backend.init()
    try:
        backend.process_output(json.dumps({"type": "item.completed", "item": {
            "type": "agent_message", "text": "answer", "metadata": {"private": "omit"}}}))
        backend.process_output('{"type":"unknown","secret":"omit"}')
        assert messages == ["answer"]
        backend.process_output(json.dumps({"type": "thread.started", "thread_id": str(uuid4())}))
        with pytest.raises(RuntimeError, match="different session"):
            backend.process_output(json.dumps({"type": "thread.started", "thread_id": str(uuid4())}))
    finally:
        backend.exit()


@pytest.mark.parametrize("backend", ["langchain", "opencode"])
def test_backends_share_dependency_validation_and_capacity(tmp_path, monkeypatch, backend):
    """Actual backend instances execute A/B then C through the same bounded scheduler."""
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    import re
    import ucagent.core.backends.langchain.agent as langchain
    from test_multi_agent import finish

    class FileModel(BaseChatModel):
        """Represent file production through real model and managed tool boundaries."""

        @property
        def _llm_type(self):
            """Identify the offline model without network configuration."""
            return "offline-file-worker"

        def bind_tools(self, tools, **kwargs):
            """Retain task boundaries supplied by the production backend."""
            assert not {"Complete", "Check", "SubAgentTool"} & {tool.name for tool in tools}
            return self

        def get_num_tokens_from_messages(self, messages, tools=None):
            """Avoid optional tokenizer downloads in this scheduling test."""
            return 20

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            """Write the requested file, then submit after its real tool response."""
            written = any(isinstance(msg, ToolMessage) and msg.name == "EditTextFile" for msg in messages)
            text = next(msg.content for msg in messages if isinstance(msg, HumanMessage))
            path = re.search(r"out/[abc]\.txt", text).group()
            message = AIMessage(content="", tool_calls=[{
                "name": "SubmitTaskResult" if written else "EditTextFile", "id": "submit" if written else "write",
                "args": {"summary": "Produced evidence"} if written else {"path": path, "content": "evidence"}}])
            return ChatResult(generations=[ChatGeneration(message=message)])

    def model_factory(*args, **kwargs):
        """Fail a CLI fallback; allocate a fresh scripted model for LangChain sessions."""
        assert backend == "langchain"
        return FileModel()

    monkeypatch.setattr(langchain, "get_chat_model", model_factory)
    monkeypatch.setattr(langchain, "negotiate_openai_api_mode", lambda *a, **kw: None)
    helper = Path(__file__).parent / "helpers" / "session_cli.py"
    executable = tmp_path / "fixture-cli"
    executable.write_text(f"#!{sys.executable}\nimport runpy\nrunpy.run_path({str(helper)!r}, run_name='__main__')\n")
    executable.chmod(0o700)
    agent = make_agent(tmp_path, max_workers=2, stages=[stage("files", output_files=[f"out/{n}.txt" for n in "abc"])],
                       config_overrides={"backend.key_name": backend, "backend.opencode.args.executable": str(executable)})
    agent.multi_agent.endpoint_factory = worker_endpoint
    try:
        agent.multi_agent.submit({"plan_id": "dag", "scope": "task", "tasks": [
            {"id": name, "instruction": f"Write out/{name}.txt", "outputs": [f"out/{name}.txt"],
             "depends_on": ["a", "b"] if name == "c" else [],
             "inputs": ["out/a.txt", "out/b.txt"] if name == "c" else []} for name in "abc"]})
        result = finish(agent.multi_agent, "dag", 20)
        assert result["plans"]["dag"]["state"] == "completed", result
        active, peak, verified = 0, 0, set()
        for event in result["events"]:
            if event["event"] == "task_started":
                if event["task_id"] == "dag/c":
                    assert verified == {"dag/a", "dag/b"}
                active += 1
                peak = max(peak, active)
            elif event["event"] == "task_finished":
                assert event["state"] == "verified"
                verified.add(event["task_id"])
                active -= 1
        assert peak == 2 and active == 0
        assert all((task["budget"]["model_rounds_used"] is None) == (backend != "langchain") for task in result["tasks"])
    finally:
        agent._startup_cleanup.close()


@pytest.mark.parametrize("mode", ["cancel", "invalid_config"])
def test_cli_configuration_failure_never_starts_model(tmp_path, mode):
    """Cancellation during probing and rejected MCP configuration both prevent model launch."""
    import threading
    import time
    from types import SimpleNamespace
    from ucagent.core.backends.cmdline import SessionCommandBackend
    from ucagent.util.config import Config

    started, model = tmp_path / "probe-started", tmp_path / "model-started"
    messages = []
    owner = SimpleNamespace(workspace=str(tmp_path), is_break=lambda: False, message_echo=messages.append)
    probe = [sys.executable, "-c", "import json; print(json.dumps({'ok': False}))"]
    options = {"validate": {"argv": probe, "expect": "result.ok"}}
    if mode == "cancel":
        options = {"inspect": [sys.executable, "-c",
                   f"from pathlib import Path; import time; Path({str(started)!r}).touch(); time.sleep(30)"]}
    backend = SessionCommandBackend(owner, Config({}), argv=[sys.executable, "-c",
                                    f"from pathlib import Path; Path({str(model)!r}).touch()"], **options)
    backend.init()
    backend.endpoint = {"url": "http://127.0.0.1:12345/mcp", "token": "test-only"}
    thread = None
    try:
        if mode == "cancel":
            thread = threading.Thread(target=backend.run_turn, args=({"messages": ["test"]},))
            thread.start()
            deadline = time.monotonic() + 3
            while not started.exists():
                assert time.monotonic() < deadline
                threading.Event().wait(0.01)
            backend.cancel()
            thread.join(3)
            assert not thread.is_alive() and backend.wait_idle(0)
        else:
            with pytest.raises(RuntimeError, match="validation failed"):
                backend.run_turn({"messages": ["test"]})
        assert not model.exists() and messages == []
    finally:
        backend.cancel()
        if thread is not None:
            thread.join(3)
        backend.close()


@pytest.mark.parametrize("busy_seconds", [0, 0.3])
def test_generic_cli_keeps_idle_timeout_and_tool_activity(tmp_path, busy_seconds):
    """Single and multi CLI execution share silence timeout while honoring in-flight tools."""
    import time
    from types import SimpleNamespace
    from ucagent.core.backends.cmdline import SessionCommandBackend
    from ucagent.util.config import Config

    started = time.monotonic()
    owner = SimpleNamespace(workspace=str(tmp_path), is_break=lambda: False,
                            message_echo=lambda text: None,
                            test_tools=[SimpleNamespace(name="Check", is_busy=lambda: time.monotonic() < started + busy_seconds)])
    backend = SessionCommandBackend(owner, Config({"cmd_timeout": 0.15}),
                                    argv=[sys.executable, "-c", "import time; time.sleep(30)"])
    backend.init()
    backend.endpoint = {"url": "http://127.0.0.1:12345/mcp", "token": "test-only"}
    try:
        with pytest.raises(RuntimeError, match="idle timeout"):
            backend.run_turn({"messages": ["test"]})
        elapsed = time.monotonic() - started
        assert busy_seconds + 0.1 <= elapsed < 3
        assert backend.process.poll() is not None and backend.wait_idle(0)
    finally:
        backend.close()
