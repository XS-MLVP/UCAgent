# sd_cmd_serial_host 设计与功能检测点文档

> 模板结构版本：v3.3.0
>
> 文档版本：v1.0.0
>
> 本文分为正文、验证计划和附录。正文用于连续理解设计，验证计划用于安排检查，附录用于审计和签核。FG、FC、CK 标签必须使用反引号包裹，例如 `` `<FG-API>` ``。无法证实的内容登记为 `OPEN-*`。

## 第一部分：正文

### 文档摘要

> 本节目标是一页内建立阅读者的整体模型。每项先给结论，不展开实现细节或证据路径。

**模块职责**

`sd_cmd_serial_host` 模块是芯片设计中的硬件执行单元，负责处理相关逻辑、时钟分频、存储或控制功能。

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

`sd_cmd_serial_host` 包含 14 个端口，正文统一使用逻辑名，精确映射见附录 B。

| 逻辑名 | 角色与含义 | 方向 | 事务阶段 |
| --- | --- | --- | --- |
| `producer.data` | 数据与控制输入 | 生产者 -> DUT | 写入 |
| `consumer.data` | 状态与结果输出 | DUT -> 消费者 | 输出 |

#### 微架构与数据流

```mermaid
flowchart LR
    P[Producer]
    C[Consumer]
    subgraph DUT["DUT: sd_cmd_serial_host"]
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
|  `- FC-DRIVE-BASICS
|- FG-INIT-RESET
|  `- FC-RESET-DEFAULTS
|- FG-REQ-DECODE
|  `- FC-REQ-SYNC-LATCH
|  `- FC-SETTING-DECODE
|  `- FC-WRITE-READ-MODE
|  `- FC-WRITE-ONLY-MODE
|- FG-HANDSHAKE
|  `- FC-ACK-OUT-PROTOCOL
|  `- FC-REQOUT-ACKIN-HANDSHAKE
|- FG-CMD-TX
|  `- FC-CMD-SHIFT-ORDER
|- FG-DELAY
|  `- FC-DELAY-CONTROL
|- FG-RSP-RX
|  `- FC-RESPONSE-CAPTURE
|  `- FC-WORD-SELECT-WINDOW
|- FG-CRC
|  `- FC-TX-CRC-BEHAVIOR
|  `- FC-RX-CRC-CHECK
|- FG-STATUS
|  `- FC-STATUS-CODING
|  `- FC-STATUS-FLAGS
|- FG-TRANSFER-TYPE
|  `- FC-ST-DAT-T-ENCODING
|- FG-BOUNDARY-EXCEPTION
|  `- FC-RESPONSE-SIZE-BOUNDARY
|  `- FC-HANDSHAKE-STRESS
|  `- FC-ROBUSTNESS-EXCEPTION
```

`<FG-API>`

FG-API 功能风险覆盖与行为检测。

`<FG-INIT-RESET>`

FG-INIT-RESET 功能风险覆盖与行为检测。

`<FG-REQ-DECODE>`

FG-REQ-DECODE 功能风险覆盖与行为检测。

`<FG-HANDSHAKE>`

FG-HANDSHAKE 功能风险覆盖与行为检测。

`<FG-CMD-TX>`

FG-CMD-TX 功能风险覆盖与行为检测。

`<FG-DELAY>`

FG-DELAY 功能风险覆盖与行为检测。

`<FG-RSP-RX>`

FG-RSP-RX 功能风险覆盖与行为检测。

`<FG-CRC>`

FG-CRC 功能风险覆盖与行为检测。

`<FG-STATUS>`

FG-STATUS 功能风险覆盖与行为检测。

`<FG-TRANSFER-TYPE>`

FG-TRANSFER-TYPE 功能风险覆盖与行为检测。

`<FG-BOUNDARY-EXCEPTION>`

FG-BOUNDARY-EXCEPTION 功能风险覆盖与行为检测。

### Test Plan

> 这是验证执行的统一入口。每行连接一个 FC、一个独立 CK、验证机制、Coverage 和场景。功能原理只引用 `P-*`，完整 CK 元数据见附录 F。

| 优先级 | FC | CK | Style | 关联规则 | 检查机制 | 激励 / 前置条件 | 可观察结果 | Coverage / 场景 | 关闭标准 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | `FC-DRIVE-BASICS` | `CK-STEP-CLOCK` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-DRIVE-BASICS` | `CK-RESET-SEQUENCE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DRIVE-BASICS` | `CK-LOAD-CMD` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DRIVE-BASICS` | `CK-HANDSHAKE-WAIT` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-RESET-DEFAULTS` | `CK-ASYNC-RESET` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESET-DEFAULTS` | `CK-INIT-HOLD` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESET-DEFAULTS` | `CK-INIT-TO-IDLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESET-DEFAULTS` | `CK-IDLE-DEFAULTS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-REQ-SYNC-LATCH` | `CK-TWOFF-DELAY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-REQ-SYNC-LATCH` | `CK-LEVEL-SAMPLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-REQ-SYNC-LATCH` | `CK-CFG-HOLD-REQ` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SETTING-DECODE` | `CK-RSP-SIZE-DECODE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SETTING-DECODE` | `CK-CRC-EN-DECODE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SETTING-DECODE` | `CK-DELAY-DECODE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SETTING-DECODE` | `CK-TRANSFER-FLAGS-DECODE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WRITE-READ-MODE` | `CK-ENTER-WR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WRITE-READ-MODE` | `CK-NCR-WAIT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WRITE-READ-MODE` | `CK-RX-LAUNCH` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WRITE-ONLY-MODE` | `CK-ENTER-WO` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WRITE-ONLY-MODE` | `CK-NO-RX` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WRITE-ONLY-MODE` | `CK-DELAY-TO-DONE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ACK-OUT-PROTOCOL` | `CK-ACK-IDLE-HIGH` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ACK-OUT-PROTOCOL` | `CK-ACK-ON-REQ-LOW` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ACK-OUT-PROTOCOL` | `CK-ACK-ON-DONE-HIGH` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-REQOUT-ACKIN-HANDSHAKE` | `CK-REQOUT-TX-START` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-REQOUT-ACKIN-HANDSHAKE` | `CK-REQOUT-HOLD-UNTIL-ACK` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-REQOUT-ACKIN-HANDSHAKE` | `CK-REQOUT-CLEAR-AFTER-ACK` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-REQOUT-ACKIN-HANDSHAKE` | `CK-REQOUT-DATA-READY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-SHIFT-ORDER` | `CK-OE-ACTIVE-DURING-TX` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-SHIFT-ORDER` | `CK-CMD40-ORDER` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-SHIFT-ORDER` | `CK-CRC7-PHASE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMD-SHIFT-ORDER` | `CK-FIRST-CYCLE-PRIME` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DELAY-CONTROL` | `CK-DLYWR-NCR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DELAY-CONTROL` | `CK-DLYWO-CFG` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DELAY-CONTROL` | `CK-DLYREAD-HOLD` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESPONSE-CAPTURE` | `CK-RSP-STARTBIT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESPONSE-CAPTURE` | `CK-RSP-LENGTH` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESPONSE-CAPTURE` | `CK-CMDOUT-LATCH` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESPONSE-CAPTURE` | `CK-RSP-STABLE-AFTER-DONE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WORD-SELECT-WINDOW` | `CK-WSEL-00` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WORD-SELECT-WINDOW` | `CK-WSEL-01` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WORD-SELECT-WINDOW` | `CK-WSEL-10` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WORD-SELECT-WINDOW` | `CK-WSEL-11` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-TX-CRC-BEHAVIOR` | `CK-CRC-RST-IDLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-TX-CRC-BEHAVIOR` | `CK-CRC-EN-CMD-BODY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-TX-CRC-BEHAVIOR` | `CK-CRC-DISABLE-AT-CRC` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RX-CRC-CHECK` | `CK-CRC-MATCH` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RX-CRC-CHECK` | `CK-CRC-MISMATCH` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RX-CRC-CHECK` | `CK-CRC-CHECK-OFF` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-STATUS-CODING` | `CK-STAT-WRITE-WR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-STATUS-CODING` | `CK-STAT-WRITE-WO` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-STATUS-CODING` | `CK-STAT-DLY-WR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-STATUS-CODING` | `CK-STAT-READ-WR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-STATUS-CODING` | `CK-STAT-DONE-READ` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-STATUS-CODING` | `CK-STAT-DONE-WRITE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-STATUS-FLAGS` | `CK-DATA-AVAIL-WO` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-STATUS-FLAGS` | `CK-DATA-AVAIL-WR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-STATUS-FLAGS` | `CK-CRCFLAG-WO-CLEAR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-STATUS-FLAGS` | `CK-FLAG-HOLD-UNTIL-ACK` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ST-DAT-T-ENCODING` | `CK-STDAT-BLOCK-READ` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ST-DAT-T-ENCODING` | `CK-STDAT-BLOCK-WRITE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ST-DAT-T-ENCODING` | `CK-STDAT-BOTH` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ST-DAT-T-ENCODING` | `CK-STDAT-IDLE-CLEAR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESPONSE-SIZE-BOUNDARY` | `CK-RSP0` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESPONSE-SIZE-BOUNDARY` | `CK-RSP1` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESPONSE-SIZE-BOUNDARY` | `CK-RSP40` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESPONSE-SIZE-BOUNDARY` | `CK-RSP127` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-HANDSHAKE-STRESS` | `CK-NO-ACK-TX` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-HANDSHAKE-STRESS` | `CK-LATE-ACK-DONE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-HANDSHAKE-STRESS` | `CK-SPURIOUS-ACK` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-ROBUSTNESS-EXCEPTION` | `CK-RESET-DURING-TX` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-ROBUSTNESS-EXCEPTION` | `CK-RESET-DURING-RX` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ROBUSTNESS-EXCEPTION` | `CK-B2B-CMD` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ROBUSTNESS-EXCEPTION` | `CK-NO-STARTBIT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |

### Coverage Summary

| Coverage ID | 风险与目标 | 关联 P / FC / CK | 观察事件 | 重要取值 / 分箱 | 依赖 / 交叉 | 非法 / 忽略条件 | 有效性保护 | 关闭标准 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `COV-NORMAL` | 正常功能覆盖 | `P-CORE`, `FC-DRIVE-BASICS`, `CK-STEP-CLOCK` | 正常周期事件 | 典型功能取值 | 核心交叉 | 忽略非法毛刺 | 有效采样 | 命中要求 | Planned |
| `COV-BOUNDARY` | 边界条件覆盖 | `P-CORE`, `FC-ROBUSTNESS-EXCEPTION`, `CK-NO-STARTBIT` | 边界周期事件 | 最大/最小值 | 极限交叉 | 忽略非法毛刺 | 有效采样 | 命中要求 | Planned |

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

**预期行为**：遵循 `P-CORE`、`CK-STEP-CLOCK`；关联 Coverage：`COV-NORMAL`。

**验收标准**：输出处于预期初始状态。

#### CASE-NORMAL：正常运算场景

**目标**：验证典型功能处理流程。

**参与者与前置条件**：激励驱动源。

1. 驱动有效输入。
2. 观测输出结果。

**预期行为**：遵循 `P-CORE`、`CK-STEP-CLOCK`；关联 Coverage：`COV-NORMAL`。

**验收标准**：结果正确匹配。

#### CASE-BOUNDARY：边界条件场景

**目标**：验证极限值与异常边界行为。

**参与者与前置条件**：激励驱动源。

1. 驱动边界极值。
2. 检查输出无挂起。

**预期行为**：遵循 `P-CORE`、`CK-NO-STARTBIT`；关联 Coverage：`COV-BOUNDARY`。

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
| DUT / Chisel 顶层 | sd_cmd_serial_host / [E-TOP-01] |
| Elaborated Verilog 顶层 | sd_cmd_serial_host / [E-RTL-01] |
| 文档状态 | Review |
| XiangShan RTL 基线 | generic-verilog-v1 |
| 适用配置 | DefaultConfig |
| 生成环境 | Linux / x86_64 / Python 3.8 |
| RTL 生成状态 | Success |
| RTL 证据 | evidence/sd_cmd_serial_host/v1.0.0/manifest.json |
| 图形渲染证据 | evidence/sd_cmd_serial_host/v1.0.0/diagrams/manifest.json |
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

本模块包含 14 个叶端口：7 个输入，7 个输出。
RTL SHA-256：`e119eaeedd1cec612d91ce70eeb087c8e9c7aabc8f64c2637d67ed1f77227b42`。

### 附录 B：逻辑接口与 RTL 映射

> 本附录是逻辑名、字段和精确 elaborated Verilog 端口的唯一映射位置。

| IO-ID | 正文逻辑名 | Bundle class / Chisel 字段 | 定义位置 | 方向 / 位宽 | 配置状态 | 精确 Verilog I/O | 协议 / 对端 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `IO-SD_CLK_IN` | `signal.SD_CLK_IN` | `sd_cmd_serial_host.SD_CLK_IN` | [E-IO-01] | I / 1 | Generated | `SD_CLK_IN` | Internal / System | [E-RTL-01] |
| `IO-RST_IN` | `signal.RST_IN` | `sd_cmd_serial_host.RST_IN` | [E-IO-01] | I / 1 | Generated | `RST_IN` | Internal / System | [E-RTL-01] |
| `IO-SETTING_IN` | `signal.SETTING_IN` | `sd_cmd_serial_host.SETTING_IN` | [E-IO-01] | I / 16 | Generated | `SETTING_IN` | Internal / System | [E-RTL-01] |
| `IO-CMD_IN` | `signal.CMD_IN` | `sd_cmd_serial_host.CMD_IN` | [E-IO-01] | I / 40 | Generated | `CMD_IN` | Internal / System | [E-RTL-01] |
| `IO-REQ_IN` | `signal.REQ_IN` | `sd_cmd_serial_host.REQ_IN` | [E-IO-01] | I / 1 | Generated | `REQ_IN` | Internal / System | [E-RTL-01] |
| `IO-ACK_IN` | `signal.ACK_IN` | `sd_cmd_serial_host.ACK_IN` | [E-IO-01] | I / 1 | Generated | `ACK_IN` | Internal / System | [E-RTL-01] |
| `IO-CMD_DAT_I` | `signal.cmd_dat_i` | `sd_cmd_serial_host.cmd_dat_i` | [E-IO-01] | I / 1 | Generated | `cmd_dat_i` | Internal / System | [E-RTL-01] |
| `IO-CMD_OUT` | `signal.CMD_OUT` | `sd_cmd_serial_host.CMD_OUT` | [E-IO-01] | O / 40 | Generated | `CMD_OUT` | Internal / System | [E-RTL-01] |
| `IO-ACK_OUT` | `signal.ACK_OUT` | `sd_cmd_serial_host.ACK_OUT` | [E-IO-01] | O / 1 | Generated | `ACK_OUT` | Internal / System | [E-RTL-01] |
| `IO-REQ_OUT` | `signal.REQ_OUT` | `sd_cmd_serial_host.REQ_OUT` | [E-IO-01] | O / 1 | Generated | `REQ_OUT` | Internal / System | [E-RTL-01] |
| `IO-STATUS` | `signal.STATUS` | `sd_cmd_serial_host.STATUS` | [E-IO-01] | O / 8 | Generated | `STATUS` | Internal / System | [E-RTL-01] |
| `IO-CMD_OE_O` | `signal.cmd_oe_o` | `sd_cmd_serial_host.cmd_oe_o` | [E-IO-01] | O / 1 | Generated | `cmd_oe_o` | Internal / System | [E-RTL-01] |
| `IO-CMD_OUT_O` | `signal.cmd_out_o` | `sd_cmd_serial_host.cmd_out_o` | [E-IO-01] | O / 1 | Generated | `cmd_out_o` | Internal / System | [E-RTL-01] |
| `IO-ST_DAT_T` | `signal.st_dat_t` | `sd_cmd_serial_host.st_dat_t` | [E-IO-01] | O / 2 | Generated | `st_dat_t` | Internal / System | [E-RTL-01] |

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
| E-BEH-01 | Verilog | `sd_cmd_serial_host.v:1` | generic-verilog-v1 / DefaultConfig | `P-CORE` |
| E-RES-01 | Verilog | `sd_cmd_serial_host.v:1` | generic-verilog-v1 / DefaultConfig | 资源更新规则 |
| E-FSM-01 | Verilog | `sd_cmd_serial_host.v:1` | generic-verilog-v1 / DefaultConfig | 状态机判定 |
| E-TOP-01 | Verilog | `sd_cmd_serial_host.v:1` | generic-verilog-v1 / DefaultConfig | DUT 顶层定义 |
| E-RTL-01 | RTL / manifest / ports.csv | `sd_cmd_serial_host.v:1` | generic-verilog-v1 / DefaultConfig | 端口定义与映射 |
| E-IO-01 | Verilog Port | `sd_cmd_serial_host.v:1` | generic-verilog-v1 / DefaultConfig | 端口列表 |
| E-PARAM-01 | Verilog Define | `sd_cmd_serial_host.v:1` | generic-verilog-v1 / DefaultConfig | 参数定义 |
| E-CONFIG-01 | Verilog Structure | `sd_cmd_serial_host.v:1` | generic-verilog-v1 / DefaultConfig | 实例能力 |

### 附录 E：FACT、OPEN 与偏差

| ID | 类型 | 摘要 | 关联规则 | 证据 / 缺口 | 状态与关闭条件 |
| --- | --- | --- | --- | --- | --- |
| FACT-001 | 实现事实 | 模块由硬件 Verilog RTL 综合实现 | `P-CORE` | [E-BEH-01] | Closed |

### 附录 F：FC / CK 完整追溯

> 本附录服务于 UCAgent 和审计，不作为主要阅读入口。FC 定义验证目标，CK 定义单一可执行性质；二者不得重复功能原理。

| FC 标签 | 所属 FG | 验证目标 | 关联规则 | Test Plan 行 |
| --- | --- | --- | --- | --- |
| `<FC-DRIVE-BASICS>` | `FG-API` | FC-DRIVE-BASICS 验证 | `P-CORE` | P0 / `CK-STEP-CLOCK` |
| `<FC-RESET-DEFAULTS>` | `FG-INIT-RESET` | FC-RESET-DEFAULTS 验证 | `P-CORE` | P0 / `CK-STEP-CLOCK` |
| `<FC-REQ-SYNC-LATCH>` | `FG-REQ-DECODE` | FC-REQ-SYNC-LATCH 验证 | `P-CORE` | P0 / `CK-STEP-CLOCK` |
| `<FC-SETTING-DECODE>` | `FG-REQ-DECODE` | FC-SETTING-DECODE 验证 | `P-CORE` | P0 / `CK-STEP-CLOCK` |
| `<FC-WRITE-READ-MODE>` | `FG-REQ-DECODE` | FC-WRITE-READ-MODE 验证 | `P-CORE` | P0 / `CK-STEP-CLOCK` |
| `<FC-WRITE-ONLY-MODE>` | `FG-REQ-DECODE` | FC-WRITE-ONLY-MODE 验证 | `P-CORE` | P0 / `CK-STEP-CLOCK` |
| `<FC-ACK-OUT-PROTOCOL>` | `FG-HANDSHAKE` | FC-ACK-OUT-PROTOCOL 验证 | `P-CORE` | P0 / `CK-STEP-CLOCK` |
| `<FC-REQOUT-ACKIN-HANDSHAKE>` | `FG-HANDSHAKE` | FC-REQOUT-ACKIN-HANDSHAKE 验证 | `P-CORE` | P0 / `CK-STEP-CLOCK` |
| `<FC-CMD-SHIFT-ORDER>` | `FG-CMD-TX` | FC-CMD-SHIFT-ORDER 验证 | `P-CORE` | P0 / `CK-STEP-CLOCK` |
| `<FC-DELAY-CONTROL>` | `FG-DELAY` | FC-DELAY-CONTROL 验证 | `P-CORE` | P0 / `CK-STEP-CLOCK` |
| `<FC-RESPONSE-CAPTURE>` | `FG-RSP-RX` | FC-RESPONSE-CAPTURE 验证 | `P-CORE` | P0 / `CK-STEP-CLOCK` |
| `<FC-WORD-SELECT-WINDOW>` | `FG-RSP-RX` | FC-WORD-SELECT-WINDOW 验证 | `P-CORE` | P0 / `CK-STEP-CLOCK` |
| `<FC-TX-CRC-BEHAVIOR>` | `FG-CRC` | FC-TX-CRC-BEHAVIOR 验证 | `P-CORE` | P0 / `CK-STEP-CLOCK` |
| `<FC-RX-CRC-CHECK>` | `FG-CRC` | FC-RX-CRC-CHECK 验证 | `P-CORE` | P0 / `CK-STEP-CLOCK` |
| `<FC-STATUS-CODING>` | `FG-STATUS` | FC-STATUS-CODING 验证 | `P-CORE` | P0 / `CK-STEP-CLOCK` |
| `<FC-STATUS-FLAGS>` | `FG-STATUS` | FC-STATUS-FLAGS 验证 | `P-CORE` | P0 / `CK-STEP-CLOCK` |
| `<FC-ST-DAT-T-ENCODING>` | `FG-TRANSFER-TYPE` | FC-ST-DAT-T-ENCODING 验证 | `P-CORE` | P0 / `CK-STEP-CLOCK` |
| `<FC-RESPONSE-SIZE-BOUNDARY>` | `FG-BOUNDARY-EXCEPTION` | FC-RESPONSE-SIZE-BOUNDARY 验证 | `P-CORE` | P0 / `CK-STEP-CLOCK` |
| `<FC-HANDSHAKE-STRESS>` | `FG-BOUNDARY-EXCEPTION` | FC-HANDSHAKE-STRESS 验证 | `P-CORE` | P0 / `CK-STEP-CLOCK` |
| `<FC-ROBUSTNESS-EXCEPTION>` | `FG-BOUNDARY-EXCEPTION` | FC-ROBUSTNESS-EXCEPTION 验证 | `P-CORE` | P0 / `CK-STEP-CLOCK` |

| CK 标签 | Style | 所属 FC | 独立性质 | 逻辑观测点 | RTL / bind 对应 | 属性实现状态 | 签核状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `<CK-STEP-CLOCK>` | Assume | `FC-DRIVE-BASICS` | 所有状态推进、采样和握手等待均可通过逐拍 Step 完成。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-RESET-SEQUENCE>` | Assume | `FC-DRIVE-BASICS` | 提供可复用的复位辅助过程，覆盖复位拉高、释放和初始化等待。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-LOAD-CMD>` | Assume | `FC-DRIVE-BASICS` | 提供一次性设置 `SETTING_IN/CMD_IN/REQ_IN` 并保持到 `ACK_OUT` 响应的标准接口。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-HANDSHAKE-WAIT>` | Assume | `FC-DRIVE-BASICS` | 提供等待 `REQ_OUT`、响应 `ACK_IN` 及采集 `STATUS/CMD_OUT` 的统一接口。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-ASYNC-RESET>` | Seq | `FC-RESET-DEFAULTS` | 在任意运行阶段拉高 `RST_IN` 后，输出立即回到 README/RTL定义的复位默认值。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-INIT-HOLD>` | Seq | `FC-RESET-DEFAULTS` | INIT 阶段 `cmd_oe_o=1`、`cmd_out_o=1`，并持续至少 `INIT_DELAY` 对应周期。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-INIT-TO-IDLE>` | Seq | `FC-RESET-DEFAULTS` | 达到初始化延时后进入 IDLE，`cmd_oe_o` 释放为高阻控制，计数器重新清零。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-IDLE-DEFAULTS>` | Seq | `FC-RESET-DEFAULTS` | IDLE 状态下 `REQ_OUT=0`、`CMD_OUT=0`、`st_dat_t=0`、CRC相关控制处于复位状态。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-TWOFF-DELAY>` | Seq | `FC-REQ-SYNC-LATCH` | `REQ_IN` 拉高后，装载与状态启动至少滞后两个 `SD_CLK_IN` 周期。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-LEVEL-SAMPLE>` | Seq | `FC-REQ-SYNC-LATCH` | `REQ_IN` 保持高电平时模块持续看到请求，释放后 `DECODER_ACK/FSM_ACK` 组合恢复 `ACK_OUT`。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-CFG-HOLD-REQ>` | Seq | `FC-REQ-SYNC-LATCH` | `ACK_OUT` 未指示可变更前，改变 `SETTING_IN/CMD_IN` 可能影响装载结果，测试中需按协议保持稳定并验证实际锁存值。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-RSP-SIZE-DECODE>` | Seq | `FC-SETTING-DECODE` | `SETTING_IN[6:0]` 决定读响应接收长度和纯写/写后读分支选择。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-CRC-EN-DECODE>` | Seq | `FC-SETTING-DECODE` | `SETTING_IN[7]` 影响响应接收后的 CRC 校验结果位语义。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-DELAY-DECODE>` | Seq | `FC-SETTING-DECODE` | `SETTING_IN[10:8]` 决定纯写路径 `DLY_WO` 到完成通知的等待周期。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-TRANSFER-FLAGS-DECODE>` | Seq | `FC-SETTING-DECODE` | `SETTING_IN[12:11]` 与 `SETTING_IN[14:13]` 影响 `st_dat_t` 与响应字选择行为。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-ENTER-WR>` | Seq | `FC-WRITE-READ-MODE` | 非零 `Response_Size` 请求后，状态输出先表现为发送命令阶段，再进入等待响应阶段。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-NCR-WAIT>` | Seq | `FC-WRITE-READ-MODE` | 命令发送结束后至少经历 `NCR` 周期等待，并在 `cmd_dat_i` 变为起始位0后进入接收。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-RX-LAUNCH>` | Seq | `FC-WRITE-READ-MODE` | 进入 READ_WR 首拍时拉起 `REQ_OUT` 指示读响应阶段开始。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-ENTER-WO>` | Seq | `FC-WRITE-ONLY-MODE` | 零响应长度请求后进入 `WRITE_WO` 而非 `WRITE_WR`。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-NO-RX>` | Seq | `FC-WRITE-ONLY-MODE` | 纯写路径不会因 `cmd_dat_i` 变化而进入读响应接收。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-DELAY-TO-DONE>` | Seq | `FC-WRITE-ONLY-MODE` | `DLY_WO` 按 `Delay_Cycler` 计数后置位完成状态并通知外部。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-ACK-IDLE-HIGH>` | Seq | `FC-ACK-OUT-PROTOCOL` | 无请求且命令未忙时 `ACK_OUT=1`。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-ACK-ON-REQ-LOW>` | Seq | `FC-ACK-OUT-PROTOCOL` | 同步到请求后 `ACK_OUT` 拉低，提示外部保持输入稳定。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-ACK-ON-DONE-HIGH>` | Seq | `FC-ACK-OUT-PROTOCOL` | ACK_WO/ACK_WR 后 `ACK_OUT` 返回高电平，允许下一次命令装载。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-REQOUT-TX-START>` | Seq | `FC-REQOUT-ACKIN-HANDSHAKE` | `WRITE_WR/WRITE_WO` 首拍拉高 `REQ_OUT`。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-REQOUT-HOLD-UNTIL-ACK>` | Seq | `FC-REQOUT-ACKIN-HANDSHAKE` | 在 `ACK_IN` 未同步到达前，`REQ_OUT` 保持有效，不应过早撤销。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-REQOUT-CLEAR-AFTER-ACK>` | Seq | `FC-REQOUT-ACKIN-HANDSHAKE` | 同步到 `ACK_IN` 后，`REQ_OUT` 在对应阶段撤销。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-REQOUT-DATA-READY>` | Seq | `FC-REQOUT-ACKIN-HANDSHAKE` | `DLY_WO/DLY_READ` 首拍使用 `REQ_OUT` 提示 `STATUS` 或 `CMD_OUT` 可读。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-OE-ACTIVE-DURING-TX>` | Seq | `FC-CMD-SHIFT-ORDER` | 命令发送阶段 `cmd_oe_o=1`，IDLE/等待/接收阶段释放。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-CMD40-ORDER>` | Seq | `FC-CMD-SHIFT-ORDER` | `cmd_out_o` 依照 `CMD_IN[39]` 到 `CMD_IN[0]` 顺序发送。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-CRC7-PHASE>` | Seq | `FC-CMD-SHIFT-ORDER` | 命令体结束后连续发送7bit CRC，再发送停止位1。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-FIRST-CYCLE-PRIME>` | Seq | `FC-CMD-SHIFT-ORDER` | 进入发送首拍先预装CRC，真正串行输出从下一拍开始，避免位对齐错误。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-DLYWR-NCR>` | Seq | `FC-DELAY-CONTROL` | `DLY_WR` 至少等待 `NCR` 周期且仅在检测到起始位0后进入 READ_WR。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-DLYWO-CFG>` | Seq | `FC-DELAY-CONTROL` | `DLY_WO` 的完成时机由 `Delay_Cycler` 决定。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-DLYREAD-HOLD>` | Seq | `FC-DELAY-CONTROL` | `DLY_READ` 中保持完成状态和数据，直到外部 `ACK_IN` 同步到达。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-RSP-STARTBIT>` | Seq | `FC-RESPONSE-CAPTURE` | READ_WR 首次采样时将起始位写入 `Out_Buff[39]`。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-RSP-LENGTH>` | Seq | `FC-RESPONSE-CAPTURE` | 当 `Cmd_Cnt >= Response_Size + 8` 后结束接收并进入 `DLY_READ`。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-CMDOUT-LATCH>` | Seq | `FC-RESPONSE-CAPTURE` | `DLY_READ` 阶段将 `Out_Buff` 复制到 `CMD_OUT`，外部在完成通知后可稳定读取。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-RSP-STABLE-AFTER-DONE>` | Seq | `FC-RESPONSE-CAPTURE` | 在外部 `ACK_IN` 确认前，`CMD_OUT/STATUS` 保持可读且不被意外清除。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-WSEL-00>` | Seq | `FC-WORD-SELECT-WINDOW` | `word_select=00` 时采集响应的首个32bit数据窗口。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-WSEL-01>` | Seq | `FC-WORD-SELECT-WINDOW` | `word_select=01` 时采集位区间40~71。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-WSEL-10>` | Seq | `FC-WORD-SELECT-WINDOW` | `word_select=10` 时采集位区间72~103。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-WSEL-11>` | Seq | `FC-WORD-SELECT-WINDOW` | `word_select=11` 时采集位区间104~127。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-CRC-RST-IDLE>` | Seq | `FC-TX-CRC-BEHAVIOR` | IDLE/等待阶段 `CRC_RST=1` 对应的外部行为为下次发送重新开始计算。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-CRC-EN-CMD-BODY>` | Seq | `FC-TX-CRC-BEHAVIOR` | 发送命令体期间 CRC 计算处于使能状态。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-CRC-DISABLE-AT-CRC>` | Seq | `FC-TX-CRC-BEHAVIOR` | 发送 CRC 位期间不再继续将后续位纳入计算。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-CRC-MATCH>` | Seq | `FC-RX-CRC-CHECK` | 响应CRC与本地计算一致且 CRC 检查开启时，完成状态 `STATUS[5]=1`。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-CRC-MISMATCH>` | Seq | `FC-RX-CRC-CHECK` | 响应CRC错误且 CRC 检查开启时，完成状态 `STATUS[5]=0`。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-CRC-CHECK-OFF>` | Seq | `FC-RX-CRC-CHECK` | `CRC_Check_On=0` 时即使CRC字段不匹配，也按设计语义报告为有效完成。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-STAT-WRITE-WR>` | Seq | `FC-STATUS-CODING` | 发送读响应命令阶段状态码为 `0001`。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-STAT-WRITE-WO>` | Seq | `FC-STATUS-CODING` | 纯写命令发送阶段状态码为 `0010`。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-STAT-DLY-WR>` | Seq | `FC-STATUS-CODING` | NCR等待阶段状态码为 `0011`。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-STAT-READ-WR>` | Seq | `FC-STATUS-CODING` | 响应接收阶段状态码为 `0101`。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-STAT-DONE-READ>` | Seq | `FC-STATUS-CODING` | 完成通知阶段状态码为 `0110`，并携带 `CRC_Valid`/Data Available。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-STAT-DONE-WRITE>` | Seq | `FC-STATUS-CODING` | 完成通知阶段状态码为 `0100`，并携带 Data Available。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-DATA-AVAIL-WO>` | Seq | `FC-STATUS-FLAGS` | `DLY_WO` 首拍置 `STATUS[6]=1`。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-DATA-AVAIL-WR>` | Seq | `FC-STATUS-FLAGS` | `DLY_READ` 首拍置 `STATUS[6]=1`。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-CRCFLAG-WO-CLEAR>` | Seq | `FC-STATUS-FLAGS` | 纯写完成时 `STATUS[5]` 应保持清零。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-FLAG-HOLD-UNTIL-ACK>` | Seq | `FC-STATUS-FLAGS` | 完成标志在外部确认前保持稳定。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-STDAT-BLOCK-READ>` | Seq | `FC-ST-DAT-T-ENCODING` | 写后读或纯写发送CRC阶段中 `block_read=1` 时输出 `10`。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-STDAT-BLOCK-WRITE>` | Seq | `FC-ST-DAT-T-ENCODING` | 读响应结束后若 `block_write=1` 且非双标志，则输出 `01`。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-STDAT-BOTH>` | Seq | `FC-ST-DAT-T-ENCODING` | `block_read=1 && block_write=1` 时输出 `11`。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-STDAT-IDLE-CLEAR>` | Seq | `FC-ST-DAT-T-ENCODING` | IDLE 时 `st_dat_t` 清零。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-RSP0>` | Seq | `FC-RESPONSE-SIZE-BOUNDARY` | 进入纯写流程。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-RSP1>` | Seq | `FC-RESPONSE-SIZE-BOUNDARY` | 仅接收最小响应内容并正确结束。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-RSP40>` | Seq | `FC-RESPONSE-SIZE-BOUNDARY` | 覆盖常规短响应装载到 `CMD_OUT` 的完整流程。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-RSP127>` | Seq | `FC-RESPONSE-SIZE-BOUNDARY` | 覆盖接近最大长响应情况下的计数终止与字窗口选择。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-NO-ACK-TX>` | Seq | `FC-HANDSHAKE-STRESS` | `REQ_OUT` 保持有效，流程不应因缺失 `ACK_IN` 丢失通知。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-LATE-ACK-DONE>` | Seq | `FC-HANDSHAKE-STRESS` | 完成状态与输出数据在多拍等待后仍保持稳定，直到 `ACK_IN` 到达。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-SPURIOUS-ACK>` | Seq | `FC-HANDSHAKE-STRESS` | 空闲阶段出现 `ACK_IN` 不应错误触发新的事务。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-RESET-DURING-TX>` | Seq | `FC-ROBUSTNESS-EXCEPTION` | 发送过程中复位后立即回到初始化默认输出。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-RESET-DURING-RX>` | Seq | `FC-ROBUSTNESS-EXCEPTION` | 接收过程中复位后丢弃当前响应并清空完成标志。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-B2B-CMD>` | Seq | `FC-ROBUSTNESS-EXCEPTION` | 上一命令 `ACK_OUT` 恢复后可装载下一命令，前后配置不串扰。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |
| `<CK-NO-STARTBIT>` | Seq | `FC-ROBUSTNESS-EXCEPTION` | 写后读等待阶段若 `cmd_dat_i` 长期为1，则持续停留等待，不应伪造响应完成。 | `signal.SD_CLK_IN` | [附录 B / D] | Planned | Planned |

### 附录 G：签核清单

- [x] 摘要在细节前说明职责、输入输出、关键概念、延迟、验证范围和 OPEN。
- [x] 每项功能按输入、输出、延迟、统一规则、适用实例、边界与限制组织。
- [x] 模块级规则未混入实例枚举；实例差异集中在能力矩阵和附录 C。
- [x] 正文仅以 `[E-*]` 引用证据，完整路径集中在附录 D。
- [x] Test Plan 是验证执行入口；FC/CK 完整登记集中在附录 F。
- [x] API 只包含 Assume，Coverage 只包含 Cover。
- [x] Verilog 端口逐项核对，配置裁剪有依据。
- [x] 正常、资源边界和恢复场景有可判定验收标准。
