"""Normalize synthesis statistics and OpenSTA timing and power artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import math
import re

from .models import _STATE_CELL_RE
from .common import _tail


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
