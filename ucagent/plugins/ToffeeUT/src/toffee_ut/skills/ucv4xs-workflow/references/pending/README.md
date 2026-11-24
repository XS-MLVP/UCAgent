
<!-- Adapted from ucv4xs/skills/pending/README.md. SPDX-License-Identifier: MPL-2.0. License: https://mozilla.org/MPL/2.0/ -->

# 待审核方法参考

以下四篇保留源集合中尚未经维护者审核的方法，供适用任务按需阅读和复核。它们不含
SKILL.md，不注册为独立 Skill，不列入阶段或通用 Skill 清单，也不自动成为验收要求。
待审不等于已完成能力验证，更不授权升级环境、迁移工程、删除内容或发布。

| 参考 | 适用问题 | 源方法的经验依据 |
|---|---|---|
| [依赖升级与能力核对](dependency-upgrade-and-capability-audit.md) | 依赖、分发名、补丁、ABI 与重建范围 | Toffee / xcomm 升级与能力核对 |
| [Fixture 集中与 agent 边界](fixture-consolidation.md) | 分散接线、重复 fixture、测试碰引脚 | 根 fixture 整理和 schema2 布局审计 |
| [框架能力选型](framework-capability-selection.md) | 哪些组件复用，哪些才需自建 | BPU / FTQ / ICache 与公共 API |
| [迁移边界复核](pin-schema-and-suite-migration.md) | 结构全绿但仍有物理耦合 | 端口别名不能证明事务化的反例 |

审核前核对当前版本的命令与公开接口、证据可复现性、未执行项和真实判定是否保留。
正式方法仍从[项目入口](../../SKILL.md)、[包结构](../../../package-layout/SKILL.md)和
[设计导航](../../../verification-completeness/SKILL.md)选择。来源指纹在[来源记录](../SOURCES.md)。
