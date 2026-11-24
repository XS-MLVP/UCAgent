---
name: rtl-verification-soundness
description: RTL 执行与复核方法导航：独立选择分层、合法激励、oracle、checker/完成性和失败证据的方法；保留 P01–P12 速查，不把历史案例或目录整理当成当前验证信用。
metadata:
  source: ucv4xs/skills/rtl-verification-soundness/SKILL.md
  source_sha256: eeaa90ab2b3050facd1e0f7bb4f2071cd3d31f88c2a412f8598b69bfbb2cb970
  license: MPL-2.0
---

<!-- Adapted from XS-MLVP/ucv4xs. SPDX-License-Identifier: MPL-2.0. License: https://mozilla.org/MPL/2.0/ -->

# 执行与复核方法入口

按问题选择完整方法，不要求串读大手册，不用本入口代替方法正文。通用执行规则和结果
格式分别见 `Guide_Doc/ut-environment.md`、`Guide_Doc/ut-results.md`；脚本工作仍使用工具。

| 要做的事 | 独立 Skill |
|---|---|
| 组织验证包、唯一所有权和 driver/monitor 分层 | [package-layout](../package-layout/SKILL.md) |
| 合法历史、准入与真正到达 DUT 的输入 | [legal-stimulus](../legal-stimulus/SKILL.md) |
| 独立答案、架构/协议边界、身份和单位 | [independent-oracle](../independent-oracle/SKILL.md) |
| 同拍采样、比较、逐 UID 账本和有界完成 | [checker-and-runtime](../checker-and-runtime/SKILL.md) |
| 失败归因、成对复验与证据绑定 | [triage-and-evidence](../triage-and-evidence/SKILL.md) |

出现准入、oracle、取消、清理或覆盖问题时，回到对应问题方法和实际合同，不通过改 expected
或扩大豁免获取通过。源码有断言、目录全、bin 命中、退出码 0 都不能替代真实比较。

设计问题从[verification-completeness](../verification-completeness/SKILL.md)选择。
[P01–P12 速查](CARD.md)保留历史错误与当前方法的对应；案例和源路径只供经验检索，不能充当
当前运行收据、波形或 PASS。
