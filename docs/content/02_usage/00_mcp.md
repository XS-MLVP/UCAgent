# MCP 集成模式（推荐）

## MCP 集成（推荐）集成 Code Agent

**注：以下输出目录以`output`为例，可自行修改为其他目录**。

基于 MCP 的外部编程 CLI 协作方式。该模式能与所有支持 MCP-Server 调用的 LLM 客户端进行协同验证，例如：Cherry Studio、Claude Code、 Gemini-CLI、VS Code Copilot、Qwen-Code 等。
平常使用是直接使用`make`命令的，要看详细命令可参考[快速开始](../01_start/02_quickstart.md)，也可以直接查看项目根目录的`Makefile`文件。

- 准备 RTL 和对应的 SPEC 文档放入`examples/{dut}`文件夹。`{dut}`是模块的名称，比如`Adder`，如果是`Adder`，目录则为`examples/Adder`。

- 打包 RTL，将文档放入工作目录并且启动 MCP server：`make mcp_{dut}`，`{dut}`为对应的模块。此处如果使用的`Adder`，则命令为`make mcp_Adder`

- 在支持 MCP client 的应用中配置 JSON：

  ```json
  {
  	"mcpServers": {
  		"unitytest": {
  			"httpUrl": "http://localhost:5000/mcp",
  			"timeout": 10000
  		}
  	}
  }
  ```

- 启动应用：此处使用的 Qwen Code，在`UCAgent/output`启动 qwen,然后输入提示词。
- 输入提示词：
  > 请通过工具`RoleInfo`获取你的角色信息和基本指导，然后完成任务。工具`ReadTextFile`读取文件。你需要在当前工作目录进行文件操作，不要超出该目录。
