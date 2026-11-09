"""Regression contracts for the user-visible console/TUI behavior after runtime extraction."""

import asyncio
import shlex
import sys
import threading

import pytest
from rich.text import Text
from textual.widgets import Input, Static

from test_console_runtime import console
from ucagent.runtime.operations import TERMINAL_STATES
from ucagent.interfaces.terminal.presentation import format_mission, format_status
from ucagent.interfaces.terminal.tui.app import VerifyApp
from ucagent.interfaces.terminal.tui.screens.confirmation import ConfirmationScreen
from ucagent.interfaces.terminal.tui.widgets import ConsoleWidget, MessagesPanel, TaskPanel
from ucagent.util.log import info


async def observe(pilot, predicate):
    """Wait for observable state with an explicit deadline instead of fixed sleeps."""
    async with asyncio.timeout(5):
        while not predicate():
            await pilot.pause(0.02)


def test_mission_renderer_preserves_baseline_markers_and_statistics():
    """The detached-data renderer retains the original indices, flags and ANSI colors."""
    mission = {"current_index": 1, "stages": [
        {"index": 0, "title": "Completed", "fail_count": 2, "skill_list": ["evidence"],
         "time_cost": "1m", "need_fail_llm_suggestion": True},
        {"index": 1, "title": "Current", "needs_human_check": True, "fail_count": 1,
         "need_pass_llm_suggestion": True},
        {"index": 2, "title": "Skipped", "is_skipped": True},
    ]}
    rendered = [Text.from_ansi(line) for line in format_mission(mission, use_skills=True)]
    assert rendered[0].plain == " 0 *  Completed ([evidence], 2 fails, 1m)"
    assert rendered[1].plain == " 1  **Current (1 fails)"
    assert rendered[2].plain == " 2    Skipped (skipped)"
    assert all(line.spans for line in rendered)
    assert "evidence" not in "\n".join(format_mission(mission))
    assert format_status({"LLM": "test", "Temperature": 0.8123, "Stream": True}) == (
        "LLM: test Temperature: 0.81 Stream: True")


@pytest.mark.asyncio
async def test_initial_layout_and_readable_status_match_original(console):
    """At the audited terminal size the original half-height console is restored."""
    app = VerifyApp(console)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        assert app.console_height == 25
        assert app.query_one(ConsoleWidget).region.height == 25
        assert app.query_one(TaskPanel).region.width == 82
        panel = app.query_one(TaskPanel)
        lines = [Text.from_ansi(line).plain for line in panel._format_task_lines()]
        assert lines[0].startswith(" 0 *")
        assert "(0 fails" in lines[0]
        status = str(app.query_one("#status-summary", Static).render())
        assert "LLM: test-model" in status and "Run Time: 0s" in status
        assert "{'" not in status


@pytest.mark.asyncio
async def test_real_print_stderr_and_logging_reach_console_once(console):
    """Exercise real streams without constructing an HTTP server or directly writing its buffer."""
    app = VerifyApp(console)
    previous_stdout, previous_stderr = sys.stdout, sys.stderr
    async with app.run_test() as pilot:
        print("parity-stdout")
        sys.stderr.write("parity-stderr\n")
        info("parity-log")
        app.flush_console_output()
        text = console.render_console_entries_since()
        for marker in ("parity-stdout", "parity-stderr", "parity-log"):
            assert text.count(marker) == 1
        assert console.host.services.status("cmd")["state"] != "ready"
    assert sys.stdout is previous_stdout and sys.stderr is previous_stderr


@pytest.mark.asyncio
async def test_history_navigates_from_actual_submitted_commands(console):
    """Arrow keys see commands submitted through the input widget, including a fresh tail."""
    console.record_cmd_history("older-command")
    app = VerifyApp(console)
    async with app.run_test() as pilot:
        entry = app.query_one("#console-input", Input)
        for command in ("status", "pwd"):
            entry.value = command
            await pilot.press("enter")
            await observe(pilot, lambda: console.history[-1] == command)
        await pilot.press("up")
        assert entry.value == "pwd"
        await pilot.press("up")
        assert entry.value == "status"
        await pilot.press("down")
        assert entry.value == "pwd"
        await pilot.press("down")
        assert entry.value == ""
        assert "LLM: test-model" in console.render_console_entries_since()


@pytest.mark.asyncio
async def test_help_toggle_and_escape_preserve_input(console):
    """F1 mounts the docked overlay and Escape dismisses it without clearing the draft."""
    app = VerifyApp(console)
    async with app.run_test() as pilot:
        entry = app.query_one("#console-input", Input)
        entry.value = "unfinished command"
        await pilot.press("f1")
        assert len(app.query("#help-overlay")) == 1
        await pilot.press("escape")
        assert not app.query("#help-overlay")
        assert entry.value == "unfinished command"
        await pilot.press("f1", "f1")
        assert not app.query("#help-overlay")


@pytest.mark.asyncio
async def test_shell_completion_respects_cwd_and_quoted_spaces(console, tmp_path):
    """Tab after the shell executable inserts a usable quoted workspace filename."""
    child = tmp_path / "child"
    child.mkdir()
    (child / "two words.txt").write_text("payload")
    console.execute_line("cd child")
    assert "two words.txt" in console.registry.complete("shell cat ", console.session)
    app = VerifyApp(console)
    async with app.run_test() as pilot:
        entry = app.query_one("#console-input", Input)
        entry.value = 'shell cat "two w'
        await pilot.press("tab")
        assert shlex.split(entry.value) == ["shell", "cat", "two words.txt"]


@pytest.mark.asyncio
async def test_shell_nonzero_exit_is_visible_once_and_survives_reattach(console):
    """Users see the terminal failure and exit code, beyond the initial accepted ID."""
    app = VerifyApp(console)
    async with app.run_test() as pilot:
        app.key_handler.process_command("shell printf parity-payload; exit 7")
        operation_id = console.foreground_id
        await observe(pilot, lambda: console.host.operations.get(operation_id)["state"] in TERMINAL_STATES)
        app.refresh_runtime_state()
        text = console.render_console_entries_since()
        assert text.count("process_failed:") == 1
        assert '"returncode": 7' in text
        assert ": failed" in text
        app.action_detach()
    restored = VerifyApp(console)
    async with restored.run_test() as pilot:
        restored.refresh_runtime_state()
        assert console.render_console_entries_since().count("process_failed:") == 1


@pytest.mark.asyncio
async def test_background_display_and_foreground_fallback(console):
    """A finished newer job cannot hide an earlier foreground job from Ctrl-C."""
    older = console.execute_line("sleep 30").data
    newer = console.execute_line("sleep 0.01").data
    background = console.execute_line("sleep 31", foreground=False).data
    app = VerifyApp(console)
    async with app.run_test() as pilot:
        await observe(pilot, lambda: console.host.operations.get(newer["id"])["state"] == "succeeded")
        app.refresh_runtime_state()
        app.query_one(TaskPanel)._update_daemon_cmds()
        assert "sleep 31" in str(app.query_one("#daemon-cmds", Static).render())
        assert console.get_running_commands() == ["sleep 30", "sleep 31"]
        await pilot.press("ctrl+c")
        await observe(pilot, lambda: console.host.operations.get(older["id"])["state"] == "cancelled")
        assert console.host.operations.get(background["id"])["state"] == "running"
        assert not console.cancel_foreground()


@pytest.mark.asyncio
async def test_confirmation_cancel_then_accept_and_scope(console, tmp_path):
    """Cancel never starts work; accepting confirms exactly one command."""
    target = tmp_path / "disposable.txt"
    target.write_text("test")
    app = VerifyApp(console)
    async with app.run_test() as pilot:
        app.key_handler.process_command("shell rm disposable.txt")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmationScreen)
        assert not console.host.operations.list()
        await pilot.press("escape")
        assert target.exists()
        app.key_handler.process_command("shell rm disposable.txt")
        await pilot.pause()
        await pilot.click("#confirm-command")
        await observe(pilot, lambda: console.foreground_id is not None)
        operation_id = console.foreground_id
        await observe(pilot, lambda: console.host.operations.get(operation_id)["state"] in TERMINAL_STATES)
        assert console.host.operations.get(operation_id)["state"] == "succeeded"
        assert not target.exists() and console.session.confirmed is False
        target.write_text("second command")
        app.key_handler.process_command("shell rm disposable.txt")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmationScreen)
        assert len(console.host.operations.list()) == 1
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_model_and_mcp_messages_during_detach_are_replayed_once(console):
    """The session owns message buffering while the UI can be replaced freely."""
    app = VerifyApp(console)
    async with app.run_test() as pilot:
        console.agent.message_echo_handler("first")
        await pilot.pause(0.2)
        app.action_detach()
    console.agent.message_echo_handler("between", end="")
    console.agent.message_echo_handler(" views")
    console.agent._mcps_logger.info("mcp-between")
    console.host.output.write("output-between\n")
    restored = VerifyApp(console)
    async with restored.run_test() as pilot:
        await observe(pilot, lambda: len(restored.query_one(MessagesPanel)._render_history) >= 3)
        text = "\n".join(line.plain for line in restored.query_one(MessagesPanel)._render_history)
        assert text.count("first") == 1
        assert text.count("between views") == 1
        assert text.count("mcp-between") == 1
        assert console.render_console_entries_since().count("output-between") == 1


@pytest.mark.asyncio
async def test_initial_model_work_starts_after_ui_sinks_and_keeps_command_order(console):
    """Automatic model work and following commands never run ahead of the mounted TUI."""
    entered = threading.Event()

    def first_round():
        """Assert the frontend is attached at the first real backend callback."""
        assert console.host.message_view_attached
        print("first-model-console")
        console.agent.message_echo_handler("first-model-message")
        entered.set()

    console.agent.round_hook = first_round
    console.host.startup.start(["nr", "status"], console, wait_for_display=True, interactive=True)
    assert console.agent.invoke_round == 0
    app = VerifyApp(console)
    async with app.run_test() as pilot:
        await observe(pilot, lambda: entered.is_set() and console.history[-1:] == ["status"])
        await observe(pilot, lambda: bool(app.query_one(MessagesPanel)._render_history))
        assert console.history == ["nr", "status"]
        assert console.render_console_entries_since().count("first-model-console") == 1
        messages = "\n".join(line.plain for line in app.query_one(MessagesPanel)._render_history)
        assert messages.count("first-model-message") == 1
        assert console.host.startup.model_started
        await pilot.press("up")
        assert app.query_one("#console-input", Input).value == "status"


@pytest.mark.asyncio
async def test_slow_service_command_keeps_ui_responsive_and_owned(console, monkeypatch):
    """A blocked service action stays host-owned while keyboard help remains responsive."""
    entered, release = threading.Event(), threading.Event()

    def service(command, arguments, session):
        """Hold the service boundary until the test has interacted with Textual."""
        entered.set()
        assert release.wait(5), "Service operation was not released"
        return {"ok": True, "message": "Service ready"}

    monkeypatch.setattr(console.host.services, "execute", service)
    app = VerifyApp(console)
    try:
        async with app.run_test() as pilot:
            app.key_handler.process_command("cmd_api_start")
            await observe(pilot, entered.is_set)
            operation_id = console.foreground_id
            await pilot.press("f1")
            assert app.query("#help-overlay")
            app.action_detach()
        assert console.host.operations.get(operation_id)["state"] == "running"
    finally:
        release.set()
    assert console.host.operations.wait(operation_id, 3)["state"] == "succeeded"
    restored = VerifyApp(console)
    async with restored.run_test() as pilot:
        await observe(pilot, lambda: "Service ready" in console.render_console_entries_since())
        assert console.render_console_entries_since().count("Service ready") == 1


@pytest.mark.asyncio
async def test_detach_replays_new_output_appended_to_existing_entry(console):
    """Coalescing output entries cannot swallow text when returning to the terminal."""
    console.record_console_output("old output\n")
    app = VerifyApp(console)
    async with app.run_test():
        print("new output")
        app.cleanup()
    assert app.session_output == "new output\n"


@pytest.mark.asyncio
async def test_pending_messages_before_mount_are_not_cleared_by_restore(console):
    """Service logs buffered before TUI construction survive widget state restoration."""
    console.agent._mcps_logger.info("before-mount-message")
    console.host.output.write("before-mount-output\n")
    app = VerifyApp(console)
    async with app.run_test() as pilot:
        await observe(pilot, lambda: bool(app.query_one(MessagesPanel)._render_history))
        text = "\n".join(line.plain for line in app.query_one(MessagesPanel)._render_history)
        assert text.count("before-mount-message") == 1
        assert console.render_console_entries_since().count("before-mount-output") == 1


@pytest.mark.asyncio
async def test_output_during_ui_teardown_remains_available_to_console(console):
    """Late worker prints after view cleanup are retained until the next frontend reads them."""
    app = VerifyApp(console)
    async with app.run_test():
        app.cleanup()
        print("teardown-worker-output")
    assert console.drain_output().count("teardown-worker-output") == 1
    assert not console.host.message_view_attached
