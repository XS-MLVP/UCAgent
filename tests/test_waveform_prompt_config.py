"""Dynamic Bug waveform requirements in the default Chinese mission prompt."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ucagent.util.config import load_yaml_with_env_vars


def test_default_prompt_requires_waveinfo_for_dynamic_bugs():
    config_path = (
        Path(__file__).parents[1] / "ucagent/lang/zh/config/default.yaml"
    )
    config = load_yaml_with_env_vars(str(config_path))
    system_prompt = config["mission"]["prompt"]["system"]
    parent_stage = next(
        stage
        for stage in config["stage"]
        if stage["name"] == "comprehensive_verification_and_bug_analysis"
    )
    parent_task = "\n".join(str(item) for item in parent_stage["task"])
    batch_stage = next(
        stage
        for stage in parent_stage["stage"]
        if stage["name"] == "test_case_implementation_in_batch"
    )
    batch_task = "\n".join(str(item) for item in batch_stage["task"])

    assert "必须调用`WaveInfo`" in system_prompt
    assert "不得豁免动态Bug的`WaveInfo`取证" in system_prompt
    assert "不能伪造receipt" in system_prompt
    assert 'WaveInfo(test_case_name="test_{DUT}_xxx"' in system_prompt
    assert "signal_catalog中确实存在时使用" in system_prompt
    assert "receipt会签名持久化" in system_prompt
    assert "不需要重新调用WaveInfo或重写所有<WAVEFORM-ANALYSIS>" in system_prompt
    assert "status: evidence_window_required" in system_prompt
    assert "recommended_evidence_call" in system_prompt
    assert "不能把`analysis_window.effective_start_step/effective_end_step`" in system_prompt
    assert "最终显式窗口调用必须同时传非负start_step和end_step" in system_prompt
    assert "优先复制返回的`bug_document_fields`" in system_prompt
    assert "不能直接复制静态Bug标签" in parent_task
    assert "无可用波形时" in parent_task
    assert "除已确认DUT Bug复现用例外，其他用例必须全部Pass" in parent_task
    assert "不是要求已确认Bug用例也Pass" in parent_task
    assert "不得以测试Bug或BG-*-0占位保留Fail" in batch_task
    assert "任何未分类Fail" in batch_task


def test_system_prompt_distinguishes_infrastructure_and_dut_bug_failures():
    config_path = (
        Path(__file__).parents[1] / "ucagent/lang/zh/config/default.yaml"
    )
    config = load_yaml_with_env_vars(str(config_path))
    system_prompt = config["mission"]["prompt"]["system"]

    assert "除已确认DUT Bug的复现用例外，其他用例全部Pass" in system_prompt
    assert "这些问题必须修复后重跑到Pass" in system_prompt
    assert "不能以“测试Bug”、assert False或<BG-*-0>占位保留Fail" in system_prompt
    assert "create_test_case_templates`模板构建阶段是明确例外" in system_prompt
    assert "所有尚未实现的测试模板都必须以`assert False" in system_prompt
    assert "模板Fail仅表示“尚未实现”，不作为DUT Bug" in system_prompt
    assert "只验证测试框架/API调用链自身且不以DUT功能输出为判定对象" in system_prompt
    assert "包括API功能测试、综合验证、静态Bug动态验证和随机验证" in system_prompt
    assert "确认复现DUT Bug，则必须保持Fail并完整取证" in system_prompt


def test_bug_analysis_guide_distinguishes_mcp_sentinels_and_evidence_windows():
    guide_path = (
        Path(__file__).parents[1]
        / "ucagent/lang/zh/doc/Guide_Doc/dut_bug_analysis.md"
    )
    guide = guide_path.read_text(encoding="utf-8")

    assert "canonical 表示" in guide
    assert "status: evidence_window_required" in guide
    assert "必须逐字使用 `recommended_evidence_call`" in guide
    assert "不能把 `effective_start_step/effective_end_step` 手工复制" in guide
    assert "`start_step` 和 `end_step` 必须同时提供" in guide
    assert "成功的最终取证返回会包含 `bug_document_fields`" in guide


def test_waveform_checker_is_available_before_dynamic_test_checkers():
    config_path = (
        Path(__file__).parents[1] / "ucagent/lang/zh/config/default.yaml"
    )
    config = load_yaml_with_env_vars(str(config_path))

    stages = {stage["name"]: stage for stage in config["stage"]}
    comprehensive = stages["comprehensive_verification_and_bug_analysis"]
    nested = {
        stage["name"]: stage for stage in comprehensive.get("stage", [])
    }
    expected_stages = {
        "comprehensive_verification_and_bug_analysis": "UnityChipCheckerTestCase",
        "test_case_implementation_in_batch": "UnityChipCheckerBatchTestsImplementation",
        "refine_test_cases_based_on_functional_points": "UnityChipCheckerTestCase",
        "verification_review_and_summary": "UnityChipCheckerTestCase",
    }

    for name, downstream_checker in expected_stages.items():
        stage = (
            comprehensive
            if name == "comprehensive_verification_and_bug_analysis"
            else stages[name]
            if name in stages
            else nested[name]
        )
        checker_names = [item["clss"] for item in stage.get("checker", [])]
        assert "UnityChipCheckerWaveformBugAnalysis" in checker_names
        assert checker_names.index("UnityChipCheckerWaveformBugAnalysis") < checker_names.index(
            downstream_checker
        )

    for name in (
        "static_bug_validation",
        "line_coverage_analysis_and_improvement",
        "generate_random_test_cases",
    ):
        stage = stages[name]
        assert "UnityChipCheckerWaveformBugAnalysis" not in [
            item["clss"] for item in stage.get("checker", [])
        ]
