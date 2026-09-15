# -*- coding: utf-8 -*-
"""Pre-layout PPA analysis backed by Yosys, OpenSTA, and TC waveforms."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any, ClassVar, Optional
from uuid import uuid4

from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from ucagent.util.functions import make_llm_tool_ret
from ucagent.tools.fileops import is_file_writeable
from ucagent.tools.uctool import UCTool
from ucagent.util.log import info


_TOP_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_SCOPE_RE = re.compile(
    r"^[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*$"
)
_RANGED_REFERENCE_RE = re.compile(
    r"^(?P<name>.+?)\[(?P<left>-?\d+)(?::(?P<right>-?\d+))?\]$"
)
_STATE_CELL_RE = re.compile(r"(?:^|[_$])(dff|sdff|adff|dlatch|mem)(?:[_$]|$)", re.I)
_REPORT_ID_RE = re.compile(r"^ppa-[0-9a-f]{32}$")
_PPA_CACHE_LOCK = threading.Lock()


class AnalyzePPAArgs(BaseModel):
    """Strict public arguments for :class:`AnalyzePPA`."""

    model_config = ConfigDict(extra="forbid")

    rtl_files: list[str] | None = Field(
        default=None,
        description=(
            "Workspace-relative Verilog .v source files for one design. "
            "Omit to derive from the current RTL backend manifest."
        ),
    )
    top_module: str | None = Field(
        default=None,
        description=(
            "Exact top-level Verilog module name to elaborate and analyze. "
            "Omit to derive from the current RTL backend manifest."
        ),
    )
    waveform_files: list[str] | None = Field(
        default=None,
        description=(
            "Ordered workspace-relative .vcd/.fst files from independent performance-test "
            "TC runs. Their activities are duration-weighted internally. "
            "Omit to derive from the current performance manifest."
        ),
    )
    waveform_scope: str | None = Field(
        default=None,
        description=(
            "Common dotted waveform hierarchy containing the DUT ports, for example "
            "testbench.dut. Omit to derive from the current performance manifest."
        ),
    )
    liberty_file: str | None = Field(
        default=None,
        description=(
            "Optional workspace-relative Liberty .lib file. The bundled Nangate45 "
            "reference library is used when omitted."
        ),
    )
    sdc_file: str | None = Field(
        default=None,
        description="Optional workspace-relative SDC timing constraints file.",
    )
    clock_port: str | None = Field(
        default=None,
        description="Top-level clock port used with clock_period_ns when no SDC is supplied.",
    )
    clock_period_ns: float | None = Field(
        default=None,
        gt=0,
        description="Positive clock period in nanoseconds, paired with clock_port.",
    )
    report_path: str | None = Field(
        default=None,
        description=(
            "Optional writable workspace-relative .json destination. Defaults to "
            "{OUT}/{top_module}_ppa_report.json."
        ),
    )
    baseline_report_id: str | None = Field(
        default=None,
        description=(
            "Optional report_id from the internal PPA cache. The current report is "
            "compared against that baseline after analysis."
        ),
    )
    max_timing_paths: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum critical timing paths retained in the detailed report.",
    )
    max_power_instances: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum highest-power instances retained in the detailed report.",
    )
    timeout: int = Field(
        default=300,
        ge=10,
        le=3600,
        description="Overall Yosys/OpenSTA execution deadline in seconds.",
    )

    @model_validator(mode="after")
    def validate_contract(self):
        """Reject ambiguous constraints and malformed design identifiers.

        The four workspace-derivable fields may arrive as ``None``; format
        validation is deferred until :meth:`AnalyzePPA._run` fills them from
        the manifests, so this validator only checks fields that are actually
        present.
        """

        if self.top_module is not None and not _TOP_MODULE_RE.fullmatch(self.top_module):
            raise ValueError("top_module must be an ordinary Verilog identifier")
        if self.waveform_scope is not None and not _SCOPE_RE.fullmatch(self.waveform_scope):
            raise ValueError("waveform_scope must be a dotted waveform hierarchy")
        explicit_clock = self.clock_port is not None or self.clock_period_ns is not None
        if explicit_clock and (self.clock_port is None or self.clock_period_ns is None):
            raise ValueError("clock_port and clock_period_ns must be provided together")
        if self.sdc_file is not None and explicit_clock:
            raise ValueError(
                "sdc_file and explicit clock_port/clock_period_ns are mutually exclusive"
            )
        if self.clock_port is not None and not _TOP_MODULE_RE.fullmatch(self.clock_port):
            raise ValueError("clock_port must be an ordinary Verilog identifier")
        if self.baseline_report_id is not None and not _REPORT_ID_RE.fullmatch(
            self.baseline_report_id
        ):
            raise ValueError("baseline_report_id must match ppa- followed by 32 lowercase hex characters")
        return self


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


def _sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest for one file."""

    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _diagnostic(
    stage: str,
    error_code: str,
    error: str,
    next_action: str,
    **details: Any,
) -> dict[str, Any]:
    """Build one bounded, task-oriented diagnostic mapping."""

    result = {
        "stage": stage,
        "error_code": error_code,
        "error": error,
        "next_action": next_action,
    }
    result.update({key: value for key, value in details.items() if value is not None})
    return result


def _json_safe(value: Any) -> Any:
    """Recursively replace non-finite floats with JSON null."""

    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _redact_private_paths(value: Any, paths: tuple[Path, ...]) -> Any:
    """Remove trusted workflow source identities from a report tree."""

    if isinstance(value, dict):
        return {key: _redact_private_paths(item, paths) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_private_paths(item, paths) for item in value]
    if isinstance(value, str):
        redacted = value
        for path in sorted(paths, key=lambda item: len(str(item)), reverse=True):
            for token in {
                str(path),
                path.as_posix(),
                str(path.parent),
                path.parent.as_posix(),
                path.name,
            }:
                if token:
                    redacted = redacted.replace(token, "<internal-analysis-source>")
        return redacted
    return value


def _tail(text: str, limit: int = 4000) -> str:
    """Return a bounded subprocess log excerpt favoring the final diagnostics."""

    if len(text) <= limit:
        return text
    return f"... [truncated {len(text) - limit} characters]\n{text[-limit:]}"


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
    expected: list[_InputBit],
) -> list[tuple[str, int]]:
    """Resolve one VCD reference into value-string positions for expected input bits."""

    by_port: dict[str, list[_InputBit]] = defaultdict(list)
    for bit in expected:
        by_port[bit.port].append(bit)
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

    def covered(scope: str) -> set[str]:
        """Return expected input bits declared directly below one scope."""

        prefix = f"{scope}."
        result: set[str] = set()
        for signal_info in header.data.values():
            width = int(signal_info.size)
            for reference in signal_info.references:
                if reference.startswith(prefix):
                    result.update(
                        bit_key
                        for bit_key, _ in _reference_bit_positions(
                            reference[len(prefix) :], width, expected_bits
                        )
                    )
        return result

    if covered(requested_scope) == expected_keys:
        return requested_scope

    candidates: set[str] = set()
    for signal_info in header.data.values():
        for reference in signal_info.references:
            parts = reference.split(".")
            for cut in range(1, len(parts)):
                scope = ".".join(parts[:cut])
                if scope in candidates:
                    continue
                if covered(scope) == expected_keys:
                    candidates.add(scope)
    if candidates:
        return sorted(candidates, key=lambda value: (-value.count("."), value))[0]
    return requested_scope


def _convert_fst_to_vcd(source: Path, destination: Path) -> None:
    """Convert an FST waveform to a temporary VCD through pylibfst's streaming API."""

    try:
        import pylibfst  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "pylibfst is required for .fst input; install pylibfst>=0.2.1,<0.3.0"
        ) from exc
    reader = pylibfst.lib.fstReaderOpen(os.fsencode(source))
    if reader == pylibfst.ffi.NULL:
        raise ValueError(f"pylibfst could not open FST file: {source.name}")
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
    candidates: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for identifier, signal_info in header.data.items():
        width = int(signal_info.size)
        for reference in signal_info.references:
            if not reference.startswith(prefix):
                continue
            positions = _reference_bit_positions(
                reference[len(prefix) :], width, expected_bits
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


def _load_json_file(path: Path) -> Any:
    """Load a JSON artifact and identify an absent or malformed report clearly."""

    if not path.is_file():
        raise ValueError(f"expected report was not produced: {path.name}")
    with path.open("r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


def _load_opensta_json(path: Path, *, allow_empty: bool = False) -> tuple[Any, str]:
    """Load OpenSTA JSON while retaining warnings redirected before the JSON value."""

    if not path.is_file():
        raise ValueError(f"expected OpenSTA report was not produced: {path.name}")
    raw = path.read_text(encoding="utf-8", errors="replace")
    if not raw.strip() and allow_empty:
        return {"checks": []}, ""
    starts = [index for token in ("{", "[") if (index := raw.find(token)) >= 0]
    if not starts:
        raise ValueError(f"OpenSTA report contains no JSON value: {_tail(raw, 1000)}")
    start = min(starts)
    try:
        value, _ = json.JSONDecoder().raw_decode(raw[start:])
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"OpenSTA emitted malformed JSON in {path.name}: {exc}; "
            f"excerpt={_tail(raw, 1000)}"
        ) from exc
    return value, raw[:start].strip()


def _module_stats(stats: dict[str, Any], top_module: str) -> dict[str, Any]:
    """Select the top-module block across supported Yosys stat JSON layouts."""

    modules = stats.get("modules", {})
    if top_module in modules:
        return modules[top_module]
    escaped = f"\\{top_module}"
    if escaped in modules:
        return modules[escaped]
    if len(modules) == 1:
        return next(iter(modules.values()))
    return stats


def _classify_design(
    generic_stats: dict[str, Any],
    generic_json: dict[str, Any],
    top_module: str,
) -> tuple[str, dict[str, Any]]:
    """Classify statefulness only from elaborated/synthesized Yosys evidence."""

    module_stats = _module_stats(generic_stats, top_module)
    cell_types = module_stats.get("num_cells_by_type", {})
    state_cells = {
        str(cell_type): int(count)
        for cell_type, count in cell_types.items()
        if _STATE_CELL_RE.search(str(cell_type)) and int(count) > 0
    }
    memory_bits = int(module_stats.get("num_memory_bits", 0) or 0)
    modules = generic_json.get("modules", {})
    blackboxes = [
        name
        for name, module in modules.items()
        if str(module.get("attributes", {}).get("blackbox", "0")).lstrip("0") == "1"
    ]
    evidence = {
        "source": "yosys_post_synth_pre_technology_mapping",
        "state_cell_types": state_cells,
        "memory_bits": memory_bits,
        "blackbox_modules": blackboxes,
        "cell_types_examined": len(cell_types),
    }
    if blackboxes:
        return "unknown", evidence
    if state_cells or memory_bits:
        return "sequential", evidence
    return "combinational", evidence


def _power_totals(power_json: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Normalize OpenSTA group or instance power JSON into totals and rows."""

    rows: list[dict[str, Any]] = []
    if isinstance(power_json, list):
        rows = [item for item in power_json if isinstance(item, dict)]
    elif isinstance(power_json, dict):
        if isinstance(power_json.get("Total"), dict):
            rows = [
                {"group": name, **values}
                for name, values in power_json.items()
                if isinstance(values, dict)
            ]
        for key in ("power", "groups", "instances", "records"):
            value = power_json.get(key)
            if isinstance(value, list):
                rows = [item for item in value if isinstance(item, dict)]
                break
        if not rows and all(
            key in power_json for key in ("internal", "switching", "leakage")
        ):
            rows = [power_json]
    total_row = next(
        (
            row
            for row in rows
            if str(row.get("group", row.get("name", ""))).lower() == "total"
        ),
        rows[-1] if len(rows) == 1 else None,
    )
    if total_row is None:
        raise ValueError("OpenSTA power JSON does not contain a Total row")

    def number(*keys: str) -> float | None:
        """Return the first finite numeric value from equivalent field names."""

        for key in keys:
            if key in total_row:
                try:
                    value = float(total_row[key])
                except (TypeError, ValueError):
                    continue
                return value if math.isfinite(value) else None
        return None

    internal = number("internal", "internal_power")
    switching = number("switching", "switching_power")
    leakage = number("leakage", "leakage_power")
    total = number("total", "total_power")
    dynamic = (
        internal + switching
        if internal is not None and switching is not None
        else None
    )
    if total is None and dynamic is not None and leakage is not None:
        total = dynamic + leakage
    return {
        "total_w": total,
        "dynamic_w": dynamic,
        "internal_w": internal,
        "switching_w": switching,
        "leakage_w": leakage,
        "unit": "W",
    }, rows


def _power_rows(power_json: Any) -> list[dict[str, Any]]:
    """Extract OpenSTA power rows without requiring an aggregate Total entry."""

    if isinstance(power_json, list):
        return [item for item in power_json if isinstance(item, dict)]
    if isinstance(power_json, dict):
        if power_json and all(
            isinstance(value, dict) for value in power_json.values()
        ):
            return [
                {"group": name, **values}
                for name, values in power_json.items()
            ]
        for key in ("power", "groups", "instances", "records"):
            value = power_json.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if any(
            key in power_json
            for key in ("internal", "switching", "leakage", "total")
        ):
            return [power_json]
    return []


def _timing_paths(timing_json: Any) -> list[dict[str, Any]]:
    """Find OpenSTA path dictionaries across its supported JSON wrappers."""

    if isinstance(timing_json, list):
        return [item for item in timing_json if isinstance(item, dict)]
    if not isinstance(timing_json, dict):
        return []
    for key in ("checks", "paths", "path_groups"):
        value = timing_json.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if any(key in timing_json for key in ("arrival", "delay", "slack")):
        return [timing_json]
    return []


def _timing_summary(paths: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive critical delay, WNS, TNS, and limiting endpoints from timing paths."""

    def finite_from(row: dict[str, Any], *keys: str) -> float | None:
        """Read a finite path metric, deriving arrival from source points if needed."""

        for key in keys:
            value = row.get(key)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                return float(value)
        if any(key in {"delay", "arrival", "path_delay"} for key in keys):
            source_path = row.get("source_path")
            if isinstance(source_path, list):
                arrivals = [
                    float(point["arrival"])
                    for point in source_path
                    if isinstance(point, dict)
                    and isinstance(point.get("arrival"), (int, float))
                    and math.isfinite(float(point["arrival"]))
                ]
                if arrivals:
                    return max(arrivals)
        return None

    delays = [
        value
        for row in paths
        if (value := finite_from(row, "delay", "arrival", "path_delay")) is not None
    ]
    slacks = [
        value
        for row in paths
        if (value := finite_from(row, "slack")) is not None
    ]
    limiting = None
    if paths:
        row = max(
            paths,
            key=lambda item: finite_from(item, "delay", "arrival", "path_delay")
            or float("-inf"),
        )
        limiting = {
            key: row[key]
            for key in ("startpoint", "endpoint", "path_group", "clock", "delay", "slack")
            if key in row
        }
    critical_seconds = max(delays) if delays else None
    if limiting is not None:
        limiting["critical_path_delay_ns"] = (
            critical_seconds * 1e9 if critical_seconds is not None else None
        )
    return {
        "metric_kind": "critical_path_delay",
        "critical_path_delay_ns": (
            critical_seconds * 1e9 if critical_seconds is not None else None
        ),
        "equivalent_max_frequency_hz": (
            1.0 / critical_seconds if critical_seconds and critical_seconds > 0 else None
        ),
        "wns_ns": min(slacks) * 1e9 if slacks else None,
        "tns_ns": sum(value for value in slacks if value < 0) * 1e9 if slacks else None,
        "limiting_path": limiting,
    }


def _parse_sta_metric(text: str, metric: str) -> float | None:
    """Parse one finite OpenSTA text metric expressed in configured ns units."""

    patterns = {
        "wns": r"worst\s+slack\s+max\s+(?P<value>\S+)",
        "tns": r"tns\s+max\s+(?P<value>\S+)",
    }
    match = re.search(patterns[metric], text, re.I)
    if match is None:
        return None
    try:
        value = float(match.group("value"))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


@dataclass(frozen=True)
class _MetricSpec:
    """One stable PPA metric and the direction considered beneficial."""

    name: str
    path: tuple[str, ...]
    preference: str
    unit: str


_COMPARISON_METRICS: dict[str, tuple[_MetricSpec, ...]] = {
    "area": (
        _MetricSpec("total", ("summary", "area", "total"), "lower", "liberty_area_unit"),
        _MetricSpec("sequential", ("summary", "area", "sequential"), "lower", "liberty_area_unit"),
        _MetricSpec("combinational", ("summary", "area", "combinational"), "lower", "liberty_area_unit"),
        _MetricSpec("cell_count", ("summary", "area", "cell_count"), "lower", "cells"),
        _MetricSpec(
            "sequential_cell_count",
            ("summary", "area", "sequential_cell_count"),
            "lower",
            "cells",
        ),
        _MetricSpec(
            "combinational_cell_count",
            ("summary", "area", "combinational_cell_count"),
            "lower",
            "cells",
        ),
    ),
    "timing": (
        _MetricSpec(
            "critical_path_delay_ns",
            ("summary", "timing", "critical_path_delay_ns"),
            "lower",
            "ns",
        ),
        _MetricSpec(
            "maximum_frequency_hz",
            ("summary", "timing", "maximum_frequency_hz"),
            "higher",
            "Hz",
        ),
        _MetricSpec(
            "equivalent_max_frequency_hz",
            ("summary", "timing", "equivalent_max_frequency_hz"),
            "higher",
            "Hz",
        ),
        _MetricSpec("wns_ns", ("summary", "timing", "wns_ns"), "higher", "ns"),
        _MetricSpec("tns_ns", ("summary", "timing", "tns_ns"), "higher", "ns"),
    ),
    "power": (
        _MetricSpec("total_w", ("summary", "power", "total_w"), "lower", "W"),
        _MetricSpec("dynamic_w", ("summary", "power", "dynamic_w"), "lower", "W"),
        _MetricSpec("internal_w", ("summary", "power", "internal_w"), "lower", "W"),
        _MetricSpec("switching_w", ("summary", "power", "switching_w"), "lower", "W"),
        _MetricSpec("leakage_w", ("summary", "power", "leakage_w"), "lower", "W"),
    ),
}


def _nested_value(mapping: dict[str, Any], path: tuple[str, ...]) -> Any:
    """Read one nested report value without accepting a structurally different shape."""

    value: Any = mapping
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _metric_change(
    baseline: Any,
    current: Any,
    *,
    preference: str,
    unit: str,
    comparable: bool,
) -> dict[str, Any]:
    """Describe numeric direction and improvement semantics for one metric."""

    result = {
        "baseline": baseline,
        "current": current,
        "absolute_change": None,
        "percent_change": None,
        "direction": "unavailable",
        "assessment": "unavailable",
        "preference": preference,
        "unit": unit,
    }
    if not isinstance(baseline, (int, float)) or isinstance(baseline, bool):
        return result
    if not isinstance(current, (int, float)) or isinstance(current, bool):
        return result
    baseline_number = float(baseline)
    current_number = float(current)
    if not math.isfinite(baseline_number) or not math.isfinite(current_number):
        return result
    delta = current_number - baseline_number
    if math.isclose(current_number, baseline_number, rel_tol=1e-9, abs_tol=1e-15):
        delta = 0.0
        direction = "unchanged"
    else:
        direction = "increased" if delta > 0 else "decreased"
    if baseline_number != 0:
        percent_change = delta / abs(baseline_number) * 100.0
    elif delta == 0:
        percent_change = 0.0
    else:
        percent_change = None
    if not comparable:
        assessment = "not_comparable"
    elif direction == "unchanged":
        assessment = "unchanged"
    elif preference == "lower":
        assessment = "improved" if delta < 0 else "regressed"
    elif preference == "higher":
        assessment = "improved" if delta > 0 else "regressed"
    else:
        assessment = "neutral"
    result.update(
        {
            "absolute_change": delta,
            "percent_change": percent_change,
            "direction": direction,
            "assessment": assessment,
        }
    )
    return result


def _report_waveform_paths(report: dict[str, Any]) -> list[str]:
    """Return the ordered performance-TC path identity from report provenance."""

    waveforms = report.get("provenance", {}).get("waveform_files", [])
    return [
        item["path"]
        for item in waveforms
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    ]


def _comparison_compatibility(
    baseline: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    """Explain whether area, timing, and power changes share valid foundations."""

    baseline_provenance = baseline.get("provenance", {})
    current_provenance = current.get("provenance", {})
    same_top = baseline_provenance.get("top_module") == current_provenance.get(
        "top_module"
    )
    same_rtl_libraries = baseline_provenance.get(
        "rtl_libraries"
    ) == current_provenance.get("rtl_libraries")
    same_liberty = baseline_provenance.get("liberty_sha256") == current_provenance.get(
        "liberty_sha256"
    ) and baseline_provenance.get("liberty_sha256") is not None
    same_constraints = (
        baseline_provenance.get("sdc_sha256") == current_provenance.get("sdc_sha256")
        and baseline_provenance.get("clock_constraint")
        == current_provenance.get("clock_constraint")
    )
    same_timing_kind = _nested_value(
        baseline, ("summary", "timing", "metric_kind")
    ) == _nested_value(current, ("summary", "timing", "metric_kind"))
    same_waveform_scope = baseline_provenance.get(
        "waveform_scope"
    ) == current_provenance.get("waveform_scope")
    same_tc_paths = _report_waveform_paths(baseline) == _report_waveform_paths(current)
    baseline_activity = _nested_value(
        baseline, ("waveform_aggregation", "merged_input_bits")
    )
    current_activity = _nested_value(
        current, ("waveform_aggregation", "merged_input_bits")
    )
    same_input_activity = (
        isinstance(baseline_activity, list)
        and isinstance(current_activity, list)
        and baseline_activity == current_activity
    )
    reliable_power = bool(
        _nested_value(baseline, ("waveform_aggregation", "reliable"))
    ) and bool(_nested_value(current, ("waveform_aggregation", "reliable")))

    def group(reasons: list[str]) -> dict[str, Any]:
        """Build one compact compatibility group from its blocking reasons."""

        return {"comparable": not reasons, "reasons": reasons}

    area_reasons = []
    if not same_top:
        area_reasons.append("top_module_changed")
    if not same_rtl_libraries:
        area_reasons.append("rtl_library_set_changed")
    if not same_liberty:
        area_reasons.append("liberty_changed_or_unknown")
    timing_reasons = list(area_reasons)
    if not same_constraints:
        timing_reasons.append("timing_constraints_changed")
    if not same_timing_kind:
        timing_reasons.append("timing_metric_kind_changed")
    power_reasons = list(area_reasons)
    if not same_waveform_scope:
        power_reasons.append("waveform_scope_changed")
    if not same_tc_paths:
        power_reasons.append("performance_tc_set_changed")
    if not same_input_activity:
        power_reasons.append("merged_input_activity_changed_or_unknown")
    if not reliable_power:
        power_reasons.append("waveform_activity_unreliable")
    result = {
        "area": group(area_reasons),
        "timing": group(timing_reasons),
        "power": group(power_reasons),
    }
    result["overall"] = all(item["comparable"] for item in result.values())
    return result


def _clock_metric_changes(
    baseline: dict[str, Any],
    current: dict[str, Any],
    *,
    comparable: bool,
) -> list[dict[str, Any]]:
    """Compare per-clock period and frequency metrics by exact clock name."""

    def clocks(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Index valid clock rows from one report summary."""

        rows = _nested_value(report, ("summary", "timing", "clocks"))
        if not isinstance(rows, list):
            return {}
        return {
            row["clock"]: row
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("clock"), str)
        }

    baseline_clocks = clocks(baseline)
    current_clocks = clocks(current)
    changes = []
    for clock in sorted(set(baseline_clocks) | set(current_clocks)):
        baseline_row = baseline_clocks.get(clock, {})
        current_row = current_clocks.get(clock, {})
        changes.append(
            {
                "clock": clock,
                "minimum_period_ns": _metric_change(
                    baseline_row.get("minimum_period_ns"),
                    current_row.get("minimum_period_ns"),
                    preference="lower",
                    unit="ns",
                    comparable=comparable,
                ),
                "maximum_frequency_hz": _metric_change(
                    baseline_row.get("maximum_frequency_hz"),
                    current_row.get("maximum_frequency_hz"),
                    preference="higher",
                    unit="Hz",
                    comparable=comparable,
                ),
            }
        )
    return changes


def _cell_type_changes(
    baseline: dict[str, Any], current: dict[str, Any], limit: int = 50
) -> dict[str, Any]:
    """Return the largest mapped cell-count changes for implementation diagnosis."""

    baseline_cells = _nested_value(baseline, ("details", "area_by_cell_type"))
    current_cells = _nested_value(current, ("details", "area_by_cell_type"))
    baseline_cells = baseline_cells if isinstance(baseline_cells, dict) else {}
    current_cells = current_cells if isinstance(current_cells, dict) else {}
    rows = []
    for cell_type in set(baseline_cells) | set(current_cells):
        old = int(baseline_cells.get(cell_type, 0) or 0)
        new = int(current_cells.get(cell_type, 0) or 0)
        if old == new:
            continue
        rows.append(
            {
                "cell_type": cell_type,
                "baseline_count": old,
                "current_count": new,
                "count_change": new - old,
                "direction": "increased" if new > old else "decreased",
            }
        )
    rows.sort(key=lambda item: (-abs(item["count_change"]), item["cell_type"]))
    return {
        "total_changed_cell_types": len(rows),
        "shown": min(len(rows), limit),
        "omitted": max(0, len(rows) - limit),
        "changes": rows[:limit],
    }


def _compare_reports(
    baseline: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    """Build the canonical structured diff between one baseline and current report."""

    if baseline.get("schema_version") != "1.1":
        raise ValueError(
            "baseline report schema_version must be 1.1; rerun AnalyzePPA to create a current cache entry"
        )
    compatibility = _comparison_compatibility(baseline, current)
    metrics: dict[str, Any] = {}
    key_changes = []
    assessment_counts = {
        "improved": 0,
        "regressed": 0,
        "unchanged": 0,
        "not_comparable": 0,
        "unavailable": 0,
        "neutral": 0,
    }
    for group_name, specs in _COMPARISON_METRICS.items():
        group_metrics = {}
        comparable = compatibility[group_name]["comparable"]
        for spec in specs:
            change = _metric_change(
                _nested_value(baseline, spec.path),
                _nested_value(current, spec.path),
                preference=spec.preference,
                unit=spec.unit,
                comparable=comparable,
            )
            group_metrics[spec.name] = change
            assessment_counts[change["assessment"]] += 1
            if change["direction"] != "unchanged" and change["direction"] != "unavailable":
                key_changes.append(
                    {
                        "group": group_name,
                        "metric": spec.name,
                        "baseline": change["baseline"],
                        "current": change["current"],
                        "absolute_change": change["absolute_change"],
                        "percent_change": change["percent_change"],
                        "direction": change["direction"],
                        "assessment": change["assessment"],
                        "unit": spec.unit,
                    }
                )
        metrics[group_name] = group_metrics
    key_changes.sort(
        key=lambda item: (
            0 if item["assessment"] == "regressed" else 1,
            -abs(item["percent_change"] or 0.0),
            item["group"],
            item["metric"],
        )
    )
    metrics["timing"]["clocks"] = _clock_metric_changes(
        baseline,
        current,
        comparable=compatibility["timing"]["comparable"],
    )
    return {
        "status": "success",
        "baseline_report_id": baseline.get("report_id"),
        "current_report_id": current.get("report_id"),
        "baseline_created_at": baseline.get("created_at"),
        "compatibility": compatibility,
        "summary": {
            "assessment_counts": assessment_counts,
            "key_changes": key_changes[:20],
            "key_changes_omitted": max(0, len(key_changes) - 20),
        },
        "metrics": metrics,
        "detail_changes": {
            "status": {
                "baseline": baseline.get("status"),
                "current": current.get("status"),
                "changed": baseline.get("status") != current.get("status"),
            },
            "design_type": {
                "baseline": _nested_value(baseline, ("summary", "design_type")),
                "current": _nested_value(current, ("summary", "design_type")),
                "changed": _nested_value(baseline, ("summary", "design_type"))
                != _nested_value(current, ("summary", "design_type")),
            },
            "limiting_path": {
                "baseline": _nested_value(
                    baseline, ("summary", "timing", "limiting_path")
                ),
                "current": _nested_value(
                    current, ("summary", "timing", "limiting_path")
                ),
            },
            "area_by_cell_type": _cell_type_changes(baseline, current),
        },
    }


def compare_ppa_reports(
    baseline: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    """Compare two schema-1.1 PPA reports without running analysis tools."""

    if not isinstance(baseline, dict) or not isinstance(current, dict):
        raise TypeError("baseline and current PPA reports must be mappings")
    if current.get("schema_version") != "1.1":
        raise ValueError(
            "current report schema_version must be 1.1; rerun AnalyzePPA"
        )
    return _compare_reports(baseline, current)


class AnalyzePPA(UCTool):
    """Analyze pre-layout area, timing, and waveform-driven power for Verilog RTL."""

    name: str = "AnalyzePPA"
    description: str = (
        "Synthesize one Verilog design and produce a structured pre-layout PPA report. "
        "Provide all .v RTL sources, the exact top module, a common DUT waveform scope, "
        "and a list of independent .vcd/.fst performance-test TC waveforms. The tool "
        "validates every TC, merges input activity by total simulated duration, runs "
        "Yosys and OpenSTA, automatically determines whether the synthesized design is "
        "combinational or sequential, and reports area, timing or equivalent maximum "
        "frequency, power, detailed breakdowns, hotspots, diagnostics, and provenance. "
        "Every report receives a unique report_id and is retained in the internal cache; "
        "provide baseline_report_id to compare the current metrics with a cached report. "
        "The cache retains the newest 100 reports by default. Paths must be workspace-relative. "
        "Do not concatenate waveforms before calling."
    )
    args_schema: Optional[ArgsSchema] = AnalyzePPAArgs
    return_direct: bool = False
    call_lock_arguments: tuple[str, ...] = ()

    workspace: str = Field(default=".", description="UCAgent workspace root.")
    output_dir: str = Field(default="output", description="Default report directory.")
    cache_limit: int = Field(
        default=100,
        exclude=True,
        repr=False,
        description="Maximum number of recent reports retained in the internal cache.",
    )
    write_dirs: list[str] | None = Field(default=None, exclude=True, repr=False)
    un_write_dirs: list[str] | None = Field(default=None, exclude=True, repr=False)
    _active_processes: set[subprocess.Popen] = PrivateAttr(default_factory=set)
    _process_lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)

    _DEFAULT_LIBERTY: ClassVar[Path] = (
        Path(__file__).resolve().parent
        / "assets"
        / "NangateOpenCellLibrary_typical.lib"
    )

    def __init__(
        self,
        workspace: str = ".",
        output_dir: str = "output",
        cache_limit: int = 100,
        write_dirs: list[str] | None = None,
        un_write_dirs: list[str] | None = None,
        **kwargs,
    ) -> None:
        """Configure workspace confinement and report write permissions."""

        super().__init__(**kwargs)
        self.workspace = str(Path(workspace).resolve())
        output = Path(output_dir)
        if output.is_absolute():
            try:
                output = output.resolve(strict=False).relative_to(self.workspace)
            except ValueError as exc:
                raise ValueError("output_dir must be inside the workspace") from exc
        self.output_dir = output.as_posix()
        if isinstance(cache_limit, bool) or not isinstance(cache_limit, int):
            raise ValueError("cache_limit must be an integer")
        if cache_limit < 1 or cache_limit > 10000:
            raise ValueError("cache_limit must be between 1 and 10000")
        self.cache_limit = cache_limit
        self.write_dirs = list(write_dirs) if write_dirs is not None else None
        self.un_write_dirs = list(un_write_dirs) if un_write_dirs is not None else None

    def cb_force_exit(self) -> None:
        """Terminate every currently active process group on cancellation or timeout."""

        with self._process_lock:
            processes = list(self._active_processes)
        for process in processes:
            if process.poll() is not None:
                continue
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:  # pragma: no cover - exercised only on Windows
                    process.kill()
            except ProcessLookupError:
                continue

    def _resolve_input(self, value: str, suffixes: set[str] | None) -> Path:
        """Resolve an existing regular file without allowing workspace escape."""

        if not isinstance(value, str) or not value.strip():
            raise ValueError("input paths must be non-empty strings")
        normalized = value.replace("\\", "/")
        if any(ord(character) < 32 for character in normalized):
            raise ValueError(f"input path contains a control character: {value!r}")
        pure = PurePosixPath(normalized)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"path must remain relative to the workspace: {value}")
        lexical = Path(self.workspace) / pure
        resolved = lexical.resolve(strict=True)
        try:
            resolved.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError(f"path escapes the workspace: {value}") from exc
        if resolved != lexical.absolute() and any(
            parent.is_symlink()
            for parent in [lexical, *lexical.parents]
            if parent != Path(self.workspace).parent
        ):
            raise ValueError(f"symbolic links are not accepted for input paths: {value}")
        if not resolved.is_file():
            raise ValueError(f"input is not a regular file: {value}")
        if suffixes is not None and resolved.suffix.lower() not in suffixes:
            raise ValueError(
                f"input has unsupported extension {resolved.suffix!r}: {value}; "
                f"expected one of {sorted(suffixes)}"
            )
        return resolved

    def _resolve_report(self, value: str) -> tuple[Path, str]:
        """Resolve a writable JSON destination and reject symlink traversal."""

        normalized = value.replace("\\", "/")
        if any(ord(character) < 32 for character in normalized):
            raise ValueError("report_path contains a control character")
        pure = PurePosixPath(normalized)
        if pure.is_absolute() or ".." in pure.parts or pure.as_posix() in {"", "."}:
            raise ValueError("report_path must be a workspace-relative file path")
        if pure.suffix.lower() != ".json":
            raise ValueError("report_path must end with .json")
        allowed, reason = is_file_writeable(
            pure.as_posix(), self.un_write_dirs, self.write_dirs
        )
        if not allowed:
            raise ValueError(reason)
        lexical = Path(self.workspace) / pure
        current = Path(self.workspace)
        for part in pure.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(f"report_path traverses a symbolic link: {value}")
        resolved_parent = lexical.parent.resolve(strict=False)
        try:
            resolved_parent.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("report_path escapes the workspace") from exc
        return lexical, pure.as_posix()

    @staticmethod
    def _trim_instance_power(path: Path, limit: int | None) -> None:
        """Keep only the top ``limit`` instances by total power in the JSON.

        The guarded ``-instances [get_cells *]`` fallback lists every mapped
        cell; sorting here keeps the artifact the same size the ranking flag
        would have produced.
        """

        if not limit or not path.is_file():
            return
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(rows, list) or len(rows) <= limit:
            return

        def total(row):
            for key in ("total", "Total", "total_power"):
                value = row.get(key) if isinstance(row, dict) else None
                if isinstance(value, (int, float)):
                    return value
                if isinstance(value, dict):
                    for sub in value.values():
                        if isinstance(sub, (int, float)):
                            return sub
            return 0.0

        rows.sort(key=total, reverse=True)
        path.write_text(
            json.dumps(rows[:limit], indent=2), encoding="utf-8"
        )

    def _run_process(
        self,
        command: list[str],
        cwd: Path,
        deadline: float,
    ) -> subprocess.CompletedProcess[str]:
        """Run one external tool without a shell under the shared deadline."""

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("PPA analysis deadline expired")
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=(os.name == "posix"),
        )
        with self._process_lock:
            self._active_processes.add(process)
        try:
            stdout, stderr = process.communicate(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:  # pragma: no cover - exercised only on Windows
                process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:  # pragma: no cover - exercised only on Windows
                    process.kill()
                stdout, stderr = process.communicate()
            raise TimeoutError(
                f"command exceeded the remaining PPA timeout: {command[0]}"
            ) from exc
        finally:
            with self._process_lock:
                self._active_processes.discard(process)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)

    @staticmethod
    def _yosys_quote(value: str) -> str:
        """Quote one string for a Yosys command script."""

        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    @staticmethod
    def _tcl_brace(value: str) -> str:
        """Quote one value as a Tcl brace word."""

        escaped = value.replace("\\", "\\\\")
        escaped = escaped.replace("{", "\\{").replace("}", "\\}")
        return "{" + escaped + "}"

    def _tool_version(self, executable: str, run_dir: Path, deadline: float) -> str | None:
        """Return a bounded external-tool version without failing completed analysis."""

        try:
            completed = self._run_process(
                [executable, "-version"], run_dir, deadline
            )
        except Exception:
            return None
        version = completed.stdout.strip() or completed.stderr.strip()
        return version if completed.returncode == 0 and version else None

    def _synthesize(
        self,
        rtl_files: list[Path],
        top_module: str,
        liberty: Path,
        run_dir: Path,
        deadline: float,
        *,
        systemverilog: bool = False,
    ) -> dict[str, Any]:
        """Run Yosys and return mapped/generic structured artifacts and logs."""

        script = run_dir / "synth.ys"
        lines = [
            "read_verilog "
            + ("-sv " if systemverilog else "")
            + " ".join(self._yosys_quote(str(path)) for path in rtl_files),
            f"hierarchy -check -top {top_module}",
            # Keep the analysis bounded for generated arithmetic cones.  The
            # default resource-sharing and fraig/scorr ABC script can spend
            # tens of minutes on a small RTL function with exhaustive
            # encoders; PPA still uses Liberty mapping, while OpenSTA remains
            # the timing authority below.
            f"synth -top {top_module} -noabc -noshare",
            'tee -o "generic_stats.json" stat -json',
            'write_json "generic.json"',
            f"dfflibmap -liberty {self._yosys_quote(str(liberty))}",
            f"abc -liberty {self._yosys_quote(str(liberty))} "
            # Keep the useful Liberty mapper while avoiding the expensive
            # fraig/scorr passes.  Semicolons are encoded as comma-separated
            # script tokens and preserve the ABC network-flow mapping steps.
            "-script +strash,dc2,dretime,strash,;&get,-n,;&dch,-f,;&nf,;&put",
            "clean -purge",
            # Map constant nets to dedicated tie cells so the emitted netlist
            # contains no constant-driver `assign` statements, and rename all
            # internal $-prefixed objects to driver-derived public names so
            # no escaped identifiers remain.  OpenSTA's Verilog reader rejects
            # both constructs.
            "hilomap -hicell LOGIC1_X1 Z -locell LOGIC0_X1 Z",
            "autoname",
            f'tee -o "mapped_stats.json" stat -json -liberty {self._yosys_quote(str(liberty))}',
            'write_verilog -noattr -noexpr -nodec "mapped.v"',
            'write_json "mapped.json"',
        ]
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        yosys = shutil.which("yosys")
        if yosys is None:
            raise FileNotFoundError("yosys was not found on PATH")
        info("[AnalyzePPA] Yosys running synthesis script...")
        completed = self._run_process([yosys, "-s", str(script)], run_dir, deadline)
        if completed.returncode != 0:
            raise RuntimeError(
                "Yosys synthesis failed\n"
                f"stdout:\n{_tail(completed.stdout)}\n"
                f"stderr:\n{_tail(completed.stderr)}"
            )
        return {
            "generic_stats": _load_json_file(run_dir / "generic_stats.json"),
            "generic_json": _load_json_file(run_dir / "generic.json"),
            "mapped_stats": _load_json_file(run_dir / "mapped_stats.json"),
            "mapped_json": _load_json_file(run_dir / "mapped.json"),
            "netlist": run_dir / "mapped.v",
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "executable": yosys,
        }

    def _constraints_tcl(
        self,
        sdc_file: Path | None,
        clock_port: str | None,
        clock_period_ns: float | None,
    ) -> list[str]:
        """Return OpenSTA timing-constraint commands for the selected API branch."""

        if sdc_file is not None:
            return [f"read_sdc {self._tcl_brace(str(sdc_file))}"]
        if clock_port is not None and clock_period_ns is not None:
            return [
                f"create_clock -name {self._tcl_brace(clock_port)} "
                f"-period {clock_period_ns:.12g} "
                f"[get_ports {self._tcl_brace(clock_port)}]"
            ]
        return []

    def _run_opensta(
        self,
        *,
        mode: str,
        netlist: Path,
        top_module: str,
        liberty: Path,
        activity: list[dict[str, Any]],
        sdc_file: Path | None,
        clock_port: str | None,
        clock_period_ns: float | None,
        max_paths: int,
        max_instances: int,
        mapped_cell_count: int,
        run_dir: Path,
        deadline: float,
    ) -> dict[str, Any]:
        """Run an independent OpenSTA timing or power analysis script."""

        script = run_dir / f"{mode}.tcl"
        lines = [
            f"read_liberty {self._tcl_brace(str(liberty))}",
            f"read_verilog {self._tcl_brace(str(netlist))}",
            f"link_design {self._tcl_brace(top_module)}",
            "set_cmd_units -time ns -capacitance pF -resistance kOhm "
            "-voltage V -current mA -power W -distance um",
            *self._constraints_tcl(sdc_file, clock_port, clock_period_ns),
        ]
        power_setup_lines: list[str] = []
        if mode == "timing":
            lines.extend(
                [
                    f"report_checks -path_delay max -group_path_count {max_paths} "
                    f"-endpoint_path_count {max_paths} -format json > "
                    f"{self._tcl_brace(str(run_dir / 'timing.json'))}",
                    f"report_checks -unconstrained -path_delay max -group_path_count {max_paths} "
                    f"-endpoint_path_count {max_paths} -format json > "
                    f"{self._tcl_brace(str(run_dir / 'unconstrained_timing.json'))}",
                    f"report_clock_min_period > {self._tcl_brace(str(run_dir / 'clock_min_period.txt'))}",
                    f"report_worst_slack -max -digits 6 > {self._tcl_brace(str(run_dir / 'wns.txt'))}",
                    f"report_tns -max -digits 6 > {self._tcl_brace(str(run_dir / 'tns.txt'))}",
                    f"set ppa_clock_file [open {self._tcl_brace(str(run_dir / 'clock_names.txt'))} w]",
                    "foreach ppa_clock [get_clocks *] { puts $ppa_clock_file [get_name $ppa_clock] }",
                    "close $ppa_clock_file",
                ]
            )
        elif mode == "power":
            for item in activity:
                density_per_ns = float(item["density_hz"]) * 1e-9
                lines.append(
                    "set_power_activity -input_ports "
                    f"[get_ports {self._tcl_brace(item['input_bit'])}] "
                    f"-density {density_per_ns:.17g} "
                    f"-duty {float(item['duty_cycle']):.17g}"
                )
            power_setup_lines = list(lines)
            lines.append(
                f"report_power -format json > {self._tcl_brace(str(run_dir / 'power.json'))}"
            )
        else:
            raise ValueError(f"unsupported OpenSTA mode: {mode}")
        lines.append("exit")
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        sta = shutil.which("sta") or shutil.which("opensta")
        if sta is None:
            raise FileNotFoundError("OpenSTA executable 'sta' was not found on PATH")
        info(f"[AnalyzePPA] OpenSTA running: {Path(script).name}")
        completed = self._run_process([sta, "-no_splash", str(script)], run_dir, deadline)
        combined_log = f"{completed.stdout}\n{completed.stderr}"
        if completed.returncode != 0 or re.search(r"(?m)^Error:", combined_log):
            raise RuntimeError(
                f"OpenSTA {mode} analysis failed\n"
                f"stdout:\n{_tail(completed.stdout)}\n"
                f"stderr:\n{_tail(completed.stderr)}"
            )
        result = {
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "executable": sta,
        }
        if mode == "timing":
            result["timing_json"], result["report_warnings"] = _load_opensta_json(
                run_dir / "timing.json", allow_empty=True
            )
            (
                result["unconstrained_timing_json"],
                result["unconstrained_report_warnings"],
            ) = _load_opensta_json(
                run_dir / "unconstrained_timing.json", allow_empty=True
            )
            min_period = run_dir / "clock_min_period.txt"
            result["clock_min_period"] = (
                min_period.read_text(encoding="utf-8", errors="replace")
                if min_period.is_file()
                else ""
            )
            clock_names = run_dir / "clock_names.txt"
            result["clock_names"] = (
                [
                    line.strip()
                    for line in clock_names.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()
                    if line.strip()
                ]
                if clock_names.is_file()
                else []
            )
            for metric in ("wns", "tns"):
                metric_path = run_dir / f"{metric}.txt"
                result[metric] = (
                    metric_path.read_text(encoding="utf-8", errors="replace")
                    if metric_path.is_file()
                    else ""
                )
        else:
            result["power_json"], result["report_warnings"] = _load_opensta_json(
                run_dir / "power.json"
            )
            instance_script = run_dir / "power_instances.tcl"
            instance_path = run_dir / "instance_power.json"
            instance_lines = list(power_setup_lines)
            if mapped_cell_count <= 25000:
                instance_lines.extend(
                    [
                        "set ppa_cells [get_cells *]",
                        "report_power -instances $ppa_cells -format json > "
                        f"{self._tcl_brace(str(instance_path))}",
                    ]
                )
            elif max_instances and mapped_cell_count <= 100000:
                # Some OpenSTA builds advertise -highest_power_instances in help
                # but reject the flag at parse time, dropping sta into its
                # interactive prompt mid-script.  Emit both forms in guarded
                # blocks: the ranking flag when supported, otherwise the full
                # per-instance report which Python filters to the top N.
                instance_lines.extend(
                    [
                        "if {[catch {report_power -highest_power_instances "
                        f"{max_instances} -format json > "
                        f"{self._tcl_brace(str(instance_path))}"
                        "} ppa_rank_error]} {",
                        f"  report_power -instances [get_cells *] -format json > "
                        f"{self._tcl_brace(str(instance_path))}",
                        "}",
                    ]
                )
            elif max_instances:
                # OpenSTA's instance ranking is quadratic-ish on very large
                # flattened netlists and can outlive the total-power report.
                # Group totals remain complete; make the optional detail
                # explicitly diagnostic instead of blocking the PPA result.
                result["instance_power_omitted"] = (
                    "instance power ranking omitted for a netlist with "
                    f"{mapped_cell_count} cells (limit: 100000)"
                )
            if instance_lines:
                instance_lines.append("exit")
                instance_script.write_text(
                    "\n".join(instance_lines) + "\n", encoding="utf-8"
                )
                try:
                    instance_completed = self._run_process(
                        [sta, "-no_splash", str(instance_script)], run_dir, deadline
                    )
                    instance_log = (
                        f"{instance_completed.stdout}\n{instance_completed.stderr}"
                    )
                    # The fallback -instances form lists every cell; trim it to
                    # the requested top-N ranking by total power.
                    if instance_path.is_file():
                        self._trim_instance_power(instance_path, max_instances)
                    if instance_completed.returncode != 0 or re.search(
                        r"(?m)^Error:", instance_log
                    ):
                        raise RuntimeError(_tail(instance_log, 1000))
                    (
                        result["instance_power_json"],
                        result["instance_report_warnings"],
                    ) = _load_opensta_json(instance_path)
                except Exception as exc:
                    result["instance_power_omitted"] = _tail(str(exc), 1000)
        return result

    @staticmethod
    def _area_summary(mapped_stats: dict[str, Any], top_module: str) -> dict[str, Any]:
        """Extract cell count and Liberty area from Yosys statistics."""

        stats = _module_stats(mapped_stats, top_module)
        cell_types = stats.get("num_cells_by_type", {})
        total = stats.get("area")
        total_value = float(total) if isinstance(total, (int, float)) else None
        sequential_cells = sum(
            int(count)
            for cell_type, count in cell_types.items()
            if _STATE_CELL_RE.search(str(cell_type))
        )
        sequential_area = stats.get("sequential_area")
        sequential_area_value = (
            float(sequential_area)
            if isinstance(sequential_area, (int, float))
            else None
        )
        return {
            "total": total_value,
            "sequential": sequential_area_value,
            "combinational": (
                total_value - sequential_area_value
                if total_value is not None and sequential_area_value is not None
                else None
            ),
            "cell_count": int(stats.get("num_cells", sum(cell_types.values())) or 0),
            "sequential_cell_count": sequential_cells,
            "combinational_cell_count": int(
                stats.get("num_cells", sum(cell_types.values())) or 0
            )
            - sequential_cells,
            "unit": "liberty_area_unit",
        }

    @staticmethod
    def _parse_clock_period(text: str) -> list[dict[str, Any]]:
        """Parse bounded per-clock minimum period/frequency evidence from OpenSTA text."""

        clocks: list[dict[str, Any]] = []
        pattern = re.compile(
            r"(?P<clock>\S+)\s+period_min\s*=\s*(?P<period>[-+0-9.eE]+)\s+"
            r"fmax\s*=\s*(?P<fmax>[-+0-9.eE]+|inf)",
            re.I,
        )
        for match in pattern.finditer(text):
            period = float(match.group("period"))
            fmax_text = match.group("fmax")
            reported_fmax = (
                None if fmax_text.lower() == "inf" else float(fmax_text)
            )
            maximum_frequency_hz = (
                reported_fmax * 1e6
                if reported_fmax is not None and math.isfinite(reported_fmax)
                else None
            )
            clocks.append(
                {
                    "clock": match.group("clock"),
                    "minimum_period_ns": (
                        1e9 / maximum_frequency_hz
                        if maximum_frequency_hz is not None
                        and maximum_frequency_hz > 0
                        else None
                    ),
                    "maximum_frequency_hz": (
                        maximum_frequency_hz
                    ),
                    "opensta_reported_minimum_period_ns": (
                        period if period > 0 and math.isfinite(period) else None
                    ),
                    "opensta_reported_fmax_mhz": (
                        reported_fmax
                        if reported_fmax is not None and math.isfinite(reported_fmax)
                        else None
                    ),
                }
            )
        return clocks

    def _write_report(self, destination: Path, report: dict[str, Any]) -> None:
        """Atomically persist strict UTF-8 JSON without NaN or Infinity."""

        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file_obj:
                json.dump(
                    _json_safe(report),
                    file_obj,
                    indent=2,
                    ensure_ascii=True,
                    allow_nan=False,
                )
                file_obj.write("\n")
                file_obj.flush()
                os.fsync(file_obj.fileno())
            os.replace(temporary, destination)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def _cache_root(self, *, create: bool) -> Path:
        """Resolve the internal cache root without following workspace symlinks."""

        workspace = Path(self.workspace).resolve()
        state_root = workspace / ".ucagent"
        cache_root = state_root / "ppa_reports"
        for candidate in (state_root, cache_root):
            if candidate.is_symlink():
                raise ValueError(
                    f"internal PPA cache path must not be a symbolic link: {candidate}"
                )
        if create:
            cache_root.mkdir(parents=True, exist_ok=True)
        if cache_root.exists() and not cache_root.is_dir():
            raise ValueError(f"internal PPA cache path is not a directory: {cache_root}")
        return cache_root

    def _new_report_id(self) -> str:
        """Generate a unique report identifier not currently present in this workspace."""

        cache_root = self._cache_root(create=False)
        for _attempt in range(10):
            report_id = f"ppa-{uuid4().hex}"
            if not (cache_root / f"{report_id}.json").exists():
                return report_id
        raise RuntimeError("could not allocate a unique PPA report_id")

    def _load_cache_index(self, cache_root: Path) -> dict[str, Any]:
        """Load and validate the current canonical PPA cache index."""

        index_path = cache_root / "index.json"
        if not index_path.exists():
            return {"schema_version": "1.0", "reports": []}
        if index_path.is_symlink() or not index_path.is_file():
            raise ValueError("internal PPA cache index must be a regular file")
        try:
            with index_path.open("r", encoding="utf-8") as file_obj:
                index = json.load(file_obj)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"internal PPA cache index is unreadable: {exc}") from exc
        if not isinstance(index, dict) or index.get("schema_version") != "1.0":
            raise ValueError("internal PPA cache index schema_version must be 1.0")
        entries = index.get("reports")
        if not isinstance(entries, list):
            raise ValueError("internal PPA cache index reports must be a list")
        seen = set()
        for entry in entries:
            report_id = entry.get("report_id") if isinstance(entry, dict) else None
            if not isinstance(report_id, str) or not _REPORT_ID_RE.fullmatch(report_id):
                raise ValueError("internal PPA cache index contains an invalid report_id")
            report_sha256 = entry.get("sha256")
            if not isinstance(report_sha256, str) or not re.fullmatch(
                r"[0-9a-f]{64}", report_sha256
            ):
                raise ValueError(
                    "internal PPA cache index contains an invalid report SHA-256"
                )
            if report_id in seen:
                raise ValueError("internal PPA cache index contains duplicate report_id values")
            seen.add(report_id)
        return index

    def _available_report_ids(self, limit: int = 20) -> list[str]:
        """Return the newest bounded baseline candidates from the internal index."""

        cache_root = self._cache_root(create=False)
        if not cache_root.exists():
            return []
        index = self._load_cache_index(cache_root)
        return [
            entry["report_id"]
            for entry in reversed(index["reports"][-limit:])
        ]

    def _load_cached_report(self, report_id: str) -> dict[str, Any]:
        """Load one exact cached report by its validated immutable identifier."""

        if not _REPORT_ID_RE.fullmatch(report_id):
            raise ValueError("baseline_report_id has an invalid format")
        cache_root = self._cache_root(create=False)
        if not cache_root.exists():
            raise FileNotFoundError(f"cached PPA report was not found: {report_id}")
        index = self._load_cache_index(cache_root)
        matching_entries = [
            entry for entry in index["reports"] if entry["report_id"] == report_id
        ]
        if not matching_entries:
            raise FileNotFoundError(
                f"cached PPA report is not retained in the internal index: {report_id}"
            )
        report_path = cache_root / f"{report_id}.json"
        if report_path.is_symlink():
            raise ValueError(f"cached PPA report must not be a symbolic link: {report_id}")
        if not report_path.is_file():
            raise FileNotFoundError(f"cached PPA report was not found: {report_id}")
        if _sha256_file(report_path) != matching_entries[0]["sha256"]:
            raise ValueError(f"cached PPA report hash does not match: {report_id}")
        try:
            with report_path.open("r", encoding="utf-8") as file_obj:
                report = json.load(file_obj)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cached PPA report is unreadable: {report_id}: {exc}") from exc
        if not isinstance(report, dict) or report.get("report_id") != report_id:
            raise ValueError(f"cached PPA report identity does not match: {report_id}")
        return report

    def _store_cached_report(self, report: dict[str, Any]) -> dict[str, Any]:
        """Atomically cache one report, index it, and evict entries beyond the limit."""

        report_id = report.get("report_id")
        if not isinstance(report_id, str) or not _REPORT_ID_RE.fullmatch(report_id):
            raise ValueError("report has no valid report_id for caching")
        with _PPA_CACHE_LOCK:
            cache_root = self._cache_root(create=True)
            report_path = cache_root / f"{report_id}.json"
            if report_path.exists():
                raise ValueError(f"report_id collision in internal cache: {report_id}")
            index = self._load_cache_index(cache_root)
            entries = list(index["reports"])
            if any(entry["report_id"] == report_id for entry in entries):
                raise ValueError(f"report_id already exists in internal index: {report_id}")
            entries.append(
                {
                    "report_id": report_id,
                    "sha256": None,
                    "created_at": report.get("created_at"),
                    "top_module": report.get("provenance", {}).get("top_module"),
                    "status": report.get("status"),
                    "report_path": report.get("report_path"),
                }
            )
            pruned = entries[:-self.cache_limit]
            retained = entries[-self.cache_limit :]
            cache_info = {
                "stored": True,
                "limit": self.cache_limit,
                "retained_reports": len(retained),
                "relative_path": f".ucagent/ppa_reports/{report_id}.json",
            }
            report["cache"] = cache_info
            try:
                self._write_report(report_path, report)
                entries[-1]["sha256"] = _sha256_file(report_path)
                self._write_report(
                    cache_root / "index.json",
                    {
                        "schema_version": "1.0",
                        "cache_limit": self.cache_limit,
                        "reports": retained,
                    },
                )
            except Exception:
                try:
                    report_path.unlink()
                except FileNotFoundError:
                    pass
                raise
            for entry in pruned:
                old_report_id = entry["report_id"]
                if not _REPORT_ID_RE.fullmatch(old_report_id):
                    continue
                try:
                    (cache_root / f"{old_report_id}.json").unlink()
                except FileNotFoundError:
                    pass
            return cache_info

    def analyze(
        self,
        arguments: AnalyzePPAArgs,
        *,
        rtl_provenance: list[dict[str, str]] | None = None,
        rtl_library_provenance: list[dict[str, Any]] | None = None,
        trusted_rtl_library_files: tuple[Path, ...] | None = None,
        trusted_rtl_files: tuple[Path, ...] | None = None,
        rtl_systemverilog: bool = False,
    ) -> dict[str, Any]:
        """Execute PPA with optional trusted inputs and authored provenance.

        ``rtl_systemverilog`` must be set when trusted RTL files were emitted
        in SystemVerilog form by a language backend, so Yosys reads them with
        SystemVerilog mode enabled.
        """

        diagnostics: list[dict[str, Any]] = []
        info(
            f"[AnalyzePPA] Starting: top={arguments.top_module}, "
            f"{len(arguments.rtl_files or [])} RTL files, "
            f"{len(arguments.waveform_files or [])} waveforms, "
            f"scope={arguments.waveform_scope}"
        )
        default_report = f"{self.output_dir}/{arguments.top_module}_ppa_report.json"
        report_value = arguments.report_path or default_report
        report_path, report_relative = self._resolve_report(report_value)
        report_id = self._new_report_id()
        authored_rtl_paths: set[Path] = set()
        published_libraries: list[dict[str, Any]] = []
        report: dict[str, Any] = {
            "schema_version": "1.1",
            "report_id": report_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "error",
            "summary": {
                "design_type": "unknown",
                "area": None,
                "timing": None,
                "power": None,
            },
            "comparison": {
                "status": "not_requested",
                "baseline_report_id": None,
                "current_report_id": report_id,
            },
            "hotspots": {
                "timing_paths": [],
                "power_instances": [],
                "findings": [],
            },
            "waveform_aggregation": {
                "method": "duration_weighted_independent_tc_activity",
                "formula": {
                    "density_hz": "sum(tc_transition_count) / sum(tc_duration_seconds)",
                    "duty_cycle": "sum(tc_high_duration_seconds) / sum(tc_duration_seconds)",
                },
                "reliable": False,
                "test_cases": [],
                "merged_input_bits": [],
            },
            "details": {
                "classification": None,
                "area_by_cell_type": {},
                "timing_paths": [],
                "power_groups": [],
            },
            "diagnostics": diagnostics,
            "provenance": {
                "rtl_files": [],
                "rtl_libraries": [],
                "waveform_files": [],
                "top_module": arguments.top_module,
                "waveform_scope": arguments.waveform_scope,
                "liberty_file": None,
                "liberty_sha256": None,
                "sdc_file": arguments.sdc_file,
                "sdc_sha256": None,
                "clock_constraint": (
                    {
                        "clock_port": arguments.clock_port,
                        "clock_period_ns": arguments.clock_period_ns,
                    }
                    if arguments.clock_port is not None
                    else None
                ),
                "tools": {},
            },
            "cache": {
                "stored": False,
                "limit": self.cache_limit,
            },
            "report_path": report_relative,
        }
        deadline = time.monotonic() + arguments.timeout
        try:
            if len(set(arguments.rtl_files)) != len(arguments.rtl_files):
                raise ValueError("rtl_files contains duplicate paths")
            if len(set(arguments.waveform_files)) != len(arguments.waveform_files):
                raise ValueError("waveform_files contains duplicate paths")
            if trusted_rtl_files is None:
                rtl_files = [
                    self._resolve_input(path, {".v"}) for path in arguments.rtl_files
                ]
            else:
                rtl_files = []
                for path in trusted_rtl_files:
                    if not isinstance(path, Path) or not path.is_absolute():
                        raise ValueError(
                            "trusted_rtl_files must contain absolute Path values"
                        )
                    resolved = path.resolve()
                    if path.is_symlink() or not resolved.is_file() or resolved.suffix != ".v":
                        raise ValueError(
                            "trusted_rtl_files must contain regular Verilog files"
                        )
                    rtl_files.append(resolved)
                if (
                    not rtl_files
                    or len(set(rtl_files)) != len(rtl_files)
                    or rtl_files != sorted(rtl_files, key=lambda item: item.as_posix())
                ):
                    raise ValueError(
                        "trusted_rtl_files must be a non-empty unique path-sorted tuple"
                    )
            if (rtl_library_provenance is None) != (
                trusted_rtl_library_files is None
            ):
                raise ValueError(
                    "RTL library provenance and trusted source files must be provided together"
                )
            if rtl_library_provenance is not None:
                if len(rtl_library_provenance) != len(trusted_rtl_library_files):
                    raise ValueError(
                        "RTL library provenance and trusted source file counts differ"
                    )
                for index, (row, source) in enumerate(
                    zip(rtl_library_provenance, trusted_rtl_library_files)
                ):
                    if (
                        not isinstance(row, dict)
                        or set(row) != {"library_index", "path", "sha256"}
                        or isinstance(row["library_index"], bool)
                        or not isinstance(row["library_index"], int)
                        or row["library_index"] < 0
                        or not isinstance(row["path"], str)
                        or not row["path"]
                        or Path(row["path"]).is_absolute()
                        or ".." in Path(row["path"]).parts
                        or not isinstance(row["sha256"], str)
                        or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                    ):
                        raise ValueError(
                            f"rtl_library_provenance[{index}] is invalid"
                        )
                    if (
                        not isinstance(source, Path)
                        or not source.is_absolute()
                        or source.is_symlink()
                        or not source.is_file()
                    ):
                        raise ValueError(
                            f"trusted_rtl_library_files[{index}] is invalid"
                        )
                    resolved_source = source.resolve()
                    if _sha256_file(resolved_source) != row["sha256"]:
                        raise ValueError(
                            f"rtl_library_provenance[{index}] hash differs from the trusted source"
                        )
                    published_libraries.append(dict(row))
                report["provenance"]["rtl_libraries"] = published_libraries
            waveform_files = [
                self._resolve_input(path, {".vcd", ".fst"})
                for path in arguments.waveform_files
            ]
            hashes: dict[str, str] = {}
            for label, path in zip(arguments.waveform_files, waveform_files):
                digest = _sha256_file(path)
                if digest in hashes:
                    raise ValueError(
                        "waveform_files contains duplicate SHA-256 content: "
                        f"{hashes[digest]} and {label}"
                    )
                hashes[digest] = label
                report["provenance"]["waveform_files"].append(
                    {
                        "path": label,
                        "format": path.suffix.lower().lstrip("."),
                        "sha256": digest,
                        "size_bytes": path.stat().st_size,
                    }
                )
            if trusted_rtl_files is None:
                for label, path in zip(arguments.rtl_files, rtl_files):
                    report["provenance"]["rtl_files"].append(
                        {
                            "path": label,
                            "sha256": _sha256_file(path),
                            "size_bytes": path.stat().st_size,
                        }
                    )
            liberty = (
                self._resolve_input(arguments.liberty_file, {".lib"})
                if arguments.liberty_file
                else self._DEFAULT_LIBERTY
            )
            if not liberty.is_file():
                raise FileNotFoundError(
                    "bundled Nangate45 Liberty asset is missing; reinstall UCAgent or "
                    "provide liberty_file"
                )
            sdc = (
                self._resolve_input(arguments.sdc_file, {".sdc"})
                if arguments.sdc_file
                else None
            )
            report["provenance"]["liberty_file"] = (
                arguments.liberty_file or "bundled:NangateOpenCellLibrary_typical.lib"
            )
            report["provenance"]["liberty_sha256"] = _sha256_file(liberty)
            report["provenance"]["sdc_sha256"] = _sha256_file(sdc) if sdc else None
            with tempfile.TemporaryDirectory(prefix="ucagent-ppa-") as temporary:
                run_dir = Path(temporary)
                self.put_alive_data("PPA: synthesizing and technology-mapping RTL with Yosys")
                info("[AnalyzePPA] Phase 1/4: Yosys synthesis + technology mapping (this is the longest step)...")
                synthesis = self._synthesize(
                    rtl_files,
                    arguments.top_module,
                    liberty,
                    run_dir,
                    deadline,
                    systemverilog=rtl_systemverilog,
                )
                report["provenance"]["tools"]["yosys"] = {
                    "executable": synthesis["executable"],
                    "version": next(
                        (
                            line.strip()
                            for line in synthesis["stdout"].splitlines()
                            if line.strip().startswith("Yosys ")
                        ),
                        None,
                    ),
                    "log_excerpt": _tail(synthesis["stdout"] + synthesis["stderr"], 2000),
                }
                design_type, classification = _classify_design(
                    synthesis["generic_stats"],
                    synthesis["generic_json"],
                    arguments.top_module,
                )
                report["summary"]["design_type"] = design_type
                report["details"]["classification"] = classification
                area = self._area_summary(
                    synthesis["mapped_stats"], arguments.top_module
                )
                report["summary"]["area"] = area
                info(
                    f"[AnalyzePPA] Phase 1/4 done: {area.get('cell_count', '?')} cells, "
                    f"area={area.get('total', '?')} {area.get('unit', '')}"
                )
                mapped_stats = _module_stats(
                    synthesis["mapped_stats"], arguments.top_module
                )
                report["details"]["area_by_cell_type"] = mapped_stats.get(
                    "num_cells_by_type", {}
                )
                input_bits = _port_bits(synthesis["mapped_json"], arguments.top_module)
                self.put_alive_data(
                    f"PPA: aggregating {len(waveform_files)} independent TC waveforms"
                )
                tc_activity = []
                waveform_errors = False
                resolved_waveform_scope: str | None = None
                for label, waveform in zip(arguments.waveform_files, waveform_files):
                    try:
                        parse_path = waveform
                        if waveform.suffix.lower() == ".fst":
                            parse_path = run_dir / f"waveform-{len(tc_activity)}.vcd"
                            _convert_fst_to_vcd(waveform, parse_path)
                        tc_info, activity = _parse_vcd_activity(
                            parse_path, label, arguments.waveform_scope, input_bits
                        )
                        detected_scope = tc_info.get("waveform_scope")
                        if not isinstance(detected_scope, str) or not detected_scope:
                            raise ValueError("waveform parser returned no resolved scope")
                        if resolved_waveform_scope is None:
                            resolved_waveform_scope = detected_scope
                            report["provenance"]["waveform_scope"] = detected_scope
                        elif detected_scope != resolved_waveform_scope:
                            raise ValueError(
                                "performance waveforms resolve to different DUT scopes: "
                                f"{resolved_waveform_scope} and {detected_scope}"
                            )
                        provenance = next(
                            item
                            for item in report["provenance"]["waveform_files"]
                            if item["path"] == label
                        )
                        tc_info.update(
                            {
                                "format": provenance["format"],
                                "sha256": provenance["sha256"],
                                "weight": None,
                                "status": "valid",
                            }
                        )
                        tc_activity.append((tc_info, activity))
                    except Exception as exc:
                        waveform_errors = True
                        tc_info = {"path": label, "status": "invalid", "error": str(exc)}
                        diagnostics.append(
                            _diagnostic(
                                "waveform_aggregation",
                                "invalid_tc_waveform",
                                f"Waveform '{label}' cannot contribute reliable activity: {exc}",
                                "Regenerate this exact performance TC waveform with the common DUT scope and all top-level input ports, then rerun AnalyzePPA with the full TC list.",
                                artifact=label,
                            )
                        )
                    report["waveform_aggregation"]["test_cases"].append(tc_info)
                if tc_activity:
                    total_duration = sum(tc["duration_seconds"] for tc, _ in tc_activity)
                    for tc, _ in tc_activity:
                        tc["weight"] = tc["duration_seconds"] / total_duration
                    merged_activity = _aggregate_tc_activity(tc_activity)
                    report["waveform_aggregation"]["merged_input_bits"] = merged_activity
                    report["waveform_aggregation"]["total_duration_seconds"] = total_duration
                    report["waveform_aggregation"]["reliable"] = not waveform_errors
                else:
                    merged_activity = []
                self.put_alive_data("PPA: running independent OpenSTA timing analysis")
                try:
                    info("[AnalyzePPA] Phase 2/4: OpenSTA static timing analysis...")
                    timing_run = self._run_opensta(
                        mode="timing",
                        netlist=synthesis["netlist"],
                        top_module=arguments.top_module,
                        liberty=liberty,
                        activity=[],
                        sdc_file=sdc,
                        clock_port=arguments.clock_port,
                        clock_period_ns=arguments.clock_period_ns,
                        max_paths=arguments.max_timing_paths,
                        max_instances=arguments.max_power_instances,
                        mapped_cell_count=area["cell_count"],
                        run_dir=run_dir,
                        deadline=deadline,
                    )
                    constrained_paths = _timing_paths(timing_run["timing_json"])
                    unconstrained_paths = _timing_paths(
                        timing_run["unconstrained_timing_json"]
                    )
                    clock_names = set(timing_run["clock_names"])
                    unconstrained_paths = [
                        path
                        for path in unconstrained_paths
                        if str(path.get("startpoint", "")) not in clock_names
                    ]
                    paths = constrained_paths + unconstrained_paths
                    unique_paths = []
                    seen_paths = set()
                    for path in paths:
                        identity = (
                            path.get("type"),
                            path.get("path_group"),
                            path.get("startpoint"),
                            path.get("endpoint"),
                            path.get("path_type"),
                        )
                        if identity not in seen_paths:
                            seen_paths.add(identity)
                            unique_paths.append(path)
                    paths = unique_paths[: arguments.max_timing_paths]
                    timing = _timing_summary(paths)
                    info("[AnalyzePPA] Phase 2/4 done.")
                    exact_wns = _parse_sta_metric(timing_run["wns"], "wns")
                    exact_tns = _parse_sta_metric(timing_run["tns"], "tns")
                    if exact_wns is not None:
                        timing["wns_ns"] = exact_wns
                    if exact_tns is not None:
                        timing["tns_ns"] = exact_tns
                    clocks = self._parse_clock_period(timing_run["clock_min_period"])
                    timing["clocks"] = clocks
                    if clocks and any(item["maximum_frequency_hz"] for item in clocks):
                        timing["metric_kind"] = "minimum_clock_period"
                        timing["maximum_frequency_hz"] = min(
                            item["maximum_frequency_hz"]
                            for item in clocks
                            if item["maximum_frequency_hz"] is not None
                        )
                    else:
                        timing["maximum_frequency_hz"] = timing[
                            "equivalent_max_frequency_hz"
                        ]
                    timing_available = (
                        timing["critical_path_delay_ns"] is not None
                        and timing["critical_path_delay_ns"] > 0
                    ) or timing["maximum_frequency_hz"] is not None
                    report["summary"]["timing"] = timing if timing_available else None
                    report["details"]["timing_paths"] = paths[: arguments.max_timing_paths]
                    report["hotspots"]["timing_paths"] = paths[: arguments.max_timing_paths]
                    if not timing_available:
                        diagnostics.append(
                            _diagnostic(
                                "timing",
                                "timing_metric_unavailable",
                                "OpenSTA found no positive critical data-path delay or finite minimum clock period.",
                                "Add complete timing constraints and ensure the synthesized design contains a valid data path; infinity is intentionally reported as null.",
                                observed={"clocks": clocks, "path_count": len(paths)},
                            )
                        )
                    if timing["wns_ns"] is not None and timing["wns_ns"] < 0:
                        report["hotspots"]["findings"].append(
                            {
                                "kind": "negative_slack",
                                "value_ns": timing["wns_ns"],
                                "location": timing["limiting_path"],
                            }
                        )
                    report["provenance"]["tools"]["opensta_timing"] = {
                        "executable": timing_run["executable"],
                        "version": self._tool_version(
                            timing_run["executable"], run_dir, deadline
                        ),
                        "log_excerpt": _tail(
                            timing_run["stdout"] + timing_run["stderr"], 2000
                        ),
                    }
                except Exception as exc:
                    diagnostics.append(
                        _diagnostic(
                            "timing",
                            "opensta_timing_failed",
                            str(exc),
                            "Inspect the bounded OpenSTA diagnostic, fix the netlist/Liberty/SDC or clock constraint mismatch, and rerun AnalyzePPA.",
                        )
                    )
                if not merged_activity:
                    diagnostics.append(
                        _diagnostic(
                            "power",
                            "no_valid_waveform_activity",
                            "No waveform supplied a complete set of valid top-level input activities.",
                            "Fix every invalid TC waveform diagnostic and rerun AnalyzePPA with the complete performance-test waveform list.",
                        )
                    )
                else:
                    self.put_alive_data("PPA: running OpenSTA with merged TC activity")
                    try:
                        info("[AnalyzePPA] Phase 3/4: OpenSTA power analysis (activity from waveforms)...")
                        power_run = self._run_opensta(
                            mode="power",
                            netlist=synthesis["netlist"],
                            top_module=arguments.top_module,
                            liberty=liberty,
                            activity=merged_activity,
                            sdc_file=sdc,
                            clock_port=arguments.clock_port,
                            clock_period_ns=arguments.clock_period_ns,
                            max_paths=arguments.max_timing_paths,
                            max_instances=arguments.max_power_instances,
                            mapped_cell_count=area["cell_count"],
                            run_dir=run_dir,
                            deadline=deadline,
                        )
                        power, groups = _power_totals(power_run["power_json"])
                        info("[AnalyzePPA] Phase 3/4 done.")
                        report["summary"]["power"] = power
                        report["details"]["power_groups"] = groups
                        instance_rows = []
                        instance_json = power_run.get("instance_power_json")
                        if instance_json is not None:
                            instance_rows = _power_rows(instance_json)

                            def instance_total(row: dict[str, Any]) -> float:
                                """Return a sortable total for one OpenSTA instance row."""

                                for key in ("total", "total_power"):
                                    try:
                                        return float(row.get(key, 0.0))
                                    except (TypeError, ValueError):
                                        pass
                                return sum(
                                    float(row.get(key, 0.0) or 0.0)
                                    for key in ("internal", "switching", "leakage")
                                )

                            instance_rows = sorted(
                                (
                                    row
                                    for row in instance_rows
                                    if str(row.get("group", row.get("name", ""))).lower()
                                    != "total"
                                ),
                                key=instance_total,
                                reverse=True,
                            )[: arguments.max_power_instances]
                        report["hotspots"]["power_instances"] = instance_rows
                        if power_run.get("instance_power_omitted"):
                            diagnostics.append(
                                _diagnostic(
                                    "power",
                                    "power_instance_breakdown_unavailable",
                                    "OpenSTA produced total/group power but could not produce the requested native top-instance breakdown for this large design.",
                                    "Use the retained group totals and cell-area breakdown to narrow the block, or run a compatible OpenSTA build for instance ranking.",
                                    observed=power_run["instance_power_omitted"],
                                )
                            )
                        report["provenance"]["tools"]["opensta_power"] = {
                            "executable": power_run["executable"],
                            "version": self._tool_version(
                                power_run["executable"], run_dir, deadline
                            ),
                            "log_excerpt": _tail(
                                power_run["stdout"] + power_run["stderr"], 2000
                            ),
                        }
                    except Exception as exc:
                        diagnostics.append(
                            _diagnostic(
                                "power",
                                "opensta_power_failed",
                                str(exc),
                                "Inspect the bounded OpenSTA diagnostic, verify Liberty pin models and waveform input coverage, then rerun AnalyzePPA.",
                            )
                        )
                required = (
                    report["summary"]["area"] is not None
                    and report["summary"]["area"]["total"] is not None,
                    report["summary"]["timing"] is not None,
                    report["summary"]["power"] is not None
                    and report["summary"]["power"]["total_w"] is not None,
                    report["summary"]["design_type"] != "unknown",
                    report["waveform_aggregation"]["reliable"],
                )
                report["status"] = "success" if all(required) else "partial"
                if report["summary"]["area"]["total"] is None:
                    diagnostics.append(
                        _diagnostic(
                            "area",
                            "area_metric_unavailable",
                            "Yosys mapped the design but the selected Liberty did not yield a finite total cell area.",
                            "Verify that every mapped cell has an area in liberty_file, then rerun AnalyzePPA.",
                        )
                    )
                if report["summary"]["design_type"] == "unknown":
                    diagnostics.append(
                        _diagnostic(
                            "classification",
                            "design_type_unknown",
                            "Yosys evidence contains unresolved blackboxes or is insufficient for a combinational/sequential decision.",
                            "Resolve every blackbox and rerun synthesis; do not supply a manual circuit classification.",
                            observed=classification,
                        )
                    )
        except Exception as exc:
            diagnostics.append(
                _diagnostic(
                    "analysis",
                    "ppa_analysis_failed",
                    str(exc),
                    "Fix the exact input, dependency, synthesis, or path error reported above and rerun AnalyzePPA with the same complete input contract.",
                )
            )
            report["status"] = "error"

        if rtl_provenance is not None:
            published_rtl = []
            if not isinstance(rtl_provenance, list) or not rtl_provenance:
                raise ValueError("rtl_provenance must be a non-empty source list")
            for index, row in enumerate(rtl_provenance):
                if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
                    raise ValueError(f"rtl_provenance[{index}] is invalid")
                source = self._resolve_input(row["path"], None)
                authored_rtl_paths.add(source.resolve())
                digest = _sha256_file(source)
                if digest != row["sha256"]:
                    raise ValueError(
                        f"rtl_provenance[{index}] hash differs from the authored source"
                    )
                published_rtl.append(
                    {
                        "path": row["path"],
                        "sha256": digest,
                        "size_bytes": source.stat().st_size,
                    }
                )
            report["provenance"]["rtl_files"] = published_rtl

        if trusted_rtl_files is not None:
            private_rtl_files = tuple(
                path.resolve()
                for path in trusted_rtl_files
                if path.resolve() not in authored_rtl_paths
            )
            report = _redact_private_paths(report, private_rtl_files)
            report["provenance"]["rtl_libraries"] = published_libraries
            diagnostics = report["diagnostics"]

        if arguments.baseline_report_id is not None:
            try:
                baseline = self._load_cached_report(arguments.baseline_report_id)
                report["comparison"] = _compare_reports(baseline, report)
            except Exception as exc:
                try:
                    available_report_ids = self._available_report_ids()
                except Exception:
                    available_report_ids = []
                report["comparison"] = {
                    "status": "error",
                    "baseline_report_id": arguments.baseline_report_id,
                    "current_report_id": report_id,
                    "error": str(exc),
                    "available_report_ids": available_report_ids,
                }
                diagnostics.append(
                    _diagnostic(
                        "comparison",
                        "baseline_report_unavailable",
                        str(exc),
                        "Rerun with baseline_report_id set to one of available_report_ids, or omit it to create a new baseline.",
                        artifact=f".ucagent/ppa_reports/{arguments.baseline_report_id}.json",
                        observed={
                            "baseline_report_id": arguments.baseline_report_id,
                            "available_report_ids": available_report_ids,
                        },
                    )
                )
                if report["status"] == "success":
                    report["status"] = "partial"

        try:
            self._store_cached_report(report)
        except Exception as exc:
            report["cache"] = {
                "stored": False,
                "limit": self.cache_limit,
                "error": str(exc),
            }
            diagnostics.append(
                _diagnostic(
                    "report_cache",
                    "report_cache_failed",
                    str(exc),
                    "Fix workspace .ucagent/ppa_reports permissions or integrity, then rerun AnalyzePPA to create a reusable report_id.",
                    artifact=".ucagent/ppa_reports",
                )
            )
            if report["status"] == "success":
                report["status"] = "partial"
                comparison_status = _nested_value(
                    report, ("comparison", "detail_changes", "status")
                )
                if isinstance(comparison_status, dict):
                    comparison_status["current"] = "partial"
                    comparison_status["changed"] = (
                        comparison_status.get("baseline") != "partial"
                    )
        report = _json_safe(report)
        info(f"[AnalyzePPA] Phase 4/4: writing report to {report_path} and refreshing dashboard...")
        self._write_report(report_path, report)
        self._refresh_dashboard_snapshot(report)
        info(
            f"[AnalyzePPA] COMPLETE: status={report.get('status')}, "
            f"report_id={report.get('report_id')}"
        )
        return report

    def _refresh_dashboard_snapshot(self, report: dict[str, Any]) -> None:
        """Re-embed the latest PPA result into the workspace dashboard HTML.

        The dashboard reads its embedded JSON snapshot when opened via
        ``file://``; this method replaces the ``finalPpa`` key in that
        snapshot so a file-mode refresh after ``tool_invoke AnalyzePPA``
        shows the new measurement without rerunning the workflow's final
        delivery stage.  The HTTP mode always fetches the current JSON
        files directly and needs no assistance.
        """

        workspace = Path(self.workspace).resolve()
        dashboard = workspace / self.output_dir / "design_with_ppa_dashboard.html"
        # The DUT-specific filename takes precedence when it exists.
        dut = ""
        try:
            from ucagent.util.config import load_runtime_config
            runtime = load_runtime_config(str(workspace))
            dut = runtime.get("DUT", "")
        except Exception:
            pass
        if dut:
            dut_dashboard = workspace / self.output_dir / f"{dut}_ppa_dashboard.html"
            dashboard = dut_dashboard  # Always prefer the DUT-specific path
        snapshot_fresh = False
        if not dashboard.is_file():
            # The dashboard was deleted or never rendered: recreate it from the
            # plugin's workflow template with the canonical Jinja2 rendering so
            # every template variable resolves exactly as the workflow would.
            template = (
                Path(__file__).resolve().parent
                / "templates"
                / "unit_design"
            )
            if not template.is_dir() or not dut:
                return  # No template or DUT identity available; cannot rebuild.
            out = ""
            version = ""
            try:
                from ucagent.util.config import load_runtime_config
                runtime_cfg = load_runtime_config(str(workspace))
                out = runtime_cfg.get("OUT", "")
            except Exception:
                pass
            try:
                from design_with_ppa import __version__ as _plugin_version
                version = str(_plugin_version)
            except Exception:
                pass
            import jinja2 as _jinja2
            env = _jinja2.Environment(
                loader=_jinja2.FileSystemLoader(str(template)),
                keep_trailing_newline=True,
            )
            from datetime import datetime as _dt, timezone as _tz
            rendered_at = _dt.now(_tz.utc).isoformat()
            rendered = env.get_template("{{DUT}}_ppa_dashboard.html").render(
                DUT=dut,
                OUT=out or "output",
                Version=version or "1.0",
                CWD=str(workspace),
                UC_LIB_PATH="",
                RENDERED_AT=rendered_at,
            )
            text = rendered
            snapshot_fresh = True
        else:
            text = dashboard.read_text(encoding="utf-8")
        marker_start = text.find("id=\"design-with-ppa-snapshot\"")
        if marker_start < 0:
            return  # Not the v2 dashboard template.
        # Find the JSON payload inside the snapshot <script> block
        json_start = text.find(">", marker_start)
        if json_start < 0:
            return
        json_start += 1
        json_end = text.find("</script>", json_start)
        if json_end < 0:
            return
        payload_text = text[json_start:json_end].strip()
        if not payload_text:
            return
        import json as _json
        if snapshot_fresh:
            # Template snapshot is a placeholder; load the current workspace
            # data so the rebuilt dashboard renders immediately in file://
            # mode with real curves, state, and PPA results.
            snapshot = {"schema_version": "1.0"}
            for key, rel_path in (
                ("curve", f"{dut}_performance_curve.json"),
                ("state", "../.ucagent/design_with_ppa/state.json"),
                ("runtime", "../.ucagent/runtime_config.json"),
            ):
                source = workspace / self.output_dir / rel_path
                if not source.is_file():
                    continue
                try:
                    snapshot[key] = _json.loads(source.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
        else:
            try:
                snapshot = _json.loads(payload_text)
            except (ValueError, TypeError):
                return
        snapshot["finalPpa"] = {
            "schema_version": report.get("schema_version"),
            "report_id": report.get("report_id"),
            "status": report.get("status"),
            "summary": report.get("summary"),
        }
        new_payload = _json.dumps(
            snapshot, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
        dashboard.write_text(
            text[:json_start] + new_payload + text[json_end:], encoding="utf-8"
        )

    def _derive_workspace_arguments(
        self,
        rtl_files: list[str] | None,
        top_module: str | None,
        waveform_files: list[str] | None,
        waveform_scope: str | None,
    ) -> tuple[list[str], str, list[str], str]:
        """Fill omitted required arguments from the current workspace state.

        The RTL backend manifest supplies the authored sources and top module;
        the performance manifest supplies the ordered waveform list and scope.
        This lets ``tool_invoke AnalyzePPA`` regenerate a report without
        hand-copying paths that the workflow already recorded.
        """

        import json as _json
        from ucagent.util.functions import load_json_file
        workspace = Path(self.workspace).resolve()
        if not rtl_files or not top_module:
            manifest_path = workspace / ".ucagent" / "design_with_ppa" / "rtl_backend_manifest.json"
            if not manifest_path.is_file():
                raise ValueError(
                    "rtl_files/top_module omitted but no RTL backend manifest found at "
                    ".ucagent/design_with_ppa/rtl_backend_manifest.json; "
                    "pass them explicitly or run the RTL stage first."
                )
            manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
            if not rtl_files:
                rtl_files = [
                    row["path"]
                    for row in manifest.get("rtl_sources", [])
                    if isinstance(row, dict) and isinstance(row.get("path"), str)
                ]
                if not rtl_files:
                    raise ValueError("RTL backend manifest has no rtl_sources paths.")
            if not top_module:
                top_module = manifest.get("top_module") or ""
                if not top_module:
                    raise ValueError("RTL backend manifest has no top_module.")
        waveform_files = list(waveform_files or [])
        if not waveform_files or not waveform_scope:
            perf_path = workspace / "output" / "performance" / "performance_manifest.json"
            if self.output_dir:
                perf_path = workspace / self.output_dir / "performance" / "performance_manifest.json"
            if not perf_path.is_file():
                raise ValueError(
                    "waveform_files/waveform_scope omitted but no performance manifest "
                    "found at the configured output's performance/performance_manifest.json; "
                    "pass them explicitly or run the performance evidence stage first."
                )
            perf = _json.loads(perf_path.read_text(encoding="utf-8"))
            if not waveform_files:
                for entry in perf.get("tests", []):
                    if not isinstance(entry, dict):
                        continue
                    wave = entry.get("waveform")
                    if isinstance(wave, dict) and isinstance(wave.get("path"), str):
                        waveform_files.append(wave["path"])
                    elif isinstance(wave, str):
                        waveform_files.append(wave)
                if not waveform_files:
                    raise ValueError("Performance manifest has no waveform paths.")
            if not waveform_scope:
                waveform_scope = perf.get("waveform_scope") or ""
            if not waveform_scope:
                # The workflow default is TOP.<top_module>; the analysis also
                # auto-discovers a deeper wrapper scope from the VCD header
                # when this default does not cover the top-level input bits.
                waveform_scope = f"TOP.{top_module}"
        return rtl_files, top_module, waveform_files, waveform_scope

    def _run(
        self,
        rtl_files: list[str] | None = None,
        top_module: str | None = None,
        waveform_files: list[str] | None = None,
        waveform_scope: str | None = None,
        liberty_file: str | None = None,
        sdc_file: str | None = None,
        clock_port: str | None = None,
        clock_period_ns: float | None = None,
        report_path: str | None = None,
        baseline_report_id: str | None = None,
        max_timing_paths: int = 10,
        max_power_instances: int = 10,
        timeout: int = 300,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Validate public arguments, execute analysis, and return the structured report."""

        del run_manager
        rtl_files, top_module, waveform_files, waveform_scope = (
            self._derive_workspace_arguments(
                rtl_files, top_module, waveform_files, waveform_scope
            )
        )
        arguments = AnalyzePPAArgs(
            rtl_files=rtl_files,
            top_module=top_module,
            waveform_files=waveform_files,
            waveform_scope=waveform_scope,
            liberty_file=liberty_file,
            sdc_file=sdc_file,
            clock_port=clock_port,
            clock_period_ns=clock_period_ns,
            report_path=report_path,
            baseline_report_id=baseline_report_id,
            max_timing_paths=max_timing_paths,
            max_power_instances=max_power_instances,
            timeout=timeout,
        )
        return make_llm_tool_ret(self.analyze(arguments), check_pass=False)
