"""FST implementations using pywellen by default and wavekit as an alternative."""

from .adapter_pywellen import PywellenReaderAdapter
from .adapter_wavekit import WavekitReaderAdapter


class WellenFstReader(PywellenReaderAdapter):
    """Decode FST values with pywellen and preserve declared names/time bounds."""

    def __enter__(self):
        """Read the metadata absent from pywellen's Python API, then open values."""
        import pywellen  # noqa: F401 - check availability before native metadata I/O
        import pylibfst

        handle = pylibfst.lib.fstReaderOpen(self.path.encode('utf-8'))
        if handle == pylibfst.ffi.NULL:
            raise ValueError('Cannot open the selected FST file')
        try:
            self._begin_time = int(pylibfst.lib.fstReaderGetStartTime(handle))
            self._end_time = int(pylibfst.lib.fstReaderGetEndTime(handle))
            _, signals = pylibfst.get_scopes_signals2(handle)
            for name, descriptor in signals.by_name.items():
                self._add_declaration(name, int(descriptor.length))
        finally:
            pylibfst.lib.fstReaderClose(handle)
        return super().__enter__()


class WavekitFstReader(WavekitReaderAdapter):
    """Adapt wavekit's FST implementation to the public waveform contract."""

    def __init__(self, path: str) -> None:
        """Create a resource-owning context for exactly the selected FST file."""
        import wavekit

        super().__init__(wavekit.FstReader(path))
