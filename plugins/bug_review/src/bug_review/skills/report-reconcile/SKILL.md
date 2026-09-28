---
name: report-reconcile
description: Compare independent case findings with all original claims and record missing DUT candidates.
---

# Report Reconciliation

## 目标

阅读输入镜像中的 `bug_summary.md`、`bug_analysis.md` 和原验证总结。`ReportClaimBlocks` 只列原始 BG 块位置、标签与 TC 字样，不判断它们归属哪个 Bug。你根据原文、独立 case 结论、Spec 与 RTL 填写归因草稿；再用 `ReviewBugContext(sections=["claims", "summary"])` 按已填写的关系分页复查。报告级聚合 tests 保留在 `aggregate_case_ids`、`aggregate_refs`，不自动并入 case 关联。原 ID、置信度、检查点与来源行段必须保留。

## 操作

使用 `dut_evidence` 已创建的 `{OUT}/drafts/attribution.json`；若缺失则调用 `CreateAttributionDraft` 或 `RunSkillScript(commands=[["ext/bug_review/report-reconcile", "create_attribution_draft.py"]])`，两者只生成空格式。调用 `DescribeReviewSchema(record_type="attribution_draft")` 看字段。逐 Bug 填写 `bug_id`、`claim_refs`、`bg_ids`、`fg_ids`、`fc_ids`、`ck_ids`、`case_ids`、原文 `source_labels`、Spec/RTL 候选与 `rationale`。原标签与复核关系不一致时保留两者并说明。每个原始 BG 块至少有一个去向。用 `ReviewRefCheck` 核实候选，填写 `reconciliation`。再调用 `ReviewCaseDiff` 查看已填 case 归属与聚合清单、本次失败的差集；原关联不能充当旧失败证据。`previously_failed_now_passed` 只列有原文证明旧失败且本次通过的 case，在 `original_failure_refs` 提供原文 `路径:行号[-行号]`。`review_index.json.bugs` 是按 Bug ID 为键的对象，jq 遍历用 `.bugs | to_entries[]`。先 `CommitAttribution(draft_path="results/drafts/attribution.json", dry_run=true)` 预检，再正式提交。随后 Check、SetSkillUsage、日志、Complete。
