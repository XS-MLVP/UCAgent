<!-- SPDX-License-Identifier: Apache-2.0 -->

# ACT4 Privileged Coverpoints 设计模板

适用阶段：01_coverpoints，供 02_norm_mapping 继续使用。
先读[模板使用说明](README.md)和[工作流指南](../ACT4_Privileged_Suite_Workflow_Guide.md)。
本文是填写提纲；占位项必须由本轮 CTP、manual 和冻结 ACT4 证据替换。

## 输入与写入位置

| 输入 | 必须确认的事实 |
| --- | --- |
| 本轮 CTP HTML 和 raw Sheet CSV | 精确 suite、唯一 table/tab、下载时间与 hash |
| specification / normative metadata 副本 | manual HEAD、逐字节副本、rule name/names 与 tag 配对 |
| 冻结 ACT4 源码与相近 coverage/init | sample API、信号字段、有效宏、XLEN、include 顺序 |
| baseline、switch audit | 首次 ACT4 写入前已记录，使用的能力/控制有证据 |

阶段 01 的 coverage 只写入：
- `{OUT}/{DUT}/coverpoints/priv/{DUT}_coverage.svh`
- `{OUT}/{DUT}/coverpoints/priv/{DUT}_coverage_init.svh`

辅助产物使用工作流规定的精确名字：
- `{OUT}/{DUT}/{DUT}.csv`、`{DUT}_testplan.md`、`{DUT}_normative_rules.csv`
- `{OUT}/{DUT}/{DUT}_coverage_intent.yaml`
- `{OUT}/{DUT}/reports/sheet_manual_sv_mapping.md`
- `{OUT}/{DUT}/reports/coverage_gaps_and_conflicts.md`
- provenance、baseline、switch audit 和累计 AI review

阶段 02 在内部目录生成 `coverpoints/norm/{DUT}.yaml`。阶段 04 才把经审查的
coverage/init/mapping 逐字节复制到 ACT4 同名新路径，复制前确认基线中不存在目标。
完整阶段输出以配置为准；以上不是新增文件白名单。

## 1. 原始请求与规范化计划

1. 从 CTP 精确 table id/title 发现唯一 Sheet tab，不硬编码 table number/gid。
2. 把 raw CSV 当矩阵审阅；记录 request/non-request 矩形和带理由的 exclusions，
   覆盖所有非空 cell。区域坐标是 1-based 闭区间。
3. 每个 source item 用稳定语义 ID，关联请求与共享上下文 cells；位置只写在 cells 中。
4. CSV 固定列为 `source_items,coverpoint,normative_rules,disposition`；其中
   source_items 与 normative_rules 均以 JSON 字符串数组编码。
5. 每个 source item 恰好被消费一次。多个请求可合并为一个 logical coverpoint；
   一个 logical coverpoint 展开多个 SV target 留给 mapping，不能重复消费 source item。
6. disposition 仅使用 `coverpoint` 或 `removed`。删除项的 coverpoint 留空、
   normative_rules 为 `[]`；新增项的 source_items 为 `[]`。新增/删除需 provenance
   changes 的 rationale/evidence，范围必须仍属于本 suite。
7. rule ID 只取 metadata 的 name/names，Sheet rule 文本作为检索线索。

在阅读规范快照后、重建上述 CSV/人类 testplan 前，将以下补漏活动纳入当前工作计划：

- 从本次 output 工作区内已拷贝、冻结 HEAD 的 `riscv-arch-test/` 参考其他扩展已有的
  testplan、coverpoints 和测试用例，必要时查看 generator。可从 testplans/、coverpoints/、
  tests/ 等实际目录直接查找，无需先找到 testplan；只使用这份副本作为辅助资产来源。
- 对照前置状态、刺激、值域、预期结果和恢复流程，判断目标扩展自身要求下是否存在
  遗漏。H extension 可从 satp/地址翻译、中断 delegation 等设计入手；仅采纳目标规范、
  suite 范围和测试目标支持且必要的补充，不强行引入不必要、重复或属于其他扩展的内容。
- 将采纳设计改写为目标 testplan 的条目、子场景或测试维度，按后续步骤同步受影响的
  coverpoints、coverage intent/规范映射，无需修改每份资产。没有原始 source item 对应
  的规范内新增项按既有 source_items=[] 和 provenance changes 规则登记。
- 补全后的全部资产统一遵守上述第 1-7 项，以及下文的 Markdown 六字段、coverage 语义、
  intent 和 mapping 要求，保持集合一致与可追溯；参考不放宽最终 testplan 的规定，也
  不能作为省略当前扩展特有测试的理由。
- 将实际参考路径、发现的遗漏及采纳或不采纳的主要原因简记到 journal，采纳依据可放入
  已有 coverage gaps 或 Test notes。未发现适用且必要的补充时保留当前计划并继续，不要求
  新增数量、另建报告、遍历全部扩展或构建运行参考 suite，不增加 checker 或阶段门槛。

## 2. 人类 testplan

按以下 Markdown 结构填写。示例标识是占位符，不代表新增规范规则。

```markdown

# {DUT} Human-Readable Test Plan

| Coverpoint | Source request | Normative rules | Disposition |
| --- | --- | --- | --- |
| `cp_operation_context` | 原始请求的语义摘要 | `rule_from_metadata` | coverpoint |

## `cp_operation_context`

- Functional description: 规范定义的功能及正文锚点。
- Interface / instruction: 具体指令、CSR、字段、操作数或可观测接口。
- Privilege / preconditions: 特权级、虚拟化状态、目标能力、前置 CSR/内存状态。
- Expected result: 正常结果或精确异常，以及可判定的观测值。
- Timing / state restoration: 采样前后关系、必要 fence、状态保存与恢复。
- Test notes: WARL、合法值域、XLEN 差异、非目标 fault 排除与证据限制。
```

摘要表每个有效 logical coverpoint 恰好一行；Source request 不显示内部 ID 或坐标。
删除请求另列 Removed requests。六个字段不能只重复 coverpoint 名。

## 3. 观察模型设计表

写入 `reports/sheet_manual_sv_mapping.md`，每个主 target 都填一行：

| Logical coverpoint / actual SV target | Rule 与规范锚点 | Stimulus | Target selector | Operation qualifier | Observed outcome | Value domain / sampling time |
| --- | --- | --- | --- | --- | --- | --- |
| 待填 | 待填 | generator 建立什么状态 | CSR/字段/指令/地址对象 | read/write/execute/trap 条件 | 结果值、cause、目标模式 | 合法值/bin 与 before/after |

每项先写出功能、接口和时间关系，再选 coverpoint/cross：
- CSR 地址位只能作为 selector，不能单独证明发生了 CSR 写入或写后值正确。
- trap 目标须采样实际 trap/cause，并关联触发操作；退休指令或旧 cause 不能冒充本次异常。
- walking-bit 应区分 bit position；仅 `$onehot` 的真假不足以证明逐位遍历。
- cross 输入使用明确 bins，防止 default bin 造成误命中。
- 对 XLEN/虚拟化字段先查当前 RVVI 定义，不从 suite 名推断字段宽度或 mode 编码。
- 从同版本范例确认 covergroup 名、实例化、sample 函数签名与 dispatch；不预设
  `COVER_*`、CSR 常量或宏名一定存在。
- 不把 setup、页表或特权级切换的激励代码写进 SV；这些属于 generator。

## 4. coverage intent

写入 `{DUT}_coverage_intent.yaml`。下面是结构示例，所有 target/member 名都待替换：

```yaml
schema_version: 1
suite: "{DUT}"
supported_xlens: [64]  # 仅在目标证据确认 RV64 后保留
targets:
  cp_operation_context:
    covergroup: "{DUT}_cg"
    target_kind: cross
    required_cross_members: [operation_selector, execution_state, observed_result]
    exact_cross_members: true
```

普通 coverpoint 可使用 `required_bins` 或 `required_expression_terms`。
只有实际存在条件编译时才填写 `required_conditions`，例如 scanner 记录的
`ifdef:UDB_MXLEN_64`。至少一种可验证约束必须非空，但不能为满足 schema 增造维度。

这些字段检查的是成员、bin、预处理条件文本和表达式子串。必须先从规范独立推导意图，
再对照 SV；从有缺陷的 SV 反抄一份 intent 只能得到自洽的错误，不能证明语义正确。

## 5. norm mapping 与缺口

`{DUT}_normative_rules.csv` 的列是 `Normative Rule,Rule Text,Coverpoints`，
rule 集合与优化 CSV 一致；路径指向真实生成的 covergroup/target。

阶段 02 的 mapping 形状如下，rule 名和 target 都是待替换示意：
```yaml
normative_rule_definitions:
  - name: rule_from_metadata
    coverpoint: "{DUT}_cg/cp_operation_context"
```

以当前 DeveloperGuide 和 checker 支持的路径语法展开一对多 target。
不要使用 `coverpoints` 别名或旧 `norm-rules.json`。

`reports/coverage_gaps_and_conflicts.md` 按具体 target/subcase 记录：

| 范围 | 冲突或缺失事实 | 当前证据 | 影响生成/运行/coverage 哪一层 | 处置与后续动作 |
| --- | --- | --- | --- | --- |
| 待填 | 待填 | 文件/命令/原始结果 | 待填 | 待填 |

公共服务关闭时按 consumer 拆分；动态 coverage 不可用并不自动删除生成目标。
实验候选写入 experimental 目录并登记，不能混入正式 coverage。

## 6. 阶段检查与交接

阶段 01 使用 CTPReference、ManualReference、Asset、SwitchCapability、Manifest
(integrity_only)、AIReview；阶段 02 使用 Asset、AIReview。
必需 check 名从配置逐字读取。Check 可能生成报告文件，应登记其输出；
Complete 再验证后推进。静态通过不代表 SV 已编译或 coverage bins 已命中。

交接给 generator 的是：已冻结请求、规则映射、观察模型、coverage intent 和具体缺口。
后续按[VM 模板](privileged_vm_resource_template.md)建立 consumer 资源契约。
