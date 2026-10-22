
# Xpra 图形应用与交互式 Console

CMD WebUI 可以通过 Xpra 在浏览器中显示服务端的图形应用，也可以通过图形终端运行交互式命令。Agent Dashboard 的 **Xpra** 按钮打开会话管理页；点击 **Create session** 弹出创建窗口；每个会话的 **Open** 链接直接打开应用显示页。显示页使用 UCAgent 的界面，复用官方 HTML5 客户端的协议和渲染库，不再展示官方的连接表单。

会话属于创建它的 CMD 服务，不会发现、接管或删除同机其他用户或服务启动的 Xpra 会话。Web Terminal、Web Console 与 Xpra 使用独立连接，可以同时运行。

## 安装与启动条件

在运行 CMD 服务的环境中安装 Xpra 服务端、X11 服务支持、虚拟显示程序（如 Xvfb）及官方 `xpra-html5` 客户端。Console 模式还需要图形终端，默认是 `xterm`。真实集成验证以 Xpra 6.5.5 为基线。

CMD 服务和目标应用可部署在具备上述依赖的 Linux 主机或 Docker 容器中，用户通过浏览器访问会话管理页和应用显示页。已在 macOS 上使用 Chrome 和 WebKit 验证直连及 Master 代理访问。

CMD 服务缺少 Xpra 时仍可启动，其他 API 继续可用。管理页会显示缺少程序或资源的提示。`status` 接口检查可执行程序、版本及显式配置的资源路径；实际创建会话时进一步检查服务端和 HTML5 服务是否能够启动。

沿用 CMD 服务的启动和认证设置，例如在 PDB 中执行：

```text
cmd_api_start --passwd your-password
```

直接访问 `http://127.0.0.1:8765/api/xpra/`，使用与其他 CMD API 相同的 Basic 认证。CMD 服务未配置密码时，Xpra 也允许无密码访问。HTML5 页面、资源与 WebSocket 同样受该策略约束，密码不会写入连接 URL。进入管理页完成 CMD 或 Master 登录后，点击 **Open** 会根据 URL 中的会话 ID 自动检查访问权限并连接，无需再次填写 Xpra 主机、端口、用户名或密码。会话 ID 本身不授予访问权限；未认证的新浏览器仍需先完成当前入口的登录。

部分浏览器不会在 WebSocket 握手中携带页面的 Basic 认证头。显示页每次连接前会通过认证后的 HTTP 请求取得一个有效期 5 分钟的连接 Cookie；Cookie 使用 HttpOnly、SameSite=Strict，HTTPS 下还使用 Secure，仅适用于当前会话及当前代理路径的 WebSocket。它不能用于调用管理接口，其他会话也不能使用；连接建立后不会因 Cookie 到期被断开，重连时自动重新签发。命令行 WebSocket 客户端仍可直接使用 Basic 认证。

## 配置

将以下设置放入 UCAgent 配置文件；字段从当前生效的配置读取，修改后重启 CMD 服务：

```yaml
cmd_api:
  xpra:
    executable: xpra
    max_sessions: 5
    terminal_command: [xterm, -e]
    html_dir: null
    startup_timeout: 20
    shutdown_timeout: 5
    presets:
      - label: Terminal
        name: Terminal
        mode: console
        command: bash -l
        cwd: .
        env: {}
        idle_timeout: -1
      - label: Browser
        name: Browser
        mode: gui
        command: chromium --no-first-run --no-default-browser-check about:blank
        cwd: .
        env: {}
        idle_timeout: -1
      - label: Codex
        name: Codex
        mode: console
        command: codex
        cwd: .
        env: {}
        idle_timeout: -1
      - label: OpenCode
        name: OpenCode
        mode: console
        command: opencode
        cwd: .
        env: {}
        idle_timeout: -1
      - label: Qwen Code
        name: Qwen Code
        mode: console
        command: qwen
        cwd: .
        env: {}
        idle_timeout: -1
```

| 字段 | 用途 |
| --- | --- |
| `executable` | Xpra 程序名或可执行文件路径 |
| `max_sessions` | 同时活动的会话数，默认 5；必须为正整数 |
| `terminal_command` | Console 的图形终端启动参数列表，随后追加应用命令及其参数 |
| `html_dir` | 官方 HTML5 资源目录，必须包含 `index.html`；`null` 使用 Xpra 自带资源 |
| `startup_timeout` | 等待 HTML5 服务就绪的秒数，必须为正数 |
| `shutdown_timeout` | 等待所属 Xpra 正常停止的秒数，超时后强制回收 |
| `presets` | 创建表单的快捷按钮列表；`[]` 隐藏全部按钮。自定义列表会完整替换默认列表 |

Xpra 使用私有临时目录和 Unix socket，不另外开放 Xpra TCP 端口。会话隔离 Xpra 的系统/用户配置目录，避免其中的监听设置或额外启动命令绕过 CMD 管理；通过上述 UCAgent 配置调整本功能。

## 创建快捷按钮与 Code Agent

创建表单默认提供 **Terminal**、**Browser**、**Codex**、**OpenCode**、**Qwen Code** 快捷按钮。点击 **Create session** 打开创建弹框，其中提供这些快捷按钮。点击按钮会完整填入名称、模式、命令、工作目录、环境变量和空闲超时；确认或修改参数后，点击 **Create session** 才会启动程序。按钮本身不启动会话，也不占用配额。

**Terminal** 使用 Console 模式启动 `bash -l`，通过配置的图形终端显示交互式 shell；可以将命令改为 `zsh -l` 等已安装的 shell。**Browser** 使用 GUI 模式启动 `chromium --no-first-run --no-default-browser-check about:blank`，可以将命令改为实际浏览器路径或 Firefox 等程序。浏览器运行在 CMD 服务所在环境中，需要在那里安装相应程序；访问的网络和文件也来自该服务环境。

每个 `presets` 条目包含必填的 `label`（按钮文字）和 `command`；其余字段与创建接口一致：`name` 默认空字符串，`mode` 默认 `gui`，`cwd` 默认 `.`，`env` 默认 `{}`，`idle_timeout` 默认 `-1`。Code Agent 预设应显式使用 `mode: console`，通过配置的图形终端运行交互界面。可以修改命令为可执行文件的绝对路径，或追加该 CLI 支持的参数；工作目录仍需位于 workspace 内。

`codex`、`opencode`、`qwen` 必须安装在 **CMD 服务实际运行的环境** 中，且能通过其 PATH 找到；若 CMD 在容器里运行，宿主机的 CLI 安装不会自动出现在容器中。预设使用交互式启动命令，CLI 自身的首次登录、模型配置和授权仍由该 CLI 完成。缺少命令时，创建接口和页面会提示安装程序或修正路径。

预设参数会通过认证后的 API 发送给浏览器，供用户查看和编辑。不要在预设命令或 `env` 中放入 API 密钥、令牌或密码；在 CMD 运行环境中设置所需凭据，由子进程继承。快捷按钮不会修改 Code Agent 的登录配置或审批选项。

预设列表即使在缺少 Xpra 或目标 CLI 时仍可读取。格式无效时，页面显示配置错误，手动创建表单继续可用。修改配置后重启 CMD 服务。

## API

全部接口统一使用 `/api/xpra/` 前缀。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/xpra/` | 会话管理页面 |
| GET | `/api/xpra/status` | 程序可用性、版本、Console 终端可用性和诊断 |
| GET | `/api/xpra/presets` | 返回 `{"presets": [...]}`，供创建页填充参数；沿用 CMD／Master 认证 |
| GET | `/api/xpra/sessions` | 所属会话列表、活动数量、最大数量 |
| POST | `/api/xpra/sessions` | 创建会话；HTML5 服务就绪后返回 201 |
| GET | `/api/xpra/sessions/{id}` | 单个会话详情、最近错误和有长度限制的日志 |
| DELETE | `/api/xpra/sessions/{id}` | 停止并删除所属会话 |
| POST | `/api/xpra/sessions/{id}/connect` | 检查会话并签发或刷新当前浏览器的连接 Cookie，成功返回 204；仍需 CMD／Master HTTP 认证 |
| GET | `/api/xpra/sessions/{id}/view` | 自动连接的 HTML5 显示页面 |
| GET / HEAD | `/api/xpra/sessions/{id}/client/{path}` | UCAgent 应用显示界面及官方协议、渲染资源 |
| WebSocket | `/api/xpra/sessions/{id}/client/` | 画面、键鼠及客户端协议交互 |

创建 GUI 会话：

```bash
curl -u :your-password \
  -H 'Content-Type: application/json' \
  -d '{"name":"Clock","mode":"gui","command":"xclock","cwd":".","env":{}}' \
  http://127.0.0.1:8765/api/xpra/sessions
```

创建 Console 会话使用相同接口和字段，例如：

```json
{
  "name": "Interactive shell",
  "mode": "console",
  "command": "bash -l",
  "cwd": ".",
  "env": {"TERM": "xterm-256color"},
  "idle_timeout": 300
}
```

`command` 必填；`mode` 默认为 `gui`，`name` 默认采用启动程序名称，`cwd` 默认是 workspace 根目录，`env` 默认是空对象。工作目录必须存在且位于 workspace 内，符号链接不能指向外部目录。

命令按引号拆分为参数，不自动解释 shell 表达式。需要管道、重定向或 shell 初始化时明确提交 `bash -lc 'your command'`。Console 模式将拆分后的参数追加到 `terminal_command` 后；GUI 模式直接启动应用。

会话包含 `id`、`name`、`mode`、`command`、`cwd`、`idle_timeout`、`status`、`created_at`、`viewer_path` 和 `last_error`；详情还包括最多 200 条输出的 `log_tail`。`viewer_path` 相对于当前 `/api/xpra/` 基址解析。`created_at` 是 Unix 时间戳。环境变量值不会作为会话字段返回，已知凭据及提交的环境变量值会在捕获日志中遮盖。

## 显示页操作

点击 **Open** 后直接进入应用。Console 默认铺满可用显示区域；GUI 保留应用自身的窗口尺寸和调整功能。顶部显示实际连接状态，提供 **Reconnect**、**Full screen**、**Sessions**、**Exit**，以及窗口切换列表；最小化的应用可以通过窗口列表恢复。

Console 中先拖动鼠标选中文本，再右键选择 **Copy selection** 复制到本地剪贴板；右键选择 **Paste** 将本地剪贴板文本粘贴进终端。也支持 `⌘C` / `⌘V` 和 `Ctrl+Shift+C` / `Ctrl+Shift+V`；普通 `Ctrl+C` 仍用于终端中断。打开菜单不会改变当前选区，未选中文本时复制按钮不可用。

浏览器要求剪贴板权限时，需要允许本次访问；普通 HTTP、浏览器限制或拒绝权限时会打开手动复制/粘贴窗口。也可直接选择 **Paste text…**，在本地文本框中使用浏览器的粘贴操作，再点击 **Paste into terminal**。文本框中的内容在提交前不会发送给应用。粘贴按原文发送，文本中的换行可能触发终端执行。

Console 按住修饰键（Shift、Control、Command 或 Alt）点击右键，仍会把右键交给远端应用，供终端应用自身的菜单或鼠标功能使用。GUI 模式的右键始终交给远端应用；应用区域不弹出本地浏览器菜单。顶部导航和按钮保留浏览器的右键行为。

点击 **Exit** 并确认后会停止应用、删除当前 session，并返回当前入口的会话管理页；当前客户端会断开。退出过程中暂停自动重连，失败时显示原因并允许重试。关闭浏览器标签页时按该 session 的空闲超时设置保留应用。

刷新页面会重新验证并自动连接。临时断线时自动重试最多 5 次，并显示重试进度；会话已删除、已退出或访问被拒绝时显示具体原因和操作提示，不跳转到官方连接页面。点击 **Reconnect** 可以手动发起新的连接。初次连接不会主动读取本地剪贴板或申请音频权限；剪贴板交互由用户的复制、粘贴操作触发。

每个 session 同时只允许一个客户端控制。后打开的显示页自动抢占原连接；原页面显示 **Session opened in another client** 提示及 **Take back** 按钮，停止自动重连。点击 **Take back** 可抢回当前页面，另一页面会收到同样提示。直连、Master task 代理和 agent 代理共同遵守此规则。

## 生命周期与错误处理

状态包括 `starting`、`running`、`stopping`、`exited` 和 `failed`。启动中、运行中、停止中的会话都占用活动名额；已退出或启动失败的会话不占用名额，仍可查看日志或删除记录。

创建时可设置 `idle_timeout`，单位为整数秒：`-1`（默认）表示不超时，正整数表示没有已连接客户端持续达到该秒数后自动退出应用；`0`、其他负数、非整数及超过 `4294967` 的值无效。计时从会话服务就绪后没有客户端时开始，客户端连接后取消计时，最后一个客户端断开后重新计时。客户端保持连接时，即使没有键鼠输入也不会超时；管理页轮询、查看详情和加载资源不算客户端连接。抢占期间的新客户端会继续保持会话。

空闲超时退出后，列表中保留 `exited` 记录供查看日志和删除，活动名额及进程资源已释放。`-1` 时关闭浏览器或断网会保留应用；有限超时时可在到期前重新打开。应用退出后会话结束；删除会话、停止 CMD 服务或正常退出 UCAgent 时清理所属 Xpra、子进程和临时资源。服务重启后不恢复旧会话。

接口失败通过 `detail` 返回结构化诊断：

```json
{
  "detail": {
    "error_code": "XPRA_SESSION_LIMIT",
    "message": "The maximum number of active Xpra sessions has been reached.",
    "next_action": "Delete an unused session or increase cmd_api.xpra.max_sessions."
  }
}
```

| 状态码 | 典型原因 | 操作 |
| --- | --- | --- |
| 401 | 缺少或错误的 CMD / Master 凭据 | 使用当前入口的认证信息 |
| 404 | 会话不存在或已删除 | 刷新列表并打开现有会话 |
| 409 | 达到容量上限或创建被停止操作取消 | 删除空闲会话，或重试创建 |
| 422 | 命令、工作目录、环境变量或请求字段无效 | 按诊断修正输入 |
| 502 | 无法连接所属 Xpra 上游 | 查看会话状态和日志，再重连 |
| 503 | 程序、终端、HTML5 资源或服务端能力缺失；会话不在运行 | 按诊断安装/配置运行条件，或创建新会话 |
| 504 | 启动未在期限内完成 | 查看日志，修复显示环境，必要时调整启动等待时间 |

创建失败会返回可查询的 `session_id` 和日志；提交参数本身无效或程序不存在时，可能尚未分配会话 ID。管理页和显示页直接展示错误原因与下一步操作。

## Master 代理与现有终端

通过现有 Master CMD 代理访问时，在上述地址前增加 `/task/{task_id}/cmd` 或 `/agent/{agent_id}/cmd`，例如：

```text
/task/{task_id}/cmd/api/xpra/
/agent/{agent_id}/cmd/api/xpra/sessions/{id}/view
```

管理页、HTML5 资源和 WebSocket 使用同一代理前缀。浏览器使用 Master 认证，Master 为上游 CMD 连接提供对应凭据。HTTPS 页面自动使用 WSS，部署到外部反向代理后应继续允许 WebSocket Upgrade。

Agent 通过实际注册和心跳向所连接的 Master 更新 CMD 代理凭据；Master 在内存中用于 HTTP/WebSocket 转发，不在 Agent 列表、详情或持久化的 Agent 快照中返回或保存该密码。Master 重启后由新的心跳恢复凭据。

现有终端保持独立服务的 `/ws`，Master 保持 `/terminal/ws` 和 `/web-console/ws`。Xpra 使用 CMD 下的 `/api/xpra/sessions/{id}/client/`，删除、刷新或重连 Xpra 不会接管终端连接，也不会终止终端进程。

## 完整运行环境集成测试

在安装了项目完整依赖、picker、Verilator、Xpra 服务端、官方 HTML5 资源、Xvfb、xterm 和 xclock 的 Linux 环境中，可运行：

```bash
UCAGENT_RUN_XPRA_INTEGRATION=1 python -m pytest -q tests/test_api_xpra_full_runtime.py
```

测试先用 picker 和 Verilator 从 Adder RTL 导出并编译真实 DUT 包，再通过正式 CLI 加载默认验证工作流，分别验证 Web Terminal、Web Console 模式与 CMD API、Xpra 的共存。它检查真实 PDB 命令执行、终端输入输出、实际心跳注册后的 Master 认证代理、GUI/Console 会话创建删除，以及正常退出 UCAgent 后的所属进程清理。同一个 Agent 的 Web Terminal 和 Web Console 沿用 CLI 原有的互斥限制；可在多个 Agent 中分别运行。测试使用项目自带的 `blank` 后端，不发起模型请求；不会替换 Agent、PDB 或工作流对象。未显式启用时跳过此测试，普通单元测试不要求本机安装 Xpra 服务端。
