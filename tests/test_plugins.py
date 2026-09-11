"""Focused tests for UCAgent plugin discovery, validation, and tool creation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import importlib
import json
import sys
from unittest import mock

import pytest

from ucagent.plugins import (
    CommandRequirement,
    GuideDocCopyPolicy,
    PluginGuideDocCopyPolicy,
    LoadedPlugin,
    Plugin,
    PluginContext,
    PluginError,
    PluginWorkflow,
    available_plugin_names,
    collect_plugin_resources,
    configured_plugin_search_paths,
    create_plugin_checker_registry,
    create_plugin_tools,
    load_plugin,
    load_plugins,
    plugin_summary,
    resolve_guide_doc_copy_policy,
    resolve_plugin_guide_doc_copy_policy,
    resolve_plugin_workflow,
    resolve_workflow_template_context,
    validate_plugin,
    validate_workflow_dependencies,
)
import ucagent.plugins as plugin_module
from ucagent.checkers.base import Checker
from ucagent.cli import _plugin_discovery_overrides, run
from ucagent.stage.vstage import parse_vstage
from ucagent.tools.uctool import UCTool, to_fastmcp
from ucagent.tools.fileops import is_file_writeable as _is_file_writeable
from ucagent.util.config import Config
from ucagent.verify_agent import VerifyAgent


@pytest.fixture(autouse=True)
def _clear_temporary_plugin_modules() -> None:
    """Keep local plugin import identity isolated across temporary projects."""

    for module_name in list(sys.modules):
        if module_name == "sample_plugin" or module_name.startswith("sample_plugin."):
            del sys.modules[module_name]
    yield
    for module_name in list(sys.modules):
        if module_name == "sample_plugin" or module_name.startswith("sample_plugin."):
            del sys.modules[module_name]


class _TestTool(UCTool):
    """Provide a minimal UCTool instance for factory contract tests."""

    name: str = "TestPluginTool"
    description: str = "Return a deterministic plugin test result."

    def _run(self) -> str:
        """Return the deterministic test result."""

        return "ok"


class PluginCheckerSample(Checker):
    """Provide a minimal Checker contribution for registry and stage tests."""

    def __init__(self, cfg) -> None:
        """Initialize the Checker with its resolved UCAgent configuration."""

        super().__init__()
        self.cfg = cfg

    def do_check(self, is_complete: bool = False, **kwargs):
        """Accept the stage so tests can prove plugin Checker construction."""

        return True, {"plugin_checker": True, "is_complete": is_complete}


def _write_local_plugin(
    project: Path,
    *,
    plugin_name: str = "sample-plugin",
    package_name: str = "sample_plugin",
) -> Path:
    """Create one importable local plugin project with the canonical manifest."""

    package = project / "src" / package_name
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(
        '"""Temporary plugin package."""\n', encoding="utf-8"
    )
    (package / "provider.py").write_text(
        "\n".join(
            [
                '"""Temporary plugin provider."""',
                "from pathlib import Path",
                "from ucagent.plugins import Plugin, PluginContext",
                "from ucagent.tools.uctool import UCTool",
                "",
                "class LocalTool(UCTool):",
                '    """Minimal local plugin tool."""',
                '    name: str = "LocalPluginTool"',
                '    description: str = "Return a local plugin result."',
                "    def _run(self) -> str:",
                '        """Return a deterministic result."""',
                '        return "local"',
                "",
                "def create_tools(context: PluginContext):",
                '    """Create tools with the supplied runtime context."""',
                "    return [LocalTool()]",
                "",
                "def get_plugin() -> Plugin:",
                '    """Return this temporary plugin descriptor."""',
                "    root = Path(__file__).resolve().parent",
                "    return Plugin(",
                f'        name="{plugin_name}",',
                '        version="1.2.3",',
                '        description="Temporary plugin.",',
                "        root=root,",
                "        tool_factories=(create_tools,),",
                "    )",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = project / "ucagent-plugin.toml"
    manifest.write_text(
        "\n".join(
            [
                "schema_version = 1",
                f'name = "{plugin_name}"',
                f'entry = "{package_name}.provider:get_plugin"',
                'python_path = "src"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def _context(workspace: Path) -> PluginContext:
    """Build a minimal resolved plugin context for tool factory tests."""

    return PluginContext(
        workspace=workspace,
        output_dir="output",
        write_dirs=("output",),
        un_write_dirs=("rtl",),
        cfg=SimpleNamespace(),
        plugin_root=workspace,
    )


def test_local_project_and_collection_search_load_the_same_plugin(tmp_path: Path) -> None:
    """A project path and configured parent search path must resolve one plugin ID."""

    project = tmp_path / "DesignPlugin"
    _write_local_plugin(project)

    direct = load_plugin(str(project), check_dependencies=False)
    searched = load_plugin(
        "sample-plugin",
        search_paths=[tmp_path],
        check_dependencies=False,
    )

    assert direct.plugin.name == searched.plugin.name == "sample-plugin"
    assert searched.source == str(project / "ucagent-plugin.toml")
    assert direct.python_import_root == (project / "src").resolve()
    assert searched.python_import_root == (project / "src").resolve()
    assert "sample-plugin" in available_plugin_names([tmp_path])


def test_local_plugin_import_root_is_available_to_test_subprocesses(
    tmp_path: Path,
) -> None:
    """RunTestCases must import public helpers from an activated source plugin."""

    project = tmp_path / "DesignPlugin"
    _write_local_plugin(project)
    loaded = load_plugin(str(project), check_dependencies=False)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agent = VerifyAgent(
        workspace=str(workspace),
        dut_name="empty",
        output="unity_test",
        config_file="master.yaml",
        cfg_override=[
            {"backend.key_name": "blank"},
            {"guide_doc.enable": False},
            {"langfuse.enable": False},
        ],
        no_embed_tools=True,
        no_history=True,
        plugins=[loaded],
    )
    try:
        assert agent.stage_manager.free_pytest_run.run_test.extra_python_paths == [
            str((project / "src").resolve())
        ]
    finally:
        agent.exit()


def test_plugin_import_root_is_available_to_stage_checker_pytest(
    tmp_path: Path,
) -> None:
    """Checker-managed pytest must receive the same trusted plugin import root."""

    cfg = Config(
        {
            "skill": {"use_skill": False},
            "hist_ignore_pattern": [],
            "stage": [
                {
                    "name": "test-gate",
                    "desc": "Run tests.",
                    "task": [],
                    "checker": [
                        {
                            "name": "tests",
                            "clss": "UnityChipCheckerTestMustPass",
                            "args": {
                                "target_file": "output/tests/test_*.py",
                                "test_dir": "output/tests",
                                "test_prefix": "test_",
                            },
                        }
                    ],
                }
            ],
        }
    )
    cfg._temp_cfg = {"OUT": "output", "DUT": "dut"}
    stage = parse_vstage(cfg, cfg.stage, str(tmp_path), None)[0]
    private_root = str(tmp_path / "private-python-dut")
    plugin_root = str(tmp_path / "plugin" / "src")
    stage.checker[0].run_test.set_extra_python_paths([private_root])
    manager = SimpleNamespace(test_python_import_roots=[plugin_root])

    stage.set_stage_manager(manager)

    assert stage.checker[0].run_test.extra_python_paths == [
        plugin_root,
        private_root,
    ]


def test_configured_search_paths_require_a_list_of_existing_directories(
    tmp_path: Path,
) -> None:
    """The resolved config contract must reject malformed or absent search roots."""

    valid = SimpleNamespace(get_value=lambda key, default: [str(tmp_path)])
    assert configured_plugin_search_paths(valid) == (tmp_path.resolve(),)

    malformed = SimpleNamespace(get_value=lambda key, default: str(tmp_path))
    with pytest.raises(PluginError, match="must be a list"):
        configured_plugin_search_paths(malformed)

    missing = SimpleNamespace(
        get_value=lambda key, default: [str(tmp_path / "missing")]
    )
    with pytest.raises(PluginError, match="was not found"):
        configured_plugin_search_paths(missing)


def test_manifest_schema_and_identity_are_exact(tmp_path: Path) -> None:
    """Local loading must reject unknown fields and provider identity mismatches."""

    project = tmp_path / "plugin"
    manifest = _write_local_plugin(project)
    manifest.write_text(
        manifest.read_text(encoding="utf-8") + 'unknown = "value"\n',
        encoding="utf-8",
    )
    with pytest.raises(PluginError, match="must contain only"):
        load_plugin(str(project), check_dependencies=False)

    manifest = _write_local_plugin(project, plugin_name="manifest-name")
    provider = project / "src" / "sample_plugin" / "provider.py"
    provider.write_text(
        provider.read_text(encoding="utf-8").replace(
            'name="manifest-name"', 'name="provider-name"'
        ),
        encoding="utf-8",
    )
    sys.modules.pop("sample_plugin.provider", None)
    importlib.invalidate_caches()
    with pytest.raises(PluginError, match="does not match"):
        load_plugin(str(project), check_dependencies=False)


def test_validation_rejects_escaped_resources_and_missing_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plugin resources and declared runtime prerequisites must be validated."""

    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    escaped = Plugin(
        name="escaped-plugin",
        version="1.0.0",
        description="Escaped resource test.",
        root=root,
        assets=(outside,),
    )
    with pytest.raises(PluginError, match="inside plugin root"):
        validate_plugin(escaped, check_dependencies=False)

    missing_package = Plugin(
        name="missing-package",
        version="1.0.0",
        description="Missing package test.",
        root=root,
        python_requirements=("definitely-not-a-real-package-ucagent>=1",),
    )
    with pytest.raises(PluginError, match="requires Python package"):
        validate_plugin(missing_package)

    missing_command = Plugin(
        name="missing-command",
        version="1.0.0",
        description="Missing command test.",
        root=root,
        command_requirements=(
            CommandRequirement("missing", ("ucagent-command-that-does-not-exist",)),
        ),
    )
    monkeypatch.setattr("ucagent.plugins.shutil.which", lambda executable: None)
    with pytest.raises(PluginError, match="requires command"):
        validate_plugin(missing_command)


def test_workflow_resolution_is_qualified_and_unambiguous(tmp_path: Path) -> None:
    """Workflow selectors must resolve by plugin ID or reject an ambiguous short name."""

    config = tmp_path / "workflow.yaml"
    config.write_text("template: \"\"\n", encoding="utf-8")
    loaded = []
    for name in ("plugin-a", "plugin-b"):
        root = tmp_path / name
        root.mkdir()
        local_config = root / "workflow.yaml"
        local_config.write_text("template: \"\"\n", encoding="utf-8")
        plugin = validate_plugin(
            Plugin(
                name=name,
                version="1.0.0",
                description=f"{name} workflow.",
                root=root,
                workflows=(PluginWorkflow("analyze", local_config),),
            ),
            check_dependencies=False,
        )
        loaded.append(LoadedPlugin(plugin, name, name))

    selected, workflow = resolve_plugin_workflow(loaded, "plugin-a:analyze")
    assert selected.plugin.name == "plugin-a"
    assert workflow.name == "analyze"
    with pytest.raises(PluginError, match="ambiguous"):
        resolve_plugin_workflow(loaded, "analyze")


def test_workflow_dependencies_are_checked_only_after_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Tool-only activation must not require a workflow-only command."""

    config = tmp_path / "workflow.yaml"
    config.write_text('template: ""\n', encoding="utf-8")
    plugin = Plugin(
        name="selective-dependencies",
        version="1.0.0",
        description="Workflow-only dependency test.",
        root=tmp_path,
        workflows=(
            PluginWorkflow(
                "build",
                config,
                command_requirements=(
                    CommandRequirement("Picker", ("picker",)),
                ),
            ),
        ),
        command_requirements=(CommandRequirement("Yosys", ("yosys",)),),
    )
    monkeypatch.setattr(
        "ucagent.plugins.shutil.which",
        lambda executable: executable if executable == "yosys" else None,
    )
    validated = validate_plugin(plugin)
    with pytest.raises(PluginError, match="Picker"):
        validate_workflow_dependencies(validated.name, validated.workflows[0])


def test_workflow_dependency_probes_version_and_subcommand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Selected workflows must prove declared version and subcommand probes."""

    config = tmp_path / "workflow.yaml"
    config.write_text('template: ""\n', encoding="utf-8")
    workflow = PluginWorkflow(
        "build",
        config,
        command_requirements=(
            CommandRequirement(
                "Picker",
                ("picker",),
                version_args=("--version",),
                required_subcommands=("export",),
            ),
        ),
    )
    monkeypatch.setattr("ucagent.plugins.shutil.which", lambda executable: "/bin/picker")
    calls = []

    def fake_run(command, **kwargs):
        """Return bounded successful probe output and record exact arguments."""

        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="picker 1.0", stderr="")

    monkeypatch.setattr("ucagent.plugins.subprocess.run", fake_run)
    validate_workflow_dependencies("sample", workflow)
    assert calls == [
        ["/bin/picker", "--version"],
        ["/bin/picker", "export", "--help"],
    ]


def test_workflow_template_target_rejects_static_escape(tmp_path: Path) -> None:
    """A workflow template destination may not be absolute or contain parent traversal."""

    config = tmp_path / "workflow.yaml"
    config.write_text('template: ""\n', encoding="utf-8")
    template = tmp_path / "template"
    template.mkdir()
    plugin = Plugin(
        "escaped-target",
        "1.0.0",
        "Escaped template target.",
        tmp_path,
        workflows=(
            PluginWorkflow(
                "build",
                config,
                template_dir=template,
                template_target="../outside",
            ),
        ),
    )
    with pytest.raises(PluginError, match="workspace-relative"):
        validate_plugin(plugin, check_dependencies=False)


def test_workflow_template_context_factory_is_validated(tmp_path: Path) -> None:
    """Workflow template hooks must be callable and return safe finite mappings."""

    config = tmp_path / "workflow.yaml"
    config.write_text('template: ""\n', encoding="utf-8")
    plugin = Plugin(
        "template-hook",
        "1.0.0",
        "Invalid template hook.",
        tmp_path,
        workflows=(
            PluginWorkflow(
                "build",
                config,
                template_context_factory="not-callable",  # type: ignore[arg-type]
            ),
        ),
    )
    with pytest.raises(PluginError, match="template_context_factory must be callable"):
        validate_plugin(plugin, check_dependencies=False)

    with pytest.raises(PluginError, match="must not replace core values"):
        resolve_workflow_template_context(
            lambda cfg, context: {"DUT": "replacement"},
            Config(),
            {"DUT": "dut", "OUT": "output"},
        )
    with pytest.raises(PluginError, match="finite JSON"):
        resolve_workflow_template_context(
            lambda cfg, context: {"VALUE": float("nan")},
            Config(),
            {"DUT": "dut", "OUT": "output"},
        )


def test_installed_and_local_plugin_id_conflict_lists_both_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An installed/local duplicate ID must fail without importing either candidate."""

    project = tmp_path / "DesignPlugin"
    manifest = _write_local_plugin(project)

    class FakeEntryPoint:
        """Expose installed metadata without needing a real distribution."""

        name = "sample-plugin"
        value = "installed_sample.provider:get_plugin"
        dist = SimpleNamespace(name="installed-sample-distribution")

    monkeypatch.setattr(plugin_module, "_entry_points", lambda: [FakeEntryPoint()])
    with pytest.raises(PluginError) as exc_info:
        load_plugin("sample-plugin", search_paths=[tmp_path], check_dependencies=False)
    message = str(exc_info.value)
    assert "installed-sample-distribution" in message
    assert str(manifest) in message


def test_each_plugin_capability_is_independently_optional(tmp_path: Path) -> None:
    """Tool, Checker, Doc, Skill, and workflow contributions must not depend on peers."""

    doc_root = tmp_path / "docs"
    doc_root.mkdir()
    (doc_root / "plugin.md").write_text("# Plugin\n", encoding="utf-8")
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: sample-skill\n"
        "description: Optional sample guidance.\n"
        "---\n\n"
        "# Sample Skill\n",
        encoding="utf-8",
    )
    config = tmp_path / "workflow.yaml"
    config.write_text('template: ""\n', encoding="utf-8")

    descriptors = {
        "empty": Plugin("empty", "1.0.0", "Metadata only.", tmp_path),
        "tool": Plugin(
            "tool", "1.0.0", "Tool only.", tmp_path, tool_factories=(lambda ctx: _TestTool(),)
        ),
        "checker": Plugin(
            "checker",
            "1.0.0",
            "Checker only.",
            tmp_path,
            checkers=(PluginCheckerSample,),
        ),
        "doc": Plugin(
            "doc", "1.0.0", "Doc only.", tmp_path, guide_doc_paths=(doc_root,)
        ),
        "skill": Plugin(
            "skill", "1.0.0", "Skill only.", tmp_path, skill_paths=(skill_root,)
        ),
        "workflow": Plugin(
            "workflow",
            "1.0.0",
            "Workflow only.",
            tmp_path,
            workflows=(PluginWorkflow("sample", config),),
        ),
    }

    validated = {
        name: validate_plugin(plugin, check_dependencies=False)
        for name, plugin in descriptors.items()
    }

    assert validated["empty"].tool_factories == ()
    assert validated["checker"].checkers == (PluginCheckerSample,)
    assert validated["doc"].guide_doc_paths == (doc_root,)
    assert validated["skill"].skill_paths == (skill_root,)
    assert [item.name for item in validated["workflow"].workflows] == ["sample"]


def test_plugin_checker_short_name_is_resolved_without_global_injection(
    tmp_path: Path,
) -> None:
    """An active plugin Checker must be usable by short name in any stage config."""

    plugin = validate_plugin(
        Plugin(
            "checker-plugin",
            "1.0.0",
            "Checker contribution.",
            tmp_path,
            checkers=(PluginCheckerSample,),
        ),
        check_dependencies=False,
    )
    loaded = LoadedPlugin(plugin, "checker-plugin", "test")
    registry = create_plugin_checker_registry([loaded])
    cfg = Config(
        {
            "skill": {"use_skill": False},
            "hist_ignore_pattern": [],
            "stage": [
                {
                    "name": "plugin-check",
                    "desc": "Run the plugin Checker.",
                    "task": [],
                    "checker": [
                        {
                            "name": "plugin_checker",
                            "clss": "PluginCheckerSample",
                            "args": {},
                            "extra_args": {},
                        }
                    ],
                }
            ],
        }
    )
    cfg._temp_cfg = {"OUT": "output"}

    stage = parse_vstage(
        cfg,
        cfg.stage,
        str(tmp_path),
        None,
        checker_registry=registry,
    )[0]

    assert isinstance(stage.checker[0], PluginCheckerSample)
    assert not hasattr(importlib.import_module("ucagent.checkers"), "PluginCheckerSample")
    assert stage._do_check(is_complete=True)[0] is True


def test_plugin_checker_validation_and_cross_plugin_conflicts_are_rejected(
    tmp_path: Path,
) -> None:
    """Checker contributions must be subclasses with globally unique active short names."""

    invalid = Plugin(
        "invalid-checker",
        "1.0.0",
        "Invalid Checker.",
        tmp_path,
        checkers=(object,),
    )
    with pytest.raises(PluginError, match="Checker subclasses"):
        validate_plugin(invalid, check_dependencies=False)

    loaded = []
    for plugin_name in ("checker-a", "checker-b"):
        plugin = validate_plugin(
            Plugin(
                plugin_name,
                "1.0.0",
                "Conflicting Checker.",
                tmp_path,
                checkers=(PluginCheckerSample,),
            ),
            check_dependencies=False,
        )
        loaded.append(LoadedPlugin(plugin, plugin_name, "test"))
    with pytest.raises(PluginError, match="Duplicate plugin Checker name"):
        create_plugin_checker_registry(loaded)

    from ucagent.checkers import HumanChecker

    core_conflict = Plugin(
        "core-conflict",
        "1.0.0",
        "Core conflict.",
        tmp_path,
        checkers=(HumanChecker,),
    )
    with pytest.raises(PluginError, match="core Checker"):
        validate_plugin(core_conflict, check_dependencies=False)


def test_plugin_and_selected_workflow_resources_are_merged_and_deduplicated(
    tmp_path: Path,
) -> None:
    """Plugin-level resources must remain active with optional workflow resources appended."""

    doc_root = tmp_path / "docs"
    doc_root.mkdir()
    (doc_root / "plugin.md").write_text("Plugin doc.\n", encoding="utf-8")
    workflow_doc = tmp_path / "workflow-doc.md"
    workflow_doc.write_text("Workflow doc.\n", encoding="utf-8")
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "sample-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: sample-skill\ndescription: Sample guidance.\n---\n",
        encoding="utf-8",
    )
    config = tmp_path / "workflow.yaml"
    config.write_text('template: ""\n', encoding="utf-8")
    plugin = validate_plugin(
        Plugin(
            "resource-plugin",
            "1.0.0",
            "Independent resources.",
            tmp_path,
            guide_doc_paths=(doc_root,),
            skill_paths=(skill_root,),
            workflows=(
                PluginWorkflow(
                    "sample",
                    config,
                    guide_doc_paths=(doc_root, workflow_doc),
                    skill_paths=(skill_root,),
                ),
            ),
        ),
        check_dependencies=False,
    )
    loaded = LoadedPlugin(plugin, "resource-plugin", "test")

    docs, skills = collect_plugin_resources(
        [loaded], (loaded, plugin.workflows[0])
    )

    assert docs == [doc_root, workflow_doc]
    assert skills == [("resource-plugin", skill_root)]
    summary = plugin_summary(loaded)
    assert summary["checkers"] == []
    assert summary["guide_docs"] == ["docs"]
    assert summary["skills"] == ["skills"]


def test_guide_doc_copy_policy_validates_actions_and_relative_paths() -> None:
    """Workflow YAML may select exact core Guide_Doc composition actions."""

    cfg = Config(
        {
            "guide_doc": {
                "core_copy_policy": {
                    "default_action": "ignore",
                    "retain": ["dut_fixture.md"],
                    "override": ["dut_api_instruction.md"],
                    "ignore": ["nested/unused.md"],
                }
            }
        }
    )
    policy = resolve_guide_doc_copy_policy(cfg)

    assert policy == GuideDocCopyPolicy(
        default_action="ignore",
        retain=("dut_fixture.md",),
        override=("dut_api_instruction.md",),
        ignore=("nested/unused.md",),
    )
    assert policy.action_for("dut_fixture.md") == "retain"
    assert policy.action_for("dut_api_instruction.md") == "override"
    assert policy.action_for("dut_bug_analysis.md") == "ignore"

    for invalid in (
        {
            "default_action": "replace",
            "retain": [],
            "override": [],
            "ignore": [],
        },
        {
            "default_action": "retain",
            "retain": ["../outside.md"],
            "override": [],
            "ignore": [],
        },
        {
            "default_action": "retain",
            "retain": ["same.md"],
            "override": ["same.md"],
            "ignore": [],
        },
        {
            "default_action": "retain",
            "retain": ["./dut_fixture.md"],
            "override": [],
            "ignore": [],
        },
        {
            "default_action": "retain",
            "retain": ["dut_fixture.md", "dut_fixture.md"],
            "override": [],
            "ignore": [],
        },
    ):
        with pytest.raises(PluginError):
            resolve_guide_doc_copy_policy(
                Config({"guide_doc": {"core_copy_policy": invalid}})
            )


def test_plugin_guide_doc_copy_policy_selects_contributed_documents() -> None:
    """Workflow config may retain or ignore exact plugin Guide_Doc paths."""

    cfg = Config(
        {
            "guide_doc": {
                "plugin_copy_policy": {
                    "default_action": "ignore",
                    "retain": ["coding_standard_chisel.md", "shared/api.md"],
                    "ignore": ["coding_standard_verilog.md"],
                }
            }
        }
    )

    policy = resolve_plugin_guide_doc_copy_policy(cfg)

    assert policy == PluginGuideDocCopyPolicy(
        default_action="ignore",
        retain=("coding_standard_chisel.md", "shared/api.md"),
        ignore=("coding_standard_verilog.md",),
    )
    assert policy.action_for("coding_standard_chisel.md") == "retain"
    assert policy.action_for("new.md") == "ignore"

    for invalid in (
        {"default_action": "override", "retain": [], "ignore": []},
        {"default_action": "retain", "retain": ["../outside.md"], "ignore": []},
        {"default_action": "retain", "retain": ["same.md"], "ignore": ["same.md"]},
        {"default_action": "retain", "retain": [], "ignore": []},
    ):
        invalid = dict(invalid)
        if invalid == {"default_action": "retain", "retain": [], "ignore": []}:
            invalid["extra"] = []
        with pytest.raises(PluginError):
            resolve_plugin_guide_doc_copy_policy(
                Config({"guide_doc": {"plugin_copy_policy": invalid}})
            )


def test_plugin_skill_roots_require_valid_skill_contracts(tmp_path: Path) -> None:
    """Plugin validation must reject absent or malformed Skill contracts before runtime."""

    empty_root = tmp_path / "empty-skills"
    empty_root.mkdir()
    with pytest.raises(PluginError, match="at least one SKILL.md"):
        validate_plugin(
            Plugin(
                "empty-skill",
                "1.0.0",
                "Empty Skill root.",
                tmp_path,
                skill_paths=(empty_root,),
            ),
            check_dependencies=False,
        )

    malformed_root = tmp_path / "malformed-skills"
    malformed_skill = malformed_root / "sample-skill"
    malformed_skill.mkdir(parents=True)
    (malformed_skill / "SKILL.md").write_text(
        "---\nname: wrong-name\ndescription: Sample.\n---\n",
        encoding="utf-8",
    )
    with pytest.raises(PluginError, match="matching its directory"):
        validate_plugin(
            Plugin(
                "malformed-skill",
                "1.0.0",
                "Malformed Skill.",
                tmp_path,
                skill_paths=(malformed_root,),
            ),
            check_dependencies=False,
        )


def test_plugin_skill_roots_cannot_overwrite_the_same_runtime_target(
    tmp_path: Path,
) -> None:
    """Plugin and workflow Skill roots must not silently overwrite one target Skill."""

    roots = []
    for root_name in ("base-skills", "workflow-skills"):
        skill_root = tmp_path / root_name
        skill = skill_root / "sample-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: sample-skill\ndescription: Sample guidance.\n---\n",
            encoding="utf-8",
        )
        roots.append(skill_root)
    config = tmp_path / "workflow.yaml"
    config.write_text('template: ""\n', encoding="utf-8")
    plugin = validate_plugin(
        Plugin(
            "skill-conflict",
            "1.0.0",
            "Conflicting Skill roots.",
            tmp_path,
            skill_paths=(roots[0],),
            workflows=(
                PluginWorkflow("sample", config, skill_paths=(roots[1],)),
            ),
        ),
        check_dependencies=False,
    )
    loaded = LoadedPlugin(plugin, "skill-conflict", "test")

    with pytest.raises(PluginError, match="Skill target conflicts"):
        collect_plugin_resources([loaded], (loaded, plugin.workflows[0]))


def test_tool_factories_receive_plugin_root_and_enforce_unique_uctools(
    tmp_path: Path,
) -> None:
    """Tool creation must bind each root and reject invalid or duplicate results."""

    roots = [tmp_path / "one", tmp_path / "two"]
    for root in roots:
        root.mkdir()
    observed_roots = []

    def factory(context: PluginContext) -> _TestTool:
        """Record the plugin-specific root and return a valid tool."""

        observed_roots.append(context.plugin_root)
        return _TestTool()

    first = LoadedPlugin(
        Plugin("first", "1.0.0", "First plugin.", roots[0], (factory,)),
        "first",
        "first",
    )
    tools = create_plugin_tools([first], _context(tmp_path))
    assert [tool.name for tool in tools] == ["TestPluginTool"]
    assert observed_roots == [roots[0]]

    invalid = LoadedPlugin(
        Plugin("invalid", "1.0.0", "Invalid plugin.", roots[1], (lambda ctx: object(),)),
        "invalid",
        "invalid",
    )
    with pytest.raises(PluginError, match="UCTool"):
        create_plugin_tools([invalid], _context(tmp_path))

    second = LoadedPlugin(
        Plugin("second", "1.0.0", "Second plugin.", roots[1], (factory,)),
        "second",
        "second",
    )
    with pytest.raises(PluginError, match="Duplicate plugin tool name"):
        create_plugin_tools([first, second], _context(tmp_path))


def test_duplicate_plugin_selection_is_rejected(tmp_path: Path) -> None:
    """Selecting the same plugin through a path and configured ID must fail clearly."""

    project = tmp_path / "plugin"
    _write_local_plugin(project)
    with pytest.raises(PluginError, match="selected more than once"):
        load_plugins(
            [str(project), "sample-plugin"],
            search_paths=[tmp_path],
            check_dependencies=False,
        )


def test_installed_entry_point_is_discovered_and_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An installed distribution entry point must load directly by stable plugin ID."""

    root = tmp_path / "installed"
    root.mkdir()
    descriptor = Plugin(
        name="installed-plugin",
        version="1.0.0",
        description="Installed entry point plugin.",
        root=root,
    )

    class FakeEntryPoint:
        """Model the importlib metadata surface consumed by the loader."""

        name = "installed-plugin"
        value = "installed_plugin.provider:get_plugin"
        dist = SimpleNamespace(name="ucagent-installed-plugin")

        @staticmethod
        def load():
            """Return the installed plugin provider."""

            return lambda: descriptor

    monkeypatch.setattr(plugin_module, "_entry_points", lambda: [FakeEntryPoint()])

    assert available_plugin_names() == ["installed-plugin"]
    loaded = load_plugin("installed-plugin", check_dependencies=False)
    assert loaded.plugin.name == "installed-plugin"
    assert loaded.source == "ucagent-installed-plugin"


def test_cli_discovers_plugin_id_from_configured_collection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The layered config search path must drive CLI listing and validation by ID."""

    collection = tmp_path / "plugins"
    project = collection / "DesignPlugin"
    _write_local_plugin(project)
    config = tmp_path / "config.yaml"
    config.write_text(
        "plugin:\n"
        "  search_paths:\n"
        f'    - "{collection}"\n',
        encoding="utf-8",
    )

    with mock.patch(
        "sys.argv", ["ucagent", "--config", str(config), "--list-plugins"]
    ):
        run()
    assert "sample-plugin" in capsys.readouterr().out.splitlines()

    with mock.patch(
        "sys.argv",
        [
            "ucagent",
            "--config",
            str(config),
            "--validate-plugin",
            "sample-plugin",
        ],
    ):
        run()
    output = capsys.readouterr().out
    json_start = output.rfind("[\n  {")
    assert json_start >= 0
    payload = json.loads(output[json_start:])
    assert payload[0]["name"] == "sample-plugin"


def test_plugin_discovery_uses_only_search_path_overrides() -> None:
    """Workflow-owned CLI values must wait until the workflow config is loaded."""

    overrides = [
        {"design_with_ppa.rtl.language": "chisel"},
        {"plugin.search_paths": ["/plugins"]},
        {"plugin.search_paths[0]": "/other-plugins"},
        {"backend.key_name": "opencode"},
    ]

    assert _plugin_discovery_overrides(overrides) == [
        {"plugin.search_paths": ["/plugins"]},
        {"plugin.search_paths[0]": "/other-plugins"},
    ]


def test_plugin_workflow_keeps_declared_skills_optional_when_disabled(
    tmp_path: Path,
) -> None:
    """A plugin workflow must start with ``--no-use-skill`` and retain its non-Skill path."""

    project = tmp_path / "WorkflowPlugin"
    _write_local_plugin(project)
    plugin_root = project / "src" / "sample_plugin"
    workflow_config = plugin_root / "workflow.yaml"
    workflow_config.write_text(
        'template: ""\nworkflow_only:\n  value: default\n', encoding="utf-8"
    )
    skills = plugin_root / "skills" / "sample-skill"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text(
        "---\n"
        "name: sample-skill\n"
        "description: Optional workflow guidance.\n"
        "---\n\n"
        "# Sample Skill\n",
        encoding="utf-8",
    )
    provider = project / "src" / "sample_plugin" / "provider.py"
    content = provider.read_text(encoding="utf-8")
    content = content.replace(
        "from ucagent.plugins import Plugin, PluginContext",
        "from ucagent.plugins import Plugin, PluginContext, PluginWorkflow",
    ).replace(
        "        tool_factories=(create_tools,),",
        "        tool_factories=(create_tools,),\n"
        "        workflows=(PluginWorkflow(\n"
        '            name="analyze",\n'
        '            config_file=root / "workflow.yaml",\n'
        '            skill_paths=(root / "skills",),\n'
        "        ),),",
    )
    provider.write_text(content, encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with mock.patch(
        "sys.argv",
        [
            "ucagent",
            str(workspace),
            "dut",
            "--plugin",
            str(project),
            "--plugin-workflow",
            "sample-plugin:analyze",
            "--no-use-skill",
            "--override",
            "workflow_only.value=selected",
        ],
    ), mock.patch("ucagent.verify_agent.VerifyAgent") as verify_agent:
        run()

    kwargs = verify_agent.call_args.kwargs
    assert kwargs["config_file"] is None
    assert kwargs["workflow_config_file"] == str(workflow_config)
    assert kwargs["plugin_workflow"] == "sample-plugin:analyze"
    assert kwargs["cfg_override"] == [
        {"workflow_only.value": "selected"},
        {"skill.use_skill": False},
    ]
    assert kwargs["plugin_skill_paths"] == [
        ("sample-plugin", str(plugin_root / "skills"))
    ]


def test_cli_activates_plugin_level_docs_and_skills_without_a_workflow(
    tmp_path: Path,
) -> None:
    """Top-level Doc and Skill contributions must activate without selecting a workflow."""

    project = tmp_path / "ResourcePlugin"
    _write_local_plugin(project)
    plugin_root = project / "src" / "sample_plugin"
    docs = plugin_root / "Guide_Doc"
    docs.mkdir()
    (docs / "sample.md").write_text("# Sample Plugin\n", encoding="utf-8")
    skills = plugin_root / "skills"
    skill = skills / "sample-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: sample-skill\n"
        "description: Optional plugin guidance.\n"
        "---\n\n"
        "# Sample Skill\n",
        encoding="utf-8",
    )
    provider = plugin_root / "provider.py"
    provider.write_text(
        provider.read_text(encoding="utf-8").replace(
            "        tool_factories=(create_tools,),",
            "        tool_factories=(create_tools,),\n"
            "        guide_doc_paths=(root / 'Guide_Doc',),\n"
            "        skill_paths=(root / 'skills',),",
        ),
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with mock.patch(
        "sys.argv",
        [
            "ucagent",
            str(workspace),
            "dut",
            "--plugin",
            str(project),
            "--no-use-skill",
        ],
    ), mock.patch("ucagent.verify_agent.VerifyAgent") as verify_agent:
        run()

    kwargs = verify_agent.call_args.kwargs
    assert kwargs["plugin_guide_doc_paths"] == [str(docs)]
    assert kwargs["plugin_skill_paths"] == [("sample-plugin", str(skills))]
    assert kwargs["cfg_override"] == [{"skill.use_skill": False}]


def test_verify_agent_direct_plugin_activation_copies_docs_and_optional_skills(
    tmp_path: Path,
) -> None:
    """Direct API callers must receive plugin-level resources without CLI preprocessing."""

    plugin_root = tmp_path / "plugin"
    docs = plugin_root / "Guide_Doc"
    docs.mkdir(parents=True)
    (docs / "plugin-api.md").write_text("# Plugin API\n", encoding="utf-8")
    skills = plugin_root / "skills"
    skill = skills / "sample-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: sample-skill\n"
        "description: Optional direct API guidance.\n"
        "---\n\n"
        "# Sample Skill\n",
        encoding="utf-8",
    )
    plugin = validate_plugin(
        Plugin(
            "resource-plugin",
            "1.0.0",
            "Direct API resources.",
            plugin_root,
            guide_doc_paths=(docs,),
            skill_paths=(skills,),
        ),
        check_dependencies=False,
    )
    loaded = LoadedPlugin(plugin, "resource-plugin", "test")

    def create_agent(workspace: Path, use_skill: bool) -> VerifyAgent:
        """Create a model-free agent with the selected Skill state."""

        workspace.mkdir(exist_ok=True)
        return VerifyAgent(
            workspace=str(workspace),
            dut_name="empty",
            output="unity_test",
            config_file="master.yaml",
            cfg_override=[
                {"backend.key_name": "blank"},
                {"guide_doc.enable": True},
                {"skill.use_skill": use_skill},
                {"langfuse.enable": False},
                {"vmanager.llm_suggestion.check_fail_refinement.enable": False},
                {"vmanager.llm_suggestion.check_pass_refinement.enable": False},
            ],
            no_embed_tools=True,
            no_history=True,
            plugins=[loaded],
        )

    disabled_workspace = tmp_path / "disabled"
    disabled_agent = create_agent(disabled_workspace, False)
    try:
        assert (disabled_workspace / "Guide_Doc" / "plugin-api.md").is_file()
        assert not (
            disabled_workspace
            / ".ucagent"
            / "skills"
            / "ext"
            / "resource-plugin"
        ).exists()
    finally:
        disabled_agent.exit()

    (docs / "plugin-api.md").write_text(
        "# Updated Plugin API\n", encoding="utf-8"
    )
    refreshed_agent = create_agent(disabled_workspace, False)
    try:
        assert (
            disabled_workspace / "Guide_Doc" / "plugin-api.md"
        ).read_text(encoding="utf-8") == "# Updated Plugin API\n"
    finally:
        refreshed_agent.exit()

    enabled_workspace = tmp_path / "enabled"
    enabled_agent = create_agent(enabled_workspace, True)
    try:
        assert (
            enabled_workspace
            / ".ucagent"
            / "skills"
            / "ext"
            / "resource-plugin"
            / "sample-skill"
            / "SKILL.md"
        ).is_file()
    finally:
        enabled_agent.exit()


def test_verify_agent_refreshes_plugin_docs_after_interrupted_run(
    tmp_path: Path,
) -> None:
    """Startup must recover Guide_Doc permissions left by an unclean exit."""

    plugin_root = tmp_path / "plugin"
    docs = plugin_root / "Guide_Doc"
    docs.mkdir(parents=True)
    plugin_doc = docs / "plugin-api.md"
    plugin_doc.write_text("# First Plugin API\n", encoding="utf-8")
    plugin = validate_plugin(
        Plugin(
            "restart-doc-plugin",
            "1.0.0",
            "Restart-safe runtime documents.",
            plugin_root,
            guide_doc_paths=(docs,),
        ),
        check_dependencies=False,
    )
    loaded = LoadedPlugin(plugin, "restart-doc-plugin", "test")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def create_agent() -> VerifyAgent:
        """Create one model-free agent over the shared restart workspace."""

        return VerifyAgent(
            workspace=str(workspace),
            dut_name="empty",
            output="unity_test",
            config_file="master.yaml",
            cfg_override=[
                {"backend.key_name": "blank"},
                {"guide_doc.enable": True},
                {"skill.use_skill": False},
                {"langfuse.enable": False},
                {"vmanager.llm_suggestion.check_fail_refinement.enable": False},
                {"vmanager.llm_suggestion.check_pass_refinement.enable": False},
            ],
            no_embed_tools=True,
            no_history=True,
            plugins=[loaded],
        )

    first_agent = create_agent()
    second_agent = None
    try:
        runtime_doc = workspace / "Guide_Doc" / "plugin-api.md"
        runtime_doc.chmod(0o444)
        (workspace / "Guide_Doc").chmod(0o555)
        plugin_doc.write_text("# Updated Plugin API\n", encoding="utf-8")

        second_agent = create_agent()

        assert runtime_doc.read_text(encoding="utf-8") == "# Updated Plugin API\n"
    finally:
        if second_agent is not None:
            second_agent.exit()
        first_agent.exit()


def test_verify_agent_rejects_plugin_doc_conflicting_with_base_runtime_doc(
    tmp_path: Path,
) -> None:
    """Plugin document refresh must not permit overriding a core Guide_Doc."""

    plugin_root = tmp_path / "plugin"
    docs = plugin_root / "Guide_Doc"
    docs.mkdir(parents=True)
    (docs / "dut_api_instruction.md").write_text(
        "# Conflicting API Contract\n", encoding="utf-8"
    )
    plugin = validate_plugin(
        Plugin(
            "doc-conflict-plugin",
            "1.0.0",
            "Conflicting Doc contribution.",
            plugin_root,
            guide_doc_paths=(docs,),
        ),
        check_dependencies=False,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(ValueError, match="base runtime document"):
        VerifyAgent(
            workspace=str(workspace),
            dut_name="empty",
            output="unity_test",
            config_file="master.yaml",
            cfg_override=[
                {"backend.key_name": "blank"},
                {"guide_doc.enable": True},
            ],
            no_embed_tools=True,
            no_history=True,
            plugins=[LoadedPlugin(plugin, "doc-conflict-plugin", "test")],
        )


def test_verify_agent_composes_core_and_plugin_guide_docs_by_policy(
    tmp_path: Path,
) -> None:
    """A workflow policy must retain, override, and omit exact core documents."""

    plugin_root = tmp_path / "plugin"
    docs = plugin_root / "Guide_Doc"
    docs.mkdir(parents=True)
    replacement = "\n# Plugin API Contract\n"
    (docs / "dut_api_instruction.md").write_text(replacement, encoding="utf-8")
    (docs / "plugin_only.md").write_text(
        "\n# Plugin Only\n", encoding="utf-8"
    )
    plugin = validate_plugin(
        Plugin(
            "doc-policy-plugin",
            "1.0.0",
            "Guide document composition.",
            plugin_root,
            guide_doc_paths=(docs,),
        ),
        check_dependencies=False,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agent = VerifyAgent(
        workspace=str(workspace),
        dut_name="empty",
        output="unity_test",
        config_file="master.yaml",
        cfg_override=[
            {"backend.key_name": "blank"},
            {"guide_doc.enable": True},
            {
                "guide_doc.core_copy_policy.override": [
                    "dut_api_instruction.md"
                ]
            },
            {"guide_doc.core_copy_policy.ignore": ["dut_bug_analysis.md"]},
            {"langfuse.enable": False},
        ],
        no_embed_tools=True,
        no_history=True,
        plugins=[LoadedPlugin(plugin, "doc-policy-plugin", "test")],
    )
    try:
        runtime_docs = workspace / "Guide_Doc"
        assert (runtime_docs / "dut_api_instruction.md").read_text(
            encoding="utf-8"
        ) == replacement
        assert not (runtime_docs / "dut_bug_analysis.md").exists()
        assert (runtime_docs / "dut_fixture.md").is_file()
        assert (runtime_docs / "plugin_only.md").is_file()
    finally:
        agent.exit()


def test_verify_agent_filters_plugin_guide_docs_after_template_resolution(
    tmp_path: Path,
) -> None:
    """A workflow may expose only the Guide_Doc selected by resolved config."""

    plugin_root = tmp_path / "plugin"
    docs = plugin_root / "Guide_Doc"
    docs.mkdir(parents=True)
    (docs / "coding_standard_verilog.md").write_text(
        "\n# Verilog\n", encoding="utf-8"
    )
    (docs / "coding_standard_chisel.md").write_text(
        "\n# Chisel\n", encoding="utf-8"
    )
    plugin = validate_plugin(
        Plugin(
            "filtered-doc-plugin",
            "1.0.0",
            "Selected runtime guide documents.",
            plugin_root,
            guide_doc_paths=(docs,),
        ),
        check_dependencies=False,
    )
    workspace = tmp_path / "workspace"
    runtime_docs = workspace / "Guide_Doc"
    runtime_docs.mkdir(parents=True)
    (runtime_docs / "coding_standard_verilog.md").write_text(
        "stale\n", encoding="utf-8"
    )
    agent = VerifyAgent(
        workspace=str(workspace),
        dut_name="empty",
        output="unity_test",
        config_file="master.yaml",
        cfg_override=[
            {"backend.key_name": "blank"},
            {"guide_doc.enable": True},
            {
                "guide_doc.plugin_copy_policy": {
                    "default_action": "ignore",
                    "retain": ["coding_standard_chisel.md"],
                    "ignore": ["coding_standard_verilog.md"],
                }
            },
            {"langfuse.enable": False},
        ],
        no_embed_tools=True,
        no_history=True,
        plugins=[LoadedPlugin(plugin, "filtered-doc-plugin", "test")],
    )
    try:
        assert (runtime_docs / "coding_standard_chisel.md").is_file()
        assert not (runtime_docs / "coding_standard_verilog.md").exists()
        assert (runtime_docs / "dut_fixture.md").is_file()
    finally:
        agent.exit()


def test_verify_agent_rejects_plugin_doc_symlink_parent(
    tmp_path: Path,
) -> None:
    """A nested plugin document must not follow a workspace symlink."""

    plugin_root = tmp_path / "plugin"
    docs = plugin_root / "Guide_Doc" / "nested"
    docs.mkdir(parents=True)
    (docs / "plugin.md").write_text("\n# Plugin\n", encoding="utf-8")
    plugin = validate_plugin(
        Plugin(
            "nested-doc-plugin",
            "1.0.0",
            "Nested Guide document contribution.",
            plugin_root,
            guide_doc_paths=(plugin_root / "Guide_Doc",),
        ),
        check_dependencies=False,
    )
    workspace = tmp_path / "workspace"
    runtime_docs = workspace / "Guide_Doc"
    runtime_docs.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (runtime_docs / "nested").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="must not contain symbolic links"):
        VerifyAgent(
            workspace=str(workspace),
            dut_name="empty",
            output="unity_test",
            config_file="master.yaml",
            cfg_override=[
                {"backend.key_name": "blank"},
                {"guide_doc.enable": True},
                {"langfuse.enable": False},
            ],
            no_embed_tools=True,
            no_history=True,
            plugins=[LoadedPlugin(plugin, "nested-doc-plugin", "test")],
        )
    assert not (outside / "plugin.md").exists()


def test_verify_agent_rejects_doc_contribution_when_runtime_docs_are_disabled(
    tmp_path: Path,
) -> None:
    """Doc-only plugins must fail clearly in modes that disable runtime Guide_Doc."""

    plugin_root = tmp_path / "plugin"
    docs = plugin_root / "Guide_Doc"
    docs.mkdir(parents=True)
    (docs / "plugin.md").write_text("# Plugin\n", encoding="utf-8")
    plugin = validate_plugin(
        Plugin(
            "doc-plugin",
            "1.0.0",
            "Doc contribution.",
            plugin_root,
            guide_doc_paths=(docs,),
        ),
        check_dependencies=False,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(ValueError, match="guide_doc.enable"):
        VerifyAgent(
            workspace=str(workspace),
            dut_name="empty",
            output="unity_test",
            config_file="master.yaml",
            cfg_override=[{"backend.key_name": "blank"}],
            no_embed_tools=True,
            no_history=True,
            plugins=[LoadedPlugin(plugin, "doc-plugin", "test")],
        )


def test_verify_agent_allows_protected_template_file_inside_render_target(
    tmp_path: Path,
) -> None:
    """One template-rendered file may protect itself inside the render target."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    template_root = tmp_path / "templates"
    template = template_root / "managed"
    template.mkdir(parents=True)
    (template / "generated.txt").write_text("generated\n", encoding="utf-8")
    (template / "locked.py").write_text("managed = True\n", encoding="utf-8")

    agent = VerifyAgent(
        workspace=str(workspace),
        dut_name="dut",
        output="out",
        config_file="master.yaml",
        cfg_override=[
            {"backend.key_name": "blank"},
            {"template": "managed"},
            {"un_write_dirs": ["out/locked.py"]},
        ],
        template_dir=str(template_root),
        template_target="{OUT}",
        no_embed_tools=True,
        no_history=True,
    )
    assert (workspace / "out" / "generated.txt").read_text(
        encoding="utf-8"
    ) == "generated\n"
    locked = workspace / "out" / "locked.py"
    assert locked.read_text(encoding="utf-8") == "managed = True\n"
    assert not (locked.stat().st_mode & 0o200), "rendered file must be read-only"
    ok, reason = _is_file_writeable(
        "out/locked.py", un_write_dirs=["out/locked.py"]
    )
    assert ok is False, reason
    del agent


def test_verify_agent_rejects_protected_directory_inside_render_target(
    tmp_path: Path,
) -> None:
    """Directory-level read-only protection inside a render target stays invalid."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    template_root = tmp_path / "templates"
    template = template_root / "blocked"
    template.mkdir(parents=True)
    (template / "generated.txt").write_text("generated\n", encoding="utf-8")

    with pytest.raises(ValueError, match="read-only path"):
        VerifyAgent(
            workspace=str(workspace),
            dut_name="dut",
            output="out",
            config_file="master.yaml",
            cfg_override=[
                {"backend.key_name": "blank"},
                {"template": "blocked"},
                {"un_write_dirs": ["out/ro_dir"]},
            ],
            template_dir=str(template_root),
            template_target="{OUT}",
            no_embed_tools=True,
            no_history=True,
        )


def test_verify_agent_rejects_template_target_overlapping_read_only_input(
    tmp_path: Path,
) -> None:
    """Workflow templates must never render into or above the read-only DUT tree."""

    workspace = tmp_path / "workspace"
    dut = workspace / "dut"
    dut.mkdir(parents=True)
    readme = dut / "README.md"
    readme.write_text("immutable input\n", encoding="utf-8")
    template_root = tmp_path / "templates"
    template = template_root / "blocked"
    template.mkdir(parents=True)
    (template / "generated.txt").write_text("generated\n", encoding="utf-8")

    with pytest.raises(ValueError, match="read-only path"):
        VerifyAgent(
            workspace=str(workspace),
            dut_name="dut",
            output="dut",
            config_file="master.yaml",
            cfg_override=[
                {"backend.key_name": "blank"},
                {"template": "blocked"},
                {"un_write_dirs": ["dut"]},
            ],
            template_dir=str(template_root),
            template_target="{OUT}",
            no_embed_tools=True,
            no_history=True,
        )
    assert readme.read_text(encoding="utf-8") == "immutable input\n"
    assert not (dut / "generated.txt").exists()


def test_verify_agent_renders_resolved_template_override_values(
    tmp_path: Path,
) -> None:
    """Workflow template variables must control both paths and file content."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    template_root = tmp_path / "templates"
    template = template_root / "language"
    template.mkdir(parents=True)
    (template / "{{SOURCE_FILE}}").write_text(
        "language={{SOURCE_LANGUAGE}} dut={{DUT}}\n", encoding="utf-8"
    )

    agent = VerifyAgent(
        workspace=str(workspace),
        dut_name="VectorUnit",
        output="generated",
        config_file="master.yaml",
        cfg_override=[
            {"backend.key_name": "blank"},
            {"template": "language"},
            {"template_overwrite.SOURCE_FILE": "{DUT}.scala"},
            {"template_overwrite.SOURCE_LANGUAGE": "chisel"},
        ],
        template_dir=str(template_root),
        template_target="{OUT}",
        no_embed_tools=True,
        no_history=True,
    )
    try:
        assert (workspace / "generated" / "VectorUnit.scala").read_text(
            encoding="utf-8"
        ) == "language=chisel dut=VectorUnit\n"
    finally:
        agent.exit()


def test_verify_agent_renders_dynamic_workflow_template_context(
    tmp_path: Path,
) -> None:
    """A selected workflow may derive template values from the final resolved config."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    template_root = tmp_path / "templates"
    template = template_root / "language"
    template.mkdir(parents=True)
    (template / "{{SOURCE_FILE}}").write_text(
        "{{SOURCE_BODY}}", encoding="utf-8"
    )
    workflow_config = tmp_path / "workflow.yaml"
    workflow_config.write_text(
        "sample:\n  language: chisel\n", encoding="utf-8"
    )

    def template_context(cfg, base_context):
        """Select a source scaffold from the final language option."""

        language = cfg.get_value("sample.language")
        return {
            "SOURCE_FILE": f"{base_context['DUT']}.scala",
            "SOURCE_BODY": f"language={language}\n",
        }

    agent = VerifyAgent(
        workspace=str(workspace),
        dut_name="VectorUnit",
        output="generated",
        config_file="master.yaml",
        cfg_override=[
            {"backend.key_name": "blank"},
            {"template": "language"},
        ],
        workflow_config_file=str(workflow_config),
        template_dir=str(template_root),
        template_target="{OUT}",
        template_context_factory=template_context,
        no_embed_tools=True,
        no_history=True,
    )
    try:
        assert (workspace / "generated" / "VectorUnit.scala").read_text(
            encoding="utf-8"
        ) == "language=chisel\n"
    finally:
        agent.exit()


def test_design_with_ppa_local_plugin_creates_mcp_compatible_tool(tmp_path: Path) -> None:
    """The shipped DesignWithPPA project must load, locate assets, and convert to MCP."""

    repository = Path(__file__).resolve().parent.parent
    project = repository / "examples" / "DesignWithPPA"
    loaded = load_plugin(str(project))
    tools = create_plugin_tools([loaded], _context(tmp_path))

    assert loaded.plugin.name == "design-with-ppa"
    assert plugin_summary(loaded)["tool_factories"] == 1
    assert [tool.name for tool in tools] == ["AnalyzePPA", "RunDesignConsistency"]
    assert tools[0]._DEFAULT_LIBERTY.is_file()
    parameters = to_fastmcp(tools[0]).parameters
    rtl_schema = parameters["properties"]["rtl_files"]
    assert rtl_schema["anyOf"][0] == {"items": {"type": "string"}, "type": "array"}
    waveform_schema = parameters["properties"]["waveform_files"]
    assert waveform_schema["anyOf"][0] == {"items": {"type": "string"}, "type": "array"}
    consistency_parameters = to_fastmcp(tools[1]).parameters
    assert consistency_parameters["properties"]["test_dir"]["default"] == "{OUT}/tests"
    assert consistency_parameters["properties"]["test_glob"]["default"] == "{OUT}/tests/test_{DUT}_*.py"
