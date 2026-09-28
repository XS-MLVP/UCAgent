---
name: waveform-review
description: Obtain signed default WaveInfo evidence for independently suspected DUT cases.
---

# DUT Evidence

## 操作

先调用 `CreateAttributionDraft` 创建空归因格式；可用 `ReportClaimBlocks` 分页查看原文 BG 标题、行段及原始 TC 标签，由你根据已完成的 case 初判在草稿中写初步 case→Bug 线索。原报告根因段不是独立波形或 RTL 证据。此阶段无需填完全部 Bug，完整归因留到 `report_reconcile`。已有草稿继续编辑，不重新创建。

对 `failure_analysis.category=suspected_dut` 或时序争议 case，先调用 `ResolveReviewCase(case_id=...)`，逐字使用返回的 `waveform_test_case_name`。默认 `WaveInfo` 最终取证会预检该身份；非索引名称不会产生最终签名收据。先探测信号目录和事件，再以有效事务窗口、非空事件 pattern 和完整信号组取得最终 receipt。长窗口关注 `clamped_to_waveform` 与 `timeline_truncated`；超限时提高 `max_signals` 或缩小窗口。

信号组要包含时序 DUT 的真实时钟、相关输入/选择/使能、输出/状态/有效位、真实接受/响应控制和至少一条功能选择/状态/错误传播路径；组合 DUT 声明 `combinational` 且不虚构时钟。viewer 显示同一签名集合，不能只看结果信号。可在 `{OUT}/wave_signal_presets.json` 的 `presets` 下存命名组，最终 WaveInfo 用 `signal_group_preset` 展开；收据签名的是展开后的精确路径。

调用 `ApplyReceiptToCase(case_id, receipt_id)`，让工具直接复制签名窗口、信号组与 viewer URL。之后只补写观察、对齐和源码分析。`ValidateCaseRecords` 可随时检查；无可用收据写具体诊断并保持未定。设 `stage_status.dut_evidence=complete`，Check、SetSkillUsage、日志、Complete。
