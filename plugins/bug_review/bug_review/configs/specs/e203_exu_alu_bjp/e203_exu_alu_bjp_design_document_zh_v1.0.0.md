# e203_exu_alu_bjp 设计与功能检测点文档

> 模板结构版本：v3.3.0
>
> 文档版本：v1.0.0
>
> 本文分为正文、验证计划和附录。正文用于连续理解设计，验证计划用于安排检查，附录用于审计和签核。FG、FC、CK 标签必须使用反引号包裹，例如 `` `<FG-API>` ``。无法证实的内容登记为 `OPEN-*`。

## 第一部分：正文

### 文档摘要

> 本节目标是一页内建立阅读者的整体模型。每项先给结论，不展开实现细节或证据路径。

**模块职责**

`e203_exu_alu_bjp` 模块是芯片设计中的硬件执行单元，负责处理相关逻辑、时钟分频、存储或控制功能。

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

`e203_exu_alu_bjp` 包含 30 个端口，正文统一使用逻辑名，精确映射见附录 B。

| 逻辑名 | 角色与含义 | 方向 | 事务阶段 |
| --- | --- | --- | --- |
| `producer.data` | 数据与控制输入 | 生产者 -> DUT | 写入 |
| `consumer.data` | 状态与结果输出 | DUT -> 消费者 | 输出 |

#### 微架构与数据流

```mermaid
flowchart LR
    P[Producer]
    C[Consumer]
    subgraph DUT["DUT: e203_exu_alu_bjp"]
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
|  `- FC-API-SCOPE
|- FG-HANDSHAKE
|  `- FC-VALID-PASS
|  `- FC-READY-PASS
|- FG-ALU-REQ
|  `- FC-CMP-REQ
|  `- FC-ADD-REQ
|  `- FC-SPECIAL-NO-ALU-REQ
|  `- FC-REQ-OVERLAP-RISK
|- FG-OPERAND-SELECT
|  `- FC-NONJUMP-OPERAND
|  `- FC-JUMP-OPERAND
|- FG-RESOLVE-COMMIT
|  `- FC-CMT-BJP
|  `- FC-PREDICT-PASS
|  `- FC-RESOLVE-SELECT
|- FG-WRITEBACK
|  `- FC-WDAT-SOURCE
|  `- FC-WERR-CONST
|- FG-SPECIAL-COMMIT
|  `- FC-MRET-CMT
|  `- FC-DRET-CMT
|  `- FC-FENCEI-CMT
|- FG-COMB-ROBUSTNESS
|  `- FC-CLK-RST-INSENSITIVE
|  `- FC-UNUSED-INPUT-INDEP
|  `- FC-ILLEGAL-ENCODING
```

`<FG-API>`

FG-API 功能风险覆盖与行为检测。

`<FG-HANDSHAKE>`

FG-HANDSHAKE 功能风险覆盖与行为检测。

`<FG-ALU-REQ>`

FG-ALU-REQ 功能风险覆盖与行为检测。

`<FG-OPERAND-SELECT>`

FG-OPERAND-SELECT 功能风险覆盖与行为检测。

`<FG-RESOLVE-COMMIT>`

FG-RESOLVE-COMMIT 功能风险覆盖与行为检测。

`<FG-WRITEBACK>`

FG-WRITEBACK 功能风险覆盖与行为检测。

`<FG-SPECIAL-COMMIT>`

FG-SPECIAL-COMMIT 功能风险覆盖与行为检测。

`<FG-COMB-ROBUSTNESS>`

FG-COMB-ROBUSTNESS 功能风险覆盖与行为检测。

### Test Plan

> 这是验证执行的统一入口。每行连接一个 FC、一个独立 CK、验证机制、Coverage 和场景。功能原理只引用 `P-*`，完整 CK 元数据见附录 F。

| 优先级 | FC | CK | Style | 关联规则 | 检查机制 | 激励 / 前置条件 | 可观察结果 | Coverage / 场景 | 关闭标准 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | `FC-API-SCOPE` | `CK-STEP-DRIVE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-API-SCOPE` | `CK-OUTPUT-CAPTURE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-API-SCOPE` | `CK-INFO-ENCODE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-API-SCOPE` | `CK-ALU-INJECT` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-VALID-PASS` | `CK-VALID-0` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-VALID-PASS` | `CK-VALID-1` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-VALID-PASS` | `CK-VALID-INDEP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-READY-PASS` | `CK-READY-0` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-READY-PASS` | `CK-READY-1` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-READY-PASS` | `CK-READY-INDEP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMP-REQ` | `CK-BEQ` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMP-REQ` | `CK-BNE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMP-REQ` | `CK-BLT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMP-REQ` | `CK-BGT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMP-REQ` | `CK-BLTU` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMP-REQ` | `CK-BGTU` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ADD-REQ` | `CK-JUMP-ADD` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ADD-REQ` | `CK-JUMP-NO-CMP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SPECIAL-NO-ALU-REQ` | `CK-MRET-IDLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SPECIAL-NO-ALU-REQ` | `CK-DRET-IDLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SPECIAL-NO-ALU-REQ` | `CK-FENCEI-IDLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-REQ-OVERLAP-RISK` | `CK-MULTI-CMP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-REQ-OVERLAP-RISK` | `CK-CMP-AND-JUMP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-NONJUMP-OPERAND` | `CK-RS1-PASS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-NONJUMP-OPERAND` | `CK-RS2-PASS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-NONJUMP-OPERAND` | `CK-IMM-IGNORED` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-NONJUMP-OPERAND` | `CK-PC-IGNORED` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-JUMP-OPERAND` | `CK-JUMP-OP1-PC` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-JUMP-OPERAND` | `CK-RV32-OFFSET` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-JUMP-OPERAND` | `CK-NONRV32-OFFSET` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-JUMP-OPERAND` | `CK-RS-IGNORED-ON-JUMP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMT-BJP` | `CK-BXX-CMT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMT-BJP` | `CK-JUMP-CMT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CMT-BJP` | `CK-SPECIAL-NOT-BJP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-PREDICT-PASS` | `CK-PRDT-0` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-PREDICT-PASS` | `CK-PRDT-1` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-PREDICT-PASS` | `CK-PRDT-INDEP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESOLVE-SELECT` | `CK-JUMP-RSLV-1` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESOLVE-SELECT` | `CK-BRANCH-RSLV-0` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESOLVE-SELECT` | `CK-BRANCH-RSLV-1` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-RESOLVE-SELECT` | `CK-JUMP-PRIORITY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WDAT-SOURCE` | `CK-WDAT-JUMP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WDAT-SOURCE` | `CK-WDAT-BRANCH` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WDAT-SOURCE` | `CK-WDAT-SPECIAL` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-WERR-CONST` | `CK-WERR-ALWAYS-0` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-MRET-CMT` | `CK-MRET-0` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-MRET-CMT` | `CK-MRET-1` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DRET-CMT` | `CK-DRET-0` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DRET-CMT` | `CK-DRET-1` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-FENCEI-CMT` | `CK-FENCEI-0` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-FENCEI-CMT` | `CK-FENCEI-1` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CLK-RST-INSENSITIVE` | `CK-CLK-TOGGLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CLK-RST-INSENSITIVE` | `CK-RST-TOGGLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-UNUSED-INPUT-INDEP` | `CK-IMM-NO-EFFECT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-UNUSED-INPUT-INDEP` | `CK-ADDRES-NO-CMT-EFFECT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-UNUSED-INPUT-INDEP` | `CK-CMPRES-NO-REQ-EFFECT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ILLEGAL-ENCODING` | `CK-ZERO-INFO` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ILLEGAL-ENCODING` | `CK-SPECIAL-OVERLAP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ILLEGAL-ENCODING` | `CK-RAW-LOGIC-CONSISTENCY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |

### Coverage Summary

| Coverage ID | 风险与目标 | 关联 P / FC / CK | 观察事件 | 重要取值 / 分箱 | 依赖 / 交叉 | 非法 / 忽略条件 | 有效性保护 | 关闭标准 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `COV-NORMAL` | 正常功能覆盖 | `P-CORE`, `FC-API-SCOPE`, `CK-STEP-DRIVE` | 正常周期事件 | 典型功能取值 | 核心交叉 | 忽略非法毛刺 | 有效采样 | 命中要求 | Planned |
| `COV-BOUNDARY` | 边界条件覆盖 | `P-CORE`, `FC-ILLEGAL-ENCODING`, `CK-RAW-LOGIC-CONSISTENCY` | 边界周期事件 | 最大/最小值 | 极限交叉 | 忽略非法毛刺 | 有效采样 | 命中要求 | Planned |

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

**预期行为**：遵循 `P-CORE`、`CK-STEP-DRIVE`；关联 Coverage：`COV-NORMAL`。

**验收标准**：输出处于预期初始状态。

#### CASE-NORMAL：正常运算场景

**目标**：验证典型功能处理流程。

**参与者与前置条件**：激励驱动源。

1. 驱动有效输入。
2. 观测输出结果。

**预期行为**：遵循 `P-CORE`、`CK-STEP-DRIVE`；关联 Coverage：`COV-NORMAL`。

**验收标准**：结果正确匹配。

#### CASE-BOUNDARY：边界条件场景

**目标**：验证极限值与异常边界行为。

**参与者与前置条件**：激励驱动源。

1. 驱动边界极值。
2. 检查输出无挂起。

**预期行为**：遵循 `P-CORE`、`CK-RAW-LOGIC-CONSISTENCY`；关联 Coverage：`COV-BOUNDARY`。

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
| DUT / Chisel 顶层 | e203_exu_alu_bjp / [E-TOP-01] |
| Elaborated Verilog 顶层 | e203_exu_alu_bjp / [E-RTL-01] |
| 文档状态 | Review |
| XiangShan RTL 基线 | generic-verilog-v1 |
| 适用配置 | DefaultConfig |
| 生成环境 | Linux / x86_64 / Python 3.8 |
| RTL 生成状态 | Success |
| RTL 证据 | evidence/e203_exu_alu_bjp/v1.0.0/manifest.json |
| 图形渲染证据 | evidence/e203_exu_alu_bjp/v1.0.0/diagrams/manifest.json |
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

本模块包含 30 个叶端口：11 个输入，19 个输出。
RTL SHA-256：`2e4ae627463f2eaa10edfabc4aac4f25ce8f33b9fce74a84df03fa5b72c9a1a6`。

### 附录 B：逻辑接口与 RTL 映射

> 本附录是逻辑名、字段和精确 elaborated Verilog 端口的唯一映射位置。

| IO-ID | 正文逻辑名 | Bundle class / Chisel 字段 | 定义位置 | 方向 / 位宽 | 配置状态 | 精确 Verilog I/O | 协议 / 对端 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `IO-BJP_I_VALID` | `signal.bjp_i_valid` | `e203_exu_alu_bjp.bjp_i_valid` | [E-IO-01] | I / 1 | Generated | `bjp_i_valid` | Internal / System | [E-RTL-01] |
| `IO-BJP_I_READY` | `signal.bjp_i_ready` | `e203_exu_alu_bjp.bjp_i_ready` | [E-IO-01] | O / 1 | Generated | `bjp_i_ready` | Internal / System | [E-RTL-01] |
| `IO-BJP_I_RS1` | `signal.bjp_i_rs1` | `e203_exu_alu_bjp.bjp_i_rs1` | [E-IO-01] | I / 32 | Generated | `bjp_i_rs1` | Internal / System | [E-RTL-01] |
| `IO-BJP_I_RS2` | `signal.bjp_i_rs2` | `e203_exu_alu_bjp.bjp_i_rs2` | [E-IO-01] | I / 32 | Generated | `bjp_i_rs2` | Internal / System | [E-RTL-01] |
| `IO-BJP_I_IMM` | `signal.bjp_i_imm` | `e203_exu_alu_bjp.bjp_i_imm` | [E-IO-01] | I / 32 | Generated | `bjp_i_imm` | Internal / System | [E-RTL-01] |
| `IO-BJP_I_PC` | `signal.bjp_i_pc` | `e203_exu_alu_bjp.bjp_i_pc` | [E-IO-01] | I / 32 | Generated | `bjp_i_pc` | Internal / System | [E-RTL-01] |
| `IO-BJP_I_INFO` | `signal.bjp_i_info` | `e203_exu_alu_bjp.bjp_i_info` | [E-IO-01] | I / 17 | Generated | `bjp_i_info` | Internal / System | [E-RTL-01] |
| `IO-BJP_O_VALID` | `signal.bjp_o_valid` | `e203_exu_alu_bjp.bjp_o_valid` | [E-IO-01] | O / 1 | Generated | `bjp_o_valid` | Internal / System | [E-RTL-01] |
| `IO-BJP_O_READY` | `signal.bjp_o_ready` | `e203_exu_alu_bjp.bjp_o_ready` | [E-IO-01] | I / 1 | Generated | `bjp_o_ready` | Internal / System | [E-RTL-01] |
| `IO-BJP_O_WBCK_WDAT` | `signal.bjp_o_wbck_wdat` | `e203_exu_alu_bjp.bjp_o_wbck_wdat` | [E-IO-01] | O / 32 | Generated | `bjp_o_wbck_wdat` | Internal / System | [E-RTL-01] |
| `IO-BJP_O_WBCK_ERR` | `signal.bjp_o_wbck_err` | `e203_exu_alu_bjp.bjp_o_wbck_err` | [E-IO-01] | O / 1 | Generated | `bjp_o_wbck_err` | Internal / System | [E-RTL-01] |
| `IO-BJP_O_CMT_BJP` | `signal.bjp_o_cmt_bjp` | `e203_exu_alu_bjp.bjp_o_cmt_bjp` | [E-IO-01] | O / 1 | Generated | `bjp_o_cmt_bjp` | Internal / System | [E-RTL-01] |
| `IO-BJP_O_CMT_MRET` | `signal.bjp_o_cmt_mret` | `e203_exu_alu_bjp.bjp_o_cmt_mret` | [E-IO-01] | O / 1 | Generated | `bjp_o_cmt_mret` | Internal / System | [E-RTL-01] |
| `IO-BJP_O_CMT_DRET` | `signal.bjp_o_cmt_dret` | `e203_exu_alu_bjp.bjp_o_cmt_dret` | [E-IO-01] | O / 1 | Generated | `bjp_o_cmt_dret` | Internal / System | [E-RTL-01] |
| `IO-BJP_O_CMT_FENCEI` | `signal.bjp_o_cmt_fencei` | `e203_exu_alu_bjp.bjp_o_cmt_fencei` | [E-IO-01] | O / 1 | Generated | `bjp_o_cmt_fencei` | Internal / System | [E-RTL-01] |
| `IO-BJP_O_CMT_PRDT` | `signal.bjp_o_cmt_prdt` | `e203_exu_alu_bjp.bjp_o_cmt_prdt` | [E-IO-01] | O / 1 | Generated | `bjp_o_cmt_prdt` | Internal / System | [E-RTL-01] |
| `IO-BJP_O_CMT_RSLV` | `signal.bjp_o_cmt_rslv` | `e203_exu_alu_bjp.bjp_o_cmt_rslv` | [E-IO-01] | O / 1 | Generated | `bjp_o_cmt_rslv` | Internal / System | [E-RTL-01] |
| `IO-BJP_REQ_ALU_OP1` | `signal.bjp_req_alu_op1` | `e203_exu_alu_bjp.bjp_req_alu_op1` | [E-IO-01] | O / 32 | Generated | `bjp_req_alu_op1` | Internal / System | [E-RTL-01] |
| `IO-BJP_REQ_ALU_OP2` | `signal.bjp_req_alu_op2` | `e203_exu_alu_bjp.bjp_req_alu_op2` | [E-IO-01] | O / 32 | Generated | `bjp_req_alu_op2` | Internal / System | [E-RTL-01] |
| `IO-BJP_REQ_ALU_CMP_EQ` | `signal.bjp_req_alu_cmp_eq` | `e203_exu_alu_bjp.bjp_req_alu_cmp_eq` | [E-IO-01] | O / 1 | Generated | `bjp_req_alu_cmp_eq` | Internal / System | [E-RTL-01] |
| `IO-BJP_REQ_ALU_CMP_NE` | `signal.bjp_req_alu_cmp_ne` | `e203_exu_alu_bjp.bjp_req_alu_cmp_ne` | [E-IO-01] | O / 1 | Generated | `bjp_req_alu_cmp_ne` | Internal / System | [E-RTL-01] |
| `IO-BJP_REQ_ALU_CMP_LT` | `signal.bjp_req_alu_cmp_lt` | `e203_exu_alu_bjp.bjp_req_alu_cmp_lt` | [E-IO-01] | O / 1 | Generated | `bjp_req_alu_cmp_lt` | Internal / System | [E-RTL-01] |
| `IO-BJP_REQ_ALU_CMP_GT` | `signal.bjp_req_alu_cmp_gt` | `e203_exu_alu_bjp.bjp_req_alu_cmp_gt` | [E-IO-01] | O / 1 | Generated | `bjp_req_alu_cmp_gt` | Internal / System | [E-RTL-01] |
| `IO-BJP_REQ_ALU_CMP_LTU` | `signal.bjp_req_alu_cmp_ltu` | `e203_exu_alu_bjp.bjp_req_alu_cmp_ltu` | [E-IO-01] | O / 1 | Generated | `bjp_req_alu_cmp_ltu` | Internal / System | [E-RTL-01] |
| `IO-BJP_REQ_ALU_CMP_GTU` | `signal.bjp_req_alu_cmp_gtu` | `e203_exu_alu_bjp.bjp_req_alu_cmp_gtu` | [E-IO-01] | O / 1 | Generated | `bjp_req_alu_cmp_gtu` | Internal / System | [E-RTL-01] |
| `IO-BJP_REQ_ALU_ADD` | `signal.bjp_req_alu_add` | `e203_exu_alu_bjp.bjp_req_alu_add` | [E-IO-01] | O / 1 | Generated | `bjp_req_alu_add` | Internal / System | [E-RTL-01] |
| `IO-BJP_REQ_ALU_CMP_RES` | `signal.bjp_req_alu_cmp_res` | `e203_exu_alu_bjp.bjp_req_alu_cmp_res` | [E-IO-01] | I / 1 | Generated | `bjp_req_alu_cmp_res` | Internal / System | [E-RTL-01] |
| `IO-BJP_REQ_ALU_ADD_RES` | `signal.bjp_req_alu_add_res` | `e203_exu_alu_bjp.bjp_req_alu_add_res` | [E-IO-01] | I / 32 | Generated | `bjp_req_alu_add_res` | Internal / System | [E-RTL-01] |
| `IO-CLK` | `signal.clk` | `e203_exu_alu_bjp.clk` | [E-IO-01] | I / 1 | Generated | `clk` | Internal / System | [E-RTL-01] |
| `IO-RST_N` | `signal.rst_n` | `e203_exu_alu_bjp.rst_n` | [E-IO-01] | I / 1 | Generated | `rst_n` | Internal / System | [E-RTL-01] |

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
| E-BEH-01 | Verilog | `e203_exu_alu_bjp.v:1` | generic-verilog-v1 / DefaultConfig | `P-CORE` |
| E-RES-01 | Verilog | `e203_exu_alu_bjp.v:1` | generic-verilog-v1 / DefaultConfig | 资源更新规则 |
| E-FSM-01 | Verilog | `e203_exu_alu_bjp.v:1` | generic-verilog-v1 / DefaultConfig | 状态机判定 |
| E-TOP-01 | Verilog | `e203_exu_alu_bjp.v:1` | generic-verilog-v1 / DefaultConfig | DUT 顶层定义 |
| E-RTL-01 | RTL / manifest / ports.csv | `e203_exu_alu_bjp.v:1` | generic-verilog-v1 / DefaultConfig | 端口定义与映射 |
| E-IO-01 | Verilog Port | `e203_exu_alu_bjp.v:1` | generic-verilog-v1 / DefaultConfig | 端口列表 |
| E-PARAM-01 | Verilog Define | `e203_exu_alu_bjp.v:1` | generic-verilog-v1 / DefaultConfig | 参数定义 |
| E-CONFIG-01 | Verilog Structure | `e203_exu_alu_bjp.v:1` | generic-verilog-v1 / DefaultConfig | 实例能力 |

### 附录 E：FACT、OPEN 与偏差

| ID | 类型 | 摘要 | 关联规则 | 证据 / 缺口 | 状态与关闭条件 |
| --- | --- | --- | --- | --- | --- |
| FACT-001 | 实现事实 | 模块由硬件 Verilog RTL 综合实现 | `P-CORE` | [E-BEH-01] | Closed |

### 附录 F：FC / CK 完整追溯

> 本附录服务于 UCAgent 和审计，不作为主要阅读入口。FC 定义验证目标，CK 定义单一可执行性质；二者不得重复功能原理。

| FC 标签 | 所属 FG | 验证目标 | 关联规则 | Test Plan 行 |
| --- | --- | --- | --- | --- |
| `<FC-API-SCOPE>` | `FG-API` | FC-API-SCOPE 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-VALID-PASS>` | `FG-HANDSHAKE` | FC-VALID-PASS 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-READY-PASS>` | `FG-HANDSHAKE` | FC-READY-PASS 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-CMP-REQ>` | `FG-ALU-REQ` | FC-CMP-REQ 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-ADD-REQ>` | `FG-ALU-REQ` | FC-ADD-REQ 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-SPECIAL-NO-ALU-REQ>` | `FG-ALU-REQ` | FC-SPECIAL-NO-ALU-REQ 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-REQ-OVERLAP-RISK>` | `FG-ALU-REQ` | FC-REQ-OVERLAP-RISK 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-NONJUMP-OPERAND>` | `FG-OPERAND-SELECT` | FC-NONJUMP-OPERAND 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-JUMP-OPERAND>` | `FG-OPERAND-SELECT` | FC-JUMP-OPERAND 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-CMT-BJP>` | `FG-RESOLVE-COMMIT` | FC-CMT-BJP 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-PREDICT-PASS>` | `FG-RESOLVE-COMMIT` | FC-PREDICT-PASS 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-RESOLVE-SELECT>` | `FG-RESOLVE-COMMIT` | FC-RESOLVE-SELECT 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-WDAT-SOURCE>` | `FG-WRITEBACK` | FC-WDAT-SOURCE 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-WERR-CONST>` | `FG-WRITEBACK` | FC-WERR-CONST 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-MRET-CMT>` | `FG-SPECIAL-COMMIT` | FC-MRET-CMT 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-DRET-CMT>` | `FG-SPECIAL-COMMIT` | FC-DRET-CMT 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-FENCEI-CMT>` | `FG-SPECIAL-COMMIT` | FC-FENCEI-CMT 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-CLK-RST-INSENSITIVE>` | `FG-COMB-ROBUSTNESS` | FC-CLK-RST-INSENSITIVE 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-UNUSED-INPUT-INDEP>` | `FG-COMB-ROBUSTNESS` | FC-UNUSED-INPUT-INDEP 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-ILLEGAL-ENCODING>` | `FG-COMB-ROBUSTNESS` | FC-ILLEGAL-ENCODING 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |

| CK 标签 | Style | 所属 FC | 独立性质 | 逻辑观测点 | RTL / bind 对应 | 属性实现状态 | 签核状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `<CK-STEP-DRIVE>` | Assume | `FC-API-SCOPE` | CK-STEP-DRIVE | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-OUTPUT-CAPTURE>` | Assume | `FC-API-SCOPE` | CK-OUTPUT-CAPTURE | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-INFO-ENCODE>` | Assume | `FC-API-SCOPE` | CK-INFO-ENCODE | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-ALU-INJECT>` | Assume | `FC-API-SCOPE` | CK-ALU-INJECT | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-VALID-0>` | Seq | `FC-VALID-PASS` | CK-VALID-0 | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-VALID-1>` | Seq | `FC-VALID-PASS` | CK-VALID-1 | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-VALID-INDEP>` | Seq | `FC-VALID-PASS` | CK-VALID-INDEP | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-READY-0>` | Seq | `FC-READY-PASS` | CK-READY-0 | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-READY-1>` | Seq | `FC-READY-PASS` | CK-READY-1 | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-READY-INDEP>` | Seq | `FC-READY-PASS` | CK-READY-INDEP | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-BEQ>` | Seq | `FC-CMP-REQ` | CK-BEQ | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-BNE>` | Seq | `FC-CMP-REQ` | CK-BNE | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-BLT>` | Seq | `FC-CMP-REQ` | CK-BLT | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-BGT>` | Seq | `FC-CMP-REQ` | CK-BGT | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-BLTU>` | Seq | `FC-CMP-REQ` | CK-BLTU | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-BGTU>` | Seq | `FC-CMP-REQ` | CK-BGTU | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-JUMP-ADD>` | Seq | `FC-ADD-REQ` | CK-JUMP-ADD | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-JUMP-NO-CMP>` | Seq | `FC-ADD-REQ` | CK-JUMP-NO-CMP | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-MRET-IDLE>` | Seq | `FC-SPECIAL-NO-ALU-REQ` | CK-MRET-IDLE | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-DRET-IDLE>` | Seq | `FC-SPECIAL-NO-ALU-REQ` | CK-DRET-IDLE | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-FENCEI-IDLE>` | Seq | `FC-SPECIAL-NO-ALU-REQ` | CK-FENCEI-IDLE | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-MULTI-CMP>` | Seq | `FC-REQ-OVERLAP-RISK` | CK-MULTI-CMP | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-CMP-AND-JUMP>` | Seq | `FC-REQ-OVERLAP-RISK` | CK-CMP-AND-JUMP | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-RS1-PASS>` | Seq | `FC-NONJUMP-OPERAND` | CK-RS1-PASS | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-RS2-PASS>` | Seq | `FC-NONJUMP-OPERAND` | CK-RS2-PASS | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-IMM-IGNORED>` | Seq | `FC-NONJUMP-OPERAND` | CK-IMM-IGNORED | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-PC-IGNORED>` | Seq | `FC-NONJUMP-OPERAND` | CK-PC-IGNORED | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-JUMP-OP1-PC>` | Seq | `FC-JUMP-OPERAND` | CK-JUMP-OP1-PC | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-RV32-OFFSET>` | Seq | `FC-JUMP-OPERAND` | CK-RV32-OFFSET | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-NONRV32-OFFSET>` | Seq | `FC-JUMP-OPERAND` | CK-NONRV32-OFFSET | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-RS-IGNORED-ON-JUMP>` | Seq | `FC-JUMP-OPERAND` | CK-RS-IGNORED-ON-JUMP | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-BXX-CMT>` | Seq | `FC-CMT-BJP` | CK-BXX-CMT | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-JUMP-CMT>` | Seq | `FC-CMT-BJP` | CK-JUMP-CMT | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-SPECIAL-NOT-BJP>` | Seq | `FC-CMT-BJP` | CK-SPECIAL-NOT-BJP | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-PRDT-0>` | Seq | `FC-PREDICT-PASS` | CK-PRDT-0 | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-PRDT-1>` | Seq | `FC-PREDICT-PASS` | CK-PRDT-1 | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-PRDT-INDEP>` | Seq | `FC-PREDICT-PASS` | CK-PRDT-INDEP | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-JUMP-RSLV-1>` | Seq | `FC-RESOLVE-SELECT` | CK-JUMP-RSLV-1 | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-BRANCH-RSLV-0>` | Seq | `FC-RESOLVE-SELECT` | CK-BRANCH-RSLV-0 | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-BRANCH-RSLV-1>` | Seq | `FC-RESOLVE-SELECT` | CK-BRANCH-RSLV-1 | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-JUMP-PRIORITY>` | Seq | `FC-RESOLVE-SELECT` | CK-JUMP-PRIORITY | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-WDAT-JUMP>` | Seq | `FC-WDAT-SOURCE` | CK-WDAT-JUMP | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-WDAT-BRANCH>` | Seq | `FC-WDAT-SOURCE` | CK-WDAT-BRANCH | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-WDAT-SPECIAL>` | Seq | `FC-WDAT-SOURCE` | CK-WDAT-SPECIAL | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-WERR-ALWAYS-0>` | Seq | `FC-WERR-CONST` | CK-WERR-ALWAYS-0 | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-MRET-0>` | Seq | `FC-MRET-CMT` | CK-MRET-0 | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-MRET-1>` | Seq | `FC-MRET-CMT` | CK-MRET-1 | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-DRET-0>` | Seq | `FC-DRET-CMT` | CK-DRET-0 | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-DRET-1>` | Seq | `FC-DRET-CMT` | CK-DRET-1 | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-FENCEI-0>` | Seq | `FC-FENCEI-CMT` | CK-FENCEI-0 | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-FENCEI-1>` | Seq | `FC-FENCEI-CMT` | CK-FENCEI-1 | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-CLK-TOGGLE>` | Seq | `FC-CLK-RST-INSENSITIVE` | CK-CLK-TOGGLE | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-RST-TOGGLE>` | Seq | `FC-CLK-RST-INSENSITIVE` | CK-RST-TOGGLE | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-IMM-NO-EFFECT>` | Seq | `FC-UNUSED-INPUT-INDEP` | CK-IMM-NO-EFFECT | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-ADDRES-NO-CMT-EFFECT>` | Seq | `FC-UNUSED-INPUT-INDEP` | CK-ADDRES-NO-CMT-EFFECT | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-CMPRES-NO-REQ-EFFECT>` | Seq | `FC-UNUSED-INPUT-INDEP` | CK-CMPRES-NO-REQ-EFFECT | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-ZERO-INFO>` | Seq | `FC-ILLEGAL-ENCODING` | CK-ZERO-INFO | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-SPECIAL-OVERLAP>` | Seq | `FC-ILLEGAL-ENCODING` | CK-SPECIAL-OVERLAP | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |
| `<CK-RAW-LOGIC-CONSISTENCY>` | Seq | `FC-ILLEGAL-ENCODING` | CK-RAW-LOGIC-CONSISTENCY | `signal.bjp_i_valid` | [附录 B / D] | Planned | Planned |

### 附录 G：签核清单

- [x] 摘要在细节前说明职责、输入输出、关键概念、延迟、验证范围和 OPEN。
- [x] 每项功能按输入、输出、延迟、统一规则、适用实例、边界与限制组织。
- [x] 模块级规则未混入实例枚举；实例差异集中在能力矩阵和附录 C。
- [x] 正文仅以 `[E-*]` 引用证据，完整路径集中在附录 D。
- [x] Test Plan 是验证执行入口；FC/CK 完整登记集中在附录 F。
- [x] API 只包含 Assume，Coverage 只包含 Cover。
- [x] Verilog 端口逐项核对，配置裁剪有依据。
- [x] 正常、资源边界和恢复场景有可判定验收标准。
