---
name: report-publication
description: Render and verify final module, failed-case and Bug pages before public promotion.
---

# Report Publication

## 操作

`{OUT}/review_index.json` 指向全部 case、Bug、根因、覆盖率、环境质量与对账记录。依次调用 `RenderBugReviewReport(verify_only=false)` 和 `RenderBugReviewReport(verify_only=true)`，直接生成并核验工作区 `report/` 下的模块首页、case、Bug、源码、波形快照和 `report_manifest.json`。模块页用中文展示全集/缺口、失败归因、环境质量和覆盖率；缺陷主表仅列已确认且复核置信度不低于 0.8 的记录，其他裁决保留详情与数据。case 页展示场景、预期、实际、归因、波形与 Bug 关联；每个 ROOT 一个详情页，现象入口跳到其锚点；右侧一个主要预览和多个完整波形入口，逐条注明支持的现象和 case，Spec/RTL 链接到高亮行段。渲染时仅归档与签名收据一致且仍存在的原波形；原文件已轮换时保留收据与分析，不生成伪预览。`--verify` 同时核对源码页面、锚点、波形快照、收据/viewer 与链接。

核验后 Check、SetSkillUsage、日志、Complete。完成回调重建 `output/index.html` 与独立的 `output/serve.py`，并记录 publish 状态；不用手工修改状态。总门户显示模块主表中已确认且置信度不低于 0.8 的去重根因组数，不显示原始 Bug 条目总数，也不插入指南链接。分享整个 `output/` 文件夹后，可在接收方的 `output/` 目录运行 `python3 serve.py` 查看报告与静态波形，无需插件或 UCAgent。若阶段已完成但门户缺失，运行 `make publish_<module>` 恢复发布，不重跑测试或波形。

## Current ROOT and evidence contract

Render current verified records: one ROOT detail with member phenomena and their own case/execution support; one explicit main preview and multiple labelled full-wave links. Keep original identifiers, tokens and decisions intact. Missing snapshots or event coverage remain visible delivery gaps. This stage does not invent steps, event times, classifications or root decisions. See `Guide_Doc/bug_review_writing.md` and `Guide_Doc/bug_review_example_root.md`.

Long signed windows use an event-centered thumbnail interval, at most 64 raw ticks before and after the checked event, clipped to the signed window. Show its measured bounds and retain every local transition. Full Surfer links keep the original signed window, receipt and snapshot.

## Sourced reader context

Render previously submitted dut_context, affected_behavior, signal_explanations and causal_steps; do not generate missing analysis in the renderer or publication stage. Default sections focus on DUT purpose, verification goal, defect scenario and RTL propagation. Keep routine case operations and deduplicated receipt downloads collapsed. See Guide_Doc/bug_review_example_ptw.md.
