---
name: env-generation
description: Formal 验证环境（Checker & Bind Wrapper）的配置与构建指南
---

# 形式化验证环境构建指南 (Environment Generation)

本小节指导如何在使用 `GenerateFormalEnv` 工具后，进一步根据物理设计架构去完善自动生成的 checker 和 wrapper 文件。

在生成了基础代码后，作为 Agent，你需要重点解决以下深层次的环境适配问题：

## 1. 完善符号化索引 (Symbolic Indexing)

形式化验证如果试图穷举大型数组的状态往往会导致状态机爆炸。为了防范此情况并覆盖每一处逻辑，设计若存在数组应当采用符号化切片（Symbolic Indexing）。

### 判断标准：合适启用符号索引？
如果 RTL 包含以下特征之一，则**必须**使用符号化索引：
1. 声明了数组型寄存器（例如 `reg [31:0] mem [0:15];`）
2. 包含多个同构的外露实例（例如 `entries_0, entries_1, ...`）
3. 使用了 `genvar / generate` 循环生成大范围重复结构。

### 操作步骤：
打开自动生成的 `{OUT}/tests/{DUT}_wrapper.sv`，寻找相关的占位符。`GenerateFormalEnv` 已生成 `fv_idx` 和 `fv_mon_...` 的占位符（处于被注释状态）：
1. 请取消相关占位逻辑的注释。
2. 严格根据 RTL 的内部信号路径完成这些多路选择器 (Mux) 逻辑。
3. 确保将 `fv_mon_x` 之类的被观测信号正确的引到 checker 的被测接口上。

## 2. 导出白盒信号 (White-box Verification)

形式化验证需要透视设计内部。所有的指针 (pointers)、状态转换标识 (flags)、状态机主状态 (fsm states) 等不能仅在模块内起作用。
- 在 `wrapper.sv` 文件内，将这些必须监控的关键内部信号提取出来（例如 `wire [3:0] dut_state = dut.fsm_state;`）。
- 将提取出的信号接入实例化的 `checker` 模块端口里。

## 3. 时序极性与校正确认

即使有了基于文档生成的骨架，也常常会被一些微小的环境定义毁掉证明过程。
- 查看生成的 `wrapper.sv` 顶部 `Clock/Reset Remapping` 区域。
- 确认工具所映射的极性是否符合预期？（尤其是，如果这是一个高电平有效的复位信号，其应当被映射为 `wire rst_n = ~rst;`）。对于误判情况需要立即重写映射。

## 4. 保留 SVA 代码骨架

`GenerateFormalEnv` 工具在运行期间会悄无声息地从 `03_{DUT}_functions_and_checks.md` 文档提取标签，追加到 `checker.sv` 末端，这些骨架具有形式为 `[LLM-TODO]` 的特殊代码。
**请不要在此阶段填写它们！** 你的首要工作仅仅是配置和补齐环境，实际的断言编写任务属于接下来的 Stage 5 环节。
