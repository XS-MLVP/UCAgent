---
name: inventory-review
description: Collect every pytest node, preserve original Bug pointers and import the full replay baseline.
---

# Full Replay

## 目标

从 `review_job.json` 选中的模块收集全部 pytest node ID。原报告仅机械索引 Bug ID、来源行段、原置信度与关联 case；本阶段不依据旧根因解释失败。

## 操作

用 `ReadTextFile` 阅读 `Guide_Doc/analysis.md` 和 `review_job.json`。执行：

```text
RunSkillScript(commands=[["ext/bug_review/inventory-review", "create_review_json.py", "<workspace>"]])
```

脚本创建 `{OUT}/review_index.json`、`test_manifest.json`、`replay_summary.json`、`coverage.json`、`environment_review.json`、`report_reconciliation.json`、每个 case 骨架和空的 `wave_signal_presets.json`。Skill 不可用时调用 `PrepareReviewInventory`，产物相同。`test_manifest.json.collected` 是全集；收集失败保留 `collection_errors`。

用 `RunTestCases(pytest_args="<test_manifest.json.pytest_target>")` 运行全集；分批时按收集项传精确 node，并保留相同 pytest 配置。每批结束立即调用 `CaptureReplayReport`，将真实报告快照及精确 node 结果写入 case 与 `replay_summary.json`。缺失结果保留 `not_run`，填写具体阻断原因；原报告关联但本次未收集的 case 也写明原因，不能按原报告推断 Pass/Fail。核对全集、排除项、报告快照和覆盖率口径，设 `stage_status.full_replay=complete`，然后 Check、SetSkillUsage、日志、Complete。
