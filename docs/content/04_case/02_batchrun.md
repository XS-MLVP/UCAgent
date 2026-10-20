
# 批处理执行

批处理的核心是让一个任务完成后退出，再启动下一个任务；MCP 场景还可以使用 Code Agent 的 Stop hook 自动发送继续或退出提示。每个任务必须使用独立 workspace，避免历史和产物混淆。

## 1. 自动退出

启动 UCAgent 时加入：

```bash
--exit-on-completion
# 简写
-eoc
```

它只在 Agent 成功调用 `Exit` 且所有阶段完成后退出。它不会把 Checker 失败、进程崩溃或网络断开当作成功；批处理脚本必须检查退出码和真实产物。

普通模式的最小串行示例：

```bash
set -e
ucagent workspaces/adder Adder --tui --loop --exit-on-completion
ucagent workspaces/mux Mux --tui --loop --exit-on-completion
```

用不同 workspace 运行；不要在循环中 `rm -rf output` 清理仍在使用的目录。需要重新开始时，显式为当前任务选择新的 workspace 或按项目约定清理其专属目录。

## 2. 源码仓库示例

仓库提供了可直接阅读和修改的 [examples/BatchRun/README.md](https://github.com/XS-MLVP/UCAgent/blob/main/examples/BatchRun/README.md) 和 [Makefile](https://github.com/XS-MLVP/UCAgent/blob/main/examples/BatchRun/Makefile)。它们包含：

- `api_batch`：依次运行 Adder、Mux、FSM，并在每个任务完成后复制结果；
- `mcp_batch`：为每个 MCP 任务分配端口，再依次调度；
- `iflow_batch_auto_tmux`：用 tmux 同时驱动 UCAgent MCP 进程和 iFlow 客户端。

示例中的 `exited.txt` 是 Makefile 自己写入的完成标记，不是 UCAgent 的通用状态文件。生产脚本应优先检查进程退出码、`.ucagent/ucagent_info.json` 和测试报告。

## 3. MCP + Hook

MCP 批处理通常有两个终端：

1. UCAgent 启动 `--mcp-server-no-file-tools` 和 `--exit-on-completion`；
2. Code Agent 连接 `/mcp`，在每轮停止时通过 hook 获取下一条提示并发送到客户端。

UCAgent 提供：

```bash
ucagent --hook-message 'continue|quit'
```

`--hook-message` 的格式是 `[config_file.yaml::]continue_key[|stop_key]`：

- 不带文件时，从当前分层配置的 `hooks` 读取；
- `continue` 和 `quit` 是内置配置中的默认键；
- 也可以写 `config.yaml::my_continue|my_stop` 读取自定义 YAML 键；
- 命令只输出提示词，不会发送消息或操作 tmux。

在 shell hook 中应正确引用包含空格的提示词，并显式指定目标 tmux pane。不同 Code Agent 的 hook schema 和 timeout 单位不同，请以客户端文档为准。

Claude Code 的 MCP 添加命令示例：

```bash
claude mcp add --transport http unitytest http://127.0.0.1:5000/mcp
```

iFlow、Claude Code、Gemini CLI 等客户端的完整 hook 配置请参考各自文档和仓库中的 BatchRun 示例，不要把一个客户端的 JSON 直接用于另一个客户端。

## 4. 可靠的批处理检查

每个任务至少记录：

- workspace、DUT、配置文件和 MCP 端口；
- 启动命令、开始/结束时间和退出码；
- `.ucagent/` 状态、测试报告和主要阶段结果；
- 失败任务的日志和下一步动作。

批处理脚本遇到失败时应停止或进入明确的失败队列，不要继续复制半成品覆盖成功结果。重试前先判断是模型/API、测试基础设施、配置还是 DUT 缺陷。

## 5. 排障

- **任务没有自动退出**：确认阶段全部通过、Agent 调用了 `Exit`，并传入了 `--exit-on-completion`。
- **Hook 没有触发**：先单独运行 `ucagent --hook-message 'continue|quit'` 检查输出，再检查客户端 hook 命令、tmux pane 和权限。
- **MCP 连接失败**：核对 `--mcp-server-port`、客户端 `/mcp` 地址、host、防火墙和客户端超时。
- **重复执行覆盖结果**：给每次任务分配独立 workspace 或带时间戳的结果目录；不要把旧的 `output/` 当成全局临时目录。

先跑通单个任务，再把同一命令放进批处理；需要并行而非串行时，参见[多实例并发执行](01_multirun.md)。
