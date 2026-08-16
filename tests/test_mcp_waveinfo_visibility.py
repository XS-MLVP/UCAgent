"""Regression coverage for WaveInfo exposure through no-file-ops MCP mode."""

from types import SimpleNamespace

from ucagent.server.api_mcp import _collect_mcp_tools


def _agent():
    return SimpleNamespace(
        tool_list_base=["ReadTextFile"],
        tool_list_task=["Check"],
        tool_list_ext=["RunTestCases"],
        tool_list_waveform=["WaveInfo"],
        tool_list_file=["PathList", "EditTextFile"],
    )


def test_no_file_ops_keeps_waveinfo_but_hides_generic_file_tools():
    tools = _collect_mcp_tools(_agent(), no_file_ops=True)

    assert tools == ["ReadTextFile", "Check", "RunTestCases", "WaveInfo"]


def test_regular_mcp_mode_exposes_waveinfo_and_file_tools():
    tools = _collect_mcp_tools(_agent(), no_file_ops=False)

    assert tools == [
        "ReadTextFile",
        "Check",
        "RunTestCases",
        "WaveInfo",
        "PathList",
        "EditTextFile",
    ]
