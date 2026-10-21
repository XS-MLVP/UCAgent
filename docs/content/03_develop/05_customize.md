
# 定制工具

工具提供 Agent 执行任务所需的能力，例如解析文件、统计数据、运行仿真或访问领域服务。推荐继承 `UCTool`，获得调用计数、超时、进度反馈和 MCP 转换支持；验收规则放在 [Checker](07_checkers.md) 中。

## 一个可运行的工具

将下面的代码保存为可导入的 `my_tools.py`：

```python
"""Example tool that greets a named recipient."""

from pydantic import BaseModel, Field
from ucagent.tools.uctool import UCTool


class HelloArgs(BaseModel):
    """Arguments accepted by the Hello tool."""

    who: str = Field(min_length=1, description="Name of the recipient")


class HelloTool(UCTool):
    """Return a greeting for a named recipient."""

    name: str = "Hello"
    description: str = "Return a greeting for the specified recipient."
    args_schema: type[BaseModel] = HelloArgs

    def _run(self, who: str, run_manager=None) -> dict:
        """Build the greeting without external side effects."""
        return {"greeting": f"Hello, {who}!"}
```

工具应有唯一 `name`、明确 `description` 和带字段说明的 `args_schema`。返回字符串或结构化数据均可；Agent 需要继续使用字段时，优先返回字典。不要在构造函数中执行实际任务。

## 注册和调用

在启动 UCAgent 的环境中确保模块可导入，例如使用 `--append-py-path <module-directory>`。然后在项目配置中注册：

```yaml
ex_tools:
  - my_tools.HelloTool
```

临时注册可以使用 `--ex-tools my_tools.HelloTool`。配置和 CLI 中的外部工具都会被装配；配置文件之间的 `ex_tools` 列表仍遵循整体替换规则。工具类或工厂需要支持零参调用。

内置短名从 `ucagent.tools` 导出，目前通过 `ucagent/tools/__init__.py` 的延迟导出映射维护。项目工具通常使用完整模块路径即可。需要运行时上下文、包内资源或独立分发时，使用[插件](09_plugins.md)。

本地测试：

```python
from my_tools import HelloTool
from ucagent.tools.uctool import to_mcp_tool

tool = HelloTool()
assert tool.invoke({"who": "UCAgent"}) == {"greeting": "Hello, UCAgent!"}
mcp_tool = to_mcp_tool(tool)
assert mcp_tool.name == "Hello"
```

启动后可以用 `tool_list` 查看工具，用 `tool_invoke Hello who='UCAgent'` 调用。

## 文件路径与权限

文件工具应使用 `BaseReadWrite` 的路径和权限校验，避免依赖进程当前目录或直接对用户输入调用 `os.path.abspath()`：

```python
"""Example workspace-aware text statistics tool."""

from pathlib import Path
from pydantic import BaseModel, Field
from ucagent.tools.fileops import BaseReadWrite
from ucagent.tools.uctool import UCTool


class TextLengthArgs(BaseModel):
    """Workspace-relative text file to inspect."""

    path: str = Field(description="Workspace-relative UTF-8 text file path")


class TextLength(UCTool, BaseReadWrite):
    """Count characters in a validated workspace file."""

    name: str = "TextLength"
    description: str = "Count characters in a UTF-8 text file inside the workspace."
    args_schema: type[BaseModel] = TextLengthArgs

    def _run(self, path: str, run_manager=None) -> dict:
        """Validate the input file and return its character count."""
        ok, error, real_path = self.check_file(path)
        if not ok:
            return {"error": error, "next_action": "provide an existing workspace-relative file"}
        try:
            text = Path(real_path).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            return {"error": str(exc), "next_action": "provide a readable UTF-8 text file"}
        return {"path": path, "characters": len(text)}
```

上例还需要初始化工作区上下文，不能直接作为零参 `ex_tools` 使用。独立测试时，先执行 `tool = TextLength()`，再调用 `tool.init_base_rw(workspace, write_dirs=[], un_write_dirs=[])`。正式扩展推荐通过[插件工具工厂](09_plugins.md)接收 workspace 和读写策略并完成初始化；普通 `ex_tools` 装配器不会自动注入这些值。

`get_real_path` 解析工作区路径；`check_file` 检查文件并返回 `(ok, error, real_path)`。写入工具要使用 `check_file(path, for_write=True, allow_missing=True)`，同时处理父目录、已有文件和失败回滚。不要绕过配置的可写/禁止写入目录。

## 通过 MCP 暴露

`to_mcp_tool` 要求 `args_schema` 是 Pydantic `BaseModel`，不支持 LangChain injected arguments。加入外部工具列表后，工具会随 UCAgent 的 MCP Server 暴露：

- `--mcp-server`：包含文件操作工具组。
- `--mcp-server-no-file-tools`：省略该组；基础 `ReadTextFile` 和外部工具仍会暴露，因此自定义工具必须自行遵守权限。
- 默认端点：`http://127.0.0.1:5000/mcp`，地址由 MCP host/port 参数控制。

控制台也可以执行 `start_mcp_server [host] [port]`，或 `start_mcp_server --no-file-ops [host] [port]`。

下面使用随 UCAgent 依赖安装的 MCP SDK，无需另装 `fastmcp` 客户端包：

```python
"""Call the Hello tool on a running UCAgent MCP server."""

import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    """Discover tools and invoke Hello within the client session."""
    async with streamable_http_client("http://127.0.0.1:5000/mcp") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print(await session.list_tools())
            print(await session.call_tool("Hello", {"who": "UCAgent"}))


if __name__ == "__main__":
    asyncio.run(main())
```

## 长任务与排查

长任务可以在 `_run` 中调用 `self.put_alive_data(message)` 报告进度。MCP 调用需要日志推送时，可启用 `sync_block_log_to_client`。UCAgent 默认工具超时来自 `setting.yaml` 的 `call_time_out`；客户端还需配置足够的调用超时。

工具未出现时，先检查模块导入、零参构造、`ex_tools`、忽略列表和 `args_schema`；调用失败时，再检查输入路径、权限、依赖和超时。测试应覆盖成功、缺文件、非法路径和错误输入，且验证本地调用与 MCP 转换。

完整工作流中的工具实现见 [Mini 示例](08_mini_example.md)；独立扩展的上下文和交付方式见[插件开发与发布](09_plugins.md)。
