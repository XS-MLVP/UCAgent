---
name: ucagent
description: UCAgent是基于大语言模型的自动化任务执行AI代理，支持通用工作流配置和执行。本技能提供配置文件编写规范、自定义Checker开发指南、--emulate-config配置校验工具使用方法，帮助用户快速创建、验证和运行各类任务工作流。
---

# ucagent

## 概述

UCAgent是一个基于大语言模型的自动化任务执行AI代理，支持通用工作流配置和执行。本技能提供完整的UCAgent配置、Checker开发和任务流程指导。

## 快速开始

### 步骤1：创建配置文件

创建一个YAML格式的配置文件，定义任务和工作流：

```yaml
mission:
  name: "{DUT}文档生成"
  prompt:
    system: |
      你是专业的技术文档工程师，需要完成{DUT}项目的文档编写工作。

stage:
  - name: "requirement_analysis"
    desc: "分析{DUT}项目需求"
    task:
      - "阅读项目源码，理解功能和接口"
      - "编写需求说明文档requirement.md"
    output_files:
      - "requirement.md"
    checker:
      - name: "file_check"
        clss: "OrginFileMustExistChecker"
        args:
          file_path: "requirement.md"
```

### 步骤2：校验配置文件

使用`--emulate-config`参数验证配置正确性：

```bash
python3 cli.py --emulate-config --config config.yaml
```

### 步骤3：运行任务

配置校验通过后，正式运行任务：

```bash
python3 cli.py workspace/ DUT --config config.yaml --loop
```

## 1. 配置文件编写指南

UCAgent使用YAML格式的配置文件定义任务、工作流和检查规则。配置文件通常包含以下核心部分：

### 1.1 基本配置结构

```yaml
# 任务基本信息
mission:
  name: "任务名称，支持变量{DUT}、{OUT}等"
  prompt:
    system: |
      系统提示词，定义Agent的角色和行为规范

# MCP服务器配置（可选）
mcp_server:
  init_prompt: >
    Code Agent初始化提示词

# 模板配置（可选）
template: "使用的模板名称，为空则不使用预定义模板"

# 工作流阶段定义（stage可以嵌套）
stage:
  - name: "阶段名称（唯一标识）"
    desc: "阶段描述，支持变量替换"
    task:
      - "任务要求1"
      - "任务要求2"
      - "任务要求3"
    output_files:
      - "该阶段需要生成的文件路径"
    checker:
      - name: "检查器名称"
        clss: "检查器类名或完整模块路径"
        args:
          参数名: "参数值"
  - stage:
      - name: "子阶段名称"
        desc: "子阶段描述"
        task:
          - "子任务要求1"
          - "子任务要求2"
  - name: "阶段名称2"
    desc: "阶段描述2"
    task:
      - "任务要求..."
```

### 1.2 常用变量说明

- `{DUT}`：被验证设计的名称
- `{OUT}`：输出目录路径
- `{WORKSPACE}`：工作区根路径
- `{TEMPLATES}`：模板目录路径

### 1.3 完整配置示例

```yaml
mission:
  name: "{DUT}项目文档编写"
  prompt:
    system: |
      你是专业的技术文档工程师，需要完成{DUT}项目的文档编写工作。
      严格按照阶段要求执行任务，通过Checker检查后才能进入下一阶段。

stage:
  - name: "requirement_analysis"
    desc: "分析{DUT}项目需求"
    task:
      - "阅读项目源码，理解功能和接口"
      - "编写需求说明文档requirement.md"
      - "列出所有需要文档化的功能点"
    output_files:
      - "requirement.md"
    checker:
      - name: "markdown_check"
        clss: "MarkdownFileChecker"
        args:
          file_path: "requirement.md"
          required_sections: ["项目概述", "功能说明", "接口文档"]

  - name: "user_guide_writing"
    desc: "编写用户手册"
    task:
      - "基于功能点编写详细用户手册"
      - "覆盖所有使用场景和操作步骤"
      - "保存为user_guide.md"
    output_files:
      - "user_guide.md"
    checker:
      - name: "guide_check"
        clss: "MarkdownFileChecker"
        args:
          file_path: "user_guide.md"
          min_word_count: 500
```

## 2. Checker 开发指南

Checker是UCAgent的质量保证组件，在每个阶段完成后自动运行，验证输出是否符合预期。

### 2.1 内置通用Checker

UCAgent内置了以下通用Checker，可直接在配置中使用：

#### 基础检查器

| Checker名称 | 功能说明 | 常用参数 | 源文件 |
|------------|----------|----------|--------|
| `NopChecker` | 空操作检查器，总是返回通过 | 无需参数 | [./checkers/base.py#L302](./checkers/base.py#L302) |
| `HumanChecker` | 人工检查器，需要人工确认才能通过 | need_human_check | [./checkers/base.py#L720](./checkers/base.py#L720) |
| `OrginFileMustExistChecker` | 检查原始文件是否存在 | file_path | [./checkers/base.py#L753](./checkers/base.py#L753) |
| `FilesMustNotExist` | 检查指定文件不存在 | file_patterns | [./checkers/base.py#L777](./checkers/base.py#L777) |

#### 文件检查器

| Checker名称 | 功能说明 | 常用参数 | 源文件 |
|------------|----------|----------|--------|
| `MarkDownHeadChecker` | Markdown文件标题检查，验证是否包含必需的标题结构 | file_path, template_file, header_levels | [./checkers/file_markdown.py#L188](./checkers/file_markdown.py#L188) |
| `BatchFileProcess` | 批量文件处理基类，支持批量检查多个文件 | name, file_pattern, batch_size | [./checkers/file_markdown.py#L47](./checkers/file_markdown.py#L47) |
| `FileLineMapChecker` | 文件行映射检查，验证文件内容与预期行映射是否匹配 | file_path, line_map | [./checkers/file_linemap.py#L102](./checkers/file_linemap.py#L102) |

#### 脚本和命令检查器

| Checker名称 | 功能说明 | 常用参数 | 源文件 |
|------------|----------|----------|--------|
| `BashScriptChecker` | Bash脚本/命令执行检查，支持成功/失败模式匹配 | cmd, arguments, pass_pattern, fail_pattern, timeout | [./checkers/bash_script.py#L11](./checkers/bash_script.py#L11) |


#### 使用示例

```yaml
checker:
  # 基础文件检查
  - name: "file_exists_check"
    clss: "OrginFileMustExistChecker"
    args:
      file_path: "dut_spec.md"

  # Markdown标题检查
  - name: "markdown_headers_check"
    clss: "MarkDownHeadChecker"
    args:
      file_path: "testplan.md"
      template_file: "templates/testplan_template.md"
      header_levels: [1, 2, 3]

  # Bash脚本执行检查
  - name: "run_test_check"
    clss: "BashScriptChecker"
    args:
      cmd: "pytest"
      arguments: ["tests/", "-v"]
      pass_pattern: {"passed": "All tests passed"}
      fail_pattern: {"FAILED": "Some tests failed"}
      timeout: 300

  # 单元测试必须通过
  - name: "test_must_pass"
    clss: "UnityChipCheckerTestMustPass"
    args:
      target_file: "test_*.py"
      test_dir: "tests"
      test_prefix: "test_"
      min_file_tests: 3
      timeout: 600

  # DUT API检查
  - name: "dut_api_check"
    clss: "UnityChipCheckerDutApi"
    args:
      api_prefix: "dut_"
      target_file: "dut_api.py"
      min_apis: 5

  # 人工确认检查
  - name: "human_review"
    clss: "HumanChecker"
    args:
      need_human_check: true
```

### 2.2 自定义Checker开发

#### 2.2.1 基本结构

所有自定义Checker都需要继承`ucagent.checkers.base.Checker`基类，并实现`do_check`方法：

```python
from ucagent.checkers.base import Checker
import os

class MyCustomChecker(Checker):
    """自定义检查器功能说明"""

    def __init__(self, param1: str, param2: int = 10, **kwargs):
        """
        初始化检查器
        :param param1: 参数1说明
        :param param2: 参数2说明（可选，默认值10）
        :param kwargs: 其他通用参数（如need_human_check）
        """
        self.param1 = param1
        self.param2 = param2
        # 设置是否需要人工检查
        self.set_human_check_needed(kwargs.get("need_human_check", False))

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """
        执行检查逻辑（必须实现）
        :param timeout: 超时时间（秒）
        :return: (是否通过, 结果详情)
        """
        # 获取文件绝对路径
        file_path = self.get_path(self.param1)
        
        # 检查文件是否存在
        if not os.path.exists(file_path):
            return False, {
                "error": f"文件{self.param1}不存在",
                "suggestion": "请确保生成了所需文件"
            }
        
        # 自定义检查逻辑
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if len(content) < self.param2:
            return False, {
                "error": f"文件内容过短，当前长度{len(content)}，要求至少{self.param2}字符",
                "current_length": len(content),
                "required_length": self.param2,
                "suggestion": "请补充文件内容"
            }
        
        # 检查通过
        return True, {
            "message": "检查通过",
            "file_length": len(content)
        }
```

#### 2.2.2 配置中使用自定义Checker

```yaml
checker:
  - name: "my_custom_check"
    clss: "my_module.MyCustomChecker"  # 完整模块路径
    args:
      param1: "output/result.md"
      param2: 1000
      need_human_check: false
```

#### 2.2.3 部署自定义Checker

使用`--append-py-path`（简写`-app`）参数将自定义Checker所在目录加入Python路径：

```bash
python3 cli.py --emulate-config --config <path_to_config.yaml> --append-py-path <path_to_custom_checkers/abc.py or path_to_custom_checkers/>
```

### 2.3 Checker最佳实践

1. **错误信息清晰**：提供具体的错误描述、当前值、期望值和修改建议
2. **异常处理**：捕获文件读取、解析等可能的异常，返回友好的错误信息
3. **路径处理**：始终使用`self.get_path(relative_path)`获取绝对路径
4. **结果结构化**：返回字典格式的结果，便于Agent理解和处理
5. **人工检查开关**：对于关键检查点，可以设置`need_human_check: true`要求人工确认

## 3. 配置校验工具：--emulate-config

UCAgent提供`--emulate-config`参数(需要通过`--config`指定配置文件)，用于在正式运行前验证配置文件的正确性，避免运行过程中出现配置错误。

### 3.1 功能说明

`--emulate-config`会执行以下检查：
1. 验证配置文件语法正确性
2. 检查所有阶段定义是否完整
3. 验证所有Checker类是否可以正常加载
4. 检查参数配置是否符合要求
5. 模拟完整配置流程，不会实际运行验证任务或调用LLM

### 3.2 使用方法

```bash
python3 cli.py --emulate-config --config <path_to_config.yaml>
```

### 3.3 输出说明

运行后会输出：
- 系统提示词（System Prompt）
- 任务详情（包含总阶段数）
- 逐个阶段检查结果
- 最终校验成功/失败提示

如果配置存在错误，会在对应阶段显示具体的错误信息，帮助快速定位问题。

### 3.4 典型使用场景

1. **开发新配置时**：编写完配置后先使用`--emulate-config`验证正确性
2. **修改现有配置时**：修改配置后校验是否引入错误
3. **自定义Checker开发时**：验证Checker是否可以正常加载和初始化

## 4. 完整工作流

### 4.1 开发流程

1. 编写任务配置文件（例如config.yaml）
2. 开发自定义Checker（如果需要）
3. 使用`--emulate-config`校验配置正确性
4. 人工正式运行UCAgent执行任务
5. 人工查看执行结果和报告

## 常见问题和边界情况

### 配置文件问题

**问题1：配置文件路径错误**
```
Error: Config file not found
```
解决：确保配置文件路径正确，使用绝对路径或相对于当前目录的相对路径。

**问题2：YAML语法错误**
```
Error: YAML parsing failed
```
解决：检查YAML缩进、引号、冒号等语法，使用在线YAML验证器检查。

**问题3：变量未替换**
```
{DUT} appears in output
```
解决：确保变量名正确（区分大小写），检查mission.name和stage.desc中的变量使用。

### Checker问题

**问题1：Checker类找不到**
```
Error: Checker class not found
```
解决：
- 检查clss字段是否正确（完整模块路径）
- 使用`--append-py-path`添加自定义Checker路径
- 确保Checker类已正确导出

**问题2：Checker参数错误**
```
Error: Missing required argument
```
解决：检查args字段是否包含Checker所需的所有参数，参考Checker文档。

**问题3：Checker检查失败**
```
Checker failed: file not found
```
解决：
- 检查文件路径是否正确
- 确保前一阶段已生成所需文件
- 使用`self.get_path()`处理相对路径

## 最佳实践

### 配置文件编写

1. **清晰的阶段划分**：每个阶段完成一个明确的任务
2. **详细的任务描述**：提供具体的任务要求和输出要求
3. **合理的Checker选择**：选择合适的Checker验证阶段输出
4. **变量使用**：使用`{DUT}`等变量提高配置复用性

### Checker开发

1. **错误信息清晰**：提供具体的错误描述、当前值、期望值和修改建议
2. **异常处理**：捕获文件读取、解析等异常，返回友好的错误信息
3. **路径处理**：使用`self.get_path(relative_path)`获取绝对路径
4. **结果结构化**：返回字典格式的结果，便于Agent理解和处理

### 工作流管理

1. **先校验后运行**：使用`--emulate-config`验证配置正确性
2. **增量开发**：先完成基础阶段，再逐步添加复杂功能
3. **版本控制**：使用Git管理工作区和配置文件
4. **日志记录**：启用日志记录便于问题排查

