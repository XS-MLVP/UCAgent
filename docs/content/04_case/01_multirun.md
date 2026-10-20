
# 多实例并发执行

同时验证多个 DUT 时，每个实例必须拥有独立的 workspace、状态目录和服务端口。不要让两个 Agent 共享同一个 `.ucagent/`、`unity_test/` 或 MCP 端口，否则历史、产物和工具调用会互相覆盖。

## 1. 选择运行方式

| 方式 | 模型连接 | 适合场景 |
| --- | --- | --- |
| 普通模式并发 | 每个 UCAgent 使用 LangChain 后端 | 本地脚本或 tmux 同时跑多个任务 |
| 命令行后端并发 | 每个实例使用独立 MCP 端口并调用 Code Agent | 需要外部 Agent 的任务 |
| Master | 一个 Master 管理多个子 Agent | 有集中调度、队列和 Web 监控需求 |

多实例只是把任务拆开，不会改变单个任务的阶段和 Checker 语义。

## 2. 普通模式：独立 workspace

为每个 DUT 准备独立目录：

```text
workspaces/
├── adder/
│   └── Adder/          # picker 导出的 DUT 包和 README
└── mux/
    └── Mux/
```

分别启动：

```bash
ucagent workspaces/adder Adder --output unity_test --tui --loop
ucagent workspaces/mux Mux --output unity_test --tui --loop
```

两个进程的 workspace 不同，即使都使用默认输出目录 `unity_test` 也不会冲突。生产脚本应记录每个任务的 PID、日志路径和退出码；不要在循环中删除共享的 `output/`。

源码仓库中也可以使用 Makefile 的 `CWD` 覆盖：

```bash
make test_Adder CWD=output/adder
make test_Mux CWD=output/mux
```

`test_<DUT>` 会在各自的 `CWD` 中运行 `init_<DUT>`，并复制 `examples/<DUT>`。如果源文件来自其他位置，先手动准备 workspace 或修改 `SRC`。

## 3. MCP/Code Agent 并发

每个实例需要：

1. 独立 workspace；
2. 独立 MCP 端口；
3. 独立客户端配置目录（例如 `.iflow/`、`.qwen/`、`.codex/`）；
4. 独立日志和会话。

示例：

```bash
ucagent workspaces/adder Adder \
  --mcp-server-no-file-tools --mcp-server-port 5001 --tui

ucagent workspaces/mux Mux \
  --mcp-server-no-file-tools --mcp-server-port 5002 --tui
```

对应客户端必须分别指向：

```text
http://127.0.0.1:5001/mcp
http://127.0.0.1:5002/mcp
```

不要复制一份包含旧端口的客户端配置后直接复用；启动前检查配置文件和命令预览。客户端超时应覆盖编译和测试可能需要的时间。

## 4. 用 tmux 管理会话

可以把每个实例放到一个 tmux pane：

```bash
tmux new-session -d -s ucagent_multi

tmux send-keys -t ucagent_multi:0.0 \
  'ucagent workspaces/adder Adder --tui --loop' C-m

tmux split-window -h -t ucagent_multi:0.0
tmux send-keys -t ucagent_multi:0.1 \
  'ucagent workspaces/mux Mux --tui --loop' C-m

tmux attach-session -t ucagent_multi
```

不要依赖固定的 `sleep 10` 判断任务是否就绪；用日志、端口检查或 Agent 状态确认。需要停止时先在 pane 中终止对应进程，再关闭 tmux 会话。

## 5. Master 多任务

任务数量较多时，启动一个 Master，让 Launch 页面为每个任务创建独立 workspace，并按 `process`、Docker、Docker Swarm 或 Kubernetes 拉起子 Agent。Master 的 `master_api.max_task_count` 控制同时运行的任务数，超出后进入等待队列。

Master 适合集中查看状态和日志；任务仍应使用独立的输出、端口和客户端配置。详见 [Master 模式](../01_start/04_master_mode.md) 和 [Web Master 使用指南](../02_usage/07_web_master.md)。

## 6. 排障

- **端口冲突**：为每个 MCP Server 指定不同的 `--mcp-server-port`，或使用 `-1` 自动选择端口，并把实际端口写入客户端配置。
- **产物互相覆盖**：检查 workspace、`--output`、`.ucagent/` 和客户端配置目录是否独立。
- **任务停在等待**：查看 Master 的并发上限和 Launch Queue；普通模式则检查进程、日志和模型 API 限流。
- **客户端无法连接**：确认 UCAgent 已启动对应 MCP 参数，客户端使用 `/mcp` 端点，且 host/port 与权限一致。

批处理和 Hook 驱动的无人值守流程见[批处理执行](02_batchrun.md)；不建议从本页复制未经验证的客户端专属脚本。
