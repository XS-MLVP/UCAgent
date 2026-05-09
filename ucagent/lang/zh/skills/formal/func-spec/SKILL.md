---
name: func-spec
description: 提取和分析被测模块(DUT)的功能规格和形式化检测点
---

# 功能规格与检测点分析工作流 (Functional Spec)

本技能指导如何基于给定的基础信息，细化出该 DUT 应该包含的具体功能检测点，并写入规划文档 `{OUT}/03_{DUT}_functions_and_checks.md`。

> **功能点标签规范、Style 标注规则与高级模式示例参见 `Guide_Doc/functions_and_checks.md`**

## 步骤

### 1. 读取基础信息
阅读输入说明、RTL 源码或预生成的文档骨架，理解 DUT 的核心功能。

### 2. 规划三级标签结构
按照 `Guide_Doc/functions_and_checks.md` 中的规范，使用 `<FG-XXX>` (功能组)、`<FC-XXX>` (功能点)、`<CK-XXX>` (检测点) 组织层级。

### 3. 标注断言推导 (Style)
**最重要的一步！** 每一个 `<CK-XXX>` 检测点后面，必须紧跟 `(Style: X)` 标注。X 根据规则取值为、`Assume`、`Comb`、`Seq` 或 `Cover`。详见 Guide_Doc 的定义部分。

### 4. 补充检测点描述
使用自然语言（或伪代码）描述"应该检查什么逻辑"。不要写具体的 SVA 语法（例如 `|->` 等），这部分属于 Stage 5 的工作。

### 5. 完成后调用 Complete

## 核心规则
1. 对于每一个状态转移或者核心功能 Seq 检测点，尽最大可能配对提供一个 Cover 检查（证明其可达性）。
2. 在规划阶段严禁编写真实的 SystemVerilog 代码，只写逻辑描述。
