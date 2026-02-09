# 快速编写指南

想定制自己的完整工作流，其实只需要四个东西：工作流、工具、模板(指导)文件、检查器。

- 工作流：定义任务流程
- 工具：特定领域任务的工具
- 模板（指导）文件：指导与规范大模型的输出
- 检查器：某阶段完成后的合规情况

完整工作流的目录结构如下：

```bash
$ tree MyWorkflow
MyWorkflow
├── Guide_Doc
│   ├── Guide_Docs1.md                          # 指导与模板文件
│   └── ...
├── __init__.py                                 # 让目录成为Python包
├── Makefile                                    # 编译命令（可选）
├── mini.yaml                                   # 工作流配置
├── my_checkers.py                              # 检查器
├── my_tools.py                                 # 工具
└── README.md                                   # 整体工作流说明
```

以上都可以体现在一个工作流里，下面直接以一个简化的工作流为例。

## 工作流

> 💡 **详细说明**：关于工作流配置的完整说明，请参考 [工作流配置](03_workflow.md)

简化`yaml`文件如下，其位置为`examples/MyWorkflow/MyWorkflow.yaml`

```yaml
# 1. 自定义工具注册（External Tools）
ex_tools:
  - "module.path.ToolClass"

# 2. 模板变量定义（Template Variables）
template_overwrite:
  PROJECT: "MyProject"
  OUT: "OutputPath"

# 3. 任务描述（Mission）
mission:
  name: "WorkflowName"
  prompt:
    system: "你是一位技术文档专家..."

# 4. 工作流定义（Stages）
stage:
  - name: StageName
    desc: "Stage_Description"
    task:
      - "第一步..."
      - "第二步..."
      - ...
    reference_files:
      - "Guide_Doc/project_analysis_guide.md" #以MyWorkflow目录为基准
    output_files:
      - "{OUT}/{PROJECT}_analysis.md"
    checker:
      - name: word_count_check
        clss: "examples.MyWorkflow.MyChecker.MyCheckerClass"
        args:
          ArgsName1: "args1"
          ArgsName2: "args2"
  - name: StageName
    desc: "Stage_Description"
    ...
```

## 工具

> 💡 **详细说明**：关于自定义工具开发的完整指南，请参考 [定制工具](05_customize.md)

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

### 使用

编写完成后将`MyTool.py`文件放置在`examples/MyWorkflow/`目录下，之后再在工作流的`yaml`里将其注册后就能让Agent调用工具了。

```yaml
# 注册工具
ex_tools:
  - "examples.MyWorkflow.MyTool"
```

## 模板(指导)文件

> 💡 **详细说明**：关于模板文件系统的完整介绍，请参考 [模板文件与生成产物](04_template.md)

### 编写

在`yaml`中通过`reference_files`可以指定模板/指导文件，让Agent参考。
编写需求的模板或者指导，将其`TemplateOrGuide.md`放在`examples/MyWorkflow/Guide_Doc`目录下。

### 使用

在工作流中使用只需要在`reference_files`中指定，之后就能让Agent参考了。

```yaml
stage:
  - name: StageName
    reference_files:
      - "Guide_Doc/project_analysis_guide.md" # ← 指导文档
    task:
      - "参考 Guide_Doc/project_analysis_guide.md 的指导，提取关键信息"
```

## 检查器

> 💡 **详细说明**：关于检查器的完整说明，请参考 [检查器](07_checkers.md)

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

### 使用

编写完成后将`MyChecker.py`文件放置在`examples/MyWorkflow/`目录下，之后再在工作流的`yaml`里就能让Agent调用了。

```yaml
stage:
  - name: StageName
    checker:
      - name: CheckerName
        clss: "examples.MyWorkflow.MyChecker.MyCheckerClass"
        args:
          ArgsName1: "args1"
          ArgsName2: "args2"
```

## 启动UCAgent与使用

> 💡 **完整示例**：查看完整的可运行示例，请参考 [Mini 示例](08_mini_example.md)

编写完所有文件后，可以在`examples/MyWorkflow/`下通过如下命令来启动。

```bash
python3 ../../ucagent.py \
        ./output/  \
		--mcp-server-no-file-tools \
		--config ./mini.yaml \
		--guid-doc-path ./Guide_Doc/ \
		-s -hm --tui --no-embed-tools
```

之后在`examples/MyWorkflow/output`下启动Code Agent输入提示词即可。
