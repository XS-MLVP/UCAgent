---
name: independent-oracle
description: 给 expected 标独立来源和适用范围，分清架构与协议、身份与物理槽、单位与粒度；用错误算法和成对控制反查同源错误，不通过读取 DUT 或照抄 RTL 消除差异。
metadata:
  source: ucv4xs/skills/execution/independent-oracle.md
  source_sha256: 7d39b8ee308a362463b6507ac0b121699d41b02786d270f48f933c782deebc33
  license: MPL-2.0
---

<!-- Adapted from XS-MLVP/ucv4xs. SPDX-License-Identifier: MPL-2.0. License: https://mozilla.org/MPL/2.0/ -->

# 如何建立独立 oracle 并选对抽象层级

## 何时使用、准备什么

实现 expected、修模型或复核模型与 RTL 全绿时使用。输入为行为要求、规范/合同版本、固定
配置，以及接口与架构对象的映射；依据状态沿用 `Guide_Doc/ut-contracts.md`。

confirmed 来源必须是启动时已提供且未变化的独立输入文件；先用 UTProject inspect
盘点。URL 或本轮自写说明不能提升依据状态；缺资料时保留 inferred/open 并请求用户提供。

## 怎么做

1. 每条关键答案标来源与条件：规范、已确认合同、固定配置、独立性质或仅实现观察。
   实现观察不能反推正确答案，未经核实的第三方模型也不是无条件 golden。
2. 分开架构结果和协议检查。ISA 模型不自动覆盖内部握手、状态匹配和失效；协议模型也
   不证明最终架构语义。交界与未验证部分必须写明。
3. 显式绑定身份、单位和粒度。身份/年龄在输入侧建立，不能从返回标签倒推；逐字节或
   逐元素语义不能用整体地址范围或物理槽号代替。
4. 用独立算法、固定答案或不变量交叉核对权限作用域、故障优先级、编码别名和状态清理。
   只能从实现推测时登记待确认，不改 expected 消灭差异。
5. 已确认的复位/配置值写成带来源的固定答案，不从 live DUT 读取自证；运行时协商或
   实现自由度单独定义合同，不误当固定值比较。
6. 构造能区分原错误算法和正确算法的输入。运行冻结错误模型或 expected 变体，要求
   独立检查拒绝；翻转读数只证明受检路径，不证明模型语义独立性或 RTL mutation coverage。
7. **不要照抄 RTL 的边界表达式。** 协议中的资源/事件/不变量可以建模，不能因为形式相同
   就复制边界判断。模型和 DUT 能看到的状态、消费者更新时间可能不同；相位分歧须先有
   独立理由判谁错，无法判断就保留失败/未确认，不用“贴近实现”换绿。

## 特别复核的数据泄漏与坐标错误

- 参考模型 temporary 删除 pending 不代表独立；实际送给 DUT 的 refill 数据是否混入
  golden store 字节，须沿生产链核对。
- carry/续半槽位由真实 producer 到 consumer 的有效域定义，不能把“不是某种短指令”
  直接等价成“本窗口新起始”；新旧模型同答仍可能同错。
- 同一个 PC 在不同通道可能是字节、半字或带 guard 的坐标。输入计划要显式转换，不能
  从返回值猜单位，或把 first-owner 改成 last-writer 来掩盖输入混用。
- 生产者年龄与反向端口压力的位宽回绕分开说明，后者不能升级为整机可达信用。

## 产出与验收

保留 oracle 来源表（版本/条款/配置/适用域）、身份与粒度映射、实现位置、代表性错误算法、
正负对照及待确认项。纯实现刻画注明 characterization；若替换或性能行为本有已确认要求，
也要验证，不能一概排除。

选择一条同源错误，即使 RTL 与旧模型同答，独立检查仍能指出差异。布局或槽号改变而
语义不变时，答案保持应有不变量；规范未定义的字段不能被过严比较。

## 历史案例位置

- `ucv4xs/docs/lessons/rtl-verification-soundness-20261026.md`（P04/P05）。
- `ucv4xs/docs/lessons/lsq-baseline-regression-20261103.md`，模型与 RTL 相位分歧。
- `ucv4xs/docs/lessons/semantic-boundary-repair-20261101.md`，DCache refill/golden 泄漏。
- `ucv4xs/suites/frontend/ifu/docs/bugs/open/instr-boundary-carry-ftq-owner.md`。
- `ucv4xs/suites/frontend/ftq/docs/spec/verification/transaction-adaptation.md`，组合坐标与阶段。

案例是源工程经验，不是当前 DUT 的测试结果；缺原始资料时明确证据未取得。
