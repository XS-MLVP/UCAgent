"""Read structured Bug Review workspace artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path


def read_object(path: str | Path) -> dict:
    """Read one UTF-8 JSON file and require an object at its top level."""
    with Path(path).open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def atomic_write_json(path: Path, value: object) -> None:
    """Write one JSON document through a temporary file so readers never see a partial write."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(str(temporary), str(path))
