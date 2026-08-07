# 增量修复前的工作流初步认知

## 目的

本阶段的目标是让增量 Agent 在制定修复计划前理解工作流的整体用途、主要阶段、工具与
Checker 的职责、用户输入输出、环境入口和用户专业知识。它不是完整代码审计，也不负责
在此时发现所有实现缺陷。

评估 finding 只描述已观察到的问题，不能直接当作完整修改方案。Agent 先通过核心配置和
文档建立全局认识，进入后续计划阶段后，再针对批准项完整阅读受影响组件的源码、规格、
注册、测试和相关文档。

## 必读范围

先调用 `IncrementalContextInventory` 生成最小架构基线，然后完整读取以下具体文件（存在时）：

1. `workflow/config.yaml`、`workflow/config/inc.yaml`、中心 `workflow_spec.yaml` 和验收规则。
2. `workflow/README.md`，以及 `docs/README.md`、`02输入输出.md`、`03步骤及检查.md`。
3. `docs/04开发者文档-tools.md`、`docs/05开发者文档-checkers.md`，只用于建立组件地图。
4. `workflow/Makefile`、`workflow/setup.py`、`workflow/ucagent_setup.sh`、`workflow/requirements.txt`。
5. `res/common.json`（和存在时的 `res/index.json`），以及当前 `eval/approvals.json`、
   `eval/applied_changes.json`。

这些文件足以说明整体用途、运行入口、输入输出、组件职责、批准边界和同步风险。初步认知
必须在完成这个固定清单后立即结束；它不是“先把整个工作流读完”的门槛。

不要求在本阶段逐个读取：

- `workflow/Guide_Doc/` 的全部文档、`workflow/docs/` 的其余文档和 `res/` 的其余资料
- `workflow/input/`、`workflow/tools/*.py`、`workflow/checkers/*.py`
- `.workflow/tool_specs/`、`.workflow/checker_specs/` 及注册/绑定细节
- 工具和 Checker 测试目录及全部 fixture、输出、日志、缓存、历史版本和旧候选

工具与 Checker 的总体信息应从 `workflow_spec.yaml`、最终配置和两份开发者文档获取。计划
阶段只把批准项切成小批次；部署阶段每次只完整读取当前批次实际涉及组件的源码、规格、绑定、
测试、必要 Guide_Doc 片段和相关用户资源。完成该批第一份候选并部署后，才允许开始下一批。

## 需要形成的认识

阅读完成后应能简要回答：

1. 这个生产工作流解决什么用户问题。
2. 用户提供哪些输入，工作流产生哪些输出。
3. 主流程和增量流程各自包含哪些主要阶段。
4. 工具负责哪些生成、编译、仿真、覆盖率或报告工作。
5. Checker 在哪些阶段阻止错误产物继续流转。
6. config、workflow spec、工具、Checker 和文档之间为什么需要同步。
7. setup、Makefile 和 shell 环境入口承担什么作用。
8. `res/` 中有哪些用户专业知识需要约束本次修复。
9. 当前批准项大致影响哪些组件，哪些文件需要在下一阶段深入阅读。

这里只需要初步架构认识，不要求为每个源码函数做代码分析，也不要求运行测试证明行为。

## 清单工具

调用方式：

```text
IncrementalContextInventory(
  action="initialize",
  workflow_root="workflow",
  resource_root="res",
  output_path="<run_dir>/context/incremental_context_report.json",
  overwrite=true
)
```

`run_dir` 必须从 `tmp/inc_runs/current.json` 读取并替换成真实路径。`action=initialize` 只枚举核心文件、计算 SHA256 并写入本轮目录。它不会分析文件内容，
也不会修改 `workflow/`、`eval/` 或 `res/`。禁止用 `RunTestCases` 执行临时哈希脚本。

读取结束后必须用 `action=update` 提交四项总览和 `file_updates`。每条 file update 包含
初始化清单中已有的 path，以及 purpose、contract、synchronizes_with。工具拒绝未知
路径、重复路径、过短分析和初始化后已经改变 SHA256 的文件，并使用同目录临时文件和
`os.replace` 原子写入报告。可以一次提交全部文件，也可以分批提交；分批时不得重新
initialize，否则会清除前一批分析。

```text
IncrementalContextInventory(
  action="update",
  output_path="<run_dir>/context/incremental_context_report.json",
  architecture="不少于四十字符的具体架构说明",
  runtime_flow="不少于四十字符的实际运行链说明",
  approved_change_impact="不少于四十字符的批准影响说明",
  cross_file_risks="不少于四十字符的同步风险说明",
  file_updates=[
    {
      "path": "workflow/config.yaml",
      "purpose": "主运行配置，定义实际执行阶段和绑定关系",
      "contract": "必须与中心规范中的同名阶段逐字段一致",
      "synchronizes_with": ["workflow/.workflow/workflow_spec.yaml"]
    }
  ]
)
```

最后调用 `action=validate`。只有返回 `valid=true` 才能结束认知阶段。禁止用
`EditTextFile`、`ReplaceStringInFile` 或其他普通文件工具直接编辑报告 JSON；这会绕过
路径、哈希和结构校验，并可能产生非法控制字符。

## 报告格式

报告沿用以下结构：

```json
{
  "contract_version": 1,
  "workflow_root": "workflow",
  "files": [
    {
      "path": "workflow/config.yaml",
      "category": "configuration",
      "sha256": "64位小写十六进制",
      "purpose": "主运行配置，定义阶段和工具绑定",
      "contract": "必须与中心规范及实际工具输出保持一致",
      "synchronizes_with": ["workflow/.workflow/workflow_spec.yaml"]
    }
  ],
  "architecture": "整体组件和职责的简要说明",
  "runtime_flow": "从输入到输出的主要运行流程",
  "approved_change_impact": "批准项可能影响的组件及后续深读范围",
  "cross_file_risks": "需要在修复阶段重点防止的同步风险"
}
```

每个核心文件提供一条简要记录即可。`purpose` 和 `contract` 应说明真实用途，不需要达到
开发者文档级别的代码分析。没有直接同步文件时，`synchronizes_with` 可以为空。

四项总览应基于配置、中心规范、文档和资源形成，不要复制 finding 全文。发现某个问题
需要进一步确认时，应写入后续深读范围，而不是在本阶段展开完整实现审查。

## 读取回执

UCAgent 会对固定核心文件登记 `ReadTextFile` 回执。调用 `Check` 或 `Complete` 时，未读取的
基线文件会被列出并阻止阶段通过。递归目录、通配路径和“全部生产文档”不属于本阶段回执范围。

这个机制只覆盖上述核心范围，不再追踪每个工具源码和测试 fixture。大文件可按合理分段
读取，但必须读到文件末尾；搜索结果不能代替对核心配置和文档的阅读。

## 通过条件

1. 固定最小架构基线已经读取，没有递归扩展为全树审计。
2. 报告包含当前核心文件路径和正确 SHA256。
3. 每条记录有简要但具体的用途与契约说明。
4. 四项总览能够说明架构、运行流程、批准影响和跨文件风险。
5. 报告 JSON 可以正常解析。
6. 本阶段没有运行行为测试，也没有修改正式工作流。
7. `IncrementalContextInventory(action="validate")` 返回 `valid=true`。

满足这些条件即可进入计划阶段。后续对受影响组件的深读和验证不能由本阶段报告替代。
