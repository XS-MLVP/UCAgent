
# UCAgent 运行模式总览

普通模式执行单个任务，Master 模式管理多个任务。两者使用同一套阶段与 Checker 机制；具体流程和产物由所选工作流决定。

|  | 普通模式 | Master 模式 |
| --- | --- | --- |
| 定位 | 单个 Agent 进程完成一个验证任务 | 多任务管理进程 |
| 执行方式 | 当前 Agent 执行验证任务 | 创建、启动并监控多个子 Agent |
| 交互载体 | 终端（PDB/TUI），也可开启普通 Agent 的 Web 入口 | 浏览器 Web 面板（默认 `http://127.0.0.1:8800`） |
| 适用场景 | 单模块验证、本地调试 | 多任务并行、集中调度、团队协作 |

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

> 注意：上面列出的命令行 Code Agent 后端必须搭配 `--mcp-server-no-file-tools` 或 `--mcp-server` 启动（UCAgent 由此对外提供 MCP 服务），否则 CLI 会直接报错拒绝启动。

例如 README 快速开始同款命令，使用 opencode 后端并立即自动执行：

```bash
make mcp_Adder ARGS="--loop --backend=opencode"
```

展开后的完整命令为：

```bash
python3 ucagent.py output/workspace_Adder/ Adder --config config.yaml -s -hm --tui --mcp-server-no-file-tools --loop --backend=opencode
```

`--loop`（`-l`）使 Agent 启动后立即进入自动执行循环；不加该参数时，Agent 停在交互控制台，等待手动输入 `loop` 后才开始执行。

以 opencode 为例的完整步骤（安装、LLM API 配置、启动）见 [MCP 接入](03_mcp_mode.md)；手动启动 MCP Server、再从另一个终端连接的方式也在该章。LangChain 直连的模型配置见[直接使用](../02_usage/01_direct.md)。

### TUI 终端

加 `--tui` 参数（或启动后在 PDB 控制台输入 `tui` 命令）进入终端交互界面：左侧任务/阶段/工具面板，右侧消息面板，底部命令输入框，全部 PDB 命令均可直接输入。完整上手（含 DUT 准备与模型配置）见[普通模式](02_normal_mode.md)，界面操作见 [TUI](../02_usage/04_tui.md)。

### Web 界面

普通模式不依赖终端也能完成交互，Web 入口有三种：

- **Agent 仪表盘**：启动参数 `--export-cmd-api`，或启动后在 PDB/TUI 控制台执行 `cmd_api_start`，浏览器打开 `http://127.0.0.1:8765`。可查看阶段进度、任务与工具状态，切换阶段 HM/Skip 等人工审核开关，管理工作区文件，并通过 Chat 模式直接与所配置的大模型对话。该入口不要求先进入 TUI。
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
