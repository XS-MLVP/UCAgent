# 创建工作流配置

工作流配置是 UCAgent 的核心，它定义了整个验证任务的步骤、检查点和执行逻辑。可以说，**工作流就是任务的骨架**，决定了 Agent 要做什么、如何做、如何验证。

## 为什么需要工作流配置？

在传统的自动化脚本中，我们需要编写大量代码来定义任务流程。而在 UCAgent 中，您只需要：

1. **用自然语言描述任务**：告诉 Agent 每个阶段要做什么
2. **指定参考资料**：提供模板文件作为规范指导
3. **配置验证规则**：定义检查器确保输出质量

这样，您就能构建一个灵活、可维护的验证工作流。

## Mini-Example：计算器文档生成器

让我们通过实际例子学习。我们要为计算器项目创建一个文档生成工作流，包含两个阶段（Stage）：

### 阶段1：分析计算器项目

- 读取 `Calculator/README.md` 了解项目
- 提取核心功能、技术特性、使用场景
- 生成分析文档 `output/Calculator_analysis.md`

### 阶段2：生成项目文档

- 基于分析结果
- 按照文档模板规范
- 生成完整的项目文档 `output/Calculator_documentation.md`

## 工作流配置文件结构

工作流配置使用 YAML 格式，包含以下核心部分：

```yaml
# 1. 自定义工具注册（External Tools）
ex_tools:
  - "module.path.ToolClass"

# 2. 模板变量定义（Template Variables）
template_overwrite:
  PROJECT: "Calculator"
  OUT: "output"

# 3. 任务描述（Mission）
mission:
  name: "项目文档生成任务"
  prompt:
    system: "你是一位技术文档专家..."

# 4. 工作流定义（Stages）
stage:
  - name: stage_name
    desc: "阶段描述"
    task: [...]
    reference_files: [...]
    output_files: [...]
    checker: [...]
```

??? note "关于后端配置"
MiniWorkflow 示例使用 **MCP (Model Context Protocol) 模式**，通过外部 Code Agent（如 Claude、Cursor）来执行任务，因此**不需要在配置文件中设置 backend**。

## 完整的 mini.yaml 实现

现在让我们逐部分编写完整的配置文件：

### 第1部分：自定义工具注册

```yaml
# ===== 自定义工具注册（External Tools） =====
# 注册我们自己编写的工具，让 Agent 可以调用
ex_tools:
  - "examples.MiniWorkflow.my_tools.CountWords"
  - "examples.MiniWorkflow.my_tools.ExtractSections"
```

**说明**：

- `ex_tools`：列表形式，每项是一个工具类的完整模块路径
- Agent 启动时会自动加载这些工具
- 工具的具体实现我们将在第4章学习

### 第2部分：模板变量定义

```yaml
# ===== 模板变量定义（Template Variables） =====
# 定义在整个工作流中使用的变量，可以在配置和模板中引用
template_overwrite:
  PROJECT: "Calculator" # 项目名称
  OUT: "output" # 输出目录
  DOC_GEN_LANG: "中文" # 文档生成语言
```

**说明**：

- `template_overwrite`：定义全局变量
- 在配置文件中使用：`{PROJECT}` 会被替换为 `Calculator`
- 在模板文件中使用：`{PROJECT}` 也会被自动替换
- 这样修改项目名称时，只需改一处即可

### 第3部分：保护目录配置

```yaml
# ===== 保护目录配置 =====
# 防止 Agent 误修改重要文件
un_write_dirs:
  - "Calculator/" # 保护源项目目录
  - "Guide_Doc/" # 保护指导文档目录
```

**说明**：

- `un_write_dirs`：禁止写入的目录列表
- Agent 尝试写入这些目录时会被拒绝，确保安全

### 第4部分：任务描述

```yaml
# ===== 任务描述（Mission） =====
# 告诉 Agent 它的角色和职责
mission:
  name: "{PROJECT} 文档生成任务"
  prompt:
    system: |
      你是一位优秀的技术文档工程师，擅长分析项目并编写高质量的文档。

      你的任务是：
      1. 仔细阅读项目的 README 文件，理解项目的核心功能和技术特性
      2. 按照提供的模板规范，生成结构清晰、内容完整的项目文档
      3. 使用 {DOC_GEN_LANG} 编写所有文档
      4. 确保文档符合 Markdown 格式规范

      请使用工具 ReadTextFile 读取文件内容，使用 EditTextFile 创建或修改文件。
      在计划通过Complete工具推进到下一个阶段前，需要通过工具SetCurrentStageJournal 进行阶段日志记录，方便后续追踪和分析。
      完成每个阶段后，务必使用 Complete 工具检查并推进到下一阶段。
```

**说明**：

- `mission.name`：任务名称，可使用变量
- `mission.prompt.system`：系统提示（System Prompt），定义 Agent 的角色和行为
- 这里我们告诉 Agent 它是文档工程师，要完成什么任务

### 第5部分：工作流定义（核心）

```yaml
# ===== 工作流定义（Stages） =====
stage:
  # ========== 阶段1：分析计算器项目 ==========
  - name: analyze_project
    desc: "分析项目功能和特性"

    # 任务列表（Task List）
    # Agent 会按照这些描述执行任务
    task:
      - "第1步：使用 ReadTextFile 工具读取 {PROJECT}/README.md，了解项目的基本信息"
      - "第2步：仔细分析项目的核心功能、技术特性和使用场景"
      - "第3步：参考 Guide_Doc/project_analysis_guide.md 的指导，提取关键信息"
      - "第4步：使用 EditTextFile 工具创建分析文档 {OUT}/{PROJECT}_analysis.md"
      - "第5步：使用 CountWords 工具统计文档字数，确保内容充实"
      - "第6步：使用 Complete 工具完成当前阶段"

    # 参考文件（Reference Files）
    # Agent 会在执行任务前阅读这些文件作为指导
    reference_files:
      - "Guide_Doc/project_analysis_guide.md"

    # 预期输出文件（Output Files）
    # 声明这个阶段会生成哪些文件
    output_files:
      - "{OUT}/{PROJECT}_analysis.md"

    # 检查器列表（Checkers）
    # 用于验证阶段输出是否合格
    checker:
      # 检查器1：验证文档字数
      - name: word_count_check
        clss: "examples.MiniWorkflow.my_checkers.WordCountChecker"
        args:
          file_path: "{OUT}/{PROJECT}_analysis.md"
          word_min: 500
          word_max: 2000

      # 检查器2：验证 Markdown 格式
      - name: markdown_format_check
        clss: "UnityChipCheckerMarkdownFileFormat"
        args:
          markdown_file_list: "{OUT}/{PROJECT}_analysis.md"
          no_line_break: true

  # ========== 阶段2：生成项目文档 ==========
  - name: generate_documentation
    desc: "生成完整的项目文档"

    task:
      - "第1步：使用 ReadTextFile 工具读取 {OUT}/{PROJECT}_analysis.md，了解分析结果"
      - "第2步：参考 Guide_Doc/documentation_template.md 的文档结构要求"
      - "第3步：基于分析结果，编写完整的项目文档，包含：项目概述、功能说明、技术架构、使用方法"
      - "第4步：使用 EditTextFile 工具创建文档 {OUT}/{PROJECT}_documentation.md"
      - "第5步：使用 ExtractSections 工具检查文档章节结构是否完整"
      - "第6步：使用 Complete 工具完成当前阶段"

    reference_files:
      - "Guide_Doc/documentation_template.md"
      - "{OUT}/{PROJECT}_analysis.md" # 前一个阶段的输出也可以作为参考

    output_files:
      - "{OUT}/{PROJECT}_documentation.md"

    checker:
      # 检查器1：验证文档字数
      - name: word_count_check
        clss: "examples.MiniWorkflow.my_checkers.WordCountChecker"
        args:
          file_path: "{OUT}/{PROJECT}_documentation.md"
          word_min: 800
          word_max: 3000

      # 检查器2：验证必需章节
      - name: required_sections_check
        clss: "examples.MiniWorkflow.my_checkers.RequiredSectionsChecker"
        args:
          file_path: "{OUT}/{PROJECT}_documentation.md"
          required_sections:
            - "项目概述"
            - "功能说明"
            - "技术架构"
            - "使用方法"

      # 检查器3：验证 Markdown 格式
      - name: markdown_format_check
        clss: "UnityChipCheckerMarkdownFileFormat"
        args:
          markdown_file_list: "{OUT}/{PROJECT}_documentation.md"
          no_line_break: true
```

## 配置字段详解

### Stage 字段说明

| 字段              | 类型         | 必需 | 说明                               |
| ----------------- | ------------ | ---- | ---------------------------------- |
| `name`            | string       | 是   | 阶段的唯一标识符，用于日志和命令   |
| `desc`            | string       | 是   | 阶段的简短描述，显示在 TUI 界面    |
| `task`            | list[string] | 是   | 任务列表，用自然语言描述要做的事   |
| `reference_files` | list[string] | 否   | 参考文件列表，Agent 会读取这些文件 |
| `output_files`    | list[string] | 否   | 预期输出文件，用于文档说明         |
| `checker`         | list[object] | 否   | 检查器列表，验证阶段输出质量       |

### Checker 配置说明

每个检查器包含三个字段：

```yaml
- name: checker_name # 检查器名称（用于日志）
  clss: "module.Class" # 检查器类的完整路径
  args: # 传递给检查器的参数
    param1: value1
    param2: value2
```

## 变量使用规范

在配置文件中可以使用以下变量：

| 变量             | 说明                       | 示例         |
| ---------------- | -------------------------- | ------------ |
| `{PROJECT}`      | 项目名称                   | `Calculator` |
| `{OUT}`          | 输出目录                   | `output`     |
| `{DOC_GEN_LANG}` | 文档语言                   | `中文`       |
| `{DUT}`          | 待测模块名（硬件验证场景） | -            |

**使用位置**：

- ✅ 可以在 `task`、`reference_files`、`output_files` 中使用
- ✅ 可以在 `checker.args` 中使用
- ✅ 可以在 `mission.name` 和 `mission.prompt` 中使用
- ❌ 不能在 `name`、`desc`、`clss` 中使用

## 完整文件预览

以上所有配置整合后，完整的 `mini.yaml` 文件如下：

```yaml
# mini.yaml - 计算器文档生成器工作流配置

ex_tools:
  - "examples.MiniWorkflow.my_tools.CountWords"
  - "examples.MiniWorkflow.my_tools.ExtractSections"

template_overwrite:
  PROJECT: "Calculator"
  OUT: "output"
  DOC_GEN_LANG: "中文"

un_write_dirs:
  - "Calculator/"
  - "Guide_Doc/"

mission:
  name: "{PROJECT} 文档生成任务"
  prompt:
    system: |
      你是一位优秀的技术文档工程师，擅长分析项目并编写高质量的文档。

      你的任务是：
      1. 仔细阅读项目的 README 文件，理解项目的核心功能和技术特性
      2. 按照提供的模板规范，生成结构清晰、内容完整的项目文档
      3. 使用 {DOC_GEN_LANG} 编写所有文档
      4. 确保文档符合 Markdown 格式规范

      请使用工具 ReadTextFile 读取文件内容，使用 EditTextFile 创建或修改文件。
      在计划通过Complete工具推进到下一个阶段前，需要通过工具SetCurrentStageJournal 进行阶段日志记录，方便后续追踪和分析。
      完成每个阶段后，务必使用 Complete 工具检查并推进到下一阶段。

stage:
  - name: analyze_project
    desc: "分析项目功能和特性"
    task:
      - "第1步：使用 ReadTextFile 工具读取 {PROJECT}/README.md，了解项目的基本信息"
      - "第2步：仔细分析项目的核心功能、技术特性和使用场景"
      - "第3步：参考 Guide_Doc/project_analysis_guide.md 的指导，提取关键信息"
      - "第4步：使用 EditTextFile 工具创建分析文档 {OUT}/{PROJECT}_analysis.md"
      - "第5步：使用 CountWords 工具统计文档字数，确保内容充实"
      - "第6步：使用 Complete 工具完成当前阶段"
    reference_files:
      - "Guide_Doc/project_analysis_guide.md"
    output_files:
      - "{OUT}/{PROJECT}_analysis.md"
    checker:
      - name: word_count_check
        clss: "examples.MiniWorkflow.my_checkers.WordCountChecker"
        args:
          file_path: "{OUT}/{PROJECT}_analysis.md"
          word_min: 500
          word_max: 2000
      - name: markdown_format_check
        clss: "UnityChipCheckerMarkdownFileFormat"
        args:
          markdown_file_list: "{OUT}/{PROJECT}_analysis.md"
          no_line_break: true

  - name: generate_documentation
    desc: "生成完整的项目文档"
    task:
      - "第1步：使用 ReadTextFile 工具读取 {OUT}/{PROJECT}_analysis.md，了解分析结果"
      - "第2步：参考 Guide_Doc/documentation_template.md 的文档结构要求"
      - "第3步：基于分析结果，编写完整的项目文档，包含：项目概述、功能说明、技术架构、使用方法"
      - "第4步：使用 EditTextFile 工具创建文档 {OUT}/{PROJECT}_documentation.md"
      - "第5步：使用 ExtractSections 工具检查文档章节结构是否完整"
      - "第6步：使用 Complete 工具完成当前阶段"
    reference_files:
      - "Guide_Doc/documentation_template.md"
      - "{OUT}/{PROJECT}_analysis.md"
    output_files:
      - "{OUT}/{PROJECT}_documentation.md"
    checker:
      - name: word_count_check
        clss: "examples.MiniWorkflow.my_checkers.WordCountChecker"
        args:
          file_path: "{OUT}/{PROJECT}_documentation.md"
          word_min: 800
          word_max: 3000
      - name: required_sections_check
        clss: "examples.MiniWorkflow.my_checkers.RequiredSectionsChecker"
        args:
          file_path: "{OUT}/{PROJECT}_documentation.md"
          required_sections:
            - "项目概述"
            - "功能说明"
            - "技术架构"
            - "使用方法"
      - name: markdown_format_check
        clss: "UnityChipCheckerMarkdownFileFormat"
        args:
          markdown_file_list: "{OUT}/{PROJECT}_documentation.md"
          no_line_break: true
```

## 配置编写技巧

### 1. Task 编写原则

✅ **好的 Task 描述**：

- 明确具体：告诉 Agent 做什么、用什么工具
- 步骤清晰：使用"第1步"、"第2步"编号
- 包含验证：最后一步总是"使用 Complete 工具完成"

❌ **不好的 Task 描述**：

- "分析项目" ➜ 太模糊，Agent 不知道具体做什么
- "生成文档" ➜ 没有说明输出位置和格式要求

### 2. Reference Files 使用建议

- 将通用规范放在模板文件中
- 前一阶段的输出可以作为后续阶段的参考
- 使用变量让配置更灵活

### 3. Checker 配置建议

- 至少配置一个格式检查器（如 Markdown 格式）
- 添加业务检查器验证特定规则（如字数、章节）
- 检查器失败时，Agent 会自动重试修正

## 小结

通过本章，您学会了：

✅ 工作流配置的完整结构  
✅ 如何定义阶段（Stage）和任务（Task）  
✅ 如何配置检查器（Checker）验证输出  
✅ 如何使用变量让配置更灵活

**下一步**：工作流定义了"做什么"，但 Agent 还需要知道"怎么做才规范"。接下来我们学习如何创建模板文件！

👉 继续阅读：[模板文件系统](03_template_files.md)

## 延伸阅读

- [工作流详细文档](../03_develop/01_workflow.md) - 了解更多高级特性
- [内置检查器列表](../03_develop/04_tool_list.md) - 查看可用的内置检查器
