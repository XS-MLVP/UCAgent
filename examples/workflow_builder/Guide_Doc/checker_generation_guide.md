# Checker 生成规范

## 概述

Checker 是 UCAgent 的确定性检查器，继承 `ucagent.checkers.base.Checker`，在阶段完成时由 UCAgent 自动调用。每个 Checker 的 `do_check` 方法返回 `(bool, dict)`——第一个值表示通过/失败，第二个值包含详细信息。

主构建流程不再设置后置的 Checker 设计与生成阶段。Stage 1 必须在
`workflow_build.yaml` 的 `workflow_spec.checkers` 中一次规划全部业务 Checker，
并在 `workflow_spec.stages` 中规划 reference_files、output_files 和 Checker
绑定；Stage 2 的 WorkflowBuilder 会直接生成 spec、Python 实现与显式 fixture。

中心 Checker 定义使用 `name`、详细 `description`、`entry`、完整受信任 Python
`source`、`fixtures` 和 `tests`。fixture 路径只能位于
`.workflow/checker_tests/cases/<CheckerName>/`；tests 必须至少有一个
`expected_pass: true` 和一个 `expected_pass: false`。同一 Checker 可以被多个阶段
绑定，但 source 只定义一次，各阶段在 binding 的 `args` 中提供自己的构造参数。
旧式只列阶段名，或只声明 `rules/auto_tests/register` 而不提供完整中心规划的
`workflow_build.yaml` 会被严格拒绝。

### Checker 说明文本的硬性约束

每个 `do_check()` 方法必须直接包含非空 docstring。UCAgent 在渲染阶段详情时会调用
`str(checker)`，其底层断言 `checker.do_check.__doc__` 非空；如果只给 Checker 类添加
docstring，或者只设置类属性 `description`，仍会产生
`No description provided for this checker(...)` 并中断工作流。

三种说明不能互相替代：

- spec 的 `description` 用于记录业务目的，并生成 Checker 的 `description` 类属性。
- Checker 类 docstring 用于开发者阅读和 API 文档。
- `do_check()` 方法 docstring 用于 UCAgent 阶段详情，是运行时强制要求。

至少使用下面的结构：

```python
def do_check(self, timeout=0, **kwargs):
    """Validate the declared artifact and return deterministic evidence."""
    ...
```

不得把字符串写在方法外、写成普通注释，或仅依赖继承方法的 docstring。生成或手写后必须
执行 `str(checker)`；`make check_checkers` 和 `make test_checkers` 都必须覆盖该调用。

---

## 第一部分：独立维护用 Checker Spec 格式

以下声明式格式只用于兼容独立维护。主构建必须使用上述内联源码中心规划，构建后会自动
得到 `.workflow/checker_specs/<CheckerName>.yaml`：

```yaml
name: my_checker                      # checker 唯一名称
description: "checker 功能描述"        # 给 Agent 看的说明
entry:
  file: checkers/my_checker.py        # 生成的目标文件路径（必须 checkers/ 开头）
  class_name: MyChecker               # Python 类名
  method: do_check                    # 入口方法名
rules:                                # 检查规则
  type: json_required_keys            # 规则类型（见下文）
  required_keys: [field1, field2]     # 规则参数
auto_tests: true                      # 自动生成正反测试
register:                             # 注册信息
  stage: target_stage_name            # 注册到哪个阶段
  args:                               # 传递给构造函数的参数
    path: output/result.json          # checker 检查的目标文件
tests:                                # 测试用例（auto_tests=true 时由生成器写回）
  - name: valid_case
    expected_pass: true
  - name: invalid_case
    expected_pass: false
```

---

## 第二部分：手写 Checker 完整模板

不依赖生成器，从零编写一个 Checker：

```python
# -*- coding: utf-8 -*-
import json
from pathlib import Path

from ucagent.checkers.base import Checker


class MyChecker(Checker):
    """检查业务阶段产出的 JSON 文件是否包含必需字段。"""

    name = "my_checker"
    description = "检查 JSON 文件顶层是否包含 status 和 summary 字段"

    required_keys = ["status", "summary"]

    def __init__(self, path: str = "", required_keys=None, **kwargs):
        super().__init__()
        self.path = path                          # checker 检查的目标文件
        self.required_keys = list(required_keys or self.required_keys)
        self.set_human_check_needed(kwargs.get("need_human_check", False))

    def _resolve(self):
        """安全解析文件路径（相对于工作流 workspace）"""
        candidate = Path(self.path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"Unsafe checker path: {self.path}")
        root = Path(self.workspace or ".").resolve()
        target = (root / candidate).resolve()
        if target != root and not str(target).startswith(str(root) + "/"):
            raise ValueError(f"Unsafe checker path: {self.path}")
        return target

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, dict]:
        """
        返回值：(是否通过, 详细信息字典)
        通过：return True, {"message": "..."}
        失败：return False, {"error": "...", ...}
        """
        try:
            target = self._resolve()

            # 1. 检查文件是否存在
            if not target.is_file():
                return False, {
                    "error": "CHECKER-DATA-001: 目标文件不存在",
                    "path": self.path,
                }

            # 2. 读取并解析 JSON
            data = json.loads(target.read_text(encoding="utf-8"))

            # 3. 检查顶层是否为 mapping
            if not isinstance(data, dict):
                return False, {
                    "error": "CHECKER-DATA-002: JSON 顶层必须是 mapping",
                    "path": self.path,
                }

            # 4. 检查必需字段
            missing = [key for key in self.required_keys if key not in data]
            if missing:
                return False, {
                    "error": "CHECKER-DATA-003: JSON 缺少必需字段",
                    "path": self.path,
                    "missing_keys": missing,
                }

            # 5. 通过
            return True, {
                "message": "JSON 包含所有必需字段",
                "path": self.path,
                "required_keys": self.required_keys,
            }

        except Exception as exc:
            return False, {
                "error": f"CHECKER-DATA-999: {exc}",
                "path": self.path,
            }
```

---

## 第三部分：Config 注册

Checker 注册到 `config.yaml` 的对应 stage 的 `checker` 列表：

```yaml
stage:
  - name: my_stage
    checker:
      - name: my_checker
        clss: "checkers.my_checker.MyChecker"
        args:
          path: output/result.json
```

`clss` 的格式是 Python 导入路径：`checkers.<文件名（无.py）>.<类名>`。

---

## 第四部分：四种规则类型完整示例

### 1. json_required_keys — JSON 必需字段检查

```python
# checkers/json_required_keys_checker.py
import json
from pathlib import Path
from ucagent.checkers.base import Checker


class JsonRequiredKeysChecker(Checker):
    name = "json_required_keys_checker"
    description = "检查 JSON 文件顶层是否包含指定字段"

    required_keys = []

    def __init__(self, path: str = "", required_keys=None, **kwargs):
        super().__init__()
        self.path = path
        self.required_keys = list(required_keys or self.required_keys)
        self.set_human_check_needed(kwargs.get("need_human_check", False))

    def _resolve(self):
        candidate = Path(self.path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"Unsafe checker path: {self.path}")
        root = Path(self.workspace or ".").resolve()
        target = (root / candidate).resolve()
        if target != root and not str(target).startswith(str(root) + "/"):
            raise ValueError(f"Unsafe checker path: {self.path}")
        return target

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, dict]:
        try:
            target = self._resolve()
            if not target.is_file():
                return False, {"error": "CHECKER-DATA-001: JSON result file not found", "path": self.path}
            data = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return False, {"error": "CHECKER-DATA-002: JSON top-level must be mapping", "path": self.path}
            missing = [key for key in self.required_keys if key not in data]
            if missing:
                return False, {
                    "error": "CHECKER-DATA-003: JSON result is missing required keys",
                    "path": self.path,
                    "missing_keys": missing,
                }
            return True, {
                "message": "JSON result contains all required keys",
                "path": self.path,
                "required_keys": self.required_keys,
            }
        except Exception as exc:
            return False, {"error": f"CHECKER-DATA-999: {exc}", "path": self.path}
```

对应的 Spec：

```yaml
name: json_required_keys_checker
description: "检查分析结果 JSON 是否包含必需字段"
entry:
  file: checkers/json_required_keys_checker.py
  class_name: JsonRequiredKeysChecker
  method: do_check
rules:
  type: json_required_keys
  required_keys:
    - status
    - summary
    - items
auto_tests: true
register:
  stage: analyze_content
  args:
    path: output/analysis.json
```

### 2. json_numeric_range — JSON 数值范围检查

```python
# checkers/json_numeric_range_checker.py
import json
from pathlib import Path
from ucagent.checkers.base import Checker


class JsonNumericRangeChecker(Checker):
    name = "json_numeric_range_checker"
    description = "检查 JSON 文件中指定字段是否在闭区间内"

    field = ""
    minimum = 0
    maximum = 100

    def __init__(self, path: str = "", field=None, minimum=None, maximum=None, **kwargs):
        super().__init__()
        self.path = path
        self.field = field or self.field
        self.minimum = self.minimum if minimum is None else minimum
        self.maximum = self.maximum if maximum is None else maximum
        self.set_human_check_needed(kwargs.get("need_human_check", False))

    def _resolve(self):
        candidate = Path(self.path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"Unsafe checker path: {self.path}")
        root = Path(self.workspace or ".").resolve()
        target = (root / candidate).resolve()
        if target != root and not str(target).startswith(str(root) + "/"):
            raise ValueError(f"Unsafe checker path: {self.path}")
        return target

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, dict]:
        try:
            target = self._resolve()
            data = json.loads(target.read_text(encoding="utf-8"))
            value = data.get(self.field) if isinstance(data, dict) else None
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False, {
                    "error": "CHECKER-RANGE-001: field is not numeric",
                    "field": self.field,
                    "value": value,
                }
            passed = self.minimum <= value <= self.maximum
            return passed, {
                "message": "numeric range check completed",
                "field": self.field,
                "value": value,
                "minimum": self.minimum,
                "maximum": self.maximum,
            }
        except Exception as exc:
            return False, {"error": f"CHECKER-RANGE-999: {exc}", "path": self.path}
```

### 3. file_exists — 文件存在检查

```python
# checkers/file_exists_checker.py
from pathlib import Path
from ucagent.checkers.base import Checker


class FileExistsChecker(Checker):
    name = "file_exists_checker"
    description = "检查工作流相对路径的文件是否存在"

    def __init__(self, path: str = "", **kwargs):
        super().__init__()
        self.path = path
        self.set_human_check_needed(kwargs.get("need_human_check", False))

    def _resolve(self):
        candidate = Path(self.path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"Unsafe checker path: {self.path}")
        root = Path(self.workspace or ".").resolve()
        target = (root / candidate).resolve()
        if target != root and not str(target).startswith(str(root) + "/"):
            raise ValueError(f"Unsafe checker path: {self.path}")
        return target

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, dict]:
        try:
            target = self._resolve()
            return target.is_file(), {
                "message": "file existence check completed",
                "path": self.path,
                "exists": target.is_file(),
            }
        except Exception as exc:
            return False, {"error": f"CHECKER-FILE-999: {exc}", "path": self.path}
```

### 4. command_exit_code — 命令退出码检查

```python
# checkers/command_exit_code_checker.py
import subprocess
from pathlib import Path
from ucagent.checkers.base import Checker


class CommandExitCodeChecker(Checker):
    name = "command_exit_code_checker"
    description = "运行白名单命令并检查退出码"

    allowed_commands = ["python3", "make"]
    expected_exit_code = 0

    def __init__(self, command=None, expected_exit_code=None, **kwargs):
        super().__init__()
        self.command = list(command or [])
        self.expected_exit_code = self.expected_exit_code if expected_exit_code is None else expected_exit_code
        self.set_human_check_needed(kwargs.get("need_human_check", False))

    def do_check(self, timeout=30, **kwargs) -> tuple[bool, dict]:
        try:
            if not self.command or self.command[0] not in self.allowed_commands:
                return False, {
                    "error": "CHECKER-CMD-001: command is not allowlisted",
                    "command": self.command,
                }
            proc = subprocess.run(
                self.command,
                cwd=str(Path(self.workspace or ".").resolve()),
                text=True,
                capture_output=True,
                timeout=timeout or 30,
            )
            passed = proc.returncode == self.expected_exit_code
            return passed, {
                "message": "command exit-code check completed",
                "command": self.command,
                "returncode": proc.returncode,
                "expected_exit_code": self.expected_exit_code,
                "stdout": proc.stdout[-2000:],
                "stderr": proc.stderr[-2000:],
            }
        except Exception as exc:
            return False, {"error": f"CHECKER-CMD-999: {exc}", "command": self.command}
```

---

## 第五部分：自定义 Checker 示例

### Markdown 章节检查器

检查 Markdown 文件是否包含指定标题：

```python
# checkers/markdown_sections_checker.py
from pathlib import Path
from ucagent.checkers.base import Checker


class MarkdownSectionsChecker(Checker):
    name = "markdown_sections_checker"
    description = "检查 Markdown 文件是否包含指定章节"

    required_sections = []

    def __init__(self, path: str = "", required_sections=None, **kwargs):
        super().__init__()
        self.path = path
        self.required_sections = list(required_sections or [])
        self.set_human_check_needed(kwargs.get("need_human_check", False))

    def _resolve(self):
        candidate = Path(self.path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"Unsafe checker path: {self.path}")
        root = Path(self.workspace or ".").resolve()
        target = (root / candidate).resolve()
        if target != root and not str(target).startswith(str(root) + "/"):
            raise ValueError(f"Unsafe checker path: {self.path}")
        return target

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, dict]:
        try:
            target = self._resolve()
            if not target.is_file():
                return False, {"error": "MD-CHECK-001: 文件不存在", "path": self.path}

            content = target.read_text(encoding="utf-8")
            missing = [sec for sec in self.required_sections if f"## {sec}" not in content]
            if missing:
                return False, {
                    "error": "MD-CHECK-002: 缺少必需章节",
                    "path": self.path,
                    "missing_sections": missing,
                }

            return True, {
                "message": "所有必需章节存在",
                "path": self.path,
                "sections_found": self.required_sections,
            }
        except Exception as exc:
            return False, {"error": f"MD-CHECK-999: {exc}", "path": self.path}
```

对应的 Spec：

```yaml
name: markdown_sections_checker
description: "检查文档是否包含 Purpose、Usage、Checks 三个必需章节"
entry:
  file: checkers/markdown_sections_checker.py
  class_name: MarkdownSectionsChecker
  method: do_check
rules:
  type: file_exists                    # auto_tests 用 file_exists 代替
auto_tests: false                      # 自定义 checker 不需要 auto_tests
register:
  stage: generate_report
  args:
    path: output/report.md
    required_sections:
      - Purpose
      - Usage
      - Checks
```

---

## 第六部分：Auto Tests 机制

设置 `auto_tests: true` 时，生成器自动：

1. 创建正反测试夹具（如 `.workflow/checker_tests/cases/<checker_name>/valid.json`）
2. 向 spec 的 `tests` 列表写回测试用例
3. 将夹具路径写入 spec 的 `register.args`

不同规则类型生成的测试：

| 规则类型 | 正向测试（expected_pass=true） | 反向测试（expected_pass=false） |
|----------|-------------------------------|--------------------------------|
| `json_required_keys` | 包含所有必需字段的 JSON | 缺少最后一个字段的 JSON |
| `json_numeric_range` | 值 = minimum 的 JSON | 值 = maximum+1 的 JSON |
| `file_exists` | 创建 present.txt | 引用不存在的 missing.txt |
| `command_exit_code` | `python3 -c "raise SystemExit(0)"` | `python3 -c "raise SystemExit(1)"` |

---

## 第七部分：验证闭环

```
make check_checker_specs   → 校验 checker_spec YAML 格式和字段
make check_checkers        → 校验继承关系、do_check 方法及方法级 docstring，并调用 str(checker)
make test_checkers         → direct runner 直接实例化+正反测试
make smoke                 → 在真实 UCAgent 阶段完成时触发 checker
make check                 → 确认闭环不破坏其他检查
```

如果出现 `No description provided for this checker(...)`，应在报错类的 `do_check()`
函数体第一条语句补充非空 docstring，再重新执行 `make check_checkers` 和
`make test_checkers`。不要只修改 spec `description` 或类属性 `description`。
