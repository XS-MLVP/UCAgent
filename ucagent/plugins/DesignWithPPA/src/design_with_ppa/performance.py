"""Deterministic simulation-time performance measurements and result receipts."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

from ucagent.util.config import load_runtime_config

from .contracts import canonical_json_sha256, performance_stimulus_identity


PERFORMANCE_RESULT_SCHEMA_VERSION = "1.0"
PERFORMANCE_MANIFEST_SCHEMA_VERSION = "1.0"
_TIME_UNIT_SECONDS = {
    "s": 1.0,
    "ms": 1e-3,
    "us": 1e-6,
    "ns": 1e-9,
    "ps": 1e-12,
    "fs": 1e-15,
}


def _finite_number(value: Any, field: str) -> float:
    """Return one finite non-boolean numeric value or raise a precise error."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _time_unit(value: str) -> str:
    """Validate and normalize a supported simulation time unit."""

    if not isinstance(value, str) or value not in _TIME_UNIT_SECONDS:
        raise ValueError(
            f"time_unit must be one of {', '.join(_TIME_UNIT_SECONDS)}"
        )
    return value


def measure_latency(start_time: float, end_time: float, time_unit: str) -> float:
    """Measure non-negative elapsed simulation time in the caller's declared unit."""

    _time_unit(time_unit)
    start = _finite_number(start_time, "start_time")
    end = _finite_number(end_time, "end_time")
    if end < start:
        raise ValueError("end_time must be greater than or equal to start_time")
    return end - start


def measure_cycle_latency(start_cycle: int, end_cycle: int) -> int:
    """Measure non-negative latency between two integer simulation cycles."""

    if (
        isinstance(start_cycle, bool)
        or isinstance(end_cycle, bool)
        or not isinstance(start_cycle, int)
        or not isinstance(end_cycle, int)
    ):
        raise TypeError("start_cycle and end_cycle must be integers")
    if start_cycle < 0 or end_cycle < start_cycle:
        raise ValueError(
            "cycles must be non-negative and end_cycle must not precede start_cycle"
        )
    return end_cycle - start_cycle


def measure_throughput(
    transaction_count: int,
    start_time: float,
    end_time: float,
    time_unit: str,
) -> float:
    """Measure completed transactions per declared simulation time unit."""

    if isinstance(transaction_count, bool) or not isinstance(transaction_count, int):
        raise TypeError("transaction_count must be an integer")
    if transaction_count < 0:
        raise ValueError("transaction_count must be non-negative")
    duration = measure_latency(start_time, end_time, time_unit)
    if duration == 0:
        raise ValueError("throughput duration must be greater than zero")
    return transaction_count / duration


def _sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one regular non-symlink file."""

    if path.is_symlink() or not path.is_file():
        raise ValueError(f"artifact must be a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _workspace_relative(workspace: Path, path_value: str | os.PathLike[str]) -> Path:
    """Resolve one artifact inside the workspace without accepting path escape."""

    path = Path(path_value)
    candidate = path.resolve() if path.is_absolute() else (workspace / path).resolve()
    try:
        candidate.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(f"artifact must remain inside workspace: {path_value}") from exc
    return candidate


def _normalize_metrics(metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize metric mappings into finite, unit-bearing deterministic rows."""

    if not isinstance(metrics, Mapping) or not metrics:
        raise ValueError("metrics must be a non-empty mapping")
    rows = []
    for metric_id in sorted(metrics):
        if not isinstance(metric_id, str) or not metric_id.strip():
            raise ValueError("metric IDs must be non-empty strings")
        raw = metrics[metric_id]
        if isinstance(raw, Mapping):
            value = _finite_number(raw.get("value"), f"metrics.{metric_id}.value")
            unit = raw.get("unit")
            kind = raw.get("kind", "custom")
            direction = raw.get("direction")
        else:
            value = _finite_number(raw, f"metrics.{metric_id}")
            unit = "count"
            kind = "custom"
            direction = None
        if not isinstance(unit, str) or not unit.strip():
            raise ValueError(f"metrics.{metric_id}.unit must be non-empty")
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError(f"metrics.{metric_id}.kind must be non-empty")
        if direction not in (None, "min", "max"):
            raise ValueError(f"metrics.{metric_id}.direction must be min or max")
        row = {"id": metric_id, "kind": kind, "value": value, "unit": unit}
        if direction is not None:
            row["direction"] = direction
        rows.append(row)
    return rows


def _node_id(request: Any) -> str:
    """Return the canonical workspace-relative pytest node ID."""

    node = getattr(request, "node", None)
    node_id = getattr(node, "nodeid", None) or getattr(request, "nodeid", None)
    if not isinstance(node_id, str) or not node_id.strip():
        raise ValueError("request must expose a non-empty pytest node.nodeid")
    raw_path, separator, node_suffix = node_id.partition("::")
    node_path = getattr(node, "path", None)
    if node_path is not None:
        workspace = Path.cwd().resolve()
        candidate = Path(node_path)
        candidate = (
            candidate.resolve()
            if candidate.is_absolute()
            else (workspace / candidate).resolve()
        )
        try:
            raw_path = candidate.relative_to(workspace).as_posix()
        except ValueError as exc:
            raise ValueError(
                "pytest test source must remain inside the workspace"
            ) from exc
    elif Path(raw_path).is_absolute():
        workspace = Path.cwd().resolve()
        try:
            raw_path = Path(raw_path).resolve().relative_to(workspace).as_posix()
        except ValueError as exc:
            raise ValueError(
                "pytest test source must remain inside the workspace"
            ) from exc
    else:
        raw_path = Path(raw_path).as_posix()
    return f"{raw_path}::{node_suffix}" if separator else raw_path


def get_performance_waveform_path(
    request: Any,
    *,
    extension: str = "vcd",
) -> Path:
    """Return one unique workspace waveform path for a pytest performance node.

    The path is resolved before DUT reset so the RTL fixture can call
    ``SetWaveform`` before the first ``Step``. Calling this function again for
    the same pytest node returns the same path without creating trace content.
    """

    if extension not in {"vcd", "fst"}:
        raise ValueError("extension must be vcd or fst")
    workspace = Path.cwd().resolve()
    runtime = load_runtime_config(str(workspace))
    output = runtime.get("OUT")
    if not isinstance(output, str) or not output.strip():
        raise ValueError("runtime config OUT must be a non-empty string")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", _node_id(request)).strip("._")
    if not safe_name:
        raise ValueError("pytest node ID cannot be converted to a waveform name")
    wave_dir = _workspace_relative(
        workspace, Path(output) / "performance" / "waves"
    )
    if wave_dir.is_symlink() or (wave_dir.exists() and not wave_dir.is_dir()):
        raise ValueError("performance waveform directory must be a regular directory")
    wave_dir.mkdir(parents=True, exist_ok=True)
    return wave_dir / f"{safe_name}.{extension}"


def write_performance_result(
    request: Any,
    metrics: Mapping[str, Any],
    waveform_path: str | os.PathLike[str],
    stimulus_manifest: Mapping[str, Any],
) -> str:
    """Atomically write one performance-TC sidecar and return its workspace path."""

    workspace = Path.cwd().resolve()
    runtime = load_runtime_config(str(workspace))
    output = runtime.get("OUT")
    if not isinstance(output, str) or not output.strip():
        raise ValueError("runtime config OUT must be a non-empty string")
    node_id = _node_id(request)
    waveform = _workspace_relative(workspace, waveform_path)
    if waveform.suffix.lower() not in {".vcd", ".fst"}:
        raise ValueError("waveform_path must have .vcd or .fst suffix")
    waveform_hash = _sha256_file(waveform)
    if not isinstance(stimulus_manifest, Mapping) or not stimulus_manifest:
        raise ValueError("stimulus_manifest must be a non-empty mapping")
    stimulus = dict(stimulus_manifest)
    required_stimulus_fields = {
        "deterministic",
        "seed",
        "parameters",
        "start_time",
        "end_time",
        "time_unit",
        "transaction_count",
        "input_trace",
    }
    missing_fields = sorted(required_stimulus_fields - set(stimulus))
    if missing_fields:
        raise ValueError(
            f"stimulus_manifest is missing required fields: {missing_fields}"
        )
    if type(stimulus["deterministic"]) is not bool:
        raise TypeError("stimulus_manifest.deterministic must be boolean")
    seed = stimulus["seed"]
    if seed is not None and (
        isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
    ):
        raise ValueError("stimulus_manifest.seed must be null or a non-negative integer")
    if seed is None and not stimulus["deterministic"]:
        raise ValueError(
            "stimulus_manifest requires deterministic=true when seed is null"
        )
    if not isinstance(stimulus["parameters"], Mapping):
        raise TypeError("stimulus_manifest.parameters must be a mapping")
    time_unit = _time_unit(stimulus["time_unit"])
    duration = measure_latency(
        stimulus["start_time"], stimulus["end_time"], time_unit
    )
    if duration <= 0:
        raise ValueError("stimulus_manifest duration must be greater than zero")
    transaction_count = stimulus["transaction_count"]
    if isinstance(transaction_count, bool) or not isinstance(transaction_count, int):
        raise TypeError("stimulus_manifest.transaction_count must be an integer")
    if transaction_count < 0:
        raise ValueError("stimulus_manifest.transaction_count must be non-negative")
    if stimulus["input_trace"] in (None, [], {}):
        raise ValueError("stimulus_manifest.input_trace must be non-empty")
    # Observed end time and transaction count may change when RTL performance
    # improves. They are measurements, not part of the repeatable stimulus ID.
    stimulus_hash = canonical_json_sha256(performance_stimulus_identity(stimulus))
    input_trace = stimulus.get("input_trace")
    input_trace_hash = canonical_json_sha256(
        input_trace if input_trace is not None else stimulus
    )
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", node_id).strip("._")
    if not safe_name:
        raise ValueError("pytest node ID cannot be converted to an artifact name")
    result_dir = _workspace_relative(
        workspace, Path(output) / "performance" / "results"
    )
    result_dir.mkdir(parents=True, exist_ok=True)
    result_path = result_dir / f"{safe_name}.json"
    if result_path.is_symlink():
        raise ValueError(f"performance result must not be a symlink: {result_path}")
    result = {
        "schema_version": PERFORMANCE_RESULT_SCHEMA_VERSION,
        "test_case": node_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metrics": _normalize_metrics(metrics),
        "waveform": {
            "path": waveform.relative_to(workspace).as_posix(),
            "sha256": waveform_hash,
            "format": waveform.suffix.lower().lstrip("."),
        },
        "stimulus": stimulus,
        "measurement": {
            "start_time": _finite_number(stimulus["start_time"], "start_time"),
            "end_time": _finite_number(stimulus["end_time"], "end_time"),
            "duration": duration,
            "time_unit": time_unit,
            "transaction_count": transaction_count,
        },
        "stimulus_sha256": stimulus_hash,
        "input_trace_sha256": input_trace_hash,
    }
    fd, temporary = tempfile.mkstemp(
        prefix=f".{result_path.name}.", suffix=".tmp", dir=result_dir
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file_obj:
            json.dump(result, file_obj, indent=2, ensure_ascii=False, allow_nan=False)
            file_obj.write("\n")
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.replace(temporary, result_path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return result_path.relative_to(workspace).as_posix()


def build_performance_manifest(
    workspace: str | os.PathLike[str],
    result_files: list[Path],
    destination: Path,
) -> dict[str, Any]:
    """Build and atomically persist a stable manifest from validated TC sidecars."""

    workspace_path = Path(workspace).resolve()
    rows = []
    seen_tests: set[str] = set()
    seen_waveforms: set[str] = set()
    for result_file in sorted(result_files, key=lambda item: item.as_posix()):
        with result_file.open("r", encoding="utf-8") as file_obj:
            result = json.load(file_obj)
        test_case = result["test_case"]
        waveform_path = result["waveform"]["path"]
        if test_case in seen_tests:
            raise ValueError(f"duplicate performance test_case: {test_case}")
        if waveform_path in seen_waveforms:
            raise ValueError(f"duplicate performance waveform: {waveform_path}")
        seen_tests.add(test_case)
        seen_waveforms.add(waveform_path)
        rows.append(
            {
                "test_case": test_case,
                "result_path": result_file.relative_to(workspace_path).as_posix(),
                "result_sha256": _sha256_file(result_file),
                "waveform": result["waveform"],
                "metrics": result["metrics"],
                "measurement": result["measurement"],
                "deterministic": result["stimulus"]["deterministic"],
                "seed": result["stimulus"]["seed"],
                "parameters": result["stimulus"]["parameters"],
                "stimulus_sha256": result["stimulus_sha256"],
                "input_trace_sha256": result["input_trace_sha256"],
            }
        )
    manifest = {
        "schema_version": PERFORMANCE_MANIFEST_SCHEMA_VERSION,
        "tests": rows,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file_obj:
            json.dump(manifest, file_obj, indent=2, ensure_ascii=False, allow_nan=False)
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
    return manifest
