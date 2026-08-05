# -*- coding: utf-8 -*-
"""Checker source templates."""

from __future__ import annotations

from pprint import pformat
from typing import Any


def _header(spec: dict[str, Any], imports: str, class_body: str) -> str:
    entry = spec["entry"]
    return f'''# -*- coding: utf-8 -*-
"""Generated from .workflow/checker_specs/{spec["name"]}.yaml."""

{imports}

from ucagent.checkers.base import Checker


class {entry["class_name"]}(Checker):
    name = {spec["name"]!r}
    description = {spec.get("description", "")!r}
{class_body}
'''


def _path_helpers() -> str:
    return '''
    def _resolve(self):
        candidate = Path(self.path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"Unsafe checker path: {self.path}")
        root = Path(self.workspace or ".").resolve()
        target = (root / candidate).resolve()
        if target != root and not str(target).startswith(str(root) + "/"):
            raise ValueError(f"Unsafe checker path: {self.path}")
        return target
'''


def _render_json_required_keys(spec: dict[str, Any]) -> str:
    entry = spec["entry"]
    default_path = spec.get("register", {}).get("args", {}).get("path", "")
    body = f'''    required_keys = {pformat(spec["rules"]["required_keys"], width=100)}

    def __init__(self, path: str = {default_path!r}, required_keys=None, **kwargs):
        super().__init__()
        if not path:
            for key, value in kwargs.items():
                if key.endswith("_path") and isinstance(value, str):
                    path = value
                    break
        self.path = path
        self.required_keys = list(required_keys or self.required_keys)
        self.set_human_check_needed(kwargs.get("need_human_check", False))
{_path_helpers()}
    def {entry["method"]}(self, timeout=0, **kwargs):
        """Validate that the configured JSON result contains every required key."""
        try:
            target = self._resolve()
            if not target.is_file():
                return False, {{"error": "CHECKER-DATA-001: JSON result file not found", "path": self.path}}
            data = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return False, {{"error": "CHECKER-DATA-002: JSON top-level must be mapping", "path": self.path}}
            missing = [key for key in self.required_keys if key not in data]
            if missing:
                return False, {{"error": "CHECKER-DATA-003: JSON result is missing required keys", "path": self.path, "missing_keys": missing}}
            return True, {{"message": "JSON result contains all required keys", "path": self.path, "required_keys": self.required_keys}}
        except Exception as exc:
            return False, {{"error": f"CHECKER-DATA-999: {{exc}}", "path": self.path}}
'''
    return _header(spec, "import json\nfrom pathlib import Path", body)


def _render_json_numeric_range(spec: dict[str, Any]) -> str:
    entry = spec["entry"]
    rules = spec["rules"]
    default_path = spec.get("register", {}).get("args", {}).get("path", "")
    body = f'''    field = {rules["field"]!r}
    minimum = {rules["minimum"]!r}
    maximum = {rules["maximum"]!r}

    def __init__(self, path: str = {default_path!r}, field=None, minimum=None, maximum=None, **kwargs):
        super().__init__()
        if not path:
            for key, value in kwargs.items():
                if key.endswith("_path") and isinstance(value, str):
                    path = value
                    break
        self.path = path
        self.field = field or self.field
        self.minimum = self.minimum if minimum is None else minimum
        self.maximum = self.maximum if maximum is None else maximum
        self.set_human_check_needed(kwargs.get("need_human_check", False))
{_path_helpers()}
    def {entry["method"]}(self, timeout=0, **kwargs):
        """Validate that a JSON numeric field is within the configured inclusive range."""
        try:
            target = self._resolve()
            data = json.loads(target.read_text(encoding="utf-8"))
            value = data.get(self.field) if isinstance(data, dict) else None
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False, {{"error": "CHECKER-RANGE-001: field is not numeric", "field": self.field, "value": value}}
            passed = self.minimum <= value <= self.maximum
            return passed, {{"message": "numeric range check completed", "field": self.field, "value": value, "minimum": self.minimum, "maximum": self.maximum}}
        except Exception as exc:
            return False, {{"error": f"CHECKER-RANGE-999: {{exc}}", "path": self.path}}
'''
    return _header(spec, "import json\nfrom pathlib import Path", body)


def _render_file_exists(spec: dict[str, Any]) -> str:
    entry = spec["entry"]
    default_path = spec.get("register", {}).get("args", {}).get("path", "")
    body = f'''
    def __init__(self, path: str = {default_path!r}, **kwargs):
        super().__init__()
        if not path:
            for key, value in kwargs.items():
                if key.endswith("_path") and isinstance(value, str):
                    path = value
                    break
        self.path = path
        self.set_human_check_needed(kwargs.get("need_human_check", False))
{_path_helpers()}
    def {entry["method"]}(self, timeout=0, **kwargs):
        """Validate that the configured workflow-relative file exists."""
        try:
            target = self._resolve()
            return target.is_file(), {{"message": "file existence check completed", "path": self.path, "exists": target.is_file()}}
        except Exception as exc:
            return False, {{"error": f"CHECKER-FILE-999: {{exc}}", "path": self.path}}
'''
    return _header(spec, "from pathlib import Path", body)


def _render_command_exit_code(spec: dict[str, Any]) -> str:
    entry = spec["entry"]
    rules = spec["rules"]
    default_args = spec.get("register", {}).get("args", {})
    body = f'''    allowed_commands = {pformat(rules["allowed_commands"], width=100)}
    expected_exit_code = {rules.get("expected_exit_code", 0)!r}

    def __init__(self, command=None, expected_exit_code=None, **kwargs):
        super().__init__()
        self.command = list(command or {default_args.get("command", [])!r})
        self.expected_exit_code = self.expected_exit_code if expected_exit_code is None else expected_exit_code
        self.set_human_check_needed(kwargs.get("need_human_check", False))

    def {entry["method"]}(self, timeout=30, **kwargs):
        """Run an allowlisted command and validate its exit code."""
        try:
            if not self.command or self.command[0] not in self.allowed_commands:
                return False, {{"error": "CHECKER-CMD-001: command is not allowlisted", "command": self.command}}
            proc = subprocess.run(self.command, cwd=str(Path(self.workspace or ".").resolve()), text=True, capture_output=True, timeout=timeout or 30)
            passed = proc.returncode == self.expected_exit_code
            return passed, {{"message": "command exit-code check completed", "command": self.command, "returncode": proc.returncode, "expected_exit_code": self.expected_exit_code, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}}
        except Exception as exc:
            return False, {{"error": f"CHECKER-CMD-999: {{exc}}", "command": self.command}}
'''
    return _header(spec, "import subprocess\nfrom pathlib import Path", body)


def render_checker_from_spec(spec: dict[str, Any]) -> str:
    renderers = {
        "json_required_keys": _render_json_required_keys,
        "json_numeric_range": _render_json_numeric_range,
        "file_exists": _render_file_exists,
        "command_exit_code": _render_command_exit_code,
    }
    return renderers[spec["rules"]["type"]](spec)
