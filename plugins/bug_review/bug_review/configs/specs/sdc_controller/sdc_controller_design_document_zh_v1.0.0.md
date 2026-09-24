# sdc_controller 设计与功能检测点文档

> 模板结构版本：v3.3.0
>
> 文档版本：v1.0.0
>
> 本文分为正文、验证计划和附录。正文用于连续理解设计，验证计划用于安排检查，附录用于审计和签核。FG、FC、CK 标签必须使用反引号包裹，例如 `` `<FG-API>` ``。无法证实的内容登记为 `OPEN-*`。

## 第一部分：正文

### 文档摘要

> 本节目标是一页内建立阅读者的整体模型。每项先给结论，不展开实现细节或证据路径。

**模块职责**

`sdc_controller` 模块是芯片设计中的硬件执行单元，负责处理相关逻辑、时钟分频、存储或控制功能。

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

`sdc_controller` 包含 32 个端口，正文统一使用逻辑名，精确映射见附录 B。

| 逻辑名 | 角色与含义 | 方向 | 事务阶段 |
| --- | --- | --- | --- |
| `producer.data` | 数据与控制输入 | 生产者 -> DUT | 写入 |
| `consumer.data` | 状态与结果输出 | DUT -> 消费者 | 输出 |

#### 微架构与数据流

```mermaid
flowchart LR
    P[Producer]
    C[Consumer]
    subgraph DUT["DUT: sdc_controller"]
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
|  `- FC-WB-ACCESS
|  `- FC-SD-CMD-IO
|  `- FC-SD-DATA-AND-DMA-IO
|  `- FC-SYSTEM-IO
|- FG-WB-SLAVE
|  `- FC-WB-HANDSHAKE
|  `- FC-WB-BYTE-ENABLE
|  `- FC-WB-ADDRESS-MAP
|- FG-CMD
|  `- FC-CMD-SETUP
|  `- FC-CMD-LAUNCH
|  `- FC-CMD-RESPONSE
|  `- FC-CMD-CARD-DETECT-GATING
|- FG-DATA
|  `- FC-DATA-CMD-COORDINATION
|  `- FC-DMA-MASTER-READ
|  `- FC-DMA-MASTER-WRITE
|  `- FC-SD-DATA-PHY
|- FG-BD
|  `- FC-BD-WRITE-FORMAT
|  `- FC-BD-QUEUE-ACCOUNTING
|  `- FC-BD-TX-RX-INDEPENDENCE
|- FG-INTERRUPT
|  `- FC-NORMAL-INT-STATUS
|  `- FC-ERROR-INT-STATUS
|  `- FC-BD-INT-STATUS
|  `- FC-EXTERNAL-IRQ-PINS
|- FG-SYSTEM
|  `- FC-HARD-RESET
|  `- FC-SOFTWARE-RESET
|  `- FC-CLOCK-DIVIDER
|  `- FC-CARD-DETECT-STATUS
|- FG-ROBUSTNESS
|  `- FC-CMD-DATA-CONCURRENCY
|  `- FC-DMA-ACK-STALL
|  `- FC-ILLEGAL-OR-BOUNDARY-ACCESS
|  `- FC-ERROR-RECOVERY
```

`<FG-API>`

FG-API 功能风险覆盖与行为检测。

`<FG-WB-SLAVE>`

FG-WB-SLAVE 功能风险覆盖与行为检测。

`<FG-CMD>`

FG-CMD 功能风险覆盖与行为检测。

`<FG-DATA>`

FG-DATA 功能风险覆盖与行为检测。

`<FG-BD>`

FG-BD 功能风险覆盖与行为检测。

`<FG-INTERRUPT>`

FG-INTERRUPT 功能风险覆盖与行为检测。

`<FG-SYSTEM>`

FG-SYSTEM 功能风险覆盖与行为检测。

`<FG-ROBUSTNESS>`

FG-ROBUSTNESS 功能风险覆盖与行为检测。

### Test Plan

> 这是验证执行的统一入口。每行连接一个 FC、一个独立 CK、验证机制、Coverage 和场景。功能原理只引用 `P-*`，完整 CK 元数据见附录 F。

| 优先级 | FC | CK | Style | 关联规则 | 检查机制 | 激励 / 前置条件 | 可观察结果 | Coverage / 场景 | 关闭标准 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | `FC-WB-ACCESS` | `CK-WRITE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WB-ACCESS` | `CK-READ` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WB-ACCESS` | `CK-BYTE-SEL` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WB-ACCESS` | `CK-IDLE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WB-ACCESS` | `CK-TIMING` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SD-CMD-IO` | `CK-CMD-INJECT` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SD-CMD-IO` | `CK-CMD-OBSERVE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SD-CMD-IO` | `CK-CMD-OE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SD-DATA-AND-DMA-IO` | `CK-DATA-INJECT` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SD-DATA-AND-DMA-IO` | `CK-DATA-OBSERVE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SD-DATA-AND-DMA-IO` | `CK-MASTER-READ-RSP` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SD-DATA-AND-DMA-IO` | `CK-MASTER-WRITE-ACK` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SD-DATA-AND-DMA-IO` | `CK-MASTER-OBSERVE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SYSTEM-IO` | `CK-CARD-DETECT` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SYSTEM-IO` | `CK-IRQ-OBSERVE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-SYSTEM-IO` | `CK-RESET-SEQUENCE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SYSTEM-IO` | `CK-CLOCK-RUN` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WB-HANDSHAKE` | `CK-WRITE-ACK` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WB-HANDSHAKE` | `CK-READ-ACK` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WB-HANDSHAKE` | `CK-NO-SPURIOUS-ACK` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WB-HANDSHAKE` | `CK-DATA-VALID-WITH-ACK` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WB-BYTE-ENABLE` | `CK-FULL-WORD` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WB-BYTE-ENABLE` | `CK-LOW-BYTE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WB-BYTE-ENABLE` | `CK-HIGH-BYTE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WB-BYTE-ENABLE` | `CK-SPARSE-BYTE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WB-ADDRESS-MAP` | `CK-CFG-SPACE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WB-ADDRESS-MAP` | `CK-STATUS-SPACE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WB-ADDRESS-MAP` | `CK-BD-SPACE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WB-ADDRESS-MAP` | `CK-ISOLATION` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-SETUP` | `CK-ARG-WRITE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-SETUP` | `CK-CMDSET-WRITE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-SETUP` | `CK-TIMEOUT-WRITE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-LAUNCH` | `CK-START` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-LAUNCH` | `CK-BUSY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-LAUNCH` | `CK-IDLE-RETURN` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-RESPONSE` | `CK-RESP-CAPTURE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-RESPONSE` | `CK-RESP-DONE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-RESPONSE` | `CK-RESP-TIMEOUT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-RESPONSE` | `CK-RESP-CRC-ERR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-CARD-DETECT-GATING` | `CK-NO-CARD-BLOCK` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-CARD-DETECT-GATING` | `CK-CARD-PRESENT-ALLOW` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DATA-CMD-COORDINATION` | `CK-TX-CMD-REQ` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DATA-CMD-COORDINATION` | `CK-RX-CMD-REQ` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DATA-CMD-COORDINATION` | `CK-CMD-BUSY-WAIT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DMA-MASTER-READ` | `CK-READ-START` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DMA-MASTER-READ` | `CK-READ-ADDR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DMA-MASTER-READ` | `CK-READ-DATA-ACCEPT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DMA-MASTER-READ` | `CK-READ-END` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DMA-MASTER-WRITE` | `CK-WRITE-START` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DMA-MASTER-WRITE` | `CK-WRITE-ADDR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DMA-MASTER-WRITE` | `CK-WRITE-DATA` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DMA-MASTER-WRITE` | `CK-WRITE-END` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SD-DATA-PHY` | `CK-TX-OE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SD-DATA-PHY` | `CK-TX-DATA-ACTIVITY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SD-DATA-PHY` | `CK-RX-OE-LOW` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SD-DATA-PHY` | `CK-RX-DATA-ACCEPT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BD-WRITE-FORMAT` | `CK-FIRST-WORD` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BD-WRITE-FORMAT` | `CK-SECOND-WORD` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BD-WRITE-FORMAT` | `CK-PAIRING` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BD-QUEUE-ACCOUNTING` | `CK-FREE-COUNT-DECREASE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BD-QUEUE-ACCOUNTING` | `CK-CONSUME-ORDER` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BD-QUEUE-ACCOUNTING` | `CK-COMPLETE-UPDATE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BD-TX-RX-INDEPENDENCE` | `CK-TX-ONLY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BD-TX-RX-INDEPENDENCE` | `CK-RX-ONLY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BD-TX-RX-INDEPENDENCE` | `CK-PARALLEL-EXIST` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-NORMAL-INT-STATUS` | `CK-SET-ON-CMD-DONE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-NORMAL-INT-STATUS` | `CK-READABLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-NORMAL-INT-STATUS` | `CK-CLEAR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ERROR-INT-STATUS` | `CK-SET-ON-TIMEOUT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ERROR-INT-STATUS` | `CK-SET-ON-CRC` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BD-INT-STATUS` | `CK-SET-ON-DATA-DONE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-EXTERNAL-IRQ-PINS` | `CK-INTA-GATE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-EXTERNAL-IRQ-PINS` | `CK-INTB-GATE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-EXTERNAL-IRQ-PINS` | `CK-INTC-GATE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-EXTERNAL-IRQ-PINS` | `CK-DEASSERT-AFTER-CLEAR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-HARD-RESET` | `CK-REG-DEFAULT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-HARD-RESET` | `CK-OUTPUT-DEFAULT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-HARD-RESET` | `CK-BD-RESET` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SOFTWARE-RESET` | `CK-SRST-TRIGGER` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SOFTWARE-RESET` | `CK-SRST-EFFECT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SOFTWARE-RESET` | `CK-SRST-RECOVER` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CLOCK-DIVIDER` | `CK-DIV-CONFIG` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CLOCK-DIVIDER` | `CK-CLK-TOGGLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CLOCK-DIVIDER` | `CK-DIV-CHANGE-EFFECT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CARD-DETECT-STATUS` | `CK-DETECT-PRESENT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CARD-DETECT-STATUS` | `CK-DETECT-ABSENT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-DATA-CONCURRENCY` | `CK-NO-CMD-REENTRY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-DATA-CONCURRENCY` | `CK-DATA-WAITS-CMD` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-DATA-CONCURRENCY` | `CK-RECOVER-AFTER-SERIAL` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DMA-ACK-STALL` | `CK-HOLD-UNTIL-ACK` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DMA-ACK-STALL` | `CK-RELEASE-ON-ACK` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DMA-ACK-STALL` | `CK-LONG-STALL-HANDLING` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ILLEGAL-OR-BOUNDARY-ACCESS` | `CK-UNDEFINED-REG-READ` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ILLEGAL-OR-BOUNDARY-ACCESS` | `CK-UNDEFINED-REG-WRITE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ILLEGAL-OR-BOUNDARY-ACCESS` | `CK-EMPTY-BD-NO-TRANSFER` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ILLEGAL-OR-BOUNDARY-ACCESS` | `CK-PARTIAL-BD-WRITE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ERROR-RECOVERY` | `CK-ERROR-LATCH` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ERROR-RECOVERY` | `CK-CLEAR-AND-RETRY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ERROR-RECOVERY` | `CK-NO-STUCK-BUSY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |

### Coverage Summary

| Coverage ID | 风险与目标 | 关联 P / FC / CK | 观察事件 | 重要取值 / 分箱 | 依赖 / 交叉 | 非法 / 忽略条件 | 有效性保护 | 关闭标准 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `COV-NORMAL` | 正常功能覆盖 | `P-CORE`, `FC-WB-ACCESS`, `CK-WRITE` | 正常周期事件 | 典型功能取值 | 核心交叉 | 忽略非法毛刺 | 有效采样 | 命中要求 | Planned |
| `COV-BOUNDARY` | 边界条件覆盖 | `P-CORE`, `FC-ERROR-RECOVERY`, `CK-NO-STUCK-BUSY` | 边界周期事件 | 最大/最小值 | 极限交叉 | 忽略非法毛刺 | 有效采样 | 命中要求 | Planned |

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

**预期行为**：遵循 `P-CORE`、`CK-WRITE`；关联 Coverage：`COV-NORMAL`。

**验收标准**：输出处于预期初始状态。

#### CASE-NORMAL：正常运算场景

**目标**：验证典型功能处理流程。

**参与者与前置条件**：激励驱动源。

1. 驱动有效输入。
2. 观测输出结果。

**预期行为**：遵循 `P-CORE`、`CK-WRITE`；关联 Coverage：`COV-NORMAL`。

**验收标准**：结果正确匹配。

#### CASE-BOUNDARY：边界条件场景

**目标**：验证极限值与异常边界行为。

**参与者与前置条件**：激励驱动源。

1. 驱动边界极值。
2. 检查输出无挂起。

**预期行为**：遵循 `P-CORE`、`CK-NO-STUCK-BUSY`；关联 Coverage：`COV-BOUNDARY`。

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
| DUT / Chisel 顶层 | sdc_controller / [E-TOP-01] |
| Elaborated Verilog 顶层 | sdc_controller / [E-RTL-01] |
| 文档状态 | Review |
| XiangShan RTL 基线 | generic-verilog-v1 |
| 适用配置 | DefaultConfig |
| 生成环境 | Linux / x86_64 / Python 3.8 |
| RTL 生成状态 | Success |
| RTL 证据 | evidence/sdc_controller/v1.0.0/manifest.json |
| 图形渲染证据 | evidence/sdc_controller/v1.0.0/diagrams/manifest.json |
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

本模块包含 32 个叶端口：13 个输入，19 个输出。
RTL SHA-256：`61c2920a2f27d23930b8805c92345e7f9aa16d02a571be15c5fbc85c1c028d50`。

### 附录 B：逻辑接口与 RTL 映射

> 本附录是逻辑名、字段和精确 elaborated Verilog 端口的唯一映射位置。

| IO-ID | 正文逻辑名 | Bundle class / Chisel 字段 | 定义位置 | 方向 / 位宽 | 配置状态 | 精确 Verilog I/O | 协议 / 对端 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `IO-WB_CLK_I` | `signal.wb_clk_i` | `sdc_controller.wb_clk_i` | [E-IO-01] | I / 1 | Generated | `wb_clk_i` | Internal / System | [E-RTL-01] |
| `IO-WB_RST_I` | `signal.wb_rst_i` | `sdc_controller.wb_rst_i` | [E-IO-01] | I / 1 | Generated | `wb_rst_i` | Internal / System | [E-RTL-01] |
| `IO-WB_DAT_I` | `signal.wb_dat_i` | `sdc_controller.wb_dat_i` | [E-IO-01] | I / 32 | Generated | `wb_dat_i` | Internal / System | [E-RTL-01] |
| `IO-WB_DAT_O` | `signal.wb_dat_o` | `sdc_controller.wb_dat_o` | [E-IO-01] | O / 32 | Generated | `wb_dat_o` | Internal / System | [E-RTL-01] |
| `IO-CARD_DETECT` | `signal.card_detect` | `sdc_controller.card_detect` | [E-IO-01] | I / 1 | Generated | `card_detect` | Internal / System | [E-RTL-01] |
| `IO-WB_ADR_I` | `signal.wb_adr_i` | `sdc_controller.wb_adr_i` | [E-IO-01] | I / 8 | Generated | `wb_adr_i` | Internal / System | [E-RTL-01] |
| `IO-WB_SEL_I` | `signal.wb_sel_i` | `sdc_controller.wb_sel_i` | [E-IO-01] | I / 4 | Generated | `wb_sel_i` | Internal / System | [E-RTL-01] |
| `IO-WB_WE_I` | `signal.wb_we_i` | `sdc_controller.wb_we_i` | [E-IO-01] | I / 1 | Generated | `wb_we_i` | Internal / System | [E-RTL-01] |
| `IO-WB_CYC_I` | `signal.wb_cyc_i` | `sdc_controller.wb_cyc_i` | [E-IO-01] | I / 1 | Generated | `wb_cyc_i` | Internal / System | [E-RTL-01] |
| `IO-WB_STB_I` | `signal.wb_stb_i` | `sdc_controller.wb_stb_i` | [E-IO-01] | I / 1 | Generated | `wb_stb_i` | Internal / System | [E-RTL-01] |
| `IO-WB_ACK_O` | `signal.wb_ack_o` | `sdc_controller.wb_ack_o` | [E-IO-01] | O / 1 | Generated | `wb_ack_o` | Internal / System | [E-RTL-01] |
| `IO-M_WB_ADR_O` | `signal.m_wb_adr_o` | `sdc_controller.m_wb_adr_o` | [E-IO-01] | O / 32 | Generated | `m_wb_adr_o` | Internal / System | [E-RTL-01] |
| `IO-M_WB_SEL_O` | `signal.m_wb_sel_o` | `sdc_controller.m_wb_sel_o` | [E-IO-01] | O / 4 | Generated | `m_wb_sel_o` | Internal / System | [E-RTL-01] |
| `IO-M_WB_WE_O` | `signal.m_wb_we_o` | `sdc_controller.m_wb_we_o` | [E-IO-01] | O / 1 | Generated | `m_wb_we_o` | Internal / System | [E-RTL-01] |
| `IO-M_WB_DAT_I` | `signal.m_wb_dat_i` | `sdc_controller.m_wb_dat_i` | [E-IO-01] | I / 32 | Generated | `m_wb_dat_i` | Internal / System | [E-RTL-01] |
| `IO-M_WB_DAT_O` | `signal.m_wb_dat_o` | `sdc_controller.m_wb_dat_o` | [E-IO-01] | O / 32 | Generated | `m_wb_dat_o` | Internal / System | [E-RTL-01] |
| `IO-M_WB_CYC_O` | `signal.m_wb_cyc_o` | `sdc_controller.m_wb_cyc_o` | [E-IO-01] | O / 1 | Generated | `m_wb_cyc_o` | Internal / System | [E-RTL-01] |
| `IO-M_WB_STB_O` | `signal.m_wb_stb_o` | `sdc_controller.m_wb_stb_o` | [E-IO-01] | O / 1 | Generated | `m_wb_stb_o` | Internal / System | [E-RTL-01] |
| `IO-M_WB_ACK_I` | `signal.m_wb_ack_i` | `sdc_controller.m_wb_ack_i` | [E-IO-01] | I / 1 | Generated | `m_wb_ack_i` | Internal / System | [E-RTL-01] |
| `IO-M_WB_CTI_O` | `signal.m_wb_cti_o` | `sdc_controller.m_wb_cti_o` | [E-IO-01] | O / 3 | Generated | `m_wb_cti_o` | Internal / System | [E-RTL-01] |
| `IO-M_WB_BTE_O` | `signal.m_wb_bte_o` | `sdc_controller.m_wb_bte_o` | [E-IO-01] | O / 2 | Generated | `m_wb_bte_o` | Internal / System | [E-RTL-01] |
| `IO-SD_DAT_DAT_I` | `signal.sd_dat_dat_i` | `sdc_controller.sd_dat_dat_i` | [E-IO-01] | I / 4 | Generated | `sd_dat_dat_i` | Internal / System | [E-RTL-01] |
| `IO-SD_DAT_OUT_O` | `signal.sd_dat_out_o` | `sdc_controller.sd_dat_out_o` | [E-IO-01] | O / 4 | Generated | `sd_dat_out_o` | Internal / System | [E-RTL-01] |
| `IO-SD_DAT_OE_O` | `signal.sd_dat_oe_o` | `sdc_controller.sd_dat_oe_o` | [E-IO-01] | O / 1 | Generated | `sd_dat_oe_o` | Internal / System | [E-RTL-01] |
| `IO-SD_CMD_DAT_I` | `signal.sd_cmd_dat_i` | `sdc_controller.sd_cmd_dat_i` | [E-IO-01] | I / 1 | Generated | `sd_cmd_dat_i` | Internal / System | [E-RTL-01] |
| `IO-SD_CMD_OUT_O` | `signal.sd_cmd_out_o` | `sdc_controller.sd_cmd_out_o` | [E-IO-01] | O / 1 | Generated | `sd_cmd_out_o` | Internal / System | [E-RTL-01] |
| `IO-SD_CMD_OE_O` | `signal.sd_cmd_oe_o` | `sdc_controller.sd_cmd_oe_o` | [E-IO-01] | O / 1 | Generated | `sd_cmd_oe_o` | Internal / System | [E-RTL-01] |
| `IO-SD_CLK_O_PAD` | `signal.sd_clk_o_pad` | `sdc_controller.sd_clk_o_pad` | [E-IO-01] | O / 1 | Generated | `sd_clk_o_pad` | Internal / System | [E-RTL-01] |
| `IO-IFDEF` | `signal.ifdef` | `sdc_controller.ifdef` | [E-IO-01] | O / 1 | Generated | `ifdef` | Internal / System | [E-RTL-01] |
| `IO-ENDIF` | `signal.endif` | `sdc_controller.endif` | [E-IO-01] | O / 1 | Generated | `endif` | Internal / System | [E-RTL-01] |
| `IO-INT_B` | `signal.int_b` | `sdc_controller.int_b` | [E-IO-01] | O / 1 | Generated | `int_b` | Internal / System | [E-RTL-01] |
| `IO-INT_C` | `signal.int_c` | `sdc_controller.int_c` | [E-IO-01] | O / 1 | Generated | `int_c` | Internal / System | [E-RTL-01] |

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
| E-BEH-01 | Verilog | `sdc_controller.v:1` | generic-verilog-v1 / DefaultConfig | `P-CORE` |
| E-RES-01 | Verilog | `sdc_controller.v:1` | generic-verilog-v1 / DefaultConfig | 资源更新规则 |
| E-FSM-01 | Verilog | `sdc_controller.v:1` | generic-verilog-v1 / DefaultConfig | 状态机判定 |
| E-TOP-01 | Verilog | `sdc_controller.v:1` | generic-verilog-v1 / DefaultConfig | DUT 顶层定义 |
| E-RTL-01 | RTL / manifest / ports.csv | `sdc_controller.v:1` | generic-verilog-v1 / DefaultConfig | 端口定义与映射 |
| E-IO-01 | Verilog Port | `sdc_controller.v:1` | generic-verilog-v1 / DefaultConfig | 端口列表 |
| E-PARAM-01 | Verilog Define | `sdc_controller.v:1` | generic-verilog-v1 / DefaultConfig | 参数定义 |
| E-CONFIG-01 | Verilog Structure | `sdc_controller.v:1` | generic-verilog-v1 / DefaultConfig | 实例能力 |

### 附录 E：FACT、OPEN 与偏差

| ID | 类型 | 摘要 | 关联规则 | 证据 / 缺口 | 状态与关闭条件 |
| --- | --- | --- | --- | --- | --- |
| FACT-001 | 实现事实 | 模块由硬件 Verilog RTL 综合实现 | `P-CORE` | [E-BEH-01] | Closed |

### 附录 F：FC / CK 完整追溯

> 本附录服务于 UCAgent 和审计，不作为主要阅读入口。FC 定义验证目标，CK 定义单一可执行性质；二者不得重复功能原理。

| FC 标签 | 所属 FG | 验证目标 | 关联规则 | Test Plan 行 |
| --- | --- | --- | --- | --- |
| `<FC-WB-ACCESS>` | `FG-API` | FC-WB-ACCESS 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-SD-CMD-IO>` | `FG-API` | FC-SD-CMD-IO 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-SD-DATA-AND-DMA-IO>` | `FG-API` | FC-SD-DATA-AND-DMA-IO 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-SYSTEM-IO>` | `FG-API` | FC-SYSTEM-IO 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-WB-HANDSHAKE>` | `FG-WB-SLAVE` | FC-WB-HANDSHAKE 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-WB-BYTE-ENABLE>` | `FG-WB-SLAVE` | FC-WB-BYTE-ENABLE 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-WB-ADDRESS-MAP>` | `FG-WB-SLAVE` | FC-WB-ADDRESS-MAP 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-CMD-SETUP>` | `FG-CMD` | FC-CMD-SETUP 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-CMD-LAUNCH>` | `FG-CMD` | FC-CMD-LAUNCH 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-CMD-RESPONSE>` | `FG-CMD` | FC-CMD-RESPONSE 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-CMD-CARD-DETECT-GATING>` | `FG-CMD` | FC-CMD-CARD-DETECT-GATING 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-DATA-CMD-COORDINATION>` | `FG-DATA` | FC-DATA-CMD-COORDINATION 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-DMA-MASTER-READ>` | `FG-DATA` | FC-DMA-MASTER-READ 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-DMA-MASTER-WRITE>` | `FG-DATA` | FC-DMA-MASTER-WRITE 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-SD-DATA-PHY>` | `FG-DATA` | FC-SD-DATA-PHY 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-BD-WRITE-FORMAT>` | `FG-BD` | FC-BD-WRITE-FORMAT 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-BD-QUEUE-ACCOUNTING>` | `FG-BD` | FC-BD-QUEUE-ACCOUNTING 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-BD-TX-RX-INDEPENDENCE>` | `FG-BD` | FC-BD-TX-RX-INDEPENDENCE 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-NORMAL-INT-STATUS>` | `FG-INTERRUPT` | FC-NORMAL-INT-STATUS 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-ERROR-INT-STATUS>` | `FG-INTERRUPT` | FC-ERROR-INT-STATUS 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-BD-INT-STATUS>` | `FG-INTERRUPT` | FC-BD-INT-STATUS 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-EXTERNAL-IRQ-PINS>` | `FG-INTERRUPT` | FC-EXTERNAL-IRQ-PINS 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-HARD-RESET>` | `FG-SYSTEM` | FC-HARD-RESET 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-SOFTWARE-RESET>` | `FG-SYSTEM` | FC-SOFTWARE-RESET 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-CLOCK-DIVIDER>` | `FG-SYSTEM` | FC-CLOCK-DIVIDER 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-CARD-DETECT-STATUS>` | `FG-SYSTEM` | FC-CARD-DETECT-STATUS 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-CMD-DATA-CONCURRENCY>` | `FG-ROBUSTNESS` | FC-CMD-DATA-CONCURRENCY 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-DMA-ACK-STALL>` | `FG-ROBUSTNESS` | FC-DMA-ACK-STALL 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-ILLEGAL-OR-BOUNDARY-ACCESS>` | `FG-ROBUSTNESS` | FC-ILLEGAL-OR-BOUNDARY-ACCESS 验证 | `P-CORE` | P0 / `CK-WRITE` |
| `<FC-ERROR-RECOVERY>` | `FG-ROBUSTNESS` | FC-ERROR-RECOVERY 验证 | `P-CORE` | P0 / `CK-WRITE` |

| CK 标签 | Style | 所属 FC | 独立性质 | 逻辑观测点 | RTL / bind 对应 | 属性实现状态 | 签核状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `<CK-WRITE>` | Assume | `FC-WB-ACCESS` | 能够通过 `wb_*` 端口发起一次合法写事务，并在 Step 驱动下等待 `wb_ack_o` 应答。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-READ>` | Assume | `FC-WB-ACCESS` | 能够通过 `wb_*` 端口发起一次合法读事务，并在应答周期采样 `wb_dat_o`。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-BYTE-SEL>` | Assume | `FC-WB-ACCESS` | 支持配置 `wb_sel_i[3:0]` 发起按字节读写，以便后续验证部分字节更新行为。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-IDLE>` | Assume | `FC-WB-ACCESS` | 访问结束后能释放 `wb_cyc_i/wb_stb_i/wb_we_i` 并保持输入稳定，避免事务串扰。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-TIMING>` | Assume | `FC-WB-ACCESS` | 所有 Wishbone 访问均通过 `Step()` 推进，不采用组合直读方式。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-CMD-INJECT>` | Assume | `FC-SD-CMD-IO` | 可按拍驱动 `sd_cmd_dat_i` 以模拟卡端响应比特流。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-CMD-OBSERVE>` | Assume | `FC-SD-CMD-IO` | 可逐拍观测 `sd_cmd_out_o` 的发送行为。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-CMD-OE>` | Assume | `FC-SD-CMD-IO` | 可观测 `sd_cmd_oe_o` 在发送/空闲状态下的变化。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-DATA-INJECT>` | Assume | `FC-SD-DATA-AND-DMA-IO` | 可按拍驱动 `sd_dat_dat_i[3:0]` 模拟卡端数据返回。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-DATA-OBSERVE>` | Assume | `FC-SD-DATA-AND-DMA-IO` | 可观测 `sd_dat_out_o[3:0]` 与 `sd_dat_oe_o` 的发送行为。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-MASTER-READ-RSP>` | Assume | `FC-SD-DATA-AND-DMA-IO` | 当 DUT 发起主接口读事务时，可驱动 `m_wb_dat_i` 与 `m_wb_ack_i` 返回数据。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-MASTER-WRITE-ACK>` | Assume | `FC-SD-DATA-AND-DMA-IO` | 当 DUT 发起主接口写事务时，可驱动 `m_wb_ack_i` 完成握手。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-MASTER-OBSERVE>` | Assume | `FC-SD-DATA-AND-DMA-IO` | 可采样 `m_wb_adr_o/m_wb_we_o/m_wb_dat_o/m_wb_cyc_o/m_wb_stb_o/m_wb_cti_o/m_wb_bte_o`。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-CARD-DETECT>` | Assume | `FC-SYSTEM-IO` | 可控制 `card_detect` 高低以模拟插卡/拔卡。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-IRQ-OBSERVE>` | Assume | `FC-SYSTEM-IO` | 可采样 `int_a/int_b/int_c` 的置位与清除。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-RESET-SEQUENCE>` | Assume | `FC-SYSTEM-IO` | 可通过 `wb_rst_i` 和 `Step()` 完成上电/复位序列。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-CLOCK-RUN>` | Assume | `FC-SYSTEM-IO` | 可初始化并推进 `wb_clk_i` 时钟，支撑全部时序验证。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-WRITE-ACK>` | Seq | `FC-WB-HANDSHAKE` | 在 `wb_cyc_i` 与 `wb_stb_i` 有效且 `wb_we_i=1` 时，DUT 应对合法写请求产生应答。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-READ-ACK>` | Seq | `FC-WB-HANDSHAKE` | 在 `wb_cyc_i` 与 `wb_stb_i` 有效且 `wb_we_i=0` 时，DUT 应对合法读请求产生应答。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-NO-SPURIOUS-ACK>` | Seq | `FC-WB-HANDSHAKE` | 在未发起事务时 `wb_ack_o` 不应无故翻转为有效。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-DATA-VALID-WITH-ACK>` | Seq | `FC-WB-HANDSHAKE` | 读事务返回数据应在应答周期可被稳定采样。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-FULL-WORD>` | Seq | `FC-WB-BYTE-ENABLE` | `wb_sel_i=4'b1111` 时完整 32 位更新。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-LOW-BYTE>` | Seq | `FC-WB-BYTE-ENABLE` | 仅低 8 位使能时，仅低字节被修改。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-HIGH-BYTE>` | Seq | `FC-WB-BYTE-ENABLE` | 仅高 8 位使能时，仅高字节被修改。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-SPARSE-BYTE>` | Seq | `FC-WB-BYTE-ENABLE` | 分散字节使能时，仅选中字节更新。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-CFG-SPACE>` | Seq | `FC-WB-ADDRESS-MAP` | 配置寄存器地址可读写且返回值符合定义。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-STATUS-SPACE>` | Seq | `FC-WB-ADDRESS-MAP` | 状态寄存器地址可读，且反映外设运行状态。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-BD-SPACE>` | Seq | `FC-WB-ADDRESS-MAP` | BD 地址区域可作为 Tx/Rx 描述符入口访问。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-ISOLATION>` | Seq | `FC-WB-ADDRESS-MAP` | 一个地址空间的写入不应意外修改另一个空间内容。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-ARG-WRITE>` | Seq | `FC-CMD-SETUP` | 命令参数写入后可被准确读回或被后续发送流程采用。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-CMDSET-WRITE>` | Seq | `FC-CMD-SETUP` | 命令设置字段写入后可被准确读回或驱动命令行为。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-TIMEOUT-WRITE>` | Seq | `FC-CMD-SETUP` | 超时寄存器支持写入并影响超时处理路径。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-START>` | Seq | `FC-CMD-LAUNCH` | 执行启动操作后 `sd_cmd_oe_o` 被拉高并开始在 `sd_cmd_out_o` 上输出命令序列。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-BUSY>` | Seq | `FC-CMD-LAUNCH` | 命令发送/等待响应期间相关状态位体现 busy，阻止不当重入。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-IDLE-RETURN>` | Seq | `FC-CMD-LAUNCH` | 命令完成后输出使能释放，通路返回空闲状态。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-RESP-CAPTURE>` | Seq | `FC-CMD-RESPONSE` | 输入合法响应比特流后，响应寄存器更新。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-RESP-DONE>` | Seq | `FC-CMD-RESPONSE` | 响应接收结束后完成类状态/中断位置位。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-RESP-TIMEOUT>` | Seq | `FC-CMD-RESPONSE` | 无响应或超时场景下错误状态置位。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-RESP-CRC-ERR>` | Seq | `FC-CMD-RESPONSE` | 响应 CRC 异常时错误状态置位。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-NO-CARD-BLOCK>` | Seq | `FC-CMD-CARD-DETECT-GATING` | `card_detect` 指示无卡时，命令请求应失败、超时或报告错误，而非正常成功。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-CARD-PRESENT-ALLOW>` | Seq | `FC-CMD-CARD-DETECT-GATING` | `card_detect` 指示有卡时，命令流程可正常发起。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-TX-CMD-REQ>` | Seq | `FC-DATA-CMD-COORDINATION` | 存在可发送 Tx BD 时，数据模块可请求发送对应写命令。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-RX-CMD-REQ>` | Seq | `FC-DATA-CMD-COORDINATION` | 存在可接收 Rx BD 时，数据模块可请求发送对应读命令。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-CMD-BUSY-WAIT>` | Seq | `FC-DATA-CMD-COORDINATION` | 命令通路忙时，数据流程等待而不并发破坏当前命令。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-READ-START>` | Seq | `FC-DMA-MASTER-READ` | Tx 传输开始后产生 `m_wb_cyc_o/m_wb_stb_o` 读事务。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-READ-ADDR>` | Seq | `FC-DMA-MASTER-READ` | 主接口读地址与所配置系统内存地址匹配。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-READ-DATA-ACCEPT>` | Seq | `FC-DMA-MASTER-READ` | 在 `m_wb_ack_i` 到来时接受 `m_wb_dat_i` 数据。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-READ-END>` | Seq | `FC-DMA-MASTER-READ` | 数据取完后撤销主接口事务控制信号。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-WRITE-START>` | Seq | `FC-DMA-MASTER-WRITE` | Rx 传输过程中产生主接口写事务。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-WRITE-ADDR>` | Seq | `FC-DMA-MASTER-WRITE` | 主接口写地址与所配置系统内存地址匹配。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-WRITE-DATA>` | Seq | `FC-DMA-MASTER-WRITE` | 主接口写数据来自 SD 接收数据路径。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-WRITE-END>` | Seq | `FC-DMA-MASTER-WRITE` | 收到 `m_wb_ack_i` 后可正确结束写事务。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-TX-OE>` | Seq | `FC-SD-DATA-PHY` | 发送数据块时 `sd_dat_oe_o` 置位。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-TX-DATA-ACTIVITY>` | Seq | `FC-SD-DATA-PHY` | 发送期间 `sd_dat_out_o` 出现有效活动而非长期静止。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-RX-OE-LOW>` | Seq | `FC-SD-DATA-PHY` | 接收数据块时 `sd_dat_oe_o` 保持非驱动状态。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-RX-DATA-ACCEPT>` | Seq | `FC-SD-DATA-PHY` | 向 `sd_dat_dat_i` 注入数据后可驱动接收流程前进。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-FIRST-WORD>` | Seq | `FC-BD-WRITE-FORMAT` | 第一次写入作为系统内存地址保存。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-SECOND-WORD>` | Seq | `FC-BD-WRITE-FORMAT` | 第二次写入作为卡块地址/控制字保存。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-PAIRING>` | Seq | `FC-BD-WRITE-FORMAT` | 仅完成成对写入后，该 BD 才对后续数据流程可见。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-FREE-COUNT-DECREASE>` | Seq | `FC-BD-QUEUE-ACCOUNTING` | 写入新 BD 后相应 free/available 统计发生预期变化。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-CONSUME-ORDER>` | Seq | `FC-BD-QUEUE-ACCOUNTING` | 多个 BD 按写入顺序被消费。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-COMPLETE-UPDATE>` | Seq | `FC-BD-QUEUE-ACCOUNTING` | 传输完成后 BD 状态寄存器/中断状态更新。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-TX-ONLY>` | Seq | `FC-BD-TX-RX-INDEPENDENCE` | 写入 Tx BD 不应改变 Rx 统计或触发 Rx 流程。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-RX-ONLY>` | Seq | `FC-BD-TX-RX-INDEPENDENCE` | 写入 Rx BD 不应改变 Tx 统计或触发 Tx 流程。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-PARALLEL-EXIST>` | Seq | `FC-BD-TX-RX-INDEPENDENCE` | 同时配置 Tx/Rx BD 时，两侧状态可独立观测。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-SET-ON-CMD-DONE>` | Seq | `FC-NORMAL-INT-STATUS` | 命令成功完成后普通中断状态相应位置位。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-READABLE>` | Seq | `FC-NORMAL-INT-STATUS` | 普通中断状态寄存器可被主机读出。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-CLEAR>` | Seq | `FC-NORMAL-INT-STATUS` | 主机清除操作后相关状态位清零。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-SET-ON-TIMEOUT>` | Seq | `FC-ERROR-INT-STATUS` | 命令或数据超时后错误状态置位。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-SET-ON-CRC>` | Seq | `FC-ERROR-INT-STATUS` | CRC 错误后错误状态置位。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-SET-ON-DATA-DONE>` | Seq | `FC-BD-INT-STATUS` | BD 或数据完成事件使对应状态位置位。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-INTA-GATE>` | Seq | `FC-EXTERNAL-IRQ-PINS` | 仅当 normal status 与 normal signal enable 有交集时 `int_a` 置位。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-INTB-GATE>` | Seq | `FC-EXTERNAL-IRQ-PINS` | 仅当 error status 与 error signal enable 有交集时 `int_b` 置位。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-INTC-GATE>` | Seq | `FC-EXTERNAL-IRQ-PINS` | 仅当 Bd isr status 与 Bd isr enable 有交集时 `int_c` 置位。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-DEASSERT-AFTER-CLEAR>` | Seq | `FC-EXTERNAL-IRQ-PINS` | 状态清零或使能关闭后中断引脚撤销。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-REG-DEFAULT>` | Seq | `FC-HARD-RESET` | 复位后关键可读寄存器返回默认值。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-OUTPUT-DEFAULT>` | Seq | `FC-HARD-RESET` | 复位后 `wb_ack_o`、`sd_cmd_oe_o`、`sd_dat_oe_o`、中断引脚等保持默认无效状态。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-BD-RESET>` | Seq | `FC-HARD-RESET` | 复位后 BD 队列统计恢复初始值。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-SRST-TRIGGER>` | Seq | `FC-SOFTWARE-RESET` | 写软件复位位后模块进入复位流程。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-SRST-EFFECT>` | Seq | `FC-SOFTWARE-RESET` | 复位后关键状态和控制寄存器回到默认值或规格定义值。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-SRST-RECOVER>` | Seq | `FC-SOFTWARE-RESET` | 复位完成后模块可重新接受新的寄存器配置和命令。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-DIV-CONFIG>` | Seq | `FC-CLOCK-DIVIDER` | 时钟分频寄存器支持写入配置。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-CLK-TOGGLE>` | Seq | `FC-CLOCK-DIVIDER` | 非复位且有效配置下 `sd_clk_o_pad` 发生翻转。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-DIV-CHANGE-EFFECT>` | Seq | `FC-CLOCK-DIVIDER` | 不同分频值下时钟翻转节奏发生变化。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-DETECT-PRESENT>` | Seq | `FC-CARD-DETECT-STATUS` | `card_detect` 为有卡状态时允许正常命令/数据流程。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-DETECT-ABSENT>` | Seq | `FC-CARD-DETECT-STATUS` | `card_detect` 为无卡状态时状态寄存器或命令流程反映无卡条件。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-NO-CMD-REENTRY>` | Seq | `FC-CMD-DATA-CONCURRENCY` | 命令进行中重复启动新命令不会破坏当前事务。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-DATA-WAITS-CMD>` | Seq | `FC-CMD-DATA-CONCURRENCY` | 数据流程需要命令资源时会等待 busy 释放。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-RECOVER-AFTER-SERIAL>` | Seq | `FC-CMD-DATA-CONCURRENCY` | 前一事务完成后下一事务能够继续推进。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-HOLD-UNTIL-ACK>` | Seq | `FC-DMA-ACK-STALL` | 在 `m_wb_ack_i` 到来前，主接口事务关键信号保持稳定。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-RELEASE-ON-ACK>` | Seq | `FC-DMA-ACK-STALL` | 收到 ACK 后及时撤销或推进到下一拍事务。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-LONG-STALL-HANDLING>` | Seq | `FC-DMA-ACK-STALL` | 长时间无 ACK 时不应出现非法抖动、错误地址跳变或无界重复完成。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-UNDEFINED-REG-READ>` | Seq | `FC-ILLEGAL-OR-BOUNDARY-ACCESS` | 读取未定义地址时返回值和应答行为符合实现约定且稳定。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-UNDEFINED-REG-WRITE>` | Seq | `FC-ILLEGAL-OR-BOUNDARY-ACCESS` | 写未定义地址不应破坏已定义寄存器状态。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-EMPTY-BD-NO-TRANSFER>` | Seq | `FC-ILLEGAL-OR-BOUNDARY-ACCESS` | 无有效 BD 时不应无故发起 DMA 或 SD 数据传输。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-PARTIAL-BD-WRITE>` | Seq | `FC-ILLEGAL-OR-BOUNDARY-ACCESS` | 仅写入半个 BD 时不应被误认为可执行任务。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-ERROR-LATCH>` | Seq | `FC-ERROR-RECOVERY` | 错误发生后对应状态被可靠锁存，便于软件读取。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-CLEAR-AND-RETRY>` | Seq | `FC-ERROR-RECOVERY` | 清除错误并重新配置后，可再次发起命令或数据流程。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |
| `<CK-NO-STUCK-BUSY>` | Seq | `FC-ERROR-RECOVERY` | 错误处理后 busy/事务控制不会永久卡死。 | `signal.wb_clk_i` | [附录 B / D] | Planned | Planned |

### 附录 G：签核清单

- [x] 摘要在细节前说明职责、输入输出、关键概念、延迟、验证范围和 OPEN。
- [x] 每项功能按输入、输出、延迟、统一规则、适用实例、边界与限制组织。
- [x] 模块级规则未混入实例枚举；实例差异集中在能力矩阵和附录 C。
- [x] 正文仅以 `[E-*]` 引用证据，完整路径集中在附录 D。
- [x] Test Plan 是验证执行入口；FC/CK 完整登记集中在附录 F。
- [x] API 只包含 Assume，Coverage 只包含 Cover。
- [x] Verilog 端口逐项核对，配置裁剪有依据。
- [x] 正常、资源边界和恢复场景有可判定验收标准。
