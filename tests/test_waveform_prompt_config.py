"""Dynamic Bug waveform requirements in the default Chinese mission prompt."""

from pathlib import Path
import re
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ucagent.checkers.toffee_report import check_dynamic_bug_analysis_content
from ucagent.util.bug_analysis_contract import (
    DYNAMIC_BUG_DOCUMENT_PATH,
    TEST_CASE_SERIALIZATION,
)
from ucagent.util.config import Config, load_yaml_with_env_vars


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
    assert "API CK失败时先核对coverage/check function" in task
    assert "CK Fail本身不证明DUT Bug" in task
    assert "报告关联到同一精确CK的正确Fail TC" in task
    assert "该CK可以已被TC成功触发并通过覆盖" in task
    assert "不要求Fail TC关联失败CK" in task
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

    assert "优先怀疑是芯片设计问题" not in system_prompt
    assert "不要急于修改测试" not in parent_task
    assert "每个Fail TC都不预设责任方" in system_prompt
    assert "progress_summary.status: batch_advanced" in system_prompt
    assert "不是Checker失败" in system_prompt
    assert "不得把`check_pass: false`单独解释为验证失败" in system_prompt
    assert "specification_expected" in system_prompt
    assert "精确input、specification_expected、测试代码中的test_expected、DUT actual和classification" in system_prompt
    assert "禁止调用WaveInfo或记录Bug" in system_prompt
    assert "每个Fail TC都不预设责任方" in parent_task
    assert "input、specification_expected、test_expected、DUT actual和classification" in parent_task
    assert "分类完成前禁止调用WaveInfo" in parent_task
    assert "如果Fail，不预设责任方" in batch_task
    assert "input、specification_expected、test_expected、DUT actual和classification" in batch_task
    assert "禁止调用WaveInfo或记录Bug" in batch_task
    assert "当前批次只分析{LIST_CURRENT_CASES}及当前报告为这些TC关联的CK" in batch_task
    assert "Fail TC与CK覆盖状态彼此独立" in batch_task
    assert "不要求每个Fail TC关联失败CK" in batch_task
    assert "`WaveInfo`是必须调用的诊断工具" in system_prompt
    assert "不得豁免动态Bug的`WaveInfo`取证" in system_prompt
    assert "LLM不得复制或修改receipt字段" in system_prompt
    assert (
        'WaveInfo(test_case_name="{OUT}/tests/test_{DUT}_xxx.py::test_{DUT}_xxx"'
        in system_prompt
    )
    assert "recommended_call.test_case_name只是波形basename定位提示" in system_prompt
    assert "tests.test_case_instances" in system_prompt
    assert "实际FAILED参数化child" in system_prompt
    assert "YAML `executed_test_case`记录该child" in system_prompt
    assert "本次运行由agent.cfg解析出的TC输出目录是`{OUT}/tests`" in system_prompt
    assert "每个文档TC文件路径必须以`{OUT}/tests/`开头" in system_prompt
    assert "RunTestCases(target=...)`例外地相对于配置TC目录" in system_prompt
    assert "不同路径绝不等价" in system_prompt
    assert "signal_catalog中确实存在时使用" in system_prompt
    assert "可以继续使用已验证的签名receipt和中央记录" in system_prompt
    assert "任务中途只运行部分用例时" in system_prompt
    assert "最终record_and_report_bugs阶段必须先运行完整DUT测试集合" in system_prompt
    assert "CMD API" not in system_prompt
    assert "v2 token" not in system_prompt
    assert "测试或波形后来变化不要求普通stage刷新已签名证据" in system_prompt
    assert "status: evidence_window_required" in system_prompt
    assert "recommended_evidence_call" in system_prompt
    assert "不能把`analysis_window.effective_start_step/effective_end_step`" in system_prompt
    assert "最终显式窗口调用必须同时传非负start_step和end_step" in system_prompt
    assert "ApplyWaveInfoEvidence(target_file=..., bug_tag=..., test_case_tag=..., receipt_id=...)" in system_prompt
    assert "一个BG有多个Fail TC时分别调用" in system_prompt
    assert "同名BG跨CK或目标关联有歧义时传`checkpoint_path=" in system_prompt
    assert "动态Bug文档以完整FG/FC/CK/BG路径为验收单位" in system_prompt
    assert "不得手工复制receipt字段、中央波形或viewer token" in system_prompt
    assert "工具保留其他BG路径、兄弟TC和中央记录" in system_prompt
    assert "一个Fail TC揭示多个独立Bug时保留不同BG" in system_prompt
    assert "相同test_case_tag和不同bug_tag分别调用" in system_prompt
    assert "新增关联不需要replace_existing" in system_prompt
    assert "LLM不得复制或修改receipt字段" in system_prompt
    assert "优先由该Skill的`record_dynamic_bug.py`和`ApplyWaveInfoEvidence`确定性维护动态Bug文档" in system_prompt
    assert "其他文档和代码仍使用当前stage允许的普通工具" in system_prompt
    assert "`-MODE repair`" in system_prompt
    assert "若相同文档阻塞仍存在" in system_prompt
    assert "返回`manual_edit_fallback`时按其`scope`和`after_edit`执行" in system_prompt
    assert "并立即重跑`-MODE repair`和Check" in system_prompt
    assert "先用`-MODE bug`" in system_prompt
    assert "再用`-MODE root`" in system_prompt
    assert "Skill禁用或未复制时" in system_prompt
    assert "以完整FG/FC/CK/BG路径为验收单位" in system_prompt
    assert "同一CK/BG路径的后续Fail TC直接交给`ApplyWaveInfoEvidence`" in system_prompt
    assert "每个根因实体使用文档级唯一<ROOT-XXX>标签" in system_prompt
    assert "至少反向关联一个真实存在的完整BG路径" in system_prompt
    assert "两个缺陷组合后才产生的错误使用独立<ROOT-XXX>" in system_prompt
    assert "<ROOT-CAUSES>" in system_prompt
    assert "<CAUSE-REF-ROOT-XXX>" in system_prompt
    assert "<RELATED-BUG-FG-.../FC-.../CK-.../BG-...>" in system_prompt
    assert "通过内嵌完整路径的<RELATED-BUG-FG-.../FC-.../CK-.../BG-...>" in system_prompt
    assert "每个BG必须且只能通过一个<CAUSE-REF-ROOT-XXX>引用一个根因" in system_prompt
    assert "清除全部`<BUG-TODO>`" in system_prompt
    assert "<WAVEFORM-REF>" in system_prompt
    assert "<WAVEFORM-EVIDENCE>" in system_prompt
    assert "一个Fail TC无论关联多少BG都只有一份波形数据" in system_prompt
    assert "receipt_test_mismatch" in system_prompt
    assert "matching_final_receipt_not_found" in system_prompt
    assert "details.parameterized_receipts" in system_prompt
    assert "details.recovery_call" in system_prompt
    assert "保持test_case_tag不变" in system_prompt
    assert "同一tool+status+target连续同错" in system_prompt
    assert "不得猜参数ID或手写receipt/YAML/viewer" in system_prompt
    assert "`bug_tags`与`bug_evidence`必须覆盖全部关联BG" in system_prompt
    assert "`required_signals`并集" in system_prompt
    assert "CK失败本身不证明DUT存在Bug" in system_prompt
    assert "不得为了满足失败CK门禁而修改当前Pass用例使其Fail" in system_prompt
    assert "正确修复predicate、关联、采样或驱动后CK可以转为Pass" in system_prompt
    assert "a+(~b)+0`表示`a-b-1" in system_prompt
    assert "测试激励/driver是否真正触发目标场景" in system_prompt
    assert "该TC关联的CK可以已经Pass" in system_prompt
    assert "独立的失败CK单向门禁" in system_prompt
    assert "每个保留的失败CK必须至少有一个" in system_prompt
    assert "不是严格一一对应" in system_prompt
    assert "这个CK可以已经被该TC成功触发并通过覆盖" in system_prompt
    assert "不要求每个Fail TC关联失败CK" in system_prompt
    assert "完整FG/FC/CK/BG路径为验收单位" in system_prompt
    assert "同一CK分支内同一个BG只出现一次" in system_prompt
    assert "`rtl/module.sv:10`和`rtl/module.sv:L10-L14`均无效" in system_prompt
    assert "`rtl/module.sv:10-14`" in system_prompt
    assert "`rtl/module.sv:10-10`" in system_prompt
    assert "<ROOT-SOURCE-FIRST-ERROR>" in system_prompt
    assert "<ROOT-SOURCE-PROPAGATION>" in system_prompt
    assert "<ROOT-SOURCE-OBSERVABLE>" in system_prompt
    assert "不能直接复制静态Bug标签" in parent_task
    assert "真实WaveInfo confirmed证据" in parent_task
    assert "除已确认DUT Bug复现用例外，其他用例必须全部Pass" in parent_task
    assert "不是要求已确认Bug用例也Pass" in parent_task
    assert "每个剩余失败CK必须有报告关联到同一CK的正确Fail TC" in parent_task
    assert "该CK可以已经通过覆盖" in parent_task
    assert "不能由TC Fail反推CK Fail" in parent_task
    assert "不得以测试Bug或BG-*-0占位保留Fail" in batch_task
    assert "任何未分类Fail" in batch_task
    assert "尽可能不直接编辑{OUT}/{DUT}_bug_analysis.md" in batch_task
    assert "record_dynamic_bug.py的-MODE repair" in batch_task
    assert "调用-MODE bug完整写入BG三个字段" in batch_task
    assert "对每个不同ROOT调用-MODE root" in batch_task
    assert "若相同文档阻塞仍存在" in batch_task
    assert "manual_edit_fallback" in batch_task
    assert "随后立即重跑-MODE repair和Check" in batch_task
    assert "Skill禁用或脚本未复制时" in batch_task
    assert "完成BG三个字段、唯一<CAUSE-REF-ROOT-XXX>、ROOT五个分析字段及双向链接" in batch_task
    assert "只处理当前反馈中的第一个阻塞项" in batch_task
    assert "同一记录的其他字段以及其他记录都不属于本次动作" in batch_task
    assert "RunTestCases只能运行当前批次已有的真实pytest验证用例" in batch_task
    assert "伪测试" in batch_task
    assert "ReplaceStringInFile传只覆盖当前Checker阻塞位置的line_blocks" in batch_task
    assert "rerun_test、rerun_waveinfo或apply_evidence为false" in batch_task
    assert "逐个审查{OUT}/{DUT}_bug_analysis.md中的每个非零置信度<BG-*>" in review_task
    assert "独立核对<ROOT-SOURCE-FIRST-ERROR>" in review_task
    assert "不能只检查标签存在或删除占位符" in review_task
    assert "禁止通过删除<TC-*>、<BG-*>或整个FG/FC/CK分支" in batch_task
    assert "一次`Step(1)`只表示仿真推进一步" in system_prompt
    assert "不能按固定信号名推断" in system_prompt
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
    assert "结论必须落在真实事务和有效响应窗口" in review_task
    assert "signal_groups和在线viewer是否同时包含时钟" in review_task
    assert "最终WaveInfo调用必须填写完整signal_groups" in batch_task

    resolved_config = Config(config)
    resolved_config.update_template({"OUT": "unity_test", "DUT": "Adder"})
    resolved_system_prompt = resolved_config.mission.prompt.system
    resolved_parent = next(
        stage
        for stage in resolved_config.stage
        if stage.name == "comprehensive_verification_and_bug_analysis"
    )
    resolved_batch = next(
        stage
        for stage in resolved_parent.stage
        if stage.name == "test_case_implementation_in_batch"
    )
    resolved_batch_task = "\n".join(str(item) for item in resolved_batch.task)
    assert "TC输出目录是`unity_test/tests`" in resolved_system_prompt
    assert "每个文档TC文件路径必须以`unity_test/tests/`开头" in resolved_system_prompt
    assert "agent.cfg已解析本次TC输出目录为unity_test/tests" in resolved_batch_task
    assert "{OUT}/tests" not in resolved_system_prompt
    assert "{OUT}/tests" not in resolved_batch_task
    for marker in (
        "<STATIC-BUG-SUMMARY>",
        "<STATIC-BUG-DETAILS>",
        "<STATIC-BUG-PROGRESS>",
    ):
        assert marker in static_task
        assert marker in static_validation_task
    assert "不能替代机器分区标签" in static_task
    assert "不能替代机器分区标签" in static_validation_task
    assert "CURRENT_FILE_PROGRESS_MARKERS" in static_task
    assert '<file sha256="' in static_task
    assert "sha256由Checker基于当前文件原始字节计算" in static_task
    assert "LINK回填不依赖linkbug.py" in static_validation_task


def test_dynamic_bug_target_tc_forms_and_no_bug_result_are_consistent():
    repo_root = Path(__file__).parents[1]
    config = load_yaml_with_env_vars(
        str(repo_root / "ucagent/lang/zh/config/default.yaml")
    )
    system_prompt = config["mission"]["prompt"]["system"]
    parent_stage = next(
        stage
        for stage in config["stage"]
        if stage["name"] == "comprehensive_verification_and_bug_analysis"
    )
    batch_stage = next(
        stage
        for stage in parent_stage["stage"]
        if stage["name"] == "test_case_implementation_in_batch"
    )
    batch_task = "\n".join(str(item) for item in batch_stage["task"])
    guide = (
        repo_root / "ucagent/lang/zh/doc/Guide_Doc/dut_bug_analysis.md"
    ).read_text(encoding="utf-8")
    skill_paths = (
        "dynamic-bug-recording/SKILL.md",
        "test-case-implementation-in-batch/SKILL.md",
        "static-bug-validation/SKILL.md",
    )
    skills = [
        (
            repo_root
            / "ucagent/lang/zh/skills/unitytest"
            / relative_path
        ).read_text(encoding="utf-8")
        for relative_path in skill_paths
    ]
    from ucagent.util.functions import description_bug_doc

    checker_help = "\n".join(description_bug_doc())

    assert DYNAMIC_BUG_DOCUMENT_PATH == "{OUT}/{DUT}_bug_analysis.md"
    for text in (system_prompt, batch_task, guide, checker_help, *skills):
        assert DYNAMIC_BUG_DOCUMENT_PATH in text
        assert "{DUT}_dynamic_bug_analysis.md" not in text
        assert (
            "可见Markdown标题" in text
            or "visible Markdown title" in text
            or "可见标题" in text
        )

    assert "tests.test_case_instances" in system_prompt
    assert "executed_test_case" in system_prompt
    assert "tests.test_case_instances" in batch_task
    assert "executed_test_case" in batch_task
    for text in (guide, checker_help):
        assert TEST_CASE_SERIALIZATION["markdown_tag"] in text
        assert TEST_CASE_SERIALIZATION["tool_or_yaml"] in text
        assert TEST_CASE_SERIALIZATION["waveinfo"] in text
    for skill in skills:
        assert "函数级" in skill
        assert "参数化" in skill
        assert "不等价" in skill

    assert "### 2.1 未发现动态 Bug" in guide
    assert "三个容器正文均为空" in guide
    assert "<DYNAMIC-BUGS>\n</DYNAMIC-BUGS>" in guide
    assert "<ROOT-CAUSES>\n</ROOT-CAUSES>" in guide
    assert "<WAVEFORM-EVIDENCE>\n</WAVEFORM-EVIDENCE>" in guide
    assert "三个容器正文全部为空" in system_prompt
    assert "三个空容器" in batch_task
    assert "every container body empty" in checker_help
    for skill in skills:
        assert "三个" in skill and "空" in skill and "容器" in skill


def test_partial_test_report_contract_is_consistent_across_runtime_guidance():
    repo_root = Path(__file__).parents[1]
    config = load_yaml_with_env_vars(
        str(repo_root / "ucagent/lang/zh/config/default.yaml")
    )
    random_stage = next(
        stage for stage in config["stage"]
        if stage["name"] == "generate_random_test_cases"
    )
    random_task = "\n".join(str(item) for item in random_stage["task"])
    guide = (
        repo_root / "ucagent/lang/zh/doc/Guide_Doc/dut_bug_analysis.md"
    ).read_text(encoding="utf-8")
    skill = (
        repo_root
        / "ucagent/lang/zh/skills/unitytest/dynamic-bug-recording/SKILL.md"
    ).read_text(encoding="utf-8")

    for text in (random_task, guide, skill):
        assert "跨阶段累计文档" in text
        assert "局部报告" in text
        assert "历史" in text and "TC" in text
        assert "同名" in text and "BG/TC" in text
        assert "FG/FC/CK/BG" in text or "FG/FC/CK路径" in text
        assert "中央" in text and "一份" in text

    assert "只对局部报告中逐字出现的TC更新Fail/Pass分类" in random_task
    assert "最终综合阶段运行完整 DUT 测试集合后" in guide
    assert "当前Fail必须分类" in skill


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


def test_current_replay_contract_is_synchronized_across_runtime_guidance():
    repo_root = Path(__file__).parents[1]
    config = load_yaml_with_env_vars(
        str(repo_root / "ucagent/lang/zh/config/default.yaml")
    )
    final_stage = next(
        stage for stage in config["stage"]
        if stage["name"] == "record_and_report_bugs"
    )
    final_task = "\n".join(str(item) for item in final_stage["task"])
    guide = (
        repo_root / "ucagent/lang/zh/doc/Guide_Doc/dut_bug_analysis.md"
    ).read_text(encoding="utf-8")
    implementation_skill = (
        repo_root
        / "ucagent/lang/zh/skills/unitytest/test-case-implementation-in-batch/SKILL.md"
    ).read_text(encoding="utf-8")

    assert "语义指纹不变的全部当前机器字段由Checker一次原子刷新" in final_task
    assert "current_receipt_id和精确Apply调用" in final_task
    assert "不要重复运行pytest/WaveInfo" in final_task
    assert "自动为所有此类 TC 生成当前 receipt" in guide
    assert "不需要再次运行 pytest 或 WaveInfo" in guide
    assert "Checker会一次原子刷新语义指纹不变的当前机器证据" in implementation_skill


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
    assert "Skill 禁用、未复制或脚本不可用时" in guide
    assert "调用 `ApplyWaveInfoEvidence`" in guide
    assert "同一 Bug 有多个 Fail TC 时，对每个 BG/TC 分别调用一次" in guide
    assert "目标 TC 不存在且 BG 位置唯一时" in guide
    assert "LLM 不得手工复制 BG、创建兄弟 TC" in guide
    assert "同一 Fail TC 揭示多个独立 Bug 时" in guide
    assert "每次调用只更新目标关联，不会覆盖其他 Bug" in guide
    assert "签名窗口和 `signal_groups` 同时支持各缺陷时" in guide
    assert "每个规范化 TC 在整个文档中有且只有一个" in guide
    assert "bug_tags" in guide and "bug_evidence" in guide
    assert "required_signals" in guide
    assert "<WAVEFORM-REF>" in guide
    assert "<WAVEFORM-VIEWER>" in guide
    assert "CMD API" not in guide
    assert "v2 逻辑定位" not in guide
    assert "普通增量 stage 使用`require_current_replay=false`" in guide
    assert "只有对应验证项配置`require_current_replay=true`" in guide
    assert "不得修改 Markdown 层级、标题、字段顺序或容器布局" in guide
    assert "YAML 与 viewer 只出现在该 TC 的中央记录中" in guide
    assert "先确认事务有效，再判断数据是否错误" in guide
    assert "调用一次 `Step(1)` 只表示仿真时间推进了一步" in guide
    assert "API 内部是否已经调用 `Step`、等待握手或采样结果" in guide
    assert "一次单点 data mismatch 只能作为继续调查的线索" in guide
    assert "不能根据特定信号名猜测" in guide
    assert "CK 失败本身不证明 DUT 存在 Bug" in guide
    assert "coverage/check function 是否真实表达规格" in guide
    assert "测试激励或 driver 是否真正触发目标场景" in guide
    assert "每个 Fail TC 都不预设责任方" in guide
    assert "`input | specification_expected | test_expected | actual | classification`" in guide
    assert "禁止调用 WaveInfo 或记录 Bug" in guide
    assert "只分析当前批次 TC 及当前报告为这些 TC 关联的 CK" in guide
    assert "CK predicate 或 sample 错误属于验证问题" in guide
    assert "每个阶段结束时仍失败的 CK" in guide
    assert "多对多而不是一一对应" in guide
    assert "CK 可以已经 Pass" in guide
    assert "不要求每个 Fail TC 关联失败 CK" in guide
    assert "失败 CK 必须有同 CK Fail TC" in guide
    assert "不得为了满足失败 CK 门禁而把当前 Pass 用例改成 Fail" in guide
    assert "`a + (~b) + 0 = a - b - 1`" in guide
    assert "Configured TC output directory`实际值" in guide
    assert "禁止复制为实际标签" in guide
    assert "只删除`:start-end`或`:line`报告行范围" in guide
    assert "相似节点不代表路径等价" in guide
    assert "recommended_call.test_case_name`只是波形文件 basename 定位提示" in guide
    assert "相似节点同样只供核对拼写" in guide
    assert "若 Apply 返回`receipt_test_mismatch`" in guide
    assert "保持`test_case_tag`逐字不变" in guide
    assert "原样调用一次 WaveInfo" in guide
    assert "不得手工写 receipt-backed YAML" in guide
    assert "同一 tool、status 和 target 连续返回相同错误后" in guide
    assert "`signal_groups` 的固定子字段为" in guide
    assert "clocks -> inputs -> outputs -> protocol -> key_signals" in guide
    assert "最终调用若缺少完整角色" in guide
    assert "TOP.dut.ready" in guide

    implementation_skill = (
        Path(__file__).parents[1]
        / "ucagent/lang/zh/skills/unitytest/test-case-implementation-in-batch/SKILL.md"
    ).read_text(encoding="utf-8")
    static_skill = (
        Path(__file__).parents[1]
        / "ucagent/lang/zh/skills/unitytest/static-bug-validation/SKILL.md"
    ).read_text(encoding="utf-8")
    dynamic_bug_skill = (
        Path(__file__).parents[1]
        / "ucagent/lang/zh/skills/unitytest/dynamic-bug-recording/SKILL.md"
    ).read_text(encoding="utf-8")
    for skill in (implementation_skill, static_skill):
        assert "完整`signal_groups`" in skill
        assert "输入" in skill and "输出" in skill and "协议" in skill
        assert "viewer" in skill
    assert "CK失败时必须先核对coverage/check function" in dynamic_bug_skill
    assert (
        "读取`.ucagent/runtime_config.json`中的`test_output_dir`"
        in dynamic_bug_skill
    )
    assert "作为本次实际TC输出目录" in dynamic_bug_skill
    assert "PYTEST_TARGET_DIRECTORY_PREFIX.correct_target" in implementation_skill
    assert "tests.test_case_instances" in implementation_skill
    assert "测试激励/driver" in dynamic_bug_skill
    assert "CK Fail本身不能作为DUT Bug结论" in dynamic_bug_skill
    assert "不要求每个Fail TC关联失败CK" in dynamic_bug_skill
    assert "不得把当前Pass用例改成Fail来满足门禁" in dynamic_bug_skill
    assert "`a+(~b)+0`是`a-b-1`" in dynamic_bug_skill
    assert "非参数化WaveInfo只去掉`TC-`" in dynamic_bug_skill
    assert "实际FAILED child" in dynamic_bug_skill
    assert "inventory和相似节点只供定位/核对，不参与匹配" in dynamic_bug_skill
    assert "原样执行`details.recovery_call`一次" in dynamic_bug_skill
    assert "验收单位是完整`FG/FC/CK/BG`路径" in dynamic_bug_skill
    assert "每个 BG 必须且只能有一个根因" in dynamic_bug_skill
    assert "内嵌完整FG/FC/CK/BG路径" in dynamic_bug_skill
    assert "`ApplyWaveInfoEvidence(..., checkpoint_path=" in dynamic_bug_skill
    assert "每个Fail TC都不预设责任方" in dynamic_bug_skill
    assert "`input | specification_expected | test_expected | actual | classification`" in dynamic_bug_skill
    assert "静态候选不能覆盖TC级反证" in dynamic_bug_skill
    assert "调用脚本、WaveInfo或创建/更新非零BG之前" in dynamic_bug_skill
    assert "无Bug分支的完成条件" in dynamic_bug_skill
    assert "公共Skill没有使用证据门禁" in dynamic_bug_skill
    assert "不调用`SetSkillUsage`" in dynamic_bug_skill
    assert "只分析当前批次待实现TC及当前报告为这些TC关联的CK" in implementation_skill
    assert "`input | specification_expected | test_expected | actual | classification`" in implementation_skill
    assert "禁止调用`WaveInfo`、创建/更新非零BG或引用静态候选" in implementation_skill
    assert "`FAILED` TC关联的CK可以是`PASSED`" in implementation_skill
    assert "不要求每个Fail TC关联失败CK" in implementation_skill
    assert "修改当前`PASSED`关联用例使其`FAILED`" in implementation_skill
    assert "`a+(~b)+0`是`a-b-1`" in implementation_skill
    assert "非参数化WaveInfo只去掉`TC-`" in implementation_skill
    assert "inventory和相似节点只供定位/核对" in implementation_skill
    assert "原样执行`details.recovery_call`一次" in implementation_skill


def test_bug_document_error_help_uses_current_machine_contract():
    from ucagent.util.functions import description_bug_doc

    help_text = "\n".join(description_bug_doc())

    assert "Follow the active stage task" in help_text
    assert "prefer that Skill's deterministic operations" in help_text
    assert "avoid proactive direct edits to the Bug document" in help_text
    assert "If the same blocker remains" in help_text
    assert "immediately rerun -MODE repair and Check" in help_text
    assert "scope and after_edit call in a returned manual_edit_fallback" in help_text
    assert "When Skill support or the script is unavailable" in help_text
    assert "only an optional helper" not in help_text
    for marker in (
        "<DYNAMIC-BUGS>",
        "<BUG-OVERVIEW>",
        "<BUG-SYMPTOMS>",
        "<BUG-TRIGGER>",
        "<ROOT-CAUSES>",
        "<CAUSE-REF-ROOT-NAME>",
        "<ROOT-CAUSE-ANALYSIS>",
        "<ROOT-SOURCE-EVIDENCE>",
        "<ROOT-CAUSAL-CHAIN>",
        "<ROOT-FIX>",
        "<ROOT-RETEST>",
        "<RELATED-BUGS>",
        "<ROOT-NAME>",
        "<RELATED-BUG-FG-NAME/FC-NAME/CK-NAME/BG-NAME-XX>",
        "<BUG-TODO>",
        "<ROOT-SOURCE-FIRST-ERROR>",
        "<ROOT-SOURCE-PROPAGATION>",
        "<ROOT-SOURCE-OBSERVABLE>",
        "<ROOT-SOURCE-UNAVAILABLE>",
    ):
        assert marker in help_text
    assert "```yaml" in help_text
    assert "waveform_analysis" in help_text
    assert "first non-empty content after every TC" in help_text
    assert "WAVEFORM-REF" in help_text
    assert "exactly one central WAVEFORM-TC record" in help_text
    assert "alignment_evidence" in help_text
    assert "required_signals, observed_behavior, source_correlation" in help_text
    assert "Do not copy, invent, or edit receipt-backed fields" in help_text
    assert "owns one exact BG/TC association per call" in help_text
    assert "If one failed TC exposes independent Bugs, keep distinct BGs" in help_text
    assert "Cross-BG application does not require replace_existing" in help_text
    assert "union of every bug_evidence.<BG>.required_signals" in help_text
    assert "One Step only advances simulation" in help_text
    assert "request-accept and response-valid conditions" in help_text
    assert "only an investigation clue" in help_text
    assert "complete HDL fenced block containing each marker" in help_text
    assert "This branch cannot contain an HDL fence" in help_text
    assert "Do not rename, translate, omit, duplicate, or reorder them" in help_text
    assert "exact level-6 display title" in help_text
    assert "Guide_Doc/dut_bug_analysis.md section 5.1" in help_text
    assert "Every BG path has exactly one root cause" in help_text
    assert "bidirectional" in help_text
    assert "Angle-bracket tags may be hidden by Markdown" in help_text
    assert "every visible title must describe the actual item" in help_text
    assert "visible heading reuses the TC title" in help_text
    assert "Every remaining FAILED DUT test" in help_text
    assert "Every remaining failed checkpoint" in help_text
    assert "prefer record_dynamic_bug.py with -MODE bug" in help_text
    assert "-MODE root for each distinct ROOT" in help_text
    assert "if the same blocker remains" in help_text
    assert "manual_edit_fallback scope and after_edit call" in help_text
    assert "immediately rerun -MODE repair and Check" in help_text
    assert "A failed checkpoint does not by itself prove a DUT Bug" in help_text
    assert "test stimulus/driver" in help_text
    assert "checkpoint that is itself PASSED" in help_text
    assert "derive an independent expected value" in help_text
    assert "specification expected, test expected, DUT actual, and classification" in help_text
    assert "coverage/check function, predicate, CovGroup.sample call" in help_text
    assert "Validation is scoped to the full FG/FC/CK/BG path" in help_text
    assert "Every CK-scoped BG path independently contains its three BG fields" in help_text
    assert "`Adder/Adder.v:10`" in help_text
    assert "`Adder/Adder.v:10-14` is valid" in help_text
    assert "`Adder/Adder.v:10-10`" in help_text
    assert "`Adder/Adder.v:L10-L14` must be repaired" in help_text
    assert help_text.index("derive an independent expected value") < help_text.index(
        "Only after the preceding checks are correct"
    )
    assert "receipt_id: <real WaveInfo receipt_id>" not in help_text
    assert "Adder.v line 10" not in help_text


def test_bug_analysis_guide_examples_link_tests_to_central_waveform_records():
    guide_path = (
        Path(__file__).parents[1]
        / "ucagent/lang/zh/doc/Guide_Doc/dut_bug_analysis.md"
    )
    guide = guide_path.read_text(encoding="utf-8")
    assert "每个 BG/TC 紧随精确`<WAVEFORM-REF>`" in guide
    assert "<WAVEFORM-REF> [WAVEFORM-EVIDENCE](#waveform-" in guide
    assert "<WAVEFORM-EVIDENCE>" in guide
    heading = (
        "### 进位输入触发溢出波形 "
        "<WAVEFORM-TC-tests/test_adder.py::test_overflow>"
    )
    assert heading in guide
    assert guide.count(heading) == 1
    assert "YAML 与 viewer 只出现在该 TC 的中央记录中" in guide


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
        "<FILE-path/to/file.v:起始行-结束行>",
        "<FG-NULL>/<FC-NULL>/<CK-NULL>/<BG-STATIC-NULL>",
        '<file sha256="CURRENT_SHA256">path/to/file.v</file>',
        "<BUG-OVERVIEW>",
        "<BUG-SYMPTOMS>",
        "<BUG-TRIGGER>",
        "<CAUSE-REF-ROOT-NAME>",
        "<ROOT-CAUSE-ANALYSIS>",
        "<ROOT-SOURCE-EVIDENCE>",
        "<ROOT-CAUSAL-CHAIN>",
        "<ROOT-FIX>",
        "<ROOT-RETEST>",
        "<RELATED-BUGS>",
        "<BUG-TODO>",
        "<ROOT-SOURCE-UNAVAILABLE>",
        "<ROOT-SOURCE-FIRST-ERROR>",
        "<ROOT-SOURCE-PROPAGATION>",
        "<ROOT-SOURCE-OBSERVABLE>",
        "<STATIC-BUG-SUMMARY>",
        "<STATIC-BUG-DETAILS>",
        "<STATIC-BUG-PROGRESS>",
    )
    for marker in required_markers:
        assert marker in guide

    assert "<WAVEFORM-REF>" in guide
    assert "<WAVEFORM-TC-" in guide
    assert "bug_tags" in guide
    assert "bug_evidence" in guide
    assert "required_signals" in guide
    assert "所有 BG 的`required_signals`并集" in guide
    assert "每个 ROOT 的`<ROOT-SOURCE-EVIDENCE>`必须包含源码代码块" in guide
    assert "<ROOT-SOURCE-UNAVAILABLE>" in guide
    assert "一个 BG 必须且只能关联一个根因" in guide
    assert "根因实体必须位于唯一`<ROOT-CAUSES>`分区" in guide


def test_bug_analysis_guide_examples_embed_annotated_source_after_overview():
    guide_path = (
        Path(__file__).parents[1]
        / "ucagent/lang/zh/doc/Guide_Doc/dut_bug_analysis.md"
    )
    guide = guide_path.read_text(encoding="utf-8")
    assert guide.index("<BUG-OVERVIEW>") < guide.index("<ROOT-SOURCE-EVIDENCE>")
    source_example = guide.split("```systemverilog", 1)[1].split("```", 1)[0]
    assert "<ROOT-SOURCE-FIRST-ERROR>" in source_example
    assert "<ROOT-SOURCE-PROPAGATION>" in source_example
    assert "<ROOT-SOURCE-OBSERVABLE>" in source_example


def test_dynamic_bug_template_has_canonical_root_cause_section():
    template_path = (
        Path(__file__).parents[1]
        / "ucagent/lang/zh/template/unity_test/{{DUT}}_bug_analysis.md"
    )
    template = template_path.read_text(encoding="utf-8")

    assert template.startswith("\n# {{DUT}} 动态 Bug 分析")
    assert "<DYNAMIC-BUGS>" in template
    assert "## 动态 Bug 记录" in template
    assert "## 波形证据" in template
    assert "## 根因分析" in template
    assert "<ROOT-CAUSES>\n</ROOT-CAUSES>" in template
    assert template.index("</DYNAMIC-BUGS>") < template.index("<ROOT-CAUSES>")
    assert template.index("</ROOT-CAUSES>") < template.index("<WAVEFORM-EVIDENCE>")


def test_bug_analysis_guide_requires_scaffold_completion_with_or_without_skill():
    guide_path = (
        Path(__file__).parents[1]
        / "ucagent/lang/zh/doc/Guide_Doc/dut_bug_analysis.md"
    )
    guide = guide_path.read_text(encoding="utf-8")

    assert "### 5.1 完整标准案例" in guide
    assert "# Adder 动态 Bug 分析" in guide
    assert "### 算术功能 <FG-ARITHMETIC>" in guide
    assert "#### 加法结果 <FC-ADD-RESULT>" in guide
    assert "##### 进位输出 <CK-CARRY-OUT>" in guide
    assert "###### 完整和进位丢失（95%） <BG-SUM-CARRY-DROPPED-95>" in guide
    assert "- 进位输入产生进位 <TC-tests/test_adder.py::test_cin_carry>" in guide
    assert "rtl/Adder.sv:24-26" in guide
    assert (
        "### 进位输入产生进位波形 "
        "<WAVEFORM-TC-tests/test_adder.py::test_cin_carry>"
    ) in guide
    assert "### 功能组：<FG-ARITHMETIC>" not in guide
    assert "- 失败用例：<TC-tests/test_adder.py::test_cin_carry>" not in guide
    assert "标准案例体现以下不可变边界" in guide
    assert "建立骨架并分阶段写入" in guide
    assert "Skill 禁用、未复制或脚本不可用时" in guide
    assert "按Guide_Doc/dut_bug_analysis.md中的第 5.2.2 节展开三个字段和根因引用" in guide
    assert "只处理反馈中的第一个阻塞项" in guide
    assert "调用 `ApplyWaveInfoEvidence`" in guide
    assert "不要为同一 BG 的后续 Fail TC 复制该结构" in guide
    assert "优先通过该Skill的`record_dynamic_bug.py`、`WaveInfo`和`ApplyWaveInfoEvidence`维护" in guide
    assert "若相同文档阻塞仍存在" in guide
    assert "按其`scope`编辑，并执行`after_edit`" in guide
    assert "立即重跑`-MODE repair`和`Check`" in guide
    assert "调用`record_dynamic_bug.py -MODE bug`" in guide
    assert "调用`record_dynamic_bug.py -MODE root`" in guide
    assert "必须用真实结论替换全部`<BUG-TODO>`" not in guide
    assert "任何非零 BG 或 ROOT 残留`<BUG-TODO>`都不能完成阶段" in guide

    config = load_yaml_with_env_vars(
        str(Path(__file__).parents[1] / "ucagent/lang/zh/config/default.yaml")
    )
    rendered_config = str(config)
    assert "Guide第5.1节" not in rendered_config
    assert "Guide第 5.1 节" not in rendered_config

    skill_paths = (
        "dynamic-bug-recording/SKILL.md",
        "static-bug-validation/SKILL.md",
        "test-case-implementation-in-batch/SKILL.md",
    )
    skill_root = Path(__file__).parents[1] / "ucagent/lang/zh/skills/unitytest"
    for relative_path in skill_paths:
        skill_text = (skill_root / relative_path).read_text(encoding="utf-8")
        assert "Guide_Doc/dut_bug_analysis.md中的第" in skill_text
        assert "Guide第5.1节" not in skill_text
        assert "Guide第 5.1 节" not in skill_text


def test_bug_analysis_guide_scaffold_shows_multi_child_hierarchy():
    guide = (
        Path(__file__).parents[1]
        / "ucagent/lang/zh/doc/Guide_Doc/dut_bug_analysis.md"
    ).read_text(encoding="utf-8")
    hierarchy = guide.split("#### 5.2.1 多分支层次骨架", 1)[1].split(
        "#### 5.2.2 单个 BG 的完整字段骨架", 1
    )[0]

    assert hierarchy.count("<FG-") == 2
    assert hierarchy.count("<FC-") == 4
    assert hierarchy.count("<CK-") == 8
    assert hierarchy.count("<BG-") == 16
    assert hierarchy.count("<TC-") == 32

    bg_test_counts = {}
    current_bg = None
    for line in hierarchy.splitlines():
        bg_match = re.search(r"<(BG-[^<>]+)>", line)
        if bg_match:
            current_bg = bg_match.group(1)
            bg_test_counts[current_bg] = 0
            continue
        if current_bg and re.search(r"<TC-[^<>]+>", line):
            bg_test_counts[current_bg] += 1
    assert set(bg_test_counts.values()) == {2}

    assert hierarchy.index("<FG-ARITHMETIC>") < hierarchy.index("<FG-PROTOCOL>")
    assert hierarchy.index("<FC-ADD-RESULT>") < hierarchy.index("<FC-SUB-RESULT>")
    assert hierarchy.index("<CK-SUM-OUT>") < hierarchy.index("<CK-CARRY-OUT>")
    assert hierarchy.index("<BG-SUM-TRUNCATED-95>") < hierarchy.index(
        "<BG-SUM-STALE-90>"
    )
    first_bg = hierarchy.split("<BG-SUM-TRUNCATED-95>", 1)[1].split(
        "<BG-SUM-STALE-90>", 1
    )[0]
    assert first_bg.count("<TC-") == 2


def test_bug_analysis_guide_places_fields_after_all_tests():
    repo_root = Path(__file__).parents[1]
    guide = (
        repo_root
        / "ucagent/lang/zh/doc/Guide_Doc/dut_bug_analysis.md"
    ).read_text(encoding="utf-8")
    agent_rules = (repo_root / "AGENTS.md").read_text(encoding="utf-8")
    scaffold = guide.split("#### 5.2.2 单个 BG 的完整字段骨架", 1)[1].split(
        "## 6. 证据保留与重放", 1
    )[0]

    assert scaffold.count("<TC-") == 2
    assert scaffold.rindex("<TC-") < scaffold.index("<BUG-OVERVIEW>")
    assert "字段开始后不再出现 TC" in guide
    assert "新增 TC 必须插入第一个 BG 字段之前" in guide
    assert "before the three ordered `<BUG-*>` analysis fields" in agent_rules
    assert "never append another TC after the" in agent_rules
    assert "qualify every Guide_Doc section reference" in agent_rules
    assert "Guide_Doc/dut_bug_analysis.md section 5.1" in agent_rules


def test_bug_analysis_guide_canonical_example_is_checker_valid(tmp_path):
    guide = (
        Path(__file__).parents[1]
        / "ucagent/lang/zh/doc/Guide_Doc/dut_bug_analysis.md"
    ).read_text(encoding="utf-8")
    section_start = guide.index("### 5.1 完整标准案例")
    fence_start = guide.index("`````markdown\n", section_start) + len(
        "`````markdown\n"
    )
    fence_end = guide.index("\n`````", fence_start)
    example = guide[fence_start:fence_end]
    (tmp_path / "Adder_bug_analysis.md").write_text(example, encoding="utf-8")

    passed, message = check_dynamic_bug_analysis_content(
        str(tmp_path), "Adder_bug_analysis.md"
    )
    assert passed is True, message

    assert re.findall(r"^### .+ <(ROOT-[^<>]+)>$", example, re.MULTILINE) == [
        "ROOT-SUM-CARRY-WIDTH",
        "ROOT-SATURATION-DETECTOR-CONSTANT",
    ]
    assert re.findall(r"^###### .+ <(BG-[^<>]+)>$", example, re.MULTILINE) == [
        "BG-SUM-CARRY-DROPPED-95",
        "BG-FULL-RESULT-TRUNCATED-93",
        "BG-SATURATION-DISABLED-92",
    ]
    assert re.findall(
        r"^### .+ <(WAVEFORM-TC-[^<>]+)>$", example, re.MULTILINE
    ) == [
        "WAVEFORM-TC-tests/test_adder.py::test_cin_carry",
        "WAVEFORM-TC-tests/test_adder.py::test_saturation_limit",
    ]

    shared_tc = "TC-tests/test_adder.py::test_cin_carry"
    assert example.count(f"- 进位输入产生进位 <{shared_tc}>") == 2
    assert example.count(f"<WAVEFORM-{shared_tc}>") == 1
    shared_root = example.split(
        "### 加法中间量宽度不足 <ROOT-SUM-CARRY-WIDTH>", 1
    )[1].split(
        "### 饱和溢出检测被固定为无效 "
        "<ROOT-SATURATION-DETECTOR-CONSTANT>",
        1,
    )[0]
    assert shared_root.count("<RELATED-BUG-") == 2
    independent_root = example.split(
        "### 饱和溢出检测被固定为无效 "
        "<ROOT-SATURATION-DETECTOR-CONSTANT>",
        1,
    )[1].split("</ROOT-CAUSES>", 1)[0]
    assert independent_root.count("<RELATED-BUG-") == 1

    payloads = [
        yaml.safe_load(yaml_text)["waveform_analysis"]
        for yaml_text in re.findall(
            r"```yaml\n(.*?)\n```", example, re.DOTALL
        )
    ]
    assert len(payloads) == 2
    by_test = {payload["test_case"]: payload for payload in payloads}
    assert set(by_test) == {
        "TC-tests/test_adder.py::test_cin_carry",
        "TC-tests/test_adder.py::test_saturation_limit",
    }
    assert by_test[shared_tc]["bug_tags"] == [
        "BG-FULL-RESULT-TRUNCATED-93",
        "BG-SUM-CARRY-DROPPED-95",
    ]
    assert set(by_test[shared_tc]["bug_evidence"]) == set(
        by_test[shared_tc]["bug_tags"]
    )
    shared_signal_groups = by_test[shared_tc]["signal_groups"]
    documented_signals = {
        signal
        for field in ("clocks", "inputs", "outputs", "protocol", "key_signals")
        for signal in shared_signal_groups[field]
    }
    required_signals = {
        signal
        for evidence in by_test[shared_tc]["bug_evidence"].values()
        for signal in evidence["required_signals"]
    }
    assert required_signals <= documented_signals
    saturation_tc = "TC-tests/test_adder.py::test_saturation_limit"
    assert by_test[saturation_tc]["bug_tags"] == [
        "BG-SATURATION-DISABLED-92"
    ]
    assert set(by_test[saturation_tc]["bug_evidence"]) == {
        "BG-SATURATION-DISABLED-92"
    }


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
