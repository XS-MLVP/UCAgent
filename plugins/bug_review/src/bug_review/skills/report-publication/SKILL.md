---
name: report-publication
description: Render and verify final module, failed-case and Bug pages before public promotion.
---

# Report Publication

## 操作

`{OUT}/review_index.json` 指向全部 case、Bug、根因、覆盖率、环境质量与对账记录。用以下命令生成并核验：

```text
RunSkillScript(commands=[["ext/bug_review/report-publication", "render_report.py", ""]])
RunSkillScript(commands=[["ext/bug_review/report-publication", "render_report.py", "--verify"]])
```

Skill 不可用时依次调用 `RenderBugReviewReport(verify_only=false)` 和 `RenderBugReviewReport(verify_only=true)`。产物在 `{OUT}/report/`：模块 `index.html`、`cases/` 失败详情、`bugs/` 缺陷详情、`sources/` 源码全文预览、可用时的 `surfer/` 静态前端与 `waveforms/` 原波形快照，以及 `report_manifest.json`。模块页用中文展示全集/缺口、失败归因、环境质量和覆盖率；缺陷主表仅列已确认且复核置信度不低于 0.8 的记录，其他裁决保留详情与数据。case 页展示场景、预期、实际、归因、波形与 Bug 关联；Bug 页的签名波形给出关键观察和完整预览入口，源码表链接到全文预览并高亮引用行段。渲染时仅归档与签名收据一致且仍存在的原波形；原文件已轮换时保留收据与分析，不生成伪预览。`--verify` 同时核对源码页面、锚点、波形快照、收据/viewer 与链接。

核验后 Check、SetSkillUsage、日志、Complete。完成回调把已核验 `report/` 发布到模块公开入口、重建 `output/index.html` 与独立的 `output/serve.py`，并记录 publish 状态；不用手工修改状态。总门户显示模块主表中已确认且置信度不低于 0.8 的去重根因组数，不显示原始 Bug 条目总数，也不插入指南链接。分享整个 `output/` 文件夹后，可在接收方的 `output/` 目录运行 `python3 serve.py` 查看报告与静态波形，无需插件或 UCAgent。若阶段已完成但门户缺失，运行 `python -m bug_review.workflow publish --workspace <run>` 恢复发布，不重跑测试或波形。
