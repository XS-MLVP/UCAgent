# Formal Verification with UCAgent

UCAgent Formal 是一个基于大语言模型驱动的自动化形式化验证框架，能够自动完成从 RTL 分析到 SVA 生成、工具执行和 Bug 报告的全流程验证。

## 📋 目录

- [快速开始](#快速开始)
- [工作流程](#工作流程)
- [生成产物说明](#生成产物说明)
- [使用示例](#使用示例)
- [配置说明](#配置说明)
- [技术架构](#技术架构)

## 🚀 快速开始

### 使用 Docker 环境（推荐）

Docker 环境已包含所有必需的验证工具（Verilator、SWIG、Python、Node.js、npm 等）：

#### 步骤 1：启动 Docker 容器

```bash
# 拉取镜像
docker pull ghcr.io/xs-mlvp/ucagent:latest

# 启动容器（交互式）
docker run -it --rm \
  -v $(pwd):/workspace/examples/Formal \
  -e OPENAI_API_KEY=${OPENAI_API_KEY:-} \
  -w /workspace/examples/Formal \
  ghcr.io/xs-mlvp/ucagent:latest
```

#### 步骤 2：在容器内安装配置 Code Agent

```bash
# 安装 qwen-code-cli
npm install -g @qwen/qwen-code-cli

# 配置 MCP Server
mkdir -p ~/.qwen
cat > ~/.qwen/settings.json << 'EOF'
{
    "mcpServers": {
        "unitytest": {
            "httpUrl": "http://localhost:5000/mcp",
            "timeout": 300000
        }
    }
}
EOF
```

**其他 Code Agent 选项**：
- [Claude Code](https://claude.com/product/claude-code)
- [OpenCode](https://opencode.ai/)
- [GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli)
- [Kilo CLI](https://kilo.ai/cli)

#### 步骤 3：开始验证

**方式一：自动运行（推荐）**

```bash
# 指定后端自动运行，无需手动启动 Code Agent
make mcp_Adder ARGS="--loop --backend=qwen"

# 或使用其他支持的后端，参考 ../../ucagent/setting.yaml
```

**方式二：手动运行 Code Agent**

在第一个终端启动 MCP Server：
```bash
make mcp_Adder
# 启动 MCP Server 在 http://127.0.0.1:5000/mcp
```

在第二个终端（容器内另开一个 shell）启动 Code Agent：
```bash
# 进入同一容器
docker exec -it <container_id> bash
cd /workspace/examples/Formal/output
qwen
```

在 Code Agent 中输入提示词：
> 请通过工具 `RoleInfo` 获取你的角色信息和基本指导，然后完成任务。请使用工具 `ReadTextFile` 读取文件。你需要在当前工作目录进行文件操作，不要超出该目录。

### 本地环境

如果已安装所需依赖（Python 3.11+, Verilator, Node.js, 形式化验证工具等）：

```bash
# 1. 安装 UCAgent
pip install -e ../../

# 2. 安装 Formal 特定依赖
pip install -r requirements.txt

# 3. 安装并配置 Code Agent（以 qwen 为例）
npm install -g @qwen/qwen-code-cli
# 配置 ~/.qwen/settings.json（参考上述 Docker 步骤）

# 4. 运行验证
make mcp_Adder ARGS="--loop --backend=qwen"
```

## 🔄 工作流程

Formal Agent 将验证任务分解为 8 个自动化阶段：

```
┌─────────────────────────────────────────────────────────────┐
│  1. 需求分析与规划                                            │
│     → 理解设计范围，制定验证策略                                │
├─────────────────────────────────────────────────────────────┤
│  2. DUT 功能理解                                             │
│     → 解析 RTL 接口、时钟域、内部结构                         │
├─────────────────────────────────────────────────────────────┤
│  3. 功能规格分析                                             │
│     → 分解为功能组 <FG>、功能点 <FC>、检测点 <CK>            │
├─────────────────────────────────────────────────────────────┤
│  4. 验证环境生成                                             │
│     → 生成 Checker + Wrapper，实现白盒信号可见               │
├─────────────────────────────────────────────────────────────┤
│  5. SVA 属性生成                                             │
│     → 将每个 <CK> 转换为对应的 SVA 代码                      │
├─────────────────────────────────────────────────────────────┤
│  6. 脚本生成                                                 │
│     → 自动生成形式化验证工具 TCL 脚本                         │
├─────────────────────────────────────────────────────────────┤
│  7. 环境调试                                                 │
│     → 迭代消除 TRIVIALLY_TRUE 等环境问题                     │
├─────────────────────────────────────────────────────────────┤
│  8. Bug 分析与报告                                           │
│     → 分析反例，定位根因，生成修复建议                        │
└─────────────────────────────────────────────────────────────┘
```

## 📦 生成产物说明

运行验证后，会在 `output/unity_tests/tests/` 目录下生成以下核心文件：

```
output/unity_tests/tests/
├── {DUT}_checker.sv       # SVA 属性文件（Safety/Liveness/Assume/Cover）
├── {DUT}_wrapper.sv       # DUT 包装器（白盒信号提取）
├── {DUT}_formal.tcl       # 形式化验证工具脚本
└── avis/                  # 验证工具输出
    ├── avis.log          # 验证结果日志
    └── ...               # 反例波形等
```

### 验证结果解读

查看 `avis.log` 了解各属性的证明结果：

```
Property                Result          含义
----------------------------------------------------
A_CK_OVERFLOW          PASS            ✅ 属性通过验证
A_CK_LIVENESS          FALSE           ❌ 发现反例（潜在 Bug）
C_CK_STATE_FULL        PASS            ✅ 覆盖率达到
M_CK_VALID_STABLE      TRIVIALLY_TRUE  ⚠️ 环境过约束
```

## 📝 使用示例

### 示例 1：验证 Adder（加法器）

```bash
# 初始化并验证
make mcp_Adder

# 查看生成的 SVA
cat output/unity_tests/tests/Adder_checker.sv

# 查看验证结果
cat output/unity_tests/tests/avis.log
```

**预期产物**：
- 6-10 条算术属性（溢出检查、结果正确性）
- 2-4 条环境约束（输入有效性）
- 2-3 条覆盖属性（边界条件可达性）

### 示例 2：验证交通灯控制器

```bash
# 初始化交通灯设计（包含已知 Bug）
make init_traffic
cd output/traffic

# 运行 UCAgent
ucagent . traffic --config ../../formal.yaml \
  --guid-doc-path ../../FormalDoc/ \
  --output ../../unity_tests
（可选）

```bash
# OpenAI API（使用 OpenAI 模型时需要）
export OPENAI_API_KEY=sk-xxx

# 或使用其他兼容 API
export OPENAI_API_BASE=https://your-api-endpoint
export OPENAI_API_KEY=your-api-key

# LangChain 追踪（可选，用于调试）
export LANGCHAIN_API_KEY=lsv2_xxx
export LANGCHAIN_TRACING_V2=true
```

> **提示**：具体需要哪些环境变量取决于你选择的 AI 模型后端，详见配置文件 `formal.yaml# 示例 3：自定义设计验证

```bash
# 1. 准备设计文件
mkdir -p rtls/MyDesign
cp your_design.v rtls/MyDesign/

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

### 环境变量

```bash
# OpenAI API（必需）
export OPENAI_API_KEY=sk-xxx

# LangChain 追踪（可选）
export LANGCHAIN_API_KEY=lsv2_xxx
export LANGCHAIN_TRACING_V2=true
```

## 🏗️ 技术架构

### 核心特性

- **风格标注规格语言**：`<FG-功能组>/<FC-功能点>/<CK-检测点>` 结构化分解
- **符号化索引**：使用 `fv_idx` 验证数组型结构（寄存器堆、FIFO、Cache）
- **自动化调试**：迭代消除 TRIVIALLY_TRUE 等环境问题
- **MCP 协议集成**：与外部 Code Agent 无缝协作

### 验证工具支持

| 工具 | 状态 | 说明 |
|------|------|------|
| JasperGold | ✅ | Cadence 形式化验证工具 |
| VC Formal | ✅ | Synopsys 形式化验证工具 |
| AVI | ✅ | 开源形式化验证工具 |

## � 常见问题

**Q: 如何处理 TRIVIALLY_TRUE？**  
A: Agent 会自动检测并迭代修复环境过约束问题。

**Q: 如何加速证明？**  
A: 使用符号化索引、添加精确的环境约束、分解复杂属性。

**Q: 验证失败怎么办？**  
A: 查看 `avis.log` 分析失败原因，Agent 会自动生成 Bug 报告和修复建议。

## 📚 参考文档

- [形式化验证指南](./FormalDoc/) - 详细的风格指南和模板
- [UCAgent 文档](../../docs/) - 完整框架文档

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

- Bug 报告：https://github.com/XS-MLVP/UCAgent/issues
- 功能建议：https://github.com/XS-MLVP/UCAgent/discussions

## 📄 许可证

MIT License - 详见 [LICENSE](../../LICENSE)

---

**UCAgent Formal** - 让形式化验证变得简单
