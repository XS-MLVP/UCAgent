
# XiangShan Module Design Document

本文是 RTL2Spec 设计文档的写作契约。生成前先完成 evidence，再阅读目标模块和实际支撑结论的相关 Scala 源码。所有实现结论必须来自同一提交、同一配置下的源码、生成 RTL、ports.csv 或已签名的相关源码记录。

## 输出顺序

正式设计文档只能按下列顺序组织，不能增加“生成过程”“阅读建议”或其他说明章节：

1. `文档摘要`
2. `设计概览`
3. `功能行为`
4. `验证策略与 Testplan`
5. `形式化属性契约`
6. `Sign-off 与开放项`
7. `附录 A：I/O 定义与接口约束`
8. `附录 B：参数、编码、状态与复位`
9. `附录 C：范围、文档控制、证据与版本变更`
10. `附录 D：CK 追溯矩阵`
11. `附录 E：场景视角 Test Case`

模板中的 HTML 注释只给生成器约束，不能复制到正式设计文档或质量报告正文。工具写入的 metadata marker 和 related-source marker 是审计元数据，可以保留。不得把生成过程、模型选择、阅读建议、排版规则或无法证实的“设计意图”写成 DUT 事实。

## Workspace Contract

工作区必须提供干净的 `third_party/XiangShan` Git checkout 和递归子模块。目标模块使用准确的 Chisel class 名；配置使用实际配置 class。开始前检查 `outputs/{DUT}`、`reports/{DUT}` 和 `evidence/{DUT}`，任一目录存在旧内容都必须停止并要求用户自行打包归档、清理后重新开始。禁止自动覆盖、删除或生成版本号。

生成顺序固定为：`preflight` -> `evidence` -> 读取目标源码/RTL/ports -> 读取实际相关源码 -> `related_sources` -> 草稿 -> `metadata` -> `validate` -> `lint`。Mermaid 只作为 Markdown fenced source 保存，不生成 SVG。

## Evidence Order

1. 运行 `RTL2SpecCommand(action="preflight")` 和 `action="evidence"`。
2. 阅读 `evidence/{DUT}/manifest.json`、`ports.csv` 和 `{DUT}.sv`。manifest 的 commit、config、generation_status、RTL hash、端口数和工具版本是事实来源。
3. 阅读目标模块源码，定位接口、参数、状态、复位、时序和行为分支。
4. 对本次实际读取过的相关模块执行 `related_sources`，包括用于上下文核对但未支撑最终结论的模块；不得把“被完整芯片编译过”当作“文档参考过”。
5. 每个正文结论若依赖相关模块，必须引用相应 `E-REL-*`；附录 C 必须列出路径、定义行和 SHA-256。

## Reader Model

正文按读者理解 DUT 的顺序展开：

- `文档摘要`给职责、边界、输入输出、容量时延、验证范围和开放项。
- `设计概览`依次给职责与边界、事务模型、数据/控制通路、关键资源与冲突、时序与状态。资源表只记录影响容量、顺序、仲裁或恢复的真实资源；组合直连模块明确写不适用并给出证据。正文只用逻辑接口名；完整扁平端口和源码位置移到附录。
- `功能行为`按数据路径定义一个或多个 `P-*`。每段都必须写激励条件、处理过程、输出或状态结果、时延/顺序、边界与恢复、配置裁剪。
- `验证策略与 Testplan`先说明风险优先级，再说明 stimulus、monitor、checker、reference model、assertion、coverage 和 formal harness 的责任及采样工件；统一 Testplan 行连接一个 FC、一个 CK、一个 P-*、激励、观察结果、Coverage/场景和关闭标准。
- `形式化属性契约`先记录时钟复位、X 态、公平性/等待界限和 harness 边界，再绑定每个 CK 的 Assume、Assert 或 Cover、历史有效、状态和实现状态。
- `Sign-off 与开放项`使用结构化开放项表和签核状态表；只报告当前签核状态和可执行关闭条件。
- 附录保存完整 I/O、参数/编码/状态、范围控制、证据、版本变更、CK 追溯和场景 Test Case。

## Transaction Rules

存在 ready/valid 时，必须明确 `valid && ready` 的接受条件、未接受时 payload 保持、消费者背压时输出保持、接受后资源和计数的变化。不能用“握手完成”代替具体条件。

存在 flush、replay、cancel、error 或 reset 时，必须逐项说明：哪些事务已经存活、哪些事务被取消、取消后是否禁止旧输出、恢复如何建立新事务、同周期事件的优先级。配置或特性被关闭时，说明 disabled 状态的无副作用；没有证据时写 `OPEN-*`。

## Coverage Practice Principles

Coverage 是可观察的完成事件，不是“输入已经驱动”。每个 Coverage 项至少定义目标行为、观察事件、重要分箱、功能交叉、非法/忽略组合、有效性保护和关闭工件。失败测试、未握手输入和无效输出不能计入有效覆盖。宽总线和大数组使用有理由的边界或分组，不展开无法闭合的全组合。

## Presentation Grammar

- 只保留模板规定的标题和必要的 P-/CASE-重复段；不在正式文档中留下 HTML 注释、方括号占位符、TODO 或 TBD。
- 一个事实只在一个位置完整定义。正文引用 `P-*`、`E-*`、`OPEN-*`、`CK-*` 或章节名，不能复制完整端口表、参数表或源码路径。
- 正文使用稳定的逻辑接口名，例如 `fetch_block`、`decode_stream`、`recovery.flush`；附录 A 才展开 Chisel 字段和 Verilog 名。
- Mermaid 图只表达逻辑边界和通路，不放完整端口清单、源码路径或无法验证的内部状态。
- 证据引用使用 `[E-*]`。相关模块只能使用 manifest 中已签名的 `E-REL-*`。
- “Proved”“Covered”“Closed”等词只有在对应工具和工件真实存在时才能使用；文档自检不等于验证通过。

## 行为段落最低内容

每个 `P-*` 必须回答以下问题：

1. 什么输入、状态和控制条件会激励它？
2. DUT 按什么顺序处理，是否有仲裁、存储、旁路或多周期阶段？
3. 输出、状态、计数和资源如何变化？
4. 时延是组合、固定周期还是由下游背压决定？顺序如何保持？
5. 满/空、同周期竞争、错误、flush/replay/cancel 和 reset 如何处理？
6. 参数或特性关闭后有哪些无副作用保证？

## 附录规则

- 附录 A 是完整扁平 I/O 和协议约束的唯一映射；Generated 端口必须逐项存在于 `ports.csv`，Elided 必须给出源码/配置理由。
- 附录 B 是参数、编码、状态和复位的唯一完整定义。没有显式状态或编码时写不适用并引用证据。
- 附录 C 是范围、文档控制、证据和版本变更的唯一完整位置。只有支撑正文结论的相关模块证据需要在这里列出；所有实际读取过的相关模块由质量报告完整记录。
- 附录 D 是 FC/CK 唯一追溯矩阵；每个 CK 只定义一行，并与 Testplan、形式化属性和场景一致。
- 附录 E 是参与者视角的 Test Case；只为 DUT 实际存在或本次验证覆盖的场景创建 CASE 段。每个场景先填写参与者、前置条件、输入、预期输出和 FC/CK，再写动作、阶段结果和验收标准，算法引用 `P-*`。正常、边界或恢复场景不适用时删除对应段，并在范围或开放项中说明理由。

## Static Validation

完成草稿后执行：

```text
RTL2SpecCommand(action="metadata", module="{DUT}", config="{XS_CONFIG}")
RTL2SpecCommand(action="validate", module="{DUT}", config="{XS_CONFIG}")
RTL2SpecCommand(action="lint", module="{DUT}", config="{XS_CONFIG}")
```

修复标题层级、缺失的最低表格、未定义 ID、未记录的 `E-REL-*`、错误端口、断链、未闭合 Mermaid fence 和 HTML 注释后重新执行检查。模板表格可以按实际证据增加；metadata 只同步工具确认的事实，不替作者关闭开放项。

## Completion Standard

只有以下条件全部满足，文档阶段才能完成：

- 输出顺序和模板结构通过检查；
- evidence、manifest、ports.csv 和 RTL 的 commit/config/hash 一致；
- 相关源码只包含实际读取且已签名的模块；
- 每个行为段落具备最低内容，ready/valid、背压、取消和配置裁剪已明确或登记 OPEN；
- 正文只保留逻辑接口名，扁平 I/O、路径、参数和证据集中在规定附录；
- Testplan、形式化属性、CK 矩阵和 Test Case 互相一致；
- 真实验证工件支持的项目才关闭，其他项目保持 OPEN；
- 设计文档和质量报告不含模板生成约束或其他 HTML 注释（工具审计 marker 除外）。

## 完整参考示例

下面的完整文档展示当前模板的标题顺序、表格位置、Mermaid 源码、P/FC/CK/COV/CASE 追溯和 OPEN 状态。示例中的 Sbuffer 事实只用于演示结构，生成实际 DUT 文档时必须全部替换为当前 evidence 支持的内容。

````markdown

# Sbuffer 设计与功能检测点文档

> 模板结构版本：v5.1.0
>
> 正式输出顺序固定为：文档摘要、设计概览、功能行为、验证策略与 Testplan、形式化属性契约、Sign-off 与开放项、附录 A 至附录 E。正文只使用逻辑接口名；完整端口、源码路径、参数、证据和版本变更放在附录。无法证实的内容写入 `OPEN-*`。

## 文档摘要


**模块职责**

Sbuffer 将输入数据组合转发到结果端口，不包含状态、握手或恢复事务。

**输入与生产者**

- `input.data`：由测试激励提供，用于传递数据。
- `control.reset`：由测试控制提供，用于传递数据。

**输出与消费者**

- `input.data`：由检查器接收，用于传递数据。
- `output.done`：由N/A消费，用于传递数据。

**关键概念**

- **组合转发**：输入值直接连接到输出值。
- **直连路径**：输入值直接连接到输出值。

**关键延迟与容量**

- 典型时延：组合路径，零拍。
- 吞吐与容量：每周期一项，无在途事务。

**验证范围**

覆盖组合转发、全零/全一边界；未执行形式化和覆盖率工具。

**开放项**

OPEN-FORMAL-01：未运行形式化工具。

## 设计概览

### 职责与边界

DUT 只负责组合转发；输入和输出均为逻辑数据接口，边界外的复位、时钟和验证环境不参与该路径。P-FORWARD、E-RTL-01。

### 事务模型


1. **产生**：测试激励稳定 input.data。
2. **接受**：模块无 ready/valid，输入值改变即进入组合路径。
3. **处理**：input.data 直接经过组合连接。
4. **完成**：检查器采样 output.data。
5. **取消与恢复**：无 flush、replay、cancel、error 或状态资源，故无存活或取消事务。

### 数据与控制通路


| 逻辑接口 | 生产者 / 消费者 | 方向 | 事务阶段 | 有效与背压约束 |
| --- | --- | --- | --- | --- |
| `input.data` | 测试激励 / DUT | 输入 | 连续观察 | 无握手；组合值稳定 |
| `output.data` | DUT / 检查器 | 输出 | 组合输出 | 无握手；组合值稳定 |
| `control.reset` | 测试控制 / DUT | 控制 | 不适用 | 无状态 |

input.data 通过组合路径到达 output.data；没有控制、错误或取消路径。P-FORWARD。

### 关键资源与冲突

| 资源 | 类型 / 容量 | 写入 / 产生 | 读取 / 消费 | 冲突 / 优先级 | 观测点 |
| --- | --- | --- | --- | --- | --- |
| 无 | `none` | 不适用 | 不适用 | 不适用 | `input.data` / `output.data` |

### 时序与状态

组合路径无寄存器和显式状态机；复位与时钟未参与数据路径，状态机不适用。E-RTL-01。

```mermaid
flowchart LR
    PN/A
    CN/A
    RN/A
    subgraph DUTN/A
        INN/A
        COREN/A
        OUTN/A
        IN --> CORE --> OUT
    end
    P -->|logical ingress| IN
    OUT -->|logical egress| C
    R -.->|flush / cancel / error| CORE
```

## 功能行为


### P-FORWARD：组合转发

N/A

**激励条件**：N/A

**处理过程**：N/A

**输出与状态结果**：N/A

**时延与顺序**：N/A

**边界与恢复**：N/A

**配置裁剪**：N/A

**证据**：E-RTL-01。完整位置见附录 C。

## 验证策略与 Testplan

### 验证策略

N/A

**优先级原则**

- `P0`：N/A
- `P1`：N/A
- `P2`：N/A

### 验证架构与采样点

| 组件 | 责任 | 输入 / 输出 | 采样点或工件 |
| --- | --- | --- | --- |
| `stimulus` | 产生合法和边界值 | `input.data` | 输入值 |
| `monitor` | 采集组合输出 | `output.data` | 输出值 |
| `checker` | 比较输入和输出 | 输入 / 输出 | 等值检查 |
| `formal harness` | 不适用 | N/A | 未执行 |

### 功能分组

`<FG-API>`

- FC-INPUT-CONTRACT：N/A

`<FG-CORE>`

- FC-BEHAVIOR：N/A

`<FG-RECOVERY>`

- FC-RECOVERY：N/A

### Testplan


| 优先级 | FC | CK | Style | 关联行为 | 检查机制 | 激励 / 前置条件 | 可观察结果 | Coverage / 场景 | 关闭标准 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P0 | `FC-INPUT-CONTRACT` | `CK-API-INPUT` | Assume | `P-FORWARD` | Assertion | 输入为已知 8 位值 | output.data | `COV-NORMAL` / `CASE-NORMAL` | 测试通过 |
| P0 | `FC-BEHAVIOR` | `CK-EVENT-RESULT` | Seq | `P-FORWARD` | Scoreboard | 输入变化 | 输出等于输入 | `COV-NORMAL` / `CASE-NORMAL` | 测试通过 |
| P1 | `FC-RECOVERY` | `CK-RECOVERY` | Seq | `P-FORWARD` | Assertion + scoreboard | 无恢复事件 | 无取消事务 | `COV-RECOVERY` / `CASE-RECOVERY` | 测试通过 |

### Coverage Summary

| Coverage ID | 目标行为 | 观察事件 | 重要取值 / 分箱 | 依赖 / 交叉 | 非法 / 忽略条件 | 有效性保护 | 关闭标准 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `COV-NORMAL` | 正常组合路径 | N/A | 0x00、0xff | 输入取值 | 无效输入不采样 | 等值检查通过 | 覆盖两个边界值 | Planned |
| `COV-BOUNDARY` | 全零/全一边界 | N/A | 0x00、0xff | 输入 x 输出 | 无效输入不采样 | 等值检查通过 | 覆盖两个边界值 | Planned |
| `COV-RECOVERY` | 恢复不适用 | 不适用 | 不适用 | 不适用 | 恢复激励忽略 | 不适用 | 覆盖两个边界值 | Planned |

## 形式化属性契约

### 契约边界与执行条件

| 项目 | 约束或定义 | 依据 / 状态 |
| --- | --- | --- |
| 时钟与复位 | 无时钟；复位不参与数据路径 | `E-RTL-01` |
| X 态与未知值 | 仅采样已知输入 | `OPEN-FORMAL-01` |
| 公平性与等待界限 | 不适用，无仲裁 | `E-RTL-01` |
| Harness 边界 | 组合输入到输出 | `E-RTL-01` |

### 属性实现状态

| CK | 类型 | 契约 | 当前实现 | 属性状态 | 签核状态 |
| --- | --- | --- | --- | --- | --- |
| `CK-API-INPUT` | Assume | 输入为已知值 | 未实现 | Planned | OPEN |
| `CK-EVENT-RESULT` | Assert | 输出等于输入 | 未实现 | Planned | OPEN |
| `CK-RECOVERY` | Assert | 无取消事务 | 未实现 | Planned | OPEN |
| `CK-COVER-BOUNDARY` | Cover | 边界值可达 | 未实现 | Planned | OPEN |

### Assume

N/A

### Assert

N/A

### Cover

N/A

## Sign-off 与开放项

### 开放项

| ID | 缺口或问题 | 影响 | 关闭动作与所需证据 | 状态 |
| --- | --- | --- | --- | --- |
| `OPEN-FORMAL-01` | 未运行形式化工具 | Formal / assertion | 编译并运行属性，保存工件 | Open |

### 签核状态

| 项目 | 状态 | 依据 |
| --- | --- | --- |
| I/O mapping | Pass | `E-RTL-01` |
| Testplan | Review | `FC-BEHAVIOR` |
| Formal / assertion | Unrun | `OPEN-FORMAL-01` |
| Regression / coverage | Unrun | `OPEN-FORMAL-01` |
| 当前文档状态 | Draft | `OPEN-FORMAL-01` |

## 附录 A：I/O 定义与接口约束


| IO-ID | 正文逻辑接口 | Bundle / Chisel 字段 | 定义位置 | 方向 / 位宽 | 配置状态 | 精确 Verilog I/O | 协议 / 对端 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `IO-INPUT-01` | `input.data` | `N/A` | `evidence/Sbuffer/Sbuffer.sv:1` | `I/8` | Generated | `io_data` | `N/A` | `E-RTL-01` |
| `IO-OUTPUT-01` | `output.data` | `N/A` | `evidence/Sbuffer/Sbuffer.sv:1` | `O/8` | Generated | `io_result` | `N/A` | `E-RTL-01` |

N/A

## 附录 B：参数、编码、状态与复位

### 参数与配置

| 参数 ID | 参数 / 派生常量 | 配置值 | 约束或裁剪 | 证据 |
| --- | --- | --- | --- | --- |
| `PARAM-01` | `Sbuffer` | `8` | `无参数` | `E-RTL-01` |

### 编码、状态与复位

| 状态/编码 ID | 名称或编码 | 进入条件 | 退出条件 | reset 值 / 复位行为 | 证据 |
| --- | --- | --- | --- | --- | --- |
| `STATE-01` | `无状态` | `输入有效` | `输入有效` | `未使用` | `E-RTL-01` |

N/A

## 附录 C：范围、文档控制、证据与版本变更

### 范围与文档控制

| 项目 | 内容 |
| --- | --- |
| 使用模板版本 | v5.1.0 |
| DUT / Chisel 顶层 | `Sbuffer` |
| Elaborated Verilog 顶层 | `Sbuffer` |
| 文档状态 | Draft / Review / Frozen |
| XiangShan RTL 基线 | `fixture-commit` |
| 适用配置 | `DefaultConfig` |
| RTL 生成状态 | `success` |
| RTL 证据 | `evidence/Sbuffer/manifest.json；4 ports` |
| Mermaid 图形源码 | `1` |
| 生成日期 | `2026-09-23` |

| 范围或条件 | 裁定 | 理由 / 证据 |
| --- | --- | --- |
| DUT 边界 | `Sbuffer 组合路径` | `无内部状态` |
| 相关模块源码 | `无` | `无相关源码` |
| 未覆盖验证 | `形式化和覆盖率` | `N/A` |
| 特性门控 | `not applicable` | `无内部状态` |

### 证据与版本变更


| Evidence ID | 类型 | 来源位置 | Commit / 配置 | 支持内容 |
| --- | --- | --- | --- | --- |
| `E-RTL-01` | RTL/ports | `evidence/Sbuffer/Sbuffer.sv:1` | `fixture/DefaultConfig` | `组合转发` |

| 版本变更 ID | 变更类型 | 本次变更 | 影响范围 | 依据 |
| --- | --- | --- | --- | --- |
| `CHANGE-01` | Initial / Patch / Review | `初始文档` | `全部章节` | `E-RTL-01 / OPEN-FORMAL-01` |

## 附录 D：CK 追溯矩阵

### 功能组与 FC

| FC | 所属 FG | 验证目标 | 关联行为 | Testplan 行 |
| --- | --- | --- | --- | --- |
| `FC-INPUT-CONTRACT` | `FG-API` | 数据一致 | `P-FORWARD` | 1 |
| `FC-BEHAVIOR` | `FG-CORE` | 数据一致 | `P-FORWARD` | 1 |
| `FC-RECOVERY` | `FG-RECOVERY` | 数据一致 | `P-FORWARD` | 1 |

### CK 追溯

| CK | FC | 检查目标 | Style | 属性状态 | Test Case | Coverage | 签核状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `CK-API-INPUT` | `FC-INPUT-CONTRACT` | 数据一致 | Assume | Planned | `CASE-NORMAL` | `COV-NORMAL` | OPEN |
| `CK-EVENT-RESULT` | `FC-BEHAVIOR` | 数据一致 | Assert/Seq | Planned | `CASE-NORMAL` | `COV-NORMAL` | OPEN |
| `CK-RECOVERY` | `FC-RECOVERY` | 数据一致 | Assert/Seq | Planned | `CASE-RECOVERY` | `COV-RECOVERY` | OPEN |
| `CK-COVER-BOUNDARY` | `FC-RECOVERY` | 数据一致 | Cover | Planned | `CASE-BOUNDARY` | `COV-BOUNDARY` | OPEN |

## 附录 E：场景视角 Test Case


### CASE-NORMAL：转发数据

| 参与者 | 前置条件 | 输入 | 预期输出 | 关联 FC / CK |
| --- | --- | --- | --- | --- |
| 生产者、DUT、检查器 | 组合路径稳定 | `input.data` | `output.data` 等于输入 | `FC-BEHAVIOR`, `CK-EVENT-RESULT` |

**参与者与前置条件**：N/A

1. 产生合法 input.data。
2. 组合路径稳定。
3. 观察 output.data。

**验收标准**：output.data 等于 input.data；引用 P-FORWARD、CK-EVENT-RESULT、COV-NORMAL。

### CASE-BOUNDARY：取值边界

| 参与者 | 前置条件 | 输入 | 预期输出 | 关联 FC / CK |
| --- | --- | --- | --- | --- |
| 生产者、DUT、检查器 | 输入可取全零和全一 | `0x00`, `0xff` | 输出保持等值 | `FC-BEHAVIOR`, `CK-COVER-BOUNDARY` |

**参与者与前置条件**：输入取全零和全一。

1. 施加边界值。
2. 观察输出一致。

**验收标准**：输出与输入一致；引用 P-FORWARD、CK-COVER-BOUNDARY、COV-BOUNDARY。

### CASE-RECOVERY：恢复适用性

| 参与者 | 前置条件 | 输入 | 预期输出 | 关联 FC / CK |
| --- | --- | --- | --- | --- |
| 生产者、DUT、检查器 | 无恢复资源 | 无恢复 transaction | 无存活或取消事务 | `FC-RECOVERY`, `CK-RECOVERY` |

**参与者与前置条件**：该组合模块没有恢复资源，恢复场景不适用。

1. 不施加恢复事件。
2. 不存在存活或取消事务。
3. 不适用。

**验收标准**：不适用；引用 E-RTL-01。


### CASE-EXTRA：其他场景

| 参与者 | 前置条件 | 输入 | 预期输出 | 关联 FC / CK |
| --- | --- | --- | --- | --- |
| N/A | 无额外场景 | N/A | N/A | N/A |

无额外场景。

````
