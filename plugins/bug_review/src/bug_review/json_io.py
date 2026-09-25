"""Read structured Bug Review workspace artifacts."""

from __future__ import annotations

import json
from pathlib import Path


def read_object(path: str | Path) -> dict:
    """Read one UTF-8 JSON file and require an object at its top level."""
    with Path(path).open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value
