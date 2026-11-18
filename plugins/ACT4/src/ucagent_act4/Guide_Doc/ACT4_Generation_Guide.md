
# ACT4 原生资产生成

## 1. 选择工作流

| 工作流 | 权威计划 | 实现重点 |
| --- | --- | --- |
| privileged-suite-generation | `testplans/priv/{DUT}.yaml` | 特权状态、异常、CSR、VM 资源及 suite generator |
| unprivileged-suite-generation | `testplans/{DUT}.csv` | 指令 × XLEN × coverpoint/variant、覆盖模板、formatter、decoder |

两者都先准备资源、环境和固定输入，再生成、检查原生资产，最后在独立副本只应用贡献集验证。
已有计划不是禁止补充的上限；以对应 ISA 为依据补漏，但不得默默删除已有请求或缩减 XLEN。
特权流程保留 `Guide_Doc/ACT4_Privileged_Suite_Workflow_Guide.md` 的 VM、参考模型与签名验收。
不发生 trap 的表驱动指令测试不需要虚构 VM 契约或 priv generator。路线按测试结构而非
ISA 类别选择，规则见 `Guide_Doc/ACT4_Asset_Authoring_Guide.md section 1`；需要 trap 的
非特权指令也使用场景型路线。功能名字未必等于 ACT suite，先确认精确名称。

## 2. 准备输入

使用 ACT4Resources 的 list/read 找到本 suite 所需全部规范原文，然后在输入阶段调用：

```text
Check(stage_args={"action":"prepare","manual_files":["src/priv/sstc.adoc"]})
Complete()
```

这是 Sstc 示例，其他 suite 必须换成实际原文路径。`inputs/` 包含原生计划快照（若存在）、
规范逐文件快照、`norm-rules.json`、公开规则全集和 `receipt.json`。不要手写或编辑收据。
原生计划不存在可创建；规范来源缺失或所需 rule 没有正式记录时，不得发明 ID。
规则 JSON 的发布版本与 manual HEAD 分别记录，必须核对文本与原文语义，不能假定同版本。
官方编码图等规则的 text 可以为空；这不代表规则不存在。输入收据列出 non_text_rules 和
对应原文出现位置 rule_locations，须核对原图表及其依赖；不能把空文本当作已解释的语义，
也不能为公开 JSON 编造文本。未能读取的图表/依赖作为来源限制带入最终报告。
进度表用于了解尚待贡献的工作，不替代固定版本的原生 schema、规范或构建结果。

## 3. 权威计划与派生视图

特权 YAML 遵循本轮捕获的 `testplan.schema.json`。每个有效行需填写完整意图、预期、
检查方式和 rules。下面是格式示例，规则名必须换成本轮捕获的真实名称：

```yaml
suite: Example
coverpoints:
  - name: cp_access
    goal: Access control
    description: Exercise permitted and denied accesses under the specified control settings
    expectation: Permitted accesses return the specified value; denied accesses raise the specified exception
    check: Compare the observed value and exception cause with the reference result
    rules: [example_access_rule]
```

特权 Check 从 YAML 派生 `{DUT}.csv` 和 `{DUT}_testplan.md`。机器 CSV 使用
`source_items,coverpoint,normative_rules,disposition`，数组字段为 JSON 数组；不要手工维护
第二份权威计划。人类视图按原生行列出字段，可回溯原生路径；设计细节写在原生行内。

非特权完整最小矩阵示例：

```csv
Instruction,Type,RV32,RV64,cp_rd,cp_rs1,cp_rs2
add,R,x,x,x,x,x
```

可选 `ExtraExtensions` 位于 RV64 后。coverpoint 单元格 `x` 表示基础模板，其他非空值表示
变体后缀。新覆盖点需要 SV template 和 Python generator；新 Type 需要 sample template 和
formatter；新指令需核对原生 decoder。优先复用，不修改生成的解码包、SV 或汇编来绕过源码。

## 4. 资产契约

写入 `{OUT}/intermediate/{DUT}/asset_contract.yaml`。下面是完整非特权示例：

```yaml
schema_version: 1
suite: Example
kind: unprivileged
parameters:
  status: required
  names: [MXLEN]
  rationale: The selected XLEN determines which instruction rows and register widths apply
ctp_sources:
  - docs/ctp/src/example.adoc
validation_configs:
  - config/spike/spike-rv64-max/test_config.yaml
extension_sources: []
```

特权使用 `kind: privileged`；无需 `extension_sources`。无参数时完整参数字段为：

```yaml
parameters:
  status: not_applicable
  names: []
  rationale: The selected rules have no implementation-dependent parameter affecting these tests
```

必须根据实际 ISA/UDB 核对该理由；不能仅为了不生成文件而写不适用。VM contract 或 Python
函数参数不能代替 ACT 的参数映射。`validation_configs` 必须选择固定 ACT 中有 `run_cmd.txt`
的真实配置，覆盖适用 XLEN；某模型不支持的范围明确列为限制，不能删掉生成请求。

非特权 `extension_sources` 仅能列实际新增/修改的以下原生扩展点：

- `generators/coverage/src/covergroupgen/templates/*.sv`
- `generators/testgen/src/testgen/coverpoints/*.py`
- `generators/testgen/src/testgen/formatters/types/*.py`
- `framework/src/act/fcov/disassemble.svh`
- `testplans/coverage/instruction_formats.csv`

其余框架、构建、环境宏和签名实现保持不变。共享扩展点影响其他 suite 时还需相应回归，
本工作流的 suite 级验证不能宣称替代全仓 CI。

## 5. 原生规则、参数和 CTP

`coverpoints/norm/Example.yaml` 完整结构示例：

```yaml
normative_rule_definitions:
  - name: example_access_rule
    coverpoint: [Example_cg/cp_access]
```

规则必须来自捕获 JSON 的 `name`，目标应是实际 coverage 路径；原生解释性 waiver 需要
明确理由，不是测试通过的证据。保留当前 ACT 要求的字段名 `normative_rule_definitions`。

`coverpoints/param/Example.yaml` 完整示例：

```yaml
parameter_definitions:
  - name: MXLEN
    coverpoint: [all tests]
    effect: [Select the supported XLEN rows and their expected register width]
```

参数名必须由真实 UDB 查询确认；effect 解释对测试的影响，而不是复述名字。
在实际 CTP 章节接入生成表，例如特权章节使用：

```asciidoc
include::{testplansdir}/priv/Example.adoc[]
include::norm/Example_norm_rules.adoc[]
```

非特权按本轮 CTP 的生成目录接入 `Example.adoc`。参数表为 `Example_parameters.adoc`，
由原生 norm 表生成器自动包含或由章节显式包含。仅生成 YAML 不代表文档已接入或成功渲染。

## 6. 提交边界与验证

File manifest 完整格式见 `Guide_Doc/ACT4_Checker_Guide/ACT4FileManifestChecker.md`。
贡献集是将交付的源文件集合，包含变更的计划、映射、章节和必要生成源码，以及上游要求
保留的生成 SV/.S。是否提交 `.S` 以固定仓库的 tracked/ignore 状态为准：ignored 的中间
汇编不提交；已跟踪或未被忽略的测试汇编与 generator 同步提交。修复仍须修改 generator
并重新生成，不能手改汇编。ELF、签名、日志、工具缓存和本地契约不进入贡献 patch。

原生验证阶段调用 `Check(stage_args={"action":"validate","timeout":3600})`，再普通 Check
和 Complete。真实执行包括生成一致性、源码 hooks、需要时 UDB 参数查询、CTP 构建、选定
native configs 的编译与执行。隔离副本只包含固定 ACT 和 contribution_set；未变更的原生
依赖可以直接复用，不需重复交付。日志和收据留在 `native-validation/`。

失败或零 ELF 阻止验收；不可用工具明确记为 limitation，不能记为通过。普通 Check 只核验
当前源码、输入、环境及证据，不重复运行命令。修改这些内容后必须重新验证。不得将
AI 自审、签名生成或模型运行通过解释为真实 DUT 已认证、覆盖率 100% 或上游 CI 全通过。

## 7. 最终报告

`final.md` 是唯一总结入口，`changes.patch` 是贡献补丁；详细证据只链接、不重复复制。
以下为最小完整非特权报告的结构示例，实际 suite、文件、结果和限制必须来自本轮：

```markdown

# Example generation report

## Executive conclusion

Generated the instruction plan, coverage and test sources, rule mapping and CTP integration.
Native validation passed for the selected configuration. Maintainer review and contributor signing remain human work.

## Coverage scope

The plan selects add on RV32 and RV64. Execution covered only the selected RV64 configuration;
RV32 execution and hardware coverage are not claimed.

## Report index

- [Prepared inputs](intermediate/Example/inputs/receipt.json)
- [Environment](intermediate/Example/environment/summary.md)
- [Native validation](intermediate/Example/native-validation/receipt.json)
- [Design review](intermediate/Example/reports/design_review.md)
- [Manifest](intermediate/Example/reports/Example_file_manifest.yaml)

## Limitations and non-claims

Selected configurations are not the whole upstream CI. No DUT certification or hardware coverage claim.
The contributor must arrange licensing review, DCO sign-off, commit signing and maintainer review.

## Reproduction

Apply changes.patch to the recorded ACT commit, prepare its pinned dependencies, then use the native commands
and selected configurations recorded in the validation receipt. Modify generator sources, not generated assembly.
```

在最终报告中另加且仅加一个 YAML fence，内容必须与真实 native receipt 完全相同：

```yaml
generation_result:
  asset_completeness: complete
  validation_complete: true
  limitations: []
  source_limitations:
    - Published rule text and pinned manual are separate snapshots; compare semantics before implementation.
  submission_requirements:
    - Real maintainer review
    - SPDX/licensing review
    - Contributor DCO sign-off and cryptographic commit signature
```

`validation_complete` 仅表示所选命令全部通过，不代表未选配置或可选 coverage 已验证。
source_limitations 保留输入收据的来源边界，包括发布版本与原文独立、非文本规则需核对图表等。
有不可用步骤时为 false，并在 limitations 中列其真实步骤名，同时在人类摘要中说明原因和
恢复办法。特权报告还保留其 validation state 与专用章节，不能用此汇总代替签名或范围验收。
