"""Global conversation admission must preserve terminal lifetime commands."""
import io
import pytest
from test_global_tui import global_session, runtime
from ucagent.interfaces.terminal.console import Console
from ucagent.interfaces.terminal.tui.global_app import GlobalApp
from ucagent.interfaces.terminal.presentation import format_result
from ucagent.runtime.control.commands import CommandResult

@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["q", "quit", "exit", "shutdown", "/q", "/quit"])
async def test_quit_after_global_tui_detaches_closes_host(global_session, command):
    frontend, runtime, seen = global_session
    app = GlobalApp(frontend)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(.2)
        await pilot.press("ctrl+q")
    assert frontend.host.snapshot()["instance"] == "ready"
    terminal = Console(frontend.host, session=frontend, output_stream=io.StringIO())
    terminal.display_result(terminal.execute_line(command))
    assert frontend.host.wait(3)["instance"] == "closed"
    assert not runtime.inbox.items and seen == []


def test_global_console_formats_message_receipts_and_reserves_force(global_session):
    frontend, runtime, _ = global_session
    terminal = Console(frontend.host, session=frontend, output_stream=io.StringIO())
    result = terminal.execute_line("Please verify the DUT")
    terminal.display_result(result)
    assert "Message: queued" in terminal.output.getvalue()
    assert runtime.inbox.items[-1]["text"] == "Please verify the DUT"
    assert terminal.execute_line("   ") is None
    calls = []
    frontend.host.force_exit = calls.append
    terminal.display_result(terminal.execute_line("q force"))
    assert calls == [130] and len(runtime.inbox.items) == 1


def test_non_operation_dictionary_is_not_formatted_as_operation():
    assert '"state": "ready"' in format_result(CommandResult("custom", {"id": "task", "state": "ready"}))
