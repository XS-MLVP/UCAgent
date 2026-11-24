---
status: pending
source: ucv4xs/skills/pending/fixture-consolidation.md
source_sha256: 0b9a8c13ce6ffbb763190c7612122c2a1a1e52db2dd27beb3851ba5229b524dd
license: MPL-2.0
---

<!-- Adapted from XS-MLVP/ucv4xs. SPDX-License-Identifier: MPL-2.0. License: https://mozilla.org/MPL/2.0/ -->

# Fixture 集中与 agent 边界（待审核）

## 适用场景与输入

已有工程 fixture 分散在 DUT 子目录、转发 conftest，新增 DUT 复制接线，或功能场景直接
读写 agent.dut、pins、时钟时参考。迁移先取得授权，保留原 collection、判定和源版本；
不能因为读到本稿就删除现有文件。

输入为当前 workspace schema、pytest 根、原 fixtures/插件依赖、测试选择及实际调用链。
独立 ToffeeUT 不强加 ucv 外层；已有 ucv4xs 工程沿用其配方与命名空间。

## 目标与步骤

1. 机械盘点交给现有布局工具：列出 fixture 名称、依赖、使用点、注册入口、嵌套配置与
   输出职责。无人使用不等于可以直接删除，先核对用途、活动状态及用户授权。
2. 将注册集中在工程根 conftest.py；DUT 专用实现/参数生成可归其 tests，真正通用插件
   归 shared/env。简短定义留在根也合法，注册表风格不是 pytest 语法限制。
3. 保留每 DUT 的实际时序预算、配置、导出类、模型与初态合同。共享参数化实现按
   workspace.json 显式登记，不统一成猜测值，不按 fixture 函数数量推导 DUT 数。
4. 先改引用并验证接线，再按授权归档/移除冗余转发；不破坏用户已有入口。目录目标使用
   testbenches 六职责，env.py/env 二选一，不在实现包根再放 agent/ 或 pytest 根。
5. 让测试调用事务/精确对齐 API，不直接动时钟或 level driver；但不能把整个场景和所有
   断言藏在一次不透明调用内，也不能只把物理字段改名。
6. selftest 根据内容分类，不改写原始功能判定；共享自检不取得 DUT 功能信用。辅助全局
   覆盖组显式 capture=False，不用一个目录名宣称已经隔离。
7. 结构检查复用通用 schema 规则，语义检查追实际调用链、所有权、采样与独立 oracle。
   结构全绿不证明事务边界；静态缺口也不能通过工程专属豁免掩盖。
8. 比较迁移前后**有序 nodeid、判定、依赖与选择**，不只比数量。收集、纯组件自检、
   原生构建、真实 DUT 回归分开记录；未重建的部分不借旧结果补证。

## 验收

- 根 fixture/pytest 注册入口唯一，新增 DUT 接入显式实现包或共享参数化实现。
- 功能用例不直接访问原生对象、物理别名、私有 driver/模型；编码自检另列。
- 重复 claim、缺端口、未知键在约定边界失败；错误 expected 被拒绝；关闭 monitor 后
  依赖场景不得静默通过。
- shared 只保留真正共享职责，无独立 DUT/top，不反向依赖具体 DUT 或 tools。
- 路径移动不改变模型选择、资源根和原始判定；串行/并发 collection 与 cwd 恢复经过核对。

源工程 2026-10-30/31 的 fixture 整理是历史记录，不是本次迁移成绩。该记录明确指出
接线统一后仍可能存在 pin-level 耦合，继续参考[迁移边界复核](pin-schema-and-suite-migration.md)。
正式分层方法见[package-layout](../../../package-layout/SKILL.md)。
