
# 形式化缺陷报告

本阶段依据已核验的 `RTL_BUG` 分析填写缺陷观测，Check生成 `04_{DUT}_bug_report.md`。使用可选数据技能或普通文件工具维护同一YAML，以RunFormal evidence核对真实证据，不手写派生Markdown。公共数据完整例子见 `Guide_Doc/formal_data.md`。

## 提交与验收

1. 技能可用时，通过原有RunSkillScript调用ext/formal/data的`formal_data.py prepare bugs`，取得精确观测和ready_update；无技能时Check协调条目，用普通文件工具读取并填写同一bugs子树。
2. 核对RunFormal evidence给出的本条真实反例、独立参考值及实际输出；静态失败使用声明契约证据，不编造输入序列。
3. 数据技能可用`data.shared`一次提交共同根因及entries；将完整结构化请求写JSON文件，再经RunSkillScript调用`update --request-file`，不拼shell内嵌JSON。无技能时各YAML观测保留一致的共享值。
4. 日志后Complete，Check只用于实际诊断。无RTL_BUG时不制造占位Bug；修复建议未经新验证不得称已通过。

`shared` 可含 `root_cause_id/root_cause/fix/severity/confidence`，必须有明确的非空root_cause_id。`entries` 每项含工具返回的id/property及该属性的 `description/trigger/expected/actual`，并补齐 `ck_id/fg_id/fc_id/rtl_file/rtl_line`。严重度和置信度从HIGH/MEDIUM/LOW选取。共享字段若在entry重复出现，值必须一致，不能悄悄覆盖。

失败属性数量是观测数，独立root_cause_id数量是根因数。相同根因只维护一次原因与修复，各条目保留自己的触发和输出证据。Cover、UNPROVEN、超时或工具故障不能登记成RTL Bug；属性参考计算错误必须先修至通过。

## 完整报告参考

下面是两个属性观测关联一个根因的完整渲染布局。真实名称、位置和数值必须来自当前任务与证据；不得复制本例作为证明。报告从标题到最后分隔线与生成模板一致。

```markdown

# PacketGate 形式化验证缺陷报告

> 本文档由 `.formal_records.yaml` 自动生成，请勿手动编辑。

本报告记录了 2 条失败属性观测，关联 1 个独立根因。

## Root causes

### ROOT-PACKET-ELIGIBILITY

- Root cause: 共同资格条件取反，导致两侧输出不符合规格。
- Fix: 修正共同资格条件，按原目标重新运行并检查真实结果。
- Severity: HIGH
- Properties: u_left.A_CK_PACKET_ELIGIBLE, u_right.A_CK_PACKET_ELIGIBLE

---

## Failed Property: `u_left.A_CK_PACKET_ELIGIBLE`

### <FG-LOGIC> 关联的功能组

### <FC-PACKET-LEFT> 关联的功能点

### <BG-FORMAL-001> 左侧资格输出与规格不符

<CK-PACKET-LEFT>

**FILE-RTL文件路径**: PacketGate/PacketGate.sv:8
**问题描述**: 当前左侧witness中request=1但eligible=0，与组合资格条件不符。
**根因引用**: ROOT-PACKET-ELIGIBILITY
**触发条件**: 工具当前左侧属性witness的request=1采样。
**预期行为**: eligible=1。
**实际行为**: eligible=0。
**置信度**: HIGH

---

## Failed Property: `u_right.A_CK_PACKET_ELIGIBLE`

### <FG-LOGIC> 关联的功能组

### <FC-PACKET-RIGHT> 关联的功能点

### <BG-FORMAL-002> 右侧输出受到相同资格条件错误影响

<CK-PACKET-RIGHT>

**FILE-RTL文件路径**: PacketGate/PacketGate.sv:9
**问题描述**: 当前右侧witness中request=0但eligible=1，与规格不符。
**根因引用**: ROOT-PACKET-ELIGIBILITY
**触发条件**: 工具当前右侧属性witness的request=0采样。
**预期行为**: eligible=0。
**实际行为**: eligible=1。
**置信度**: HIGH

---
```
