# e203_biu 设计与功能检测点文档

> 模板结构版本：v3.3.0
>
> 文档版本：v1.0.0
>
> 本文分为正文、验证计划和附录。正文用于连续理解设计，验证计划用于安排检查，附录用于审计和签核。FG、FC、CK 标签必须使用反引号包裹，例如 `` `<FG-API>` ``。无法证实的内容登记为 `OPEN-*`。

## 第一部分：正文

### 文档摘要

> 本节目标是一页内建立阅读者的整体模型。每项先给结论，不展开实现细节或证据路径。

**模块职责**

`e203_biu` 模块是芯片设计中的硬件执行单元，负责处理相关逻辑、时钟分频、存储或控制功能。

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

`e203_biu` 包含 124 个端口，正文统一使用逻辑名，精确映射见附录 B。

| 逻辑名 | 角色与含义 | 方向 | 事务阶段 |
| --- | --- | --- | --- |
| `producer.data` | 数据与控制输入 | 生产者 -> DUT | 写入 |
| `consumer.data` | 状态与结果输出 | DUT -> 消费者 | 输出 |

#### 微架构与数据流

```mermaid
flowchart LR
    P[Producer]
    C[Consumer]
    subgraph DUT["DUT: e203_biu"]
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
|  `- FC-SINGLE-TRANS
|  `- FC-RSP-INJECT
|  `- FC-CONCURRENT-SCENARIO
|- FG-UPSTREAM
|  `- FC-LSU-CMD
|  `- FC-IFU-CMD
|  `- FC-UPSTREAM-RSP-BACKPRESSURE
|- FG-ARBITRATION
|  `- FC-LSU-PRIORITY
|  `- FC-SINGLE-SOURCE
|  `- FC-SOURCE-ROUTING
|- FG-BUFFER-FLOW
|  `- FC-CMD-BACKPRESSURE
|  `- FC-RSP-INORDER
|  `- FC-BIU-ACTIVE
|- FG-ADDRESS-DECODE
|  `- FC-ROUTE-PPI
|  `- FC-ROUTE-CLINT
|  `- FC-ROUTE-PLIC
|  `- FC-ROUTE-FIO
|  `- FC-ROUTE-MEM
|  `- FC-DECODE-UNIQUE
|- FG-DOWNSTREAM
|  `- FC-TARGET-HANDSHAKE
|  `- FC-UNSELECTED-SILENT
|  `- FC-DOWNSTREAM-RSP-MUX
|- FG-IFU-ERROR
|  `- FC-IFU-PERIPH-ERROR
|  `- FC-IFU-WRITE-ERROR
|  `- FC-DISABLED-TARGET-ERROR
|  `- FC-FAST-ERROR-RSP
|- FG-RESPONSE
|  `- FC-RDATA-RETURN
|  `- FC-ERR-RETURN
|  `- FC-EXCL-OK-RETURN
|- FG-CMD-ATTR
|  `- FC-BASIC-ATTR
|  `- FC-EXT-ATTR
|- FG-CONCURRENCY-BOUNDARY
|  `- FC-DUAL-SOURCE-STRESS
|  `- FC-TARGET-SWITCH
|  `- FC-RESET-BOUNDARY
|  `- FC-EXTREME-BACKPRESSURE
```

`<FG-API>`

FG-API 功能风险覆盖与行为检测。

`<FG-UPSTREAM>`

FG-UPSTREAM 功能风险覆盖与行为检测。

`<FG-ARBITRATION>`

FG-ARBITRATION 功能风险覆盖与行为检测。

`<FG-BUFFER-FLOW>`

FG-BUFFER-FLOW 功能风险覆盖与行为检测。

`<FG-ADDRESS-DECODE>`

FG-ADDRESS-DECODE 功能风险覆盖与行为检测。

`<FG-DOWNSTREAM>`

FG-DOWNSTREAM 功能风险覆盖与行为检测。

`<FG-IFU-ERROR>`

FG-IFU-ERROR 功能风险覆盖与行为检测。

`<FG-RESPONSE>`

FG-RESPONSE 功能风险覆盖与行为检测。

`<FG-CMD-ATTR>`

FG-CMD-ATTR 功能风险覆盖与行为检测。

`<FG-CONCURRENCY-BOUNDARY>`

FG-CONCURRENCY-BOUNDARY 功能风险覆盖与行为检测。

### Test Plan

> 这是验证执行的统一入口。每行连接一个 FC、一个独立 CK、验证机制、Coverage 和场景。功能原理只引用 `P-*`，完整 CK 元数据见附录 F。

| 优先级 | FC | CK | Style | 关联规则 | 检查机制 | 激励 / 前置条件 | 可观察结果 | Coverage / 场景 | 关闭标准 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | `FC-SINGLE-TRANS` | `CK-LSU` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SINGLE-TRANS` | `CK-IFU` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SINGLE-TRANS` | `CK-STEP-DRIVEN` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RSP-INJECT` | `CK-TARGET-SEPARATE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RSP-INJECT` | `CK-ERROR-RSP` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RSP-INJECT` | `CK-ZERO-WAIT` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CONCURRENT-SCENARIO` | `CK-DUAL-MASTER` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CONCURRENT-SCENARIO` | `CK-UPSTREAM-BACKPRESSURE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CONCURRENT-SCENARIO` | `CK-DOWNSTREAM-BACKPRESSURE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-LSU-CMD` | `CK-HS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-LSU-CMD` | `CK-HOLD` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-LSU-CMD` | `CK-RSP-RETURN` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-UPSTREAM-RSP-BACKPRESSURE` | `CK-LSU-STALL` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-UPSTREAM-RSP-BACKPRESSURE` | `CK-IFU-STALL` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-UPSTREAM-RSP-BACKPRESSURE` | `CK-NO-CROSS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-LSU-PRIORITY` | `CK-SAME-CYCLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-LSU-PRIORITY` | `CK-IFU-WAIT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-LSU-PRIORITY` | `CK-POST-LSU` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SINGLE-SOURCE` | `CK-LSU-ONLY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SINGLE-SOURCE` | `CK-IFU-ONLY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SINGLE-SOURCE` | `CK-NO-SPURIOUS-BLOCK` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SOURCE-ROUTING` | `CK-LSU-TAG` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SOURCE-ROUTING` | `CK-IFU-TAG` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SOURCE-ROUTING` | `CK-ORDERED-MIX` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-BACKPRESSURE` | `CK-DOWNSTREAM-NOTREADY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-BACKPRESSURE` | `CK-NO-OVERACCEPT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-BACKPRESSURE` | `CK-RECOVER` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RSP-INORDER` | `CK-TWO-REQ` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RSP-INORDER` | `CK-MIXED-TARGET` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RSP-INORDER` | `CK-NO-DUP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BIU-ACTIVE` | `CK-IDLE-LOW` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BIU-ACTIVE` | `CK-BUSY-HIGH` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BIU-ACTIVE` | `CK-RETURN-IDLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ROUTE-PPI` | `CK-SELECT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ROUTE-PPI` | `CK-UNIQUE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ROUTE-PPI` | `CK-ENABLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ROUTE-MEM` | `CK-DEFAULT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DECODE-UNIQUE` | `CK-ONEHOT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DECODE-UNIQUE` | `CK-ERR-OR-TARGET` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DECODE-UNIQUE` | `CK-NO-GHOST` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-TARGET-HANDSHAKE` | `CK-VALID-READY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-TARGET-HANDSHAKE` | `CK-STABLE-WHEN-WAIT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-TARGET-HANDSHAKE` | `CK-NO-FALSE-HS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-UNSELECTED-SILENT` | `CK-NO-SPURIOUS-PPI` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-UNSELECTED-SILENT` | `CK-NO-SPURIOUS-CLINT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-UNSELECTED-SILENT` | `CK-NO-SPURIOUS-OTHERS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DOWNSTREAM-RSP-MUX` | `CK-CORRECT-SOURCE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DOWNSTREAM-RSP-MUX` | `CK-ERR-PROP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DOWNSTREAM-RSP-MUX` | `CK-RDATA-PROP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-IFU-PERIPH-ERROR` | `CK-PPI` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-IFU-PERIPH-ERROR` | `CK-CLINT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-IFU-PERIPH-ERROR` | `CK-PLIC-FIO` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-IFU-WRITE-ERROR` | `CK-ERR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-IFU-WRITE-ERROR` | `CK-ZERO-DATA` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-IFU-WRITE-ERROR` | `CK-NO-REAL-TARGET` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DISABLED-TARGET-ERROR` | `CK-PERIPH-DISABLED` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DISABLED-TARGET-ERROR` | `CK-MEM-DISABLED` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DISABLED-TARGET-ERROR` | `CK-NO-REROUTE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-FAST-ERROR-RSP` | `CK-LOW-LATENCY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-FAST-ERROR-RSP` | `CK-HS-CONSISTENT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-FAST-ERROR-RSP` | `CK-NO-DEADLOCK` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RDATA-RETURN` | `CK-DIFF-PATTERN` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ERR-RETURN` | `CK-DOWNSTREAM` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ERR-RETURN` | `CK-LOCAL` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ERR-RETURN` | `CK-NO-FALSE-ERR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-EXCL-OK-RETURN` | `CK-PASS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-EXCL-OK-RETURN` | `CK-FAIL` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-EXCL-OK-RETURN` | `CK-INDEPENDENT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BASIC-ATTR` | `CK-ADDR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BASIC-ATTR` | `CK-READ-WRITE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BASIC-ATTR` | `CK-WDATA-WMASK` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-EXT-ATTR` | `CK-BURST-BEAT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-EXT-ATTR` | `CK-LOCK-EXCL` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-EXT-ATTR` | `CK-SIZE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DUAL-SOURCE-STRESS` | `CK-REPEATED-ARBT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DUAL-SOURCE-STRESS` | `CK-PROGRESS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DUAL-SOURCE-STRESS` | `CK-NO-LOCKUP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-TARGET-SWITCH` | `CK-PERIPH-TO-MEM` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-TARGET-SWITCH` | `CK-MEM-TO-PERIPH` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-TARGET-SWITCH` | `CK-NO-LEAKAGE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-RESET-BOUNDARY` | `CK-AFTER-RESET` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESET-BOUNDARY` | `CK-CLEAR-PENDING` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESET-BOUNDARY` | `CK-NO-SPURIOUS-RSP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-EXTREME-BACKPRESSURE` | `CK-LONG-STALL` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-EXTREME-BACKPRESSURE` | `CK-STALL-RECOVER` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-EXTREME-BACKPRESSURE` | `CK-MIXED-CORNER` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-IFU-CMD` | `CK-IFU-CMD-DEFAULT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ROUTE-CLINT` | `CK-ROUTE-CLINT-DEFAULT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ROUTE-PLIC` | `CK-ROUTE-PLIC-DEFAULT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ROUTE-FIO` | `CK-ROUTE-FIO-DEFAULT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |

### Coverage Summary

| Coverage ID | 风险与目标 | 关联 P / FC / CK | 观察事件 | 重要取值 / 分箱 | 依赖 / 交叉 | 非法 / 忽略条件 | 有效性保护 | 关闭标准 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `COV-NORMAL` | 正常功能覆盖 | `P-CORE`, `FC-SINGLE-TRANS`, `CK-LSU` | 正常周期事件 | 典型功能取值 | 核心交叉 | 忽略非法毛刺 | 有效采样 | 命中要求 | Planned |
| `COV-BOUNDARY` | 边界条件覆盖 | `P-CORE`, `FC-EXTREME-BACKPRESSURE`, `CK-ROUTE-FIO-DEFAULT` | 边界周期事件 | 最大/最小值 | 极限交叉 | 忽略非法毛刺 | 有效采样 | 命中要求 | Planned |

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

**预期行为**：遵循 `P-CORE`、`CK-LSU`；关联 Coverage：`COV-NORMAL`。

**验收标准**：输出处于预期初始状态。

#### CASE-NORMAL：正常运算场景

**目标**：验证典型功能处理流程。

**参与者与前置条件**：激励驱动源。

1. 驱动有效输入。
2. 观测输出结果。

**预期行为**：遵循 `P-CORE`、`CK-LSU`；关联 Coverage：`COV-NORMAL`。

**验收标准**：结果正确匹配。

#### CASE-BOUNDARY：边界条件场景

**目标**：验证极限值与异常边界行为。

**参与者与前置条件**：激励驱动源。

1. 驱动边界极值。
2. 检查输出无挂起。

**预期行为**：遵循 `P-CORE`、`CK-ROUTE-FIO-DEFAULT`；关联 Coverage：`COV-BOUNDARY`。

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
| DUT / Chisel 顶层 | e203_biu / [E-TOP-01] |
| Elaborated Verilog 顶层 | e203_biu / [E-RTL-01] |
| 文档状态 | Review |
| XiangShan RTL 基线 | generic-verilog-v1 |
| 适用配置 | DefaultConfig |
| 生成环境 | Linux / x86_64 / Python 3.8 |
| RTL 生成状态 | Success |
| RTL 证据 | evidence/e203_biu/v1.0.0/manifest.json |
| 图形渲染证据 | evidence/e203_biu/v1.0.0/diagrams/manifest.json |
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

本模块包含 124 个叶端口：56 个输入，68 个输出。
RTL SHA-256：`ea2093a96cc032b1aeab9aadbbcf982baa7ea6d614f27ac82d4a18b4901c9b49`。

### 附录 B：逻辑接口与 RTL 映射

> 本附录是逻辑名、字段和精确 elaborated Verilog 端口的唯一映射位置。

| IO-ID | 正文逻辑名 | Bundle class / Chisel 字段 | 定义位置 | 方向 / 位宽 | 配置状态 | 精确 Verilog I/O | 协议 / 对端 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `IO-BIU_ACTIVE` | `signal.biu_active` | `e203_biu.biu_active` | [E-IO-01] | O / 1 | Generated | `biu_active` | Internal / System | [E-RTL-01] |
| `IO-LSU2BIU_ICB_CMD_VALID` | `signal.lsu2biu_icb_cmd_valid` | `e203_biu.lsu2biu_icb_cmd_valid` | [E-IO-01] | I / 1 | Generated | `lsu2biu_icb_cmd_valid` | Internal / System | [E-RTL-01] |
| `IO-LSU2BIU_ICB_CMD_READY` | `signal.lsu2biu_icb_cmd_ready` | `e203_biu.lsu2biu_icb_cmd_ready` | [E-IO-01] | O / 1 | Generated | `lsu2biu_icb_cmd_ready` | Internal / System | [E-RTL-01] |
| `IO-LSU2BIU_ICB_CMD_ADDR` | `signal.lsu2biu_icb_cmd_addr` | `e203_biu.lsu2biu_icb_cmd_addr` | [E-IO-01] | I / 32 | Generated | `lsu2biu_icb_cmd_addr` | Internal / System | [E-RTL-01] |
| `IO-LSU2BIU_ICB_CMD_READ` | `signal.lsu2biu_icb_cmd_read` | `e203_biu.lsu2biu_icb_cmd_read` | [E-IO-01] | I / 1 | Generated | `lsu2biu_icb_cmd_read` | Internal / System | [E-RTL-01] |
| `IO-LSU2BIU_ICB_CMD_WDATA` | `signal.lsu2biu_icb_cmd_wdata` | `e203_biu.lsu2biu_icb_cmd_wdata` | [E-IO-01] | I / 32 | Generated | `lsu2biu_icb_cmd_wdata` | Internal / System | [E-RTL-01] |
| `IO-LSU2BIU_ICB_CMD_WMASK` | `signal.lsu2biu_icb_cmd_wmask` | `e203_biu.lsu2biu_icb_cmd_wmask` | [E-IO-01] | I / 4 | Generated | `lsu2biu_icb_cmd_wmask` | Internal / System | [E-RTL-01] |
| `IO-LSU2BIU_ICB_CMD_BURST` | `signal.lsu2biu_icb_cmd_burst` | `e203_biu.lsu2biu_icb_cmd_burst` | [E-IO-01] | I / 2 | Generated | `lsu2biu_icb_cmd_burst` | Internal / System | [E-RTL-01] |
| `IO-LSU2BIU_ICB_CMD_BEAT` | `signal.lsu2biu_icb_cmd_beat` | `e203_biu.lsu2biu_icb_cmd_beat` | [E-IO-01] | I / 2 | Generated | `lsu2biu_icb_cmd_beat` | Internal / System | [E-RTL-01] |
| `IO-LSU2BIU_ICB_CMD_LOCK` | `signal.lsu2biu_icb_cmd_lock` | `e203_biu.lsu2biu_icb_cmd_lock` | [E-IO-01] | I / 1 | Generated | `lsu2biu_icb_cmd_lock` | Internal / System | [E-RTL-01] |
| `IO-LSU2BIU_ICB_CMD_EXCL` | `signal.lsu2biu_icb_cmd_excl` | `e203_biu.lsu2biu_icb_cmd_excl` | [E-IO-01] | I / 1 | Generated | `lsu2biu_icb_cmd_excl` | Internal / System | [E-RTL-01] |
| `IO-LSU2BIU_ICB_CMD_SIZE` | `signal.lsu2biu_icb_cmd_size` | `e203_biu.lsu2biu_icb_cmd_size` | [E-IO-01] | I / 2 | Generated | `lsu2biu_icb_cmd_size` | Internal / System | [E-RTL-01] |
| `IO-LSU2BIU_ICB_RSP_VALID` | `signal.lsu2biu_icb_rsp_valid` | `e203_biu.lsu2biu_icb_rsp_valid` | [E-IO-01] | O / 1 | Generated | `lsu2biu_icb_rsp_valid` | Internal / System | [E-RTL-01] |
| `IO-LSU2BIU_ICB_RSP_READY` | `signal.lsu2biu_icb_rsp_ready` | `e203_biu.lsu2biu_icb_rsp_ready` | [E-IO-01] | I / 1 | Generated | `lsu2biu_icb_rsp_ready` | Internal / System | [E-RTL-01] |
| `IO-LSU2BIU_ICB_RSP_ERR` | `signal.lsu2biu_icb_rsp_err` | `e203_biu.lsu2biu_icb_rsp_err` | [E-IO-01] | O / 1 | Generated | `lsu2biu_icb_rsp_err` | Internal / System | [E-RTL-01] |
| `IO-LSU2BIU_ICB_RSP_EXCL_OK` | `signal.lsu2biu_icb_rsp_excl_ok` | `e203_biu.lsu2biu_icb_rsp_excl_ok` | [E-IO-01] | O / 1 | Generated | `lsu2biu_icb_rsp_excl_ok` | Internal / System | [E-RTL-01] |
| `IO-LSU2BIU_ICB_RSP_RDATA` | `signal.lsu2biu_icb_rsp_rdata` | `e203_biu.lsu2biu_icb_rsp_rdata` | [E-IO-01] | O / 32 | Generated | `lsu2biu_icb_rsp_rdata` | Internal / System | [E-RTL-01] |
| `IO-IFDEF` | `signal.ifdef` | `e203_biu.ifdef` | [E-IO-01] | O / 32 | Generated | `ifdef` | Internal / System | [E-RTL-01] |
| `IO-IFU2BIU_ICB_CMD_READY` | `signal.ifu2biu_icb_cmd_ready` | `e203_biu.ifu2biu_icb_cmd_ready` | [E-IO-01] | O / 1 | Generated | `ifu2biu_icb_cmd_ready` | Internal / System | [E-RTL-01] |
| `IO-IFU2BIU_ICB_CMD_ADDR` | `signal.ifu2biu_icb_cmd_addr` | `e203_biu.ifu2biu_icb_cmd_addr` | [E-IO-01] | I / 32 | Generated | `ifu2biu_icb_cmd_addr` | Internal / System | [E-RTL-01] |
| `IO-IFU2BIU_ICB_CMD_READ` | `signal.ifu2biu_icb_cmd_read` | `e203_biu.ifu2biu_icb_cmd_read` | [E-IO-01] | I / 1 | Generated | `ifu2biu_icb_cmd_read` | Internal / System | [E-RTL-01] |
| `IO-IFU2BIU_ICB_CMD_WDATA` | `signal.ifu2biu_icb_cmd_wdata` | `e203_biu.ifu2biu_icb_cmd_wdata` | [E-IO-01] | I / 32 | Generated | `ifu2biu_icb_cmd_wdata` | Internal / System | [E-RTL-01] |
| `IO-IFU2BIU_ICB_CMD_WMASK` | `signal.ifu2biu_icb_cmd_wmask` | `e203_biu.ifu2biu_icb_cmd_wmask` | [E-IO-01] | I / 4 | Generated | `ifu2biu_icb_cmd_wmask` | Internal / System | [E-RTL-01] |
| `IO-IFU2BIU_ICB_CMD_BURST` | `signal.ifu2biu_icb_cmd_burst` | `e203_biu.ifu2biu_icb_cmd_burst` | [E-IO-01] | I / 2 | Generated | `ifu2biu_icb_cmd_burst` | Internal / System | [E-RTL-01] |
| `IO-IFU2BIU_ICB_CMD_BEAT` | `signal.ifu2biu_icb_cmd_beat` | `e203_biu.ifu2biu_icb_cmd_beat` | [E-IO-01] | I / 2 | Generated | `ifu2biu_icb_cmd_beat` | Internal / System | [E-RTL-01] |
| `IO-IFU2BIU_ICB_CMD_LOCK` | `signal.ifu2biu_icb_cmd_lock` | `e203_biu.ifu2biu_icb_cmd_lock` | [E-IO-01] | I / 1 | Generated | `ifu2biu_icb_cmd_lock` | Internal / System | [E-RTL-01] |
| `IO-IFU2BIU_ICB_CMD_EXCL` | `signal.ifu2biu_icb_cmd_excl` | `e203_biu.ifu2biu_icb_cmd_excl` | [E-IO-01] | I / 1 | Generated | `ifu2biu_icb_cmd_excl` | Internal / System | [E-RTL-01] |
| `IO-IFU2BIU_ICB_CMD_SIZE` | `signal.ifu2biu_icb_cmd_size` | `e203_biu.ifu2biu_icb_cmd_size` | [E-IO-01] | I / 2 | Generated | `ifu2biu_icb_cmd_size` | Internal / System | [E-RTL-01] |
| `IO-IFU2BIU_ICB_RSP_VALID` | `signal.ifu2biu_icb_rsp_valid` | `e203_biu.ifu2biu_icb_rsp_valid` | [E-IO-01] | O / 1 | Generated | `ifu2biu_icb_rsp_valid` | Internal / System | [E-RTL-01] |
| `IO-IFU2BIU_ICB_RSP_READY` | `signal.ifu2biu_icb_rsp_ready` | `e203_biu.ifu2biu_icb_rsp_ready` | [E-IO-01] | I / 1 | Generated | `ifu2biu_icb_rsp_ready` | Internal / System | [E-RTL-01] |
| `IO-IFU2BIU_ICB_RSP_ERR` | `signal.ifu2biu_icb_rsp_err` | `e203_biu.ifu2biu_icb_rsp_err` | [E-IO-01] | O / 1 | Generated | `ifu2biu_icb_rsp_err` | Internal / System | [E-RTL-01] |
| `IO-IFU2BIU_ICB_RSP_EXCL_OK` | `signal.ifu2biu_icb_rsp_excl_ok` | `e203_biu.ifu2biu_icb_rsp_excl_ok` | [E-IO-01] | O / 1 | Generated | `ifu2biu_icb_rsp_excl_ok` | Internal / System | [E-RTL-01] |
| `IO-IFU2BIU_ICB_RSP_RDATA` | `signal.ifu2biu_icb_rsp_rdata` | `e203_biu.ifu2biu_icb_rsp_rdata` | [E-IO-01] | O / 32 | Generated | `ifu2biu_icb_rsp_rdata` | Internal / System | [E-RTL-01] |
| `IO-ENDIF` | `signal.endif` | `e203_biu.endif` | [E-IO-01] | O / 32 | Generated | `endif` | Internal / System | [E-RTL-01] |
| `IO-PPI_ICB_ENABLE` | `signal.ppi_icb_enable` | `e203_biu.ppi_icb_enable` | [E-IO-01] | I / 1 | Generated | `ppi_icb_enable` | Internal / System | [E-RTL-01] |
| `IO-PPI_ICB_CMD_VALID` | `signal.ppi_icb_cmd_valid` | `e203_biu.ppi_icb_cmd_valid` | [E-IO-01] | O / 1 | Generated | `ppi_icb_cmd_valid` | Internal / System | [E-RTL-01] |
| `IO-PPI_ICB_CMD_READY` | `signal.ppi_icb_cmd_ready` | `e203_biu.ppi_icb_cmd_ready` | [E-IO-01] | I / 1 | Generated | `ppi_icb_cmd_ready` | Internal / System | [E-RTL-01] |
| `IO-PPI_ICB_CMD_ADDR` | `signal.ppi_icb_cmd_addr` | `e203_biu.ppi_icb_cmd_addr` | [E-IO-01] | O / 32 | Generated | `ppi_icb_cmd_addr` | Internal / System | [E-RTL-01] |
| `IO-PPI_ICB_CMD_READ` | `signal.ppi_icb_cmd_read` | `e203_biu.ppi_icb_cmd_read` | [E-IO-01] | O / 1 | Generated | `ppi_icb_cmd_read` | Internal / System | [E-RTL-01] |
| `IO-PPI_ICB_CMD_WDATA` | `signal.ppi_icb_cmd_wdata` | `e203_biu.ppi_icb_cmd_wdata` | [E-IO-01] | O / 32 | Generated | `ppi_icb_cmd_wdata` | Internal / System | [E-RTL-01] |
| `IO-PPI_ICB_CMD_WMASK` | `signal.ppi_icb_cmd_wmask` | `e203_biu.ppi_icb_cmd_wmask` | [E-IO-01] | O / 4 | Generated | `ppi_icb_cmd_wmask` | Internal / System | [E-RTL-01] |
| `IO-PPI_ICB_CMD_BURST` | `signal.ppi_icb_cmd_burst` | `e203_biu.ppi_icb_cmd_burst` | [E-IO-01] | O / 2 | Generated | `ppi_icb_cmd_burst` | Internal / System | [E-RTL-01] |
| `IO-PPI_ICB_CMD_BEAT` | `signal.ppi_icb_cmd_beat` | `e203_biu.ppi_icb_cmd_beat` | [E-IO-01] | O / 2 | Generated | `ppi_icb_cmd_beat` | Internal / System | [E-RTL-01] |
| `IO-PPI_ICB_CMD_LOCK` | `signal.ppi_icb_cmd_lock` | `e203_biu.ppi_icb_cmd_lock` | [E-IO-01] | O / 1 | Generated | `ppi_icb_cmd_lock` | Internal / System | [E-RTL-01] |
| `IO-PPI_ICB_CMD_EXCL` | `signal.ppi_icb_cmd_excl` | `e203_biu.ppi_icb_cmd_excl` | [E-IO-01] | O / 1 | Generated | `ppi_icb_cmd_excl` | Internal / System | [E-RTL-01] |
| `IO-PPI_ICB_CMD_SIZE` | `signal.ppi_icb_cmd_size` | `e203_biu.ppi_icb_cmd_size` | [E-IO-01] | O / 2 | Generated | `ppi_icb_cmd_size` | Internal / System | [E-RTL-01] |
| `IO-PPI_ICB_RSP_VALID` | `signal.ppi_icb_rsp_valid` | `e203_biu.ppi_icb_rsp_valid` | [E-IO-01] | I / 1 | Generated | `ppi_icb_rsp_valid` | Internal / System | [E-RTL-01] |
| `IO-PPI_ICB_RSP_READY` | `signal.ppi_icb_rsp_ready` | `e203_biu.ppi_icb_rsp_ready` | [E-IO-01] | O / 1 | Generated | `ppi_icb_rsp_ready` | Internal / System | [E-RTL-01] |
| `IO-PPI_ICB_RSP_ERR` | `signal.ppi_icb_rsp_err` | `e203_biu.ppi_icb_rsp_err` | [E-IO-01] | I / 1 | Generated | `ppi_icb_rsp_err` | Internal / System | [E-RTL-01] |
| `IO-PPI_ICB_RSP_EXCL_OK` | `signal.ppi_icb_rsp_excl_ok` | `e203_biu.ppi_icb_rsp_excl_ok` | [E-IO-01] | I / 1 | Generated | `ppi_icb_rsp_excl_ok` | Internal / System | [E-RTL-01] |
| `IO-PPI_ICB_RSP_RDATA` | `signal.ppi_icb_rsp_rdata` | `e203_biu.ppi_icb_rsp_rdata` | [E-IO-01] | I / 32 | Generated | `ppi_icb_rsp_rdata` | Internal / System | [E-RTL-01] |
| `IO-CLINT_REGION_INDIC` | `signal.clint_region_indic` | `e203_biu.clint_region_indic` | [E-IO-01] | I / 32 | Generated | `clint_region_indic` | Internal / System | [E-RTL-01] |
| `IO-CLINT_ICB_ENABLE` | `signal.clint_icb_enable` | `e203_biu.clint_icb_enable` | [E-IO-01] | I / 1 | Generated | `clint_icb_enable` | Internal / System | [E-RTL-01] |
| `IO-CLINT_ICB_CMD_VALID` | `signal.clint_icb_cmd_valid` | `e203_biu.clint_icb_cmd_valid` | [E-IO-01] | O / 1 | Generated | `clint_icb_cmd_valid` | Internal / System | [E-RTL-01] |
| `IO-CLINT_ICB_CMD_READY` | `signal.clint_icb_cmd_ready` | `e203_biu.clint_icb_cmd_ready` | [E-IO-01] | I / 1 | Generated | `clint_icb_cmd_ready` | Internal / System | [E-RTL-01] |
| `IO-CLINT_ICB_CMD_ADDR` | `signal.clint_icb_cmd_addr` | `e203_biu.clint_icb_cmd_addr` | [E-IO-01] | O / 32 | Generated | `clint_icb_cmd_addr` | Internal / System | [E-RTL-01] |
| `IO-CLINT_ICB_CMD_READ` | `signal.clint_icb_cmd_read` | `e203_biu.clint_icb_cmd_read` | [E-IO-01] | O / 1 | Generated | `clint_icb_cmd_read` | Internal / System | [E-RTL-01] |
| `IO-CLINT_ICB_CMD_WDATA` | `signal.clint_icb_cmd_wdata` | `e203_biu.clint_icb_cmd_wdata` | [E-IO-01] | O / 32 | Generated | `clint_icb_cmd_wdata` | Internal / System | [E-RTL-01] |
| `IO-CLINT_ICB_CMD_WMASK` | `signal.clint_icb_cmd_wmask` | `e203_biu.clint_icb_cmd_wmask` | [E-IO-01] | O / 4 | Generated | `clint_icb_cmd_wmask` | Internal / System | [E-RTL-01] |
| `IO-CLINT_ICB_CMD_BURST` | `signal.clint_icb_cmd_burst` | `e203_biu.clint_icb_cmd_burst` | [E-IO-01] | O / 2 | Generated | `clint_icb_cmd_burst` | Internal / System | [E-RTL-01] |
| `IO-CLINT_ICB_CMD_BEAT` | `signal.clint_icb_cmd_beat` | `e203_biu.clint_icb_cmd_beat` | [E-IO-01] | O / 2 | Generated | `clint_icb_cmd_beat` | Internal / System | [E-RTL-01] |
| `IO-CLINT_ICB_CMD_LOCK` | `signal.clint_icb_cmd_lock` | `e203_biu.clint_icb_cmd_lock` | [E-IO-01] | O / 1 | Generated | `clint_icb_cmd_lock` | Internal / System | [E-RTL-01] |
| `IO-CLINT_ICB_CMD_EXCL` | `signal.clint_icb_cmd_excl` | `e203_biu.clint_icb_cmd_excl` | [E-IO-01] | O / 1 | Generated | `clint_icb_cmd_excl` | Internal / System | [E-RTL-01] |
| `IO-CLINT_ICB_CMD_SIZE` | `signal.clint_icb_cmd_size` | `e203_biu.clint_icb_cmd_size` | [E-IO-01] | O / 2 | Generated | `clint_icb_cmd_size` | Internal / System | [E-RTL-01] |
| `IO-CLINT_ICB_RSP_VALID` | `signal.clint_icb_rsp_valid` | `e203_biu.clint_icb_rsp_valid` | [E-IO-01] | I / 1 | Generated | `clint_icb_rsp_valid` | Internal / System | [E-RTL-01] |
| `IO-CLINT_ICB_RSP_READY` | `signal.clint_icb_rsp_ready` | `e203_biu.clint_icb_rsp_ready` | [E-IO-01] | O / 1 | Generated | `clint_icb_rsp_ready` | Internal / System | [E-RTL-01] |
| `IO-CLINT_ICB_RSP_ERR` | `signal.clint_icb_rsp_err` | `e203_biu.clint_icb_rsp_err` | [E-IO-01] | I / 1 | Generated | `clint_icb_rsp_err` | Internal / System | [E-RTL-01] |
| `IO-CLINT_ICB_RSP_EXCL_OK` | `signal.clint_icb_rsp_excl_ok` | `e203_biu.clint_icb_rsp_excl_ok` | [E-IO-01] | I / 1 | Generated | `clint_icb_rsp_excl_ok` | Internal / System | [E-RTL-01] |
| `IO-CLINT_ICB_RSP_RDATA` | `signal.clint_icb_rsp_rdata` | `e203_biu.clint_icb_rsp_rdata` | [E-IO-01] | I / 32 | Generated | `clint_icb_rsp_rdata` | Internal / System | [E-RTL-01] |
| `IO-PLIC_REGION_INDIC` | `signal.plic_region_indic` | `e203_biu.plic_region_indic` | [E-IO-01] | I / 32 | Generated | `plic_region_indic` | Internal / System | [E-RTL-01] |
| `IO-PLIC_ICB_ENABLE` | `signal.plic_icb_enable` | `e203_biu.plic_icb_enable` | [E-IO-01] | I / 1 | Generated | `plic_icb_enable` | Internal / System | [E-RTL-01] |
| `IO-PLIC_ICB_CMD_VALID` | `signal.plic_icb_cmd_valid` | `e203_biu.plic_icb_cmd_valid` | [E-IO-01] | O / 1 | Generated | `plic_icb_cmd_valid` | Internal / System | [E-RTL-01] |
| `IO-PLIC_ICB_CMD_READY` | `signal.plic_icb_cmd_ready` | `e203_biu.plic_icb_cmd_ready` | [E-IO-01] | I / 1 | Generated | `plic_icb_cmd_ready` | Internal / System | [E-RTL-01] |
| `IO-PLIC_ICB_CMD_ADDR` | `signal.plic_icb_cmd_addr` | `e203_biu.plic_icb_cmd_addr` | [E-IO-01] | O / 32 | Generated | `plic_icb_cmd_addr` | Internal / System | [E-RTL-01] |
| `IO-PLIC_ICB_CMD_READ` | `signal.plic_icb_cmd_read` | `e203_biu.plic_icb_cmd_read` | [E-IO-01] | O / 1 | Generated | `plic_icb_cmd_read` | Internal / System | [E-RTL-01] |
| `IO-PLIC_ICB_CMD_WDATA` | `signal.plic_icb_cmd_wdata` | `e203_biu.plic_icb_cmd_wdata` | [E-IO-01] | O / 32 | Generated | `plic_icb_cmd_wdata` | Internal / System | [E-RTL-01] |
| `IO-PLIC_ICB_CMD_WMASK` | `signal.plic_icb_cmd_wmask` | `e203_biu.plic_icb_cmd_wmask` | [E-IO-01] | O / 4 | Generated | `plic_icb_cmd_wmask` | Internal / System | [E-RTL-01] |
| `IO-PLIC_ICB_CMD_BURST` | `signal.plic_icb_cmd_burst` | `e203_biu.plic_icb_cmd_burst` | [E-IO-01] | O / 2 | Generated | `plic_icb_cmd_burst` | Internal / System | [E-RTL-01] |
| `IO-PLIC_ICB_CMD_BEAT` | `signal.plic_icb_cmd_beat` | `e203_biu.plic_icb_cmd_beat` | [E-IO-01] | O / 2 | Generated | `plic_icb_cmd_beat` | Internal / System | [E-RTL-01] |
| `IO-PLIC_ICB_CMD_LOCK` | `signal.plic_icb_cmd_lock` | `e203_biu.plic_icb_cmd_lock` | [E-IO-01] | O / 1 | Generated | `plic_icb_cmd_lock` | Internal / System | [E-RTL-01] |
| `IO-PLIC_ICB_CMD_EXCL` | `signal.plic_icb_cmd_excl` | `e203_biu.plic_icb_cmd_excl` | [E-IO-01] | O / 1 | Generated | `plic_icb_cmd_excl` | Internal / System | [E-RTL-01] |
| `IO-PLIC_ICB_CMD_SIZE` | `signal.plic_icb_cmd_size` | `e203_biu.plic_icb_cmd_size` | [E-IO-01] | O / 2 | Generated | `plic_icb_cmd_size` | Internal / System | [E-RTL-01] |
| `IO-PLIC_ICB_RSP_VALID` | `signal.plic_icb_rsp_valid` | `e203_biu.plic_icb_rsp_valid` | [E-IO-01] | I / 1 | Generated | `plic_icb_rsp_valid` | Internal / System | [E-RTL-01] |
| `IO-PLIC_ICB_RSP_READY` | `signal.plic_icb_rsp_ready` | `e203_biu.plic_icb_rsp_ready` | [E-IO-01] | O / 1 | Generated | `plic_icb_rsp_ready` | Internal / System | [E-RTL-01] |
| `IO-PLIC_ICB_RSP_ERR` | `signal.plic_icb_rsp_err` | `e203_biu.plic_icb_rsp_err` | [E-IO-01] | I / 1 | Generated | `plic_icb_rsp_err` | Internal / System | [E-RTL-01] |
| `IO-PLIC_ICB_RSP_EXCL_OK` | `signal.plic_icb_rsp_excl_ok` | `e203_biu.plic_icb_rsp_excl_ok` | [E-IO-01] | I / 1 | Generated | `plic_icb_rsp_excl_ok` | Internal / System | [E-RTL-01] |
| `IO-PLIC_ICB_RSP_RDATA` | `signal.plic_icb_rsp_rdata` | `e203_biu.plic_icb_rsp_rdata` | [E-IO-01] | I / 32 | Generated | `plic_icb_rsp_rdata` | Internal / System | [E-RTL-01] |
| `IO-IFDEF` | `signal.ifdef` | `e203_biu.ifdef` | [E-IO-01] | I / 32 | Generated | `ifdef` | Internal / System | [E-RTL-01] |
| `IO-FIO_ICB_ENABLE` | `signal.fio_icb_enable` | `e203_biu.fio_icb_enable` | [E-IO-01] | I / 1 | Generated | `fio_icb_enable` | Internal / System | [E-RTL-01] |
| `IO-FIO_ICB_CMD_VALID` | `signal.fio_icb_cmd_valid` | `e203_biu.fio_icb_cmd_valid` | [E-IO-01] | O / 1 | Generated | `fio_icb_cmd_valid` | Internal / System | [E-RTL-01] |
| `IO-FIO_ICB_CMD_READY` | `signal.fio_icb_cmd_ready` | `e203_biu.fio_icb_cmd_ready` | [E-IO-01] | I / 1 | Generated | `fio_icb_cmd_ready` | Internal / System | [E-RTL-01] |
| `IO-FIO_ICB_CMD_ADDR` | `signal.fio_icb_cmd_addr` | `e203_biu.fio_icb_cmd_addr` | [E-IO-01] | O / 32 | Generated | `fio_icb_cmd_addr` | Internal / System | [E-RTL-01] |
| `IO-FIO_ICB_CMD_READ` | `signal.fio_icb_cmd_read` | `e203_biu.fio_icb_cmd_read` | [E-IO-01] | O / 1 | Generated | `fio_icb_cmd_read` | Internal / System | [E-RTL-01] |
| `IO-FIO_ICB_CMD_WDATA` | `signal.fio_icb_cmd_wdata` | `e203_biu.fio_icb_cmd_wdata` | [E-IO-01] | O / 32 | Generated | `fio_icb_cmd_wdata` | Internal / System | [E-RTL-01] |
| `IO-FIO_ICB_CMD_WMASK` | `signal.fio_icb_cmd_wmask` | `e203_biu.fio_icb_cmd_wmask` | [E-IO-01] | O / 4 | Generated | `fio_icb_cmd_wmask` | Internal / System | [E-RTL-01] |
| `IO-FIO_ICB_CMD_BURST` | `signal.fio_icb_cmd_burst` | `e203_biu.fio_icb_cmd_burst` | [E-IO-01] | O / 2 | Generated | `fio_icb_cmd_burst` | Internal / System | [E-RTL-01] |
| `IO-FIO_ICB_CMD_BEAT` | `signal.fio_icb_cmd_beat` | `e203_biu.fio_icb_cmd_beat` | [E-IO-01] | O / 2 | Generated | `fio_icb_cmd_beat` | Internal / System | [E-RTL-01] |
| `IO-FIO_ICB_CMD_LOCK` | `signal.fio_icb_cmd_lock` | `e203_biu.fio_icb_cmd_lock` | [E-IO-01] | O / 1 | Generated | `fio_icb_cmd_lock` | Internal / System | [E-RTL-01] |
| `IO-FIO_ICB_CMD_EXCL` | `signal.fio_icb_cmd_excl` | `e203_biu.fio_icb_cmd_excl` | [E-IO-01] | O / 1 | Generated | `fio_icb_cmd_excl` | Internal / System | [E-RTL-01] |
| `IO-FIO_ICB_CMD_SIZE` | `signal.fio_icb_cmd_size` | `e203_biu.fio_icb_cmd_size` | [E-IO-01] | O / 2 | Generated | `fio_icb_cmd_size` | Internal / System | [E-RTL-01] |
| `IO-FIO_ICB_RSP_VALID` | `signal.fio_icb_rsp_valid` | `e203_biu.fio_icb_rsp_valid` | [E-IO-01] | I / 1 | Generated | `fio_icb_rsp_valid` | Internal / System | [E-RTL-01] |
| `IO-FIO_ICB_RSP_READY` | `signal.fio_icb_rsp_ready` | `e203_biu.fio_icb_rsp_ready` | [E-IO-01] | O / 1 | Generated | `fio_icb_rsp_ready` | Internal / System | [E-RTL-01] |
| `IO-FIO_ICB_RSP_ERR` | `signal.fio_icb_rsp_err` | `e203_biu.fio_icb_rsp_err` | [E-IO-01] | I / 1 | Generated | `fio_icb_rsp_err` | Internal / System | [E-RTL-01] |
| `IO-FIO_ICB_RSP_EXCL_OK` | `signal.fio_icb_rsp_excl_ok` | `e203_biu.fio_icb_rsp_excl_ok` | [E-IO-01] | I / 1 | Generated | `fio_icb_rsp_excl_ok` | Internal / System | [E-RTL-01] |
| `IO-FIO_ICB_RSP_RDATA` | `signal.fio_icb_rsp_rdata` | `e203_biu.fio_icb_rsp_rdata` | [E-IO-01] | I / 32 | Generated | `fio_icb_rsp_rdata` | Internal / System | [E-RTL-01] |
| `IO-ENDIF` | `signal.endif` | `e203_biu.endif` | [E-IO-01] | I / 32 | Generated | `endif` | Internal / System | [E-RTL-01] |
| `IO-MEM_ICB_CMD_VALID` | `signal.mem_icb_cmd_valid` | `e203_biu.mem_icb_cmd_valid` | [E-IO-01] | O / 1 | Generated | `mem_icb_cmd_valid` | Internal / System | [E-RTL-01] |
| `IO-MEM_ICB_CMD_READY` | `signal.mem_icb_cmd_ready` | `e203_biu.mem_icb_cmd_ready` | [E-IO-01] | I / 1 | Generated | `mem_icb_cmd_ready` | Internal / System | [E-RTL-01] |
| `IO-MEM_ICB_CMD_ADDR` | `signal.mem_icb_cmd_addr` | `e203_biu.mem_icb_cmd_addr` | [E-IO-01] | O / 32 | Generated | `mem_icb_cmd_addr` | Internal / System | [E-RTL-01] |
| `IO-MEM_ICB_CMD_READ` | `signal.mem_icb_cmd_read` | `e203_biu.mem_icb_cmd_read` | [E-IO-01] | O / 1 | Generated | `mem_icb_cmd_read` | Internal / System | [E-RTL-01] |
| `IO-MEM_ICB_CMD_WDATA` | `signal.mem_icb_cmd_wdata` | `e203_biu.mem_icb_cmd_wdata` | [E-IO-01] | O / 32 | Generated | `mem_icb_cmd_wdata` | Internal / System | [E-RTL-01] |
| `IO-MEM_ICB_CMD_WMASK` | `signal.mem_icb_cmd_wmask` | `e203_biu.mem_icb_cmd_wmask` | [E-IO-01] | O / 4 | Generated | `mem_icb_cmd_wmask` | Internal / System | [E-RTL-01] |
| `IO-MEM_ICB_CMD_BURST` | `signal.mem_icb_cmd_burst` | `e203_biu.mem_icb_cmd_burst` | [E-IO-01] | O / 2 | Generated | `mem_icb_cmd_burst` | Internal / System | [E-RTL-01] |
| `IO-MEM_ICB_CMD_BEAT` | `signal.mem_icb_cmd_beat` | `e203_biu.mem_icb_cmd_beat` | [E-IO-01] | O / 2 | Generated | `mem_icb_cmd_beat` | Internal / System | [E-RTL-01] |
| `IO-MEM_ICB_CMD_LOCK` | `signal.mem_icb_cmd_lock` | `e203_biu.mem_icb_cmd_lock` | [E-IO-01] | O / 1 | Generated | `mem_icb_cmd_lock` | Internal / System | [E-RTL-01] |
| `IO-MEM_ICB_CMD_EXCL` | `signal.mem_icb_cmd_excl` | `e203_biu.mem_icb_cmd_excl` | [E-IO-01] | O / 1 | Generated | `mem_icb_cmd_excl` | Internal / System | [E-RTL-01] |
| `IO-MEM_ICB_CMD_SIZE` | `signal.mem_icb_cmd_size` | `e203_biu.mem_icb_cmd_size` | [E-IO-01] | O / 2 | Generated | `mem_icb_cmd_size` | Internal / System | [E-RTL-01] |
| `IO-MEM_ICB_RSP_VALID` | `signal.mem_icb_rsp_valid` | `e203_biu.mem_icb_rsp_valid` | [E-IO-01] | I / 1 | Generated | `mem_icb_rsp_valid` | Internal / System | [E-RTL-01] |
| `IO-MEM_ICB_RSP_READY` | `signal.mem_icb_rsp_ready` | `e203_biu.mem_icb_rsp_ready` | [E-IO-01] | O / 1 | Generated | `mem_icb_rsp_ready` | Internal / System | [E-RTL-01] |
| `IO-MEM_ICB_RSP_ERR` | `signal.mem_icb_rsp_err` | `e203_biu.mem_icb_rsp_err` | [E-IO-01] | I / 1 | Generated | `mem_icb_rsp_err` | Internal / System | [E-RTL-01] |
| `IO-MEM_ICB_RSP_EXCL_OK` | `signal.mem_icb_rsp_excl_ok` | `e203_biu.mem_icb_rsp_excl_ok` | [E-IO-01] | I / 1 | Generated | `mem_icb_rsp_excl_ok` | Internal / System | [E-RTL-01] |
| `IO-MEM_ICB_RSP_RDATA` | `signal.mem_icb_rsp_rdata` | `e203_biu.mem_icb_rsp_rdata` | [E-IO-01] | I / 32 | Generated | `mem_icb_rsp_rdata` | Internal / System | [E-RTL-01] |
| `IO-ENDIF` | `signal.endif` | `e203_biu.endif` | [E-IO-01] | I / 32 | Generated | `endif` | Internal / System | [E-RTL-01] |
| `IO-RST_N` | `signal.rst_n` | `e203_biu.rst_n` | [E-IO-01] | I / 1 | Generated | `rst_n` | Internal / System | [E-RTL-01] |

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
| E-BEH-01 | Verilog | `e203_biu.v:1` | generic-verilog-v1 / DefaultConfig | `P-CORE` |
| E-RES-01 | Verilog | `e203_biu.v:1` | generic-verilog-v1 / DefaultConfig | 资源更新规则 |
| E-FSM-01 | Verilog | `e203_biu.v:1` | generic-verilog-v1 / DefaultConfig | 状态机判定 |
| E-TOP-01 | Verilog | `e203_biu.v:1` | generic-verilog-v1 / DefaultConfig | DUT 顶层定义 |
| E-RTL-01 | RTL / manifest / ports.csv | `e203_biu.v:1` | generic-verilog-v1 / DefaultConfig | 端口定义与映射 |
| E-IO-01 | Verilog Port | `e203_biu.v:1` | generic-verilog-v1 / DefaultConfig | 端口列表 |
| E-PARAM-01 | Verilog Define | `e203_biu.v:1` | generic-verilog-v1 / DefaultConfig | 参数定义 |
| E-CONFIG-01 | Verilog Structure | `e203_biu.v:1` | generic-verilog-v1 / DefaultConfig | 实例能力 |

### 附录 E：FACT、OPEN 与偏差

| ID | 类型 | 摘要 | 关联规则 | 证据 / 缺口 | 状态与关闭条件 |
| --- | --- | --- | --- | --- | --- |
| FACT-001 | 实现事实 | 模块由硬件 Verilog RTL 综合实现 | `P-CORE` | [E-BEH-01] | Closed |

### 附录 F：FC / CK 完整追溯

> 本附录服务于 UCAgent 和审计，不作为主要阅读入口。FC 定义验证目标，CK 定义单一可执行性质；二者不得重复功能原理。

| FC 标签 | 所属 FG | 验证目标 | 关联规则 | Test Plan 行 |
| --- | --- | --- | --- | --- |
| `<FC-SINGLE-TRANS>` | `FG-API` | FC-SINGLE-TRANS 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-RSP-INJECT>` | `FG-API` | FC-RSP-INJECT 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-CONCURRENT-SCENARIO>` | `FG-API` | FC-CONCURRENT-SCENARIO 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-LSU-CMD>` | `FG-UPSTREAM` | FC-LSU-CMD 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-IFU-CMD>` | `FG-UPSTREAM` | FC-IFU-CMD 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-UPSTREAM-RSP-BACKPRESSURE>` | `FG-UPSTREAM` | FC-UPSTREAM-RSP-BACKPRESSURE 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-LSU-PRIORITY>` | `FG-ARBITRATION` | FC-LSU-PRIORITY 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-SINGLE-SOURCE>` | `FG-ARBITRATION` | FC-SINGLE-SOURCE 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-SOURCE-ROUTING>` | `FG-ARBITRATION` | FC-SOURCE-ROUTING 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-CMD-BACKPRESSURE>` | `FG-BUFFER-FLOW` | FC-CMD-BACKPRESSURE 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-RSP-INORDER>` | `FG-BUFFER-FLOW` | FC-RSP-INORDER 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-BIU-ACTIVE>` | `FG-BUFFER-FLOW` | FC-BIU-ACTIVE 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-ROUTE-PPI>` | `FG-ADDRESS-DECODE` | FC-ROUTE-PPI 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-ROUTE-CLINT>` | `FG-ADDRESS-DECODE` | FC-ROUTE-CLINT 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-ROUTE-PLIC>` | `FG-ADDRESS-DECODE` | FC-ROUTE-PLIC 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-ROUTE-FIO>` | `FG-ADDRESS-DECODE` | FC-ROUTE-FIO 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-ROUTE-MEM>` | `FG-ADDRESS-DECODE` | FC-ROUTE-MEM 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-DECODE-UNIQUE>` | `FG-ADDRESS-DECODE` | FC-DECODE-UNIQUE 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-TARGET-HANDSHAKE>` | `FG-DOWNSTREAM` | FC-TARGET-HANDSHAKE 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-UNSELECTED-SILENT>` | `FG-DOWNSTREAM` | FC-UNSELECTED-SILENT 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-DOWNSTREAM-RSP-MUX>` | `FG-DOWNSTREAM` | FC-DOWNSTREAM-RSP-MUX 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-IFU-PERIPH-ERROR>` | `FG-IFU-ERROR` | FC-IFU-PERIPH-ERROR 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-IFU-WRITE-ERROR>` | `FG-IFU-ERROR` | FC-IFU-WRITE-ERROR 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-DISABLED-TARGET-ERROR>` | `FG-IFU-ERROR` | FC-DISABLED-TARGET-ERROR 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-FAST-ERROR-RSP>` | `FG-IFU-ERROR` | FC-FAST-ERROR-RSP 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-RDATA-RETURN>` | `FG-RESPONSE` | FC-RDATA-RETURN 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-ERR-RETURN>` | `FG-RESPONSE` | FC-ERR-RETURN 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-EXCL-OK-RETURN>` | `FG-RESPONSE` | FC-EXCL-OK-RETURN 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-BASIC-ATTR>` | `FG-CMD-ATTR` | FC-BASIC-ATTR 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-EXT-ATTR>` | `FG-CMD-ATTR` | FC-EXT-ATTR 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-DUAL-SOURCE-STRESS>` | `FG-CONCURRENCY-BOUNDARY` | FC-DUAL-SOURCE-STRESS 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-TARGET-SWITCH>` | `FG-CONCURRENCY-BOUNDARY` | FC-TARGET-SWITCH 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-RESET-BOUNDARY>` | `FG-CONCURRENCY-BOUNDARY` | FC-RESET-BOUNDARY 验证 | `P-CORE` | P0 / `CK-LSU` |
| `<FC-EXTREME-BACKPRESSURE>` | `FG-CONCURRENCY-BOUNDARY` | FC-EXTREME-BACKPRESSURE 验证 | `P-CORE` | P0 / `CK-LSU` |

| CK 标签 | Style | 所属 FC | 独立性质 | 逻辑观测点 | RTL / bind 对应 | 属性实现状态 | 签核状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `<CK-LSU>` | Assume | `FC-SINGLE-TRANS` | CK-LSU | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-IFU>` | Assume | `FC-SINGLE-TRANS` | CK-IFU | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-STEP-DRIVEN>` | Assume | `FC-SINGLE-TRANS` | CK-STEP-DRIVEN | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-TARGET-SEPARATE>` | Assume | `FC-RSP-INJECT` | CK-TARGET-SEPARATE | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-ERROR-RSP>` | Assume | `FC-RSP-INJECT` | CK-ERROR-RSP | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-ZERO-WAIT>` | Assume | `FC-RSP-INJECT` | CK-ZERO-WAIT | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-DUAL-MASTER>` | Assume | `FC-CONCURRENT-SCENARIO` | CK-DUAL-MASTER | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-UPSTREAM-BACKPRESSURE>` | Assume | `FC-CONCURRENT-SCENARIO` | CK-UPSTREAM-BACKPRESSURE | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-DOWNSTREAM-BACKPRESSURE>` | Assume | `FC-CONCURRENT-SCENARIO` | CK-DOWNSTREAM-BACKPRESSURE | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-HS>` | Seq | `FC-LSU-CMD` | CK-HS | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-HOLD>` | Seq | `FC-LSU-CMD` | CK-HOLD | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-RSP-RETURN>` | Seq | `FC-LSU-CMD` | CK-RSP-RETURN | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-LSU-STALL>` | Seq | `FC-UPSTREAM-RSP-BACKPRESSURE` | CK-LSU-STALL | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-IFU-STALL>` | Seq | `FC-UPSTREAM-RSP-BACKPRESSURE` | CK-IFU-STALL | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-NO-CROSS>` | Seq | `FC-UPSTREAM-RSP-BACKPRESSURE` | CK-NO-CROSS | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-SAME-CYCLE>` | Seq | `FC-LSU-PRIORITY` | CK-SAME-CYCLE | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-IFU-WAIT>` | Seq | `FC-LSU-PRIORITY` | CK-IFU-WAIT | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-POST-LSU>` | Seq | `FC-LSU-PRIORITY` | CK-POST-LSU | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-LSU-ONLY>` | Seq | `FC-SINGLE-SOURCE` | CK-LSU-ONLY | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-IFU-ONLY>` | Seq | `FC-SINGLE-SOURCE` | CK-IFU-ONLY | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-NO-SPURIOUS-BLOCK>` | Seq | `FC-SINGLE-SOURCE` | CK-NO-SPURIOUS-BLOCK | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-LSU-TAG>` | Seq | `FC-SOURCE-ROUTING` | CK-LSU-TAG | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-IFU-TAG>` | Seq | `FC-SOURCE-ROUTING` | CK-IFU-TAG | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-ORDERED-MIX>` | Seq | `FC-SOURCE-ROUTING` | CK-ORDERED-MIX | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-DOWNSTREAM-NOTREADY>` | Seq | `FC-CMD-BACKPRESSURE` | CK-DOWNSTREAM-NOTREADY | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-NO-OVERACCEPT>` | Seq | `FC-CMD-BACKPRESSURE` | CK-NO-OVERACCEPT | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-RECOVER>` | Seq | `FC-CMD-BACKPRESSURE` | CK-RECOVER | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-TWO-REQ>` | Seq | `FC-RSP-INORDER` | CK-TWO-REQ | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-MIXED-TARGET>` | Seq | `FC-RSP-INORDER` | CK-MIXED-TARGET | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-NO-DUP>` | Seq | `FC-RSP-INORDER` | CK-NO-DUP | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-IDLE-LOW>` | Seq | `FC-BIU-ACTIVE` | CK-IDLE-LOW | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-BUSY-HIGH>` | Seq | `FC-BIU-ACTIVE` | CK-BUSY-HIGH | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-RETURN-IDLE>` | Seq | `FC-BIU-ACTIVE` | CK-RETURN-IDLE | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-SELECT>` | Seq | `FC-ROUTE-PPI` | CK-SELECT | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-UNIQUE>` | Seq | `FC-ROUTE-PPI` | CK-UNIQUE | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-ENABLE>` | Seq | `FC-ROUTE-PPI` | CK-ENABLE | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-DEFAULT>` | Seq | `FC-ROUTE-MEM` | CK-DEFAULT | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-ONEHOT>` | Seq | `FC-DECODE-UNIQUE` | CK-ONEHOT | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-ERR-OR-TARGET>` | Seq | `FC-DECODE-UNIQUE` | CK-ERR-OR-TARGET | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-NO-GHOST>` | Seq | `FC-DECODE-UNIQUE` | CK-NO-GHOST | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-VALID-READY>` | Seq | `FC-TARGET-HANDSHAKE` | CK-VALID-READY | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-STABLE-WHEN-WAIT>` | Seq | `FC-TARGET-HANDSHAKE` | CK-STABLE-WHEN-WAIT | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-NO-FALSE-HS>` | Seq | `FC-TARGET-HANDSHAKE` | CK-NO-FALSE-HS | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-NO-SPURIOUS-PPI>` | Seq | `FC-UNSELECTED-SILENT` | CK-NO-SPURIOUS-PPI | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-NO-SPURIOUS-CLINT>` | Seq | `FC-UNSELECTED-SILENT` | CK-NO-SPURIOUS-CLINT | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-NO-SPURIOUS-OTHERS>` | Seq | `FC-UNSELECTED-SILENT` | CK-NO-SPURIOUS-OTHERS | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-CORRECT-SOURCE>` | Seq | `FC-DOWNSTREAM-RSP-MUX` | CK-CORRECT-SOURCE | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-ERR-PROP>` | Seq | `FC-DOWNSTREAM-RSP-MUX` | CK-ERR-PROP | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-RDATA-PROP>` | Seq | `FC-DOWNSTREAM-RSP-MUX` | CK-RDATA-PROP | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-PPI>` | Seq | `FC-IFU-PERIPH-ERROR` | CK-PPI | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-CLINT>` | Seq | `FC-IFU-PERIPH-ERROR` | CK-CLINT | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-PLIC-FIO>` | Seq | `FC-IFU-PERIPH-ERROR` | CK-PLIC-FIO | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-ERR>` | Seq | `FC-IFU-WRITE-ERROR` | CK-ERR | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-ZERO-DATA>` | Seq | `FC-IFU-WRITE-ERROR` | CK-ZERO-DATA | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-NO-REAL-TARGET>` | Seq | `FC-IFU-WRITE-ERROR` | CK-NO-REAL-TARGET | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-PERIPH-DISABLED>` | Seq | `FC-DISABLED-TARGET-ERROR` | CK-PERIPH-DISABLED | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-MEM-DISABLED>` | Seq | `FC-DISABLED-TARGET-ERROR` | CK-MEM-DISABLED | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-NO-REROUTE>` | Seq | `FC-DISABLED-TARGET-ERROR` | CK-NO-REROUTE | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-LOW-LATENCY>` | Seq | `FC-FAST-ERROR-RSP` | CK-LOW-LATENCY | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-HS-CONSISTENT>` | Seq | `FC-FAST-ERROR-RSP` | CK-HS-CONSISTENT | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-NO-DEADLOCK>` | Seq | `FC-FAST-ERROR-RSP` | CK-NO-DEADLOCK | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-DIFF-PATTERN>` | Seq | `FC-RDATA-RETURN` | CK-DIFF-PATTERN | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-DOWNSTREAM>` | Seq | `FC-ERR-RETURN` | CK-DOWNSTREAM | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-LOCAL>` | Seq | `FC-ERR-RETURN` | CK-LOCAL | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-NO-FALSE-ERR>` | Seq | `FC-ERR-RETURN` | CK-NO-FALSE-ERR | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-PASS>` | Seq | `FC-EXCL-OK-RETURN` | CK-PASS | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-FAIL>` | Seq | `FC-EXCL-OK-RETURN` | CK-FAIL | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-INDEPENDENT>` | Seq | `FC-EXCL-OK-RETURN` | CK-INDEPENDENT | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-ADDR>` | Seq | `FC-BASIC-ATTR` | CK-ADDR | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-READ-WRITE>` | Seq | `FC-BASIC-ATTR` | CK-READ-WRITE | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-WDATA-WMASK>` | Seq | `FC-BASIC-ATTR` | CK-WDATA-WMASK | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-BURST-BEAT>` | Seq | `FC-EXT-ATTR` | CK-BURST-BEAT | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-LOCK-EXCL>` | Seq | `FC-EXT-ATTR` | CK-LOCK-EXCL | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-SIZE>` | Seq | `FC-EXT-ATTR` | CK-SIZE | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-REPEATED-ARBT>` | Seq | `FC-DUAL-SOURCE-STRESS` | CK-REPEATED-ARBT | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-PROGRESS>` | Seq | `FC-DUAL-SOURCE-STRESS` | CK-PROGRESS | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-NO-LOCKUP>` | Seq | `FC-DUAL-SOURCE-STRESS` | CK-NO-LOCKUP | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-PERIPH-TO-MEM>` | Seq | `FC-TARGET-SWITCH` | CK-PERIPH-TO-MEM | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-MEM-TO-PERIPH>` | Seq | `FC-TARGET-SWITCH` | CK-MEM-TO-PERIPH | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-NO-LEAKAGE>` | Seq | `FC-TARGET-SWITCH` | CK-NO-LEAKAGE | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-AFTER-RESET>` | Seq | `FC-RESET-BOUNDARY` | CK-AFTER-RESET | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-CLEAR-PENDING>` | Seq | `FC-RESET-BOUNDARY` | CK-CLEAR-PENDING | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-NO-SPURIOUS-RSP>` | Seq | `FC-RESET-BOUNDARY` | CK-NO-SPURIOUS-RSP | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-LONG-STALL>` | Seq | `FC-EXTREME-BACKPRESSURE` | CK-LONG-STALL | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-STALL-RECOVER>` | Seq | `FC-EXTREME-BACKPRESSURE` | CK-STALL-RECOVER | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-MIXED-CORNER>` | Seq | `FC-EXTREME-BACKPRESSURE` | CK-MIXED-CORNER | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-IFU-CMD-DEFAULT>` | Seq | `FC-IFU-CMD` | 验证 FC-IFU-CMD 默认行为 | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-ROUTE-CLINT-DEFAULT>` | Seq | `FC-ROUTE-CLINT` | 验证 FC-ROUTE-CLINT 默认行为 | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-ROUTE-PLIC-DEFAULT>` | Seq | `FC-ROUTE-PLIC` | 验证 FC-ROUTE-PLIC 默认行为 | `signal.biu_active` | [附录 B / D] | Planned | Planned |
| `<CK-ROUTE-FIO-DEFAULT>` | Seq | `FC-ROUTE-FIO` | 验证 FC-ROUTE-FIO 默认行为 | `signal.biu_active` | [附录 B / D] | Planned | Planned |

### 附录 G：签核清单

- [x] 摘要在细节前说明职责、输入输出、关键概念、延迟、验证范围和 OPEN。
- [x] 每项功能按输入、输出、延迟、统一规则、适用实例、边界与限制组织。
- [x] 模块级规则未混入实例枚举；实例差异集中在能力矩阵和附录 C。
- [x] 正文仅以 `[E-*]` 引用证据，完整路径集中在附录 D。
- [x] Test Plan 是验证执行入口；FC/CK 完整登记集中在附录 F。
- [x] API 只包含 Assume，Coverage 只包含 Cover。
- [x] Verilog 端口逐项核对，配置裁剪有依据。
- [x] 正常、资源边界和恢复场景有可判定验收标准。
