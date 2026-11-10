---
name: sva-opt
description: 指导解释覆盖率报告并优化未覆盖死角的技能
---

# 形式化覆盖率优化工作流 (Coverage Optimization)

本技能指导如何根据覆盖率检查结果对断言集合进行增补，实现 COI 覆盖闭环。

本阶段的主要写入口是 `.formal_records.yaml.spec` 与对应的 `sva_body` 字段。

> **COI 概念、fanin.rep 格式、信号映射表参见 `Guide_Doc/coi_coverage.md`**
> **SVA 编码规范参见 `Guide_Doc/sva_property.md`**

执行说明：
- 在本工作流中，请优先通过 `RunSkillScript` 调用技能脚本
- 不要假设宿主 `python3` 环境具备所有依赖
- `checker.sv` 是派生产物，新增断言后应以 full refresh 生成结果为准

## 步骤

### 1. 读取 Checker 反馈

调用 Check → 读取 Checker 返回的 COI 覆盖率数据和未覆盖信号列表。
Formal 工具的执行时间可能很长，尤其在多时钟域和大状态空间设计上，这是正常现象。不要因为短时间没有输出就频繁中断或重试，优先等待更长时间的结果再做判断。

### 2. 分析每个未覆盖信号

对照 `Guide_Doc/coi_coverage.md` 中的信号→断言映射表，判断每个未覆盖信号：
- 是有效业务逻辑 → 需要补断言
- 是不可达死逻辑 → 标记 UNREACHABLE

### 3. 补充断言（先更新 YAML，再自动同步）

1. 使用 `update_spec.py` 在 `.formal_records.yaml` 中新增 `CK-XXX` 检测点条目。
2. 使用 `update_sva_body.py` 为新检测点编写 SVA 代码实现：

```bash
python3 .ucagent/skills/ext/formal/sva-gen/scripts/update_sva_body.py <CK-ID> "<SVA_CODE_BODY>"
```

3. 调用 `PropertyStructureChecker`。系统会自动根据最新的 YAML 渲染并覆盖 `checker.sv`，确保新断言生效。

⚠️ **必须用 assert 验证行为正确性，不能仅靠 cover 刷 COI**


### 4. 重跑受管理证明批次

修改 YAML 并完成环境生成后调用 `RunFormal(action="run")`；`RunFormal(action="status")` 查看 5 分钟和 20 分钟快照。对超出预算的未解决属性先分析原因，再使用 `RunFormal(action="review", property_names=["完整属性名"], disposition="retry" 或 "defer", reason="具体分析", next_action="下一步")` 记录处置。暂缓是 UNPROVEN，不得视作 Pass。运行与处置契约见 `Guide_Doc/formal_execution.md`；证明仅通过 RunFormal 启动。

### 5. 完成后调用 Complete

## 核心规则

1. 每个未覆盖信号至少需要一个 assert，仅 cover 引用不够
2. 补断言时必须先更新 `.formal_records.yaml`，不要直接编辑 checker.sv
3. UNREACHABLE 必须满足严格条件才能标记（参见 `Guide_Doc/coi_coverage.md`）
