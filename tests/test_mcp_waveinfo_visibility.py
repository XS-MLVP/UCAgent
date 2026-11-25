"""Regression coverage for bounded analysis tool visibility in MCP modes."""

from types import SimpleNamespace
from pathlib import Path

import pytest

from ucagent.util.config import Config, load_yaml_with_env_vars

from ucagent.interfaces.server.api_mcp import _collect_mcp_tools


def _agent(ignore_tools: list[str] | None = None):
    """Build a minimal MCP agent with optional resolved tool configuration."""

    def named(name: str) -> SimpleNamespace:
        """Construct the smallest tool-shaped object accepted by configuration filters."""

        return SimpleNamespace(name=name)

    agent = SimpleNamespace(
        tool_list_base=[named("ReadTextFile")],
        tool_list_task=[named("Check")],
        tool_list_ext=[named("RunTestCases")],
        tool_list_plugin=[
            named("WaveInfo"),
            named("ApplyWaveInfoEvidence"),
            named("ReviewWaveInfoEvidenceBatch"),
            named("AnalyzePPA"),
        ],
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


@pytest.mark.parametrize("use_skill", [False, True])
def test_required_workflow_tools_checked_after_mcp_and_config_filters(use_skill):
    """No-file mode and explicit tool filters must fail before serving an unusable workflow."""

    agent = _agent()
    agent.cfg = Config({"runtime_options": {"required_mcp_tools": ["EditTextFile", "ReadTextFile"]},
                        "skill": {"use_skill": use_skill}})
    assert "EditTextFile" in {tool.name for tool in _collect_mcp_tools(agent, False)}
    with pytest.raises(ValueError, match="Required workflow MCP tools.*EditTextFile") as error:
        _collect_mcp_tools(agent, True)
    assert "--mcp-server" in str(error.value)
    for filters in ({"ignore_tools": ["Edit*"]}, {"selected_tools": ["ReadTextFile"]}):
        agent.cfg.set_value("tools", filters)
        with pytest.raises(ValueError, match="Required workflow MCP tools.*EditTextFile"):
            _collect_mcp_tools(agent, False)


def test_required_mcp_tools_rejects_invalid_types_and_names():
    """A malformed requirement must not silently disable the capability check."""

    for value in (None, True, "EditTextFile", {}, [None], [1], [""], ["  "]):
        agent = _agent()
        agent.cfg = Config({"runtime_options": {"required_mcp_tools": value}})
        with pytest.raises(ValueError, match="must be a list of nonempty tool names"):
            _collect_mcp_tools(agent, False)


def test_supervisor_endpoint_keeps_delegation_permissions():
    """Business requirements must not grant file tools to a multi-agent supervisor."""

    agent = _agent()
    agent.cfg = Config({"runtime_options": {"required_mcp_tools": ["EditTextFile"]}})
    agent.multi_agent = object()
    agent.test_tools = [SimpleNamespace(name="SubAgentTool")]
    for disabled in (False, True):
        assert [tool.name for tool in _collect_mcp_tools(agent, disabled)] == ["SubAgentTool"]


def test_unittest_workflows_declare_required_mcp_tools(monkeypatch):
    """Standalone UnitTest workflows declare file tools in both supported runtime boolean modes."""

    root = Path(__file__).parents[1] / "ucagent/plugins/UnitTest/src/unit_test/workflows"
    for enabled in ("true", "false"):
        monkeypatch.setenv("NEED_REF_MODEL", enabled)
        monkeypatch.setenv("IGNORE_MOCK_COMPONENT", enabled)
        for name in ("unittest", "incremental", "vibe"):
            cfg = load_yaml_with_env_vars(str(root / f"{name}.yaml"))
            assert cfg["runtime_options"]["required_mcp_tools"] == [
                "ReadTextFile", "EditTextFile", "ReplaceStringInFile", "DeleteTextLines",
            ]
