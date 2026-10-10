---
name: inventory-review
description: Collect every pytest node, preserve original Bug pointers and import the full replay baseline.
---

# Full Replay

## 目标

从当前 run 工作区收集全部 pytest node ID。原报告仅索引 Bug ID、来源行段、原置信度和未归属的原始 case 标签；BG／FC／CK 及 Bug→case 归属由 LLM 在独立 case 初判后填写。

## 操作

用 `ReadTextFile` 阅读 `Guide_Doc/analysis.md`，然后调用 `PrepareReviewInventory`。该工具创建 `{OUT}/review_index.json`、`test_manifest.json`、`replay_summary.json`、`coverage.json`、`environment_review.json`、`report_reconciliation.json`、逐 case 骨架和空的 `wave_signal_presets.json`。`test_manifest.json.collected` 是全集。pytest 收集使用本次运行的可写 `verification_review/run/test_report/`，不改只读测试副本或 `.pytest.ini`。收集失败时读 `{OUT}/diagnostics/collection.log`，修复具体权限或动态库加载问题后重试；失败不生成权威索引，不可凭部分 node 继续。

用 `RunTestCases(pytest_args="<test_manifest.json.pytest_target>")` 运行全集；分批时按收集项传精确 node，并保留相同 pytest 配置。每批结束立即使用返回的精确invocation_id调用 `CaptureReplayReport(invocation_id="...")`，将真实报告快照及精确 node 结果写入 case 与 `replay_summary.json`；最后一批补齐全集后，该工具从各次不可覆盖的快照核对来源并聚合覆盖证据，在baseline-coverage目录保留原始来源及稳定引用，然后将可核实的全量统计写入 `coverage.json`；来源或口径不一致时写unavailable及原因，你只核对这些字段并按需在 `basis` 补充口径说明，不要手写 `source_ref`。全集导入完成时还会自动清理不再需要的波形：每次运行的波形已由工具自动整体搬入 `unity_test/data` 下以其时间戳命名的新会话目录（一次运行一个目录，永不覆盖），导入只删除全部会话中通过/跳过 case 的 fst/dat 波形，失败、错误、xfailed、xpassed 及无法归属 case 的波形在各自会话中保留供 dut_evidence 使用；不要手工增删波形文件，确需通过 case 的波形时按 case_triage 的定向复跑生成。缺失结果保留 `not_run`，填写具体阻断原因；原报告关联但本次未收集的 case 也写明原因，不能按原报告推断 Pass/Fail。核对全集、排除项、报告快照和覆盖率口径，设 `stage_status.full_replay=complete`，然后 Check、SetSkillUsage、日志、Complete。Check 失败若指向记录字段，用 `UpdateReviewRecord` 修正该字段后重新 Check；已完成的测试运行绝不因记录字段重复执行，且已导入的基线不可重复导入。
