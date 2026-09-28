
# Bug Review 分析指导

## 工作区、输入与执行顺序

`review_job.json.source_run` 指定本次唯一模块。`{OUT}/inputs/<workspace>/` 是原文只读镜像，含 Bug 报告、Spec、RTL 和测试源码；`{OUT}/tests/<workspace>/` 是可运行的测试副本。两处的测试、fixture、Spec、RTL 和模型均不得修改。`make bug-review-analysis` 默认对所有输入模块重新运行；`make bug_review_<name>` 只运行一个模块。

六阶段顺序为 `full_replay → case_triage → dut_evidence → report_reconcile → root_correlation → publish`。初始索引只保存原 Bug ID、摘要来源和原始标签，不自动判定 BG／FC／CK 或 Bug→case 关系。先取得本次全量运行事实并独立分析失败；随后由你阅读原报告、测试、Spec、RTL 和波形，填写具体归属。

进入每阶段先看 `CurrentTips` 所列参考文件与完整 Skill 名。需要正文时调用 MCP `ReadTextFile(count>0)`；`ReadTextFile(count=0)` 只登记本阶段已阅读且内容未变的文件，不返回正文，不能用来首次阅读 `SKILL.md`。原生 Read 或 shell 读取不会形成阶段的已读证据；阶段切换或上下文压缩后若登记不存在，按提示重新登记。大篇原文可按 Bug ID 用 `ReviewBugContext` 分页读取。Skill 启用且 CurrentTips 列出阶段 Skill 时，依次 `ListSkill → ReadTextFile(SKILL.md) → 完成产物 → Check → SetSkillUsage → SetCurrentStageJournal → Complete`，Skill 名使用完整 `ext/bug_review/...`。Skill 禁用时直接使用本 Guide、同样的工具和字段，不调用 `SetSkillUsage`。

## 记录与工具

`{OUT}/review_index.json` 保存身份、来源、复核后的关系和记录路径。`DescribeReviewSchema(record_type=...)` 返回 `index`、`manifest`、`replay_summary`、`case`、`environment`、`reconciliation`、`coverage`、`bug`、`roots`、`attribution_draft` 的机器可读 JSON Schema。原文仍位于输入镜像。case 文件起始于 `{OUT}/cases/`，归因提交后位于 `{OUT}/attributions/<revision>/cases/`；活动 Bug 裁决与根因在 `{OUT}/reviews/<revision>/`；报告只在 `{OUT}/report/`。

独立 case 初判结束后，`ReportClaimBlocks` 分页列出原报告 BG 标题、精确行段与原始 TC 标签，不决定 Bug 归属。先填写归因草稿的关系，再用 `ReviewBugContext(bug_id=..., sections=["claims"], max_chars=16000, ref_offset=0)` 读某条原声明的有界字段与行段，用 `case_offset`/`ref_offset` 分页；缺失归属时工具提示填写草稿，不按 CK 或关键词猜测。`ReviewRefCheck(refs=["path:start[-end]"])` 批量核实 Spec/RTL/测试源码行，返回真实原文但不替代语义判断。多个引用分别放入数组，一个裁决的 `spec_ref`、`rtl_ref` 各为单一 `路径:行号[-行号]` 字符串。

报告 case ID 是不带 `results/tests/` 前缀的精确 node；`replay_target` 相对 RunTestCases 的 `{OUT}/tests`；`waveform_test_case_name` 必须取本次 RunTestCases 报告中的完整 node。`ResolveReviewCase` 接受完整 case ID、`TC-<case_id>`、完整 replay target 或 WaveInfo 名，返回全部身份和已附着收据；短 basename 有歧义时只列候选，不猜测。最终 WaveInfo 使用该精确身份、事件 pattern、有效事务窗口和完整信号组。可在 `{OUT}/wave_signal_presets.json` 的 `presets` 下命名信号组，并用 WaveInfo `signal_group_preset` 展开；receipt 签名展开后的真实路径。信号组计入 `max_signals`。检查零匹配、窗口 clamp 和 timeline 截断。`ReviewReceiptSummary(bug_id=...|case_id=..., limit=50)` 只返回有界收据身份、窗口及可用状态，完整单条结果用 `WaveInfoReceipts`。用 `ApplyReceiptToCase(case_id, receipt_id)` 复制签名机器字段，绝不手工编码 viewer URL；`ValidateCaseRecords` 可随时只读 lint。长阶段调用 `ReviewStageProgress` 查看尚未初判或缺波形的精确 case 清单。

改单个索引、case、coverage、replay summary 或环境记录：先写 `{OUT}/drafts/` 下完整替换 JSON，再调用 `UpdateReviewRecord(target_path="results/<记录>", draft_path="results/drafts/<草稿>.json")`。工具拒绝非法 schema、case 关联和已签名字段损坏。`CreateAttributionDraft` 或 report-reconcile Skill 脚本只建立空的 `{OUT}/drafts/attribution.json` 格式；你填写 `bugs[]` 的主张行段、BG／FG／FC／CK、case、原标签、候选引用及判断理由，和 `reconciliation` 的对账内容。先 `CommitAttribution(draft_path="results/drafts/attribution.json", dry_run=true)` 检查原文块覆盖及关联差异，再正式提交，一次更新索引、case 反向关联和对账记录。`CreateDecisionDraft` 或 evidence-correlation Skill 脚本只生成空的 `decisions[]` 与 `roots[]`；你填写全部具体裁决。先 `SubmitReviewDecisions(dry_run=true, draft_path=...)` 校验，再正式提交。`ReviewRevisionHistory` 可列出修订及变更。

## 完整索引示例

以下展示尚未裁定归属的完整 `review_index.json` 骨架。路径与 ID 是示意，实际内容须来自当前工作区。

```json
{
  "schema": "bug_review.v7",
  "record_type": "index",
  "workspace": {
    "name": "workspace_example_dut",
    "dut": "example_dut",
    "source_path": "/project/inputs/workspace_example_dut",
    "execution_workspace": "/project/output/workspace_example_dut/runs/run-example",
    "started_at": "2026-09-25T01:00:00+00:00"
  },
  "source_files": {
    "bug_summary": "/project/inputs/workspace_example_dut/unity_test/example_dut_bug_summary.md",
    "bug_analysis": "/project/inputs/workspace_example_dut/unity_test/example_dut_bug_analysis.md"
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
    "unity_test/tests/test_output.py::test_hold": {
      "replay_target": "workspace_example_dut/unity_test/tests/test_output.py::test_hold",
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

以下是 LLM 阅读原文和 case 后填写的完整 `{OUT}/drafts/attribution.json`。空格式由工具或 Skill 脚本创建，不预填此处的示例内容。`claim_refs` 必须使用 `ReportClaimBlocks` 给出的整块精确行段；`source_labels` 保留原文 BG 标签，`bg_ids` 等是复核后的关系。

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
      "case_ids": ["unity_test/tests/test_output.py::test_hold"],
      "source_labels": ["BG-OUTPUT-HOLD-80"],
      "spec_candidates": ["example_dut/spec.md:42-48"],
      "rtl_candidates": ["example_dut/control.v:80-84"],
      "rationale": "原 BG 块描述背压期间数据变化；该 case 的独立复测与该场景相符。"
    }
  ],
  "reconciliation": {
    "schema": "bug_review.v7", "record_type": "reconciliation",
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
  "schema": "bug_review.v7",
  "record_type": "case",
  "case_id": "unity_test/tests/test_output.py::test_hold",
  "bug_ids": [],
  "replay": {
    "status": "failed", "invocation_success": true,
    "baseline_id": "baseline-example", "report_node_id": "results/tests/workspace_example_dut/unity_test/tests/test_output.py::test_hold",
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
    "scenario": "output backpressure", "spec_expected": "data remains stable before acceptance",
    "test_expected": "assert stable data", "actual": "data changed while ready=0",
    "rationale": "driver and assertion agree with the specification",
    "evidence_refs": ["example_dut/spec.md:42-48", "unity_test/tests/test_output.py:20-30"],
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

收集阶段显式把 pytest/toffee 报告写到本次运行工作区的可写 `uc_test_report/`，因此 `{OUT}/tests/` 可保持只读。`PrepareReviewInventory` 返回 `PYTEST_COLLECTION_FAILED` 时先读 `{OUT}/diagnostics/collection.log` 的完整异常，再修复环境并重试；失败不会建立权威索引。若 macOS 拒绝加载 dylib，按日志中的具体库路径检查系统隔离属性，只处理可运行副本；不得改输入镜像或 `.pytest.ini`。Skill 脚本收集失败时也在同一路径保留日志。

`environment_review.json` 记录具体质量发现及受影响 case。收集完整性、执行环境、fixture/reset、驱动/采样、参考模型、随机种子/复现性六项审查都要填写结论或缺口，不生成无来源总分。`coverage.json` 的 line 和 functional 指标要分开标明 `source_ref`、`run_scope`、`basis`、分子/分母或数值；无法核实时设 unavailable 并写原因，FG/FC/CK 实现数不是本次采样覆盖率。

## 六阶段裁决与发布

`case_triage` 对每个 failed/error/xpassed 写独立 `failure_analysis`。类别至少区分 environment、spec_misread、test_implementation、suspected_dut、spec_ambiguous、insufficient_evidence；后续有证据可改为 confirmed_dut。Spec 误读必须引用冲突的真实条款；规格歧义保持待澄清。无 Bug 归属的失败仍保留 case 页，不能制造 DUT Bug。测试/环境故障不要求 WaveInfo receipt。

`dut_evidence` 开始时创建空归因草稿；`ReportClaimBlocks` 的原标签和 TC 可供你在独立 case 初判后填写初步线索，便于选代表 case 和信号，完整复核留到下一阶段。原报告根因文字不得作为独立取证结论。此阶段只对 DUT 候选或时序争议取证。确认 DUT Bug 需要正确的失败测试、有效事务窗口内的签名 receipt、Spec 条款和解释首次偏差的 RTL 因果链。缺失证据写 `diagnostic`，保持未定。已签收据的 case 文件窗口、信号组和 viewer 必须与 receipt 逐字一致；手工转写 URL 会被拒绝。

`report_reconcile` 完整阅读原 summary、analysis，逐块确认原文 BG 标签、FG／FC／CK、TC 与逻辑 Bug 的实际关系。脚本只列源块与创建格式，具体内容由你填写。每个原 BG 块至少要在一个 `claim_refs` 中有去向；原标签和复核归属不一致时保留两者并在 `rationale` 解释。报告级 tests 聚合清单只保存在 `aggregate_case_ids`、`aggregate_refs`，不自动加入 `case_ids`。`ReviewCaseDiff(limit=100, offset=0)` 按规范 `case_id` 返回草稿中已复核关联、聚合独有、本次收集、本次失败及其差集；原关联本身不证明旧失败。`review_index.json.bugs` 是按 Bug ID 索引的对象，逐项查看可遍历 `.bugs.items()`，在 jq 中用 `.bugs | to_entries[]`。候选引用须用 `ReviewRefCheck` 逐项核实，再用 `CommitAttribution` 提交完整关联。活动对账记录由索引的 `reconciliation_path` 指向，必须列出全部 `original_bug_ids`、新增的 `discovered_bug_ids`、无 Bug 归属失败 `unreported_failed_cases`。`previously_failed_now_passed` 只列原报告有失败记录且本次通过的 case；每项须在 `original_failure_refs[case_id]` 给出证明旧失败的原文 `路径:行号[-行号]`。另在 `statistics_review` 解释原/今统计口径。旧 Bug 未复现本身不足以裁为 refuted。

`root_correlation` 用 `CreateDecisionDraft` 创建空 `decisions[]`／`roots[]`，按 `DescribeReviewSchema(record_type="bug"|"roots")` 由你填写完整裁决。confirmed 的置信度为 `0 < value <= 1`，需要正确失败测试、可用签名波形、真实 Spec 和 RTL 因果链；refuted 保留原声明且置信度为 0；inconclusive 的置信度为 null。同一 root 的 confirmed Bug 中 `rtl_ref`、`first_error`、`causal_chain` 与 root 对应字段必须逐字一致；额外 case 细节写 `rationale`、`observed_behavior`。先明确成员与 `root_id`，再 dry-run 和正式提交。

`publish` 渲染并核验 `{OUT}/report/index.html`、`cases/`、`bugs/`、`sources/`、可用时的 `surfer/` 与 `waveforms/`，以及 `report_manifest.json`。模块页以中文显示结论、数量、覆盖率与失败 case；缺陷主表仅汇总 `verdict=confirmed` 且 `review_confidence >= 0.8` 的 Bug，按最终根因聚合，一组一行并链接每个成员详情，按组内最低置信度降序。总门户的高置信度根因数沿用模块主表的去重根因口径，不插入指南链接。未展示的原声明仍保留数据及 Bug 详情，排除 DUT 缺陷的声明不计入根因数。Bug 详情在场景、预期和实际行为下方用一段中文概述复核归因、根因位置和造成的现象；“证据链”的签名波形给出关键观察，并在原波形仍可由收据定位时提供完整预览按钮。该按钮读取报告内的静态波形快照，须通过本地报告服务打开；原文件已轮换时保留收据与分析而不补造快照。“相关文档”默认展开，链接原报告和关联规格文档，其中报告级用例清单以表格区分复核关联与仅原报告提及的用例；末段“相关源码”默认折叠，只列 RTL 文件与简析。点击引用打开报告内全文预览，并高亮所引行段。复核状态分 complete/incomplete；显式收集、执行或归因缺口可发布 incomplete，静默遗漏不能通过 Check。此阶段不手工设置 `stage_status.publish`；Check 验证页面、快照与源码行段链接，Complete 回调发布、重建 `output/index.html` 和 `output/serve.py`，并记录完成状态。接收方只拿到整个 `output/` 文件夹时，在其根目录运行 `python3 serve.py`，用打印的本地 HTTP 地址浏览报告。公开入口为 `output/index.html → output/workspace_<name>/report/index.html → case/Bug 页`；运行中 JSON、draft、测试和收据留在 `runs/`。若门户缺失，使用 `python -m bug_review.workflow publish --workspace <run>` 恢复，不重跑分析。若公开目录不可写，发布错误给出具体路径。
