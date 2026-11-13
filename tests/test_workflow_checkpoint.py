"""H4 checkpoint ownership, configuration identity and safe control-session routing."""

import copy
from pathlib import Path
from types import SimpleNamespace
import threading
import pytest

from test_workflow_contracts import catalog
from ucagent.core.workflow.chain import WorkflowChain
from ucagent.runtime.workflow_checkpoint import WorkflowCheckpoint, policy_fingerprint
from ucagent.runtime.workflow_control import ChainRegistry, RoutedOwner
from ucagent.runtime.control.commands import CommandSession
from ucagent.runtime.control.controller import ControlError


def test_exclusive_checkpoint_and_reconciled_restart(tmp_path):
    """Only clean, configuration-matching state may be reused by a subsequent process."""
    entries = catalog(tmp_path)
    store = WorkflowCheckpoint(tmp_path / "chain")
    try:
        with pytest.raises(RuntimeError, match="active owner"):
            WorkflowCheckpoint(store.root)
        chain = WorkflowChain(entries, "fixture:a", tmp_path, persist=store.save)
        chain.state.update(quiescent=True, policy_fingerprint=policy_fingerprint(entries.settings), execution_fingerprint="execution")
        chain.save()
        recovered = store.load(entries, "execution")
        assert recovered["chain_id"] == chain.state["chain_id"]
        with pytest.raises(ValueError, match="configuration changed"):
            store.load(entries, "other")
        chain.state["quiescent"] = False
        chain.save()
        with pytest.raises(RuntimeError, match="Unreconciled"):
            store.load(entries, "execution")
        chain.state["quiescent"] = True
        chain.save()
        entries.entries["fixture:a"].workflow.config_file.write_text("stage: [changed]\n")
        with pytest.raises(ValueError, match="source/configuration changed"):
            store.load(entries, "execution")
    finally:
        store.close()
    new_owner = WorkflowCheckpoint(store.root)
    new_owner.close()


def test_checkpoint_rejects_symlink_root(tmp_path):
    """Framework-owned state cannot be redirected through a business-controlled symlink."""
    (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        WorkflowCheckpoint(tmp_path / "link/chain")


def test_old_control_session_must_refresh_before_new_run(tmp_path):
    """A network session created for A cannot accidentally write to B after cutover."""
    chain = WorkflowChain(catalog(tmp_path), "fixture:a", tmp_path)
    called = []
    registry = SimpleNamespace(submit=lambda line, session: called.append(line), resolve=lambda name: SimpleNamespace(owner="control", name=name))
    app = SimpleNamespace(_route_lock=threading.RLock(), executor=SimpleNamespace(chain=chain),
        active=SimpleNamespace(registry=registry, agent=SimpleNamespace(workspace=str(tmp_path))),
        snapshot=lambda: chain.view())
    router = ChainRegistry(app)
    session = CommandSession(tmp_path)
    router.submit("help", session)
    chain.state["runs"].append(chain.new_run("fixture:b", tmp_path / "b"))
    with pytest.raises(ControlError, match="workflow changed"):
        router.submit("continue", session)
    router.submit("status", session)
    router.submit("help", session)
    assert called == ["help", "help"]
    assert session.cwd == tmp_path


def test_captured_callback_is_fenced(tmp_path):
    """Late callbacks bind to their original owner and fail instead of jumping to B."""
    app = SimpleNamespace(_route_lock=threading.RLock(), active=SimpleNamespace(controller=SimpleNamespace(status=lambda: "A")))
    routed = RoutedOwner(app, "controller")
    old = routed.status
    app.active = SimpleNamespace(controller=SimpleNamespace(status=lambda: "B"))
    assert routed.status() == "B"
    with pytest.raises(ControlError, match="workflow changed"):
        old()


def test_public_http_control_survives_source_retirement(tmp_path, monkeypatch):
    """A stable listener reports B and rejects mutations bearing A's old run identity."""
    import httpx
    from test_workflow_decisions import setup_agent
    from test_multi_agent import make_agent
    from test_workflow_runtime import advance
    from ucagent.runtime.host import RuntimeHost
    from ucagent.runtime.workflow_handoff import WorkflowHandoff
    from ucagent.runtime.workflow_control import WorkflowApplication
    from ucagent.interfaces.server.api_cmd import ControlApiServer
    agent, chain, _ = setup_agent(tmp_path, monkeypatch)
    source = RuntimeHost(agent, mode="service")
    source.start()

    def factory(run):
        """Construct B and leave its business execution idle for control assertions."""
        target = make_agent(Path(run["workspace"]))
        host = RuntimeHost(target, mode="service")
        host.start()
        monkeypatch.setattr(target.multi_agent, "start_workflow", lambda: None)
        return host

    executor = WorkflowHandoff(chain, source, factory, tmp_path / "chain")
    app = WorkflowApplication(executor)
    app.services.command_factory = lambda **opts: ControlApiServer(app.controller,
        registry=app.registry, operations=app.operations, services=app.services, host_control=app, **opts)
    server = app.services.command_factory(port=0, sock="")
    result = app.services.start("cmd", lambda: server)
    assert result["ok"], result
    url = server.url()
    old_run = chain.current["run_id"]
    try:
        with httpx.Client(base_url=url, timeout=3) as client:
            initial = client.get("/api/runtime/status")
            assert initial.status_code == 200, initial.text
            assert initial.headers["X-UCAgent-Run-ID"] == old_run
            agent.multi_agent.start_workflow()
            advance(executor, lambda: (chain.current["transition"] or {}).get("status") == "ready")
            blocked = client.post("/api/file/edit", headers={"X-UCAgent-Run-ID": old_run},
                                  json={"path": "out/result.md", "content": "late mutation"})
            assert blocked.status_code == 409
            advance(executor, lambda: len(chain.state["runs"]) == 2)
            assert source._closed.is_set() and server.is_ready
            status = client.get("/api/runtime/status")
            assert status.status_code == 200, status.text
            new_run = status.headers["X-UCAgent-Run-ID"]
            assert new_run != old_run
            assert status.json()["data"]["workflow_chain"]["runs"][-1]["run_id"] == new_run
            stale = client.post("/api/runtime/pause", headers={"X-UCAgent-Run-ID": old_run})
            assert stale.status_code == 409
            paused = client.post("/api/runtime/pause", headers={"X-UCAgent-Run-ID": new_run})
            assert paused.status_code == 200, paused.text
            assert chain.state["status"] == "paused"
    finally:
        app.request_shutdown()
        app.pump()
        assert not server.is_running
