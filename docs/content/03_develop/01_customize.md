# 定制功能

## 添加工具与 MCP Server 工具

面向可修改本仓库代码的高级用户，以下说明如何：

- 添加一个新工具（供本地/Agent 内调用）
- 将工具暴露为 MCP Server 工具（供外部 IDE/客户端调用）
- 控制选择哪些工具被暴露与如何调用

涉及关键位置：

- `ucagent/tools/uctool.py`：工具基类 UCTool、to_fastmcp（LangChain Tool → FastMCP Tool）
- `ucagent/util/functions.py`：`import_and_instance_tools`（按名称导入实例）、`create_verify_mcps`（启动 FastMCP）
- `ucagent/verify_agent.py`：装配工具清单，`start_mcps` 组合并启动 Server
- `ucagent/cli.py` / `ucagent/verify_pdb.py`：命令行与 TUI 内的 MCP 启动命令

### 1) 工具体系与装配

- 工具基类 UCTool：
  - 继承 LangChain BaseTool，内置：call_count 计数、call_time_out 超时、流式/阻塞提示、MCP Context 注入（ctx.info）、防重入等。
  - 推荐自定义工具继承 UCTool，获得更好的 MCP 行为与调试体验。
- 运行期装配（VerifyAgent 初始化）：
  - 基础工具：RoleInfo、ReadTextFile
  - 嵌入工具：参考检索与记忆（除非 `--no-embed-tools`）
  - 文件工具：读/写/查找/路径等（可在 MCP 无文件工具模式下剔除）
  - 阶段工具：由 StageManager 按工作流动态提供
  - 外部工具：来自配置项 `ex_tools` 与 CLI `--ex-tools`（通过 `import_and_instance_tools` 零参实例化）
- 名称解析：
  - 短名：类/工厂函数需在 `ucagent/tools/__init__.py` 导出（例如 `from .mytool import HelloTool`），即可在 `ex_tools` 写 `HelloTool`
  - 全路径：`mypkg.mytools.HelloTool` / `mypkg.mytools.Factory`

### 2) 添加一个新工具（本地/Agent 内）

规范要求：

- 唯一 name、清晰 description
- 使用 pydantic BaseModel 定义 args_schema（MCP 转换依赖）
- 实现 \_run（同步）或 \_arun（异步）；继承 UCTool 可直接获得超时、流式与 ctx 注入

示例 1：同步工具（计数问候）

```python
from pydantic import BaseModel, Field
from ucagent.tools.uctool import UCTool

class HelloArgs(BaseModel):
		who: str = Field(..., description="要问候的人")

class HelloTool(UCTool):
		name: str = "Hello"
		description: str = "向指定对象问候，并统计调用次数"
		args_schema = HelloArgs

		def _run(self, who: str, run_manager=None) -> str:
				return f"Hello, {who}! (called {self.call_count+1} times)"
```

注册与使用：

- 临时：`--ex-tools mypkg.mytools.HelloTool`
- 持久：项目 `config.yaml`

```yaml
ex_tools:
	- mypkg.mytools.HelloTool
```

（可选）短名注册：在 `ucagent/tools/__init__.py` 导出 `HelloTool` 后，可写 `--ex-tools HelloTool`。

示例 2：异步流式工具（ctx.info + 超时）

```python
from pydantic import BaseModel, Field
from ucagent.tools.uctool import UCTool
import asyncio

class ProgressArgs(BaseModel):
		steps: int = Field(5, ge=1, le=20, description="进度步数")

class ProgressTool(UCTool):
		name: str = "Progress"
		description: str = "演示流式输出与超时处理"
		args_schema = ProgressArgs

		async def _arun(self, steps: int, run_manager=None):
				for i in range(steps):
						self.put_alive_data(f"step {i+1}/{steps}")  # 供阻塞提示/日志缓冲
						await asyncio.sleep(0.5)
				return "done"
```

说明：UCTool.ainvoke 会在 MCP 模式下注入 ctx，并启动阻塞提示线程；当 `sync_block_log_to_client=True` 时会周期性 `ctx.info` 推送日志，超时后返回错误与缓冲日志。

### 3) 暴露为 MCP Server 工具

工具 → MCP 转换（`ucagent/tools/uctool.py::to_fastmcp`）：

- 必须：args_schema 继承 BaseModel；不支持“注入参数”签名。
- UCTool 子类会得到 context_kwarg="ctx" 的 FastMCP 工具，具备流式交互能力。

Server 端启动：

- VerifyAgent.start_mcps 组合工具：`tool_list_base + tool_list_task + tool_list_ext + [tool_list_file]`
- `ucagent/util/functions.py::create_verify_mcps` 将工具序列转换为 FastMCP 工具并启动 uvicorn（`mcp.streamable_http_app()`）。

如何选择暴露范围：

- CLI：
  - 启动（含文件工具）：`--mcp-server`
  - 启动（无文件工具）：`--mcp-server-no-file-tools`
  - 地址：`--mcp-server-host`，端口：`--mcp-server-port`
- TUI 命令：`start_mcp_server [host] [port]` / `start_mcp_server_no_file_ops [host] [port]`

### 4) 客户端调用流程

FastMCP Python 客户端（参考 `tests/test_mcps.py`）：

```python
from fastmcp import Client

client = Client("http://127.0.0.1:5000/mcp", timeout=10)
print(client.list_tools())
print(client.call_tool("Hello", {"who": "UCAgent"}))
```

IDE/Agent（Claude Code、Copilot、Qwen Code 等）：将 `httpUrl` 指向 `http://<host>:<port>/mcp`，即可发现并调用工具。

### 5) 生命周期、并发与超时

- 计数：UCTool 内置 call_count；非 UCTool 工具由 `import_and_instance_tools` 包装计数。
- 并发保护：is_in_streaming/is_alive_loop 防止重入；同一实例不允许并发执行。
- 超时：`call_time_out`（默认 20s）+ 客户端 timeout；阻塞时可用 `put_alive_data` + `sync_block_log_to_client=True` 推送心跳。

### 6) 配置策略与最佳实践

- ex_tools 列表为“整体覆盖”，项目 `config.yaml` 需写出完整清单。
- 短名 vs 全路径：短名更便捷，全路径适用于私有包不修改本仓库时。
- 无参构造/工厂：装配器直接调用 `(...)()`，复杂配置建议在工厂内部处理（读取环境/配置文件）。
- 文件写权限：MCP 无文件工具模式下不要暴露写类工具；如需写入，请在本地 Agent 内使用或显式允许写目录。

#### 通过环境变量注入外部工具（EX_TOOLS）

配置文件支持 Bash 风格环境变量占位：`$(VAR: default)`。你可以让 `ex_tools` 从环境变量注入工具类列表（支持模块全名或 `ucagent.tools` 下的短名）。

1. 在项目的 `config.yaml` 或用户级 `~/.ucagent/setting.yaml` 中写入：

```yaml
ex_tools: $(EX_TOOLS: [])
```

2. 用环境变量提供列表（必须是可被 YAML 解析的数组字面量）：

```zsh
export EX_TOOLS='["SqThink","HumanHelp"]'
# 或使用完整类路径：
# export EX_TOOLS='["ucagent.tools.extool.SqThink","ucagent.tools.human.HumanHelp"]'
```

3. 启动后本地对话与 MCP Server 中都会出现这些工具。短名需要在 `ucagent/tools/__init__.py` 导出；否则请使用完整模块路径。

4. 与 CLI 的 `--ex-tools` 选项是合并关系（两边都会被装配）。

### 7) 常见问题排查

- 工具未出现在 MCP 列表：未被装配（ex_tools 未配置/未导出）、args_schema 非 BaseModel、Server 未按预期启动。
- 调用报“注入参数不支持”：工具定义包含 LangChain 的 injected args；请改成显式 args_schema 参数。
- 超时：调大 `call_time_out` 或客户端 timeout；在长任务中输出进度维持心跳。
- 短名无效：未在 `ucagent/tools/__init__.py` 导出；改用全路径或补导出。
