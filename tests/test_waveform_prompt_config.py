"""Dynamic Bug waveform requirements in the default Chinese mission prompt."""

from pathlib import Path
import re
import sys
import textwrap

import yaml

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
    review_stage = next(
        stage
        for stage in config["stage"]
        if stage["name"] == "verification_review_and_summary"
    )
    review_task = "\n".join(str(item) for item in review_stage["task"])
    static_stage = next(
        stage for stage in config["stage"] if stage["name"] == "static_bug_analysis"
    )
    static_task = "\n".join(str(item) for item in static_stage["task"])
    static_validation_stage = next(
        stage for stage in config["stage"] if stage["name"] == "static_bug_validation"
    )
    static_validation_task = "\n".join(
        str(item) for item in static_validation_stage["task"]
    )

    assert "必须调用`WaveInfo`" in system_prompt
    assert "不得豁免动态Bug的`WaveInfo`取证" in system_prompt
    assert "不能伪造receipt" in system_prompt
    assert 'WaveInfo(test_case_name="test_{DUT}_xxx"' in system_prompt
    assert "signal_catalog中确实存在时使用" in system_prompt
    assert "receipt会签名持久化" in system_prompt
    assert "不需要重新调用WaveInfo或重写所有waveform_analysis YAML块" in system_prompt
    assert "status: evidence_window_required" in system_prompt
    assert "recommended_evidence_call" in system_prompt
    assert "不能把`analysis_window.effective_start_step/effective_end_step`" in system_prompt
    assert "最终显式窗口调用必须同时传非负start_step和end_step" in system_prompt
    assert "将返回的`bug_document_fields`作为```yaml代码块的完整映射" in system_prompt
    assert "它已包含唯一顶层键waveform_analysis，不要再包一层" in system_prompt
    assert "必须集中在对应<BG-*>条目内" in system_prompt
    assert "不得在文档末尾另建与标签分离的全局根因分析章节" in system_prompt
    assert "recordbug.py`只生成带`<BUG-TODO>`" in system_prompt
    assert "Checker不解析“待补充”等自然语言占位词" in system_prompt
    assert "<BUG-SOURCE-FIRST-ERROR>" in system_prompt
    assert "<BUG-SOURCE-PROPAGATION>" in system_prompt
    assert "<BUG-SOURCE-OBSERVABLE>" in system_prompt
    assert "旧`-ROOT/-FILE/-FIX`参数已删除" in system_prompt
    assert "都不能通过Check/Complete" in system_prompt
    assert "不能直接复制静态Bug标签" in parent_task
    assert "无可用波形时" in parent_task
    assert "除已确认DUT Bug复现用例外，其他用例必须全部Pass" in parent_task
    assert "不是要求已确认Bug用例也Pass" in parent_task
    assert "不得以测试Bug或BG-*-0占位保留Fail" in batch_task
    assert "任何未分类Fail" in batch_task
    assert "recordbug.py只接收BG/TC/BD并生成含`<BUG-TODO>`" in batch_task
    assert "脚本成功当成分析完成" in batch_task
    assert "逐个审查{OUT}/{DUT}_bug_analysis.md中的每个非零置信度<BG-*>" in review_task
    assert "独立核对<BUG-SOURCE-FIRST-ERROR>是否为首个错误决策" in review_task
    assert "不得因recordbug.py成功、字段非空或Checker尚未报错" in review_task
    assert "禁止通过删除<TC-*>、<BG-*>或整个FG/FC/CK分支" in batch_task
    for marker in (
        "<STATIC-BUG-SUMMARY>",
        "<STATIC-BUG-DETAILS>",
        "<STATIC-BUG-PROGRESS>",
    ):
        assert marker in static_task
        assert marker in static_validation_task
    assert "Skill脚本和Checker不解析中文标题" in static_task
    assert "linkbug.py和Checker不解析中文标题" in static_validation_task


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
    assert "```yaml" in guide
    assert "`waveform_analysis:` 必须是唯一顶层键" in guide
    assert "不再使用 `<WAVEFORM-ANALYSIS>` 自定义标签" in guide
    assert "省略了每个 `<TC-*>` 后的波形块" not in guide
    clock_call = guide.split("时钟对齐最终调用示例：", 1)[1].split(
        "显式时间窗最终调用示例：", 1
    )[0]
    assert clock_call.count("context_steps=1") == 1


def test_bug_document_error_help_uses_current_machine_contract():
    from ucagent.util.functions import description_bug_doc

    help_text = "\n".join(description_bug_doc())
    for marker in (
        "<DYNAMIC-BUGS>",
        "<BUG-OVERVIEW>",
        "<BUG-SYMPTOMS>",
        "<BUG-TRIGGER>",
        "<BUG-ROOT-CAUSE>",
        "<BUG-SOURCE-EVIDENCE>",
        "<BUG-CAUSAL-CHAIN>",
        "<BUG-FIX>",
        "<BUG-RETEST>",
        "<BUG-TODO>",
        "<BUG-SOURCE-FIRST-ERROR>",
        "<BUG-SOURCE-PROPAGATION>",
        "<BUG-SOURCE-OBSERVABLE>",
        "<BUG-SOURCE-UNAVAILABLE>",
    ):
        assert marker in help_text
    assert "```yaml" in help_text
    assert "waveform_analysis" in help_text
    assert "complete WaveInfo bug_document_fields" in help_text
    assert "alignment_evidence, observed_behavior, source_correlation" in help_text
    assert "Do not invent or copy example receipt values" in help_text
    assert "complete HDL fenced block containing each marker" in help_text
    assert "This branch cannot contain an HDL fence" in help_text
    assert "Display headings are optional/localizable and are not parsed" in help_text
    assert "Root cause analysis inside this BG entry" not in help_text
    assert "receipt_id: <real WaveInfo receipt_id>" not in help_text
    assert "Adder.v line 10" not in help_text


def _assert_test_tags_cascade_to_waveform_yaml(example: str) -> None:
    lines = example.splitlines()
    test_lines = [
        index
        for index, line in enumerate(lines)
        if re.search(r"<TC-(?!\*)[^<>]+>", line)
    ]
    assert test_lines
    for test_line in test_lines:
        fence_line = next(
            index
            for index in range(test_line + 1, len(lines))
            if lines[index].strip()
        )
        assert lines[fence_line].strip() == "```yaml"
        closing_line = next(
            index
            for index in range(fence_line + 1, len(lines))
            if lines[index].strip() == "```"
        )
        payload = yaml.safe_load(
            textwrap.dedent("\n".join(lines[fence_line + 1 : closing_line]))
        )
        assert set(payload) == {"waveform_analysis"}
        analysis = payload["waveform_analysis"]
        assert analysis["status"] == "confirmed"
        common_fields = {
            "receipt_id",
            "result_fingerprint",
            "waveform_file",
            "freshness_identity",
            "size_bytes",
            "session_started_at",
            "modified_at",
            "modified_time_ns",
            "observed_at",
            "analysis_mode",
            "pattern",
            "context_steps",
            "max_points",
            "wave_step",
            "timeline_truncated",
            "alignment_evidence",
            "observed_behavior",
            "source_correlation",
        }
        assert common_fields <= set(analysis)
        if analysis["analysis_mode"] == "clock_aligned":
            assert {
                "logged_cycle",
                "cycle_tolerance",
                "clock_signal",
                "clock_edge",
                "cycle_origin",
                "clock_occurrence_index",
                "cycle_delta",
            } <= set(analysis)
        else:
            assert analysis["analysis_mode"] == "explicit_window"
            assert {"start_step", "end_step"} <= set(analysis)


def test_bug_analysis_guide_examples_cascade_fenced_waveform_blocks_from_tests():
    guide_path = (
        Path(__file__).parents[1]
        / "ucagent/lang/zh/doc/Guide_Doc/dut_bug_analysis.md"
    )
    guide = guide_path.read_text(encoding="utf-8")
    bug_example = guide.split("### Bug条目示例", 1)[1].split(
        "### 标签与字段书写要点", 1
    )[0]
    static_validation_example = guide.split(
        "**阶段三：`{DUT}_bug_analysis.md` 中对应的动态Bug记录**", 1
    )[1].split("### 7.4 全部文件都没有发现静态 Bug", 1)[0]

    _assert_test_tags_cascade_to_waveform_yaml(bug_example)
    _assert_test_tags_cascade_to_waveform_yaml(static_validation_example)


def test_bug_analysis_guide_documents_all_checker_markers_and_colocates_analysis():
    guide_path = (
        Path(__file__).parents[1]
        / "ucagent/lang/zh/doc/Guide_Doc/dut_bug_analysis.md"
    )
    guide = guide_path.read_text(encoding="utf-8")

    required_markers = (
        "<FG-NAME>",
        "<FC-NAME>",
        "<CK-NAME>",
        "<DYNAMIC-BUGS>",
        "<BG-NAME-XX>",
        "<TC-test_file.py::test_name>",
        "waveform_analysis",
        "<BG-STATIC-NNN-NAME>",
        "<LINK-BUG-[BG-TBD]>",
        "<LINK-BUG-[BG-NAME-XX]>",
        "<LINK-BUG-[BG-NA]>",
        "<FILE-path/to/file.v:L1-L2>",
        "<FG-NULL>/<FC-NULL>/<CK-NULL>/<BG-STATIC-NULL>",
        "<file>path/to/file.v</file>",
        "<BUG-OVERVIEW>",
        "<BUG-SYMPTOMS>",
        "<BUG-TRIGGER>",
        "<BUG-ROOT-CAUSE>",
        "<BUG-SOURCE-EVIDENCE>",
        "<BUG-CAUSAL-CHAIN>",
        "<BUG-FIX>",
        "<BUG-RETEST>",
        "<BUG-TODO>",
        "<BUG-SOURCE-UNAVAILABLE>",
        "<BUG-SOURCE-FIRST-ERROR>",
        "<BUG-SOURCE-PROPAGATION>",
        "<BUG-SOURCE-OBSERVABLE>",
        "<STATIC-BUG-SUMMARY>",
        "<STATIC-BUG-DETAILS>",
        "<STATIC-BUG-PROGRESS>",
    )
    for marker in required_markers:
        assert marker in guide

    bug_example = guide.split("### Bug条目示例", 1)[1].split(
        "### 标签与字段书写要点", 1
    )[0]
    for section in (
        "**Bug 概述**",
        "**现象与等级**",
        "**复现用例与波形证据**",
        "**触发条件与影响范围**",
        "**根因分析**",
        "**源码证据与逐行分析**",
        "**动态因果链**",
        "**修复建议**",
        "**风险与复验计划**",
    ):
        assert section in bug_example
    assert bug_example.index("**Bug 概述**") < bug_example.index(
        "**源码证据与逐行分析**"
    )
    assert "<BUG-SOURCE-FIRST-ERROR>" in bug_example
    assert "<BUG-SOURCE-PROPAGATION>" in bug_example
    assert "<BUG-SOURCE-OBSERVABLE>" in bug_example
    assert "有可访问源码时，根因分析必须包含源码代码块" in guide
    assert "<BUG-SOURCE-UNAVAILABLE>" in guide
    assert "## 缺陷根因分析" not in guide
    assert "不要在文档末尾再建立一个与 BG 标签分离的“根因分析汇总”" in guide


def test_bug_analysis_guide_examples_embed_annotated_source_after_overview():
    guide_path = (
        Path(__file__).parents[1]
        / "ucagent/lang/zh/doc/Guide_Doc/dut_bug_analysis.md"
    )
    guide = guide_path.read_text(encoding="utf-8")
    dynamic_example = guide.split("### Bug条目示例", 1)[1].split(
        "### 标签与字段书写要点", 1
    )[0]
    static_example = guide.split("### 7.2 static_bug_analysis 阶段示例", 1)[1].split(
        "### 7.3 static_bug_validation 阶段如何更新 LINK", 1
    )[0]
    confirmed_example = guide.split(
        "**阶段三：`{DUT}_bug_analysis.md` 中对应的动态Bug记录**", 1
    )[1].split("### 7.4 全部文件都没有发现静态 Bug", 1)[0]

    assert dynamic_example.index("**Bug 概述**") < dynamic_example.index(
        "**源码证据与逐行分析**"
    ) < dynamic_example.index("**动态因果链**")
    assert static_example.index("**候选概述**") < static_example.index(
        "**源码证据与逐行分析**"
    ) < static_example.index("**静态因果链**")
    assert confirmed_example.index("**Bug 概述**") < confirmed_example.index(
        "**源码证据与逐行分析**"
    ) < confirmed_example.index("**动态因果链**")

    for example in (dynamic_example, static_example, confirmed_example):
        assert "<BUG-SOURCE-FIRST-ERROR>" in example
        assert "<BUG-SOURCE-PROPAGATION>" in example
        assert "<BUG-SOURCE-OBSERVABLE>" in example
    assert "UartTx.v:50-56" not in guide


def test_dynamic_bug_template_does_not_split_root_cause_from_bug_entries():
    template_path = (
        Path(__file__).parents[1]
        / "ucagent/lang/zh/template/unity_test/{{DUT}}_bug_analysis.md"
    )
    template = template_path.read_text(encoding="utf-8")

    assert template.startswith("# {{DUT}} 动态 Bug 分析")
    assert "<DYNAMIC-BUGS>" in template
    assert "## 未测试通过检测点分析" in template
    assert "## 缺陷根因分析" not in template


def test_bug_analysis_guide_requires_skill_scaffold_completion():
    guide_path = (
        Path(__file__).parents[1]
        / "ucagent/lang/zh/doc/Guide_Doc/dut_bug_analysis.md"
    )
    guide = guide_path.read_text(encoding="utf-8")

    assert "Skill 模式的两阶段写入" in guide
    assert "脚本成功不代表分析完成" in guide
    assert "旧 `-ROOT/-FILE/-FIX` 参数已经删除" in guide
    assert "替换所有 `<BUG-TODO>`" in guide
    assert "Checker 会逐个非零 BG 拒绝残留 `<BUG-TODO>`" in guide


def test_dynamic_test_classification_precedes_global_waveform_sweep():
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
        "basic_api_functional_test": "UnityChipCheckerDutApiTest",
        "comprehensive_verification_and_bug_analysis": "UnityChipCheckerTestCase",
        "test_case_implementation_in_batch": "UnityChipCheckerBatchTestsImplementation",
        "refine_test_cases_based_on_functional_points": "UnityChipCheckerTestCase",
        "verification_review_and_summary": "UnityChipCheckerTestCase",
        "record_and_report_bugs": "UnityChipCheckerTestCase",
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
        assert checker_names.index(downstream_checker) < checker_names.index(
            "UnityChipCheckerWaveformBugAnalysis"
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
