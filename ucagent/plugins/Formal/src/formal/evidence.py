"""Read bounded original tool observations without interpreting a DUT specification."""

from __future__ import annotations

import logging
from pathlib import Path
import re


LOGGER = logging.getLogger(__name__)


def trace_observations(path: Path, max_signals: int = 64) -> dict:
    """Read direct signals of every top scope at the last recorded timestamp.

    This is a stored sample, not a claim about the failing clock occurrence.
    Unknown/high-impedance bits remain explicit masks and are never presented as
    known zeros. Nested aliases are omitted to avoid redundant observations.
    """
    unavailable = {"status": "unavailable", "signals": [], "sample_kind": "last_recorded_sample_not_failure_cycle",
                   "next_action": "Review the original proof report; ask the operator to restore observation access if needed. Do not invent signal values."}
    if not path.is_file():
        return {**unavailable, "reason": "original_trace_not_available"}
    if path.stat().st_size > 32 * 1024 * 1024:
        return {**unavailable, "reason": "original_trace_exceeds_observation_budget"}
    reader = None
    try:
        from wavekit import VcdReader
        reader = VcdReader(str(path))
        sample_time = reader.end_time
        scope_names = {scope.full_name for scope in reader.top_scopes}
        references = [name for name in reader.file_handle.signals if name.rsplit(".", 1)[0] in scope_names]
        rows = []
        omitted = 0
        for reference in references:
            if len(rows) >= max_signals:
                omitted += 1
                continue
            signal = reader.file_handle[reference]
            width = int(signal.size)
            if not 0 < width <= 4096:
                omitted += 1
                continue
            raw = next((value for timestamp, value in reversed(signal.tv) if timestamp <= sample_time), None)
            if raw is None:
                rows.append({"name": reference, "width": width, "available": False})
                continue
            bits = raw.lower()
            if not bits or set(bits) - set("01xz") or len(bits) > width:
                rows.append({"name": reference, "width": width, "available": False})
                continue
            bits = bits.rjust(width, bits[0] if bits[0] in "xz" else "0")
            x_mask = int("".join("1" if bit == "x" else "0" for bit in bits), 2)
            z_mask = int("".join("1" if bit == "z" else "0" for bit in bits), 2)
            rows.append({"name": reference, "width": width, "available": True,
                         "value": hex(int(bits, 2)) if not (x_mask or z_mask) else None,
                         "bits": bits if x_mask or z_mask else None,
                         "unknown_mask": hex(x_mask), "z_mask": hex(z_mask)})
        return {"status": "available" if rows else "unavailable", "sampled_time": sample_time,
                "time_unit": str(reader.file_handle.timescale.get("unit", "unknown")),
                "time_magnitude": str(reader.file_handle.timescale.get("magnitude", "1")),
                "sample_kind": "last_recorded_sample_not_failure_cycle", "signals": rows,
                "total_signals": len(references), "omitted_signals": omitted, "truncated": bool(omitted),
                "next_action": "Compare these original observations with the stated specification. Expected behavior is not computed by this report."}
    except Exception:
        LOGGER.exception("Cannot read original Formal trace observations: %s", path)
        return {**unavailable, "reason": "original_observation_access_failed"}
    finally:
        if reader is not None:
            reader.close()


def original_inputs(path: Path) -> dict:
    """Expose a bounded original initialization without replaying or minimizing it."""
    values, total, truncated, value_truncated = [], 0, False, False
    if path.is_file():
        with path.open(encoding="utf-8", errors="replace") as stream:
            text = stream.read(32769)
        truncated = len(text) > 32768
        initialization = re.search(r"// initialization\s*initial\s+begin(.*?)\bend\b", text[:32768], re.DOTALL)
        if initialization:
            for name, width, bits in re.findall(r"([\w.$\[\]\\]+)\s*<=\s*(\d+)'b([01xzXZ]+)\s*;", initialization.group(1)):
                total += 1
                if len(values) >= 64:
                    continue
                width = int(width)
                unknown = bool(set(bits.lower()) & {"x", "z"})
                clipped = len(bits) > 4096 or width > 4096 or len(bits) > width
                value_truncated = value_truncated or clipped
                row = {"signal": name, "width": width,
                       "value": bits[:4096] if clipped or unknown else hex(int(bits, 2)),
                       "has_unknown": unknown}
                if clipped:
                    row.update(value_truncated=True, value_range="leading source digits only; not the complete signal value")
                values.append(row)
    return {"initial_values": values, "initial_values_only": True,
            "initial_values_truncated": truncated or value_truncated or total > len(values),
            "initial_values_observed_count": total, "witness_source_truncated": truncated}


def observation_text(evidence: dict) -> tuple[str, str]:
    """Project original machine facts into report fields, never expected semantics."""
    inputs = evidence.get("initial_values", [])
    trigger = "Original tool initialization: " + "; ".join(f"{item['signal']}={item['value']} (width={item['width']})" for item in inputs)
    if not inputs:
        trigger = "Tool result has no exported dynamic initialization; review the original report."
    if evidence.get("initial_values_truncated"):
        trigger += " [Partial initialization; inspect the original artifact.]"
    observation = evidence.get("trace_observations", {})
    actual = f"Original tool verdict: {evidence.get('raw_status', evidence.get('result', 'unknown'))}. "
    if observation.get("status") == "available":
        actual += f"Stored sample at {observation['sampled_time']} x {observation['time_magnitude']} {observation['time_unit']} (not asserted to be the failure cycle): "
        actual += "; ".join(f"{row['name']}={row.get('value') if row.get('value') is not None else row.get('bits', 'unavailable')} (width={row['width']})" for row in observation["signals"])
        if observation.get("truncated"):
            actual += " [Partial signal list; inspect the original artifact.]"
    else:
        actual += "Original signal observations are unavailable; no values are inferred."
    return trigger, actual
