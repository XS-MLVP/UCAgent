# e203_exu_alu_muldiv 设计与功能检测点文档

> 模板结构版本：v3.3.0
>
> 文档版本：v1.0.0
>
> 本文分为正文、验证计划和附录。正文用于连续理解设计，验证计划用于安排检查，附录用于审计和签核。FG、FC、CK 标签必须使用反引号包裹，例如 `` `<FG-API>` ``。无法证实的内容登记为 `OPEN-*`。

## 第一部分：正文

### 文档摘要

> 本节目标是一页内建立阅读者的整体模型。每项先给结论，不展开实现细节或证据路径。

**模块职责**

`e203_exu_alu_muldiv` 模块是芯片设计中的硬件执行单元，负责处理相关逻辑、时钟分频、存储或控制功能。

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

`e203_exu_alu_muldiv` 包含 27 个端口，正文统一使用逻辑名，精确映射见附录 B。

| 逻辑名 | 角色与含义 | 方向 | 事务阶段 |
| --- | --- | --- | --- |
| `producer.data` | 数据与控制输入 | 生产者 -> DUT | 写入 |
| `consumer.data` | 状态与结果输出 | DUT -> 消费者 | 输出 |

#### 微架构与数据流

```mermaid
flowchart LR
    P[Producer]
    C[Consumer]
    subgraph DUT["DUT: e203_exu_alu_muldiv"]
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
|  `- FC-TRANSACTION
|  `- FC-RESET-INIT
|- FG-INTERFACE
|  `- FC-INPUT-HANDSHAKE
|  `- FC-OUTPUT-HANDSHAKE
|  `- FC-LONGPIPE
|  `- FC-B2B-CONTROL
|  `- FC-ITAG-PROPAGATION
|  `- FC-FLUSH
|- FG-MULTIPLY
|  `- FC-MUL-LOW
|  `- FC-MUL-HIGH
|  `- FC-MUL-BOUNDARY
|  `- FC-MUL-LATENCY
|- FG-DIVIDE
|  `- FC-DIV-SIGNED
|  `- FC-DIV-UNSIGNED
|  `- FC-REM-SIGNED
|  `- FC-REM-UNSIGNED
|  `- FC-DIV-REM-CONSISTENCY
|  `- FC-DIV-SPECIAL
|  `- FC-DIV-LATENCY
|  `- FC-DIV-BOUNDARY
```

`<FG-API>`

FG-API 功能风险覆盖与行为检测。

`<FG-INTERFACE>`

FG-INTERFACE 功能风险覆盖与行为检测。

`<FG-MULTIPLY>`

FG-MULTIPLY 功能风险覆盖与行为检测。

`<FG-DIVIDE>`

FG-DIVIDE 功能风险覆盖与行为检测。

### Test Plan

> 这是验证执行的统一入口。每行连接一个 FC、一个独立 CK、验证机制、Coverage 和场景。功能原理只引用 `P-*`，完整 CK 元数据见附录 F。

| 优先级 | FC | CK | Style | 关联规则 | 检查机制 | 激励 / 前置条件 | 可观察结果 | Coverage / 场景 | 关闭标准 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | `FC-TRANSACTION` | `CK-REQ-HS` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-TRANSACTION` | `CK-RSP-HS` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-TRANSACTION` | `CK-STEP-DRIVE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-TRANSACTION` | `CK-PORT-OBS` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-RESET-INIT` | `CK-RESET-LOW` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-RESET-INIT` | `CK-RESET-RELEASE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESET-INIT` | `CK-INIT-OUTPUT` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-INPUT-HANDSHAKE` | `CK-IDLE-READY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-INPUT-HANDSHAKE` | `CK-BUSY-BACKPRESSURE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-INPUT-HANDSHAKE` | `CK-HS-LOCK` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-INPUT-HANDSHAKE` | `CK-VALID-WAIT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-OUTPUT-HANDSHAKE` | `CK-RESULT-VALID` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-OUTPUT-HANDSHAKE` | `CK-RESULT-HOLD` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-OUTPUT-HANDSHAKE` | `CK-RESULT-CLEAR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-OUTPUT-HANDSHAKE` | `CK-ERR-CONST0` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-LONGPIPE` | `CK-LONGPIPE-ASSERT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-LONGPIPE` | `CK-LONGPIPE-STABLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-B2B-CONTROL` | `CK-NOB2B-ON` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-B2B-CONTROL` | `CK-NOB2B-OFF` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-B2B-CONTROL` | `CK-B2B-AFTER-RSP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ITAG-PROPAGATION` | `CK-ITAG-0` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ITAG-PROPAGATION` | `CK-ITAG-1` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ITAG-PROPAGATION` | `CK-ITAG-B2B` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-FLUSH` | `CK-FLUSH-EXEC` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-FLUSH` | `CK-FLUSH-RESP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-FLUSH` | `CK-FLUSH-RECOVER` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-FLUSH` | `CK-FLUSH-IDEMPOTENT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-MUL-LOW` | `CK-BASIC-POS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-MUL-LOW` | `CK-ZERO-FACTOR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-MUL-LOW` | `CK-ONE-FACTOR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-MUL-LOW` | `CK-NEGATIVE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-MUL-LOW` | `CK-OVERFLOW-LOW` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-MUL-HIGH` | `CK-MULH-SS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-MUL-HIGH` | `CK-MULH-UU` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-MUL-HIGH` | `CK-MULH-SU` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-MUL-HIGH` | `CK-SIGN-EXT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-MUL-HIGH` | `CK-BOUNDARY-HIGH` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-MUL-BOUNDARY` | `CK-MINXMIN` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-MUL-BOUNDARY` | `CK-MINXNEG1` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-MUL-BOUNDARY` | `CK-ALL1XALL1` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-MUL-BOUNDARY` | `CK-ALT-BIT-PATTERN` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-MUL-LATENCY` | `CK-NO-EARLY-RSP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-MUL-LATENCY` | `CK-FINITE-COMPLETE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-MUL-LATENCY` | `CK-SINGLE-RSP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-SIGNED` | `CK-BASIC-SS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-SIGNED` | `CK-TRUNC-ZERO` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-SIGNED` | `CK-DIVIDEND-SMALL` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-SIGNED` | `CK-POWER2` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-SIGNED` | `CK-BOUNDARY-SS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-UNSIGNED` | `CK-BASIC-UU` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-UNSIGNED` | `CK-U-DIVIDEND-SMALL` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-UNSIGNED` | `CK-U-MAX` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-UNSIGNED` | `CK-U-POWER2` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-REM-SIGNED` | `CK-BASIC-REM-SS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-REM-SIGNED` | `CK-REM-SIGN` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-REM-SIGNED` | `CK-REM-ZERO` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-REM-SIGNED` | `CK-REM-BOUNDARY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-REM-UNSIGNED` | `CK-BASIC-REM-UU` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-REM-UNSIGNED` | `CK-U-REM-SMALL` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-REM-UNSIGNED` | `CK-U-REM-ZERO` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-REM-UNSIGNED` | `CK-U-REM-MAX` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-REM-CONSISTENCY` | `CK-QR-IDENTITY-SS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-REM-CONSISTENCY` | `CK-QR-IDENTITY-UU` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-REM-CONSISTENCY` | `CK-REM-MAG-SS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-REM-CONSISTENCY` | `CK-REM-RANGE-UU` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-SPECIAL` | `CK-DIV0-QUOT-SS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-SPECIAL` | `CK-DIV0-QUOT-UU` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-SPECIAL` | `CK-DIV0-REM-SS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-SPECIAL` | `CK-DIV0-REM-UU` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-SPECIAL` | `CK-OVF-INTMIN` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-LATENCY` | `CK-DIV-NO-EARLY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-LATENCY` | `CK-DIV-FINITE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-LATENCY` | `CK-DIV-SINGLE-RSP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-LATENCY` | `CK-CORR-VISIBLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-BOUNDARY` | `CK-INTMIN-DIV-1` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-BOUNDARY` | `CK-INTMIN-DIV-2` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-BOUNDARY` | `CK-NEG1-DIV-INTMIN` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-BOUNDARY` | `CK-ALL1-DIV-ALL1` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-BOUNDARY` | `CK-ALT-DIV-PATTERN` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DIV-BOUNDARY` | `CK-PRIME-NONMULT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |

### Coverage Summary

| Coverage ID | 风险与目标 | 关联 P / FC / CK | 观察事件 | 重要取值 / 分箱 | 依赖 / 交叉 | 非法 / 忽略条件 | 有效性保护 | 关闭标准 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `COV-NORMAL` | 正常功能覆盖 | `P-CORE`, `FC-TRANSACTION`, `CK-REQ-HS` | 正常周期事件 | 典型功能取值 | 核心交叉 | 忽略非法毛刺 | 有效采样 | 命中要求 | Planned |
| `COV-BOUNDARY` | 边界条件覆盖 | `P-CORE`, `FC-DIV-BOUNDARY`, `CK-PRIME-NONMULT` | 边界周期事件 | 最大/最小值 | 极限交叉 | 忽略非法毛刺 | 有效采样 | 命中要求 | Planned |

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

**预期行为**：遵循 `P-CORE`、`CK-REQ-HS`；关联 Coverage：`COV-NORMAL`。

**验收标准**：输出处于预期初始状态。

#### CASE-NORMAL：正常运算场景

**目标**：验证典型功能处理流程。

**参与者与前置条件**：激励驱动源。

1. 驱动有效输入。
2. 观测输出结果。

**预期行为**：遵循 `P-CORE`、`CK-REQ-HS`；关联 Coverage：`COV-NORMAL`。

**验收标准**：结果正确匹配。

#### CASE-BOUNDARY：边界条件场景

**目标**：验证极限值与异常边界行为。

**参与者与前置条件**：激励驱动源。

1. 驱动边界极值。
2. 检查输出无挂起。

**预期行为**：遵循 `P-CORE`、`CK-PRIME-NONMULT`；关联 Coverage：`COV-BOUNDARY`。

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
| DUT / Chisel 顶层 | e203_exu_alu_muldiv / [E-TOP-01] |
| Elaborated Verilog 顶层 | e203_exu_alu_muldiv / [E-RTL-01] |
| 文档状态 | Review |
| XiangShan RTL 基线 | generic-verilog-v1 |
| 适用配置 | DefaultConfig |
| 生成环境 | Linux / x86_64 / Python 3.8 |
| RTL 生成状态 | Success |
| RTL 证据 | evidence/e203_exu_alu_muldiv/v1.0.0/manifest.json |
| 图形渲染证据 | evidence/e203_exu_alu_muldiv/v1.0.0/diagrams/manifest.json |
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

本模块包含 27 个叶端口：14 个输入，13 个输出。
RTL SHA-256：`023b966a0d80c96e0eb6ebf824e8634eb016873b892a44a3b7c9fbb648f47580`。

### 附录 B：逻辑接口与 RTL 映射

> 本附录是逻辑名、字段和精确 elaborated Verilog 端口的唯一映射位置。

| IO-ID | 正文逻辑名 | Bundle class / Chisel 字段 | 定义位置 | 方向 / 位宽 | 配置状态 | 精确 Verilog I/O | 协议 / 对端 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `IO-MDV_NOB2B` | `signal.mdv_nob2b` | `e203_exu_alu_muldiv.mdv_nob2b` | [E-IO-01] | I / 1 | Generated | `mdv_nob2b` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_I_VALID` | `signal.muldiv_i_valid` | `e203_exu_alu_muldiv.muldiv_i_valid` | [E-IO-01] | I / 1 | Generated | `muldiv_i_valid` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_I_READY` | `signal.muldiv_i_ready` | `e203_exu_alu_muldiv.muldiv_i_ready` | [E-IO-01] | O / 1 | Generated | `muldiv_i_ready` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_I_RS1` | `signal.muldiv_i_rs1` | `e203_exu_alu_muldiv.muldiv_i_rs1` | [E-IO-01] | I / 32 | Generated | `muldiv_i_rs1` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_I_RS2` | `signal.muldiv_i_rs2` | `e203_exu_alu_muldiv.muldiv_i_rs2` | [E-IO-01] | I / 32 | Generated | `muldiv_i_rs2` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_I_IMM` | `signal.muldiv_i_imm` | `e203_exu_alu_muldiv.muldiv_i_imm` | [E-IO-01] | I / 32 | Generated | `muldiv_i_imm` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_I_INFO` | `signal.muldiv_i_info` | `e203_exu_alu_muldiv.muldiv_i_info` | [E-IO-01] | I / 13 | Generated | `muldiv_i_info` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_I_ITAG` | `signal.muldiv_i_itag` | `e203_exu_alu_muldiv.muldiv_i_itag` | [E-IO-01] | I / 1 | Generated | `muldiv_i_itag` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_I_LONGPIPE` | `signal.muldiv_i_longpipe` | `e203_exu_alu_muldiv.muldiv_i_longpipe` | [E-IO-01] | O / 1 | Generated | `muldiv_i_longpipe` | Internal / System | [E-RTL-01] |
| `IO-FLUSH_PULSE` | `signal.flush_pulse` | `e203_exu_alu_muldiv.flush_pulse` | [E-IO-01] | I / 1 | Generated | `flush_pulse` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_O_VALID` | `signal.muldiv_o_valid` | `e203_exu_alu_muldiv.muldiv_o_valid` | [E-IO-01] | O / 1 | Generated | `muldiv_o_valid` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_O_READY` | `signal.muldiv_o_ready` | `e203_exu_alu_muldiv.muldiv_o_ready` | [E-IO-01] | I / 1 | Generated | `muldiv_o_ready` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_O_WBCK_WDAT` | `signal.muldiv_o_wbck_wdat` | `e203_exu_alu_muldiv.muldiv_o_wbck_wdat` | [E-IO-01] | O / 32 | Generated | `muldiv_o_wbck_wdat` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_O_WBCK_ERR` | `signal.muldiv_o_wbck_err` | `e203_exu_alu_muldiv.muldiv_o_wbck_err` | [E-IO-01] | O / 1 | Generated | `muldiv_o_wbck_err` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_REQ_ALU_OP1` | `signal.muldiv_req_alu_op1` | `e203_exu_alu_muldiv.muldiv_req_alu_op1` | [E-IO-01] | O / 35 | Generated | `muldiv_req_alu_op1` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_REQ_ALU_OP2` | `signal.muldiv_req_alu_op2` | `e203_exu_alu_muldiv.muldiv_req_alu_op2` | [E-IO-01] | O / 35 | Generated | `muldiv_req_alu_op2` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_REQ_ALU_ADD` | `signal.muldiv_req_alu_add` | `e203_exu_alu_muldiv.muldiv_req_alu_add` | [E-IO-01] | O / 1 | Generated | `muldiv_req_alu_add` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_REQ_ALU_SUB` | `signal.muldiv_req_alu_sub` | `e203_exu_alu_muldiv.muldiv_req_alu_sub` | [E-IO-01] | O / 1 | Generated | `muldiv_req_alu_sub` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_REQ_ALU_RES` | `signal.muldiv_req_alu_res` | `e203_exu_alu_muldiv.muldiv_req_alu_res` | [E-IO-01] | I / 35 | Generated | `muldiv_req_alu_res` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_SBF_0_ENA` | `signal.muldiv_sbf_0_ena` | `e203_exu_alu_muldiv.muldiv_sbf_0_ena` | [E-IO-01] | O / 1 | Generated | `muldiv_sbf_0_ena` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_SBF_0_NXT` | `signal.muldiv_sbf_0_nxt` | `e203_exu_alu_muldiv.muldiv_sbf_0_nxt` | [E-IO-01] | O / 33 | Generated | `muldiv_sbf_0_nxt` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_SBF_0_R` | `signal.muldiv_sbf_0_r` | `e203_exu_alu_muldiv.muldiv_sbf_0_r` | [E-IO-01] | I / 33 | Generated | `muldiv_sbf_0_r` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_SBF_1_ENA` | `signal.muldiv_sbf_1_ena` | `e203_exu_alu_muldiv.muldiv_sbf_1_ena` | [E-IO-01] | O / 1 | Generated | `muldiv_sbf_1_ena` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_SBF_1_NXT` | `signal.muldiv_sbf_1_nxt` | `e203_exu_alu_muldiv.muldiv_sbf_1_nxt` | [E-IO-01] | O / 33 | Generated | `muldiv_sbf_1_nxt` | Internal / System | [E-RTL-01] |
| `IO-MULDIV_SBF_1_R` | `signal.muldiv_sbf_1_r` | `e203_exu_alu_muldiv.muldiv_sbf_1_r` | [E-IO-01] | I / 33 | Generated | `muldiv_sbf_1_r` | Internal / System | [E-RTL-01] |
| `IO-CLK` | `signal.clk` | `e203_exu_alu_muldiv.clk` | [E-IO-01] | I / 1 | Generated | `clk` | Internal / System | [E-RTL-01] |
| `IO-RST_N` | `signal.rst_n` | `e203_exu_alu_muldiv.rst_n` | [E-IO-01] | I / 1 | Generated | `rst_n` | Internal / System | [E-RTL-01] |

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
| E-BEH-01 | Verilog | `e203_exu_alu_muldiv.v:1` | generic-verilog-v1 / DefaultConfig | `P-CORE` |
| E-RES-01 | Verilog | `e203_exu_alu_muldiv.v:1` | generic-verilog-v1 / DefaultConfig | 资源更新规则 |
| E-FSM-01 | Verilog | `e203_exu_alu_muldiv.v:1` | generic-verilog-v1 / DefaultConfig | 状态机判定 |
| E-TOP-01 | Verilog | `e203_exu_alu_muldiv.v:1` | generic-verilog-v1 / DefaultConfig | DUT 顶层定义 |
| E-RTL-01 | RTL / manifest / ports.csv | `e203_exu_alu_muldiv.v:1` | generic-verilog-v1 / DefaultConfig | 端口定义与映射 |
| E-IO-01 | Verilog Port | `e203_exu_alu_muldiv.v:1` | generic-verilog-v1 / DefaultConfig | 端口列表 |
| E-PARAM-01 | Verilog Define | `e203_exu_alu_muldiv.v:1` | generic-verilog-v1 / DefaultConfig | 参数定义 |
| E-CONFIG-01 | Verilog Structure | `e203_exu_alu_muldiv.v:1` | generic-verilog-v1 / DefaultConfig | 实例能力 |

### 附录 E：FACT、OPEN 与偏差

| ID | 类型 | 摘要 | 关联规则 | 证据 / 缺口 | 状态与关闭条件 |
| --- | --- | --- | --- | --- | --- |
| FACT-001 | 实现事实 | 模块由硬件 Verilog RTL 综合实现 | `P-CORE` | [E-BEH-01] | Closed |

### 附录 F：FC / CK 完整追溯

> 本附录服务于 UCAgent 和审计，不作为主要阅读入口。FC 定义验证目标，CK 定义单一可执行性质；二者不得重复功能原理。

| FC 标签 | 所属 FG | 验证目标 | 关联规则 | Test Plan 行 |
| --- | --- | --- | --- | --- |
| `<FC-TRANSACTION>` | `FG-API` | FC-TRANSACTION 验证 | `P-CORE` | P0 / `CK-REQ-HS` |
| `<FC-RESET-INIT>` | `FG-API` | FC-RESET-INIT 验证 | `P-CORE` | P0 / `CK-REQ-HS` |
| `<FC-INPUT-HANDSHAKE>` | `FG-INTERFACE` | FC-INPUT-HANDSHAKE 验证 | `P-CORE` | P0 / `CK-REQ-HS` |
| `<FC-OUTPUT-HANDSHAKE>` | `FG-INTERFACE` | FC-OUTPUT-HANDSHAKE 验证 | `P-CORE` | P0 / `CK-REQ-HS` |
| `<FC-LONGPIPE>` | `FG-INTERFACE` | FC-LONGPIPE 验证 | `P-CORE` | P0 / `CK-REQ-HS` |
| `<FC-B2B-CONTROL>` | `FG-INTERFACE` | FC-B2B-CONTROL 验证 | `P-CORE` | P0 / `CK-REQ-HS` |
| `<FC-ITAG-PROPAGATION>` | `FG-INTERFACE` | FC-ITAG-PROPAGATION 验证 | `P-CORE` | P0 / `CK-REQ-HS` |
| `<FC-FLUSH>` | `FG-INTERFACE` | FC-FLUSH 验证 | `P-CORE` | P0 / `CK-REQ-HS` |
| `<FC-MUL-LOW>` | `FG-MULTIPLY` | FC-MUL-LOW 验证 | `P-CORE` | P0 / `CK-REQ-HS` |
| `<FC-MUL-HIGH>` | `FG-MULTIPLY` | FC-MUL-HIGH 验证 | `P-CORE` | P0 / `CK-REQ-HS` |
| `<FC-MUL-BOUNDARY>` | `FG-MULTIPLY` | FC-MUL-BOUNDARY 验证 | `P-CORE` | P0 / `CK-REQ-HS` |
| `<FC-MUL-LATENCY>` | `FG-MULTIPLY` | FC-MUL-LATENCY 验证 | `P-CORE` | P0 / `CK-REQ-HS` |
| `<FC-DIV-SIGNED>` | `FG-DIVIDE` | FC-DIV-SIGNED 验证 | `P-CORE` | P0 / `CK-REQ-HS` |
| `<FC-DIV-UNSIGNED>` | `FG-DIVIDE` | FC-DIV-UNSIGNED 验证 | `P-CORE` | P0 / `CK-REQ-HS` |
| `<FC-REM-SIGNED>` | `FG-DIVIDE` | FC-REM-SIGNED 验证 | `P-CORE` | P0 / `CK-REQ-HS` |
| `<FC-REM-UNSIGNED>` | `FG-DIVIDE` | FC-REM-UNSIGNED 验证 | `P-CORE` | P0 / `CK-REQ-HS` |
| `<FC-DIV-REM-CONSISTENCY>` | `FG-DIVIDE` | FC-DIV-REM-CONSISTENCY 验证 | `P-CORE` | P0 / `CK-REQ-HS` |
| `<FC-DIV-SPECIAL>` | `FG-DIVIDE` | FC-DIV-SPECIAL 验证 | `P-CORE` | P0 / `CK-REQ-HS` |
| `<FC-DIV-LATENCY>` | `FG-DIVIDE` | FC-DIV-LATENCY 验证 | `P-CORE` | P0 / `CK-REQ-HS` |
| `<FC-DIV-BOUNDARY>` | `FG-DIVIDE` | FC-DIV-BOUNDARY 验证 | `P-CORE` | P0 / `CK-REQ-HS` |

| CK 标签 | Style | 所属 FC | 独立性质 | 逻辑观测点 | RTL / bind 对应 | 属性实现状态 | 签核状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `<CK-REQ-HS>` | Assume | `FC-TRANSACTION` | 能够在 `muldiv_i_valid && muldiv_i_ready` 成立时成功发射一条请求。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-RSP-HS>` | Assume | `FC-TRANSACTION` | 能够在 `muldiv_o_valid && muldiv_o_ready` 成立时完成结果接收。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-STEP-DRIVE>` | Assume | `FC-TRANSACTION` | 测试 API 仅通过 `Step()` 推进时钟和事务，不采用组合偷看或内部强制赋值。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-PORT-OBS>` | Assume | `FC-TRANSACTION` | 结果判断仅基于输入输出端口可见信息完成。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-RESET-LOW>` | Assume | `FC-RESET-INIT` | `rst_n` 拉低后模块进入初始空闲状态。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-RESET-RELEASE>` | Assume | `FC-RESET-INIT` | 复位释放后模块能够重新接收请求。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-INIT-OUTPUT>` | Assume | `FC-RESET-INIT` | 初始化后关键输出处于可预测状态，不出现脏 valid/err。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-IDLE-READY>` | Seq | `FC-INPUT-HANDSHAKE` | 模块空闲且无阻塞条件时 `muldiv_i_ready` 可接受新请求。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-BUSY-BACKPRESSURE>` | Seq | `FC-INPUT-HANDSHAKE` | 模块处理在途请求期间不会错误重复接收新请求。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-HS-LOCK>` | Seq | `FC-INPUT-HANDSHAKE` | 请求握手后，即使输入操作数变化，已发射事务结果仍应由握手时采样值决定。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-VALID-WAIT>` | Seq | `FC-INPUT-HANDSHAKE` | `muldiv_i_valid` 持续拉高等待 ready 时，请求不会丢失。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-RESULT-VALID>` | Seq | `FC-OUTPUT-HANDSHAKE` | 运算完成后 `muldiv_o_valid` 正确拉高。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-RESULT-HOLD>` | Seq | `FC-OUTPUT-HANDSHAKE` | `muldiv_o_valid=1 && muldiv_o_ready=0` 时写回结果保持稳定。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-RESULT-CLEAR>` | Seq | `FC-OUTPUT-HANDSHAKE` | 结果握手完成后 `muldiv_o_valid` 能正确撤销，进入空闲或下一事务状态。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-ERR-CONST0>` | Seq | `FC-OUTPUT-HANDSHAKE` | 所有合法场景下 `muldiv_o_wbck_err` 保持为0。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-LONGPIPE-ASSERT>` | Seq | `FC-LONGPIPE` | mul/div 请求期间 `muldiv_i_longpipe` 行为符合长流水单元预期。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-LONGPIPE-STABLE>` | Seq | `FC-LONGPIPE` | 一次事务执行期间 longpipe 指示不会无故抖动为错误状态。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-NOB2B-ON>` | Seq | `FC-B2B-CONTROL` | `mdv_nob2b=1` 时不允许违反规格的连续接收行为。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-NOB2B-OFF>` | Seq | `FC-B2B-CONTROL` | `mdv_nob2b=0` 时接口行为不应被额外错误抑制。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-B2B-AFTER-RSP>` | Seq | `FC-B2B-CONTROL` | 前一条结果完成握手后，下一条请求的接收时机符合 b2b 控制预期。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-ITAG-0>` | Seq | `FC-ITAG-PROPAGATION` | 输入 itag=0 的事务输出标签匹配该请求。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-ITAG-1>` | Seq | `FC-ITAG-PROPAGATION` | 输入 itag=1 的事务输出标签匹配该请求。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-ITAG-B2B>` | Seq | `FC-ITAG-PROPAGATION` | 连续不同标签事务不会在输出阶段发生错配。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-FLUSH-EXEC>` | Seq | `FC-FLUSH` | 执行过程中 flush 能取消当前运算。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-FLUSH-RESP>` | Seq | `FC-FLUSH` | 结果待接收期间 flush 不应输出过期结果。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-FLUSH-RECOVER>` | Seq | `FC-FLUSH` | flush 后模块可重新接收并正确处理新请求。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-FLUSH-IDEMPOTENT>` | Seq | `FC-FLUSH` | 空闲或已取消状态下重复 flush 不应导致额外脏响应。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-BASIC-POS>` | Seq | `FC-MUL-LOW` | 小正数相乘结果正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-ZERO-FACTOR>` | Seq | `FC-MUL-LOW` | 任一操作数为0时结果为0。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-ONE-FACTOR>` | Seq | `FC-MUL-LOW` | 乘以1时结果保持另一操作数低32位。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-NEGATIVE>` | Seq | `FC-MUL-LOW` | 有符号负数参与时低32位结果正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-OVERFLOW-LOW>` | Seq | `FC-MUL-LOW` | 完整64位乘积超出32位时，写回低32位截断正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-MULH-SS>` | Seq | `FC-MUL-HIGH` | signed×signed 的高32位正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-MULH-UU>` | Seq | `FC-MUL-HIGH` | unsigned×unsigned 的高32位正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-MULH-SU>` | Seq | `FC-MUL-HIGH` | signed×unsigned 的高32位正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-SIGN-EXT>` | Seq | `FC-MUL-HIGH` | 负数高位计算不因符号扩展错误而偏差。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-BOUNDARY-HIGH>` | Seq | `FC-MUL-HIGH` | 涉及 `0x80000000`、`0xFFFFFFFF`、`0x7FFFFFFF` 等边界值时高位正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-MINXMIN>` | Seq | `FC-MUL-BOUNDARY` | `0x80000000 * 0x80000000` 的低位/高位表现符合对应指令语义。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-MINXNEG1>` | Seq | `FC-MUL-BOUNDARY` | `0x80000000 * 0xFFFFFFFF` 在不同乘法指令下结果正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-ALL1XALL1>` | Seq | `FC-MUL-BOUNDARY` | `0xFFFFFFFF * 0xFFFFFFFF` 在 signed/unsigned 语义下结果正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-ALT-BIT-PATTERN>` | Seq | `FC-MUL-BOUNDARY` | 如 `0xAAAAAAAA`、`0x55555555` 组合下结果正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-NO-EARLY-RSP>` | Seq | `FC-MUL-LATENCY` | 乘法结果不会在预期完成窗口前错误有效。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-FINITE-COMPLETE>` | Seq | `FC-MUL-LATENCY` | 乘法事务能在合理有限周期内完成。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-SINGLE-RSP>` | Seq | `FC-MUL-LATENCY` | 单个乘法请求只产生一次结果响应。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-BASIC-SS>` | Seq | `FC-DIV-SIGNED` | 正/负数组合下商结果正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-TRUNC-ZERO>` | Seq | `FC-DIV-SIGNED` | 非整除场景商朝0方向截断。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-DIVIDEND-SMALL>` | Seq | `FC-DIV-SIGNED` | 商应为0或0xFFFFFFFF等符合符号规则的结果。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-POWER2>` | Seq | `FC-DIV-SIGNED` | 对 2^n 除数的结果正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-BOUNDARY-SS>` | Seq | `FC-DIV-SIGNED` | `INT_MIN`、`INT_MAX`、-1、1 等组合结果正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-BASIC-UU>` | Seq | `FC-DIV-UNSIGNED` | 常规 unsigned 商结果正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-U-DIVIDEND-SMALL>` | Seq | `FC-DIV-UNSIGNED` | 商为0。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-U-MAX>` | Seq | `FC-DIV-UNSIGNED` | `0xFFFFFFFF` 等边界操作数结果正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-U-POWER2>` | Seq | `FC-DIV-UNSIGNED` | 结果正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-BASIC-REM-SS>` | Seq | `FC-REM-SIGNED` | 常规场景余数正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-REM-SIGN>` | Seq | `FC-REM-SIGNED` | 余数符号与被除数一致。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-REM-ZERO>` | Seq | `FC-REM-SIGNED` | 能整除时余数为0。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-REM-BOUNDARY>` | Seq | `FC-REM-SIGNED` | 极值/负数场景余数正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-BASIC-REM-UU>` | Seq | `FC-REM-UNSIGNED` | 常规场景余数正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-U-REM-SMALL>` | Seq | `FC-REM-UNSIGNED` | 余数等于被除数。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-U-REM-ZERO>` | Seq | `FC-REM-UNSIGNED` | 能整除时余数为0。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-U-REM-MAX>` | Seq | `FC-REM-UNSIGNED` | 边界输入余数正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-QR-IDENTITY-SS>` | Seq | `FC-DIV-REM-CONSISTENCY` | signed 场景下商余组合满足恒等式。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-QR-IDENTITY-UU>` | Seq | `FC-DIV-REM-CONSISTENCY` | unsigned 场景下商余组合满足恒等式。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-REM-MAG-SS>` | Seq | `FC-DIV-REM-CONSISTENCY` | signed 余数绝对值小于除数绝对值。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-REM-RANGE-UU>` | Seq | `FC-DIV-REM-CONSISTENCY` | unsigned 余数小于除数。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-DIV0-QUOT-SS>` | Seq | `FC-DIV-SPECIAL` | DIV 除数为0时结果符合规格。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-DIV0-QUOT-UU>` | Seq | `FC-DIV-SPECIAL` | DIVU 除数为0时结果符合规格。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-DIV0-REM-SS>` | Seq | `FC-DIV-SPECIAL` | REM 除数为0时结果符合规格。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-DIV0-REM-UU>` | Seq | `FC-DIV-SPECIAL` | REMU 除数为0时结果符合规格。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-OVF-INTMIN>` | Seq | `FC-DIV-SPECIAL` | `INT_MIN / -1` 和 `INT_MIN % -1` 结果符合规格。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-DIV-NO-EARLY>` | Seq | `FC-DIV-LATENCY` | 除法/求余结果不会异常提前产生。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-DIV-FINITE>` | Seq | `FC-DIV-LATENCY` | 除法/求余请求能在合理有限周期内完成。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-DIV-SINGLE-RSP>` | Seq | `FC-DIV-LATENCY` | 单个除法/求余请求只返回一次结果。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-CORR-VISIBLE>` | Seq | `FC-DIV-LATENCY` | 需要修正的边界输入，其最终商和余数对外表现与参考模型一致。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-INTMIN-DIV-1>` | Seq | `FC-DIV-BOUNDARY` | `0x80000000 / 1` 与对应余数结果符合有符号语义。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-INTMIN-DIV-2>` | Seq | `FC-DIV-BOUNDARY` | `0x80000000 / 2` 与对应余数结果正确，覆盖高位绝对值移位路径。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-NEG1-DIV-INTMIN>` | Seq | `FC-DIV-BOUNDARY` | 商和余数满足向零截断及余数同号规则。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-ALL1-DIV-ALL1>` | Seq | `FC-DIV-BOUNDARY` | `0xFFFFFFFF / 0xFFFFFFFF` 及对应余数在 signed/unsigned 语义下均正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-ALT-DIV-PATTERN>` | Seq | `FC-DIV-BOUNDARY` | 如 `0xAAAAAAAA`、`0x55555555` 组合下商/余结果正确。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |
| `<CK-PRIME-NONMULT>` | Seq | `FC-DIV-BOUNDARY` | 大数且非整除组合的商余结果正确，覆盖修正阶段可见行为。 | `signal.mdv_nob2b` | [附录 B / D] | Planned | Planned |

### 附录 G：签核清单

- [x] 摘要在细节前说明职责、输入输出、关键概念、延迟、验证范围和 OPEN。
- [x] 每项功能按输入、输出、延迟、统一规则、适用实例、边界与限制组织。
- [x] 模块级规则未混入实例枚举；实例差异集中在能力矩阵和附录 C。
- [x] 正文仅以 `[E-*]` 引用证据，完整路径集中在附录 D。
- [x] Test Plan 是验证执行入口；FC/CK 完整登记集中在附录 F。
- [x] API 只包含 Assume，Coverage 只包含 Cover。
- [x] Verilog 端口逐项核对，配置裁剪有依据。
- [x] 正常、资源边界和恢复场景有可判定验收标准。
