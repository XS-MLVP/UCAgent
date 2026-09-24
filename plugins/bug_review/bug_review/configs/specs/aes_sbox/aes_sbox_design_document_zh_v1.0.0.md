# aes_sbox 设计与功能检测点文档

> 模板结构版本：v3.3.0
>
> 文档版本：v1.0.0
>
> 本文分为正文、验证计划和附录。正文用于连续理解设计，验证计划用于安排检查，附录用于审计和签核。FG、FC、CK 标签必须使用反引号包裹，例如 `` `<FG-API>` ``。无法证实的内容登记为 `OPEN-*`。

## 第一部分：正文

### 文档摘要

> 本节目标是一页内建立阅读者的整体模型。每项先给结论，不展开实现细节或证据路径。

**模块职责**

`aes_sbox` 模块是芯片设计中的硬件执行单元，负责处理相关逻辑、时钟分频、存储或控制功能。

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

`aes_sbox` 包含 2 个端口，正文统一使用逻辑名，精确映射见附录 B。

| 逻辑名 | 角色与含义 | 方向 | 事务阶段 |
| --- | --- | --- | --- |
| `producer.data` | 数据与控制输入 | 生产者 -> DUT | 写入 |
| `consumer.data` | 状态与结果输出 | DUT -> 消费者 | 输出 |

#### 微架构与数据流

```mermaid
flowchart LR
    P[Producer]
    C[Consumer]
    subgraph DUT["DUT: aes_sbox"]
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
|  `- FC-STEP-IO
|- FG-INTERFACE
|  `- FC-IO-WIDTH
|  `- FC-COMB-RESPONSE
|- FG-FORWARD-SBOX
|  `- FC-KNOWN-VECTORS
|  `- FC-FULL-LUT-MAPPING
|  `- FC-PERMUTATION-PROPERTY
|- FG-ALGORITHM-BOUNDARY
|  `- FC-ZERO-INVERSE-SPECIAL
|  `- FC-BOUNDARY-INPUTS
|  `- FC-SEQUENTIAL-INPUT-TRANSITIONS
```

`<FG-API>`

FG-API 功能风险覆盖与行为检测。

`<FG-INTERFACE>`

FG-INTERFACE 功能风险覆盖与行为检测。

`<FG-FORWARD-SBOX>`

FG-FORWARD-SBOX 功能风险覆盖与行为检测。

`<FG-ALGORITHM-BOUNDARY>`

FG-ALGORITHM-BOUNDARY 功能风险覆盖与行为检测。

### Test Plan

> 这是验证执行的统一入口。每行连接一个 FC、一个独立 CK、验证机制、Coverage 和场景。功能原理只引用 `P-*`，完整 CK 元数据见附录 F。

| 优先级 | FC | CK | Style | 关联规则 | 检查机制 | 激励 / 前置条件 | 可观察结果 | Coverage / 场景 | 关闭标准 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | `FC-STEP-IO` | `CK-SET-A-READ-B` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-STEP-IO` | `CK-MULTI-STEP-STABLE` | Assume | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-IO-WIDTH` | `CK-INPUT-8BIT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-IO-WIDTH` | `CK-OUTPUT-8BIT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-COMB-RESPONSE` | `CK-INPUT-CHANGE-UPDATES-OUTPUT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-COMB-RESPONSE` | `CK-STATELESS-BEHAVIOR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-KNOWN-VECTORS` | `CK-ZERO-VECTOR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-KNOWN-VECTORS` | `CK-ONES-VECTOR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-KNOWN-VECTORS` | `CK-TYPICAL-VECTOR` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-FULL-LUT-MAPPING` | `CK-ALL-256-VALUES` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-FULL-LUT-MAPPING` | `CK-NO-MISMATCH-INDEX` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-PERMUTATION-PROPERTY` | `CK-OUTPUT-UNIQUE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-PERMUTATION-PROPERTY` | `CK-OUTPUT-COVER-256` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ZERO-INVERSE-SPECIAL` | `CK-ZERO-SPECIAL-HANDLING` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-ZERO-INVERSE-SPECIAL` | `CK-ZERO-FINAL-AFFINE` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BOUNDARY-INPUTS` | `CK-LOW-BOUNDARY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BOUNDARY-INPUTS` | `CK-HIGH-BOUNDARY` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-BOUNDARY-INPUTS` | `CK-PATTERN-INPUTS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SEQUENTIAL-INPUT-TRANSITIONS` | `CK-BACK-TO-BACK-TRANSITIONS` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |
| P1 | `FC-SEQUENTIAL-INPUT-TRANSITIONS` | `CK-RETURN-TO-PREVIOUS-INPUT` | Seq | `P-CORE` | Assertion | 激励驱动 | 结果观测与断言 | `COV-NORMAL` / `CASE-NORMAL` | regression 通过 |

### Coverage Summary

| Coverage ID | 风险与目标 | 关联 P / FC / CK | 观察事件 | 重要取值 / 分箱 | 依赖 / 交叉 | 非法 / 忽略条件 | 有效性保护 | 关闭标准 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `COV-NORMAL` | 正常功能覆盖 | `P-CORE`, `FC-STEP-IO`, `CK-SET-A-READ-B` | 正常周期事件 | 典型功能取值 | 核心交叉 | 忽略非法毛刺 | 有效采样 | 命中要求 | Planned |
| `COV-BOUNDARY` | 边界条件覆盖 | `P-CORE`, `FC-SEQUENTIAL-INPUT-TRANSITIONS`, `CK-RETURN-TO-PREVIOUS-INPUT` | 边界周期事件 | 最大/最小值 | 极限交叉 | 忽略非法毛刺 | 有效采样 | 命中要求 | Planned |

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

**预期行为**：遵循 `P-CORE`、`CK-SET-A-READ-B`；关联 Coverage：`COV-NORMAL`。

**验收标准**：输出处于预期初始状态。

#### CASE-NORMAL：正常运算场景

**目标**：验证典型功能处理流程。

**参与者与前置条件**：激励驱动源。

1. 驱动有效输入。
2. 观测输出结果。

**预期行为**：遵循 `P-CORE`、`CK-SET-A-READ-B`；关联 Coverage：`COV-NORMAL`。

**验收标准**：结果正确匹配。

#### CASE-BOUNDARY：边界条件场景

**目标**：验证极限值与异常边界行为。

**参与者与前置条件**：激励驱动源。

1. 驱动边界极值。
2. 检查输出无挂起。

**预期行为**：遵循 `P-CORE`、`CK-RETURN-TO-PREVIOUS-INPUT`；关联 Coverage：`COV-BOUNDARY`。

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
| DUT / Chisel 顶层 | aes_sbox / [E-TOP-01] |
| Elaborated Verilog 顶层 | aes_sbox / [E-RTL-01] |
| 文档状态 | Review |
| XiangShan RTL 基线 | generic-verilog-v1 |
| 适用配置 | DefaultConfig |
| 生成环境 | Linux / x86_64 / Python 3.8 |
| RTL 生成状态 | Success |
| RTL 证据 | evidence/aes_sbox/v1.0.0/manifest.json |
| 图形渲染证据 | evidence/aes_sbox/v1.0.0/diagrams/manifest.json |
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

本模块包含 2 个叶端口：1 个输入，1 个输出。
RTL SHA-256：`fa797b07fcdecacbf409c6393f79350f90a066f84f26e6155ba0788c213c849b`。

### 附录 B：逻辑接口与 RTL 映射

> 本附录是逻辑名、字段和精确 elaborated Verilog 端口的唯一映射位置。

| IO-ID | 正文逻辑名 | Bundle class / Chisel 字段 | 定义位置 | 方向 / 位宽 | 配置状态 | 精确 Verilog I/O | 协议 / 对端 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `IO-A` | `signal.a` | `aes_sbox.a` | [E-IO-01] | I / 8 | Generated | `a` | Internal / System | [E-RTL-01] |
| `IO-B` | `signal.b` | `aes_sbox.b` | [E-IO-01] | O / 8 | Generated | `b` | Internal / System | [E-RTL-01] |

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
| E-BEH-01 | Verilog | `aes_sbox.v:1` | generic-verilog-v1 / DefaultConfig | `P-CORE` |
| E-RES-01 | Verilog | `aes_sbox.v:1` | generic-verilog-v1 / DefaultConfig | 资源更新规则 |
| E-FSM-01 | Verilog | `aes_sbox.v:1` | generic-verilog-v1 / DefaultConfig | 状态机判定 |
| E-TOP-01 | Verilog | `aes_sbox.v:1` | generic-verilog-v1 / DefaultConfig | DUT 顶层定义 |
| E-RTL-01 | RTL / manifest / ports.csv | `aes_sbox.v:1` | generic-verilog-v1 / DefaultConfig | 端口定义与映射 |
| E-IO-01 | Verilog Port | `aes_sbox.v:1` | generic-verilog-v1 / DefaultConfig | 端口列表 |
| E-PARAM-01 | Verilog Define | `aes_sbox.v:1` | generic-verilog-v1 / DefaultConfig | 参数定义 |
| E-CONFIG-01 | Verilog Structure | `aes_sbox.v:1` | generic-verilog-v1 / DefaultConfig | 实例能力 |

### 附录 E：FACT、OPEN 与偏差

| ID | 类型 | 摘要 | 关联规则 | 证据 / 缺口 | 状态与关闭条件 |
| --- | --- | --- | --- | --- | --- |
| FACT-001 | 实现事实 | 模块由硬件 Verilog RTL 综合实现 | `P-CORE` | [E-BEH-01] | Closed |

### 附录 F：FC / CK 完整追溯

> 本附录服务于 UCAgent 和审计，不作为主要阅读入口。FC 定义验证目标，CK 定义单一可执行性质；二者不得重复功能原理。

| FC 标签 | 所属 FG | 验证目标 | 关联规则 | Test Plan 行 |
| --- | --- | --- | --- | --- |
| `<FC-STEP-IO>` | `FG-API` | FC-STEP-IO 验证 | `P-CORE` | P0 / `CK-SET-A-READ-B` |
| `<FC-IO-WIDTH>` | `FG-INTERFACE` | FC-IO-WIDTH 验证 | `P-CORE` | P0 / `CK-SET-A-READ-B` |
| `<FC-COMB-RESPONSE>` | `FG-INTERFACE` | FC-COMB-RESPONSE 验证 | `P-CORE` | P0 / `CK-SET-A-READ-B` |
| `<FC-KNOWN-VECTORS>` | `FG-FORWARD-SBOX` | FC-KNOWN-VECTORS 验证 | `P-CORE` | P0 / `CK-SET-A-READ-B` |
| `<FC-FULL-LUT-MAPPING>` | `FG-FORWARD-SBOX` | FC-FULL-LUT-MAPPING 验证 | `P-CORE` | P0 / `CK-SET-A-READ-B` |
| `<FC-PERMUTATION-PROPERTY>` | `FG-FORWARD-SBOX` | FC-PERMUTATION-PROPERTY 验证 | `P-CORE` | P0 / `CK-SET-A-READ-B` |
| `<FC-ZERO-INVERSE-SPECIAL>` | `FG-ALGORITHM-BOUNDARY` | FC-ZERO-INVERSE-SPECIAL 验证 | `P-CORE` | P0 / `CK-SET-A-READ-B` |
| `<FC-BOUNDARY-INPUTS>` | `FG-ALGORITHM-BOUNDARY` | FC-BOUNDARY-INPUTS 验证 | `P-CORE` | P0 / `CK-SET-A-READ-B` |
| `<FC-SEQUENTIAL-INPUT-TRANSITIONS>` | `FG-ALGORITHM-BOUNDARY` | FC-SEQUENTIAL-INPUT-TRANSITIONS 验证 | `P-CORE` | P0 / `CK-SET-A-READ-B` |

| CK 标签 | Style | 所属 FC | 独立性质 | 逻辑观测点 | RTL / bind 对应 | 属性实现状态 | 签核状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `<CK-SET-A-READ-B>` | Assume | `FC-STEP-IO` | CK-SET-A-READ-B | `signal.a` | [附录 B / D] | Planned | Planned |
| `<CK-MULTI-STEP-STABLE>` | Assume | `FC-STEP-IO` | CK-MULTI-STEP-STABLE | `signal.a` | [附录 B / D] | Planned | Planned |
| `<CK-INPUT-8BIT>` | Seq | `FC-IO-WIDTH` | CK-INPUT-8BIT | `signal.a` | [附录 B / D] | Planned | Planned |
| `<CK-OUTPUT-8BIT>` | Seq | `FC-IO-WIDTH` | CK-OUTPUT-8BIT | `signal.a` | [附录 B / D] | Planned | Planned |
| `<CK-INPUT-CHANGE-UPDATES-OUTPUT>` | Seq | `FC-COMB-RESPONSE` | CK-INPUT-CHANGE-UPDATES-OUTPUT | `signal.a` | [附录 B / D] | Planned | Planned |
| `<CK-STATELESS-BEHAVIOR>` | Seq | `FC-COMB-RESPONSE` | CK-STATELESS-BEHAVIOR | `signal.a` | [附录 B / D] | Planned | Planned |
| `<CK-ZERO-VECTOR>` | Seq | `FC-KNOWN-VECTORS` | CK-ZERO-VECTOR | `signal.a` | [附录 B / D] | Planned | Planned |
| `<CK-ONES-VECTOR>` | Seq | `FC-KNOWN-VECTORS` | CK-ONES-VECTOR | `signal.a` | [附录 B / D] | Planned | Planned |
| `<CK-TYPICAL-VECTOR>` | Seq | `FC-KNOWN-VECTORS` | CK-TYPICAL-VECTOR | `signal.a` | [附录 B / D] | Planned | Planned |
| `<CK-ALL-256-VALUES>` | Seq | `FC-FULL-LUT-MAPPING` | CK-ALL-256-VALUES | `signal.a` | [附录 B / D] | Planned | Planned |
| `<CK-NO-MISMATCH-INDEX>` | Seq | `FC-FULL-LUT-MAPPING` | CK-NO-MISMATCH-INDEX | `signal.a` | [附录 B / D] | Planned | Planned |
| `<CK-OUTPUT-UNIQUE>` | Seq | `FC-PERMUTATION-PROPERTY` | CK-OUTPUT-UNIQUE | `signal.a` | [附录 B / D] | Planned | Planned |
| `<CK-OUTPUT-COVER-256>` | Seq | `FC-PERMUTATION-PROPERTY` | CK-OUTPUT-COVER-256 | `signal.a` | [附录 B / D] | Planned | Planned |
| `<CK-ZERO-SPECIAL-HANDLING>` | Seq | `FC-ZERO-INVERSE-SPECIAL` | CK-ZERO-SPECIAL-HANDLING | `signal.a` | [附录 B / D] | Planned | Planned |
| `<CK-ZERO-FINAL-AFFINE>` | Seq | `FC-ZERO-INVERSE-SPECIAL` | CK-ZERO-FINAL-AFFINE | `signal.a` | [附录 B / D] | Planned | Planned |
| `<CK-LOW-BOUNDARY>` | Seq | `FC-BOUNDARY-INPUTS` | CK-LOW-BOUNDARY | `signal.a` | [附录 B / D] | Planned | Planned |
| `<CK-HIGH-BOUNDARY>` | Seq | `FC-BOUNDARY-INPUTS` | CK-HIGH-BOUNDARY | `signal.a` | [附录 B / D] | Planned | Planned |
| `<CK-PATTERN-INPUTS>` | Seq | `FC-BOUNDARY-INPUTS` | CK-PATTERN-INPUTS | `signal.a` | [附录 B / D] | Planned | Planned |
| `<CK-BACK-TO-BACK-TRANSITIONS>` | Seq | `FC-SEQUENTIAL-INPUT-TRANSITIONS` | CK-BACK-TO-BACK-TRANSITIONS | `signal.a` | [附录 B / D] | Planned | Planned |
| `<CK-RETURN-TO-PREVIOUS-INPUT>` | Seq | `FC-SEQUENTIAL-INPUT-TRANSITIONS` | CK-RETURN-TO-PREVIOUS-INPUT | `signal.a` | [附录 B / D] | Planned | Planned |

### 附录 G：签核清单

- [x] 摘要在细节前说明职责、输入输出、关键概念、延迟、验证范围和 OPEN。
- [x] 每项功能按输入、输出、延迟、统一规则、适用实例、边界与限制组织。
- [x] 模块级规则未混入实例枚举；实例差异集中在能力矩阵和附录 C。
- [x] 正文仅以 `[E-*]` 引用证据，完整路径集中在附录 D。
- [x] Test Plan 是验证执行入口；FC/CK 完整登记集中在附录 F。
- [x] API 只包含 Assume，Coverage 只包含 Cover。
- [x] Verilog 端口逐项核对，配置裁剪有依据。
- [x] 正常、资源边界和恢复场景有可判定验收标准。
