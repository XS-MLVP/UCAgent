---
name: report-reconcile
description: Compare independent case findings with all original claims and record missing DUT candidates.
---

# Report Reconciliation

## 目标

现在阅读输入镜像中的 `bug_summary.md` 和原验证总结；按 Bug ID 用 `ReviewBugContext(sections=["claims", "summary"])` 分页查看 `bug_analysis.md`，需要更多原文时用 `SearchText`、`ReadTextFile` 分段读取。逐条核对原声明，补充原报告的 Spec/RTL 候选。BG 条目级 TC 为该 Bug 权威关联；报告级聚合 tests 保留在 `aggregate_case_ids`、`aggregate_refs`，不自动并入 case 关联。原 ID、置信度、检查点与来源行段必须保留。

## 操作

先调用 `ReviewCaseDiff` 按规范 case ID 查看 BG 关联、报告级聚合与本次失败的差集；返回的三种 case 身份用于后续精确调用，不从路径前缀自行推断。原关联不能充当旧失败证据。`review_index.json.bugs` 是按 Bug ID 为键的对象，jq 遍历用 `.bugs | to_entries[]`。解释原报告遗漏的失败、旧失败现通过、以及统计总数和采样口径差异。`previously_failed_now_passed` 只列有原文证明旧失败且本次通过的 case，每项在 `original_failure_refs` 提供原文 `路径:行号[-行号]`。只有独立 case 证据支持的 DUT 候选才能新增 `origin=discovered` Bug。调用 `CreateAttributionDraft` 生成含 `bug_case_ids`、预填 `bug_candidates` 和 `reconciliation` 的草稿；用 `ReviewRefCheck` 核实候选行段及语义，再补完整对账。先 `CommitAttribution(draft_path="results/drafts/attribution.json", dry_run=true)` 预检，查看逐 Bug 的 `bg_required`、`aggregate_only`、`missing`、`draft_added`，再正式提交。随后 Check、SetSkillUsage、日志、Complete。
