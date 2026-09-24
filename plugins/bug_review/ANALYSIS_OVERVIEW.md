# Bug Review 插件结构与分析流程

本文按当前 `bug_review` 源码和 `workflows/analysis.yaml` 说明插件的分析流程、主要文件、可精简项，以及它和其他 UCAgent 插件的组合方式。当前 `plugins/bug_review/` 在工作区中是未跟踪目录；本文只记录分析结果，不删除或改写现有实现。

## 分析工作流

工作流入口是 `bug_review/workflows/analysis.yaml`。九个阶段都引用 `Guide_Doc/analysis.md` 和工作区的 `benchmark_job.json`，并由 `BugReviewStageChecker` 按阶段名检查产物。阶段推进、任务队列、状态和产物校验由 `BugReviewRunStage`、`BugReviewTasks`、`BugReviewSubmitResponse`、`BugReviewStatus` 等插件工具驱动。

| 阶段 | 工作内容 | 主要输入 / 参考 | 主要输出 |
|---|---|---|---|
| `inputs` | 发现 DUT 与运行，冻结分析范围；检查报告和证据是否缺失。分析输入应是本次测试运行的工作区副本。 | `Guide_Doc/analysis.md`、`benchmark_job.json`、显式运行路径及其测试产物 | `input_inventory.json`、`analysis_scope.json` |
| `parse` | 解析测试、模型声明、覆盖率、规格和 RTL 关联，整理全部失败用例，包括参数化实例和失败阶段。 | 同上；冻结的输入运行、测试报告、规格和 RTL | `parsed_inputs.json` |
| `replay` | 在隔离副本重跑测试，审查原始和本次报告中的所有失败，逐项归因并记录复现状态。 | 同上；解析结果、原始和重跑报告、测试源码 | `tasks/*/replay/reviews.json` |
| `waveform` | 检查本次失败用例的波形，结合事务和时序证据复核归因；确认 DUT Bug 时保留真实波形证据。 | 同上；失败用例、驱动/规格、`BugReviewWaveInfo` 返回的波形上下文 | `tasks/*/waveform/reviews.json` |
| `semantic` | 比较候选 Bug 的语义等价性；必要时完成后续独立审查轮次。 | 同上；冻结的候选与证据、任务请求 | `tasks/*/semantic/comparison_result.json` |
| `failure_mode` | 审查根因失效模式；按工作流要求收集多票判断并处理冲突。 | 同上；已验收的测试、语义与波形证据 | `tasks/*/failure_mode_complete.json` |
| `root_appeal` | 审查 RTL 根因申诉和缺陷聚类，形成根因关系。 | 同上；前序判断和根因审查任务 | `tasks/*/root_review/result.json` |
| `alignment` | 将报告根因与 GT 对齐，避免把未命中的 GT 归给模型。 | 同上；最终复核证据、GT 注册库和待对齐任务 | `tasks/*/analysis.json` |
| `publish_analysis` | 生成报告数据、详情页、HTML 和带哈希的分析清单；发布分析证据，不计算模型得分。 | 同上；汇总分析、最终 Bug 分析、复核与波形证据、适用的报告 profile | `analysis/analysis_manifest.json`、`analysis/dut_*/report_data.json`、HTML 报告及 Bug 详情页 |

Make 前置步骤通过 `input_preparation.py` 复制 UnityTest workspace 并运行测试；这属于工作流启动准备，不是 YAML 中的独立阶段。`analysis_scope.json` 固定范围后，后续阶段围绕该范围产生并校验任务证据。历史报告可用于参考，但不能代替规定的本次重跑。

### 当前边界：评分流程没有接通

仓库还含有 `workflows/scoring.yaml` 和 `Guide_Doc/scoring.md`，但当前 `plugin.py` 只把 `analysis` 注册为 `PluginWorkflow`；`workflow.py` 的 `prepare()` 和 `Workflow` 初始化也只接受 `kind == "analysis"`。因此现有 UCAgent 插件入口无法选择或执行 `bug_review:scoring`。Makefile 中 `bug-review-scoring` 目标也尝试准备并启动这个未接通的流程。评分资源目前应视为待修复功能或待清理候选，不能当作当前可用功能。

## 主要目录和文件

| 路径 | 职责 |
|---|---|
| `ucagent-plugin.toml` | 源码态发现清单，提供插件 ID、Provider 路径和 Python 根目录。 |
| `pyproject.toml` | 独立发行包、依赖、UCAgent entry point、命令行入口及包内资源配置。 |
| `bug_review/plugin.py` | 向 UCAgent 注册工具工厂、Checker 和插件工作流。 |
| `bug_review/adapter.py` | UCAgent 工具与 Checker 适配层；调用内部工作流并返回诊断。 |
| `bug_review/workflow.py` | 分析阶段调度、状态/产物校验、人工判断队列接续和报告发布。 |
| `bug_review/input_preparation.py` | 复制外部 DUT workspace，并按要求重跑 UnityTest。 |
| `bug_review/inputs.py`、`scope.py` | 解析输入路径并发现、冻结本次分析范围。 |
| `bug_review/tasks.py`、`test_execution.py`、`waveform.py`、`case_analysis.py` | 判断提交与任务持久化、测试回放、波形取证和失败用例归因。 |
| `bug_review/benchmark_workflow/` | 复用的分析核心：输入发现/解析、证据模型、回放、语义与根因任务、报告及评分计算组件。 |
| `bug_review/configs/` | GT 注册库、DUT 规格和覆盖率契约、评分策略、报告配置等随包数据。 |
| `bug_review/resources/` | 波形转换和 QEMU Python 启动辅助资源。 |
| `bug_review/workflows/`、`Guide_Doc/` | Agent 阶段定义和运行说明；当前只有分析工作流已注册。 |
| `Makefile`、`README.md`、`tests/` | 开发/启动快捷入口、说明和回归测试。 |

## 和 DesignWithPPA、RTL2Spec 的结构区别

三者通过相同的 UCAgent 插件接口接入：清单/发行配置、`plugin.py` Provider、工具/Checker、工作流 YAML 和随包资源。主要区别在插件包承担的职责：

- `DesignWithPPA` 和 `RTL2Spec` 主要以被 UCAgent 调度的设计/文档工作流为中心。
- `bug_review` 除 UCAgent 工作流外，还自行准备输入副本、运行测试、维护复核队列和状态，并生成较复杂的分析报告；`benchmark_workflow/` 和基准配置数据因此更大。
- `bug_review` 当前把阶段流程和大量报告渲染放在较大的 `workflow.py` 中，核心处理则分散在大量 `benchmark_workflow` 文件里。这是维护复杂度和职责边界上的差异，不能仅凭文件数量判定为冗余。

## 精简建议

暂不建议按“文件未被直接 import”或“文件很多”删除代码。工作流按字符串调度阶段，配置文件和 JSON 也会被运行时读取，普通静态 import 搜索容易误判。建议先按功能决策分批核实：

1. **评分路径**：明确是否保留独立评分。如果保留，需要同时注册评分工作流、实现 `prepare-scoring` 和 scoring 阶段执行/状态契约，再验证 Make/README 的命令；如果取消，再一起移除未使用的评分 YAML、Guide 和仅服务该路径的实现/数据。
2. **`bug_review.toml` 的 `[benchmark].duts`**：YAML 已说明分析范围不使用该列表，README 也描述以显式输入/发现结果确定范围。可确认是否还有其他读取者；若没有，移除该字段。整个 TOML 仍承担 replay 等配置输入，不能因此直接删除。
3. **`requirements.txt`**：当前只有 `UCAgent>=26.9.2.dev6`，与 `pyproject.toml` 的运行依赖重复。若项目只支持包安装，可考虑删除；若支持 `pip install -r requirements.txt`，保留并说明用途。
4. **启动文档/Make 命令**：README 写的仓库根目录目标与插件内 Makefile 的目标名不一致，且根 Makefile 没有对应目标。统一工作目录和命令名可减少无效入口；这是文档/入口修正，不应通过删除插件 Makefile解决。
5. **打包清单**：`pyproject.toml` 明确包含 `configs/**/*.json`、`configs/**/*.md`、工作流、Guide 和资源。若任何文件移除，应先检查运行时读取路径和 sdist/wheel 是否仍能在安装环境工作；尤其不能把 GT/规格数据误当成测试 fixture。

## 一个插件使用另一个插件的能力

**在一次 Agent 启动中组合多个插件：可以。** `--plugin` 可重复传入；UCAgent 会把已选插件的工具和 Checker 合并注册，并收集其通用 Guide_Doc/Skill 资源。插件工具名称和 Checker 名称冲突会报错。`--plugin-workflow` 则从已激活插件中解析一个工作流，因此一次启动选择一个插件工作流，同时可加载其他插件提供的工具/Checker。

例如可同时激活两个插件，并运行其中一个的工作流：

```bash
ucagent <workspace> <dut> \
  --plugin bug_review \
  --plugin design-with-ppa \
  --plugin-workflow bug_review:analysis
```

这表示 Agent 可见两个插件注册的工具/Checker，工作流仍来自 `bug_review:analysis`。它不代表 `bug_review` 的 Python 代码会自动调用 DesignWithPPA 的工具，也不表示 UCAgent 有插件间依赖解析、版本协商或服务编排。若一个插件要在 Python 内直接复用另一个插件的库，应显式声明 Python 包依赖并定义稳定的库接口；不应依赖“另一个插件恰好也被激活”。当前 `Plugin` 描述没有声明插件依赖的字段。

对 Bug Review 来说，复用别的插件能力是否有意义取决于具体操作：同一 Agent 会话需要额外工具时可以组合激活；但 Bug Review 的核心回放、证据和报告流程目前是自己的实现，不会因同时加载 DesignWithPPA 或 RTL2Spec 就自动改变。
