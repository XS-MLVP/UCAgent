# 工具生成规范

## 概述

工作流工具是普通的 Python 类，通过 `WorkflowToolGenerator` 从结构化 spec 文件生成框架代码，也可以手写完整实现。工具不绑定 MCP、LangChain 或 UCAgent 框架，只依赖 Python 标准库。

---

## 第一部分：工具 Spec 格式

每份工具 spec 是 `.workflow/tool_specs/<tool_name>.yaml`，必须包含以下字段：

```yaml
name: my_tool                    # 工具唯一名称
description: "工具功能描述"       # 给 Agent 看的说明
entry:
  file: tools/my_tool.py         # 生成的目标文件路径（必须 tools/ 开头）
  class_name: MyTool             # Python 类名
  method: run                    # 入口方法名
inputs:                          # 输入参数列表
  - name: path
    type: path                   # 类型：path/string/int/bool
    required: true
    description: "输入文件路径"
outputs:                         # 输出规范
  type: dict
  required_keys:                 # 必须包含的顶层 key
    - ok
    - data
    - errors
    - warnings
    - meta
  data_required_keys:            # data 字段中必须包含的 key
    - result
    - line_count
tests:                           # 测试用例
  - name: basic_test
    input:
      path: .workflow/tool_tests/cases/<tool_name>/sample.txt
    expected:
      ok: true
```

`run_command_tool` 是固定运行基础设施，不属于业务 `required_tools`。它允许在工作流根目录或子目录执行经过批准的检查目标，以及根级 `tmp/` 内的单个 `.py`/`.sh` batch 文件，但不会提供真正的文件系统沙箱；因此脚本内容仍需经过代码审查。调用者不得使用绝对路径、`..`、inline interpreter、额外解释器参数、shell 拼接或未批准参数。batch 产生的一次性脚本和中间文件只能放入根级 `tmp/`，持久脚本必须进入明确的交付目录并有 spec、测试和开发者文档；`make clean` 会清空 `tmp/` 的普通与隐藏内容。

---

## 第二部分：统一返回结构

所有工具的 `run` 方法必须返回带以下五个顶层 key 的 dict：

```python
{
    "ok": True,              # 布尔值，整体成功/失败
    "data": {},              # 业务数据
    "errors": [],            # 错误列表，每项含 code 和 message
    "warnings": [],          # 警告列表
    "meta": {},              # 元信息（输入参数、上下文等）
}
```

失败时也必须返回相同结构，在 `errors` 中放置错误码和信息：

```python
{
    "ok": False,
    "data": {},
    "errors": [{"code": "MY-TOOL-001", "message": "File not found: input.txt"}],
    "warnings": [],
    "meta": {"path": "input.txt"},
}
```

---

## 第三部分：手写工具的完整模板

不依赖生成器，从零编写一个工具类。以下是必须遵循的骨架：

```python
# -*- coding: utf-8 -*-
from pathlib import Path


class MyTool:
    # 1. 元数据（必填）
    name = "my_tool"
    description = "工具功能描述"

    # 2. 输入 schema（必填）
    input_schema = {
        "path": {
            "type": "path",
            "required": True,
            "description": "输入文件路径，相对于工作流根目录",
        },
        "option": {
            "type": "string",
            "required": False,
            "description": "可选参数",
        },
    }

    # 3. 输出 schema（必填）
    output_schema = {
        "type": "dict",
        "required_keys": ["ok", "data", "errors", "warnings", "meta"],
        "data_required_keys": ["result", "line_count"],
    }

    # 4. 构造函数（必填）
    def __init__(self, root_dir="."):
        self.root_dir = Path(root_dir).resolve()

    # 5. 路径安全函数（必填）
    def _safe_resolve(self, path):
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"Unsafe path outside workflow root: {path}")
        target = (self.root_dir / candidate).resolve()
        if target != self.root_dir and not str(target).startswith(str(self.root_dir) + "/"):
            raise ValueError(f"Unsafe path outside workflow root: {path}")
        return target

    # 6. 入口方法（必填）
    def run(self, **kwargs) -> dict:
        try:
            path = kwargs.get("path")
            option = kwargs.get("option", "default")

            if not path:
                return {
                    "ok": False,
                    "data": {},
                    "errors": [{"code": "MY-TOOL-001", "message": "Missing required parameter: path"}],
                    "warnings": [],
                    "meta": {"inputs": kwargs},
                }

            target = self._safe_resolve(path)
            if not target.is_file():
                return {
                    "ok": False,
                    "data": {},
                    "errors": [{"code": "MY-TOOL-002", "message": f"File not found: {path}"}],
                    "warnings": [],
                    "meta": {"path": path},
                }

            content = target.read_text(encoding="utf-8")
            # ===== 在这里实现你的业务逻辑 =====
            result = f"Processed with option={option}: {len(content)} chars"

            return {
                "ok": True,
                "data": {
                    "result": result,
                    "line_count": len(content.splitlines()),
                },
                "errors": [],
                "warnings": [],
                "meta": {"path": path, "option": option},
            }

        except Exception as exc:
            return {
                "ok": False,
                "data": {},
                "errors": [{"code": "MY-TOOL-999", "message": str(exc)}],
                "warnings": [],
                "meta": {"inputs": kwargs},
            }
```

---

## 第四部分：内置基础工具完整源码

### ReadTextFileTool — 读取文本文件

```python
# -*- coding: utf-8 -*-
from pathlib import Path


class ReadTextFileTool:
    name = "read_text_file_tool"
    description = "读取工作流目录内的文本文件，并返回文件内容、行数和字符数。"

    input_schema = {
        "path": {
            "type": "path",
            "required": True,
            "description": "需要读取的文本文件路径，相对于工作流根目录。",
        }
    }

    output_schema = {
        "type": "dict",
        "required_keys": ["ok", "data", "errors", "warnings", "meta"],
        "data_required_keys": ["content", "line_count", "char_count"],
    }

    def __init__(self, root_dir="."):
        self.root_dir = Path(root_dir).resolve()

    def _safe_resolve(self, path):
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"Unsafe path outside workflow root: {path}")
        target = (self.root_dir / candidate).resolve()
        if target != self.root_dir and not str(target).startswith(str(self.root_dir) + "/"):
            raise ValueError(f"Unsafe path outside workflow root: {path}")
        return target

    def run(self, path: str) -> dict:
        try:
            target = self._safe_resolve(path)
            if not target.exists():
                return {
                    "ok": False,
                    "data": {},
                    "errors": [{"code": "READ-FILE-001", "message": f"File not found: {path}"}],
                    "warnings": [],
                    "meta": {"path": path},
                }
            if not target.is_file():
                return {
                    "ok": False,
                    "data": {},
                    "errors": [{"code": "READ-FILE-002", "message": f"Path is not a file: {path}"}],
                    "warnings": [],
                    "meta": {"path": path},
                }
            content = target.read_text(encoding="utf-8")
            return {
                "ok": True,
                "data": {
                    "content": content,
                    "line_count": len(content.splitlines()),
                    "char_count": len(content),
                },
                "errors": [],
                "warnings": [],
                "meta": {"path": path},
            }
        except Exception as exc:
            return {
                "ok": False,
                "data": {},
                "errors": [{"code": "READ-FILE-999", "message": str(exc)}],
                "warnings": [],
                "meta": {"path": path},
            }
```

### WriteTextFileTool — 写入文本文件

```python
# -*- coding: utf-8 -*-
from pathlib import Path


class WriteTextFileTool:
    name = "write_text_file_tool"
    description = "向工作流目录内写入文本文件，并返回写入路径和字节数。"

    input_schema = {
        "path": {
            "type": "path",
            "required": True,
            "description": "需要写入的文本文件路径，相对于工作流根目录。",
        },
        "content": {
            "type": "string",
            "required": True,
            "description": "要写入的文本内容。",
        },
        "overwrite": {
            "type": "bool",
            "required": False,
            "description": "是否允许覆盖已有文件，默认 false。",
        },
    }

    output_schema = {
        "type": "dict",
        "required_keys": ["ok", "data", "errors", "warnings", "meta"],
        "data_required_keys": ["written_path", "bytes_written"],
    }

    def __init__(self, root_dir="."):
        self.root_dir = Path(root_dir).resolve()

    def _safe_resolve(self, path):
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"Unsafe path outside workflow root: {path}")
        target = (self.root_dir / candidate).resolve()
        if target != self.root_dir and not str(target).startswith(str(self.root_dir) + "/"):
            raise ValueError(f"Unsafe path outside workflow root: {path}")
        return target

    def run(self, path: str, content: str, overwrite: bool = False) -> dict:
        try:
            target = self._safe_resolve(path)
            if target.exists() and not overwrite:
                return {
                    "ok": False,
                    "data": {},
                    "errors": [{"code": "WRITE-FILE-001", "message": f"File already exists: {path}"}],
                    "warnings": [],
                    "meta": {"path": path},
                }
            if target.exists() and not target.is_file():
                return {
                    "ok": False,
                    "data": {},
                    "errors": [{"code": "WRITE-FILE-002", "message": f"Path is not a file: {path}"}],
                    "warnings": [],
                    "meta": {"path": path},
                }
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return {
                "ok": True,
                "data": {
                    "written_path": str(target.relative_to(self.root_dir)),
                    "bytes_written": len(content.encode("utf-8")),
                },
                "errors": [],
                "warnings": [],
                "meta": {"path": path, "overwrite": overwrite},
            }
        except Exception as exc:
            return {
                "ok": False,
                "data": {},
                "errors": [{"code": "WRITE-FILE-999", "message": str(exc)}],
                "warnings": [],
                "meta": {"path": path, "overwrite": overwrite},
            }
```

### RunCommandTool — 安全执行命令

```python
# -*- coding: utf-8 -*-
import shlex
import subprocess
from pathlib import Path


class RunCommandTool:
    name = "run_command_tool"
    description = "在工作流目录内运行白名单命令或受控 batch 脚本，并返回执行证据。"

    allowed_commands = {"python", "python3", "bash", "sh", "pytest", "make", "ls", "cat", "pwd"}
    allowed_make_targets = {
        "help", "clean", "plan", "package", "check", "check_input",
        "check_example", "check_config", "check_inc_config", "check_layout", "check_docs",
        "check_tool_specs", "check_tools", "test_tools",
        "check_checker_specs", "check_checkers", "test_checkers",
        "check_package", "test_mcp",
    }
    forbidden_fragments = ("sudo", "rm -rf", "curl | bash", "chmod -R", "&&", "||", ";", "|", "`", "$(")

    input_schema = {
        "command": {
            "type": "string",
            "required": True,
            "description": "只允许白名单命令；Python/Shell 脚本必须位于工作流根级 tmp/ 内。",
        },
        "cwd": {
            "type": "path",
            "required": False,
            "description": "命令运行目录，相对于工作流根目录。",
        },
        "timeout": {
            "type": "int",
            "required": False,
            "description": "超时时间秒数，默认 30。",
        },
    }

    output_schema = {
        "type": "dict",
        "required_keys": ["ok", "data", "errors", "warnings", "meta"],
        "data_required_keys": ["return_code", "stdout", "stderr"],
    }

    def __init__(self, root_dir="."):
        self.root_dir = Path(root_dir).resolve()

    def _safe_cwd(self, cwd):
        rel = Path(cwd or ".")
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"Unsafe cwd outside workflow root: {cwd}")
        target = (self.root_dir / rel).resolve()
        if target != self.root_dir and not str(target).startswith(str(self.root_dir) + "/"):
            raise ValueError(f"Unsafe cwd outside workflow root: {cwd}")
        if not target.is_dir():
            raise ValueError(f"cwd is not a directory: {cwd}")
        return target

    def _safe_argument_path(self, value, workdir):
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"Unsafe command path: {value}")
        target = (workdir / candidate).resolve()
        if target != self.root_dir and self.root_dir not in target.parents:
            raise ValueError(f"Unsafe command path: {value}")
        return target

    def _parse_command(self, command, workdir):
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command is empty")
        for fragment in self.forbidden_fragments:
            if fragment in command:
                raise ValueError(f"Forbidden command fragment: {fragment}")
        argv = shlex.split(command)
        if not argv:
            raise ValueError("command is empty")
        if argv[0] not in self.allowed_commands:
            raise ValueError(f"Command not allowed: {argv[0]}")
        executable = argv[0]
        if executable in {"python", "python3", "bash", "sh"}:
            if len(argv) != 2 or argv[1].startswith("-"):
                raise ValueError("Interpreter requires exactly one tmp script")
            suffix = ".py" if executable in {"python", "python3"} else ".sh"
            script = self._safe_argument_path(argv[1], workdir)
            temp_root = (self.root_dir / "tmp").resolve()
            if (
                script.suffix != suffix
                or not script.is_file()
                or (script != temp_root and temp_root not in script.parents)
            ):
                raise ValueError(f"Script must be an existing {suffix} file below tmp/")
        elif executable == "make":
            if len(argv) != 2 or argv[1] not in self.allowed_make_targets:
                raise ValueError("make target is not allowed")
        elif executable in {"cat", "ls"}:
            if any(arg.startswith("-") for arg in argv[1:]):
                raise ValueError("command options are not allowed")
            for value in argv[1:]:
                self._safe_argument_path(value, workdir)
        elif executable == "pwd" and len(argv) != 1:
            raise ValueError("pwd does not accept arguments")
        return argv

    def run(self, command: str, cwd: str = ".", timeout: int = 30) -> dict:
        try:
            workdir = self._safe_cwd(cwd)
            argv = self._parse_command(command, workdir)
            timeout_value = int(timeout or 30)
            if timeout_value <= 0 or timeout_value > 120:
                raise ValueError("timeout must be between 1 and 120 seconds")
            proc = subprocess.run(
                argv,
                cwd=str(workdir),
                text=True,
                capture_output=True,
                timeout=timeout_value,
                shell=False,
            )
            return {
                "ok": proc.returncode == 0,
                "data": {
                    "return_code": proc.returncode,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                },
                "errors": [] if proc.returncode == 0 else [{"code": "RUN-CMD-001", "message": "Command returned non-zero"}],
                "warnings": [],
                "meta": {"command": command, "cwd": cwd, "timeout": timeout_value},
            }
        except Exception as exc:
            return {
                "ok": False,
                "data": {},
                "errors": [{"code": "RUN-CMD-999", "message": str(exc)}],
                "warnings": [],
                "meta": {"command": command, "cwd": cwd, "timeout": timeout},
            }
```

---

## 第五部分：手写业务工具完整示例

### JSON 结果收集器

收集多个 JSON 结果文件，合并为一个汇总 JSON。

```python
# -*- coding: utf-8 -*-
import json
from pathlib import Path


class JsonResultCollector:
    name = "json_result_collector"
    description = "收集多个 JSON 结果文件，合并为一个汇总 JSON。"

    input_schema = {
        "paths": {
            "type": "string_list",
            "required": True,
            "description": "JSON 文件路径列表，以逗号分隔",
        },
        "output_path": {
            "type": "path",
            "required": True,
            "description": "汇总结果输出路径",
        },
        "sort_by": {
            "type": "string",
            "required": False,
            "description": "按哪个字段排序，默认不排序",
        },
    }

    output_schema = {
        "type": "dict",
        "required_keys": ["ok", "data", "errors", "warnings", "meta"],
        "data_required_keys": ["collected_count", "failed_count", "output_path"],
    }

    def __init__(self, root_dir="."):
        self.root_dir = Path(root_dir).resolve()

    def _safe_resolve(self, path):
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"Unsafe path: {path}")
        target = (self.root_dir / candidate).resolve()
        if target != self.root_dir and not str(target).startswith(str(self.root_dir) + "/"):
            raise ValueError(f"Unsafe path: {path}")
        return target

    def run(self, paths: str = "", output_path: str = "", sort_by: str = "") -> dict:
        errors = []
        warnings = []
        results = []
        failed = 0

        path_list = [p.strip() for p in paths.split(",") if p.strip()]
        if not path_list:
            return {
                "ok": False,
                "data": {"collected_count": 0, "failed_count": 0, "output_path": output_path},
                "errors": [{"code": "COL-001", "message": "paths 不能为空"}],
                "warnings": [],
                "meta": {"inputs": {"paths": paths, "output_path": output_path}},
            }

        for rel_path in path_list:
            try:
                target = self._safe_resolve(rel_path)
                if not target.is_file():
                    failed += 1
                    warnings.append(f"文件不存在: {rel_path}")
                    continue
                data = json.loads(target.read_text(encoding="utf-8"))
                results.append(data)
            except json.JSONDecodeError:
                failed += 1
                warnings.append(f"JSON 解析失败: {rel_path}")
            except Exception as exc:
                failed += 1
                errors.append({"code": "COL-002", "message": f"{rel_path}: {exc}"})

        if sort_by:
            results.sort(key=lambda x: x.get(sort_by, ""))

        summary = {
            "total": len(path_list),
            "collected": len(results),
            "failed": failed,
            "results": results,
        }

        try:
            out = self._safe_resolve(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            return {
                "ok": False,
                "data": {"collected_count": len(results), "failed_count": failed, "output_path": output_path},
                "errors": [{"code": "COL-003", "message": f"写入输出文件失败: {exc}"}],
                "warnings": warnings,
                "meta": {"paths": path_list, "output_path": output_path},
            }

        return {
            "ok": True,
            "data": {
                "collected_count": len(results),
                "failed_count": failed,
                "output_path": output_path,
            },
            "errors": errors,
            "warnings": warnings,
            "meta": {"paths": path_list, "output_path": output_path, "sort_by": sort_by},
        }
```

对应的 Spec（如果使用 from_spec 模式生成框架后再手写补全）：

```yaml
name: json_result_collector
description: "收集多个 JSON 结果文件并合并为一个汇总 JSON。"

entry:
  file: tools/json_result_collector.py
  class_name: JsonResultCollector
  method: run

inputs:
  - name: paths
    type: string
    required: true
    description: "JSON 文件路径列表，以逗号分隔"
  - name: output_path
    type: path
    required: true
    description: "汇总结果输出路径"
  - name: sort_by
    type: string
    required: false
    description: "按哪个字段排序"

outputs:
  type: dict
  required_keys:
    - ok
    - data
    - errors
    - warnings
    - meta
  data_required_keys:
    - collected_count
    - failed_count
    - output_path

tests:
  - name: collect_two_files
    input:
      paths: ".workflow/tool_tests/cases/json_result_collector/a.json,.workflow/tool_tests/cases/json_result_collector/b.json"
      output_path: ".workflow/tool_tests/cases/json_result_collector/summary.json"
    expected:
      ok: true
  - name: empty_paths
    input:
      paths: ""
      output_path: "output/dummy.json"
    expected:
      ok: false
```

---

## ⚠️ 重要警告：生成器只产框架，不产业务逻辑

`WorkflowToolGenerator` 在 `from_spec` 模式下生成的工具只做了两件事：

1. 读取 `path` 参数指向的文件
2. 对所有 `data_required_keys` 填充默认值

默认值规则（`_default_value`）：

| 字段命名模式 | 默认值 |
|-------------|--------|
| `*_count` / `count` | `0` |
| `has_*` / `is_*` | `False` |
| `*_names` / `*_ports` / `*s` | `[]` |
| 其他 | `""` |

**这意味着任何需要真正业务逻辑的工具（解析、聚合、比对、计算），生成器只能产出空壳。**

Agent 必须在生成后验证：读取 `tools/<tool>.py`，确认 `run()` 方法中 data 字段是否有真实赋值逻辑。若所有字段仅依赖 `_default_value`，必须手写补全实现。

## 第六部分：两种生成模式对比

### base 模式（可选内置工具）

`base` 模式只用于需求明确需要这些通用能力时。不要把 `read_text_file_tool`、`write_text_file_tool`
或 `run_command_tool` 当成所有工作流的默认工具；工作流应优先从 `requirements_manifest.required_tools`
设计自己的业务工具。调用 `base` 模式时必须显式传入 `tools=[...]`，空列表会被拒绝，避免误生成无关工具。

```text
WorkflowToolGenerator(
  workflow_root="<root>",
  mode="base",
  tools=["read_text_file_tool", "write_text_file_tool", "run_command_tool"],
  existing_policy="create_only",
  update_config=true
)
```

直接写入完整的 spec 和代码文件。生成的是**立即可用的完整工具**，但只应在当前工作流确实需要时使用。

### from_spec 模式（从 spec 生成框架）

```text
WorkflowToolGenerator(
  workflow_root="<root>",
  mode="from_spec",
  spec_paths=[".workflow/tool_specs/my_tool.yaml"],
  existing_policy="create_only",
  update_config=true
)
```

生成的是**骨架代码**：所有 `data_required_keys` 自动填默认值，文件读取后的 `content`/`line_count`/`char_count` 自动填充。需要手写补充实际业务逻辑。源码一旦补充业务实现，后续只能使用 `create_only` 保留它；`refresh_scaffold` 仅接受生成状态摘要匹配的未修改骨架，`force_replace` 会破坏人工实现，除非用户明确批准恢复骨架，否则禁止使用。

### 什么时候用哪种

| 场景 | 推荐方式 |
|------|----------|
| 基础 I/O 工具（读文件、写文件、运行命令） | base 模式 |
| 数据收集、聚合、解析、比对等复杂逻辑 | from_spec 生成骨架 → 手写补全业务逻辑 |
| 简单文件属性检查（存在、大小、格式） | from_spec 生成即可（读文件+填 content 够用） |
| 需要调用外部库或 API | 完全手写 |

---

## 第七部分：路径安全

所有工具必须实现 `_safe_resolve` 方法：

- **禁止绝对路径**：`candidate.is_absolute()` → 抛 ValueError
- **禁止 `..`**：`".." in candidate.parts` → 抛 ValueError
- **禁止越界**：resolve 后不在 root_dir 下 → 抛 ValueError

---

## 第八部分：配置注册

工具注册到 `config.yaml` 的 `tools.GeneratedTools`：

```yaml
tools:
  RunTestCases:
    test_dir: .workflow/tool_tests/cases
  GeneratedTools:
    - name: my_tool
      spec: .workflow/tool_specs/my_tool.yaml
      file: tools/my_tool.py
      enabled: true
```

注意：`tools` 必须是 **mapping**，不能是 list。

---

## 第九部分：验证闭环

```
make check_tool_specs → 校验 spec YAML 格式和必需字段
make check_tools      → 校验生成工具代码的结构（类名、方法、schema）
make test_tools       → direct runner 直接实例化+调用测试用例
make test_mcp         → 启动子 UCAgent，通过真实 MCP 调用工具
make check            → 确认闭环不破坏其他检查
```

---

## 第十部分：测试夹具规范

- `expected.ok=true` 的测试输入放在 `.workflow/tool_tests/cases/`，不要创建根目录 `examples/`
- 上述路径是子工作流内部契约。当前外层 Builder Agent 调用 `ReadTextFile`、`PathList`、`GetFileInfo` 或 `RunTestCases` 时，必须在前面加生成根目录（例如 `{TEST_WORKFLOW_ROOT}/.workflow/tool_tests/cases`）；只有写入子工作流的 spec、config 和 Makefile 时才保留 `.workflow/...`。外层提示 `.workflow/...` 不存在时，不得在外层 workspace 创建补丁目录。
- 生成工具的测试不是 pytest 文件集合，而是由 `.workflow/tool_specs/*.yaml` 中的 `tests` 驱动。应在子工作流根目录运行 `make check_tool_specs`、`make check_tools`、`make test_tools`，由 `tool_direct_runner.py` 执行；不要调用外层 `RunTestCases` 查找 `test_tool_checks.py`，也不要为了消除“收集 0 项”而创建虚假 pytest 文件。
- `smoke_tool_selection.yaml.fixture_paths` 可以声明普通文件，也可以声明包含实际文件的
  非空目录。源码树、图片集合等目录型输入应保留目录语义；Checker 会递归确认目录中
  至少存在一个文件。空目录不算有效正向 fixture。
- 禁止依赖 `output/`、`.workflow/logs/` 等在发布清理中删除的路径
- 每个工具至少需要一个正向测试和一个失败测试

## 日志位置

```
.workflow/logs/tool_spec_check.log   ← make check_tool_specs 输出
.workflow/logs/tool_static_check.log ← make check_tools 输出
.workflow/logs/tool_direct_run.log   ← make test_tools 输出
.workflow/logs/tool_mcp_run.log      ← make test_mcp 子 UCAgent 日志
output/mcp_test_result.log           ← MCP 测试结果汇总
```
