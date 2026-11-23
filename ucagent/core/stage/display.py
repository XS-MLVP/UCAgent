"""Human-readable projections of Check and Complete diagnostics."""

from __future__ import annotations

from typing import Any

import yaml


_MAX_TEXT = 1600
_FAILURE_FIELDS = (
    ("error_code", "Code"),
    ("error", "Error"),
    ("next_action", "Next"),
    ("observed", "Observed"),
    ("expected", "Expected"),
    ("artifact", "Artifact"),
    ("location", "Location"),
)
_CONTEXT_FIELDS = (
    ("stage_index", "Stage index"),
    ("stage_name", "Stage"),
    ("status", "Status"),
    ("error_code", "Code"),
    ("error", "Error"),
    ("next_action", "Next"),
    ("observed", "Observed"),
    ("expected", "Expected"),
    ("artifact", "Artifact"),
    ("location", "Location"),
    ("message", "Message"),
)
_NESTED_FIELDS = (
    ("missing", "Missing"),
    ("invalid", "Invalid"),
    ("files", "Files"),
    ("verified_files", "Verified files"),
    ("errors", "Errors"),
    ("items", "Items"),
    ("path", "Path"),
    ("problem", "Problem"),
    ("reason", "Reason"),
)


def _clip(value: Any) -> str:
    """Keep one display field bounded without exposing unrelated dictionary keys."""
    text = str(value).strip()
    if len(text) > _MAX_TEXT:
        return text[:_MAX_TEXT].rstrip() + "\n... (truncated)"
    return text


def _parse(value: Any) -> Any:
    """Parse the YAML/JSON tool payload while retaining plain text diagnostics."""
    if isinstance(value, dict) or value is None:
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError:
        return text
    return parsed if isinstance(parsed, dict) else text


def _readable_value(value: Any, depth: int = 0, *, include_mapping: bool = False) -> str:
    """Extract bounded, human-readable context from checker diagnostics."""
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, str):
        return _clip(value)
    if isinstance(value, (int, float, bool)):
        return str(value)
    if depth >= 3:
        return ""
    if isinstance(value, list):
        parts = [_readable_value(item, depth + 1) for item in value[:3]]
        return " | ".join(part for part in parts if part)
    if not isinstance(value, dict):
        return _clip(value)

    parts = []
    for key, label in _CONTEXT_FIELDS:
        if key not in value:
            continue
        rendered = _readable_value(value[key], depth + 1)
        if rendered:
            parts.append(f"{label}: {rendered}")
    for key, label in _NESTED_FIELDS:
        if key not in value:
            continue
        rendered = _readable_value(value[key], depth + 1, include_mapping=True)
        if rendered:
            parts.append(f"{label}: {rendered}")
    for key in ("last_msg", "diagnostic", "details"):
        if key not in value:
            continue
        rendered = _readable_value(value[key], depth + 1)
        if rendered and all(rendered not in part for part in parts):
            parts.append(rendered)
    if include_mapping and not parts:
        items = list(value.items())
        for key, item in items[:3]:
            rendered = _readable_value(item, depth + 1, include_mapping=True)
            if rendered:
                parts.append(f"{key}: {rendered}")
        if len(items) > 3:
            parts.append(f"... (+{len(items) - 3})")
    return " | ".join(parts)


def format_check_result(value: Any, sender: str | None = None, *, tool: str = "Check") -> str:
    """Render only actionable Check context instead of serializing the full result."""
    info = _parse(value)
    prefix = f"[{tool}] {sender}" if sender else tool
    if not isinstance(info, dict):
        return f"{prefix} | RESULT\n{_clip(info)}" if info else f"{prefix} | no result"
    nested = info.get("last_check_result")
    if isinstance(nested, dict) and "check_pass" not in info:
        info = nested

    passed = info.get("check_pass")
    if passed is None and "complete" in info:
        passed = info.get("complete")
    status = "PASS" if passed is True else "FAIL" if passed is False else "RESULT"
    lines = [f"{prefix} | {status}"]

    failure = info.get("failure_summary")
    progress = info.get("progress_summary")
    scope = failure if isinstance(failure, dict) else progress if isinstance(progress, dict) else None
    if isinstance(scope, dict):
        stage_index = scope.get("stage_index")
        stage_name = scope.get("stage_name")
        if stage_index is not None or stage_name:
            label = f"Stage {stage_index}" if stage_index is not None else "Stage"
            lines.append(f"{label}: {stage_name}" if stage_name else label)

    message = info.get("message")
    if isinstance(message, str) and message.strip():
        lines.append(_clip(message))

    next_action = None
    if isinstance(failure, dict):
        for key, label in _FAILURE_FIELDS:
            rendered = _readable_value(failure.get(key))
            if not rendered:
                continue
            lines.append(f"{label}: {rendered}")
            if key == "next_action":
                next_action = rendered
        remaining = failure.get("remaining_validation_gates_not_run")
        if remaining:
            lines.append(f"Remaining gates: {remaining}")

    if isinstance(progress, dict):
        progress_status = progress.get("status")
        if progress_status:
            lines.append(f"Progress: {_clip(progress_status)}")
        detail = _readable_value(progress.get("progress"))
        if detail:
            lines.append(f"Current work: {detail}")
        progress_next = _readable_value(progress.get("next_action"))
        if progress_next and progress_next != next_action:
            lines.append(f"Next: {progress_next}")
        remaining = progress.get("remaining_validation_gates_not_run")
        if remaining:
            lines.append(f"Remaining gates: {remaining}")

    action = info.get("action")
    if isinstance(action, str) and action.strip() and action.strip() != next_action:
        lines.append(f"Next: {_clip(action)}")

    if not isinstance(failure, dict) and not isinstance(progress, dict):
        context = _readable_value(info.get("check_info"))
        if context:
            lines.append(f"Context: {context}")
    return "\n".join(lines)
