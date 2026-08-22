# 工具列表

> 💡 **自定义工具**：关于如何开发自定义工具，请参考 [定制工具](05_customize.md)

以下为当前仓库内内置工具（UCTool 家族）的概览，按功能类别归纳：名称（调用名）、用途与参数说明（字段: 类型 — 含义）。

提示：

- 带有“文件写”能力的工具仅在本地/允许写模式下可用；MCP 无文件工具模式不会暴露写类工具。
- 各工具均基于 args_schema 校验参数，MCP 客户端将根据 schema 生成参数表单。

## 基础/信息类

- RoleInfo（RoleInfo）
  - 用途：返回当前代理的角色信息（可在启动时自定义 role_info）。
  - 参数：无

- HumanHelp（HumanHelp）
  - 用途：向人类请求帮助（仅在确实卡住时使用）。
  - 参数：
    - message: str — 求助信息

## 规划/ToDo 类

- CreateToDo
  - 用途：创建 ToDo（覆盖旧 ToDo）。
  - 参数：
    - task_description: str — 任务描述
    - steps: List[str] — 步骤（1–20 步）
- CompleteToDoSteps
  - 用途：将指定步骤标记为完成，可附加备注。
  - 参数：
    - completed_steps: List[int] — 完成的步骤序号（1-based）
    - notes: str — 备注
- UndoToDoSteps
  - 用途：撤销步骤完成状态，可附加备注。
  - 参数：
    - steps: List[int] — 撤销的步骤序号（1-based）
    - notes: str — 备注
- ResetToDo
  - 用途：重置/清空当前 ToDo。
  - 参数：无
- GetToDoSummary / ToDoState
  - 用途：获取 ToDo 摘要 / 看板状态短语。
  - 参数：无

## 记忆/检索类

- SemanticSearchInGuidDoc（SemanticSearchInGuidDoc）
  - 用途：在 Guide_Doc/项目文档中做语义检索，返回最相关片段。
  - 参数：
    - query: str — 查询语句
    - limit: int — 返回条数（1–100，默认 3）

- MemoryPut
  - 用途：按 scope 写入长时记忆。
  - 参数：
    - scope: str — 命名空间/范围（如 general/task-specific）
    - data: str — 内容（可为 JSON 文本）
- MemoryGet
  - 用途：按 scope 检索记忆。
  - 参数：
    - scope: str — 命名空间/范围
    - query: str — 查询语句
    - limit: int — 返回条数（1–100，默认 3）

## 测试/执行类

- RunPyTest（RunPyTest）
  - 用途：在指定目录/文件下运行 pytest，支持返回 stdout/stderr。
  - 参数：
    - test_dir_or_file: str — 测试目录或文件
    - pytest_ex_args: str — 额外 pytest 参数（如 "-v -\-capture=no"）
    - return_stdout: bool — 是否返回标准输出
    - return_stderr: bool — 是否返回标准错误
    - timeout: int — 超时秒数（默认 15）

- RunUnityChipTest（RunUnityChipTest）
  - 用途：面向 UnityChip 项目封装的测试执行，产生 toffee_report.json 等结果。
  - 参数：同 RunPyTest；另含内部字段（workspace/result_dir/result_json_path）。

## 文件/路径/文本类

- SearchText（SearchText）
  - 用途：在工作区内按文本搜索，支持通配与正则。
  - 参数：
    - pattern: str — 搜索模式（明文/通配/正则）
    - directory: str — 相对目录（为空则全仓；填文件则仅搜该文件）
    - max_match_lines: int — 每个文件返回的最大匹配行数（默认 20）
    - max_match_files: int — 返回的最大文件数（默认 10）
    - use_regex: bool — 是否使用正则
    - case_sensitive: bool — 区分大小写
    - include_line_numbers: bool — 返回是否带行号
    - context_before: int — 每个命中前返回的上下文行数（0–20，默认 1）
    - context_after: int — 每个命中后返回的上下文行数（0–20，默认 1）
  - 返回：每个命中文件仅显示一次文件名，其后为带原始行号的代码块；重叠的上下文会自动合并，不连续的片段以 `...` 分隔。

- FindFiles（FindFiles）
  - 用途：按通配符查找文件。
  - 参数：
    - pattern: str — 文件名模式（fnmatch 通配）
    - directory: str — 相对目录（为空则全仓）
    - max_match_files: int — 返回最大文件数（默认 10）

- PathList（PathList）
  - 用途：列出目录结构（可限制深度）。
  - 参数：
    - path: str — 目录（相对 workspace）
    - depth: int — 深度（-1 全部，0 当前）

- ReadBinFile（ReadBinFile）
  - 用途：读取二进制文件（返回 [BIN_DATA]）。
  - 参数：
    - path: str — 文件路径（相对 workspace）
    - start: int — 起始字节（默认 0）
    - end: int — 结束字节（默认 -1 表示 EOF）

- ReadTextFile（ReadTextFile）
  - 用途：读取文本文件（带行号，返回 [TXT_DATA]）。
  - 参数：
    - path: str — 文件路径（相对 workspace）
    - start: int — 起始行（1-based，默认 1）
    - count: int — 行数（-1 到文件末尾）

- EditTextFile（EditTextFile）
  - 用途：创建或覆盖完整文本文件；也可显式选择追加。
  - 参数：
    - path: str — 文件路径（相对 workspace，必填）
    - content: str — 完整文件内容（必填；空字符串表示创建或清空空文件）
    - append: bool — 是否追加；默认 false，即创建或覆盖完整文件
    - expected_sha256: str — 可选的读取时 SHA-256，用于避免覆盖并发修改

- DeleteTextLines（DeleteTextLines）
  - 用途：仅在大量文本修改时，从已有 UTF-8 文件中一次删除多个完整物理行或闭区间行块。少量局部修改直接使用 `ReplaceStringInFile`。推荐流程是先用 `ReadTextFile`确认行号和 SHA-256，调用本工具删除全部旧行块，重新读取缩短后的文件，再用 `ReplaceStringInFile`完成精确编辑或插入。
  - 参数：
    - path: str — 已有文本文件路径（相对 workspace，必填）
    - line_blocks: list[int | [int, int]] — 1-based 单行或闭区间，例如 `[1, 4, 5, [10, 20], [40, 55]]`；区间必须嵌套在外层列表中，单独删除第 10 至 20 行应传 `[[10, 20]]`，而 `[10, 20]` 表示删除两个单行；所有项都引用删除前同一文件快照中的原始行号，不会逐项重新编号；重叠和相邻区间会合并
    - expected_sha256: str — 可选但建议提供的读取时 SHA-256；文件已变化时整次拒绝
  - 约束：全部行块会在写入前校验；任何反向或越界区间都会取消整个操作，不会部分删除，也不会删除文件本身。

- ReplaceStringInFile（ReplaceStringInFile）
  - 用途：在已有文本文件的指定行块中精确替换唯一的一处非空文本；未指定行块时搜索全文。
  - 参数：
    - path: str — 已有文件路径（相对 workspace，必填）
    - old_string: str — 唯一匹配的非空原文本（必填）
    - new_string: str — 替换后的文本（必填；空字符串表示删除匹配内容）
    - line_blocks: list[[int, int]] — 可选的 1-based 闭区间搜索块，例如 `[[10, 20], [40, 50]]`；默认全文
    - expected_sha256: str — 可选的读取时 SHA-256
    - dry_run: bool — 仅校验并返回差异，不写入文件
  - 约束：重叠或相邻块会先合并；匹配必须完整位于一个合并后的块中，并且在全部指定块中合计只出现一次。

- CopyFile（CopyFile）
  - 用途：复制文件；可选覆盖。
  - 参数：
    - source_path: str — 源文件
    - dest_path: str — 目标文件
    - overwrite: bool — 目标存在时是否覆盖

- MoveFile（MoveFile）
  - 用途：移动/重命名文件；可选覆盖。
  - 参数：
    - source_path: str — 源文件
    - dest_path: str — 目标文件
    - overwrite: bool — 目标存在时是否覆盖

- DeleteFile（DeleteFile）
  - 用途：删除文件。
  - 参数：
    - path: str — 文件路径

- CreateDirectory（CreateDirectory）
  - 用途：创建目录（递归）。
  - 参数：
    - path: str — 目录路径
    - parents: bool — 递归创建父目录
    - exist_ok: bool — 已存在是否忽略

- GetFileInfo（GetFileInfo）
  - 用途：获取文件信息（大小、修改时间、人类可读尺寸等）。
  - 参数：
    - path: str — 文件路径

## 扩展示例

- SimpleReflectionTool（SimpleReflectionTool）
  - 用途：示例型“自我反思”工具（来自 extool.py），可作为扩展参考。
  - 参数：
    - message: str — 自我反思文本

备注：

- 工具调用超时默认 20s（具体工具可重写）；长任务请周期性输出进度避免超时。
- MCP 无文件工具模式下默认不暴露写类工具；如需写入，建议在本地 Agent 模式或按需限制可写目录。

## 相关文档

- [定制工具](05_customize.md) - 学习如何开发自定义工具
- [工作流配置](03_workflow.md) - 了解如何在工作流中注册和使用工具
- [架构与工作原理](02_architecture.md) - 理解工具在 UCAgent 中的角色
- [Quick Start](01_quick_start.md) - 快速创建包含自定义工具的工作流
