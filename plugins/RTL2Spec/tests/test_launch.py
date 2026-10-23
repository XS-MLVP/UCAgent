"""Exercise file-based startup without a model session or hardware toolchain."""

import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

from rtl2spec.launch import build_command, main


@pytest.mark.parametrize("profile", ["generic", "xiangshan"])
def test_bundled_config_resolves_with_the_real_cli(tmp_path, monkeypatch, profile):
    """A copied profile selects the existing workflow and overrides environment defaults."""
    from ucagent.cli import get_args
    from ucagent.util.config import get_config
    from rtl2spec.plugin import get_plugin

    config_file = tmp_path / "rtl2spec.yaml"
    assert main(["--init", profile, "--config", str(config_file)]) == 0
    monkeypatch.chdir(tmp_path.parent)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XIANGSHAN_CONFIG", "WrongConfig")
    monkeypatch.setenv("RTL2SPEC_CONFIG", "WrongConfig")
    command = build_command(config_file)
    assert command[:4] == [sys.executable, "-P", "-m", "ucagent.cli"]
    monkeypatch.setattr(sys, "argv", ["ucagent", *command[4:]])
    args = get_args()
    assert args.workspace == str(tmp_path / f"{profile}-spec-workspace")
    assert args.dut == ("GenericBlock" if profile == "generic" else "Sbuffer")
    assert args.plugin == ["rtl2spec"]
    assert args.plugin_workflow == f"rtl2spec:{profile}-design-document"
    assert args.config == str(config_file)
    assert args.output == "outputs"
    assert args.no_history and args.mcp_server_no_file_tools
    assert not Path(args.workspace).exists()
    workflow = next(item for item in get_plugin().workflows if item.name == f"{profile}-design-document")
    cfg = get_config(args.config, args.override, args.workspace, workflow_config_file=workflow.config_file)
    field = "GENERIC_CONFIG" if profile == "generic" else "XS_CONFIG"
    assert cfg.get_value(f"template_overwrite.{field}") == ("Generic" if profile == "generic" else "DefaultConfig")
    assert cfg.backend.key_name == "codex"
    assert len(cfg.stage) == 4


def test_config_preserves_agent_options_and_space_containing_paths(tmp_path, monkeypatch):
    """The exact YAML reaches UCAgent; launcher paths are independent of the current directory."""
    folder = tmp_path / "config with spaces"
    folder.mkdir()
    config_file = folder / "run.yaml"
    config_file.write_text(yaml.safe_dump({
        "rtl2spec": {"workspace": "../workspace with spaces", "module": "Top", "workflow": "generic-design-document", "output": "runs/second run"},
        "backend": {"key_name": "blank"}, "langfuse": {"enable": False},
    }))
    monkeypatch.chdir(tmp_path.parent)
    command = build_command(config_file)
    assert command[4:6] == [str(tmp_path / "workspace with spaces"), "Top"]
    assert command[command.index("--config") + 1] == str(config_file)
    assert command[command.index("--output") + 1] == "runs/second run"
    assert "--backend" not in command


@pytest.mark.parametrize("workspace", ["~/spec-workspace", "/tmp/absolute-spec-workspace"])
def test_workspace_expands_home_and_preserves_absolute_paths(tmp_path, monkeypatch, workspace):
    """User paths follow ordinary path rules without shell evaluation."""
    monkeypatch.setenv("HOME", str(tmp_path))
    config_file = tmp_path / "run.yaml"
    config_file.write_text(yaml.safe_dump({"rtl2spec": {"workspace": workspace, "module": "Top", "workflow": "generic-design-document"}}))
    assert build_command(config_file)[4] == str(Path(workspace).expanduser())


@pytest.mark.parametrize("text", [
    "", "[]", "backend: {key_name: codex}", "rtl2spec: null",
    "rtl2spec: {module: Top, workflow: generic-design-document}",
    "rtl2spec: {workspace: ., module: Top, workflow: generic-design-document, outpt: outputs}",
    "rtl2spec: {workspace: ., module: '../Top', workflow: generic-design-document}",
    "rtl2spec: {workspace: ., module: Top, workflow: wrong}",
    "rtl2spec: {workspace: 1, module: Top, workflow: generic-design-document}",
    "rtl2spec: [unclosed",
])
def test_invalid_yaml_never_starts_an_agent(tmp_path, monkeypatch, capsys, text):
    """Missing, malformed and mistyped startup settings fail before any launch."""
    config_file = tmp_path / "run.yaml"
    config_file.write_text(text)

    def unexpected_exec(*args):
        """Fail the test if invalid input reaches process replacement."""
        pytest.fail("Invalid settings must not start UCAgent")

    monkeypatch.setattr("rtl2spec.launch.os.execv", unexpected_exec)
    with pytest.raises(SystemExit) as error:
        main(["--config", str(config_file)])
    assert error.value.code == 2
    assert "rtl2spec:" in capsys.readouterr().err


@pytest.mark.parametrize("output", ["", ".", "../outside", "/tmp/outside"])
def test_output_must_stay_inside_the_workspace(tmp_path, output):
    """The configuration cannot direct generated artifacts outside the selected workspace."""
    config_file = tmp_path / "run.yaml"
    config_file.write_text(yaml.safe_dump({"rtl2spec": {"workspace": "workspace", "module": "Top", "workflow": "generic-design-document", "output": output}}))
    with pytest.raises(ValueError):
        build_command(config_file)


def test_output_symlink_cannot_escape_workspace(tmp_path):
    """Existing output symlinks are resolved before accepting a run directory."""
    workspace = tmp_path / "generic-spec-workspace"
    workspace.mkdir()
    (workspace / "outputs").symlink_to(tmp_path, target_is_directory=True)
    config_file = tmp_path / "run.yaml"
    main(["--init", "generic", "--config", str(config_file)])
    with pytest.raises(ValueError, match="escapes workspace"):
        build_command(config_file)


def test_init_never_overwrites_user_config(tmp_path):
    """Initializing a profile is exclusive, including when the destination is a symlink."""
    target = tmp_path / "saved.yaml"
    target.write_text("Preserve my configuration\n")
    link = tmp_path / "run.yaml"
    link.symlink_to(target)
    for path in (target, link):
        with pytest.raises(SystemExit) as error:
            main(["--init", "generic", "--config", str(path)])
        assert error.value.code == 2
    assert target.read_text() == "Preserve my configuration\n"


def test_dry_run_is_read_only(tmp_path, monkeypatch, capsys):
    """Preview quotes arguments for display without executing a shell or creating workspaces."""
    monkeypatch.chdir(tmp_path)
    main(["--init", "generic"])
    capsys.readouterr()
    assert main(["--dry-run"]) == 0
    command = shlex.split(capsys.readouterr().out)
    assert command == build_command(tmp_path / "rtl2spec.yaml")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["rtl2spec.yaml"]


def test_launch_uses_the_current_python_and_exact_argument_list(tmp_path, monkeypatch):
    """The child inherits the terminal and process lifecycle without a shell intermediary."""
    config_file = tmp_path / "run.yaml"
    main(["--init", "generic", "--config", str(config_file)])
    launched = []

    def record_exec(executable, command):
        """Capture process replacement without starting a model backend."""
        launched.append((executable, command))

    monkeypatch.setattr("rtl2spec.launch.os.execv", record_exec)
    assert main(["--config", str(config_file)]) == 0
    assert launched == [(sys.executable, build_command(config_file))]


def test_missing_config_is_actionable(tmp_path, capsys):
    """A missing configuration reports its path rather than silently using defaults."""
    with pytest.raises(SystemExit) as error:
        main(["--config", str(tmp_path / "absent.yaml")])
    assert error.value.code == 2
    assert "absent.yaml" in capsys.readouterr().err


def test_launcher_and_templates_are_declared_for_installation():
    """Both source and wheel installations expose the entry point and bundled profiles."""
    root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((root / "pyproject.toml").read_text())
    assert metadata["project"]["scripts"]["rtl2spec"] == "rtl2spec.launch:main"
    assert "launch_configs/*.yaml" in metadata["tool"]["setuptools"]["package-data"]["rtl2spec"]
    assert "recursive-include src/rtl2spec *.md *.json *.yaml *.sh" in (root / "MANIFEST.in").read_text()


@pytest.mark.parametrize("profile", ["generic", "xiangshan"])
def test_yaml_launch_initializes_a_real_agent(workspace, tmp_path, monkeypatch, profile):
    """Startup config reaches actual stages and tools without relying on environment defaults."""
    from conftest import RTL
    from ucagent.plugins import collect_plugin_resources, load_plugin, resolve_plugin_workflow
    from ucagent.verify_agent import VerifyAgent

    config_file = tmp_path / "rtl2spec.yaml"
    main(["--init", profile, "--config", str(config_file)])
    data = yaml.safe_load(config_file.read_text())
    data["rtl2spec"].update(workspace=str(workspace), module="Sbuffer", output="runs/from-config")
    data["backend"]["key_name"] = "blank"
    data["langfuse"] = {"enable": False}
    data["skill"] = {"use_skill": False}
    field = "GENERIC_CONFIG" if profile == "generic" else "XS_CONFIG"
    data["template_overwrite"][field] = "TestConfig"
    config_file.write_text(yaml.safe_dump(data))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XIANGSHAN_CONFIG", "WrongConfig")
    monkeypatch.setenv("RTL2SPEC_CONFIG", "WrongConfig")
    if profile == "generic":
        inputs = workspace / "inputs/Sbuffer"
        inputs.mkdir(parents=True)
        (inputs / "Sbuffer.sv").write_text(RTL)
    plugin = load_plugin(str(Path(__file__).resolve().parents[1]))
    workflow_id = f"rtl2spec:{profile}-design-document"
    selected = resolve_plugin_workflow([plugin], workflow_id)
    docs, _ = collect_plugin_resources([plugin], selected)
    command = build_command(config_file)
    agent = VerifyAgent(
        workspace=command[4], dut_name=command[5],
        output=command[command.index("--output") + 1],
        config_file=command[command.index("--config") + 1],
        no_embed_tools=True, no_history=True, plugins=[plugin],
        plugin_guide_doc_paths=[str(path) for path in docs], plugin_skill_paths=[],
        workflow_config_file=str(selected[1].config_file), plugin_workflow=workflow_id,
        template_context_factory=selected[1].template_context_factory,
    )
    try:
        assert agent.cfg.backend.key_name == "blank"
        assert not (workspace / ".ucagent/skills").exists()
        assert len(agent.stage_manager.stages) == 4
        assert "WrongConfig" not in agent.get_default_system_prompt()
        assert "TestConfig" in agent.get_default_system_prompt()
        tool = next(item for item in agent.test_tools if item.name == "RTL2SpecCommand")
        assert tool.output_dir == "runs/from-config"
        action = "generic_evidence" if profile == "generic" else "evidence"
        result = tool._run(action, "Sbuffer", config="TestConfig")
        assert result["ok"], result
        action = "generic_ports" if profile == "generic" else "ports"
        result = tool._run(action, "Sbuffer", config="TestConfig")
        assert result["ok"], result
        stage = agent.stage_manager.stages[0]
        stage.need_pass_llm_suggestion = False
        for name in stage.reference_files:
            agent.tool_read_text.invoke({"path": name})
        passed, result = stage.do_check(is_complete=True)
        assert passed, result
    finally:
        agent.exit()


def test_readme_example_has_real_configured_ports(tmp_path):
    """The copyable RTL/config pair captures a 32-bit register with the real frontend."""
    from rtl2spec.generic_evidence import generate_generic, validate_generic_evidence

    source = Path(__file__).resolve().parents[1] / "examples/GenericBlock"
    shutil.copytree(source, tmp_path / "inputs/GenericBlock")
    generate_generic(tmp_path, "GenericBlock", "Generic")
    _, ports = validate_generic_evidence(tmp_path, "GenericBlock", "Generic")
    widths = {port["name"]: port["width"] for port in ports}
    assert widths == {"clock": 1, "reset": 1, "enable": 1, "data_in": 32, "data_out": 32}


def test_launch_does_not_import_an_uninstalled_core_from_the_current_directory(tmp_path):
    """The child uses the configured Python environment even inside an unrelated checkout."""
    local_package = tmp_path / "ucagent"
    local_package.mkdir()
    (local_package / "__init__.py").write_text('raise RuntimeError("Unexpected local package")\n')
    config_file = tmp_path / "run.yaml"
    main(["--init", "generic", "--config", str(config_file)])
    command = build_command(config_file)
    result = subprocess.run([*command[:4], "--help"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "--plugin-workflow" in result.stdout
