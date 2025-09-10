# UCAgent（UnityChip verification Agent）

基于大模型进行自动化UT验证AI 代理

[English Introduction](/README.en.md)

### 项目简介

UCAgent 是一个基于大语言模型的自动化硬件验证AI代理，专注于芯片设计的单元测试(Unit Test)验证工作。该项目通过AI技术自动分析硬件设计，生成测试用例，并执行验证任务生成测试报告，从而提高验证效率。


**本项目关注重点：**
- 芯片验证工作流的自动化
- 功能覆盖率与代码覆盖率的完整性
- 文档、代码、报告之间的一致性

UCAgent 提供了完整的 Agent 与 LLM 交互逻辑，支持三种智能模式（standard、enhanced、advanced），并集成了丰富的文件操作工具，可通过标准化API与大语言模型进行直接交互。基于 Picker & Toffee 框架的芯片验证在本质上等价于软件测试，**因此现有的编程类 AI Agent（如 OpenHands、Copilot、Claude Code、Gemini-CLI、Qwen-Code 等）可以通过 MCP 协议与 UCAgent 进行深度协同，实现更优的验证效果和更高的自动化程度。[请参考"集成示例-gemini-cli"](#集成示例-gemini-cli)**

-----

#### 输入输出

```bash
ucagent <workspace> <dut_name>
```

**输入：**
 - `workspace：`工作目录，其中需包含待测设计（DUT），即由 picker 导出的 DUT 对应的 Python 包 `<DUT_DIR>`，例如：Adder
  - `workspace/<DUT_DIR>/README.md:` 以自然语言描述的该DUT验证需求与目标
  - 其他与验证相关的文件（例如：提供的测试实例、需求说明等）
 - `dut_name:` 待测设计的名称，即 `<DUT_DIR>`

**输出：**
- `workspace/Guide_Doc：`验证过程中所遵循的各项要求与指导文档
- `workspace/uc_test_report：` 生成的 Toffe-test 测试报告
- `workspace/unity_test/tests：` 动生成的测试用例
- `workspace/*.md：` 生成的各类文档，包括 Bug 分析、检查点记录、验证计划、验证结论等


#### 参数说明
```bash
usage: ucagent  [-h] [--config CONFIG] [--template-dir TEMPLATE_DIR] [--template-overwrite]
                [--output OUTPUT] [--override OVERRIDE] [--stream-output] [--human]
                [--interaction-mode {standard,enhanced,advanced}] [--seed SEED] [--tui]
                [--sys-tips SYS_TIPS] [--ex-tools EX_TOOLS] [--no-embed-tools] [--loop]
                [--loop-msg LOOP_MSG] [--log] [--log-file LOG_FILE] [--msg-file MSG_FILE]
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
  --interaction-mode {standard,enhanced,advanced}
                        Set the interaction mode: 'standard' (default),
                        'enhanced' (planning & memory), or 'advanced' (adaptive strategies)
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
- picker: https://github.com/XS-MLVP/picker

### 使用方法

#### 方式一：pip 安装

直接从GitHub安装最新版本：

```bash
pip install git+https://github.com/XS-MLVP/UCAgent@master
```

安装完成后，可在任意位置使用 `ucagent` 命令：

```bash
ucagent --help                    # 查看帮助信息
```

#### 方式二：源码执行（推荐）

1. 克隆仓库：
```bash
git clone https://github.com/XS-MLVP/UCAgent.git
cd UCAgent
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 编译dut，以编译example中的Adder为例
```bash
make init_Adder
```

4. 运行 Python 脚本（功能与 `ucagent` 命令完全相同）：
```bash
python ucagent.py --help                  # 查看帮助信息
python ucagent.py ./output Adder --tui    # 启动TUI界面，或者执行 make test_Adder
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
python ucagent.py ./examples/Adder Adder
```

##### 常用选项

| 参数 | 简写 | 说明 | 示例 |
|------|------|------|------|
| `--config` | - | 指定配置文件路径 | `--config config.yaml` |
| `--interaction-mode` | `-im` | 选择LLM交互模式，支持"standard", "enhanced", "advanced" | `-im enhanced` |
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

> 请通过工具`RoleInfo`获取你的角色信息和基本指导，然后完成任务。请使用工具`ReadTextFile`读取文件，用`EditTextFile`创建和编辑文件。

#### 2. 编程AI工具 (OpenHands、Cursor、Gemini-CLI等)

这些工具具备文件编辑能力，因此不需要UCAgent提供文件写入工具：

```bash
# 启动不包含文件操作工具的MCP服务器
python3 ucagent.py output/ Adder -s -hm --tui --mcp-server-no-file-tools
```

**建议的任务启动提示词（不提供文件类工具）:**

> 请通过工具`RoleInfo`获取你的角色信息和基本指导，然后完成任务。请使用工具`ReadTextFile`读取文件。你需要在当前工作目录进行文件操作，不要超出该目录。

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
      "timeout": 10000
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

> 请通过工具`RoleInfo`获取你的角色信息和基本指导，然后完成任务。请使用工具`ReadTextFile`读取文件。你需要在当前工作目录进行文件操作，不要超出该目录。

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
