---
status: pending
source: ucv4xs/skills/pending/pin-schema-and-suite-migration.md
source_sha256: d651c3e3679d8d457869e9622b8354f1ecbee1bddfa359975a030397ce220fc8
license: MPL-2.0
---

<!-- Adapted from XS-MLVP/ucv4xs. SPDX-License-Identifier: MPL-2.0. License: https://mozilla.org/MPL/2.0/ -->

# 迁移边界复核（待审核）

## 适用场景与源修订的教训

旧工程仍用端口字典/cycle-level harness，但目录或静态门禁全绿时参考。源稿已撤回
“把 io_* 换为 P.p_* / P.io(...) 就完成迁移”的判断；这是错误标准的历史反例，不是推荐
本工作流新增别名或兼容层。历史判定保持原义，不能因修正文档就改写旧运行。

输入为工程合同、fixtures、驱动/采样调用链、正负对照和新的收集清单。

| 工作层次 | 能证明 | 不能证明 |
|---|---|---|
| fixture 集中、插件导入 | 接线可发现、生命周期入口可定位 | 每 DUT 的唯一所有者、事务语义正确 |
| 端口常量/前缀助手 | 字符串集中，可能少些拼写重复 | typed transaction、缺项校验、不再触碰引脚 |
| driver/monitor/agent/checker 分层 | 经合同与控制实验验证后的对应职责 | 全硬件正确、所有 API 或覆盖闭环 |

## 怎么复核

1. 用工程实际入口取得 collection 和选择，逐 nodeid/判定对比，不能只比数量或 fixture
   函数数量；参数化不是漏接或重复接的自动证据。
2. 沿一条用例追请求类型 → 实际发射/接受/撤销 → monitor 相位 → 独立 checker。
   raw dict、物理字段、手工数拍或原生方法同名转发均待复核，不靠改名躲扫描。
3. 事务明确单位、合法域和身份，适配层收编码/解码/精确相位。不要把原生句柄转交测试
   再宣称有 agent API；也不要把全部断言隐藏到不透明调用。
4. fixture 用显式名称/参数，不按测试路径切换模型。移动后核对包根、资源、插件位置、
   临时目录和 cwd 恢复，选择与语义不应因目录变化而改变。
5. 合法控制与错误 expected 成对验证；缺端口、重复 claim、未知字段、丢采样应在约定
   边界报错。selftest 依据内容分类，marker 本身不制造硬件信用。
6. 结构整理与事务迁移分开报告，保留全部真实判定与未适配项。不为了全绿关闭必要检查，
   不把静态零命中变成独立 oracle、采样或完成性证明。

## 产出与验收

盘点、collection、结构/边界扫描和计数由已有审计脚本执行；Skill 复核调用链与结果解释。
保留测试选择、源码版本、合同、实际输出及控制实验，不预填 PASS。只读结构检查、真实
运行和语义审查分别陈述，未做的不要填成已做。

源工程 2026-10-31 的扫描记录同时包含已整理接线和仍存在物理耦合的模块，不能泛化为
当前全仓已事务化。源复核记录位置为
`ucv4xs/docs/lessons/structure-skill-review-20261031.md`；本次没有据此重跑这些模块。

正式分层与验收仍用[package-layout](../../../package-layout/SKILL.md)。
