#coding=utf-8

"""Agent backend package."""

from .base import AgentBackendBase
from .cmdline import UCAgentCmdLineBackend
from ucagent.util.config import Config


def get_backend(vagent, cfg: Config) -> AgentBackendBase:
    """
    Get the agent backend instance.

    :return: The AgentBackendBase instance.
    """
    backend_conf = cfg.backend.get_value(cfg.backend.key_name, None)
    if backend_conf is None:
        raise ValueError(f"Backend configuration for '{cfg.backend.key_name}' not found.")
    backend_conf = backend_conf.as_dict()
    backend_clss = backend_conf.get("clss", "ucagent.abackend.langchain.UCAgentLangChainBackend")
    backend_args = backend_conf.get("args", {})
    from importlib import import_module
    module_name, class_name = backend_clss.rsplit(".", 1)
    module = import_module(module_name)
    backend_clss = getattr(module, class_name)
    backend_instance = backend_clss(vagent, cfg, **backend_args)
    return backend_instance
