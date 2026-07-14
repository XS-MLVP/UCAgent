---
name: formal-summary
description: 通过脚本把最终总结写入 .formal_records.yaml 的 summary 字段，并由系统自动渲染 05 总结文档。
---

# Formal Summary

本技能用于维护 `.formal_records.yaml` 中的 `summary` 字段。

本阶段的唯一事实来源是 `.formal_records.yaml.summary`。

核心规则：
1. 禁止直接编辑 `05_{DUT}_formal_summary.md`
2. 只能通过 `RunSkillScript` 调用 `update_summary.py` 修改 YAML
3. `05_{DUT}_formal_summary.md` 是派生产物，Checker 会结合 run_results、coverage、bugs 自动校验并重建

执行说明：
- 在本工作流中，请优先通过 `RunSkillScript` 调用技能脚本
- 不要假设宿主 `python3` 环境具备所有依赖

常用命令：

```bash
python3 .ucagent/skills/formal/summary/scripts/update_summary.py -action show
python3 .ucagent/skills/formal/summary/scripts/update_summary.py -action set -path acceptance_conclusion -value "当前存在高严重度 RTL bug，不建议验收"
python3 .ucagent/skills/formal/summary/scripts/update_summary.py -action append -path severe_bugs -value '{"bug_id":"BG-FORMAL-001","bug_type":"RTL_BUG","desc":"位宽错误","checker_link":"A_CK_ADD_RESULT"}'
```

字段清单：

- `core_function`：对 DUT 核心功能的总结
- `overall_result`：整体验证结果结论
- `coi_assessment.unreachable_notes[]`：COI 或不可达逻辑说明
- `completeness.safety`：安全性检查覆盖说明
- `completeness.liveness`：活性检查覆盖说明
- `completeness.cover`：cover 完整性说明
- `severe_bugs[]`：高严重度问题列表，每项包含 `bug_id/bug_type/desc/checker_link`
- `acceptance_conclusion`：是否建议验收及理由

最小骨架：

```yaml
summary:
  core_function: ""
  overall_result: ""
  coi_assessment:
    unreachable_notes: []
  completeness:
    safety: ""
    liveness: ""
    cover: ""
  severe_bugs: []
  acceptance_conclusion: ""
```

推荐填写顺序：

1. 先根据 `run_results`、`coverage`、`bug_records` 写 `overall_result`。
2. 再总结 `core_function` 与 `completeness`，交代本次形式化覆盖了什么、还缺什么。
3. 如存在高严重度问题，逐条写入 `severe_bugs[]`，并补齐 `checker_link`。
4. 最后写 `acceptance_conclusion`，明确是否可验收。

写入约束：

- `summary` 只写人工判断和结论，不要手动填写统计数字；通过率、覆盖率、bug 数量由系统自动汇总。
- `severe_bugs[]` 仅记录高严重度问题，普通提示或待确认项不要混入这里。
- `checker_link` 应指向可定位的 checker 名称或断言标识，避免只写“见日志”。
