---
name: traceability-and-implementation
description: 把需求、行为类和场景落成合法输入、真实 DUT、独立预期、实际比较、完成义务及成对控制，双向核对 nodeid 与持续检查，不把模型自测当作硬件验证。
metadata:
  source: ucv4xs/skills/design/traceability-and-implementation.md
  source_sha256: 9b3bd8269f0f24aa3e09db9b9589d7add50a3f8f5f94c769f339b42f6a604437
  license: MPL-2.0
---

<!-- Adapted from XS-MLVP/ucv4xs. SPDX-License-Identifier: MPL-2.0. License: https://mozilla.org/MPL/2.0/ -->

# 如何把功能点实现为可运行、可检错的测试

## 何时使用、准备什么

定义功能点后、开发环境前，或复核“写了用例却没查到错误”时使用。输入是需求来源、DUT
合同、行为等价类、可用观察点；文件格式与例子见 `Guide_Doc/ut-contracts.md`。

## 怎么做

1. **明确可观察承诺。** 拆成激励前提、状态历史、结果、副作用和完成条件，说明字段有效域
   及未定义部分。
2. **独立推导答案。** 从适用规范、已确认合同、固定配置或独立性质推导 expected。RTL 可
   解释接口/时序线索，但实现本身不是正确答案；第三方 ISA 模型也须核对版本与适用语义。
3. **画最小执行路径。** 明确 fixture、producer/内存代理、driver、monitor、scoreboard 的
   职责与采样点。先接通一笔真实事务再加入目标历史/并发；这不是另建演示 DUT 的理由。
   布局按[包结构](../package-layout/SKILL.md)，不以模型自测替代真实 RTL。
4. **先列字段再接比较器。** 每项观察给单位、身份来源、有效条件和比较规则；不比较项给
   合同依据及影响。输入侧同样列合法取值、producer 分支和互斥组合；有字段名但无对应
   激励分支仍是缺口。只计算 expected 而未观察/比较也未完成。
5. **设计成对控制。** 合法行为应通过，破坏该承诺的代表性变体应在指定比较点被拒绝。
   expected 注错、观察注错、环境故障、RTL mutant 分别标注，不能混成一种验证信用。
6. **定义完成性。** 对有最终接受/完成保证的场景设置目标、UID 账本、重试及有界收尾；
   允许拒绝/取消时按合同结清，不机械要求每笔 offered 完成。
7. **接入真实执行与持续检查。** 对账定义、collection、选择器和实际结果，定向运行后接
   适用回归。未选入探针、自检单列；尚未接入 CI 的检查不能写成已生效。
8. **反查报告。** 结论必须能回到 nodeid、断言、输入、当轮证据；失败和缺口反馈到同一份
   需求/场景，而不是维护第二份“最新通过率”。

## 产出：一条可审计记录

以下是验证规格正文中的追溯记录，不是另一套必填 JSON 或替代合同块：

```yaml
requirement_id: R-ORDER
behavior_id: ordered-response
scenario_id: S-BACKPRESSURE
design_review: 合同已核；列出来源条款和参数版本
response_domain: 正常完成及合同允许的背压/替代结果
dut_and_legal_precondition: 本层责任与实际 producer 准入条件
stimulus_and_history: 环境事务入口及前态构造
input_value_domains: 字段合法域、producer 分支、尚缺的分支
oracle_and_independence: 独立输入历史、参考算法或性质及依据
observations_and_assertions: 实际字段、有效条件、比较器位置
completion_obligation: 已接受、已比较、合法拒绝/取消的义务
legal_control: 应通过的合法场景
error_control_and_layer: 应被拒绝的变体、注入层、检查点
collection_and_run: 实际 run/nodeid 和选择结果；未执行就注明
continuous_check: 当前检查入口；未接入写待实施
evidence_and_residual: 本轮证据位置、未证明范围及补法
```

模块行为清单描述应做什么，场景描述如何区分正误，运行证据保留冻结字节与逐例事实，用
链接关联。原有稳定 ID 不为改术语而重写，搬路径也不改变原始证据。

## 如何验收

至少沿一条高风险需求走完“来源 → 合法激励 → 真实 DUT → 独立答案 → 实际比较 → 正负
对照 → 运行证据”，再从一条 PASS 反向追溯。只改响应结果的对照与只改激励的对照，在
合同要求两者时同等重要；前者检查消费侧语义，不能被准入检查替代。缺环不写已完成。

相关方法：[合法激励](../legal-stimulus/SKILL.md)、[独立 oracle](../independent-oracle/SKILL.md)、
[checker 与运行时](../checker-and-runtime/SKILL.md)。源历史案例为
`ucv4xs/docs/lessons/false-negatives-20261026.md`，不是本轮复现。
