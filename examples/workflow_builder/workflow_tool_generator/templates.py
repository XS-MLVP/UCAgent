# -*- coding: utf-8 -*-
"""Tool templates used by WorkflowToolGenerator."""

from __future__ import annotations

from typing import Any

READ_TEXT_FILE_TOOL_SPEC = r'''name: read_text_file_tool
description: "读取工作流目录内的文本文件，并返回文件内容、行数和字符数。"

entry:
  file: tools/read_text_file_tool.py
  class_name: ReadTextFileTool
  method: run

inputs:
  - name: path
    type: path
    required: true
    description: "需要读取的文本文件路径，相对于工作流根目录。"

outputs:
  type: dict
  required_keys:
    - ok
    - data
    - errors
    - warnings
    - meta
  data_required_keys:
    - content
    - line_count
    - char_count

tests:
  - name: basic_read
    input:
      path: examples/input_example.json
    expected:
      ok: true
      return_type: dict
      required_keys:
        - ok
        - data
        - errors
        - warnings
        - meta
      data_required_keys:
        - content
        - line_count
        - char_count
'''

READ_TEXT_FILE_TOOL = r'''# -*- coding: utf-8 -*-
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
'''

WRITE_TEXT_FILE_TOOL_SPEC = r'''name: write_text_file_tool
description: "向工作流目录内写入文本文件，并返回写入路径和字节数。"

entry:
  file: tools/write_text_file_tool.py
  class_name: WriteTextFileTool
  method: run

inputs:
  - name: path
    type: path
    required: true
    description: "需要写入的文本文件路径，相对于工作流根目录。"
  - name: content
    type: string
    required: true
    description: "要写入的文本内容。"
  - name: overwrite
    type: bool
    required: false
    description: "是否允许覆盖已有文件，默认 false。"

outputs:
  type: dict
  required_keys:
    - ok
    - data
    - errors
    - warnings
    - meta
  data_required_keys:
    - written_path
    - bytes_written

tests:
  - name: basic_write
    input:
      path: output/tool_tests/write_text_file_basic.txt
      content: "hello workflow tool\n"
      overwrite: true
    expected:
      ok: true
      return_type: dict
      required_keys:
        - ok
        - data
        - errors
        - warnings
        - meta
      data_required_keys:
        - written_path
        - bytes_written
'''

WRITE_TEXT_FILE_TOOL = r'''# -*- coding: utf-8 -*-
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
'''

RUN_COMMAND_TOOL_SPEC = r'''name: run_command_tool
description: "在工作流目录内运行受限命令或根级 tmp/ 内的 Python/Shell batch 脚本，不使用 shell 拼接，并返回退出码、标准输出和标准错误。"

entry:
  file: tools/run_command_tool.py
  class_name: RunCommandTool
  method: run

inputs:
  - name: command
    type: string
    required: true
    description: "仅允许白名单可执行程序；脚本文件必须位于工作流根级 tmp/ 内，且不通过 shell 拼接执行。"
  - name: cwd
    type: path
    required: false
    description: "命令运行目录，相对于工作流根目录，默认当前工作流根目录。"
  - name: timeout
    type: int
    required: false
    description: "超时时间秒数，默认 30。"

outputs:
  type: dict
  required_keys:
    - ok
    - data
    - errors
    - warnings
    - meta
  data_required_keys:
    - return_code
    - stdout
    - stderr

tests:
  - name: basic_pwd
    input:
      command: pwd
      cwd: .
      timeout: 10
    expected:
      ok: true
      return_type: dict
      required_keys:
        - ok
        - data
        - errors
        - warnings
        - meta
      data_required_keys:
        - return_code
        - stdout
        - stderr
  - name: reject_inline_python
    input:
      command: "python3 -c print(1)"
      cwd: .
      timeout: 10
    expected:
      ok: false
      return_type: dict
      required_keys:
        - ok
        - data
        - errors
        - warnings
        - meta
  - name: reject_non_tmp_script
    input:
      command: "python3 tools/run_command_tool.py"
      cwd: .
      timeout: 10
    expected:
      ok: false
      return_type: dict
      required_keys:
        - ok
        - data
        - errors
        - warnings
        - meta
'''

RUN_COMMAND_TOOL = r'''# -*- coding: utf-8 -*-
import shlex
import subprocess
from pathlib import Path


class RunCommandTool:
    name = "run_command_tool"
    description = "在工作流目录内运行白名单命令或受控 batch 脚本，并返回执行证据。"

    allowed_commands = {"python", "python3", "bash", "sh", "pytest", "make", "ls", "cat", "pwd"}
    allowed_make_targets = {
        "help", "clean", "plan", "package", "check", "check_input",
        "check_example", "check_config", "check_layout", "check_docs",
        "check_tool_specs", "check_tools", "test_tools",
        "check_checker_specs", "check_checkers", "test_checkers",
        "check_package", "test_mcp",
    }
    forbidden_fragments = ("sudo", "rm -rf", "curl | bash", "chmod -R", "&&", "||", ";", "|", "`", "$(")

    input_schema = {
        "command": {
            "type": "string",
            "required": True,
            "description": "仅允许白名单命令；Python/Shell 脚本必须位于工作流根级 tmp/ 内。",
        },
        "cwd": {
            "type": "path",
            "required": False,
            "description": "命令运行目录，相对于工作流根目录，默认当前工作流根目录。",
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
            raise ValueError(f"Unsafe command path outside workflow root: {value}")
        target = (workdir / candidate).resolve()
        if target != self.root_dir and self.root_dir not in target.parents:
            raise ValueError(f"Unsafe command path outside workflow root: {value}")
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
                raise ValueError("Interpreter commands require exactly one tmp script file")
            expected_suffix = ".py" if executable in {"python", "python3"} else ".sh"
            script = self._safe_argument_path(argv[1], workdir)
            temp_root = (self.root_dir / "tmp").resolve()
            if (
                script.suffix != expected_suffix
                or not script.is_file()
                or (script != temp_root and temp_root not in script.parents)
            ):
                raise ValueError(
                    f"Script must be an existing {expected_suffix} file below workflow tmp/"
                )
        elif executable == "make":
            if len(argv) != 2 or argv[1] not in self.allowed_make_targets:
                raise ValueError("make requires one explicitly allowed target")
        elif executable in {"cat", "ls"}:
            if any(arg.startswith("-") for arg in argv[1:]):
                raise ValueError(f"{executable} options are not allowed")
            for value in argv[1:]:
                self._safe_argument_path(value, workdir)
        elif executable == "pwd" and len(argv) != 1:
            raise ValueError("pwd does not accept arguments")
        elif executable == "pytest":
            for value in argv[1:]:
                if value == "-q":
                    continue
                if value.startswith("-"):
                    raise ValueError(f"pytest option not allowed: {value}")
                self._safe_argument_path(value.split("::", 1)[0], workdir)
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
'''

BUILTIN_TOOLS = {
    "read_text_file_tool": {
        "spec_path": ".workflow/tool_specs/read_text_file_tool.yaml",
        "tool_path": "tools/read_text_file_tool.py",
        "spec": READ_TEXT_FILE_TOOL_SPEC,
        "tool": READ_TEXT_FILE_TOOL,
    },
    "write_text_file_tool": {
        "spec_path": ".workflow/tool_specs/write_text_file_tool.yaml",
        "tool_path": "tools/write_text_file_tool.py",
        "spec": WRITE_TEXT_FILE_TOOL_SPEC,
        "tool": WRITE_TEXT_FILE_TOOL,
    },
    "run_command_tool": {
        "spec_path": ".workflow/tool_specs/run_command_tool.yaml",
        "tool_path": "tools/run_command_tool.py",
        "spec": RUN_COMMAND_TOOL_SPEC,
        "tool": RUN_COMMAND_TOOL,
    },
}


def _schema_from_inputs(inputs: Any) -> dict[str, dict[str, Any]]:
    schema: dict[str, dict[str, Any]] = {}
    if not isinstance(inputs, list):
        return schema
    for item in inputs:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        schema[item["name"]] = {
            "type": item.get("type", "string"),
            "required": bool(item.get("required", False)),
            "description": item.get("description", ""),
        }
    return schema


def _output_schema_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    outputs = spec.get("outputs", {})
    if not isinstance(outputs, dict):
        outputs = {}
    return {
        "type": outputs.get("type", "dict"),
        "required_keys": outputs.get("required_keys", ["ok", "data", "errors", "warnings", "meta"]),
        "data_required_keys": outputs.get("data_required_keys", []),
    }


def render_tool_from_spec(spec: dict[str, Any]) -> str:
    """Render a Python tool implementation from a validated tool_spec."""
    return _render_generic_tool(spec)


def _render_generic_tool(spec: dict[str, Any]) -> str:
    entry = spec["entry"]
    class_name = entry["class_name"]
    method_name = entry.get("method", "run")
    tool_name = spec["name"]
    description = spec.get("description", "")
    input_schema = _schema_from_inputs(spec.get("inputs", []))
    output_schema = _output_schema_from_spec(spec)
    path_inputs = [name for name, item in input_schema.items() if item.get("type") == "path"]
    return f'''# -*- coding: utf-8 -*-
from pathlib import Path


class {class_name}:
    name = {tool_name!r}
    description = {description!r}

    input_schema = {input_schema!r}

    output_schema = {output_schema!r}

    def __init__(self, root_dir="."):
        self.root_dir = Path(root_dir).resolve()

    def _safe_resolve(self, path):
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"Unsafe path outside workflow root: {{path}}")
        target = (self.root_dir / candidate).resolve()
        if target != self.root_dir and not str(target).startswith(str(self.root_dir) + "/"):
            raise ValueError(f"Unsafe path outside workflow root: {{path}}")
        return target

    def _default_value(self, key):
        if key.endswith("_count") or key in {{"count", "line_count", "char_count"}}:
            return 0
        if key.startswith("has_") or key.startswith("is_"):
            return False
        if key.endswith("_names") or key.endswith("_ports") or key.endswith("_items") or key.endswith("s"):
            return []
        return ""

    def {method_name}(self, **kwargs) -> dict:
        try:
            data = {{key: self._default_value(key) for key in self.output_schema.get("data_required_keys", [])}}
            path_inputs = {path_inputs!r}
            if path_inputs:
                path_name = path_inputs[0]
                if path_name not in kwargs:
                    return {{
                        "ok": False,
                        "data": {{}},
                        "errors": [{{"code": "GEN-TOOL-001", "message": f"Missing required path input: {{path_name}}"}}],
                        "warnings": [],
                        "meta": {{"inputs": kwargs}},
                    }}
                target = self._safe_resolve(kwargs[path_name])
                if not target.is_file():
                    return {{
                        "ok": False,
                        "data": {{}},
                        "errors": [{{"code": "GEN-TOOL-002", "message": f"Input file not found: {{kwargs[path_name]}}"}}],
                        "warnings": [],
                        "meta": {{"inputs": kwargs}},
                    }}
                content = target.read_text(encoding="utf-8")
                if "content" in data:
                    data["content"] = content
                if "text" in data:
                    data["text"] = content
                if "line_count" in data:
                    data["line_count"] = len(content.splitlines())
                if "char_count" in data:
                    data["char_count"] = len(content)
            return {{
                "ok": True,
                "data": data,
                "errors": [],
                "warnings": [],
                "meta": {{"inputs": kwargs}},
            }}
        except Exception as exc:
            return {{
                "ok": False,
                "data": {{}},
                "errors": [{{"code": "GEN-TOOL-999", "message": str(exc)}}],
                "warnings": [],
                "meta": {{"inputs": kwargs}},
            }}
'''
