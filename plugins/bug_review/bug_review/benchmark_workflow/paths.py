"""Resolve Bug Review resources identically in source checkouts and wheels."""
from pathlib import Path


def source_root():
    """Return the plugin checkout root when a source descriptor is present."""
    root = Path(__file__).resolve().parents[2]
    return root if (root / "ucagent-plugin.toml").is_file() else None


def repository_root():
    """Return the checkout runtime root, or the installed caller directory."""
    return source_root() or Path.cwd()


def default_configs():
    """Return the reference configuration shipped inside the Python package."""
    return Path(__file__).resolve().parents[1] / "configs"


def resources_root():
    """Return replay and conversion helpers independent of optional skills."""
    return Path(__file__).resolve().parents[1] / "resources"
