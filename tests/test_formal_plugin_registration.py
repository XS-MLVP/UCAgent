# -*- coding: utf-8 -*-
"""Formal registers as a standalone local workflow plugin."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/formal/src"))

from ucagent.plugins import (
    create_plugin_checker_registry,
    load_plugin,
    resolve_plugin_workflow,
)
from ucagent.util.config import get_config

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PATH = REPO_ROOT / "plugins" / "formal"
WORKFLOW_CONFIG = PLUGIN_PATH / "src" / "formal_plugin" / "workflows" / "formal.yaml"
CHECKER_NAMES = (
    "PlanningStructureChecker",
    "BasicInfoStructureChecker",
    "FormalSpecJsonChecker",
    "PropertyStructureChecker",
    "ScriptGenerationChecker",
    "EnvironmentAnalysisChecker",
    "CoverageAnalysisChecker",
    "CounterexampleTestgenChecker",
    "BugReportConsistencyChecker",
    "FormalSummaryChecker",
    "StaticFormalBugLinkageChecker",
)


def test_formal_plugin_loads_and_declares_workflow():
    loaded = load_plugin(str(PLUGIN_PATH))
    assert loaded.plugin.name == "formal"
    assert tuple(checker.__name__ for checker in loaded.plugin.checkers) == (
        CHECKER_NAMES
    )

    (workflow,) = loaded.plugin.workflows
    assert workflow.name == "formal"
    assert workflow.config_file == WORKFLOW_CONFIG.resolve()
    assert workflow.template_dir == (
        PLUGIN_PATH / "src" / "formal_plugin" / "templates" / "formal_test"
    ).resolve()
    assert workflow.skill_paths == (
        (PLUGIN_PATH / "src" / "formal_plugin" / "skills").resolve(),
    )
    assert workflow.guide_doc_paths == (
        (PLUGIN_PATH / "src" / "formal_plugin" / "Guide_Doc").resolve(),
    )
    for path in (
        (workflow.config_file, workflow.template_dir)
        + workflow.skill_paths
        + workflow.guide_doc_paths
    ):
        assert path.exists(), path


def test_formal_checker_short_names_resolve_in_plugin_registry():
    loaded = load_plugin(str(PLUGIN_PATH))
    registry = create_plugin_checker_registry([loaded])
    for name in CHECKER_NAMES:
        assert name in registry, name


def test_formal_workflow_references_plugin_names_not_core_paths():
    """The migrated workflow uses registry short names and ext/formal skill ids."""
    text = WORKFLOW_CONFIG.read_text(encoding="utf-8")
    assert "ucagent.checkers.formal" not in text
    assert "ucagent.lang.zh.skills" not in text
    assert '"formal/' not in text
    assert "ext/formal/" in text


def test_formal_skills_match_directory_names():
    skills = PLUGIN_PATH / "src" / "formal_plugin" / "skills"
    skill_dirs = sorted(path.name for path in skills.iterdir() if path.is_dir())
    assert "lib" in skill_dirs
    for name in skill_dirs:
        metadata = (skills / name / "SKILL.md").read_text(encoding="utf-8")
        assert f"name: {name}\n" in metadata, name


def test_formal_workflow_mission_appends_to_framework_layer(tmp_path, monkeypatch):
    """As the task-workflow baseline the formal mission extends the framework
    prompts and leaves the framework skill-system text in charge."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = get_config(workflow_config_file=str(WORKFLOW_CONFIG))
    system = cfg.get_value("mission.prompt.system")
    assert "本提示词说明任务框架" in system
    assert "形式化验证架构师" in system
    assert "技能系统" in cfg.get_value("mission.prompt.skill_system")
    assert cfg.get_value("template") == "formal_test"
    assert cfg.get_value("skill.use_skill") is True
    assert cfg.get_value("tools.RunTestCases", "absent") == "absent"
