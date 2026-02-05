# 自定义工具

自定义工具是扩展 UCAgent 能力的关键机制。内置工具提供了通用的文件操作功能，但对于特定领域的任务（如 RTL 解析、仿真执行、文档分析等），我们需要开发自定义工具。可以说，**自定义工具赋予 Agent 专业领域的"超能力"**。

## 为什么需要自定义工具？

UCAgent 内置了丰富的工具（见[工具列表](../03_develop/04_tool_list.md)），如：

- `ReadTextFile`：读取文件内容
- `EditTextFile`：创建或修改文件
- `SearchText`：搜索文本
- `FindFiles`：查找文件

但这些通用工具无法满足所有需求。例如：

❌ **内置工具不足的场景**：

- 统计文档字数和段落数（需要特定的解析逻辑）
- 提取 Markdown 文档的章节结构（需要正则匹配）
- 解析 RTL 代码生成测试环境（需要调用 pyslang 库）
- 执行形式化验证工具（需要调用外部命令）

✅ **自定义工具的优势**：

- 封装复杂逻辑，简化 Agent 调用
- 集成第三方库和工具
- 提供领域专用的数据处理能力
- 返回结构化的结果供 Agent 使用

## Mini-Example 的工具需求

在计算器文档生成器中，我们需要两个自定义工具：

### 工具1：CountWords（统计字数）

- **功能**：统计 Markdown 文件的字数、段落数、章节数
- **用途**：验证文档内容是否充实
- **示例**：`CountWords("output/Calculator_analysis.md")` → 返回 "总字数: 856 字, 段落: 12 段"

### 工具2：ExtractSections（提取章节）

- **功能**：提取 Markdown 文件的所有章节标题
- **用途**：检查文档结构是否完整
- **示例**：`ExtractSections("output/Calculator_documentation.md")` → 返回章节列表

## 工具开发基础

### 核心概念

UCAgent 的工具系统基于以下概念：

1. **继承 UCTool 基类**：所有工具都继承自 `ucagent.tools.uctool.UCTool`
2. **定义参数模式（ArgsSchema）**：使用 Pydantic 定义工具的输入参数
3. **实现 \_run 方法**：在 `_run` 方法中实现工具的核心逻辑
4. **处理路径**：使用 `self.get_path()` 处理文件路径
5. **返回结果**：返回字符串结果供 Agent 使用

### 工具类结构

```python
from pydantic import BaseModel, Field
from ucagent.tools.uctool import UCTool
from ucagent.tools.fileops import BaseReadWrite


class MyToolArgs(BaseModel):
    """工具参数定义（使用 Pydantic）"""
    param1: str = Field(description="参数1的说明")
    param2: int = Field(default=10, description="参数2的说明")


class MyTool(UCTool, BaseReadWrite):
    """工具类（继承 UCTool 和 BaseReadWrite）"""

    # 工具的名称（Agent 调用时使用）
    name: str = "MyTool"

    # 工具的描述（Agent 通过描述了解工具用途）
    description: str = "这个工具做什么事情"

    # 工具的参数模式（指定参数类型和说明）
    args_schema: type[BaseModel] = MyToolArgs

    def _run(self, param1: str, param2: int = 10, run_manager=None) -> str:
        """
        执行工具逻辑

        参数:
            param1: 第一个参数
            param2: 第二个参数
            run_manager: 运行管理器（可选）

        返回:
            工具执行结果（字符串）
        """
        # 1. 处理输入参数
        # 2. 执行核心逻辑
        # 3. 返回结果
        return "执行结果"
```

## 工具1实现：CountWords

现在让我们实现第一个工具 - 统计文档字数。

### 完整代码

```python
# -*- coding: utf-8 -*-
import os
import re
from pydantic import BaseModel, Field
from ucagent.checkers.base import Checker
from ucagent.tools.uctool import UCTool
from ucagent.tools.fileops import BaseReadWrite


class CountWordsArgs(BaseModel):
    """CountWords 工具的参数定义"""
    file_path: str = Field(description="要统计字数的文件路径")


class CountWords(UCTool, BaseReadWrite):
    """
    统计文档字数工具

    功能：统计指定 Markdown 文件的字数和段落数
    用途：用于验证文档内容是否充实，满足字数要求
    """
    name: str = "CountWords"
    description: str = "统计指定 Markdown 文件的字数和段落数，返回统计信息"
    args_schema: type[BaseModel] = CountWordsArgs

    def _run(self, file_path: str, run_manager=None) -> str:
        """
        执行字数统计

        参数:
            file_path: 文件路径（支持相对路径和变量）
            run_manager: 运行管理器（可选）

        返回:
            统计结果字符串，包含字数和段落数
        """
        # 使用 get_path 处理路径，自动处理 workspace 前缀和变量替换
        abs_path = self.get_path(file_path)

        # 检查文件是否存在
        if not os.path.exists(abs_path):
            return f"错误：文件不存在 - {file_path}"

        try:
            # 读取文件内容
            with open(abs_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 统计中文字符数（不包括标点符号和空格）
            chinese_chars = len(re.findall(r'[\u4e00-\u9fa5]', content))

            # 统计英文单词数
            english_words = len(re.findall(r'\b[a-zA-Z]+\b', content))

            # 总字数 = 中文字符数 + 英文单词数
            total_words = chinese_chars + english_words

            # 统计段落数（非空行数）
            paragraphs = len([line for line in content.split('\\n') if line.strip()])

            # 统计章节数（# 开头的行）
            sections = len(re.findall(r'^#+\\s+.+$', content, re.MULTILINE))

            # 返回统计结果
            result = f"""字数统计结果：
- 总字数: {total_words} 字
- 中文字符: {chinese_chars} 字
- 英文单词: {english_words} 词
- 段落数: {paragraphs} 段
- 章节数: {sections} 章节
- 文件路径: {file_path}"""

            return result

        except Exception as e:
            return f"错误：统计字数失败 - {str(e)}"
```

### 代码详解

#### 1. 参数定义（CountWordsArgs）

```python
class CountWordsArgs(BaseModel):
    """参数定义使用 Pydantic BaseModel"""
    file_path: str = Field(description="要统计字数的文件路径")
```

**要点**：

- 必须继承 `pydantic.BaseModel`
- 使用 `Field()` 提供参数描述，Agent 通过描述了解参数用途
- 可以设置默认值：`param: int = Field(default=10, description="...")`
- 支持类型验证，Pydantic 会自动检查参数类型

#### 2. 工具类定义（CountWords）

```python
class CountWords(UCTool, BaseReadWrite):
    name: str = "CountWords"  # 工具名称
    description: str = "统计指定 Markdown 文件的字数..."  # 工具描述
    args_schema: type[BaseModel] = CountWordsArgs  # 参数模式
```

**要点**：

- 继承 `UCTool` 获得工具基础能力
- 继承 `BaseReadWrite` 文件操作工具通用功能
- 继承 `Checker` 获得文件路径处理能力（提供 `get_path` 方法）
- `description` 很重要，Agent 通过它判断何时调用该工具

#### 3. 路径处理（get_path）

```python
abs_path = self.get_path(file_path)
```

**作用**：

- 自动处理 `workspace:` 前缀
- 替换变量（如 `{PROJECT}`、`{OUT}`）
- 将相对路径转换为绝对路径

**示例**：

- 输入：`{OUT}/Calculator_analysis.md`
- 经过 `get_path` 处理
- 输出：`/absolute/path/to/output/Calculator_analysis.md`

#### 4. 核心逻辑（字数统计）

```python
# 统计中文字符
chinese_chars = len(re.findall(r'[\u4e00-\u9fa5]', content))

# 统计英文单词
english_words = len(re.findall(r'\b[a-zA-Z]+\b', content))

# 总字数
total_words = chinese_chars + english_words
```

**逻辑说明**：

- 使用正则表达式 `[\u4e00-\u9fa5]` 匹配中文字符
- 使用 `\b[a-zA-Z]+\b` 匹配英文单词
- 段落数 = 非空行数
- 章节数 = 以 `#` 开头的行数

#### 5. 错误处理

```python
try:
    # 核心逻辑
    ...
except Exception as e:
    return f"错误：统计字数失败 - {str(e)}"
```

**最佳实践**：

- 检查文件是否存在
- 使用 `try-except` 捕获异常
- 返回清晰的错误信息供 Agent 理解

## 工具2实现：ExtractSections

### 完整代码

```python
class ExtractSectionsArgs(BaseModel):
    """ExtractSections 工具的参数定义"""
    file_path: str = Field(description="要提取章节的 Markdown 文件路径")


class ExtractSections(UCTool, BaseReadWrite):
    """
    提取文档章节结构工具

    功能：提取 Markdown 文件中的所有章节标题及其层级
    用途：用于检查文档结构是否完整，是否包含必需章节
    """
    name: str = "ExtractSections"
    description: str = "提取 Markdown 文件中的所有章节标题，返回章节列表和层级结构"
    args_schema: type[BaseModel] = ExtractSectionsArgs

    def _run(self, file_path: str, run_manager=None) -> str:
        """
        执行章节提取

        参数:
            file_path: 文件路径（支持相对路径和变量）
            run_manager: 运行管理器（可选）

        返回:
            章节列表字符串，按层级组织
        """
        # 使用 get_path 处理路径
        abs_path = self.get_path(file_path)

        # 检查文件是否存在
        if not os.path.exists(abs_path):
            return f"错误：文件不存在 - {file_path}"

        try:
            # 读取文件内容
            with open(abs_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 提取所有章节标题（# 开头的行）
            # 正则表达式：^(#+)\\s+(.+)$
            sections = []
            for match in re.finditer(r'^(#+)\\s+(.+)$', content, re.MULTILINE):
                level = len(match.group(1))  # 井号数量 = 层级
                title = match.group(2).strip()  # 标题文本
                sections.append((level, title))

            # 如果没有找到章节
            if not sections:
                return f"未找到任何章节标题（以 # 开头的行）"

            # 格式化输出
            result_lines = [f"文档章节结构（共 {len(sections)} 个章节）：\\n"]

            for level, title in sections:
                # 使用缩进表示层级
                indent = "  " * (level - 1)
                result_lines.append(f"{indent}{'#' * level} {title}")

            return "\\n".join(result_lines)

        except Exception as e:
            return f"错误：提取章节失败 - {str(e)}"
```

### 关键技术：正则表达式

```python
# 匹配 Markdown 标题：^(#+)\s+(.+)$
# ^ : 行首
# (#+) : 一个或多个 # 号（分组1，表示层级）
# \s+ : 一个或多个空白字符
# (.+) : 任意字符（分组2，标题文本）
# $ : 行尾

for match in re.finditer(r'^(#+)\s+(.+)$', content, re.MULTILINE):
    level = len(match.group(1))  # 井号数量
    title = match.group(2).strip()  # 标题文本
```

## 工具注册

工具编写完成后，需要在工作流配置中注册才能使用。

### 在 mini.yaml 中注册

```yaml
ex_tools:
  - "examples.MiniWorkflow.my_tools.CountWords"
  - "examples.MiniWorkflow.my_tools.ExtractSections"
```

**格式说明**：

- 使用完整的模块路径：`module.submodule.ClassName`
- 路径从项目根目录开始
- 多个工具用列表形式注册

### 验证注册成功

启动 UCAgent 后，可以通过日志查看工具注册情况：

```
[INFO] Loaded tool: CountWords
[INFO] Loaded tool: ExtractSections
```

??? 临时注册与永久注册
    在调试时可以临时注册，当调试完成可以写入yaml持久注册

    - 临时：在启动命令(Makefile的run命令)后添加参数：`--ex-tools module.submodule.ClassName`
    - 持久：项目 `project_name.yaml`

## 完整文件：my_tools.py

将两个工具整合到一个文件中：

```python
# -*- coding: utf-8 -*-
"""
MiniWorkflow 自定义工具

这个模块包含了计算器文档生成器工作流所需的自定义工具。
"""

# （这里包含上面 CountWords 和 ExtractSections 的完整代码）

# 导出工具类
__all__ = ["CountWords", "ExtractSections"]
```

完整代码已保存在：`examples/MiniWorkflow/my_tools.py`

## Agent 如何调用工具

当 Agent 执行任务时，会根据 `description` 判断何时调用工具：

### 调用示例

**Agent 的思考过程**：

```
任务：统计文档字数，确保内容充实

我需要知道文档有多少字。
查看可用工具...发现 CountWords 工具：
  "统计指定 Markdown 文件的字数和段落数"

这正是我需要的！调用它：
CountWords(file_path="output/Calculator_analysis.md")

返回结果：
"总字数: 856 字, 段落: 12 段"

很好，字数充足，可以继续下一步。
```

## 工具开发技巧

### 1. Description 编写原则

✅ **好的 description**：

```python
description: str = "统计指定 Markdown 文件的字数和段落数，返回统计信息"
```

- 明确说明功能
- 指出输入和输出
- Agent 能准确判断使用场景

❌ **不好的 description**：

```python
description: str = "统计工具"
```

- 太模糊，Agent 不知道统计什么

### 2. 参数设计原则

- 参数名称要清晰：`file_path` 而不是 `path`
- 使用 `Field(description=...)` 详细说明参数用途
- 为可选参数设置合理的默认值

### 3. 返回值设计

- 返回字符串，格式清晰易读
- 包含关键信息，方便 Agent 理解
- 出错时返回明确的错误信息

### 4. 路径处理

- 始终使用 `self.get_path()` 处理文件路径
- 不要假设路径是绝对路径
- 检查文件是否存在再操作

## 小结

通过本章，您学会了：

✅ 自定义工具的作用和使用场景  
✅ 工具类的基本结构（继承、参数、\_run方法）  
✅ 如何使用 Pydantic 定义参数模式  
✅ 如何处理文件路径和错误  
✅ 如何在配置文件中注册工具

**下一步**：工具让 Agent 能"做事"，但我们还需要检查器来验证"做得对不对"。接下来学习如何编写自定义检查器！

👉 继续阅读：[自定义检查器](05_custom_checkers.md)

## 延伸阅读

- [内置工具列表](../03_develop/04_tool_list.md) - 查看所有可用的内置工具
- [工具开发进阶](../03_develop/03_customize.md) - 异步工具、流式输出等高级特性
