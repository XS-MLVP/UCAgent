---
name: data
description: 批量维护 Formal 任务数据、准备当前分析队列并核验输入版本；通过原有 RunSkillScript 执行。
---

# Formal 数据维护

这是可选的数据维护路径，不是独立工具，也不替代规格理解、断言设计或反例分析。使用现有 `ListSkill` 获取本技能，再用 `ReadTextFile` 阅读本文件；后续各阶段可复用该方法，不需要为每阶段重新登记技能使用。

## 查看字段与批量更新

通过现有 `RunSkillScript` 调用脚本，`commands` 中每一项仍是 `[技能ID, 脚本名, 参数字符串]`：

```json
{"commands":[["ext/formal/data","formal_data.py","inspect planning"]]}
```

可查看 `overview`、`planning`、`basic_info`、`spec`、`analysis`、`bugs`、`summary`。结果给出 `sha256`、字段契约、所有当前缺项以及 `ready_update`。分页时使用 `--offset` 和 `--limit`。

1. 用普通文件工具把填好的 `ready_update` 写入输出目录下的 JSON 请求文件，例如 `formal_test/data_update.json`。
2. 请求文件只有 `section`、`expected_sha256`，以及 `data` 或 `bodies` 二选一；不要加入 `action`，不要把整段 JSON 拼进命令参数。
3. 调用：

```json
{"commands":[["ext/formal/data","formal_data.py","update --request-file formal_test/data_update.json"]]}
```

请求版本冲突时重新 inspect，再基于新版本提交。不要更改机器结果、运行状态或证据来消除失败。

## 准备分析与 Bug 记录

先通过 `RunFormal(action="run")` 执行当前证明，再以 `RunFormal(action="status")` 等待结果。停止后可以一次准备完整队列：

```json
{"commands":[["ext/formal/data","formal_data.py","prepare analysis"]]}
```

结果包含精确分析 ID、完整属性名、原始证据及可直接填写的 `ready_update`，不必先制造一次失败的 Check 来初始化。按证据和规格填写分析及分类；证据引用由脚本校验后绑定，不由请求文件填写。常量真可能是合法恒等式，常量假可能是静态契约失败，都不能仅为变绿而改弱目标。

环境分析完成后，用 `prepare bugs` 准备 Bug 观察项。可在更新中使用显式 `shared.root_cause_id` 和共享根因、修复建议；每条观察仍保留其真实触发、预期及实际行为。失败属性数不等于独立缺陷数。

没有待填项时无需提交空请求。填写完成后，按阶段要求记录日志并调用 `Complete`；需要定位问题时才调用 `Check`。总结的统计和 Bug 表由已验证记录生成，不再填写 `severe_bugs`。

## 边界与无技能路径

完整数据、产物示例和验收规则见 `Guide_Doc/formal_data.md`、`Guide_Doc/env_analysis.md`、`Guide_Doc/bug_report.md` 与 `Guide_Doc/formal_summary.md`。机器引用保证来源关联，不保证人工手算正确；没有独立核验的数字不要声称已验证。

技能禁用或目录缺失时，直接用普通文件工具维护同一 `.formal_records.yaml`。由 `Check` 建立分析队列，使用 `RunFormal(action="evidence")` 获取并填写精确的当前证据引用；生成相同产物并满足相同门禁，不得因此跳过工作或修改原有 Skill 运行机制。
