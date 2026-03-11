#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repro-only load tests for MessagesPanel hot paths.

Usage examples:
1) Fast local check (default workload):
   uv run pytest -q tests/test_messages_panel_profile_repro.py

2) Reproduce heavy no-newline stream:
   UCA_TUI_PROFILE_CHUNKS=1200 \
   UCA_TUI_PROFILE_CHUNK_SIZE=512 \
   uv run pytest -q \
   tests/test_messages_panel_profile_repro.py::test_profile_repro_stream_without_newline

3) Reproduce heavy one-shot flush:
   UCA_TUI_PROFILE_LINES=8000 \
   UCA_TUI_PROFILE_LINE_SIZE=180 \
   uv run pytest -q \
   tests/test_messages_panel_profile_repro.py::test_profile_repro_massive_single_flush
"""

import os
import sys

import pytest
from textual.app import App

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.tui.widgets.messages_panel import MessagesPanel


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


@pytest.mark.asyncio
async def test_profile_repro_stream_without_newline():
    """Hot path repro: repeated flush while current line never gets finalized."""

    class TestApp(App):
        def compose(self):
            yield MessagesPanel(id="messages-panel")

    chunks = _int_env("UCA_TUI_PROFILE_CHUNKS", 200)
    chunk_size = _int_env("UCA_TUI_PROFILE_CHUNK_SIZE", 512)
    chunk = "x" * chunk_size

    app = TestApp()
    async with app.run_test() as pilot:
        panel = app.query_one("#messages-panel", MessagesPanel)
        for _ in range(chunks):
            panel.append_message(chunk)
            panel._flush_batch()

        assert len(panel._render_history) == 0
        assert len(panel._current_line_buffer) == chunks * chunk_size
        assert len(panel._pending_strips) > 0


@pytest.mark.asyncio
async def test_profile_repro_massive_single_flush():
    """Hot path repro: one flush that processes a large queued payload."""

    class TestApp(App):
        def compose(self):
            yield MessagesPanel(id="messages-panel")

    lines = _int_env("UCA_TUI_PROFILE_LINES", 3000)
    line_size = _int_env("UCA_TUI_PROFILE_LINE_SIZE", 120)
    line = ("y" * line_size) + "\n"

    app = TestApp()
    async with app.run_test() as pilot:
        panel = app.query_one("#messages-panel", MessagesPanel)
        panel.max_batch_items_per_flush = 10**9
        panel.max_batch_chars_per_flush = 10**9

        for _ in range(lines):
            panel.append_message(line)

        panel._flush_batch()

        assert len(panel._render_history) == min(lines, panel.max_messages)
        assert panel._batch_queue.empty()
