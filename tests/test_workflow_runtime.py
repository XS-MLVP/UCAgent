"""H3 lifecycle ordering and candidate failure behind a real RuntimeHost barrier."""

import threading
from pathlib import Path
import time
from types import SimpleNamespace
import pytest

from test_workflow_decisions import setup_agent
from test_multi_agent import make_agent
from ucagent.runtime.host import RuntimeHost
from ucagent.runtime.workflow_handoff import WorkflowHandoff


def advance(executor, predicate, timeout=6):
    """Drive passive lifecycle steps until an observable condition or a bounded failure."""
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, executor.chain.view()
        executor.step()
        threading.Event().wait(0.01)


def test_ready_commit_retire_activate_and_same_process(tmp_path, monkeypatch):
    """B has a distinct Agent and cannot execute before A is actually closed."""
    agent, chain, _ = setup_agent(tmp_path, monkeypatch)
    root = tmp_path / "chain"
    host = RuntimeHost(agent, mode="service")
    host.start()
    created = []

    def factory(run):
        """Create a second real Agent but replace only its test model start observer."""
        candidate = make_agent(Path(run["workspace"]))
        child = RuntimeHost(candidate, mode="service")
        child.start()
        created.append(child)
        monkeypatch.setattr(candidate.multi_agent, "start_workflow", lambda: chain.event(
            "test_business_start", source_closed=host._closed.is_set()))
        assert not host._closed.is_set()
        assert candidate.stage_manager.stage_index == 0
        return child

    executor = WorkflowHandoff(chain, host, factory, root)
    try:
        agent.multi_agent.start_workflow()
        advance(executor, lambda: len(chain.state["runs"]) == 2)
        kinds = [e["event"] for e in chain.state["events"]]
        assert kinds.index("candidate_ready") < kinds.index("handoff_committed") < kinds.index("source_retired") < kinds.index("test_business_start")
        assert chain.state["events"][-1]["source_closed"]
        assert created[0].agent is not agent
        assert created[0].agent.session_id != agent.session_id
        assert created[0].agent.workspace != agent.workspace
        assert not created[0].agent.multi_agent.records
        assert (root / "runs" / chain.current["run_id"] / "workspace/inputs/a.json").read_text() == "evidence"
    finally:
        executor.shutdown()
        advance(executor, executor.closed)


def test_prepare_failure_preserves_source_and_no_business_replay(tmp_path, monkeypatch):
    """A remains usable after failed B initialization, with bounded decisions and attempts."""
    agent, chain, _ = setup_agent(tmp_path, monkeypatch)
    host = RuntimeHost(agent, mode="service")
    host.start()

    def fail(run):
        """Inject a target failure after the accepted input snapshot exists."""
        raise RuntimeError("fixture startup failure")

    executor = WorkflowHandoff(chain, host, fail, tmp_path / "chain")
    try:
        agent.multi_agent.start_workflow()
        advance(executor, lambda: bool(chain.current["history"]))
        assert not host._closed.is_set()
        assert chain.current["business_status"] == "completed"
        assert len(agent.multi_agent.records) == 1
        assert "fixture startup failure" in chain.current["history"][0]["error"]
    finally:
        executor.shutdown()
        advance(executor, executor.closed)


def test_pause_after_commit_retains_unique_successor(tmp_path, monkeypatch):
    """Pause permits retirement but never releases B's execution barrier."""
    agent, chain, _ = setup_agent(tmp_path, monkeypatch)
    host = RuntimeHost(agent, mode="service")
    host.start()

    def factory(run):
        """Return a ready candidate and trap any premature activation."""
        candidate = make_agent(Path(run["workspace"]))
        child = RuntimeHost(candidate, mode="service")
        child.start()
        monkeypatch.setattr(candidate.multi_agent, "start_workflow", lambda: pytest.fail("Activated while paused"))
        return child

    executor = WorkflowHandoff(chain, host, factory, tmp_path / "chain")
    try:
        agent.multi_agent.start_workflow()
        advance(executor, lambda: (chain.current["transition"] or {}).get("status") == "committed")
        target = chain.current["transition"]["target_run_id"]
        executor.pause()
        advance(executor, lambda: chain.current["transition"]["status"] == "retired")
        executor.step()
        assert chain.current["transition"]["target_run_id"] == target
        assert len(chain.state["runs"]) == 1
        assert executor.candidate is not None
    finally:
        executor.shutdown()
        advance(executor, executor.closed)


def test_timeout_keeps_preparer_owned_until_it_finishes(tmp_path, monkeypatch):
    """A timeout does not release a live initializer or permit a second candidate."""
    agent, chain, _ = setup_agent(tmp_path, monkeypatch)
    chain.settings.ready_timeout_seconds = 0.01
    host = RuntimeHost(agent, mode="service")
    host.start()
    entered, release = threading.Event(), threading.Event()

    def slow_factory(run):
        """Hold initialization past the deadline and then fail without a Host."""
        entered.set()
        assert release.wait(4)
        raise RuntimeError("late startup failure")

    executor = WorkflowHandoff(chain, host, slow_factory, tmp_path / "chain")
    try:
        agent.multi_agent.start_workflow()
        advance(executor, entered.is_set)
        advance(executor, lambda: chain.current["transition"]["status"] == "cleanup_pending")
        assert chain.current["attempts"] == 1
        assert not host._closed.is_set()
        executor.shutdown()
        assert not executor.closed()
        release.set()
        advance(executor, executor.closed)
    finally:
        release.set()
        executor.shutdown()
        advance(executor, executor.closed)


def test_source_changed_after_acceptance_fails_before_factory(tmp_path, monkeypatch):
    """Input fingerprints bind the decision to accepted bytes, not mutable later contents."""
    agent, chain, _ = setup_agent(tmp_path, monkeypatch)
    host = RuntimeHost(agent, mode="service")
    host.start()
    executor = WorkflowHandoff(chain, host, lambda run: pytest.fail("Factory must not run"), tmp_path / "chain")
    try:
        agent.one_loop()
        (tmp_path / "out/result.md").write_text("changed")
        executor.pause()
        # Resume just the runtime decision, keeping model retry disabled for this observation.
        chain.state["status"] = "running"
        monkeypatch.setattr(agent.multi_agent, "start_workflow", lambda: None)
        advance(executor, lambda: bool(chain.current["history"]))
        assert "changed" in chain.current["history"][0]["error"]
        assert not host._closed.is_set()
    finally:
        executor.shutdown()
        advance(executor, executor.closed)


def test_shared_trace_client_outlives_retiring_instance():
    """Retiring A cannot close telemetry that candidate B still owns."""
    from unittest.mock import Mock
    from ucagent.core.agent.telemetry import acquire_trace_client
    client = Mock()
    client.auth_check.return_value = True
    factory = Mock(return_value=client)
    first, release_a = acquire_trace_client(factory, public_key="fixture", secret_key="fixture")
    second, release_b = acquire_trace_client(factory, public_key="fixture", secret_key="fixture")
    assert first is second
    release_a()
    client.shutdown.assert_not_called()
    release_b()
    release_b()
    client.shutdown.assert_called_once()


def test_source_cleanup_failure_keeps_successor_gated(tmp_path, monkeypatch):
    """A failed cleanup callback cannot be reported as successful retirement or activate B."""
    agent, chain, _ = setup_agent(tmp_path, monkeypatch)
    host = RuntimeHost(agent, mode="service")

    def broken_cleanup():
        """Inject a reported resource restoration failure at the source's retirement boundary."""
        raise RuntimeError("fixture cleanup failure")

    host.add_cleanup(broken_cleanup)
    host.start()

    def factory(run):
        """Prepare a real candidate whose execution must remain gated."""
        target = make_agent(Path(run["workspace"]))
        candidate = RuntimeHost(target, mode="service")
        candidate.start()
        monkeypatch.setattr(target.multi_agent, "start_workflow", lambda: pytest.fail("B activated after failed A cleanup"))
        return candidate

    executor = WorkflowHandoff(chain, host, factory, tmp_path / "chain")
    try:
        agent.multi_agent.start_workflow()
        advance(executor, lambda: executor.error is not None)
        assert chain.state["status"] == "paused"
        assert chain.current["transition"]["status"] == "committed"
        assert host.errors and len(chain.state["runs"]) == 1
        assert executor.candidate is not None
        assert not any(e["event"] == "source_retired" for e in chain.state["events"])
    finally:
        executor.shutdown()
        advance(executor, executor.closed)
