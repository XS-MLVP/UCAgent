"""Public Python API for the UCAgent framework."""

from .api import PUBLIC_API_NAMES, _EXPORTS
from .version import __author__, __description__, __email__, __version__, banner, SOURCE_TREE_RUNTIME

__all__ = [
    "VerifyAgent",
    "__version__",
    "__author__",
    "__email__",
    "__description__",
    "banner",
    "SOURCE_TREE_RUNTIME",
    *PUBLIC_API_NAMES,
]


def __getattr__(name):
    """Load public and registered framework symbols only when requested."""
    if name == "VerifyAgent":
        from .core.agent.execution import VerifyAgent
        globals()[name] = VerifyAgent
        return VerifyAgent
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .api import resolve
    try:
        value = resolve(name)
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    globals()[name] = value
    return value


def __dir__():
    """List documented root exports without advertising internal aliases."""
    return sorted(set(globals()) | set(__all__))
