---
name: env-generation
description: Formal 验证环境（Checker & Bind Wrapper）的配置与构建指南
---

# 形式化验证环境构建工作流 (Environment Generation)

本技能指导如何在使用 `GenerateFormalEnv` 工具生成基础代码后，进一步完善自动生成的 checker 和 wrapper 文件。

> **Checker 模块结构与编码细节参见 `Guide_Doc/checker_module.md`**
> **SVA 编码规范参见 `Guide_Doc/sva_property.md`（§3.6 Assume 禁忌）**

## 步骤

### 1. 完善符号化索引

如果 RTL 包含数组型寄存器、同构实例或 `generate` 循环，取消 wrapper 中 `fv_idx` 和 `fv_mon_...` 占位符的注释，并根据 RTL 信号路径完成 Mux 逻辑。

判断标准和操作细节参见 `Guide_Doc/checker_module.md`。

### 2. 导出白盒信号

在 `wrapper.sv` 中将 DUT 内部的关键信号（指针、状态机状态、标志位等）提取出来，接入 checker 模块端口。

### 3. 时序极性确认

检查 wrapper 顶部 `Clock/Reset Remapping` 区域，确认复位极性映射正确。

### 4. 保留 SVA 骨架

`GenerateFormalEnv` 已从 `03_{DUT}_functions_and_checks.md` 提取标签追加到 checker.sv 末端（`[LLM-TODO]` 标记）。**此阶段不要填写它们**，SVA 编写属于 Stage 5。

### 5. 禁止添加 Assume

本阶段禁止自行添加 `assume property`。所有 assume 必须在 Stage 5 中统一从 spec 文档 `(Style: Assume)` 检测点实现。

## 核心规则

1. 本阶段仅做环境配置，不写断言逻辑
2. 禁止隐式约束（如用 `assign` 强制拉死输入信号）
3. wrapper 中导出的信号名必须与 checker 端口声明一致
