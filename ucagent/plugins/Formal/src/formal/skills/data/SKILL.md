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

1. 用普通文件工具把填好的 `ready_update` 写入工具返回的 `request_artifact`。路径随当前任务的 OUT 变化。
2. 请求文件包含 `section`、`expected_sha256` 及 `data` 或 `bodies`。白盒绑定和属性可按指南中的 spec 请求一起提交。用文件路径调用 update。
3. 使用同一响应返回的 `update_call`。例如：

```json
{"commands":[["ext/formal/data","formal_data.py","update --request-file formal_test/data_update.json"]]}
```

请求版本冲突时重新 inspect，再基于新版本提交。不要更改机器结果、运行状态或证据来消除失败。

## 准备分析与 Bug 记录

先通过 `RunFormal(action="run")` 执行当前证明，再以 `RunFormal(action="status")` 等待结果。停止后按小批准备当前待审项：

```json
{"commands":[["ext/formal/data","formal_data.py","prepare analysis"]]}
```

默认最多5项并受字符预算限制。`items`把精确分析ID、完整属性名和证据摘要放在一起；`full_evidence_call`取省略事实，`trace_discovery_call`用于时序疑问；`ready_update`可直接填写，不必先制造一次失败的 Check 来初始化。按证据和规格填写分析及分类；证据引用由脚本校验后绑定，不由请求文件填写。常量真可能是合法恒等式，常量假可能是静态契约失败，都不能仅为变绿而改弱目标。

分析补丁用`items.contract_id`查询共享`review_contracts`：FA填写`analysis/resolution/action_detail`，assert归为RTL_BUG时同时填写`expected_requirement`和可选`reference_calculations`，首次完成规格关系与计算绑定，结果随update返回供后续复用。`resolution`按机器类型选assert的`RTL_BUG/ENV_PENDING`或cover的`COVER_EXPECTED_FAIL/ENV_PENDING`；FA不填TT的`root_cause/action/related_assume`。TT填写`analysis/root_cause/action`，仅`DESIGN_EXPECTED/ACCEPTED`可接受当前恒真。精确id/prop_name不变，机器引用与计算结果不填。批量有错整批不写入。

更新后pending集合会变化，按`after_update_command`从offset 0重新准备；next_offset只用于不变队列的只读翻页；实际条目数可能小于limit，使用返回的next_offset，不自行加limit。不要因旧偏移返回空页就宣称完成，错误偏移会给出明确诊断。

环境分析完成后，用`prepare bugs`取得`items[].reviewed_analysis`，无需重读同一反例、重新计算或再次填写规格。只补根因分组、源码位置、修复建议和可选`impact_assessment`；后者是人工影响推断，不能冒充所有输入上的证明。Bug的`description/trigger/actual/expected_requirement/reference_calculations/expected/reference_results`均派生，不提交。没有新证据或矛盾时，按现有已审内容继续，完整例子见`Guide_Doc/formal_data.md`。

没有待填项时无需提交空请求。人工分析、根因和总结遵循 `Guide_Doc/bug_report.md`“问题表述要求”：先用白话说清条件、位置、预期与实际差异及后果，必要术语首次解释，不自造名称、不以术语掩盖未确认原因。填写完成后，按阶段要求记录日志并调用 `Complete`；需要定位问题时才调用 `Check`。总结的统计和 Bug 表由已验证记录生成，不再填写 `severe_bugs`。

## 分批实现与复验

先用 RunFormal(action="pending") 获取 current_fc，再用 `prepare sva` 取得该 FC 的待补检查点及 `ready_update`。填写后定向运行，按返回模板用 RunFormal(action="review_fc") 处理异常，关闭当前 FC 后才能领取下一批。ENV_PENDING 必须在当前阶段修复，不能以曾运行或文字完成标记替代。用 `inspect signals --query 名称` 查白盒信号的实际名称和位宽。相关绑定与属性可同批提交，格式见 `Guide_Doc/formal_data.md`。

第 5 阶段直接调用 RunFormal(action="preflight") 完成自动临时冒烟，不填写正式 CK；临时结果不参加功能验收。第 6 阶段用 `prepare sva --assumptions` 领取正式环境 Assume，再用 `prepare sva --function FC-<ID>` 实现功能点。写 Assume 前逐项对照返回的 `description` 和规格。遇到描述中混合了独立端口义务的 CK，先按 `Guide_Doc/functions_and_checks.md` 调整 spec，然后重新领取这些 CK 并逐条填写 `sva_body`。

属性体修正后，以精确 ck_ids 和 scope=selected 复验修改目标。完整功能批次改用 fc_id。后续 status/evidence/review/cancel 使用返回的 run_id。定向批保留完整 Assume，合并本轮修复后对当前输入运行完整批次。可将同一 RunFormal 请求写入 JSON，调用 `formal_data.py proof --request-file formal_test/proof_request.json`。无技能时直接使用 RunFormal。

## 边界与无技能路径

完整数据、产物示例和验收规则见 `Guide_Doc/formal_data.md`、`Guide_Doc/env_analysis.md`、`Guide_Doc/bug_report.md` 与 `Guide_Doc/formal_summary.md`。机器引用保证来源关联，不保证人工手算正确；没有独立核验的数字不要声称已验证。

技能禁用或目录缺失时，直接用普通文件工具维护同一 `.formal_records.yaml`。由 `Check` 建立分析队列，使用 `RunFormal(action="evidence")` 获取并填写精确的当前证据引用；生成相同产物并满足相同门禁，不得因此跳过工作或修改原有 Skill 运行机制。
