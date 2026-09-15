"""Regression coverage for bounded analysis tool visibility in MCP modes."""

from types import SimpleNamespace

from ucagent.server.api_mcp import _collect_mcp_tools


def _agent(ignore_tools: list[str] | None = None):
    """Build a minimal MCP agent with optional resolved tool configuration."""

    def named(name: str) -> SimpleNamespace:
        """Construct the smallest tool-shaped object accepted by configuration filters."""

        return SimpleNamespace(name=name)

    agent = SimpleNamespace(
        tool_list_base=[named("ReadTextFile")],
        tool_list_task=[named("Check")],
        tool_list_ext=[named("RunTestCases")],
        tool_list_waveform=[
            named("WaveInfo"),
            named("ApplyWaveInfoEvidence"),
            named("ReviewWaveInfoEvidenceBatch"),
        ],
        tool_list_plugin=[named("AnalyzePPA")],
        tool_list_file=[named("PathList"), named("EditTextFile")],
    )
    if ignore_tools is not None:
        agent.cfg = SimpleNamespace(
            tools={"ignore_tools": ignore_tools, "selected_tools": []}
        )
    return agent


def test_no_file_ops_keeps_bounded_waveform_tools_but_hides_generic_file_tools():
    """No-file mode must retain bounded analysis tools while removing file operations."""

    tools = _collect_mcp_tools(_agent(), no_file_ops=True)

    assert [tool.name for tool in tools] == [
        "ReadTextFile",
        "Check",
        "RunTestCases",
        "WaveInfo",
        "ApplyWaveInfoEvidence",
        "ReviewWaveInfoEvidenceBatch",
        "AnalyzePPA",
    ]


def test_regular_mcp_mode_exposes_waveform_and_file_tools():
    """Regular MCP mode must expose every unfiltered registered tool group."""

    tools = _collect_mcp_tools(_agent(), no_file_ops=False)

    assert [tool.name for tool in tools] == [
        "ReadTextFile",
        "Check",
        "RunTestCases",
        "WaveInfo",
        "ApplyWaveInfoEvidence",
        "ReviewWaveInfoEvidenceBatch",
        "AnalyzePPA",
        "PathList",
        "EditTextFile",
    ]


def test_mcp_collection_honors_plugin_tool_ignore_configuration():
    """An ignored plugin tool must not remain reachable through MCP."""

    tools = _collect_mcp_tools(
        _agent(ignore_tools=["AnalyzePPA"]), no_file_ops=False
    )

    assert "AnalyzePPA" not in [tool.name for tool in tools]
    assert "WaveInfo" in [tool.name for tool in tools]
