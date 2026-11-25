---
name: legal-stimulus
description: 追到真实 producer 的编码、许可和历史，构造合法前态并核对实际发射/接受；区分生产可达与端口压力，验证原始字节和派生描述的身份，不把非法探针当作正常功能反例。
metadata:
  source: ucv4xs/skills/execution/legal-stimulus.md
  source_sha256: 4804dc066a6eedcd276efc363299e65756a9a64c9d14cf51936f67bdac4c907b
  license: MPL-2.0
---

<!-- Adapted from XS-MLVP/ucv4xs. SPDX-License-Identifier: MPL-2.0. License: https://mozilla.org/MPL/2.0/ -->

# 如何构造合法且真正到达 DUT 的激励

## 何时使用、准备什么

开发 fixture/driver、修改特殊操作或归因失败前使用。输入为当前
[DUT 合同与 producer 约束](../requirements-boundary/SKILL.md)、端口绑定、时序和用例承诺。

## 怎么做

1. 从真实 producer 核实编码、size/mask、对齐、互斥、许可、身份/年龄及不可撤回点；
   同值而历史不同的输入分开。
2. 在构造器/fixture 边界验证必需字段、合法编码和关系；未知键、必要端口缺失立刻报错，
   不忽略或补零。非法负例验证准入拒绝，或明确标为越域压力，不冒充正常功能反例。
3. 通过合法序列建立分配、许可、部分完成、回绕等前态，不能手填下游字段就宣称整机可达。
4. 按当前协议保持、撤销、重试，记录实际发射、fire 和事务 UID；driver 调用返回、排队
   意图与 DUT 接受是三回事。
5. 从一笔事务扩展到边界、同拍竞争和背压；改变能解释差异的因素。只按调查需要保留有界
   事务 trace，不默认采集无限证据；实际运行用 RunToffee，不在 Skill 中再造运行器。
6. 为关键准入约束保留合法控制和违反约束的负例，预期由合同决定，不能凭空要求 DUT
   拒绝所有合同之外的输入。

## 判“缺保护”前先核对上游

本层防御性 assert 不等于正常生产历史允许到达。先回答：

1. 异常、许可、类型、对齐等上游位是否已经排除了该组合？
2. 若会排除，本层断言保护的是集成错误，不能把人为去掉异常位的探针当作正常输入。
3. 合法路径按合法域驱动；拒绝路径按上游已标记的形态驱动并检查副作用。
4. “喂非法输入看它出什么”本身不支持 RTL 缺陷结论。

源 LSQ 历史案例曾观察到跨界 NC store 的 mask 不覆盖高半，但上游已把非对齐请求标成
storeAddrMisaligned，本层会拒绝；探针清掉 hasException 才能触发，不能据此确认正常路径
丢数据。保留这样的反例推理，不将其复制为当前 DUT 的假设。

## 身份和字节必须一路绑定

生产者入口与端口压力可不同，但压力入口仍遵守宽度、所有权、相位和 oracle，不能冒充
CSR/整机可达；反向还要有合法边界控制，防止准入过严。

只查 size/mask 最大值不证明可达性。字段可能有 producer 分支决定的等式约束；逐分支
推导并保留完整历史，后续来源声明不能把旧端口探针升级为生产证据。

事务同时携带原始字节与派生 oracle 描述时，必须从**实际待驱动字节**独立步进起始、宽度、
PC/身份和计数，再核对冗余描述；跨事务 carry 的低半绑定前一个真实输入 UID。各字段分别
位宽合法不等于组合语义一致。

## 产出与验收

在验证规格/实现追溯中记录 producer 来源版本、准入位置、构造历史、采样点、实际 fire/UID、
正负对照节点和生产/压力范围，格式见 `Guide_Doc/ut-contracts.md`。

合法 fixture 到达目标状态；错误编码/未知键在约定边界被识别；有最终接受保证的场景在
零接受时失败，允许拒绝的场景核对拒绝条件和副作用，不机械要求接受。

## 历史案例位置

- `ucv4xs/docs/lessons/rtl-verification-soundness-20261026.md`（P01）。
- `ucv4xs/suites/frontend/ifu/docs/spec/verification/transaction-adapters.md`，producer 与端口压力。
- `ucv4xs/suites/frontend/ifu/docs/bugs/open/instr-boundary-carry-ftq-owner.md`，可达性反证。
- `ucv4xs/suites/frontend/ifu/docs/spec/verification/observation-coverage.md`，输入描述与 carry 对账。

以上仅是源方法的历史依据，不是本次复现。完成性配套见[checker 与运行时](../checker-and-runtime/SKILL.md)。
