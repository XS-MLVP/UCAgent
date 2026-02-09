# 完整 Mini 示例

> 💡 **前置学习**：本示例综合了前面章节的所有知识。建议先阅读 [快速开始](01_quick_start.md)、[架构与工作原理](02_architecture.md)、[工作流配置](03_workflow.md)、[定制工具](05_customize.md) 和 [检查器](07_checkers.md)

恭喜！您已经学习了 UCAgent 的四大核心组件。现在让我们将它们整合起来，运行一个完整的工作流示例。

## 项目文件结构

完整的 MiniWorkflow 项目结构如下：

```
examples/MiniWorkflow/
├── Calculator/                          # 示例项目
│   └── README.md                        # 项目说明文档
├── Guide_Doc/                           # 指导文档目录
│   ├── project_analysis_guide.md       # 项目分析指南
│   ├── documentation_template.md       # 文档结构指导
│   ├── Calculator_bug_analysis.md      # Bug 分析示例
│   ├── Calculator_functions_and_checks.md  # 功能检查点示例
│   └── Calculator_line_coverage_analysis.md  # 覆盖率分析示例
├── mini.yaml                            # 工作流配置文件（约90行）
├── my_tools.py                      # 自定义工具（约100行）
├── my_checkers.py                   # 自定义检查器（约120行）
├── Makefile                         # 构建脚本
├── __init__.py                      # Python 包标记
└── output/                          # 输出目录（运行后生成）
    ├── Calculator_analysis.md       # 阶段1输出
    └── Calculator_documentation.md  # 阶段2输出
```

## 快速开始

### 1. 前置条件

确保已安装 UCAgent：

```bash
# 检查安装
ucagent --version

# 或使用项目中的 ucagent.py
python3 ucagent.py --version
```

### 2. 进入项目目录

```bash
cd examples/MiniWorkflow/
```

### 3. 运行工作流

使用 Makefile 一键运行：

```bash
make run
```

或使用完整命令：

```bash
# 先准备工作目录
mkdir -p output
cp -r Calculator output/

# 运行 UCAgent
ucagent ./output/ Calculator \
  --mcp-server-no-file-tools \
  --config ./mini.yaml \
  --guid-doc-path ./Guide_Doc/ \
  -s -hm --tui --no-embed-tools
```

**参数说明**：

- `./output/`：工作目录（将 Calculator 复制到此目录）
- `Calculator`：项目名称（对应 `{PROJECT}` 变量）
- `--mcp-server-no-file-tools`：使用 MCP Server 模式（不含文件工具）
- `--config ./mini.yaml`：指定工作流配置文件
- `--guid-doc-path ./Guide_Doc/`：指定指导文档目录
- `-s`：单步模式，每个阶段执行后暂停
- `-hm`：启用人工检查模式
- `--tui`：使用文本用户界面
- `--no-embed-tools`：不嵌入工具到提示词

### 4. 启动Code Agent

另开一个终端启动Code Agent

```bash
# 切换到目录
cd examples/MiniWorkflow/outpute
# 启动Code Agent（以gemini为例）
gemini -y
```

启动后在输入框输入提示词

> 请通过工具`RoleInfo`获取你的角色信息和基本指导，然后完成任务。请使用工具`ReadTextFile`读取文件。你需要在当前工作目录进行文件操作，不要超出该目录。

### 5. 查看输出

运行完成后，查看生成的文档：

```bash
# 查看分析文档
cat output/Calculator_analysis.md

# 查看完整文档
cat output/Calculator_documentation.md
```

## 扩展方向

掌握 mini-example 后，您可以尝试以下扩展：

### 1. 添加第3个阶段

```yaml
stage:
  - name: generate_api_docs
    desc: "生成 API 文档"
    task:
      - "基于项目分析，生成 API 接口文档"
    # ...
```

### 2. 添加更多工具

```python
# 例如：检查链接有效性
class CheckLinks(UCTool):
    name = "CheckLinks"
    description = "检查文档中的所有链接是否有效"
    # ...
```

### 3. 添加更多检查器

```python
# 例如：检查图片引用
class ImageChecker(Checker):
    def do_check(self, ...):
        # 检查所有引用的图片是否存在
        # ...
```

## 性能说明

- **首次运行**：约 1-20 分钟（包含 LLM 推理时间）
- **后续运行**：1-10 分钟（如果有缓存）
- **文件大小**：
  - 分析文档：约 1-2 KB
  - 完整文档：约 2-4 KB

## 小结

通过本章，您已经：

✅ 了解完整项目的文件结构  
✅ 学会使用 Makefile 快速运行  
✅ 掌握了一个完整的工作流示例

## 进一步学习

- [工作流配置](03_workflow.md) - 深入了解工作流的详细配置
- [模板文件](04_template.md) - 学习如何编写模板文件
- [定制工具](05_customize.md) - 开发更复杂的自定义工具
- [检查器](07_checkers.md) - 编写自定义检查器
- [快速开始](01_quick_start.md) - 创建自己的工作流
