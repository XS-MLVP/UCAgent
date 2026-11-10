"""Task and service lifetime must remain independent of local frontend attachment."""

from ucagent.interfaces.terminal.presentation import format_result, format_operation
import io
import threading

from fastapi.testclient import TestClient
import pytest

from test_console_runtime import console
from test_runtime_host import make_host
from test_tui_parity import observe
from ucagent.interfaces.terminal.console import Console
from ucagent.runtime.control.controller import ControlError
from ucagent.runtime.session import RuntimeSession
from ucagent.interfaces.server.api_cmd import ControlApiServer
from ucagent.interfaces.terminal.tui.app import VerifyApp
from textual.widgets import Input


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["q", "quit", "exit", "ctrl+q"])
async def test_leaving_view_preserves_tasks_and_real_http_service(console, command):
    """Each ordinary TUI exit preserves the same operation ID and reachable service."""
    host = console.host
    console.agent.cfg.set_value("cmd_api", {"xpra": {}, "waveform_viewers": {}})
    status = host.services.start("cmd", lambda: ControlApiServer(
        host.controller, registry=host.registry, operations=host.operations,
        services=host.services, host_control=host, host="127.0.0.1", port=0, sock=""))
    assert status["ok"], status
    server = host.services.get("cmd")
    operation = console.execute_line("sleep 30").data
    app = VerifyApp(console)
    async with app.run_test() as pilot:
        if command == "ctrl+q":
            await pilot.press("ctrl+q")
        else:
            app.query_one("#console-input", Input).value = command
            await pilot.press("enter")
    assert host.snapshot()["instance"] == "ready"
    assert host.operations.get(operation["id"])["state"] == "running"
    assert host.services.get("cmd") is server and server.is_running
    with TestClient(server._app) as client:
        assert client.get("/api/runtime/status").json()["data"]["instance"] == "ready"
    restored = VerifyApp(console)
    async with restored.run_test():
        assert console.foreground_id == operation["id"]
        assert console.cancel_foreground()
    assert host.operations.wait(operation["id"], 2)["state"] == "cancelled"


@pytest.mark.asyncio
async def test_shutdown_is_explicit_instance_action_from_tui(console):
    """An explicit shutdown cancels owned work and closes the host, unlike q."""
    operation = console.execute_line("sleep 30").data
    app = VerifyApp(console)
    async with app.run_test() as pilot:
        app.query_one("#console-input", Input).value = "shutdown"
        await pilot.press("enter")
    assert console.host.wait(3)["instance"] == "closed"
    assert console.host.operations.get(operation["id"])["state"] == "cancelled"


@pytest.mark.asyncio
async def test_view_commands_and_help_are_local_and_blank_enter_is_idle(console):
    """Local help describes q accurately; blank Enter cannot repeat a task command."""
    app = VerifyApp(console)
    async with app.run_test() as pilot:
        app.key_handler.process_command("help q")
        assert "Leave TUI; keep tasks and services running" in console.render_console_entries_since()
        app.key_handler.process_command("help shutdown")
        assert "Close the instance and stop tasks and services" in console.render_console_entries_since()
        app.key_handler.process_command("sleep 30")
        count = len(console.host.operations.list())
        await pilot.press("enter")
        assert len(console.host.operations.list()) == count
        app.key_handler.process_command("q force")
        assert console.host.snapshot()["instance"] == "ready"
        assert not app._cleaned
        with pytest.raises(ControlError):
            console.host.registry.submit("clear", console.session)


def test_sessions_do_not_replace_global_executors_or_interrupt_targets(console):
    """Constructing a new session/view cannot steal commands or Ctrl-C from an active one."""
    host = console.host
    executors = dict(host.registry.executors)
    first = console.execute_line("sleep 30").data
    host.attach_control("active-first", interrupt=console.cancel_foreground)
    other = RuntimeSession(host, result_formatter=format_result, operation_formatter=format_operation)
    Console(host, session=other, output_stream=io.StringIO())
    second = other.execute_line("sleep 30").data
    assert host.registry.executors == executors
    host.interrupt()
    assert host.operations.wait(first["id"], 2)["state"] == "cancelled"
    assert host.operations.get(second["id"])["state"] == "running"
    host.attach_control("active-second", interrupt=other.cancel_foreground)
    host.detach_control("active-first")
    host.interrupt()
    assert host.operations.wait(second["id"], 2)["state"] == "cancelled"
    host.detach_control("active-second")


def test_headless_runtime_keeps_messages_and_tasks_without_console(tmp_path):
    """A host can execute and buffer MCP messages before any local session or view exists."""
    host, runtime = make_host(tmp_path, mode="service")
    host.start()
    try:
        runtime.agent._mcps_logger.info("before-any-view")
        operation = host.operations.submit("background", lambda context: context.wait(30))
        session = RuntimeSession(host, result_formatter=format_result, operation_formatter=format_operation)
        assert "before-any-view" in session.drain_output()
        assert "before-any-view" not in session.drain_messages()
        assert host.events.read("system")["data"][-1]["source"] == "service"
        session.close()
        assert host.operations.get(operation["id"])["state"] == "running"
        assert host.snapshot()["instance"] == "ready"
    finally:
        host.request_shutdown()
        assert host.wait(3)["instance"] == "closed"


@pytest.mark.asyncio
async def test_startup_advances_without_ui_polling_after_detach(console, tmp_path):
    """The runtime, rather than a TUI timer, completes ordered initialization after detachment."""
    marker = tmp_path / "startup-finished"
    startup = console.host.startup.start(
        ["sleep 0.15", "shell printf ready > startup-finished"], console,
        wait_for_display=True, interactive=True)
    assert not marker.exists()
    app = VerifyApp(console)
    async with app.run_test():
        app.action_detach()
    result = console.host.operations.wait(startup["id"], 3)
    assert result["state"] == "succeeded", result
    assert marker.read_text() == "ready"


@pytest.mark.asyncio
async def test_interactive_startup_queries_do_not_wait_for_loop(console):
    """A live model loop permits later queries, preserving the original TUI launch behavior."""
    entered, release = threading.Event(), threading.Event()

    def blocked_round():
        """Hold the first model call until a following startup query has been submitted."""
        entered.set()
        assert release.wait(5)

    console.agent.round_hook = blocked_round
    startup = console.host.startup.start(["loop", "status"], console, interactive=True)
    try:
        assert entered.wait(2)
        result = console.host.operations.wait(startup["id"], 2)
        assert result["state"] == "succeeded", result
        assert console.history[-2:] == ["loop", "status"]
        assert console.host.operations.get(console.foreground_id)["state"] == "running"
    finally:
        release.set()


@pytest.mark.asyncio
async def test_review_continuation_belongs_to_session_and_ctrl_c(console):
    """An approval-created model operation inherits the initiating session and foreground policy."""
    entered, release = threading.Event(), threading.Event()

    def blocked_round():
        """Keep continuation live while foreground selection and cancellation are inspected."""
        entered.set()
        assert release.wait(5)

    console.agent.round_hook = blocked_round
    app = VerifyApp(console)
    try:
        async with app.run_test() as pilot:
            app.key_handler.process_command("hmcheck_pass_and_continue Reviewed")
            await observe(pilot, entered.is_set)
            rows = console.host.operations.list()
            child = next(row for row in rows if row["command"] == "continue")
            parent = next(row for row in rows if row["command"] == "hmcheck_pass_and_continue")
            assert child["parent_id"] == parent["id"]
            assert child["session_id"] == console.session.id and child["foreground"]
            assert console.foreground_id == child["id"]
            await pilot.press("ctrl+c")
            assert console.host.operations.get(child["id"])["state"] == "cancelling"
            assert not console.agent.stage_manager.stages[0].is_completed()
    finally:
        release.set()
    assert console.host.operations.wait(child["id"], 3)["state"] == "cancelled"


def test_console_and_registry_share_nonblocking_control_dispatch(console, monkeypatch):
    """A blocked service action must not block the ordinary terminal's next command."""
    entered, release = threading.Event(), threading.Event()

    def slow_service(command, arguments, session):
        """Model a service boundary with a controlled, non-UI-owned wait."""
        entered.set()
        assert release.wait(5)
        return {"ok": True}

    monkeypatch.setattr(console.host.services, "execute", slow_service)
    view = Console(console.host, session=console, output_stream=io.StringIO())
    try:
        accepted = view.execute_line("cmd_api_start")
        assert entered.wait(2)
        assert view.execute_line("status").data["LLM"] == "test-model"
        assert console.host.operations.get(accepted.data["id"])["state"] == "running"
    finally:
        release.set()
    assert console.host.operations.wait(accepted.data["id"], 2)["result"] == {"ok": True}


def test_startup_waits_for_review_continuation_before_next_model(console):
    """Initialization cannot declare approval complete and race a second model submission."""
    entered, release = threading.Event(), threading.Event()

    def first_round():
        """Block only the first model call so ordering can be observed before release."""
        if not entered.is_set():
            entered.set()
            assert release.wait(5)

    console.agent.round_hook = first_round
    startup = console.host.startup.start(["hmcheck_pass_and_continue Ready", "nr"], console)
    try:
        assert entered.wait(2)
        assert not any(row["command"] == "next_round" for row in console.host.operations.list())
    finally:
        release.set()
    result = console.host.operations.wait(startup["id"], 3)
    assert result["state"] == "succeeded", result
    assert console.agent.invoke_round == 2


def test_http_batch_waits_for_approval_continuation(console):
    """HTTP batch ordering uses the same continuation ownership as local startup."""
    host = console.host
    console.agent.cfg.set_value("cmd_api", {"xpra": {}, "waveform_viewers": {}})
    server = ControlApiServer(host.controller, registry=host.registry, operations=host.operations,
                              services=host.services, host_control=host, sock="")
    entered, release = threading.Event(), threading.Event()

    def first_round():
        """Hold the continuation until the batch has had a chance to advance incorrectly."""
        if not entered.is_set():
            entered.set()
            assert release.wait(5)

    console.agent.round_hook = first_round
    try:
        with TestClient(server._app) as client:
            accepted = client.post("/api/cmds/batch", json={
                "cmds": ["hmcheck_pass_and_continue Ready", "nr"]})
            assert accepted.status_code == 200, accepted.text
            assert entered.wait(2)
            assert not any(row["command"] == "next_round" for row in host.operations.list())
            release.set()
            result = host.operations.wait(accepted.json()["operation_id"], 3)
            assert result["state"] == "succeeded", result
            assert console.agent.invoke_round == 2
    finally:
        release.set()
        server.stop()


def test_losing_last_interactive_view_does_not_close_waiting_runtime(console):
    """Human waiting in an interactive instance survives loss of all local controls."""
    operation = console.execute_line("nr").data
    assert console.host.operations.wait(operation["id"], 2)["state"] == "succeeded"
    console.host.detach_control("test-console")
    # Waiting must not imply an automatic lifecycle transition in interactive mode.
    assert console.host.wait(0.1)["instance"] == "ready"
    console.host.attach_control("reconnected")
    assert console.controller.stage_state()["stages"][0]["needs_human_check"]
