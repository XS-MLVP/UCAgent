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
