---
name: waveform-review
description: Obtain signed default WaveInfo evidence for independently suspected DUT cases.
---

# DUT Evidence

## 操作

先调用 `CreateAttributionDraft` 创建空归因格式；可用 `ReportClaimBlocks` 分页查看原文 BG 标题、行段及原始 TC 标签，由你根据已完成的 case 初判在草稿中写初步 case→Bug 线索。原报告根因段不是独立波形或 RTL 证据。此阶段无需填完全部 Bug，完整归因留到 `report_reconcile`。已有草稿继续编辑，不重新创建。

对 `failure_analysis.category=suspected_dut` 或时序争议 case，先运行 `scripts/check_wave_availability.py` 一次性盘点目标 case 的 dump 可用性：已有 fst/vcd 的 case 直接取证，仅对缺失或仅有 dat 的 case 用脚本输出的 pytest 目标定向复跑，不整批重跑。基础设施错误导致已生成的波形丢失时，先留存缺失诊断、修复错误，再按明确盘点的精确 node 定向补取证；登记新的 invocation_id、参数、状态与 case.replay.reruns，不覆盖 baseline 或借用旧执行身份。普通 Check 不自动触发复跑。每次运行的波形都自动保存在 `unity_test/data` 下各自的 toffee_tmp 时间戳目录中，永不覆盖；除盘点指出的定向复跑外，本阶段不得再次运行任何测试。随后调用 `ResolveReviewCase(case_id=...)`，逐字使用返回的 `waveform_test_case_name`（不要自行拼接路径或补 `.py` 后缀）。默认 `WaveInfo` 最终取证会预检该身份；非索引名称不会产生最终签名收据。优先一次取证：直接以有效事务窗口、非空事件 pattern 和完整信号组取得最终 receipt，不要先做只探测不取证的预跑；返回 `evidence_window_required` 时逐字按返回的 `recommended_evidence_call` 重试同一 case，仅当返回 `metadata_only` 或 `signal_not_found` 时才降级探测，精确信号名以收据返回的 `signal_groups` 或 `{OUT}/wave_signal_presets.json` 为准，未知信号用 regex pattern 探索，不从 RTL 源码猜完整层级路径。不要把 `max_points`/`max_signals` 设得低于默认，timeline 截断会让 `evidence_usable=false` 整次作废；长窗口关注 `clamped_to_waveform` 与 `timeline_truncated`，超限时提高 `max_signals` 或缩小窗口。

信号组要包含时序 DUT 的真实时钟、相关输入/选择/使能、输出/状态/有效位、真实接受/响应控制和至少一条功能选择/状态/错误传播路径；组合 DUT 声明 `combinational` 且不虚构时钟。viewer 显示同一签名集合，不能只看结果信号。可在 `{OUT}/wave_signal_presets.json` 的 `presets` 下存命名组，最终 WaveInfo 用 `signal_group_preset` 展开；收据签名的是展开后的精确路径。

调用 `ApplyReceiptToCase(case_id, receipt_id)`，让工具直接复制签名窗口、信号组与 viewer URL。之后只补写观察、对齐和源码分析。`ValidateCaseRecords` 可随时检查；无可用收据写具体诊断并保持未定。设 `stage_status.dut_evidence=complete`，Check、SetSkillUsage、日志、Complete。

## Current ROOT and evidence contract

Record each case's ordered scenario_steps and actual execution reach, then bind its own events to exact invocation, signed receipt, original timestamp, full signal and raw value. Software records and decoded fields are not independent waveform signals. Preserve earlier attached receipts in additional_waveforms; never replace another case's observations or write a root decision during this stage. See `Guide_Doc/bug_review_writing.md` and `Guide_Doc/bug_review_example_rcmd.md`.


Use `ApplyWaveformEvent` after attaching the receipt and submitting any referenced scenario step. Supply the exact case/execution, signed signal path and raw waveform timestamp plus sourced interpretation. The tool reads `raw_value` from the unchanged source snapshot; do not transcribe hex strings into the binary field. Missing or changed snapshots are evidence gaps, not permission to invent values. Use `CreateCaseDraft` for other case edits and submit at most five cases with `UpdateCaseRecords`.


Begin an unknown-signal investigation with `ReviewSignalCatalog(case_id, contains, offset, limit)` and use its real full paths and raw time bounds. Reuse that catalog within the same snapshot. `ReviewWorkQueue` groups only shared reading context; each Case retains its own measurements. Use `ReviewCaseContext` rather than repeatedly reading the full index/schema. If Check reports `no_progress`, inspect its exact gap and pause identical retries.

本阶段查询 `ReviewWorkQueue(stage="dut_evidence", limit=5)`，包含尚缺的签名波形证据；Case 的分析文字通过 CreateCaseDraft → PatchCaseDraft → UpdateCaseRecords 修订，收据与事件继续使用专用工具。

WaveInfo 参数优先级：非空 `signal_groups` 覆盖 `signal_group_preset`；只有未提供显式分组时才展开预设。显式分组仍必须通过完整性与精确路径校验，失败时不回退到预设。`recommended_evidence_call` 会清空预设名，直接使用其中的完整参数取得后续收据。

### 断言终止与波形完整性

`insufficient_evidence` / `spec_ambiguous` 是调查待办，不能通过写一句缺口说明跳过 `dut_evidence`。默认盘点所有尚未排除 DUT 的失败项，检查 FST/VCD 是否可解析及实际起止时间；文件存在不等于可解析，可解析也不代表整个测试流程执行完。

先核对 traceback、API 与 fixture：assert/TimeoutError 会终止当前测试调用，但 pytest 正常 teardown 仍应执行 `Finish()`。区分空/损坏文件、teardown/进程崩溃、以及断言后操作未执行；不可直接把短波形称为损坏。`scenario_steps` 必须记录已执行步骤、失败位置和 `not_reached` 操作。用现有窗口分析失败之前的请求、接受、响应、采样与内部传播；例如 P 区读回断言失败后，Q 区访问尚未执行，仍应分析 P 区写读链路。禁止移除断言、强制继续原 Case 或把补充运行伪装为原始证据。

有可用收据时，即使仍未定，也要通过 `CreateCaseDraft → PatchCaseDraft → UpdateCaseRecords` 填写 `waveform.observed_behavior`、`waveform.alignment_evidence`、`waveform.source_correlation`。这些是分析字段；receipt、window、signal_groups、viewer 仍只能由证据工具写入。

真实无法取证时，执行精确 Case 的 WaveInfo，把失败收据 ID 写入 `waveform.diagnostic_receipt_id`，诊断写入 `waveform.diagnostic`。空/缺失/不可解析 dump 必须先检查 Finish/flush/teardown 并记录定向恢复复跑；元数据探测、参数错误、找错信号或仅写“待补波形”不能完成调查。确认依赖缺失可用同一 Case 的 `wavekit_unavailable` 失败收据记录阻塞，不循环复跑测试。

## Measured observations and incremental edits

For each unresolved failed Case with readable evidence, use ApplyWaveformEvent to record an actually reached boundary from the signed window. A trigger or normal_reference is valid when no deviation is proven. Save scenario_steps and narrative incrementally; stage Check requires complete investigation. Archived additional_waveforms are not independent Cases. Patch their narrative with additional_waveforms.0.observed_behavior and related analysis leaves when needed; receipt identity remains protected. See Guide_Doc/analysis.md section 未定声明调查.
