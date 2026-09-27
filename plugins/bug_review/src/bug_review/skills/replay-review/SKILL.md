---
name: replay-review
description: Independently triage every failed case and review verification-environment quality.
---

# Case Triage

## 目标

逐个分析 `replay_summary.json` 中的 failed、error、xpassed case。先读真实运行报告、测试、fixture 与 Spec；此阶段不读取原 Bug analysis 的根因文字。

## 操作

调用 `DescribeReviewSchema(record_type="case")` 与 `DescribeReviewSchema(record_type="environment")` 取得字段。逐 case 填写 `failure_analysis` 的阶段、场景、规格预期、测试预期、实际行为、来源行段、归因和不确定性。分类区分环境、Spec 误读、测试实现/时序、疑似 DUT、规格歧义及证据不足；测试失败本身不构成 DUT Bug。

必要时用 `RunTestCases` 定向复跑，并在 `replay.reruns` 记录与基线的关系；不得覆盖基线状态。填写 `environment_review.json` 的收集/执行、fixture/reset、驱动/采样、参考模型和种子/复现性六项审查；无法核实处写具体缺口。通过 `UpdateReviewRecord` 按文件更新。设 `stage_status.case_triage=complete` 后 Check、SetSkillUsage、日志、Complete。
