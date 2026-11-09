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

from ucagent.interfaces.terminal.tui.app import VerifyApp
from ucagent.interfaces.terminal.tui.widgets.console import ConsoleEntry, ConsoleWidget, ConsoleWidgetState
from ucagent.interfaces.terminal.tui.widgets.console_input import ConsoleInput
from ucagent.interfaces.terminal.tui.widgets.messages_panel import MessagesPanel
from ucagent.interfaces.terminal.tui.widgets.status_bar import StatusBar


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


from test_console_runtime import console


class TestVerifyAppPersistence:
    @pytest.mark.asyncio
    async def test_status_bar_displays_langchain_token_speed(self, console):
        console.agent.status_info = lambda: {
            "Run Time": "1s",
            "LLM": "test-model",
            "Token Speed": "12.35 tok/s",
            "Idle": "8.77 s",
            "Stream": True,
            "Interaction Mode": "test",
        }

        app = VerifyApp(console)
        async with app.run_test():
            status_bar = app.query_one("#status-bar", StatusBar)
            status_bar.update_content()

            assert "Speed: 12.35 tok/s" in status_bar._raw_text
            assert "Idle: 8.77 s" in status_bar._raw_text

    @pytest.mark.asyncio
    async def test_status_bar_keeps_zero_speed_and_idle_placeholders(self, console):

        app = VerifyApp(console)
        async with app.run_test():
            status_bar = app.query_one("#status-bar", StatusBar)
            status_bar.update_content()

            assert "Speed: 0.00 tok/s" in status_bar._raw_text
            assert "Idle: 0.00 s" in status_bar._raw_text

    @pytest.mark.asyncio
    async def test_cleanup_saves_and_next_app_restores_messages(self, console):

        app = VerifyApp(console)
        async with app.run_test() as pilot:
            app.message_echo("hello")
            app.message_echo(" world", end="")
            app.message_echo("!", end="\n")
            await pilot.pause(0.2)
            app.cleanup()

        assert console.tui_messages_state is not None
        assert [text.plain for text in console.tui_messages_state.render_history] == [
            "hello",
            " world!",
        ]

        restored_app = VerifyApp(console)
        async with restored_app.run_test() as pilot:
            panel = restored_app.query_one("#messages-panel", MessagesPanel)
            await pilot.pause(0.1)

            assert [text.plain for text in panel._render_history] == ["hello", " world!"]

    @pytest.mark.asyncio
    async def test_cleanup_saves_and_next_app_restores_console(self, console):

        app = VerifyApp(console)
        async with app.run_test() as pilot:
            widget = app.query_one("#console", ConsoleWidget)
            widget.echo_command("status")
            widget.append_output("line1\nline2\n")
            app.cleanup()

        assert console.tui_console_state is not None
        assert [(entry.kind, entry.payload) for entry in console.tui_console_state.entries] == [
            ("command", "status"),
            ("output", "line1\nline2\n"),
        ]

        restored_app = VerifyApp(console)
        async with restored_app.run_test() as pilot:
            widget = restored_app.query_one("#console", ConsoleWidget)
            await pilot.pause(0.1)

            assert [(entry.kind, entry.payload) for entry in widget._entries] == [
                ("command", "status"),
                ("output", "line1\nline2\n"),
            ]
            assert widget.output_line_count() > 0

    @pytest.mark.asyncio
    async def test_restored_app_shows_shared_pdb_console_history(self, console):
        console.record_console_command("status")
        console.record_console_output("line1\nline2\n")

        restored_app = VerifyApp(console)
        async with restored_app.run_test() as pilot:
            widget = restored_app.query_one("#console", ConsoleWidget)
            await pilot.pause(0.1)

            assert [(entry.kind, entry.payload) for entry in widget._entries] == [
                ("command", "status"),
                ("output", "line1\nline2\n"),
            ]

    @pytest.mark.asyncio
    async def test_cleanup_replays_only_new_console_entries(self, console):
        console.record_console_command("before")
        console.record_console_output("old output\n")

        app = VerifyApp(console)
        async with app.run_test():
            widget = app.query_one("#console", ConsoleWidget)
            widget.echo_command("status")
            widget.append_output("line1\nline2\n")
            app.cleanup()

        assert app.session_output == "> status\nline1\nline2\n"

    @pytest.mark.asyncio
    async def test_cleanup_saves_and_next_app_restores_command_history(self, console):

        app = VerifyApp(console)
        async with app.run_test() as pilot:
            app.key_handler._add_to_history("status")
            app.key_handler._add_to_history("next")
            app.cleanup()

        assert console.get_cmd_history() == ["status", "next"]
        assert console._history_file.is_file()

        restored_app = VerifyApp(console)
        async with restored_app.run_test() as pilot:
            console_input = restored_app.query_one(ConsoleInput)
            console_input._handle_history_up()
            await pilot.pause(0.1)

            input_widget = restored_app.query_one("#console-input", Input)
            assert restored_app.cmd_history == ["status", "next"]
            assert restored_app.key_handler.last_cmd == "next"
            assert input_widget.value == "next"

    @pytest.mark.asyncio
    async def test_restored_app_renders_persistent_running_commands(self, console):
        console.execute_line("sleep 10")
        console.execute_line("sleep 10")

        restored_app = VerifyApp(console)
        async with restored_app.run_test() as pilot:
            await pilot.pause(0.1)

            console_input = restored_app.query_one(ConsoleInput)
            loading = restored_app.query_one("#console-loading")
            running = restored_app.query_one("#running-commands")

            assert console_input.is_busy is True
            assert console_input._has_running_commands is True
            assert loading.styles.display == "block"
            assert running.styles.display == "block"
            assert str(running.render()) == "[1] sleep 10 [2] sleep 10"

    @pytest.mark.asyncio
    async def test_cancel_running_command_logs_sigint_message(self, console):
        """Cancellation must render and persist its notice before returning."""
        operation = console.execute_line("sleep 10").data

        app = VerifyApp(console)
        async with app.run_test():
            assert app.cancel_running_command() is True

            widget = app.query_one("#console", ConsoleWidget)
            notice = "Cancellation requested.\n"
            assert [(entry.kind, entry.payload) for entry in widget._entries] == [
                ("output", notice)
            ]
            assert console.host.operations.wait(operation["id"], 2)["state"] == "cancelled"
            assert console.render_console_entries_since() == notice

    @pytest.mark.asyncio
    @pytest.mark.parametrize("capture_enabled", [True, False])
    async def test_flush_console_output_drains_pending_sources(self, console, capture_enabled):
        """Explicit flushing must drain both queues once without a timer tick."""
        app = VerifyApp(console)

        async with app.run_test():
            widget = app.query_one("#console", ConsoleWidget)
            app.console_output("queued output\n")
            if capture_enabled:
                print("captured output")

            app.flush_console_output()
            app.flush_console_output()

            expected = "queued output\n"
            if capture_enabled:
                expected += "captured output\n"
            assert [(entry.kind, entry.payload) for entry in widget._entries] == [
                ("output", expected)
            ]
            persisted = console.render_console_entries_since()
            assert persisted.count("queued output\n") == 1
            assert persisted.count("captured output\n") == int(capture_enabled)
            assert widget._batch_queue.empty()

            widget._tick()
            assert widget._entries[0].payload == expected
            assert console.render_console_entries_since() == persisted

    @pytest.mark.asyncio
    async def test_cancel_without_running_command_leaves_console_unchanged(self, console):
        """An idle cancellation must not log a misleading interruption notice."""
        app = VerifyApp(console)

        async with app.run_test():
            assert app.cancel_running_command() is False
            app.flush_console_output()

            widget = app.query_one("#console", ConsoleWidget)
            assert widget._entries == []
            assert console.render_console_entries_since() == ""


class TestVerifyAppShutdown:
    @pytest.mark.asyncio
    async def test_action_quit_preserves_detached_commands(self, console):
        """A view exit preserves operations owned by the runtime host."""
        operation = console.execute_line("sleep 10", foreground=False).data
        app = VerifyApp(console)
        async with app.run_test():
            app.action_quit()
        assert console.host.operations.get(operation["id"])["state"] == "running"
