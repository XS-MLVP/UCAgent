# -*- coding: utf-8 -*-
"""UnityTest registers as a local workflow plugin without behavior change."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/unitytest/src"))

from ucagent.plugins import (
    find_owning_plugin_project,
    load_plugin,
    load_pointer_workflow_plugin,
    resolve_plugin_workflow,
)
from ucagent.util.config import (
    get_config,
    resolve_default_task_workflow,
    resolve_workflow_pointer_path,
)
from unitytest_plugin.checkers import (
    UnityChipBatchCheckerFileLineMap,
    UnityChipBatchCheckerStaticBug,
    UnityChipCheckerBatchTestsImplementation,
    UnityChipCheckerBundleWrapper,
    UnityChipCheckerDutCreation,
    UnityChipCheckerLabelStructureRefine,
    UnityChipCheckerMarkdownFileFormat,
    UnityChipCheckerMockComponent,
    UnityChipCheckerMockFixture,
    UnityChipCheckerRefineTestCases,
    UnityChipCheckerStaticBugFormat,
    UnityChipCheckerStaticBugValidation,
    UnityChipCheckerTestCaseWithLineCoverage,
    UnityChipCheckerTestFree,
    UnityChipCheckerTestMockTestBatch,
    UnityChipCheckerTestMustPass,
    UnityChipCheckerTestTemplate,
    UnityChipCheckerWaveformBugAnalysis,
)
from unitytest_plugin.plugin import create_waveform_tools

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PATH = REPO_ROOT / "plugins" / "unitytest"
WORKFLOW_CONFIG = (
    PLUGIN_PATH / "src" / "unitytest_plugin" / "workflows" / "unitytest.yaml"
)


def test_unitytest_plugin_loads_and_declares_workflow():
    loaded = load_plugin(str(PLUGIN_PATH))
    assert loaded.plugin.name == "unitytest"
    assert loaded.plugin.tool_factories == (create_waveform_tools,)
    assert loaded.plugin.checkers == (
        UnityChipBatchCheckerFileLineMap,
        UnityChipBatchCheckerStaticBug,
        UnityChipCheckerBatchTestsImplementation,
        UnityChipCheckerBundleWrapper,
        UnityChipCheckerDutCreation,
        UnityChipCheckerLabelStructureRefine,
        UnityChipCheckerMarkdownFileFormat,
        UnityChipCheckerMockComponent,
        UnityChipCheckerMockFixture,
        UnityChipCheckerRefineTestCases,
        UnityChipCheckerStaticBugFormat,
        UnityChipCheckerStaticBugValidation,
        UnityChipCheckerTestCaseWithLineCoverage,
        UnityChipCheckerTestFree,
        UnityChipCheckerTestMockTestBatch,
        UnityChipCheckerTestMustPass,
        UnityChipCheckerTestTemplate,
        UnityChipCheckerWaveformBugAnalysis,
    )
    workflow = next(
        item for item in loaded.plugin.workflows if item.name == "unitytest"
    )
    assert workflow.config_file == WORKFLOW_CONFIG.resolve()
    assert workflow.runtime_config_keys == ()


def test_unitytest_workflow_declares_moved_local_assets():
    loaded = load_plugin(str(PLUGIN_PATH))
    workflow = next(
        item for item in loaded.plugin.workflows if item.name == "unitytest"
    )
    assert workflow.template_dir == (
        PLUGIN_PATH / "src" / "unitytest_plugin" / "templates" / "unity_test"
    ).resolve()
    assert workflow.skill_paths == (
        (PLUGIN_PATH / "src" / "unitytest_plugin" / "skills").resolve(),
    )
    assert workflow.guide_doc_paths == (
        (PLUGIN_PATH / "src" / "unitytest_plugin" / "Guide_Doc").resolve(),
    )
    for path in (workflow.template_dir,) + workflow.skill_paths + workflow.guide_doc_paths:
        assert path.is_dir(), path


def test_pointer_workflow_activates_owning_plugin():
    workflow_file = resolve_workflow_pointer_path(
        "plugins/unitytest/src/unitytest_plugin/workflows/unitytest.yaml", "zh"
    )
    assert Path(workflow_file) == WORKFLOW_CONFIG.resolve()
    assert find_owning_plugin_project(workflow_file) == PLUGIN_PATH.resolve()

    loaded_plugins = []
    pair = load_pointer_workflow_plugin(workflow_file, loaded_plugins)
    assert pair is not None
    assert pair[0].plugin.name == "unitytest"
    assert pair[1].config_file == WORKFLOW_CONFIG.resolve()
    assert [item.plugin.name for item in loaded_plugins] == ["unitytest"]

    # re-running activation does not load the plugin twice
    again = load_pointer_workflow_plugin(workflow_file, loaded_plugins)
    assert again is not None
    assert again[0] is pair[0]
    assert len(loaded_plugins) == 1


def test_unitytest_plugin_workflow_resolves_by_name():
    loaded = load_plugin(str(PLUGIN_PATH))
    pair = resolve_plugin_workflow([loaded], "unitytest:unitytest")
    assert pair is not None
    assert pair[1].config_file == WORKFLOW_CONFIG.resolve()
    bare = resolve_plugin_workflow([loaded], "unitytest")
    assert bare is not None and bare[1].name == "unitytest"


def test_pointer_path_and_plugin_path_produce_equivalent_config(
    tmp_path, monkeypatch
):
    """Default pointer launch and plugin-workflow launch merge identically."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    # the pointer launch resolves the default workflow the way the cli does
    # and passes it explicitly; get_config itself never reads the pointer
    via_pointer = get_config(
        workflow_config_file=resolve_default_task_workflow()
    )
    via_plugin = get_config(workflow_config_file=str(WORKFLOW_CONFIG))
    for section in ("mission", "tools", "runtime_options", "hooks", "stage"):
        pointer_data = via_pointer.get_value(section).as_dict()
        plugin_data = via_plugin.get_value(section).as_dict()
        assert pointer_data == plugin_data, section


def test_get_config_without_workflow_file_is_framework_only(tmp_path, monkeypatch):
    """get_config never interprets the 'workflow' pointer: no
    workflow_config_file means framework-only."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = get_config()
    assert cfg.get_value("tools.RunTestCases", "absent") == "absent"
    assert cfg.get_value("runtime_options", "absent") == "absent"
    # the selector itself is still plain merged data for the launcher to read
    assert isinstance(cfg.get_value("workflow"), str)


def test_default_task_workflow_resolution_follows_config_layers(
    tmp_path, monkeypatch
):
    """The default-workflow decision reads the fully merged config: a later
    layer may redirect or null the selector."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert Path(resolve_default_task_workflow()) == WORKFLOW_CONFIG.resolve()

    redirected = tmp_path / "redirect.yaml"
    redirected.write_text(
        f"workflow: {WORKFLOW_CONFIG.resolve()}\n",
        encoding="utf-8",
    )
    assert Path(
        resolve_default_task_workflow(config_file=str(redirected))
    ) == WORKFLOW_CONFIG.resolve()

    nulled = tmp_path / "nulled.yaml"
    nulled.write_text("workflow: Null\n", encoding="utf-8")
    assert resolve_default_task_workflow(config_file=str(nulled)) is None


def test_pointer_selector_supports_installed_package_form():
    """A '<module>:<relative-path>' pointer resolves inside the importable package."""
    resolved = resolve_workflow_pointer_path(
        "unitytest_plugin:workflows/unitytest.yaml", "zh"
    )

    assert Path(resolved) == WORKFLOW_CONFIG.resolve()


def test_explicit_plugin_workflow_replaces_pointer_baseline(
    tmp_path, monkeypatch
):
    """An explicit plugin workflow must not stack the pointer workflow under it."""
    monkeypatch.chdir(tmp_path)
    design_workflow = (
        REPO_ROOT
        / "plugins"
        / "DesignWithPPA"
        / "src"
        / "design_with_ppa"
        / "workflows"
        / "unit-design-tdd.yaml"
    )

    cfg = get_config(workflow_config_file=str(design_workflow))

    assert cfg.get_value("tools.RunTestCases.test_dir") == "{OUT}/tests"
    assert cfg.get_value("skill.general_skill_list") == []
    assert cfg.get_value("skill.no_applicable_examples", "absent") == "absent"


def test_pointer_plugin_falls_back_to_installed_entry_points(monkeypatch):
    """Without a local manifest, the installed entry-point owner is activated once."""
    from importlib.metadata import EntryPoint

    import ucagent.plugins as plugins_module

    monkeypatch.setattr(plugins_module, "find_owning_plugin_project", lambda _f: None)
    monkeypatch.setattr(
        plugins_module,
        "_entry_points",
        lambda: [
            EntryPoint(
                "unitytest",
                "unitytest_plugin.plugin:get_plugin",
                plugins_module.PLUGIN_ENTRY_POINT_GROUP,
            )
        ],
    )
    loaded_plugins = []
    resources = plugins_module.load_pointer_workflow_plugin(
        str(WORKFLOW_CONFIG), loaded_plugins
    )

    assert resources is not None
    loaded, workflow = resources
    assert loaded.selector == "unitytest"
    assert workflow.config_file == WORKFLOW_CONFIG.resolve()
    assert len(loaded_plugins) == 1

    again = plugins_module.load_pointer_workflow_plugin(
        str(WORKFLOW_CONFIG), loaded_plugins
    )
    assert again[0] is loaded
    assert len(loaded_plugins) == 1


def test_pointer_plugin_returns_none_without_any_owner(monkeypatch):
    """A pointer file owned by neither a local project nor an install is inert."""
    import ucagent.plugins as plugins_module

    monkeypatch.setattr(plugins_module, "find_owning_plugin_project", lambda _f: None)
    monkeypatch.setattr(plugins_module, "_entry_points", lambda: [])

    assert (
        plugins_module.load_pointer_workflow_plugin(str(WORKFLOW_CONFIG), []) is None
    )


INCREMENTAL_CONFIG = (
    PLUGIN_PATH / "src" / "unitytest_plugin" / "workflows" / "incremental.yaml"
)
VIBE_CONFIG = PLUGIN_PATH / "src" / "unitytest_plugin" / "workflows" / "vibe.yaml"


def test_unitytest_plugin_declares_incremental_and_vibe_workflows():
    """One plugin may carry sibling workflows sharing its assets."""
    loaded = load_plugin(str(PLUGIN_PATH))
    workflows = {workflow.name: workflow for workflow in loaded.plugin.workflows}
    assert set(workflows) == {"unitytest", "incremental", "vibe"}

    incremental = workflows["incremental"]
    assert incremental.config_file == INCREMENTAL_CONFIG.resolve()
    assert incremental.template_dir == workflows["unitytest"].template_dir
    assert incremental.skill_paths == workflows["unitytest"].skill_paths
    assert incremental.guide_doc_paths == workflows["unitytest"].guide_doc_paths

    vibe = workflows["vibe"]
    assert vibe.config_file == VIBE_CONFIG.resolve()
    assert vibe.template_dir is None
    assert vibe.skill_paths == workflows["unitytest"].skill_paths

    for name, workflow in workflows.items():
        assert workflow.config_file.is_file(), name


def test_incremental_and_vibe_resolve_by_name():
    loaded = load_plugin(str(PLUGIN_PATH))
    incremental = resolve_plugin_workflow([loaded], "unitytest:incremental")
    vibe = resolve_plugin_workflow([loaded], "unitytest:vibe")
    assert incremental is not None and incremental[1].name == "incremental"
    assert vibe is not None and vibe[1].name == "vibe"


def test_incremental_and_vibe_are_self_sufficient_baselines(tmp_path, monkeypatch):
    """Sibling workflows replace the default workflow instead of stacking under
    it: each declares its own RunTestCases config, free runner included."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    for workflow_config in (INCREMENTAL_CONFIG, VIBE_CONFIG):
        cfg = get_config(workflow_config_file=str(workflow_config))
        assert cfg.get_value("tools.RunTestCases.test_dir") == "{OUT}/tests"
        assert (
            cfg.get_value("tools.RunTestCases.free_runner_clss")
            == "UnityChipCheckerTestFree"
        )
        assert cfg.get_value("runtime_options.waveform_analysis_format_priority") == [
            "fst",
            "vcd",
            "fsdb",
        ]
