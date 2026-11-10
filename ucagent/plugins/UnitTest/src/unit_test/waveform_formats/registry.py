"""Format/backend registration, ordered dependency fallback, and validation."""

from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, ExitStack, contextmanager
from pathlib import Path
import re
from typing import Any

from ucagent.util.log import log_msg
from .protocols import WaveformReader, WaveformReaderFactory


DEFAULT_WAVEFORM_ANALYSIS_FORMAT_PRIORITY = ("fst", "vcd", "fsdb")
DEFAULT_WAVEFORM_ANALYSIS_BACKEND_PRIORITY = {
    "fst": ["pywellen", "wavekit"],
    "vcd": ["pywellen", "wavekit"],
    "fsdb": ["wavekit"],
}
_FORMAT_NAME = re.compile(r"[a-z][a-z0-9_]*")
_READERS: dict[str, dict[str, WaveformReaderFactory]] = {}


def validate_waveform_analysis_format_priority(value: Any) -> list[str]:
    """Validate an ordered, nonempty list of distinct canonical format names."""
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("waveform_analysis_format_priority must be a nonempty list of format names")
    if any(not isinstance(item, str) or _FORMAT_NAME.fullmatch(item) is None for item in value):
        raise ValueError("waveform_analysis_format_priority entries must be lowercase extensions without dots")
    if len(value) != len(set(value)):
        raise ValueError("waveform_analysis_format_priority must not contain duplicate formats")
    return list(value)


def validate_waveform_analysis_backend_priority(value: Any) -> dict[str, list[str]]:
    """Validate per-format backend lists and fill unspecified built-in defaults."""
    if not isinstance(value, Mapping):
        raise ValueError("waveform_analysis_backend_priority must be a mapping of formats to backend lists")
    result = {name: list(order) for name, order in DEFAULT_WAVEFORM_ANALYSIS_BACKEND_PRIORITY.items()}
    for name, order in value.items():
        if not isinstance(name, str) or _FORMAT_NAME.fullmatch(name) is None:
            raise ValueError("waveform_analysis_backend_priority format names must be lowercase extensions")
        if (
            not isinstance(order, (list, tuple)) or not order
            or any(not isinstance(item, str) or _FORMAT_NAME.fullmatch(item) is None for item in order)
            or len(order) != len(set(order))
        ):
            raise ValueError("waveform_analysis_backend_priority entries must be nonempty lists of distinct backend names")
        result[name] = list(order)
    return result


def register_waveform_reader(
    format_name: str, factory: WaveformReaderFactory, *, backend: str = "default",
) -> None:
    """Register one named implementation of a format without importing its library.

    Plugins register before constructing WaveInfo. Distinct backend names can
    serve one format; duplicate (format, backend) registrations fail. Factories
    yield the public protocol, including advanced-option configuration.
    """
    validate_waveform_analysis_format_priority([format_name])
    if not isinstance(backend, str) or _FORMAT_NAME.fullmatch(backend) is None:
        raise ValueError("waveform backend names must be lowercase identifiers")
    if not callable(factory):
        raise TypeError("waveform reader factory must be callable")
    readers = _READERS.get(format_name, {})
    if backend in readers:
        raise ValueError(f"A waveform reader is already registered for '{format_name}' backend '{backend}'")
    _READERS[format_name] = {**readers, backend: factory}


def registered_waveform_formats() -> tuple[str, ...]:
    """Return extensions available to discovery and reader dispatch."""
    return tuple(_READERS)


def registered_waveform_backends(format_name: str) -> tuple[str, ...]:
    """Return registered implementation names for a single format."""
    return tuple(_READERS.get(format_name, {}))


def open_waveform_reader(
    path: str | Path, *, backend_priority: Mapping[str, list[str]] | None = None,
) -> AbstractContextManager[WaveformReader]:
    """Open the selected file, falling back only when a library is unavailable.

    ImportError during factory construction/entry permits the next configured
    backend. Parse errors, invalid advanced options, and errors after entry
    propagate without retrying. No other file or format is substituted.
    """
    format_name = Path(path).suffix.lower().lstrip(".")
    if format_name not in _READERS:
        raise ValueError(f"No waveform reader is registered for '{format_name}'. Registered formats: {', '.join(_READERS)}")
    priority = validate_waveform_analysis_backend_priority({} if backend_priority is None else backend_priority)
    order = priority.get(format_name, list(_READERS[format_name]))
    for name in order:
        if name not in _READERS[format_name]:
            raise ValueError(f"No waveform reader registered for '{format_name}' backend '{name}'")

    @contextmanager
    def opened() -> Iterator[WaveformReader]:
        """Keep dependency fallback outside the caller's analysis exception scope."""
        failures = []
        log_msg(f"[WaveInfo] backend_order format={format_name} backends={','.join(order)} file={path}")
        for name in order:
            stack = ExitStack()
            log_msg(f"[WaveInfo] backend_attempt format={format_name} backend={name} file={path}")
            try:
                reader = stack.enter_context(_READERS[format_name][name](str(path)))
            except ImportError as error:
                stack.close()
                failures.append(f"{name}: {error}")
                log_msg(f"[WaveInfo] backend_unavailable format={format_name} backend={name} file={path} reason={error}")
                continue
            except BaseException as error:
                stack.close()
                log_msg(f"[WaveInfo] backend_open_failed format={format_name} backend={name} file={path} error={type(error).__name__}: {error}")
                raise
            log_msg(f"[WaveInfo] backend_selected format={format_name} backend={name} file={path}")
            with stack:
                yield reader
            return
        raise ImportError(f"No configured reader is available for {path}: {'; '.join(failures)}")

    return opened()
