
# UCAgent 运行模式总览

先区分执行组织、任务管理、接入界面和后端；它们不是一组互斥的“模式”。具体阶段和验收产物由工作流决定。

| 维度 | 选择 | 含义 |
| --- | --- | --- |
| 执行组织 | `--agent-mode single` / `--agent-mode multi` | 单 Agent 执行，或 Global→Super→Sub 分层协作 |
| 任务管理 | 普通启动 / Master | Master 提供多任务创建、启动与监控面板，不是 multi 的别名 |
| 接入与展示 | Console / TUI / HTTP / MCP | 本地交互、可视化或网络接入；MCP 提供工具协议，不是执行角色 |
| 执行后端 | `--backend` | 选择 LangChain 或命令行后端，不改变 Checker 验收要求 |

- 已知工作区和 DUT，调试单个工作流：从下面的普通模式开始，默认 `single`。
- 需要自然语言编排工作流和委派执行：阅读 [Global Agent](../02_usage/13_global_agent.md) 与 [多 Agent](../02_usage/11_multi_agent.md)。
- 需要浏览器管理多个任务：阅读 [Master 模式](04_master_mode.md)。不能仅因 Master 管理多个任务，就推断子任务使用 multi。

这些维度不代表任意组合都受支持；当前公开 `multi` 入口不能与 Master 组合。

## 普通模式

普通模式下，一个 UCAgent 进程驱动一个验证任务。源码仓库中最简启动方式：

```bash
make test_Adder
```

展开后的完整命令为（`make` 目标会先自动初始化 `output/workspace_Adder` 工作区）：

```bash
python3 ucagent.py output/workspace_Adder/ Adder --config config.yaml -s -hm --tui -l
```

通过 pip 安装时可直接使用原生 CLI：

```bash
ucagent <workspace> <DUT> -s -hm --tui
```

### 后端选择（--backend）

普通模式通过 `--backend=<name>` 选择驱动验证的大模型后端，后端列表定义于 `ucagent/setting.yaml` 的 `backend:` 段，目前内置：

- `langchain`（默认）：UCAgent 进程通过 LangChain 库直连大模型，不依赖外部 code agent，适合探索自定义上下文服务等场景。
- `codex`、`opencode`、`claude`、`copilot`、`qwen`、`iflow`、`kilo`：命令行 Code Agent 后端。UCAgent 启动 MCP Server，渲染对应客户端的配置文件，并调用该客户端；具体配置文件名和命令由 `ucagent/setting.yaml` 的 backend 条目决定。
- 当前不支持的后端，可参照相同格式在 `ucagent/setting.yaml` 中自行添加。

> 上述单任务命令行后端需要 MCP 服务。本页的 UnitTest 示例使用 `--mcp-server`；不要关闭工作流必需的文件工具。配置要求见 [MCP 接入](03_mcp_mode.md)。

例如 README 快速开始同款命令，使用 opencode 后端并立即自动执行：

```bash
make mcp_Adder ARGS="--loop --backend=opencode"
```

展开后的完整命令为：

```bash
python3 ucagent.py output/workspace_Adder/ Adder --config config.yaml -s -hm --tui --mcp-server --loop --backend=opencode
```

在上述交互启动命令中，`--loop`（`-l`）在初始化时提交自动执行循环；省略它且没有其他启动任务命令时，等待手动输入 `loop`。无本地界面的服务启动默认行为见[运行控制](../02_usage/10_runtime_control.md)。

以 opencode 为例的完整步骤（安装、LLM API 配置、启动）见 [MCP 接入](03_mcp_mode.md)；手动启动 MCP Server、再从另一个终端连接的方式也在该章。LangChain 直连的模型配置见[直接使用](../02_usage/01_direct.md)。

### TUI 终端

加 `--tui` 参数（或启动后在 Console 控制台输入 `tui` 命令）进入终端交互界面：左侧任务/阶段/工具面板，右侧消息面板，底部命令输入框，任务命令与 Console 共用，退出和显示操作按当前界面处理。完整上手（含 DUT 准备与模型配置）见[普通模式](02_normal_mode.md)，界面操作见 [TUI](../02_usage/04_tui.md)。

### Web 界面

普通模式不依赖终端也能完成交互，Web 入口有三种：

- **Agent 仪表盘**：启动参数 `--export-cmd-api`，或启动后在 Console/TUI 控制台执行 `cmd_api_start`，浏览器打开 `http://127.0.0.1:8765`。可查看阶段进度、任务与工具状态，切换阶段 HM/Skip 等人工审核开关，管理工作区文件，并通过 Chat 模式直接与所配置的大模型对话。该入口不要求先进入 TUI。
- **`--web-console`**：在浏览器中托管完整的命令行/TUI 会话（默认 `localhost:8000`）。
- **`--web-terminal`**：Web 终端与本地终端并行使用（默认 `127.0.0.1:8818`）。

各参数细节见[参数说明](../02_usage/03_option.md)。

## Master 模式

Master 用于管理多个验证任务；浏览器面板（默认 `http://127.0.0.1:8800`）负责工作区、RTL 编译、任务下发和运行监控。子 Agent 由 Master 按 Launch Mode（`process`、`docker`、`docker_swarm` 或 `k8s`）拉起，并通过 `--master` 回连注册。

源码仓库中启动 Master：

```bash
make as_master_persist
```

展开后的完整命令为：

```bash
python3 ucagent.py --as-master-persist --export-cmd-api --as-master
```

通过 pip 安装时使用原生 CLI：

```bash
ucagent --as-master-persist --as-master
```

说明：

- `--as-master` 才会进入 Master 模式；`--as-master-persist` 仅指定持久化工作区目录（默认 `/tmp/ucagent_master`），必须与 `--as-master` 搭配使用。`make as_master` 使用临时工作区，`make as_master_persist` 才会保留 Master 工作区。
- Launch 的后端、模型配置和控制台命令说明见 [Web Master 使用指南](../02_usage/07_web_master.md)。

上手实操见[Master 模式](04_master_mode.md)，功能详解见[Web Master 使用指南](../02_usage/07_web_master.md)。
