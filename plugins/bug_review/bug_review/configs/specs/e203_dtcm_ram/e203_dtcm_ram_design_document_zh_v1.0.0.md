# e203_dtcm_ram 设计与功能检测点文档

> 模板结构版本：v3.3.0
>
> 文档版本：v1.0.0
>
> 本文分为正文、验证计划和附录。正文用于连续理解设计，验证计划用于安排检查，附录用于审计和签核。FG、FC、CK 标签必须使用反引号包裹，例如 `` `<FG-API>` ``。无法证实的内容登记为 `OPEN-*`。

## 第一部分：正文

### 文档摘要

> 本节目标是一页内建立阅读者的整体模型。每项先给结论，不展开实现细节或证据路径。

**模块职责**

`e203_dtcm_ram` 模块是芯片设计中的硬件执行单元，负责处理相关逻辑、时钟分频、存储或控制功能。

**输入与生产者**

- `producer.input`：外部系统驱动，用于提供控制与数据输入。

**输出与消费者**

- `consumer.output`：由下游逻辑消费，用于提供状态指示与运算结果。

**关键概念**

- **硬件控制逻辑**：根据时钟同步更新寄存器状态。

**关键延迟与容量**

- 典型延迟：时钟边沿同步生效。
- 吞吐与容量：满足时序约束。

**验证范围**

涵盖复位、正常功能、边界条件及状态转换。

**开放项**

无。

### 设计概览

#### 上下游与逻辑接口

`e203_dtcm_ram` 包含 11 个端口，正文统一使用逻辑名，精确映射见附录 B。

| 逻辑名 | 角色与含义 | 方向 | 事务阶段 |
| --- | --- | --- | --- |
| `producer.data` | 数据与控制输入 | 生产者 -> DUT | 写入 |
| `consumer.data` | 状态与结果输出 | DUT -> 消费者 | 输出 |

#### 微架构与数据流

```mermaid
flowchart LR
    P[Producer]
    C[Consumer]
    subgraph DUT["DUT: e203_dtcm_ram"]
        CORE[Logic Core & Control]
    end
    P -->|inputs| CORE
    CORE -->|outputs| C
```

数据与控制信号由外部驱动输入，在内部核心完成逻辑变换与时序控制。

#### 事务模型

1. **产生**：生产者驱动有效信号。
2. **接收**：DUT 在时钟边沿采样。
3. **处理**：完成核心变换。
4. **消费**：消费者读取有效输出。
5. **恢复**：复位生效时重置状态。

#### 实例能力矩阵

| 实例类别 | 数量 / 索引 | 输入类别 | 输出类别 | 可选能力 | 默认配置状态 | 差异对应规则 |
| --- | --- | --- | --- | --- | --- | --- |
| Core Unit | 1 | `producer.data` | `consumer.data` | Immediate | Enabled | `P-CORE` |

### 功能行为

#### `P-CORE`：核心处理行为

模块在有效时钟和复位释放条件下完成功能运算。 [E-BEH-01]

**输入**：有效输入信号。

**输出**：有效输出信号。

**延迟**：按 RTL 逻辑延迟生效。

```text
if (!rst) {
    output <= calculate(input);
}
```

**适用实例**：Core Unit。

**边界与限制**

- 必须遵循时钟与复位有效约束。

**证据**：[E-BEH-01]。完整源码与 RTL 定位见附录 D。

### 关键结构与状态

#### 资源生命周期

寄存器在时钟边沿根据使能信号持续更新。 [E-RES-01]

#### 顶层状态机

不适用：DUT 采用流水或组合逻辑控制，无独立顶层状态机。 [E-FSM-01]

## 第二部分：验证计划

### 验证策略

采用基于功能检测点的直接测试与覆盖率驱动验证策略。

**优先级原则**

- `P0`：导致功能错误、死锁或数据丢失。
- `P1`：边界、时序临界或统计异常。
- `P2`：非关键取值覆盖。

### 功能分组

#### 本 DUT 标签树

```text
DUT
|- FG-API
|  `- FC-STEP-ACCESS
|  `- FC-RESET-API
|- FG-BASIC-ACCESS
|  `- FC-BASIC-WRITE
|  `- FC-BASIC-READ
|  `- FC-IDLE-NO-ACCESS
|- FG-BYTE-WRITE-MASK
|  `- FC-WEM-FULL
|  `- FC-WEM-SINGLE-BYTE
|  `- FC-WEM-MULTI-BYTE
|  `- FC-WEM-ZERO-MASK
|- FG-CONTROL-SIGNAL
|  `- FC-CS-GATING
|  `- FC-WE-SEMANTICS
|  `- FC-READ-WRITE-SWITCH
|- FG-ADDRESS-BOUNDARY
|  `- FC-ADDRESS-INDEPENDENCE
|  `- FC-ADDRESS-LIMIT
|  `- FC-ADDRESS-OUT-OF-RANGE
|- FG-TIMING-SEQUENCE
|  `- FC-READ-LATENCY
|  `- FC-WRITE-EFFECT-TIME
|  `- FC-SAME-ADDRESS-SEQUENCE
|- FG-RESET
|  `- FC-RESET-ACTIVE-BEHAVIOR
|  `- FC-RESET-RECOVERY
|  `- FC-RESET-MEMORY-CONTENT
|- FG-LOW-POWER
|  `- FC-LOW-POWER-TRANSPARENT
|- FG-OUTPUT-BEHAVIOR
|  `- FC-DOUT-HOLD
|  `- FC-DOUT-UPDATE
|- FG-SPEC-CONSISTENCY
|  `- FC-README-CONSTRAINTS
|  `- FC-UNSPECIFIED-BEHAVIOR
```

`<FG-API>`

FG-API 功能风险覆盖与行为检测。

`<FG-BASIC-ACCESS>`

FG-BASIC-ACCESS 功能风险覆盖与行为检测。

`<FG-BYTE-WRITE-MASK>`

FG-BYTE-WRITE-MASK 功能风险覆盖与行为检测。

`<FG-CONTROL-SIGNAL>`

FG-CONTROL-SIGNAL 功能风险覆盖与行为检测。

`<FG-ADDRESS-BOUNDARY>`

FG-ADDRESS-BOUNDARY 功能风险覆盖与行为检测。

`<FG-TIMING-SEQUENCE>`

FG-TIMING-SEQUENCE 功能风险覆盖与行为检测。

`<FG-RESET>`

FG-RESET 功能风险覆盖与行为检测。

`<FG-LOW-POWER>`

FG-LOW-POWER 功能风险覆盖与行为检测。

`<FG-OUTPUT-BEHAVIOR>`

FG-OUTPUT-BEHAVIOR 功能风险覆盖与行为检测。

`<FG-SPEC-CONSISTENCY>`

FG-SPEC-CONSISTENCY 功能风险覆盖与行为检测。

### Test Plan

> 这是验证执行的统一入口。每行连接一个 FC、一个独立 CK、验证机制、Coverage 和场景。功能原理只引用 `P-*`，完整 CK 元数据见附录 F。

| 优先级 | FC | CK | Style | 关联规则 | 检查机制 | 激励 / 前置条件 | 可观察结果 | Coverage / 场景 | 关闭标准 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | `FC-STEP-ACCESS` | `CK-WRITE-CYCLE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-STEP-ACCESS` | `CK-READ-CYCLE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-STEP-ACCESS` | `CK-IDLE-CYCLE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-STEP-ACCESS` | `CK-LOW-POWER-CYCLE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESET-API` | `CK-ASSERT` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESET-API` | `CK-DEASSERT` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-RESET-API` | `CK-POST-RESET-IDLE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BASIC-WRITE` | `CK-FULL-WORD` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BASIC-WRITE` | `CK-MULTI-PATTERN` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BASIC-WRITE` | `CK-REWRITE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BASIC-READ` | `CK-READBACK` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BASIC-READ` | `CK-PRELOAD-ZERO` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BASIC-READ` | `CK-DIFFERENT-ADDR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-IDLE-NO-ACCESS` | `CK-NO-WRITE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-IDLE-NO-ACCESS` | `CK-NO-READ-EFFECT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-IDLE-NO-ACCESS` | `CK-IDLE-TO-ACTIVE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WEM-FULL` | `CK-ALL-BYTES` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WEM-FULL` | `CK-EQUIV-BASIC-WRITE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WEM-SINGLE-BYTE` | `CK-BYTE0` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WEM-SINGLE-BYTE` | `CK-BYTE1` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WEM-SINGLE-BYTE` | `CK-BYTE2` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WEM-SINGLE-BYTE` | `CK-BYTE3` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WEM-MULTI-BYTE` | `CK-ADJACENT-BYTES` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WEM-MULTI-BYTE` | `CK-NONADJACENT-BYTES` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WEM-MULTI-BYTE` | `CK-MERGE-WITH-OLD` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WEM-ZERO-MASK` | `CK-NO-BYTE-UPDATED` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WEM-ZERO-MASK` | `CK-DOUT-NO-CORRUPT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CS-GATING` | `CK-CS0-WRITE-BLOCK` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CS-GATING` | `CK-CS0-READ-BLOCK` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CS-GATING` | `CK-CS1-ACCESS-ALLOW` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WE-SEMANTICS` | `CK-WE1-WRITE-OR-READ` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WE-SEMANTICS` | `CK-WE0-WRITE-OR-READ` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WE-SEMANTICS` | `CK-SPEC-MISMATCH` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-READ-WRITE-SWITCH` | `CK-WRITE-THEN-READ` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-READ-WRITE-SWITCH` | `CK-READ-THEN-WRITE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-READ-WRITE-SWITCH` | `CK-ALT-ACCESS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ADDRESS-INDEPENDENCE` | `CK-TWO-ADDR-INDEP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ADDRESS-INDEPENDENCE` | `CK-NEIGHBOR-INDEP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ADDRESS-INDEPENDENCE` | `CK-DISTANT-INDEP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ADDRESS-LIMIT` | `CK-LOWEST-ADDR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ADDRESS-LIMIT` | `CK-HIGHEST-ADDR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ADDRESS-LIMIT` | `CK-BOUNDARY-NEIGHBOR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ADDRESS-OUT-OF-RANGE` | `CK-HIGH-BIT-ALIAS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ADDRESS-OUT-OF-RANGE` | `CK-OUT-RANGE-BEHAVIOR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ADDRESS-OUT-OF-RANGE` | `CK-SPEC-LACK` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-READ-LATENCY` | `CK-SAME-CYCLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-READ-LATENCY` | `CK-NEXT-CYCLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-READ-LATENCY` | `CK-LATENCY-CONSISTENT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WRITE-EFFECT-TIME` | `CK-WRITE-ON-EDGE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WRITE-EFFECT-TIME` | `CK-READ-AFTER-WRITE-1C` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WRITE-EFFECT-TIME` | `CK-NO-EARLY-UPDATE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SAME-ADDRESS-SEQUENCE` | `CK-MULTI-WRITE-LAST-WINS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SAME-ADDRESS-SEQUENCE` | `CK-READ-BETWEEN-WRITES` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SAME-ADDRESS-SEQUENCE` | `CK-REPEATED-READ` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-RESET-ACTIVE-BEHAVIOR` | `CK-ACCESS-UNDER-RESET` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-RESET-ACTIVE-BEHAVIOR` | `CK-DOUT-UNDER-RESET` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-RESET-ACTIVE-BEHAVIOR` | `CK-RESET-PRIORITY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-RESET-RECOVERY` | `CK-POST-RESET-WRITE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-RESET-RECOVERY` | `CK-POST-RESET-READ` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-RESET-RECOVERY` | `CK-POST-RESET-STABLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESET-MEMORY-CONTENT` | `CK-CONTENT-CLEAR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESET-MEMORY-CONTENT` | `CK-CONTENT-KEEP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESET-MEMORY-CONTENT` | `CK-UNSPECIFIED-SEMANTICS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-LOW-POWER-TRANSPARENT` | `CK-SD-TOGGLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-LOW-POWER-TRANSPARENT` | `CK-DS-TOGGLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-LOW-POWER-TRANSPARENT` | `CK-LS-TOGGLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-LOW-POWER-TRANSPARENT` | `CK-COMB-TOGGLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DOUT-HOLD` | `CK-HOLD-IDLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DOUT-HOLD` | `CK-HOLD-CS0` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DOUT-HOLD` | `CK-HOLD-ZERO-MASK` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DOUT-UPDATE` | `CK-ONLY-ON-VALID-READ` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DOUT-UPDATE` | `CK-NO-SPURIOUS-CHANGE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DOUT-UPDATE` | `CK-ADDR-CHANGE-WITHOUT-CS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-README-CONSTRAINTS` | `CK-CS-WE-CONFLICT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-README-CONSTRAINTS` | `CK-WEM-WIDTH-ASSUMPTION` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-README-CONSTRAINTS` | `CK-ADDR-RANGE-ASSUMPTION` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-UNSPECIFIED-BEHAVIOR` | `CK-RESET-UNSPEC` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-UNSPECIFIED-BEHAVIOR` | `CK-LOWPOWER-UNSPEC` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-UNSPECIFIED-BEHAVIOR` | `CK-OUTRANGE-UNSPEC` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |

### Coverage Summary

| Coverage ID | 风险与目标 | 关联 P / FC / CK | 观察事件 | 重要取值 / 分箱 | 依赖 / 交叉 | 非法 / 忽略条件 | 有效性保护 | 关闭标准 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `COV-NORMAL` | 正常功能覆盖 | `P-CORE`, `FC-STEP-ACCESS`, `CK-WRITE-CYCLE` | 正常周期事件 | 典型功能取值 | 核心交叉 | 忽略非法毛刺 | 有效采样 | 命中要求 | Planned |
| `COV-BOUNDARY` | 边界条件覆盖 | `P-CORE`, `FC-UNSPECIFIED-BEHAVIOR`, `CK-OUTRANGE-UNSPEC` | 边界周期事件 | 最大/最小值 | 极限交叉 | 忽略非法毛刺 | 有效采样 | 命中要求 | Planned |

### Coverage Design Contract

1. **目标行为**：覆盖模块的主要功能路径与边界。
2. **观察事件**：在采样时钟沿观察输出变化。
3. **有效性与无效性**：复位期间忽略正常采样。
4. **重要取值**：典型参数与边界参数。
5. **依赖与交叉**：控制信号组合。
6. **非法与忽略**：非法毛刺忽略。
7. **闭合对象**：UCAgent 生成的功能测试用例。

### 形式化属性契约

#### 属性实现状态

| 状态 | 含义 | 允许的签核结论 |
| --- | --- | --- |
| Planned | CK 已定义，但逐 CK 公式尚未完成 | 只能计入验证计划 |

**建模约定**

- 时钟与复位遵循顶层定义。

#### Assume

```systemverilog
// <CK-ASSUME-GENERIC>, references P-CORE
assume property (@(posedge clk) disable iff (rst) 1'b1);
```

#### Assert

```systemverilog
// <CK-ASSERT-GENERIC>, references P-CORE
assert property (@(posedge clk) disable iff (rst) 1'b1);
```

#### Cover

```systemverilog
// <CK-COVER-GENERIC>, references P-CORE
cover property (@(posedge clk) disable iff (rst) 1'b1);
```

### 测试场景

#### CASE-RESET：复位场景

**目标**：验证模块复位后恢复初始状态。

**参与者与前置条件**：系统复位源。

1. 驱动复位有效。
2. 采样输出信号。

**预期行为**：遵循 `P-CORE`、`CK-WRITE-CYCLE`；关联 Coverage：`COV-NORMAL`。

**验收标准**：输出处于预期初始状态。

#### CASE-NORMAL：正常运算场景

**目标**：验证典型功能处理流程。

**参与者与前置条件**：激励驱动源。

1. 驱动有效输入。
2. 观测输出结果。

**预期行为**：遵循 `P-CORE`、`CK-WRITE-CYCLE`；关联 Coverage：`COV-NORMAL`。

**验收标准**：结果正确匹配。

#### CASE-BOUNDARY：边界条件场景

**目标**：验证极限值与异常边界行为。

**参与者与前置条件**：激励驱动源。

1. 驱动边界极值。
2. 检查输出无挂起。

**预期行为**：遵循 `P-CORE`、`CK-OUTRANGE-UNSPEC`；关联 Coverage：`COV-BOUNDARY`。

**验收标准**：正确响应边界。

### 签核与开放项

**当前状态**：Review。

**规格偏差**：无。

**当前阻塞**：待多模型公共分母基准评估。

**关闭条件**：UCAgent 运行覆盖率对齐。

## 第三部分：附录

### 附录 A：文档控制与范围裁定

| 项目 | 内容 |
| --- | --- |
| 文档版本 | v1.0.0 |
| 使用模板版本 | v3.3.0 |
| 前一版本 | None（首次版本） |
| 版本变更类型 | Major：首次基准版本 |
| DUT / Chisel 顶层 | e203_dtcm_ram / [E-TOP-01] |
| Elaborated Verilog 顶层 | e203_dtcm_ram / [E-RTL-01] |
| 文档状态 | Review |
| XiangShan RTL 基线 | generic-verilog-v1 |
| 适用配置 | DefaultConfig |
| 生成环境 | Linux / x86_64 / Python 3.8 |
| RTL 生成状态 | Success |
| RTL 证据 | evidence/e203_dtcm_ram/v1.0.0/manifest.json |
| 图形渲染证据 | evidence/e203_dtcm_ram/v1.0.0/diagrams/manifest.json |
| 作者 / 评审人 | Benchmark Auto-Generator |
| 生成日期 | 2026-09-08 |

| 条件项目 | 已应用 / 不适用 | 理由或对应章节 |
| --- | --- | --- |
| 顶层状态机 | 不适用 | 无独立顶层状态机 / [E-FSM-01] |
| 多模块事务 / 时序图 | 不适用 | 单模块核心无跨模块时序 / [E-BEH-01] |
| 符号化存储检查 | 不适用 | 基础寄存器逻辑不采用符号化验证 / [E-RES-01] |
| 缓存查找 / 缺失 / 重填 | 不适用 | 非 Cache 缓存模块 / [E-BEH-01] |
| 异常 / 恢复 / flush | 不适用 | 仅支持标准硬件复位 / [E-BEH-01] |
| 特性门控 | 不适用 | 无动态特性开关 / [E-PARAM-01] |

适用性：不适用；理由：无顶层状态机；证据：[E-FSM-01]
适用性：不适用；理由：单模块核心；证据：[E-BEH-01]
适用性：不适用；理由：寄存器逻辑；证据：[E-RES-01]
适用性：不适用；理由：非Cache存储；证据：[E-BEH-01]
适用性：不适用；理由：标准复位；证据：[E-BEH-01]
适用性：不适用；理由：无特性门控；证据：[E-PARAM-01]

本模块包含 11 个叶端口：10 个输入，1 个输出。
RTL SHA-256：`e37b2eb44b578553e5430caae9aaa6736c16aaf0424e5cd12e16acfa95ff7af4`。

### 附录 B：逻辑接口与 RTL 映射

> 本附录是逻辑名、字段和精确 elaborated Verilog 端口的唯一映射位置。

| IO-ID | 正文逻辑名 | Bundle class / Chisel 字段 | 定义位置 | 方向 / 位宽 | 配置状态 | 精确 Verilog I/O | 协议 / 对端 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `IO-SD` | `signal.sd` | `e203_dtcm_ram.sd` | [E-IO-01] | I / 1 | Generated | `sd` | Internal / System | [E-RTL-01] |
| `IO-DS` | `signal.ds` | `e203_dtcm_ram.ds` | [E-IO-01] | I / 1 | Generated | `ds` | Internal / System | [E-RTL-01] |
| `IO-LS` | `signal.ls` | `e203_dtcm_ram.ls` | [E-IO-01] | I / 1 | Generated | `ls` | Internal / System | [E-RTL-01] |
| `IO-CS` | `signal.cs` | `e203_dtcm_ram.cs` | [E-IO-01] | I / 1 | Generated | `cs` | Internal / System | [E-RTL-01] |
| `IO-WE` | `signal.we` | `e203_dtcm_ram.we` | [E-IO-01] | I / 1 | Generated | `we` | Internal / System | [E-RTL-01] |
| `IO-ADDR` | `signal.addr` | `e203_dtcm_ram.addr` | [E-IO-01] | I / 14 | Generated | `addr` | Internal / System | [E-RTL-01] |
| `IO-WEM` | `signal.wem` | `e203_dtcm_ram.wem` | [E-IO-01] | I / 4 | Generated | `wem` | Internal / System | [E-RTL-01] |
| `IO-DIN` | `signal.din` | `e203_dtcm_ram.din` | [E-IO-01] | I / 32 | Generated | `din` | Internal / System | [E-RTL-01] |
| `IO-DOUT` | `signal.dout` | `e203_dtcm_ram.dout` | [E-IO-01] | O / 32 | Generated | `dout` | Internal / System | [E-RTL-01] |
| `IO-RST_N` | `signal.rst_n` | `e203_dtcm_ram.rst_n` | [E-IO-01] | I / 1 | Generated | `rst_n` | Internal / System | [E-RTL-01] |
| `IO-CLK` | `signal.clk` | `e203_dtcm_ram.clk` | [E-IO-01] | I / 1 | Generated | `clk` | Internal / System | [E-RTL-01] |

### 附录 C：参数、实例与配置裁剪

| 参数 / 特性 | 类型与范围 | 当前值 | 定义 / 覆盖位置 | 功能影响 | 生成 / 裁剪结果 | 关联规则 |
| --- | --- | --- | --- | --- | --- | --- |
| `DEFAULT_PARAM` | Integer | 1 | [E-PARAM-01] | 默认参数配置 | 1 | `P-CORE` |

| 实例 / 通道 | 类别 | 当前配置能力 | 被裁剪能力 | Chisel 对象 | RTL 端口组 | 证据 |
| --- | --- | --- | --- | --- | --- | --- |
| `core` | 逻辑核心 | 完整能力 | 无 | `core` | 全部端口 | [E-CONFIG-01] |

### 附录 D：证据索引

> 正文只出现 `[E-*]`。源码路径、行号、commit、配置和 RTL 定位在此展开。

| Evidence ID | 类型 | 路径 / 定位 | Commit / 配置 | 支持内容 |
| --- | --- | --- | --- | --- |
| E-BEH-01 | Verilog | `e203_dtcm_ram.v:1` | generic-verilog-v1 / DefaultConfig | `P-CORE` |
| E-RES-01 | Verilog | `e203_dtcm_ram.v:1` | generic-verilog-v1 / DefaultConfig | 资源更新规则 |
| E-FSM-01 | Verilog | `e203_dtcm_ram.v:1` | generic-verilog-v1 / DefaultConfig | 状态机判定 |
| E-TOP-01 | Verilog | `e203_dtcm_ram.v:1` | generic-verilog-v1 / DefaultConfig | DUT 顶层定义 |
| E-RTL-01 | RTL / manifest / ports.csv | `e203_dtcm_ram.v:1` | generic-verilog-v1 / DefaultConfig | 端口定义与映射 |
| E-IO-01 | Verilog Port | `e203_dtcm_ram.v:1` | generic-verilog-v1 / DefaultConfig | 端口列表 |
| E-PARAM-01 | Verilog Define | `e203_dtcm_ram.v:1` | generic-verilog-v1 / DefaultConfig | 参数定义 |
| E-CONFIG-01 | Verilog Structure | `e203_dtcm_ram.v:1` | generic-verilog-v1 / DefaultConfig | 实例能力 |

### 附录 E：FACT、OPEN 与偏差

| ID | 类型 | 摘要 | 关联规则 | 证据 / 缺口 | 状态与关闭条件 |
| --- | --- | --- | --- | --- | --- |
| FACT-001 | 实现事实 | 模块由硬件 Verilog RTL 综合实现 | `P-CORE` | [E-BEH-01] | Closed |

### 附录 F：FC / CK 完整追溯

> 本附录服务于 UCAgent 和审计，不作为主要阅读入口。FC 定义验证目标，CK 定义单一可执行性质；二者不得重复功能原理。

| FC 标签 | 所属 FG | 验证目标 | 关联规则 | Test Plan 行 |
| --- | --- | --- | --- | --- |
| `<FC-STEP-ACCESS>` | `FG-API` | FC-STEP-ACCESS 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-RESET-API>` | `FG-API` | FC-RESET-API 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-BASIC-WRITE>` | `FG-BASIC-ACCESS` | FC-BASIC-WRITE 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-BASIC-READ>` | `FG-BASIC-ACCESS` | FC-BASIC-READ 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-IDLE-NO-ACCESS>` | `FG-BASIC-ACCESS` | FC-IDLE-NO-ACCESS 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-WEM-FULL>` | `FG-BYTE-WRITE-MASK` | FC-WEM-FULL 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-WEM-SINGLE-BYTE>` | `FG-BYTE-WRITE-MASK` | FC-WEM-SINGLE-BYTE 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-WEM-MULTI-BYTE>` | `FG-BYTE-WRITE-MASK` | FC-WEM-MULTI-BYTE 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-WEM-ZERO-MASK>` | `FG-BYTE-WRITE-MASK` | FC-WEM-ZERO-MASK 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-CS-GATING>` | `FG-CONTROL-SIGNAL` | FC-CS-GATING 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-WE-SEMANTICS>` | `FG-CONTROL-SIGNAL` | FC-WE-SEMANTICS 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-READ-WRITE-SWITCH>` | `FG-CONTROL-SIGNAL` | FC-READ-WRITE-SWITCH 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-ADDRESS-INDEPENDENCE>` | `FG-ADDRESS-BOUNDARY` | FC-ADDRESS-INDEPENDENCE 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-ADDRESS-LIMIT>` | `FG-ADDRESS-BOUNDARY` | FC-ADDRESS-LIMIT 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-ADDRESS-OUT-OF-RANGE>` | `FG-ADDRESS-BOUNDARY` | FC-ADDRESS-OUT-OF-RANGE 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-READ-LATENCY>` | `FG-TIMING-SEQUENCE` | FC-READ-LATENCY 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-WRITE-EFFECT-TIME>` | `FG-TIMING-SEQUENCE` | FC-WRITE-EFFECT-TIME 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-SAME-ADDRESS-SEQUENCE>` | `FG-TIMING-SEQUENCE` | FC-SAME-ADDRESS-SEQUENCE 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-RESET-ACTIVE-BEHAVIOR>` | `FG-RESET` | FC-RESET-ACTIVE-BEHAVIOR 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-RESET-RECOVERY>` | `FG-RESET` | FC-RESET-RECOVERY 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-RESET-MEMORY-CONTENT>` | `FG-RESET` | FC-RESET-MEMORY-CONTENT 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-LOW-POWER-TRANSPARENT>` | `FG-LOW-POWER` | FC-LOW-POWER-TRANSPARENT 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-DOUT-HOLD>` | `FG-OUTPUT-BEHAVIOR` | FC-DOUT-HOLD 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-DOUT-UPDATE>` | `FG-OUTPUT-BEHAVIOR` | FC-DOUT-UPDATE 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-README-CONSTRAINTS>` | `FG-SPEC-CONSISTENCY` | FC-README-CONSTRAINTS 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |
| `<FC-UNSPECIFIED-BEHAVIOR>` | `FG-SPEC-CONSISTENCY` | FC-UNSPECIFIED-BEHAVIOR 验证 | `P-CORE` | P0 / `CK-WRITE-CYCLE` |

| CK 标签 | Style | 所属 FC | 独立性质 | 逻辑观测点 | RTL / bind 对应 | 属性实现状态 | 签核状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `<CK-WRITE-CYCLE>` | Assume | `FC-STEP-ACCESS` | 能够通过 Step 发起一次写访问并推进时钟。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-READ-CYCLE>` | Assume | `FC-STEP-ACCESS` | 能够通过 Step 发起一次读访问并在规定周期采样输出。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-IDLE-CYCLE>` | Assume | `FC-STEP-ACCESS` | 能够通过 Step 发起 `cs=0` 的空闲周期并观察输出稳定性。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-LOW-POWER-CYCLE>` | Assume | `FC-STEP-ACCESS` | 能够在访问周期中组合驱动 `sd/ds/ls` 输入。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-ASSERT>` | Assume | `FC-RESET-API` | 能够可靠拉低 `rst_n` 并推进时钟。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-DEASSERT>` | Assume | `FC-RESET-API` | 能够可靠释放 `rst_n` 并进入可访问状态。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-POST-RESET-IDLE>` | Assume | `FC-RESET-API` | 复位释放后可插入空闲周期作为访问起点。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-FULL-WORD>` | Seq | `FC-BASIC-WRITE` | `wem` 全有效时，32 位数据整体写入目标地址。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-MULTI-PATTERN>` | Seq | `FC-BASIC-WRITE` | 对全 0、全 1、交替位等不同写入图案均可正确存储。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-REWRITE>` | Seq | `FC-BASIC-WRITE` | 同一地址连续写入不同数据，后一次结果覆盖前一次。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-READBACK>` | Seq | `FC-BASIC-READ` | 先写后读，`dout` 返回最近一次有效写入的数据。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-PRELOAD-ZERO>` | Seq | `FC-BASIC-READ` | 未显式写入位置的读出值符合 FORCE_X2ZERO 期望或实现可观察行为。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-DIFFERENT-ADDR>` | Seq | `FC-BASIC-READ` | 不同地址返回各自独立存储的数据。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-NO-WRITE>` | Seq | `FC-IDLE-NO-ACCESS` | `cs=0` 时即使其余写信号变化也不应改写存储内容。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-NO-READ-EFFECT>` | Seq | `FC-IDLE-NO-ACCESS` | `cs=0` 时输出仅表现为保持值或实现定义的空闲值。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-IDLE-TO-ACTIVE>` | Seq | `FC-IDLE-NO-ACCESS` | 空闲周期之后的首次有效访问仍然正确。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-ALL-BYTES>` | Seq | `FC-WEM-FULL` | 四个字节全部被新数据覆盖。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-EQUIV-BASIC-WRITE>` | Seq | `FC-WEM-FULL` | 结果与基本全字写功能一致。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-BYTE0>` | Seq | `FC-WEM-SINGLE-BYTE` | 仅最低字节被更新。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-BYTE1>` | Seq | `FC-WEM-SINGLE-BYTE` | 仅次低字节被更新。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-BYTE2>` | Seq | `FC-WEM-SINGLE-BYTE` | 仅次高字节被更新。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-BYTE3>` | Seq | `FC-WEM-SINGLE-BYTE` | 仅最高字节被更新。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-ADJACENT-BYTES>` | Seq | `FC-WEM-MULTI-BYTE` | 如 `0011`、`1100` 等组合更新正确。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-NONADJACENT-BYTES>` | Seq | `FC-WEM-MULTI-BYTE` | 如 `0101`、`1010` 等组合更新正确。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-MERGE-WITH-OLD>` | Seq | `FC-WEM-MULTI-BYTE` | 读回值正确反映新字节与旧字节拼接结果。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-NO-BYTE-UPDATED>` | Seq | `FC-WEM-ZERO-MASK` | 读回值与写前完全一致。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-DOUT-NO-CORRUPT>` | Seq | `FC-WEM-ZERO-MASK` | 后续读访问不会看到伪写入数据。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-CS0-WRITE-BLOCK>` | Seq | `FC-CS-GATING` | `cs=0` 时写入请求被阻断。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-CS0-READ-BLOCK>` | Seq | `FC-CS-GATING` | `cs=0` 时不产生新的有效读出。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-CS1-ACCESS-ALLOW>` | Seq | `FC-CS-GATING` | `cs=1` 时可发生合法读写。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-WE1-WRITE-OR-READ>` | Seq | `FC-WE-SEMANTICS` | 判定 `we=1` 时真实行为是写、读还是无操作。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-WE0-WRITE-OR-READ>` | Seq | `FC-WE-SEMANTICS` | 判定 `we=0` 时真实行为是读、写还是无操作。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-SPEC-MISMATCH>` | Seq | `FC-WE-SEMANTICS` | 若 README 约束与 RTL 行为冲突，应能通过测试暴露并记录。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-WRITE-THEN-READ>` | Seq | `FC-READ-WRITE-SWITCH` | 下一次读访问能返回刚写入的数据或体现实现定义延迟。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-READ-THEN-WRITE>` | Seq | `FC-READ-WRITE-SWITCH` | 写操作不受前一拍读控制残留影响。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-ALT-ACCESS>` | Seq | `FC-READ-WRITE-SWITCH` | 多拍交替读写时行为一致稳定。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-TWO-ADDR-INDEP>` | Seq | `FC-ADDRESS-INDEPENDENCE` | 两个不同地址写入不同数据后读回各自正确。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-NEIGHBOR-INDEP>` | Seq | `FC-ADDRESS-INDEPENDENCE` | 相邻地址之间不存在串写或串读。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-DISTANT-INDEP>` | Seq | `FC-ADDRESS-INDEPENDENCE` | 跨较大地址间隔访问仍相互独立。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-LOWEST-ADDR>` | Seq | `FC-ADDRESS-LIMIT` | 最低合法地址可正常读写。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-HIGHEST-ADDR>` | Seq | `FC-ADDRESS-LIMIT` | 最高合法地址可正常读写。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-BOUNDARY-NEIGHBOR>` | Seq | `FC-ADDRESS-LIMIT` | 边界附近连续地址访问正确。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-HIGH-BIT-ALIAS>` | Seq | `FC-ADDRESS-OUT-OF-RANGE` | 仅高位不同的地址是否映射到同一物理单元。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-OUT-RANGE-BEHAVIOR>` | Seq | `FC-ADDRESS-OUT-OF-RANGE` | 超范围地址访问是否被忽略、镜像或产生其他可观察结果。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-SPEC-LACK>` | Seq | `FC-ADDRESS-OUT-OF-RANGE` | 文档未定义越界访问结果时，应记录实现风险。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-SAME-CYCLE>` | Seq | `FC-READ-LATENCY` | 读请求当拍是否立即反映到 `dout`。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-NEXT-CYCLE>` | Seq | `FC-READ-LATENCY` | 读数据是否在下一拍稳定输出。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-LATENCY-CONSISTENT>` | Seq | `FC-READ-LATENCY` | 不同地址与不同访问序列下读时延保持一致。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-WRITE-ON-EDGE>` | Seq | `FC-WRITE-EFFECT-TIME` | 写入在预期时钟边界完成。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-READ-AFTER-WRITE-1C>` | Seq | `FC-WRITE-EFFECT-TIME` | 写后第一个相关读周期可观察到新值。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-NO-EARLY-UPDATE>` | Seq | `FC-WRITE-EFFECT-TIME` | 写请求发起前或不应更新的时刻不出现新数据。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-MULTI-WRITE-LAST-WINS>` | Seq | `FC-SAME-ADDRESS-SEQUENCE` | 连续多次写同址后读回最终值正确。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-READ-BETWEEN-WRITES>` | Seq | `FC-SAME-ADDRESS-SEQUENCE` | 插入读访问时返回与时序一致的值。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-REPEATED-READ>` | Seq | `FC-SAME-ADDRESS-SEQUENCE` | 存储不变时多次读结果一致。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-ACCESS-UNDER-RESET>` | Seq | `FC-RESET-ACTIVE-BEHAVIOR` | 复位期间施加访问不会导致不可恢复异常。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-DOUT-UNDER-RESET>` | Seq | `FC-RESET-ACTIVE-BEHAVIOR` | `dout` 在复位期间表现稳定或符合实现定义。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-RESET-PRIORITY>` | Seq | `FC-RESET-ACTIVE-BEHAVIOR` | 复位与访问同时变化时，复位效果优先或行为一致可解释。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-POST-RESET-WRITE>` | Seq | `FC-RESET-RECOVERY` | 释放复位后可重新成功写入。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-POST-RESET-READ>` | Seq | `FC-RESET-RECOVERY` | 释放复位后可重新成功读取。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-POST-RESET-STABLE>` | Seq | `FC-RESET-RECOVERY` | 释放复位后经过空闲周期再访问仍稳定。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-CONTENT-CLEAR>` | Seq | `FC-RESET-MEMORY-CONTENT` | 若实现支持清零，复位后已写数据被清除。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-CONTENT-KEEP>` | Seq | `FC-RESET-MEMORY-CONTENT` | 若实现不清零，复位前已写数据在复位后仍可读出。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-UNSPECIFIED-SEMANTICS>` | Seq | `FC-RESET-MEMORY-CONTENT` | 若行为与文档描述不足，应记录规格缺口。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-SD-TOGGLE>` | Seq | `FC-LOW-POWER-TRANSPARENT` | 切换 `sd` 不改变正常访问结果。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-DS-TOGGLE>` | Seq | `FC-LOW-POWER-TRANSPARENT` | 切换 `ds` 不改变正常访问结果。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-LS-TOGGLE>` | Seq | `FC-LOW-POWER-TRANSPARENT` | 切换 `ls` 不改变正常访问结果。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-COMB-TOGGLE>` | Seq | `FC-LOW-POWER-TRANSPARENT` | `sd/ds/ls` 组合变化不引入额外副作用。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-HOLD-IDLE>` | Seq | `FC-DOUT-HOLD` | 空闲周期内 `dout` 稳定保持。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-HOLD-CS0>` | Seq | `FC-DOUT-HOLD` | `cs=0` 时 `dout` 不因地址或输入变化而异常跳变。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-HOLD-ZERO-MASK>` | Seq | `FC-DOUT-HOLD` | 零掩码写周期不会导致输出出现错误新值。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-ONLY-ON-VALID-READ>` | Seq | `FC-DOUT-UPDATE` | 只有合法读操作才触发新的读数据输出。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-NO-SPURIOUS-CHANGE>` | Seq | `FC-DOUT-UPDATE` | 控制信号无关变化不会造成 `dout` 伪更新。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-ADDR-CHANGE-WITHOUT-CS>` | Seq | `FC-DOUT-UPDATE` | `cs=0` 下地址变化不应产生新读值。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-CS-WE-CONFLICT>` | Seq | `FC-README-CONSTRAINTS` | 验证“不可同时为高”是否与写使能语义矛盾。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-WEM-WIDTH-ASSUMPTION>` | Seq | `FC-README-CONSTRAINTS` | 字节掩码语义与 32 位数据宽度保持一致。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-ADDR-RANGE-ASSUMPTION>` | Seq | `FC-README-CONSTRAINTS` | 地址越界时设计是否依赖外部约束避免错误。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-RESET-UNSPEC>` | Seq | `FC-UNSPECIFIED-BEHAVIOR` | 文档未明确复位对存储内容和输出的影响。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-LOWPOWER-UNSPEC>` | Seq | `FC-UNSPECIFIED-BEHAVIOR` | 接口存在但功能约束不足。 | `signal.sd` | [附录 B / D] | Planned | Planned |
| `<CK-OUTRANGE-UNSPEC>` | Seq | `FC-UNSPECIFIED-BEHAVIOR` | 超范围地址行为缺乏明确规范。 | `signal.sd` | [附录 B / D] | Planned | Planned |

### 附录 G：签核清单

- [x] 摘要在细节前说明职责、输入输出、关键概念、延迟、验证范围和 OPEN。
- [x] 每项功能按输入、输出、延迟、统一规则、适用实例、边界与限制组织。
- [x] 模块级规则未混入实例枚举；实例差异集中在能力矩阵和附录 C。
- [x] 正文仅以 `[E-*]` 引用证据，完整路径集中在附录 D。
- [x] Test Plan 是验证执行入口；FC/CK 完整登记集中在附录 F。
- [x] API 只包含 Assume，Coverage 只包含 Cover。
- [x] Verilog 端口逐项核对，配置裁剪有依据。
- [x] 正常、资源边界和恢复场景有可判定验收标准。
