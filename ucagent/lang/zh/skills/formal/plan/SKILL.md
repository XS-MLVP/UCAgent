---
name: formal-plan
description: 通过脚本把验证规划写入 .formal_records.yaml 的 planning 字段，并由系统自动渲染 01 规划文档。
---

# Formal Planning

本技能用于维护 `.formal_records.yaml` 中的 `planning` 字段。

本阶段的唯一事实来源是 `.formal_records.yaml.planning`。

核心规则：
1. 禁止直接编辑 `01_{DUT}_verification_needs_and_plan.md`
2. 只能通过 `RunSkillScript` 调用 `update_plan.py` 修改 YAML
3. `01_{DUT}_verification_needs_and_plan.md` 是派生产物，Checker 通过后系统会自动重建

执行说明：
- 在本工作流中，请优先通过 `RunSkillScript` 调用技能脚本
- 不要假设宿主 `python3` 环境具备所有依赖

常用命令：

```bash
python3 .ucagent/skills/formal/plan/scripts/update_plan.py -action show
python3 .ucagent/skills/formal/plan/scripts/update_plan.py -action set -path project_overview -value "这是一个..."
python3 .ucagent/skills/formal/plan/scripts/update_plan.py -action append -path assumptions -value "\"输入 valid 仅在握手期间有效\""
```

字段清单：

- `project_overview`：项目概述，字符串
- `design_spec_analysis.parameters[]`：参数列表，每项包含 `name/default/range/note`
- `design_spec_analysis.interfaces[]`：接口列表，每项包含 `name/direction/width/note`
- `complexity.state_space`：状态空间复杂度，字符串
- `complexity.arithmetic_complexity`：算术复杂度，字符串
- `complexity.storage_complexity`：存储复杂度，字符串
- `complexity.parameterization`：参数化影响，字符串
- `verification_scope.included[]`：纳入验证范围的目标
- `verification_scope.excluded[]`：暂不覆盖范围及原因
- `assumptions[]`：形式化环境假设
- `strategy[]`：验证策略、分层方法、关键检查方向
- `deliverables[]`：预期交付物
- `risks[]`：风险列表，每项包含 `risk/mitigation`
- `initial_bug_suspicions[]`：初步缺陷线索

最小骨架：

```yaml
planning:
  project_overview: ""
  design_spec_analysis:
    parameters: []
    interfaces: []
  complexity:
    state_space: ""
    arithmetic_complexity: ""
    storage_complexity: ""
    parameterization: ""
  verification_scope:
    included: []
    excluded: []
  assumptions: []
  strategy: []
  deliverables: []
  risks: []
  initial_bug_suspicions: []
```

推荐填写顺序：

1. 先写 `project_overview`，用 2 到 4 句说明 DUT 作用、输入输出和验证目标。
2. 再补 `design_spec_analysis` 与 `complexity`，这些字段决定规划文档的技术上下文。
3. 明确 `verification_scope`、`assumptions`、`strategy`，避免后续 SVA 方向发散。
4. 最后补 `deliverables`、`risks`、`initial_bug_suspicions`，用于收束执行计划。

写入约束：

- `parameters` 与 `interfaces` 必须写成对象数组，不要写自由文本段落。
- `verification_scope.included` 与 `verification_scope.excluded` 必须分别列出，不能混写。
- `risks[]` 的每一项都必须同时包含 `risk` 和 `mitigation`。
- 如果某项暂时未知，保留空字符串或空数组，不要自造额外键名。
