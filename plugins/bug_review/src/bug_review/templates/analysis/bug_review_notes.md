
# Bug Review 复核笔记

本页用于记录分析思路。权威测试、波形和裁决数据位于 `results/`。

## 人工记录

在这里记录待核查的问题、规格解释和复核结论。不要把笔记当作测试或波形收据。

## 阶段摘要

<!-- BUG-REVIEW-SUMMARY-START -->

尚无已完成的阶段。

<!-- BUG-REVIEW-SUMMARY-END -->


## 场景与证据关系

记录 ROOT、现象、精确 case／执行、step_id、event_id、receipt 与支持角色。完整填写要求和示例见 `Guide_Doc/bug_review_writing.md`；本文是工作笔记，不能替代已提交主记录或签名证据。

## Sourced reader context

记录 dut_context、affected_behavior、signal_explanations 和 causal_steps 的资料来源及尚缺内容；说明正文在对应分析阶段由 LLM 生成，通过主记录提交。完整示例见 Guide_Doc/bug_review_example_ptw.md。


## 调查记录

`investigation_contract=first_violation.v1`：每个 ROOT 的 investigation 记录约束、同一 case/invocation 内的对象身份、direct first_deviation、检测位置以及替代解释的反证或缺口，见 Guide_Doc/bug_review_investigation.md。日志线索入口为 replay_summary.log_triage_refs，仅提供原始行序候选，不决定 DUT 裁决。修复验证本轮未执行。
