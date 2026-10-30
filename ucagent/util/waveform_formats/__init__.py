"""Backend-independent waveform contracts and per-format reader registration."""

from .read_fst import WellenFstReader, WavekitFstReader
from .read_fsdb import WavekitFsdbReader
from .pagination import DEFAULT_SIGNAL_LIMIT, MAX_SIGNAL_LIMIT, paginate_signal_matches
from .protocols import (
    WaveformReader,
    WaveformReaderFactory,
    WaveformScope,
    WaveformSignal,
    WaveformSignalMatches,
    WaveformValueChanges,
    BackendArgs,
    WaveformBackendArgumentError,
)
from .registry import (
    DEFAULT_WAVEFORM_ANALYSIS_FORMAT_PRIORITY,
    DEFAULT_WAVEFORM_ANALYSIS_BACKEND_PRIORITY,
    open_waveform_reader,
    register_waveform_reader,
    registered_waveform_formats,
    registered_waveform_backends,
    validate_waveform_analysis_format_priority,
    validate_waveform_analysis_backend_priority,
)
from .read_vcd import WellenVcdReader, WavekitVcdReader


register_waveform_reader("fst", WellenFstReader, backend="pywellen")
register_waveform_reader("fst", WavekitFstReader, backend="wavekit")
register_waveform_reader("vcd", WellenVcdReader, backend="pywellen")
register_waveform_reader("vcd", WavekitVcdReader, backend="wavekit")
register_waveform_reader("fsdb", WavekitFsdbReader, backend="wavekit")

__all__ = [
    "DEFAULT_WAVEFORM_ANALYSIS_FORMAT_PRIORITY",
    "DEFAULT_WAVEFORM_ANALYSIS_BACKEND_PRIORITY",
    "BackendArgs",
    "WaveformBackendArgumentError",
    "DEFAULT_SIGNAL_LIMIT",
    "MAX_SIGNAL_LIMIT",
    "WaveformReader",
    "WaveformReaderFactory",
    "WaveformScope",
    "WaveformSignal",
    "WaveformSignalMatches",
    "WaveformValueChanges",
    "open_waveform_reader",
    "paginate_signal_matches",
    "register_waveform_reader",
    "registered_waveform_formats",
    "registered_waveform_backends",
    "validate_waveform_analysis_format_priority",
    "validate_waveform_analysis_backend_priority",
]
