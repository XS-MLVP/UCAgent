---
name: targeted-review
description: Review linked tests using real reruns, independent specifications, and bounded source context.
---

# 定向测试复核

先读 Guide_Doc/analysis.md。先 ReviewWorkQueue 获取 next_group，复用已导入执行；仅需首次执行或补充真实缺失证据时 CollectReviewCases、RunTestCases，再 CaptureReplayReport 导入精确 invocation。
按一个原 Bug 的关联 Case 分组：公共规格、helper、fixture/API 驱动和采样审查一次，再核实各项输入、分支、断言与实际失败点；同组不保证同结论。ReviewContext(claim_id=声明ID) 分页获取组上下文，case_id 仅用于必要详情及 source_context。
沿 reusable_evidence 的原始引用复用公共依据，用 ReviewRefCheck 批量补读有界来源；已有结论不能代替原始证据。UpdateCaseAnalysis 每批最多五项，shared 填公共规格、有效性、时序和引用；每项各自填执行、失败引用、推理和分类，公共内容只对确实适用的项共享。超过五项分批，不重复研究公共部分。
证据充分或具体缺口明确后及时保存，组内已完成项可供后续批次复用。只在批次提交后刷新队列；next_group 为空时 Check、日志并 Complete。无需草稿、哈希或额外知识表。
本阶段不分析波形，不等待内部根因全部定位。缺运行包时记录 replay_blocker，历史结果不得冒充本次运行。Skill 缺失时使用相同工具和 Guide 完成。
