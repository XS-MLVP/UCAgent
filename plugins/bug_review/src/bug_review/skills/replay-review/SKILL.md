---
name: replay-review
description: Independently triage every failed case and review verification-environment quality.
---

# Case Triage

## 目标

逐个分析 `replay_summary.json` 中的 failed、error、xpassed case。先读真实运行报告、测试、fixture 与 Spec；此阶段不读取原 Bug analysis 的根因文字（当前 DUT 的 `*_bug_analysis.md`、`*_bug_summary.md` 根因与结论部分）。

## 可读 Spec 与参考文档

以下文档属于规格侧输入，本阶段应阅读并用于 `spec_expected`（只读，不得修改）：

| 文档（workspace 根） | 用途 |
| --- | --- |
| `verification_review/run/unity_test/{DUT}_basic_info.md` | 模块规格：端口、寄存器窗口、接口协议（REG/MEM GIF、消息/数据通道） |
| `verification_review/run/unity_test/{DUT}_functions_and_checks.md` | 功能点与检查点定义（FG/FC/CK），对齐测试的 mark_function 标注 |
| `verification_review/run/unity_test/{DUT}_verification_needs_and_plan.md` | 验证需求与计划 |
| `verification_review/run/unity_test/{DUT}_test_summary.md` | 原始测试清单 |
| `{DUT}_RTL/*.{v,sv}` | RTL（本阶段仅用于解释失败现象，不必逐行深挖，dut_evidence 阶段再深入） |

引用行段一律写 workspace 相对 `path:start[-end]`（如 `unity_test/tests/test_x.py:10-64`、
`{DUT}_RTL/raid_regif.v:100-120`），Check 会逐条核实。

## 快速证据读取（自动归档，直接取证）

pytest stdout 由 `RunTestCases` 自动归档：最新一次运行写入
`.ucagent/current_test_report.json` 的 `pytest_stdout`，full_replay 每批导入时归档到
`{OUT}/diagnostics/run_logs/<批次>.txt`。不要手写、不要重复保存。用本 Skill 的脚本
快速取证（不重跑、不手写解析）：

```text
RunSkillScript(commands=[["ext/bug_review/replay-review", "summarize_case_failures.py", "--save"]])
# 全量分诊入口：按 (异常, 失败位置) 签名分组全部失败 case，列出无证据 case；
# --save 落盘 {OUT}/diagnostics/failure_signatures.json（含每 case 的异常行/断言行/位置/调用帧/尾部）

RunSkillScript(commands=[["ext/bug_review/replay-review", "read_case_stdout.py",
                          "<case_id> [case_id ...] [--tail N] | --full"]])
# 逐 case 打印 pytest traceback 原文（可多个 case 一次读取，同名失败取最新证据）
```

基线导入时工具已按 traceback 把机械事实（断言摘要、失败位置、观测异常行、assertion
阶段）预填进各 failed case 的 `failure_analysis`（只填空字段，不覆盖已有内容）；预填
结果在导入返回的 `failure_evidence` 中计数。复核预填内容后补充场景、规格预期、归因
与不确定性即可。

Skill 未启用或脚本缺失时：从 `.ucagent/current_test_report.json` 的 `pytest_stdout`
或 run_logs 文本中切 `=+ FAILURES =+` 段落，完成相同的取证；阶段产物与门禁要求不变。

## 操作

填写 `failure_analysis` 时严格区分五个字段：`scenario` 只写验证功能、激励和条件；`spec_expected` 只写 Spec 要求及 RTL 应有的可观测行为；`test_expected` 只写测试断言、完成条件和超时；`actual` 只写当前 case 的观测值、窗口、首个偏差和证据；`rationale` 只写测试有效性、归因理由和待补证据。每个字段至少包含当前 case 的差异事实，禁止把代表 case 的长段落原样复制到其他 case。推荐使用标签：`[功能]`、`[激励]`、`[条件]`、`[规格要求]`、`[RTL应有行为]`、`[测试断言]`、`[观测]`、`[窗口]`、`[首个偏差]`、`[证据]`、`[测试有效性]`、`[归因理由]`、`[待补证据]`。

填写归因时优先调用 `DescribeReviewSchema(record_type="case", field_path="failure_analysis")`，环境记录使用 `DescribeReviewSchema(record_type="environment")`；只有首次了解完整 case 结构才省略 field_path。用 `summarize_case_failures.py` 得到签名分组，逐组读测试源码与 Spec 对应段落，再用 `read_case_stdout.py` 取个别代表 case 的完整 traceback；逐 case 填写 `failure_analysis` 的阶段、场景、规格预期、测试预期、实际行为、来源行段、归因和不确定性。分类区分环境、Spec 误读、测试实现/时序、疑似 DUT、规格歧义及证据不足；测试失败本身不构成 DUT Bug，同一签名的 case 若机理一致可共用归因逻辑但须逐条落字段。

必要时用 `RunTestCases` 定向复跑，并在 `replay.reruns` 记录与基线的关系；不得覆盖基线状态。填写 `environment_review.json` 的收集/执行、fixture/reset、驱动/采样、参考模型和种子/复现性六项审查；无法核实处写具体缺口。单 case 用 `UpdateReviewRecord` 按文件更新；每 最多 5 个失败 case 核对后立即用 `UpdateCaseRecords` 校验提交，续跑先用 ReviewStageProgress 查剩余项并复用有效草稿。多个 case 就绪时优先 `UpdateCaseRecords`：草稿写在 `{OUT}/drafts` 下、形如 `{"cases": {case_id: 完整记录}}`，一次校验全部并落盘，任一非法则整批不写。设 `stage_status.case_triage=complete` 后 Check、SetSkillUsage、日志、Complete。

## Sourced reader context

Read the current DUT and interface documentation and author review_index.json.dut_context with source_refs, or a specific unavailable_reason. Submit the complete index through UpdateReviewRecord. Do not infer its purpose from a module name. See Guide_Doc/bug_review_example_ptw.md; root-level prose is authored in root_correlation after independent triage.


CaptureReplayReport 自动保存 replay_summary.log_triage_refs 和完整原始 stdout。按行号核对全部 assertion/stuck/ABORT 候选；候选不是 DUT 裁决，单文件顺序不证明跨 case 或 stderr 时序。

本工作流不提供任意 Python／Shell 执行工具。Case 草稿使用 PatchCaseDraft 按字段修改；其他记录用 WriteTextFile／EditTextFile 编写 JSON 草稿；RunSkillScript 仅执行 Skill 已登记的脚本，不执行 drafts 下自建的生成脚本。


每批先用 `CreateCaseDraft(case_ids=[...])` 从正式记录建立完整草稿，保留执行和签名字段；使用 PatchCaseDraft 按精确 case_id 和字段路径一次填写本批分析，expected_sha256 取 CreateCaseDraft 返回的 draft_sha256 或最新修改结果；不要逐段 ReplaceStringInFile 或维护行号。通用文件工具不能直接编辑正式记录，`UpdateCaseRecords` 硬性限制每批最多 5 个 Case。

本阶段始终使用 `ReviewWorkQueue(stage="case_triage", limit=5)`，只修正初判缺口；波形缺口由下一阶段 `ReviewWorkQueue(stage="dut_evidence", limit=5)` 处理。每批 UpdateCaseRecords 都验证初判必填项，通过后再处理下一批。
