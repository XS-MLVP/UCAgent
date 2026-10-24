
# Bug Review 分析指导

## 工作区、输入与执行顺序

当前工作区只处理一个模块，工作区目录名就是模块名。Master 工作区根目录保存唯一的 DUT、RTL、Spec 和 Guide_Doc；Bug Review 只把 UnityTest 放到 `verification_review/run/unity_test/`，pytest 报告放到 `verification_review/run/test_report/`。测试、fixture、Spec、RTL 和模型均不得修改。`make init_<module>` 准备工作区，`make bug_review_all` 依次复核模块。

需要为历史输入重新构建 native 包时，先检查 RTL 的仿真 cell／memory 模型、条件宏及 filelist，记录实际构建命令、宏、工具版本和包摘要。导入与 `Step(1)` 只证明包可加载，不能证明内部时钟和复位有效；启动全集前在独立诊断执行中核对源码要求的时钟传播、复位和初始化，不以“进程成功退出”替代它们。比如 cell 仅在 `RTL_SIM` 分支驱动输出时，应依据该模型启用此宏；不能给所有设计统一加宏或用绕过门控的另一分支替代目标模型。模型未激活造成的前置失败按构建／环境问题分析，不算尚未到达的功能场景复现。修复构建后保留旧执行，用独立工作区及新的 invocation 建立结果，不能覆盖已封存 baseline。

## 失败分析填写格式

`case_triage` 的 `failure_analysis` 不要写成没有结构的长句。五个字段各自只回答一个问题，并使用下面的固定顺序：

```text
scenario:
[功能] 这条用例验证什么功能。
[激励] 测试先做什么，再发出什么请求或数据。
[条件] 复位、参数、地址、长度和等待窗口。
[来源] tests/...:行号

spec_expected:
[规格要求] Spec 要求 DUT 在此场景下完成什么。
[RTL应有行为] 应该出现的状态、握手、数据或响应。
[来源] 文档:行号

test_expected:
[测试断言] 测试实际检查什么。
[完成条件] 使用哪个信号、返回值或断言判断完成。
[超时] 最多等待多少周期。
[来源] tests/...:行号

actual:
[观测] 当前 case 观察到的信号、返回值或异常。
[窗口] 观察起止周期或执行阶段。
[首个偏差] 第一个不符合预期的信号或事务。
[证据] 日志、报告或 receipt 路径。

rationale:
[测试有效性] 为什么测试激励和断言是合理的。
[归因理由] 为什么归为环境、测试、规格或 DUT。
[待补证据] 仍不能确认的部分；没有时写“无”。
```

示例：

```text
scenario: [功能] 验证复位后 REG GIF 是否能重新接受寄存器写请求。\n[激励] 第二次复位释放后向 Config 发起一笔写请求。\n[条件] 请求保持最多 200 个周期。\n[来源] tests/test_reset.py:20-45
spec_expected: [规格要求] 复位释放后 REG GIF 应恢复接收。\n[RTL应有行为] 请求保持期间 saccept 应置高，并随后产生响应。\n[来源] raid_enc_top_functions_and_checks.md:114
test_expected: [测试断言] 请求保持至 saccept，在 svalid && mready 时采样响应。\n[超时] 200 周期。\n[来源] tests/raid_enc_top_api.py:515-522
actual: [观测] 请求已发出但 saccept 始终为 0。\n[窗口] step 51-447。\n[首个偏差] 请求发出后未被接受。\n[证据] receipt:d31b5518...
rationale: [测试有效性] 驱动与单次复位对照用例一致。\n[归因理由] 差异只出现在第二次复位后，当前支持疑似 DUT 缺陷。\n[待补证据] 具体复位状态寄存器仍需结合 RTL 确认。
```

字段内容必须使用当前 case 的输入、信号、窗口和来源，不能直接复制同一失败族的代表 case。报告发布时一个 ROOT 对应一个 Bug 详情页，成员 BugRecord 为现象记录；正文采用 DUT 功能概述、关联功能与验证目标、缺陷场景分析、异常与 RTL 根因分析，右侧一个主要波形和多个完整波形入口。写作与完整新字段示例见 `Guide_Doc/bug_review_writing.md`；同根因多现象关系见 `Guide_Doc/bug_review_example_root.md`。

六阶段顺序为 `full_replay → case_triage → dut_evidence → report_reconcile → root_correlation → publish`。初始索引只保存原 Bug ID、摘要来源和原始标签，不自动判定 BG／FC／CK 或 Bug→case 关系。先取得本次全量运行事实并独立分析失败；随后由你阅读原报告、测试、Spec、RTL 和波形，填写具体归属。

进入每阶段先看 `CurrentTips` 所列参考文件与完整 Skill 名。需要正文时调用 MCP `ReadTextFile(count>0)`；`ReadTextFile(count=0)` 只登记本阶段已阅读且内容未变的文件，不返回正文，不能用来首次阅读 `SKILL.md`。原生 Read 或 shell 读取不会形成阶段的已读证据；阶段切换或上下文压缩后若登记不存在，按提示重新登记。大篇原文可按 Bug ID 用 `ReviewBugContext` 分页读取。Skill 启用且 CurrentTips 列出阶段 Skill 时，依次 `ListSkill → ReadTextFile(SKILL.md) → 完成产物 → Check → SetSkillUsage → SetCurrentStageJournal → Complete`，Skill 名使用完整 `ext/bug_review/...`。Skill 禁用时直接使用本 Guide、同样的工具和字段，不调用 `SetSkillUsage`。

## 记录与工具

填写单个字段时优先 `DescribeReviewSchema(record_type="case", field_path="failure_analysis")` 或 `DescribeReviewSchema(record_type="roots", field_path="roots[].investigation")`，返回该字段和必需的引用定义；只有初次了解完整记录时省略 field_path。续跑先用 ReviewStageProgress 查看剩余项，不反复读取完整索引或 Schema。 失败归因按 最多 5 个 case 分批核对、调用 UpdateCaseRecords 提交，保留每个 case 的完整证据与校验；不要等全集草稿生成完才保存。 直接用 WriteTextFile／EditTextFile 编写 JSON 草稿；本流程不提供任意 Python／Shell 执行工具，RunSkillScript 仅执行已登记脚本，不运行 drafts 下自建生成器。续跑复用已提交记录和有效草稿，仅补剩余项。

`{OUT}/review_index.json` 保存身份、来源、复核后的关系和记录路径。`DescribeReviewSchema(record_type=...)` 返回 `index`、`manifest`、`replay_summary`、`case`、`environment`、`reconciliation`、`coverage`、`bug`、`roots`、`attribution_draft` 的机器可读 JSON Schema。原文位于 Master 工作区根目录；UnityTest 原文位于 `verification_review/run/unity_test/`。case 文件起始于 `{OUT}/cases/`，归因提交后位于 `{OUT}/attributions/<revision>/cases/`；活动 Bug 裁决与根因在 `{OUT}/reviews/<revision>/`；报告位于 `verification_review/report/`。

独立 case 初判结束后，`ReportClaimBlocks` 分页列出原报告 BG 标题、精确行段与原始 TC 标签，不决定 Bug 归属。先填写归因草稿的关系，再用 `ReviewBugContext(bug_id=..., sections=["claims"], max_chars=16000, ref_offset=0)` 读某条原声明的有界字段与行段，用 `case_offset`/`ref_offset` 分页；缺失归属时工具提示填写草稿，不按 CK 或关键词猜测。`ReviewRefCheck(refs=["path:start[-end]"])` 批量核实 Spec/RTL/测试源码行，返回真实原文但不替代语义判断。多个引用分别放入数组，一个裁决的 `spec_ref`、`rtl_ref` 各为单一 `路径:行号[-行号]` 字符串。

报告 case ID 是从 `verification_review/run/unity_test/` 收集的精确 node；`replay_target` 相对 RunTestCases 的 `verification_review/run/unity_test/`；`waveform_test_case_name` 必须取本次 RunTestCases 报告中的完整 node。`ResolveReviewCase` 接受完整 case ID、`TC-<case_id>`、完整 replay target 或 WaveInfo 名，返回全部身份和已附着收据；短 basename 有歧义时只列候选，不猜测。每次运行的波形自动存放在 `verification_review/run/unity_test/data` 下各自的时间戳 toffee_tmp 会话目录，永不覆盖；dut_evidence 只消费 full_replay 保留的失败用例 dump，除盘点指出的定向复跑外本阶段不得再运行任何测试：先用 waveform-review skill 的 `check_wave_availability.py`（无 skill 时列出各会话文件对照）盘点可用性，已有 fst/vcd 直接取证，仅对缺失或仅有 dat 的 case 定向复跑，不整批重跑。若已确认基础设施错误误删波形，先保留诊断并修复错误，按盘点的精确 node 进行独立定向补取证，记录新 invocation_id、参数、状态和 case.replay.reruns；不覆盖权威 baseline，也不把新波形解释为旧执行。普通 Check 不能自动触发补取证。先用 ReviewSignalCatalog(case_id=精确ID, contains=信号名片段) 查看真实信号与时间范围，按 next_offset 翻页；已有目录无需重复探测。最终 WaveInfo 使用该精确身份、真实信号 pattern、有效事务窗口和完整信号组完成取证；返回 `evidence_window_required` 时逐字按返回的 `recommended_evidence_call` 重试同一 case，返回 `metadata_only` 或 `signal_not_found` 时才降级探测，精确信号名以收据返回的 `signal_groups` 或 preset 为准，未知信号用 regex pattern 探索。`max_points`/`max_signals` 低于默认会截断 timeline 并使 `evidence_usable=false` 整次作废。可在 `{OUT}/wave_signal_presets.json` 的 `presets` 下命名信号组，并用 WaveInfo `signal_group_preset` 展开；receipt 签名展开后的真实路径。信号组计入 `max_signals`。检查零匹配、窗口 clamp 和 timeline 截断。`ReviewReceiptSummary(bug_id=...|case_id=..., limit=50)` 只返回有界收据身份、窗口及可用状态，完整单条结果用 `WaveInfoReceipts`。可用收据取得后立即 `ApplyReceiptToCase`，观察与关联文字用 `UpdateCaseRecords` 批量落盘，不要让签名收据长期未消费。用 `ApplyReceiptToCase(case_id, receipt_id)` 复制签名机器字段，绝不手工编码 viewer URL；`ValidateCaseRecords` 可随时只读 lint。长阶段调用 `ReviewStageProgress` 查看尚未初判或缺波形的精确 case 清单。

改单个索引、case、coverage、replay summary 或环境记录：先写 `{OUT}/drafts/` 下完整替换 JSON，再调用 `UpdateReviewRecord(target_path="verification_review/analysis/<记录>", draft_path="verification_review/analysis/drafts/<草稿>.json")`。工具拒绝非法 schema、case 关联和已签名字段损坏。多 case 批量写入：把形如 `{"cases": {case_id: 完整记录}}` 的草稿放在 `{OUT}/drafts/`，调用 `UpdateCaseRecords(draft_path="verification_review/analysis/drafts/<草稿>.json")`，一次校验全部并落盘，任一非法则整批不写。`CreateAttributionDraft` 只建立空的 `{OUT}/drafts/attribution.json` 格式；你填写 `bugs[]` 的主张行段、BG／FG／FC／CK、case、原标签、候选引用及判断理由，和 `reconciliation` 的对账内容。先 `CommitAttribution(draft_path="verification_review/analysis/drafts/attribution.json", dry_run=true)` 检查原文块覆盖及关联差异，再正式提交，一次更新索引、case 反向关联和对账记录。`CreateDecisionDraft` 只生成空的 `decisions[]` 与 `roots[]`；你填写全部具体裁决。先 `SubmitReviewDecisions(dry_run=true, draft_path=...)` 校验，再正式提交。`ReviewRevisionHistory` 可列出修订及变更。

## 完整索引示例

以下展示尚未裁定归属的完整 `review_index.json` 骨架。路径与 ID 是示意，实际内容须来自当前工作区。

```json
{
  "schema": "bug_review.v9",
  "record_type": "index",
  "workspace": {
    "name": "example_dut",
    "dut": "example_dut",
    "source_path": "/project/output/example_dut",
    "execution_workspace": "/project/output/example_dut",
    "started_at": "2026-09-25T01:00:00+00:00"
  },
  "source_files": {
    "bug_summary": "/project/output/example_dut/verification_review/run/unity_test/example_dut_bug_summary.md",
    "bug_analysis": "/project/output/example_dut/verification_review/run/unity_test/example_dut_bug_analysis.md"
  },
  "dut_context": {"text": "请求处理模块，依据输入命令产生响应。", "source_refs": ["example_dut/README.md:1-5"], "unavailable_reason": ""},
  "stage_status": {
    "full_replay": "pending",
    "case_triage": "pending",
    "dut_evidence": "pending",
    "report_reconcile": "pending",
    "root_correlation": "pending",
    "publish": "pending"
  },
  "bug_order": ["BUG-OUTPUT-HOLD"],
  "bugs": {
    "BUG-OUTPUT-HOLD": {
      "origin": "reported",
      "summary_ref": "unity_test/example_dut_bug_summary.md:12",
      "analysis_refs": [],
      "reported_confidence": 0.8,
      "check_points": ["FG-OUTPUT/FC-DATA/CK-HOLD"],
      "fg_ids": [], "fc_ids": [], "ck_ids": [], "bg_ids": [],
      "source_labels": [], "attribution_rationale": "",
      "case_ids": [],
      "aggregate_case_ids": [],
      "aggregate_refs": [],
      "spec_candidates": [],
      "rtl_candidates": [],
      "review_path": null
    }
  },
  "cases": {
    "tests/test_output.py::test_hold": {
      "replay_target": "tests/test_output.py::test_hold",
      "waveform_test_case_name": "",
      "record_path": "cases/case_0001.json"
    }
  },
  "attribution_revision": null,
  "claim_mapping_path": null,
  "root_path": null,
  "coverage_path": "coverage.json",
  "manifest_path": "test_manifest.json",
  "replay_summary_path": "replay_summary.json",
  "environment_path": "environment_review.json",
  "reconciliation_path": "report_reconciliation.json"
}
```

## 完整归因草稿示例

以下是 LLM 阅读原文和 case 后填写的完整 `{OUT}/drafts/attribution.json`。空格式由工具创建，不预填此处的示例内容。`claim_refs` 必须使用 `ReportClaimBlocks` 给出的整块精确行段；`source_labels` 保留原文 BG 标签，`bg_ids` 等是复核后的关系。

```json
{
  "schema": "bug_review_attribution.v2",
  "bugs": [
    {
      "bug_id": "BUG-OUTPUT-HOLD",
      "claim_refs": ["unity_test/example_dut_bug_analysis.md:44-49"],
      "bg_ids": ["BG-OUTPUT-HOLD"],
      "fg_ids": ["FG-OUTPUT"],
      "fc_ids": ["FC-DATA"],
      "ck_ids": ["CK-HOLD"],
      "case_ids": ["tests/test_output.py::test_hold"],
      "source_labels": ["BG-OUTPUT-HOLD-80"],
      "spec_candidates": ["example_dut/spec.md:42-48"],
      "rtl_candidates": ["example_dut/control.v:80-84"],
      "rationale": "原 BG 块描述背压期间数据变化；该 case 的独立复测与该场景相符。"
    }
  ],
  "reconciliation": {
    "schema": "bug_review.v9", "record_type": "reconciliation",
    "original_bug_ids": [], "discovered_bug_ids": [],
    "unreported_failed_cases": [], "previously_failed_now_passed": [],
    "original_failure_refs": {},
    "statistics_review": "按全部已收集用例与原报告统计口径逐项对照。",
    "notes": []
  }
}
```

## 完整 case 示例

以下是 triage 阶段一个失败 case 的完整 `cases/case_0001.json`，展示执行事实、测试正确性、独立归因和待取证波形四类信息。后续 receipt、窗口、信号组和 URL 必须由 `ApplyReceiptToCase` 从真实收据写入。

```json
{
  "schema": "bug_review.v9",
  "record_type": "case",
  "case_id": "tests/test_message.py::test_message",
  "bug_ids": [],
  "replay": {
    "status": "failed",
    "invocation_success": false,
    "baseline_id": "example-baseline",
    "invocation_id": "example-execution",
    "report_node_id": "tests/test_message.py::test_message",
    "failure_phase": "",
    "reruns": [],
    "not_run_reason": "",
    "result": ""
  },
  "test_review": {
    "classification": "inconclusive",
    "correctness_confirmed": false,
    "exact_input": "",
    "specification_expected": "",
    "test_expected": "",
    "dut_actual": "",
    "driver_timing_review": "",
    "rationale": ""
  },
  "failure_analysis": {
    "category": "insufficient_evidence",
    "phase": "assertion",
    "scenario": {
      "summary": "不复位 DUT 连续提交两条读结果命令，分别暂停接收消息和数据。",
      "setup": [],
      "stimulus": [],
      "conditions": [],
      "source_refs": []
    },
    "spec_expected": {
      "summary": "输出消息应保留当前读命令的完整内容。",
      "requirement": "",
      "rtl_expectation": [],
      "source_refs": []
    },
    "test_expected": {
      "summary": "第二轮完整输出消息应等于第二条输入读命令。",
      "assertion": "assert omsg_b == msg_b",
      "completion_condition": [],
      "timeout": "",
      "source_refs": []
    },
    "actual": {
      "summary": "测试记录称第二轮仍收到第一条命令的标签。",
      "observations": [],
      "window": "",
      "first_deviation": "",
      "evidence_refs": []
    },
    "rationale": {
      "test_validity": "",
      "attribution_reason": "",
      "remaining_gap": "没有覆盖第二轮输出握手的波形；还需检查接收器行为和测试长度适用性。"
    },
    "unresolved": ""
  },
  "waveform": {
    "conclusion": "inconclusive",
    "receipt_id": "",
    "analysis_window": {},
    "signal_groups": {},
    "viewer_url": "",
    "alignment_evidence": "",
    "observed_behavior": "",
    "source_correlation": "",
    "diagnostic": ""
  },
  "additional_waveforms": [],
  "scenario_steps": [
    {
      "step_id": "read-1",
      "action": "RAID_CMD=2, R_TAG=0x31",
      "receiver_setting": "feh_raidd_cready=0，之后恢复为 1",
      "expected": "返回第一条命令的完整消息",
      "status": "reached",
      "source_refs": [
        "unity_test/tests/test_message.py:10-20"
      ],
      "execution_id": "example-execution"
    },
    {
      "step_id": "read-2",
      "action": "不复位 DUT，发送 RAID_CMD=2, R_TAG=0x33",
      "receiver_setting": "feh_raidd_cready=1, feh_raidd_wready=0",
      "expected": "返回第二条命令的完整消息",
      "status": "failed",
      "source_refs": [
        "unity_test/tests/test_message.py:21-30"
      ],
      "execution_id": "example-execution"
    }
  ],
  "events": [
    {
      "event_id": "assert-message",
      "execution_id": "example-execution",
      "step_id": "read-2",
      "kind": "assertion",
      "source_kind": "test_record",
      "source_ref": "verification_review/run/test_report/failure.txt:1-3",
      "description": "接收器记录称收到 R_TAG=0x31，完整消息一致性断言失败",
      "expected": "R_TAG=0x33",
      "condition": "",
      "receipt_id": "",
      "time": null,
      "signal_path": "",
      "raw_value": "",
      "fields": [],
      "rtl_refs": []
    }
  ]
}
```

## 全量运行与环境产物

执行入口须使当前 Python 的 `bin/` 出现在 PATH，`RunTestCases` 调用真实 `pytest`，仅能收集不代表 DUT 包可运行。原生 abort 不能作为已完成全集的结果导入；若已安装 pytest-forked，可用 `RunTestCases(target="--forked .")` 隔离每个用例，仍保留崩溃与失败，明确记录参数和运行身份。不得改写断言、隐藏崩溃或沿用不完整执行的覆盖率。工具公开参数为 `target`，不是内部函数的 `pytest_args`。

`test_manifest.json` 保存收集命令、供 `RunTestCases(target=...)` 使用的 `pytest_target`、退出码、精确 `collected` node 列表、排除原因、收集错误、pytest 版本及 `baseline_id`。`replay_summary.json` 的 `outcomes` 必须逐项覆盖 `collected`；每项为 passed、failed、error、skipped、xfailed、xpassed 或有具体原因的 not_run。`commands` 与 `batch_refs` 一一对应本次真实运行和保留的报告快照。参数化子项、随机/Mock、收集错误和 skip/xfail/xpass 都计入对账，不能只看原报告的 55 个失败。全量基线只建立一次；定向复跑记在对应 `case.replay.reruns`，不能覆盖基线。

收集阶段显式把 pytest/toffee 报告写到本次运行工作区的可写 `verification_review/run/test_report/`，因此 `verification_review/run/unity_test/` 可保持只读。`PrepareReviewInventory` 返回 `PYTEST_COLLECTION_FAILED` 时先读 `{OUT}/diagnostics/collection.log` 的完整异常，再修复环境并重试；失败不会建立权威索引。若 macOS 拒绝加载 dylib，按日志中的具体库路径检查系统隔离属性，只处理可运行副本；不得改输入镜像或 `.pytest.ini`。

`environment_review.json` 记录具体质量发现及受影响 case。收集完整性、执行环境、fixture/reset、驱动/采样、参考模型、随机种子/复现性六项审查都要填写结论或缺口，不生成无来源总分。`coverage.json` 的 line 和 functional 指标要分开标明 `source_ref`、`run_scope`、`basis`、分子/分母或数值；无法核实时设 unavailable 并写原因，FG/FC/CK 实现数不是本次采样覆盖率。

## 六阶段裁决与发布

`case_triage` 对每个 failed/error/xpassed 写独立 `failure_analysis`。类别至少区分 environment、spec_misread、test_implementation、suspected_dut、spec_ambiguous、insufficient_evidence；后续有证据可改为 confirmed_dut。Spec 误读必须引用冲突的真实条款；规格歧义保持待澄清。无 Bug 归属的失败仍保留 case 页，不能制造 DUT Bug。测试/环境故障不要求 WaveInfo receipt。

`dut_evidence` 开始时创建空归因草稿；`ReportClaimBlocks` 的原标签和 TC 可供你在独立 case 初判后填写初步线索，便于选代表 case 和信号，完整复核留到下一阶段。原报告根因文字不得作为独立取证结论。此阶段只对 DUT 候选或时序争议取证。确认 DUT Bug 需要正确的失败测试、有效事务窗口内的签名 receipt、Spec 条款和解释首次偏差的 RTL 因果链。缺失证据写 `diagnostic`，保持未定。已签收据的 case 文件窗口、信号组和 viewer 必须与 receipt 逐字一致；手工转写 URL 会被拒绝。

`report_reconcile` 完整阅读原 summary、analysis，逐块确认原文 BG 标签、FG／FC／CK、TC 与逻辑 Bug 的实际关系。工具只列源块与创建格式，具体内容由你填写。每个原 BG 块至少要在一个 `claim_refs` 中有去向；原标签和复核归属不一致时保留两者并在 `rationale` 解释。报告级 tests 聚合清单只保存在 `aggregate_case_ids`、`aggregate_refs`，不自动加入 `case_ids`。`ReviewCaseDiff(limit=100, offset=0)` 按规范 `case_id` 返回草稿中已复核关联、聚合独有、本次收集、本次失败及其差集；原关联本身不证明旧失败。`review_index.json.bugs` 是按 Bug ID 索引的对象，逐项查看可遍历 `.bugs.items()`，在 jq 中用 `.bugs | to_entries[]`。候选引用须用 `ReviewRefCheck` 逐项核实，再用 `CommitAttribution` 提交完整关联。活动对账记录由索引的 `reconciliation_path` 指向，必须列出全部 `original_bug_ids`、新增的 `discovered_bug_ids`、无 Bug 归属失败 `unreported_failed_cases`。`previously_failed_now_passed` 只列原报告有失败记录且本次通过的 case；每项须在 `original_failure_refs[case_id]` 给出证明旧失败的原文 `路径:行号[-行号]`。另在 `statistics_review` 解释原/今统计口径。旧 Bug 未复现本身不足以裁为 refuted。

`root_correlation` 用 `CreateDecisionDraft` 创建空 `decisions[]`／`roots[]`，按 `DescribeReviewSchema(record_type="bug"|"roots")` 由你填写完整裁决。confirmed 的置信度为 `0 < value <= 1`，需要正确失败测试、可用签名波形、真实 Spec 和 RTL 因果链；refuted 保留原声明且置信度为 0；inconclusive 的置信度为 null。Bug 的 `phenomenon` 必须分别填写 `scenario`、`spec_expected`、`actual` 和 `bug_root_cause`：用简明且正式的表述说明验证功能、激励和条件，给出 Spec 要求及 RTL 应有行为，描述当前 case 的实际偏差，并说明 RTL 根因；每个引用都写成可跳转的 `path:start-end`。同一 root 的 confirmed Bug 中 `rtl_ref`、`first_error`、`causal_chain` 与 root 对应字段必须逐字一致；先明确成员与 `root_id`，再 dry-run 和正式提交。

完整的 Bug 裁决草稿必须保持以下结构；示例中的内容只是填写方式示意，不能直接当作当前模块的证据：

```json
{
  "decisions": [
    {
      "schema": "bug_review.v9",
      "record_type": "bug",
      "bug_id": "MSG-OWNERSHIP",
      "phenomenon": {
        "scenario": {
          "summary": "不复位 DUT 连续提交两条读结果命令，分别暂停接收消息和数据。",
          "setup": [],
          "stimulus": [],
          "conditions": [],
          "source_refs": []
        },
        "spec_expected": {
          "summary": "输出消息应保留当前读命令的完整内容。",
          "requirement": "",
          "rtl_expectation": [],
          "source_refs": []
        },
        "actual": {
          "summary": "测试记录称第二轮仍收到第一条命令的标签。",
          "observations": [],
          "window": "",
          "first_deviation": "",
          "evidence_refs": []
        },
        "bug_root_cause": ""
      },
      "case_ids": [
        "tests/test_message.py::test_message"
      ],
      "spec_refs": [],
      "rtl_refs": [],
      "decision": {
        "verdict": "inconclusive",
        "review_confidence": null,
        "rationale": "异常只有测试记录，缺少直接波形支持。",
        "root_id": null,
        "spec_ref": "",
        "rtl_ref": "",
        "first_error": "",
        "causal_chain": ""
      },
      "evidence_bindings": [
        {
          "evidence_id": "record-message",
          "case_id": "tests/test_message.py::test_message",
          "event_id": "assert-message",
          "role": "reported_only",
          "reason": "仅引用该次执行的断言记录。",
          "remaining_gap": "没有覆盖第二轮输出握手的波形；还需检查接收器行为和测试长度适用性。"
        }
      ]
    }
  ],
  "roots": []
}
```

`publish` 从活动记录生成模块首页、case 页、每个 ROOT 的唯一详情页、未定／已排除现象入口、包内源码和波形资源。正文为 DUT 功能概述、关联功能与验证目标、缺陷场景分析、异常与 RTL 根因分析，右侧一个较大主要预览、多个完整波形入口与关键 Spec／RTL。现象入口定位到 ROOT 页内相应锚点，主要预览有显式 evidence_id，其他成员不继承其观察。模块与门户展示实际复核状态，发布完成不代表证据或复跑材料完整。先 RenderBugReviewReport，再 verify_only 校验，最后 Check 与 Complete；全过程不重新执行 DUT。接收者在 output 根目录运行 python3 serve.py，使用服务打印的实际 HTTP 地址；报告无需 UCAgent 在线服务。


## 执行快照与稳定覆盖引用

RunTestCases每次返回独立的invocation_id，并自动保存本次原始报告、stdout/stderr与退出事实到 `verification_review/run/test_report/invocations/<invocation_id>/`。full_replay每批结束使用 `CaptureReplayReport(invocation_id="返回的精确ID")` 导入；当前报告只是临时入口，不代表其他调用的结果。定向复跑继续记录在case.replay.reruns，不重新导入已完成的全量基线。

全量基线覆盖证据在 `verification_review/run/test_report/baseline-coverage/<id>/` 保存稳定引用。只有全部基线调用有可信产物和相同来源，才合并行覆盖的未命中行集合、功能覆盖的采样CK集合；不能把最后一批的百分比当全量指标。无法合并时明确记录unavailable及原因，不通过补跑伪造覆盖率。使用工具写入的source_ref与统计数值，人工只核对口径与结论。

收据查询、ApplyReceiptToCase与Checker均使用本次已解析配置中的真实DUT和同一unity_test根。缺少运行配置或作用域不匹配时停止证据升级并报告缺口，不能修改签名或手写viewer URL。

## 场景、事件与根因详情契约

case 的 `scenario_steps` 保存真实 execution_id、实际操作、接收条件、预期、source_refs 和 reached／failed／not_reached；同一步骤在不同执行中的到达状态各自保存；`events` 保存自身执行 ID、step_id、来源及观察，完整示例见 `Guide_Doc/bug_review_writing.md`。波形事件的 execution_id 必须对应 replay.invocation_id 或已登记 rerun.invocation_id；source_kind=waveform 需 receipt、原始时间、完整信号、有效条件和 raw_value。测试记录／日志事件引用自己的保存文件，不填写波形坐标。

每个现象 `evidence_bindings` 说明自己的支持关系。confirmed 需要自身 direct 的 first_deviation，正确失败测试、confirmed_dut 终态和有效签名 DUT 证据；正常对照不能代替异常。提交前整理 case 的真实终态和未解决问题，没有缺口时使用空字符串，不能让渲染器删除尚未解决问题。ROOT 填写正式简洁的 title 与 primary_evidence_id，选择成员的一条明确证据；多个完整波形入口分别说明支持的成员，不按列表顺序自动选择。

ApplyReceiptToCase 会保留被替换的主要收据到 additional_waveforms，多个 case 更新仍用 UpdateCaseRecords。每份波形结论及附着字段分别核验，签名字段不能手改。发布验证不会重新执行 DUT，不因缺失原文件作废已验证的历史 receipt；交付可用性明确显示缺口。

完整三种写作示例分别见 `Guide_Doc/bug_review_example_rcmd.md`、`Guide_Doc/bug_review_example_monitor.md`、`Guide_Doc/bug_review_example_root.md`。这些规则在 Skill 禁用时同样适用。


## 面向读者的内容生成

`case_triage` 阅读当前 DUT／接口资料，由你填写索引 `dut_context.text/source_refs`，通过索引草稿和 `UpdateReviewRecord` 提交；材料不足时明确填写 unavailable_reason，不从 DUT 名称推断功能。`root_correlation` 为 ROOT 填写 affected_behavior 与 causal_steps，为 confirmed 现象填写 signal_explanations。触发条件与 RTL 首错的解释必须来自当前 case 和源码；静态推导可不绑定动态证据，但不能声称已观测。阶段所需完整格式与字段示例见 `Guide_Doc/bug_review_example_ptw.md`。通用 API 操作保留在可展开的 case 细节中，默认页面聚焦 bug 场景和 RTL 传播。


## 首错调查契约

新盘点固定 `investigation_contract=first_violation.v1`。阶段任务、普通工具和 Checker 均使用 `Guide_Doc/bug_review_investigation.md` 的动态对象、约束、首次偏差及替代解释规则；Skill 关闭时同样执行。`CaptureReplayReport` 自动归档按原始行号排列的日志候选及完整 stdout，不据此自动改写任何裁决。复核时不要覆盖或伪造这些机械产物。


## 正式记录与小批修订

通用文件工具只允许编辑 notes、analysis/drafts 和 wave_signal_presets.json；正式 case、索引、修订、报告与测试回执由专用工具写入。用 ResolveReviewCase(case_id=完整节点 ID) 获取精确身份，禁止根据 case_XXXX.json 编号或压缩摘要猜测映射。其他 Case 文件损坏不应阻塞精确身份查询。

每批先 CreateCaseDraft(case_ids=[完整 ID，最多 5 个])，用 PatchCaseDraft(draft_path, expected_sha256, patches=[{case_id, fields}]) 按精确 Case ID 与字段路径修改本轮分析，再 UpdateCaseRecords(draft_path=...)；无需读取或重写完整 JSON、猜测行号或反复 ReplaceStringInFile。expected_sha256 使用 CreateCaseDraft 返回的 draft_sha256，后续修改使用最新返回值。草稿从现有记录复制，保留 replay、签名字段和 base_sha256，不要从记忆重建整条记录。提交若提示记录已变化，重新 CreateCaseDraft 并合并本轮分析，不能删除 base_sha256 绕过冲突。工具硬性拒绝超过 5 个 Case 的批次；每批校验提交后再处理下一批。

先 ApplyReceiptToCase 附着真实收据；再 ApplyWaveformEvent(case_id, event_id, execution_id, receipt_id, time, signal_path, kind, description, condition, expected, step_id) 保存事件。time 使用波形原始时间戳，signal_path 从签名信号列表选择；工具自动读取完整位宽的二进制 raw_value（保留 x/z），不得手填十六进制或猜测总线宽度。所选 scenario step 必须已经提交；expected、condition 与 RTL 语义仍需人工／模型依据 Spec 分析，工具读取数值不等于确认 Bug。缺失或改变的快照拒绝新增测量，保留历史证据并说明缺口。


## 有界调查与实际校验进度

使用 ReviewWorkQueue(stage="case_triage", limit=5) 或 ReviewWorkQueue(stage="dut_evidence", limit=5) 获取缺少分析／波形／事件或记录损坏的精确 Case 列表。队列不把“附着了 receipt”视为完成。scenario_key 只表示可以共用一份 Spec/RTL 阅读上下文，不能代表同一根因，也不能把某 Case 的波形结论复制到其他成员。用 ReviewCaseContext(case_id, include_sources=false) 获取单 Case 的精简上下文；确需原文时打开 include_sources，最多附带四段来源。完整 Schema、收据和报告只在具体问题需要时读取。

ReviewStageProgress 与 ReviewWorkQueue 分别返回 declared_stage_status 和 validated_stage_status。前者是已提交的阶段声明；后者来自真实 Check，正式记录、收据或来源变更后变为 stale，不代表仍然通过。相同输入与相同失败诊断连续三次时，Checker 暂停模型循环并保留 no_progress 诊断；先修改对应记录或补充缺失证据，再恢复，不以重新跑完整测试来处理格式错误。原始阶段门禁仍然执行。

重复事件测量按源文件身份／大小／mtime／ctime、信号和时间戳复用缓存；任何源身份变化重新读取。发布阶段清空测量缓存并重新检查。不会缓存整个阶段通过结果来跳过根因、引用或最终发布验证。


## 结构化草稿修订

`PatchCaseDraft` 的 `patches` 每项包含 `case_id` 和 `fields`；例如 `fields={"failure_analysis.rationale.attribution_reason":"依据当前 Case 的断言与源码说明归因", "failure_analysis.rationale.remaining_gap":"列出尚缺的具体证据"}`。一次提交本批全部已核实字段；不同 Case 独立填写。只允许修改 `test_review`、`failure_analysis`、`scenario_steps`，数组整项替换；回放、身份、Bug 关联、波形收据及事件由对应专用工具维护。草稿修改成功不等于分析完成；`UpdateCaseRecords` 对本批执行初判完整性检查，失败只修正返回的字段，不等全集完成后才检查。队列必须指定当前阶段：初判队列不包含下一阶段的波形待办。

WaveInfo 参数优先级：非空 `signal_groups` 覆盖 `signal_group_preset`；只有未提供显式分组时才展开预设。显式分组仍必须通过完整性与精确路径校验，失败时不回退到预设。`recommended_evidence_call` 会清空预设名，直接使用其中的完整参数取得后续收据。

### 断言终止与波形完整性

`insufficient_evidence` / `spec_ambiguous` 是调查待办，不能通过写一句缺口说明跳过 `dut_evidence`。默认盘点所有尚未排除 DUT 的失败项，检查 FST/VCD 是否可解析及实际起止时间；文件存在不等于可解析，可解析也不代表整个测试流程执行完。

先核对 traceback、API 与 fixture：assert/TimeoutError 会终止当前测试调用，但 pytest 正常 teardown 仍应执行 `Finish()`。区分空/损坏文件、teardown/进程崩溃、以及断言后操作未执行；不可直接把短波形称为损坏。`scenario_steps` 必须记录已执行步骤、失败位置和 `not_reached` 操作。用现有窗口分析失败之前的请求、接受、响应、采样与内部传播；例如 P 区读回断言失败后，Q 区访问尚未执行，仍应分析 P 区写读链路。禁止移除断言、强制继续原 Case 或把补充运行伪装为原始证据。

有可用收据时，即使仍未定，也要通过 `CreateCaseDraft → PatchCaseDraft → UpdateCaseRecords` 填写 `waveform.observed_behavior`、`waveform.alignment_evidence`、`waveform.source_correlation`。这些是分析字段；receipt、window、signal_groups、viewer 仍只能由证据工具写入。

真实无法取证时，执行精确 Case 的 WaveInfo，把失败收据 ID 写入 `waveform.diagnostic_receipt_id`，诊断写入 `waveform.diagnostic`。空/缺失/不可解析 dump 必须先检查 Finish/flush/teardown 并记录定向恢复复跑；元数据探测、参数错误、找错信号或仅写“待补波形”不能完成调查。确认依赖缺失可用同一 Case 的 `wavekit_unavailable` 失败收据记录阻塞，不循环复跑测试。

## 未定声明调查

可读波形的失败候选必须包含 `ApplyWaveformEvent` 测量的实际事件。先保存场景步骤，再附收据、测量事件；允许增量保存，阶段 Check 才要求调查完整。确认不了偏差时记录真实 `trigger` 或 `normal_reference`，不能伪造首错。历史 `additional_waveforms` 只验证证据身份；其说明可用 `PatchCaseDraft` 的 `additional_waveforms.0.observed_behavior` 等分析叶更新。

不能把“没有共同首错”直接当作所有成员未定的理由：先判断各自的外部违例，再解释 RTL；只有证据支持共同原因才合并 ROOT。`earliest_observed` 允许明确表示更早内部边界未定位。已证实的外部异常与未定位的内部首错要分别说明。

未定也需要调查。下面是一个完整的 Bug 记录形状（引用和事件 ID 必须替换为本次实际来源）：

```json
{
  "schema": "bug_review.v9",
  "record_type": "bug",
  "bug_id": "MSG-LATCH",
  "case_ids": ["tests/test_demo.py::test_message"],
  "spec_refs": ["spec.md:1"],
  "rtl_refs": ["rtl.v:1"],
  "phenomenon": {
    "scenario": {"summary": "请求已接受后检查返回消息"},
    "spec_expected": {"summary": "返回当前请求的消息字段"},
    "actual": {"summary": "响应窗口出现旧消息字段，尚未确定输入采样边界"},
    "bug_root_cause": "待核实消息寄存器写使能与输入接受关系"
  },
  "decision": {
    "verdict": "inconclusive",
    "review_confidence": null,
    "root_id": null,
    "rationale": "已检查响应窗口，但输入归属仍有歧义",
    "investigation": {
      "question": "响应消息是否属于当前被接受的请求？",
      "source_refs": ["spec.md:1", "rtl.v:1"],
      "evidence_ids": ["response-observed"],
      "findings": "有效响应时消息保持旧值；当前窗口未覆盖输入握手，无法排除驱动保持旧请求。",
      "blocker": "causality_unresolved",
      "remaining_gap": "缺少同一次执行的输入接受边界及消息寄存器更新证据。",
      "next_action": "检查同一波形的请求 valid/ready 和消息寄存器写使能，区分旧请求重复接受与消息未更新。"
    }
  },
  "evidence_bindings": [{
    "evidence_id": "response-observed",
    "case_id": "tests/test_demo.py::test_message",
    "event_id": "response-1",
    "role": "corroborating",
    "reason": "该 Case 已测量的有效响应观察",
    "remaining_gap": "输入归属未定位"
  }]
}
```

`blocker` 的选择：`specification_missing` 需列出实际检索过的来源及缺失要求；`evidence_unavailable` 需关联有效失败波形诊断；`causality_unresolved` 需本现象的真实波形事件、已经尝试的区分方法及剩余缺口；`claim_not_reproduced` 不能掩盖仍未解释的失败候选。对仍可通过现有信号查询解决的问题，先执行查询再结案。工具和 Checker 不替你判断 DUT，也不要求确认数量。
