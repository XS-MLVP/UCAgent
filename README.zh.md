# UCAgent（UnityChip verification Agent）

基于大模型进行自动化UT验证AI 代理

[English Introduction](/README.en.md)

### 项目简介

UCAgent 是一个基于大语言模型的自动化硬件验证AI代理，专注于芯片设计的单元测试(Unit Test)验证工作。该项目通过AI技术自动分析硬件设计，生成测试用例，并执行验证任务生成测试报告，从而提高验证效率。


**本项目关注重点：**
- 芯片验证工作流的自动化
- 功能覆盖率与代码覆盖率的完整性
- 文档、代码、报告之间的一致性

UCAgent 提供了完整的 Agent 与 LLM 交互逻辑，支持三种智能模式（standard、enhanced、advanced），并集成了丰富的文件操作工具，可通过标准化API与大语言模型进行直接交互。基于 Picker & Toffee 框架的芯片验证在本质上等价于软件测试，**因此现有的编程类 AI Agent（如 OpenHands、Copilot、Claude Code、Gemini-CLI、Qwen-Code 等）可以通过 MCP 协议与 UCAgent 进行深度协同，实现更优的验证效果和更高的自动化程度。**

-----

#### UCAgent的输入与输出

```bash
ucagent <workspace> <dut_name>
```

**输入：**
 - `workspace：`工作目录：
   - `workspace/<DUT_DIR>:` 待测设计（DUT），即由 picker 导出的 DUT 对应的 Python 包 `<DUT_DIR>`，例如：Adder
   - `workspace/<DUT_DIR>/README.md:` 以自然语言描述的该DUT验证需求与目标
   - `workspace/<DUT_DIR>/*.md:` 其他参考文件
   - `workspace/<DUT_DIR>/*.v/sv/scala:` 源文件，用于进行bug分析
   - 其他与验证相关的文件（例如：提供的测试实例、需求说明等）
 - `dut_name:` 待测设计的名称，即 `<DUT_DIR>`

**输出：**
- `workspace/Guide_Doc：`验证过程中所遵循的各项要求与指导文档
- `workspace/uc_test_report：` 生成的 Toffee-test 测试报告
- `workspace/unity_test/tests：` 自动生成的测试用例
- `workspace/*.md：` 生成的各类文档，包括 Bug 分析、检查点记录、验证计划、验证结论等


### 系统要求

- Python 3.11+
- 支持的操作系统: Linux, macOS
- 内存: 建议 4GB 以上
- 网络: 需要访问AI模型API（OpenAI兼容）
- picker: https://github.com/XS-MLVP/picker

### 快速入门

1. 下载源码
```bash
git clone https://github.com/XS-MLVP/UCAgent.git
cd UCAgent
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 编译dut，以编译example中的Adder为例（依赖[picker](https://github.com/XS-MLVP/picker)）
```bash
make init_Adder
```

4. 启动MCP-Server，默认地址为：http://127.0.0.1:5000
```bash
make mcp_Adder # workspace 设置为当前目录下的 output
```

5. 安装配置Qwen Code CLI

请参考：[https://qwenlm.github.io/qwen-code-docs/en/](https://qwenlm.github.io/qwen-code-docs/en/)

由于测试用例多了后运行时间较长，建议`timeout`值设置大一些，例如10秒，示例Qwen配置文件如下：

 `~/.qwen/settings.json` 配置文件：
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

6. 开始验证
```bash
cd output
qwen
```

**输入任务提示词：**

> 请通过工具`RoleInfo`获取你的角色信息和基本指导，然后完成任务。请使用工具`ReadTextFile`读取文件。你需要在当前工作目录进行文件操作，不要超出该目录。

提示：
- 请根据任务需要编写验证 Prompt
- 当 Code Agent 中途停止时，可输入 `继续，请通过工具Check和Complete判断是否完成所有任务`

#### 常用操作

##### TUI快捷键：
- `ctrl + 上/下/左/右`：调节界面布局
- `shift + 上/下`：调节状态面板高度
- `shift + 右`：清空控制台
- `esc`: 强制刷新界面

##### 常用交互命令：
- `q`：退出TUI（或者退出UCAgent）
- `tui`：进入TUI
- `tab`: 命令补全
- `tool_list`：列出所有可用工具
- `tool_invoke`：手动调用工具
- `help`：查看所有命令帮助

-----

### 安装使用

直接从GitHub安装最新版本：

```bash
pip install git+https://github.com/XS-MLVP/UCAgent@main
```
或者

```bash
git clone https://github.com/XS-MLVP/UCAgent.git
cd UCAgent
pip install .
```


### 使用方式

#### 1. MCP-Server 配合 Code Agent （推荐）

该模式能与所有支持MCP-Server调用的LLM客户端进行协同验证，例如：Cherry Studio、Claude Code、 Gemini-CLI、VS Code Copilot、Qwen-Code、Qoder等。

在启动 UCAgent时，通过`mcp-server`相关参数开启对应服务。

##### MCP服务器选项

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--mcp-server` | 启动MCP服务模式 | - |
| `--mcp-server-host` | MCP服务主机地址 | `127.0.0.1` |
| `--mcp-server-port` | MCP服务端口 | `5000` |
| `--mcp-server-no-file-tools` | 启动MCP服务并禁用文件操作工具 | - |
| `--no-embed-tools` | 禁用Embed嵌入类工具 | - |

示例：
```bash
ucagent output/ Adder --tui --mcp-server-no-file-tools --no-embed-tools
```

参数解释：
- `--tui` 开启字符界面，用于显示进度和命令行交互
- `--mcp-server-no-file-tools` 启动MCP服务并禁用UCAgent提供的文件编辑类工具，使用Code Agent自带的文件类工具
- `--no-embed-tools` 禁用Embed相关工具（Code Agent自带针对自身优化后的类似工具）


建议的任务启动提示词（不提供文件类工具，即`--mcp-server-no-file-tools`）:

> 请通过工具`RoleInfo`获取你的角色信息和基本指导，然后完成任务。请使用工具`ReadTextFile`读取文件。你需要在当前工作目录进行文件操作，不要超出该目录。


或者（提供文件类工具）:
> 请通过工具`RoleInfo`获取你的角色信息和基本指导，然后完成任务。请使用工具`ReadTextFile`读取文件，用`EditTextFile`创建和编辑文件。


**提示：代码类Agent针对自家模型进行了优化，因此基于他们去驱动UCAgent会获得更好的验证效果**


#### 2. 直接接入 LLM

创建并编辑 `config.yaml` 文件，配置AI模型和嵌入模型：

```yaml
# API配置（支持openai, anthropic, google_genai）
model_type: openai

# $(NAME: default_value): 读取环境变量NAME，default_value为默认值
openai:
  # 模型名称
  model_name: "$(OPENAI_MODEL: <your_chat_model_name>)"
  # API密钥
  openai_api_key: "$(OPENAI_API_KEY: [your_api_key])"
  # API基础URL
  openai_api_base: "$(OPENAI_API_BASE: http://<your_chat_model_url>/v1)"

# 向量嵌入模型配置
# 用于文档搜索和记忆功能，不需要可通过 --no-embed-tools 关闭
embed:
  # 嵌入模型名称
  model_name: "$(EMBED_MODEL: <your_embedding_model_name>)"
  # 嵌入模型API密钥
  openai_api_key: "$(EMBED_OPENAI_API_KEY: your_api_key)"
  # 嵌入模型API URL
  openai_api_base: "$(EMBED_OPENAI_API_BASE: http://<your_embedding_model_url>/v1)"
  # 嵌入维度，如 4096
  dims: "$(EMBED_OPENAI_API_BASE: 4096)
```

示例：

```bash
ucagent output/ Adder --config config.yaml -s -hm --tui -utt
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
| `--use-todo-tools` | `-utt` | 启用ToDo相关工具 | `-utt` |

##### 常用交互命令

- `ctrl+c`：暂停当前任务
- `loop [prompt]`：继续当前任务

请通过`help`命令查看所有支持的交互命令

### 人机协同验证

UCAgent 支持在验证过程中进行人机协同，允许用户暂停 AI 执行，人工干预验证过程，然后继续 AI 执行。这种模式适用于需要精细控制或复杂决策的场景。

**协同流程：**

1. 暂停 AI 执行：
   - 在直接接入 LLM 模式下：按 `Ctrl+C` 暂停。
   - 在 Code Agent 协同模式下：根据 Agent 的暂停方式（如 Gemini-cli 使用 `Esc`）暂停。

2. 人工干预：
   - 手动编辑文件、测试用例或配置。
   - 使用交互命令进行调试或调整。

3. 阶段控制：
   - 使用 `tool_invoke Check` 检查当前阶段状态。
   - 使用 `tool_invoke Complete` 标记阶段完成并进入下一阶段。

4. 继续执行：
   - 使用 `loop [prompt]` 命令继续 AI 执行，并可提供额外的提示信息。
   - 在 Code Agent 模式下，通过 Agent 的控制台输入提示。

5. 权限管理：
   - 可使用 `add_un_write_path`，`del_un_write_path` 等命令设置文件写权限，控制 AI 是否可以编辑特定文件。
   - 适用于直接接入 LLM 或强制使用 UCAgent 文件工具。

### 配置与指导文档的多语言支持

目前仓库仅提供中文版本，如果需要其他语言，可通过`ucagent --check`找到`lang_dir`目录：

```bash
ucagent --check
UCAgent Check:
Check   sys_config      ~/.local/lib/python3.11/site-packages/vagent/setting.yaml   [Found]
Check   user_config     ~/.ucagent/setting.yaml [Found]
Check   lang_dir        ~/.local/lib/python3.11/site-packages/vagent/lang   [Found]
Check   'zh' config     ~/.local/lib/python3.11/site-packages/vagent/lang/zh/config/default.yaml    [Found]
Check   'zh' Guide_Doc  ~/.local/lib/python3.11/site-packages/vagent/lang/zh/doc/Guide_Doc  [Found]
Check   'zh' template   ~/.local/lib/python3.11/site-packages/vagent/lang/zh/template/unity_test    [Found]
```

进入`lang_dir`目录，通过命令`cp -r zh en`复制一份，然后翻译为目标语言，最后在配置文件中设置：

```yaml
lang: "en"
```

或者通过参数`--config`, `--template-dir`, `--guid-doc-path` 指定到目标语言文件，达到类似效果。


### 常见问题 (FAQ)

**Q: 如何配置不同的AI模型？**
**A:** 在 `config.yaml` 中修改 `openai.model_name` 字段，支持任何OpenAI兼容的API。

**Q: 验证过程中出现错误怎么办？**
**A:** 使用 `Ctrl+C` 进入交互模式，通过 `status` 查看当前状态，使用 `help` 获取调试命令。

**Q: 可以自定义验证阶段吗？**
**A:** 可以通过修改 `vagent/lang/zh/config/default.yaml` 中的 `stage` 配置来自定义验证流程。也可直接在 config.yaml 中进行 stage 参数覆盖。

**Q: 如何添加自定义工具？**
**A:** 在 `vagent/tools/` 目录下创建新的工具类，继承 `UCTool` 基类，并通过 `--ex-tools` 参数加载。

**Q: MCP服务器无法连接？**
**A:** 检查端口是否被占用，确认防火墙设置，可以通过 `--mcp-server-port` 指定其他端口。

### 贡献指南

欢迎提交 Issue 和 Pull Request！
