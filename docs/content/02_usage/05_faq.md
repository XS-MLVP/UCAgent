
# FAQ

## 模型和配置

### 如何切换模型？

可用环境变量临时切换：

```bash
export OPENAI_MODEL="<model_name>"
export OPENAI_API_KEY="<api_key>"
export OPENAI_API_BASE="https://<provider>/v1"
```

也可以在项目 `config.yaml` 中修改 `openai.model_name` 等字段，或用 `--config <path>` 指定另一份配置。配置优先级见[工作流配置](../03_develop/03_workflow.md#3-配置加载和模板变量)；模型环境变量见[参数说明](./03_option.md)。

### `--no-embed-tools` 应该怎么用？

当前 CLI 默认已经禁用嵌入/检索工具。裸写 `--no-embed-tools` 或传 `true` 都是禁用；需要开启时使用：

```bash
--no-embed-tools false
```

嵌入工具不是普通文件工具或测试工具的前置条件。

## 运行和恢复

### UCAgent 中途退出，如何恢复？

先确认旧的 UCAgent 和外部 Code Agent 都已退出，再用相同 workspace、DUT 和配置重新启动。输入 `status` 确认阶段后，再输入 `loop` 或让外部 Agent 继续。除非明确要重新开始，不要删除 `.ucagent/` 或输出产物。

### Check 失败怎么办？

先读取 Checker 返回的 `artifact`、`location`、`observed`、`expected` 和 `next_action`。必要时使用：

```text
tool_invoke StdCheck lines=-1
tool_invoke KillCheck
```

修复后重新运行测试、`Check` 和 `Complete`。测试基础设施失败应先修复到 Pass；可复现且断言正确的 DUT 失败才记录为 Bug。

### 为什么启动时找不到 `config.yaml`？

`config.yaml` 是项目配置文件，不是 pip 安装必然提供的文件。可以：

- 在工作区创建自己的 `config.yaml`，再传 `--config config.yaml`；
- 使用源码仓库中的配置和 Makefile；
- 不传 `--config`，使用分层默认配置。

### `--no-write` 为什么不生效？

目标必须位于 workspace 内。普通文件或目录需要已经存在；通配符路径可以匹配尚未创建的目标。该选项限制 UCAgent 工具写入，不会阻止你在外部 shell 中手动修改文件。

## 工具和术语

### 如何选择文本文件工具？

当前文本文件工具使用：

- `EditTextFile`：创建、覆盖或追加完整文本文件；
- `ReplaceStringInFile`：替换已有文件中唯一的一段文本；
- `DeleteTextLines`：一次删除多个完整行块。

先用 `ReadTextFile` 获取当前内容；需要并发保护时传 `expected_sha256`。

### 如何区分 CK、TC 和 Bug？

CK 表示功能检测点，TC 表示测试用例。动态 Bug 条目应同时关联准确的 FG/FC/CK 和失败 TC；测试基础设施失败不应记录为 DUT Bug。

### MCP 连接失败怎么排查？

确认：

1. UCAgent 使用了 `--mcp-server` 或 `--mcp-server-no-file-tools`；
2. 客户端地址是 `http://<host>:<port>/mcp`；
3. 客户端端口和 `--mcp-server-port` 一致；
4. 远程场景的 `--mcp-server-host`、防火墙和权限允许连接。

命令行后端还必须启用 MCP 参数，否则 CLI 会拒绝启动。


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
