
# {{DUT}} 单元模块设计总结

只有在 PPA 优化阶段返回终止状态后，才根据 Check/Complete 给出的公开指标填写本文件。

## 机器摘要

```yaml
design_summary:
  schema_version: "1.2"
  dut: {{DUT}}
  top_module: {{DUT}}
  accepted_iteration: 0
  stop_reason: replace-from-check
  min_optimization_iterations: 5
  max_optimization_iterations: 1000
  no_improvement_patience: 3
  no_regression_metrics: [performance, timing]
  no_improvement_count: 0
  best_iteration: 0
  best_report_id: replace-from-check
  performance_curve_json: {{OUT}}/{{DUT}}_performance_curve.json
  final_ppa_report: {{OUT}}/{{DUT}}_final_ppa_report.json
```

## 功能结果

待从 Python 和 RTL regression receipts 汇总。

## PPA 摘要

待从 base/final PPA 摘要汇总面积、时序与功耗变化。

## 版本性能曲线

待从自动生成的曲线 JSON 汇总 accepted/rejected 版本、原始指标和相对 base 的方向归一化改善百分比。浏览器看板直接从 JSON 绘制响应式曲线。

## 结果看板

[打开 PPA 优化进度、报告与版本性能曲线]({{DUT}}_ppa_dashboard.html)

## 复现

待记录使用同一 README、Spec、RTL 语言配置和性能配置重新运行工作流的方法；验证由 Check/Complete 执行。

## Final RTL synchronization

```yaml
rtl_synchronization:
  schema_version: "1.0"
  status: pending-final-rtl-sync
  rtl_language: {{RTL_LANGUAGE_ID}}
  top_module: {{DUT}}
  source_files: []
  rtl_source_sha256: replace-from-final-check
  all_test_cases_passed: false
  test_case_count: 0
  test_source_sha256: replace-from-final-check
  toffee_report_sha256: replace-from-final-check
```
