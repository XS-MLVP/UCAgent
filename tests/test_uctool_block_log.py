"""Focused UCTool blocking-wait heartbeat tests: interval clamping and limits."""

import asyncio
import os
import re
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import ucagent.util.functions as fc
from ucagent.tools.uctool import UCTool
from ucagent.util.config import load_yaml_with_env_vars
from ucagent.verify_agent import VerifyAgent


class _IdleTool(UCTool):
    """Minimal streaming tool whose queue never produces an item."""

    name: str = "IdleTool"
    description: str = "Stay blocking without streaming data."

    def _run(self):
        return "unused"


_BLOCKING_RE = re.compile(r"is blocking, wait (\d+)/(\d+) seconds")


def _instant_sleep():
    """Return an awaitable no-op replacing asyncio.sleep for fast ticks."""

    async def _sleep(_delay):
        return None

    return _sleep


def _run_idle_loop(tool: _IdleTool, timeout: int, logs: list[str]) -> None:
    """Run one alive loop to exhaustion with instantaneous ticks."""

    tool.is_in_streaming = True
    asyncio.run(tool._UCTool__async_alive_loop(timeout, ctx=None))
    assert tool.force_exit is True
    assert any("call timed out" in line for line in logs)


def _remaining_values(logs: list[str]) -> list[int]:
    """Extract the reported remaining seconds from blocking notices."""

    return [
        int(match.group(1))
        for match in (_BLOCKING_RE.search(line) for line in logs)
        if match
    ]


def test_block_log_spread_over_long_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 36020s wait logs at most block_log_count lines at an even interval."""

    tool = _IdleTool()
    assert tool.block_log_count == 100
    assert tool.block_log_min_interval == 10
    assert tool.block_log_max_interval == 0
    logs: list[str] = []
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep())
    monkeypatch.setattr(fc, "info", logs.append)

    _run_idle_loop(tool, 36020, logs)

    remaining = _remaining_values(logs)
    # interval = 36020 // 100 = 360s, inside [min 10s, unlimited]; the notice
    # text reports the pre-tick remaining count, hence the +1.
    assert remaining[0] == 36020 - 360 + 1
    assert all(
        before - after == 360 for before, after in zip(remaining, remaining[1:])
    )
    assert len(remaining) == 100


def test_block_log_min_interval_defaults_to_ten_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A short timeout does not log faster than the default 10s floor."""

    tool = _IdleTool()
    logs: list[str] = []
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep())
    monkeypatch.setattr(fc, "info", logs.append)

    _run_idle_loop(tool, 60, logs)

    remaining = _remaining_values(logs)
    # 60s is an exact multiple of the 10s interval, so the final tick logs too.
    assert remaining == [51, 41, 31, 21, 11, 1]


def test_block_log_min_interval_can_restore_one_second_ticks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """set_block_log_intervals(1) restores one notice per second."""

    tool = _IdleTool()
    tool.set_block_log_intervals(1, 0)
    logs: list[str] = []
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep())
    monkeypatch.setattr(fc, "info", logs.append)

    _run_idle_loop(tool, 20, logs)

    assert _remaining_values(logs) == list(range(20, 0, -1))


def test_block_log_max_interval_caps_the_wait_notice_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured max interval caps notices even below the count spread."""

    unlimited = _IdleTool(block_log_count=10)
    capped = _IdleTool(block_log_count=10)
    capped.set_block_log_intervals(10, 1800)
    unlimited_logs: list[str] = []
    capped_logs: list[str] = []
    sleep = _instant_sleep()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(fc, "info", lambda _msg: unlimited_logs.append(_msg))

    # count=10 over 200000s spreads to 20000s; the cap pulls it to 1800s.
    _run_idle_loop(unlimited, 200000, unlimited_logs)
    monkeypatch.setattr(fc, "info", capped_logs.append)
    _run_idle_loop(capped, 200000, capped_logs)

    unlimited_remaining = _remaining_values(unlimited_logs)
    capped_remaining = _remaining_values(capped_logs)
    assert all(
        before - after == 20000
        for before, after in zip(unlimited_remaining, unlimited_remaining[1:])
    )
    assert all(
        before - after == 1800
        for before, after in zip(capped_remaining, capped_remaining[1:])
    )
    assert len(capped_remaining) > len(unlimited_remaining)


def test_setting_yaml_exposes_block_log_settings() -> None:
    """The global defaults ship in setting.yaml and parse to integers."""

    setting_path = os.path.join(
        os.path.dirname(__file__), "..", "ucagent", "setting.yaml"
    )
    data = load_yaml_with_env_vars(setting_path)
    assert data["tool_block_log_count"] == 100
    assert data["tool_block_log_min_interval"] == 10
    assert data["tool_block_log_max_interval"] == 0


def test_agent_block_log_interval_validation() -> None:
    """Invalid interval combinations are rejected before reaching tools."""

    tool = _IdleTool()
    agent = SimpleNamespace(test_tools=[tool])
    VerifyAgent.set_tool_block_log_intervals(agent, 30, 1800)
    assert tool.block_log_min_interval == 30
    assert tool.block_log_max_interval == 1800
    VerifyAgent.set_tool_block_log_intervals(agent, 30, 0)
    assert tool.block_log_max_interval == 0
    with pytest.raises(ValueError, match="min interval"):
        VerifyAgent.set_tool_block_log_intervals(agent, 0, 100)
    with pytest.raises(ValueError, match="max interval"):
        VerifyAgent.set_tool_block_log_intervals(agent, 30, 20)
    with pytest.raises(ValueError, match="max interval"):
        VerifyAgent.set_tool_block_log_intervals(agent, 30, -1)
