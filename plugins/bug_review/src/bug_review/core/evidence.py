"""Validate phenomenon-specific events and derive portable waveform navigation."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from types import SimpleNamespace
import html
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

from ucagent.util.waveform_viewer import decode_waveform_viewer_token

from .records import REF_PATTERN, source_lines


def case_waveforms(case):
    """Return every case receipt once, keeping the explicitly selected primary first."""
    return [wave for wave in [case.waveform, *case.additional_waveforms] if wave.receipt_id]


def signal_identity(name):
    """Remove a dump's terminal packed range without dropping the instance identity."""
    return re.sub(r"\[\d+:\d+\]$", "", name)


def event_issues(case, source_root, waveinfo):
    """Check execution, step, source, signed signal and window ownership for every event."""
    issues = []
    steps = {(step.execution_id, step.step_id): step for step in case.scenario_steps}
    if len(steps) != len(case.scenario_steps):
        issues.append({"field": "scenario_steps", "problem": "duplicate execution/step identity"})
    ids = set()
    executions = {case.replay.invocation_id}
    executions.update(item.get("invocation_id", "") for item in case.replay.reruns)
    executions.discard("")
    waves = {wave.receipt_id: wave for wave in case_waveforms(case)}
    if len(waves) != len(case_waveforms(case)):
        issues.append({"field": "additional_waveforms", "problem": "duplicate receipt_id"})
    for step in case.scenario_steps:
        if step.execution_id not in executions:
            issues.append({"field": "scenario_steps/execution_id", "problem": "step execution is not baseline or recorded rerun"})
        for reference in step.source_refs:
            try:
                source_lines(source_root, reference, 1)
            except (ValueError, OSError) as error:
                issues.append({"field": "scenario_steps/source_refs", "problem": str(error)})
    for event in case.events:
        base = f"events/{event.event_id}"
        if event.event_id in ids:
            issues.append({"field": base, "problem": "duplicate event_id"})
        ids.add(event.event_id)
        if event.execution_id not in executions:
            issues.append({"field": base + "/execution_id", "problem": "execution is not baseline or recorded rerun"})
        step = steps.get((event.execution_id, event.step_id))
        if event.step_id and (step is None or step.status == "not_reached"):
            issues.append({"field": base + "/step_id", "problem": "event step is missing or not reached"})
        references = [*event.rtl_refs, *(field.source_ref for field in event.fields)]
        if event.source_kind != "waveform":
            references.append(event.source_ref)
        for reference in references:
            try:
                source_lines(source_root, reference, 1)
            except (ValueError, OSError) as error:
                issues.append({"field": base + "/source_ref", "problem": str(error)})
        if event.source_kind != "waveform":
            continue
        wave = waves.get(event.receipt_id)
        receipt = waveinfo.get_analysis_receipt(event.receipt_id) if waveinfo else None
        if not wave or not receipt:
            issues.append({"field": base + "/receipt_id", "problem": "event receipt is not an attached case waveform"})
            continue
        try:
            payload = decode_waveform_viewer_token(parse_qs(urlsplit(wave.viewer_url).query)["wave"][0])
            start, end = int(payload["start"]), int(payload["end"])
            if not start <= event.time <= end:
                raise ValueError("event is outside the signed window")
            names = {signal_identity(name) for name in payload.get("signals", [])}
            if event.signal_path not in names:
                raise ValueError("full signal path is not in signed viewer signals")
            if len(event.raw_value) < max((msb + 1 for field in event.fields for msb, _ in field.parts), default=0):
                raise ValueError("field exceeds the raw bus width")
            selection = receipt.get("result", {}).get("waveform_selection", {})
            relative = selection.get("waveform_file", "")
            original = (source_root / relative).resolve() if relative else None
            if original and original.is_relative_to(source_root.resolve()) and original.is_file():
                stat = original.stat()
                if stat.st_size == selection.get("size_bytes") and stat.st_mtime_ns == selection.get("modified_time_ns"):
                    if read_event_value(original, event) != event.raw_value.lower():
                        raise ValueError("event raw_value differs from signed source snapshot")
        except (ValueError, KeyError, TypeError) as error:
            issue = {"field": base, "problem": str(error)}
            if str(error) == "event raw_value differs from signed source snapshot":
                issue["next_action"] = "Use ApplyWaveformEvent with this case/event identity to read the measured value; do not transcribe raw_value"
            issues.append(issue)
    return [{"case_id": case.case_id, **issue} for issue in issues]


def read_event_value(path, event):
    """Read one exact event value, retaining unknown masks and the full signal width."""
    path = Path(path).resolve()
    stat = path.stat()
    identity = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    return _cached_event_value(str(path), identity, event.time, event.signal_path)


@lru_cache(maxsize=2048)
def _cached_event_value(filename, identity, time, signal_path):
    """Reuse measurements only while the same immutable snapshot identity is present."""
    path = Path(filename)
    event = SimpleNamespace(time=time, signal_path=signal_path)
    import wavekit
    from ucagent.tools.waveform import WaveInfo

    reader_type = wavekit.FstReader if path.suffix == ".fst" else wavekit.VcdReader
    with reader_type(str(path)) as reader:
        if not reader.begin_time <= event.time <= reader.end_time:
            raise ValueError("event time is outside the actual waveform")
        matches = [signal for signal in reader.get_matched_signals("**").values()
                   if signal_identity(signal.full_name) == event.signal_path]
        if len(matches) != 1:
            raise ValueError("event signal is missing or ambiguous in waveform")
        trace = WaveInfo._load_trace(reader, matches[0], max(int(reader.begin_time), event.time - 1), event.time)
        state = trace.value_at(event.time)
        if state is None:
            raise ValueError("event has no waveform value")
        return "".join("x" if state.x_mask >> bit & 1 else "z" if state.z_mask >> bit & 1
                       else str(state.value >> bit & 1) for bit in reversed(range(trace.width)))


def waveform_timescale(path, reader):
    """Read the file's physical tick scale without treating timestamps as log cycles."""
    if path.suffix == ".fst":
        import pylibfst
        exponent = int(pylibfst.lib.fstReaderGetTimescale(reader.file_handle))
        return f"10^{exponent} s"
    with path.open("rb") as stream:
        header = stream.read(65536)
    match = re.search(rb"\$timescale\s+(\d+)\s*(s|ms|us|ns|ps|fs)\s+\$end", header)
    if not match:
        raise ValueError("VCD header has no supported timescale")
    value, unit = int(match.group(1)), match.group(2).decode()
    exponent = {"s": 0, "ms": -3, "us": -6, "ns": -9, "ps": -12, "fs": -15}[unit]
    while value >= 10 and value % 10 == 0:
        value //= 10
        exponent += 1
    return f"{value}*10^{exponent} s" if value != 1 else f"10^{exponent} s"


def binding_issues(bug, cases):
    """Check that a phenomenon's support belongs to its own linked case and event."""
    issues, ids = [], set()
    for binding in bug.evidence_bindings:
        base = f"bugs/{bug.bug_id}/evidence_bindings/{binding.evidence_id}"
        if binding.evidence_id in ids:
            issues.append({"field": base, "problem": "duplicate evidence_id"})
        ids.add(binding.evidence_id)
        case = cases.get(binding.case_id)
        if not case or binding.case_id not in bug.case_ids or bug.bug_id not in case.bug_ids:
            issues.append({"field": base, "problem": "binding case is not bidirectionally linked to this phenomenon"})
            continue
        event = next((event for event in case.events if event.event_id == binding.event_id), None)
        if binding.role != "reported_only" and event is None:
            issues.append({"field": base + "/event_id", "problem": "support needs this case's own event"})
        if binding.role == "direct" and (not event or event.source_kind != "waveform"
                or event.kind != "first_deviation" or binding.remaining_gap):
            issues.append({"field": base, "problem": "direct support needs a waveform deviation and no unresolved support gap"})
        if binding.role == "normal_reference" and event and event.kind != "normal_reference":
            issues.append({"field": base, "problem": "normal reference must identify a normal-reference event"})
    return issues


def root_page(root_id):
    """Derive a stable collision-resistant filename from the exact root identity."""
    return "root_" + hashlib.sha256(root_id.encode("utf-8")).hexdigest() + ".html"


def decode_fields(bits, fields):
    """Decode sourced concatenations exactly, preserving unknown bits and arbitrary width."""
    bits = bits.lower()
    if not re.fullmatch(r"[01xz]+", bits):
        raise ValueError("raw bus must be a nonempty binary/X/Z string")
    rows = []
    for field in fields:
        if any(msb >= len(bits) for msb, _ in field.parts):
            raise ValueError(f"field exceeds bus width: {field.name}")
        value = "".join(bits[len(bits) - msb - 1:len(bits) - lsb] for msb, lsb in field.parts)
        number = None if "x" in value or "z" in value else int(value, 2)
        rows.append({"name": field.name, "bits": value,
                     "value": "0b" + value if number is None else hex(number),
                     "meaning": field.enum_values.get(str(number), ""),
                     "enum_status": ("known" if number is not None and str(number) in field.enum_values
                                     else "unknown") if field.enum_values else "not_applicable",
                     "source_ref": field.source_ref})
    return rows


def snapshot_preview(path, wave, event):
    """Read measured traces from one archived snapshot; never fabricate missing events."""
    import wavekit
    from ucagent.tools.waveform import WaveInfo

    payload = decode_waveform_viewer_token(parse_qs(urlsplit(wave.viewer_url).query)["wave"][0])
    start, end = int(payload["start"]), int(payload["end"])
    if event.time is None or not start <= event.time <= end:
        raise ValueError("preview event is outside the signed window")
    if read_event_value(path, event) != event.raw_value.lower():
        raise ValueError("event raw_value differs from actual snapshot")
    reader_type = wavekit.FstReader if path.suffix == ".fst" else wavekit.VcdReader
    traces = []
    with reader_type(str(path)) as reader:
        if start < reader.begin_time or end > reader.end_time or end <= start:
            raise ValueError("preview window is outside the actual snapshot")
        # A thumbnail focuses on the checked event; the full viewer retains its
        # signed window. Keep every transition in this bounded local interval.
        if end - start > 128:
            start, end = max(start, event.time - 64), min(end, event.time + 64)
        catalog = reader.get_matched_signals("**")
        signed = {signal_identity(name) for name in payload.get("signals", [])}
        focused = [*wave.signal_groups.get("key_signals", []),
                   *wave.signal_groups.get("protocol", [])] if hasattr(wave, "signal_groups") else []
        requested = list(dict.fromkeys(signal_identity(name)
                         for name in [event.signal_path, *focused, *payload.get("signals", [])]
                         if signal_identity(name) in signed))[:6]
        for name in requested:
            matches = [signal for signal in catalog.values()
                       if signal_identity(signal.full_name) == signal_identity(name)]
            if len(matches) != 1:
                raise ValueError(f"signal is missing or ambiguous in snapshot: {name}")
            signal = matches[0]
            trace = WaveInfo._load_trace(reader, signal, start, end)
            points = [(start, trace.value_at(start))]
            points.extend((state.wave_step, state) for state in trace.states if start < state.wave_step <= end)
            if len(points) > 300:
                raise ValueError("preview exceeds transition limit; select a narrower evidence window")
            traces.append((name, trace.width, points))
        timescale = waveform_timescale(path, reader)
    left, right, height = 158, 410, 52 * len(traces) + 50
    x = lambda time: left + (time - start) / (end - start) * (right - left)
    pieces = [f"<svg class='wave-thumb' viewBox='0 0 420 {height}' role='img' aria-label='{html.escape(event.description, quote=True)}'>",
              f"<rect width='420' height='{height}' fill='#0a1520'/>"]
    for time in sorted({start, event.time, end}):
        if time != event.time and abs(x(time) - x(event.time)) < 35:
            continue
        pieces.append(f"<text x='{x(time)}' y='18' fill='#a6bfd3' font-size='12' text-anchor='middle'>{time}</text>")
    for i, (name, width, points) in enumerate(traces):
        y = 35 + i * 52
        leaf = signal_identity(name).rsplit(".", 1)[-1]
        pieces.append(f"<text x='10' y='{y + 17}' fill='#d7e8f9' font-size='12'>{html.escape(leaf)}</text>")
        for n, (time, state) in enumerate(points):
            next_time = points[n + 1][0] if n + 1 < len(points) else end
            if state is None or next_time <= time:
                continue
            unknown = bool(state.x_mask or state.z_mask)
            color = "#f2cd84" if unknown else "#77d9aa"
            if width == 1:
                if unknown:
                    pieces.append(f"<rect x='{x(time)}' y='{y + 4}' width='{x(next_time) - x(time)}' height='25' fill='#3b301d' stroke='{color}'/>")
                    if x(next_time) - x(time) > 25:
                        marker = "X" if state.x_mask else "Z"
                        pieces.append(f"<text x='{(x(time) + x(next_time)) / 2}' y='{y + 22}' text-anchor='middle' fill='{color}' font-size='11'>{marker}</text>")
                    continue
                yy = y + 4 if state.value else y + 29
                pieces.append(f"<path d='M{x(time)} {yy} H{x(next_time)}' stroke='{color}' fill='none'/>")
                if n + 1 < len(points) and points[n + 1][1] is not None:
                    after = y + 4 if points[n + 1][1].value else y + 29
                    pieces.append(f"<path d='M{x(next_time)} {yy} V{after}' stroke='{color}' fill='none'/>")
            else:
                w = x(next_time) - x(time)
                pieces.append(f"<rect x='{x(time)}' y='{y}' width='{w}' height='30' fill='#17324a' stroke='#70c8ff'/>")
                if w > 90:
                    value = "X/Z" if unknown else hex(state.value)
                    if not unknown and name == event.signal_path and event.fields:
                        decoded = decode_fields(f"{state.value:0{width}b}", event.fields)[0]
                        value = decoded["name"] + "=" + decoded["value"]
                    if len(value) > 18:
                        value = value[:9] + "…" + value[-6:]
                    pieces.append(f"<text x='{x(time) + w / 2}' y='{y + 20}' text-anchor='middle' fill='#cbe8ff' font-size='11'>{html.escape(value)}</text>")
    pieces.append(f"<path d='M{x(event.time)} 25 V{height - 10}' stroke='#f2cd84' stroke-dasharray='4 3'/></svg>")
    return {"svg": "".join(pieces), "start": start, "end": end, "timescale": timescale,
            "signal_paths": [name for name, _, _ in traces], "fields": decode_fields(event.raw_value, event.fields)}
