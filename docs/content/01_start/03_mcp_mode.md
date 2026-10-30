
# MCP 接入

MCP 接入有两种用法：

1. **命令行后端（推荐）**：用 `--backend=opencode`、`--backend=codex` 等启动 UCAgent。UCAgent 启动 MCP Server、渲染客户端配置并调用外部 Code Agent，通常只需一个终端。
2. **手动双终端**：只启动 UCAgent MCP Server，再在另一个终端手动启动 MCP 客户端，适合调试连接和交互流程。

普通模式的 LangChain 后端不需要 MCP。MCP Server 默认端点为 `http://127.0.0.1:5000/mcp`；需要共享文件操作时使用 `--mcp-server`，外部 Code Agent 自带编辑能力时，通常使用 `--mcp-server-no-file-tools`，省略 MCP 文件操作工具组。基础 `ReadTextFile` 仍会保留，用于登记阶段参考文件的阅读。

## 3.1 前置准备

先完成[前置依赖安装](00_installation.md)，再从下面两种接入方式中选择一种；同一工作区只启动一个 UCAgent 进程。

源码仓库中可先准备 DUT，以下命令只初始化工作区：

```bash
make init_Adder
```

它复制 `examples/Adder`、运行 picker，并把 DUT 放入 `output/workspace_Adder/`。后面的 `make mcp_Adder` 也会自动执行这一步。

直接使用 `ucagent` 时，需要先准备好 `workspace/<DUT>`，步骤见[普通模式](02_normal_mode.md)。

## 3.2 使用命令行后端

以 opencode 为例安装客户端（版本可按项目验证结果调整）：

```bash
curl -fsSL https://opencode.ai/install | bash -s -- --version 1.19.3
```

配置客户端使用的 OpenAI 兼容 API：

```bash
export OPENAI_MODEL="<model_name>"
export OPENAI_API_KEY="<api_key>"
export OPENAI_API_BASE="https://<provider>/v1"
```

在源码仓库中启动：

```bash
make mcp_Adder ARGS="--loop --backend=opencode"
```

等价的展开命令是：

```bash
python3 ucagent.py output/workspace_Adder/ Adder \
  --config config.yaml -s -hm --tui \
  --mcp-server-no-file-tools --loop --backend=opencode
```

使用 pip 安装时：

```bash
ucagent output/ Adder -s -hm --tui \
  --mcp-server-no-file-tools --loop --backend=opencode
```

命令行后端必须同时启用 `--mcp-server` 或 `--mcp-server-no-file-tools`，否则 CLI 会拒绝启动。其他后端名称和客户端命令见 `ucagent/setting.yaml` 的 `backend` 配置。

## 3.3 手动双终端接入（以 Codex 为例）

终端 A 选择 `codex` 后端并启动 MCP Server，不使用 `--loop`：

```bash
make mcp_Adder ARGS="--backend=codex"
# 或使用已手动准备的 output/Adder/：
ucagent output/ Adder -s -hm --tui \
  --mcp-server-no-file-tools --backend=codex
```

不进入 `loop` 时，UCAgent 等待终端 B 的客户端调用工具。Codex 的登录和模型配置需在终端 B 完成，见其客户端文档。

终端 A 默认监听 `127.0.0.1:5000`。如果端口已占用，传入 `--mcp-server-port <port>`，并在客户端配置中使用同一个端口。

终端 B 配置 Codex。手动接入时，编辑 `~/.codex/config.toml`：

```toml
[mcp_servers.ucagent]
url = "http://127.0.0.1:5000/mcp"
tool_timeout_sec = 600
```

Codex 使用 `url` 配置 streamable HTTP MCP；不需要另写 `transport = "http"`。UCAgent 的测试和编译工具可能运行较久，客户端超时应设置得足够大。

在终端 B 先切换到本次任务的工作区，再启动客户端。例如，终端 A 使用 `make mcp_Adder` 时，终端 B 执行：

```bash
cd output/workspace_Adder
codex
```

直接 CLI 示例的工作区则是 `output/`。客户端启动后，先让它读取角色和任务信息，再执行当前阶段。例如：

```text
请通过工具 RoleInfo 获取角色信息，然后读取当前任务所需文件并完成验证。使用 UCAgent 的 ReadTextFile 读取阶段 reference_files，以登记阅读记录；所有文件操作必须留在当前工作区内。
```

如果 Code Agent 暂停，先在终端 A 查看 `status`、`current_tips`，修复问题后在客户端输入继续提示。MCP 客户端的配置格式各不相同，请以客户端文档为准，只需把地址指向 `/mcp` 端点。

## 3.4 端口、权限与安全

- `--mcp-server-no-file-tools` 省略文件操作工具组，仍保留基础 `ReadTextFile`、阶段和已注册的扩展工具。客户端可以用自身工具编辑工作区。
- `--mcp-server` 额外暴露文件操作工具组。`--no-write` 限制 UCAgent 工具的写入；客户端自身的文件工具需单独配置权限。
- 远程访问时显式设置 `--mcp-server-host`，同时在网络层限制来源；默认 `127.0.0.1` 只允许本机连接。
- 端点地址、端口和客户端超时必须一致；连接失败时先检查 UCAgent 日志和端口占用，再检查客户端配置。

## 3.5 停止与重新启动服务

在 PDB 或 TUI 控制台使用 `stop_mcp_server` 停止 MCP，使用 `mcp_server_status` 查询状态，再通过 `start_mcp_server [host] [port]` 重新启动。停止时会主动结束本服务的空闲 SSE 通知连接，其他 MCP 实例的连接不受影响；正在执行的工具请求仍按 HTTP 优雅关闭时限等待完成。该时限为 60 秒，超过时限的请求仍会被取消并记录超时错误。

停止命令默认等待后台线程 5 秒。线程尚未退出时，命令明确返回 `still shutting down` 并保留服务状态，此时不能启动替代实例；等待当前调用结束后，再查询状态或重试 `stop_mcp_server`。只有线程实际退出才报告停止成功。启动超时后仍在清理的服务也保留相同的查询与停止入口。

`cmd_api_start` 启动独立的 CMD API，不会停止 MCP；MCP、CMD 和 Master API 的启动不会重置进程共享的 Uvicorn 日志级别或处理器。退出 TUI 会返回 PDB，服务是否运行应以状态命令为准。
