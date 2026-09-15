#!/usr/bin/env python3
"""Configure machine-local defaults for Workflow Builder."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
LOCAL_DIR = ROOT / ".workflow_builder"
LOCAL_CONFIG = LOCAL_DIR / "local.mk"

SETTING_ORDER = (
    "UCAGENT_HOME",
    "UCAGENT_VENV",
    "PYTHON",
    "WS",
    "EVAL_UI_HOST",
    "EVAL_UI_PORT",
    "MCP_SERVER_HOST",
    "MCP_SERVER_PORT",
    "WORKFLOW_BUILDER_PROXY_ENABLED",
    "HTTP_PROXY",
    "HTTPS_PROXY",
)


def defaults() -> dict[str, str]:
    ucagent_home = Path(os.environ.get("UCAGENT_HOME", "~/FDocB/UCAgent")).expanduser()
    ucagent_venv = Path(
        os.environ.get("UCAGENT_VENV", str(ucagent_home / ".venv"))
    ).expanduser()
    return {
        "UCAGENT_HOME": str(ucagent_home),
        "UCAGENT_VENV": str(ucagent_venv),
        "PYTHON": os.environ.get("PYTHON", str(ucagent_venv / "bin/python")),
        "WS": os.environ.get("WS", str(ROOT / "workspace")),
        "EVAL_UI_HOST": os.environ.get("EVAL_UI_HOST", "127.0.0.1"),
        "EVAL_UI_PORT": os.environ.get("EVAL_UI_PORT", "8765"),
        "MCP_SERVER_HOST": os.environ.get("MCP_SERVER_HOST", "127.0.0.1"),
        "MCP_SERVER_PORT": os.environ.get("MCP_SERVER_PORT", "5000"),
        "WORKFLOW_BUILDER_PROXY_ENABLED": os.environ.get(
            "WORKFLOW_BUILDER_PROXY_ENABLED", "0"
        ),
        "HTTP_PROXY": os.environ.get("HTTP_PROXY", os.environ.get("http_proxy", "")),
        "HTTPS_PROXY": os.environ.get(
            "HTTPS_PROXY", os.environ.get("https_proxy", "")
        ),
    }


def _unescape_make(value: str) -> str:
    return value.replace("$$", "$").replace(r"\#", "#")


def load_local(path: Path | None = None) -> dict[str, str]:
    path = path or LOCAL_CONFIG
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    assignment = re.compile(r"^([A-Z][A-Z0-9_]*)\s*:=\s*(.*)$")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = assignment.match(line.strip())
        if match and match.group(1) in SETTING_ORDER:
            result[match.group(1)] = _unescape_make(match.group(2))
    return result


def parse_bool(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return "1"
    if normalized in {"0", "false", "no", "off"}:
        return "0"
    raise ValueError("WORKFLOW_BUILDER_PROXY_ENABLED must be 0/1, true/false, yes/no, or on/off")


def normalize(values: dict[str, str]) -> dict[str, str]:
    result = dict(values)
    for key in ("UCAGENT_HOME", "UCAGENT_VENV", "WS"):
        result[key] = str(Path(os.path.expandvars(result[key])).expanduser().resolve())
    python_value = os.path.expandvars(result["PYTHON"])
    if "/" in python_value:
        python_value = str(Path(python_value).expanduser().resolve())
    result["PYTHON"] = python_value
    result["WORKFLOW_BUILDER_PROXY_ENABLED"] = parse_bool(
        result["WORKFLOW_BUILDER_PROXY_ENABLED"]
    )
    for key, value in result.items():
        if any(char in value for char in ("\n", "\r", "\x00")):
            raise ValueError(f"{key} contains a forbidden control character")
    return result


def validate(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    ucagent_home = Path(values["UCAGENT_HOME"])
    ucagent_venv = Path(values["UCAGENT_VENV"])
    if not ucagent_home.is_dir():
        errors.append(f"UCAGENT_HOME is not a directory: {ucagent_home}")
    elif not (ucagent_home / "ucagent.py").is_file():
        errors.append(f"UCAGENT_HOME does not contain ucagent.py: {ucagent_home}")
    if not ucagent_venv.is_dir():
        errors.append(f"UCAGENT_VENV is not a directory: {ucagent_venv}")
    python_value = values["PYTHON"]
    python_path = Path(python_value)
    if not (python_path.is_file() and os.access(python_path, os.X_OK)) and not shutil.which(
        python_value
    ):
        errors.append(f"PYTHON is not executable: {python_value}")
    for key in ("EVAL_UI_HOST", "MCP_SERVER_HOST"):
        if not values[key].strip() or any(char.isspace() for char in values[key]):
            errors.append(f"{key} must be a non-empty host without whitespace")
    for key in ("EVAL_UI_PORT", "MCP_SERVER_PORT"):
        try:
            port = int(values[key])
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            errors.append(f"{key} must be an integer from 1 to 65535")
    if values["WORKFLOW_BUILDER_PROXY_ENABLED"] == "1":
        if not values["HTTP_PROXY"]:
            errors.append("HTTP_PROXY is required when proxy support is enabled")
        for key in ("HTTP_PROXY", "HTTPS_PROXY"):
            value = values[key]
            if not value:
                continue
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errors.append(f"{key} must be an http:// or https:// URL")
            if parsed.username is not None or parsed.password is not None:
                errors.append(f"{key} must not contain credentials; export secrets at runtime")
    return errors


def _escape_make(value: str) -> str:
    return value.replace("$", "$$").replace("#", r"\#")


def render(values: dict[str, str]) -> str:
    lines = [
        "# Generated by workflow_builder/setup.py. Do not commit this file.",
        "# Re-run `python setup.py` to update these machine-local defaults.",
    ]
    for key in SETTING_ORDER:
        lines.append(f"{key} := {_escape_make(values[key])}")
    lines.extend(
        [
            "",
            "ifeq ($(WORKFLOW_BUILDER_PROXY_ENABLED),1)",
            "export http_proxy := $(HTTP_PROXY)",
            "export https_proxy := $(HTTPS_PROXY)",
            "export HTTP_PROXY := $(HTTP_PROXY)",
            "export HTTPS_PROXY := $(HTTPS_PROXY)",
            "unexport all_proxy",
            "unexport ALL_PROXY",
            "else",
            "unexport http_proxy",
            "unexport https_proxy",
            "unexport HTTP_PROXY",
            "unexport HTTPS_PROXY",
            "unexport all_proxy",
            "unexport ALL_PROXY",
            "endif",
            "",
        ]
    )
    return "\n".join(lines)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix="local.", suffix=".mk", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_assignments(items: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--set expects KEY=VALUE, got: {item}")
        key, value = item.split("=", 1)
        key = key.strip().upper()
        if key not in SETTING_ORDER:
            raise ValueError(f"unknown setting {key}; valid names: {', '.join(SETTING_ORDER)}")
        result[key] = value.strip()
    return result


def prompt(values: dict[str, str]) -> dict[str, str]:
    updated = dict(values)
    print("Workflow Builder machine-local configuration. Press Enter to keep a value.")
    for key in SETTING_ORDER:
        current = updated[key]
        shown = current if current else "<empty>"
        answer = input(f"{key} [{shown}]: ").strip()
        if answer:
            updated[key] = answer
    return updated


def show(values: dict[str, str], *, source: str) -> None:
    print(f"Configuration source: {source}")
    for key in SETTING_ORDER:
        print(f"{key}={values[key]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Configure machine-local defaults for Workflow Builder."
    )
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--show", action="store_true", help="show effective settings")
    parser.add_argument("--check", action="store_true", help="validate without writing")
    parser.add_argument("--dry-run", action="store_true", help="show the file without writing")
    parser.add_argument("--non-interactive", action="store_true")
    args = parser.parse_args(argv)

    try:
        values = defaults()
        values.update(load_local())
        values.update(parse_assignments(args.set))
        if not args.non_interactive and not args.check and not args.show and not args.dry_run:
            values = prompt(values)
        values = normalize(values)
    except (OSError, ValueError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    errors = validate(values)
    if errors:
        for error in errors:
            print(f"[FAIL] {error}", file=sys.stderr)
        return 2

    if args.show or args.check:
        show(values, source=str(LOCAL_CONFIG) if LOCAL_CONFIG.is_file() else "defaults/environment")
    if args.show:
        return 0
    if args.check:
        print("[PASS] Workflow Builder environment is valid")
        return 0

    content = render(values)
    if args.dry_run:
        print(content, end="")
        return 0
    atomic_write(LOCAL_CONFIG, content)
    print(f"[PASS] wrote machine-local configuration: {LOCAL_CONFIG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
