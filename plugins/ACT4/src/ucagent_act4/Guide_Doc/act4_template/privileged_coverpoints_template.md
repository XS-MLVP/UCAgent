<!-- SPDX-License-Identifier: Apache-2.0 -->

# ACT4 Privileged Coverpoints 设计模板

适用 01_coverpoints 和 02_norm_mapping。完整原生计划、输入和资产契约示例见
`Guide_Doc/ACT4_Generation_Guide.md section 2` 至 `Guide_Doc/ACT4_Generation_Guide.md section 5`。

## 1. 输入与计划

读取本轮 inputs/ 中固定原生计划、规范原文及 norm-rules.json，记录 ACT HEAD 和首次写入前
基线。创建或完善 `testplans/priv/{DUT}.yaml`，使用原生 schema。每行填写功能目标、刺激、
预期、检查方式和正式 rules，不能删除原生 source 请求。参考邻近 suite 仅用于规范内补漏。

## 2. 产物与派生视图

Check 派生 `{DUT}.csv` 和 `{DUT}_testplan.md`；不要手写或修改这两份视图。
coverage/init 草稿位于 `{OUT}/intermediate/{DUT}/coverpoints/priv/`；填写 coverage intent、
`{DUT}_normative_rules.csv`、`reports/plan_manual_sv_mapping.md`、coverage gaps、基线、
switch audit 和 AI review。阶段 04 按新 suite 政策将审查后的 coverage/mapping 复制到 ACT。

## 3. 观察模型设计表

写入 `reports/plan_manual_sv_mapping.md`，每个主 target 都填一行：

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
  - name: rule_from_norm-rules.json
    coverpoint: "{DUT}_cg/cp_operation_context"
```

以当前 DeveloperGuide 和 checker 支持的路径语法展开一对多 target。
映射字段使用 `normative_rule_definitions` 和 `coverpoint`，规则身份取自捕获的 `norm-rules.json`。

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
