---
name: env-analysis
description: 自动解析 avis.log 生成环境分析文档框架（07_{DUT}_env_analysis.md），预填 TT/FA 条目空壳，LLM 逐条填写分析内容。
---

# 环境分析文档生成

## 概述

自动化生成 `{OUT}/07_{DUT}_env_analysis.md`，解析 avis.log 预填所有 `<TT-NNN>` 和 `<FA-NNN>` 条目空壳，LLM 只需在 `[LLM-TODO]` 处填写分析内容。

## 步骤

### 1. 生成文档框架

调用工具 `InitEnvAnalysis`：

```python
InitEnvAnalysis(dut_name="{DUT}")
```

工具会自动解析 `avis.log`，生成文档框架（含概览表、TT/FA 条目空壳、健康度总结表）。已有文件自动备份为 `.bak`。

### 2. 填写分析内容

打开生成的文档，逐条填写每个 `[LLM-TODO]` 标记处的内容（根因分类、关联 Assume、判定结果、反例分析等）。

### 3. 更新健康度总结

填写文档末尾的统计表。

## 核心规则

1. ACCEPTED 的 TRIVIALLY_TRUE 比例不得超过 50%
2. RTL Bug 标记**仅在本文档中完成**，不在 checker.sv 中添加标记
3. 每个异常属性都必须有分析条目，遗漏将被 Checker 拒绝
