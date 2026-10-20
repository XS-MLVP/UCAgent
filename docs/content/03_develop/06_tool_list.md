
# 工具列表

本页按用途列出主要工具。实际可用工具由工作流、插件、技能开关和工具过滤配置决定，名称与参数以本次运行的 schema 为准。控制台用 `tool_list` 查看当前工具；自定义实现见[定制工具](05_customize.md)。

## 阶段与验收

| 工具 | 用途 |
| --- | --- |
| `RoleInfo` | 获取角色、系统任务和约束 |
| `Status` / `CurrentTips` / `Detail` | 查看阶段状态、当前任务提示和详细信息 |
| `Check` | 检查当前阶段；批量阶段可在通过后切换到下一批 |
| `Complete` | 执行最终检查和适用门禁，成功后推进阶段 |
| `GoToStage` | 回到已经到达的阶段 |
| `KillCheck` | 中止正在执行的检查 |
| `StageJournal` / `AllStageJournal` / `SetCurrentStageJournal` | 读取或记录阶段日志 |
| `StageDiff` / `StageCommit` | 查看或记录阶段产物变化 |
| `HumanHelp` | 请求人工帮助 |
| `Exit` | 按当前任务规则请求退出 |

`Check` 和 `Complete` 不是成功声明：它们会读取当前产物并执行 Checker。参数中的 `stage_args` 用于当前 Checker 支持的附加输入；`full_output: true` 可请求原始检查结果。验收规则见[工作流配置](03_workflow.md)。

## 文件与文本

所有路径都应相对于当前 workspace。写入受 UCAgent 的可写目录和禁止写入配置约束。

| 工具 | 用途与关键参数 |
| --- | --- |
| `ReadTextFile` | 读取文本；`path`、`start`（从 1 开始）、`count`。也是阶段参考文件和技能阅读记录的来源 |
| `ReadBinFile` | 读取二进制文件的字节范围 |
| `PathList` | 按深度列出目录结构 |
| `FindFiles` | 按文件名模式查找文件 |
| `SearchText` | 搜索文本或正则，可限制文件、命中数和上下文范围 |
| `EditTextFile` | 创建或覆盖完整文本；可用 `append` 追加，`expected_sha256` 检查并发修改 |
| `ReplaceStringInFile` | 精确替换唯一的非空文本；可限制 `line_blocks`，支持 SHA-256 和 `dry_run` |
| `DeleteTextLines` | 按删除前快照的物理行号删除单行或闭区间，支持 SHA-256 |
| `CopyFile` / `MoveFile` | 复制或移动文件，可指定是否覆盖 |
| `DeleteFile` | 删除文件，按 schema 提供路径及确认参数 |
| `CreateDirectory` | 创建目录 |
| `GetFileInfo` | 查看文件大小、修改时间等信息 |

`DeleteTextLines.line_blocks` 示例：`[1, [10, 20]]` 删除第 1 行及第 10–20 行；`[10, 20]` 只删除两个单行。全部范围都引用原文件，任意越界会拒绝整次操作。`ReplaceStringInFile` 的搜索块使用嵌套闭区间，如 `[[10, 20]]`，匹配在全部指定块中必须唯一。

推荐先读文件并记录 SHA-256，再提交修改；并发冲突时重新读取后重做编辑。

## 测试、命令和工作区

| 工具 | 用途 |
| --- | --- |
| `RunPyTest` | 运行 Python 测试，可提供 pytest 参数和超时，并选择返回 stdout/stderr |
| `RunUnityChipTest` | 运行 UnityChip/toffee 测试并生成相应报告 |
| `RunTestCases` | 运行阶段支持的测试用例集合 |
| `RunBashCommand` | 在工作区执行 Bash 命令；默认被工具过滤配置忽略 |
| `WorkDiff` / `WorkCommit` | 查看 Git 工作区差异或提交允许的文件；默认被忽略 |

不要把测试基础设施错误登记为 DUT Bug。真实暴露 DUT 缺陷的失败用例应保留断言，并按当前工作流记录证据。

`RunPyTest` 的输入 `timeout` 默认 15 秒；UCAgent 还会设置工具级 `call_time_out`，默认 300 秒。长任务需同时考虑工具和客户端超时，具体以实际调用配置为准。

## 波形证据

| 工具 | 用途 |
| --- | --- |
| `WaveInfo` | 查找测试波形、分析信号和时钟对齐，产生可校验的证据 receipt |
| `ApplyWaveInfoEvidence` | 使用经过验证的 receipt 更新 Bug 文档中的中心波形记录 |
| `ReviewWaveInfoEvidenceBatch` | 准备一组需要复核的波形上下文，并在全部审核完成后原子应用结果 |

波形工具依赖可选的 `wavekit`。需要波形证据的阶段必须具备依赖和真实测试数据。探索性查询不能替代完整证据；参数、TC 节点和 Bug 文档格式按当前工具 schema 与运行时 `Guide_Doc/dut_bug_analysis.md` 执行。

## 技能、规划与检索

| 工具 | 用途 |
| --- | --- |
| `ListSkill` / `RunSkillScript` / `SetSkillUsage` | 列举技能、执行脚本、登记当前阶段技能证据，见[技能](../02_usage/08_skill.md) |
| `CreateToDo` | 新建或覆盖计划，需要 2–20 步 |
| `CompleteToDoSteps` / `UndoToDoSteps` | 按从 1 开始的索引完成或撤销步骤 |
| `ResetToDo` / `GetToDoSummary` / `ToDoState` | 清空计划、读取摘要或状态 |
| `SemanticSearchInGuidDoc` | 对运行指导和项目参考资料进行语义检索 |
| `MemoryPut` / `MemoryGet` | 按 scope 写入或检索记忆 |

ToDo 工具需由对应选项启用。检索和记忆工具依赖嵌入模型，当前 CLI 默认禁用，可用 `--no-embed-tools false` 启用。规划、记忆和技能使用都不能替代 Checker 验收。

## 装配与 MCP 范围

`--mcp-server-no-file-tools` 省略文件操作工具组，仍保留基础 `ReadTextFile`、阶段工具和已注册的扩展工具。因此，这个选项并非禁止所有文件写入：外部客户端和自定义工具都需要各自遵守工作区权限。

默认配置的 `tools.ignore_tools` 包含 `RunBashCommand`、`WorkDiff`、`WorkCommit`。过滤规则由 `tools.ignore_tools` 和 `tools.selected_tools` 共同决定，调整后应以 `tool_list` 及 MCP 工具发现结果确认。CLI 选项见[参数说明](../02_usage/03_option.md)。
