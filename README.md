# UCAgent（UnityChip Verification Agent）

基于大模型进行自动化UT验证AI 代理

[English Introduction](/README.en.md)

### 项目简介

UCAgent 是一个基于大语言模型的自动化硬件验证AI代理，专注于芯片设计的单元测试(Unit Test)验证工作。该项目通过AI技术自动分析硬件设计，生成测试用例，并执行验证任务，大大提高了硬件验证的效。

**基本使用**
```bash
python3 ucagent.py <workspace> <dut_name>
```

参数：
```bash
usage: ucagent.py [-h] [--config CONFIG] [--template-dir TEMPLATE_DIR] [--template-overwrite]
                  [--output OUTPUT] [--override OVERRIDE] [--stream-output] [--human] [--seed SEED]
                  [--tui] [--sys-tips SYS_TIPS] [--ex-tools EX_TOOLS] [--no-embed-tools]
                  [--loop] [--loop-msg LOOP_MSG] [--log] [--log-file LOG_FILE] [--msg-file MSG_FILE]
                  [--mcp-server] [--mcp-server-no-file-tools] [--mcp-server-host MCP_SERVER_HOST]
                  [--mcp-server-port MCP_SERVER_PORT] [--force-stage-index FORCE_STAGE_INDEX]
                  [--no-write NO_WRITE [NO_WRITE ...]] [--version]
                  workspace dut

UCAgent - UnityChip Verification Agent

positional arguments:
  workspace             Workspace directory to run the agent in
  dut                   DUT name (sub-directory name in workspace), e.g., DualPort, Adder, ALU

options:
  -h, --help            show this help message and exit
  --config CONFIG       Path to the configuration file
  --template-dir TEMPLATE_DIR
                        Path to the template directory
  --template-overwrite  Overwrite existing templates in the workspace
  --output OUTPUT       Output directory name for verification results
  --override OVERRIDE   Override configuration settings in the format A.B.C=value
  --stream-output, -s   Stream output to the console
  --human, -hm          Enable human input mode at the beginning of the run
  --seed SEED           Seed for random number generation
  --tui                 Run in TUI (Text User Interface) mode
  --sys-tips SYS_TIPS   System tips to be used in the agent
  --ex-tools EX_TOOLS   List of external tools to be used by the agent, e.g., --ex-tools SqThink
  --no-embed-tools, --mcp-server-no-embed-tools
                        Disable embedded tools in the agent
  --loop, -l            Start the agent loop immediately
  --loop-msg LOOP_MSG   Message to be sent to the agent at the start of the loop
  --log                 Enable logging
  --log-file LOG_FILE   Path to the log file
  --msg-file MSG_FILE   Path to the message file
  --mcp-server          Run the MCP server
  --mcp-server-no-file-tools
                        Run the MCP server without file operations tools
  --mcp-server-host MCP_SERVER_HOST
                        Host for the MCP server
  --mcp-server-port MCP_SERVER_PORT
                        Port for the MCP server
  --force-stage-index FORCE_STAGE_INDEX
                        Force the stage index to start from a specific stage
  --no-write NO_WRITE [NO_WRITE ...], --nw NO_WRITE [NO_WRITE ...]
                        List of files or directories that cannot be written to during the run
  --version             show program's version number and exit

For more information, visit: https://github.com/XS-MLVP/UCAgent
```

### 系统要求

- Python 3.8+
- 支持的操作系统: Linux, macOS, Windows
- 内存: 建议 4GB 以上
- 网络: 需要访问AI模型API（OpenAI兼容）

### 使用方法

#### 方式一：pip 安装（推荐）

直接从GitHub安装最新版本：

```bash
pip install git+https://github.com/XS-MLVP/UCAgent@master
```

安装完成后，可在任意位置使用 `ucagent` 命令：

```bash
ucagent --help                    # 查看帮助信息
ucagent ./examples/Adder Adder    # 验证 Adder 设计
ucagent ./output Adder --tui      # 启动TUI界面
```

#### 方式二：源码测试

1. 克隆仓库：
```bash
git clone https://github.com/XS-MLVP/UCAgent.git
cd UCAgent
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 使用 Python 脚本运行（功能与 `ucagent` 命令完全相同）：
```bash
python ucagent.py --help                  # 查看帮助信息
python ucagent.py ./examples/Adder Adder  # 验证 Adder 设计
python ucagent.py ./output Adder --tui    # 启动TUI界面
```

### 依赖组件

#### 安装 Picker

Picker 是硬件仿真工具，用于生成Verilog的Python绑定。

```bash
# 详细安装步骤请参考官方文档
# https://github.com/XS-MLVP/picker
```

### 快速开始

#### 1. 配置设置

创建并编辑 `config.yaml` 文件，配置AI模型和嵌入模型：

```yaml
# OpenAI兼容的API配置
openai:
  openai_api_base: <your_openai_api_base_url>    # API基础URL
  model_name: <your_model_name>                  # 模型名称，如 gpt-4o-mini
  openai_api_key: <your_openai_api_key>          # API密钥

# 向量嵌入模型配置（用于文档搜索和记忆功能）
embed:
  model: <your_embed_model_name>                # 嵌入模型名称
  openai_base_url: <your_openai_api_base_url>   # 嵌入模型API URL
  api_key: <your_api_key>                       # 嵌入模型API密钥
  dims: <your_embed_model_dims>                 # 嵌入维度，如 1536
```

#### 2. 使用示例

两种安装方式的使用方法完全相同，只需将命令名替换即可：

##### 基本使用

```bash
# pip 安装版本使用 ucagent 命令
ucagent ./examples/Adder Adder

# 源码方式使用 python ucagent.py
make init_Adder
python ucagent.py ./examples/Adder Adder
```

##### 常用选项

| 参数 | 简写 | 说明 | 示例 |
|------|------|------|------|
| `--config` | - | 指定配置文件路径 | `--config config.yaml` |
| `--stream-output` | `-s` | 启用流式输出模式 | `-s` |
| `--tui` | - | 启用终端UI界面 | `--tui` |
| `--human` | `-hm` | 启用人工交互模式 | `-hm` |
| `--loop` | `-l` | 立即开始执行循环 | `-l` |
| `--seed` | - | 设置随机种子 | `--seed 12345` |
| `--log` | - | 启用日志记录 | `--log` |
| `--ex-tools` | - | 添加外部工具 | `--ex-tools SqThink` |

##### MCP服务器选项

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--mcp-server` | 启动MCP服务器模式 | - |
| `--mcp-server-host` | MCP服务器主机地址 | `127.0.0.1` |
| `--mcp-server-port` | MCP服务器端口 | `5000` |
| `--mcp-server-no-file-tools` | 禁用文件操作工具 | - |
| `--mcp-server-no-embed-tools` | 禁用嵌入式工具 | - |


##### 与其他AI工具集成 (MCP协议支持)

UCAgent 支持 [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)，可以作为工具服务器与各种AI客户端集成。


### 支持的AI客户端

#### 1. LLM客户端 (Cherry Studio、Claude Desktop等)

适用于不具备本地文件编辑能力的AI客户端：
```bash
# 启动完整功能的MCP服务器
python3 ucagent.py output/ Adder -s -hm --tui --mcp-server
```

**服务地址:** `http://127.0.0.1:5000/mcp`

**建议的任务启动提示词（提供文件类工具）:**

>首先请通过工具`RoleInfo`获取你的角色信息，然后基于unitytest中的MCP工具完成任务，包括所有文件操作。在完成每个阶段任务时，你需要用`Check`工具检测是否达标，它会自动运行程序，例如pytest等，然后返回检测结果。如果测试发现存在bug，需要进行充分详细的分析，最好能给出修复建议。请在当前工作目录进行文件操作，不要超出该目录。

#### 2. 编程AI工具 (OpenHands、Cursor、Gemini-CLI等)

这些工具具备文件编辑能力，因此不需要UCAgent提供文件写入工具：

```bash
# 启动不包含文件操作工具的MCP服务器
python3 ucagent.py output/ Adder -s -hm --tui --mcp-server-no-file-tools
```

**建议的任务启动提示词（不提供文件类工具）:**

> 首先请通过工具`RoleInfo`获取你的角色信息，然后基于unitytest中的MCP工具完成任务。在执行任务时，你可以通过`CurrentTips`获取任务提示。注意，你需要用`ReadTextFile`读取文本文件，不然我不知道你是否进行了读取操作，文件写操作你可以选择你擅长的工具；在完成每个阶段任务时，你需要用`Check`工具检测是否达标，它会自动运行程序，例如pytest等，然后返回检测结果。如果测试发现存在bug，需要进行充分详细的分析，最好能给出修复建议。请在当前工作目录进行文件操作，不要超出该目录。

**简化配置 (无嵌入工具):**

如果没有配置嵌入模型，使用 `--no-embed-tools` 参数：

```bash
python3 ucagent.py output/ Adder -s -hm --tui --mcp-server-no-file-tools --no-embed-tools
```

#### 集成示例: Gemini-CLI

##### 1. 启动UCAgent MCP服务器

```bash
# 准备环境
make clean

# 启动MCP服务器 (包含完整工具集)
make mcp_Adder

# 或者使用自定义参数启动
make mcp_all_tools_Adder ARGS="--override openai.model_name='gpt-4o-mini'"
```

> **说明:** `make mcp_all_tools_<DUT>` 会导出所有工具，包括文件操作、记忆操作等。可通过 `ARGS` 传递额外参数。

启动成功后会看到提示：
```
INFO     Uvicorn running on http://127.0.0.1:5000 (Press CTRL+C to quit)
```

##### 2. 配置Gemini-CLI

编辑 `~/.gemini/settings.json` 配置文件：
```json
{
  "mcpServers": {
    "unitytest": {
      "httpUrl": "http://localhost:5000/mcp",
      "timeout": 5000
    }
  }
}
```

##### 3. 开始验证任务

新开终端，进入项目输出目录：

```bash
cd UCAgent/output
gemini
```

**输入任务提示词:**

> 首先请通过工具`RoleInfo`获取你的角色信息，然后基于unitytest中的MCP工具完成任务。在执行任务时，你可以通过`CurrentTips`获取任务提示。注意，你需要用`ReadTextFile`读取文本文件，不然我不知道你是否进行了读取操作，文件写操作你可以选择你擅长的工具；在完成每个阶段任务时，你需要用`Check`工具检测是否达标，它会自动运行程序，例如pytest等，然后返回检测结果。如果测试发现存在bug，需要进行充分详细的分析，最好能给出修复建议。请在当前工作目录进行文件操作，不要超出该目录。

**监控进度:**

在 `gemini-cli` 运行过程中，可以通过UCAgent的TUI界面观察验证进度和状态。


### 常见问题 (FAQ)

**Q: 如何配置不同的AI模型？**
**A:** 在 `config.yaml` 中修改 `openai.model_name` 字段，支持任何OpenAI兼容的API。

**Q: 验证过程中出现错误怎么办？**
**A:** 使用 `Ctrl+C` 进入交互模式，通过 `status` 查看当前状态，使用 `help` 获取调试命令。

**Q: 可以自定义验证阶段吗？**
**A:** 可以通过修改 `vagent/config/default.yaml` 中的 `stage` 配置来自定义验证流程。

**Q: 如何添加自定义工具？**
**A:** 在 `vagent/tools/` 目录下创建新的工具类，继承 `UCTool` 基类，并通过 `--ex-tools` 参数加载。

**Q: MCP服务器无法连接？**
**A:** 检查端口是否被占用，确认防火墙设置，可以通过 `--mcp-server-port` 指定其他端口。

### 贡献指南

欢迎提交 Issue 和 Pull Request！
