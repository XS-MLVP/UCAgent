---
name: env-analysis
description: 自动解析 avis.log 生成环境分析文档框架（07_{DUT}_env_analysis.md），预填 TT/FA 条目空壳，LLM 逐条填写分析内容。
---

# 环境分析工作流 (Environment Analysis)

本技能指导如何生成并填写环境分析文档 `07_{DUT}_env_analysis.md`。

> **文档格式与判定方法参见 `Guide_Doc/env_analysis.md`**

## 步骤

### 1. 生成文档框架

使用 `RunSkillScript` 工具执行以下命令初始化文档：

```bash
python3 .ucagent/skills/env-analysis/scripts/env_analysis.py -mode init -dut_name {DUT}
```

工具自动解析 `avis.log`，生成含概览表和 TT/FA 条目空壳的文档。已有文件自动备份为 `.bak`。

### 2. 填写分析内容

打开生成的文档，逐条填写每个 `[LLM-TODO]` 标记处的内容。

- **TRIVIALLY_TRUE**：按 `Guide_Doc/env_analysis.md` 中的根因分类填写
- **FALSE**：按 `Guide_Doc/env_analysis.md` 中的判定决策树填写

### 3. 增量迭代

修改 checker.sv 后重跑验证，如出现新异常，调用：

```bash
python3 .ucagent/skills/env-analysis/scripts/env_analysis.py -mode update -dut_name {DUT}
```

工具仅追加新条目，保留已分析内容。

### 4. 完成后调用 Complete

## 核心规则

1. ACCEPTED 的 TRIVIALLY_TRUE 比例不得超过 50%
2. RTL Bug 标记**仅在本文档中完成**，不在 checker.sv 中添加标记
3. 每个异常属性都必须有分析条目，遗漏将被 Checker 拒绝
4. `ENV_PENDING` 状态的属性会阻止工作流推进，必须修复后改为 `ENV_FIXED`
