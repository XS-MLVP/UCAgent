
# RTL2Spec 质量复核报告

正式报告仅保留一个一级标题，以下六个二级区块按顺序各出现一次。每块填写实际发现或明确限制；表格需要非空数据行，不能仅保留表头、全空行、子标题、注释或代码示例。事实数量须对照当前设计文档和 semantic_review.json 核实，不能复制示例数字。

## 输入基线

- 模块：`[DUT]`
- 配置：`[config]`
- RTL/source 基线：`[manifest 中的基线]`
- RTL 生成状态：`[success / partial / provided]`
- 实际复核输入：列出本次读取的 captured RTL 和相关源码；通用 RTL 流程还应列出 preprocessed RTL、source_map 及实际编译配置。

## 源码复核发现

逐个列出当前 `P-*` 与源码对照后的结论。每条结论要指向 `E-*` 或 `OPEN-*`，并说明发现的矛盾、修正或未能判定的原因。

## 结构化事实统计

| 统计项 | 数量 | 说明 |
| --- | ---: | --- |
| P-* 总数 | `[count]` | 当前设计文档中的行为数 |
| asserted | `[count]` | 已由 assignment facts 与 E-* 范围核对的行为 |
| no_deterministic_fact | `[count]` | 复杂语义，必须关联 Open/Deferred 的 OPEN-* |
| 关联 OPEN-* | `[count]` | 当前仍未关闭的证据或判定缺口 |

## OPEN 与限制

列出未关闭的 `OPEN-*`、`partial` 生成影响、配置假设和本次不能推出的结论。关闭的 OPEN 只放在变更记录或历史说明中。

## 未执行验证

逐项记录仿真、综合、回归、断言编译、formal 和 coverage 是否执行。未执行项目保持 `Unrun` 或 `Open`，不能把结构检查写成执行通过。

## 验收范围

本报告的 Pass 只覆盖当前文档结构、源码证据、端口映射、语义复核记录和签名工件的一致性；它不表示 RTL 已通过仿真、综合、回归或形式化证明。

## 完整参考例

下面的完整 Markdown 工件展示六个固定区块的顺序和最小有效内容。实际报告应替换模块、配置、基线、事实数量和具体复核发现。

````markdown

# RTL2Spec 质量复核报告

## 输入基线

模块为 `ExampleBlock`，配置为 `DefaultConfig`，RTL/source 基线为 `fixture-source-baseline`，生成状态为 `provided`。本次通用 RTL 复核读取 `outputs/evidence/ExampleBlock.sv`、`outputs/evidence/ExampleBlock.preprocessed.sv`、`outputs/evidence/source_map.json` 和已登记的相关源码；XiangShan 复核只列出实际存在的 captured RTL 与相关源码。

## 源码复核发现

`P-FORWARD` 已对照 `E-RTL-01` 的 RTL 范围完成复核；赋值事实与源范围一致，没有发现与文档正文矛盾的行为描述。

## 结构化事实统计

| 统计项 | 数量 | 说明 |
| --- | ---: | --- |
| P-* 总数 | 1 | 当前设计文档中的行为数 |
| asserted | 1 | 已由 assignment facts 与 E-* 范围核对的行为 |
| no_deterministic_fact | 0 | 没有需要人工保留的复杂事实 |
| 关联 OPEN-* | 1 | `OPEN-FORMAL-01` 仍为 Open |

## OPEN 与限制

`OPEN-FORMAL-01` 表示本次没有执行形式化验证。当前结论只覆盖已捕获的 RTL、源码引用、端口映射和结构化复核记录，不扩展到仿真、综合或 formal 结果。

## 未执行验证

本次未执行仿真、综合、回归、断言编译、formal 和 coverage；这些项目保持 `Unrun` 或 `Open`。

## 验收范围

本报告的 Pass 仅覆盖文档结构、源码证据、端口映射、语义复核记录和签名工件的一致性，不表示 RTL 已通过动态验证或形式化证明。

````
