#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test cases for MessagesPanel widget."""

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

import pytest
from rich.text import Text
from textual.app import App
from textual.worker import WorkerState
from textual.widgets import Input

from ucagent.tui.app import VerifyApp
from ucagent.tui.widgets.console import ConsoleEntry, ConsoleWidget, ConsoleWidgetState
from ucagent.tui.widgets.console_input import ConsoleInput
from ucagent.tui.widgets.messages_panel import MessagesPanel


class TestMessagesPanelPayloadProcessing:
    """Tests for inline append logic via _process_payload."""

    @pytest.mark.asyncio
    async def test_inline_append_no_newline(self):
        """Test appending segments without newline."""

        class TestApp(App):
            def compose(self):
                yield MessagesPanel(id="messages-panel")

        app = TestApp()
        async with app.run_test() as pilot:
            panel = app.query_one("#messages-panel", MessagesPanel)

            panel._process_payload("hello")
            assert panel._current_line_buffer == "hello"
            assert len(panel._lines) == 0

            panel._process_payload(" world")
            assert panel._current_line_buffer == "hello world"
            assert len(panel._lines) == 0

    @pytest.mark.asyncio
    async def test_single_newline_finalizes_line(self):
        """Test that newline finalizes current buffer."""

        class TestApp(App):
            def compose(self):
                yield MessagesPanel(id="messages-panel")

        app = TestApp()
        async with app.run_test() as pilot:
            panel = app.query_one("#messages-panel", MessagesPanel)

            panel._process_payload("hello\n")
            assert panel._current_line_buffer == ""
            assert len(panel._lines) > 0
            assert len(panel._render_history) == 1
            assert panel._render_history[0].plain == "hello"

    @pytest.mark.asyncio
    async def test_multiple_newlines(self):
        """Test multiple newlines finalize multiple lines."""

        class TestApp(App):
            def compose(self):
                yield MessagesPanel(id="messages-panel")

        app = TestApp()
        async with app.run_test() as pilot:
            panel = app.query_one("#messages-panel", MessagesPanel)

            panel._process_payload("line1\nline2\nline3\n")
            assert panel._current_line_buffer == ""
            assert len(panel._render_history) == 3
            assert panel._render_history[0].plain == "line1"
            assert panel._render_history[1].plain == "line2"
            assert panel._render_history[2].plain == "line3"

    @pytest.mark.asyncio
    async def test_partial_line_with_newlines(self):
        """Test payload with newlines and trailing content."""

        class TestApp(App):
            def compose(self):
                yield MessagesPanel(id="messages-panel")

        app = TestApp()
        async with app.run_test() as pilot:
            panel = app.query_one("#messages-panel", MessagesPanel)

            panel._process_payload("a\nb\nc")
            assert panel._current_line_buffer == "c"
            assert len(panel._render_history) == 2
            assert panel._render_history[0].plain == "a"
            assert panel._render_history[1].plain == "b"

    @pytest.mark.asyncio
    async def test_ansi_preservation(self):
        """Test ANSI codes are preserved in render history."""

        class TestApp(App):
            def compose(self):
                yield MessagesPanel(id="messages-panel")

        app = TestApp()
        async with app.run_test() as pilot:
            panel = app.query_one("#messages-panel", MessagesPanel)

            ansi_text = "\033[31mred\033[0m text\n"
            panel._process_payload(ansi_text)

            assert len(panel._render_history) == 1
            rendered = panel._render_history[0]
            assert isinstance(rendered, Text)
            assert rendered.plain == "red text"
            assert len(rendered.spans) > 0

    @pytest.mark.asyncio
    async def test_empty_payload(self):
        """Test empty payload is a no-op."""

        class TestApp(App):
            def compose(self):
                yield MessagesPanel(id="messages-panel")

        app = TestApp()
        async with app.run_test() as pilot:
            panel = app.query_one("#messages-panel", MessagesPanel)

            panel._process_payload("")
            assert panel._current_line_buffer == ""
            assert len(panel._lines) == 0
            assert len(panel._render_history) == 0

    @pytest.mark.asyncio
    async def test_only_newlines(self):
        """Test payload with only newlines."""

        class TestApp(App):
            def compose(self):
                yield MessagesPanel(id="messages-panel")

        app = TestApp()
        async with app.run_test() as pilot:
            panel = app.query_one("#messages-panel", MessagesPanel)

            panel._process_payload("\n\n\n")
            assert panel._current_line_buffer == ""
            assert len(panel._render_history) == 3
            assert len(panel._lines) == 3

    @pytest.mark.asyncio
    async def test_rapid_sequential_appends(self):
        """Test multiple appends without newlines accumulate."""

        class TestApp(App):
            def compose(self):
                yield MessagesPanel(id="messages-panel")

        app = TestApp()
        async with app.run_test() as pilot:
            panel = app.query_one("#messages-panel", MessagesPanel)

            panel._process_payload("a")
            panel._process_payload("b")
            panel._process_payload("c")
            assert panel._current_line_buffer == "abc"
            assert len(panel._lines) == 0

            panel._process_payload("\n")
            assert panel._current_line_buffer == ""
            assert len(panel._render_history) == 1
            assert panel._render_history[0].plain == "abc"


class TestSoftWrap:
    """Tests for _soft_wrap_text static method."""

    def test_soft_wrap_no_wrap_needed(self):
        """Test text that fits within width."""
        text = Text("hello")
        wrapped = MessagesPanel._soft_wrap_text(text, 10)
        assert len(wrapped) == 1
        assert wrapped[0].plain == "hello"

    def test_soft_wrap_simple_wrap(self):
        """Test text that needs wrapping."""
        text = Text("hello world")
        wrapped = MessagesPanel._soft_wrap_text(text, 5)
        # Should wrap at character boundaries
        assert len(wrapped) > 1, "Text should be wrapped"
        # Reassemble to verify content preservation
        reassembled = "".join(w.plain for w in wrapped)
        assert reassembled == "hello world"

    def test_soft_wrap_cjk_text(self):
        """Test wrapping CJK text respects display width."""
        text = Text("中文测试")  # 4 chars, 8 display width
        wrapped = MessagesPanel._soft_wrap_text(text, 5)
        # Each CJK char is 2 width, so max 2 chars per line
        assert len(wrapped) >= 2, "CJK text should wrap based on display width"
        # Verify content preserved
        reassembled = "".join(w.plain for w in wrapped)
        assert reassembled == "中文测试"

    def test_soft_wrap_minimum_width(self):
        """Test soft wrap with width <= 1."""
        text = Text("hello")
        wrapped = MessagesPanel._soft_wrap_text(text, 1)
        # Width <= 1 should return text as-is
        assert len(wrapped) == 1
        assert wrapped[0].plain == "hello"


class TestBatchQueue:
    """Tests for thread-safe append_message → queue behavior."""

    @pytest.mark.asyncio
    async def test_append_message_queues_without_modifying_lines(self):
        """Test append_message puts into queue without immediate line modification."""

        class TestApp(App):
            def compose(self):
                yield MessagesPanel(id="messages-panel")

        app = TestApp()
        async with app.run_test() as pilot:
            panel = app.query_one("#messages-panel", MessagesPanel)

            initial_line_count = len(panel._lines)
            panel.append_message("test")

            assert len(panel._lines) == initial_line_count
            assert not panel._batch_queue.empty()

    @pytest.mark.asyncio
    async def test_batch_flush_processes_queue(self):
        """Test _flush_batch drains queue and processes messages."""

        class TestApp(App):
            def compose(self):
                yield MessagesPanel(id="messages-panel")

        app = TestApp()
        async with app.run_test() as pilot:
            panel = app.query_one("#messages-panel", MessagesPanel)

            panel.append_message("test1\n")
            panel.append_message("test2\n")

            panel._flush_batch()

            assert panel._batch_queue.empty()
            assert len(panel._render_history) == 2
            assert panel._render_history[0].plain == "test1"
            assert panel._render_history[1].plain == "test2"

    @pytest.mark.asyncio
    async def test_empty_message_ignored(self):
        """Test empty message is not queued."""

        class TestApp(App):
            def compose(self):
                yield MessagesPanel(id="messages-panel")

        app = TestApp()
        async with app.run_test() as pilot:
            panel = app.query_one("#messages-panel", MessagesPanel)

            panel.append_message("")
            assert panel._batch_queue.empty()


class TestIntegration:
    """Tests requiring a running Textual app."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_with_auto_flush(self):
        """Test full lifecycle: mount → queue → flush → render."""

        class TestApp(App):
            def compose(self):
                yield MessagesPanel(id="messages-panel")

        app = TestApp()
        async with app.run_test() as pilot:
            panel = app.query_one("#messages-panel", MessagesPanel)

            # Append message
            panel.append_message("hello\n")

            # Wait for batch flush interval (0.2s)
            await pilot.pause(0.3)

            # Verify content rendered
            assert len(panel._render_history) == 1
            assert panel._render_history[0].plain == "hello"
            assert panel._batch_queue.empty()

    @pytest.mark.asyncio
    async def test_render_line_returns_strips(self):
        """Test render_line returns valid Strip objects."""

        class TestApp(App):
            def compose(self):
                yield MessagesPanel(id="messages-panel")

        app = TestApp()
        async with app.run_test() as pilot:
            panel = app.query_one("#messages-panel", MessagesPanel)

            # Add some content
            panel._process_payload("line1\nline2\nline3\n")

            strip = panel.render_line(0)
            assert strip is not None
            assert hasattr(strip, "_segments") or hasattr(strip, "segments")

    @pytest.mark.asyncio
    async def test_clear_resets_state(self):
        """Test clear() resets all state."""

        class TestApp(App):
            def compose(self):
                yield MessagesPanel(id="messages-panel")

        app = TestApp()
        async with app.run_test() as pilot:
            panel = app.query_one("#messages-panel", MessagesPanel)

            # Add content
            panel._process_payload("test1\ntest2\n")
            assert len(panel._render_history) > 0
            assert len(panel._lines) > 0

            # Clear
            panel.clear()

            # Verify reset
            assert len(panel._render_history) == 0
            assert len(panel._lines) == 0
            assert panel._current_line_buffer == ""
            assert len(panel._pending_strips) == 0
            assert panel._widest_line_width == 0

    @pytest.mark.asyncio
    async def test_inline_append_with_pending_strips(self):
        """Test incomplete line creates pending strips."""

        class TestApp(App):
            def compose(self):
                yield MessagesPanel(id="messages-panel")

        app = TestApp()
        async with app.run_test() as pilot:
            panel = app.query_one("#messages-panel", MessagesPanel)

            # Add incomplete line
            panel._process_payload("incomplete")

            # Should have pending strips but no finalized lines
            assert len(panel._pending_strips) > 0
            assert len(panel._lines) == 0

            # Finalize the line
            panel._process_payload("\n")

            # Pending strips should be cleared, line finalized
            assert len(panel._pending_strips) == 0
            assert len(panel._lines) > 0


class TestStatePersistence:
    """Tests for exporting and restoring message history state."""

    @pytest.mark.asyncio
    async def test_export_restore_preserves_render_history_and_pending_line(self):
        class TestApp(App):
            def compose(self):
                yield MessagesPanel(id="messages-panel")

        app = TestApp()
        async with app.run_test() as pilot:
            panel = app.query_one("#messages-panel", MessagesPanel)
            panel._process_payload("line1\n\033[31mline2\033[0m\npartial")

            state = panel.export_state()

            restored = MessagesPanel(id="restored-panel")
            await app.mount(restored)
            restored.restore_state(state)

            assert [text.plain for text in restored._render_history] == ["line1", "line2"]
            assert restored._current_line_buffer == "partial"
            assert len(restored._pending_strips) > 0
            assert restored._render_history[1].spans == panel._render_history[1].spans

    @pytest.mark.asyncio
    async def test_restore_then_append_continues_existing_pending_line(self):
        class TestApp(App):
            def compose(self):
                yield MessagesPanel(id="messages-panel")

        app = TestApp()
        async with app.run_test() as pilot:
            panel = app.query_one("#messages-panel", MessagesPanel)
            panel._process_payload("partial")
            state = panel.export_state()

            panel.restore_state(state)
            panel._process_payload(" line\n")

            assert [text.plain for text in panel._render_history] == ["partial line"]
            assert panel._current_line_buffer == ""


class _FakeCfg:
    def get_value(self, key, default=None):
        return default


class _FakeAgent:
    def __init__(self) -> None:
        self.cfg = _FakeCfg()
        self._handler = None
        self._mcps_logger = None
        self.break_threads = []
        self.cleared_break_threads = []

    def set_message_echo_handler(self, handler) -> None:
        self._handler = handler

    def unset_message_echo_handler(self) -> None:
        self._handler = None

    def set_break_thread(self, thread_id: int) -> None:
        self.break_threads.append(thread_id)

    def clear_break_thread(self, thread_id: int) -> None:
        self.cleared_break_threads.append(thread_id)

    def status_info(self):
        return {
            "Run Time": "0s",
            "LLM": "test-model",
            "Stream": False,
            "Interaction Mode": "test",
        }


class _FakeVPDB:
    def __init__(self) -> None:
        self.agent = _FakeAgent()
        self.prompt = "(test) "
        self.init_cmd = []
        self.stdout = None
        self.stderr = None
        self._cmd_history = []
        self._running_commands = []
        self.save_cmd_history_calls = 0
        self.tui_console_state = None
        self.tui_messages_state = None

    def get_cmd_history(self):
        return list(self._cmd_history)

    def record_cmd_history(self, cmd):
        if not self._cmd_history or self._cmd_history[-1] != cmd:
            self._cmd_history.append(cmd)

    def save_cmd_history(self):
        self.save_cmd_history_calls += 1

    def get_running_commands(self):
        return list(self._running_commands)

    def has_running_commands(self):
        return bool(self._running_commands)

    def cancel_last_running_command(self):
        if not self._running_commands:
            return False
        self._running_commands.pop()
        return True

    def request_thread_interrupt(self, _thread_id):
        self.agent.set_break_thread(_thread_id)
        return True

    def record_console_output(self, text):
        if not text:
            return
        state = self._ensure_console_state()
        if state.entries and state.entries[-1].kind == "output":
            state.entries[-1].payload += text
        else:
            state.entries.append(ConsoleEntry("output", text))

    def record_console_command(self, cmd):
        cmd = cmd.strip()
        if not cmd or cmd == "tui":
            return
        state = self._ensure_console_state()
        state.entries.append(ConsoleEntry("command", cmd))

    def clear_console_state(self):
        state = self._ensure_console_state()
        state.entries.clear()

    def get_console_entry_count(self):
        state = self.tui_console_state
        return len(state.entries) if state is not None else 0

    def render_console_entries_since(self, start_index=0):
        state = self.tui_console_state
        if state is None or not state.entries:
            return ""
        entries = state.entries if start_index <= len(state.entries) else state.entries
        if start_index <= len(state.entries):
            entries = state.entries[start_index:]

        parts = []
        for entry in entries:
            if entry.kind == "command":
                if parts and not parts[-1].endswith("\n"):
                    parts.append("\n")
                parts.append(f"> {entry.payload}\n")
            else:
                parts.append(entry.payload)
        return "".join(parts)

    def api_task_list(self):
        return {"mission_name": "Test Mission", "task_list": {}}

    def api_mission_info(self):
        return ["Mission", "step1"]

    def api_changed_files(self):
        return []

    def api_tool_status(self):
        return []

    def api_status(self):
        return "idle"

    def _ensure_console_state(self):
        if self.tui_console_state is None:
            self.tui_console_state = ConsoleWidgetState(entries=[])
        return self.tui_console_state


class _FakeWorker:
    def __init__(self) -> None:
        self.state = WorkerState.RUNNING
        self.cancel_calls = 0

    def cancel(self) -> None:
        self.cancel_calls += 1
        self.state = WorkerState.CANCELLED


class TestVerifyAppPersistence:
    @pytest.mark.asyncio
    async def test_cleanup_saves_and_next_app_restores_messages(self):
        vpdb = _FakeVPDB()

        app = VerifyApp(vpdb)
        async with app.run_test() as pilot:
            app.message_echo("hello")
            app.message_echo(" world", end="")
            app.message_echo("!", end="\n")
            await pilot.pause(0.2)
            app.cleanup()

        assert vpdb.tui_messages_state is not None
        assert [text.plain for text in vpdb.tui_messages_state.render_history] == [
            "hello",
            " world!",
        ]

        restored_app = VerifyApp(vpdb)
        async with restored_app.run_test() as pilot:
            panel = restored_app.query_one("#messages-panel", MessagesPanel)
            await pilot.pause(0.1)

            assert [text.plain for text in panel._render_history] == ["hello", " world!"]

    @pytest.mark.asyncio
    async def test_cleanup_saves_and_next_app_restores_console(self):
        vpdb = _FakeVPDB()

        app = VerifyApp(vpdb)
        async with app.run_test() as pilot:
            console = app.query_one("#console", ConsoleWidget)
            console.echo_command("status")
            console.append_output("line1\nline2\n")
            app.cleanup()

        assert vpdb.tui_console_state is not None
        assert [(entry.kind, entry.payload) for entry in vpdb.tui_console_state.entries] == [
            ("command", "status"),
            ("output", "line1\nline2\n"),
        ]

        restored_app = VerifyApp(vpdb)
        async with restored_app.run_test() as pilot:
            console = restored_app.query_one("#console", ConsoleWidget)
            await pilot.pause(0.1)

            assert [(entry.kind, entry.payload) for entry in console._entries] == [
                ("command", "status"),
                ("output", "line1\nline2\n"),
            ]
            assert console.output_line_count() > 0

    @pytest.mark.asyncio
    async def test_restored_app_shows_shared_pdb_console_history(self):
        vpdb = _FakeVPDB()
        vpdb.record_console_command("status")
        vpdb.record_console_output("line1\nline2\n")

        restored_app = VerifyApp(vpdb)
        async with restored_app.run_test() as pilot:
            console = restored_app.query_one("#console", ConsoleWidget)
            await pilot.pause(0.1)

            assert [(entry.kind, entry.payload) for entry in console._entries] == [
                ("command", "status"),
                ("output", "line1\nline2\n"),
            ]

    @pytest.mark.asyncio
    async def test_cleanup_replays_only_new_console_entries(self):
        vpdb = _FakeVPDB()
        vpdb.record_console_command("before")
        vpdb.record_console_output("old output\n")

        app = VerifyApp(vpdb)
        async with app.run_test():
            console = app.query_one("#console", ConsoleWidget)
            console.echo_command("status")
            console.append_output("line1\nline2\n")
            app.cleanup()

        assert app.session_output == "> status\nline1\nline2\n"

    @pytest.mark.asyncio
    async def test_cleanup_saves_and_next_app_restores_command_history(self):
        vpdb = _FakeVPDB()

        app = VerifyApp(vpdb)
        async with app.run_test() as pilot:
            app.key_handler._add_to_history("status")
            app.key_handler._add_to_history("next")
            app.cleanup()

        assert vpdb.get_cmd_history() == ["status", "next"]
        assert vpdb.save_cmd_history_calls >= 1

        restored_app = VerifyApp(vpdb)
        async with restored_app.run_test() as pilot:
            console_input = restored_app.query_one(ConsoleInput)
            console_input._handle_history_up()
            await pilot.pause(0.1)

            input_widget = restored_app.query_one("#console-input", Input)
            assert restored_app.cmd_history == ["status", "next"]
            assert restored_app.key_handler.last_cmd == "next"
            assert input_widget.value == "next"

    @pytest.mark.asyncio
    async def test_restored_app_renders_persistent_running_commands(self):
        vpdb = _FakeVPDB()
        vpdb._running_commands = ["loop status", "loop next"]

        restored_app = VerifyApp(vpdb)
        async with restored_app.run_test() as pilot:
            await pilot.pause(0.1)

            console_input = restored_app.query_one(ConsoleInput)
            loading = restored_app.query_one("#console-loading")
            running = restored_app.query_one("#running-commands")

            assert console_input.is_busy is True
            assert console_input._has_running_commands is True
            assert loading.styles.display == "block"
            assert running.styles.display == "block"
            assert str(running.render()) == "[1] loop status [2] loop next"

    @pytest.mark.asyncio
    async def test_cancel_running_command_logs_sigint_message(self):
        vpdb = _FakeVPDB()
        vpdb._running_commands = ["loop status"]

        app = VerifyApp(vpdb)
        async with app.run_test() as pilot:
            assert app.cancel_running_command() is True
            await pilot.pause(0.2)

            console = app.query_one("#console", ConsoleWidget)
            outputs = [
                entry.payload for entry in console._entries if entry.kind == "output"
            ]
            assert any("SIGINT received. Stopping execution ..." in text for text in outputs)


class TestVerifyAppShutdown:
    @pytest.mark.asyncio
    async def test_action_quit_preserves_detached_commands(self):
        vpdb = _FakeVPDB()
        app = VerifyApp(vpdb)
        worker = _FakeWorker()

        async with app.run_test():
            app.key_handler._active_workers.append(worker)
            app.key_handler._worker_commands[worker] = "status"
            app.key_handler._register_worker_thread(worker, 101)
            app.daemon_cmds[1.0] = "watch"

            app.action_quit()

        assert worker.cancel_calls == 1
        assert vpdb.agent.break_threads == [101]
        assert app.daemon_cmds == {1.0: "watch"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
