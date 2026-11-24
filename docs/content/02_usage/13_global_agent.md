
# Global Agent：常驻对话与工作流会话

Global 是自然语言入口：根据你的指令选择工作流，按需启动 Super，接收经过校验的结果并汇总。每个 Super 执行一个工作流，负责阶段推进、Checker 和 Sub 任务分配。任务结束后 Global 继续等待下一条输入。

## 启动与输入

Global 是 `multi` 的顶层角色。交互启动与命令行直接指定任务使用同一条 Global → Super → Sub 链路，命令和参数见[多 Agent 启动](11_multi_agent.md)。

启动无需绑定 DUT 或工作流。进入窗口后可依次输入：

- “用 unittest 工作流验证 examples/Adder 下的 Adder。”
- “对同一个 Adder 再跑 formal 工作流。”
- “接下来验证 examples/ALU 下的 ALU，使用 unittest。”（源目录须存在）

Global 查询工作流和 DUT 来源；同名 DUT 存在多个目录时先澄清。每个任务独立准备工作区，再启动 Super；原始 DUT 来源保持不变。Super 在后台执行，Global 可继续接收任务和状态询问。结果自动返回，之后仍可输入。

`multi` 不能与 Master 合用。跨工作流选择由 Global 负责；不能在公开入口启用 `workflow_handoff_enabled`。Super 通过内部角色启动，只负责当前工作流。

## 配置工作流目录

在现有模型配置中增加以下配置。也可以用单独配置文件通过 `include` 引用模型配置，避免复制凭据。

```yaml
global_agent:
  plugin_selectors: []
  allowed_workflows: []
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
      preparation_timeout: 900
      no_embed_tools: false
      resources:
        - simulator
```

- 启动时发现安装的插件、仓库内插件及 `plugin.search_paths` 中的插件；`--plugin` / `plugin_selectors` 可显式指定来源并消除同名冲突。目录发现会导入插件声明，不激活业务工具或阶段；只配置可信插件路径。单个插件加载失败不会阻止其他插件使用。
- `allowed_workflows` 留空表示全部发现的工作流；非空则显式限制为指定的 `plugin:workflow`。目录列出用途、输入、输出、准备参数及不可用原因。安装版只内置 UnitTest，Formal 等插件须已安装或位于配置的搜索路径。新增插件后重启 Global 重新发现。
- profile 的 `backend: null`（默认值）继承 Global 后端；显式值固定该 profile 的 Super/Sub 后端。
- `launch_profiles` 是操作者定义的启动参数。Global 选择名称，不提供任意 shell、argv 或配置覆盖。目录查询不会返回 profile 的秘密配置值。
- 子级配置文件优先级为 `target_configs[workflow]`、profile 的 `config_ref`、Global 启动配置。CLI 的任务配置覆盖、输出目录和显式 Skill 开关传给子级；启动模式与进程身份由框架固定。
- `no_embed_tools: false` 根据 backend 能力选择工具路径；`true` 强制使用外部工具。需要 MCP 时监听本机动态分配端口。
- `max_parallel_supers` 限制同时准备或执行的 Super；profile 的 `max_subagents` 限制该 Super 的 Sub 数量。
- profile 的 `resources` 消耗同名容量。例如 simulator 容量为 1 时，相关 Super 串行执行。
- `max_runs_per_request` 限制一个用户请求及其结果触发的后续启动，重试也消耗预算。`max_attempts` 限制一个 Super 的执行尝试。
- 项目目录默认为启动时当前目录，可用位置参数或 `MULTI_WORKSPACE` 指定；它是 DUT 搜索范围，不是某个任务工作区。额外目录通过 `workspace_roots` 显式配置，相对路径按项目目录解析。
- Global 自身运行文件位于 `<project>/.ucagent/global/sessions/<session>/global/`；项目 `.ucagent/setting.yaml` 仍参与启动配置。各 Super 的任务目录位于同会话的 `agents/<id>/attempt-N/workspace/`。

## DUT 选择与工作区准备

`ListDUTs` 有界扫描项目和额外来源根目录（最多三层子目录、2000 个目录、返回 200 个候选），识别原始 RTL 与 `<DUT>_RTL` 工作区；不会扫描隐藏运行目录。更深层或非 RTL 任务可显式提供 `dut_name` 和 `source_workspace`。路径必须在允许范围内；禁止使用 Global 运行状态目录作为输入。

`StartSuper` 按任务解析 DUT、工作流和准备参数。状态依次为 `queued → preparing → starting → running → succeeded/failed`；准备阶段占用并发和 profile 资源配额。界面显示 DUT、工作流及准备进度。取消会终止准备命令；准备失败不会启动 Super，重试使用新目录。profile 的 `preparation_timeout` 限制准备总时长，默认 900 秒。

- `unittest:unittest` 整理 RTL/文档，导出 Picker 接口并运行 `example.py` 验证。`preparation` 支持 `simulator`（默认 `verilator`，也支持 `gsim/vcs/uvs`）和 `blackbox`（默认 false）。源内容和参数匹配已有准备记录时复用接口并重新验证；否则重新导出。已准备的来源在未指定参数时沿用记录中的模拟器和 blackbox 选择；blackbox 接口需重新导出时必须提供原始 RTL。
- `formal:formal` 从原始 RTL 或工作区的 `<DUT>_RTL` 整理 `<DUT>/`，不继承 UT 测试和模拟器接口。执行所需 EDA 工具仍须由操作者配置。
- 未声明准备钩子的工作流安全复制指定源目录；例如增量 UT 应选择已有测试工作区。复制排除 `.ucagent`、`.git`、虚拟环境等，拒绝越界文件链接和目录链接。

`make init_<DUT>`、`make formal_init_<DUT>` 使用相同插件准备接口。Make 替换已有任务资产时将旧文件保存在目标 `.ucagent/preparation-backups/`；准备失败保留原资产及命令日志。Global 的准备日志在对应 attempt 的 `preparation.log`。

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
| ListDUTs | 查询 DUT 名称、原始或已准备来源路径 |
| ListWorkflows / ListLaunchProfiles | 查询工作流目录与启动配置 |
| StartSuper | 按 DUT 和源路径异步准备并启动工作流，立即返回 Agent ID |
| ListAgents / AgentStatus | 查询 Agent 树、阶段、错误、尝试及产物 |
| MessageSuper | 向活动 Super 投递补充指令 |
| RecoverSuper | 按用户指令回复或恢复存活的暂停任务 |
| CancelSuper / RetrySuper | 取消或重试指定任务 |
| ReadAgentArtifact | 有界读取已验收产物，复核文件摘要 |

完成结果包含 `dut_name` 和 `source_workspace`，供“同一个 DUT”的后续任务明确复用。不同工作流默认从相同源文件独立准备；不会自动把上一任务整个目录当作新输入。完成结果自动进入 Global 后续对话，无需模型反复调用状态工具等待。需要串联工作流时，Global 等上游产物验收后再决定后续启动；inputs 使用 `agent_id`、`attempt`、`path` 指向已验收产物，并复制到目标 `inputs/` 路径。

## 验收与历史

Super 成功需要正常退出、有效的运行回执、正确的任务/尝试身份、完成的阶段以及匹配的输出文件和摘要。阶段结果遵循工作流既有的完成及允许跳过语义；业务正确性由对应 Checker 判断。Global 不能通过回复文字提前宣布运行成功。

ReadAgentArtifact 默认返回最多 64 KiB，单次上限 1 MiB。输入复制和产物读取会复核摘要，验收后被修改的文件不能继续作为有效产物使用。完成通知只携带有界产物摘要；完整索引保存在会话记录中，并可通过 AgentStatus 查询。

每个会话保存状态、事件、各 Agent 的尝试、业务工作区、运行回执和日志。重试使用新的 attempt，历史保留。消息日志只用于展示，不作为任务成功证据。最终文件保留在各任务工作区，没有自动打包为统一交付目录。


## 待处理任务与界面恢复

Global 保持对话区、Agent 树和输入框布局；顶部统计运行与待处理任务，Agent 树显示具体暂停类别，底部提示进入哪个 Super 处理。状态变化只通知一次。

Super 保留 Mission / Messages / Console 布局，在 Messages 上方显示执行状态卡。暂停时展开原因、当前规划消耗和适用操作；详情区区分 Agent 报告、运行时条件检查及实际调用证据。额度弹窗展示明确的增量，只有提交后才追加。人工审核继续使用原有审核和版本校验。

Sub 只显示分配给它的阶段、自己的工具统计、工具结果正文和自身 Console。任务尝试结束后显示“交由 Super 处理”，可直接打开父 Super；Sub 输入框中的文字是给 Super 的指导。

`RecoverSuper` 用于根据用户的明确指令回复或恢复一个存活的暂停任务；`MessageSuper` 只补充指导。预算追加和正式审核由 Super 的操作入口执行。进程已结束的任务显示为只读，使用 `/retry AGENT_ID` 创建新尝试。分类处理和 Console 命令详见 [多 Agent 的暂停与恢复](11_multi_agent.md#分类处理暂停与恢复)。
