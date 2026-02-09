# 定制工具

!!! tip "完整定制工作流教程"
如果你想了解如何**从零开始创建自定义工作流**（包括添加工作流、工具、检查器、模板文件），请参考 [定制开发入门](01_quick_start.md) 和 [Mini 示例](08_mini_example.md)，这些文档提供了完整的示例代码和实战案例。

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
  - 全路径：`mypkg.mytools.HelloTool` / `mypkg.mytools.Factory`(文件夹名.文件名.工具名)

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
		args_schema: Type[BaseModel] = HelloArgs

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
		args_schema: Type[BaseModel] = ProgressArgs

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

---

## MiniWorkflow 示例：创建自定义工具

> 本节介绍如何为自定义工作流开发工具。
>
> 完整示例代码请参考：`examples/MiniWorkflow/my_tools.py`

### 为什么需要自定义工具

UCAgent 内置了丰富的通用工具（如 `ReadTextFile`、`EditTextFile`、`SearchText` 等），但对于特定领域的任务，我们需要开发自定义工具。

**典型场景**：

- 统计文档字数和段落数（需要特定的解析逻辑）
- 提取 Markdown 文档的章节结构（需要正则匹配）
- 解析 RTL 代码生成测试环境（需要调用 pyslang 库）
- 执行形式化验证工具（需要调用外部命令）

### 工具开发基础

#### 核心概念

1. **继承 UCTool 基类**：所有工具都继承自 `ucagent.tools.uctool.UCTool`
2. **定义参数模式**：使用 Pydantic 定义工具的输入参数
3. **实现 \_run 方法**：在 `_run` 方法中实现工具的核心逻辑
4. **处理路径**：使用 `self.get_path()` 处理文件路径
5. **返回结果**：返回字符串结果供 Agent 使用

#### 工具类结构

```python
from pydantic import BaseModel, Field
from ucagent.tools.uctool import UCTool
from ucagent.tools.fileops import BaseReadWrite


class MyToolArgs(BaseModel):
    """工具参数定义（使用 Pydantic）"""
    param1: str = Field(description="参数1的说明")
    param2: int = Field(default=10, description="参数2的说明")


class MyTool(UCTool, BaseReadWrite):
    """工具类（继承 UCTool 和 BaseReadWrite）"""

    # 工具的名称（Agent 调用时使用）
    name: str = "MyTool"

    # 工具的描述（Agent 通过描述了解工具用途）
    description: str = "这个工具做什么事情"

    # 工具的参数模式（指定参数类型和说明）
    args_schema: type[BaseModel] = MyToolArgs

    def _run(self, param1: str, param2: int = 10, run_manager=None) -> str:
        """
        执行工具逻辑

        参数:
            param1: 第一个参数
            param2: 第二个参数
            run_manager: 运行管理器（可选）

        返回:
            工具执行结果（字符串）
        """
        # 1. 处理输入参数
        # 2. 执行核心逻辑
        # 3. 返回结果
        return "执行结果"
```

### 示例工具：CountWords

这是一个统计 Markdown 文件字数的工具：

```python
import os
import re
from pydantic import BaseModel, Field
from ucagent.tools.uctool import UCTool
from ucagent.tools.fileops import BaseReadWrite


class CountWordsArgs(BaseModel):
    """CountWords 工具的参数定义"""
    file_path: str = Field(description="要统计字数的文件路径")


class CountWords(UCTool, BaseReadWrite):
    """
    统计文档字数工具

    功能：统计指定 Markdown 文件的字数和段落数
    """
    name: str = "CountWords"
    description: str = "统计指定 Markdown 文件的字数和段落数，返回统计信息"
    args_schema: type[BaseModel] = CountWordsArgs

    def _run(self, file_path: str, run_manager=None) -> str:
        # 处理路径（支持相对路径和变量替换）
        abs_path = os.path.abspath(file_path)

        # 检查文件是否存在
        if not os.path.exists(abs_path):
            return f"错误：文件不存在 - {file_path}"

        try:
            # 读取文件内容
            with open(abs_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 统计中文字符数
            chinese_chars = len(re.findall(r'[\u4e00-\u9fa5]', content))

            # 统计英文单词数
            english_words = len(re.findall(r'\b[a-zA-Z]+\b', content))

            # 总字数 = 中文字符数 + 英文单词数
            total_words = chinese_chars + english_words

            # 统计段落数（非空行数）
            paragraphs = len([line for line in content.split('\n') if line.strip()])

            # 返回统计结果
            return f"""字数统计结果：
- 总字数: {total_words} 字
- 中文字符: {chinese_chars} 字
- 英文单词: {english_words} 词
- 段落数: {paragraphs} 段
- 文件路径: {file_path}"""

        except Exception as e:
            return f"错误：统计字数失败 - {str(e)}"
```

### 工具注册

工具编写完成后，需要在工作流配置中注册：

```yaml
ex_tools:
  - "examples.MiniWorkflow.my_tools.CountWords"
  - "examples.MiniWorkflow.my_tools.ExtractSections"
```

### 工具开发技巧

#### 1. Description 编写原则

✅ **好的 description**：

```python
description: str = "统计指定 Markdown 文件的字数和段落数，返回统计信息"
```

- 明确说明功能
- 指出输入和输出
- Agent 能准确判断使用场景

❌ **不好的 description**：

```python
description: str = "统计工具"
```

- 太模糊，Agent 不知道统计什么

#### 2. 参数设计原则

- 参数名称要清晰：`file_path` 而不是 `path`
- 使用 `Field(description=...)` 详细说明参数用途
- 为可选参数设置合理的默认值

#### 3. 返回值设计

- 返回字符串，格式清晰易读
- 包含关键信息，方便 Agent 理解
- 出错时返回明确的错误信息

#### 4. 路径处理

- 对于 MCP Server 模式，使用 `os.path.abspath()` 直接处理路径
- 对于内部工具，可使用 `self.get_path()` 自动处理 workspace 前缀和变量替换
- 检查文件是否存在再操作

### 完整示例

MiniWorkflow 示例包含两个完整的自定义工具：

- `CountWords` - 统计文档字数工具
- `ExtractSections` - 提取文档章节结构工具

完整代码请参考 `examples/MiniWorkflow/my_tools.py`

## 相关文档

- [工具列表](06_tool_list.md) - 查看所有内置工具
- [工作流配置](03_workflow.md) - 了解如何在工作流中注册工具
- [快速开始](01_quick_start.md) - 快速创建自己的工作流
- [Mini 示例](08_mini_example.md) - 查看完整的可运行示例
