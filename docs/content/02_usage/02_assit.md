
# 人机协同验证

UCAgent 允许在阶段执行、测试或 Checker 失败时暂停，人工修复文件或环境，再让 Agent 继续。普通模式和 MCP 模式使用同一套 PDB 命令；Master 模式把常用操作放到 Web 页面。

## 1. 什么时候介入

适合人工介入的情况包括：

- 规格、功能点或测试计划需要人工确认；
- 测试环境、依赖或仿真器配置需要修改；
- Checker 失败信息已经明确，但模型没有修好；
- 检查进程超时，需要查看日志并终止后重试。

测试失败本身不等于 DUT 缺陷。先确认 fixture、参考模型、API、复位/时序和断言没有问题，再决定是否记录 Bug。

## 2. 暂停和查看状态

使用 LangChain 直连时可按 `Ctrl+C` 暂停；外部 Code Agent 的暂停按其客户端操作执行。回到 UCAgent 控制台后常用命令是：

```text
status
current_tips
task_detail
changed_files
```

`status` 显示阶段进度，`current_tips` 显示当前阶段任务和 Checker 要求，`task_detail` 查看阶段详情，`changed_files` 查看近期修改。

## 3. 检查、修复和继续

1. 阅读 `Check` 返回的 artifact、location、expected 和 next_action。
2. 手动编辑文件或修复环境，必要时运行单个 pytest 用例。
3. 重新检查：

```text
tool_invoke Check
```

4. 检查通过后记录本阶段工作，再推进：

```text
tool_invoke SetCurrentStageJournal journal='已修复 fixture，相关测试和 Check 均通过'
tool_invoke Complete
```

`Complete` 要求当前阶段已有日志；如果提示参考文件未读，先用 `ReadTextFile` 读取列出的文件。需要人工审核时，按下节确认后再次调用 `Complete`。

5. 继续 Agent 循环：

```text
loop
loop 已修复 fixture，请重新运行失败用例并完成当前阶段
```

如果 `Check` 长时间没有输出：

```text
tool_invoke StdCheck lines=-1
tool_invoke KillCheck
tool_invoke Check
```

`StdCheck` 和 `KillCheck` 只针对正在运行的检查进程；先查看输出，再决定是否终止。

## 4. 强制人工审核

可以让某个阶段在 Checker 通过后等待人工确认：

```text
hmcheck_set 2 true
hmcheck_set all true
hmcheck_set 2 false
hmcheck_cstat
hmcheck_list
```

阶段索引是当前运行时的展平索引，不能直接套用另一份配置的编号。以 `status` 或 `hmcheck_list` 显示的索引为准。

暂停后确认产物和测试结果，审核通过或拒绝：

```text
hmcheck_pass 已检查规格和测试覆盖
hmcheck_fail 需要补充边界用例
```

也可以一步通过审核并继续：

```text
hmcheck_pass_and_continue 已确认
```

HM 是人工审核开关。Web 页面上的 LFail/LPass 是 LLM 失败建议和通过评审开关，和 `hmcheck_pass`/`hmcheck_fail` 的人工确认不是同一功能。

## 5. 权限和阶段控制

查看或调整 Agent 可写路径：

```text
list_rw_paths
add_write_path unity_test/
add_un_write_path Adder/
del_write_path unity_test/
del_un_write_path Adder/
```

工作流阶段控制：

```text
skip_stage 3
unskip_stage 3
tool_invoke GoToStage 2
```

`skip_stage`、`unskip_stage` 和 `GoToStage` 都使用阶段索引；`GoToStage` 只能回到已经到达的阶段。命令行启动时也可以用 `--skip`、`--unskip` 和 `--force-stage-index`，详见[参数说明](./03_option.md)。

## 6. 常用命令表

| 命令 | 作用 | 示例 |
| --- | --- | --- |
| `status` | 查看整体状态 | `status` |
| `task_detail` | 查看阶段详情 | `task_detail 2` |
| `current_tips` | 获取当前阶段指导 | `current_tips` |
| `tool_list` | 列出可用工具 | `tool_list` |
| `tool_invoke` | 在 PDB 中调用工具 | `tool_invoke RunTestCases target='',timeout=120` |
| `hmcheck_set` | 设置人工审核 | `hmcheck_set 2 true` |
| `hmcheck_pass` / `hmcheck_fail` | 通过或拒绝人工审核 | `hmcheck_pass 已确认` |
| `skip_stage` / `unskip_stage` | 跳过或恢复阶段 | `skip_stage 3` |
| `loop` | 继续模型循环 | `loop` |
| `help` | 查看当前版本命令 | `help` |
| `quit` | 退出进程 | `quit` |

在 TUI 中输入 `q`、`exit` 或 `quit` 会先返回 PDB 控制台，需再次输入 `quit` 才结束进程。

`tool_invoke` 的参数格式是：

```text
tool_invoke <tool_name> [arg1,arg2,key=value,...]
```

参数用逗号分隔，字符串使用 Python 引号，布尔值使用 `True/False`。`RunTestCases.target` 相对于当前测试目录（默认 `unity_test/tests/`），不要重复添加该目录前缀。例如：

```text
tool_invoke RunTestCases target='test_adder.py::test_add',timeout=120
```

## 7. Master 页面

Master 的 Dashboard、Task 和 Agent 页面可以查看日志、阶段文件和 Diff，并批量设置 HM、Skip、LFail、LPass。页面操作和本地命令作用相近，但入口和权限由 Master 配置决定；详细说明见 [Web Master 使用指南](./07_web_master.md)。

Web Terminal 是否同时保留本地终端，取决于子 Agent 使用的是 `--web-console` 还是 `--web-terminal`，两者区别见[参数说明](./03_option.md)。

## 8. 恢复原则

UCAgent 会在工作区保存阶段历史。进程退出后，确保旧的 UCAgent 和 Code Agent 已停止，再用相同 workspace、DUT 和配置重新启动。启动后先执行 `status`，确认当前阶段和历史，再输入 `loop` 或让外部 Agent 继续。不要为了“恢复”直接删除 `.ucagent/`、测试报告或工作流产物。
