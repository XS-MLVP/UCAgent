---
name: verification-completeness
description: 验证设计方法导航：按责任边界、观察精度、等价类、实现追溯与退出残余选择独立方法；修改验证语义时复核来源映射、类别×结果域、未分类项和可执行一致性检查。
metadata:
  source: ucv4xs/skills/verification-completeness/SKILL.md
  source_sha256: 7e9939db7a74f68a1191a6b8b35f4e07da81a9b7982d236d00219954cd9774b0
  license: MPL-2.0
---

<!-- Adapted from XS-MLVP/ucv4xs. SPDX-License-Identifier: MPL-2.0. License: https://mozilla.org/MPL/2.0/ -->

# 验证完备性：设计什么、怎么做到、何时算完成

这里只导航，不再把独立方法压成一个摘要或完整性问卷。阶段是导航，复核发现问题时可以
回到设计/执行补齐；当前合同格式与无 Skill 路径见 `Guide_Doc/ut-contracts.md` 和
`Guide_Doc/ut-methods.md`。

## 按问题选方法

| 当前问题 | 独立 Skill |
|---|---|
| 需求属于哪个 DUT、哪些行为由上层承接？ | [requirements-boundary](../requirements-boundary/SKILL.md) |
| 内部宽于端口、消费者需要更多位时怎么办？ | [observation-precision](../observation-precision/SKILL.md) |
| 如何划分行为族、结果域和有区分性的关键组合？ | [behavior-equivalence](../behavior-equivalence/SKILL.md) |
| 如何接通合法输入、独立答案、实际检查与 nodeid？ | [traceability-and-implementation](../traceability-and-implementation/SKILL.md) |
| 哪些证据支持退出、哪些必须保持未证明？ | [closure-and-residuals](../closure-and-residuals/SKILL.md) |

## 每轮迭代的四项复核

增删类别、修改期望或补观察点时，把以下结果落实到现有规格、coverage 实现与 tests 自检；
缺项就不能声称本轮功能覆盖有提升，不另建计划 JSON：

1. **来源映射**：能到达本 DUT 的每个指令/事务族属于本层、出域（谁承接）还是未证明。
2. **类别 × 结果域**：每格 pass/fail/gap/na/out-of-domain；pass/fail 有同轮 run/nodeid，
   gap 有缺什么和怎么补。结果域按当前合同选择，不给所有 DUT 强加架构专有结果。
3. **未分类项**：新增但未分析的输入、字段、历史或组合明确列出，不能塞进“其他”。
4. **可执行一致性检查**：类别/域或来源新增但无对应记录时，自检应报错。机械检查由代码
   完成，不让 Skill 代算；自检只证明资料一致性，不证明语义正确或真实场景都已比较。

行为族、要求 ID、场景、参数实例和运行判定分别记录。旧 ID 全部归类，不能代替应有行为
全集审查；真实 DUT 与模型自测、错误控制的证据也不互相兑换。

## 经验与证据边界

源 LSQ 案例只有干净完成期望，覆盖大量用例仍漏掉错误响应；这是类别 × 结果域的教训，
不是当前 DUT 的运行成绩。原资料为
`ucv4xs/suites/memblock/lsq/docs/spec/design/contracts/kind-outcome-matrix.md`。

执行与复核的方法从[rtl-verification-soundness](../rtl-verification-soundness/SKILL.md)选择；
实际 ucv4xs 工程的基线/配方语义才使用[项目入口](../ucv4xs-workflow/SKILL.md)。
