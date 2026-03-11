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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
