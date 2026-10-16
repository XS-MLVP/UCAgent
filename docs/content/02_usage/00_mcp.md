
# MCP 集成模式（推荐）

## MCP 集成（推荐）集成 Code Agent

**注：以下输出目录以`output`为例，可自行修改为其他目录**。

基于 MCP 的外部编程 CLI 协作方式。该模式能与所有支持 MCP-Server 调用的 LLM 客户端进行协同验证，例如：Cherry Studio、Claude Code、 Gemini-CLI、VS Code Copilot、Qwen-Code 等。
平常使用是直接使用`make`命令的，要看详细命令可参考[MCP 集成协同模式](../01_start/03_mcp_mode.md)，也可以直接查看项目根目录的`Makefile`文件。

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

## UCAgent 自动启动 Codex 后端

使用 `--backend codex` 且配置 `OPENAI_API_BASE` 时，默认启动命令将
`CODEX_HOME` 指向任务工作目录的 `.codex`，首次运行与续跑均加载该目录的
`config.toml`。配置选择 `ucagent` Provider，并通过 `OPENAI_API_KEY` 环境变量
认证；密钥不会写入模板。新版 Codex 忽略项目级 Provider 配置，因此不能仅将
文件写入项目 `.codex` 而继续使用个人 Codex home。

未配置 `OPENAI_API_BASE` 时，启动命令不覆盖原 `CODEX_HOME`，保留个人登录方式。
默认 `cfg_bash_enable=false`，不会将任务配置复制到 `~/.codex/config.toml`。
