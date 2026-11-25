
<!-- Adapted from ucv4xs/skills/rtl-verification-soundness/CARD.md. SPDX-License-Identifier: MPL-2.0. License: https://mozilla.org/MPL/2.0/ -->

# 历史踩坑编号到现行方法的速查

只做导航，不是已执行检查清单或新一轮硬件验收。源案例位于
`ucv4xs/docs/lessons/rtl-verification-soundness-20261026.md`，没有原始资料就写未取得。

| 历史编号 | 独立方法 |
|---|---|
| P01 生产者合法性 | [需求/边界](../requirements-boundary/SKILL.md)、[合法激励](../legal-stimulus/SKILL.md) |
| P02 并发漏采 | [checker 与运行时](../checker-and-runtime/SKILL.md) |
| P03 过严比较与过宽放行 | [checker 与运行时](../checker-and-runtime/SKILL.md) |
| P04 同源 oracle | [独立 oracle](../independent-oracle/SKILL.md) |
| P05 身份、粒度、抽象层级 | [独立 oracle](../independent-oracle/SKILL.md)、[DUT 边界](../requirements-boundary/SKILL.md) |
| P06 非区分性组合 | [行为等价类](../behavior-equivalence/SKILL.md) |
| P07 取消副作用遗漏 | [checker 与运行时](../checker-and-runtime/SKILL.md) |
| P08 空跑和假完成 | [checker 与运行时](../checker-and-runtime/SKILL.md) |
| P09 collection、字段未受检 | [实现追溯](../traceability-and-implementation/SKILL.md)、[checker](../checker-and-runtime/SKILL.md) |
| P10 生成产物缺观察点 | [DUT 边界](../requirements-boundary/SKILL.md)、[观察精度](../observation-precision/SKILL.md) |
| P11 失败消失不等于根因明确 | [归因与证据](../triage-and-evidence/SKILL.md) |
| P12 覆盖/归档齐备不等于语义完成 | [退出与残余](../closure-and-residuals/SKILL.md)、[证据审计](../triage-and-evidence/SKILL.md) |
