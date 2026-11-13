"""H5 end-to-end plugin loading, real Agent construction, tools, Checkers and peer handoff."""

import hashlib
import json
import os
from pathlib import Path
import sys
import threading

import pytest

from ucagent.application.launch import run_application
from ucagent.application.plan import LaunchRequest
from relay_fakes import RelayModel


PLUGINS = Path(__file__).parent / "fixtures/workflow_relay/plugins"


def relay_request(tmp_path, *, backend="langchain", goal="increment the supplied value"):
    """Select only source as active; sink is an explicitly trusted catalog candidate."""
    workspace = tmp_path / "source"
    (workspace / "inputs").mkdir(parents=True)
    (workspace / "inputs/request.json").write_text('{"value": 7, "operation": "increment"}')
    config = tmp_path / "launch.yaml"
    config.write_text("{}\n")
    overrides = {"backend.key_name": backend, "runtime_options.workflow_handoff_enabled": True,
        "langfuse.enable": False, "workflow_handoff": {
            "goal": goal, "chain_root": str(tmp_path / "chain"),
            "plugin_selectors": [str(PLUGINS / "relay_sink")],
            "allowed_workflows": ["relay-source:produce", "relay-sink:consume"],
            "allowed_next": {"relay-source:produce": ["relay-sink:consume"], "relay-sink:consume": []}}}
    if backend == "client_relay":
        helper = Path(__file__).parent / "helpers/session_cli.py"
        executable = tmp_path / "fixture-cli"
        executable.write_text(f"#!{sys.executable}\nimport runpy\nrunpy.run_path({str(helper)!r}, run_name='__main__')\n")
        executable.chmod(0o700)
        overrides["backend.client_relay"] = {"clss": "ucagent.core.backends.cmdline.SessionCommandBackend", "args": {
            "argv": [str(executable), "--dialect-simple", "--relay-fixture"],
            "resume_args": ["--resume-id", "{{ session_id }}"],
            "output": {"format": "jsonl", "events": [
                {"match": {"event": "start"}, "session": "conversation"},
                {"match": {"event": "message"}, "text": "body.text"},
                {"match": {"event": "done"}, "done": True}]}}}
    return LaunchRequest(task_options={"workspace": str(workspace), "dut_name": "Relay", "output": None,
        "config_file": str(config), "cfg_override": overrides, "plugin_workflow": "relay-source:produce",
        "no_embed_tools": True}, plugin_selectors=(str(PLUGINS / "relay_source"),))


@pytest.mark.parametrize("backend", ["langchain", "client_relay"])
@pytest.mark.parametrize("goal", ["increment the supplied value", "produce payload only"])
def test_two_real_plugins_from_application_entry(tmp_path, monkeypatch, backend, goal):
    """Run the complete chain in one PID and distinguish offline models from real CLI transport."""
    import ucagent.core.backends.langchain.agent as module
    models = []

    def factory(*args, **kwargs):
        """Provide fake model decisions only; all Agent/Host/Checker paths remain production."""
        assert backend == "langchain"
        model = RelayModel()
        models.append(model)
        return model

    monkeypatch.setattr(module, "get_chat_model", factory)
    monkeypatch.setattr(module, "negotiate_openai_api_mode", lambda *a, **kw: None)
    before = {t.ident for t in threading.enumerate()}
    state = run_application(relay_request(tmp_path, backend=backend, goal=goal))
    assert state["status"] == "completed"
    assert state["quiescent"]
    runs = state["runs"]
    assert len(runs) == (2 if "increment" in goal else 1)
    assert all(run["business_status"] == "completed" for run in runs)
    assert (tmp_path / "source/result_a/payload.json").is_file()
    if len(runs) == 2:
        sink = Path(runs[1]["workspace"])
        result = json.loads((sink / "result_b/result.json").read_text())
        assert result == {"value": 8, "source_sha256": hashlib.sha256((sink / "inputs/payload.json").read_bytes()).hexdigest()}
        assert (sink / "Guide_Doc/sink.md").is_file()
        assert not (sink / "Guide_Doc/source.md").exists()
        assert not (sink / "result_a").exists()
        runtime = json.loads((sink / ".ucagent/runtime_config.json").read_text())
        assert runtime["OUT"] == "result_b"
        assert any("relay_sink/src" in path for path in runtime["plugin_python_paths"])
        assert not any("relay_source/src" in path for path in runtime["plugin_python_paths"])
        events = state["events"]
        kinds = [e["event"] for e in events]
        assert kinds.index("candidate_ready") < kinds.index("source_retired") < kinds.index("successor_activated")
        assert {e["pid"] for e in events if "pid" in e} == {os.getpid()}
    if backend == "client_relay":
        calls = []
        for run in runs:
            for invocation in Path(run["workspace"]).glob(".ucagent/multi_agent/**/invocations.jsonl"):
                calls.append([json.loads(line) for line in invocation.read_text().splitlines()])
        assert len(calls) == 2 * len(runs)
        assert len({call[0]["session_id"] for call in calls}) == len(calls)
        assert all(row["pid"] != os.getpid() for call in calls for row in call)
    assert not [t.name for t in threading.enumerate() if t.ident not in before and t.name.startswith("ucagent-")]


def test_sink_business_failure_does_not_replay_source(tmp_path, monkeypatch):
    """A real sink Checker rejects wrong arithmetic while source acceptance remains intact."""
    import ucagent.core.backends.langchain.agent as module
    import relay_fakes
    monkeypatch.setattr(module, "get_chat_model", lambda *a, **kw: RelayModel())
    monkeypatch.setattr(module, "negotiate_openai_api_mode", lambda *a, **kw: None)
    original = relay_fakes.worker_action

    def wrong_arithmetic(index, tips, source):
        """Inject a model output defect without changing the real Checker or runtime."""
        name, args = original(index, tips, source)
        if name == "EditTextFile" and tips["handoff_inputs"]:
            value = json.loads(args["content"])
            value["value"] += 1
            args["content"] = json.dumps(value)
        return name, args

    monkeypatch.setattr(relay_fakes, "worker_action", wrong_arithmetic)
    with pytest.raises(SystemExit) as error:
        run_application(relay_request(tmp_path))
    assert error.value.code == 2
    state = json.loads((tmp_path / "chain/chain.json").read_text())
    assert len(state["runs"]) == 2
    assert state["runs"][0]["business_status"] == "completed"
    assert state["runs"][1]["business_status"] == "pending"
    assert state["status"] != "completed"
    assert sum(e["event"] == "candidate_ready" for e in state["events"]) == 1


@pytest.mark.parametrize("checkpoint", ["accepted", "ready", "committed", "activated"])
def test_restart_at_handoff_checkpoint_never_duplicates_successor(tmp_path, monkeypatch, checkpoint):
    """A drained shutdown resumes its checkpoint without replaying source business work."""
    from dataclasses import replace
    import ucagent.core.backends.langchain.agent as module
    from ucagent.runtime.workflow_handoff import WorkflowHandoff
    monkeypatch.setattr(module, "get_chat_model", lambda *a, **kw: RelayModel())
    monkeypatch.setattr(module, "negotiate_openai_api_mode", lambda *a, **kw: None)
    original = WorkflowHandoff.step
    stopped = []

    def shutdown_at_checkpoint(executor):
        """Stop immediately after a selected persisted lifecycle boundary."""
        if checkpoint != "accepted":
            original(executor)
        transitions = [r["transition"] for r in executor.chain.state["runs"] if r["transition"]]
        match = next((t for t in transitions if t["kind"] == "next" and t["status"] == checkpoint), None)
        if match is not None and not stopped:
            stopped.append(match["target_run_id"])
            executor.shutdown()
        if checkpoint == "accepted":
            original(executor)

    request = relay_request(tmp_path)
    monkeypatch.setattr(WorkflowHandoff, "step", shutdown_at_checkpoint)
    run_application(request)
    state = json.loads((tmp_path / "chain/chain.json").read_text())
    assert stopped and state["quiescent"]
    payload = (tmp_path / "source/result_a/payload.json").stat().st_mtime_ns
    monkeypatch.setattr(WorkflowHandoff, "step", original)
    overrides = dict(request.task_options["cfg_override"])
    overrides["workflow_handoff"] = {**overrides["workflow_handoff"], "resume_chain": str(tmp_path / "chain")}
    resumed = replace(request, task_options={**request.task_options, "cfg_override": overrides})
    result = run_application(resumed)
    assert result["status"] == "completed"
    assert len(result["runs"]) == 2
    if checkpoint in {"committed", "activated"}:
        assert result["runs"][1]["run_id"] == stopped[0]
    assert (tmp_path / "source/result_a/payload.json").stat().st_mtime_ns == payload
    assert sum(e["event"] == "handoff_committed" for e in result["events"]) == 1


@pytest.mark.skipif(os.environ.get("UCAGENT_RELAY_ONLINE") != "1", reason="Set UCAGENT_RELAY_ONLINE=1 for the configured real model smoke test")
def test_configured_real_model_relay(tmp_path):
    """Let the configured model choose a successor; keep all artifacts in a temporary chain."""
    from dataclasses import replace
    from ucagent.core.workflow.contracts import execution_overrides
    from ucagent.util.config import get_config
    config = get_config(config_file=str(Path(__file__).parents[1] / "config.yaml"), workspace=str(tmp_path))
    connections = execution_overrides(config)
    selected = config.get_value("backend.key_name", "langchain")
    if selected == "blank":
        pytest.skip("Configured backend is blank and cannot run a managed Super")
    request = relay_request(tmp_path, backend=selected)
    overrides = dict(request.task_options["cfg_override"])
    overrides.update(connections)
    overrides["langfuse.enable"] = False
    overrides["multi_agent.limits.worker_timeout_seconds"] = 120
    overrides["multi_agent.limits.supervisor_timeout_seconds"] = 120
    overrides["workflow_handoff"]["ready_timeout_seconds"] = 60
    state = run_application(replace(request, task_options={**request.task_options, "cfg_override": overrides}))
    assert state["status"] == "completed"
    assert len(state["runs"]) == 2
    sink = Path(state["runs"][-1]["workspace"])
    result = json.loads((sink / "result_b/result.json").read_text())
    assert result["value"] == 8
    assert result["source_sha256"] == hashlib.sha256((sink / "inputs/payload.json").read_bytes()).hexdigest()


def test_recovery_rejects_changed_source_business_configuration(tmp_path, monkeypatch):
    """Changing source stages or file policy cannot reuse an accepted chain checkpoint."""
    from dataclasses import replace
    import ucagent.core.backends.langchain.agent as module
    monkeypatch.setattr(module, "get_chat_model", lambda *a, **kw: RelayModel())
    monkeypatch.setattr(module, "negotiate_openai_api_mode", lambda *a, **kw: None)
    request = relay_request(tmp_path, goal="produce payload only")
    run_application(request)
    overrides = dict(request.task_options["cfg_override"])
    overrides["write_dirs"] = ["other"]
    overrides["workflow_handoff"] = {**overrides["workflow_handoff"], "resume_chain": str(tmp_path / "chain")}
    with pytest.raises(ValueError, match="source configuration changed"):
        run_application(replace(request, task_options={**request.task_options, "cfg_override": overrides}))
