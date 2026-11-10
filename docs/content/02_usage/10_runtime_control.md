# Console、TUI 与 HTTP 运行控制

一个 UCAgent 进程管理一个 Agent 实例。Console 是普通终端命令行，TUI 是可视化终端界面，HTTP 提供网页和控制 API；它们可以操作同一个实例。任务和服务由运行层管理，打开 Console 或 TUI 不会另建一个验证任务。

MCP 是供外部 Agent 调用工具的协议入口；它共享当前实例的工具和阶段状态，但不等同于 Console 命令接口。不要同时让自动循环和手动 MCP 客户端推进同一阶段；接管前先暂停并确认当前操作结束。Master 管理多个实例和任务，使用方法见 [Web Master](07_web_master.md)。

## 1. 为同一个实例打开不同入口

先按[普通模式](../01_start/02_normal_mode.md)准备好 `output/Adder/`，然后启动一次：

```bash
ucagent output/ Adder -s --human --loop
```

在该 Console 中输入下列命令，每条服务启动命令完成后可用对应状态命令确认：

```text
start_mcp_server 127.0.0.1 5000
mcp_server_status
cmd_api_start 127.0.0.1 8765
cmd_api_status
tui
```

MCP 客户端连接 `http://127.0.0.1:5000/mcp`，浏览器访问 `http://127.0.0.1:8765/`。在 TUI 输入 `q` 返回同一个 Console；再次输入 `tui` 会复用本地交互会话。也可以一次指定这些入口：

```bash
ucagent output/ Adder -s --human --tui --loop \
  --mcp-server --mcp-server-host 127.0.0.1 --mcp-server-port 5000 \
  --export-cmd-api 127.0.0.1:8765
```

上面两种启动方式二选一。再次执行 `ucagent` 会创建另一个实例，不会连接到已有任务。源码仓库的 `make test_Adder` 使用 `output/workspace_Adder/`，请按实际工作区替换路径。

交互启动和 HTTP/MCP 服务启动均等待明确的执行请求：使用 `--loop`、`--icmd`/`init_cmds` 中的模型命令，或启动后提交 `continue` 等命令。无界面、无服务的普通任务仍默认自动执行。状态查询和确定性工具调用不准备主模型。`blank` 会拒绝模型执行；显式启用的 embedding、模型审核和失败建议仍需各自的配置，工具或 Checker 也可能有独立模型依赖。

## 2. 命令、参数和长操作

Console、TUI 和 HTTP 的普通任务命令使用同一份注册表。用 `help` 查看当前实例的命令，用 `help <command>` 查看参数；插件命令只在对应插件激活后出现。`tui`、`clear` 等显示命令需要本地界面。下列是独立语法示例；工具调用结束后再提交下一条工具命令。

```text
help loop
status
tool_list Check
tool_invoke Check
tool_invoke StdCheck {"lines":-1}
tool_invoke GoToStage {"index":2}
shell ls -l
```

- `tool_invoke` 的参数只能是 JSON 对象；无参数时省略对象。不要使用 Python 位置参数、`key=value` 或表达式。
- 系统命令显式写成 `shell <command>`。未知命令报错，不会自动作为 shell 或 Python 执行；某些 shell 命令需要确认。
- `cd`、`pwd`、`chcwd` 修改或查询当前交互会话的目录，不改变整个进程或其他 HTTP 会话的目录。
- `loop`、`chat`、`tool_invoke` 等操作提交后，界面仍可输入查询命令。一次只能占用一个模型操作槽位；前一操作没有结束时再次提交会返回 `busy`。
- TUI 的 `&` 后缀标记本会话的后台操作，不增加模型并发名额。普通 Console 的长操作本身也异步执行，不需要添加 `&`。
- 普通 Console 默认允许空回车重复上一条命令，可用 `repeat_mode off` 关闭；TUI 空回车不执行命令。

长操作记录 ID、状态、结果或错误，状态为 `queued`、`running`、`cancelling` 或终态 `succeeded` / `failed` / `cancelled`。HTTP 对同步命令也生成可查询的已完成记录。`succeeded` 表示操作正常返回；例如 `Check` 正常返回 `check_pass: false` 时，仍需修复 Checker 报告的问题，不能只看操作状态认定验收通过。

人工修复、阶段审核与继续执行的步骤见[人机协同验证](02_assit.md)。

## 3. 暂停、取消、离开界面与关闭实例

| 操作 | 实际效果 |
| --- | --- |
| 本地 Console/TUI 按 `Ctrl+C` | 请求取消本交互会话最近的活动前台操作，包括其后续子操作；空闲时保留界面 |
| `agent_break` | 请求在执行边界暂停，不保证立即中止当前工具调用 |
| `agent_unbreak` | 清除暂停标志，不自动启动新操作；继续运行使用 `loop` 或 `continue` |
| TUI 输入 `q` / `quit` / `exit`，或按 `Ctrl+Q` | 关闭 TUI，返回 Console，任务和服务继续运行 |
| 普通 Console 输入 `q` / `quit` / `exit` | 请求关闭整个实例 |
| `shutdown` | 从 Console、TUI 或 HTTP 命令接口请求关闭整个实例 |
| `shutdown force` | 立即终止进程，无法保证完成保存和资源清理，仅用于明确需要强制退出时 |

取消请求发出后可能暂时显示 `cancelling`。要等待操作实际到达 `cancelled`、`failed` 或 `succeeded`，再开始冲突的操作；取消请求本身不表示工具和子进程已经退出。其他 HTTP 会话发起的操作应按其 ID 取消；手动启动的外部 MCP 客户端仍按客户端自己的方式停止。

正常 `shutdown` 会停止接收新操作，等待活动操作结束或取消，保存阶段状态、同步工作区、通知连接方，再关闭服务并清理资源。进程信号中，`SIGTERM` 请求关闭；`SIGINT` 请求取消本地前台操作，没有本地界面时请求协作暂停。

关闭终端、输入 EOF 与退出 TUI 不等价。CLI 在 Console EOF 后，若命令 HTTP 服务没有就绪，会请求关闭实例。不要把它作为后台托管方式；需要无本地终端运行时，应明确选择服务启动方式。

`Exit` 工具通知任务完成；交互或服务模式默认仍可保留实例供查看结果，`--exit-on-completion` 才要求完成后关闭。无交互、无服务的单次执行按自身完成策略退出。

## 4. HTTP 查询和控制

`--export-cmd-api` 或 `cmd_api_start` 提供同一个 Agent 的网页和命令 API。API 不依赖 TUI 是否打开；浏览器关闭也不会关闭实例。设置了服务密码时，以下 `curl` 命令需添加 `-u ':<password>'`。

| 接口 | 用途 |
| --- | --- |
| `GET /api/cmds` | 查询已注册命令 |
| `POST /api/cmd` | 提交命令，返回 `operation_id` |
| `POST /api/cmds/batch` | 按顺序执行命令，等待每条命令及后续子操作结束，并记录各条结果 |
| `GET /api/runtime/status` | 查询实例状态、执行状态、任务结果和操作列表 |
| `GET /api/operations/{operation_id}` | 查询某个操作的状态、结果、错误与取消标志 |
| `POST /api/operations/{operation_id}/cancel` | 请求取消该操作及其子操作 |
| `POST /api/runtime/pause` | 请求协作暂停，当前调用可能仍需完成 |
| `GET /api/stages/state` | 查询阶段状态和 `control_revision` |
| `POST /api/stages/review` | 按指定阶段及版本提交人工审核，可在通过后继续执行 |
| `POST /api/stages/update` | 按版本更新阶段开关 |

`/api/cmds/batch` 的请求使用 `cmds` 字符串数组，可复用 `session_id`；普通命令失败会记录错误并继续后续命令，最终汇总批次结果，已完成操作不会回滚。

例如，在另一个终端中查询或提交命令：

```bash
curl -s http://127.0.0.1:8765/api/runtime/status
curl -s http://127.0.0.1:8765/api/cmd \
  -H 'Content-Type: application/json' \
  -d '{"cmd":"status","session_id":"operator-a"}'
```

响应中的 `status: accepted` 表示请求已接收，需检查 `data.state` 或按返回的 ID 查询最终结果：

```bash
curl -s "http://127.0.0.1:8765/api/operations/<operation_id>"
curl -s -X POST "http://127.0.0.1:8765/api/operations/<operation_id>/cancel"
```

将 `<operation_id>` 替换为实际 ID。客户端应为同一交互会话复用 `session_id`，以保留 `cd` 等会话状态；未传该字段时，每次请求生成新会话标识。可选 `cwd` 必须指向当前工作区内已存在的目录。确实需要执行已确认的 shell 操作时，提交 `confirmed: true`。

阶段写操作需要传入刚读取的 `control_revision`，字段名为 `expected_revision`。例如，审核请求包含 `index`、`expected_revision`、`approved`、`message`，可选 `resume`；批量开关更新包含 `indices`、`expected_revision` 和要修改的开关。遇到 `stale_revision` 时重新读取阶段状态，确认后再提交；遇到 `busy` 时先等待或取消冲突操作，不要盲目覆盖。

HTTP 的显示命令会被拒绝；子工作区视图也不能通过命令或取消接口控制父工作区。MCP 工具调用不自动获得这些 HTTP 操作 ID；有关入口边界见[架构与工作原理](../03_develop/02_architecture.md)。

### 工作区文件和阶段历史

Web 文件管理使用人工操作权限：受 HTTP 认证、选定工作区的路径边界和操作系统权限约束，不应用 LLM 工具的 `write_dirs/un_write_dirs` 限制，也不会自动修改文件权限。人工读取、编辑和上传不会产生 LLM 的工具使用或参考文件读取证据。通过 `sub_workspace` 选择子工作区时，文件操作限定在该子工作区内；上传、重命名、读取和下载均校验最终路径及符号链接目标。

普通文件删除支持递归删除选定目录，但禁止删除选定工作区根目录；删除整个子工作区使用专门的子工作区删除入口。该入口的 `cleanup_parents=true` 只回收删除后已经为空的非工作区父目录，父目录内的普通文件及其他工作区会保留。

查看阶段产物、历史文件及差异不会同步历史、创建提交或运行 Checker。`sync_history=true` 仅允许当前活动阶段显式同步；从保存快照查看子工作区时不可执行此操作。保存快照不代表子 Agent 已停止。文件已从当前目录删除时，仍可读取其已有阶段提交；历史不可用时会明确报告，不会将当前文件冒充为历史证据。

## 5. 恢复范围

同一进程内切换 Console/TUI 会保留本地交互上下文，HTTP 服务继续操作同一实例。阶段状态、历史及部分工具证据按现有机制保存到工作区；进程重启后可以据此恢复阶段工作。

长操作记录和输出缓冲主要保存在内存中，不能在进程重启后继续查询旧操作 ID，也不保证恢复完整模型会话或执行中的调用。当前没有远程 TUI attach 或自动守护进程功能。重启流程见[人机协同验证](02_assit.md#8-恢复原则)。
