
## 自定义后端

UCAgent 内置了 `langchain` 后端用于与 LLM 进行交互（需配置 OPENAI_API_BASE 等环境变量）。此外，用户可根据需求自定义后端，或利用内置的 `UCAgentCmdLineBackend` 快速集成 Claude Code 等命令行工具。

默认后端配置示例（见 `ucagent/setting.yaml`）：

```yaml
backend:
  key_name: "langchain"  # 可选值: langchain, claude_code, opencode 等
  langchain:
    clss: ucagent.abackend.langchain.UCAgentLangChainBackend
  claude_code:
    clss: ucagent.abackend.UCAgentCmdLineBackend
    args:
      cli_cmd_new: "claude --dangerously-skip-permissions -p < {MSG_FILE}"
      cli_cmd_ctx: "claude --dangerously-skip-permissions -c -p < {MSG_FILE}"
      pre_bash_cmd:
        - "mkdir -p {CWD}/.claude/"
        - "cp ~/.claude/.mcp.json {CWD}/.mcp.json" # 确保已使用 claude mcp add --scope project ... 添加server，并备份到了 ~/.claude/.mcp.json
        - "sed -i \"s/5000\/mcp/{PORT}\/mcp/\" {CWD}/.mcp.json" # 动态修改mcp端口(5000)为配置的端口
  opencode:
    clss: ucagent.abackend.UCAgentCmdLineBackend
    args:
      cli_cmd_new: "opencode run < {MSG_FILE}"
      cli_cmd_ctx: "opencode run -c < {MSG_FILE}"
    pre_bash_cmd:
      - "cp ~/.config/opencode/opencode.json {CWD}/opencode.json" # 需提前准备好 opencode 配置文件
      - "sed -i \"s/5000\/mcp/{PORT}\/mcp/\" {CWD}/opencode.json"
```


### 切换后端

可通过以下两种方式指定使用的后端：

1. **命令行参数**：运行 `ucagent` 时添加 `--backend <backend_name>` 参数。
2. **配置文件**：在 `custom.yaml` 中修改 `backend.key_name` 的值。

### 开发自定义后端

你可以通过以下两种方式扩展后端功能：

#### 方式一：继承基类（推荐用于深度定制）

1. 创建一个新的 Python 类，继承自 `ucagent.abackend.base.AgentBackendBase`。
2. 实现基类中定义的所有抽象方法。
3. 在 `custom.yaml` 中注册该后端类（配置格式参考 `langchain`）。

#### 方式二：封装命令行工具（推荐用于集成现有 Agent）

利用 `UCAgentCmdLineBackend` 通用封装器，通过配置文件即可集成支持 CLI 交互的 Agent（如 Claude Code, iFlow CLI 等）。

**Claude Code 集成示例：**

`UCAgentCmdLineBackend` 通过文件传递消息并调用外部 CLI 工具。以下是集成 Claude Code 的完整配置：

```yaml
backend:
  key_name: "claude_code"
  claude_code:
    clss: ucagent.abackend.UCAgentCmdLineBackend
    args:
      # 首次启动会话时执行的命令（可选）
      # {MSG_FILE} 会被自动替换为包含当前提示词的临时文件路径
      cli_cmd_new: "claude --dangerously-skip-permissions -p < {MSG_FILE}"
      
      # 后续交互时执行的命令
      # 通常需要包含“继续会话”的参数（如 -c），以保持上下文
      cli_cmd_ctx: "claude --dangerously-skip-permissions -c -p < {MSG_FILE}"
      
      # 后端初始化前执行的预处理命令列表
      # 支持变量替换：{CWD} (当前工作目录), {PORT} (MCP 服务器端口)
      # 示例逻辑：将预先配置好的 .mcp.json (含 UCAgent server 配置) 复制到当前项目并在启动前替换端口
      pre_bash_cmd:
        - "mkdir -p {CWD}/.claude/"
        - "cp ~/.claude/.mcp.json {CWD}/.mcp.json"
        # 动态修改配置中的端口号，确保 MCP 连接正确
        - "sed -i \"s/5000\/mcp/{PORT}\/mcp/\" {CWD}/.mcp.json"
```

**配置参数详解：**

- `cli_cmd_new`: (可选) 首次调用时执行的命令。若未配置，则始终使用 `cli_cmd_ctx`。
- `cli_cmd_ctx`: (必填) 标准交互命令。
- `pre_bash_cmd`: (可选) 初始化阶段执行的 bash 命令列表，常用于环境准备或配置注入。
- `post_bash_cmd`: (可选) 退出阶段执行的清理命令列表。
- `abort_pattern`: (可选) 正则表达式列表。若工具输出匹配其中任意模式，将视为终止信号。
- `max_continue_fails`: (可选) 允许的最大连续失败次数（默认 20），超过此阈值将强制中断执行。

通过这种配置驱动的方式，你可以轻松地将 iFlow CLI、Gemini CLI 等任何支持标准输入/输出交互的 Agent 集成到 UCAgent 生态中。


#### 举例（使用ClaudeCode驱动UCAgent）

先配置好claude，确保以下命令可用。
```
claude --dangerously-skip-permissions -c -p 'Ni hao'
```

然后在UCAgent目录中运行

```bash
make mcp_Adder ARGS="--backend=claude_code --loop"
```
