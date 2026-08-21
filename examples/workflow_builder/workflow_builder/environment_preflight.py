# -*- coding: utf-8 -*-
"""Portable environment diagnostics for generated workflows."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


PROXY_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "OPENAI_PROXY",
    "NO_PROXY",
    "no_proxy",
)


def _proxy_issue(name: str, value: str) -> str | None:
    if name.rsplit(":", 1)[-1].lower() == "no_proxy" or not value:
        return None
    parsed = urlsplit(value)
    if parsed.username is not None or parsed.password is not None:
        return f"{name} contains credentials and must not be persisted or reported"
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        return f"{name} uses unsupported proxy scheme {scheme or '<missing>'}"
    return None


def _display_proxy(name: str, value: str) -> str:
    if name.rsplit(":", 1)[-1].lower() == "no_proxy":
        return value
    parsed = urlsplit(value)
    if parsed.username is not None or parsed.password is not None:
        return f"{parsed.scheme or 'proxy'}://<credentials-redacted>@{parsed.hostname or '<host>'}"
    return value


def _tmux_proxy_environment() -> dict[str, str]:
    if shutil.which("tmux") is None:
        return {}
    process = subprocess.run(
        ["tmux", "show-environment", "-g"],
        text=True,
        capture_output=True,
        timeout=5,
    )
    if process.returncode != 0:
        return {}
    values: dict[str, str] = {}
    for line in process.stdout.splitlines():
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name in PROXY_KEYS:
            values[name] = value
    return values


def inspect_environment(root: Path, include_tmux: bool = True) -> dict[str, Any]:
    required = (
        "setup.py",
        "config/environment.schema.yaml",
        "Makefile",
        "ucagent_setup.sh",
    )
    missing = [path for path in required if not (root / path).is_file()]
    process_proxy_values = {
        name: os.environ[name] for name in PROXY_KEYS if os.environ.get(name)
    }
    tmux_proxy_values = _tmux_proxy_environment() if include_tmux else {}
    proxy_issues = [
        issue
        for source, values in (
            ("process", process_proxy_values),
            ("tmux_global", tmux_proxy_values),
        )
        for name, value in values.items()
        if (issue := _proxy_issue(f"{source}:{name}", value))
    ]
    process_proxies = {
        name: _display_proxy(name, value)
        for name, value in process_proxy_values.items()
    }
    tmux_proxies = {
        name: _display_proxy(name, value)
        for name, value in tmux_proxy_values.items()
    }
    ucagent_home = Path(os.environ.get("UCAGENT_HOME", "")).expanduser()
    ucagent_venv = Path(os.environ.get("UCAGENT_VENV", "")).expanduser()
    warnings = []
    if not os.environ.get("UCAGENT_HOME"):
        warnings.append("UCAGENT_HOME is not set in the current process")
    elif not ucagent_home.is_dir():
        warnings.append(f"UCAGENT_HOME does not exist: {ucagent_home}")
    if not os.environ.get("UCAGENT_VENV"):
        warnings.append("UCAGENT_VENV is not set in the current process")
    elif not (ucagent_venv / "bin/python").is_file():
        warnings.append(f"UCAGENT_VENV/bin/python does not exist: {ucagent_venv}")
    return {
        "ok": not missing and not proxy_issues,
        "workflow_root": str(root),
        "missing_workflow_files": missing,
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "ucagent_home": str(ucagent_home) if os.environ.get("UCAGENT_HOME") else "",
        "ucagent_venv": str(ucagent_venv) if os.environ.get("UCAGENT_VENV") else "",
        "process_proxy_environment": process_proxies,
        "tmux_global_proxy_environment": tmux_proxies,
        "proxy_issues": proxy_issues,
        "warnings": warnings,
        "diagnostic_sources": [
            "current process environment",
            "tmux global environment" if include_tmux else "tmux inspection disabled",
        ],
    }
