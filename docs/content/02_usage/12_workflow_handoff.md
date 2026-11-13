
# 工作流接力

工作流接力让**当前 Super**在所有业务阶段验收后选择下一工作流。下一工作流创建新的 Agent、Super 会话和工作区；就绪后退役旧实例，再开始新业务。应用 PID 保持不变，没有额外的上层决策 Agent。功能默认关闭，只支持托管 multi 模式和同一 backend。

## 启用与候选配置

在启动配置中设置：

```yaml
runtime_options:
  multi_agent_enabled: true
  workflow_handoff_enabled: true
workflow_handoff:
  goal: "Increment the supplied value and deliver the final result."
  plugin_selectors:
    - /absolute/path/to/relay_sink
  allowed_workflows:
    - relay-source:produce
    - relay-sink:consume
  allowed_next:
    relay-source:produce: [relay-sink:consume]
    relay-sink:consume: []
  chain_root: /absolute/path/outside-business-workspace/relay-chain
  max_runs: 4
  max_start_attempts: 2
  ready_timeout_seconds: 30
  decision_limits:
    backend_turns: 4
    tool_calls: 20
    timeout_seconds: 120
  allow_revisit: false
```

`goal` 保留原始总体目标；后续用户指令另行记录。`plugin_selectors` 是受信任候选来源，不会把候选工具或 Guide_Doc 激活进当前 Agent。初始工作流仍通过 `--plugin`、`--plugin-workflow` 选择。不要为了把 B 加入候选而把 B 作为 A 的活动插件加载。

`allowed_next` 限定可选边，**不会自动按边执行**。即使只有一个候选，也必须由当前 Super 明确提交决策。预算跨失败重试、token 更新和恢复累计；不能通过另起规划回合重置。决策超时按墙钟时间累计，暂停也不会重置它。`max_runs` 包含初始工作流。

`target_configs` 可选，格式为 `{"relay-sink:consume": "/absolute/path/to/trusted.yaml"}` 的 YAML 映射。它提供目标专属预设。目标重新解析自己的 workflow、角色、阶段和权限；只继承 backend、模型连接、上下文设置、语言和追踪连接。不会继承 A 的完整 `--config`、业务阶段、输出目录或角色定义。源和后继的有效配置指纹用于恢复核验，配置内容和凭据不写入链记录。

`chain_root` 必须位于初始业务工作区之外，并且不能经过符号链接。省略时，在初始工作区同级的 `.ucagent-chains/<chain-id>/` 分配存储。初始工作区不会搬迁；后继使用 `chain-root/runs/<run-id>/workspace/`。

single、blank Super 和 Master 自身不支持启用此功能。禁用后不创建链目录，不增加交接工具，原有退出行为保持不变。

## Super 的交接回合

全部真实业务阶段完成、最后一个委派验收通过且写操作收拢后，Super 进入独立的 `phase=handoff` 回合。它不是业务 StageManager 中新增的一行，也不能派发给 Sub。

| 工具 | 行为 |
| --- | --- |
| `ListWorkflows` | 查看允许的候选、用途、输入/输出要求及不可用原因 |
| `RequestNextWorkflow` | 提交目标、理由、摘要、文件映射和当前 `transition_token`；返回 accepted 后立即让出 |
| `CompleteWorkflowChain` | 明确结束整条链，记录结果与理由 |
| `PauseWorkflow` | 使用当前 `planning_token` 暂停并说明缺失的信息 |
| `WorkflowTransitionStatus` | 查询已保存的链、运行和交接状态 |

请求示例：

```json
{
  "workflow_ref": "relay-sink:consume",
  "reason": "The validated payload still needs the requested increment.",
  "summary": "The producer preserved value=7 and operation=increment.",
  "inputs": {"inputs/payload.json": "result_a/payload.json"},
  "transition_token": "<CurrentTips.handoff.transition_token>"
}
```

accepted 只表示请求已持久化，不表示 B 已就绪。框架等待当前模型和工具响应结束，然后复制输入、构造 B、检查就绪、记录 commit、清理 A、切换控制路由，最后启动 B。B 的就绪预检可以建立模型客户端或 CLI/MCP 端点及检查 CLI 配置，但不会执行业务模型回合。

启动失败时 A 的业务完成状态保留，故障反馈回 A 的 Super；只有失败候选真正清理后才能重试。commit 后后继身份固定，不能回到 A 另选目标。超时不能强行终止 Python 初始化线程：仍在执行的准备或清理会保留所有权并显示 pending，不会释放第二个候选。

## 插件声明与输入隔离

`PluginWorkflow` 可声明 `purpose`、`inputs` 和 `outputs`：

```python
PluginWorkflow(
    name="consume",
    config_file=root / "workflows/consume.yaml",
    guide_doc_paths=(root / "Guide_Doc",),
    purpose="Increment a validated integer payload.",
    inputs={"inputs/payload.json": "Integer value and operation=increment"},
    outputs={"result_b/result.json": "Incremented value and source_sha256"},
)
```

这些元数据会经过真实插件加载器保留。输入映射必须完整匹配目标声明；源文件必须是当前工作流声明的输出产物。第一版使用精确文件名，不接受目录或通配符。JSON 的字段类型和内容仍由具体 Checker 验证，目录描述本身不是业务验收证据。

框架复制独立文件，不使用硬链接，拒绝路径越界、符号链接和隐藏状态文件；在接受请求、复制以及恢复时核对 SHA-256。新工作区不会复制源 `.ucagent`、Guide_Doc、Skills 或 CLI 认证文件。输入置为只读，并加入目标工具的禁止写入范围。

每次复制生成 `runs/<run-id>/handoff.json`，链记录保存相同来源、目标、大小和摘要。Sub 的 `CurrentTips.handoff_inputs` 提供受信任输入 hash，Checker 可以独立重算。A/B 的阶段历史、权限、工具、backend 会话互相独立。Langfuse 客户端按连接共享引用计数，最后一个拥有者退役后才关闭。

## 控制与恢复

Console 的 `status` 返回当前 run、历史、业务状态和交接状态；`agent_break` 暂停整条链，`continue`/`c` 恢复，`quit`/`q`/`shutdown` 收拢全部实例。SIGINT 暂停，SIGTERM 关闭。TUI 脱离保留原有语义。启动时配置的公共命令服务由应用持有，不随 A 退役关闭。

公共 HTTP 的在途写请求会纳入交接收拢，交接期间业务写入返回明确错误，状态、暂停和关闭继续可用。公共 HTTP 控制端点在 GET 响应中返回 `X-UCAgent-Run-ID`。**所有写请求必须回传当前值**；过期或缺失返回 409。发生切换后，客户端先重新 GET `/api/runtime/status` 再写入。内置 Agent 页面自动携带该请求头；检测到工作流切换后会要求刷新页面再提交编辑或命令，以免旧编辑内容被写入新工作流。自定义客户端需要遵循相同规则。命令会话也有 run 栅栏；旧会话须刷新 `status`。每个 Super/Sub 的私有 MCP 地址与授权独立；旧 Agent 的 MCP 工具不会转发成 B 的工具。启动时显式开启的公共 MCP 保留初始 Agent 身份，可读取其历史，不能用来操作后继；跨 run 的操作使用应用控制入口。

恢复时使用相同启动参数，并增加：

```yaml
workflow_handoff:
  # 其余策略保持原值
  resume_chain: /absolute/path/to/existing/relay-chain
```

恢复先取得文件锁，校验链策略、实际源配置、执行配置、插件源码/资源和目标配置指纹，再恢复阶段历史：

- 未 commit：已清理的候选记为失败尝试，A 回到交接回合，A 业务不重跑。
- 已 commit：保留唯一后继 ID，恢复 B 自己的工作区和阶段历史。
- 已完成：返回已有结果，不启动新的业务。
- 非正常终止、无法核验旧外部进程、配置变动或清理错误：明确拒绝自动恢复，保留现场供操作员核对。

自动恢复只接受 `quiescent=true` 的已收拢检查点。它不是完整 Sub 队列、任意外部副作用或硬崩溃后孤儿进程的自动恢复机制。不要手工把未核对的检查点改成 quiescent。关闭后端进程、撤销外部副作用的通用自动协调不在本版范围。

## 两个小插件自测

测试插件位于 `tests/fixtures/workflow_relay/plugins/`，不作为默认生产插件发布：

- `relay_source` / `relay-source:produce`：读取 `inputs/request.json`，生成严格校验的 `result_a/payload.json`。
- `relay_sink` / `relay-sink:consume`：新工作区读取 payload，生成加一结果及输入 hash；真实 Checker 校验算术和输入未变。

从仓库根目录运行离线验证：

```bash
.venv/bin/python -m pytest -q tests/test_workflow_contracts.py tests/test_workflow_decisions.py tests/test_workflow_runtime.py tests/test_workflow_checkpoint.py tests/test_workflow_relay.py
```

测试同时覆盖可控 LangChain 模型和真实 CLI 子进程/MCP 传输。后者验证协议和生命周期，不是真实模型推理。

使用当前仓库 `config.yaml` 的有效模型连接进行一次真实模型自测：

```bash
UCAGENT_RELAY_ONLINE=1 .venv/bin/python -m pytest -q tests/test_workflow_relay.py::test_configured_real_model_relay
```

该测试只继承连接设置，关闭测试追踪，使用临时工作区；不会改写用户 `config.yaml`。实际测试记录见[工作流接力验证记录](../03_develop/11_workflow_handoff_validation.md)。两个插件的通过不代表大型 DUT、EDA、跨 backend、共享可写工作区或生产插件已通过接力验证。
