# UCAgent（UnityChip verification Agent）

基于大模型进行自动化 UT 验证 AI 代理

[English Introduction](/README.en.md) | [UCAgent 在线文档](https://ucagent.open-verify.cc)

## 项目简介

UCAgent 是一个基于大语言模型的自动化硬件验证 AI 代理，专注于芯片设计的单元测试(Unit Test)验证工作。通过 AI 技术自动分析硬件设计，生成测试用例，执行验证任务并生成测试报告，从而提高验证效率。

**核心特点：**

- 自动化芯片验证工作流
- 支持功能覆盖率与代码覆盖率分析
- 文档、代码、报告一致性保障
- 支持 MCP 协议与主流 Code Agent（OpenHands、Copilot、Claude Code、Gemini-CLI、Qwen-Code 等）深度协同
- 提供三种智能交互模式（standard、enhanced、advanced）

更多**详细介绍请参考 [UCAgent 在线文档](https://ucagent.open-verify.cc)**

---

## 系统要求

- Python 3.11+
- 支持的操作系统: Linux, macOS
- 内存: 建议 4GB 以上
- 网络: 需要访问 AI 模型 API（OpenAI 兼容）
- picker: https://github.com/XS-MLVP/picker

---

## 快速开始

### 1. 下载源码

```bash
git clone https://github.com/XS-MLVP/UCAgent.git
cd UCAgent
```

### 2. 安装依赖

```bash
pip3 install -r requirements.txt
```

### 3. 安装配置 qwen

请参考 [https://qwenlm.github.io/qwen-code-docs/en/](https://qwenlm.github.io/qwen-code-docs/en/) 安装qwen-code-cli，然后按以下示例配置MCP Server。

`~/.qwen/settings.json` 示例：

```json
{
    "mcpServers": {
	    "unitytest": {
            "httpUrl": "http://localhost:5000/mcp",
            "timeout": 300000
        }
    }
}
```

由于测试用例多了后运行时间较长，建议 `timeout` 值设置大一些，例如 300 秒。

其他Code Agent 请参考对应文档，例如 [claude code](https://claude.com/product/claude-code), [opencode](https://opencode.ai/), [copilot-cli](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli), [kilo-cli](https://kilo.ai/cli), [iflow](https://platform.iflow.cn/cli/quickstart) 等。

### 4. 开始验证

以 example 中的 Adder 为例。

#### 4.1 方式一：指定后端自动运行 qwen（推荐）

```bash
# 默认后端为 langchain，需要配置：OPENAI_API_BASE 等环境变量
# backend can be: langchian, claude, opencode, copilot, kilo, qwen, iflow, etc.
make mcp_Adder ARGS="--loop --backend=qwen"
```

已经支持的后端请参考 [ucagent/setting.yaml](/ucagent/setting.yaml) 中的`backend`部分。

#### 4.2 方式二：手动运行qwen（适用于未适配的 CodeAgent ）

**（1）启动 MCP-Server**

```bash
make mcp_Adder  # workspace 设置为当前目录下的 output/workspace_Adder
# 调用了如下命令：
#   picker export Adder/Adder.v --rw 1 --sname Adder --tdir output/workspace_Adder/ -c -w output/workspace_Adder/Adder/Adder.fst
#   ucagent output/workspace_Adder/ Adder -s -hm --tui --mcp-server-no-file-tools --no-embed-tools
# 浏览器 Web UI 模式：
#   ucagent output/workspace_Adder/ Adder -s -hm --web-console --mcp-server-no-file-tools --no-embed-tools
# 自定义 Web UI 地址/端口/密码（HTTP Basic Auth）：
#   ucagent output/workspace_Adder/ Adder -s -hm --web-console 0.0.0.0:18000:secret --mcp-server-no-file-tools --no-embed-tools
```

MCP Server的默认地址为：http://127.0.0.1:5000/mcp

**（2）启动 qwen 执行任务**

```bash
cd output
qwen
```

按以上方式启动qwen后，输入任务提示词：

> 请通过工具`RoleInfo`获取你的角色信息和基本指导，然后完成任务。请使用工具`ReadTextFile`读取文件。你需要在当前工作目录进行文件操作，不要超出该目录。

**注意：**
- 需要在工作目录（如上述例子中的 output）中启动 Code Agent，否则可能会出现文件路径不匹配问题。
- 如果DUT比较复杂，有外围组件依赖，需要通过ucagent交互命令打开默认skip的阶段。

**提示：**

- 请根据任务需要编写验证 Prompt
- 当 Code Agent 中途停止时，可输入 `继续，请通过工具Complete判断是否完成所有任务`

> 💡 **更多使用方式：** 除了 MCP 协同模式，UCAgent 还支持直接接入 LLM、人机协同等多种模式，详见 [使用文档](https://ucagent.open-verify.cc/content/02_usage/01_direct/)


### 5. 如何提升验证质量(可选)

默认情况下，UCAgent只是启用内部的`Python Checker`进行阶段结果检查，属于启发式。如果需要验证质量提升，可以引入 `LLM 阶段结果检查`，如果需要达到“交付级”质量，还需要进一步引入`人工阶段检查`。

1. [开启LLM阶段结果检查](/examples/LLMCheck/README.md)

2. [开启人工阶段结果检查](https://ucagent.open-verify.cc/content/02_usage/02_assit/)

阶段默认检查顺序：Python Checker -> LLM -> 人工

---

## 基本操作

### TUI 快捷键

- `ctrl + 上/下/左/右`：调节界面布局（Console 高度 / Mission 面板宽度）
- `ctrl + h/j/k/l`：Vim 风格调节界面布局（等同于 ctrl+左/下/上/右）
- `ctrl + c`：取消运行中的命令；无命令运行时退出 TUI
- `ctrl + t`：打开主题选择器
- `ctrl + /` 或 `f1`：显示/隐藏快捷键帮助面板
- `shift + 右`：清空控制台输出
- `shift + 左`：清空输入行
- `tab`：命令补全；连续按 Tab 循环浏览候选项
- `pageup / pagedown`：Console 输出区翻页
- `esc`：退出滚动/分页/帮助面板，或清空输入行

### 阶段颜色提示

- `白色`：待执行
- `红色`：正在执行
- `绿色`：执行通过
- `*`：
  - 蓝色表示该阶段启用了LLM Fail检查，当阶段检查Fail次数大于3时，让LLM给出修改建议
  - 绿色表示该阶段启用了LLM Pass检查，阶段任务完成时，让LLM检查是否满足阶段任务要求
  - 红色表示该阶段需要强制人工检查，输入命令 `hmcheck_pass [msg]` 后 AI 才能继续
- `黄色`：跳过该阶段

### 常用交互命令

- `q`：退出 TUI（或退出 UCAgent）
- `tui`：进入 TUI
- `tab`: 命令补全
- `tool_list`：列出所有可用工具
- `help`：查看所有命令帮助
- `loop [prompt]`：继续当前任务

> 📖 **详细操作说明：** 查看 [TUI 使用文档](https://ucagent.open-verify.cc/content/02_usage/04_tui/)

---

## 常见问题 (FAQ)

**Q: 如何配置不同的 AI 模型？**

A: 在 `config.yaml` 中修改 `openai.model_name` 字段，支持任何 OpenAI 兼容的 API。详见[配置文档](https://ucagent.open-verify.cc/content/02_usage/01_direct/)。

**Q: 验证过程中出现错误怎么办？**

A: 使用 `Ctrl+C` 进入交互模式，通过 `status` 查看当前状态，使用 `help` 获取调试命令。

**Q: MCP 服务器无法连接？**

A: 检查端口是否被占用，确认防火墙设置，可以通过 `--mcp-server-port` 指定其他端口。

**Q: 为何有上次执行信息残留？**

A: UCAgent 默认会从工作目录中查找 `.ucagent/ucagent_info.json` 文件，来加载上次执行信息接着执行。如果不需要历史信息，请删除该文件或者使用参数 `--no-history` 忽略加载历史。

**Q: 如何运行长时间验证？**

A: 请参考 CodeAgent 的自定义后端 [examples/CustomBackend/README.md](/examples/CustomBackend/README.md)。

**Q: 可以自定义验证阶段吗？**

A: 可以，详见[自定义文档](https://ucagent.open-verify.cc/content/03_develop/01_customize/)。

**Q: 如何添加自定义工具？**

A: 在 `ucagent/tools/` 目录下创建新的工具类，继承 `UCTool` 基类，并通过 `--ex-tools` 参数加载。详见[工具列表文档](https://ucagent.open-verify.cc/content/03_develop/02_tool_list/)。

> 🔍 **更多问题：** 查看完整 [FAQ 文档](https://ucagent.open-verify.cc/content/02_usage/05_faq/)

---

## 文档构建与预览（MkDocs）

Makefile 提供文档相关辅助目标（MkDocs + Material）：

| 目标                | 作用                                         | 使用场景             |
| ------------------- | -------------------------------------------- | -------------------- |
| `make docs-help`    | 显示文档相关目标帮助                         | 查看可用命令         |
| `make docs-install` | 从 `docs/requirements-docs.txt` 安装构建依赖 | 首次使用或依赖更新时 |
| `make docs-serve`   | 本地预览（默认 127.0.0.1:8030）              | 开发和预览文档时     |
| `make docs-build`   | 构建静态站点到 `docs/site`                   | 本地生成生产版本     |
| `make docs-clean`   | 删除 `docs/site` 目录                        | 清理构建产物时       |

### 使用流程

**第一次使用（安装依赖）：**

```bash
make docs-install    # 安装 mkdocs 和 material 主题等依赖
```

**日常开发（预览文档）：**

```bash
make docs-serve      # 启动本地服务器，访问 http://127.0.0.1:8030 查看
# 修改文档后浏览器会自动刷新
```

**本地生成和查看（构建生产版本）：**

```bash
make docs-build      # 生成静态网站到 docs/site 目录
# 在本地浏览器中打开 docs/site/index.html 查看
make docs-clean      # 清理构建产物（可选）
```

### 完整工作流示例

```bash
# 1. 首次设置：安装依赖
make docs-install

# 2. 开发阶段：预览文档（可反复执行）
make docs-serve      # 在浏览器中访问 http://127.0.0.1:8030
# ...编辑文档...
# 按 Ctrl+C 停止服务

# 3. 本地生成：构建生产版本
make docs-build      # 生成 docs/site 目录
# 在本地浏览器中打开 docs/site/index.html 查看

# 4. 清理（可选）
make docs-clean      # 删除 docs/site 目录
```

### 说明

- 端口与地址目前写死于 `docs/Makefile` 中，可自行修改。
- `make docs-serve` 适合开发时使用，支持热重载
- `make docs-build` 生成完整的静态网站文件，输出到 docs/site 目录，可本地预览最终效果（打开 docs/site/index.html）

---

## PDF 手册构建（Pandoc + XeLaTeX）

用于生成较高排版质量开发者 PDF 手册：

| 目标             | 作用                                     |
| ---------------- | ---------------------------------------- |
| `make pdf`       | 从有序 Markdown 源生成 `ucagent-doc.pdf` |
| `make pdf-one`   | 与 `pdf` 等价（方便 CI 调用）            |
| `make pdf-clean` | 清理生成的 PDF 与 LaTeX 临时文件         |

### 示例

```bash
make pdf
make MONO="JetBrains Mono" pdf      # 覆盖等宽字体
make TWOSIDE=1 pdf                   # 双面排版（文件名添加 -twoside）
make pdf-clean
```

### 依赖

- pandoc
- XeLaTeX (TexLive)
- 中文字体 "Noto Serif CJK SC"
- 等宽字体（默认 DejaVu Sans Mono）
- 可选过滤器 `pandoc-crossref`

### 自定义变量

- `MONO` 更换等宽字体
- `TWOSIDE` 非空启用双面模式

### 常见问题

- **字体缺失：** 安装 CJK 字体包（如 `fonts-noto-cjk`）。
- **LaTeX 报错：** 确保安装完整 XeLaTeX 套件（必要时 `texlive-full`）。
- **交叉引用缺失：** 确认 `pandoc-crossref` 在 PATH 中。

输出：`ucagent-doc.pdf` 可随版本发布分发。

---

## 获取更多帮助

- 📚 [UCAgent 在线文档](https://ucagent.open-verify.cc)
- 🚀 [快速开始指南](https://ucagent.open-verify.cc/content/02_usage/01_direct/)
- 🔧 [自定义配置](https://ucagent.open-verify.cc/content/03_develop/01_customize/)
- 🛠️ [工具列表](https://ucagent.open-verify.cc/content/03_develop/02_tool_list/)
- 💬 [GitHub Issues](https://github.com/XS-MLVP/UCAgent/issues)

### 贡献指南

欢迎提交 Issue 和 Pull Request！
