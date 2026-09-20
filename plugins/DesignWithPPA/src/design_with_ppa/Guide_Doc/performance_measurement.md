
# 性能测试与波形证据

性能测试位于独立 Stage。必须至少实现两个 pytest 函数，函数名统一使用
`test_{DUT}_performance_*`，并添加 `@pytest.mark.performance`。每个函数必须与性能合同中一个
或多个 `measurement_test` 精确对应。性能值来自仿真 time/cycle、clock occurrence、请求接受与
响应 transaction，禁止使用 pytest 或操作系统 wall-clock。

共享 `conftest.py` 必须保留 `pytest_configure(config)`，并使用
`config.addinivalue_line("markers", "performance: ...")` 注册该 marker。不要用局部
`pytest.ini` 注册，否则 pytest rootdir 和精确 TC node ID 可能改变。

每个 TC 使用确定性 stimulus 或固定 seed，并保持固定 observation window。Python backend
先验证 stimulus、功能结果和指标计算；RTL backend 使用同一函数和输入，在 fixture 已绑定的
唯一 VCD/FST 上记录真实 activity。不得手写、拼接、复制或从 reference 合成波形。

## 每个性能 TC 的步骤

1. 使用共享 API/adapter 执行确定性输入；adapter 在握手接受边沿后记录
   `last_transaction_timing = (accepted_at, response_at)`。
2. 从该仿真时间对记录 transaction 起点和终点，不得用 API 调用前的时间代替接受时间。
3. 用 `measure_latency`、`measure_cycle_latency` 或 `measure_throughput` 计算有限值。
4. 对功能结果和性能值做真实断言；Python backend 在此完成，不创建波形或 sidecar。
5. RTL backend 继续仿真到固定 observation-window 终点，不因候选更快而提前截断。
6. 调用 `env.flush_waveform()`，确认 fixture 绑定的 `env.waveform_path` 已落盘。
7. 最后调用 `write_performance_result`；一份 sidecar 只归属当前精确 pytest node ID。

`stimulus_manifest` 必须包含 `deterministic`、`seed`、`parameters`、`start_time`、`end_time`、
`time_unit`、`transaction_count` 和非空 `input_trace`。固定向量可使用 `seed: None`，但此时
`deterministic` 必须为 `True`。随机向量必须记录非负整数 seed。所有 duration 必须大于零，
不接受 NaN、Infinity、负时长或零分母。

## 完整性能测试文件示例

```python
"""Deterministic simulation-time performance tests for Adder."""

import pytest

from design_with_ppa import measure_latency, measure_throughput, write_performance_result
from Adder_api import api_Adder_add


@pytest.mark.performance
def test_Adder_performance_latency(env, request):
    """Measure response latency for one accepted request."""

    result = api_Adder_add(env, 4, 7, max_cycles=4)
    start_time, end_time = env.last_transaction_timing
    latency = measure_latency(start_time, end_time, "ns")
    assert result == 11
    assert latency > 0
    if env.backend == "python":
        return
    env.run_until_observation_end(32)
    env.flush_waveform()
    assert env.waveform_path is not None
    write_performance_result(
        request,
        {
            "add_latency": {
                "kind": "latency",
                "value": latency,
                "unit": "ns",
                "direction": "min",
            }
        },
        env.waveform_path,
        {
            "deterministic": True,
            "seed": None,
            "parameters": {"a": 4, "b": 7, "observation_end_ns": 32},
            "start_time": start_time,
            "end_time": end_time,
            "time_unit": "ns",
            "transaction_count": 1,
            "input_trace": [{"cycle": 0, "valid_i": 1, "a_i": 4, "b_i": 7}],
        },
    )


@pytest.mark.performance
def test_Adder_performance_throughput(env, request):
    """Measure sustained completed transactions per simulation nanosecond."""

    vectors = [(1, 2), (3, 4), (5, 6), (7, 8)]
    results = []
    start_time = None
    end_time = None
    for a, b in vectors:
        results.append(api_Adder_add(env, a, b, max_cycles=4))
        accepted_at, response_at = env.last_transaction_timing
        start_time = accepted_at if start_time is None else start_time
        end_time = response_at
    throughput = measure_throughput(len(vectors), start_time, end_time, "ns")
    assert results == [3, 7, 11, 15]
    assert throughput > 0
    if env.backend == "python":
        return
    env.run_until_observation_end(64)
    env.flush_waveform()
    assert env.waveform_path is not None
    write_performance_result(
        request,
        {
            "add_throughput": {
                "kind": "throughput",
                "value": throughput,
                "unit": "transaction/ns",
                "direction": "max",
            }
        },
        env.waveform_path,
        {
            "deterministic": True,
            "seed": None,
            "parameters": {"count": len(vectors), "observation_end_ns": 64},
            "start_time": start_time,
            "end_time": end_time,
            "time_unit": "ns",
            "transaction_count": len(vectors),
            "input_trace": [
                {"transaction": index, "a_i": a, "b_i": b}
                for index, (a, b) in enumerate(vectors)
            ],
        },
    )
```

fixture 已在 reset 和首次 `Step` 前为当前性能节点调用 `SetWaveform`。测试不得再次选择另一
路径，也不得到事务完成后才启动波形。多个 TC 不能共享、覆盖或追加同一文件。Check/Complete
会清理旧性能证据、收集全部标记节点、运行受管 RTL pytest，并验证 TC、sidecar、waveform
一一对应。

## 完整 sidecar 示例

```json
{
  "schema_version": "1.0",
  "test_case": "design/tests/test_Adder_performance.py::test_Adder_performance_latency",
  "created_at": "2026-09-04T00:00:00+00:00",
  "metrics": [
    {
      "id": "add_latency",
      "kind": "latency",
      "value": 1.0,
      "unit": "ns",
      "direction": "min"
    }
  ],
  "waveform": {
    "path": "design/performance/waves/design_tests_test_Adder_performance.py_test_Adder_performance_latency.vcd",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "format": "vcd"
  },
  "stimulus": {
    "deterministic": true,
    "seed": null,
    "parameters": {"a": 4, "b": 7, "observation_end_ns": 32},
    "start_time": 2,
    "end_time": 3,
    "time_unit": "ns",
    "transaction_count": 1,
    "input_trace": [{"cycle": 0, "valid_i": 1, "a_i": 4, "b_i": 7}]
  },
  "measurement": {
    "start_time": 2.0,
    "end_time": 3.0,
    "duration": 1.0,
    "time_unit": "ns",
    "transaction_count": 1
  },
  "stimulus_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "input_trace_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
}
```

sidecar 与 manifest 是机器证据，不得手工创建或修补。若 Check 报 node、hash、unit、duration、
stimulus 或 waveform 不一致，修正测试/adapter 后重新运行整个性能集合。
