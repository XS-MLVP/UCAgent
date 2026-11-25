
<!-- Adapted from ucv4xs/skills/README.md. SPDX-License-Identifier: MPL-2.0. License: https://mozilla.org/MPL/2.0/ -->

# 按当前问题选择验证方法

## 先确定要解决什么

按当前阶段任务完成工作，不把方法目录当作每次必须全读的清单。盘点、骨架、构建、执行、
审计、汇总使用 `UTProject`、`BuildToffeeDUT`、`RunToffee`；方法帮助判断输入、如何设计
检查和如何解释证据，不生成第二套计划或替代实际执行。

下表提供问题导航，不定义新的工件格式。设计/验证规格的完整示例见
`Guide_Doc/ut-contracts.md`，用例完整示例见 `Guide_Doc/ut-environment.md`，问题与报告完整
示例见 `Guide_Doc/ut-results.md`。

## 独立问题与可选 Skill

Skill 已启用且可用时，可调用 `ListSkill` 并读取相关方法；完整 ID 为
`ext/toffee-ut/<下表名称>`，文件位于 `.ucagent/skills/ext/toffee-ut/<名称>/SKILL.md`。
表内阶段只是推荐，复核发现问题可以回到设计或执行补齐。

| 当前问题 | 推荐阶段 | 可选方法名称 | 无 Skill 时的直接操作与参考 |
|---|---|---|---|
| DUT 负责什么，哪些来源/行为还没定义？ | 规格 | requirements-boundary | 由独立要求推行为、再反查端口与状态；按 `Guide_Doc/ut-contracts.md` 写来源、合法域与责任移交 |
| 内部宽于端口、断言裁剪、缺接线怎么办？ | 规格/环境 | observation-precision | 三向对照语义、源码读写者、实际端口；按 `Guide_Doc/ut-environment.md` 保留未证明项、关闭条件和承接方 |
| 如何挑类别、响应结果域、历史和关键组合？ | 场景 | behavior-equivalence | 按 `Guide_Doc/ut-contracts.md` 建有限矩阵，选能区分正确与代表性错误的样本；未分类项明确保留 |
| 要求怎样接到真实用例和实际比较？ | 场景/实现 | traceability-and-implementation | 追到合法输入、独立 expected、观察/比较、完成和精确 nodeid；格式按 `Guide_Doc/ut-contracts.md` |
| 什么时候可以退出，残余怎么排责？ | 场景/交付 | closure-and-residuals | 先定范围与目标，逐项核对；按 `Guide_Doc/ut-results.md` 汇总，未确认、覆盖缺口和排除不算 PASS |
| 验证包怎样分层，谁驱动、谁采样？ | 盘点/环境 | package-layout | 按 `Guide_Doc/ut-project.md` 六职责落位；按 `Guide_Doc/ut-environment.md` 复用组件，保持唯一所有权与根 fixture |
| 激励是否合法、是否真的到达 DUT？ | 环境/实现 | legal-stimulus | 追真实 producer 编码/许可/历史，拒绝未知或缺字段，核对发射/接受；见 `Guide_Doc/ut-environment.md` |
| expected 是否独立，单位/身份是否正确？ | 环境/归因 | independent-oracle | 核对来源适用域与抽象层级，用独立输入历史/算法/性质；不能读取 actual 自证，见 `Guide_Doc/ut-environment.md` |
| 同拍漏采、取消、超时、假完成怎么查？ | 环境/实现/归因 | checker-and-runtime | 全通道先采样后记账，逐身份核对真实响应与有界义务；合法和单错误控制走同一路径，见 `Guide_Doc/ut-environment.md` |
| FAIL 属于 RTL、设施还是未确认？ | 归因/交付 | triage-and-evidence | 冻结失败，沿执行链反查，做区分性和双向复验；分类和完整证据格式按 `Guide_Doc/ut-results.md` |

## 导航入口与专用参考

- `verification-completeness`：设计问题导航；来源映射、类别 × 结果域、未分类项及其代码
  一致性检查在既有规格与自检内维护。自检只证明账目一致，不证明语义完整或场景已经 checked。
- `rtl-verification-soundness`：执行/复核导航，附 P01–P12 历史问题速查；历史案例不作为
  当前 DUT 的运行或波形证据。
- `ucv4xs-workflow`：仅在本次真实工程属于 ucv4xs 时，核对已有基线、配方、完整 RTL/闭包
  与 UT 的边界。独立 UT 不强加该仓库的外层目录或构建流程。

上述方法都可按问题选用，不要求重复记录 Skill 使用来代替真实工件。待审的依赖升级、
fixture 集中、框架选型、迁移边界四篇参考保留在
`.ucagent/skills/ext/toffee-ut/ucv4xs-workflow/references/pending/`；不是独立 Skill 或阶段
要求，不授权升级、迁移、删除或发布。源案例只提供经验，不能复制历史 PASS 或假定已复现。

## Skill 不可用时

不读取不存在的 Skill 目录，不等待 `ListSkill` / `SetSkillUsage`，也不降低验收。
直接按上表的操作和阶段 reference_files 使用工具、现有规格、真实代码和运行结果：

1. 先盘点资料并识别 DUT、责任层级、合法域、独立依据与观察缺口。
2. 建场景和独立判据，明确高风险组合、完成义务、退出范围及尚未分类/未证明的部分。
3. 实现事务环境、实际比较和成对自检；一致性和重复统计工作交给代码，不手工伪造结果。
4. 定向运行后完整回归，保留失败、源码/构建身份和精确节点，修设施错误后按证据归因。
5. 用 summary 汇总并核对范围，只有真实已执行且符合已确认要求的部分才支持通过结论。
