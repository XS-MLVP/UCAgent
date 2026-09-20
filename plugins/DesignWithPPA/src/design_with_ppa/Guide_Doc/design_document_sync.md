
# 最终 RTL 文档同步合同

该阶段只在最终 RTL、Python reference、同一套全部 TC 和 Toffee 报告全部通过后执行。它把最终
accepted RTL 的真实接口、语言、源文件身份和全量测试身份同步到设计文档，避免文档停留在某个
被拒绝候选版本。README 与 Spec 位于 `{DUT}`，全程只读；本阶段只更新 `{OUT}` 中列出的设计文档。

## 需要同步的文档

必须阅读最终 RTL，并更新以下文档中的自然语言、接口表、时序/协议、资源取舍、验证接受条件和
最终版本摘要：

- `{OUT}/{DUT}_architecture.md`
- `{OUT}/{DUT}_basic_info.md`
- `{OUT}/{DUT}_design_needs_and_plan.md`
- `{OUT}/{DUT}_functions_and_checks.md`
- `{OUT}/{DUT}_design_summary.md`

不得修改 README、Spec、Python 测试断言、性能合同、RTL 源码、波形、sidecar、PPA 报告或 Toffee
报告。不得创建或保留 `{OUT}/{DUT}_bug_analysis.md`、`{OUT}/{DUT}_static_bug_analysis.md` 或
其他 Bug 分析文档；这是设计交付流程，所有 TC 都必须通过。

## 同步内容

文档的正文必须反映最后 accepted RTL 的实际内容，至少核对：

- top module、参数及其合法范围；
- 每个公共端口的名称、方向、位宽、signedness、编码和协议含义；
- clock/reset 的边沿、极性、同步/异步语义；
- 组合或时序性质、transaction、latency、握手和 backpressure；
- 非法输入、未定义行为、溢出/舍入/饱和策略；
- 可综合语言子集、禁止语法和必要的 RTL-GUIDE-DEVIATION；
- 最终功能回归、性能测试、Toffee 报告和 PPA 交付结论。

不要把未接受 candidate、旧端口、旧 latency、未运行的测试或推测的 PPA 数值写成最终事实。

## 机器同步附录

每份上述 Markdown 文档必须包含且只包含一个 `## Final RTL synchronization` 节。该节由 Check
根据当前 RTL 文件和最终全量一致性收据原子更新；LLM 不得手工填写或伪造哈希。字段含义如下：

- `rtl_language`、`top_module` 和 `source_files` 必须对应最后 RTL；
- `rtl_source_sha256` 是有序 RTL 源文件路径和 SHA-256 的聚合身份；
- `all_test_cases_passed` 必须为 `true`；
- `test_case_count`、`test_source_sha256` 和 `toffee_report_sha256` 来自最终全量收据；
- `status` 必须为 `pass`。

Check 同时写入 `{OUT}/reports/{DUT}_documentation_sync.json`，其中保存文档哈希、RTL 源文件哈希、
全量测试身份和 Toffee 报告哈希。这个 JSON 是机器证据，不要在文档中复制或手工编辑。

## 完整示例

下面是一个完整的同步附录示例。真实值必须由 Check 根据当前文件替换，不能照抄示例哈希。

````markdown

# Adder 架构设计

最终 accepted RTL 是无状态组合加法器，`sum` 在输入稳定后立即得到。

## 机器合同

```yaml
architecture:
  schema_version: "1.0"
  top_module: Adder
  parameters: []
  ports:
    - name: a
      direction: input
      width: 8
      signed: false
      role: operand
    - name: b
      direction: input
      width: 8
      signed: false
      role: operand
    - name: sum
      direction: output
      width: 8
      signed: false
      role: wrapped-result
  design_intent: combinational
  clock_reset:
    clocks: []
    resets: []
    rationale: No stored state exists in the accepted RTL.
  timing:
    transaction_accept: Inputs are sampled when the caller presents a complete transaction.
    response: sum settles in the same transaction interval.
    handshake: none
    latency_cycles: 0
    backpressure: none
  illegal_inputs:
    policy: X/Z and values outside the declared binary interface are outside the contract.
  multi_clock_cdc:
    clock_domains: 0
    policy: No CDC exists.
  synthesis_constraints:
    synthesizable_only: true
    no_latch: true
    no_unknown_outputs: true
    no_initial_delay: true
    forbidden_constructs: [delay, force, release, simulation-system-task]
  acceptance_criteria:
    - sum equals (a + b) modulo 256 for every legal transaction.
```

## Final RTL synchronization

```yaml
rtl_synchronization:
  schema_version: "1.0"
  status: pass
  rtl_language: verilog
  top_module: Adder
  source_files:
    - design/rtl/Adder.v
  rtl_source_sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
  all_test_cases_passed: true
  test_case_count: 12
  test_source_sha256: abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789
  toffee_report_sha256: fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210
```

## 交付结论

最终 RTL、Python reference 和同一套 12 个 TC 全部通过；以上接口、时序和实现说明与
`design/rtl/Adder.v` 一致。
````

## Check 前自检

1. 只修改五份列出的设计文档，不修改输入 README/Spec 和测试/报告机器文件。
2. 逐项核对最终 RTL 的公共接口、时序和核心数据通路；发现旧描述就修正文档。
3. 删除任何 Bug 分析文档，确认最终全量 Python/RTL 测试和 Toffee 报告均为 Pass。
4. 调用 Check，让它生成真实同步附录和 documentation sync manifest；不要手工伪造字段。
5. Check 通过后再次调用 CurrentTips，确认没有遗留文档或全量一致性问题，再调用 Complete。
