"""Focused tests for the RTL2Spec UCAgent plugin descriptor."""

from dataclasses import replace
from pathlib import Path
import shutil
import subprocess
import tomllib

import pytest

from rtl2spec.plugin import get_plugin
from rtl2spec.checkers import RTL2SpecArtifactsChecker
from rtl2spec.tools import RTL2SpecCommand, create_tools
from ucagent.plugins import (
    LoadedPlugin,
    PluginContext,
    PluginError,
    collect_plugin_resources,
    create_plugin_checker_registry,
    create_plugin_tools,
    resolve_plugin_workflow,
    validate_plugin,
)
from ucagent.tools.uctool import to_fastmcp
from ucagent.util.functions import get_tools_from_cfg


def test_plugin_descriptor_validates() -> None:
    """The plugin exposes an in-repository workflow and all declared resources."""
    plugin = validate_plugin(get_plugin(), check_dependencies=False)
    assert plugin.name == "rtl2spec"
    assert plugin.workflows[0].name == "design-document"
    assert plugin.workflows[0].config_file.is_file()
    assert all(path.exists() for path in plugin.workflows[0].guide_doc_paths)
    assert plugin.workflows[0].template_dir is None
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    manifest = tomllib.loads((root / "ucagent-plugin.toml").read_text())
    assert (root / manifest["python_path"] / "rtl2spec/plugin.py").is_file()
    assert plugin.version == project["version"]
    assert plugin.name == manifest["name"]
    assert project["entry-points"]["ucagent.plugins"][plugin.name] == manifest["entry"]
    assert f"UCAgent{plugin.requires_ucagent}" in project["dependencies"]
    assert set(plugin.python_requirements) <= set(project["dependencies"])


def test_command_rejects_shell_like_arguments(tmp_path: Path) -> None:
    """The command tool rejects invalid identifiers before starting any command."""
    tool = RTL2SpecCommand(workspace=str(tmp_path))
    result = tool._run("preflight", "Sbuffer;touch-pwned")
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_ARGUMENTS"
    assert not (tmp_path / "pwned").exists()


@pytest.mark.parametrize(
    "version,compatible",
    [("0.9.1", False), ("26.9.2.dev13", False), ("26.9.2.dev14", True)],
)
def test_ucagent_compatibility_matches_verified_baseline(monkeypatch, version, compatible):
    """Reject unverified old cores while allowing the declared tested baseline."""
    monkeypatch.setattr("ucagent.plugins.__version__", version)
    if compatible:
        validate_plugin(get_plugin(), check_dependencies=False)
    else:
        with pytest.raises(PluginError, match="requires UCAgent"):
            validate_plugin(get_plugin(), check_dependencies=False)


def test_command_has_mcp_convertible_pydantic_schema(tmp_path: Path) -> None:
    """The plugin tool exposes the BaseModel schema required by MCP conversion."""
    mcp_tool = to_fastmcp(RTL2SpecCommand(workspace=str(tmp_path)))
    schema = mcp_tool.parameters
    assert "action" in schema["properties"]
    assert schema["additionalProperties"] is False


def test_parser_dependency_is_declared_and_diagnosed(monkeypatch):
    """Missing parser metadata yields the same actionable dependency gate as installed plugins."""
    import importlib.metadata

    real_version = importlib.metadata.version

    def installed_version(name):
        """Simulate only the parser distribution being unavailable."""
        if name == "markdown-it-py":
            raise importlib.metadata.PackageNotFoundError(name)
        return real_version(name)

    monkeypatch.setattr(importlib.metadata, "version", installed_version)
    with pytest.raises(PluginError, match="requires Python package markdown-it-py"):
        validate_plugin(get_plugin(), check_dependencies=True)


@pytest.mark.parametrize(
    "command,label",
    [("bash", "Bash"), ("git", "Git"), ("curl", "Curl"), ("make", "GNU Make")],
)
def test_missing_host_command_fails_at_activation(monkeypatch, command, label):
    """Diagnose each missing host prerequisite before the workflow starts."""
    real_which = shutil.which

    def available(name):
        """Hide only the command under test without changing the actual environment."""
        return None if name == command else real_which(name)

    monkeypatch.setattr("ucagent.plugins.shutil.which", available)
    with pytest.raises(PluginError, match=f"requires command {label}: {command}"):
        validate_plugin(get_plugin(), check_dependencies=True)


def test_factory_preserves_resolved_workspace_policy(tmp_path):
    """The registered tool factory must enforce the policy supplied by UCAgent."""
    context = PluginContext(
        workspace=tmp_path,
        output_dir="outputs/Sbuffer",
        write_dirs=("outputs/Sbuffer",),
        un_write_dirs=(".cache",),
        cfg=None,
        plugin_root=get_plugin().root,
    )
    (tool,) = create_tools(context)
    assert tool.workspace == str(tmp_path)
    assert tool.write_dirs == list(context.write_dirs)
    assert tool.un_write_dirs == list(context.un_write_dirs)
    assert tool._run("preflight", "Sbuffer")["error_code"] == "WRITE_POLICY_DENIED"


@pytest.mark.parametrize("failure", ["exit", "empty", "timeout"])
def test_broken_command_version_fails_at_activation(monkeypatch, failure):
    """An executable without a working version probe is rejected before use."""
    real_run = subprocess.run

    def probe(args, **kwargs):
        """Break only the Git version probe, preserving other command checks."""
        if Path(args[0]).name == "git" and args[1:] == ["--version"]:
            if failure == "timeout":
                raise subprocess.TimeoutExpired(args, 10)
            return subprocess.CompletedProcess(args, 1 if failure == "exit" else 0, "", "")
        return real_run(args, **kwargs)

    monkeypatch.setattr("ucagent.plugins.subprocess.run", probe)
    with pytest.raises(PluginError, match="(query Git version|working Git version command)"):
        validate_plugin(get_plugin(), check_dependencies=True)


@pytest.mark.parametrize(
    "policy,expected",
    [
        ({"selected_tools": ["RTL2SpecCommand"]}, ["RTL2SpecCommand"]),
        ({"selected_tools": ["ReadTextFile"]}, []),
        ({"ignore_tools": ["RTL2Spec*"]}, []),
        ({"selected_tools": ["RTL2SpecCommand"], "ignore_tools": ["RTL2Spec*"]}, []),
    ],
)
def test_registered_tool_obeys_agent_and_mcp_filters(tmp_path, policy, expected):
    """The factory's tool respects selection and ignore precedence before MCP export."""
    plugin = get_plugin()
    loaded = LoadedPlugin(plugin, plugin.name, "test")
    context = PluginContext(tmp_path, "outputs", ("outputs",), (), None, plugin.root)
    tools = get_tools_from_cfg(create_plugin_tools([loaded], context), policy)
    assert [tool.name for tool in tools] == expected
    assert [to_fastmcp(tool).name for tool in tools] == expected


def test_checker_registration_rejects_conflicts_without_global_mutation(monkeypatch):
    """Short names resolve locally and reject both plugin and core collisions."""
    import ucagent.checkers as core_checkers

    plugin = get_plugin()
    loaded = LoadedPlugin(plugin, plugin.name, "test")
    name = "RTL2SpecArtifactsChecker"
    assert not hasattr(core_checkers, name)
    assert create_plugin_checker_registry([loaded]) == {name: RTL2SpecArtifactsChecker}
    assert not hasattr(core_checkers, name)
    other = LoadedPlugin(replace(plugin, name="another-plugin"), "another-plugin", "test")
    with pytest.raises(PluginError, match="Duplicate plugin Checker name"):
        create_plugin_checker_registry([loaded, other])
    monkeypatch.setattr(core_checkers, name, RTL2SpecArtifactsChecker, raising=False)
    with pytest.raises(PluginError, match="conflicts with a core Checker"):
        create_plugin_checker_registry([loaded])


def test_workflow_resources_are_opt_in():
    """Using plugin tools or checkers alone must not activate the document workflow."""
    plugin = validate_plugin(get_plugin(), check_dependencies=False)
    loaded = LoadedPlugin(plugin, plugin.name, "test")
    assert collect_plugin_resources([loaded], None) == ([], [])
    selected = resolve_plugin_workflow([loaded], f"{plugin.name}:design-document")
    docs, skills = collect_plugin_resources([loaded], selected)
    assert docs == list(plugin.workflows[0].guide_doc_paths)
    assert skills == []
    assert create_plugin_checker_registry([loaded])["RTL2SpecArtifactsChecker"] is RTL2SpecArtifactsChecker
