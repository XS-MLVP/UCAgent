---
name: sva-property-generation
description: 基于 SVA 规范编写属性检测代码
---

# SVA 断言生成工作流 (SVA Property Generation)

本技能指导如何将 checker.sv 中的 `[LLM-TODO]` 骨架翻译为完整的 SVA 断言代码。

> **编码规范与代码模板参见 `Guide_Doc/sva_property.md`**

## 步骤

### 1. 读取骨架代码

读取 `{OUT}/tests/{DUT}_checker.sv`，定位所有 `[LLM-TODO]` 占位符。每个占位符对应规范文档 `03_{DUT}_functions_and_checks.md` 中的一个检测点 `<CK-XXX>`。

### 2. 确认 Style 标签

对每个 `[LLM-TODO]`，确认注释中标注的 Style（Assume / Seq / Comb / Cover），选择 `Guide_Doc/sva_property.md` 中对应的代码模板填写。

### 3. 逐条填写 SVA

按照以下命名规则实现（参见 `Guide_Doc/sva_property.md` §1.5）：
- property 名使用 `CK_` 前缀
- 实例化标签：Assume → `M_CK_`、Assert → `A_CK_`、Cover → `C_CK_`

### 4. 代码位置

所有 SVA 代码必须在 `module ... endmodule` 内部，放在对应的 FG 分组区域中。

### 5. 完成后调用 Complete

## 核心规则

1. **禁止使用 `` `define `` 宏格式**：必须使用 `property ... endproperty` + 带标签实例化
2. **禁止 `|-> 1'b1` 占位符断言**：写不出来就留 `// TODO:` 注释
3. 使用 `$past` 前检查是否真的需要上一拍的值
4. 绝对不要对输出或内部信号加 `assume property`
5. 每个 property 和实例化语句都以 `;` 结尾
