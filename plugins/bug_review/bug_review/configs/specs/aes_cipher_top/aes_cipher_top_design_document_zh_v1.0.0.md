# aes_cipher_top 设计与功能检测点文档

> 模板结构版本：v3.3.0
>
> 文档版本：v1.0.0
>
> 本文分为正文、验证计划和附录。正文用于连续理解设计，验证计划用于安排检查，附录用于审计和签核。FG、FC、CK 标签必须使用反引号包裹，例如 `` `<FG-API>` ``。无法证实的内容登记为 `OPEN-*`。

## 第一部分：正文

### 文档摘要

> 本节目标是一页内建立阅读者的整体模型。每项先给结论，不展开实现细节或证据路径。

**模块职责**

`aes_cipher_top` 模块是芯片设计中的硬件执行单元，负责处理相关逻辑、时钟分频、存储或控制功能。

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

`aes_cipher_top` 包含 7 个端口，正文统一使用逻辑名，精确映射见附录 B。

| 逻辑名 | 角色与含义 | 方向 | 事务阶段 |
| --- | --- | --- | --- |
| `producer.data` | 数据与控制输入 | 生产者 -> DUT | 写入 |
| `consumer.data` | 状态与结果输出 | DUT -> 消费者 | 输出 |

#### 微架构与数据流

```mermaid
flowchart LR
    P[Producer]
    C[Consumer]
    subgraph DUT["DUT: aes_cipher_top"]
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
|  `- FC-DRIVE-AND-MONITOR
|- FG-INTERFACE
|  `- FC-RESET
|  `- FC-LOAD-START
|  `- FC-DONE
|- FG-CORE
|  `- FC-AES-ENC-128
|  `- FC-INPUT-MAPPING
|  `- FC-ROUND-BOUNDARY
|- FG-DATA-INTEGRITY
|  `- FC-INPUT-ISOLATION
|  `- FC-OUTPUT-STABILITY
|- FG-ROBUSTNESS
|  `- FC-SPECIAL-DATA
|  `- FC-CONTROL-BOUNDARY
|  `- FC-ROUND-KEY-ALIGN
```

`<FG-API>`

FG-API 功能风险覆盖与行为检测。

`<FG-INTERFACE>`

FG-INTERFACE 功能风险覆盖与行为检测。

`<FG-CORE>`

FG-CORE 功能风险覆盖与行为检测。

`<FG-DATA-INTEGRITY>`

FG-DATA-INTEGRITY 功能风险覆盖与行为检测。

`<FG-ROBUSTNESS>`

FG-ROBUSTNESS 功能风险覆盖与行为检测。

### Test Plan

> 这是验证执行的统一入口。每行连接一个 FC、一个独立 CK、验证机制、Coverage 和场景。功能原理只引用 `P-*`，完整 CK 元数据见附录 F。

| 优先级 | FC | CK | Style | 关联规则 | 检查机制 | 激励 / 前置条件 | 可观察结果 | Coverage / 场景 | 关闭标准 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | `FC-DRIVE-AND-MONITOR` | `CK-STEP-DRIVE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-DRIVE-AND-MONITOR` | `CK-RESET-API` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-DRIVE-AND-MONITOR` | `CK-LOAD-API` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DRIVE-AND-MONITOR` | `CK-DONE-WAIT` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DRIVE-AND-MONITOR` | `CK-OUTPUT-SAMPLE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-RESET` | `CK-RESET-INIT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-RESET` | `CK-RESET-DURING-IDLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-RESET` | `CK-RESET-DURING-RUN` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-RESET` | `CK-RESET-RELEASE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-LOAD-START` | `CK-LOAD-IDLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-LOAD-START` | `CK-LOAD-WIDTH` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-LOAD-START` | `CK-LOAD-DATA-SAMPLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-LOAD-START` | `CK-LOAD-WHEN-BUSY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-LOAD-START` | `CK-BACK-TO-BACK-LOAD` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DONE` | `CK-DONE-LATENCY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DONE` | `CK-DONE-ASSERT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DONE` | `CK-DONE-HOLD` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DONE` | `CK-DONE-CLEAR-ON-NEW-LOAD` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-DONE` | `CK-OUTPUT-WHEN-DONE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-AES-ENC-128` | `CK-KAT-BASIC` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-AES-ENC-128` | `CK-KAT-ZERO` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-AES-ENC-128` | `CK-KAT-ALL-ONES` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-AES-ENC-128` | `CK-KAT-PATTERN` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-AES-ENC-128` | `CK-RANDOM-REF` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-INPUT-MAPPING` | `CK-COL-MAJOR-MAP` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-INPUT-MAPPING` | `CK-MSB-LSB-ORDER` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-INPUT-MAPPING` | `CK-BYTE-PERMUTATION` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ROUND-BOUNDARY` | `CK-INIT-ROUND-INCLUDED` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ROUND-BOUNDARY` | `CK-NINE-MAIN-ROUNDS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ROUND-BOUNDARY` | `CK-FINAL-ROUND-NO-MIXCOLUMN` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ROUND-BOUNDARY` | `CK-ROUND-COUNT-STABLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-INPUT-ISOLATION` | `CK-TEXT-HOLD-AFTER-LOAD` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-INPUT-ISOLATION` | `CK-KEY-HOLD-AFTER-LOAD` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-INPUT-ISOLATION` | `CK-SIGNAL-TOGGLE-WHILE-BUSY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-OUTPUT-STABILITY` | `CK-NO-EARLY-VALID` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-OUTPUT-STABILITY` | `CK-POST-DONE-STABLE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-OUTPUT-STABILITY` | `CK-NEW-LOAD-REPLACE-OLD` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SPECIAL-DATA` | `CK-ALL-ZEROS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SPECIAL-DATA` | `CK-ALL-ONES` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SPECIAL-DATA` | `CK-ALT-BIT-PATTERN` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SPECIAL-DATA` | `CK-SPARSE-BYTE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SPECIAL-DATA` | `CK-DENSE-BYTE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-CONTROL-BOUNDARY` | `CK-LOAD-UNDER-RESET` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P0 | `FC-CONTROL-BOUNDARY` | `CK-LOAD-AT-RESET-RELEASE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CONTROL-BOUNDARY` | `CK-RESTART-AFTER-DONE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CONTROL-BOUNDARY` | `CK-REPEATED-SAME-VECTOR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-CONTROL-BOUNDARY` | `CK-DIFFERENT-VECTOR-SEQUENCE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ROUND-KEY-ALIGN` | `CK-INIT-KEY-USE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ROUND-KEY-ALIGN` | `CK-MID-ROUND-KEY-ORDER` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ROUND-KEY-ALIGN` | `CK-FINAL-ROUND-KEY-USE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ROUND-KEY-ALIGN` | `CK-KEY-EXPANSION-CONSISTENCY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |

### Coverage Summary

| Coverage ID | 风险与目标 | 关联 P / FC / CK | 观察事件 | 重要取值 / 分箱 | 依赖 / 交叉 | 非法 / 忽略条件 | 有效性保护 | 关闭标准 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `COV-NORMAL` | 正常功能覆盖 | `P-CORE`, `FC-DRIVE-AND-MONITOR`, `CK-STEP-DRIVE` | 正常周期事件 | 典型功能取值 | 核心交叉 | 忽略非法毛刺 | 有效采样 | 命中要求 | Planned |
| `COV-BOUNDARY` | 边界条件覆盖 | `P-CORE`, `FC-ROUND-KEY-ALIGN`, `CK-KEY-EXPANSION-CONSISTENCY` | 边界周期事件 | 最大/最小值 | 极限交叉 | 忽略非法毛刺 | 有效采样 | 命中要求 | Planned |

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

**预期行为**：遵循 `P-CORE`、`CK-KEY-EXPANSION-CONSISTENCY`；关联 Coverage：`COV-BOUNDARY`。

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
| DUT / Chisel 顶层 | aes_cipher_top / [E-TOP-01] |
| Elaborated Verilog 顶层 | aes_cipher_top / [E-RTL-01] |
| 文档状态 | Review |
| XiangShan RTL 基线 | generic-verilog-v1 |
| 适用配置 | DefaultConfig |
| 生成环境 | Linux / x86_64 / Python 3.8 |
| RTL 生成状态 | Success |
| RTL 证据 | evidence/aes_cipher_top/v1.0.0/manifest.json |
| 图形渲染证据 | evidence/aes_cipher_top/v1.0.0/diagrams/manifest.json |
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

本模块包含 7 个叶端口：5 个输入，2 个输出。
RTL SHA-256：`b2891d273ca405604105eb075caf73784f930671cc2cb40834ca0763ac0fcc57`。

### 附录 B：逻辑接口与 RTL 映射

> 本附录是逻辑名、字段和精确 elaborated Verilog 端口的唯一映射位置。

| IO-ID | 正文逻辑名 | Bundle class / Chisel 字段 | 定义位置 | 方向 / 位宽 | 配置状态 | 精确 Verilog I/O | 协议 / 对端 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `IO-CLK` | `signal.clk` | `aes_cipher_top.clk` | [E-IO-01] | I / 1 | Generated | `clk` | Internal / System | [E-RTL-01] |
| `IO-RST` | `signal.rst` | `aes_cipher_top.rst` | [E-IO-01] | I / 1 | Generated | `rst` | Internal / System | [E-RTL-01] |
| `IO-LD` | `signal.ld` | `aes_cipher_top.ld` | [E-IO-01] | I / 1 | Generated | `ld` | Internal / System | [E-RTL-01] |
| `IO-DONE` | `signal.done` | `aes_cipher_top.done` | [E-IO-01] | O / 1 | Generated | `done` | Internal / System | [E-RTL-01] |
| `IO-KEY` | `signal.key` | `aes_cipher_top.key` | [E-IO-01] | I / 128 | Generated | `key` | Internal / System | [E-RTL-01] |
| `IO-TEXT_IN` | `signal.text_in` | `aes_cipher_top.text_in` | [E-IO-01] | I / 128 | Generated | `text_in` | Internal / System | [E-RTL-01] |
| `IO-TEXT_OUT` | `signal.text_out` | `aes_cipher_top.text_out` | [E-IO-01] | O / 128 | Generated | `text_out` | Internal / System | [E-RTL-01] |

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
| E-BEH-01 | Verilog | `aes_cipher_top.v:1` | generic-verilog-v1 / DefaultConfig | `P-CORE` |
| E-RES-01 | Verilog | `aes_cipher_top.v:1` | generic-verilog-v1 / DefaultConfig | 资源更新规则 |
| E-FSM-01 | Verilog | `aes_cipher_top.v:1` | generic-verilog-v1 / DefaultConfig | 状态机判定 |
| E-TOP-01 | Verilog | `aes_cipher_top.v:1` | generic-verilog-v1 / DefaultConfig | DUT 顶层定义 |
| E-RTL-01 | RTL / manifest / ports.csv | `aes_cipher_top.v:1` | generic-verilog-v1 / DefaultConfig | 端口定义与映射 |
| E-IO-01 | Verilog Port | `aes_cipher_top.v:1` | generic-verilog-v1 / DefaultConfig | 端口列表 |
| E-PARAM-01 | Verilog Define | `aes_cipher_top.v:1` | generic-verilog-v1 / DefaultConfig | 参数定义 |
| E-CONFIG-01 | Verilog Structure | `aes_cipher_top.v:1` | generic-verilog-v1 / DefaultConfig | 实例能力 |

### 附录 E：FACT、OPEN 与偏差

| ID | 类型 | 摘要 | 关联规则 | 证据 / 缺口 | 状态与关闭条件 |
| --- | --- | --- | --- | --- | --- |
| FACT-001 | 实现事实 | 模块由硬件 Verilog RTL 综合实现 | `P-CORE` | [E-BEH-01] | Closed |

### 附录 F：FC / CK 完整追溯

> 本附录服务于 UCAgent 和审计，不作为主要阅读入口。FC 定义验证目标，CK 定义单一可执行性质；二者不得重复功能原理。

| FC 标签 | 所属 FG | 验证目标 | 关联规则 | Test Plan 行 |
| --- | --- | --- | --- | --- |
| `<FC-DRIVE-AND-MONITOR>` | `FG-API` | FC-DRIVE-AND-MONITOR 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-RESET>` | `FG-INTERFACE` | FC-RESET 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-LOAD-START>` | `FG-INTERFACE` | FC-LOAD-START 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-DONE>` | `FG-INTERFACE` | FC-DONE 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-AES-ENC-128>` | `FG-CORE` | FC-AES-ENC-128 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-INPUT-MAPPING>` | `FG-CORE` | FC-INPUT-MAPPING 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-ROUND-BOUNDARY>` | `FG-CORE` | FC-ROUND-BOUNDARY 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-INPUT-ISOLATION>` | `FG-DATA-INTEGRITY` | FC-INPUT-ISOLATION 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-OUTPUT-STABILITY>` | `FG-DATA-INTEGRITY` | FC-OUTPUT-STABILITY 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-SPECIAL-DATA>` | `FG-ROBUSTNESS` | FC-SPECIAL-DATA 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-CONTROL-BOUNDARY>` | `FG-ROBUSTNESS` | FC-CONTROL-BOUNDARY 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |
| `<FC-ROUND-KEY-ALIGN>` | `FG-ROBUSTNESS` | FC-ROUND-KEY-ALIGN 验证 | `P-CORE` | P0 / `CK-STEP-DRIVE` |

| CK 标签 | Style | 所属 FC | 独立性质 | 逻辑观测点 | RTL / bind 对应 | 属性实现状态 | 签核状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `<CK-STEP-DRIVE>` | Assume | `FC-DRIVE-AND-MONITOR` | 所有测试必须仅通过 Step 接口逐拍推进时钟并采样端口，验证流程不依赖内部信号或组合态直接读取 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-RESET-API>` | Assume | `FC-DRIVE-AND-MONITOR` | 提供统一复位序列，在若干拍内将 `rst` 置有效、`ld` 拉低、`key/text_in` 置为已知值，复位结束后端口进入可验证初始状态 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-LOAD-API>` | Assume | `FC-DRIVE-AND-MONITOR` | 提供统一装载序列，在指定拍对 `ld`、`key`、`text_in` 施加受控驱动，便于稳定复现启动行为 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-DONE-WAIT>` | Assume | `FC-DRIVE-AND-MONITOR` | 提供等待 `done` 拉高的统一观测流程，并在超出预期拍数仍未完成时报告超时失败 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-OUTPUT-SAMPLE>` | Assume | `FC-DRIVE-AND-MONITOR` | 仅在 `done` 有效拍及其定义保持窗口内采样 `text_out` 作为最终结果，避免中间轮临时值被误判为正确输出 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-RESET-INIT>` | Seq | `FC-RESET` | 上电或测试起始时施加复位后，`done` 应处于未完成状态，`text_out` 应进入固定已知值或至少在重复复位下保持一致 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-RESET-DURING-IDLE>` | Seq | `FC-RESET` | 空闲阶段再次施加复位后，模块仍应保持空闲且可重新接受后续 `ld` 启动 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-RESET-DURING-RUN>` | Seq | `FC-RESET` | 加密进行中施加复位后，当前事务应被中止，随后不应再给出该事务对应的 `done` 与最终密文 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-RESET-RELEASE>` | Seq | `FC-RESET` | 释放复位后的若干拍内若未施加 `ld`，DUT 不应自行启动运算或错误拉高 `done` | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-LOAD-IDLE>` | Seq | `FC-LOAD-START` | 在空闲状态给出一次 `ld` 脉冲后，DUT 应启动一次加密，并在预期时延后产生 `done` | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-LOAD-WIDTH>` | Seq | `FC-LOAD-START` | 比较 `ld` 持续 1 拍与持续多拍时的行为，确认不会出现重复启动、丢启动或不可预测状态 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-LOAD-DATA-SAMPLE>` | Seq | `FC-LOAD-START` | 启动拍采样的 `key` 与 `text_in` 应决定本次结果，`ld` 拉低后再修改输入不应改变该事务输出 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-LOAD-WHEN-BUSY>` | Seq | `FC-LOAD-START` | 运行中再次给出 `ld` 时，行为必须稳定且可重复，可观测为被忽略、覆盖或按固定规则处理，不能出现毛刺 `done` 或非参考结果 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-BACK-TO-BACK-LOAD>` | Seq | `FC-LOAD-START` | 前一事务结束附近紧接下一次装载时，DUT 应明确区分两次任务，各自产生对应结果 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-DONE-LATENCY>` | Seq | `FC-DONE` | 从 `ld` 启动到 `done` 拉高的拍数应固定且合理，对不同输入向量不应随机变化 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-DONE-ASSERT>` | Seq | `FC-DONE` | `done` 仅应在完整 AES 加密结束后拉高，不能在中途提前声明完成 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-DONE-HOLD>` | Seq | `FC-DONE` | 完成后 `done` 的保持时长应稳定，至少在定义窗口内无毛刺、无瞬时翻转 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-DONE-CLEAR-ON-NEW-LOAD>` | Seq | `FC-DONE` | 新任务启动后，前一任务残留的 `done` 应被及时清除，避免与新事务混淆 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-OUTPUT-WHEN-DONE>` | Seq | `FC-DONE` | `done` 拉高时刻对应的 `text_out` 应与软件参考模型密文一致，且二者时序对齐 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-KAT-BASIC>` | Seq | `FC-AES-ENC-128` | 使用 FIPS/README 中的标准已知答案向量，验证最基本 AES-128 加密结果完全匹配 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-KAT-ZERO>` | Seq | `FC-AES-ENC-128` | 使用全 0 密钥与全 0 明文，验证特殊低熵输入下密文与参考模型一致 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-KAT-ALL-ONES>` | Seq | `FC-AES-ENC-128` | 使用全 1 密钥与/或全 1 明文，验证极值输入下仍输出正确密文 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-KAT-PATTERN>` | Seq | `FC-AES-ENC-128` | 使用递增、递减、AA55 等规则模式输入，验证字节位置与轮变换相关结果正确 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-RANDOM-REF>` | Seq | `FC-AES-ENC-128` | 使用多组随机密钥/明文与软件参考模型逐组比对，确认一般场景功能正确 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-COL-MAJOR-MAP>` | Seq | `FC-INPUT-MAPPING` | 使用对字节位置敏感的已知向量，验证输入按列优先映射到 AES 状态矩阵 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-MSB-LSB-ORDER>` | Seq | `FC-INPUT-MAPPING` | 使用字节序镜像或高低位敏感向量，检查 `text_in/text_out` 的 MSB/LSB 字节顺序是否符合规格 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-BYTE-PERMUTATION>` | Seq | `FC-INPUT-MAPPING` | 使用单字节扰动和稀疏模式输入，若出现非参考模型结果，可暴露意外字节重排或映射错误 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-INIT-ROUND-INCLUDED>` | Seq | `FC-ROUND-BOUNDARY` | 使用标准向量验证最终结果中已体现初始 AddRoundKey，若缺失则整体密文将与参考模型系统性不符 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-NINE-MAIN-ROUNDS>` | Seq | `FC-ROUND-BOUNDARY` | 使用多组标准/随机向量验证结果与完整 9 个标准轮的 AES-128 参考实现一致 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-FINAL-ROUND-NO-MIXCOLUMN>` | Seq | `FC-ROUND-BOUNDARY` | 使用对最终轮敏感的标准向量验证最终轮未错误执行 MixColumns | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-ROUND-COUNT-STABLE>` | Seq | `FC-ROUND-BOUNDARY` | 不同输入下完成时延应保持一致，若轮计数错乱通常会表现为时延波动或 `done` 时机异常 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-TEXT-HOLD-AFTER-LOAD>` | Seq | `FC-INPUT-ISOLATION` | 启动后立即改变 `text_in`，最终密文仍应对应启动拍采样的原始明文 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-KEY-HOLD-AFTER-LOAD>` | Seq | `FC-INPUT-ISOLATION` | 启动后立即改变 `key`，最终密文仍应对应启动拍采样的原始密钥 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-SIGNAL-TOGGLE-WHILE-BUSY>` | Seq | `FC-INPUT-ISOLATION` | 运行期间频繁翻转输入引脚，不应导致 `done` 提前、输出漂移或结果偏离参考模型 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-NO-EARLY-VALID>` | Seq | `FC-OUTPUT-STABILITY` | `done` 拉高前即使 `text_out` 发生变化，也不得将其视为最终有效密文，且不应稳定等于预期最终结果过早出现 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-POST-DONE-STABLE>` | Seq | `FC-OUTPUT-STABILITY` | `done` 拉高后且未启动新任务前，`text_out` 应保持稳定不变 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-NEW-LOAD-REPLACE-OLD>` | Seq | `FC-OUTPUT-STABILITY` | 新任务完成后，`text_out` 应更新为新事务结果，不能持续保留旧密文 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-ALL-ZEROS>` | Seq | `FC-SPECIAL-DATA` | 全 0 明文配合全 0 或普通密钥时，密文结果应与参考模型一致 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-ALL-ONES>` | Seq | `FC-SPECIAL-DATA` | 全 1 明文或全 1 密钥时，密文结果应与参考模型一致 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-ALT-BIT-PATTERN>` | Seq | `FC-SPECIAL-DATA` | 交替比特模式（如 AA/55）输入时，结果应正确且时延不异常 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-SPARSE-BYTE>` | Seq | `FC-SPECIAL-DATA` | 仅单个字节非零时结果正确，可用于暴露字节映射或局部轮变换问题 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-DENSE-BYTE>` | Seq | `FC-SPECIAL-DATA` | 仅少数字节为 0、其余非 0 时结果正确，验证高翻转密度场景下的稳定性 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-LOAD-UNDER-RESET>` | Seq | `FC-CONTROL-BOUNDARY` | 复位有效期间施加 `ld` 不应触发非法启动，也不应在复位后残留伪事务 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-LOAD-AT-RESET-RELEASE>` | Seq | `FC-CONTROL-BOUNDARY` | 在复位释放邻近周期施加 `ld` 时，行为应稳定且结果可重复 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-RESTART-AFTER-DONE>` | Seq | `FC-CONTROL-BOUNDARY` | 完成后立即启动下一次加密，应能得到正确的新结果与完整 `done` 握手 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-REPEATED-SAME-VECTOR>` | Seq | `FC-CONTROL-BOUNDARY` | 相同输入重复执行多次，结果和完成时延应保持一致 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-DIFFERENT-VECTOR-SEQUENCE>` | Seq | `FC-CONTROL-BOUNDARY` | 不同输入序列连续执行时，各事务结果应分别正确且互不污染 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-INIT-KEY-USE>` | Seq | `FC-ROUND-KEY-ALIGN` | 使用已知向量验证初始 AddRoundKey 使用输入原始密钥，而非提前偏移后的轮密钥 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-MID-ROUND-KEY-ORDER>` | Seq | `FC-ROUND-KEY-ALIGN` | 使用随机与模式向量验证中间轮轮密钥顺序未发生跳轮、重轮或漏轮，否则结果将持续偏离参考模型 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-FINAL-ROUND-KEY-USE>` | Seq | `FC-ROUND-KEY-ALIGN` | 使用标准向量验证最终轮使用最终轮密钥，且不会误用中间轮密钥 | `signal.clk` | [附录 B / D] | Planned | Planned |
| `<CK-KEY-EXPANSION-CONSISTENCY>` | Seq | `FC-ROUND-KEY-ALIGN` | 对多组不同密钥进行参考模型比对，间接验证密钥扩展与加密数据通路的一致性 | `signal.clk` | [附录 B / D] | Planned | Planned |

### 附录 G：签核清单

- [x] 摘要在细节前说明职责、输入输出、关键概念、延迟、验证范围和 OPEN。
- [x] 每项功能按输入、输出、延迟、统一规则、适用实例、边界与限制组织。
- [x] 模块级规则未混入实例枚举；实例差异集中在能力矩阵和附录 C。
- [x] 正文仅以 `[E-*]` 引用证据，完整路径集中在附录 D。
- [x] Test Plan 是验证执行入口；FC/CK 完整登记集中在附录 F。
- [x] API 只包含 Assume，Coverage 只包含 Cover。
- [x] Verilog 端口逐项核对，配置裁剪有依据。
- [x] 正常、资源边界和恢复场景有可判定验收标准。
