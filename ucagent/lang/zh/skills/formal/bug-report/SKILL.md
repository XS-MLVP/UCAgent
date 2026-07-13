---
name: bug-report
description: 从 analysis 中提取 RTL_BUG 属性，LLM 通过脚本将 Bug 详细信息写入 .formal_records.yaml。
---

# Bug 报告生成工作流 (Bug Report)

本技能指导如何从验证分析中提取 RTL Bug 并通过 **脚本** 将报告写入 `.formal_records.yaml`。

本阶段的唯一事实来源是 `.formal_records.yaml.bugs`。

> **文档格式与归因方法参见 `Guide_Doc/bug_report.md`**

执行说明：
- 在本工作流中，请优先通过 `RunSkillScript` 调用技能脚本
- 不要假设宿主 `python3` 环境具备所有依赖
- `04_{DUT}_bug_report.md` 是派生产物，不要直接编辑

## 步骤

### 1. 生成 Bug 骨架

Bug 骨架由 Checker 根据 `.formal_records.yaml.analysis.fa_entries` 中标记为 `RTL_BUG` 的属性自动生成。
你不需要手动运行初始化脚本。

### 2. 查看待填写条目

```bash
python3 .ucagent/skills/formal/bug-report/scripts/update_bug.py -action show
```

### 3. 填写 Bug 详情

**禁止直接编辑 YAML**，使用 `RunSkillScript` 调用脚本：

```bash
python3 .ucagent/skills/formal/bug-report/scripts/update_bug.py \
  -id BG-FORMAL-001 \
  -fg_id FG-ARITHMETIC \
  -fc_id FC-ADD-BASIC \
  -rtl_file Adder/Adder.v \
  -rtl_line 10 \
  -description "sum 位宽错误导致加法结果不完整" \
  -root_cause "output [WIDTH-2:0] sum 位宽参数错误" \
  -trigger "当 a + b + cin >= 2^63 时触发" \
  -expected "sum[63:0] 输出完整的 64 位加法结果" \
  -actual "sum[62:0] 仅输出 63 位" \
  -fix "将 Adder.v 第 10 行改为 output [WIDTH-1:0] sum" \
  -severity HIGH \
  -confidence HIGH
```

**severity 枚举值：** `HIGH` / `MEDIUM` / `LOW`
**confidence 枚举值：** `HIGH` / `MEDIUM` / `LOW`

### 4. 完成后调用 Check

Checker 验证所有字段已填写（非 `[LLM-TODO]`），通过后自动重建 `04_{DUT}_bug_report.md`。

## 核心规则

1. 每个 `RTL_BUG` 属性都必须有对应的 bug 条目
2. 若无 RTL_BUG，`bugs` 设为空数组 `[]`
3. `fg_id`、`fc_id` 必须来自 `spec` 中的标签
4. 多个 bug 若共享根因，必须在各自条目中注明关联
