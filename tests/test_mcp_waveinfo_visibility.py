"""Regression coverage for waveform tools in no-file-ops MCP mode."""

from types import SimpleNamespace

from ucagent.server.api_mcp import _collect_mcp_tools


def _agent():
    return SimpleNamespace(
        tool_list_base=["ReadTextFile"],
        tool_list_task=["Check"],
        tool_list_ext=["RunTestCases"],
        tool_list_waveform=["WaveInfo", "ApplyWaveInfoEvidence"],
        tool_list_file=["PathList", "EditTextFile"],
    )


def test_no_file_ops_keeps_bounded_waveform_tools_but_hides_generic_file_tools():
    tools = _collect_mcp_tools(_agent(), no_file_ops=True)

    assert tools == [
        "ReadTextFile",
        "Check",
        "RunTestCases",
        "WaveInfo",
        "ApplyWaveInfoEvidence",
    ]


def test_regular_mcp_mode_exposes_waveform_and_file_tools():
    tools = _collect_mcp_tools(_agent(), no_file_ops=False)

    assert tools == [
        "ReadTextFile",
        "Check",
        "RunTestCases",
        "WaveInfo",
        "ApplyWaveInfoEvidence",
        "PathList",
        "EditTextFile",
    ]
