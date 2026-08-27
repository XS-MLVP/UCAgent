from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ucagent.util.config import (
    Config,
    get_config,
    load_runtime_config,
    load_yaml_with_env_vars,
    save_runtime_config,
)
from ucagent.stage.vstage import VerifyStage, parse_vstage
from ucagent.tools.skill import (
    ArgsRunSkillScript,
    ListSkill,
    RunSkillScript,
    _get_skill_script_env,
    _scan_skills,
)
from ucagent.util.functions import copytree_incremental


CREATE_SCRIPT = (
    REPO_ROOT
    / "ucagent/lang/zh/skills/unitytest/create-test-case-templates/scripts/createtemplate.py"
)
CONFIG_PATH = REPO_ROOT / "ucagent/lang/zh/config/default.yaml"
INC_CONFIG_PATH = REPO_ROOT / "ucagent/lang/zh/config/inc.yaml"
VIBE_CONFIG_PATH = REPO_ROOT / "ucagent/lang/zh/config/vibe.yaml"
SKILL_ROOT = REPO_ROOT / "ucagent/lang/zh/skills/unitytest"


def _save_runtime_config_for_test(workspace):
    cfg = Config(
        {
            "runtime_options": {
                "need_ref_model": False,
                "mock_components_enabled": False,
            },
            "tools": {"RunTestCases": {"test_dir": "unity_test/tests"}},
        }
    )
    cfg._temp_cfg = {"DUT": "Demo", "OUT": "unity_test"}
    save_runtime_config(str(workspace), cfg)


def _write_test_skill(workspace, scripts):
    skill_dir = workspace / ".ucagent/skills/unitytest/example-skill"
    script_dir = skill_dir / "scripts"
    script_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: example-skill\n"
        "description: Exercise Skill evidence behavior.\n"
        "---\n\n"
        "# Example Skill\n",
        encoding="utf-8",
    )
    for script_name, script_content in scripts.items():
        (script_dir / script_name).write_text(script_content, encoding="utf-8")
    return "unitytest/example-skill"


def _skill_evidence_agent(stage, save_calls):
    manager = SimpleNamespace(
        cfg=SimpleNamespace(get_value=lambda _key, default=None: default),
        get_current_stage=lambda: stage,
        save_stage_info=lambda: save_calls.append(True),
    )
    return SimpleNamespace(stage_manager=manager)


def test_run_skill_script_commands_accept_canonical_array_and_json_fallback():
    commands = [["unitytest/example-skill", "run.py", "--mode verify"]]

    direct = ArgsRunSkillScript.model_validate({"commands": commands})
    serialized = ArgsRunSkillScript.model_validate(
        {"commands": json.dumps(commands)}
    )

    assert direct.commands == commands
    assert serialized.commands == commands


def test_run_skill_script_commands_reject_empty_array():
    with pytest.raises(ValidationError, match="at least 1 item"):
        ArgsRunSkillScript.model_validate({"commands": []})


def test_list_skill_records_and_persists_list_evidence(tmp_path):
    skill_name = _write_test_skill(tmp_path, {})
    stage = VerifyStage.__new__(VerifyStage)
    stage.meta_data = {}
    stage.skill_list = {skill_name: [False, False, False]}
    save_calls = []
    agent = _skill_evidence_agent(stage, save_calls)

    result = ListSkill(workspace=str(tmp_path)).bind(agent)._run()

    assert f"Skill Name: {skill_name}" in result
    assert stage.skill_list[skill_name] == [True, False, False]
    assert save_calls == [True]


def test_successful_skill_script_records_and_persists_use_evidence(tmp_path):
    _save_runtime_config_for_test(tmp_path)
    skill_name = _write_test_skill(tmp_path, {"pass.py": "print('done')\n"})
    stage = VerifyStage.__new__(VerifyStage)
    stage.meta_data = {}
    stage.skill_list = {skill_name: [True, True, False]}
    save_calls = []
    agent = _skill_evidence_agent(stage, save_calls)

    result = RunSkillScript(workspace=str(tmp_path)).bind(agent)._run(
        [[skill_name, "pass.py", ""]]
    )

    assert result == "done\n"
    assert stage.skill_list[skill_name] == [True, True, True]
    assert save_calls == [True]


@pytest.mark.parametrize(
    "commands",
    (
        [["unitytest/example-skill", "fail.py", ""]],
        [
            ["unitytest/example-skill", "pass.py", ""],
            ["unitytest/example-skill", "fail.py", ""],
        ],
    ),
)
def test_failed_or_partial_skill_script_call_does_not_record_use(
    tmp_path, commands
):
    _save_runtime_config_for_test(tmp_path)
    skill_name = _write_test_skill(
        tmp_path,
        {
            "pass.py": "print('done')\n",
            "fail.py": "raise SystemExit(3)\n",
        },
    )
    stage = VerifyStage.__new__(VerifyStage)
    stage.meta_data = {}
    stage.skill_list = {skill_name: [True, True, False]}
    save_calls = []
    agent = _skill_evidence_agent(stage, save_calls)

    result = RunSkillScript(workspace=str(tmp_path)).bind(agent)._run(commands)

    assert "Command failed with exit code 3" in result
    assert stage.skill_list[skill_name] == [True, True, False]
    assert save_calls == []


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


def test_agent_runtime_config_persists_resolved_values_from_cfg(tmp_path):
    cfg = Config(
        {
            "runtime_options": {
                "need_ref_model": True,
                "mock_components_enabled": False,
            },
            "tools": {"RunTestCases": {"test_dir": "custom_tests"}},
        }
    )
    cfg._temp_cfg = {"DUT": "Adder", "OUT": "unity_test"}
    runtime_path = save_runtime_config(str(tmp_path), cfg)

    assert runtime_path == tmp_path / ".ucagent" / "runtime_config.json"
    assert json.loads(runtime_path.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "DUT": "Adder",
        "OUT": "unity_test",
        "test_output_dir": "custom_tests",
        "ucagent_python_path": str(REPO_ROOT),
        "current_test_report": ".ucagent/current_test_report.json",
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
            },
            "tools": {"RunTestCases": {"test_dir": "unity_test/tests"}},
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
                "test_output_dir": "unity_test/tests",
                "ucagent_python_path": str(REPO_ROOT),
                "current_test_report": ".ucagent/current_test_report.json",
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


def test_runtime_config_requires_resolved_test_output_dir(tmp_path):
    runtime_path = tmp_path / ".ucagent" / "runtime_config.json"
    runtime_path.parent.mkdir()
    runtime_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "DUT": "Adder",
                "OUT": "unity_test",
                "ucagent_python_path": str(REPO_ROOT),
                "current_test_report": ".ucagent/current_test_report.json",
                "runtime_options": {
                    "need_ref_model": False,
                    "mock_components_enabled": True,
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="test_output_dir.*non-empty string"):
        load_runtime_config(str(tmp_path))


def test_runtime_config_requires_ucagent_python_path(tmp_path):
    runtime_path = tmp_path / ".ucagent" / "runtime_config.json"
    runtime_path.parent.mkdir()
    runtime_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "DUT": "Adder",
                "OUT": "unity_test",
                "test_output_dir": "unity_test/tests",
                "current_test_report": ".ucagent/current_test_report.json",
                "runtime_options": {
                    "need_ref_model": False,
                    "mock_components_enabled": True,
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="ucagent_python_path.*non-empty string"):
        load_runtime_config(str(tmp_path))


@pytest.mark.parametrize("invalid_path", ("relative/path", "/path/without/ucagent"))
def test_runtime_config_rejects_invalid_ucagent_python_path(
    tmp_path, invalid_path
):
    runtime_path = tmp_path / ".ucagent" / "runtime_config.json"
    runtime_path.parent.mkdir()
    runtime_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "DUT": "Adder",
                "OUT": "unity_test",
                "test_output_dir": "unity_test/tests",
                "ucagent_python_path": invalid_path,
                "current_test_report": ".ucagent/current_test_report.json",
                "runtime_options": {
                    "need_ref_model": False,
                    "mock_components_enabled": True,
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="ucagent_python_path"):
        load_runtime_config(str(tmp_path))


def test_runtime_config_rejects_different_ucagent_installation(tmp_path):
    other_root = tmp_path / "other_install"
    other_package = other_root / "ucagent"
    other_package.mkdir(parents=True)
    (other_package / "__init__.py").write_text("", encoding="utf-8")
    runtime_path = tmp_path / ".ucagent" / "runtime_config.json"
    runtime_path.parent.mkdir()
    runtime_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "DUT": "Adder",
                "OUT": "unity_test",
                "test_output_dir": "unity_test/tests",
                "ucagent_python_path": str(other_root),
                "current_test_report": ".ucagent/current_test_report.json",
                "runtime_options": {
                    "need_ref_model": False,
                    "mock_components_enabled": True,
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="does not match the currently running"):
        load_runtime_config(str(tmp_path))


def test_runtime_config_build_requires_resolved_test_output_dir(tmp_path):
    cfg = Config(
        {
            "runtime_options": {
                "need_ref_model": False,
                "mock_components_enabled": True,
            }
        }
    )
    cfg._temp_cfg = {"DUT": "Adder", "OUT": "unity_test"}

    with pytest.raises(ValueError, match="RunTestCases.test_dir.*non-empty string"):
        save_runtime_config(str(tmp_path), cfg)


def test_runtime_config_excludes_unrelated_cfg_and_secrets(tmp_path):
    cfg = Config(
        {
            "runtime_options": {
                "need_ref_model": False,
                "mock_components_enabled": True,
            },
            "tools": {"RunTestCases": {"test_dir": "unity_test/tests"}},
            "openai": {"openai_api_key": "must-not-be-exported"},
        }
    )
    cfg._temp_cfg = {"DUT": "Adder", "OUT": "unity_test"}

    runtime_path = save_runtime_config(str(tmp_path), cfg)
    snapshot = json.loads(runtime_path.read_text(encoding="utf-8"))

    assert "openai" not in snapshot
    assert "must-not-be-exported" not in runtime_path.read_text(encoding="utf-8")


def test_skill_script_environment_uses_runtime_ucagent_path(
    tmp_path, monkeypatch
):
    cfg = Config(
        {
            "runtime_options": {
                "need_ref_model": False,
                "mock_components_enabled": False,
            },
            "tools": {"RunTestCases": {"test_dir": "unity_test/tests"}},
        }
    )
    cfg._temp_cfg = {"DUT": "Adder", "OUT": "unity_test"}
    save_runtime_config(str(tmp_path), cfg)
    monkeypatch.setenv(
        "PYTHONPATH",
        os.pathsep.join(["/other/import/root", str(REPO_ROOT)]),
    )
    monkeypatch.setenv("DUT", "WrongDut")
    monkeypatch.setenv("OUT", "wrong_output")

    env = _get_skill_script_env(str(tmp_path))

    assert env["PYTHONPATH"].split(os.pathsep) == [
        str(REPO_ROOT),
        "/other/import/root",
    ]
    assert env["DUT"] == "Adder"
    assert env["OUT"] == "unity_test"


def test_run_skill_script_imports_source_ucagent_without_external_pythonpath(
    tmp_path, monkeypatch
):
    cfg = Config(
        {
            "runtime_options": {
                "need_ref_model": False,
                "mock_components_enabled": False,
            },
            "tools": {"RunTestCases": {"test_dir": "unity_test/tests"}},
        }
    )
    cfg._temp_cfg = {"DUT": "Adder", "OUT": "unity_test"}
    save_runtime_config(str(tmp_path), cfg)
    copytree_incremental(
        str(REPO_ROOT / "ucagent/lang/zh/skills"),
        str(tmp_path / ".ucagent/skills"),
        enable_skill_list=["unitytest/functions-and-checks"],
    )
    output_dir = tmp_path / "unity_test"
    output_dir.mkdir()
    target_doc = output_dir / "Adder_functions_and_checks.md"
    target_doc.write_text(
        "# Adder Functions and Checks\n\n## 功能点与检测点\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("PYTHONPATH", raising=False)

    result = RunSkillScript(workspace=str(tmp_path))._run([[
        "unitytest/functions-and-checks",
        "update.py",
        "-MODE FG -ITEMS '[{\"fg\":\"FG-API\",\"desc\":\"API behavior.\"}]'",
    ]])

    assert result == "Inserted 1 FG item(s).\n"
    assert "<FG-API>" in target_doc.read_text(encoding="utf-8")


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
                "test_output_dir": "unity_test/tests",
                "ucagent_python_path": str(REPO_ROOT),
                "current_test_report": ".ucagent/current_test_report.json",
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
    assert template_args["test_func_rules"] == "standard"
    assert template_args["ignore_tc_prefix"] == "test_api_{DUT}_"

    api_args = next(
        checker["args"]
        for checker in stages["basic_api_functional_test"]["checker"]
        if checker["name"] == "api_test_check"
    )
    assert api_args["args_test_func_prefix"] == "test_api_{DUT}_"
    assert api_args["test_func_prefix"] == "test_api_{DUT}_"
    assert api_args["test_func_rules"] == "standard"

    environment = {
        stage["name"]: stage
        for stage in stages["test_environment_implementation"]["stage"]
    }
    env_args = environment["evaluate_env_fixture"]["checker"][1]["args"]
    assert env_args["test_prefix"] == "test_api_{DUT}_env_"
    assert env_args["first_arg"] == "env"

    mock_parent = environment["mock_functional_test"]
    mock_args = next(
        checker["args"] for checker in mock_parent["checker"]
        if checker["clss"] == "UnityChipCheckerTestMustPass"
    )
    assert mock_args["test_prefix"] == "test_api_{DUT}_mock_"
    mock_batch = mock_parent["stage"][0]["checker"][0]["args"]
    assert mock_batch["test_prefix"] == "test_api_{DUT}_mock_"
    assert mock_batch["first_arg"] == "mock_dut"

    reference_args = next(
        checker["args"]
        for checker in stages["reference_model_fixture_imp"]["checker"]
        if checker["clss"] == "UnityChipCheckerTestMustPass"
    )
    assert reference_args["test_prefix"] == (
        "test_api_{DUT}_reference_model_"
    )

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
    assert batch_args["test_func_rules"] == "standard"

    static_stage = stages["static_bug_validation"]
    static_args = next(
        checker["args"]
        for checker in static_stage["checker"]
        if checker["name"] == "static_confirmed_bugs_test_check"
    )
    assert static_args["args_check"] is True
    assert static_args["args_pattern"] == ["env", "ref_model"]
    assert static_args["args_test_func_prefix"] == "test_static_{DUT}_"
    assert static_args["test_func_prefix"] == "test_static_{DUT}_"
    assert static_args["test_func_file"] == (
        "{OUT}/tests/test_{DUT}_static_verify_*.py"
    )
    assert static_args["test_func_rules"] == "standard"

    random_args = next(
        checker["args"]
        for checker in stages["generate_random_test_cases"]["checker"]
        if checker["name"] == "random_test_check"
    )
    assert random_args["args_test_func_prefix"] == "test_random_"
    assert random_args["test_func_prefix"] == "test_random_"
    assert random_args["test_func_rules"] == "standard"

    standard_stage_names = {
        "create_test_case_templates",
        "comprehensive_verification_and_bug_analysis",
        "test_case_implementation_in_batch",
        "refine_test_cases_based_on_functional_points",
        "line_coverage_analysis_and_improvement",
        "verification_review_and_summary",
        "record_and_report_bugs",
    }
    for stage in _iter_stages(config["stage"]):
        if stage["name"] not in standard_stage_names:
            continue
        test_checkers = [
            checker for checker in stage.get("checker", [])
            if checker["clss"] in {
                "UnityChipCheckerTestTemplate",
                "UnityChipCheckerBatchTestsImplementation",
                "UnityChipCheckerTestCase",
                "UnityChipCheckerTestCaseWithLineCoverage",
            }
        ]
        assert test_checkers
        assert all(
            checker["args"].get("test_func_rules") == "standard"
            for checker in test_checkers
        )


def test_incremental_and_vibe_test_stages_keep_naming_contracts():
    incremental = load_yaml_with_env_vars(str(INC_CONFIG_PATH))
    incremental_stages = _stage_map(incremental)
    api_checker = incremental_stages["update_env_and_api_test"]["checker"][0]
    assert api_checker["args"]["test_func_prefix"] == "test_api_{DUT}_"
    assert api_checker["args"]["test_func_rules"] == "standard"

    for stage_name in (
        "update_directed_testing_test_cases",
        "update_random_test_cases",
        "final_verification_and_report",
    ):
        checker = incremental_stages[stage_name]["checker"][0]
        assert checker["args"]["test_func_rules"] == "standard"

    vibe = load_yaml_with_env_vars(str(VIBE_CONFIG_PATH))
    vibe_checker = vibe["stage"][0]["checker"][0]
    assert vibe_checker["args"]["test_func_rules"] == "standard"


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
    assert "第一个阻塞项" in implementation_skill
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
        "由工具创建缺失的兄弟TC、引用和中央记录",
        "不得手工创建另一套BG层级",
        "同一Fail TC揭示多个独立Bug时",
        "为每个BG用相同TC调用一次",
    ):
        assert viewer_text in implementation_skill
    assert "同一Fail TC证实多个独立动态Bug时" in static_skill
    assert "目标BG/TC之外的Bug记录不会被修改" in static_skill
    assert "单独运行当前静态候选用例时" in static_skill
    assert "最终记录阶段仍需完整测试运行" in static_skill
    assert "CMD API" not in implementation_skill
    assert "CMD API" not in static_skill


def test_default_workflow_requires_stage_skills_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NEED_REF_MODEL", "false")
    monkeypatch.setenv("IGNORE_MOCK_COMPONENT", "true")
    cfg = get_config(config_file=str(CONFIG_PATH))
    config = load_yaml_with_env_vars(str(CONFIG_PATH))
    stages = _stage_map(config)

    assert cfg.skill.use_skill is True
    assert cfg.launch.default_args.use_skill is True
    assert "只有Skill启用且当前stage实际配置了非空`skill_list`时" in config["mission"]["prompt"]["system"]
    assert "未配置`skill_list`或其为空时，不调用`SetSkillUsage`" in config["mission"]["prompt"]["system"]
    assert "`general_skill_list`中的通用Skill始终可选" in config["mission"]["prompt"]["system"]
    assert "不能把“脚本可选”误解为整个Skill可跳过" in config["mission"]["prompt"]["system"]
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
        "force_use_skill" not in stage
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
    comprehensive = stages["comprehensive_verification_and_bug_analysis"]
    batch_stage = next(
        stage
        for stage in comprehensive["stage"]
        if stage["name"] == "test_case_implementation_in_batch"
    )

    assert "写入不依赖Skill脚本" in function_task
    assert "直接使用文本编辑工具" in static_task
    assert "ReadTextFile读取.ucagent/runtime_config.json" in template_task
    assert "用文本编辑工具直接创建测试模板" in template_task
    assert "LINK回填不依赖linkbug.py" in validation_task
    assert "对已有静态报告使用ReplaceStringInFile" in validation_task
    assert "ReplaceStringInFile或EditTextFile" not in validation_task
    assert batch_stage["skill_list"] == [
        "unitytest/test-case-implementation-in-batch"
    ]
    assert stages["static_bug_validation"]["skill_list"] == [
        "unitytest/static-bug-validation"
    ]
    for stage_name in (
        "basic_api_functional_test",
        "refine_test_cases_based_on_functional_points",
        "generate_random_test_cases",
        "verification_review_and_summary",
    ):
        assert stages[stage_name]["skill_list"] == [
            "unitytest/dynamic-bug-recording"
        ]


def test_stage_force_use_skill_defaults_true_and_allows_explicit_opt_out(tmp_path):
    cfg = Config({
        "skill": {"use_skill": False},
        "hist_ignore_pattern": [],
        "stage": [
            {
                "name": "required_by_default",
                "desc": "required",
                "task": [],
                "skill_list": ["unitytest/not-copied"],
            },
            {
                "name": "explicitly_optional",
                "desc": "optional",
                "task": [],
                "skill_list": ["unitytest/not-copied"],
                "force_use_skill": False,
            },
        ],
    })
    cfg._temp_cfg = {"OUT": "unity_test"}

    stages = parse_vstage(cfg, cfg.stage, str(tmp_path), None)

    assert [(stage.name, stage.force_use_skill) for stage in stages] == [
        ("required_by_default", True),
        ("explicitly_optional", False),
    ]
    assert all(stage.skill_list == {} for stage in stages)


@pytest.mark.parametrize("invalid_value", (None, "false", 0))
def test_stage_force_use_skill_rejects_non_boolean_values(tmp_path, invalid_value):
    cfg = Config({
        "skill": {"use_skill": False},
        "hist_ignore_pattern": [],
        "stage": [{
            "name": "invalid_force_value",
            "desc": "invalid",
            "task": [],
            "force_use_skill": invalid_value,
        }],
    })
    cfg._temp_cfg = {"OUT": "unity_test"}

    with pytest.raises(ValueError, match="force_use_skill must be a boolean"):
        parse_vstage(cfg, cfg.stage, str(tmp_path), None)


def test_enabled_stage_skill_default_blocks_complete_but_explicit_opt_out_does_not(
    tmp_path,
):
    skill_dir = tmp_path / ".ucagent" / "skills" / "unitytest" / "example"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: example\ndescription: example method\n---\n\n# Example\n",
        encoding="utf-8",
    )
    cfg = Config({
        "skill": {"use_skill": True},
        "hist_ignore_pattern": [],
        "stage": [
            {
                "name": "required_by_default",
                "desc": "required",
                "task": [],
                "skill_list": ["unitytest/example"],
            },
            {
                "name": "explicitly_optional",
                "desc": "optional",
                "task": [],
                "skill_list": ["unitytest/example"],
                "force_use_skill": False,
            },
        ],
    })
    cfg._temp_cfg = {"OUT": "unity_test"}
    required_stage, optional_stage = parse_vstage(
        cfg, cfg.stage, str(tmp_path), None
    )

    required_passed, required_info = required_stage._do_check(is_complete=True)
    optional_passed, _optional_info = optional_stage._do_check(is_complete=True)

    assert required_passed is False
    assert required_info[0]["last_msg"]["diagnostic"]["error_code"] == (
        "SKILL_USAGE_INCOMPLETE"
    )
    assert optional_passed is True


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
    assert stage.force_use_skill is True
    original_task = stage.task()
    stage.on_init()
    assert stage.task() == original_task
    assert "-MODE repair" not in "\n".join(stage.task())
    passed, _check_info = stage._do_check(is_complete=True)
    assert passed is True


def test_dynamic_bug_skill_hook_owns_only_the_dynamic_bug_document(tmp_path):
    source = SKILL_ROOT / "dynamic-bug-recording"
    destination = (
        tmp_path
        / ".ucagent/skills/unitytest/dynamic-bug-recording"
    )
    copytree_incremental(str(source), str(destination))
    cfg = SimpleNamespace(
        skill=SimpleNamespace(use_skill=True),
        _temp_cfg={"OUT": "unity_test", "DUT": "Adder"},
        hist_ignore_pattern=[],
    )
    original_task = [
        "edit tests normally",
        "update the functions-and-checks document with normal tools",
    ]
    stage = VerifyStage(
        cfg=cfg,
        workspace=str(tmp_path),
        name="dynamic_bug_stage",
        description="record dynamic bugs",
        task=original_task,
        checker=[],
        reference_files=[],
        skill_list=["unitytest/dynamic-bug-recording"],
        output_files=[],
    )

    assert stage.task() == original_task
    stage.on_init()
    hooked_task = stage.task()

    assert hooked_task[:2] == original_task
    assert len(hooked_task) == 3
    policy = hooked_task[-1]
    assert "`unity_test/Adder_bug_analysis.md`" in policy
    assert "{OUT}" not in policy
    assert "其他文档和代码仍使用" in policy
    assert "优先维护策略" in policy
    assert "尽可能使用当前 Skill" in policy
    assert "-MODE repair" in policy
    assert "-MODE bug" in policy
    assert "-MODE root" in policy
    assert "相同阻塞仍存在" in policy
    assert "manual_edit_fallback.allowed=true" in policy
    assert "precondition" in policy
    assert "after_edit" in policy
    assert "workflow_context.remaining_sequence" in policy
    assert "禁止使用" not in policy
    assert "不得绕过 Skill" not in policy


def test_all_default_workflow_skills_keep_scripts_optional():
    skill_docs = {
        path.parent.name: path.read_text(encoding="utf-8")
        for path in sorted(SKILL_ROOT.glob("*/SKILL.md"))
    }

    assert set(skill_docs) == {
        "create-test-case-templates",
        "dynamic-bug-recording",
        "functions-and-checks",
        "mock-components",
        "static-bug-analysis",
        "static-bug-validation",
        "test-case-implementation-in-batch",
    }
    for name in (
        "create-test-case-templates",
        "dynamic-bug-recording",
        "functions-and-checks",
        "static-bug-analysis",
        "static-bug-validation",
        "test-case-implementation-in-batch",
    ):
        assert "文本编辑工具" in skill_docs[name]

    for name in (
        "create-test-case-templates",
        "dynamic-bug-recording",
        "functions-and-checks",
        "static-bug-analysis",
        "static-bug-validation",
        "test-case-implementation-in-batch",
    ):
        assert "可选" in skill_docs[name]

    assert "RunSkillScript" not in skill_docs["mock-components"]

    assert "record_dynamic_bug.py" in skill_docs["dynamic-bug-recording"]
    assert "record_static_bug.py" in skill_docs["static-bug-analysis"]
    assert "current_batch_progress_markers" in skill_docs["static-bug-analysis"]
    assert '<file sha256="CURRENT_SHA256">' in skill_docs["static-bug-analysis"]
    assert "ucagent_python_path" in skill_docs["functions-and-checks"]
    assert "python3 script" not in skill_docs["functions-and-checks"]
    assert '["unitytest/functions-and-checks", "update.py"' in skill_docs[
        "functions-and-checks"
    ]
    assert "unitytest/dynamic-bug-recording" in skill_docs[
        "test-case-implementation-in-batch"
    ]
    assert "unitytest/dynamic-bug-recording" in skill_docs[
        "static-bug-validation"
    ]


def test_shared_dynamic_bug_skill_is_copied_and_discoverable(tmp_path):
    source_root = REPO_ROOT / "ucagent/lang/zh/skills"
    workspace_skill_root = tmp_path / ".ucagent/skills"

    copytree_incremental(str(source_root), str(workspace_skill_root))
    skills = {skill["name"]: skill for skill in _scan_skills(str(tmp_path))}

    assert "unitytest/dynamic-bug-recording" in skills
    assert skills["unitytest/dynamic-bug-recording"]["script"] == {
        "record_dynamic_bug.py": (
            ".ucagent/skills/unitytest/dynamic-bug-recording/"
            "scripts/record_dynamic_bug.py"
        )
    }


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
