# MiniWorkflow - 定制工作流示例

这是一个完整的 UCAgent 定制工作流示例，演示如何从零开始创建自定义工作流。

## 📚 完整教程

详细的定制工作流教程请参考：[自定义工作流完整指南](../../docs/content/04_custom_workflow/00_index.md)

## 🎯 示例说明

本示例实现了一个**文档生成器工作流**，功能是为软件项目自动生成完整的技术文档。

### 工作流结构

```yaml
工作流：MiniWorkflow (2个阶段)
├── 阶段1: analyze_project (项目分析)
│   ├── 工具: CountWords - 统计文档字数
│   ├── 工具: ExtractSections - 提取文档结构
│   └── 任务: 分析项目README，生成项目分析报告
│
└── 阶段2: generate_documentation (文档生成)
    ├── 检查器: WordCountChecker - 验证文档字数
    ├── 检查器: RequiredSectionsChecker - 验证章节完整性
    └── 任务: 根据分析报告生成完整的技术文档
```

### 文件结构

```
MiniWorkflow/
├── Calculator/                    # 示例项目（计算器）
│   └── README.md                  # 项目描述文件
├── Guide_Doc/                     # 指导文档目录
│   ├── project_analysis_guide.md              # 项目分析指南
│   ├── documentation_template.md              # 文档结构指导
│   ├── Calculator_bug_analysis.md             # Bug 分析示例文档
│   ├── Calculator_functions_and_checks.md     # 功能与检查点示例
│   └── Calculator_line_coverage_analysis.md   # 行覆盖率分析示例
├── mini.yaml                      # 工作流配置
├── my_tools.py                    # 自定义工具
├── my_checkers.py                 # 自定义检查器
├── Makefile                       # 构建和运行脚本
├── __init__.py                    # Python 包初始化文件
└── README.md                      # 本文件
```

## 🚀 快速开始

### 1. 安装依赖

```bash
# 在 UCAgent 根目录下
pip install -r requirements.txt
```

### 2. 测试工具和检查器

```bash
cd examples/MiniWorkflow
make test
```

预期输出：

```
测试自定义工具...
工具导入成功
测试自定义检查器...
检查器导入成功
所有测试通过!
```

### 3. 运行工作流

```bash
make run
```

工作流会执行以下步骤：

1. 清理并初始化输出目录
2. 复制 Calculator 项目到 output/
3. 启动 UCAgent 执行2个阶段
4. 生成项目分析和技术文档

**预期运行时间**：10-20 分钟（取决于大模型响应速度）

## 📋 核心组件说明

### 1. 工作流配置 (mini.yaml)

```yaml
stages:
  - name: analyze_project # 第一阶段：项目分析
    tasks:
      - description: 分析项目
        input_files:
          - "{PROJECT}/README.md"
        output_files:
          - "unity_test/{DUT}_analysis.md"

  - name: generate_documentation # 第二阶段：文档生成
    tasks:
      - description: 生成文档
        output_files:
          - "unity_test/{DUT}_documentation.md"
    checkers:
      - WordCountChecker
      - RequiredSectionsChecker
```

### 2. 自定义工具 (my_tools.py)

#### CountWords - 字数统计工具

- **功能**：统计文档字数、段落数、章节数
- **用途**：帮助了解项目规模，控制生成文档长度

#### ExtractSections - 章节提取工具

- **功能**：提取 Markdown 文档的标题结构
- **用途**：分析文档组织，确保结构完整

### 3. 自定义检查器 (my_checkers.py)

#### WordCountChecker - 字数检查器

- **检查项**：文档字数是否在指定范围（默认500-2000字）
- **目的**：确保文档详略得当，不过于简略或冗长

#### RequiredSectionsChecker - 章节检查器

- **检查项**：文档是否包含所有必需章节
- **必需章节**：项目概述、功能说明、技术架构、使用方法
- **目的**：确保文档结构完整，符合技术文档规范

### 4. 指导文档 (Guide_Doc/)

#### project_analysis_guide.md

项目分析指南，包含4个分析维度：

- 基本信息（名称、版本、状态）
- 功能概述（核心功能、扩展功能）
- 技术特性（架构、性能、跨平台支持）
- 使用场景（目标用户、典型应用）

#### documentation_template.md

技术文档模板，定义标准结构：

- 项目概述（背景、定位、版本）
- 功能说明（详细功能列表）
- 技术架构（技术栈、设计模式）
- 使用方法（安装、配置、示例）

## 🔍 生成结果示例

成功运行后，在 `output/unity_test/` 目录下会生成：

1. **Calculator_analysis.md** - 项目分析报告
   - 字数：~1000字
   - 内容：项目基本信息、功能概述、技术特性、使用场景

2. **Calculator_documentation.md** - 完整技术文档 ✅
   - 字数：~1500字
   - 章节：项目概述、功能说明、技术架构、使用方法
   - 状态：通过所有检查器验证

## 🛠️ 自定义和扩展

### 修改检查标准

编辑 `mini.yaml` 中的检查器配置：

```yaml
checkers:
  - name: WordCountChecker
    file_path: "unity_test/{DUT}_documentation.md"
    word_min: 1000 # 修改最小字数
    word_max: 3000 # 修改最大字数

  - name: RequiredSectionsChecker
    file_path: "unity_test/{DUT}_documentation.md"
    required_sections: # 自定义必需章节
      - "API文档"
      - "配置指南"
```

### 添加新工具

1. 在 `my_tools.py` 中定义新工具类（继承 `UCTool`）
2. 在 `mini.yaml` 的 `ex_tools` 中注册
3. 在阶段任务中引用新工具

### 添加新检查器

1. 在 `my_checkers.py` 中定义新检查器类（继承 `Checker`）
2. 在 `mini.yaml` 的相应阶段添加检查器配置

## 📖 学习路径

建议按以下顺序学习：

1. **阅读教程文档** - [00_index.md](../../docs/content/04_custom_workflow/00_index.md)
2. **理解架构** - [01_ucagent_architecture.md](../../docs/content/04_custom_workflow/01_ucagent_architecture.md)
3. **研究本示例代码** - 从 mini.yaml 开始，理解配置结构
4. **运行并观察** - `make run` 查看实际执行过程
5. **修改和实验** - 调整配置参数，观察行为变化
6. **创建自己的工作流** - 参考本示例，为自己的项目定制

## ❓ 常见问题

### Q1: 运行时提示找不到模块？

**A**: 确保在 UCAgent 根目录安装了依赖：`pip install -r requirements.txt`

### Q2: 工作流执行失败？

**A**: 检查以下项：

- 是否配置了有效的大模型 API（在 config.yaml 或环境变量中）
- 网络连接是否正常
- 查看 `output/.ucagent/logs/` 下的日志文件

### Q3: 生成的文档不符合预期？

**A**: 可以：

- 修改 `Guide_Doc/` 下的指导文档，提供更详细的规范
- 调整 `mini.yaml` 中的任务描述
- 在 TUI 界面中使用 `human_modify` 命令人工修正

### Q4: 如何跳过某个阶段？

**A**: 启动后在 TUI 界面中输入：`skip_stage <stage_name>`

### Q5: 检查器一直失败怎么办？

**A**: 可以：

- 调整检查器参数（放宽标准）
- 使用 `hmcheck_set false <checker_name>` 临时关闭检查器
- 人工修改输出文件后重新检查

## 🔗 相关资源

- [完整教程](../../docs/content/04_custom_workflow/00_index.md)
- [UCAgent 架构](../../docs/content/04_custom_workflow/01_ucagent_architecture.md)
- [Formal 专业案例](../../docs/content/04_custom_workflow/07_formal_analysis.md)
- [调试指南](../../docs/content/04_custom_workflow/08_run_debug.md)

## 📝 许可证

本示例遵循 UCAgent 项目的许可证。
