"""Project real public-pin waveforms onto a common unit workload time scale."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re

from vcdvcd import VCDVCD

from ..contracts import sha256_file
from .models import Interface


def waveform_as_vcd(raw: Path, scratch: Path) -> Path:
    """Return a VCD view of a native dump; FST is streamed through the shared converter."""

    if raw.suffix != ".fst":
        return raw
    converted = scratch / (raw.stem + ".vcd")
    from ..ppa import _convert_fst_to_vcd

    _convert_fst_to_vcd(raw, converted)
    return converted


def unit_activity_waveform(raw: Path, output: Path, interface: Interface, *,
                           activity_span: list[int],
                           clock_period_ns: float) -> dict:
    """Crop reset/idle activity and scale the active window to the frozen period.

    The window is bounded by the first and last real transitions of the
    non-clock public pins, so no particular signal, clock, or dump granularity
    is assumed: FST's event-driven collapsing and VCD's fixed half-step
    sampling both project identically. ``activity_span`` supplies the matching
    logical cycle numbers recorded by the managed environment.
    """

    vcd = waveform_as_vcd(raw, output.parent)
    parsed = VCDVCD(str(vcd))
    pin_signals = {}
    for name in interface.pins:
        matching = []
        for identifier, signal in parsed.data.items():
            for reference in signal.references:
                parent, _, leaf = reference.rpartition(".")
                if (parent.rsplit(".", 1)[-1] == interface.top
                        and re.fullmatch(re.escape(name) + r"(?:\[[^\]]+\])?", leaf)):
                    matching.append(identifier)
        if len(set(matching)) != 1:
            raise ValueError(f"Cannot uniquely bind public pin to raw waveform: {name}")
        pin_signals[name] = parsed.data[matching[0]]
    data_edges = sorted({tick
                         for name, signal in pin_signals.items()
                         if name != interface.clock
                         for tick, _ in signal.tv if tick > 0})
    if len(data_edges) < 2:
        raise ValueError(
            "Unit dump shows fewer than two public-pin transitions; drive real "
            "workload activity so power is measured over actual transactions")
    first_cycle, last_cycle = activity_span[0], activity_span[1]
    if last_cycle <= first_cycle:
        last_cycle = first_cycle + 1
    initial_tick = data_edges[0]
    ticks_per_cycle = (data_edges[-1] - data_edges[0]) / (last_cycle - first_cycle)
    if ticks_per_cycle <= 0:
        raise ValueError("Cannot align the real waveform with measured unit cycles")
    start = initial_tick
    end = start + (last_cycle - first_cycle + 1) * ticks_per_cycle
    events = defaultdict(list)
    header = ["$timescale 1fs $end", "$scope module TOP $end", f"$scope module {interface.top} $end"]
    for index, (name, pin) in enumerate(interface.pins.items()):
        signal = pin_signals[name]
        symbol = f"p{index}"
        header.append(f"$var wire {pin.width} {symbol} {name} $end")
        initial = "x" * pin.width
        for tick, value in signal.tv:
            if tick <= start:
                initial = value
            elif tick < end:
                physical_tick = round((tick - start) / ticks_per_cycle * clock_period_ns * 1_000_000)
                events[physical_tick].append(f"b{value} {symbol}")
        events[0].insert(0, f"b{initial} {symbol}")
    header += ["$upscope $end", "$upscope $end", "$enddefinitions $end"]
    events[round((last_cycle - first_cycle + 1) * clock_period_ns * 1_000_000)]
    with output.open("w", encoding="ascii") as stream:
        stream.write("\n".join(header) + "\n")
        for tick, values in sorted(events.items()):
            stream.write(f"#{tick}\n" + "\n".join(values) + "\n")
    if vcd != raw:
        vcd.unlink()
    return {"raw_sha256": sha256_file(raw), "activity_sha256": sha256_file(output),
            "native_start_tick": initial_tick, "native_end_tick": end,
            "native_ticks_per_cycle": ticks_per_cycle,
            "activity_first_cycle": first_cycle, "activity_last_cycle": last_cycle,
            "clock_period_ns": clock_period_ns}
