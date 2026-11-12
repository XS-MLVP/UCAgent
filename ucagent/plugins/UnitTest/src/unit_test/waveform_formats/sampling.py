"""Backend-independent digital trace states and edge sampling used by both workflows."""

from bisect import bisect_right
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from .protocols import WaveformReader, WaveformSignal


@dataclass(frozen=True)
class ValueState:
    """One digital value and the original four-state masks."""

    wave_step: int
    value: int
    x_mask: int
    z_mask: int


@dataclass
class SignalTrace:
    """Mapped digital states and optional information from each value/mask load."""

    name: str
    width: int
    states: list[ValueState]
    extensions: dict[str, dict[str, Any]]

    @cached_property
    def wave_steps(self) -> list[int]:
        """Index the loaded transitions for repeated window samples."""
        return [state.wave_step for state in self.states]

    def value_at(self, wave_step: int) -> ValueState | None:
        """Return the last recorded state at or before the exact native tick."""
        index = bisect_right(self.wave_steps, wave_step) - 1
        return self.states[index] if index >= 0 else None


def load_signal_trace(
    reader: WaveformReader,
    signal: WaveformSignal,
    begin_step: int | None = None,
    end_step: int | None = None,
    extensions_for=None,
) -> SignalTrace:
    """Load mapped values and X/Z masks, preserving per-load extensions."""
    # Include a state before the requested window so transitions at its first
    # timestamp can be evaluated. Readers retain the latest earlier state.
    load_begin = None if begin_step is None else max(0, begin_step - 1)
    load_end = None if end_step is None else end_step + 1
    mapped = {}
    extensions = {}
    for channel, value_mapping in (
        ("value", {"0": 0, "1": 1, "x": 0, "z": 0}),
        ("x_mask", {"0": 0, "1": 0, "x": 1, "z": 0}),
        ("z_mask", {"0": 0, "1": 0, "x": 0, "z": 1}),
    ):
        changes = reader.load_value_changes(
            signal, value_mapping, begin_time=load_begin, end_time=load_end,
        )
        mapped[channel] = {int(row[0]): int(row[1]) for row in changes["mapped"]}
        extra = extensions_for(changes) if extensions_for else {}
        if extra:
            extensions[channel] = extra

    value_by_step = mapped["value"]
    x_by_step = mapped["x_mask"]
    z_by_step = mapped["z_mask"]
    wave_steps = sorted(set(value_by_step) | set(x_by_step) | set(z_by_step))
    states = [
        ValueState(
            wave_step=wave_step,
            value=value_by_step.get(wave_step, 0),
            x_mask=x_by_step.get(wave_step, 0),
            z_mask=z_by_step.get(wave_step, 0),
        )
        for wave_step in wave_steps
    ]
    return SignalTrace(
        name=signal.full_name, width=int(signal.width), states=states, extensions=extensions,
    )


def is_clock_edge(previous, current: ValueState, edge: str, width: int) -> bool:
    """Recognize a known one-bit transition, preserving unknown clock intervals."""
    if width != 1:
        raise ValueError(f"event='{edge}' requires a one-bit signal")
    if previous is None or previous.x_mask or previous.z_mask or current.x_mask or current.z_mask:
        return False
    start, stop = (0, 1) if edge == "rising" else (1, 0)
    return previous.value == start and current.value == stop
