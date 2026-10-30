"""FSDB reader implemented through a lazily imported wavekit backend."""

from .adapter_wavekit import WavekitReaderAdapter


class WavekitFsdbReader(WavekitReaderAdapter):
    """Adapt wavekit's FSDB reader to the public waveform contract."""

    def __init__(self, path: str) -> None:
        """Create a resource-owning context for exactly the selected FSDB file."""
        import wavekit

        super().__init__(wavekit.FsdbReader(path))
