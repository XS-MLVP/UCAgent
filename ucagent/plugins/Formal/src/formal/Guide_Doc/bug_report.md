
# 形式化缺陷报告

本阶段依据已核验的 `RTL_BUG` 分析填写缺陷观测，Check生成 `04_{DUT}_bug_report.md`。使用可选数据技能或普通文件工具维护同一YAML，以RunFormal evidence核对真实证据，不手写派生Markdown。公共数据完整例子见 `Guide_Doc/formal_data.md`。

## 提交与验收

1. 技能可用时，通过原有RunSkillScript调用ext/formal/data的`formal_data.py prepare bugs`，取得精确观测和ready_update；无技能时Check协调条目，用普通文件工具读取并填写同一bugs子树。
2. 复用首次FA分析的规格关系、真实观测和参考计算；prepare bugs返回`reused_analysis`。同一当前证据无需重新读原始反例、另起脚本计算或重写规格；发现新问题或证据/表达式变化才回到analysis修订。静态失败不编造输入序列。
3. 数据技能可用`data.shared`一次提交共同根因及entries；将完整结构化请求写JSON文件，再经RunSkillScript调用`update --request-file`，不拼shell内嵌JSON。无技能时各YAML观测保留一致的共享值。
4. 日志后Complete，Check只用于实际诊断。无RTL_BUG时不制造占位Bug；修复建议未经新验证不得称已通过。

`shared` 可含 `root_cause_id/root_cause/fix/severity/confidence`，必须有明确的非空root_cause_id。`entries`只补精确id/property及源码归属字段，已填字段不重复提交；可选`impact_assessment`单列人工影响推断。`description/trigger/actual/expected_requirement/reference_calculations/expected/reference_results`在Bug节均由当前FA分析和机器证据派生，不在本阶段重写。严重度/置信度从HIGH/MEDIUM/LOW选择，共享字段不能冲突。

当前反例只证明该反例上的行为，不能单独证明“所有输入”或故障比例。根因依据源码给出并标为人工评估；影响推断未知时留空，报告默认只声明当前反例或静态检查范围。需要修订规格关系或参考表达式时回到analysis一次更新，完整请求见`Guide_Doc/formal_data.md`“规格预期与可复现参考计算”。保存采样不自动等于失败周期，数据不可用时不推断零值。

失败属性数量是观测数，独立root_cause_id数量是根因数。相同根因只维护一次原因与修复，各条目保留自己的触发和输出证据。Cover、UNPROVEN、超时或工具故障不能登记成RTL Bug；属性参考计算错误必须先修至通过。

## 完整报告参考

下面是两个属性观测关联一个根因的完整渲染布局。真实名称、位置和数值必须来自当前任务与证据；不得复制本例作为证明。报告从标题到最后分隔线与生成模板一致。

```markdown

# PacketGate 形式化验证缺陷报告

> 本文档由 `.formal_records.yaml` 自动生成，请勿手动编辑。

本报告记录了 2 条失败属性观测，关联 1 个独立根因。

机器观测只覆盖记录中的反例或静态检查；不会由单个反例证明所有输入上的影响。规格解释、根因和影响范围推断均为人工评估，须与机器观测区分。

## Root causes

### ROOT-PACKET-ELIGIBILITY

- Root cause (人工源码归因，不是影响范围证明): 共同资格条件取反，导致两侧输出不符合规格。
- Fix: 修正共同资格条件，按原目标重新运行并检查真实结果。
- Severity: HIGH
- Properties: u_left.A_CK_PACKET_ELIGIBLE, u_right.A_CK_PACKET_ELIGIBLE

---

## Failed Property: `u_left.A_CK_PACKET_ELIGIBLE`

### <FG-LOGIC> 关联的功能组

### <FC-PACKET-LEFT> 关联的功能点

### <BG-FORMAL-001> Current property u_left.A_CK_PACKET_ELIGIBLE: FALSIFIED. This observation applies to the original recorded counterexample only; wider input-range impact needs separate justification.

<CK-PACKET-LEFT>

**FILE-RTL文件路径**: PacketGate/PacketGate.sv:8
**问题描述**: Current property u_left.A_CK_PACKET_ELIGIBLE: FALSIFIED. This observation applies to the original recorded counterexample only; wider input-range impact needs separate justification.
**根因引用**: ROOT-PACKET-ELIGIBILITY
**触发条件**: Original tool initialization: request=0x1 (width=1)
**预期行为**: Specification interpretation (author-provided; not machine-proven): eligible 应等于输入request。
**实际行为**: Original tool verdict: Fail (1). Stored sample at 0 x 1 ns (not asserted to be the failure cycle): PacketShell.eligible=0x0 (width=1)
**证据范围**: 仅本条当前反例或静态检查；未据此证明所有输入上的影响。
**置信度**: HIGH

---

## Failed Property: `u_right.A_CK_PACKET_ELIGIBLE`

### <FG-LOGIC> 关联的功能组

### <FC-PACKET-RIGHT> 关联的功能点

### <BG-FORMAL-002> Current property u_right.A_CK_PACKET_ELIGIBLE: FALSIFIED. This observation applies to the original recorded counterexample only; wider input-range impact needs separate justification.

<CK-PACKET-RIGHT>

**FILE-RTL文件路径**: PacketGate/PacketGate.sv:9
**问题描述**: Current property u_right.A_CK_PACKET_ELIGIBLE: FALSIFIED. This observation applies to the original recorded counterexample only; wider input-range impact needs separate justification.
**根因引用**: ROOT-PACKET-ELIGIBILITY
**触发条件**: Original tool initialization: request=0x0 (width=1)
**预期行为**: Specification interpretation (author-provided; not machine-proven): eligible 应等于输入request。
**实际行为**: Original tool verdict: Fail (1). Stored sample at 0 x 1 ns (not asserted to be the failure cycle): PacketShell.eligible=0x1 (width=1)
**证据范围**: 仅本条当前反例或静态检查；未据此证明所有输入上的影响。
**置信度**: HIGH

---
```
