
# 自定义检查器

> 💡 **前置学习**：检查器在工作流中用于验证阶段输出。建议先阅读 [工作流配置](03_workflow.md) 了解检查器的使用场景

自定义检查器是工作流质量保证的关键组件。它们在每个阶段（Stage）完成后自动运行，验证输出是否符合预期。可以说，**检查器是工作流的"质检员"**，确保 Agent 的工作符合标准。

## 为什么需要自定义检查器？

UCAgent 提供了一些内置检查器（如 Markdown 格式检查），但对于特定的业务规则，我们需要自定义检查器。

❌ **内置检查器的局限**：

- 只能检查通用的格式问题
- 无法验证业务逻辑
- 不能检查领域专用的规则

✅ **自定义检查器的优势**：

- 验证特定的业务规则（如字数范围、必需章节）
- 提供详细的错误信息指导 Agent 修正
- 支持复杂的验证逻辑
- 可以访问共享数据进行上下文相关的检查

## Mini-Example 的检查器需求

在计算器文档生成器中，我们需要两个自定义检查器：

### 检查器1：WordCountChecker（字数检查）

- **功能**：检查文档字数是否在 500-2000 范围内
- **用途**：确保文档内容充实但不冗长
- **失败时**：返回当前字数和缺少/超出的字数

### 检查器2：RequiredSectionsChecker（章节检查）

- **功能**：检查文档是否包含必需的章节（如"项目概述"、"功能说明"）
- **用途**：确保文档结构完整
- **失败时**：返回缺失的章节列表

## 检查器开发基础

### 核心概念

UCAgent 的检查器系统基于以下概念：

1. **继承 Checker 基类**：所有检查器都继承自 `ucagent.checkers.base.Checker`
2. **实现 **init** 方法**：接收并保存检查器参数
3. **实现 do_check 方法**：执行检查逻辑，返回 `(bool, dict)`
4. **处理路径**：使用 `self.get_path()` 处理文件路径
5. **返回结果**：成功返回 `(True, result)`，失败返回 `(False, error_info)`

### 检查器类结构

```python
from ucagent.checkers.base import Checker


class MyChecker(Checker):
    """检查器类（继承 Checker）"""

    def __init__(self, param1: str, param2: int = 10, **kwargs):
        """
        初始化检查器

        参数:
            param1: 第一个参数
            param2: 第二个参数（可选）
            **kwargs: 其他参数（如 need_human_check）
        """
        # 保存参数
        self.param1 = param1
        self.param2 = param2

        # 设置是否需要人工检查
        self.set_human_check_needed(kwargs.get("need_human_check", False))

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """
        执行检查逻辑（必须实现）

        参数:
            timeout: 超时时间（秒）
            **kwargs: 其他参数

        返回:
            (is_pass, result):
                - is_pass (bool): True 表示通过，False 表示失败
                - result (dict|str): 检查结果详情
        """
        # 1. 获取要检查的数据
        # 2. 执行检查逻辑
        # 3. 返回结果

        if check_passed:
            return True, {"message": "检查通过", "details": "..."}
        else:
            return False, {"error": "检查失败", "suggestion": "..."}
```

## 检查器1实现：WordCountChecker

### 完整代码

```python
class WordCountChecker(Checker):
    """
    文档字数检查器

    功能：检查文档的字数是否在指定范围内
    用途：确保文档内容充实，不会太短或太长
    """

    def __init__(self, file_path: str, word_min: int = 0, word_max: int = 10000, **kwargs):
        """
        初始化检查器

        参数:
            file_path: 要检查的文件路径
            word_min: 最小字数要求
            word_max: 最大字数限制
            **kwargs: 其他参数（包含 need_human_check 等）
        """
        self.file_path = file_path
        self.word_min = word_min
        self.word_max = word_max
        self.set_human_check_needed(kwargs.get("need_human_check", False))

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        # 处理路径
        abs_path = self.get_path(self.file_path)

        # 检查文件存在
        if not os.path.exists(abs_path):
            return False, {
                "error": f"文件不存在：{self.file_path}",
                "suggestion": "请确认文件已生成"
            }

        try:
            # 读取文件
            with open(abs_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 统计字数
            chinese_chars = len(re.findall(r'[\u4e00-\u9fa5]', content))
            english_words = len(re.findall(r'\b[a-zA-Z]+\b', content))
            total_words = chinese_chars + english_words

            # 检查字数范围
            if total_words < self.word_min:
                return False, {
                    "error": f"文档字数不足",
                    "current_words": total_words,
                    "required_min": self.word_min,
                    "shortage": self.word_min - total_words,
                    "suggestion": f"还差 {self.word_min - total_words} 字"
                }

            if total_words > self.word_max:
                return False, {
                    "error": f"文档字数超出限制",
                    "current_words": total_words,
                    "required_max": self.word_max,
                    "excess": total_words - self.word_max
                }

            # 检查通过
            return True, {
                "message": "字数检查通过",
                "current_words": total_words,
                "required_range": f"{self.word_min}-{self.word_max}"
            }

        except Exception as e:
            return False, {"error": f"检查失败：{str(e)}"}
```

### 代码详解

#### 1. 初始化方法（**init**）

```python
def __init__(self, file_path: str, word_min: int = 0, word_max: int = 10000, **kwargs):
    self.file_path = file_path
    self.word_min = word_min
    self.word_max = word_max
    self.set_human_check_needed(kwargs.get("need_human_check", False))
```

**要点**：

- 接收所有需要的参数
- 使用 `**kwargs` 接收额外参数（如 `need_human_check`）
- 调用 `set_human_check_needed()` 设置是否需要人工检查

#### 2. 检查方法（do_check）

```python
def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
    # 返回 (bool, dict) 元组
    return True, {"message": "通过"}  # 或
    return False, {
        "error": "失败原因及完整原始信息",
        "diagnostic": {
            "error_code": "DOCUMENT_TOO_SHORT",
            "error": "文档只有 450 字，少于最低要求 500 字。",
            "observed": {"word_count": 450},
            "expected": {"minimum_word_count": 500},
            "next_action": "在目标文档中补充至少 50 字有效内容，然后重新调用 Check。",
        },
    }
```

**返回值格式**：

- 第一个值：`bool`，表示是否通过
- 第二个值：`dict` 或 `str`，提供详细信息
- 只有 Checker 明确返回完整诊断时，StageManager 才会生成紧凑的 `failure_summary`；仅包含有界诊断字段时可直接返回该映射，同时包含完整日志等原始信息时则把有界映射放在 `diagnostic` 字段中
- 诊断至少包含稳定的 `error_code`、具体 `error` 和可直接执行的 `next_action`
- 如果 Checker 无法确定修复方法，不要制造宽泛诊断；在普通返回中保留完整 `error`、`details`、`STDOUT` 和 `STDERR`，Check/Complete 会原样显示
- 调用方可用 `stage_args={"full_output": true}` 在存在结构化诊断时同时取得完整原始返回；该保留字段不会传入 Checker

#### 3. 路径处理

```python
abs_path = self.get_path(self.file_path)
```

**作用**：与工具相同，自动处理变量和路径转换。

#### 4. 错误信息设计

✅ **好的错误信息**：

```python
return False, {
    "error": "文档字数不足",
    "diagnostic": {
        "error_code": "DOCUMENT_TOO_SHORT",
        "error": "文档只有 450 字，少于最低要求 500 字。",
        "observed": {"word_count": 450, "shortage": 50},
        "expected": {"minimum_word_count": 500},
        "next_action": "补充至少 50 字与当前章节相关的有效内容，然后重新调用 Check。"
    }
}
```

- 明确指出问题
- 提供具体数据
- 给出修正建议

## 检查器2实现：RequiredSectionsChecker

### 完整代码

完整代码请参考 `examples/MiniWorkflow/my_checkers.py`。

### 关键逻辑：章节提取和匹配

```python
# 提取所有二级标题
found_sections = []
for match in re.finditer(r'^##\s+(.+)$', content, re.MULTILINE):
    section_title = match.group(1).strip()
    found_sections.append(section_title)

# 检查每个必需章节
missing_sections = []
for required in self.required_sections:
    found = False
    for found_section in found_sections:
        if required in found_section or found_section in required:
            found = True
            break

    if not found:
        missing_sections.append(required)

# 判断结果
if missing_sections:
    return False, {
        "error": "文档缺少必需章节",
        "missing_sections": missing_sections,
        "suggestion": f"请添加：{', '.join(missing_sections)}"
    }
```

## 检查器配置

检查器在工作流配置中使用，位于每个 `stage` 的 `checker` 列表中。

### 在 mini.yaml 中配置

```yaml
stage:
  - name: generate_documentation
    checker:
      # 检查器1：字数检查
      - name: word_count_check
        clss: "examples.MiniWorkflow.my_checkers.WordCountChecker"
        args:
          file_path: "{OUT}/{PROJECT}_documentation.md"
          word_min: 800
          word_max: 3000

      # 检查器2：章节检查
      - name: required_sections_check
        clss: "examples.MiniWorkflow.my_checkers.RequiredSectionsChecker"
        args:
          file_path: "{OUT}/{PROJECT}_documentation.md"
          required_sections:
            - "项目概述"
            - "功能说明"
            - "技术架构"
            - "使用方法"
```

**配置说明**：

- `name`：检查器名称（用于日志）
- `clss`：检查器类的完整模块路径
- `args`：传递给 `__init__` 的参数

## 检查器执行机制

### 执行时机

```
Agent 执行任务
    │
    ▼
Agent 调用 Complete 工具
    │
    ▼
运行所有配置的检查器
    │
    ├─> 检查器1: WordCountChecker
    │     └─> 返回 (True, {...})  ✓
    │
    ├─> 检查器2: RequiredSectionsChecker
    │     └─> 返回 (False, {"missing": [...]})  ✗
    │
    ▼
有检查器失败
    │
    └─> 向 Agent 返回错误信息
        Agent 根据错误信息修正输出
        重新调用 Complete
```

### 失败重试机制

- Agent 会读取检查器的错误信息
- 根据 `suggestion` 字段修正输出
- 重新调用 `Complete` 工具
- 最多重试 3-5 次（可配置）

## 检查器开发技巧

### 1. 错误信息设计

提供详细的错误信息帮助 Agent 快速定位问题：

```python
return False, {
    "error": "具体错误描述",
    "current_value": "当前值",
    "expected_value": "期望值",
    "suggestion": "如何修正"
}
```

### 2. 处理边界情况

```python
# 检查文件存在
if not os.path.exists(abs_path):
    return False, {"error": "文件不存在"}

# 检查内容为空
if not content.strip():
    return False, {"error": "文件内容为空"}
```

### 3. 使用异常处理

```python
try:
    # 核心逻辑
    ...
except FileNotFoundError:
    return False, {"error": "文件未找到"}
except Exception as e:
    return False, {"error": f"检查失败：{str(e)}"}
```

### 4. 提供建设性建议

❌ **不好的错误信息**：

```python
return False, {"error": "检查失败"}
```

✅ **好的错误信息**：

```python
return False, {
    "error": "文档缺少必需章节",
    "missing_sections": ["项目概述", "功能说明"],
    "suggestion": "请在文档中添加 ## 项目概述 和 ## 功能说明 章节"
}
```

## 完整文件：my_checkers.py

完整代码已保存在：`examples/MiniWorkflow/my_checkers.py`

## 小结

通过本章，您学会了：

✅ 自定义检查器的作用和执行机制  
✅ 检查器类的基本结构（继承、**init**、do_check）  
✅ 如何设计清晰的错误信息  
✅ 如何在配置文件中使用检查器

**下一步**：现在您已经掌握了工作流配置、模板、工具和检查器四大核心组件。接下来让我们整合所有内容，运行完整的 mini-example！

👉 继续阅读：[完整 Mini 示例](08_mini_example.md)

## 相关文档

- [工作流配置](03_workflow.md) - 了解如何在工作流中配置检查器
- [快速开始](01_quick_start.md) - 快速创建自己的工作流
- [定制工具](05_customize.md) - 学习如何开发自定义工具
- [Mini 示例](08_mini_example.md) - 查看完整的可运行示例
