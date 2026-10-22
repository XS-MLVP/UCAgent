
# 前置依赖安装

> 注：本文所有示例输出目录统一以 `output` 为例，用户可自行修改自定义工作目录。

## 1.1 系统要求

- 开源仓库代码 Python 版本：3.11+
- 操作系统：Linux / macOS
- API 需求：选择 LangChain 或命令行后端时，都需要一个可访问的模型服务；具体环境变量见[直接使用](../02_usage/01_direct.md)
- 内存：建议 4GB+
- 依赖：
  - [picker](https://github.com/XS-MLVP/picker)（RTL 验证需要，用于导出 Python DUT 包；安装和仿真器依赖见其项目文档）
  - 外部 Code Agent（仅 MCP/命令行后端需要），例如 [opencode](https://opencode.ai/)

## 1.2 安装 UCAgent 主体

**方式一（推荐）：克隆仓库并安装依赖**

```bash
git clone https://github.com/XS-MLVP/UCAgent.git
cd UCAgent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
```

完整克隆源码仓库，本地保留 Makefile，后续可使用 `make` 系列快捷指令。

**方式二：pip 直接安装**

```bash
python3 -m venv ~/.venvs/ucagent
source ~/.venvs/ucagent/bin/activate
python -m pip install --upgrade pip
python -m pip install git+https://github.com/XS-MLVP/UCAgent@main
```

仅安装 UCAgent 程序包，本地不保留源码，无 Makefile，无法使用 `make` 指令，需直接使用 `ucagent` 原生命令行参数启动。

## 安装测试

安装后先检查当前环境：

```bash
python --version
ucagent --help
```

每次打开新终端，都需要重新激活安装时使用的虚拟环境。`ucagent --help` 成功只说明 CLI 可用；进行 RTL 验证前，还需按 picker 文档安装仿真器、CMake 和编译工具，并检查：

```bash
picker --check
verilator --version
cmake --version
```

这里使用 picker 默认的 Verilator 后端。纯文档类的 [Mini 示例](../03_develop/08_mini_example.md) 不需要 picker。

`ucagent --help` 的界面示例：

![ucagent --help](image1.png)

各参数的分组说明、默认值与完整示例见[参数说明](../02_usage/03_option.md)。

## 1.3 安装 Code Agent（可选）

普通模式的默认 `langchain` 后端不需要外部 Code Agent。选择 `opencode`、`codex`、`claude` 等命令行后端，或手动接入 MCP 时，才需要安装对应客户端。本章后续示例以 opencode 为例；建议固定已验证版本：

```bash
curl -fsSL https://opencode.ai/install | bash -s -- --version 1.19.3
```

UCAgent 当前内置的命令行后端包括 `claude`、`opencode`、`copilot`、`qwen`、`iflow`、`kilo` 和 `codex`。安装客户端后，通过 `--backend=<name>` 选择；客户端的登录、模型和版本要求以其官方文档为准。
