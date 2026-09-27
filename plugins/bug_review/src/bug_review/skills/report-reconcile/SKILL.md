---
name: report-reconcile
description: Compare independent case findings with all original claims and record missing DUT candidates.
---

# Report Reconciliation

## 目标

现在阅读输入镜像中的 `bug_summary.md` 和原验证总结；按 Bug ID 用 `ReviewBugContext(sections=["claims", "summary"])` 分页查看 `bug_analysis.md`，需要更多原文时用 `SearchText`、`ReadTextFile` 分段读取。逐条核对原声明，补充原报告的 Spec/RTL 候选。BG 条目级 TC 为该 Bug 权威关联；报告级聚合 tests 保留在 `aggregate_case_ids`、`aggregate_refs`，不自动并入 case 关联。原 ID、置信度、检查点与来源行段必须保留。

## 操作

对照全量结果和 case 初判，解释原报告遗漏的失败、旧失败现通过、以及统计总数和采样口径差异。`previously_failed_now_passed` 只列有原文证明旧失败且本次通过的 case，每个 case 在 `original_failure_refs` 提供对应的原文 `路径:行号[-行号]`；原 Bug 关联但没有旧失败证据的通过项只在 notes 中说明。只有独立 case 证据支持的 DUT 候选才能新增 `origin=discovered` Bug；其他失败留在 case 归因。调用 `CreateAttributionDraft` 创建完整 Bug→case 及对账草稿，填写 `reconciliation` 的旧/新 Bug、未归属失败、旧失败现通过、原文引用和统计对比。先 `CommitAttribution(draft_path="results/drafts/attribution.json", dry_run=true)` 预检，再正式提交，工具更新双向关联及阶段状态。随后 Check、SetSkillUsage、日志、Complete。
