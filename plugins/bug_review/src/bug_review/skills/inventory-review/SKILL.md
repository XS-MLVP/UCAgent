---
name: inventory-review
description: Collect every pytest node, preserve original Bug pointers and import the full replay baseline.
---

# Full Replay

## 目标

从当前 run 工作区收集全部 pytest node ID。原报告仅索引 Bug ID、来源行段、原置信度和未归属的原始 case 标签；BG／FC／CK 及 Bug→case 归属由 LLM 在独立 case 初判后填写。

## 操作

用 `ReadTextFile` 阅读 `Guide_Doc/analysis.md`，然后调用 `PrepareReviewInventory`。该工具创建 `{OUT}/review_index.json`、`test_manifest.json`、`replay_summary.json`、`coverage.json`、`environment_review.json`、`report_reconciliation.json`、逐 case 骨架和空的 `wave_signal_presets.json`。`test_manifest.json.collected` 是全集。pytest 收集使用本次运行的可写 `verification_review/run/test_report/`，不改只读测试副本或 `.pytest.ini`。收集失败时读 `{OUT}/diagnostics/collection.log`，修复具体权限或动态库加载问题后重试；失败不生成权威索引，不可凭部分 node 继续。

用 `RunTestCases(pytest_args="<test_manifest.json.pytest_target>")` 运行全集；分批时按收集项传精确 node，并保留相同 pytest 配置。每批结束立即调用 `CaptureReplayReport`，将真实报告快照及精确 node 结果写入 case 与 `replay_summary.json`。缺失结果保留 `not_run`，填写具体阻断原因；原报告关联但本次未收集的 case 也写明原因，不能按原报告推断 Pass/Fail。核对全集、排除项、报告快照和覆盖率口径，设 `stage_status.full_replay=complete`，然后 Check、SetSkillUsage、日志、Complete。
