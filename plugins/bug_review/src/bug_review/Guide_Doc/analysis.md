
# Bug Review 分析指导

## 工作区、输入与执行顺序

当前工作区只处理一个模块，工作区目录名就是模块名。Master 工作区根目录保存唯一的 DUT、RTL、Spec 和 Guide_Doc；Bug Review 只把 UnityTest 放到 `verification_review/run/unity_test/`，pytest 报告放到 `verification_review/run/test_report/`。测试、fixture、Spec、RTL 和模型均不得修改。`make init_<module>` 准备工作区，`make bug_review_all` 依次复核模块。

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

字段内容必须使用当前 case 的输入、信号、窗口和来源，不能直接复制同一失败族的代表 case。报告发布时会把这些字段组织为“现象分析”；Bug 页面中的“证据溯源”分别列出 Spec、Case 和 RTL 引用表。

六阶段顺序为 `full_replay → case_triage → dut_evidence → report_reconcile → root_correlation → publish`。初始索引只保存原 Bug ID、摘要来源和原始标签，不自动判定 BG／FC／CK 或 Bug→case 关系。先取得本次全量运行事实并独立分析失败；随后由你阅读原报告、测试、Spec、RTL 和波形，填写具体归属。

进入每阶段先看 `CurrentTips` 所列参考文件与完整 Skill 名。需要正文时调用 MCP `ReadTextFile(count>0)`；`ReadTextFile(count=0)` 只登记本阶段已阅读且内容未变的文件，不返回正文，不能用来首次阅读 `SKILL.md`。原生 Read 或 shell 读取不会形成阶段的已读证据；阶段切换或上下文压缩后若登记不存在，按提示重新登记。大篇原文可按 Bug ID 用 `ReviewBugContext` 分页读取。Skill 启用且 CurrentTips 列出阶段 Skill 时，依次 `ListSkill → ReadTextFile(SKILL.md) → 完成产物 → Check → SetSkillUsage → SetCurrentStageJournal → Complete`，Skill 名使用完整 `ext/bug_review/...`。Skill 禁用时直接使用本 Guide、同样的工具和字段，不调用 `SetSkillUsage`。

## 记录与工具

`{OUT}/review_index.json` 保存身份、来源、复核后的关系和记录路径。`DescribeReviewSchema(record_type=...)` 返回 `index`、`manifest`、`replay_summary`、`case`、`environment`、`reconciliation`、`coverage`、`bug`、`roots`、`attribution_draft` 的机器可读 JSON Schema。原文位于 Master 工作区根目录；UnityTest 原文位于 `verification_review/run/unity_test/`。case 文件起始于 `{OUT}/cases/`，归因提交后位于 `{OUT}/attributions/<revision>/cases/`；活动 Bug 裁决与根因在 `{OUT}/reviews/<revision>/`；报告位于 `verification_review/report/`。

独立 case 初判结束后，`ReportClaimBlocks` 分页列出原报告 BG 标题、精确行段与原始 TC 标签，不决定 Bug 归属。先填写归因草稿的关系，再用 `ReviewBugContext(bug_id=..., sections=["claims"], max_chars=16000, ref_offset=0)` 读某条原声明的有界字段与行段，用 `case_offset`/`ref_offset` 分页；缺失归属时工具提示填写草稿，不按 CK 或关键词猜测。`ReviewRefCheck(refs=["path:start[-end]"])` 批量核实 Spec/RTL/测试源码行，返回真实原文但不替代语义判断。多个引用分别放入数组，一个裁决的 `spec_ref`、`rtl_ref` 各为单一 `路径:行号[-行号]` 字符串。

报告 case ID 是从 `verification_review/run/unity_test/` 收集的精确 node；`replay_target` 相对 RunTestCases 的 `verification_review/run/unity_test/`；`waveform_test_case_name` 必须取本次 RunTestCases 报告中的完整 node。`ResolveReviewCase` 接受完整 case ID、`TC-<case_id>`、完整 replay target 或 WaveInfo 名，返回全部身份和已附着收据；短 basename 有歧义时只列候选，不猜测。每次运行的波形自动存放在 `verification_review/run/unity_test/data` 下各自的时间戳 toffee_tmp 会话目录，永不覆盖；dut_evidence 只消费 full_replay 保留的失败用例 dump，除盘点指出的定向复跑外本阶段不得再运行任何测试：先用 waveform-review skill 的 `check_wave_availability.py`（无 skill 时列出各会话文件对照）盘点可用性，已有 fst/vcd 直接取证，仅对缺失或仅有 dat 的 case 定向复跑，不整批重跑。最终 WaveInfo 使用该精确身份、事件 pattern、有效事务窗口和完整信号组，一次调用完成取证，不要先做只探测不取证的预跑；返回 `evidence_window_required` 时逐字按返回的 `recommended_evidence_call` 重试同一 case，返回 `metadata_only` 或 `signal_not_found` 时才降级探测，精确信号名以收据返回的 `signal_groups` 或 preset 为准，未知信号用 regex pattern 探索。`max_points`/`max_signals` 低于默认会截断 timeline 并使 `evidence_usable=false` 整次作废。可在 `{OUT}/wave_signal_presets.json` 的 `presets` 下命名信号组，并用 WaveInfo `signal_group_preset` 展开；receipt 签名展开后的真实路径。信号组计入 `max_signals`。检查零匹配、窗口 clamp 和 timeline 截断。`ReviewReceiptSummary(bug_id=...|case_id=..., limit=50)` 只返回有界收据身份、窗口及可用状态，完整单条结果用 `WaveInfoReceipts`。可用收据取得后立即 `ApplyReceiptToCase`，观察与关联文字用 `UpdateCaseRecords` 批量落盘，不要让签名收据长期未消费。用 `ApplyReceiptToCase(case_id, receipt_id)` 复制签名机器字段，绝不手工编码 viewer URL；`ValidateCaseRecords` 可随时只读 lint。长阶段调用 `ReviewStageProgress` 查看尚未初判或缺波形的精确 case 清单。

改单个索引、case、coverage、replay summary 或环境记录：先写 `{OUT}/drafts/` 下完整替换 JSON，再调用 `UpdateReviewRecord(target_path="analysis/<记录>", draft_path="analysis/drafts/<草稿>.json")`。工具拒绝非法 schema、case 关联和已签名字段损坏。多 case 批量写入：把形如 `{"cases": {case_id: 完整记录}}` 的草稿放在 `{OUT}/drafts/`，调用 `UpdateCaseRecords(draft_path="analysis/drafts/<草稿>.json")`，一次校验全部并落盘，任一非法则整批不写。`CreateAttributionDraft` 只建立空的 `{OUT}/drafts/attribution.json` 格式；你填写 `bugs[]` 的主张行段、BG／FG／FC／CK、case、原标签、候选引用及判断理由，和 `reconciliation` 的对账内容。先 `CommitAttribution(draft_path="analysis/drafts/attribution.json", dry_run=true)` 检查原文块覆盖及关联差异，再正式提交，一次更新索引、case 反向关联和对账记录。`CreateDecisionDraft` 只生成空的 `decisions[]` 与 `roots[]`；你填写全部具体裁决。先 `SubmitReviewDecisions(dry_run=true, draft_path=...)` 校验，再正式提交。`ReviewRevisionHistory` 可列出修订及变更。

## 完整索引示例

以下展示尚未裁定归属的完整 `review_index.json` 骨架。路径与 ID 是示意，实际内容须来自当前工作区。

```json
{
  "schema": "bug_review.v8",
  "record_type": "index",
  "workspace": {
    "name": "example_dut",
    "dut": "example_dut",
    "source_path": "/project/output/example_dut/source",
    "execution_workspace": "/project/output/example_dut",
    "started_at": "2026-09-25T01:00:00+00:00"
  },
  "source_files": {
    "bug_summary": "/project/output/example_dut/verification_review/run/unity_test/example_dut_bug_summary.md",
    "bug_analysis": "/project/output/example_dut/verification_review/run/unity_test/example_dut_bug_analysis.md"
  },
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
      "replay_target": "test_output.py::test_hold",
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
    "schema": "bug_review.v8", "record_type": "reconciliation",
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
  "schema": "bug_review.v8",
  "record_type": "case",
  "case_id": "tests/test_output.py::test_hold",
  "bug_ids": [],
  "replay": {
    "status": "failed", "invocation_success": true,
    "baseline_id": "baseline-example", "report_node_id": "analysis/tests/test_output.py::test_hold",
    "failure_phase": "assertion", "reruns": [], "not_run_reason": "", "result": "replay/batch-example.json: failed"
  },
  "test_review": {
    "classification": "suspected_dut_bug", "correctness_confirmed": true,
    "exact_input": "valid=1, ready=0", "specification_expected": "data stable until accepted",
    "test_expected": "data remains unchanged", "dut_actual": "data changed",
    "driver_timing_review": "sampled on the next active edge", "rationale": "test waits for the defined sampling edge"
  },
  "failure_analysis": {
    "category": "suspected_dut", "phase": "assertion",
    "scenario": {
      "summary": "验证 ready=0 时输出数据保持稳定。",
      "setup": ["valid=1, ready=0"],
      "stimulus": ["保持一笔输出事务等待接收"],
      "conditions": ["观察窗口为下一个有效时钟沿"],
      "source_refs": ["tests/test_output.py:20-30"]
    },
    "spec_expected": {
      "summary": "ready=0 时数据应保持稳定。",
      "requirement": "数据在被接受前不得改变。",
      "rtl_expectation": ["valid 保持有效", "data 保持不变"],
      "source_refs": ["example_dut/spec.md:42-48"]
    },
    "test_expected": {
      "summary": "测试断言 ready=0 期间数据不变。",
      "assertion": "data remains unchanged",
      "completion_condition": ["在下一个有效采样沿检查 data"],
      "timeout": "无",
      "source_refs": ["tests/test_output.py:20-30"]
    },
    "actual": {
      "summary": "ready=0 时 data 发生变化。",
      "observations": ["data changed while ready=0"],
      "window": "下一个有效采样沿",
      "first_deviation": "ready 仍为 0 时 data 首次改变",
      "evidence_refs": ["tests/test_output.py:20-30"]
    },
    "rationale": {
      "test_validity": "驱动和断言符合规格中的采样条件。",
      "attribution_reason": "当前现象与 DUT 输出保持逻辑不符。",
      "remaining_gap": ""
    },
    "unresolved": ""
  },
  "waveform": {
    "conclusion": "inconclusive", "receipt_id": "",
    "analysis_window": {}, "signal_groups": {}, "viewer_url": "",
    "alignment_evidence": "", "observed_behavior": "",
    "source_correlation": "", "diagnostic": "DUT evidence pending"
  }
}
```

## 全量运行与环境产物

`test_manifest.json` 保存收集命令、供 `RunTestCases(pytest_args=...)` 使用的 `pytest_target`、退出码、精确 `collected` node 列表、排除原因、收集错误、pytest 版本及 `baseline_id`。`replay_summary.json` 的 `outcomes` 必须逐项覆盖 `collected`；每项为 passed、failed、error、skipped、xfailed、xpassed 或有具体原因的 not_run。`commands` 与 `batch_refs` 一一对应本次真实运行和保留的报告快照。参数化子项、随机/Mock、收集错误和 skip/xfail/xpass 都计入对账，不能只看原报告的 55 个失败。全量基线只建立一次；定向复跑记在对应 `case.replay.reruns`，不能覆盖基线。

收集阶段显式把 pytest/toffee 报告写到本次运行工作区的可写 `verification_review/run/test_report/`，因此 `verification_review/run/unity_test/` 可保持只读。`PrepareReviewInventory` 返回 `PYTEST_COLLECTION_FAILED` 时先读 `{OUT}/diagnostics/collection.log` 的完整异常，再修复环境并重试；失败不会建立权威索引。若 macOS 拒绝加载 dylib，按日志中的具体库路径检查系统隔离属性，只处理可运行副本；不得改输入镜像或 `.pytest.ini`。

`environment_review.json` 记录具体质量发现及受影响 case。收集完整性、执行环境、fixture/reset、驱动/采样、参考模型、随机种子/复现性六项审查都要填写结论或缺口，不生成无来源总分。`coverage.json` 的 line 和 functional 指标要分开标明 `source_ref`、`run_scope`、`basis`、分子/分母或数值；无法核实时设 unavailable 并写原因，FG/FC/CK 实现数不是本次采样覆盖率。

## 六阶段裁决与发布

`case_triage` 对每个 failed/error/xpassed 写独立 `failure_analysis`。类别至少区分 environment、spec_misread、test_implementation、suspected_dut、spec_ambiguous、insufficient_evidence；后续有证据可改为 confirmed_dut。Spec 误读必须引用冲突的真实条款；规格歧义保持待澄清。无 Bug 归属的失败仍保留 case 页，不能制造 DUT Bug。测试/环境故障不要求 WaveInfo receipt。

`dut_evidence` 开始时创建空归因草稿；`ReportClaimBlocks` 的原标签和 TC 可供你在独立 case 初判后填写初步线索，便于选代表 case 和信号，完整复核留到下一阶段。原报告根因文字不得作为独立取证结论。此阶段只对 DUT 候选或时序争议取证。确认 DUT Bug 需要正确的失败测试、有效事务窗口内的签名 receipt、Spec 条款和解释首次偏差的 RTL 因果链。缺失证据写 `diagnostic`，保持未定。已签收据的 case 文件窗口、信号组和 viewer 必须与 receipt 逐字一致；手工转写 URL 会被拒绝。

`report_reconcile` 完整阅读原 summary、analysis，逐块确认原文 BG 标签、FG／FC／CK、TC 与逻辑 Bug 的实际关系。工具只列源块与创建格式，具体内容由你填写。每个原 BG 块至少要在一个 `claim_refs` 中有去向；原标签和复核归属不一致时保留两者并在 `rationale` 解释。报告级 tests 聚合清单只保存在 `aggregate_case_ids`、`aggregate_refs`，不自动加入 `case_ids`。`ReviewCaseDiff(limit=100, offset=0)` 按规范 `case_id` 返回草稿中已复核关联、聚合独有、本次收集、本次失败及其差集；原关联本身不证明旧失败。`review_index.json.bugs` 是按 Bug ID 索引的对象，逐项查看可遍历 `.bugs.items()`，在 jq 中用 `.bugs | to_entries[]`。候选引用须用 `ReviewRefCheck` 逐项核实，再用 `CommitAttribution` 提交完整关联。活动对账记录由索引的 `reconciliation_path` 指向，必须列出全部 `original_bug_ids`、新增的 `discovered_bug_ids`、无 Bug 归属失败 `unreported_failed_cases`。`previously_failed_now_passed` 只列原报告有失败记录且本次通过的 case；每项须在 `original_failure_refs[case_id]` 给出证明旧失败的原文 `路径:行号[-行号]`。另在 `statistics_review` 解释原/今统计口径。旧 Bug 未复现本身不足以裁为 refuted。

`root_correlation` 用 `CreateDecisionDraft` 创建空 `decisions[]`／`roots[]`，按 `DescribeReviewSchema(record_type="bug"|"roots")` 由你填写完整裁决。confirmed 的置信度为 `0 < value <= 1`，需要正确失败测试、可用签名波形、真实 Spec 和 RTL 因果链；refuted 保留原声明且置信度为 0；inconclusive 的置信度为 null。Bug 的 `phenomenon` 必须分别填写 `scenario`、`spec_expected`、`actual` 和 `bug_root_cause`：用口语说明验证功能、激励和条件，给出 Spec 要求及 RTL 应有行为，描述当前 case 的实际偏差，并说明 RTL 根因；每个引用都写成可跳转的 `path:start-end`。同一 root 的 confirmed Bug 中 `rtl_ref`、`first_error`、`causal_chain` 与 root 对应字段必须逐字一致；先明确成员与 `root_id`，再 dry-run 和正式提交。

完整的 Bug 裁决草稿必须保持以下结构；示例中的内容只是填写方式示意，不能直接当作当前模块的证据：

```json
{
  "decisions": [
    {
      "schema": "bug_review.v8",
      "record_type": "bug",
      "bug_id": "BUG-EXAMPLE",
      "phenomenon": {
        "scenario": {
          "summary": "验证输出阻塞期间结果保持稳定：先发送一个有效请求，再保持 ready=0",
          "setup": ["复位完成", "输出端施加背压"],
          "stimulus": ["valid=1, data=0x55"],
          "conditions": ["等待 ready 重新拉高"],
          "source_refs": ["tests/test_example.py:20-28"]
        },
        "spec_expected": {
          "summary": "请求未被接受前，输出数据必须保持不变",
          "requirement": "valid && !ready 时保持当前结果",
          "rtl_expectation": ["输出寄存器不应更新"],
          "source_refs": ["DUT/spec.md:20-24"]
        },
        "actual": {
          "summary": "ready 仍为 0 时输出从 0x55 变为 0xAA",
          "observations": ["第 12 个时钟沿发生变化"],
          "window": "cycle 10-14",
          "first_deviation": "cycle 12",
          "evidence_refs": ["DUT/control.v:80-84"]
        },
        "bug_root_cause": "输出寄存器更新条件缺少 ready 门控"
      },
      "case_ids": ["tests/test_example.py::test_hold"],
      "spec_refs": ["DUT/spec.md:20-24"],
      "rtl_refs": ["DUT/control.v:80-84"],
      "decision": {
        "verdict": "confirmed",
        "review_confidence": 0.95,
        "rationale": "正确失败的测试、签名波形和首个偏差共同支持该结论",
        "root_id": "ROOT-HOLD",
        "spec_ref": "DUT/spec.md:20-24",
        "rtl_ref": "DUT/control.v:80-84",
        "first_error": "阻塞期间输出寄存器提前更新",
        "causal_chain": "缺少 ready 门控导致未接受请求改变输出"
      }
    }
  ],
  "roots": [
    {
      "root_id": "ROOT-HOLD",
      "rtl_ref": "DUT/control.v:80-84",
      "first_error": "阻塞期间输出寄存器提前更新",
      "causal_chain": "缺少 ready 门控导致未接受请求改变输出",
      "bug_ids": ["BUG-EXAMPLE"]
    }
  ]
}
```

`publish` 渲染并核验 `report/index.html`、`cases/`、`bugs/`、`sources/`、可用时的 `surfer/` 与 `waveforms/`，以及 `report_manifest.json`。模块页以中文显示结论、数量、覆盖率与失败 case；缺陷主表仅汇总 `verdict=confirmed` 且 `review_confidence >= 0.8` 的 Bug，按最终根因聚合，一组一行并链接每个成员详情，按组内最低置信度降序。总门户的高置信度根因数沿用模块主表的去重根因口径，不插入指南链接。未展示的原声明仍保留数据及 Bug 详情，排除 DUT 缺陷的声明不计入根因数。Bug 详情在场景、预期和实际行为下方用一段中文概述复核归因、根因位置和造成的现象；“证据链”的签名波形给出关键观察，并在原波形仍可由收据定位时提供完整预览按钮。该按钮读取报告内的静态波形快照，须通过本地报告服务打开；原文件已轮换时保留收据与分析而不补造快照。“相关文档”默认展开，链接原报告和关联规格文档，其中报告级用例清单以表格区分复核关联与仅原报告提及的用例；末段“相关源码”默认折叠，只列 RTL 文件与简析。点击引用打开报告内全文预览，并高亮所引行段。复核状态分 complete/incomplete；显式收集、执行或归因缺口可发布 incomplete，静默遗漏不能通过 Check。此阶段不手工设置 `stage_status.publish`；Check 验证页面、快照与源码行段链接，Complete 回调重建 `output/index.html` 和 `output/serve.py`，并记录完成状态。接收方只拿到整个 `output/` 文件夹时，在其根目录运行 `python3 serve.py`，用打印的本地 HTTP 地址浏览报告。公开入口为 `output/index.html → output/<name>/verification_review/report/index.html → case/Bug 页`；分析 JSON 和草稿位于 `analysis/`，测试位于 `tests/`，收据位于 `.ucagent/`。若门户缺失，使用 `make publish_<module>` 恢复，不重跑分析。若公开目录不可写，发布错误给出具体路径。
