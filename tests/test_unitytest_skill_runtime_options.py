from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ucagent.util.config import (
    Config,
    get_config,
    load_runtime_config,
    load_yaml_with_env_vars,
    save_runtime_config,
)
from ucagent.stage.vstage import VerifyStage


CREATE_SCRIPT = (
    REPO_ROOT
    / "ucagent/lang/zh/skills/unitytest/create-test-case-templates/scripts/createtemplate.py"
)
CONFIG_PATH = REPO_ROOT / "ucagent/lang/zh/config/default.yaml"
SKILL_ROOT = REPO_ROOT / "ucagent/lang/zh/skills/unitytest"


def _load_create_script():
    spec = importlib.util.spec_from_file_location("test_createtemplate", CREATE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _stage_map(config):
    return {stage["name"]: stage for stage in config["stage"]}


def _iter_stages(stages):
    for stage in stages:
        yield stage
        yield from _iter_stages(stage.get("stage", []))


def test_agent_runtime_config_persists_resolved_options_from_cfg(tmp_path):
    cfg = Config(
        {
            "runtime_options": {
                "need_ref_model": True,
                "mock_components_enabled": False,
            }
        }
    )
    cfg._temp_cfg = {"DUT": "Adder", "OUT": "unity_test"}
    runtime_path = save_runtime_config(str(tmp_path), cfg)

    assert runtime_path == tmp_path / ".ucagent" / "runtime_config.json"
    assert json.loads(runtime_path.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "DUT": "Adder",
        "OUT": "unity_test",
        "runtime_options": {
            "need_ref_model": True,
            "mock_components_enabled": False,
        },
    }


@pytest.mark.parametrize("invalid_key", ("need_ref_model", "mock_components_enabled"))
def test_agent_runtime_config_rejects_non_boolean_options(tmp_path, invalid_key):
    cfg = Config(
        {
            "runtime_options": {
                "need_ref_model": True,
                "mock_components_enabled": False,
            }
        }
    )
    setattr(cfg.runtime_options, invalid_key, "true")
    cfg._temp_cfg = {"DUT": "Adder", "OUT": "unity_test"}

    with pytest.raises(ValueError, match=rf"{invalid_key}.*boolean"):
        save_runtime_config(str(tmp_path), cfg)


def test_template_script_reads_cfg_snapshot_instead_of_environment(
    tmp_path, monkeypatch
):
    runtime_path = tmp_path / ".ucagent" / "runtime_config.json"
    runtime_path.parent.mkdir()
    runtime_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "DUT": "Adder",
                "OUT": "unity_test",
                "runtime_options": {
                    "need_ref_model": False,
                    "mock_components_enabled": True,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEED_REF_MODEL", "true")
    monkeypatch.setenv("IGNORE_MOCK_COMPONENT", "true")

    runtime_config = load_runtime_config(str(tmp_path))

    assert runtime_config["runtime_options"] == {
        "need_ref_model": False,
        "mock_components_enabled": True,
    }


def test_runtime_config_excludes_unrelated_cfg_and_secrets(tmp_path):
    cfg = Config(
        {
            "runtime_options": {
                "need_ref_model": False,
                "mock_components_enabled": True,
            },
            "openai": {"openai_api_key": "must-not-be-exported"},
        }
    )
    cfg._temp_cfg = {"DUT": "Adder", "OUT": "unity_test"}

    runtime_path = save_runtime_config(str(tmp_path), cfg)
    snapshot = json.loads(runtime_path.read_text(encoding="utf-8"))

    assert "openai" not in snapshot
    assert "must-not-be-exported" not in runtime_path.read_text(encoding="utf-8")


def test_template_script_main_uses_workspace_runtime_config(tmp_path, monkeypatch):
    module = _load_create_script()
    module.project_root = str(tmp_path)
    runtime_dir = tmp_path / ".ucagent"
    runtime_dir.mkdir()
    (runtime_dir / "runtime_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "DUT": "Adder",
                "OUT": "unity_test",
                "runtime_options": {
                    "need_ref_model": True,
                    "mock_components_enabled": False,
                },
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "unity_test"
    output_dir.mkdir()
    (output_dir / "Adder_functions_and_checks.md").write_text(
        "<FG-ARITH>\n<FC-ADD>\n<CK-NORMAL>\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEED_REF_MODEL", "false")
    monkeypatch.setenv("IGNORE_MOCK_COMPONENT", "false")

    module.main()

    generated = (
        output_dir / "tests/test_Adder_arith.py"
    ).read_text(encoding="utf-8")
    assert "def test_normal(env, ref_model):" in generated
    assert "def test_normal(env):" not in generated


@pytest.mark.parametrize(
    ("need_ref_model", "expected_signature", "unexpected_signature"),
    (
        (False, "def test_normal(env):", "def test_normal(env, ref_model):"),
        (True, "def test_normal(env, ref_model):", "def test_normal(env):"),
    ),
)
def test_template_generator_uses_resolved_reference_model_contract(
    tmp_path, need_ref_model, expected_signature, unexpected_signature
):
    module = _load_create_script()
    module.project_root = str(tmp_path)
    functions = {"FG-ARITH": {"FC-ADD": {"CK-NORMAL": {}}}}

    module.generate_templates(
        "Adder",
        "unity_test",
        functions,
        need_ref_model=need_ref_model,
    )

    generated = (
        tmp_path / "unity_test/tests/test_Adder_arith.py"
    ).read_text(encoding="utf-8")
    assert expected_signature in generated
    assert unexpected_signature not in generated
    assert 'assert False, "Not implemented"' in generated


def test_runtime_options_stay_internal_and_update_checker_contracts(monkeypatch):
    monkeypatch.setenv("NEED_REF_MODEL", "true")
    monkeypatch.setenv("IGNORE_MOCK_COMPONENT", "false")
    config = load_yaml_with_env_vars(str(CONFIG_PATH))
    stages = _stage_map(config)

    assert config["runtime_options"] == {
        "need_ref_model": True,
        "mock_components_enabled": True,
    }

    for stage in _iter_stages(config["stage"]):
        for item in stage.get("task", []):
            if isinstance(item, dict):
                assert "是否已启用参考模型" not in item
                assert "是否已启用Mock组件" not in item

    config_text = CONFIG_PATH.read_text(encoding="utf-8")
    assert "是否已启用参考模型" not in config_text
    assert "是否已启用Mock组件" not in config_text

    create_stage = stages["create_test_case_templates"]
    template_args = next(
        checker["args"]
        for checker in create_stage["checker"]
        if checker["name"] == "template_check"
    )
    assert template_args["args_check"] is True
    assert template_args["args_pattern"] == ["env", "ref_model"]
    assert "args_test_func_prefix" not in template_args

    comprehensive = stages["comprehensive_verification_and_bug_analysis"]
    batch_stage = next(
        stage
        for stage in comprehensive["stage"]
        if stage["name"] == "test_case_implementation_in_batch"
    )
    batch_args = next(
        checker["args"]
        for checker in batch_stage["checker"]
        if checker["name"] == "batch_test_cases_implementation_check"
    )
    assert batch_args["args_check"] is True
    assert batch_args["args_pattern"] == ["env", "ref_model"]

    static_stage = stages["static_bug_validation"]
    static_args = next(
        checker["args"]
        for checker in static_stage["checker"]
        if checker["name"] == "static_confirmed_bugs_test_check"
    )
    assert static_args["args_check"] is True
    assert static_args["args_pattern"] == ["env", "ref_model"]
    assert static_args["args_test_func_prefix"] == "test_static_{DUT}_"


def test_mock_stages_use_dedicated_skill_when_enabled(monkeypatch):
    monkeypatch.setenv("NEED_REF_MODEL", "true")
    monkeypatch.setenv("IGNORE_MOCK_COMPONENT", "false")
    stages = _stage_map(load_yaml_with_env_vars(str(CONFIG_PATH)))
    env_stage = stages["test_environment_implementation"]
    nested = {stage["name"]: stage for stage in env_stage["stage"]}

    for name in ("mock_design_and_implementation", "mock_fixture_implementation"):
        assert nested[name]["ignore"] is False
        assert nested[name]["skill_list"] == ["unitytest/mock-components"]

    mock_parent = nested["mock_functional_test"]
    batch = next(
        stage
        for stage in mock_parent["stage"]
        if stage["name"] == "test_mock_components_in_batch"
    )
    assert batch["ignore"] is False
    assert batch["skill_list"] == ["unitytest/mock-components"]
    checker_args = batch["checker"][0]["args"]
    assert checker_args["first_arg"] == "mock_dut"


def test_unitytest_skills_document_fixture_boundaries():
    create_skill = (SKILL_ROOT / "create-test-case-templates/SKILL.md").read_text(
        encoding="utf-8"
    )
    implementation_skill = (
        SKILL_ROOT / "test-case-implementation-in-batch/SKILL.md"
    ).read_text(encoding="utf-8")
    static_skill = (SKILL_ROOT / "static-bug-validation/SKILL.md").read_text(
        encoding="utf-8"
    )
    mock_skill = (SKILL_ROOT / "mock-components/SKILL.md").read_text(
        encoding="utf-8"
    )

    for skill in (create_skill, implementation_skill, static_skill, mock_skill):
        assert "是否已启用参考模型" not in skill
        assert "是否已启用Mock组件" not in skill
        assert "NEED_REF_MODEL" not in skill
        assert "IGNORE_MOCK_COMPONENT" not in skill
        assert "runtime_options" not in skill

    assert "createtemplate.py" in create_skill
    assert "脚本是可选助手" in create_skill
    assert "内置文本编辑工具创建" in create_skill
    assert "当前批次已经生成的测试模板签名为准" in implementation_skill
    assert "def test_xxx(env, ref_model)" in implementation_skill
    assert "def test_api_{DUT}_mock_xxx(mock_dut)" in implementation_skill
    assert "参考当前工作区已有的普通DUT测试模板" in static_skill
    assert "def test_static_{DUT}_xxx(env, ref_model)" in static_skill
    assert "Mock组件独立单元测试" in static_skill
    assert "普通DUT测试是否包含`ref_model`不改变Mock单元测试签名" in mock_skill
    assert "不调用`mark_function`" in mock_skill
    assert "不调用WaveInfo" in mock_skill
    for protocol_text in (
        "一次`Step(1)`只推进仿真",
        "API内部是否已经",
        "ready/valid",
        "响应latency",
        "单点data mismatch",
    ):
        assert protocol_text in implementation_skill
        assert protocol_text in static_skill
    for viewer_text in (
        "中断或重启后可以复用通过验证的`WaveInfo` receipt",
        "不得删除历史TC/BG",
        "`bug_document_viewer_link`必须由`ApplyWaveInfoEvidence`直接写入",
        "BG位置唯一时工具自动创建尚不存在的兄弟TC",
        "不要再次运行骨架脚本或手工复制BG/TC",
        "同一Fail TC揭示多个独立Bug时",
        "每个精确BG/TC分别调用`ApplyWaveInfoEvidence`",
    ):
        assert viewer_text in implementation_skill
    assert "同一Fail TC证实多个独立动态Bug时" in static_skill
    assert "目标BG/TC之外的Bug记录不会被修改" in static_skill
    assert "单独运行当前静态候选用例时" in static_skill
    assert "最终记录阶段仍需完整测试运行" in static_skill
    assert "CMD API" not in implementation_skill
    assert "CMD API" not in static_skill


def test_default_workflow_is_complete_when_skills_are_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NEED_REF_MODEL", "false")
    monkeypatch.setenv("IGNORE_MOCK_COMPONENT", "true")
    cfg = get_config(config_file=str(CONFIG_PATH))
    config = load_yaml_with_env_vars(str(CONFIG_PATH))
    stages = _stage_map(config)

    assert cfg.skill.use_skill is False
    assert "Skill与其中的脚本只是可选的批量辅助" in config["mission"]["prompt"]["system"]
    assert "只有需要删除大量完整文本行时" in config["mission"]["prompt"]["system"]
    assert (
        "DeleteTextLines(path, line_blocks, expected_sha256)"
        in config["mission"]["prompt"]["system"]
    )
    assert (
        "重新读取缩短后的文件后用`ReplaceStringInFile`"
        in config["mission"]["prompt"]["system"]
    )
    assert all(
        stage.get("force_use_skill") is not True
        for stage in _iter_stages(config["stage"])
    )

    function_task = "\n".join(
        str(item) for item in stages["functional_specification_analysis"]["task"]
    )
    static_task = "\n".join(
        str(item) for item in stages["static_bug_analysis"]["task"]
    )
    template_task = "\n".join(
        str(item) for item in stages["create_test_case_templates"]["task"]
    )
    validation_task = "\n".join(
        str(item) for item in stages["static_bug_validation"]["task"]
    )

    assert "写入不依赖Skill脚本" in function_task
    assert "直接使用文本编辑工具" in static_task
    assert "ReadTextFile读取.ucagent/runtime_config.json" in template_task
    assert "用文本编辑工具直接创建测试模板" in template_task
    assert "LINK回填不依赖linkbug.py" in validation_task
    assert "对已有静态报告使用ReplaceStringInFile" in validation_task
    assert "ReplaceStringInFile或EditTextFile" not in validation_task


def test_disabled_skills_do_not_require_copied_skill_files(tmp_path):
    cfg = SimpleNamespace(
        skill=SimpleNamespace(use_skill=False),
        _temp_cfg={"OUT": "unity_test"},
        hist_ignore_pattern=[],
    )

    stage = VerifyStage(
        cfg=cfg,
        workspace=str(tmp_path),
        name="no_skill_stage",
        description="no skill stage",
        task=["edit the output with built-in tools"],
        checker=[],
        reference_files=[],
        skill_list=["unitytest/not-copied"],
        output_files=[],
    )

    assert stage.skill_list == {}


def test_all_default_workflow_skills_keep_scripts_optional():
    skill_docs = {
        path.parent.name: path.read_text(encoding="utf-8")
        for path in sorted(SKILL_ROOT.glob("*/SKILL.md"))
    }

    assert set(skill_docs) == {
        "create-test-case-templates",
        "functions-and-checks",
        "mock-components",
        "static-bug-analysis",
        "static-bug-validation",
        "test-case-implementation-in-batch",
    }
    for name in (
        "create-test-case-templates",
        "functions-and-checks",
        "static-bug-analysis",
        "static-bug-validation",
        "test-case-implementation-in-batch",
    ):
        assert "文本编辑工具" in skill_docs[name]

    for name in (
        "create-test-case-templates",
        "functions-and-checks",
        "static-bug-analysis",
        "static-bug-validation",
        "test-case-implementation-in-batch",
    ):
        assert "可选" in skill_docs[name]

    assert "RunSkillScript" not in skill_docs["mock-components"]


def test_batch_test_implementation_requires_ck_driven_tests(monkeypatch):
    monkeypatch.setenv("NEED_REF_MODEL", "false")
    monkeypatch.setenv("IGNORE_MOCK_COMPONENT", "true")
    stages = _stage_map(load_yaml_with_env_vars(str(CONFIG_PATH)))
    comprehensive = stages["comprehensive_verification_and_bug_analysis"]
    batch_stage = next(
        stage
        for stage in comprehensive["stage"]
        if stage["name"] == "test_case_implementation_in_batch"
    )

    assert "{OUT}/{DUT}_functions_and_checks.md" in batch_stage["reference_files"]

    task_text = "\n".join(
        item if isinstance(item, str) else "\n".join(map(str, item.items()))
        for item in batch_stage["task"]
    )
    for required_text in (
        "docstring",
        "注释",
        "TASK/TODO",
        "mark_function",
        "{OUT}/{DUT}_functions_and_checks.md",
        "触发前提",
        "状态/时序",
        "边界/异常行为",
        "仅调用API",
        "expected/actual",
        "mark_function本身不等于完成CK验证",
    ):
        assert required_text in task_text

    implementation_skill = (
        SKILL_ROOT / "test-case-implementation-in-batch/SKILL.md"
    ).read_text(encoding="utf-8")
    for required_text in (
        "docstring",
        "`TASK/TODO`",
        "`{OUT}/{DUT}_functions_and_checks.md`",
        "触发前提",
        "状态/时序",
        "边界/异常行为",
        "仅调用API",
        "expected/actual",
        "`mark_function`本身不等于完成CK验证",
        "一次`Step(1)`只推进仿真",
        "禁止API调用后机械地只Step一次",
    ):
        assert required_text in implementation_skill
