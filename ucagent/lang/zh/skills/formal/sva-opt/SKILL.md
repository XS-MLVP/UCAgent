---
name: coverage-optimization
description: 指导解释覆盖率报告并优化未覆盖死角的技能
---

# 形式化覆盖率优化工作流 (Coverage Optimization)

本技能指导如何根据覆盖率检查结果对断言集合进行增补，实现 COI 覆盖闭环。

> **COI 概念、fanin.rep 格式、信号映射表参见 `Guide_Doc/coi_coverage.md`**
> **SVA 编码规范参见 `Guide_Doc/sva_property.md`**

## 步骤

### 1. 读取 Checker 反馈

调用 Check → 读取 Checker 返回的 COI 覆盖率数据和未覆盖信号列表。

### 2. 分析每个未覆盖信号

对照 `Guide_Doc/coi_coverage.md` 中的信号→断言映射表，判断每个未覆盖信号：
- 是有效业务逻辑 → 需要补断言
- 是不可达死逻辑 → 标记 UNREACHABLE

### 3. 补充断言（先 spec 后 SVA）

1. 先在 `{OUT}/03_{DUT}_functions_and_checks.md` 中补充 `<CK-XXX>` 检测点
2. 然后在 `checker.sv` 中实现 SVA 断言（参考 `Guide_Doc/sva_property.md`）

⚠️ **必须用 assert 验证行为正确性，不能仅靠 cover 刷 COI**

### 4. 重跑验证

使用 `RunSkillScript` 工具执行以下命令重跑验证，并查看新的 COI：

```bash
python3 .ucagent/skills/coverage-optimization/scripts/run_formal_verification.py -dut_name {DUT}
```

### 5. 完成后调用 Complete

## 核心规则

1. 每个未覆盖信号至少需要一个 assert，仅 cover 引用不够
2. 补断言时必须先更新 spec 文档再改 checker.sv
3. UNREACHABLE 必须满足严格条件才能标记（参见 `Guide_Doc/coi_coverage.md`）
