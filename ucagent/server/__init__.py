# -*- coding: utf-8 -*-
"""UCAgent server subpackage."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "PdbCmdApiServer",
    "PdbMasterApiServer",
    "PdbMasterClient",
    "PdbMcpServer",
    "WebUISession",
    "run_web_ui_session",
]

_EXPORTS = {
    "PdbCmdApiServer": ".api_cmd",
    "PdbMasterApiServer": ".api_master",
    "PdbMasterClient": ".api_master",
    "PdbMcpServer": ".api_mcp",
    "WebUISession": ".web_ui_session",
    "run_web_ui_session": ".web_ui_session",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
