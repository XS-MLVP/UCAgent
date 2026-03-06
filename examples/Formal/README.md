# Formal Verification with UCAgent

UCAgent Formal 是一个基于大语言模型驱动的自动化形式化验证框架，能够自动完成从 RTL 分析到 SVA 生成、工具执行和 Bug 报告的全流程验证。底层形式化引擎使用**形式化属性验证工具 FormalMC**（华大九天），它通过将 RTL 建模为自动机并遍历全状态空间来检验断言，具备业界领先的引擎和验证策略。

## 📋 目录

- [快速开始](#快速开始)
- [工作流程](#工作流程)
- [生成产物说明](#生成产物说明)
- [使用示例](#使用示例)
- [配置说明](#配置说明)

## 🚀 快速开始

### 使用 Docker 环境（推荐）

Docker 环境已包含所有必需的验证工具（Verilator、SWIG、Python、Node.js、npm 等）：

#### 步骤 1：启动 Docker 容器

```bash
# 拉取镜像
docker pull ghcr.io/xs-mlvp/ucagent:latest

# 启动容器（交互式），命名容器方便后续 exec 进入
docker run -it --rm --name ucagent-server \
  -w /workspace/ucagent/examples/Formal \
  ghcr.io/xs-mlvp/ucagent:latest
```

#### 步骤 2：在容器内启动 MCP Server

```bash

# 初始化并启动 MCP Server（以 Adder 为例）
make mcp_Adder
# MCP Server 启动在 http://127.0.0.1:5000/mcp
# 此终端会持续运行，保持不动
```

#### 步骤 3：新开一个终端，进入同一个容器

```bash
# 在宿主机新开一个终端，exec 进入同一个容器
docker exec -it ucagent-server bash
```

#### 步骤 4：安装配置并启动 Code Agent

根据需要选择并安装合适的 Code Agent，配置 MCP Server 地址后启动：

- [Qwen Code](https://qwenlm.github.io/qwen-code-docs/en/)
- [Claude Code](https://claude.com/product/claude-code)
- [OpenCode](https://opencode.ai/)
- [GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli)

MCP Server 地址：`http://localhost:5000/mcp`，超时建议设置 300 秒以上。

之后进入 `/workspace/ucagent/examples/Formal/output` 目录，启动 Code Agent，输入如下提示词：
> 请通过工具 `RoleInfo` 获取你的角色信息和基本指导，然后完成任务。请使用工具 `ReadTextFile` 读取文件。你需要在当前工作目录进行文件操作，不要超出该目录。

---

### 本地部署环境

如果不使用 docker 环境，则需要手动安装所需依赖（Python 3.11+, Verilator, Node.js, 形式化验证工具等）：

```bash
# 1. 安装 UCAgent 及其依赖
pip install -e ../../

# 2. 安装 Formal 特定依赖
pip install -r requirements.txt

# 3. 运行验证
make mcp_Adder

# 3. 安装并配置 Code Agent
# 其他步骤同上
```

## 🔄 工作流程

Formal Agent 将验证任务分解为 8 个自动化阶段：

| 阶段 | 名称 | 说明 |
|:---:|------|------|
| 1 | 需求分析与规划 | 理解设计范围，制定验证策略 |
| 2 | DUT 功能理解 | 解析 RTL 接口、时钟域、内部结构 |
| 3 | 功能规格分析 | 分解为功能组 `<FG>`、功能点 `<FC>`、检测点 `<CK>` |
| 4 | 验证环境生成 | 生成 Checker + Wrapper，实现白盒信号可见 |
| 5 | SVA 属性生成 | 将每个 `<CK>` 转换为对应的 SVA 代码 |
| 6 | 脚本生成 | 自动生成形式化验证工具 TCL 脚本 |
| 7 | 环境调试 | 迭代消除 TRIVIALLY_TRUE 等环境问题 |
| 8 | Bug 分析与报告 | 分析反例，定位根因，生成修复建议 |

## 📦 生成产物说明

运行验证后，会在 `output/unity_test/` 目录下生成以下文件：

### 分析文档

```
output/unity_test/
├── 01_{DUT}_verification_needs_and_plan.md  # 验证需求与规划文档
├── 02_{DUT}_basic_info.md                   # DUT 基础信息（接口定义、时钟域等）
├── 03_{DUT}_functions_and_checks.md         # 功能点与检测点详细描述
├── 04_{DUT}_bug_report.md                   # Bug 分析报告（失败属性的根因分析）
└── 05_{DUT}_formal_summary.md               # 验证总结报告（覆盖率、结果汇总）
```

**说明**：
- `01` 文档包含验证范围定义、关键目标和验证策略
- `02` 文档记录 DUT 的端口信号、时钟复位行为和内部结构分析
- `03` 文档采用 `<FG>`（功能组）→ `<FC>`（功能点）→ `<CK>`（检测点）的层次化结构描述
- `04` 文档对每个失败的属性提供反例分析、根因定位和修复建议
- `05` 文档总结验证覆盖度、通过/失败属性统计和遗留问题

### 验证代码与结果

```
output/unity_test/tests/
├── {DUT}_checker.sv       # SVA 属性文件（Assertion/Assume/Cover）
├── {DUT}_wrapper.sv       # DUT 包装器（实例化 DUT 和 Checker）
├── {DUT}_formal.tcl       # 形式化验证工具脚本（AVIS/JasperGold）
├── avis.log              # 验证结果日志（各属性 PASS/FAIL 状态）
└── avis/                 # 验证工具输出目录
    ├── rtl.stems         # 反例波形文件索引
    └── checker_inst.*/   # 每个失败属性的反例详情
```

**说明**：
- `{DUT}_checker.sv` 包含所有 SVA 断言，按 `A_CK_*`（断言）、`M_CK_*`（假设）、`C_CK_*`（覆盖）命名
- `{DUT}_wrapper.sv` 将 DUT 和 Checker 连接，提供白盒信号访问能力
- `{DUT}_formal.tcl` 配置工具参数（时钟、复位、超时、验证目标等）
- `avis.log` 示例结果：
  ```
  Property                 Result          含义
  --------------------------------------------------
  A_CK_FLUSH_GPF_RESET    FALSE           ❌ 发现反例（Flush 优先级错误）
  A_CK_READ_PTR_INC       PASS            ✅ 属性通过验证
  C_CK_BYPASS_HIT         PASS            ✅ 覆盖率达到
  M_CK_RESET_VALID        TRIVIALLY_TRUE  ⚠️ 环境假设未被激活
  ```

## 📝 使用示例

### 示例 1：验证 Adder（加法器）

```bash
# 初始化并验证
make mcp_Adder

# 启动code agent

# 输入初始提示词

# 查看验证结果
cat output/unity_tests/tests/avis.log
```

**预期产物**：
- 6-10 条算术属性（溢出检查、结果正确性）
- 2-4 条环境约束（输入有效性）
- 2-3 条覆盖属性（边界条件可达性）

### 示例 2：添加新的测试任务

```bash
# 1. 准备设计文件
mkdir -p rtls/MyDesign 
cp /path/to/MyDesign.v rtls/MyDesign/                    # 准备rtl
cp /path/to/MyDesignREADME.md rtls/MyDesign/README.md    # 准备规格说明文档

# 2. 运行验证
make mcp_MyDesign

# 3. 查看生成的验证环境
ls -la output/unity_tests/tests/
```

## ⚙️ 配置说明

### `formal.yaml` 核心配置项

```yaml
# 自定义工具
ex_tools:
  - "examples.Formal.scripts.formal_tools.GenerateChecker"
  - "examples.Formal.scripts.formal_tools.GenerateFormalScript"

# 模板变量
template_overwrite:
  DOC_GEN_LANG: "中文"           # 文档语言
  RTL_PATH: "{DUT}"              # RTL 源码路径
  FILE_PATH: "output/{DUT}"      # 工作目录
  OUT_PATH: "output/{OUT}"       # 输出目录

# 只读目录（禁止修改）
un_write_dirs:
  - "{DUT}/"
  - "Guide_Doc/"

# 指导文档路径
guid_doc_path: "./FormalDoc/"

# 验证任务配置
mission:
  name: "{DUT} 形式化验证任务"
  prompt:
    system: |
      你是一名顶尖的形式化验证架构师...
      核心技术栈：
        - 符号化索引 (fv_idx)
        - 活性证明 (Liveness)
        - 覆盖率驱动 (Cover)
```

## 📚 参考文档

- [形式化验证指南](./FormalDoc/) - 详细的风格指南和模板
- [UCAgent 文档](../../docs/) - 完整框架文档

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

- Bug 报告：https://github.com/XS-MLVP/UCAgent/issues
- 功能建议：https://github.com/XS-MLVP/UCAgent/discussions

---

**UCAgent Formal** - 让形式化验证变得简单
