---
name: sva-property-generation
description: 基于 SVA 规范编写属性检测代码
---

# SVA 断言生成规范指南 (SVA Property Generation)

本小节指导如何基于规范将预留的 SVA 骨架转换为形式化工具使用的 SystemVerilog Assertions (SVA)，这些断言必须填入到 `XXX_checker.sv` 模块中对应的 FG 分组区域内。

请注意，在前一个环境生成阶段，`GenerateFormalEnv` 原理上已经自动在 `checker.sv` 的末端（`endmodule` 之前）为您生成了所有规范文档中标注的带实例化标签的完整 `[LLM-TODO]` 骨架。您现在的任务**仅仅是专注并且原样保留这些骨架**，将各处条件逻辑准确无误地填入占位符中。

## 命名规则

在编写 SVA 时请遵循以下命名规则（通常情况下，工具为您生成的骨架已经自动符合）：
- 将原文档检测点标签 `<CK-XXX-YYY>` 中的短横线 `-` 替换为下划线 `_`
- property 名使用 `CK_` 前缀，例如：`CK_API_INPUT_KNOWN`
- 实例化标签使用类型前缀：
  - Assume → `M_CK_` 
  - Assert → `A_CK_` 
  - Cover  → `C_CK_` 

## 标准代码格式

**所有断言必须使用 `property ... endproperty` 格式定义，然后通过带标签的实例化语句引用。**

⚠️ **禁止使用 `` `define `` 宏格式！** 必须使用下面的 property 定义格式。

### 1. (Style: Assume) — 环境约束

必须被翻译为 `assume property`，用于给形式化工具施加输入约束。

```systemverilog
// <CK-API-INPUT-KNOWN> (Style: Assume)
property CK_API_INPUT_KNOWN;
  @(posedge clk) disable iff (!rst_n)
  !$isunknown(data_in);
endproperty
M_CK_API_INPUT_KNOWN: assume property (CK_API_INPUT_KNOWN);
```

如果是组合假设（不带时钟），使用：
```systemverilog
property CK_API_PARAM_VALID;
  param_value < MAX_VALUE;
endproperty
M_CK_API_PARAM_VALID: assume property (CK_API_PARAM_VALID);
```

### 2. (Style: Seq) — 时序断言

用于包含时序跨度的操作或基于时钟的多周期同步操作。这是**最常用的验证实体断言形式**！
通常包含蕴含操作符 `|->` (交叠) 或 `|=>` (非交叠)。

```systemverilog
// <CK-VALID-READY> (Style: Seq)
property CK_VALID_READY;
  @(posedge clk) disable iff (!rst_n)
  valid && !ready |=> $stable(data);
endproperty
A_CK_VALID_READY: assert property (CK_VALID_READY);
```

### 3. (Style: Comb) — 组合逻辑断言

**注意：Comb 类型表示没有引入延迟的时序要求，仅包含组合逻辑！**
如果验证纯组合逻辑（如纯加法器），不能引入多周期操作符（如 `$past`, `|=>`），且不要使用 `s_eventually`。

```systemverilog
// <CK-ADD-RESULT-CORRECT> (Style: Comb)
property CK_ADD_RESULT_CORRECT;
  {cout, sum} == (a + b + cin);
endproperty
A_CK_ADD_RESULT_CORRECT: assert property (@(posedge clk) disable iff (!rst_n) CK_ADD_RESULT_CORRECT);
```

> 注意：Comb property 内部不带 `@(posedge clk)`，而是在 assert 实例化时添加。

### 4. (Style: Cover) — 可达性证明

用于可达性证明，防止过约束！必须且只能被翻译为 `cover property`。

```systemverilog
// <CK-COVER-FIFO-FULL> (Style: Cover)
property CK_COVER_FIFO_FULL;
  @(posedge clk) disable iff (!rst_n)
  full == 1'b1;
endproperty
C_CK_COVER_FIFO_FULL: cover property (CK_COVER_FIFO_FULL);
```

**安全假定提示：** 如果设计中出现明显能让引擎穷举爆炸的东西（如128位复杂乘法器），不要试图通过穷举它产生 Cover。Cover 的主要价值是验证握手、满空、计数溢出等。

## 代码位置要求

所有 SVA 代码必须写在 `XXX_checker.sv` 模块的 `module ... endmodule` **内部**，并放在对应的 FG 分组区域：

```systemverilog
module DUT_checker (...);
  default clocking cb @(posedge clk); endclocking
  default disable iff (!rst_n);

  // --- 2. FG-ENVIRONMENT ---
  // Assume 类型的断言放在这里

  // --- 3. FG-CONTROL ---
  // Seq 类型的状态断言放在这里

  // --- 4. FG-DATAPATH ---
  // Comb/Seq 类型的数据通路断言放在这里

  // --- 5. FG-PROGRESS ---
  // Liveness 断言放在这里

  // --- 6. FG-COVERAGE ---
  // Cover 类型的断言放在这里
endmodule
```

## 注意事项与常见错误

1. **禁止使用 `` `define `` 宏格式**：所有断言必须使用 `property ... endproperty` + 带标签实例化的格式。
2. **代码必须在 `endmodule` 之前**：不要把断言代码写在模块外部。
3. 使用 `$past`：检查你的使用场景，如果这是一个仅靠组合逻辑瞬间发生变化的信号，那么你实际上只关心当前拍，不应该使用 `$past`，直接比较结果。只有在做状态迁移验证（如"当拍满足A，且上一拍满足B"）时才使用 `$past`。
4. 绝对不要对输出端口、内部网络节点加上 `assume property` 约束，这样会破坏该模块本身的被测逻辑导致假阳性。`Assume` 只能对模块的 `input` 进行约束。
5. 每个 property 定义结尾使用分号 `;`，每个实例化语句结尾使用分号 `;`。
