"""TUI style utilities."""

from pathlib import Path

STYLES_DIR = Path(__file__).parent
DEFAULT_CSS_PATH = STYLES_DIR / "default.tcss"

__all__ = ["STYLES_DIR", "DEFAULT_CSS_PATH"]
