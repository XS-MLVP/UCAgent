"""Attach/detach a real Textual view without transferring business operation ownership."""

import pytest
from test_console_runtime import console
from ucagent.interfaces.terminal.tui.app import VerifyApp
from ucagent.interfaces.terminal.tui.widgets import ConsoleWidget, MessagesPanel


@pytest.mark.asyncio
async def test_tui_detaches_and_reattaches_same_operation(console):
    """Leaving the interface preserves its operation ID and does not start a duplicate call."""
    operation = console.execute_line("sleep 10").data
    app = VerifyApp(console)
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        app.action_detach()
    assert console.host.operations.get(operation["id"])["state"] == "running"
    restored = VerifyApp(console)
    async with restored.run_test() as pilot:
        await pilot.pause(0.1)
        assert console.get_running_commands() == ["sleep 10"]
        assert restored.cancel_running_command()
    assert console.host.operations.wait(operation["id"], 2)["state"] == "cancelled"
    assert len(console.host.operations.list()) == 1


@pytest.mark.asyncio
async def test_tui_messages_and_console_history_survive_without_duplicates(console):
    """Repeated UI attachment reuses transcript and pending message state."""
    app = VerifyApp(console)
    async with app.run_test() as pilot:
        app.message_echo("hello")
        app.console_output("one line\n")
        await pilot.pause(0.3)
        app.cleanup()
    restored = VerifyApp(console)
    async with restored.run_test() as pilot:
        await pilot.pause(0.1)
        assert console.render_console_entries_since().count("one line") == 1
        assert [line.plain for line in restored.query_one(MessagesPanel)._render_history] == ["hello"]


@pytest.mark.asyncio
async def test_typed_quit_detaches_without_shutting_down(console):
    """Bare quit has the same view-only meaning as Ctrl-Q."""
    app = VerifyApp(console)
    async with app.run_test():
        app.key_handler.process_command("quit")
    assert console.host.snapshot()["instance"] == "ready"
