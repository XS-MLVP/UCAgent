# -*- coding: utf-8 -*-
"""Stable semantic section contract for generated GuideDoc documents."""

from __future__ import annotations

from typing import Any


REQUIRED_SECTION_IDS = (
    "purpose",
    "inputs",
    "outputs",
    "usage",
    "execution",
    "checks",
    "failure_recovery",
)

LEGACY_HEADING_IDS = {
    "Purpose": "purpose",
    "目的": "purpose",
    "工作流目标": "purpose",
    "Inputs": "inputs",
    "输入": "inputs",
    "Outputs": "outputs",
    "输出": "outputs",
    "Usage": "usage",
    "使用方法": "usage",
    "运行方式": "usage",
    "Execution": "execution",
    "执行步骤": "execution",
    "执行": "execution",
    "Checks": "checks",
    "检查": "checks",
    "检查方法": "checks",
    "Failure Recovery": "failure_recovery",
    "失败恢复": "failure_recovery",
    "异常处理": "failure_recovery",
}

REQUIRED_OPERATION_MARKERS = {
    "inputs": ("input/<TARGET>/", "input/example"),
    "outputs": ("output/",),
    "usage": (
        "TARGET",
        "input/<TARGET>/",
        "input/example",
        "output/",
        "make check_example",
        "make run",
    ),
}


def section_id(section: dict[str, Any]) -> str:
    """Return an explicit semantic id or a backward-compatible heading mapping."""
    value = section.get("id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    heading = section.get("heading")
    return LEGACY_HEADING_IDS.get(heading, "") if isinstance(heading, str) else ""
