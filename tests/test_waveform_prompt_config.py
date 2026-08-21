"""Dynamic Bug waveform requirements in the default Chinese mission prompt."""

from pathlib import Path
import re
import sys
import textwrap

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ucagent.util.config import load_yaml_with_env_vars
from ucagent.util.waveform_viewer import decode_waveform_viewer_token


def test_api_test_prompt_and_guide_require_api_checkpoint_association():
    repo_root = Path(__file__).parents[1]
    config = load_yaml_with_env_vars(
        str(repo_root / "ucagent/lang/zh/config/default.yaml")
    )
    stage = next(
        item for item in config["stage"]
        if item["name"] == "basic_api_functional_test"
    )
    task = "\n".join(str(item) for item in stage["task"])
    checker = next(
        item for item in stage["checker"]
        if item["clss"] == "UnityChipCheckerDutApiTest"
    )
    guide = (
        repo_root / "ucagent/lang/zh/doc/Guide_Doc/dut_api_instruction.md"
    ).read_text(encoding="utf-8")

    assert "每个API测试函数都必须在函数开头添加对应API分组CK" in task
    assert "不能只mark其他功能分组CK" in task
    assert "额外功能CK不能替代" in task
    assert "不能为通过Checker而批量标记无关API CK" in task
    assert checker["args"]["api_ck_prefix"] == "FG-API/"

    assert "API 检查点关联（必需）" in guide
    assert "不能由其他功能分组的 CK 替代" in guide
    assert "这些非 API 分组关联是可选项" in guide
    assert "不要为了通过 Checker 而把所有 API CK 批量标记" in guide
    assert 'fc_cover["FG-API"].mark_function' in guide
    assert 'fc_cover["FG-ARITHMETIC"].mark_function' in guide


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
    template_stage = next(
        stage
        for stage in config["stage"]
        if stage["name"] == "create_test_case_templates"
    )
    template_task = "\n".join(str(item) for item in template_stage["task"])

    assert "必须调用`WaveInfo`" in system_prompt
    assert "不得豁免动态Bug的`WaveInfo`取证" in system_prompt
    assert "不能伪造receipt" in system_prompt
    assert 'WaveInfo(test_case_name="test_{DUT}_xxx"' in system_prompt
    assert "signal_catalog中确实存在时使用" in system_prompt
    assert "可以直接复用文档中通过验证的receipt_id" in system_prompt
    assert "任务中途只运行部分用例时" in system_prompt
    assert "最终record_and_report_bugs阶段必须先运行完整DUT测试集合" in system_prompt
    assert "CMD API" not in system_prompt
    assert "v2 token" not in system_prompt
    assert "不需要重新调用WaveInfo或重写所有waveform_analysis YAML块" in system_prompt
    assert "status: evidence_window_required" in system_prompt
    assert "recommended_evidence_call" in system_prompt
    assert "不能把`analysis_window.effective_start_step/effective_end_step`" in system_prompt
    assert "最终显式窗口调用必须同时传非负start_step和end_step" in system_prompt
    assert "ApplyWaveInfoEvidence(target_file=..., bug_tag=..., test_case_tag=..., receipt_id=...)" in system_prompt
    assert "同一BG有多个Fail TC时，每个TC分别调用一次" in system_prompt
    assert "目标TC不存在且该BG位置唯一时，工具自动创建TC" in system_prompt
    assert "不得手工复制BG或兄弟TC" in system_prompt
    assert "已有兄弟TC证据会保留且不需要replace_existing" in system_prompt
    assert "同一Fail TC揭示多个独立Bug时" in system_prompt
    assert "使用不同bug_tag和相同test_case_tag分别调用" in system_prompt
    assert "其他BG和兄弟TC证据都会保留" in system_prompt
    assert "LLM不得复制、拼接或手工修改receipt" in system_prompt
    assert "若脚本不可用，则用文本编辑工具" in system_prompt
    assert "第6.1.1节的最小骨架示例" in system_prompt
    assert "必须集中在对应<BG-*>条目内" in system_prompt
    assert "不得在文档末尾另建与标签分离的全局根因分析章节" in system_prompt
    assert "脚本只为新Bug生成第一份带`<BUG-TODO>`" in system_prompt
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
    assert "record_dynamic_bug.py可用" in batch_task
    assert "脚本不可用" in batch_task
    assert "机器证据写入成功当成分析完成" in batch_task
    assert "逐个审查{OUT}/{DUT}_bug_analysis.md中的每个非零置信度<BG-*>" in review_task
    assert "独立核对<BUG-SOURCE-FIRST-ERROR>是否为首个错误决策" in review_task
    assert "不得因record_dynamic_bug.py成功、字段非空或Checker尚未报错" in review_task
    assert "禁止通过删除<TC-*>、<BG-*>或整个FG/FC/CK分支" in batch_task
    assert "一次`Step(1)`只表示仿真推进一步" in system_prompt
    assert "不能由Checker按固定信号名自动推断" in system_prompt
    assert "最终WaveInfo取证不能只查看发生不一致的目标data" in system_prompt
    assert "`pattern`只负责定位事件" in system_prompt
    assert "同一组真实完整路径必须进入timeline、签名receipt和在线viewer" in system_prompt
    assert "`protocol`仅在规格和接口确认没有" in system_prompt
    assert "已提供的{OUT}/tests/{DUT}_api.py" in system_prompt
    assert "只有最早traceback和对应源码共同证明基础设施本身有缺陷" in system_prompt
    assert "是已提供的只读基础设施契约" in template_task
    assert "禁止改动API、create_dut、dut/env fixture" in template_task
    assert "不得删除mark_function、改成空覆盖组、绕过fixture" in template_task
    assert "ready/valid或等价接受条件" in batch_task
    assert "禁止API调用后机械地Step一次就断言data" in batch_task
    assert "协议无效窗口或任意单点data mismatch" in static_validation_task
    assert "observed_behavior是否只在协议允许的响应采样窗口" in review_task
    assert "signal_groups和在线viewer是否同时包含时钟" in review_task
    assert "最终WaveInfo调用必须填写完整signal_groups" in batch_task
    for marker in (
        "<STATIC-BUG-SUMMARY>",
        "<STATIC-BUG-DETAILS>",
        "<STATIC-BUG-PROGRESS>",
    ):
        assert marker in static_task
        assert marker in static_validation_task
    assert "Checker不解析中文标题" in static_task
    assert "Checker不解析中文标题" in static_validation_task
    assert "LINK回填不依赖linkbug.py" in static_validation_task


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
    assert "不得为了绕过fixture、fake DUT、mark_function或覆盖率错误" in system_prompt


def test_fixture_guidance_is_consistent_across_runtime_docs_and_skills():
    root = Path(__file__).parents[1]
    template_guide = (
        root / "ucagent/lang/zh/doc/Guide_Doc/dut_test_template.md"
    ).read_text(encoding="utf-8")
    fixture_guide = (
        root / "ucagent/lang/zh/doc/Guide_Doc/dut_fixture.md"
    ).read_text(encoding="utf-8")
    test_case_guide = (
        root / "ucagent/lang/zh/doc/Guide_Doc/dut_test_case.md"
    ).read_text(encoding="utf-8")
    create_skill = (
        root
        / "ucagent/lang/zh/skills/unitytest/create-test-case-templates/SKILL.md"
    ).read_text(encoding="utf-8")
    implementation_skill = (
        root
        / "ucagent/lang/zh/skills/unitytest/test-case-implementation-in-batch/SKILL.md"
    ).read_text(encoding="utf-8")
    static_skill = (
        root
        / "ucagent/lang/zh/skills/unitytest/static-bug-validation/SKILL.md"
    ).read_text(encoding="utf-8")
    api_template = (
        root / "ucagent/lang/zh/template/unity_test/tests/{{DUT}}_api.py"
    ).read_text(encoding="utf-8")

    for document in (
        template_guide,
        fixture_guide,
        test_case_guide,
        create_skill,
        implementation_skill,
        static_skill,
    ):
        assert "fc_cover" in document
        assert "最早traceback" in document
        assert any(keyword in document for keyword in ("不得", "禁止", "不能"))

    assert "API、fixture与覆盖率定义的只读边界" in template_guide
    assert "只能创建或修正普通`test_*.py`模板" in template_guide
    assert "不得在测试文件中伪造`fc_cover`" in test_case_guide
    assert "不修改`{DUT}_api.py`" in create_skill
    assert "默认只编辑当前测试文件" in implementation_skill
    assert "默认只新增或修改当前静态验证测试" in static_skill
    assert "同时服务于真实DUT与模板阶段fake DUT" in api_template
    assert "进入测试模板创建和测试实现阶段后" in api_template
    assert "删除覆盖组/fc_cover绑定" in api_template

    inc_config = load_yaml_with_env_vars(
        str(root / "ucagent/lang/zh/config/inc.yaml")
    )
    inc_stages = {stage["name"]: stage for stage in inc_config["stage"]}
    update_api_task = "\n".join(
        str(item) for item in inc_stages["update_test_env_and_api"]["task"]
    )
    update_api_test_task = "\n".join(
        str(item) for item in inc_stages["update_env_and_api_test"]["task"]
    )
    assert "没有需求变更时不要重写已提供模板" in update_api_task
    assert "必须保留ucagent.is_imp_test_template()下的fake DUT路径" in update_api_task
    assert "最早traceback明确证明API/fixture实现本身有缺陷" in update_api_test_task


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
    assert "`bug_document_viewer_link`" in guide
    assert "脚本不可用时，使用文本编辑工具" in guide
    assert "调用 `ApplyWaveInfoEvidence`" in guide
    assert "同一 Bug 有多个 Fail TC 时，对每个 BG/TC 分别调用一次" in guide
    assert "目标 TC 不存在且 BG 位置唯一时" in guide
    assert "LLM 不得手工复制 BG、创建兄弟 TC" in guide
    assert "同一 Fail TC 揭示多个独立 Bug 时" in guide
    assert "每次调用只更新目标 BG/TC，不会覆盖其他 Bug" in guide
    assert "签名窗口和 `signal_groups` 同时支持各缺陷时" in guide
    assert "test_add_with_cin_overflow_partitioned_operands" in guide
    assert guide.count("<TC-tests/test_adder.py::test_add_with_cin_overflow_") == 2
    assert "八个分析字段" in guide
    assert 'status: "<BUG-TODO>"' in guide
    assert "<WAVEFORM-VIEWER> [<BUG-TODO>](/surfer/?wave=<BUG-TODO>)" in guide
    assert "`<WAVEFORM-VIEWER>`" in guide
    assert "CMD API" not in guide
    assert "v2 逻辑定位" not in guide
    assert "非最终阶段的 Check/Complete 只验证文档与签名 receipt" in guide
    assert "最终 `record_and_report_bugs` 阶段必须先运行完整 DUT 测试集合" in guide
    assert "显示文字不参与解析" in guide
    assert "不再使用 `<WAVEFORM-ANALYSIS>` 自定义标签" in guide
    assert "省略了每个 `<TC-*>` 后的波形块" not in guide
    assert "先确认事务有效，再判断数据是否错误" in guide
    assert "调用一次 `Step(1)` 只表示仿真时间推进了一步" in guide
    assert "API 内部是否已经调用 `Step`、等待握手或采样结果" in guide
    assert "一次单点 data mismatch 只能作为继续调查的线索" in guide
    assert "不能由 Checker 根据特定信号名自动完成" in guide
    assert "`signal_groups` 的固定子字段如下" in guide
    assert "clocks -> inputs -> outputs -> protocol -> key_signals" in guide
    assert "最终调用若缺少完整角色" in guide
    assert "在线 viewer 的签名信号集合覆盖上述时钟" in guide
    assert "TOP.dut.ready" in guide
    clock_call = guide.split("时钟对齐最终调用示例：", 1)[1].split(
        "显式时间窗最终调用示例：", 1
    )[0]
    assert clock_call.count("context_steps=1") == 1

    implementation_skill = (
        Path(__file__).parents[1]
        / "ucagent/lang/zh/skills/unitytest/test-case-implementation-in-batch/SKILL.md"
    ).read_text(encoding="utf-8")
    static_skill = (
        Path(__file__).parents[1]
        / "ucagent/lang/zh/skills/unitytest/static-bug-validation/SKILL.md"
    ).read_text(encoding="utf-8")
    for skill in (implementation_skill, static_skill):
        assert "完整`signal_groups`" in skill
        assert "输入" in skill and "输出" in skill and "协议" in skill
        assert "viewer" in skill


def test_bug_document_error_help_uses_current_machine_contract():
    from ucagent.util.functions import description_bug_doc

    help_text = "\n".join(description_bug_doc())

    assert "Follow the active stage task" in help_text
    assert "only an optional helper" in help_text
    assert "active stage Skill for the complete workflow" not in help_text
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
    assert "use ApplyWaveInfoEvidence to write the generated mapping" in help_text
    assert "alignment_evidence, observed_behavior, source_correlation" in help_text
    assert "Do not copy, invent, or edit receipt-backed fields" in help_text
    assert "owns exactly one BG/TC pair per call" in help_text
    assert "If one failed TC exposes independent Bugs, keep distinct BGs" in help_text
    assert "Cross-BG application does not require replace_existing" in help_text
    assert "One Step only advances simulation" in help_text
    assert "request-accept and response-valid conditions" in help_text
    assert "only an investigation clue" in help_text
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
            "signal_groups",
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
        viewer_line = next(
            index
            for index in range(closing_line + 1, len(lines))
            if lines[index].strip()
        )
        viewer_match = re.fullmatch(
            r"<WAVEFORM-VIEWER> \[[^\]]+\]\(/surfer/\?wave=([A-Za-z0-9_-]+)\)",
            lines[viewer_line].strip(),
        )
        assert viewer_match
        viewer_payload = decode_waveform_viewer_token(viewer_match.group(1))
        assert viewer_payload["v"] == 2
        assert viewer_payload["test_dir"] == "unity_test/tests"
        assert viewer_payload["test_case"] == Path(
            analysis["waveform_file"]
        ).stem
        assert viewer_payload["cursor"] == str(analysis["wave_step"])
        pattern_signals = [item["signal"] for item in analysis["pattern"]]
        assert all(signal in viewer_payload["signals"] for signal in pattern_signals)
        signal_groups = analysis["signal_groups"]
        assert signal_groups["clock_mode"] in {"clocked", "combinational"}
        assert signal_groups["inputs"]
        assert signal_groups["outputs"]
        assert signal_groups["key_signals"]
        grouped_signals = [
            signal
            for field in ("clocks", "inputs", "outputs", "protocol", "key_signals")
            for signal in signal_groups[field]
        ]
        assert all(signal in viewer_payload["signals"] for signal in grouped_signals)


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
        "<WAVEFORM-VIEWER>",
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


def test_bug_analysis_guide_requires_scaffold_completion_with_or_without_skill():
    guide_path = (
        Path(__file__).parents[1]
        / "ucagent/lang/zh/doc/Guide_Doc/dut_bug_analysis.md"
    )
    guide = guide_path.read_text(encoding="utf-8")

    assert "建立骨架并分阶段写入" in guide
    assert "脚本不可用时也不阻塞整个流程" in guide
    assert "使用文本编辑工具参照本节最小骨架" in guide
    assert "调用 `ApplyWaveInfoEvidence`" in guide
    assert "不要为同一 BG 的后续 Fail TC 复制该结构" in guide
    assert "旧 `-ROOT/-FILE/-FIX` 参数已经删除" in guide
    assert "八个分析章节中的全部 `<BUG-TODO>`" in guide
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
        waveform_checker = next(
            item
            for item in stage["checker"]
            if item["clss"] == "UnityChipCheckerWaveformBugAnalysis"
        )
        if name == "record_and_report_bugs":
            assert waveform_checker["args"]["require_current_replay"] is True
        else:
            assert waveform_checker["args"].get("require_current_replay", False) is False

    for name in (
        "static_bug_validation",
        "line_coverage_analysis_and_improvement",
        "generate_random_test_cases",
    ):
        stage = stages[name]
        assert "UnityChipCheckerWaveformBugAnalysis" not in [
            item["clss"] for item in stage.get("checker", [])
        ]
