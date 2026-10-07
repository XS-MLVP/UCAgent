---
name: replay-review
description: Independently triage every failed case and review verification-environment quality.
---

# Case Triage

## 目标

逐个分析 `replay_summary.json` 中的 failed、error、xpassed case。先读真实运行报告、测试、fixture 与 Spec；此阶段不读取原 Bug analysis 的根因文字（`raid_enc_top_bug_analysis.md`、`raid_enc_top_bug_summary.md` 的根因与结论部分）。

## 可读 Spec 与参考文档

以下文档属于规格侧输入，本阶段应阅读并用于 `spec_expected`（只读，不得修改）：

| 文档（workspace 根） | 用途 |
| --- | --- |
| `verification_review/run/unity_test/raid_enc_top_basic_info.md` | 模块规格：端口、寄存器窗口、接口协议（REG/MEM GIF、消息/数据通道） |
| `verification_review/run/unity_test/raid_enc_top_functions_and_checks.md` | 功能点与检查点定义（FG/FC/CK），对齐测试的 mark_function 标注 |
| `verification_review/run/unity_test/raid_enc_top_verification_needs_and_plan.md` | 验证需求与计划 |
| `verification_review/run/unity_test/raid_enc_top_test_summary.md` | 原始测试清单 |
| `raid_enc_top_RTL/*.v` | RTL（本阶段仅用于解释失败现象，不必逐行深挖，dut_evidence 阶段再深入） |

引用行段一律写 workspace 相对 `path:start[-end]`（如 `unity_test/tests/test_x.py:10-64`、
`raid_enc_top_RTL/raid_regif.v:100-120`），Check 会逐条核实。

## 快速证据读取（先落盘，再取证）

pytest stdout 只出现在 `RunTestCases` 的文本返回里，批次报告不含失败文本。约定：
**每批 RunTestCases 的返回文本立即保存到 `{OUT}/diagnostics/run_logs/<批次标签>.txt`**，
之后用本 Skill 的脚本快速取证（不重跑、不手写解析）：

```text
RunSkillScript(commands=[["ext/bug_review/replay-review", "summarize_case_failures.py", "--save"]])
# 全量分诊入口：按 (异常, 失败位置) 签名分组全部失败 case，列出无证据 case；
# --save 落盘 {OUT}/diagnostics/failure_signatures.json（含每 case 的异常行/位置/调用帧/尾部）

RunSkillScript(commands=[["ext/bug_review/replay-review", "read_case_stdout.py",
                          "<case_id> [case_id ...] [--tail N] | --full"]])
# 逐 case 打印保存的 pytest traceback 原文（可多个 case 一次读取）
```

Skill 未启用或脚本缺失时：手工从保存的 run_logs 文本中切 `=+ FAILURES =+` 段落，
完成相同的取证与落盘；阶段产物与门禁要求不变。

## 操作

填写 `failure_analysis` 时严格区分五个字段：`scenario` 只写验证功能、激励和条件；`spec_expected` 只写 Spec 要求及 RTL 应有的可观测行为；`test_expected` 只写测试断言、完成条件和超时；`actual` 只写当前 case 的观测值、窗口、首个偏差和证据；`rationale` 只写测试有效性、归因理由和待补证据。每个字段至少包含当前 case 的差异事实，禁止把代表 case 的长段落原样复制到其他 case。推荐使用标签：`[功能]`、`[激励]`、`[条件]`、`[规格要求]`、`[RTL应有行为]`、`[测试断言]`、`[观测]`、`[窗口]`、`[首个偏差]`、`[证据]`、`[测试有效性]`、`[归因理由]`、`[待补证据]`。

调用 `DescribeReviewSchema(record_type="case")` 与 `DescribeReviewSchema(record_type="environment")` 取得字段。用 `summarize_case_failures.py` 得到签名分组，逐组读测试源码与 Spec 对应段落，再用 `read_case_stdout.py` 取个别代表 case 的完整 traceback；逐 case 填写 `failure_analysis` 的阶段、场景、规格预期、测试预期、实际行为、来源行段、归因和不确定性。分类区分环境、Spec 误读、测试实现/时序、疑似 DUT、规格歧义及证据不足；测试失败本身不构成 DUT Bug，同一签名的 case 若机理一致可共用归因逻辑但须逐条落字段。

必要时用 `RunTestCases` 定向复跑，并在 `replay.reruns` 记录与基线的关系；不得覆盖基线状态。填写 `environment_review.json` 的收集/执行、fixture/reset、驱动/采样、参考模型和种子/复现性六项审查；无法核实处写具体缺口。通过 `UpdateReviewRecord` 按文件更新。设 `stage_status.case_triage=complete` 后 Check、SetSkillUsage、日志、Complete。
