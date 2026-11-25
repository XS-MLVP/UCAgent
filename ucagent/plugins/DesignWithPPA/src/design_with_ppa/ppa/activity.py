"""Streaming waveform input activity and independent test-case aggregation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import ctypes
import os
import re

from .models import _RANGED_REFERENCE_RE, _FST_VECTOR_SUFFIX_RE


@dataclass(frozen=True)


class _InputBit:
    """One synthesized top-level input bit and its OpenSTA port spelling."""

    port: str
    index: int | None
    sta_name: str

    @property
    def key(self) -> str:
        """Return the stable report key for this input bit."""

        return self.sta_name


@dataclass


class _BitActivity:
    """Streaming activity accumulator for one input bit in one TC."""

    seen: bool = False
    state: str = "x"
    last_tick: int = 0
    first_tick: int | None = None
    transitions: float = 0.0
    high_ticks: int = 0
    unknown_ticks: int = 0

    def observe(self, tick: int, state: str) -> None:
        """Consume one value event without treating the first value as a transition."""

        normalized = state.lower()
        if normalized not in {"0", "1", "x", "z"}:
            normalized = "x"
        if not self.seen:
            self.seen = True
            self.state = normalized
            self.last_tick = tick
            self.first_tick = tick
            return
        elapsed = max(0, tick - self.last_tick)
        if self.state == "1":
            self.high_ticks += elapsed
        elif self.state not in {"0", "1"}:
            self.unknown_ticks += elapsed
        if normalized != self.state:
            self.transitions += (
                1.0 if normalized in {"0", "1"} and self.state in {"0", "1"} else 0.5
            )
        self.state = normalized
        self.last_tick = tick

    def finish(self, end_tick: int) -> None:
        """Accumulate the final interval through the TC end timestamp."""

        if not self.seen:
            return
        elapsed = max(0, end_tick - self.last_tick)
        if self.state == "1":
            self.high_ticks += elapsed
        elif self.state not in {"0", "1"}:
            self.unknown_ticks += elapsed


@dataclass(frozen=True)


class _ReferenceBinding:
    """Map one VCD identifier value position to synthesized input bits."""

    reference: str
    width: int
    positions: tuple[tuple[str, int], ...]


class _ActivityCallbacks:
    """vcdvcd callbacks that stream only selected input-port activity."""

    def __init__(
        self,
        bindings: dict[str, _ReferenceBinding],
        accumulators: dict[str, _BitActivity],
    ) -> None:
        """Store immutable identifier bindings and mutable bit accumulators."""

        self.bindings = bindings
        self.accumulators = accumulators

    def enddefinitions(self, vcd, signals, cur_sig_vals) -> None:
        """Accept the parsed VCD header; no additional setup is required."""

        del vcd, signals, cur_sig_vals

    def time(self, vcd, time_value, cur_sig_vals) -> None:
        """Accept timestamp callbacks; value callbacks carry the effective timestamp."""

        del vcd, time_value, cur_sig_vals

    def value(self, vcd, time, value, identifier_code, cur_sig_vals) -> None:
        """Expand a scalar/vector VCD event into its synthesized input bits."""

        del vcd, cur_sig_vals
        binding = self.bindings.get(identifier_code)
        if binding is None:
            return
        normalized = str(value).lower()
        if len(normalized) < binding.width:
            pad = normalized[0] if normalized and normalized[0] in {"x", "z"} else "0"
            normalized = pad * (binding.width - len(normalized)) + normalized
        elif len(normalized) > binding.width:
            normalized = normalized[-binding.width :]
        for bit_key, position in binding.positions:
            self.accumulators[bit_key].observe(time, normalized[position])


def _port_bits(mapped_json: dict[str, Any], top_module: str) -> list[_InputBit]:
    """Extract synthesized top-level input bits in deterministic port order."""

    module = mapped_json.get("modules", {}).get(top_module)
    if not isinstance(module, dict):
        raise ValueError(f"mapped netlist does not contain top module '{top_module}'")
    result: list[_InputBit] = []
    for name, port in module.get("ports", {}).items():
        if port.get("direction") != "input":
            continue
        width = len(port.get("bits", []))
        if width <= 0:
            continue
        if width == 1:
            result.append(_InputBit(name, None, name))
            continue
        offset = int(port.get("offset", 0))
        if int(port.get("upto", 0)):
            indices = range(offset + width - 1, offset - 1, -1)
        else:
            indices = range(offset, offset + width)
        result.extend(_InputBit(name, index, f"{name}[{index}]") for index in indices)
    if not result:
        raise ValueError("synthesized top module has no input ports")
    return result


def _reference_bit_positions(
    local_reference: str,
    signal_width: int,
    by_port: dict[str, list[_InputBit]],
) -> list[tuple[str, int]]:
    """Resolve one VCD reference into value-string positions for expected input bits.

    ``by_port`` is the expected-bit index keyed by port name.  Callers build it
    once because reference resolution runs per declared reference, per scope
    candidate, and per waveform, so rebuilding it per call dominates runtime
    on wide input ports.
    """

    range_match = _RANGED_REFERENCE_RE.fullmatch(local_reference)
    if range_match:
        port = range_match.group("name")
        if port not in by_port:
            return []
        left = int(range_match.group("left"))
        right_text = range_match.group("right")
        if right_text is None:
            index = left
            candidates = [bit for bit in by_port[port] if bit.index == index]
            return [(candidates[0].key, 0)] if candidates and signal_width == 1 else []
        right = int(right_text)
        indices = list(range(left, right + (1 if right >= left else -1), 1 if right >= left else -1))
        if len(indices) != signal_width:
            return []
        expected_by_index = {bit.index: bit for bit in by_port[port]}
        if any(index not in expected_by_index for index in indices):
            return []
        return [(expected_by_index[index].key, position) for position, index in enumerate(indices)]
    if local_reference not in by_port:
        return []
    port_bits = by_port[local_reference]
    if len(port_bits) != signal_width:
        return []
    if signal_width == 1:
        return [(port_bits[0].key, 0)]
    by_index = {bit.index: bit for bit in port_bits}
    descending = sorted((index for index in by_index if index is not None), reverse=True)
    return [(by_index[index].key, position) for position, index in enumerate(descending)]


def _discover_waveform_scope(
    header: Any,
    requested_scope: str,
    expected_bits: list[_InputBit],
) -> str:
    """Resolve a generated wrapper scope when the configured default is stale.

    RTL simulators commonly add a language-specific top wrapper (for example,
    ``TOP.<dut>_top``).  The discovery is intentionally conservative: a scope
    is accepted only when its declarations cover every synthesized top-level
    input bit, and the deepest deterministic candidate is selected.  A custom
    scope that already satisfies the contract is always preserved.
    """

    expected_keys = {bit.key for bit in expected_bits}
    by_port: dict[str, list[_InputBit]] = defaultdict(list)
    for bit in expected_bits:
        by_port[bit.port].append(bit)
    # Group every declared reference under its direct parent scope once so
    # scoring a candidate costs only that scope's own children.  Rescanning
    # the whole header per candidate prefix is quadratic in references and
    # dominated wide-port discovery on generated RTL waveforms.
    children: dict[str, list[tuple[str, int]]] = defaultdict(list)
    scopes: set[str] = set()
    for signal_info in header.data.values():
        width = int(signal_info.size)
        for reference in signal_info.references:
            parts = reference.split(".")
            for cut in range(1, len(parts)):
                scopes.add(".".join(parts[:cut]))
            children[".".join(parts[:-1])].append((parts[-1], width))

    def covered(scope: str) -> set[str]:
        """Return expected input bits declared directly below one scope."""

        result: set[str] = set()
        for local_reference, width in children.get(scope, ()):
            result.update(
                bit_key
                for bit_key, _ in _reference_bit_positions(
                    local_reference, width, by_port
                )
            )
        return result

    if covered(requested_scope) == expected_keys:
        return requested_scope

    for scope in sorted(scopes, key=lambda value: (-value.count("."), value)):
        if scope != requested_scope and covered(scope) == expected_keys:
            return scope
    return requested_scope


def _convert_fst_to_vcd(
    source: Path,
    destination: Path,
    wanted_ports: set[str] | None = None,
) -> None:
    """Convert an FST waveform to a temporary VCD through pylibfst's streaming API.

    ``wanted_ports`` restricts value-change decoding to the facets whose
    declared name (ignoring a trailing vector suffix such as ``[5:0]``) is one
    of those top-level input ports.  The emitted hierarchy section still lists
    every declared signal, so downstream scope discovery and coverage checks
    see the same contract while the decoded value stream stays proportional to
    the input ports instead of the whole DUT.  Facet names in FST hierarchies
    separate the vector suffix with a space (``cfg_addr [5:0]``), unlike VCD
    references.  A wanted set that matches no facet falls back to decoding
    everything so an unexpected naming scheme degrades to the previous
    behavior instead of silently dropping all activity.
    """

    try:
        import pylibfst  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "pylibfst is required for .fst input; install pylibfst>=0.2.1,<0.3.0"
        ) from exc
    reader = pylibfst.lib.fstReaderOpen(os.fsencode(source))
    if reader == pylibfst.ffi.NULL:
        raise ValueError(f"pylibfst could not open FST file: {source.name}")
    selected_handles: set[int] = set()
    if wanted_ports is not None:
        _scopes, signals = pylibfst.get_scopes_signals2(reader)
        for name, signal in signals.by_name.items():
            local = name.rsplit(".", 1)[-1]
            if _FST_VECTOR_SUFFIX_RE.sub("", local) in wanted_ports:
                selected_handles.add(signal.handle)
    libc = ctypes.CDLL(None)
    libc.fopen.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    libc.fopen.restype = ctypes.c_void_p
    libc.fclose.argtypes = [ctypes.c_void_p]
    libc.fclose.restype = ctypes.c_int
    file_pointer = libc.fopen(os.fsencode(destination), b"wb")
    if not file_pointer:
        pylibfst.lib.fstReaderClose(reader)
        raise OSError(f"could not create temporary VCD: {destination}")
    cffi_file = pylibfst.ffi.cast("FILE *", file_pointer)
    try:
        if pylibfst.lib.fstReaderProcessHier(reader, cffi_file) == 0:
            raise ValueError(f"pylibfst could not decode FST hierarchy: {source.name}")
        if selected_handles:
            for handle in sorted(selected_handles):
                pylibfst.lib.fstReaderSetFacProcessMask(reader, handle)
        else:
            pylibfst.lib.fstReaderSetFacProcessMaskAll(reader)
        if pylibfst.lib.fstReaderIterBlocks(
            reader, pylibfst.ffi.NULL, pylibfst.ffi.NULL, cffi_file
        ) == 0:
            raise ValueError(f"pylibfst could not decode FST value blocks: {source.name}")
    finally:
        pylibfst.lib.fstReaderClose(reader)
        libc.fclose(file_pointer)


def _parse_vcd_activity(
    path: Path,
    source_label: str,
    waveform_scope: str,
    expected_bits: list[_InputBit],
) -> tuple[dict[str, Any], dict[str, dict[str, float]]]:
    """Stream one VCD TC and return provenance plus per-input-bit SI activity."""

    try:
        from vcdvcd import VCDVCD  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "vcdvcd is required for waveform activity; install vcdvcd>=2.3.5,<3.0.0"
        ) from exc
    header = VCDVCD(str(path), only_sigs=True, store_tvs=False)
    if not header.signals:
        raise ValueError("waveform contains no declared signals")
    waveform_scope = _discover_waveform_scope(header, waveform_scope, expected_bits)
    prefix = f"{waveform_scope}."
    by_port: dict[str, list[_InputBit]] = defaultdict(list)
    for bit in expected_bits:
        by_port[bit.port].append(bit)
    candidates: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for identifier, signal_info in header.data.items():
        width = int(signal_info.size)
        for reference in signal_info.references:
            if not reference.startswith(prefix):
                continue
            positions = _reference_bit_positions(
                reference[len(prefix) :], width, by_port
            )
            for bit_key, position in positions:
                candidates[bit_key].append((identifier, reference, position))
    missing = [bit.key for bit in expected_bits if not candidates.get(bit.key)]
    if missing:
        available = [signal for signal in header.signals if signal.startswith(prefix)][:20]
        raise ValueError(
            "waveform scope does not expose every synthesized input bit; "
            f"missing={missing[:20]}, available_under_scope={available}"
        )
    selected: dict[str, tuple[str, str, int]] = {}
    for bit in expected_bits:
        choices = candidates[bit.key]
        identifiers = {choice[0] for choice in choices}
        if len(identifiers) > 1:
            refs = [choice[1] for choice in choices[:10]]
            raise ValueError(f"ambiguous waveform definitions for input {bit.key}: {refs}")
        selected[bit.key] = choices[0]
    grouped: dict[str, list[tuple[str, int]]] = defaultdict(list)
    reference_by_identifier: dict[str, str] = {}
    width_by_identifier: dict[str, int] = {}
    for bit_key, (identifier, reference, position) in selected.items():
        grouped[identifier].append((bit_key, position))
        reference_by_identifier[identifier] = reference
        width_by_identifier[identifier] = int(header.data[identifier].size)
    bindings = {
        identifier: _ReferenceBinding(
            reference=reference_by_identifier[identifier],
            width=width_by_identifier[identifier],
            positions=tuple(positions),
        )
        for identifier, positions in grouped.items()
    }
    accumulators = {bit.key: _BitActivity() for bit in expected_bits}
    callbacks = _ActivityCallbacks(bindings, accumulators)
    parsed = VCDVCD(
        str(path),
        signals=[binding.reference for binding in bindings.values()],
        store_tvs=False,
        callbacks=callbacks,
    )
    if not parsed.timescale or "timescale" not in parsed.timescale:
        raise ValueError("waveform has no valid $timescale")
    observed_starts = [
        accumulator.first_tick
        for accumulator in accumulators.values()
        if accumulator.first_tick is not None
    ]
    start_tick = min([int(parsed.begintime), *observed_starts])
    end_tick = int(parsed.endtime)
    duration_ticks = end_tick - start_tick
    if duration_ticks <= 0:
        raise ValueError(
            f"waveform effective duration must be positive, observed {duration_ticks} ticks"
        )
    scale_seconds = float(parsed.timescale["timescale"])
    duration_seconds = duration_ticks * scale_seconds
    activities: dict[str, dict[str, float]] = {}
    for bit_key, accumulator in accumulators.items():
        accumulator.finish(end_tick)
        if not accumulator.seen:
            raise ValueError(f"input {bit_key} has no value samples")
        activities[bit_key] = {
            "duration_seconds": duration_seconds,
            "transition_count": accumulator.transitions,
            "high_duration_seconds": accumulator.high_ticks * scale_seconds,
            "unknown_duration_seconds": accumulator.unknown_ticks * scale_seconds,
        }
    per_tc = {
        "path": source_label,
        "begin_tick": start_tick,
        "end_tick": end_tick,
        "duration_seconds": duration_seconds,
        "timescale_seconds": scale_seconds,
        "timescale": (
            f"{parsed.timescale.get('magnitude')} {parsed.timescale.get('unit')}"
        ),
        "signal_coverage": {
            "required_input_bits": len(expected_bits),
            "covered_input_bits": len(activities),
            "ratio": 1.0,
        },
        "transition_count": sum(item["transition_count"] for item in activities.values()),
        "waveform_scope": waveform_scope,
    }
    return per_tc, activities


def _aggregate_tc_activity(
    tc_activities: list[tuple[dict[str, Any], dict[str, dict[str, float]]]],
) -> list[dict[str, Any]]:
    """Duration-weight independent TC activity into OpenSTA density and duty values."""

    merged: list[dict[str, Any]] = []
    if not tc_activities:
        return merged
    bit_keys = list(tc_activities[0][1])
    for bit_key in bit_keys:
        duration = sum(activity[bit_key]["duration_seconds"] for _, activity in tc_activities)
        transitions = sum(activity[bit_key]["transition_count"] for _, activity in tc_activities)
        high_duration = sum(
            activity[bit_key]["high_duration_seconds"] for _, activity in tc_activities
        )
        unknown_duration = sum(
            activity[bit_key]["unknown_duration_seconds"] for _, activity in tc_activities
        )
        merged.append(
            {
                "input_bit": bit_key,
                "contributing_files": [tc["path"] for tc, _ in tc_activities],
                "total_duration_seconds": duration,
                "transition_count": transitions,
                "density_hz": transitions / duration,
                "duty_cycle": high_duration / duration,
                "unknown_fraction": unknown_duration / duration,
            }
        )
    return merged
