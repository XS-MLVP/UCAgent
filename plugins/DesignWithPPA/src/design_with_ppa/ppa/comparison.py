"""Metric changes and measurement-condition compatibility for PPA reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import math


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
    for key in ("backend", "pdk"):
        if not baseline_provenance.get(key) or baseline_provenance.get(key) != current_provenance.get(key):
            area_reasons.append(f"{key}_changed_or_unknown")
    baseline_versions = {key: row.get("version") for key, row in baseline_provenance.get("tools", {}).items()}
    current_versions = {key: row.get("version") for key, row in current_provenance.get("tools", {}).items()}
    if baseline_versions != current_versions:
        area_reasons.append("tool_versions_changed")
    if _nested_value(baseline, ("summary", "area", "unit")) != _nested_value(current, ("summary", "area", "unit")):
        area_reasons.append("area_unit_changed")
    if not same_top:
        area_reasons.append("top_module_changed")
    if not same_rtl_libraries:
        area_reasons.append("rtl_library_set_changed")
    if not same_liberty and (baseline_provenance.get("liberty_sha256") is not None or current_provenance.get("liberty_sha256") is not None):
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

    if baseline.get("schema_version") != "1.2":
        raise ValueError(
            "baseline report schema_version must be 1.2; rerun AnalyzePPA to create a current cache entry"
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
            unit = spec.unit
            if group_name == "area" and spec.name in {"total", "sequential", "combinational"}:
                unit = _nested_value(current, ("summary", "area", "unit")) or unit
            change = _metric_change(
                _nested_value(baseline, spec.path),
                _nested_value(current, spec.path),
                preference=spec.preference,
                unit=unit,
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
                        "unit": unit,
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
    """Compare two schema-1.2 PPA reports without running analysis tools."""

    if not isinstance(baseline, dict) or not isinstance(current, dict):
        raise TypeError("baseline and current PPA reports must be mappings")
    if current.get("schema_version") != "1.2":
        raise ValueError(
            "current report schema_version must be 1.2; rerun AnalyzePPA"
        )
    return _compare_reports(baseline, current)
