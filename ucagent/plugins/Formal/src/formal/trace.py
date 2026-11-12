"""Query bounded digital samples from a verified Formal counterexample."""

from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TraceQuery(BaseModel):
    """Describe signal discovery or one exact native-time sample window."""

    model_config = ConfigDict(extra="forbid")
    mode: Literal["artifact", "signals", "samples"] = "signals"
    signal_query: str = Field(default="**", min_length=1, max_length=256)
    signals: list[str] = Field(default_factory=list, max_length=16)
    start: Annotated[int, Field(strict=True)] | str | None = None
    end: Annotated[int, Field(strict=True)] | str | None = None
    clock: str | None = Field(default=None, max_length=1024)
    edge: Literal["rising", "falling"] = "rising"
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = Field(default=None, max_length=140)

    @model_validator(mode="after")
    def validate_window(self):
        """Require explicit bounds and exact signal names for samples."""
        if self.mode == "samples":
            if not self.signals or len(set(self.signals)) != len(self.signals) or any(not name or len(name) > 1024 for name in self.signals):
                raise ValueError("Samples require 1..16 unique full signal paths.")
            for value in (self.start, self.end):
                if value is None or not str(value).isascii() or not str(value).isdecimal() or len(str(value)) > 24:
                    raise ValueError("Sample window requires nonnegative native start/end ticks.")
            if int(self.start) > int(self.end):
                raise ValueError("Sample window start must not exceed end.")
        elif self.signals or self.start is not None or self.end is not None or self.clock:
            raise ValueError("Signal discovery uses signal_query and cursor.")
        return self


def _waveform_module():
    """Load the framework's bundled waveform reader for a Formal-only installation."""
    try:
        return import_module("unit_test.waveform_formats")
    except ModuleNotFoundError as exc:
        if exc.name != "unit_test":
            raise
        import ucagent.plugins
        from ucagent.core.plugins import PluginError, load_plugin

        project = Path(ucagent.plugins.__file__).resolve().parent / "UnitTest"
        try:
            load_plugin(str(project), check_dependencies=False)
        except PluginError as plugin_error:
            raise ValueError(f"Cannot load the bundled waveform reader: {plugin_error}") from plugin_error
        return import_module("unit_test.waveform_formats")


def trace_page(path: Path, digest: str, query: TraceQuery) -> dict:
    """Read a page bound to the verified VCD and query without inferring a failure cycle."""
    if path.suffix.lower() != ".vcd":
        raise ValueError("Formal trace must be an original VCD.")
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Original VCD exceeds the 32 MiB analysis budget; open the original artifact.")
    signature = sha256((digest + query.model_dump_json(exclude={"cursor"})).encode()).hexdigest()
    offset = 0
    if query.cursor:
        revision, separator, suffix = query.cursor.partition(":")
        if not separator or revision != signature or not suffix.isdecimal() or len(suffix) > 12:
            raise ValueError("Cursor belongs to a different trace or query.")
        offset = int(suffix)

    waveform = _waveform_module()
    from unit_test.waveform_formats.sampling import is_clock_edge, load_signal_trace

    with waveform.open_waveform_reader(path, backend_priority={"vcd": ["wavekit"]}) as reader:
        timescale = reader.timescale
        result = {
            "trace_sha256": digest, "time_magnitude": str(timescale.get("magnitude", "1")),
            "time_unit": str(timescale.get("unit", "unknown")),
            "first_tick": str(reader.begin_time), "last_tick": str(reader.end_time),
            "offset": offset,
        }
        if query.mode == "signals":
            matches = reader.get_matched_signals(query.signal_query, offset=offset, limit=query.limit)
            rows = [{"path": item.full_name, "width": item.width} for item in matches["signals"].values()]
            total = matches["total"]
            result["signals"] = rows
        else:
            start, end = int(query.start), int(query.end)
            if start < reader.begin_time or end > reader.end_time:
                raise ValueError("Sample window is outside the recorded VCD range.")
            traces, missing = {}, []
            for name in dict.fromkeys([*query.signals, *([query.clock] if query.clock else [])]):
                # Search accepts globs for discovery. Sampling binds only an exact returned path.
                matches = reader.get_matched_signals(name, limit=8)
                match = next((item for item in matches["signals"].values() if item.full_name == name), None)
                if match is None:
                    missing.append(name)
                elif match.width > 4096:
                    raise ValueError(f"Signal exceeds the supported analysis width: {name}")
                else:
                    traces[name] = load_signal_trace(reader, match, start, end)
            if query.clock:
                clock = traces.get(query.clock)
                if clock is None or clock.width != 1:
                    raise ValueError("Sample clock must identify an exact one-bit VCD signal.")
                points = [state.wave_step for previous, state in zip(clock.states, clock.states[1:])
                          if start <= state.wave_step <= end and is_clock_edge(previous, state, query.edge, clock.width)]
            else:
                points = sorted({start, end, *(state.wave_step for trace in traces.values() for state in trace.states
                                               if start <= state.wave_step <= end)})
            total = len(points)
            rows = []
            for tick in points[offset:offset + query.limit]:
                values = {}
                for name in query.signals:
                    trace = traces.get(name)
                    value = trace.value_at(tick) if trace else None
                    values[name] = None if value is None else {
                        "width": trace.width, "value": hex(value.value) if not (value.x_mask or value.z_mask) else None,
                        "x_mask": hex(value.x_mask), "z_mask": hex(value.z_mask),
                    }
                rows.append({"tick": str(tick), "values": values})
            result.update(samples=rows, missing_signals=missing, start=str(start), end=str(end),
                          clock=query.clock, edge=query.edge if query.clock else None,
                          sample_kind="clock_edge" if query.clock else "value_changes_and_window_bounds")
    following = offset + len(rows)
    result.update(total=total, truncated=following < total,
                  next_cursor=f"{signature}:{following}" if following < total else None)
    return result
