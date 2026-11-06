# -*- coding: utf-8 -*-
"""UCAgent server subpackage."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "ControlApiServer",
    "MasterApiServer",
    "MasterClient",
    "McpServer",
    "WebTerminalServer",
]

_EXPORTS = {
    "ControlApiServer": ".api_cmd",
    "MasterApiServer": ".api_master",
    "MasterClient": ".api_master",
    "McpServer": ".api_mcp",
    "WebTerminalServer": ".api_terminal",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
