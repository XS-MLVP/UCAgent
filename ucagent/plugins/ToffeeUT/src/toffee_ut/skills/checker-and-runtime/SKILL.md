---
name: checker-and-runtime
description: 实现字段比较、同拍全通道采样、逐 UID 义务、有界完成和取消副作用检查；复核实际 native seed、首响应相位、SDK 终态与真实交付，防止次生清理错误或假完成掩盖原失败。
metadata:
  source: ucv4xs/skills/execution/checker-and-runtime.md
  source_sha256: fb4e8595376030a617593ccaafa8dc6a34a9bd498889ff09f5fd039129f55e0e
  license: MPL-2.0
---

<!-- Adapted from XS-MLVP/ucv4xs. SPDX-License-Identifier: MPL-2.0. License: https://mozilla.org/MPL/2.0/ -->

# 如何实现 checker、并发采样和完成性检查

## 何时使用、准备什么

开发环境、改比较器或复核假通过时使用。输入为有效条件/时间保证明确的合同、独立 oracle、
真实生成物和实际测试选择。公共运行规则见 `Guide_Doc/ut-environment.md`，结果规则见
`Guide_Doc/ut-results.md`。

## 怎么做

1. 建立“要求 → 驱动字段 → 观察字段 → 比较器 → nodeid”关联；缺字段立即报错，未比较项
   写合同理由，不靠默认 0 掩盖缺接线。
2. 按 valid/mask/选择条件比较。合法额外事务用地址、类型、UID 和时窗限定的允许集合
   处理，不能因为模型不支持就打开整段 allow_unexpected。
3. 在约定沿先取得**全部通道快照**，再统一更新状态/账本。等待一路不能停止服务其他路，
   不能由 if/continue 分支漏掉已发生的 fire。
4. 用不可变 UID 分记 offered、pending/retry、accepted、有效 completed、合法取消和
   outstanding；保持多拍不重复计数，按源对账。守恒式来自具体协议，不机械套总数相等。
5. 有最终接受/完成保证的用例设目标和 watchdog，预算耗尽失败；允许拒绝、取消或无活性
   保证的情况按合同处理，不添加“所有请求最终完成”的假要求。
6. 对 kill/flush/redirect/reset 列出必须、禁止、允许延后的副作用；检查当拍后再发送新
   身份事务，验证旧异常、数据和目的地没有非法残留。
7. 对账测试定义、重复/失活项、真实 collection 和实际执行，确认依赖的生成断言存在且
   启用。sample 只是 reached，checked 必须能找到实际执行的区分性比较。
8. 受控自检错键、缺字段、错 expected/观察、未授权事务、零接受、接受后不完成、背压重复
   计数；应在承诺检查点失败而非被 setup error 挡住。标清注入层，selftest 不计 RTL 信用。

## 收尾、时间和身份的重点复核

- **正文 FAIL 与清理 ERROR 分开。** 异步 pytest fixture 的 yield 不保证收到正文异常。
  已经观察的正文失败不应被重复 finish 变成假 ERROR；独立清理错误仍须保留，正文 PASS
  或缺报告时仍严格收尾，不能吞比较/取消错误换成功。
- **物理 fire 与生效义务分开。** flush 未必门控 ready；无 tag 线路不能靠数据倒推身份。
  合法取消后迟到与新的 WaitResp 歧义响应须按 peer 历史处理，环境 UID 不是硬件 tag。
- **finish 不清债。** 不能自动 flush、reset、补响应，或发出未授权计划来凑完成。既检查
  未发射日程/控制计划，也检查已观察 offer；只允许合同规定的自主尾部继续推进。
- **实际 native seed。** 请求种子、收据种子与构造 argv 要对上。模块导入固定默认值、
  只读另一个配置、完全不传 argv 都会制造假多 seed；保留默认、覆盖、非法值和两次构造
  之间变化的控制。没有真实原生复验，就不能把请求值写成已生效。
- **多义务终态不能合并。** redirect 仲裁取消不一定取消已注册 resolve；重发可能有新
  attempt 但保留 allocation 祖先。无响应 handoff 不能算下游响应/全机退休；未接受 offer
  和已接受待完成义务分开。
- **固定延迟不是输入到达证明。** 还要核对输入 UID、发射/接受沿与阶段来源；相同 payload
  不合并身份。响应只在合同规定的首个检查点取样，不能等到等于 expected 才挑样本。
- **来源随数据传播。** metadata 诊断副本不能冒充原 lookup，显式端口重放不能变成生产
  祖先信用。沿前 getter 可能只是排队意图，必须区分 readiness、真实发射和消费相位。
- **SDK COMPLETED 不等于正确硬件响应。** reset/过滤可能终态交付句柄；另记实际有效
  响应、终态原因、真正比较过的结果，不能只数句柄 completed。
- **首错优先且及时传播。** 真实比较失败要立即唤醒长等待，不继续跑到 monitor 溢出；
  账本因原错停止更新时，不能让次生“缺 sample/交付”错误覆盖原语义失败。
- **性能优化不能删证明。** 每沿只索引当前义务而非扫描全部历史；不通过删历史换速度，
  最终 finish 仍逐项核对。

## 产出与验收

保留字段/比较器对账、同拍事件对照、逐 UID/源义务、收尾预算、默认 collection 与额外探针
范围、自检控制、真实观察和比较位置及盲区。Toffee 的 Driver/Monitor/Scoreboard 负责可复用
机制，工程只补当前合同语义，不在 Skill 中另造执行器或覆盖统计。

正常场景通过；代表性错误在指定点被识别。同拍不丢事件、保持多拍不重复，取消无非法
副作用，未偿还义务不能正常退出；原始判定和独立清理错误不被隐藏。

## 历史案例位置

源方法的细节来自以下历史资料，不是插件已完成这些 DUT 验收的声明：

- `ucv4xs/docs/lessons/rtl-verification-soundness-20261026.md`（P02/P03/P06–P10）。
- `ucv4xs/docs/lessons/transaction-boundary-repair-20261101.md`，Sbuffer 成对控制。
- `ucv4xs/suites/frontend/ifu/docs/spec/verification/transaction-adapters.md`，正文/收尾、Uncache 义务。
- `ucv4xs/docs/local-configuration.md`，回归 seed 与原生初始化。
- `ucv4xs/suites/frontend/ftq/docs/spec/verification/transaction-adaptation.md`，收尾边界。
- `ucv4xs/suites/frontend/bpu/docs/spec/verification/contracts/mbtb-transaction-contract.md`。
- `ucv4xs/suites/frontend/icache/docs/spec/verification/transactions/databank-transaction-adaptation.md`。
- `ucv4xs/docs/history/transaction-goal-mbtb-disposition-index-20261102.json`。

失败解释仍需[归因复核](../triage-and-evidence/SKILL.md)，不能只比较 FAIL 数。
