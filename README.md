# UCAgent（UnityChip Verification Agent）

基于大模型进行自动化UT验证AI 代理（


## 项目简介

UCAgent 是一个基于大语言模型的自动化硬件验证AI代理，专注于芯片设计的单元测试(Unit Test)验证工作。该项目通过AI技术自动分析硬件设计，生成测试用例，并执行验证任务，大大提高了硬件验证的效。

**基本使用**
```bash
python3 ucagent.py <workspace> <dut_name> --config config.yaml
```

**流模式 + TUI界面 + 人工交互**
```bash
python3 ucagent.py <workspace> <dut_name> --config config.yaml --tui --human
```

**指定输出目录**
```bash
python3 ucagent.py <workspace> <dut_name> --config config.yaml --output <output_dir>
```

**启动MCP服务器模式**
```bash
python3 ucagent.py <workspace> <dut_name> --config config.yaml --mcp-server
```

- 🤖 **智能验证流程**: 基于6阶段验证流程，自动完成从需求分析到缺陷分析的全过程
- 🛠️ **丰富的工具集**: 内置完整的文件操作、搜索、编辑等工具，支持复杂的验证任务
- 🔄 **MCP协议支持**: 支持Model Context Protocol，可与多种AI客户端集成
- 📊 **交互式界面**: 支持TUI模式和PDB调试，便于监控和调试
- 🎯 **可配置框架**: 灵活的配置系统，支持多种AI模型和自定义工具
- 📝 **模板系统**: 内置验证模板，快速启动验证项目

## 系统要求

- Python 3.8+
- 支持的操作系统: Linux, macOS, Windows
- 内存: 建议 4GB 以上
- 网络: 需要访问AI模型API（OpenAI兼容）

## 安装方法

UCAgent 提供两种安装方式，两种方式使用相同的命令行接口：

### 方式一：pip 安装（推荐）

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

### 方式二：源码安装

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

> **说明**: `python ucagent.py` 和 `ucagent` 命令使用相同的底层实现，功能完全一致。`ucagent.py` 只是为了向后兼容而保留的包装器。

### 依赖组件

#### 安装 Picker

Picker 是硬件仿真工具，用于生成Verilog的Python绑定。

```bash
# 详细安装步骤请参考官方文档
# https://github.com/XS-MLVP/picker
```

#### 主要依赖包

- `langchain`: LLM应用开发框架
- `langgraph`: 多代理工作流框架  
- `langmem`: 长期记忆管理
- `openai`: OpenAI API客户端
- `urwid`: 终端UI库

## 快速开始

### 1. 配置设置

创建并编辑 `config.yaml` 文件，配置AI模型和嵌入模型：

```yaml
# OpenAI兼容的API配置
openai:
  openai_api_base: <your_openai_api_base_url>    # API基础URL
  model_name: <your_model_name>                  # 模型名称，如 gpt-4o-mini
  openai_api_key: <your_openai_api_key>         # API密钥

# 向量嵌入模型配置（用于文档搜索和记忆功能）
embed:
  model: <your_embed_model_name>                 # 嵌入模型名称
  openai_base_url: <your_openai_api_base_url>   # 嵌入模型API URL
  api_key: <your_api_key>                       # 嵌入模型API密钥
  dims: <your_embed_model_dims>                 # 嵌入维度，如 1536
```

### 2. 使用示例

两种安装方式的使用方法完全相同，只需将命令名替换即可：

#### 基本使用

```bash
# pip 安装版本使用 ucagent 命令
ucagent ./examples/Adder Adder

# 源码版本使用 python ucagent.py
python ucagent.py ./examples/Adder Adder
```

#### 常用选项

```bash
# 启动交互式TUI界面
ucagent ./output Adder --tui

# 启用人工交互模式
ucagent ./examples/Adder Adder --human

# 指定配置文件和输出目录
ucagent ./my_design MyDUT --config ./config.yaml --output ./test_output

# 启用流式输出和日志
ucagent ./examples/Adder Adder --stream-output --log
```

### 3. 快速测试

使用内置的 Makefile 快速开始：

```bash
# 准备示例项目
make dut

# 运行 Adder 示例验证
make test_Adder

# 或者运行其他示例
make test_ALU
make test_DualPort
```

测试结果位于 `./output` 目录中。

### 4. 高级用法

无论使用哪种安装方式，高级功能的使用方法都相同（只需替换命令名）：

```bash
# 基本语法
ucagent <workspace> <dut_name> [选项]
# 或者
python ucagent.py <workspace> <dut_name> [选项]

# 常用高级选项组合
ucagent <workspace> <dut_name> --config config.yaml --tui --human
ucagent <workspace> <dut_name> --config config.yaml --output <output_dir>
ucagent <workspace> <dut_name> --stream-output --log --loop

# MCP服务器模式
ucagent <workspace> <dut_name> --config config.yaml --mcp-server
```

查看完整选项列表：
```bash
ucagent --help
# 或
python ucagent.py --help
```

## 验证流程

UCAgent 按照预定义的6个阶段执行验证任务，每个阶段都有明确的目标和检测标准：

| 阶段 | 名称 | 主要任务 | 输出产物 |
|------|------|----------|----------|
| 1 | **需求分析与验证规划** | 深入理解DUT功能规格、接口定义和性能指标，识别验证范围和潜在风险点 | 需求理解文档、验证计划 |
| 2 | **功能规格分析与测试点定义** | 按照功能分组-功能点-检测点的层次结构，系统性分析所有功能模块 | 功能分析文档(`{DUT}_functions_and_checks.md`) |
| 3 | **测试平台基础架构设计** | 设计高级API接口，封装DUT底层操作，提供稳定的测试基础设施 | API接口文件(`{DUT}_api.py`) |
| 4 | **功能覆盖率模型实现** | 基于功能文档创建覆盖率模型，实现覆盖组和检查点的完整映射 | 覆盖率定义(`{DUT}_function_coverage_def.py`) |
| 5 | **测试框架脚手架构建** | 创建测试用例模板，建立标准测试结构和覆盖率标记框架 | 测试模板文件(`test_*.py`) |
| 6 | **全面验证执行与缺陷分析** | 实现完整测试逻辑，执行验证并进行深度缺陷分析 | 完整测试用例、缺陷分析报告 |

每个阶段都需要通过自动化检测才能进入下一阶段，确保验证质量和流程完整性。

## 主要目录结构

```
UCAgent/
├── LICENSE                   # 开源协议
├── Makefile                  # 快速测试入口
├── README.md                 # 项目说明文档
├── config.yaml               # 用户配置文件（覆盖默认配置）
├── requirements.txt          # Python依赖列表
├── ucagent.py                # 主程序入口
├── doc/                      # AI参考文档目录
│   ├── Guide_Doc/           # 验证指南文档
│   └── Function_Coverage/   # 功能覆盖率文档
├── examples/                 # 测试示例项目
│   ├── Adder/               # 加法器示例
│   ├── ALU/                 # 算术逻辑单元示例
│   └── DualPort/            # 双端口RAM示例
├── output/                   # 验证输出目录（运行时生成）
├── tests/                    # 单元测试
└── vagent/                   # Agent核心代码
    ├── config/
    │   └── default.yaml      # 默认配置文件
    ├── stage/                # 验证阶段流程定义
    ├── template/
    │   └── unity_test/       # 验证模板文件
    ├── tools/                # 工具集实现
    │   ├── fileops.py       # 文件操作工具
    │   ├── memory.py        # 记忆管理工具
    │   ├── testops.py       # 测试操作工具
    │   └── ...              # 其他工具
    ├── util/                 # 工具函数
    ├── verify_agent.py       # 主Agent逻辑
    ├── verify_pdb.py         # PDB调试接口
    └── verify_ui.py          # TUI交互界面
```

## 内置工具集

UCAgent 提供了丰富的内置工具来支持验证任务：

### 文件操作工具
- **ReadTextFile**: 读取文本文件内容
- **ReadBinFile**: 读取二进制文件
- **WriteToFile**: 写入文件（覆盖模式）
- **AppendToFile**: 追加内容到文件
- **TextFileReplace**: 文本文件内容替换（单块）
- **TextFileMultiReplace**: 文本文件内容替换（多块）
- **CopyFile**: 复制文件
- **MoveFile**: 移动/重命名文件
- **DeleteFile**: 删除文件或目录

### 搜索和浏览工具
- **SearchText**: 在文件中搜索文本（支持正则表达式）
- **FindFiles**: 按模式查找文件
- **PathList**: 列出目录内容
- **GetFileInfo**: 获取文件详细信息

### 目录管理工具
- **CreateDirectory**: 创建目录

### 验证专用工具
- **SearchInGuidDoc**: 搜索参考文档
- **MemoryPut/MemoryGet**: 长期记忆管理
- **CurrentTips**: 获取当前阶段提示
- **Check**: 检测当前阶段是否完成
- **Complete**: 完成当前阶段，进入下一阶段

## 命令行参数详解

### 基本用法
```bash
python3 ucagent.py <workspace> <dut> [options]
```

### 必需参数
- **workspace**: 工作目录路径
- **dut**: DUT名称（workspace中的子目录名）

### 常用选项
### 完整参数列表

```bash
python3 ucagent.py --help
usage: ucagent.py [-h] [--config CONFIG] [--template-dir TEMPLATE_DIR] [--template-overwrite]
                 [--output OUTPUT] [--override OVERRIDE] [--stream-output] [--human] [--seed SEED]
                 [--tui] [--sys-tips SYS_TIPS] [--ex-tools EX_TOOLS] [--loop] [--loop-msg LOOP_MSG]
                 [--log] [--log-file LOG_FILE] [--msg-file MSG_FILE] [--mcp-server]
                 [--mcp-server-no-file-tools] [--mcp-server-host MCP_SERVER_HOST]
                 [--mcp-server-port MCP_SERVER_PORT]
                 workspace dut

Verify Agent

positional arguments:
  workspace             Workspace directory to run the agent in
  dut                   a sub-directory name in worspace, e.g., DualPort, Adder, ALU

options:
  -h, --help            show this help message and exit
  --config CONFIG       Path to the configuration file
  --template-dir TEMPLATE_DIR
                        Path to the template directory
  --template-overwrite  Overwrite existing templates in the workspace
  --output OUTPUT       Path to the configuration file
  --override OVERRIDE   Override configuration settings in the format A.B.C=value
  --stream-output, -s   Stream output to the console
  --human, -hm          Enable human input mode in the beginning of the run
  --seed SEED           Seed for random number generation, if applicable
  --tui                 Run in TUI mode
  --sys-tips SYS_TIPS   Set of system tips to be used in the agent
  --ex-tools EX_TOOLS   List of external tools class to be used by the agent, eg --ex-tools SqThink
  --loop, -l            Start the agent loop imimediately
  --loop-msg LOOP_MSG   Message to be sent to the agent at the start of the loop
  --log                 Enable logging
  --log-file LOG_FILE   Path to the log file
  --msg-file MSG_FILE   Path to the msg file
  --mcp-server          Run the MCP server
  --mcp-server-no-file-tools
                        Run the MCP server without file operations
  --mcp-server-host MCP_SERVER_HOST
                        Host for the MCP server
  --mcp-server-port MCP_SERVER_PORT
                        Port for the MCP serve
```


### 常用选项

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

### MCP服务器选项

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--mcp-server` | 启动MCP服务器模式 | - |
| `--mcp-server-host` | MCP服务器主机地址 | `127.0.0.1` |
| `--mcp-server-port` | MCP服务器端口 | `5000` |
| `--mcp-server-no-file-tools` | 禁用文件操作工具 | - |
| `--mcp-server-no-embed-tools` | 禁用嵌入式工具 | - |

### 配置覆盖

使用 `--override` 参数可以临时覆盖配置文件中的设置：

```bash
# 覆盖模型名称
--override openai.model_name=gpt-4o-mini

# 覆盖多个配置（用逗号分隔）
```

### 交互模式

在Agent执行过程中，可以通过 `Ctrl+C` 中断进入交互模式：

- `help`: 列出所有可用命令
- `help <cmd>`: 查看特定命令的帮助信息
- `status`: 查看当前执行状态
- `continue`: 继续执行
- `exit`: 退出程序

## 与其他AI工具集成 (MCP协议支持)

UCAgent 支持 [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)，可以作为工具服务器与各种AI客户端集成。

### 支持的AI客户端

#### 1. LLM客户端 (Cherry Studio、Claude Desktop等)

适用于不具备本地文件编辑能力的AI客户端：
```bash
# 启动完整功能的MCP服务器
python3 ucagent.py output/ Adder -s -hm --tui --mcp-server
```

**导出的工具包括:**

**任务管理工具:**
- `CurrentTips` - 获取当前阶段提示
- `Detail` - 查看任务详情
- `Status` - 检查当前状态  
- `Check` - 检测是否通过当前阶段
- `Complete` - 完成当前阶段进入下一阶段
- `GoToStage` - 跳转到指定阶段

**文档和记忆工具:**
- `SearchInGuidDoc` - 搜索参考文档
- `MemoryPut` - 保存长期记忆
- `MemoryGet` - 检索长期记忆

**文件操作工具:**
- `ReadTextFile` - 读取文本文件
- `TextFileReplace` - 文本文件内容替换（单块）
- `TextFileMultiReplace` - 文本文件内容替换（多块）  
- `WriteToFile` - 写入文件
- `AppendToFile` - 追加文件内容

**服务地址:** `http://127.0.0.1:5000/mcp`

**建议的任务启动提示词:**

>请用 `'SearchInGuidDoc', 'MemoryPut', 'MemoryGet', 'CurrentTips', 'Detail', 'Status', 'Check', 'Complete', 'GoToStage', 'ReadTextFile', 'TextFileReplace', 'TextFileMultiReplace', 'WriteToFile', 'AppendToFile'`等工具完成任务。现在你可以通过CurrentTips获取任务提示。注意，你需要用ReadTextFile读文件，否则我不知道你是否进行了读取操作，文件写操作你可以选择你擅长的工具；在完成每个阶段任务时，你需要用Check工具检测是否达标，它会自动运行程序，例如pytest等，然后返回检测结果。

#### 2. 编程AI工具 (OpenHands、Cursor、Gemini-CLI等)

这些工具具备文件编辑能力，因此不需要UCAgent提供文件写入工具：

```bash
# 启动不包含文件操作工具的MCP服务器
python3 ucagent.py output/ Adder -s -hm --tui --mcp-server-no-file-tools
```

**建议的任务启动提示词:**

> 首先请通过工具`RoleInfo`获取你的角色信息，然后基于`'SearchInGuidDoc', 'MemoryPut', 'MemoryGet', 'CurrentTips', 'Detail', 'Status', 'Check', 'Complete', 'GoToStage', 'ReadTextFile'`等工具完成任务。执行任务时需要通过CurrentTips获取任务提示。注意，你需要用ReadTextFile读取文本文件，不然我不知道你是否进行了读取操作，文件写操作你可以选择你擅长的工具；在完成每个阶段任务时，你需要用Check工具检测是否达标，它会自动运行程序，例如pytest等，然后返回检测结果。如果测试发现存在bug，需要进行充分详细的分析，最好能给出修复建议。

**简化配置 (无嵌入工具):**

如果没有配置嵌入模型，使用 `--no-embed-tools` 参数：

```bash
python3 ucagent.py output/ Adder -s -hm --tui --mcp-server-no-file-tools --no-embed-tools
```

**对应的提示词:**

> 首先请通过工具`RoleInfo`获取你的角色信息，然后基于`'CurrentTips', 'Detail', 'Status', 'Check', 'Complete', 'GoToStage', 'ReadTextFile'`等工具完成任务。执行任务时需要通过CurrentTips获取任务提示。注意，你需要用ReadTextFile读取文本文件，不然我不知道你是否进行了读取操作，文件写操作你可以选择你擅长的工具；在完成每个阶段任务时，你需要用Check工具检测是否达标，它会自动运行程序，例如pytest等，然后返回检测结果。如果测试发现存在bug，需要进行充分详细的分析，最好能给出修复建议。

### 集成示例: Gemini-CLI

#### 1. 启动UCAgent MCP服务器

```bash
# 准备环境
make dut

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

#### 2. 配置Gemini-CLI

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

#### 3. 开始验证任务

新开终端，进入项目输出目录：

```bash
cd UCAgent/output
gemini
```

**输入任务提示词:**

> 首先请通过工具`RoleInfo`获取你的角色信息，然后基于unitytest中的MCP工具完成任务。在执行任务时，你可以通过`CurrentTips`获取任务提示。注意，你需要用`ReadTextFile`读取文本文件，不然我不知道你是否进行了读取操作，文件写操作你可以选择你擅长的工具；在完成每个阶段任务时，你需要用`Check`工具检测是否达标，它会自动运行程序，例如pytest等，然后返回检测结果。如果测试发现存在bug，需要进行充分详细的分析，最好能给出修复建议。

**监控进度:**

在 `gemini-cli` 运行过程中，可以通过UCAgent的TUI界面观察验证进度和状态。

## 示例项目

UCAgent 提供了三个完整的验证示例：

### 1. Adder (加法器)
- **路径**: `examples/Adder/`
- **功能**: 简单的加法运算器
- **适合**: 初学者了解基本验证流程
- **运行**: `make test_Adder`

### 2. ALU (算术逻辑单元)  
- **路径**: `examples/ALU/`
- **功能**: 包含加减乘除和逻辑运算
- **适合**: 中等复杂度的验证任务
- **运行**: `make test_ALU`

### 3. DualPort (双端口RAM)
- **路径**: `examples/DualPort/`  
- **功能**: 双端口内存控制器
- **适合**: 复杂时序和接口验证
- **运行**: `make test_DualPort`

## 常见问题 (FAQ)

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

## 贡献指南

欢迎提交 Issue 和 Pull Request！

### 开发环境设置
```bash
git clone https://github.com/XS-MLVP/UCAgent.git
cd UCAgent
pip install -r requirements.txt
```

### 运行单元测试
```bash
python -m pytest tests/
```

### 代码规范
- 使用 Python 3.8+ 语法
- 遵循 PEP 8 代码风格
- 添加适当的类型注解
- 编写单元测试

## 许可证

本项目采用 [MIT许可证](LICENSE)。

## 致谢

感谢所有为UCAgent项目做出贡献的开发者和用户！

- [picker项目](https://github.com/XS-MLVP/picker) - 硬件仿真工具
- [LangChain](https://github.com/langchain-ai/langchain) - LLM应用框架
- [MCP协议](https://modelcontextprotocol.io/) - 模型上下文协议
