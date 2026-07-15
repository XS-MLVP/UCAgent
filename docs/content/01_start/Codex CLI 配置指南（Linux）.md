# Codex CLI 配置指南（Linux）

本文档介绍如何在 Linux 上安装和配置 Codex CLI，使其连接不同的大语言模型，并与 UCAgent 协同工作。
---

## 1. 基本概念

### 什么是 Code Agent

Code Agent（编程智能体）是一种 AI 工具，它能理解自然语言指令，自主地读写文件、执行命令、调用工具来完成软件工程任务。与普通的 AI 对话不同，Agent 可以**直接操作你的项目**——创建文件、运行测试、修复 bug，而不仅仅是给你一段代码让你自己粘贴。

### 什么是 Codex CLI

Codex CLI 是 OpenAI 开源的终端编程代理。它在命令行中运行，接收你的指令，通过大语言模型进行推理，并调用本地工具（读写文件、执行 shell 命令等）来完成任务。

```
你 → Codex CLI → 大语言模型 → 决策 → 调用工具 → 观察结果 → 继续推理 → ...
```

### 为什么需要配置

Codex CLI 默认连接 OpenAI 的 API。如果你需要使用其他模型（如 DeepSeek），或者需要接入 UCAgent 提供的 MCP 工具服务器，就需要手动配置。配置的核心是告诉 Codex：

1. **用哪个模型** — 模型名称和 API 地址
2. **怎么通信** — API 协议格式
3. **有哪些工具** — MCP 服务器地址和工具权限

---

## 2. 安装 Codex CLI

### 前置条件

- **Node.js** 18+（推荐 LTS 版本）
- **npm**（随 Node.js 一起安装）
  验证 Node.js 是否已安装：
  
  ```bash
  node --version # 应输出 v18.x 或更高
  npm --version
  ```
  
  如未安装，可从 [Node.js 官网](https://nodejs.org/) 下载，或使用包管理器：
  
  ```bash
  # Ubuntu/Debian
  curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
  sudo apt install -y nodejs
  ```
  
  ### 安装 Codex
  
  ```bash
  sudo npm install -g @openai/codex
  ```
  
  验证安装：
  
  ```bash
  codex --version
  ```

---

## 3. 核心配置文件

Codex 的配置文件位于 `~/.codex/config.toml`。首次运行 Codex 时会自动创建该文件。以下是完整的配置项说明。

### 3.1 全局设置

```toml
# 指定使用哪个模型提供商（对应下方 [model_providers.xxx] 的名称）
model_provider = "deepseek"
# 模型名称，需与提供商支持的模型名一致
model = "deepseek-v4-pro"
# 推理深度：low / medium / high / xhigh
# 越高越适合复杂任务，但消耗更多 token
model_reasoning_effort = "high"
# 禁止 OpenAI 存储你的请求/响应数据（隐私保护）
disable_response_storage = true
# 是否允许模型访问网络（如 curl 下载文件）
# "enabled" 允许，"disabled" 禁止
network_access = "enabled"
```

### 3.2 模型提供商 `[model_providers.xxx]`

定义模型的 API 端点和通信方式。可以配置多个提供商，通过 `model_provider` 切换。

```toml
[model_providers.deepseek]
name = "deepseek"
# API 基础地址
# 直连 DeepSeek：https://api.deepseek.com/v1
# 通过本地代理：http://localhost:4444/v1
base_url = "http://localhost:4444/v1"
# API 协议格式（关键配置）
# "responses" — OpenAI Responses API（新版 Codex 强制要求此值）
wire_api = "responses"
# 认证方式：指定环境变量名，Codex 从中读取 API Key
env_key = "DEEPSEEK_API_KEY"
```

> **关于 `wire_api`**：新版 Codex（v0.140+）已移除 `wire_api = "chat"` 的支持，只允许 `"responses"`。如果你的模型提供商不支持 Responses API（如 DeepSeek），需要通过本地代理做协议转换，详见第 4 节。

### 3.3 项目信任级别 `[projects.xxx]`

控制 Codex 在不同目录下的权限。

```toml
[projects."/home/user/myproject"]
# "trusted" — 自动批准文件读写和命令执行
# 不设置 — 每次操作都需要手动确认
trust_level = "trusted"
```

### 3.4 MCP 服务器 `[mcp_servers.xxx]`

MCP（Model Context Protocol）是 Agent 调用外部工具的标准协议。通过配置 MCP 服务器，Codex 可以使用 UCAgent 提供的验证工具。

```toml
[mcp_servers.unitytest]
# MCP 服务器的 HTTP 地址
url = "http://localhost:5000/mcp"
# 可选：为单个工具设置审批模式
# "approve" — 自动批准（适合信任的工具）
# 不设置 — 每次调用需手动确认
[mcp_servers.unitytest.tools.RoleInfo]
approval_mode = "approve"
[mcp_servers.unitytest.tools.ReadTextFile]
approval_mode = "approve"
[mcp_servers.unitytest.tools.Check]
approval_mode = "approve"
```

常用 UCAgent MCP 工具：
| 工具名 | 功能 |
| ------------------------ | ----------- |
| `RoleInfo` | 获取角色信息和任务指导 |
| `ReadTextFile` | 读取工作区文件 |
| `Detail` | 查看任务阶段详情 |
| `Check` | 检查当前阶段实现 |
| `Complete` | 标记阶段完成 |
| `RunTestCases` | 执行测试用例 |
| `AllStageJournal` | 查看所有阶段日志 |
| `SetCurrentStageJournal` | 设置当前阶段日志 |

---

## 4. 模型接入方案

### 方案 A：直接使用 OpenAI

最简单的方案，适合有 OpenAI API Key 的用户。

```toml
model_provider = "openai"
model = "gpt-5.6-Sol"
model_reasoning_effort = "high"
disable_response_storage = true
[model_providers.openai]
name = "openai"
base_url = "https://api.openai.com/v1"
wire_api = "responses"
requires_openai_auth = true
```

然后在 `~/.codex/auth.json` 中设置 API Key：

```json
{
 "OPENAI_API_KEY": "sk-your-openai-api-key"
}
```

或者直接设置环境变量：

```bash
export OPENAI_API_KEY="sk-your-openai-api-key"
```

### 方案 B：使用 DeepSeek（国内推荐）

DeepSeek 提供与国内兼容的高性价比 API，但存在协议差异：

- **Codex** 使用 OpenAI Responses API（`/v1/responses`）
- **DeepSeek** 只提供 Chat Completions API（`/v1/chat/completions`）
  因此需要一个本地代理来做协议转换。使用 **codex-relay**。
  
  #### 方案 B：使用 codex-relay（推荐）
  
  codex-relay 是一个轻量级的协议转换代理，将 Codex 的 Responses API 请求转换为 DeepSeek 的 Chat Completions API。
  **安装**
  从 [codex-relay 发布页](https://github.com/nicepkg/codex-relay/releases) 下载 Linux 版本并解压，将可执行文件放到 PATH 中：
  
  ```bash
  # 下载 
  pip install codex-relay
  ```
  
  验证安装：
  
  ```bash
  codex-relay --version
  ```
  
  安装完成后，完成环境变量配置，并运行以下命令：
  
  ```
  export DEEPSEEK_API_KEY="你的DeepSeek API Key"
  codex-relay --print-config \
  --upstream https://api.deepseek.com/v1 \
  --api-key $DEEPSEEK_API_KEY
  ```
  
  按照codex-relay的指示，将配置信息复制到`.codex/config.toml`里，将base_url改为`"http://localhost:4444/v1"`
  
  ```toml
  model_provider = "deepseek"
  model = "deepseek-v4-pro"
  model_reasoning_effort = "high"
  disable_response_storage = true
  [model_providers.deepseek]
  name = "deepseek"
  base_url = "http://localhost:4444/v1"
  wire_api = "responses"
  env_key = "DEEPSEEK_API_KEY"
  ```
  
  修改.codex/auth.json 中的API key
  
  ```json
  {
  "OPENAI_API_KEY": "your-API-key-here
  }
  ```
  
  **使用流程**
  每次使用 Codex 前，需要先启动 codex-relay：
  
  ```bash
  # 终端 1：启动 codex-relay
  codex-relay --upstream https://api.deepseek.com/v1 --api-key "$DEEPSEEK_API_KEY"
  ```
  
  然后在另一个终端启动 Codex：
  
  ```bash
  # 终端 2：启动 Codex
  codex
  ```
  
  **codex-relay 参数说明**
  
  | 参数           | 环境变量                   | 默认值                            | 说明         |
  | ------------ | ---------------------- | ------------------------------ | ---------- |
  | `--port`     | `CODEX_RELAY_PORT`     | `4444`                         | 监听端口       |
  | `--bind`     | `CODEX_RELAY_BIND`     | `127.0.0.1`                    | 绑定地址       |
  | `--upstream` | `CODEX_RELAY_UPSTREAM` | `https://openrouter.ai/api/v1` | 上游 API 地址  |
  | `--api-key`  | `CODEX_RELAY_API_KEY`  | 空                              | 上游 API Key |
  
  ```bash
  # 检查 relay 是否在运行
  curl -s http://localhost:4444/v1/models
  # 应返回模型列表，如：
  # {"data":[{"id":"deepseek-v4-flash",...},{"id":"deepseek-v4-pro",...}]}
  ```
  
  
  
  ### 方案 C：使用通义千问 Qwen
  
  通义千问（Qwen）是阿里云的大语言模型，提供 OpenAI 兼容的 API，可以直接被 Codex 调用，**无需额外的协议转换代理**。
  **获取 API Key**
1. 访问 [阿里云百炼平台](https://bailian.console.aliyun.com/)，注册并登录
2. 在「API Key 管理」中创建 API Key
   **可用模型**
   
   | 模型名称                | 说明              |
   | ------------------- | --------------- |
   | `qwen3-coder-plus`  | 代码增强模型，推荐用于编程任务 |
   | `qwen3-coder-flash` | 代码模型轻量版，响应更快    |
   | `qwen3-max`         | 通用旗舰模型          |
   | `qwen3.6-plus`      | 通用增强模型          |
   | **config.toml 配置**  |                 |
   
   ```toml
   model_provider = "qwen"
   model = "qwen3-coder-plus"
   model_reasoning_effort = "high"
   disable_response_storage = true
   [model_providers.qwen]
   name = "qwen"
   base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
   wire_api = "responses"
   requires_openai_auth = true
   ```
   
   **auth.json**
   
   ```json
   {
   "OPENAI_API_KEY": "sk-your-dashscope-api-key"
   }
   ```
   
   > **说明**：通义千问的 DashScope API 原生支持 OpenAI Responses API 格式，因此不需要像 DeepSeek 那样配置本地代理。直接配置 `base_url` 指向 DashScope 端点即可。

---

## 5. 与 UCAgent 集成

### 5.1 什么是 MCP

MCP（Model Context Protocol）是一种标准协议，让 AI Agent 能够调用外部工具。在 UCAgent 的场景中：

- **UCAgent MCP Server** 提供验证相关的工具（读文件、跑测试、检查进度等）
- **Codex** 作为 MCP Client，通过 HTTP 连接 MCP Server，调用这些工具完成任务
  
  ### 5.2 启动 UCAgent MCP Server
  
  **前置准备**（如果尚未完成）：
  
  ```bash
  # 安装 UCAgent
  pip3 install git+https://git@github.com/XS-MLVP/UCAgent@main
  # 将 RTL 导出为 Python 包（在包含源文件的目录下执行）
  picker export <源文件>.v --rw 1 --sname <DUT名> --tdir output/ -c -w output/<DUT名>/<DUT名>.fst
  ```
  
  **启动 MCP Server**：
  方式一：使用完整命令
  
  ```bash
  ucagent <workspace> <dut_name> -s -hm --tui --mcp-server-no-file-tools --no-embed-tools
  ```
  
  方式二：使用 Makefile 快捷命令（如果项目提供了 Makefile）
  
  ```bash
  make mcp_<dut_name>
  ```
  
  例如：
  
  ```bash
  # 完整命令
  ucagent output/ Adder -s -hm --tui --mcp-server-no-file-tools --no-embed-tools
  # 或 Makefile 快捷方式
  make mcp_Adder
  ```
  
  MCP Server 默认监听 `http://localhost:5000/mcp`。启动后会显示 TUI 界面，可以在其中查看任务进度。
  
  ### 5.3 配置 Codex 连接 MCP Server
  
  在 `~/.codex/config.toml` 中添加 MCP 服务器配置：
  
  ```toml
  [mcp_servers.unitytest]
  url = "http://localhost:5000/mcp"
  # 为常用工具设置自动审批
  [mcp_servers.unitytest.tools.RoleInfo]
  approval_mode = "approve"
  [mcp_servers.unitytest.tools.ReadTextFile]
  approval_mode = "approve"
  [mcp_servers.unitytest.tools.Detail]
  approval_mode = "approve"
  [mcp_servers.unitytest.tools.AllStageJournal]
  approval_mode = "approve"
  [mcp_servers.unitytest.tools.SetCurrentStageJournal]
  approval_mode = "approve"
  [mcp_servers.unitytest.tools.Complete]
  approval_mode = "approve"
  [mcp_servers.unitytest.tools.Check]
  approval_mode = "approve"
  [mcp_servers.unitytest.tools.RunTestCases]
  approval_mode = "approve"
  ```
  
  ### 5.4 启动 Codex 并开始工作
  
  ```bash
  # 终端 1：启动 codex-relay（如果使用 DeepSeek）
  codex-relay --upstream https://api.deepseek.com/v1 --api-key "$DEEPSEEK_API_KEY"
  # 终端 2：进入工作目录（通常是 UCAgent 的 output 目录）
  cd <workspace>/output
  # 启动 Codex
  codex
  ```
  
  启动后输入提示词：
  
  > 请通过工具 RoleInfo 获取你的角色信息和基本指导，然后完成任务。请使用工具 ReadTextFile 读取文件。你需要在当前工作目录进行文件操作，不要超出该目录。
  > Codex 会自动调用 MCP 工具，按 UCAgent 的工作流推进验证任务。
  > **提示**：如果 Codex 中途停止但任务未完成，可以查看 MCP Server 的 TUI 界面确认进度，然后在 Codex 中输入"继续"来恢复执行。

---

## 6. 完整配置示例

以下是一个使用 DeepSeek + UCAgent 的完整 `~/.codex/config.toml` 示例：

```toml
# ===== 全局设置 =====
model_provider = "deepseek"
model = "deepseek-v4-pro"
model_reasoning_effort = "high"
disable_response_storage = true
# ===== 模型提供商 =====
[model_providers.deepseek]
name = "deepseek"
base_url = "http://localhost:4444/v1"
wire_api = "responses"
env_key = "DEEPSEEK_API_KEY"
# ===== 项目信任 =====
[projects."/home/user/workspace"]
trust_level = "trusted"
# ===== MCP 服务器（UCAgent）=====
[mcp_servers.unitytest]
url = "http://localhost:5000/mcp"
[mcp_servers.unitytest.tools.RoleInfo]
approval_mode = "approve"
[mcp_servers.unitytest.tools.ReadTextFile]
approval_mode = "approve"
[mcp_servers.unitytest.tools.Detail]
approval_mode = "approve"
[mcp_servers.unitytest.tools.AllStageJournal]
approval_mode = "approve"
[mcp_servers.unitytest.tools.SetCurrentStageJournal]
approval_mode = "approve"
[mcp_servers.unitytest.tools.Complete]
approval_mode = "approve"
[mcp_servers.unitytest.tools.Check]
approval_mode = "approve"
[mcp_servers.unitytest.tools.RunTestCases]
approval_mode = "approve"
```

---

## 7. 常见问题

### Q: 报错 `unexpected status 404 Not Found: url: https://api.deepseek.com/v1/responses`

**原因**：`base_url` 直接指向了 DeepSeek API，而 DeepSeek 不支持 `/v1/responses` 端点。
**解决**：确保 `base_url` 指向本地 codex-relay（`http://localhost:4444/v1`），而不是直接指向 DeepSeek。codex-relay 会将 Responses API 转换为 Chat Completions API。

### Q: 报错 `wire_api = "chat"` is no longer supported

**原因**：新版 Codex 已移除对 `wire_api = "chat"` 的支持。
**解决**：将 config.toml 中的 `wire_api` 设为 `"responses"`，然后通过 codex-relay 做协议转换。不要尝试改为 `"chat"`。

### Q: 报错 `Model metadata for 'xxx' not found`

**原因**：codex-relay 没有从上游获取到模型列表，或模型名称拼写错误。
**解决**：

```bash
# 检查 relay 是否正常运行
curl -s http://localhost:4444/v1/models
# 确认模型名称与上游返回的一致
```

### Q: 代理连接超时或拒绝连接

**排查步骤**：

```bash
# 检查 codex-relay 是否在运行
ps aux | grep codex-relay
# 检查端口是否可达
curl -s http://localhost:4444/v1/models
# 如果没有运行，重新启动
codex-relay --upstream https://api.deepseek.com/v1 --api-key "$DEEPSEEK_API_KEY"
```

### Q: MCP 工具调用时报错连接失败

**排查步骤**：

```bash
# 检查 UCAgent MCP Server 是否在运行
curl -s http://localhost:5000/mcp
# 确认 config.toml 中的 url 与实际端口一致
# 默认端口为 5000，可通过 ucagent 启动参数修改
```

### Q: 如何切换不同的模型

修改 config.toml 中的 `model_provider` 和 `model`，并确保对应的 `[model_providers.xxx]` 已正确配置。如果有多个提供商，可以快速切换：

```toml
# 切换到 OpenAI
model_provider = "openai"
model = "gpt-5.5"
# 切换到 DeepSeek
model_provider = "deepseek"
model = "deepseek-v4-pro"
```
