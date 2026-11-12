"""Formal data stays an optional Skill using unchanged framework execution."""

from pathlib import Path
import json
import re

import pytest
import yaml

from formal.checkers.formal import FormalSpecJsonChecker
from formal.plugin import create_tools, get_plugin
from ucagent.core.plugins import PluginContext
from ucagent.core.stage.vstage import get_root_stage
from ucagent.core.tools.fileops import ReadTextFile
from ucagent.util.config import Config, get_config, load_yaml_with_env_vars


WORKFLOW = Path(__file__).resolve().parents[1] / "src/formal/workflows/formal.yaml"


def walk_stages(stages):
    """Iterate all configured levels so no hidden child requires a Skill."""
    for stage in stages:
        yield stage
        yield from walk_stages(stage.get("stage", []))


@pytest.mark.parametrize("enabled", [True, False])
def test_tool_first_stages_resolve_without_skill_directory(tmp_path, monkeypatch, enabled):
    """Actual stage guidance and plugin tools do not depend on optional Skill assets."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    cfg = get_config(workflow_config_file=str(WORKFLOW), cfg_override=[{"skill.use_skill": enabled}])
    cfg.update_template({"DUT": "PacketGate", "OUT": "proofs", "WORKSPACE": str(tmp_path), "Version": "test"})
    cfg.un_freeze()
    cfg._temp_cfg = {"DUT": "PacketGate", "OUT": "proofs", "WORKSPACE": str(tmp_path)}
    cfg.freeze()
    plugin = get_plugin()
    root = get_root_stage(cfg, str(tmp_path), ReadTextFile(str(tmp_path)),
                          checker_registry={checker.__name__: checker for checker in plugin.checkers})
    assert not (tmp_path / ".ucagent/skills").exists()
    assert cfg.get_value("skill.use_skill") is enabled
    assert len(root.substages) == 9
    for stage in root.substages:
        assert stage.skill_list == {}
        assert not stage.substages
        assert "skill_list" not in stage.task_info()
    specification = next(stage for stage in root.substages if stage.name == "functional_specification_analysis")
    assert len(specification.checker) == 1
    assert specification.checker[0]._check_level == "ck"
    context = PluginContext(workspace=tmp_path, output_dir="proofs", dut_name="PacketGate",
                            cfg=cfg, write_dirs=("proofs",), un_write_dirs=("PacketGate",),
                            plugin_root=plugin.root)
    assert {tool.name for tool in create_tools(context)} == {"RunFormal"}
    assert plugin.workflows[0].skill_paths == (WORKFLOW.parent.parent / "skills",)


def test_workflow_has_no_default_skill_ceremony_or_partial_spec_stages():
    """The workflow removes redundant child gates while retaining the complete contract."""
    raw = load_yaml_with_env_vars(str(WORKFLOW))
    assert raw["skill"]["use_skill"] is True
    assert raw["skill"]["general_skill_list"] == ["ext/formal/data"]
    for stage in walk_stages(raw["stage"]):
        assert "skill_list" not in stage
        assert "force_use_skill" not in stage
    specification = next(stage for stage in raw["stage"] if stage["name"] == "functional_specification_analysis")
    assert "stage" not in specification
    assert specification["checker"][0]["args"]["check_level"] == "ck"
    assert specification["reference_files"]
    system = raw["mission"]["prompt"]["system"]
    assert "不需要SetSkillUsage" in system
    assert "RunSkillScript" in system
    assert "ext/formal/data" in system
    assert "普通文件工具" in system
    assert "SetCurrentStageJournal记录日志" in system
    analysis = next(stage for stage in raw["stage"] if stage["name"] == "environment_debugging_iteration")
    bugs = next(stage for stage in raw["stage"] if stage["name"] == "formal_execution")
    assert "prepare analysis" in " ".join(analysis["task"])
    assert "无技能" in " ".join(analysis["task"])
    assert "prepare bugs" in " ".join(bugs["task"])
    assert "无技能" in " ".join(bugs["task"])


def test_merged_specification_gate_still_requires_all_hierarchy_levels(tmp_path):
    """One full gate rejects FG-only and FC-only drafts before accepting complete CKs."""
    output = tmp_path / "proofs"
    output.mkdir()
    path = output / ".formal_records.yaml"
    checker = FormalSpecJsonChecker("PacketGate", check_level="ck", cfg=Config({"output": "proofs"}))
    checker.set_workspace(str(tmp_path))
    checker.on_init()
    group = {"id": "FG-LOGIC", "name": "Packet eligibility", "functions": []}
    data = {"dut": "PacketGate", "spec": {"function_groups": [group]}}
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert checker.do_check()[0] is False
    function = {"id": "FC-ELIGIBLE", "description": "Output follows request", "check_points": []}
    group["functions"].append(function)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert checker.do_check()[0] is False
    function["check_points"].append({"id": "CK-ELIGIBLE", "style": "Comb", "description": "eligible equals request"})
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    ok, details = checker.do_check()
    assert ok, details
    assert "FG+FC+CK" in details
    assert (output / "03_PacketGate_functions_and_checks.md").exists()


def test_runtime_guidance_uses_prepare_and_derived_bug_summary():
    """Public guidance distinguishes read-only inspection from explicit queue preparation."""
    docs = WORKFLOW.parent.parent / "Guide_Doc"
    data = (docs / "formal_data.md").read_text(encoding="utf-8")
    assert 'formal_data.py\",\"prepare analysis' in data
    assert "ready_update" in data
    assert "只读查看" in data
    assert "update --request-file formal_test/data_update.json" in data
    assert "技能关闭或缺失时" in data
    assert "不存在独立的FormalData工具" in data
    assert "不手工复制哈希" in data
    assert "不再填写severe_bugs" in data
    examples = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", data, re.DOTALL)]
    commands = [value for value in examples if "commands" in value]
    requests = [value for value in examples if "section" in value]
    assert commands and requests
    for value in commands:
        assert len(value["commands"]) == 1
        assert value["commands"][0][:2] == ["ext/formal/data", "formal_data.py"]
        assert len(value["commands"][0]) == 3
    for value in requests:
        assert set(value) <= {"section", "expected_sha256", "data", "bodies"}
        assert "action" not in value
    summary = (docs / "formal_summary.md").read_text(encoding="utf-8")
    assert "严重缺陷汇总从已核验Bug记录派生" in summary
    assert "## 6. 验收结论" in summary
    assert "## 当前输入机器证明状态" in summary
