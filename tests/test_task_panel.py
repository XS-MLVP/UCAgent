"""Regression tests for nonblocking Changed Files polling."""

import asyncio
import threading
from unittest.mock import Mock

import pytest
from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.widgets import Input, Static
from textual.worker import WorkerCancelled, WorkerFailed

from ucagent.tui.widgets.task_panel import TaskPanel


class _TaskApp(App):
    """Mount the task panel with a command input and a controlled API."""

    task_width = reactive(40)

    def __init__(self, scan):
        """Supply only the APIs consumed by the task panel."""
        super().__init__()
        self.daemon_cmds = {}
        self.vpdb = Mock()
        self.vpdb.api_task_list.return_value = {"mission_name": "Test"}
        self.vpdb.api_mission_info.return_value = ["Test", "step"]
        self.vpdb.api_tool_status.return_value = []
        self.vpdb.api_status.return_value = "idle"
        self.vpdb.api_changed_files = scan

    def compose(self) -> ComposeResult:
        """Expose an input to check event processing during a slow scan."""
        yield TaskPanel()
        yield Input(id="command")


@pytest.mark.asyncio
@pytest.mark.parametrize("remove_panel", [False, True])
async def test_slow_scan_keeps_input_responsive_and_does_not_overlap(remove_panel):
    """Timer ticks keep processing input without launching duplicate scans."""
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    scan_threads = []

    def scan():
        """Hold a filesystem call until the UI has handled input."""
        scan_threads.append(threading.get_ident())
        started.set()
        try:
            if not release.wait(5):
                raise TimeoutError("UI did not release the scan")
            return [(0, 1700000000, f"report-{i}.md") for i in range(7)]
        finally:
            finished.set()

    app = _TaskApp(scan)
    try:
        async with app.run_test() as pilot:
            assert await asyncio.to_thread(started.wait, 2)
            assert len(scan_threads) == 1
            assert scan_threads[0] != threading.get_ident()
            panel = app.query_one(TaskPanel)
            worker = panel._changed_files_worker
            for _ in range(3):
                panel.update_content()
            app.query_one(Input).focus()
            await pilot.press("x")
            assert app.query_one(Input).value == "x"
            assert len(scan_threads) == 1
            assert panel._changed_files_worker is worker

            if remove_panel:
                await panel.remove()
                release.set()
                with pytest.raises(WorkerCancelled):
                    await asyncio.wait_for(worker.wait(), 2)
                assert await asyncio.to_thread(finished.wait, 2)
                return

            release.set()
            await asyncio.wait_for(worker.wait(), 2)
            content = str(panel.query_one("#changed-files", Static).content)
            assert "report-0.md" in content
            assert "report-4.md" in content
            assert "report-5.md" not in content
    finally:
        release.set()


@pytest.mark.asyncio
async def test_failed_scan_preserves_display_and_can_retry():
    """A background scan error keeps the last result and allows later refreshes."""
    scan = Mock(side_effect=[
        [(0, 1700000000, "previous.md")],
        OSError("temporary filesystem failure"),
        [(0, 1700000001, "current.md")],
    ])
    app = _TaskApp(scan)
    async with app.run_test():
        panel = app.query_one(TaskPanel)
        await asyncio.wait_for(panel._changed_files_worker.wait(), 2)
        display = panel.query_one("#changed-files", Static)
        previous = display.content
        assert "previous.md" in str(previous)

        panel.update_content()
        with pytest.raises(WorkerFailed):
            await asyncio.wait_for(panel._changed_files_worker.wait(), 2)
        assert display.content == previous

        panel.update_content()
        await asyncio.wait_for(panel._changed_files_worker.wait(), 2)
        assert "current.md" in str(display.content)
