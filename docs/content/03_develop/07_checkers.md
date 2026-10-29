
# 自定义 Checker

Checker 是阶段的确定性验收门。Agent 生成或修改产物后可调用 `Check` 获取反馈；所有 Checker、引用文件
和输出文件门禁通过后，`Complete` 才能推进阶段。Checker 只负责验证事实，不能把“看起来
完成”当作通过。

## 什么时候需要自定义 Checker

内置 Checker 适合常见的 Markdown、文件、测试、覆盖率和批任务检查。需要验证业务规则时，
可以编写自定义 Checker，例如：

- 文档必须包含指定标题和字段；
- 生成的配置必须引用现有文件；
- 一个批次中的每个测试项都必须有对应产物；
- 外部命令必须返回成功，并且输出满足明确条件。

Checker 应检查可观察的文件、配置或命令结果。不要只相信 Agent 在文档中写出的进度标记，
也不要为了让阶段通过而放宽测试断言。

## 生命周期

`VerifyStage` 创建 Checker 时会把配置中的 `args` 和当前 `cfg` 传入构造函数，然后设置
workspace 和 stage。Stage Manager 之后才会注入；因此：

1. `__init__` 必须先调用 `super().__init__()`，只保存参数并创建轻量对象；
2. 依赖 workspace、stage、Stage Manager 或文件扫描的初始化放到 `on_init()`；
3. `do_check` 执行实时验证，返回 `(bool, result)`；
4. `get_template_data()` 只能返回缓存状态，不能扫描文件、推进批次或写 checkpoint；
5. 每个重写的 `do_check` 都必须有有意义的 docstring，因为它会显示在阶段信息中。

最小结构：

~~~python
from pathlib import Path

from ucagent.checkers.base import Checker


class FileExistsChecker(Checker):
    """检查工作区内的目标文件是否存在。"""

    def __init__(self, path: str, **kwargs):
        """Store the artifact path and optional human-review setting."""
        super().__init__()
        self.path = path
        self.set_human_check_needed(kwargs.get("need_human_check", False))

    def on_init(self):
        """准备阶段相关的缓存状态。"""
        return super().on_init()

    def do_check(self, is_complete=False, **kwargs) -> tuple[bool, object]:
        """检查目标文件，并返回通过结果或结构化诊断。"""
        root = Path(self.workspace).resolve()
        target = (root / self.path).resolve()
        if Path(self.path).is_absolute() or not target.is_relative_to(root):
            return False, {
                "error_code": "INVALID_ARTIFACT_PATH",
                "error": "artifact path must be relative and remain inside workspace",
                "artifact": self.path,
                "next_action": "configure a workspace-relative artifact path",
            }
        if not target.is_file():
            return False, {
                "error_code": "FILE_MISSING",
                "error": f"required artifact is missing: {self.path}",
                "artifact": self.path,
                "expected": "a regular file",
                "next_action": "create the file, then call Check again",
            }
        return True, {"artifact": self.path}
~~~

`get_path` 用于把相对路径拼接到 workspace，但不能替代完整的边界校验。接收可变路径时，应像上例一样解析真实路径并确认它仍位于工作区内，包括符号链接指向的目标。

## 配置 Checker

阶段配置通过 `clss` 指定类，`args` 传给构造函数，`extra_args` 在实例化后通过
`set_extra` 设置。短名从 `ucagent.checkers` 导出；自定义类使用完整导入路径：

~~~yaml
stage:
  - name: generate_documentation
    desc: "生成项目文档"
    task:
      - "读取项目资料并写入文档"
    output_files:
      - "{OUT}/{DUT}_documentation.md"
    checker:
      - name: required_sections
        clss: "examples.MiniWorkflow.my_checkers.RequiredSectionsChecker"
        args:
          file_path: "{OUT}/{DUT}_documentation.md"
          required_sections:
            - "项目概述"
            - "功能说明"
          need_human_check: false
~~~

配置中的 `args` 会自动附带当前 `cfg`；自定义构造函数用 `**kwargs` 接收它或其他可选参数。
列表字段按层整体替换，复制配置时要写出完整的 Checker 列表。

## 诊断结果

通过时返回简洁的结果。失败时，如果能确定修复方法，返回一个有界的结构化诊断，至少包含：

- `error_code`：稳定的机器可读代码；
- `error`：具体问题；
- `next_action`：下一步应执行的修复或工具调用；
- `artifact`、`location`、`observed`、`expected`：在有帮助时提供，内容要有界。

~~~python
return False, {
    "error_code": "DOCUMENT_TOO_SHORT",
    "error": "the document contains 450 words; at least 500 are required",
    "artifact": "unity_test/Adder_analysis.md",
    "observed": {"word_count": 450},
    "expected": {"minimum_word_count": 500},
    "next_action": "add at least 50 words of relevant content, then call Check",
}
~~~

如果结果还需要保留命令的原始输出，把有界诊断放在 `diagnostic` 字段中，并把原始输出限制
在合理大小。不要从普通的 `error`、`details`、`STDOUT` 或 `STDERR` 字段猜测失败摘要；
阶段管理会保留没有完整诊断的原始结果。调用方可以在 `stage_args` 中传
`{"full_output": true}`，要求同时返回原始结果。

`do_check` 的 `is_complete` 参数用于区分中间 `Check` 和最终 `Complete`。不要在 `Check`
中提前声明所有批次完成，也不要把中间进度当作最终验证。

## 批量 Checker

需要分批处理测试用例、功能点或行映射时，使用 `BatchTask`，不要另写 checkpoint
和批次状态机：

`BatchTask` 从 `ucagent.checkers.base` 导入。完成输入与产物校验、同步任务列表后，调用：

~~~python
return self.batch_task.do_complete(
    note_msg=[],
    is_complete=is_complete,
    fail_source_msg="generate artifacts for the missing source items",
    fail_gen_msg="remove generated items that are absent from the source",
    exmsg="read the current batch details before continuing",
)
~~~

这段调用用于已有批量 Checker 的 `do_check`，不能代替源数据扫描和产物校验。实际实现还需要：

- 在构造 `BatchTask` 前设置 `batch_size`；
- 保留并同步 `source_task_list`、`gen_task_list`、`tbd_task_list` 和 `cmp_task_list`；
- 把源文件当作事实来源，checkpoint 只用于恢复；
- 源数据改变时移除或标记过期任务；未知、重复或伪造的进度必须失败；
- 用 `do_complete()` 完成批次转换，它会保存进度并在批次通过时重置连续失败计数；
- 空源列表、无效路径和不完整产物都要返回明确诊断。

功能行映射还要求 `file_list` 是唯一文件集合，不把 `Guide_Doc` 当作映射目标；每个非空物理
行都要有 FG/FC/CK 或有理由的 `IGNORE`，一个映射块最多 100 行。

## 人工检查和阶段门禁

Checker 可以通过 `set_human_check_needed(True)` 请求人工检查；这会让阶段在 Checker
通过后等待人工操作。阶段的 `reference_files`、`output_files` 和技能门禁由 Stage Manager
统一处理，Checker 不应重复实现这些门禁。

技能门禁只在技能支持启用且当前阶段的 `skill_list` 非空时生效。`force_use_skill: false`
会让该阶段技能可选；`general_skill_list` 不会进入阶段强制门禁。技能关闭时，Checker 必须
仍能用普通工具和现有产物完成相同验证。

## 测试自定义 Checker

至少覆盖：

- 文件不存在、空文件和格式错误；
- 正常输入、边界值和错误输入；
- workspace 路径边界；
- 诊断字段是否完整且内容有界；
- 批任务在新增、删除和修改源数据后的同步行为。

可运行的最小实现见仓库的
[examples/MiniWorkflow/my_checkers.py](https://github.com/XS-MLVP/UCAgent/blob/main/examples/MiniWorkflow/my_checkers.py)。
完整的工具和工作流示例见 [定制开发入门](01_quick_start.md)、[工作流配置](03_workflow.md) 和
[Mini 示例](08_mini_example.md)。
