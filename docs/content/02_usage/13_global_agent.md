
# Global Agent：常驻对话与工作流会话

Global 是自然语言入口：根据你的指令选择工作流，按需启动 Super，接收经过校验的结果并汇总。每个 Super 执行一个工作流，负责阶段推进、Checker 和 Sub 任务分配。任务结束后 Global 继续等待下一条输入。

## 启动与输入

```bash
ucagent ./workspace --agent-mode global --config ./config.yaml
```

交互启动默认进入 Global TUI，也可以显式传入 `--tui`。`--human` 选择 Console。无需初始任务或 `--loop`；没有输入时不调用模型。

在输入框描述任务，例如“用 unittest 工作流验证当前 DUT”。Global 查询可用工作流，信息充分后直接启动 Super；信息不足时先澄清。Super 在后台执行，Global 可继续接收其他任务和状态询问。

`--loop-msg "自然语言任务"` 在 Global 模式下只作为一次初始输入。需要无界面的单次执行时，同时指定 `--exit-on-completion`；当前请求的子任务、结果事件及最终回复全部处理后退出，失败使用非零退出码。

Global 本身使用 single-agent 执行，启动的 Super 使用 multi-agent。Global 不能与 Master、workflow handoff 或 `--plugin-workflow` 合用；工作流由会话中的 StartSuper 选择，子级并发通过启动配置指定。

## 配置工作流目录

在现有模型配置中增加以下配置。也可以用单独配置文件通过 `include` 引用模型配置，避免复制凭据。

```yaml
global_agent:
  plugin_selectors:
    - /absolute/path/to/UCAgent/ucagent/plugins/UnitTest
  allowed_workflows:
    - unittest:unittest
  target_configs: {}
  max_parallel_supers: 2
  max_runs_per_request: 12
  workspace_roots: []
  resources:
    simulator: 1
  launch_profiles:
    standard:
      backend: langchain
      max_subagents: 2
      max_attempts: 2
      no_embed_tools: false
      resources:
        - simulator
```

- `allowed_workflows` 必须能从已加载插件或 `plugin_selectors` 解析；目录列出用途、输入、输出及不可用原因。
- `launch_profiles` 是操作者定义的启动参数。Global 选择名称，不提供任意 shell、argv 或配置覆盖。目录查询不会返回 profile 的秘密配置值。
- 子级配置优先级为 `target_configs[workflow]`、profile 的 `config_ref`、Global 启动配置。
- `no_embed_tools: false` 根据 backend 能力选择工具路径；`true` 强制使用外部工具。需要 MCP 时监听本机动态分配端口。
- `max_parallel_supers` 限制同时执行的 Super；profile 的 `max_subagents` 限制该 Super 的 Sub 数量。
- profile 的 `resources` 消耗同名容量。例如 simulator 容量为 1 时，相关 Super 串行执行。
- `max_runs_per_request` 限制一个用户请求及其结果触发的后续启动，重试也消耗预算。`max_attempts` 限制一个 Super 的执行尝试。
- 默认只允许从 Global 工作区内选择业务来源；额外目录通过 `workspace_roots` 显式配置。每次执行派生独立工作区，排除 `.ucagent`、`.git` 和虚拟环境等运行目录；拒绝越界符号链接和可能造成递归复制的目录链接。

## 两种界面与导航

Global TUI 主体是对话，侧栏显示 Super/Sub、工作流和执行状态。主对话显示关键事件及最终结果；选择 Agent 打开详细消息，避免所有子级工具输出混在主对话里。

Super 和 Sub 都使用原有执行 TUI：左侧 Mission、右侧 Messages、下方 Console 和底部状态栏，保留分隔条拖动、命令历史与名称补全。Super 展示阶段、文件变更、工具调用和 Sub 列表；Sub 展示所属工作流、任务指令、状态、结果及自身消息。页面切换不会取消任务，各页面独立保留消息、输入草稿、历史和分区大小。

| 操作 | 用途 |
| --- | --- |
| 自然语言 | 发起任务、提问、描述后续工作 |
| `/agents` | 查询 Agent 状态 |
| `/open AGENT_ID` | 打开指定 Super |
| `/cancel AGENT_ID` | 取消指定 Super 及其所属执行 |
| `/retry AGENT_ID` | 在预算内重试失败或取消的任务 |
| `/help` | 查看 Global 界面命令 |
| `/quit` | 退出 Global 宿主并回收子进程 |
| Ctrl-Q | 从 Global TUI 返回 Console，任务继续 |
| Escape 或 `/back` | 从 Agent 页面返回上一级；优先关闭帮助、补全或 Console 翻页模式 |
| Ctrl-方向键 / Ctrl-H/J/K/L | 在 Super/Sub 页面调整分区大小 |
| F1 / Ctrl-T | 在 Super/Sub 页面查看快捷键 / 选择主题 |

Super 页面可直接输入 `status`、`task_status` 等已注册 Console 命令，也支持 `/status` 形式；其他普通文本作为补充指令，在安全的规划边界交付。Sub 页的补充指令交给父 Super，不直接改写正在运行的 Sub 任务。Super 页的 Ctrl-C 中断该 Super 的操作，不取消其他 Super；Sub 的暂停或取消在父 Super 页面执行。

## 从另一终端查看

会话目录由 ListAgents 和 Global 启动状态提供，也可在工作区的 `.ucagent/global/sessions/` 中找到。

```bash
ucagent attach /absolute/path/to/session_dir --agent super-xxxxxxxxxxxx
```

attach 连接已有运行实例，不创建 Agent 或重跑工作流。关闭查看窗口不停止任务。任务结束后可以查看保存的只读状态和消息。

当前只支持本机会话连接。Global 宿主退出会回收所属进程；重启可查看历史，不会重新接管旧进程。工作区和进程隔离不等同于操作系统安全沙箱。

## Global 可用工具

| 工具 | 用途 |
| --- | --- |
| ListWorkflows / ListLaunchProfiles | 查询工作流目录与启动配置 |
| StartSuper | 异步启动一个工作流，立即返回 Agent ID |
| ListAgents / AgentStatus | 查询 Agent 树、阶段、错误、尝试及产物 |
| MessageSuper | 向活动 Super 投递补充指令 |
| CancelSuper / RetrySuper | 取消或重试指定任务 |
| ReadAgentArtifact | 有界读取已验收产物，复核文件摘要 |

完成结果自动进入 Global 后续对话，无需模型反复调用状态工具等待。需要串联工作流时，Global 等上游产物验收后再决定后续启动；inputs 使用 `agent_id`、`attempt`、`path` 指向已验收产物，并复制到目标 `inputs/` 路径。

## 验收与历史

Super 成功需要正常退出、有效的运行回执、正确的任务/尝试身份、完成的阶段以及匹配的输出文件和摘要。阶段结果遵循工作流既有的完成及允许跳过语义；业务正确性由对应 Checker 判断。Global 不能通过回复文字提前宣布运行成功。

ReadAgentArtifact 默认返回最多 64 KiB，单次上限 1 MiB。输入复制和产物读取会复核摘要，验收后被修改的文件不能继续作为有效产物使用。完成通知只携带有界产物摘要；完整索引保存在会话记录中，并可通过 AgentStatus 查询。

每个会话保存状态、事件、各 Agent 的尝试、业务工作区、运行回执和日志。重试使用新的 attempt，历史保留。消息日志只用于展示，不作为任务成功证据。最终文件保留在各任务工作区，没有自动打包为统一交付目录。
