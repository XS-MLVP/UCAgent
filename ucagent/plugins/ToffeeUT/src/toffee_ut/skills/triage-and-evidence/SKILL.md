---
name: triage-and-evidence
description: 从真实 run/nodeid 沿合法激励、采样、比较和独立预期反查失败，用区分性与双向复验支持归因，绑定源码/构建/选择/种子，按逐例迁移而非总数判断升级影响。
metadata:
  source: ucv4xs/skills/review/triage-and-evidence.md
  source_sha256: 8743e263ea6af7b71174c1fc75fee0c59ac21158503c343eb2668596957003e8
  license: MPL-2.0
---

<!-- Adapted from XS-MLVP/ucv4xs. SPDX-License-Identifier: MPL-2.0. License: https://mozilla.org/MPL/2.0/ -->

# 如何归因失败并建立可复核证据

## 何时使用、准备什么

出现 FAIL/ERROR、准备改 expected/时序/豁免，或宣称缺陷关闭时使用。输入为原始阶段错误、
日志、精确 run/nodeid 与选择、源码、RTL/构建身份、配置和实际 seed 使用。

## 怎么做

1. **先保存再改。** 冻结原失败和当时的输入/配置，写要检验的根因假设。新运行用新目录，
   不覆盖旧结果，也不拿当前源解释旧运行。
2. **沿链反查。** 实际收集/执行 → 激励合法、前态可达 → 全通道采样和完成 → 字段实际
   比较 → oracle 独立且适用 → DUT 是否违反要求。静态搜索只是分诊，不构成根因证明。
3. **区分性实验。** 最小合法复现配邻近合法控制。改延迟、相位、模型或驱动后变绿，只先
   证明相关性，要用能排除其他解释的对照确认。
4. **限制修复范围。** 修输入/采样/oracle 时保留仍受保证的检查；不扩大 XFAIL、skip 或
   允许集合吞掉新原因。strict XFAIL 也不验证失败原因，历史标记须重新审查适用性。
5. **两方向复验。** 误报修复既不再误伤合法场景，也仍检出邻近错误；漏检修复既检出
   原错误，也不把合法情况误报。注明 checker/模型实验、观察注错或真实 RTL 的区别。
6. **对齐证据。** 核对源版本/字节、RTL、原生库/构建、工具、参数、seed、nodeid、日志
   和同轮覆盖。运行中/运行后差异分开；缺原件就写缺失，不虚构 hash、复现或波形。
   自动审计通过只说明它检查的条件满足。
7. **升级后逐节点分类。** 基线提交变了不表示本机已生成/构建/运行。按新身份生成并构建
   后比较 FAIL→PASS（可能上游修复）、PASS→FAIL（可能模型滞后）、FAIL→FAIL（仍待处置），
   各给源码级判据。完整回归期间冻结适配；前后源码不一致的运行不能用作当前验收。

## 产出与结论等级

问题格式见 `Guide_Doc/ut-results.md`，当前分类字段只使用下表，不另造同义状态：

| classification | 最低依据 |
|---|---|
| rtl | 合法输入下真实 DUT 断言失败，违反已确认 requirement，有独立 expected 与可重复观察 |
| verification | 激励、环境、oracle 或 checker 错误有明确证据，并需修后成对复验 |
| unconfirmed | 证据不足；给缺项和下一实验 |
| out-of-domain | 当前层不负责，给承接层；不称系统已排除 |
| ruled-out | 针对原假设有具体反证和适用范围，不泛化为没有其他缺陷 |

记录原假设、证明/反证、变更理由、修前/修后运行、注入层、持续检查位置和残余。
按独立根因统计问题，失败节点与重复症状数量另列。问题归 docs/bugs/open，复验关闭后保留
历史并移 closed。请求 seed 不证明 native argv 生效，收据完整不证明 oracle 独立。

## 如何验收

另一位复核者能从结论找到原失败、合同和成对控制。错 run、缺日志、未选入反例不能支持
相应声明；真实设计失败保留 FAIL，设施错误先修复。原生判定、证据缺口和交付范围分开。

运行和计数用 RunToffee / UTProject，不在 Skill 重写。波形观察使用 WaveInfo，按
Guide_Doc/ut-waveform.md 引用真实节点、信号、窗口及根因分析；缺少实际观察不能确认，
也不能把源工程历史波形当成本轮证据。

源案例：`ucv4xs/docs/lessons/rtl-verification-soundness-20261026.md`（P11/P12）。
退出标准见[退出与残余](../closure-and-residuals/SKILL.md)。
