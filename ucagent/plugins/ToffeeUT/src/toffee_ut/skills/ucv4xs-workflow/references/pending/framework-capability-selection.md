---
status: pending
source: ucv4xs/skills/pending/framework-capability-selection.md
source_sha256: f4250cbc732e5a5ab075e5b3cf6d22ce0aebd13d01ca65128293b8edc12d09ce
license: MPL-2.0
---

<!-- Adapted from XS-MLVP/ucv4xs. SPDX-License-Identifier: MPL-2.0. License: https://mozilla.org/MPL/2.0/ -->

# 框架能力选型（待审核）

## 适用问题

准备写 driver/monitor/agent/checker，已有环境有自制时钟、采样队列或 expected 队列，或
需要判断某项能力归框架还是工程时参考。先核对当前锁定版本的真实文档/公开 API；源案例
的能力缺口不能不加核对地成为本机事实。

## 先复用，再说明自建差异

| 需求 | 优先核对的组件 | 工程侧工作 | 不应无说明重复的部分 |
|---|---|---|---|
| 端口、方向与所有权 | Bundle / SignalDriver | 名称、宽度、idle | 遍历数据对象猜方向 |
| 单/多周期和流水输入 | 当前 Driver 模板 | 接受、阶段、撤销 | 时钟调度器和接受事件 |
| 输出采样 | SamplingMonitor / 协议 Monitor | 相位、有效、解码、不可变值 | 无界队列、无丢拍诊断的采样器 |
| 关联与响应检查 | Agent / Scoreboard | 独立模型、key、延迟、比较 | expected 队列和独立超时实现 |
| 功能覆盖 | CoverGroupDef 等 | 覆盖语义和目标 | 手写另一份 JSON 计数 |
| 原生覆盖 | toffee run / RunToffee | 构建、映射、口径 | 手写或伪造收据 |
| 证据不足的已执行用例 | uncertain 标记 | 原因和追溯 | 把缺证据写成 PASS |

## 选型步骤

1. 写清请求/响应的身份、单位、有效条件、终态和合法域。
2. 画 producer → driver、输出 → monitor、独立答案 → checker 的接线与生命周期。
3. 对照公开组件，能复用机制的就不重造。确有多接口/装配差异可由工程组合，但不能
   仅凭旧案例判断当前 Agent 是否适用；必须核对当前能力与具体合同。
4. 自建部分在工程 docs 说明不适用原因、已保留/缺少的接受事件、丢拍报错、清理与覆盖
   行为，以及关闭条件。名称相似不代表等价。
5. 用错误期望、缺端口/未知键、重复 claim、monitor 关闭等控制验证边界。应识别错误而
   非因无关 setup error 失败；合法场景仍须通过。

## 案例与审核边界

源 BPU 的薄驱动/快照适配、FTQ harness 与 agent 分工、ICache 的根 fixture 与事务封装，
说明可以组合框架机制而不复制它们，并不认证所有当前工程/API。真实原生构建、执行和
覆盖分别陈述，未做就写未验证；纯模型 PASS 或一个负对照不能替代真实 DUT 检查。

机械查询与执行交给工具/已有脚本；本稿不提供安装器或探针工程。正式方法仍见
[package-layout](../../../package-layout/SKILL.md)、[oracle](../../../independent-oracle/SKILL.md)和
[checker](../../../checker-and-runtime/SKILL.md)。
