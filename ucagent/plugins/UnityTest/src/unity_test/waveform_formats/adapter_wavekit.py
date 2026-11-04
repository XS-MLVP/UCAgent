"""Shared adapter from wavekit's reader API to UCAgent's public contract."""

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from types import TracebackType
from typing import Any

from .protocols import BackendArgs, WaveformBackendArgumentError, WaveformScope, WaveformSignal, WaveformSignalMatches, WaveformValueChanges
from .pagination import DEFAULT_SIGNAL_LIMIT, paginate_signal_matches


class WavekitReaderAdapter(AbstractContextManager["WavekitReaderAdapter"]):
    """Own a wavekit context and expose only the operations needed by WaveInfo."""

    backend_name = "wavekit"

    def __init__(self, context: Any) -> None:
        """Store a wavekit reader context created by a format-specific reader."""
        self._context = context
        self._reader: Any = None

    def __enter__(self) -> "WavekitReaderAdapter":
        """Enter the backend context and expose its reader through this adapter."""
        self._reader = self._context.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Close backend resources even when analysis raises an exception."""
        try:
            return self._context.__exit__(exc_type, exc_value, traceback)
        finally:
            self._reader = None

    @property
    def begin_time(self) -> int:
        """Return the first native simulation timestamp."""
        return int(self._reader.begin_time)

    @property
    def end_time(self) -> int:
        """Return the last native simulation timestamp."""
        return int(self._reader.end_time)

    @property
    def top_scopes(self) -> Sequence[WaveformScope]:
        """Return the backend's real top-level scopes."""
        return self._reader.top_scopes

    def configure_backend(self, backend_args: BackendArgs) -> dict[str, Any]:
        """Describe the absence of advanced options and reject unsupported input."""
        if backend_args == "help":
            return {"options": {}, "description": "No advanced options are available for this waveform.", "examples": [{"backend_args": {}}]}
        if backend_args != {}:
            raise WaveformBackendArgumentError('No advanced options are supported; request backend_args="help".')
        return {}

    def get_matched_signals(
        self, path: str, *, offset: int = 0, limit: int = DEFAULT_SIGNAL_LIMIT,
    ) -> WaveformSignalMatches:
        """Page wavekit descriptors by full path without adding query extensions."""
        return paginate_signal_matches(
            self._reader.get_matched_signals(path), offset=offset, limit=limit,
        )

    def load_value_changes(
        self,
        signal: WaveformSignal,
        value_mapping: Mapping[str, int],
        begin_time: int | None = None,
        end_time: int | None = None,
    ) -> WaveformValueChanges:
        """Wrap wavekit's mapped rows; this backend supplies no extension fields."""
        return {
            "mapped": self._reader._load_value_changes(
                signal, dict(value_mapping), begin_time=begin_time, end_time=end_time,
            ),
        }
