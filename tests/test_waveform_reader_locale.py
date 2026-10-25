"""Native waveform initialization must not poison subsequent text processing."""

from contextlib import nullcontext
import locale

import pytest
import wavekit

from ucagent.util.waveform_formats import open_waveform_reader


@pytest.mark.parametrize("extension,reader_name", [
    ("fsdb", "FsdbReader"), ("vcd", "VcdReader"), ("fst", "FstReader"),
])
@pytest.mark.parametrize("fail", [False, True])
def test_native_reader_restores_locale(tmp_path, monkeypatch, extension, reader_name, fail):
    """Restore the full locale on successful and failed native initialization."""
    original_locale = locale.setlocale(locale.LC_ALL)
    try:
        locale.setlocale(locale.LC_CTYPE, "C.UTF-8")
        expected_locale = locale.setlocale(locale.LC_ALL)
        text_file = tmp_path / "text.txt"
        text_file.write_text(chr(0x4e2d), encoding="utf-8")
        reader = object()

        def native_reader(path):
            """Simulate the locale reset performed by a native runtime."""
            assert path == f"capture.{extension}"
            locale.setlocale(locale.LC_ALL, "C")
            if fail:
                raise RuntimeError("native initialization failed")
            return nullcontext(reader)

        monkeypatch.setattr(wavekit, reader_name, native_reader)
        if fail:
            with pytest.raises(RuntimeError, match="native initialization failed"):
                open_waveform_reader(f"capture.{extension}")
        else:
            with open_waveform_reader(f"capture.{extension}") as opened:
                assert opened is reader
        assert locale.setlocale(locale.LC_ALL) == expected_locale
        with text_file.open() as stream:
            assert stream.read() == chr(0x4e2d)
    finally:
        locale.setlocale(locale.LC_ALL, original_locale)
