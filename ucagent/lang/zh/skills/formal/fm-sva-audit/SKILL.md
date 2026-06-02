---
name: sva-audit
description: 环境分析技能。Checker 已自动解析日志并生成骨架，LLM 仅需通过脚本填写分析详情。
---

# 环境分析工作流 (Environment Analysis)

本技能指导如何分析验证结果并通过 **`update_analysis.py` 脚本** 将分析写入 `.formal_records.yaml`。

> **注意**：得益于自动化升级，Checker 在执行验证后已自动在 `.formal_records.yaml` 中为所有异常属性生成了 `[LLM-TODO]` 骨架。你不再需要手动运行初始化脚本。

## 步骤

### 1. 查看待填写条目

首先运行以下命令，查看有哪些属性需要分析（标记为 `❌` 的条目）：

```bash
python3 .ucagent/skills/formal/fm-sva-audit/scripts/update_analysis.py -action show
```

### 2. 填写 TRIVIALLY_TRUE 分析

对于日志中出现的 `TRIVIALLY_TRUE` 属性（通常是由于 Assume 过约束导致），使用以下命令填写：

```bash
python3 .ucagent/skills/formal/fm-sva-audit/scripts/update_analysis.py \
  -type tt -id TT-001 \
  -root_cause ASSUME_TOO_STRONG \
  -related_assume M_CK_API_INPUT_KNOWN \
  -analysis "输入约束过强导致属性永真" \
  -action_val FIXED \
  -action_detail "放宽 assume 约束条件"
```

**root_cause 枚举值：** `ASSUME_TOO_STRONG` / `SIGNAL_CONSTANT` / `WRAPPER_ERROR` / `DESIGN_EXPECTED`
**action 枚举值：** `FIXED` / `ACCEPTED`

### 3. 填写 FALSE 属性分析

对于 `FALSE` 属性（断言失败或 Cover 失败），使用以下命令分类：

```bash
python3 .ucagent/skills/formal/fm-sva-audit/scripts/update_analysis.py \
  -type fa -id FA-001 \
  -resolution RTL_BUG \
  -analysis "RTL 中 sum 位宽定义错误导致断言失败" \
  -action_detail "修改 output [WIDTH-2:0] 为 [WIDTH-1:0]"
```

**resolution 枚举值：** `RTL_BUG` / `ENV_FIXED` / `ENV_PENDING` / `COVER_EXPECTED_FAIL`

### 4. 增量更新 (可选)

如果你修改了 SVA 代码或约束并重跑了验证，Checker 会自动检测新异常并追加骨架。若需手动触发同步，可运行：

```bash
python3 .ucagent/skills/formal/fm-sva-audit/scripts/env_analysis.py -mode update
```

### 5. 完成后调用 Complete/Check

Checker 会验证所有条目是否已填写完整（无 `[LLM-TODO]`），通过后自动重燃 `07_{DUT}_env_analysis.md` 文档。

## 常见环境错误修复指南 (Troubleshooting)

如果在运行 EDA 工具时遇到语法错误（Syntax Error），请按以下优先级修复：

### 1. 缺失参数 (如 `WIDTH` 未定义)
**禁止直接修改 `wrapper.sv`！** 改动会被系统自动渲染覆盖。
应使用 `update_spec.py` 将参数记录在 YAML 中：
```bash
python3 .ucagent/skills/formal/func-spec/scripts/update_spec.py -action set_param -id WIDTH -value 64
```
完成后重新调用 `Check`，系统会自动渲染生成带参数定义的 SV 环境。

### 2. 信号位宽错误或缺失内部信号
**禁止直接修改 `wrapper.sv`！**
应使用 `add_signal` 动作：
```bash
python3 .ucagent/skills/formal/func-spec/scripts/update_spec.py -action add_signal -desc "logic [WIDTH-1:0] my_internal_sig"
```

## 核心规则

1. **禁止直接编辑 YAML**：必须通过脚本操作。
2. **禁止直接编辑生成的 SV 文件进行参数修复**：所有的参数化配置（WIDTH等）必须沉淀在 YAML 中。
3. **ACCEPTED 比例限制**：标记为 `ACCEPTED` 的 TRIVIALLY_TRUE 比例不应过高，优先尝试通过修改约束来修复 (`FIXED`)。
4. **阻塞规则**：`ENV_PENDING` 状态的属性会阻止工作流推进，必须修复环境后改为 `ENV_FIXED`。

