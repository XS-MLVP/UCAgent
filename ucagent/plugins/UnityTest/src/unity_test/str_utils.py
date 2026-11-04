# -*- coding: utf-8 -*-
"""Shared string and list display helpers for bounded plugin diagnostics."""


def list_str_abbr(data: list, max_items=50, show_counts=False):
    """Abbreviate a list and optionally report total, shown, and remaining counts."""
    if not isinstance(data, list):
        return str(data)
    if show_counts:
        total = len(data)
        if total <= max_items:
            return f"Total: {total}. Details: {', '.join(str(item) for item in data)}."
        remaining = total - max_items
        shown = ", ".join(str(item) for item in data[:max_items])
        return (
            f"Total: {total}. First {max_items}: {shown}. "
            f"Remaining: {remaining} not shown."
        )
    subfix = ", ..."
    if len(data) <= max_items:
        subfix = ""
    return ", ".join([str(d) for d in data[:max_items]]) + subfix
