"""JSON-safe report values, hashing, redaction, and actionable diagnostics."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import math


def _sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest for one file."""

    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _diagnostic(
    stage: str,
    error_code: str,
    error: str,
    next_action: str,
    **details: Any,
) -> dict[str, Any]:
    """Build one bounded, task-oriented diagnostic mapping."""

    result = {
        "stage": stage,
        "error_code": error_code,
        "error": error,
        "next_action": next_action,
    }
    result.update({key: value for key, value in details.items() if value is not None})
    return result


def _json_safe(value: Any) -> Any:
    """Recursively replace non-finite floats with JSON null."""

    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _redact_private_paths(value: Any, paths: tuple[Path, ...]) -> Any:
    """Remove trusted workflow source identities from a report tree."""

    if isinstance(value, dict):
        return {key: _redact_private_paths(item, paths) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_private_paths(item, paths) for item in value]
    if isinstance(value, str):
        redacted = value
        for path in sorted(paths, key=lambda item: len(str(item)), reverse=True):
            for token in {
                str(path),
                path.as_posix(),
                str(path.parent),
                path.parent.as_posix(),
                path.name,
            }:
                if token:
                    redacted = redacted.replace(token, "<internal-analysis-source>")
        return redacted
    return value


def _tail(text: str, limit: int = 4000) -> str:
    """Return a bounded subprocess log excerpt favoring the final diagnostics."""

    if len(text) <= limit:
        return text
    return f"... [truncated {len(text) - limit} characters]\n{text[-limit:]}"
