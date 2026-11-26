
# 生成运行与来源选择

## 1. 当前任务

从 `.ucagent/act4-run.yaml` 的 `act4_run` 取得 suite、target_context、九类 mode/source/path/on_missing、上游版本及限制。
不要重新解释环境变量。先完成独立 ISA 计划，再检查文件清单、选取来源、导入、审查、生成及复验。
`improve` 允许零修改；`regenerate` 不读该类别旧设计，但仍要遵守 ISA、框架 API 和其他类别的依赖。
Norm Rules、UDB/Params、RVVI、RVMODEL Macros、Sail 是 `repair_only` 共享输入。缺能力或缺文件不构成 bug；先引用、复用或记录限制，不为凑齐清单造规则、改模型。suite 自己的规范映射、测试计划和测试代码仍按任务生成。
决定文件所属类别时按内容和归属仓库区分：发布规则原文和上游定义归共享输入，suite 内的规则到覆盖点映射归覆盖或计划；不能把原文改动改名为映射或测试修复。
不得借旧 CTP、报告、补丁、生成结果或共享源目录绕开这一限制；不能声称模型已忘记先验知识。

## 2. 来源选择和导入

独立计划见 `Guide_Doc/ACT4_Extension_Review_Guide.md section 10`。
来源阶段调用 `Check(stage_args={"action":"discover"})`，读取
`{OUT}/intermediate/{DUT}/asset-inputs/inventory.json` 的文件名清单。
为九类资产创建同目录 `selection.yaml`：用精确原生路径列出全部相关源文件，包括待重生成文件，
以便从本轮可读工作副本移除；没找到的类别写空 files 和有来源的理由，不编造文件。
`requirements` 引用独立计划的 I 编号。不得通过遗漏选择使旧设计继续留在工作副本中。
未选源文件的类别无需强挂无关条目，可写 `files: []`、`requirements: []` 和具体理由。独立计划因缺规范明确没有义务时，也可保留空 requirements 继续有限的静态审查；
这不代表具备生成依据或完整性证明，后续必需生成和验证仍须补齐规范，不能伪造 I 编号。

`repositories` 只列 ACT 之外的 Git 仓库；先按固定版本准备到
`{OUT}/intermediate/{DUT}/dependency-sources/<name>`。ACT 自动登记为 `act4`。
文件一律声明 `repository/path/local_path`；上游或重生成的 `local_path` 是 null，
本地来源使用配置目录下的相对文件路径。歧义、缺失、共享文件策略冲突必须先解决，不能任意挑一个。
同一文件可供多个类别使用，但来源须一致，不能既要求移除重生成又要求保留；后续 checklist 必须覆盖每个所属类别，共享输入保护仍适用。

以下是结构完整的示例；路径、理由和 I1 必须换为本轮实际发现，不是 Sstc 完整资产清单：

```yaml
schema_version: 1
suite: Sstc
repositories: {}
assets:
  norm_rules:
    files: []
    reason: No editable rule source was selected; bind the pinned ISA and record rule disposition in the checklist.
    requirements: [I1]
  udb_params:
    files: []
    reason: Inspect parameter needs against I1 before deciding whether a separate dependency is required.
    requirements: [I1]
  rvvi:
    files: []
    reason: Determine observation requirements from I1 and the framework interface.
    requirements: [I1]
  rvmodel_macros:
    files: []
    reason: Assess timer platform support from the independent design.
    requirements: [I1]
  testplan:
    files:
      - repository: act4
        path: testplans/priv/Sstc.yaml
        local_path: null
    reason: Selected native plan for comparison with the independently derived I1.
    requirements: [I1]
  ctp:
    files: []
    reason: Render CTP from the accepted native plan after source comparison.
    requirements: [I1]
  coverpoints:
    files: []
    reason: No matching editable coverage file was found in this example input; implement from I1.
    requirements: [I1]
  sail:
    files: []
    reason: Assess existing reference capability and record actual applicability before any model change.
    requirements: [I1]
  tests:
    files: []
    reason: No editable generator was found in this example input; derive stimulus and assertions from I1.
    requirements: [I1]
```

只有本地补丁时，文件条目用例如
`{repository: act4, path: generators/testgen/src/testgen/priv/Sstc.py, local_path: changes.patch, patch_base: "<40位实际提交SHA>"}`。
从原输出的 manifest/来源记录确认基线，不凭补丁正文猜测；与本轮固定提交不符就停止导入，明确所需版本。
补丁在隔离副本先检查可应用性，只提取所选原生文件。ELF/bin-only 输入不能用作源码。

调用 `Check(stage_args={"action":"import"})` 后只读来源被冻结；普通 Check/Complete 核验来源未变。
编辑 `riscv-arch-test/` 和 `capabilities/<name>/`，不编辑 `act4-inputs/`、
`act4-inputs-dependencies/`、原本地目录或 receipt。配置或来源选择有误时换新工作区。

## 3. 基线审查、生成和复验

使用 `Guide_Doc/ACT4_Extension_Review_Guide.md` 的 scope/review/final 格式。
scope 路径相对 `act4-inputs`，但不得引用 receipt.removed 中待重生成旧文件；空资产集合是合法的新生成输入。
缺失/重生成是计划工作，changes 可使用 `findings: []` 和 `requirements: [I1]`；不能为了生成而伪造缺陷。
发现的真实缺陷仍须给证据、修复方案和复验。九类资产使用
`Guide_Doc/ACT4_Checker_Guide/ACT4AssetChecklistChecker.md` 的 checklist，纳入所有导入仓库。
请求策略不替代实际 action；共享来源或依赖受影响时补充消费者回归。

复验阶段只改工作源码，不直接编辑 review/candidate；普通 Check 同步 candidate。
生成路径必须纳入 review.changes/post_assets；之后用 run_commands 获取真实 after 证据。
任何进一步修改都要刷新受影响验证，不能复用旧结论。

## 4. 最终结果

根目录 `final.md` 先写验收的审查摘要：检查、生成/修复、未解决项、原因和用户需要提供的帮助。
链接 `intermediate/{DUT}/review-results/final.md` 查看逐项 finding 和证据。
按 `asset-inputs/policies.md` 纳入完整可见的 Asset input policies 表，再保留九类实际结果 checklist。
门禁发布相对导入基线的 `changes.patch`；无修改时为空，不是失败。依赖补丁在 `dependency-patches/`。
日志、来源和审查过程保留在 intermediate，不复制为多份根目录报告。
未完成必需验证不能声明完成；商业工具缺失及外部限制须明确记录，不把“没有运行”写成通过。
