# 工具列表

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

  - 用途：编辑/创建文本文件，模式：replace/overwrite/append。
  - 参数：
    - path: str — 文件路径（相对 workspace，不存在则创建）
    - data: str — 写入的文本（None 表示清空）
    - mode: str — 编辑模式（replace/overwrite/append，默认 replace）
    - start: int — replace 模式的起始行（1-based）
    - count: int — replace 模式替换行数（-1 到末尾，0 插入）
    - preserve_indent: bool — replace 时是否保留缩进

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

- ReplaceStringInFile（ReplaceStringInFile）

  - 用途：精确字符串替换（强约束匹配；可新建文件）。
  - 参数：
    - path: str — 目标文件
    - old_string: str — 需要被替换的完整原文（含上下文，精确匹配）
    - new_string: str — 新内容

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
