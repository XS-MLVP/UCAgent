
# Custom Tools

Tools provide the capabilities required for an Agent to execute tasks, such as parsing files, statistical analysis, running simulations, or accessing domain services. It is recommended to inherit `UCTool` to obtain call counting, timeout handling, progress feedback, and MCP conversion support; acceptance rules are located in [Checker](07_checkers.md).

## A Runnable Tool

Save the following code as an importable `my_tools.py`:

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

Tools should have a unique `name`, a clear `description`, and an `args_schema` with field descriptions. Returning strings or structured data is acceptable; however, if the Agent needs to continue using fields, a dictionary should be returned as a priority. Do not perform actual tasks in the constructor.

## Registration and Invocation

Ensure the module is importable in the UCAgent startup environment, for example by using `--append-py-path <module-directory>`. Then register it in the project configuration:

```yaml
ex_tools:
  - my_tools.HelloTool
```

Temporary registration can be done using `--ex-tools my_tools.HelloTool`. Both configuration and CLI external tools are assembled; the `ex_tools` list across configuration files still follows the overall replacement rule. Tool classes or factories must support zero-argument invocation.

Built-in short names are exported from `ucagent.tools` and are currently maintained via lazy export mapping in `ucagent/tools/__init__.py`. Project tools typically use the full module path. When runtime context, package resources, or independent distribution are required, use [plugins](09_plugins.md).

Local testing:

```python
from my_tools import HelloTool
from ucagent.tools.uctool import to_mcp_tool

tool = HelloTool()
assert tool.invoke({"who": "UCAgent"}) == {"greeting": "Hello, UCAgent!"}
mcp_tool = to_mcp_tool(tool)
assert mcp_tool.name == "Hello"
```

After startup, you can view tools using `tool_list` and invoke them using `tool_invoke Hello who='UCAgent'`.

## File Paths and Permissions

File tools should use the path and permission validation from `BaseReadWrite` to avoid relying on the current process directory or calling `os.path.abspath()` directly on user input:

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

The example above also requires initializing the workspace context and cannot be used directly as a zero-argument `ex_tools`. For independent testing, first execute `tool = TextLength()`, then call `tool.init_base_rw(workspace, write_dirs=[], un_write_dirs=[])`. It is recommended to use the [plugin tool factory](09_plugins.md) for formal extensions to receive the workspace and read/write strategy to complete initialization; standard `ex_tools` assemblers do not automatically inject these values.

`get_real_path` resolves workspace-relative paths; `check_file` validates the file and returns `(ok, error, real_path)`. Write tools must use `check_file(path, for_write=True, allow_missing=True)` and handle parent directories, existing files, and rollback on failure. Do not bypass configured writable or no-write directories.

## Exposure via MCP

The `to_mcp_tool` function requires `args_schema` to be a Pydantic `BaseModel` and does not support LangChain injected arguments. Once added to the external tools list, the tool will be exposed via UCAgent's MCP Server:

- `--mcp-server`: Includes the file operations tool group.
- `--mcp-server-no-file-tools`: Omits this group; the basic `ReadTextFile` and external tools are still exposed, so custom tools must adhere to permissions themselves.
- Default endpoint: `http://127.0.0.1:5000/mcp`, where the address is controlled by the MCP host/port parameters.

The console can also execute `start_mcp_server [host] [port]` or `start_mcp_server --no-file-ops [host] [port]`.

The following example uses the MCP SDK installed as a dependency of UCAgent, without needing to install the `fastmcp` client package separately:

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

## Long Tasks and Debugging

Long tasks can report progress by calling `self.put_alive_data(message)` within `_run`. For MCP calls requiring log pushing, `sync_block_log_to_client` can be enabled. The default tool timeout in UCAgent comes from `call_time_out` in `setting.yaml`; the client also needs to configure sufficient call timeouts.

If a tool is not found, first check module imports, zero-argument construction, `ex_tools`, ignore lists, and `args_schema`. If a call fails, then check input paths, permissions, dependencies, and timeouts. Tests should cover success, missing files, invalid paths, and erroneous inputs, verifying both local invocation and MCP conversion.

For tool implementations in a complete workflow, see [Mini Example](08_mini_example.md); context and delivery methods for independent extensions are covered in [Plugin Development and Release](09_plugins.md).
