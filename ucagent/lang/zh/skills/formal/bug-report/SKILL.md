---
name: bug-report
description: 自动解析环境分析文档中的 RTL_BUG 属性，生成 Bug 报告框架（04_{DUT}_bug_report.md），LLM 填写根因分析和修复建议。
---

# Bug 报告生成工作流 (Bug Report)

本技能指导如何生成并填写 Bug 报告文档 `04_{DUT}_bug_report.md`。

> **文档格式与归因方法参见 `Guide_Doc/bug_report.md`**

## 步骤

### 1. 生成报告框架

使用 `RunSkillScript` 工具执行以下命令生成报告骨架：

```bash
python3 .ucagent/skills/bug-report/scripts/init_bug_report.py -dut_name {DUT}
```

工具自动从 `07_{DUT}_env_analysis.md` 提取 RTL_BUG，生成报告框架。无 RTL_BUG 时生成无缺陷声明。

### 2. 填写分析内容

打开生成的文档，逐条填写每个 `[LLM-TODO]` 标记处的内容：
- 所有 `<FG-*>` 和 `<FC-*>` 标签必须来自 `03_{DUT}_functions_and_checks.md`
- 反例波形解读：按列表结构分点写出触发条件、关键信号值、预期输出和实际输出
- 如有多个 Bug，先按 `Guide_Doc/bug_report.md` 中的归因方法做聚类分析

### 3. 完成后调用 Complete

## 核心规则

1. 每个函数至少一个 assert
2. 若无 RTL_BUG，生成无缺陷声明即可
3. 多个 bug 若共享根因，必须在总结表中合并说明（参见 `Guide_Doc/bug_report.md`）
