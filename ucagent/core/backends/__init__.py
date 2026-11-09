#coding=utf-8

"""Agent backend package."""

from ucagent.core.backends.base import AgentBackendBase
from ucagent.core.backends.blank import BlankBackend
from ucagent.core.backends.cmdline import UCAgentCmdLineBackend
from ucagent.util.config import Config


def get_backend_class(cfg: Config) -> type[AgentBackendBase]:
    """Resolve the configured backend class without constructing a model client."""
    from importlib import import_module
    backend = cfg.backend.get_value(cfg.backend.key_name, None)
    if backend is None:
        raise ValueError(f"Backend configuration for '{cfg.backend.key_name}' not found.")
    path = backend.get_value("clss", "ucagent.core.backends.langchain.UCAgentLangChainBackend")
    module_name, class_name = path.rsplit(".", 1)
    backend_class = getattr(import_module(module_name), class_name)
    if not isinstance(backend_class, type) or not issubclass(backend_class, AgentBackendBase):
        raise TypeError(f"Backend class {path!r} must inherit AgentBackendBase.")
    return backend_class


def get_backend(vagent, cfg: Config) -> AgentBackendBase:
    """Construct the exact backend declared by the resolved configuration."""
    backend_class = get_backend_class(cfg)
    options = cfg.backend.get_value(cfg.backend.key_name).get_value("args", {})
    if isinstance(options, Config):
        options = options.as_dict()
    return backend_class(vagent, cfg, **options)
