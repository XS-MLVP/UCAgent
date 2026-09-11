
# 设计输入与架构合同

本工作流只读取 `{DUT}/README.md` 和 `{DUT}/spec/**/*.md`，所有派生产物写入 `{OUT}`。先稳定 FG/FC/CK，再为每份 Spec 建立逐行映射。映射键只能是 `FG-*/FC-*/CK-*` 或带具体理由的 `IGNORE/FC-*/CK-*`，单个范围不得超过 100 个物理行。

输入 Spec 中已有的标题或 FG/FC/CK 名称只是需求来源，不代表其结构已经完整。输出的 `{OUT}/{DUT}_functions_and_checks.md` 必须形成严格的三层 `FG -> FC -> CK` 树：每个 FG 至少包含一个 FC，每个 FC 至少包含一个可验证 CK，每个标签 ID 在全文唯一。应保留到原始 Spec 路径和行号的追溯关系；当输入只定义了 FG/FC、同一 CK 被多个功能引用或名称不满足规范时，必须拆分并补充唯一的规范标签，不能留下无 CK 的叶节点，也不能在多个父节点下重复定义同一 CK。

标签层级写入 `{OUT}/{DUT}_functions_and_checks.md`，逐行映射写入当前阶段给出的 `{OUT}/line_map/*_line_func_map.txt`。输入发生变化时再次调用 `Check`，并按诊断重新检查依赖该输入的产物。

`{OUT}/{DUT}_architecture.md` 必须包含且只包含一个以 `architecture` 为根的 fenced YAML 机器合同。组合设计也必须明确写出 clock/reset 不适用的原因；不得省略字段。每个参数记录 `type`、`default` 和 `valid_range`；每个端口记录方向、位宽、signedness 和 role。时序或混合设计的 clock 必须记录 `posedge|negedge`，reset 必须记录 active level、同步/异步语义及其所属 clock。同步 reset 必须使用 `sample_edge: posedge|negedge`；异步 reset 必须使用 `assertion_edge: posedge|negedge`，并写明非空的 `deassertion` 策略。不要使用 `rising`、`falling` 等其他 edge 拼写。

## 完整架构示例

````markdown

# Adder 架构设计

该模块实现带有效握手的 8 位加法。

## 机器合同

```yaml
architecture:
  schema_version: "1.0"
  top_module: Adder
  parameters:
    - name: WIDTH
      type: integer
      default: 8
      valid_range: "1..64"
  ports:
    - name: a
      direction: input
      width: WIDTH
      signed: false
      role: operand
    - name: b
      direction: input
      width: WIDTH
      signed: false
      role: operand
    - name: valid_i
      direction: input
      width: 1
      signed: false
      role: request-valid
    - name: sum
      direction: output
      width: WIDTH
      signed: false
      role: result
    - name: valid_o
      direction: output
      width: 1
      signed: false
      role: response-valid
  design_intent: combinational
  clock_reset:
    clocks: []
    resets: []
    rationale: No stored state; outputs are a pure function of current inputs.
  timing:
    transaction_accept: valid_i == 1
    response: valid_o and sum settle in the same transaction interval
    handshake: valid-only; no ready signal
    latency_cycles: 0
    backpressure: none
  illegal_inputs:
    policy: All binary input values are legal; X/Z are outside the interface contract.
  multi_clock_cdc:
    clock_domains: 0
    policy: No CDC exists in this combinational module.
  synthesis_constraints:
    synthesizable_only: true
    no_latch: true
    no_unknown_outputs: true
    no_initial_delay: true
    forbidden_constructs: [delay, force, release, simulation-system-task]
  acceptance_criteria:
    - "valid_o equals valid_i"
    - "when valid_i is 1, sum equals (a + b) modulo 2**WIDTH"
    - "all FG/FC/CK tests pass for both the Python reference and RTL design"
```
````

时序设计的同步 reset 使用以下字段；`sample_edge` 表示 reset 在哪个 clock edge 被采样：

```yaml
clock_reset:
  clocks:
    - name: clk
      edge: posedge
  resets:
    - name: rst_n
      active_level: low
      synchrony: synchronous
      clock: clk
      sample_edge: posedge
  rationale: State and the active-low synchronous reset are sampled on the clk posedge.
```

异步 reset 使用以下字段：

```yaml
clock_reset:
  clocks:
    - name: clk
      edge: posedge
  resets:
    - name: rst_n
      active_level: low
      synchrony: asynchronous
      clock: clk
      assertion_edge: negedge
      deassertion: synchronous-to-clk
  rationale: State updates on clk; reset assertion is asynchronous and release is synchronized.
```

无 reset 时保留空 `resets`，并在 `rationale` 中说明设计依据。

## 完整行映射示例

行映射由当前 Spec 原文派生，不是可脱离原文自由编写的设计说明；每个范围都必须能回查到
对应文件的真实物理行。

```text
FG-ARITH/FC-ADD/CK-RESULT: 1-24
IGNORE/FC-DOC/CK-CONTEXT: 25-28 # These prose lines identify authorship and do not define behavior.
```
