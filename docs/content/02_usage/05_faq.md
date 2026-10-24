
# FAQ

## FAQ

- 模型切换：在 `config.yaml` 改 `openai.model_name`
- 验证过程中出现错误怎么办：使用 `Ctrl+C` 进入交互模式，通过 `status` 查看当前状态，使用 `help` 获取调试命令。
- Check 失败：先 `ReadTextFile` 阅读 reference_files；再按返回信息修复，循环 RunTestCases → Check
- 自定义阶段：修改 `ucagent/lang/zh/config/default.yaml` 的 `stage`；或用 `--override` 临时覆盖
- 添加工具：`ucagent/tools/` 下新建类，继承 `UCTool`，运行时 `--ex-tools YourTool`
- MCP 连接失败：检查端口/防火墙，改 `--mcp-server-port`；无嵌入可加 `--no-embed-tools`
- 只读保护：通过 `--no-write/--nw` 指定路径限制写入（必须位于 workspace 内）

### UCAgent 闪退，如何恢复验证流程？

- 确保 UCAgent 和目前正在使用的 Code Agent(如 Qwen Code Cli)都已经退出，若没有则手动退出
- 重新启动 UCAgent，它会自动继续之前的工作流
- 重新启动 Code Agent 并输入“继续”即可恢复之前的验证流程

### 为什么快速启动找不到 config.yaml/定制流程时找不到 config.yaml?

- 使用 pip 安装后并没有`config.yaml`那个文件，所以在快速启动的[启动 MCP 服务](../01_start/03_mcp_mode.md#45-启动-mcp-服务终端-a)没有加`--config config.yaml`这个选项。
- 可以通过在工作目录添加`config.yaml`文件并且加上`--config config.yaml`参数来启动；也可以使用克隆仓库来使用 UCAgent 的方式来解决。

### 运行中如何调整消息窗口与 token 上限？

- 在 TUI 输入 `messages_config` 查看当前配置；
- 使用 `messages_config max_tokens 131072` 调整预估 token 触发值；
- 使用 `messages_config max_keep_msgs 200` 调整独立的消息数触发值；
- 两项中的任意一项超限都会压缩。只提高 `max_tokens` 不会关闭消息数限制；可将对应限制设为 `0` 来禁用该触发条件。

### 文档中的 “CK bug” 要改吗？

- 是。术语统一为 “TC bug”。同时确保 bug 文档里的 `<TC-*>` 能匹配失败用例（文件/类/用例名）。

### 为什么找不到 WriteTextFile 工具？

- 该工具已移除。创建或覆盖文本文件请调用 `EditTextFile(path, content)`；只有追加内容时才传 `append=true`。对已有文件做少量局部修改时使用 `ReplaceStringInFile(path, old_string, new_string)`；需要限定搜索范围时可加 `line_blocks=[[start, end], ...]`，默认搜索全文。只有大量修改需要先删除多个完整行块时，才先用 `DeleteTextLines(path, line_blocks, expected_sha256)`批量删除，重新读取文件后再用 `ReplaceStringInFile`完成精确编辑。


## LangChain 模型流中断后如何恢复？

LangChain 主模型调用和上下文摘要对读取超时、网络错误、远端协议断流最多额外重试两次，退避为 1 秒、2 秒；鉴权和配置错误不重试，耗尽次数后保留原异常。主模型重试位于 model middleware 内，不重新执行整个 Agent 图或已完成工具。未完成的流式回复只可能出现在控制台预览，不提交为可执行工具调用；重试日志会注明丢弃了不完整回复。停止主模型时会取消重试退避，异步任务取消正常传播。摘要调用采用同样的次数上限，原有上下文仅在完整摘要返回后更新。

这是 UCAgent 层的额外重试上限，模型 SDK 自身的重试配置仍独立存在。持续超时应检查上游／网关的连接、首响应、空闲和总时长限制，不能靠无限重试解决。

### Pytest environment and idle autonomous rounds

Test tools run `sys.executable -m pytest`, using the Agent's Python interpreter,
so a different `pytest` on `PATH` cannot silently select another virtual environment.
Install test plugins such as `pytest-forked` in that interpreter. Keep required
isolation options enabled when repairing an environment failure.

`loop_settings.max_no_tool_rounds` defaults to `3`: autonomous execution pauses
when that many consecutive completed model rounds invoke no tools. A tool call
resets the counter; `0` disables this guard. This is independent of repeated
Checker diagnostics. A model saying that it is waiting does not itself pause
execution. An incomplete paused workflow remains incomplete in managed runs.

`loop_settings.max_tool_error_rounds` also defaults to `3`. It bounds consecutive
model turns spent repairing invalid tool invocations inside one conversation
round, including consecutive wholly failed tool batches inside the LangChain
graph; `0` disables this guard.

内部上下文摘要使用非流式请求：摘要只在完整响应后参与后续分析，避免额外 SSE 连接中断导致任务退出。主分析输出方式不受影响；摘要请求仍保留传输重试和超时，服务不可用时仍会明确失败。

`RunSkillScript` 执行 Python 脚本时使用 Agent 自身的 `sys.executable`，与运行中的二进制扩展依赖保持同一 Python ABI，不再从 PATH 选择另一个 `python3`。
