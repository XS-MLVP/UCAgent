
# Bug Review 分析指导

## 输入与目标

输入是只读的 `inputs/workspace_*` UnityTest 工作区。阅读原 Bug 摘要、动态 Bug 文档、规格、RTL、测试和本次执行证据，逐条裁决原声明并审查新失败。原声明始终保留；排除 DUT Bug 时 `review_confidence` 为 `0`。相同 RTL 首错和因果链的条目合并为一个根因组，但每个 Bug 的 CK、TC 与证据仍独立可查。

每阶段先调用 `BugReviewRunStage(stage=当前阶段)`。返回 `awaiting_judgments` 时调用 `BugReviewTasks`，读取 `messages` 和身份字段，再通过 `BugReviewSubmitResponse` 提交。待办清空后重调 `BugReviewRunStage`；Check 通过后记录日志并 Complete。输入代码不可修改，分析笔记写入 `notes/`。

`notes/bug_review_notes.md` 是可选的工作笔记。若 CurrentTips 列出 `ext/bug_review/review-notes`，可读取其 SKILL.md 并在阶段产物完成后用 `sync_review_notes.py` 更新阶段摘要；未列出时直接阅读 `{OUT}` 下的产物，也可手工更新笔记。笔记中的人工记录会在摘要刷新时保留。Checker 只接受结构化产物和真实工具证据，不把笔记当作测试、波形或裁决收据。

## inventory：输入与骨架

核对 `{OUT}/input_inventory.json` 及每个工作区的 `bug_inventory.json`、`bug_outline.md`。骨架列出原 Bug ID、声明、相关 TC/CK、RTL 和 ROOT 候选，以及待核实事项。候选位置仅是调查起点。

`bug_outline.md` 的完整例子如下；实际内容由输入解析生成：

```markdown

# example_dut Bug 复核骨架

输入工作区：/absolute/path/inputs/workspace_example_dut

## DATA-HOLD

输出背压期间数据必须保持稳定。

- 关联测试：unity_test/tests/test_example_dut_output.py::test_data_hold
- CK：FG-OUTPUT/FC-DATA/CK-HOLD
- Spec 候选：example_dut/SPEC.md:42-48
- RTL 候选：example_dut_RTL/output_ctrl.v:80-88
- ROOT 候选：ROOT-OUTPUT-HOLD
- 待核实：测试正确性、规格预期、重跑结果、波形有效窗口和 RTL 因果链
```

## replay：重跑与测试正确性

本阶段只使用隔离副本中本次执行的报告判断复现状态。逐项阅读 `BugReviewTasks` 中的失败证据，独立从规格推导 `specification_expected`，核对 `exact_input`、`test_expected`、`dut_actual`、driver/fixture、参考模型、复位、握手和采样时序。

提交 `classification`、`correctness_confirmed`、上述四个事实字段、`driver_timing_review`、`rationale` 和非空 `evidence_refs`。分类可选 `suspected_dut_bug`、`spec_misunderstanding`、`testbench_issue`、`environment_issue`、`inconclusive`。只有测试正确性已核实才能选 `suspected_dut_bug`。未复现只是一项执行状态。报告缺失、无用例、收集失败或运行错误不能解释为零失败。

## waveform：波形与事务

对本次仍失败且没有明确环境诊断的用例，先调用 `BugReviewWaveInfo(task_id=任务ID, query={})` 获取精确 `test_case_name` 和波形目录。最终请求指定真实 `signal_groups`、定位用的 `pattern`，以及 `start_step/end_step` 或 `logged_cycle/clock_signal`。信号组覆盖时钟（若有）、相关输入输出、真实请求接受/响应有效控制和关键状态路径。

结合规格和测试驱动代码核对事务归属、握手、有效窗口和响应延迟。日志 cycle 与波形 step 通过时钟出现序号及事务上下文对齐。提交 `conclusion`、工具返回的 `evidence_id`、`alignment_evidence`、`observed_behavior`、`source_correlation`、`rationale` 和 `evidence_refs`。无法取证时保留工具错误并选 `inconclusive`；不得自行生成证据 ID、receipt、viewer 或信号值。

## correlate：逐 Bug 裁决

每个任务包含一个原声明或一个新失败，以及关联的 replay/waveform 证据。完整响应结构如下；`evidence_refs` 必须是当前任务证据内存在且非空的路径：

```json
{
  "verdict": "confirmed",
  "review_confidence": 0.95,
  "rationale": "正确测试在有效握手后观察到输出数据改变，与规格保持条件冲突。",
  "spec_ref": "example_dut/SPEC.md:42-48",
  "rtl_ref": "example_dut_RTL/output_ctrl.v:80-88",
  "first_error": "背压期间输出寄存器仍推进",
  "causal_chain": "推进使旧事务数据被下一拍覆盖，产生输出保持违例。",
  "evidence_refs": ["/bug/summary", "/cases/0/waveform/verified_evidence"]
}
```

`verdict` 为 `confirmed`、`refuted` 或 `inconclusive`。`confirmed` 需要正确测试稳定失败、真实签名波形，以及现存输入文件中的 Spec/RTL 行号；置信度为大于 0 且不超过 1 的数值。`refuted` 必须使用 `review_confidence: 0`；`inconclusive` 使用 `null`。后两类在来源确实不可得时可留空 `spec_ref`、`rtl_ref`、`first_error` 和 `causal_chain`，但须说明依据或缺口。相同根因使用一致的 `rtl_ref`、`first_error` 和 `causal_chain`，以便形成共同根因组；不能因为标题或症状相似就合并。

## publish：报告

`report_data.json` 是 HTML 的事实来源。检查总索引列出全部输入工作区，各工作区页面列出原 Bug、新发现、复现和裁决状态；每个 Bug 详情保留原置信度、复核置信度、关联 TC、波形、Spec、RTL 和根因组。没有确认 Bug 时仍发布原声明的排除或未定结果。页面链接必须能够打开对应的详情和结构化证据。
