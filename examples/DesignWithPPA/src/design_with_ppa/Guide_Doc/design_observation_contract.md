
# 功能观测合同

功能观测合同定义同一套 Python/RTL 测试如何从公开 `env` 识别每个功能 CK。它先于
coverage predicate 编写，用来把“需要观测什么”和“predicate 如何表达”分开。合同不得增加
设计端口，也不得依赖具体 backend、私有 DUT 成员、测试注入标志或中间生成源码。

合同文件固定为 `{OUT}/{DUT}_observation_contract.yaml`，顶层键为
`observation_contract`，`schema_version` 固定为 `"1.0"`。

## 观测类型

- `pins`：CK 可直接从 architecture 声明的公开 pin 或 adapter 的公开归一化状态判断。
  `event` 必须为 `null`。
- `event`：CK 依赖握手接受、等待、响应或 API 拒绝等瞬时行为。事件必须由 adapter/API 在
  真实动作点记录并立即采样；测试不得调用私有记录方法或直接写入事件证据。

事件 `capture` 只能是 `api_validation`、`after_refresh`、`after_step`、
`transaction_accept`、`transaction_observation` 或 `response`。每个字段必须同时提供非空、
不重复的 `source_refs`，逐项列出该值依赖的公共 pin 或统一 cycle 状态。字段 `source` 只能是：

- `public_input`：从公开输入 pin 读取；
- `public_output`：从公开输出 pin 读取；
- `transaction_identity`：接受时保存并在后续事件中保持不变的请求身份；
- `cycle_state`：由 `Step` 次数、接受周期或响应周期确定；
- `derived_public_value`：仅由公开输入、公开输出和确定性规格推导的分类值。

`public_input` 和 `transaction_identity` 的 `source_refs` 只能引用 architecture input pin；
`public_output` 只能引用 output/inout pin；`derived_public_value` 可以引用一个或多个公开 pin；
`cycle_state` 的 `source_refs` 必须恰好为 `[cycle]`，引用 adapter 对外提供的统一 `cycle`
属性。该属性从 0 开始，在 adapter 每次实际执行一个 `Step` 后增加 1；reset 可以按 architecture
约定重新归零，但 Python 与 RTL backend 必须一致。事件调用必须把合同字段写成显式关键字，
例如 `result=result`；只在变量、注释、docstring 或未调用的字典中出现字段名不算实现证据。
接受调用中作为显式关键字保存的 transaction identity 会由统一 helper 自动合并到后续 observation
和 response；后续调用只显式传入新增状态或结果字段，不得重复传入已保存 identity。helper 自动生成的
`transaction_id`、`accepted_at`、`observed_at` 和 `response_at` 也不需要由调用方伪造或重复传入。
`derived_public_value` 的实现必须覆盖其说明和 CK predicate 使用的全部分类值；不能只让字段名在
事件中出现，却使某个规范分类在所有公开输入/输出组合下都不可达。功能测试首次暴露分类值与
predicate 不可达或互相矛盾时，应回修确定性分类、predicate 或 observation contract 中真正错误的
一方，并重新运行相同测试节点，不能通过删除字段、恒真 predicate 或改用普通向量绕过该 CK。

每个非 `FG-PPA` CK 必须在 `checkpoints` 中恰好出现一次。`fields` 必须足以区分该 CK，
不能只记录事件名、任意 transaction ID、恒真标志或与 CK 无关的字段。两个 CK 如果具有完全
相同的触发、输入条件和可观察结果，应回到功能合同合并，而不是制造字段差异。

## 实现顺序

1. 从 `{OUT}/{DUT}_functions_and_checks.md` 枚举全部功能 CK。
2. 优先选择公开 pin 观测；只有瞬时行为才定义事件。
3. 对每个事件确定唯一真实 capture 时点、字段来源和含义。
4. 在共享 adapter/API 中实现事件；一次写完输入后先 `RefreshComb()`，需要推进状态时再
   `Step(1)`，边沿后需要观察组合输出时再次 `RefreshComb()`。
5. 事件字段在 Python reference 与 RTL backend 下必须具有相同含义和类型。
6. 完成观测 instrumentation 后，coverage 阶段才把每个 CK 占位替换为 predicate。

## 完整合同示例

```yaml
observation_contract:
  schema_version: "1.0"
  events:
    - name: transaction_accepted
      capture: transaction_accept
      fields:
        - name: operation
          source: transaction_identity
          source_refs: [operation_i]
          description: Accepted public operation selector.
        - name: a
          source: public_input
          source_refs: [a_i]
          description: Accepted first operand.
        - name: b
          source: public_input
          source_refs: [b_i]
          description: Accepted second operand.
    - name: response_observed
      capture: response
      fields:
        - name: operation
          source: transaction_identity
          source_refs: [operation_i]
          description: Operation retained from the accepted request.
        - name: result
          source: public_output
          source_refs: [result_o]
          description: Public result sampled at the response.
        - name: latency_cycles
          source: cycle_state
          source_refs: [cycle]
          description: Cycles from accepted request to observed response.
  checkpoints:
    - id: FG-ARITH/FC-ADD/CK-NORMAL
      observation: event
      event: response_observed
      fields: [operation, result]
      predicate_intent: Match an add response whose result equals the specified sum.
    - id: FG-PROTOCOL/FC-RESET/CK-RESET-OUTPUT
      observation: pins
      event: null
      fields: [valid_o, result_o]
      predicate_intent: Match the specified public reset-state outputs.
    - id: FG-PROTOCOL/FC-LATENCY/CK-ONE-CYCLE
      observation: event
      event: response_observed
      fields: [operation, latency_cycles]
      predicate_intent: Match a response exactly one cycle after request acceptance.
```

## 完整 instrumentation 示例

```python
def add(self, a, b, max_cycles=4):
    """Execute one backend-neutral add transaction."""

    self.a_i.value = a
    self.b_i.value = b
    self.valid_i.value = 1
    self._dut.RefreshComb()
    accepted_at = self.cycle
    transaction_id = self._record_transaction_accepted(
        accepted_at,
        operation="add",
        a=a,
        b=b,
    )
    self._step()
    self._dut.RefreshComb()
    result = self.result_o.value
    self._record_response_observed(
        transaction_id,
        self.cycle,
        result=result,
        latency_cycles=self.cycle - accepted_at,
    )
    return result
```

示例中的 `_step()` 是 adapter 内部统一动作；它每执行一个底层 Step 就同步增加
`self.cycle`。字段必须在真实接受与响应点产生。不得从测试函数调用 `_record_*`，
也不得为了 coverage 增加 RTL 诊断端口。
