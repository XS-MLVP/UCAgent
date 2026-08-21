#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import base64
import binascii
import json
from collections import OrderedDict
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import Any, Mapping


WAVEFORM_VIEWER_VERSION = 2
WAVEFORM_VIEWER_SUPPORTED_VERSIONS = frozenset({1, WAVEFORM_VIEWER_VERSION})
WAVEFORM_VIEWER_ROUTE = "/surfer/"
WAVEFORM_VIEWER_MARKER = "<WAVEFORM-VIEWER>"
WAVEFORM_VIEWER_MAX_SIGNALS = 64
WAVEFORM_VIEWER_EXTENSIONS = frozenset({".vcd", ".fst"})

_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]+")
_DECIMAL_RE = re.compile(r"0|[1-9][0-9]*")
_LINK_RE = re.compile(
    rf"{re.escape(WAVEFORM_VIEWER_MARKER)}[ \t]+\[[^\]\r\n]+\]"
    rf"\({re.escape(WAVEFORM_VIEWER_ROUTE)}\?wave=([A-Za-z0-9_-]+)\)"
)
_COMMON_KEYS = frozenset({"v", "start", "end", "cursor", "signals"})
_V1_KEYS = _COMMON_KEYS | {"file"}
_V2_KEYS = _COMMON_KEYS | {"test_dir", "test_case"}
_SESSION_RE = re.compile(r"toffee_tmp_(\d{14})_(\d{3,6})")


class WaveformViewerProtocolError(ValueError):
    """Raised when a waveform-viewer payload or link violates the protocol."""


def normalize_waveform_file(value: Any) -> str:
    """Return a safe, canonical workspace-relative waveform path."""

    if not isinstance(value, str) or not value:
        raise WaveformViewerProtocolError("file must be a non-empty string")
    if "\\" in value:
        raise WaveformViewerProtocolError("file must use '/' separators")
    if any(ord(character) < 32 for character in value):
        raise WaveformViewerProtocolError("file must not contain control characters")
    if "://" in value or "?" in value or "#" in value:
        raise WaveformViewerProtocolError("file must not be a URL")

    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    parts = value.split("/")
    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise WaveformViewerProtocolError("file must be workspace-relative")
    if any(part in {"", ".", ".."} for part in parts):
        raise WaveformViewerProtocolError(
            "file must not contain empty, '.' or '..' path segments"
        )
    if posix_path.suffix.lower() not in WAVEFORM_VIEWER_EXTENSIONS:
        raise WaveformViewerProtocolError("file must end in .vcd or .fst")
    return value


def normalize_waveform_test_dir(value: Any) -> str:
    """Return a safe workspace-relative test directory for logical v2 links."""

    if not isinstance(value, str) or not value:
        raise WaveformViewerProtocolError("test_dir must be a non-empty string")
    if "\\" in value:
        raise WaveformViewerProtocolError("test_dir must use '/' separators")
    if any(ord(character) < 32 for character in value):
        raise WaveformViewerProtocolError("test_dir must not contain control characters")
    if "://" in value or "?" in value or "#" in value:
        raise WaveformViewerProtocolError("test_dir must not be a URL")
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if value == ".":
        return value
    parts = value.split("/")
    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise WaveformViewerProtocolError("test_dir must be workspace-relative")
    if any(part in {"", ".", ".."} for part in parts):
        raise WaveformViewerProtocolError(
            "test_dir must not contain empty, '.' or '..' path segments"
        )
    return value


def normalize_waveform_test_case(value: Any) -> str:
    """Validate the exact waveform basename used by UnityChip test output."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise WaveformViewerProtocolError(
            "test_case must be a non-empty canonical string"
        )
    if any(ord(character) < 32 for character in value):
        raise WaveformViewerProtocolError("test_case must not contain control characters")
    if "/" in value or "\\" in value or "::" in value:
        raise WaveformViewerProtocolError(
            "test_case must be an exact function basename, not a path or node ID"
        )
    if value.lower().endswith((".vcd", ".fst", ".dat")):
        raise WaveformViewerProtocolError(
            "test_case must not include a waveform file extension"
        )
    return value


def _normalize_decimal(name: str, value: Any) -> str:
    if not isinstance(value, str) or _DECIMAL_RE.fullmatch(value) is None:
        raise WaveformViewerProtocolError(
            f"{name} must be a canonical non-negative decimal string"
        )
    return value


def normalize_waveform_viewer_payload(payload: Mapping[str, Any]) -> OrderedDict:
    """Validate and return one deterministic waveform-viewer payload."""

    if not isinstance(payload, Mapping):
        raise WaveformViewerProtocolError("payload must be a JSON object")
    version = payload.get("v")
    if type(version) is not int or version not in WAVEFORM_VIEWER_SUPPORTED_VERSIONS:
        raise WaveformViewerProtocolError(
            f"unsupported waveform viewer protocol version: {version!r}"
        )
    allowed_keys = _V1_KEYS if version == 1 else _V2_KEYS
    unknown = set(payload) - allowed_keys
    if unknown:
        raise WaveformViewerProtocolError(
            f"payload contains unknown field(s): {', '.join(sorted(unknown))}"
        )
    normalized = OrderedDict([("v", version)])
    if version == 1:
        normalized["file"] = normalize_waveform_file(payload.get("file"))
    else:
        normalized["test_dir"] = normalize_waveform_test_dir(
            payload.get("test_dir")
        )
        normalized["test_case"] = normalize_waveform_test_case(
            payload.get("test_case")
        )
    time_keys = ("start", "end", "cursor")
    present_time_keys = [key for key in time_keys if key in payload]
    if present_time_keys and len(present_time_keys) != len(time_keys):
        raise WaveformViewerProtocolError(
            "start, end and cursor must either all be present or all be omitted"
        )
    if present_time_keys:
        for key in time_keys:
            normalized[key] = _normalize_decimal(key, payload[key])
        if not (
            int(normalized["start"])
            <= int(normalized["cursor"])
            <= int(normalized["end"])
        ):
            raise WaveformViewerProtocolError(
                "time range must satisfy start <= cursor <= end"
            )

    if "signals" in payload:
        raw_signals = payload["signals"]
        if not isinstance(raw_signals, list) or not raw_signals:
            raise WaveformViewerProtocolError("signals must be a non-empty JSON array")
        signals = []
        seen = set()
        for signal in raw_signals:
            if not isinstance(signal, str) or not signal.strip():
                raise WaveformViewerProtocolError(
                    "each signal must be a non-empty string"
                )
            if signal not in seen:
                seen.add(signal)
                signals.append(signal)
        if len(signals) > WAVEFORM_VIEWER_MAX_SIGNALS:
            raise WaveformViewerProtocolError(
                f"signals must contain at most {WAVEFORM_VIEWER_MAX_SIGNALS} entries"
            )
        if not present_time_keys:
            raise WaveformViewerProtocolError(
                "signals require start, end and cursor"
            )
        normalized["signals"] = signals
    elif present_time_keys:
        raise WaveformViewerProtocolError(
            "an analysis window requires at least one signal"
        )
    return normalized


def resolve_latest_waveform_file(
    workspace: str | Path,
    test_dir: str,
    test_case: str,
) -> Path | None:
    """Resolve the newest matching FST/VCD by timestamp encoded in session names."""

    normalized_dir = normalize_waveform_test_dir(test_dir)
    normalized_case = normalize_waveform_test_case(test_case)
    workspace_path = Path(workspace).resolve()
    data_dir = (workspace_path / normalized_dir / "data").resolve()
    try:
        data_dir.relative_to(workspace_path)
    except ValueError as error:
        raise WaveformViewerProtocolError(
            "test_dir must resolve inside the current workspace"
        ) from error
    if not data_dir.is_dir():
        return None

    sessions = []
    for path in data_dir.rglob("toffee_tmp_*"):
        if not path.is_dir():
            continue
        match = _SESSION_RE.fullmatch(path.name)
        if match is None:
            continue
        stamp, fraction = match.groups()
        sessions.append((stamp, fraction.ljust(6, "0"), path.stat().st_mtime_ns, path))
    sessions.sort(key=lambda item: (item[0], item[1], item[2], str(item[3])), reverse=True)

    name_pattern = re.compile(
        rf"{re.escape(normalized_case)}(?P<suffix>\d*)\.(?P<format>fst|vcd)",
        flags=re.IGNORECASE,
    )
    for _stamp, _fraction, _mtime, session in sessions:
        matches = []
        for path in session.rglob("*"):
            if not path.is_file():
                continue
            match = name_pattern.fullmatch(path.name)
            if match is None:
                continue
            suffix = int(match.group("suffix") or 0)
            format_rank = 1 if match.group("format").lower() == "fst" else 0
            matches.append((format_rank, suffix, path.stat().st_mtime_ns, str(path), path))
        if matches:
            matches.sort(reverse=True)
            selected = matches[0][-1].resolve()
            try:
                selected.relative_to(workspace_path)
            except ValueError as error:
                raise WaveformViewerProtocolError(
                    "resolved waveform must remain inside the current workspace"
                ) from error
            return selected
    return None


def encode_waveform_viewer_payload(payload: Mapping[str, Any]) -> str:
    """Encode a validated payload as canonical unpadded Base64URL."""

    normalized = normalize_waveform_viewer_payload(payload)
    serialized = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(serialized).decode("ascii").rstrip("=")


def decode_waveform_viewer_token(token: str) -> OrderedDict:
    """Decode a canonical Base64URL token and validate its payload."""

    if not isinstance(token, str) or _TOKEN_RE.fullmatch(token) is None:
        raise WaveformViewerProtocolError(
            "wave token must be non-empty unpadded Base64URL"
        )
    try:
        raw = base64.b64decode(
            token + "=" * (-len(token) % 4),
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WaveformViewerProtocolError(
            f"wave token does not contain valid UTF-8 JSON: {error}"
        ) from error
    normalized = normalize_waveform_viewer_payload(payload)
    if encode_waveform_viewer_payload(normalized) != token:
        raise WaveformViewerProtocolError(
            "wave token is not in canonical Base64URL form"
        )
    return normalized


def build_waveform_viewer_url(payload: Mapping[str, Any]) -> str:
    """Build the same-origin relative Surfer URL for a payload."""

    return f"{WAVEFORM_VIEWER_ROUTE}?wave={encode_waveform_viewer_payload(payload)}"


def build_waveform_viewer_markdown_link(
    payload: Mapping[str, Any],
    *,
    label: str | None = None,
) -> str:
    """Build a tagged Markdown link; its visible label is not part of the protocol."""

    normalized = normalize_waveform_viewer_payload(payload)
    visible_label = label or (
        PurePosixPath(normalized["file"]).name
        if normalized["v"] == 1
        else normalized["test_case"]
    )
    visible_label = visible_label.replace("[", "(").replace("]", ")").strip()
    if not visible_label or "\n" in visible_label or "\r" in visible_label:
        raise WaveformViewerProtocolError("viewer link label must be non-empty and single-line")
    return (
        f"{WAVEFORM_VIEWER_MARKER} [{visible_label}]"
        f"({build_waveform_viewer_url(normalized)})"
    )


def parse_waveform_viewer_markdown_link(line: str) -> tuple[str, OrderedDict]:
    """Parse one canonical Bug-document viewer link line."""

    if not isinstance(line, str):
        raise WaveformViewerProtocolError("viewer link must be a string")
    match = _LINK_RE.fullmatch(line)
    if match is None:
        raise WaveformViewerProtocolError(
            "viewer link must use the <WAVEFORM-VIEWER> marker and "
            "/surfer/?wave=<token> route"
        )
    token = match.group(1)
    return token, decode_waveform_viewer_token(token)
