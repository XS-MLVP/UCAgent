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

Skill 不可用时依次调用 `RenderBugReviewReport(verify_only=false)` 和 `RenderBugReviewReport(verify_only=true)`。产物在 `{OUT}/report/`：模块 `index.html`、`cases/` 失败详情、`bugs/` 疑似 Bug 详情和 `report_manifest.json`。模块页展示全集/缺口、失败归因、环境质量、覆盖率及 Bug 列表；case 页展示场景、预期、实际、归因、波形与 Bug 关联；Bug 页展示原声明、Spec/RTL、裁决和根因。

核验后 Check、SetSkillUsage、日志、Complete。完成回调把已核验 `report/` 发布到模块公开入口、重建 `output/index.html` 并记录 publish 状态；不用手工修改状态。若阶段已完成但门户缺失，运行 `python -m bug_review.workflow publish --workspace <run>` 恢复发布，不重跑测试或波形。
