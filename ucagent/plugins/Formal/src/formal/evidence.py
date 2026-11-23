"""Read bounded original tool observations without interpreting a DUT specification."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from hashlib import file_digest, sha256
import logging
from pathlib import Path
import re


LOGGER = logging.getLogger(__name__)
_VCD_EXPORT_DATE = re.compile(rb"\A\$date[ \t]*\r?\n[ \t]*[^\r\n$]{1,160}\r?\n\$end[ \t]*\r?\n")
_VCD_REVIEW_LIMIT = 32 * 1024 * 1024


class TraceChangedError(ValueError):
    """The original trace changed while deriving its stored sample."""


def same_vcd_payload(workspace: Path, previous: dict, current: dict) -> bool:
    """Compare two sealed traces while ignoring only the leading export date."""
    digests = []
    for evidence in (previous, current):
        artifact = evidence.get("trace_artifact")
        expected = evidence["evidence_ref"].get("trace_sha256")
        if not artifact or not expected:
            return False
        relative = Path(artifact)
        path = workspace / relative
        try:
            if (relative.is_absolute() or path.is_symlink() or path.suffix.lower() != ".vcd"
                    or not path.resolve().is_relative_to(workspace) or not path.is_file()
                    or path.stat().st_size > _VCD_REVIEW_LIMIT):
                return False
            with path.open("rb") as stream:
                payload = stream.read(_VCD_REVIEW_LIMIT + 1)
        except OSError:
            return False
        date = _VCD_EXPORT_DATE.match(payload)
        if len(payload) > _VCD_REVIEW_LIMIT or not date or sha256(payload).hexdigest() != expected:
            return False
        digests.append(sha256(memoryview(payload)[date.end():]).digest())
    return digests[0] == digests[1]


def trace_observations(path: Path, max_signals: int = 64, *, verified_sha256: str | None = None) -> dict:
    """Read direct signals of every top scope at the last recorded timestamp.

    This is a stored sample, not a claim about the failing clock occurrence.
    Unknown/high-impedance bits remain explicit masks and are never presented as
    known zeros. Nested aliases are omitted to avoid redundant observations.
    A caller supplying verified_sha256 must check the original file on every call.
    """
    unavailable = {"status": "unavailable", "signals": [], "sample_kind": "last_recorded_sample_not_failure_cycle",
                   "next_action": "Review the original proof report; ask the operator to restore observation access if needed. Do not invent signal values."}
    if not path.is_file():
        if verified_sha256 is not None:
            raise TraceChangedError("Original trace changed during observation extraction.")
        return {**unavailable, "reason": "original_trace_not_available"}
    if path.stat().st_size > _VCD_REVIEW_LIMIT:
        return {**unavailable, "reason": "original_trace_exceeds_observation_budget"}
    try:
        if verified_sha256 is not None:
            return deepcopy(_verified_trace_sample(path, max_signals, verified_sha256))
        return _read_trace_sample(path, max_signals)
    except TraceChangedError:
        raise
    except Exception:
        LOGGER.exception("Cannot read original Formal trace observations: %s", path)
        return {**unavailable, "reason": "original_observation_access_failed"}


@lru_cache(maxsize=32)
def _verified_trace_sample(path: Path, max_signals: int, digest: str) -> dict:
    """Reuse only derived observations for a caller-verified trace and sample limit."""
    result = _read_trace_sample(path, max_signals)
    try:
        with path.open("rb") as stream:
            current = file_digest(stream, "sha256").hexdigest()
    except OSError as exc:
        raise TraceChangedError("Original trace changed during observation extraction.") from exc
    if current != digest:
        raise TraceChangedError("Original trace changed during observation extraction.")
    return result


def _read_trace_sample(path: Path, max_signals: int) -> dict:
    """Read the original final stored sample without caching failed extraction."""
    from wavekit import VcdReader

    reader = VcdReader(str(path))
    try:
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
    finally:
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


def focus_property_observations(evidence, state, name):
    """Select original rows for identifiers in the frozen CK and its clock/reset."""
    from .skills.lib.formal_tools import _ck_to_sv_names

    spec = (state.get("semantic_inputs") or {}).get("spec") or {}
    label = name.rsplit(".", 1)[-1]
    matches = [(fc["id"], ck) for group in spec.get("function_groups", []) for fc in group["functions"]
               for ck in fc["check_points"] if _ck_to_sv_names(ck["id"], ck["style"])[1] == label]
    if len(matches) != 1:
        return {**evidence, "view": "full", "view_reason": "No unique archived CK matched the native label."}
    fc_id, ck = matches[0]
    body = ck.get("sva_body") or ""
    clock = ((state.get("batch_context") or {}).get("shared_environment") or {}).get("clock_reset") or {}
    names = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_$]*", re.sub(r"/\*.*?\*/|//[^\n]*", "", body, flags=re.S)))
    names.update(clock.get(key) for key in ("actual_clock", "actual_reset", "env_clock", "env_reset"))
    initial = [row for row in evidence["initial_values"] if row["signal"].rsplit(".", 1)[-1] in names]
    trace = evidence["trace_observations"]
    signals = [row for row in trace["signals"] if row["name"].rsplit(".", 1)[-1] in names]
    omitted = trace.get("total_signals", len(trace["signals"])) - len(signals)
    call = {"action": "evidence", "property_names": [name], "run_id": state["run_id"]}
    return {**evidence, "view": "property_signals", "ck_id": ck["id"], "sva_body": body,
            "initial_values": initial,
            "initial_values_truncated": evidence["initial_values_truncated"] or len(initial) < len(evidence["initial_values"]),
            "trace_observations": {**trace, "signals": signals, "omitted_signals": omitted, "truncated": bool(omitted)},
            "inspect_archived_fc": {"request": {"action": "inspect", "section": "spec", "run_id": state["run_id"],
                                               "query": fc_id}},
            "all_observations_call": {**call, "evidence_view": "full"},
            **({"trace_call": {**call, "trace_query": {"mode": "signals"}}} if evidence["trace_artifact"] else {})}


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
