
# 波形观察与 Bug 根因复核

## 获取实际观察

`RunToffee` 默认采集登记的原生 DUT 波形，不推进额外时钟、不改变引脚写入方式。
fixture 必须在仿真推进前登记 DUT，并正常或异常收尾；已有 fixture 可继续复用。
没有可用观察时工具报告具体缺口，不把缺波形变成 PASS。需要补采时才重跑对应选择；
仅修改分析说明、已有有效原件时不要重新仿真。`waveforms=false` 明确不采集波形，
因此不能用这次运行完成需要波形证据的根因确认。

先调用 `WaveInfo(test_case_name="<exact-nodeid>")`，查看实际信号目录、记录范围及
可选波形。一个节点存在多个 DUT 观察时，用返回的 `waveform` 路径明确选择，不猜测。
如果最新指针已切到另一批定向，可传 `run="results/<run-id>"` 读取明确的签名归档：
当前输入与归档仍须一致，工具不改写 `latest.json`。新生成的观察收据只绑定所选运行，
不能代替另一批运行的根因证据。输入已变化的原件依然保留，但不能用此入口作为当前证据。
大型 FST 的 `signal_query="**"` 会先枚举整个信号树，再按 `signal_limit` 分页；缩小页长
不能减少枚举开销。已知层次时用具体的 `signal_query` 或直接用已确认的信号路径和窄时间窗，
不要反复查询全目录。解码器打开 FST 时仍需构建层次，耗时不表示正在仿真。
然后传 `signal_groups` 和明确的 `begin_time`、`end_time` 取得完整事件窗口：

```json
{
  "test_case_name": "testbenches/queue/tests/test_response.py::test_order",
  "signal_groups": {
    "clocks": ["TOP.clk"],
    "inputs": ["TOP.push", "TOP.data_in"],
    "outputs": ["TOP.valid", "TOP.data_out"],
    "internal": ["TOP.read_ptr"]
  },
  "begin_time": 100,
  "end_time": 131
}
```

信号名和窗口必须来自本次实际目录。无时钟 DUT 的 `clocks` 用空数组。窗口时间是
波形时间戳，不是测试日志里的周期号；先以真实时钟、握手和事务身份对齐，再分析首个
错误。输出保留 X/Z，不能把未知值当零。结果过多时缩小窗口或相关信号，不能将截断
数据作为完整证据。目录查询不产生根因收据。

## 分析与工件

原始 FAIL 保留。先排除非法刺激、采样/完成、比较和独立 oracle 错误，再判断 DUT
是否违反已确认要求。波形收据只证明实际读到的信号，不自动证明根因解释正确。
对每个声称已确认的失败节点记录一次 `waveform_evidence`，引用工具返回的 `receipt`、
实际时间线中的 `at_time` 和有独立依据的 `analysis`。不可手写或修改机器收据。

以下为完整的问题记录；路径、信号事实和时间必须使用本次工具结果：

````markdown

# Queue 背压恢复后的顺序违约

## 现象与独立依据

合法的两次入队已被接受。恢复出队时，第二个有效响应仍携带第一个条目的数据，
违反 inputs/queue-interface.md 中已确认的 Q-ORDER 要求。

```yaml
kind: issue
run: results/<actual-run-id>
nodeids:
  - testbenches/queue/tests/test_response.py::test_order
classification: rtl
requirement: Q-ORDER
evidence: 本轮 call 断言失败，实际接受历史与返回数据不符；保留原断言和运行日志
next_action: 修复已定位的指针更新后重跑受影响节点，再按任务范围复验
waveform_evidence:
  - nodeid: testbenches/queue/tests/test_response.py::test_order
    receipt: results/waveform-evidence/<returned-receipt>.json
    at_time: 120
    analysis: 对齐时钟与两次合法接受后，首个错误响应时 read_ptr 未前进，data_out 重复旧值；独立输入队列与 monitor 同沿快照一致，排除了预期和漏采错误
```

## 复核边界

该结论只覆盖引用的要求、节点和观察窗口，不替代其他功能与覆盖验收。
````

静态候选的 `status: rtl` 同样需要 `requirement`、当前 `run`、实际失败 `nodeids` 和
相同的 `waveform_evidence`。`unconfirmed` 是证据未齐的真实状态，不是完成根因任务的
替代方案。检查只读验证收据和分析引用，不自动重跑、重写分析或降低验收要求。
