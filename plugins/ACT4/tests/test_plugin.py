"""Focused tests for the ACT4 privileged-suite plugin descriptor."""

from dataclasses import replace
import importlib.metadata
from pathlib import Path
import subprocess
import tomllib

import pytest
import yaml

from act4_privileged_suite.plugin import get_plugin
from ucagent.plugins import (
    LoadedPlugin,
    collect_plugin_resources,
    configured_plugin_search_paths,
    create_plugin_checker_registry,
    load_plugin,
    PluginError,
    validate_plugin,
    validate_workflow_dependencies,
)
from ucagent.util.config import Config
from ucagent.verify_agent import VerifyAgent


def test_plugin_descriptor_and_resources_validate() -> None:
    """Validate the opt-in workflow and locate every declared resource root."""
    plugin = validate_plugin(get_plugin(), check_dependencies=False)
    assert plugin.name == "act4-privileged-suite"
    assert plugin.workflows[0].name == "privileged-suite-generation"
    assert plugin.workflows[0].config_file.is_file()
    assert plugin.workflows[0].guide_doc_paths[0].is_dir()
    assert (plugin.workflows[0].guide_doc_paths[0] / "ACT4_Privileged_Suite_Workflow_Guide.md").is_file()

    loaded = LoadedPlugin(plugin, plugin.name, "test")
    assert collect_plugin_resources([loaded]) == ([], [])
    docs, skills = collect_plugin_resources([loaded], (loaded, plugin.workflows[0]))
    assert skills == []
    assert docs == [plugin.workflows[0].guide_doc_paths[0]]


def test_workflow_checker_arguments_construct_with_plugin_registry() -> None:
    """Construct all stage gates through the plugin's registered short names."""
    plugin = validate_plugin(get_plugin(), check_dependencies=False)
    workflow = plugin.workflows[0]
    config = yaml.safe_load(workflow.config_file.read_text(encoding="utf-8"))
    registry = create_plugin_checker_registry(
        [LoadedPlugin(plugin, plugin.name, "test")]
    )

    assert len(config["stage"]) == 7
    assert config["stage"][-1]["name"] == "generate_final_human_report"
    for stage in config["stage"]:
        for checker in stage["checker"]:
            checker_class = registry[checker["clss"]]
            checker_class(**checker["args"], cfg=config)


def test_workflow_checker_names_are_plugin_short_names() -> None:
    """Keep the workflow independent of file-based checker import paths."""
    workflow = Path(get_plugin().workflows[0].config_file)
    config = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    classes = {
        checker["clss"]
        for stage in config["stage"]
        for checker in stage["checker"]
    }
    assert classes == {
        "ACT4AIReviewChecker",
        "ACT4AssetChecker",
        "ACT4CTPReferenceChecker",
        "ACT4FileManifestChecker",
        "ACT4FinalReportChecker",
        "ACT4ManualReferenceChecker",
        "ACT4SwitchCapabilityChecker",
        "ACT4TestAssetChecker",
    }


def test_stages_reference_bundled_contracts() -> None:
    """Expose each gate's rules and the current artifact template before generation."""
    plugin = get_plugin()
    workflow = yaml.safe_load(plugin.workflows[0].config_file.read_text(encoding="utf-8"))
    templates = [
        "privileged_coverpoints_template.md",
        "privileged_coverpoints_template.md",
        "privileged_vm_resource_template.md",
        "privileged_test_generator_template.md",
        "privileged_validation_handoff_template.md",
        "privileged_validation_handoff_template.md",
        "privileged_validation_handoff_template.md",
    ]
    for stage, template in zip(workflow["stage"], templates, strict=True):
        references = stage["reference_files"]
        assert f"Guide_Doc/act4_template/{template}" in references
        for gate in stage["checker"]:
            assert f"Guide_Doc/ACT4_Checker_Guide/{gate['clss']}.md" in references
        for reference in references:
            if reference.startswith("Guide_Doc/"):
                assert (plugin.root / reference).is_file(), reference


@pytest.mark.parametrize("parent_search", [True, False])
def test_configured_search_path_finds_plugin(monkeypatch, parent_search) -> None:
    """Discover the actual manifest by ID from either a plugin root or its parent."""
    project_root = Path(__file__).resolve().parents[1]
    search_root = project_root.parent if parent_search else project_root
    config = Config({"plugin": {"search_paths": [str(search_root)]}})
    monkeypatch.setattr("ucagent.plugins._entry_points", lambda: ())
    loaded = load_plugin(
        "act4-privileged-suite",
        search_paths=configured_plugin_search_paths(config),
    )
    assert Path(loaded.source) == project_root / "ucagent-plugin.toml"
    assert loaded.plugin.name == "act4-privileged-suite"


@pytest.mark.parametrize("checker_class", get_plugin().checkers, ids=lambda item: item.__name__)
def test_registry_rejects_conflicts_without_global_mutation(monkeypatch, checker_class) -> None:
    """Keep every checker local and reject collisions with plugins and core exports."""
    import ucagent.checkers as core_checkers

    plugin = get_plugin()
    loaded = LoadedPlugin(plugin, plugin.name, "test")
    name = checker_class.__name__
    assert not hasattr(core_checkers, name)
    assert create_plugin_checker_registry([loaded])[name] is checker_class
    assert not hasattr(core_checkers, name)
    other = LoadedPlugin(replace(plugin, name="another-plugin"), "another-plugin", "test")
    with pytest.raises(PluginError, match="Duplicate plugin Checker name"):
        create_plugin_checker_registry([loaded, other])
    monkeypatch.setattr(core_checkers, name, checker_class, raising=False)
    with pytest.raises(PluginError, match="conflicts with a core Checker"):
        create_plugin_checker_registry([loaded])


@pytest.mark.parametrize(
    "version,compatible",
    [("0.9.1", False), ("26.9.2.dev24", False), ("26.9.2.dev25", True)],
)
def test_ucagent_compatibility_matches_verified_baseline(monkeypatch, version, compatible) -> None:
    """Require the core release exercised by the plugin's lifecycle tests."""
    monkeypatch.setattr("ucagent.plugins.__version__", version)
    if compatible:
        validate_plugin(get_plugin(), check_dependencies=False)
    else:
        with pytest.raises(PluginError, match="requires UCAgent"):
            validate_plugin(get_plugin(), check_dependencies=False)


def test_missing_yaml_dependency_reports_requirement(monkeypatch) -> None:
    """Diagnose missing distribution metadata before activating checkers."""
    real_version = importlib.metadata.version

    def installed_version(name):
        """Hide only PyYAML while keeping the rest of the environment available."""
        if name == "PyYAML":
            raise importlib.metadata.PackageNotFoundError(name)
        return real_version(name)

    monkeypatch.setattr(importlib.metadata, "version", installed_version)
    with pytest.raises(PluginError, match="requires Python package PyYAML"):
        validate_plugin(get_plugin(), check_dependencies=True)


def test_checker_activation_does_not_require_workflow_commands(monkeypatch) -> None:
    """Allow static checkers without importing the generation workflow's host tools."""
    monkeypatch.setattr("ucagent.plugins.shutil.which", lambda executable: None)
    validate_plugin(get_plugin(), check_dependencies=True)
    plugin = get_plugin()
    with pytest.raises(PluginError, match="requires command"):
        validate_workflow_dependencies(plugin.name, plugin.workflows[0])


@pytest.mark.parametrize("failure", ["exit", "empty", "timeout"])
@pytest.mark.parametrize("command,label", [("bash", "Bash"), ("git", "Git"), ("curl", "Curl"), ("make", "GNU Make")])
def test_broken_command_version_fails_before_workflow(monkeypatch, failure, command, label) -> None:
    """Reject unusable host tools even when their executables exist on PATH."""
    real_run = subprocess.run

    def probe(args, **kwargs):
        """Fail just the selected host-tool version probe."""
        if Path(args[0]).name == command and args[1:] == ["--version"]:
            if failure == "timeout":
                raise subprocess.TimeoutExpired(args, 10)
            return subprocess.CompletedProcess(args, 1 if failure == "exit" else 0, "", "")
        return real_run(args, **kwargs)

    monkeypatch.setattr("ucagent.plugins.subprocess.run", probe)
    plugin = get_plugin()
    with pytest.raises(PluginError, match=f"(query {label} version|working {label} version command)"):
        validate_workflow_dependencies(plugin.name, plugin.workflows[0])


def test_distribution_and_source_manifest_share_plugin_identity() -> None:
    """Require source loading and installed entry points to select one provider."""
    project_root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((project_root / "pyproject.toml").read_text())["project"]
    manifest = tomllib.loads((project_root / "ucagent-plugin.toml").read_text())
    plugin = get_plugin()
    assert plugin.name == manifest["name"]
    assert project["entry-points"]["ucagent.plugins"][plugin.name] == manifest["entry"]
    assert project["version"] == plugin.version
    assert f"UCAgent{plugin.requires_ucagent}" in project["dependencies"]
    assert set(plugin.python_requirements) <= set(project["dependencies"])


@pytest.mark.parametrize("skill_enabled", [True, False])
@pytest.mark.parametrize("manual_setting", ["default", "environment", "override"])
def test_agent_starts_with_complete_workflow(
    tmp_path, monkeypatch, skill_enabled, manual_setting
) -> None:
    """Initialize actual stages with both Skill settings and resolved manual paths."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ACT4_MANUAL_ROOT", raising=False)
    loaded = load_plugin(str(Path(__file__).resolve().parents[1]))
    workflow = loaded.plugin.workflows[0]
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    expected_manual = "riscv-isa-manual"
    overrides = [
        {"backend.key_name": "blank"},
        {"skill.use_skill": skill_enabled},
        {"langfuse.enable": False},
    ]
    if manual_setting != "default":
        monkeypatch.setenv("ACT4_MANUAL_ROOT", str(tmp_path / "external manual"))
        expected_manual = str(tmp_path / "external manual")
    if manual_setting == "override":
        expected_manual = str(tmp_path / "override manual")
        overrides.append({"template_overwrite.ACT4_MANUAL_ROOT": expected_manual})
    agent = VerifyAgent(
        workspace=str(workspace),
        dut_name="ExampleSuite",
        output="act4_assets",
        workflow_config_file=str(workflow.config_file),
        plugin_workflow=f"{loaded.plugin.name}:{workflow.name}",
        plugins=[loaded],
        template_context_factory=workflow.template_context_factory,
        plugin_guide_doc_paths=[str(path) for path in workflow.guide_doc_paths],
        cfg_override=overrides,
        no_embed_tools=True,
        no_history=True,
    )
    try:
        stages = agent.stage_manager.stages
        assert len(stages) == 7
        assert len([checker for stage in stages for checker in stage.checker]) == 25
        for stage in stages:
            for checker in stage.checker:
                assert isinstance(checker._cb_list, dict)
                assert checker.stage is stage
                assert checker.workspace == str(workspace)
                checker.on_init()
        manual_checker = stages[0].checker[1]
        assert manual_checker.manual_root == expected_manual
        assert agent.cfg.un_write_dirs == ["Guide_Doc"]
        assert agent.cfg.write_dirs == ["act4_assets", "riscv-arch-test"]
        assert agent.cfg.template == ""
        guide = workspace / "Guide_Doc"
        assert (guide / "ACT4_Privileged_Suite_Workflow_Guide.md").is_file()
        assert (guide / "act4_template/README.md").is_file()
        for stage in agent.cfg.stage:
            for reference in stage.reference_files:
                if reference.startswith("Guide_Doc/"):
                    assert (workspace / reference).is_file(), reference
        assert not (guide / "dut_fixture.md").exists()
        assert not (workspace / "act4_assets/tests").exists()
        assert agent.cfg.skill.use_skill is skill_enabled
    finally:
        agent.exit()


@pytest.mark.parametrize(
    "manual",
    ["act4_assets/manual", "riscv-arch-test", "riscv-arch-test/spec", ".", ""],
)
def test_manual_cannot_overlap_generated_assets(tmp_path, manual) -> None:
    """Reject manual inputs that a generation command could overwrite."""
    config = Config({"template_overwrite": {"ACT4_MANUAL_ROOT": manual}})
    with pytest.raises(PluginError, match="ACT4_MANUAL_ROOT"):
        get_plugin().workflows[0].template_context_factory(
            config, {"WORKSPACE": str(tmp_path), "OUT": "act4_assets"}
        )


@pytest.mark.parametrize("output", ["../outside", ".", "", "/tmp/act4-output", "riscv-arch-test", "riscv-arch-test/out"])
def test_output_must_stay_inside_workspace(tmp_path, output) -> None:
    """Reject output roots that escape or replace the task workspace."""
    config = Config({"template_overwrite": {"ACT4_MANUAL_ROOT": "riscv-isa-manual"}})
    with pytest.raises(PluginError, match="output"):
        get_plugin().workflows[0].template_context_factory(
            config, {"WORKSPACE": str(tmp_path), "OUT": output}
        )


@pytest.mark.parametrize("target", ["output", "act4"])
def test_writable_directory_symlinks_cannot_escape_workspace(tmp_path, target) -> None:
    """Validate resolved write targets before copying guides or generating files."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    name = "act4_assets" if target == "output" else "riscv-arch-test"
    (workspace / name).symlink_to(outside, target_is_directory=True)
    config = Config({"template_overwrite": {"ACT4_MANUAL_ROOT": "riscv-isa-manual"}})
    with pytest.raises(PluginError, match="workspace"):
        get_plugin().workflows[0].template_context_factory(
            config, {"WORKSPACE": str(workspace), "OUT": "act4_assets"}
        )


@pytest.mark.parametrize("manual", ["riscv-isa-manual", "external manual"])
def test_separate_output_and_readonly_manual_are_allowed(tmp_path, manual) -> None:
    """Keep nested output and external read-only specification inputs supported."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    setting = str(tmp_path / manual) if manual == "external manual" else manual
    config = Config({"template_overwrite": {"ACT4_MANUAL_ROOT": setting}})

    assert get_plugin().workflows[0].template_context_factory(
        config, {"WORKSPACE": str(workspace), "OUT": "generated/act4_assets"}
    ) == {}


@pytest.mark.parametrize("command", ["bash", "git", "curl", "make"])
def test_workflow_reports_missing_commands(monkeypatch, command) -> None:
    """Report each unavailable workflow prerequisite before stage execution."""
    import shutil

    real_which = shutil.which
    monkeypatch.setattr(
        "ucagent.plugins.shutil.which",
        lambda executable: None if executable == command else real_which(executable),
    )
    plugin = get_plugin()
    with pytest.raises(PluginError, match="requires command"):
        validate_workflow_dependencies(plugin.name, plugin.workflows[0])
