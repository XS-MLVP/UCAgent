
# 性能合同

性能合同位于 `{OUT}/{DUT}_performance_contract.yaml`。每个指标必须追溯到真实 Spec 文件和物理行，声明单位、优化方向、聚合方法和精确 pytest node ID。Spec 没有数值阈值时使用 `target: null`、`hard_requirement: false`，base 实测值成为非退化基线。

## 完整合同示例

```yaml
schema_version: "1.0"
dut: Adder
top_module: Adder
metrics:
  - id: add_latency
    kind: latency
    source:
      path: Adder/spec/performance.md
      line: 8
    unit: ns
    direction: min
    target: 2.0
    hard_requirement: true
    aggregation: max
    measurement_test: design/tests/test_Adder_performance.py::test_Adder_performance_latency
    clock_or_time_base: waveform-timescale
  - id: add_throughput
    kind: throughput
    source:
      path: Adder/spec/performance.md
      line: 12
    unit: transaction/ns
    direction: max
    target: null
    hard_requirement: false
    aggregation: mean
    measurement_test: design/tests/test_Adder_performance.py::test_Adder_performance_throughput
    clock_or_time_base: waveform-timescale
```

`latency`、`area` 和 `power` 通常使用 `direction: min`；`throughput` 和 `frequency` 使用 `direction: max`。custom 指标必须由 Spec 明确其方向和单位。
