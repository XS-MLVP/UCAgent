
# 最终设计报告

最终报告只总结 Check/Complete 从全部完整、功能通过的 accepted 版本中选出的 best 源码和 PPA。不得把 rejected candidate 写成最终版本。终止状态后的 Complete 还会执行一次最终全量一致性门禁：从 `{OUT}/tests/test_{DUT}_*.py` 收集唯一 TC 集合，用同一组文件分别运行 Python reference 和最新 RTL；两边每个节点都必须通过，且最终 RTL 的 `uc_test_report/toffee_report.json` 必须覆盖完整集合。机器收据写入 `{OUT}/reports/{DUT}_final_all_tc_validation.json`，其中保存两边的节点、状态、测试源哈希以及最终 Toffee 报告哈希。终止状态后的 Check 会生成 `{OUT}/{DUT}_performance_curve.json`：该文件按连续 `version`（base 为 0，随后每次候选递增 1）保留所有评估版本的 accepted/rejected/omitted 状态；只有具备完整功能、性能和 PPA 证据的版本才包含指标曲线点。功能或 PPA 证据不完整的 candidate 同时记录在 `omitted_iterations` 和连续版本表中，不得伪造曲线点或手工编辑曲线 JSON。`{OUT}/reports/ppa/iterations/iteration-XXX.json` 对每个版本都存在并使用同一个编号。`{OUT}/{DUT}_ppa_dashboard.html` 由工作流模板预置，浏览器直接绘制响应式曲线，不再维护一份可能与数据分离的 SVG 文件。

`design_summary` fenced YAML 只记录公开交付身份、停止原因、最少/最大配置轮数、连续无改善计数、接受门禁保护的指标类别（`no_regression_metrics`，默认 `[performance, timing]`）、最佳版本和报告路径。正文必须给出功能覆盖、base 到 final 的指标变化、被拒候选、未满足风险和复现方式，并用相对 Markdown 链接打开同目录看板。方向归一化定义为：`max` 指标使用 `(current - base) / abs(base) * 100`，`min` 指标使用 `(base - current) / abs(base) * 100`；正值表示改善。非零 current 遇到零 base 时 JSON 使用 `null` 和 `zero_baseline`，不生成 NaN 或 Infinity。曲线中的单一 `ppa.selection_score` 以 base 为 1.0，使用 `timing_efficiency^w_t * area_efficiency^w_a * power_efficiency^w_p`（指数由 `design_with_ppa.score_weights` 配置，默认各 1.0；自定义性能指标不设权重，性能维度只由 frequency/critical delay 体现），越大越好，只是 accepted 版本上的诊断排名：交付的 best 版本由保护类别上的 Pareto 支配选择确定（curve 的顶层 `best_iteration` 与 `iterations[].best` 标记），当未保护类别（如面积/功耗）回退换得保护类别改善时，score 最大值可以与交付 best 不同，这属于合法分歧而非证据不一致。rejected 版本的诊断 score 不具备任何资格。接受门禁为：`no_regression_metrics` 列出的指标类别中任何指标不得相对上一 accepted 版本回退，且至少一项主要指标严格改善。

看板是确定性机器产物，不得手工补写数据。最终 Check 会把当时已验证的 state、final PPA 和 curve 作为只读 JSON 快照安全内嵌，因此 `file://` 直接打开即可显示完整结果；目录选择器可以改读所选 workspace 的更新文件。通过相对 HTTP URL 打开时，每 15 秒重新读取相对路径并自动刷新。页面提供 Toffee HTML 入口以及 Dark、Light、Graphite 三套主题，迭代记录默认每页 50 个版本，可用下拉选项或自定义整数调整（1 到 1000）。主题、accepted/rejected 与指标筛选、分页状态只保存为带 DUT 和输出目录命名空间的浏览器偏好：HTTP 模式使用 `localStorage`，`file://` 模式还使用当前 URL fragment 以保证刷新后恢复；两者都不写入 workspace。每一行还会自动提供该版本不可变 RTL 源码、快照 manifest 和当轮验证报告的只读相对链接；accepted 行指向 accepted 快照，rejected 行指向被恢复前的 candidate 快照。LLM 不得手写、猜测或修改这些链接。

## 完整最终报告示例

````markdown

# Adder 单元模块设计总结

## 交付摘要

最终 RTL 已通过 Python/RTL 共用功能回归和性能用例。达到最少候选轮数后，连续三个候选均无可接受改善，最终版本保持 round 0。

## 机器摘要

```yaml
design_summary:
  schema_version: "1.2"
  dut: Adder
  top_module: Adder
  accepted_iteration: 0
  stop_reason: no_pareto_improvement
  min_optimization_iterations: 5
  max_optimization_iterations: 1000
  no_improvement_patience: 3
  no_regression_metrics: [performance, timing]
  no_improvement_count: 3
  best_iteration: 0
  best_report_id: ppa-example-report-id
  performance_curve_json: design/Adder_performance_curve.json
  final_ppa_report: design/Adder_final_ppa_report.json
```

## 功能结果

- Python executable-spec regression: Pass
- RTL design regression: Pass
- FG/FC/CK mapping: complete

## PPA 摘要

| 指标 | Base | Final | 变化 |
| :--- | ---: | ---: | :--- |
| Area | 42.0 | 42.0 | unchanged |
| Critical delay | 0.80 ns | 0.80 ns | unchanged |
| Power | 0.0012 W | 0.0012 W | unchanged |
| PPA score | 1.0× | 1.0× | unchanged |

## 版本性能曲线

版本表包含连续的 round 0、round 1、round 2……；只有完整证据版本进入指标曲线，因此功能失败版本会显示为无指标的 omitted 行而不是虚构数据。看板中的灰色空心点和灰色行表示未接受版本，指标变化仍按正负值标出改善或退化。单一 PPA score 曲线以 base 为 1.0；rejected 点仅用于诊断，最终 best 只从 eligible accepted 点中选择。每行的 `Sources and reports` 入口由最终 Check 从已验证快照生成，可直接查看该轮的全部 RTL 源文件及机器报告。

## 结果看板

[打开 PPA 优化进度、报告与版本性能曲线](Adder_ppa_dashboard.html)

## 复现

使用同一 README、Spec、RTL 语言配置和性能配置重新运行工作流；功能测试、性能用例与 PPA 分析由 Check/Complete 复验。
````

## 最终全量 TC 收据示例

Complete 生成的 `{OUT}/reports/{DUT}_final_all_tc_validation.json` 必须记录同一套
pytest 节点在两个 backend 的结果。以下是完整的最小通过结构；`test_cases` 顺序按节点
字典序稳定保存，RTL 条目指向最后一次生成的原始 Toffee JSON。

```json
{
  "schema_version": "1.0",
  "status": "pass",
  "test_cases": ["design/tests/test_Adder_functional.py::test_add"],
  "test_case_count": 1,
  "test_source_rows": [
    {"path": "design/tests/test_Adder_functional.py", "sha256": "...64 hex..."}
  ],
  "test_source_sha256": "...64 hex...",
  "same_test_cases": true,
  "python": {
    "status": "pass",
    "test_cases": [
      {"node_id": "design/tests/test_Adder_functional.py::test_add", "status": "PASSED"}
    ],
    "test_case_count": 1,
    "report_path": "uc_test_report/toffee_report.json",
    "report_sha256": "...64 hex...",
    "snapshot_path": "design/reports/design_with_ppa/python_toffee_report.json",
    "snapshot_sha256": "...64 hex...",
    "source_sha256": "...64 hex..."
  },
  "rtl": {
    "status": "pass",
    "test_cases": [
      {"node_id": "design/tests/test_Adder_functional.py::test_add", "status": "PASSED"}
    ],
    "test_case_count": 1,
    "report_path": "uc_test_report/toffee_report.json",
    "report_sha256": "...64 hex...",
    "snapshot_path": "design/reports/design_with_ppa/rtl_toffee_report.json",
    "snapshot_sha256": "...64 hex...",
    "source_sha256": "...64 hex..."
  },
  "toffee_report": {
    "backend": "rtl",
    "report_path": "uc_test_report/toffee_report.json",
    "report_sha256": "...64 hex...",
    "all_test_cases": true,
    "html_path": "uc_test_report/index.html"
  },
  "checked_at": "2026-01-01T00:00:00+00:00"
}
```
