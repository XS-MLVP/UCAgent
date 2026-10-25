"""Waveform format priorities and extensible, lazily opened reader factories."""

from contextlib import AbstractContextManager
from functools import partial
import locale
from pathlib import Path
import re
from threading import RLock
from typing import Any, Callable


DEFAULT_WAVEFORM_ANALYSIS_FORMAT_PRIORITY = ("fst", "vcd", "fsdb")
WaveformReaderFactory = Callable[[str], AbstractContextManager[Any]]
_FORMAT_NAME = re.compile(r"[a-z][a-z0-9_]*")
_READER_INIT_LOCK = RLock()


def validate_waveform_analysis_format_priority(value: Any) -> list[str]:
    """Validate an ordered, nonempty list of distinct canonical format names."""
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("waveform_analysis_format_priority must be a nonempty list of format names")
    if any(not isinstance(item, str) or _FORMAT_NAME.fullmatch(item) is None for item in value):
        raise ValueError("waveform_analysis_format_priority entries must be lowercase extensions without dots")
    if len(value) != len(set(value)):
        raise ValueError("waveform_analysis_format_priority must not contain duplicate formats")
    return list(value)


def _open_wavekit_reader(path: str, reader_name: str) -> AbstractContextManager[Any]:
    """Load native readers without retaining their process-wide locale changes."""
    with _READER_INIT_LOCK:
        previous_locale = locale.setlocale(locale.LC_ALL)
        try:
            import wavekit

            return getattr(wavekit, reader_name)(path)
        finally:
            locale.setlocale(locale.LC_ALL, previous_locale)


_READERS: dict[str, WaveformReaderFactory] = {}


def register_waveform_reader(format_name: str, factory: WaveformReaderFactory) -> None:
    """Register an extension and context-managed wavekit-compatible reader.

    Built-in formats register during module initialization. Register extensions
    once during application/plugin initialization, before constructing WaveInfo,
    and include them in its configured format priority.
    Existing registrations cannot be overwritten.
    """
    validate_waveform_analysis_format_priority([format_name])
    if not callable(factory):
        raise TypeError("waveform reader factory must be callable")
    if format_name in _READERS:
        raise ValueError(f"A waveform reader is already registered for '{format_name}'")
    _READERS[format_name] = factory


register_waveform_reader("fst", partial(_open_wavekit_reader, reader_name="FstReader"))
register_waveform_reader("vcd", partial(_open_wavekit_reader, reader_name="VcdReader"))
register_waveform_reader("fsdb", partial(_open_wavekit_reader, reader_name="FsdbReader"))


def registered_waveform_formats() -> tuple[str, ...]:
    """Return the extensions available to waveform discovery and reader dispatch."""
    return tuple(_READERS)


def open_waveform_reader(path: str | Path) -> AbstractContextManager[Any]:
    """Open exactly the selected format without substituting another waveform."""
    format_name = Path(path).suffix.lower().lstrip(".")
    if format_name not in _READERS:
        raise ValueError(
            f"No waveform reader is registered for '{format_name}'. "
            f"Registered formats: {', '.join(_READERS)}"
        )
    return _READERS[format_name](str(path))
