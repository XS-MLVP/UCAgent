---
name: counterexample-testgen
description: 自动解析环境分析文档和 wrapper.sv，为每个 RTL_BUG 生成 Python 测试函数框架，LLM 填写引脚驱动和断言逻辑。
---

# 反例测试用例生成

## 概述

自动化生成 `{OUT}/tests/test_{DUT}_counterexample.py`，每个 RTL_BUG 对应一个测试函数框架（含 DUT 初始化、复位序列），LLM 只需在 `[LLM-TODO]` 处填写引脚驱动和断言。

## 步骤

### 1. 生成测试文件框架

调用工具 `InitTestFile`：

```python
InitTestFile(dut_name="{DUT}")
```

工具会自动从分析文档提取 RTL_BUG，从 wrapper.sv 识别时钟/复位端口，生成完整测试文件框架。

### 2. 填写测试逻辑

对于每个测试函数中的 `[LLM-TODO]`：读取 avis.log 反例信息 + RTL 源码，填写引脚驱动和 assert 断言。

### 3. 完成后调用 Complete

## 核心规则

1. 每个函数至少一个 assert，末尾调用 `dut.Finish()`
2. 若无 RTL_BUG，生成注释文件即可
