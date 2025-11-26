

### 添加自定义工具

自定义工具允许你在 UCAgent 的流程中插入特定业务逻辑。下面的步骤概括了从编写到验证的完整流程，确保工具可被代理自动发现并调用。

#### 开发要求

创建工具类时需要：
- 继承 `ucagent.tools.uctool.UCTool`，以获得统一的初始化和参数校验逻辑
- 实现 `_run` 方法，在其中编写具体行为；方法应返回字符串或约定的数据结构
- 可选地参考 LangChain 的 [BaseTool 文档](https://langchain-doc.readthedocs.io/en/latest/modules/agents/examples/custom_tools.html#subclassing-the-basetool-class) 获取更丰富的设计范式

#### 示例实现

```python
#coding=utf-8
"""Custom tools for UCAgent."""

from ucagent.tools.uctool import UCTool


class MyCustomTool(UCTool):
    """A custom tool that performs a specific task."""
    name: str = "MyCustomTool"
    description: str = "This tool performs a custom operation defined by the user."

    def _run(self, run_manager=None) -> str:
        # Implement the custom logic here
        return "MyCustomTool has been executed successfully."
```

将工具保存为 Python 文件后，可通过 `-app` 与 `-et` 参数加载。例如：

```bash
ucagent -app path_to_python_file -et my_tools.MyCustomTool
```

其中：
- `path_to_python_file` 指向包含 `MyCustomTool` 类定义的脚本
- `my_tools.MyCustomTool` 为模块路径 + 类名，便于框架定位工具

#### 测试与验证

在当前目录中执行：

#### 测试

在本目录下运行：
```bash
make mcp_tool
```
执行成功后，启动 TUI 并打开工具面板，确认列表中出现 `MyCustomTool`。若工具未显示，检查模块路径是否正确、虚拟环境是否加载，以及 `_run` 方法是否抛出异常。

可通过命令`tool_invoke MyCustomTool`进行调用测试。
