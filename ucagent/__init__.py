"""Public Python API for UCAgent verification tasks."""

from .version import __author__, __description__, __email__, __version__, banner, SOURCE_TREE_RUNTIME

__all__ = ["VerifyAgent", "__version__", "__author__", "__email__", "__description__", "banner", "SOURCE_TREE_RUNTIME"]


def __getattr__(name):
    """Load the public Agent class only when requested, keeping control-only imports independent."""
    if name != "VerifyAgent":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .core.agent.execution import VerifyAgent
    globals()[name] = VerifyAgent
    return VerifyAgent
