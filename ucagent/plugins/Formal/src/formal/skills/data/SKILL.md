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

可查看 `overview`、`planning`、`basic_info`、`spec`、`analysis`、`bugs`、`summary`。先用默认视图只看缺项和最小请求；需要修改既有正文时加`--full`，需要完整契约才加`--schema`，所有节选项一致。可选事实表不必重复填满。更新成功后直接使用返回的新sha256、剩余缺项和下一步，不必为确认写入再inspect。分页用`--offset/--limit`；basic_info.clock_count未知需核实，确无时钟才填0。

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

分析补丁用`review_items.contract_id`查询共享`review_contracts`：FA填写`analysis/resolution/action_detail`，assert归为RTL_BUG时同时填写`expected_requirement`和可选`reference_calculations`，首次完成规格关系与计算绑定，结果随update返回供后续复用。`resolution`按机器类型选assert的`RTL_BUG/ENV_PENDING`或cover的`COVER_EXPECTED_FAIL/ENV_PENDING`；FA不填TT的`root_cause/action/related_assume`。TT填写`analysis/root_cause/action`，仅`DESIGN_EXPECTED/ACCEPTED`可接受当前恒真。精确id/prop_name不变，机器引用与计算结果不填。批量有错整批不写入。

更新后pending集合会变化，按`after_update_command`从offset 0重新准备；next_offset只用于不变队列的只读翻页。不要因旧偏移返回空页就宣称完成，错误偏移会给出明确诊断。

环境分析完成后，用`prepare bugs`取得`reused_analysis`，无需重读同一反例、重新计算或再次填写规格。只补根因分组、源码位置、修复建议和可选`impact_assessment`；后者是人工影响推断，不能冒充所有输入上的证明。Bug的`description/trigger/actual/expected_requirement/reference_calculations/expected/reference_results`均派生，不提交。没有新证据或矛盾时，按现有已审内容继续，完整例子见`Guide_Doc/formal_data.md`。

没有待填项时无需提交空请求。填写完成后，按阶段要求记录日志并调用 `Complete`；需要定位问题时才调用 `Check`。总结的统计和 Bug 表由已验证记录生成，不再填写 `severe_bugs`。

## 边界与无技能路径

完整数据、产物示例和验收规则见 `Guide_Doc/formal_data.md`、`Guide_Doc/env_analysis.md`、`Guide_Doc/bug_report.md` 与 `Guide_Doc/formal_summary.md`。机器引用保证来源关联，不保证人工手算正确；没有独立核验的数字不要声称已验证。

技能禁用或目录缺失时，直接用普通文件工具维护同一 `.formal_records.yaml`。由 `Check` 建立分析队列，使用 `RunFormal(action="evidence")` 获取并填写精确的当前证据引用；生成相同产物并满足相同门禁，不得因此跳过工作或修改原有 Skill 运行机制。
