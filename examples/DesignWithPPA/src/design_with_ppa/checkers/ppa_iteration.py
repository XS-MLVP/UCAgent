"""Strict-Pareto PPA base/candidate iteration engine and helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any
from ucagent.checkers.base import Checker
from ..contracts import (
    atomic_json,
    diagnostic,
    finite_number,
    load_json,
    load_yaml,
    no_improvement_patience,
    no_regression_metric_categories,
    optimization_limits,
    ppa_score_weights,
    resolve_workspace_path,
    resolved_output,
    sha256_file,
)
from ..ppa import (
    AnalyzePPA,
    AnalyzePPAArgs,
    compare_ppa_reports,
)
from ..rtl import (
    RTLPreparationRequest,
    discover_rtl_libraries,
    discover_rtl_sources,
    resolve_rtl_config,
    validate_prepared_rtl,
)

from .common import (
    _VERILOG_IDENTIFIER_RE,
    _bounded_checker_value,
    _contract_identity,
    _hash_rows,
    _rows_sha256,
    _test_source_rows,
    _validated_input_identity,
)
from .evidence import (
    _public_evidence_error,
    _pytest_evidence,
    _redact_backend_output,
)
from .performance_checkers import (
    _validate_performance_contract,
)
from . import runtime  # qualified so tests patch one runtime module


_PPA_SCORE_ID = "ppa.selection_score"


def _ppa_score_formula(weights: dict[str, float]) -> str:
    """Render the weight-aware selection-score formula for evidence artifacts."""

    return " * ".join(
        f"{dimension}_efficiency"
        if weights.get(dimension, 1.0) == 1.0
        else f"{dimension}_efficiency^{weights[dimension]:g}"
        for dimension in ("timing", "area", "power")
    )


def _metric_category(metric_id: str) -> str:
    """Classify one primary metric id into its no-regression category.

    Simulation latency/throughput metrics from the performance contract have
    DUT-defined ids and form the ``performance`` category; every primary PPA
    metric is prefixed with its ``ppa.<category>.`` group.
    """

    if metric_id.startswith("ppa.area."):
        return "area"
    if metric_id.startswith("ppa.timing."):
        return "timing"
    if metric_id.startswith("ppa.power."):
        return "power"
    return "performance"


_DASHBOARD_SNAPSHOT_START = (
    '<script id="design-with-ppa-snapshot" type="application/json">'
)


_DASHBOARD_SNAPSHOT_END = "</script>"


def _copy_rtl_snapshot(
    workspace: Path,
    rtl_language: str,
    rtl_files: list[Path],
    destination: Path,
) -> str:
    """Snapshot authored RTL, returning its aggregate digest."""

    state_root = workspace / ".ucagent" / "design_with_ppa"
    state_root.mkdir(parents=True, exist_ok=True)
    if state_root.is_symlink() or destination.is_symlink():
        raise ValueError("DesignWithPPA state and snapshot paths must not be symlinks")
    source_rows = _hash_rows(workspace, rtl_files)
    aggregate = _rows_sha256(source_rows)
    if destination.exists():
        manifest = load_json(destination / "snapshot.json")
        if (
            manifest.get("schema_version") != "1.1"
            or manifest.get("rtl_language") != rtl_language
            or manifest.get("rtl_sources") != source_rows
            or manifest.get("snapshot_sha256") != aggregate
        ):
            raise ValueError(f"RTL snapshot already exists with different content: {destination}")
        for row in source_rows:
            snapshot_source = resolve_workspace_path(
                destination, row["path"], must_exist=True
            )
            if sha256_file(snapshot_source) != row["sha256"]:
                raise ValueError(f"existing RTL snapshot hash mismatch: {row['path']}")
        return aggregate
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent)
    )
    try:
        snapshot_files = {
            row["path"]: source for source, row in zip(rtl_files, source_rows)
        }
        for relative_value, source in sorted(snapshot_files.items()):
            relative = Path(relative_value)
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if sha256_file(target) != sha256_file(source):
                raise ValueError(f"copied RTL snapshot hash mismatch: {relative_value}")
        manifest = {
            "schema_version": "1.1",
            "rtl_language": rtl_language,
            "rtl_sources": source_rows,
        }
        manifest["snapshot_sha256"] = aggregate
        atomic_json(temporary / "snapshot.json", manifest)
        os.replace(temporary, destination)
        return aggregate
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _restore_rtl_snapshot(
    workspace: Path,
    snapshot: Path,
    current_files: list[Path],
) -> str:
    """Restore accepted authored RTL with atomic replacements."""

    manifest = load_json(snapshot / "snapshot.json")
    source_rows = manifest.get("rtl_sources")
    if not isinstance(source_rows, list) or not source_rows:
        raise ValueError("accepted RTL snapshot manifest has no sources")
    expected: set[Path] = set()
    for row in source_rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise ValueError("accepted RTL snapshot source row is invalid")
        source = resolve_workspace_path(snapshot, row["path"], must_exist=True)
        if sha256_file(source) != row.get("sha256"):
            raise ValueError(f"accepted RTL snapshot hash mismatch: {row['path']}")
        target = resolve_workspace_path(workspace, row["path"])
        expected.add(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".restore", dir=target.parent
        )
        os.close(fd)
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
    for current in sorted(set(current_files)):
        if current.resolve() not in expected:
            current.unlink()
    restored_sources = [
        resolve_workspace_path(workspace, row["path"], must_exist=True)
        for row in source_rows
    ]
    aggregate = _rows_sha256(_hash_rows(workspace, restored_sources))
    if aggregate != manifest.get("snapshot_sha256"):
        raise ValueError("restored RTL aggregate hash does not match accepted snapshot")
    return aggregate


def _load_cached_ppa(workspace: Path, report_id: str) -> dict[str, Any]:
    """Load an exact indexed PPA report from the internal immutable cache."""

    if not isinstance(report_id, str) or not re.fullmatch(r"ppa-[0-9a-f]{32}", report_id):
        raise ValueError("PPA report_id has an invalid format")
    cache = workspace / ".ucagent" / "ppa_reports"
    index = load_json(cache / "index.json")
    if index.get("schema_version") != "1.0" or not isinstance(index.get("reports"), list):
        raise ValueError("PPA cache index has an invalid schema")
    matches = [
        row
        for row in index["reports"]
        if isinstance(row, dict) and row.get("report_id") == report_id
    ]
    if not matches:
        raise FileNotFoundError(f"PPA report is not retained in cache: {report_id}")
    expected_hash = matches[0].get("sha256")
    if not isinstance(expected_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", expected_hash
    ):
        raise ValueError(f"PPA cache index lacks report integrity: {report_id}")
    report_path = cache / f"{report_id}.json"
    if sha256_file(report_path) != expected_hash:
        raise ValueError(f"cached PPA report hash mismatch: {report_id}")
    report = load_json(report_path)
    if report.get("report_id") != report_id or report.get("schema_version") != "1.1":
        raise ValueError(f"cached PPA report identity is invalid: {report_id}")
    return report


def _load_bound_ledger(
    workspace: Path, state: dict[str, Any], ledger_file: str
) -> dict[str, Any]:
    """Load the public ledger only when its exact bytes match private workflow state."""

    ledger_path = resolve_workspace_path(workspace, ledger_file, must_exist=True)
    expected_hash = state.get("ledger_sha256")
    if not isinstance(expected_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", expected_hash
    ):
        raise ValueError("private iteration state has no valid ledger_sha256")
    if sha256_file(ledger_path) != expected_hash:
        raise ValueError("optimization ledger differs from private workflow state")
    return load_yaml(ledger_path)


def _resolved_workflow_ppa_config(
    cfg: Any, top_module: str
) -> dict[str, Any]:
    """Return the finite PPA configuration bound to workflow history."""

    if not isinstance(top_module, str) or not _VERILOG_IDENTIFIER_RE.fullmatch(
        top_module
    ):
        raise ValueError("PPA configuration requires a valid top module")
    result = {
        "waveform_scope": cfg.get_value(
            "design_with_ppa.ppa.waveform_scope", f"TOP.{top_module}"
        ),
        "liberty_file": cfg.get_value("design_with_ppa.ppa.liberty_file", None),
        "sdc_file": cfg.get_value("design_with_ppa.ppa.sdc_file", None),
        "clock_port": cfg.get_value("design_with_ppa.ppa.clock_port", None),
        "clock_period_ns": cfg.get_value(
            "design_with_ppa.ppa.clock_period_ns", None
        ),
        "max_timing_paths": cfg.get_value(
            "design_with_ppa.ppa.max_timing_paths", 10
        ),
        "max_power_instances": cfg.get_value(
            "design_with_ppa.ppa.max_power_instances", 10
        ),
    }
    try:
        json.dumps(result, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("resolved PPA configuration must be finite JSON") from exc
    return result


def _run_workflow_ppa(
    workspace: Path,
    cfg: Any,
    architecture: dict[str, Any],
    rtl_config: Any,
    rtl_language_backend: Any,
    rtl_files: list[Path],
    rtl_rows: list[dict[str, str]],
    rtl_library_files: tuple[Path, ...],
    rtl_library_rows: list[dict[str, Any]],
    prepared_content: dict[str, Any],
    performance_manifest: dict[str, Any],
    report_file: str,
    baseline_report_id: str | None,
    timeout: int,
) -> dict[str, Any]:
    """Prepare private analysis inputs and create one workflow-owned PPA report."""

    top_module = architecture.get("top_module")
    if not isinstance(top_module, str) or not _VERILOG_IDENTIFIER_RE.fullmatch(
        top_module
    ):
        raise ValueError("architecture top_module is invalid")
    waveform_files = [
        row.get("waveform", {}).get("path")
        for row in performance_manifest.get("tests", [])
        if isinstance(row, dict)
    ]
    if not waveform_files or any(not isinstance(path, str) for path in waveform_files):
        raise ValueError("performance manifest has no valid ordered waveform set")
    ppa_config = _resolved_workflow_ppa_config(cfg, top_module)
    build_root = Path(tempfile.mkdtemp(prefix="ucagent-design-with-ppa-ppa-"))
    try:
        request = RTLPreparationRequest(
            workspace=workspace,
            language=rtl_config.language,
            top_module=top_module,
            source_files=tuple(rtl_files),
            library_files=rtl_library_files,
            build_dir=build_root,
            language_options=rtl_config.language_options,
            python_dut_options=rtl_config.python_dut_options,
            timeout=timeout,
        )
        prepared = validate_prepared_rtl(
            workspace,
            request,
            rtl_language_backend.prepare(request),
        )
        if prepared.content_identity() != prepared_content:
            raise ValueError(
                "prepared RTL content differs from the synchronized Python-DUT build"
            )
        arguments = AnalyzePPAArgs(
            rtl_files=[row["path"] for row in rtl_rows],
            top_module=top_module,
            waveform_files=waveform_files,
            waveform_scope=ppa_config["waveform_scope"],
            liberty_file=ppa_config["liberty_file"],
            sdc_file=ppa_config["sdc_file"],
            clock_port=ppa_config["clock_port"],
            clock_period_ns=ppa_config["clock_period_ns"],
            report_path=report_file,
            baseline_report_id=baseline_report_id,
            max_timing_paths=ppa_config["max_timing_paths"],
            max_power_instances=ppa_config["max_power_instances"],
            timeout=timeout,
        )
        report = AnalyzePPA(
            workspace=str(workspace),
            output_dir=resolved_output(cfg),
            write_dirs=[resolved_output(cfg)],
            un_write_dirs=[],
        ).analyze(
            arguments,
            rtl_provenance=rtl_rows,
            rtl_library_provenance=rtl_library_rows,
            trusted_rtl_library_files=rtl_library_files,
            trusted_rtl_files=prepared.analysis_verilog_files,
        )
    finally:
        shutil.rmtree(build_root, ignore_errors=True)
    return report


def _aggregate_contract_metrics(
    manifest: dict[str, Any], contract_metrics: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Aggregate measured values according to each performance contract metric."""

    values: dict[str, list[float]] = {metric_id: [] for metric_id in contract_metrics}
    tests = manifest.get("tests")
    if not isinstance(tests, list) or not tests:
        raise ValueError("performance manifest tests must be non-empty")
    for test in tests:
        if not isinstance(test, dict) or not isinstance(test.get("metrics"), list):
            raise ValueError("performance manifest metric rows are invalid")
        for row in test["metrics"]:
            metric_id = row.get("id") if isinstance(row, dict) else None
            if metric_id in values:
                values[metric_id].append(finite_number(row.get("value"), metric_id))
    aggregated = {}
    for metric_id, contract in contract_metrics.items():
        rows = values[metric_id]
        if not rows:
            raise ValueError(f"performance metric has no measured values: {metric_id}")
        aggregation = contract["aggregation"]
        ordered = sorted(rows)
        if aggregation == "min":
            value = min(rows)
        elif aggregation == "max":
            value = max(rows)
        elif aggregation == "sum":
            value = sum(rows)
        elif aggregation == "mean":
            value = sum(rows) / len(rows)
        else:
            rank = max(0, min(len(ordered) - 1, int(0.95 * len(ordered) + 0.999999) - 1))
            value = ordered[rank]
        aggregated[metric_id] = {
            "value": value,
            "unit": contract["unit"],
            "direction": contract["direction"],
            "target": contract["target"],
            "hard_requirement": contract["hard_requirement"],
            "aggregation": aggregation,
        }
    return aggregated


def _ppa_primary_metrics(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract complete normalized area, timing, and power primary metrics."""

    if report.get("status") != "success":
        raise ValueError("PPA report status must be success")
    summary = report.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("PPA report summary is missing")
    area = finite_number(summary.get("area", {}).get("total"), "PPA area.total")
    power = finite_number(summary.get("power", {}).get("total_w"), "PPA power.total_w")
    timing = summary.get("timing")
    if not isinstance(timing, dict):
        raise ValueError("PPA timing summary is missing")
    maximum_frequency = timing.get("maximum_frequency_hz")
    if timing.get("metric_kind") == "minimum_clock_period" and isinstance(
        maximum_frequency, (int, float)
    ) and not isinstance(maximum_frequency, bool):
        timing_name = "maximum_frequency_hz"
        timing_value = finite_number(maximum_frequency, "PPA maximum_frequency_hz")
        timing_direction = "max"
        timing_unit = "Hz"
    else:
        timing_name = "critical_path_delay_ns"
        timing_value = finite_number(
            timing.get("critical_path_delay_ns"), "PPA critical_path_delay_ns"
        )
        timing_direction = "min"
        timing_unit = "ns"
    return {
        "ppa.area.total": {"value": area, "unit": "library_area", "direction": "min"},
        f"ppa.timing.{timing_name}": {
            "value": timing_value,
            "unit": timing_unit,
            "direction": timing_direction,
        },
        "ppa.power.total_w": {"value": power, "unit": "W", "direction": "min"},
    }


def _ppa_selection_score(
    base_metrics: dict[str, dict[str, Any]],
    current_metrics: dict[str, dict[str, Any]],
    *,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Return one base-normalized performance-per-power-area ranking score.

    One timing metric represents performance: frequency is used directly when
    available, while critical delay is inverted. Area and power are inverted
    because smaller values are better. The dimensionless score is ``1.0`` for
    base and larger is better, computed as the product of each dimension's
    efficiency ratio raised to its configured weight (default ``1.0`` each;
    ``0`` removes the dimension). Custom functional performance metrics carry
    no weight because the frequency metric already represents them through a
    deterministic linear relationship. The score ranks only versions that
    already passed all functional, hard-target, comparability, and
    no-regression acceptance gates; rejected versions may still carry a
    diagnostic score for comparison.
    """

    resolved_weights = {
        dimension: 1.0 for dimension in ("timing", "area", "power")
    }
    if weights is not None:
        if set(weights) != set(resolved_weights):
            raise ValueError("PPA score weights must cover timing, area, and power")
        for dimension, value in weights.items():
            resolved_weights[dimension] = finite_number(
                value, f"PPA score weight {dimension}"
            )
            if resolved_weights[dimension] < 0.0:
                raise ValueError("PPA score weights must be non-negative")
    required = ("ppa.area.total", "ppa.power.total_w")
    timing_ids = sorted(
        metric_id for metric_id in base_metrics if metric_id.startswith("ppa.timing.")
    )
    if any(metric_id not in base_metrics for metric_id in required) or len(timing_ids) != 1:
        raise ValueError("PPA score requires area, power, and exactly one timing metric")
    component_ids = {
        "timing": timing_ids[0],
        "area": "ppa.area.total",
        "power": "ppa.power.total_w",
    }
    components: dict[str, dict[str, Any]] = {}
    unavailable = []
    score = 1.0
    for component, metric_id in component_ids.items():
        base = base_metrics[metric_id]
        current = current_metrics.get(metric_id)
        if not isinstance(base, dict) or not isinstance(current, dict):
            raise ValueError(f"PPA score metric is missing: {metric_id}")
        if (
            current.get("unit") != base.get("unit")
            or current.get("direction") != base.get("direction")
            or base.get("direction") not in {"min", "max"}
        ):
            raise ValueError(f"PPA score metric contract changed: {metric_id}")
        base_value = finite_number(base.get("value"), f"base PPA score {metric_id}")
        current_value = finite_number(
            current.get("value"), f"current PPA score {metric_id}"
        )
        if base_value <= 0.0 or current_value <= 0.0:
            ratio = None
            unavailable.append(metric_id)
        elif base["direction"] == "max":
            ratio = current_value / base_value
        else:
            ratio = base_value / current_value
        if ratio is not None:
            score *= finite_number(ratio, f"PPA score ratio {metric_id}") ** float(
                resolved_weights[component]
            )
        components[component] = {
            "metric_id": metric_id,
            "base": base_value,
            "current": current_value,
            "unit": base["unit"],
            "direction": base["direction"],
            "weight": resolved_weights[component],
            "efficiency_ratio": round(ratio, 12) if ratio is not None else None,
        }
    return {
        "metric_id": _PPA_SCORE_ID,
        "value": round(score, 12) if not unavailable else None,
        "unit": "x_base",
        "direction": "max",
        "status": "available" if not unavailable else "unavailable",
        "formula": _ppa_score_formula(resolved_weights),
        "weights": dict(resolved_weights),
        "baseline_iteration": 0,
        "components": components,
        "unavailable_metrics": unavailable,
    }


def _embed_dashboard_snapshot(
    dashboard_text: str, snapshot: dict[str, Any]
) -> str:
    """Replace the dashboard's inert JSON snapshot without enabling HTML injection."""

    start = dashboard_text.find(_DASHBOARD_SNAPSHOT_START)
    if start < 0 or dashboard_text.find(_DASHBOARD_SNAPSHOT_START, start + 1) >= 0:
        raise ValueError("design dashboard must contain one embedded snapshot container")
    payload_start = start + len(_DASHBOARD_SNAPSHOT_START)
    end = dashboard_text.find(_DASHBOARD_SNAPSHOT_END, payload_start)
    if end < 0:
        raise ValueError("design dashboard embedded snapshot container is not closed")
    payload = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    payload = (
        payload.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    return dashboard_text[:payload_start] + payload + dashboard_text[end:]


def _public_ppa_summary(report: dict[str, Any]) -> dict[str, Any]:
    """Return bounded PPA data that can guide source edits without internal identities."""

    summary = report.get("summary")
    details = report.get("details")
    if not isinstance(summary, dict):
        return {}
    area = summary.get("area") if isinstance(summary.get("area"), dict) else {}
    timing = (
        summary.get("timing") if isinstance(summary.get("timing"), dict) else {}
    )
    power = summary.get("power") if isinstance(summary.get("power"), dict) else {}
    details = details if isinstance(details, dict) else {}
    area_by_cell_type = details.get("area_by_cell_type")
    power_groups = details.get("power_groups")
    return {
        "design_type": summary.get("design_type"),
        "area": {
            key: area.get(key)
            for key in (
                "total",
                "sequential",
                "combinational",
                "cell_count",
                "sequential_cell_count",
                "combinational_cell_count",
            )
            if key in area
        },
        "timing": {
            key: timing.get(key)
            for key in (
                "metric_kind",
                "critical_path_delay_ns",
                "maximum_frequency_hz",
                "equivalent_max_frequency_hz",
                "wns_ns",
                "tns_ns",
            )
            if key in timing
        },
        "power": {
            key: power.get(key)
            for key in (
                "total_w",
                "dynamic_w",
                "internal_w",
                "switching_w",
                "leakage_w",
            )
            if key in power
        },
        "area_by_cell_type": (
            dict(list(sorted(area_by_cell_type.items()))[:20])
            if isinstance(area_by_cell_type, dict)
            else {}
        ),
        "power_groups": (
            power_groups[:20]
            if isinstance(power_groups, list)
            else power_groups
            if isinstance(power_groups, dict)
            else {}
        ),
    }


def _metric_assessment(
    baseline: float,
    current: float,
    direction: str,
    *,
    rel_tol: float,
    abs_tol: float,
) -> str:
    """Classify one normalized metric with fixed absolute and relative tolerances."""

    tolerance = max(abs_tol, rel_tol * max(abs(baseline), abs(current)))
    delta = current - baseline
    if abs(delta) <= tolerance:
        return "unchanged"
    if direction == "min":
        return "improved" if delta < 0 else "regressed"
    return "improved" if delta > 0 else "regressed"


def _primary_metric_changes(
    baseline_metrics: dict[str, dict[str, Any]],
    current_metrics: dict[str, dict[str, Any]],
    *,
    rel_tol: float,
    abs_tol: float,
) -> dict[str, dict[str, Any]]:
    """Compare one complete normalized primary-metric set with fixed tolerances."""

    if set(baseline_metrics) != set(current_metrics):
        raise ValueError("primary metric sets differ")
    changes = {}
    for metric_id in sorted(current_metrics):
        baseline = baseline_metrics[metric_id]
        current = current_metrics[metric_id]
        if current.get("unit") != baseline.get("unit") or current.get(
            "direction"
        ) != baseline.get("direction"):
            raise ValueError(f"primary metric contract changed: {metric_id}")
        baseline_value = finite_number(baseline.get("value"), metric_id)
        current_value = finite_number(current.get("value"), metric_id)
        delta = current_value - baseline_value
        changes[metric_id] = {
            "baseline": baseline_value,
            "current": current_value,
            "delta": delta,
            "percent_change": (
                (delta / abs(baseline_value)) * 100.0
                if baseline_value != 0.0
                else (0.0 if delta == 0.0 else None)
            ),
            "unit": current["unit"],
            "direction": current["direction"],
            "assessment": _metric_assessment(
                baseline_value,
                current_value,
                current["direction"],
                rel_tol=rel_tol,
                abs_tol=abs_tol,
            ),
        }
    return changes


def select_best_accepted_record(
    records: list[dict[str, Any]],
    *,
    rel_tol: float = 1e-6,
    abs_tol: float = 1e-12,
    categories: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Select the unique best complete accepted version without a weighted score.

    The optimization contract defines a partial order rather than an arbitrary
    area/timing/power weighting.  A record dominates another when every
    comparable primary metric is no worse and at least one is strictly better,
    using the recorded metric direction and fixed tolerances.  When
    ``categories`` is given, only metrics inside those no-regression
    categories participate in dominance and equivalence; the default ``None``
    compares every primary metric.  The selected record must dominate every
    other complete accepted record.  If all records are equivalent, the newest
    iteration is selected; incomparable frontiers are rejected as invalid
    evidence instead of being guessed.
    """

    if not isinstance(records, list) or not records:
        raise ValueError("accepted record list is empty")
    if rel_tol < 0 or abs_tol < 0:
        raise ValueError("Pareto tolerances must be non-negative")

    accepted: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict) or record.get("accepted") is not True:
            continue
        if record.get("functional_regression", {}).get("pass") is not True:
            continue
        ppa_metrics = record.get("ppa_metrics")
        performance_metrics = record.get("performance_metrics")
        if not isinstance(ppa_metrics, dict) or not ppa_metrics:
            continue
        if not isinstance(performance_metrics, dict) or not performance_metrics:
            continue
        metrics = {**ppa_metrics, **performance_metrics}
        for metric_id, metric in metrics.items():
            if not isinstance(metric, dict):
                raise ValueError(f"accepted metric is invalid: {metric_id}")
            if metric.get("direction") not in {"min", "max"}:
                raise ValueError(f"accepted metric direction is invalid: {metric_id}")
            if not isinstance(metric.get("unit"), str) or not metric["unit"]:
                raise ValueError(f"accepted metric unit is invalid: {metric_id}")
            finite_number(metric.get("value"), f"accepted metric {metric_id}")
        accepted.append(record)
    if not accepted:
        raise ValueError("no complete accepted record is available")

    metric_sets = [
        set(record.get("ppa_metrics", {}))
        | set(record.get("performance_metrics", {}))
        for record in accepted
    ]
    if any(metric_set != metric_sets[0] for metric_set in metric_sets[1:]):
        raise ValueError("accepted primary metric sets differ")

    scoped = frozenset(categories) if categories is not None else None

    def metrics_for(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Return the merged and category-scoped metric vector for one record."""

        merged = {
            **record.get("ppa_metrics", {}),
            **record.get("performance_metrics", {}),
        }
        if scoped is None:
            return merged
        return {
            metric_id: metric
            for metric_id, metric in merged.items()
            if _metric_category(metric_id) in scoped
        }

    def dominates(left: dict[str, Any], right: dict[str, Any]) -> bool:
        """Return whether ``left`` strictly Pareto-dominates ``right``."""

        changes = _primary_metric_changes(
            metrics_for(right),
            metrics_for(left),
            rel_tol=rel_tol,
            abs_tol=abs_tol,
        )
        assessments = [change["assessment"] for change in changes.values()]
        return bool(assessments) and all(
            assessment in {"improved", "unchanged"} for assessment in assessments
        ) and "improved" in assessments

    maximal = [
        candidate
        for candidate in accepted
        if not any(
            other is not candidate and dominates(other, candidate)
            for other in accepted
        )
    ]
    if len(maximal) == 1:
        return maximal[0]
    # Equal metric vectors are deliberately resolved by iteration, which keeps
    # the final artifact stable while avoiding an invented scalar objective.
    equivalent = maximal[0]
    equivalent_metrics = metrics_for(equivalent)
    if all(
        all(
            change["assessment"] == "unchanged"
            for change in _primary_metric_changes(
                equivalent_metrics,
                metrics_for(candidate),
                rel_tol=rel_tol,
                abs_tol=abs_tol,
            ).values()
        )
        for candidate in maximal[1:]
    ):
        return max(
            maximal,
            key=lambda record: (
                record.get("iteration", -1)
                if isinstance(record.get("iteration"), int)
                and not isinstance(record.get("iteration"), bool)
                else -1
            ),
        )
    raise ValueError("accepted records contain an incomparable Pareto frontier")


def _load_candidate_hypothesis(
    hypothesis_path: Path,
    candidate_index: int,
    processed_hashes: list[str],
) -> tuple[dict[str, Any], str]:
    """Load one iteration-bound hypothesis and reject replay of processed content."""

    hypothesis = load_yaml(hypothesis_path)
    if set(hypothesis) != {
        "iteration",
        "hypothesis",
        "target_hotspot",
        "expected_metrics",
    }:
        raise ValueError(
            "candidate hypothesis must contain exactly iteration, hypothesis, "
            "target_hotspot, and expected_metrics"
        )
    iteration = hypothesis["iteration"]
    if (
        isinstance(iteration, bool)
        or not isinstance(iteration, int)
        or iteration != candidate_index
    ):
        raise ValueError(
            f"candidate hypothesis iteration must be {candidate_index}"
        )
    if not isinstance(hypothesis["hypothesis"], str) or not hypothesis[
        "hypothesis"
    ].strip():
        raise ValueError("candidate hypothesis must be non-empty")
    if not isinstance(hypothesis["target_hotspot"], str) or not hypothesis[
        "target_hotspot"
    ].strip():
        raise ValueError("candidate target_hotspot must be non-empty")
    expected_metrics = hypothesis["expected_metrics"]
    if (
        not isinstance(expected_metrics, list)
        or not expected_metrics
        or any(not isinstance(metric, str) or not metric.strip() for metric in expected_metrics)
        or len(set(expected_metrics)) != len(expected_metrics)
    ):
        raise ValueError(
            "candidate expected_metrics must be a non-empty list of unique strings"
        )
    hypothesis_hash = sha256_file(hypothesis_path)
    if hypothesis_hash in processed_hashes:
        raise ValueError(
            "candidate hypothesis content was already processed; write a new "
            "iteration-bound hypothesis before changing RTL"
        )
    return hypothesis, hypothesis_hash


class PPAIterationChecker(Checker):
    """Create a PPA base or evaluate candidate rounds against persisted Pareto state."""

    def __init__(
        self,
        test_dir: str,
        functional_test_glob: str,
        performance_contract_file: str,
        performance_manifest_file: str,
        ppa_report_file: str,
        rtl_backend_manifest_file: str,
        ledger_file: str,
        base_report_file: str,
        iteration_report_dir: str,
        timeout: int,
        cfg: Any,
        phase: str = "optimization",
        rel_tolerance: float = 1e-6,
        abs_tolerance: float = 1e-12,
        ret_std_out: bool = True,
        ret_std_error: bool = True,
        input_manifest_file: str | None = None,
        design_contract_files: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Store one explicit base/optimization phase and its artifact contract."""

        super().__init__()
        del kwargs
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
            raise ValueError("timeout must be a positive integer")
        self.cfg = cfg
        if phase not in {"base", "optimization"}:
            raise ValueError("phase must be base or optimization")
        self.phase = phase
        self.rtl_config, self.rtl_language_backend = resolve_rtl_config(cfg)
        self.test_dir = test_dir
        self.functional_test_glob = functional_test_glob
        self.performance_contract_file = performance_contract_file
        self.performance_manifest_file = performance_manifest_file
        self.ppa_report_file = ppa_report_file
        self.rtl_backend_manifest_file = rtl_backend_manifest_file
        self.ledger_file = ledger_file
        self.base_report_file = base_report_file
        self.iteration_report_dir = iteration_report_dir
        self.timeout = timeout
        self.rel_tolerance = finite_number(rel_tolerance, "rel_tolerance")
        self.abs_tolerance = finite_number(abs_tolerance, "abs_tolerance")
        for field, value in (
            ("ret_std_out", ret_std_out),
            ("ret_std_error", ret_std_error),
        ):
            if not isinstance(value, bool):
                raise ValueError(f"{field} must be a bool")
        self.ret_std_out = ret_std_out
        self.ret_std_error = ret_std_error
        if design_contract_files is not None and (
            not isinstance(design_contract_files, list)
            or any(
                not isinstance(value, str) or not value
                for value in design_contract_files
            )
        ):
            raise ValueError(
                "design_contract_files must be a list of non-empty strings"
            )
        self.input_manifest_file = input_manifest_file
        self.design_contract_files = list(design_contract_files or [])
        if self.rel_tolerance < 0 or self.abs_tolerance < 0:
            raise ValueError("Pareto tolerances must be non-negative")
        self.min_optimization_iterations, self.max_optimization_iterations = optimization_limits(cfg)
        self.no_improvement_patience = no_improvement_patience(cfg)
        self.no_regression_categories = no_regression_metric_categories(cfg)
        self.score_weights = ppa_score_weights(cfg)
        self._cached_status = "not_initialized"
        self._cached_candidate_count = 0
        self._cached_accepted_iteration: int | None = None
        self._cached_best_iteration: int | None = None
        self._cached_best_report_id: str | None = None
        self._cached_no_improvement_count = 0

    def _cache_state(self, state: dict[str, Any] | None) -> None:
        """Project persisted state into read-only CurrentTips template values."""

        if state is None:
            self._cached_status = "not_initialized"
            self._cached_candidate_count = 0
            self._cached_accepted_iteration = None
            self._cached_best_iteration = None
            self._cached_best_report_id = None
            self._cached_no_improvement_count = 0
            return
        self._cached_status = str(state.get("status", "invalid"))
        candidate_count = state.get("candidate_count", 0)
        accepted_iteration = state.get("accepted_iteration")
        best_iteration = state.get("best_iteration")
        best_report_id = state.get("best_report_id")
        no_improvement_count = state.get("no_improvement_count", 0)
        self._cached_candidate_count = (
            candidate_count
            if isinstance(candidate_count, int) and not isinstance(candidate_count, bool)
            else 0
        )
        self._cached_accepted_iteration = (
            accepted_iteration
            if isinstance(accepted_iteration, int)
            and not isinstance(accepted_iteration, bool)
            else None
        )
        self._cached_best_iteration = (
            best_iteration
            if isinstance(best_iteration, int) and not isinstance(best_iteration, bool)
            else None
        )
        self._cached_best_report_id = (
            best_report_id if isinstance(best_report_id, str) and best_report_id else None
        )
        self._cached_no_improvement_count = (
            no_improvement_count
            if isinstance(no_improvement_count, int)
            and not isinstance(no_improvement_count, bool)
            else 0
        )
        stage = getattr(self, "stage", None)
        meta_data = getattr(stage, "meta_data", None)
        if isinstance(meta_data, dict):
            meta_data["design_with_ppa_progress"] = {
                "status": self._cached_status,
                "candidate_count": self._cached_candidate_count,
                "accepted_iteration": self._cached_accepted_iteration,
                "best_iteration": self._cached_best_iteration,
                "best_report_id": self._cached_best_report_id,
                "no_improvement_count": self._cached_no_improvement_count,
            }

    def on_init(self):
        """Cache only the current persisted iteration status before rendering stage text."""

        workspace = Path(self.workspace).resolve()
        state_path = workspace / ".ucagent" / "design_with_ppa" / "state.json"
        if state_path.is_file() and not state_path.is_symlink():
            try:
                state = load_json(state_path)
                self._cache_state(state)
            except ValueError:
                self._cached_status = "invalid"
        return super().on_init()

    def get_template_data(self) -> dict[str, Any]:
        """Expose cached iteration status and both optimization bounds."""

        meta_data = getattr(getattr(self, "stage", None), "meta_data", {})
        progress = (
            meta_data.get("design_with_ppa_progress", {})
            if isinstance(meta_data, dict)
            else {}
        )
        if not isinstance(progress, dict):
            progress = {}
        candidate_count = progress.get("candidate_count", self._cached_candidate_count)
        if not isinstance(candidate_count, int) or isinstance(candidate_count, bool):
            candidate_count = self._cached_candidate_count
        status = progress.get("status", self._cached_status)
        no_improvement_count = progress.get(
            "no_improvement_count", self._cached_no_improvement_count
        )
        if not isinstance(no_improvement_count, int) or isinstance(
            no_improvement_count, bool
        ):
            no_improvement_count = self._cached_no_improvement_count
        remaining = max(
            0, self.min_optimization_iterations - candidate_count
        )
        if status == "not_initialized":
            next_candidate: int | None = 1 if self.min_optimization_iterations or self.max_optimization_iterations else None
        elif status == "awaiting_candidate":
            next_candidate = candidate_count + 1
        else:
            next_candidate = None
        return {
            "PPA_MIN_OPTIMIZATION_ITERATIONS": self.min_optimization_iterations,
            "PPA_MAX_OPTIMIZATION_ITERATIONS": self.max_optimization_iterations,
            "PPA_CANDIDATE_COUNT": candidate_count,
            "PPA_REMAINING_MIN_ITERATIONS": remaining,
            "PPA_NO_IMPROVEMENT_PATIENCE": self.no_improvement_patience,
            "PPA_NO_REGRESSION_METRICS": ",".join(self.no_regression_categories),
            "PPA_SCORE_WEIGHTS": ", ".join(
                f"{dimension}={self.score_weights[dimension]:g}"
                for dimension in ("timing", "area", "power")
            ),
            "PPA_NO_IMPROVEMENT_COUNT": no_improvement_count,
            "PPA_REMAINING_NO_IMPROVEMENT": max(
                0, self.no_improvement_patience - no_improvement_count
            ),
            "PPA_ACCEPTED_ITERATION": progress.get(
                "accepted_iteration", self._cached_accepted_iteration
            ),
            "PPA_BEST_ITERATION": progress.get(
                "best_iteration", self._cached_best_iteration
            ),
            "PPA_BEST_REPORT_ID": progress.get(
                "best_report_id", self._cached_best_report_id
            ),
            "PPA_NEXT_CANDIDATE": next_candidate,
        }

    def _persist(
        self,
        workspace: Path,
        state: dict[str, Any],
        ledger: dict[str, Any],
        message: str,
    ) -> str:
        """Persist private state and public ledger, snapshot history, then bind its hash."""

        state_path = workspace / ".ucagent" / "design_with_ppa" / "state.json"
        ledger_path = resolve_workspace_path(workspace, self.ledger_file)
        atomic_json(state_path, state)
        from ..contracts import atomic_yaml

        atomic_yaml(ledger_path, ledger)
        history_commit = self.stage.hist_snapshot(message)
        ledger["records"][-1]["internal_history_commit"] = history_commit
        atomic_yaml(ledger_path, ledger)
        state["ledger_sha256"] = sha256_file(ledger_path)
        atomic_json(state_path, state)
        self._cache_state(state)
        return history_commit

    def _restore(
        self,
        workspace: Path,
        state: dict[str, Any],
        current_files: list[Path],
    ) -> str:
        """Restore the last accepted language and analysis files."""

        snapshot_value = state.get("accepted_snapshot")
        if not isinstance(snapshot_value, str):
            raise ValueError("iteration state has no accepted_snapshot")
        snapshot = resolve_workspace_path(workspace, snapshot_value, must_exist=True)
        return _restore_rtl_snapshot(workspace, snapshot, current_files)

    def do_check(self, is_complete: bool = False, **kwargs: Any):
        """Build the base or evaluate one current candidate for the configured phase."""

        del is_complete, kwargs
        workspace = Path(self.workspace).resolve()
        min_iterations = self.min_optimization_iterations
        max_iterations = self.max_optimization_iterations
        state_root = workspace / ".ucagent" / "design_with_ppa"
        state_root.mkdir(parents=True, exist_ok=True)
        state_path = state_root / "state.json"
        if self.phase == "optimization" and not state_path.is_file():
            return False, diagnostic(
                "ppa_base_required",
                "The verified round-0 PPA base has not been recorded.",
                (
                    "Return to ppa_base_characterization and call Check. Proceed only after "
                    "that stage reports complete area, power, and timing/frequency metrics "
                    "for a functionally passing base."
                ),
                artifact=self.base_report_file,
                location=self.base_report_file,
                observed={"base_report": "not recorded"},
                expected="A successful round-0 report with area, power, and timing/frequency metrics.",
            )
        try:
            design_inputs = (
                _validated_input_identity(workspace, self.input_manifest_file)
                if self.input_manifest_file is not None
                else None
            )
            design_contracts = (
                _contract_identity(workspace, self.design_contract_files)
                if self.design_contract_files
                else None
            )
            performance_contracts = (
                _contract_identity(
                    workspace,
                    [*self.design_contract_files, self.performance_contract_file],
                )
                if self.design_contract_files
                else None
            )
            rtl_files = list(
                discover_rtl_sources(
                    workspace, self.rtl_config, self.rtl_language_backend
                )
            )
            rtl_rows = _hash_rows(workspace, rtl_files)
            rtl_hash = _rows_sha256(rtl_rows)
            rtl_library_files, rtl_library_provenance = discover_rtl_libraries(
                workspace, self.rtl_config, self.rtl_language_backend
            )
            rtl_library_rows = list(rtl_library_provenance)
            test_dir = resolve_workspace_path(workspace, self.test_dir, must_exist=True)
            functional_pattern = Path(self.functional_test_glob)
            if functional_pattern.is_absolute() or ".." in functional_pattern.parts:
                raise ValueError("functional_test_glob must remain workspace-relative")
            functional_test_files = sorted(
                path.resolve()
                for path in workspace.glob(self.functional_test_glob)
                if (
                    path.is_file()
                    and not path.is_symlink()
                    and "performance" not in path.name.lower()
                )
            )
            if not functional_test_files:
                raise ValueError(
                    f"no non-performance functional tests matched {self.functional_test_glob}"
                )
            rtl_backend_manifest_path = resolve_workspace_path(
                workspace, self.rtl_backend_manifest_file, must_exist=True
            )
            rtl_backend_manifest = load_json(rtl_backend_manifest_path)
            if rtl_backend_manifest.get("schema_version") != "1.4":
                raise ValueError("RTL backend manifest schema_version is invalid")
            builder = rtl_backend_manifest.get("python_dut_builder")
            if (
                not isinstance(builder, dict)
                or builder.get("coverage") is not True
                or builder.get("waveform_format") != "vcd"
            ):
                raise ValueError("RTL backend evidence capabilities are incomplete")
            if rtl_backend_manifest.get("rtl_language") != self.rtl_config.language:
                raise ValueError("RTL backend language differs from current configuration")
            if rtl_backend_manifest.get("rtl_config") != self.rtl_config.identity():
                raise ValueError("RTL backend configuration is stale")
            if rtl_backend_manifest.get("rtl_sources") != rtl_rows:
                raise ValueError("RTL backend is stale for the current RTL source set")
            if rtl_backend_manifest.get("rtl_libraries") != rtl_library_rows:
                raise ValueError("RTL backend is stale for the configured RTL libraries")
            prepared_content = rtl_backend_manifest.get("prepared_content")
            if (
                not isinstance(prepared_content, dict)
                or set(prepared_content) != {"analysis", "python_dut"}
            ):
                raise ValueError("RTL backend prepared-content identity is invalid")
            if self.input_manifest_file is not None and rtl_backend_manifest.get(
                "design_inputs"
            ) != design_inputs:
                raise ValueError("RTL backend design input identity is stale")
            if self.design_contract_files and rtl_backend_manifest.get(
                "contracts"
            ) != design_contracts:
                raise ValueError("RTL backend generated contract identity is stale")
            rtl_dut_identity = runtime._validate_workspace_python_dut(
                workspace, rtl_backend_manifest
            )
            test_source_rows = _test_source_rows(workspace, test_dir)
            test_source_hash = _rows_sha256(test_source_rows)
            if state_path.exists():
                source_state = load_json(state_path)
                if source_state.get("rtl_config") != self.rtl_config.identity():
                    return False, diagnostic(
                        "ppa_rtl_language_changed",
                        "The RTL language configuration changed after the base was recorded.",
                        (
                            "Restore the configured RTL language/options used by round 0, or "
                            "restart the workflow from RTL implementation when the language "
                            "change is intentional. All candidates must use one language contract."
                        ),
                        artifact="design_with_ppa.rtl",
                        location="design_with_ppa.rtl",
                        observed=self.rtl_config.identity(),
                        expected=source_state.get("rtl_config"),
                    )
                if source_state.get("base_rtl_libraries") != rtl_library_rows:
                    return False, diagnostic(
                        "ppa_rtl_libraries_changed",
                        "Configured RTL library contents changed after the base was recorded.",
                        (
                            "Restore every configured library path and file to the round-0 "
                            "identity, or restart from RTL validation and rebuild the base when "
                            "the library change is intentional."
                        ),
                        observed=rtl_library_rows,
                        expected=source_state.get("base_rtl_libraries"),
                        artifact="design_with_ppa.rtl.library_paths",
                        location="design_with_ppa.rtl.library_paths",
                    )
                if source_state.get("base_design_inputs") != design_inputs:
                    return False, diagnostic(
                        "ppa_design_inputs_changed",
                        "README or design Spec identity changed after the functional base was recorded.",
                        (
                            "Restart from design_needs_and_plan, remap the changed README/Spec "
                            "lines, and regenerate the contracts, shared tests, RTL, performance "
                            "evidence, and PPA base from the new requirements."
                        ),
                        observed=design_inputs,
                        expected=source_state.get("base_design_inputs"),
                        artifact=self.input_manifest_file,
                        location=self.input_manifest_file,
                    )
                if source_state.get("base_design_contracts") != design_contracts:
                    return False, diagnostic(
                        "ppa_design_contract_changed",
                        "Architecture or FG/FC/CK contract identity changed after the functional base was recorded.",
                        (
                            "Restart from the changed architecture or FG/FC/CK contract stage, "
                            "then regenerate the executable reference, shared tests, RTL, "
                            "performance evidence, and PPA base."
                        ),
                        artifact=(self.design_contract_files[0] if self.design_contract_files else self.performance_contract_file),
                        location=(self.design_contract_files[0] if self.design_contract_files else self.performance_contract_file),
                        observed=design_contracts,
                        expected=source_state.get("base_design_contracts"),
                    )
                if test_source_rows != source_state.get("base_test_sources"):
                    return False, diagnostic(
                        "ppa_test_contract_changed",
                        "The test/API/reference source set changed after the functional base was recorded.",
                        (
                            "If the change was accidental, restore the exact round-0 shared "
                            "test/API/reference sources. If it was required by the Spec, restart "
                            "from the affected Python TDD stage and rebuild RTL, performance "
                            "evidence, and the PPA base using the changed test contract."
                        ),
                        observed={"sha256": test_source_hash},
                        expected={
                            "sha256": source_state.get("base_test_sources_sha256")
                        },
                        artifact=self.test_dir,
                        location=self.test_dir,
                    )
            if self.phase == "base" and state_path.exists():
                state = load_json(state_path)
                ledger = _load_bound_ledger(workspace, state, self.ledger_file)
                records = ledger.get("records")
                if (
                    state.get("schema_version") != "1.5"
                    or ledger.get("schema_version") != "1.5"
                    or not isinstance(records, list)
                    or len(records) != 1
                    or records[0].get("iteration") != 0
                    or records[0].get("version") != 0
                    or records[0].get("kind") != "base"
                    or records[0].get("accepted") is not True
                    or state.get("candidate_count") != 0
                    or state.get("base_report_id") != records[0].get("ppa_report_id")
                    or state.get("accepted_rtl_sha256") != rtl_hash
                ):
                    candidate_count = state.get("candidate_count")
                    if (
                        state.get("schema_version") == "1.5"
                        and ledger.get("schema_version") == "1.5"
                        and isinstance(candidate_count, int)
                        and not isinstance(candidate_count, bool)
                        and candidate_count > 0
                    ):
                        raise ValueError(
                            "persisted PPA state already contains evaluated "
                            "candidate rounds; the base cannot be re-entered "
                            "after candidates exist - proceed to the "
                            "ppa_best_version_finalization Check instead"
                        )
                    raise ValueError("persisted PPA base state is incomplete or no longer isolated")
                base_report = _load_cached_ppa(workspace, state.get("base_report_id"))
                if base_report.get("status") != "success":
                    raise ValueError("persisted PPA base report is not complete")
                base_report_path = resolve_workspace_path(
                    workspace, self.base_report_file, must_exist=True
                )
                iteration_report_path = resolve_workspace_path(
                    workspace,
                    Path(self.iteration_report_dir) / "iteration-000.json",
                    must_exist=True,
                )
                if (
                    load_json(base_report_path) != base_report
                    or load_json(iteration_report_path) != base_report
                    or records[0].get("ppa_report_sha256")
                    != sha256_file(
                        workspace
                        / ".ucagent"
                        / "ppa_reports"
                        / f"{state['base_report_id']}.json"
                    )
                ):
                    raise ValueError("persisted PPA base report copies are inconsistent")
                snapshot_value = records[0].get("snapshot")
                if not isinstance(snapshot_value, str) or not snapshot_value:
                    raise ValueError("persisted PPA base snapshot identity is missing")
                snapshot = resolve_workspace_path(
                    workspace, snapshot_value, must_exist=True
                )
                snapshot_manifest = load_json(snapshot / "snapshot.json")
                snapshot_rows = snapshot_manifest.get("rtl_sources")
                if (
                    snapshot_manifest.get("schema_version") != "1.1"
                    or snapshot_manifest.get("rtl_language")
                    != self.rtl_config.language
                    or snapshot_manifest.get("snapshot_sha256") != rtl_hash
                    or records[0].get("snapshot_sha256") != rtl_hash
                    or not isinstance(snapshot_rows, list)
                    or not snapshot_rows
                    or _rows_sha256(snapshot_rows) != rtl_hash
                ):
                    raise ValueError("persisted PPA base snapshot is inconsistent")
                for row in snapshot_rows:
                    if (
                        not isinstance(row, dict)
                        or not isinstance(row.get("path"), str)
                        or not isinstance(row.get("sha256"), str)
                    ):
                        raise ValueError("persisted PPA base snapshot source row is invalid")
                    snapshot_source = resolve_workspace_path(
                        snapshot, row["path"], must_exist=True
                    )
                    if sha256_file(snapshot_source) != row["sha256"]:
                        raise ValueError(
                            f"persisted PPA base snapshot hash mismatch: {row['path']}"
                        )
                return True, {
                    "message": "Functional RTL and round-0 PPA base are recorded.",
                    "stop_reason": state.get("stop_reason"),
                    "accepted_iteration": 0,
                    "analysis": _public_ppa_summary(base_report),
                    "performance_metrics": records[0].get("performance_metrics"),
                }

            functional_result = runtime._run_pytest(
                workspace,
                test_dir,
                "rtl",
                self.timeout,
                [],
                test_files=functional_test_files,
                rtl_dut_identity=rtl_dut_identity,
            )
            functional_pass = functional_result.returncode == 0
        except subprocess.TimeoutExpired as exc:
            return False, diagnostic(
                "ppa_iteration_functional_timeout",
                f"Candidate functional regression exceeded {self.timeout} seconds.",
                (
                    "Run the shared test nodes individually with RunTestCases to identify the "
                    "first nonterminating transaction. Bound protocol waits with max_cycles and "
                    "repair that shared API/env behavior or selected-language RTL, then call "
                    "Check again. Increase the timeout only after each node terminates alone."
                ),
                artifact=self.test_dir,
                location=self.functional_test_glob,
                observed={
                    "timeout_seconds": self.timeout,
                    "reason": str(exc),
                    "partial_stdout_tail": _redact_backend_output(
                        runtime.timeout_stream_fragment(exc.stdout), 2000, (workspace,)
                    ),
                    "partial_stderr_tail": _redact_backend_output(
                        runtime.timeout_stream_fragment(exc.stderr), 2000, (workspace,)
                    ),
                },
                expected=f"The complete shared RTL regression terminates within {self.timeout} seconds.",
            )
        except (OSError, ValueError, FileNotFoundError) as exc:
            return False, diagnostic(
                "ppa_iteration_rtl_invalid",
                "The current authored RTL candidate could not enter functional evaluation.",
                (
                    "Use observed.reason to identify the exact source, top/port, library, "
                    "shared-test, or generated-runtime freshness failure. Repair the named "
                    "authored source/configuration, then call the RTL validation-stage Check "
                    "before retrying this PPA Check. Do not edit generated runtime evidence."
                ),
                artifact=self.rtl_config.source_glob,
                location=self.rtl_config.source_glob,
                observed={"reason": _redact_backend_output(str(exc), 4000, (workspace,))},
                expected="A current architecture-consistent RTL source/library set and a valid automatic RTL test runtime.",
            )

        if not functional_pass:
            if not state_path.exists():
                failure = _pytest_evidence(
                    functional_result,
                    ret_std_out=self.ret_std_out,
                    ret_std_error=self.ret_std_error,
                    sensitive_paths=(workspace,),
                )
                return False, diagnostic(
                    "ppa_base_functional_regression_failed",
                    "The proposed base RTL does not pass the full functional regression.",
                    (
                        "Start with the first failed node in observed. If collection/runtime "
                        "failed, repair that shared test, API, env, or reference contract. If "
                        "an assertion failed only for RTL, preserve the shared TC expectation "
                        "and repair the selected-language source. Call Check again to rerun all "
                        "functional, performance, and PPA base gates."
                    ),
                    artifact=self.rtl_config.source_glob,
                    location=(failure.get("failed_nodes") or [self.functional_test_glob])[0],
                    observed=failure,
                    expected="Every non-performance shared TC passes against the base RTL before PPA characterization.",
                )
            try:
                state = load_json(state_path)
                ledger = _load_bound_ledger(workspace, state, self.ledger_file)
                if state.get("status") == "complete":
                    raise ValueError("optimization already reached a terminal state")
                candidate_index = int(state.get("candidate_count", 0)) + 1
                if candidate_index > max_iterations:
                    raise ValueError("candidate count exceeds the configured maximum optimization limit")
                hypothesis_path = resolve_workspace_path(
                    workspace,
                    Path(resolved_output(self.cfg))
                    / "reports"
                    / "ppa"
                    / "candidate_hypothesis.yaml",
                    must_exist=True,
                )
                hypothesis, hypothesis_hash = _load_candidate_hypothesis(
                    hypothesis_path,
                    candidate_index,
                    state.get("processed_hypothesis_sha256", []),
                )
                hypothesis_text = hypothesis["hypothesis"]
                target_hotspot = hypothesis["target_hotspot"]
                expected_metrics = hypothesis["expected_metrics"]
                candidate_snapshot = (
                    state_root / "candidates" / f"iteration-{candidate_index:03d}"
                )
                candidate_snapshot.parent.mkdir(parents=True, exist_ok=True)
                candidate_snapshot_hash = _copy_rtl_snapshot(
                    workspace,
                    self.rtl_config.language,
                    rtl_files,
                    candidate_snapshot,
                )
                candidate_history_commit = self.stage.hist_snapshot(
                    f"DesignWithPPA candidate iteration {candidate_index:03d} evidence"
                )
                restored_hash = self._restore(workspace, state, rtl_files)
                # A functional regression is an invalid candidate, not evidence
                # that the PPA search has plateaued.  Preserve the patience
                # counter so a broken build/test environment cannot consume the
                # no-improvement budget or terminate the search.
                no_improvement_count = int(state.get("no_improvement_count", 0))
                stop_reason = None
                if candidate_index >= max_iterations:
                    stop_reason = "max_iterations_reached"
                record = {
                    "iteration": candidate_index,
                    "version": candidate_index,
                    "kind": "candidate",
                    "accepted": False,
                    "parent_accepted_iteration": state["accepted_iteration"],
                    "optimization_hypothesis": hypothesis_text,
                    "target_hotspot": target_hotspot,
                    "expected_metrics": expected_metrics,
                    "hypothesis_sha256": hypothesis_hash,
                    "rtl_language": self.rtl_config.language,
                    "rtl_sources": rtl_rows,
                    "rtl_libraries": rtl_library_rows,
                    "rtl_sha256": rtl_hash,
                    "design_inputs": design_inputs,
                    "design_contracts": design_contracts,
                    "test_sources": test_source_rows,
                    "test_sources_sha256": test_source_hash,
                    "candidate_snapshot": candidate_snapshot.relative_to(workspace).as_posix(),
                    "candidate_snapshot_sha256": candidate_snapshot_hash,
                    "rtl_backend_manifest_sha256": None,
                    "performance_manifest_sha256": None,
                    "waveforms": [],
                    "ppa_report_id": None,
                    "ppa_report_sha256": None,
                    "ppa_metrics": {},
                    "performance_metrics": {},
                    "comparison_to_previous": None,
                    "comparison_to_base": None,
                "metric_changes_to_previous": None,
                "metric_changes_to_base": None,
                "metric_changes_to_best": None,
                "pareto_assessments": {},
                "no_regression_metrics": list(self.no_regression_categories),
                "score_weights": dict(self.score_weights),
                "regressed_metrics": [],
                "rejection_reason": "functional_regression_failed",
                    "stop_reason": stop_reason,
                    "no_improvement_count": no_improvement_count,
                    "functional_regression": {
                        "pass": False,
                        "pytest": _pytest_evidence(
                            functional_result,
                            ret_std_out=self.ret_std_out,
                            ret_std_error=self.ret_std_error,
                            sensitive_paths=(workspace,),
                        ),
                    },
                    "restored_rtl_sha256": restored_hash,
                    "candidate_history_commit": candidate_history_commit,
                    "internal_history_commit": None,
                }
                iteration_report_path = resolve_workspace_path(
                    workspace,
                    Path(self.iteration_report_dir)
                    / f"iteration-{candidate_index:03d}.json",
                )
                atomic_json(
                    iteration_report_path,
                    {
                        "schema_version": "1.0",
                        "artifact_type": "ppa_iteration",
                        "iteration": candidate_index,
                        "version": candidate_index,
                        "kind": "candidate",
                        "accepted": False,
                        "status": "rejected",
                        "rejection_reason": "functional_regression_failed",
                        "report_id": None,
                        "rtl_sha256": rtl_hash,
                        "candidate_snapshot": candidate_snapshot.relative_to(
                            workspace
                        ).as_posix(),
                        "functional_regression": record[
                            "functional_regression"
                        ],
                    },
                )
                state["candidate_count"] = candidate_index
                state["no_improvement_count"] = no_improvement_count
                state["best_iteration"] = state.get("best_iteration", state.get("accepted_iteration", 0))
                state["best_report_id"] = state.get("best_report_id", state.get("accepted_report_id"))
                state["best_rtl_sha256"] = state.get("best_rtl_sha256", state.get("accepted_rtl_sha256"))
                state["best_snapshot"] = state.get("best_snapshot", state.get("accepted_snapshot"))
                state.setdefault("processed_hypothesis_sha256", []).append(
                    hypothesis_hash
                )
                state["status"] = "complete" if stop_reason else "awaiting_candidate"
                state["stop_reason"] = stop_reason
                ledger["stop_reason"] = stop_reason
                ledger["no_improvement_count"] = no_improvement_count
                ledger["records"].append(record)
                history_commit = self._persist(
                    workspace,
                    state,
                    ledger,
                    f"DesignWithPPA candidate iteration {candidate_index:03d} (functional rejection)",
                )
            except (OSError, ValueError, FileNotFoundError, KeyError) as exc:
                return False, diagnostic(
                    "ppa_functional_rejection_failed",
                    "The failing candidate could not be recorded and restored deterministically.",
                    (
                        "Do not edit optimization records or generated evidence. Call Check "
                        "again so the workflow can finish rejecting and restoring this candidate. "
                        "If the same diagnostic repeats, restart ppa_candidate_optimization "
                        "before authoring another candidate."
                    ),
                    artifact=self.rtl_config.source_glob,
                    location="ppa_candidate_optimization",
                    observed={"reason": _public_evidence_error(str(exc))},
                    expected="The failed candidate is recorded once and the last accepted RTL is restored byte-for-byte.",
                )
            if stop_reason:
                return True, {
                    "message": "The functionally failing candidate was rejected and the accepted RTL was restored.",
                    "stop_reason": stop_reason,
                    "accepted_iteration": state["accepted_iteration"],
                    "no_improvement_count": state.get("no_improvement_count", 0),
                }
            failure = _pytest_evidence(
                functional_result,
                ret_std_out=self.ret_std_out,
                ret_std_error=self.ret_std_error,
                sensitive_paths=(workspace,),
            )
            return False, diagnostic(
                "ppa_candidate_functional_rejected",
                "The candidate failed functional regression and was restored to the last accepted RTL.",
                (
                    "Read the first failed node and assertion in observed before choosing the "
                    "next optimization. The rejected candidate is preserved as evidence and the "
                    "authored RTL is already restored. Write a new hypothesis for the next "
                    "iteration, change only the restored selected-language source, and call Check."
                ),
                artifact=self.rtl_config.source_glob,
                location=(failure.get("failed_nodes") or [self.functional_test_glob])[0],
                observed={
                    "candidate_iteration": candidate_index,
                    "accepted_iteration": state["accepted_iteration"],
                    "restored": True,
                    "pytest": failure,
                },
                expected="The next candidate starts from the restored accepted RTL and passes every shared functional TC.",
            )

        state = None
        ledger = None
        if state_path.exists():
            try:
                state = load_json(state_path)
                ledger = _load_bound_ledger(workspace, state, self.ledger_file)
            except (ValueError, FileNotFoundError) as exc:
                return False, diagnostic(
                    "ppa_iteration_state_invalid",
                    "Generated optimization evidence is inconsistent or incomplete.",
                    (
                        "Do not edit generated reports or optimization records. Call Check once "
                        "to retry deterministic recovery. If the same error repeats, restart "
                        "ppa_candidate_optimization so its evidence is regenerated."
                    ),
                    artifact=self.ledger_file,
                    location="ppa_candidate_optimization",
                    observed={"reason": _public_evidence_error(str(exc))},
                    expected="One complete, internally consistent base and contiguous evaluated candidate sequence.",
                )
            if state.get("schema_version") != "1.5" or ledger.get("schema_version") != "1.5":
                return False, diagnostic(
                    "ppa_iteration_state_schema_invalid",
                    "Generated optimization evidence has an invalid schema.",
                    "Do not edit generated evidence. Restart ppa_candidate_optimization to regenerate the current schema before changing RTL.",
                    artifact=self.ledger_file,
                    location="ppa_candidate_optimization",
                    observed={"evidence_schema": "unsupported or inconsistent"},
                    expected={"schema_version": "1.5"},
                )
            if state.get("min_optimization_iterations") != min_iterations or state.get(
                "max_optimization_iterations"
            ) != max_iterations:
                return False, diagnostic(
                    "ppa_iteration_limit_changed",
                    "The minimum or maximum optimization bound changed after base initialization.",
                    (
                        "Restore the configured minimum/maximum used to create round 0, or "
                        "restart ppa_base_characterization when the new bounds are intentional."
                    ),
                    artifact="design_with_ppa",
                    location="design_with_ppa.min_optimization_iterations / design_with_ppa.max_optimization_iterations",
                    observed={
                        "min": state.get("min_optimization_iterations"),
                        "max": state.get("max_optimization_iterations"),
                    },
                    expected={"min": min_iterations, "max": max_iterations},
                )
            if state.get("no_improvement_patience") != self.no_improvement_patience:
                return False, diagnostic(
                    "ppa_patience_changed",
                    "The no-improvement patience changed after base initialization.",
                    "Restore the round-0 patience value, or restart ppa_base_characterization when the new value is intentional.",
                    artifact="design_with_ppa.no_improvement_patience",
                    location="design_with_ppa.no_improvement_patience",
                    observed=state.get("no_improvement_patience"),
                    expected=self.no_improvement_patience,
                )
            if state.get("no_regression_metrics") != list(
                self.no_regression_categories
            ):
                return False, diagnostic(
                    "ppa_no_regression_scope_changed",
                    "The protected no-regression metric categories changed after base initialization.",
                    (
                        "Restore the round-0 design_with_ppa.no_regression_metrics "
                        "value, or restart ppa_base_characterization when the new "
                        "acceptance scope is intentional."
                    ),
                    artifact="design_with_ppa.no_regression_metrics",
                    location="design_with_ppa.no_regression_metrics",
                    observed={
                        "no_regression_metrics": state.get("no_regression_metrics")
                    },
                    expected={
                        "no_regression_metrics": list(self.no_regression_categories)
                    },
                )
            if state.get("score_weights") != dict(self.score_weights):
                return False, diagnostic(
                    "ppa_score_weights_changed",
                    "The PPA selection-score weights changed after base initialization.",
                    (
                        "Restore the round-0 design_with_ppa.score_weights value, "
                        "or restart ppa_base_characterization when the new "
                        "weighting is intentional."
                    ),
                    artifact="design_with_ppa.score_weights",
                    location="design_with_ppa.score_weights",
                    observed={"score_weights": state.get("score_weights")},
                    expected={"score_weights": dict(self.score_weights)},
                )
            ppa_config = _resolved_workflow_ppa_config(
                self.cfg, ledger.get("top_module")
            )
            if state.get("ppa_config") != ppa_config:
                return False, diagnostic(
                    "ppa_configuration_changed",
                    "The resolved PPA configuration changed after the base was recorded.",
                    (
                        "Restore the round-0 top, Liberty, SDC/clock constraint, and waveform "
                        "scope configuration. If the analysis contract intentionally changed, "
                        "restart ppa_base_characterization and regenerate every candidate."
                    ),
                    artifact="design_with_ppa.ppa",
                    location="design_with_ppa.ppa",
                    observed=ppa_config,
                    expected=state.get("ppa_config"),
                )
            if state.get("status") == "complete":
                if rtl_hash != state.get("accepted_rtl_sha256"):
                    return False, diagnostic(
                        "ppa_completed_rtl_changed",
                        "The selected-language source changed after optimization completed.",
                        (
                            "Call the best-version finalization Check to restore the verified "
                            "best source. If this change is intentional, restart RTL validation "
                            "and PPA base characterization so it is evaluated as a new design."
                        ),
                        artifact=self.rtl_config.source_glob,
                        location=self.rtl_config.source_glob,
                        observed={"source_identity": rtl_hash, "optimization_status": "complete"},
                        expected={"source_identity": state.get("accepted_rtl_sha256")},
                    )
                return True, {
                    "message": "PPA optimization is complete.",
                    "stop_reason": state.get("stop_reason"),
                    "accepted_iteration": state.get("accepted_iteration"),
                }
            if rtl_hash == state.get("accepted_rtl_sha256"):
                return False, diagnostic(
                    "ppa_candidate_required",
                    "No selected-language RTL change is available for the next candidate.",
                    (
                        "Review the current and best metrics from CurrentTips, write the next "
                        "iteration-bound candidate_hypothesis.yaml, then make one bounded change "
                        "to the selected-language RTL and call Check. Test-runtime synchronization, "
                        "regression, waveform generation, and PPA analysis are automatic."
                    ),
                    artifact=self.rtl_config.source_glob,
                    location=self.rtl_config.source_glob,
                    observed={
                        "rtl_language": self.rtl_config.language,
                        "accepted_iteration": state.get("accepted_iteration"),
                    },
                    expected={
                        "next_candidate": int(state.get("candidate_count", 0)) + 1,
                        "required_changes": ["new hypothesis", "changed selected-language RTL"],
                    },
                )

        try:
            contract, contract_metrics = _validate_performance_contract(
                workspace,
                resolve_workspace_path(
                    workspace, self.performance_contract_file, must_exist=True
                ),
            )
            performance_manifest_path = resolve_workspace_path(
                workspace, self.performance_manifest_file, must_exist=True
            )
            performance_manifest = load_json(performance_manifest_path)
            if self.input_manifest_file is not None and performance_manifest.get(
                "design_inputs"
            ) != design_inputs:
                raise ValueError("performance manifest design input identity is stale")
            if self.design_contract_files and performance_manifest.get(
                "contracts"
            ) != performance_contracts:
                raise ValueError("performance manifest generated contract identity is stale")
            measured_metrics = _aggregate_contract_metrics(
                performance_manifest, contract_metrics
            )
            expected_baseline = (
                state.get("accepted_report_id") if state is not None else None
            )
            manifest_waveforms = [
                {
                    "path": row["waveform"]["path"],
                    "sha256": row["waveform"]["sha256"],
                }
                for row in performance_manifest["tests"]
            ]
            ppa_report = None
            ppa_config = _resolved_workflow_ppa_config(
                self.cfg, contract["top_module"]
            )
            expected_clock_constraint = (
                {
                    "clock_port": ppa_config["clock_port"],
                    "clock_period_ns": ppa_config["clock_period_ns"],
                }
                if ppa_config["clock_port"] is not None
                else None
            )
            expected_liberty_file = (
                ppa_config["liberty_file"]
                or "bundled:NangateOpenCellLibrary_typical.lib"
            )
            ppa_report_path = resolve_workspace_path(
                workspace, self.ppa_report_file
            )
            if ppa_report_path.is_file() and not ppa_report_path.is_symlink():
                try:
                    candidate_report = load_json(ppa_report_path)
                    cached_candidate = _load_cached_ppa(
                        workspace, candidate_report.get("report_id")
                    )
                    candidate_rtl = [
                        {"path": row.get("path"), "sha256": row.get("sha256")}
                        for row in cached_candidate.get("provenance", {}).get(
                            "rtl_files", []
                        )
                        if isinstance(row, dict)
                    ]
                    candidate_waves = [
                        {"path": row.get("path"), "sha256": row.get("sha256")}
                        for row in cached_candidate.get("provenance", {}).get(
                            "waveform_files", []
                        )
                        if isinstance(row, dict)
                    ]
                    candidate_libraries = cached_candidate.get(
                        "provenance", {}
                    ).get("rtl_libraries")
                    comparison = cached_candidate.get("comparison", {})
                    provenance = cached_candidate.get("provenance", {})
                    expected_status = (
                        "not_requested" if expected_baseline is None else "success"
                    )
                    if (
                        candidate_report == cached_candidate
                        and cached_candidate.get("status") == "success"
                        and candidate_rtl == rtl_rows
                        and candidate_libraries == rtl_library_rows
                        and candidate_waves == manifest_waveforms
                        and provenance.get("top_module") == contract["top_module"]
                        and provenance.get("waveform_scope")
                        == ppa_config["waveform_scope"]
                        and provenance.get("liberty_file") == expected_liberty_file
                        and provenance.get("sdc_file") == ppa_config["sdc_file"]
                        and provenance.get("clock_constraint")
                        == expected_clock_constraint
                        and comparison.get("status") == expected_status
                        and comparison.get("baseline_report_id") == expected_baseline
                    ):
                        ppa_report = cached_candidate
                except (OSError, ValueError, FileNotFoundError):
                    pass
            if ppa_report is None:
                ppa_report = _run_workflow_ppa(
                    workspace=workspace,
                    cfg=self.cfg,
                    architecture=contract,
                    rtl_config=self.rtl_config,
                    rtl_language_backend=self.rtl_language_backend,
                    rtl_files=rtl_files,
                    rtl_rows=rtl_rows,
                    rtl_library_files=rtl_library_files,
                    rtl_library_rows=rtl_library_rows,
                    prepared_content=prepared_content,
                    performance_manifest=performance_manifest,
                    report_file=self.ppa_report_file,
                    baseline_report_id=expected_baseline,
                    timeout=self.timeout,
                )
            if ppa_report.get("status") != "success":
                report_diagnostics = ppa_report.get("diagnostics")
                if not isinstance(report_diagnostics, list):
                    report_diagnostics = []
                return False, diagnostic(
                    "ppa_analysis_incomplete",
                    "Automatic PPA analysis did not produce a complete report.",
                    (
                        "Read the bounded analysis diagnostics in observed. Repair the named "
                        "selected-language RTL/top/library/timing configuration when synthesis "
                        "or timing failed, or return to performance_evidence when waveform "
                        "activity is missing/unreliable. Then call Check again. Do not edit the "
                        "generated PPA report."
                    ),
                    artifact=self.ppa_report_file,
                    location=self.ppa_report_file,
                    observed={
                        "status": ppa_report.get("status"),
                        "analysis_diagnostics": _bounded_checker_value(report_diagnostics[:3]),
                    },
                    expected={
                        "status": "success",
                        "required_metrics": ["area", "power", "frequency or critical delay"],
                        "waveform_activity": "reliable",
                    },
                )
            ppa_report_path = resolve_workspace_path(
                workspace, self.ppa_report_file, must_exist=True
            )
            report_id = ppa_report.get("report_id")
            cached_report = _load_cached_ppa(workspace, report_id)
            if cached_report != ppa_report:
                raise ValueError("current PPA report differs from its immutable cache entry")
            if cached_report.get("provenance", {}).get("top_module") != contract.get(
                "top_module"
            ):
                raise ValueError("PPA report top_module differs from the performance contract")
            ppa_metrics = _ppa_primary_metrics(cached_report)
            provenance_rtl = cached_report.get("provenance", {}).get("rtl_files")
            if not isinstance(provenance_rtl, list):
                raise ValueError("PPA report lacks RTL provenance")
            provenance_rows = [
                {"path": row.get("path"), "sha256": row.get("sha256")}
                for row in provenance_rtl
                if isinstance(row, dict)
            ]
            if provenance_rows != rtl_rows:
                raise ValueError("PPA report RTL provenance is stale for this build")
            if cached_report.get("provenance", {}).get(
                "rtl_libraries"
            ) != rtl_library_rows:
                raise ValueError("PPA report RTL library provenance is stale for this build")
            provenance_waveforms = [
                {"path": row.get("path"), "sha256": row.get("sha256")}
                for row in cached_report.get("provenance", {}).get(
                    "waveform_files", []
                )
                if isinstance(row, dict)
            ]
            if provenance_waveforms != manifest_waveforms:
                raise ValueError(
                    "PPA report waveform provenance differs from the ordered performance manifest"
                )
        except (OSError, ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
            reason = _public_evidence_error(str(exc))
            return False, diagnostic(
                "ppa_iteration_artifact_invalid",
                "The candidate inputs or generated PPA evidence are missing, stale, or inconsistent.",
                (
                    "Use observed.reason to identify whether the named mismatch is in the "
                    "performance contract/manifest, authored RTL/top/libraries, or analysis "
                    "configuration. Repair the corresponding authored input or rerun its "
                    "preceding Check, then call this Check again. Do not hand-edit generated "
                    "waveforms, manifests, reports, hashes, or optimization records."
                ),
                artifact=self.ppa_report_file,
                location=self.ppa_report_file,
                observed={"reason": reason},
                expected={
                    "rtl": "current authored source, top, and configured libraries",
                    "performance": "current ordered TC manifest with reliable waveforms",
                    "ppa": "successful area, power, and timing/frequency analysis",
                },
            )

        if state is None:
            comparison_status = cached_report.get("comparison", {}).get("status")
            if comparison_status != "not_requested":
                return False, diagnostic(
                    "ppa_base_comparison_invalid",
                    "The base PPA report must be created without a baseline report.",
                    "Do not edit the report. Call Check in ppa_base_characterization to regenerate round 0 without a comparison target.",
                    artifact=self.base_report_file,
                    location=self.base_report_file,
                    observed=comparison_status,
                    expected="not_requested",
                )
            if not functional_pass:
                failure = _pytest_evidence(
                    functional_result,
                    ret_std_out=self.ret_std_out,
                    ret_std_error=self.ret_std_error,
                    sensitive_paths=(workspace,),
                )
                return False, diagnostic(
                    "ppa_base_functional_regression_failed",
                    "The proposed base RTL does not pass the full functional regression.",
                    (
                        "Start with the first failed node in observed. Repair a collection/API/env "
                        "failure in the shared test infrastructure, or preserve a valid shared "
                        "assertion and repair the selected-language RTL when only RTL behavior "
                        "differs. Then call Check to rerun functional, performance, and PPA gates."
                    ),
                    artifact=self.rtl_config.source_glob,
                    location=(failure.get("failed_nodes") or [self.functional_test_glob])[0],
                    observed=failure,
                    expected="Every shared non-performance TC passes before round-0 PPA evidence is accepted.",
                )
            snapshot_path = state_root / "accepted" / "iteration-000"
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_hash = _copy_rtl_snapshot(
                workspace,
                self.rtl_config.language,
                rtl_files,
                snapshot_path,
            )
            base_report_path = resolve_workspace_path(workspace, self.base_report_file)
            base_report_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ppa_report_path, base_report_path)
            record = {
                "iteration": 0,
                "version": 0,
                "kind": "base",
                "accepted": True,
                "parent_accepted_iteration": None,
                "optimization_hypothesis": "functional base",
                "rtl_language": self.rtl_config.language,
                "rtl_sources": rtl_rows,
                "rtl_libraries": rtl_library_rows,
                "rtl_sha256": rtl_hash,
                "design_inputs": design_inputs,
                "design_contracts": design_contracts,
                "test_sources": test_source_rows,
                "test_sources_sha256": test_source_hash,
                "snapshot": snapshot_path.relative_to(workspace).as_posix(),
                "snapshot_sha256": snapshot_hash,
                "rtl_backend_manifest_sha256": sha256_file(rtl_backend_manifest_path),
                "performance_manifest_sha256": sha256_file(performance_manifest_path),
                "waveforms": [row["waveform"] for row in performance_manifest["tests"]],
                "ppa_report_id": report_id,
                "ppa_report_sha256": sha256_file(
                    workspace / ".ucagent" / "ppa_reports" / f"{report_id}.json"
                ),
                "ppa_metrics": ppa_metrics,
                "ppa_score": _ppa_selection_score(
                    ppa_metrics, ppa_metrics, weights=self.score_weights
                ),
                "performance_metrics": measured_metrics,
                "comparison_to_previous": None,
                "comparison_to_base": None,
                "metric_changes_to_previous": None,
                "metric_changes_to_base": None,
                "pareto_assessments": {},
                "no_regression_metrics": list(self.no_regression_categories),
                "score_weights": dict(self.score_weights),
                "regressed_metrics": [],
                "functional_regression": {
                    "pass": True,
                    "pytest": _pytest_evidence(
                        functional_result,
                        ret_std_out=self.ret_std_out,
                        ret_std_error=self.ret_std_error,
                        sensitive_paths=(workspace,),
                    ),
                },
                "internal_history_commit": None,
            }
            stop_reason = "base_only" if min_iterations == 0 else None
            state = {
                "schema_version": "1.5",
                "status": "complete" if stop_reason else "awaiting_candidate",
                "rtl_config": self.rtl_config.identity(),
                "ppa_config": ppa_config,
                "min_optimization_iterations": min_iterations,
                "max_optimization_iterations": max_iterations,
                "no_improvement_patience": self.no_improvement_patience,
                "no_regression_metrics": list(self.no_regression_categories),
                "score_weights": dict(self.score_weights),
                "no_improvement_count": 0,
                "best_iteration": 0,
                "best_report_id": report_id,
                "best_rtl_sha256": rtl_hash,
                "best_snapshot": snapshot_path.relative_to(workspace).as_posix(),
                "candidate_count": 0,
                "accepted_iteration": 0,
                "accepted_report_id": report_id,
                "accepted_report_sha256": record["ppa_report_sha256"],
                "accepted_rtl_sha256": rtl_hash,
                "accepted_snapshot": snapshot_path.relative_to(workspace).as_posix(),
                "base_report_id": report_id,
                "base_report_sha256": record["ppa_report_sha256"],
                "base_rtl_libraries": rtl_library_rows,
                "base_design_inputs": design_inputs,
                "base_design_contracts": design_contracts,
                "base_test_sources": test_source_rows,
                "base_test_sources_sha256": test_source_hash,
                "base_performance_identity": [
                    {
                        "test_case": row["test_case"],
                        "deterministic": row["deterministic"],
                        "seed": row["seed"],
                        "parameters": row["parameters"],
                        "stimulus_sha256": row["stimulus_sha256"],
                        "input_trace_sha256": row["input_trace_sha256"],
                    }
                    for row in performance_manifest["tests"]
                ],
                "processed_report_ids": [report_id],
                "processed_hypothesis_sha256": [],
                "stop_reason": stop_reason,
            }
            ledger = {
                "schema_version": "1.5",
                "dut": contract["dut"],
                "top_module": contract["top_module"],
                "rtl_language": self.rtl_config.language,
                "rtl_libraries": rtl_library_rows,
                "min_optimization_iterations": min_iterations,
                "max_optimization_iterations": max_iterations,
                "no_improvement_patience": self.no_improvement_patience,
                "no_regression_metrics": list(self.no_regression_categories),
                "score_weights": dict(self.score_weights),
                "no_improvement_count": 0,
                "best_iteration": 0,
                "best_report_id": report_id,
                "best_selection_reason": "base is the only complete accepted version",
                "tolerance": {
                    "relative": self.rel_tolerance,
                    "absolute": self.abs_tolerance,
                },
                "stop_reason": stop_reason,
                "records": [record],
            }
            iteration_report_path = resolve_workspace_path(
                workspace,
                Path(self.iteration_report_dir) / "iteration-000.json",
            )
            iteration_report_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ppa_report_path, iteration_report_path)
            history_commit = self._persist(
                workspace, state, ledger, "DesignWithPPA base PPA snapshot"
            )
            if stop_reason or self.phase == "base":
                return True, {
                    "message": (
                        "Functional base and base PPA are complete; optimization is disabled."
                        if stop_reason
                        else "Functional RTL and round-0 PPA base are recorded."
                    ),
                    "stop_reason": stop_reason,
                    "accepted_iteration": 0,
                    "analysis": _public_ppa_summary(cached_report),
                    "performance_metrics": measured_metrics,
                }
            return False, diagnostic(
                "ppa_candidate_required",
                "The functional base is recorded and optimization rounds remain.",
                (
                    "Use observed.analysis and observed.performance_metrics to select one "
                    "specific hotspot. Write candidate_hypothesis.yaml for iteration 1, change "
                    "only the selected-language RTL, then call Check for complete evaluation."
                ),
                artifact=self.rtl_config.source_glob,
                location=self.rtl_config.source_glob,
                observed={
                    "accepted_iteration": 0,
                    "analysis": _public_ppa_summary(cached_report),
                    "performance_metrics": measured_metrics,
                },
                expected={
                    "minimum_candidates": min_iterations,
                    "maximum_candidates": max_iterations,
                },
            )

        if report_id in state.get("processed_report_ids", []):
            return False, diagnostic(
                "ppa_new_candidate_required",
                "The current selected-language source has already been evaluated and no new candidate is available.",
                (
                    "Use the reported current/best metrics to choose a different bounded "
                    "optimization. Write candidate_hypothesis.yaml with the exact next iteration, "
                    "modify the selected-language RTL so its source hash changes, then call Check."
                ),
                artifact=self.rtl_config.source_glob,
                location=self.rtl_config.source_glob,
                observed={
                    "candidate_count": state.get("candidate_count"),
                    "accepted_iteration": state.get("accepted_iteration"),
                    "analysis": _public_ppa_summary(cached_report),
                },
                expected={
                    "next_candidate": int(state.get("candidate_count", 0)) + 1,
                    "source": "not previously evaluated",
                    "hypothesis": "new and iteration-bound",
                },
            )

        candidate_index = int(state.get("candidate_count", 0)) + 1
        if candidate_index > max_iterations:
            return False, diagnostic(
                "ppa_iteration_limit_exceeded",
                "A candidate was supplied after the configured maximum optimization limit.",
                "Call Check without further source edits so the verified accepted RTL can be restored and finalized; do not create another candidate.",
                artifact=self.rtl_config.source_glob,
                location=self.rtl_config.source_glob,
                observed={"candidate_iteration": candidate_index},
                expected={"maximum_candidate_iteration": max_iterations},
            )
        report_comparison = cached_report.get("comparison")
        if (
            not isinstance(report_comparison, dict)
            or report_comparison.get("status") != "success"
            or report_comparison.get("baseline_report_id")
            != state.get("accepted_report_id")
            or report_comparison.get("current_report_id") != report_id
        ):
            return False, diagnostic(
                "ppa_candidate_baseline_invalid",
                "The candidate analysis is not comparable with the previous accepted version.",
                "Do not edit the generated report. Call Check again so the current candidate is analyzed against the latest accepted version; if it repeats, restart ppa_candidate_optimization before changing RTL.",
                artifact=self.ppa_report_file,
                location=self.ppa_report_file,
                observed={
                    "comparison_status": (
                        report_comparison.get("status")
                        if isinstance(report_comparison, dict)
                        else "missing"
                    )
                },
                expected={"comparison_status": "success", "baseline": "latest accepted version"},
            )
        hypothesis_path = resolve_workspace_path(
            workspace,
            Path(resolved_output(self.cfg)) / "reports" / "ppa" / "candidate_hypothesis.yaml",
            must_exist=True,
        )
        try:
            hypothesis, hypothesis_hash = _load_candidate_hypothesis(
                hypothesis_path,
                candidate_index,
                state.get("processed_hypothesis_sha256", []),
            )
            hypothesis_text = hypothesis["hypothesis"]
            target_hotspot = hypothesis["target_hotspot"]
            expected_metrics = hypothesis["expected_metrics"]
        except (ValueError, FileNotFoundError) as exc:
            return False, diagnostic(
                "ppa_candidate_hypothesis_invalid",
                "The candidate hypothesis is missing, malformed, stale, or bound to the wrong iteration.",
                (
                    "Open the reported YAML and use observed.reason to correct the first field. "
                    "It must contain exactly iteration, hypothesis, target_hotspot, and a "
                    "non-empty unique expected_metrics list for the current candidate. Then "
                    "call Check without reusing a prior hypothesis."
                ),
                artifact=hypothesis_path.relative_to(workspace).as_posix(),
                location=hypothesis_path.relative_to(workspace).as_posix(),
                observed={"reason": _redact_backend_output(str(exc), 2000, (workspace,))},
                expected={
                    "iteration": candidate_index,
                    "fields": ["iteration", "hypothesis", "target_hotspot", "expected_metrics"],
                },
            )

        identity = [
            {
                "test_case": row["test_case"],
                "deterministic": row["deterministic"],
                "seed": row["seed"],
                "parameters": row["parameters"],
                "stimulus_sha256": row["stimulus_sha256"],
                "input_trace_sha256": row["input_trace_sha256"],
            }
            for row in performance_manifest["tests"]
        ]
        if identity != state.get("base_performance_identity"):
            return False, diagnostic(
                "ppa_performance_identity_changed",
                "The ordered performance TC, seed, parameter, stimulus, or input-trace identity differs from base.",
                (
                    "Compare observed and expected to find the first changed TC identity. "
                    "Restore its base node ID, parameters, deterministic seed, stimulus, and "
                    "top-level input trace in the authored performance test, then call Check to "
                    "regenerate the complete candidate evidence set. Do not edit the manifest."
                ),
                observed=identity[:20],
                expected=state.get("base_performance_identity", [])[:20],
                artifact=self.performance_manifest_file,
                location=self.performance_manifest_file,
            )

        try:
            previous_report = _load_cached_ppa(
                workspace, state["accepted_report_id"]
            )
            base_report = _load_cached_ppa(workspace, state["base_report_id"])
            previous_report_hash = sha256_file(
                workspace
                / ".ucagent"
                / "ppa_reports"
                / f"{state['accepted_report_id']}.json"
            )
            base_report_hash = sha256_file(
                workspace
                / ".ucagent"
                / "ppa_reports"
                / f"{state['base_report_id']}.json"
            )
        except (OSError, ValueError, FileNotFoundError, KeyError) as exc:
            return False, diagnostic(
                "ppa_accepted_report_unavailable",
                "The accepted/base analysis evidence is unavailable or inconsistent.",
                (
                    "Do not edit generated PPA evidence. Call Check once to retry loading the "
                    "verified base and accepted reports. If the same diagnostic repeats, restart "
                    "ppa_candidate_optimization before authoring another candidate."
                ),
                artifact=self.ppa_report_file,
                location="ppa_candidate_optimization",
                observed={"reason": _public_evidence_error(str(exc))},
                expected="Readable, integrity-checked round-0 and previous-accepted PPA reports.",
            )
        if previous_report_hash != state.get("accepted_report_sha256"):
            return False, diagnostic(
                "ppa_accepted_report_integrity_failed",
                "The previous accepted analysis evidence failed its integrity check.",
                "Do not edit the report or optimization records. Restart ppa_candidate_optimization before evaluating another candidate.",
                artifact=self.ppa_report_file,
                location="ppa_candidate_optimization",
                observed={"accepted_report_integrity": "failed"},
                expected={"accepted_report_integrity": "verified"},
            )
        if base_report_hash != state.get("base_report_sha256"):
            return False, diagnostic(
                "ppa_base_report_integrity_failed",
                "The base analysis evidence failed its integrity check.",
                "Do not edit the report or optimization records. Restart ppa_base_characterization and regenerate all optimization candidates.",
                artifact=self.ppa_report_file,
                location="ppa_base_characterization",
                observed={"base_report_integrity": "failed"},
                expected={"base_report_integrity": "verified"},
            )
        comparison = compare_ppa_reports(previous_report, cached_report)
        base_comparison = compare_ppa_reports(base_report, cached_report)
        compatibility = comparison.get("compatibility", {})
        if not compatibility.get("overall"):
            return False, diagnostic(
                "ppa_candidate_not_comparable",
                "The candidate PPA report is not comparable with the previous accepted report.",
                (
                    "Use observed.mismatches to restore the previous accepted top module, "
                    "Liberty file, SDC/clock constraint, timing metric kind, waveform scope, "
                    "ordered TC identities, stimulus/input traces, and reliable input activity. "
                    "Repair authored configuration/tests only, then call Check to regenerate evidence."
                ),
                observed=_bounded_checker_value(compatibility),
                artifact=self.ppa_report_file,
                location=self.ppa_report_file,
                expected={
                    "overall": True,
                    "same_contract": [
                        "top_module", "liberty", "timing_constraint", "timing_metric_kind",
                        "waveform_scope", "ordered_tc_identity", "stimulus_input_trace",
                    ],
                    "waveform_activity": "reliable and comparable",
                },
            )
        if not base_comparison.get("compatibility", {}).get("overall"):
            return False, diagnostic(
                "ppa_candidate_not_comparable_to_base",
                "The candidate PPA report is not comparable with the base report.",
                (
                    "Use observed.mismatches to restore the round-0 analysis and performance "
                    "contract: top, Liberty, constraints, timing metric kind, waveform scope, "
                    "ordered TC identity, stimulus/input trace, and reliable activity. Then call "
                    "Check to regenerate the candidate evidence."
                ),
                observed=_bounded_checker_value(base_comparison.get("compatibility")),
                artifact=self.ppa_report_file,
                location=self.ppa_report_file,
                expected={"overall": True, "reference": "round-0 base contract"},
            )
        previous_record = next(
            record
            for record in reversed(ledger["records"])
            if record.get("accepted") is True
        )
        previous_metrics = {
            **previous_record["ppa_metrics"],
            **previous_record["performance_metrics"],
        }
        current_metrics = {**ppa_metrics, **measured_metrics}
        if set(previous_metrics) != set(current_metrics):
            return False, diagnostic(
                "ppa_primary_metric_set_changed",
                "The candidate primary metric set differs from the accepted metric contract.",
                "Restore the exact metric IDs in the authored performance contract/tests, then call Check to regenerate sidecars, waveforms, and PPA evidence; do not edit generated reports.",
                artifact=self.performance_contract_file,
                location=self.performance_contract_file,
                observed={"metric_ids": sorted(current_metrics)},
                expected={"metric_ids": sorted(previous_metrics)},
            )
        for metric_id, current in current_metrics.items():
            previous = previous_metrics[metric_id]
            if current.get("unit") != previous.get("unit") or current.get(
                "direction"
            ) != previous.get("direction"):
                return False, diagnostic(
                    "ppa_primary_metric_contract_changed",
                    f"The unit or direction changed for primary metric {metric_id}.",
                    f"Restore metric {metric_id!r} to the round-0 unit and direction in the performance contract/test calculation, then call Check to regenerate all candidate evidence.",
                    artifact=self.performance_contract_file,
                    location=f"{self.performance_contract_file} metric {metric_id}",
                    observed={"metric_id": metric_id, "unit": current.get("unit"), "direction": current.get("direction")},
                    expected={"metric_id": metric_id, "unit": previous.get("unit"), "direction": previous.get("direction")},
                )
        metric_changes_to_previous = _primary_metric_changes(
            previous_metrics,
            current_metrics,
            rel_tol=self.rel_tolerance,
            abs_tol=self.abs_tolerance,
        )
        base_record = ledger["records"][0]
        base_metrics = {
            **base_record["ppa_metrics"],
            **base_record["performance_metrics"],
        }
        metric_changes_to_base = _primary_metric_changes(
            base_metrics,
            current_metrics,
            rel_tol=self.rel_tolerance,
            abs_tol=self.abs_tolerance,
        )
        best_record = next(
            (
                row
                for row in reversed(ledger["records"])
                if row.get("accepted") is True
                and row.get("ppa_report_id") == state.get("best_report_id")
            ),
            None,
        )
        if best_record is None:
            best_record = previous_record
        best_metrics = {
            **best_record["ppa_metrics"],
            **best_record["performance_metrics"],
        }
        metric_changes_to_best = _primary_metric_changes(
            best_metrics,
            current_metrics,
            rel_tol=self.rel_tolerance,
            abs_tol=self.abs_tolerance,
        )
        assessments = {
            metric_id: change["assessment"]
            for metric_id, change in metric_changes_to_previous.items()
        }

        rejection_reason = None
        stop_reason = None
        hard_failures = []
        for metric_id, metric in measured_metrics.items():
            if not metric["hard_requirement"]:
                continue
            target = finite_number(metric["target"], f"{metric_id}.target")
            value = finite_number(metric["value"], f"{metric_id}.value")
            tolerance = max(
                self.abs_tolerance,
                self.rel_tolerance * max(abs(target), abs(value)),
            )
            if (metric["direction"] == "min" and value - target > tolerance) or (
                metric["direction"] == "max" and target - value > tolerance
            ):
                hard_failures.append(metric_id)
        if hard_failures:
            rejection_reason = "hard_performance_target_failed"
        else:
            regressed_metrics = sorted(
                metric_id
                for metric_id, assessment in assessments.items()
                if assessment == "regressed"
            )
            protected_regressions = [
                metric_id
                for metric_id in regressed_metrics
                if _metric_category(metric_id) in self.no_regression_categories
            ]
            if protected_regressions:
                rejection_reason = "pareto_regression"
                stop_reason = None
            elif not any(
                value == "improved" for value in assessments.values()
            ):
                rejection_reason = "no_pareto_improvement"
                stop_reason = None

        no_improvement_count = int(state.get("no_improvement_count", 0))
        if rejection_reason in {"pareto_regression", "no_pareto_improvement"}:
            no_improvement_count = min(
                self.no_improvement_patience, no_improvement_count + 1
            )
        elif rejection_reason is None:
            no_improvement_count = 0
        if (
            rejection_reason in {
                "pareto_regression",
                "no_pareto_improvement",
            }
            and candidate_index >= min_iterations
            and no_improvement_count >= self.no_improvement_patience
        ):
            stop_reason = "no_pareto_improvement"
        if candidate_index >= max_iterations:
            stop_reason = "max_iterations_reached"
        # Hard-target failures remain actionable and should not be mistaken for
        # a PPA plateau; they can only stop through the explicit safety bound.
        if rejection_reason == "hard_performance_target_failed" and candidate_index < max_iterations:
            stop_reason = None

        candidate_snapshot = state_root / "candidates" / f"iteration-{candidate_index:03d}"
        candidate_snapshot.parent.mkdir(parents=True, exist_ok=True)
        candidate_snapshot_hash = _copy_rtl_snapshot(
            workspace,
            self.rtl_config.language,
            rtl_files,
            candidate_snapshot,
        )
        candidate_history_commit = self.stage.hist_snapshot(
            f"DesignWithPPA candidate iteration {candidate_index:03d} evidence"
        )

        accepted = rejection_reason is None
        report_destination = resolve_workspace_path(
            workspace,
            Path(self.iteration_report_dir) / f"iteration-{candidate_index:03d}.json",
        )
        report_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ppa_report_path, report_destination)
        record = {
            "iteration": candidate_index,
            "version": candidate_index,
            "kind": "candidate",
            "accepted": accepted,
            "parent_accepted_iteration": state["accepted_iteration"],
            "optimization_hypothesis": hypothesis_text,
            "target_hotspot": target_hotspot,
            "expected_metrics": expected_metrics,
            "hypothesis_sha256": hypothesis_hash,
            "rtl_language": self.rtl_config.language,
            "rtl_sources": rtl_rows,
            "rtl_libraries": rtl_library_rows,
            "rtl_sha256": rtl_hash,
            "design_inputs": design_inputs,
            "design_contracts": design_contracts,
            "test_sources": test_source_rows,
            "test_sources_sha256": test_source_hash,
            "candidate_snapshot": candidate_snapshot.relative_to(workspace).as_posix(),
            "candidate_snapshot_sha256": candidate_snapshot_hash,
            "rtl_backend_manifest_sha256": sha256_file(rtl_backend_manifest_path),
            "performance_manifest_sha256": sha256_file(performance_manifest_path),
            "waveforms": [row["waveform"] for row in performance_manifest["tests"]],
            "ppa_report_id": report_id,
            "ppa_report_sha256": sha256_file(
                workspace / ".ucagent" / "ppa_reports" / f"{report_id}.json"
            ),
            "ppa_metrics": ppa_metrics,
            "ppa_score": _ppa_selection_score(
                base_record["ppa_metrics"], ppa_metrics, weights=self.score_weights
            ),
            "performance_metrics": measured_metrics,
            "comparison_to_previous": comparison,
            "comparison_to_base": base_comparison,
            "metric_changes_to_previous": metric_changes_to_previous,
            "metric_changes_to_base": metric_changes_to_base,
            "metric_changes_to_best": metric_changes_to_best,
            "pareto_assessments": assessments,
            "no_regression_metrics": list(self.no_regression_categories),
            "score_weights": dict(self.score_weights),
            "regressed_metrics": regressed_metrics,
            "rejection_reason": rejection_reason,
            "stop_reason": stop_reason,
            "no_improvement_count": no_improvement_count,
            "functional_regression": {
                "pass": functional_pass,
                "pytest": _pytest_evidence(
                    functional_result,
                    ret_std_out=self.ret_std_out,
                    ret_std_error=self.ret_std_error,
                    sensitive_paths=(workspace,),
                ),
            },
            "candidate_history_commit": candidate_history_commit,
            "internal_history_commit": None,
        }
        state["candidate_count"] = candidate_index
        state["no_improvement_count"] = no_improvement_count if not accepted else 0
        state.setdefault("processed_report_ids", []).append(report_id)
        state.setdefault("processed_hypothesis_sha256", []).append(
            hypothesis_hash
        )
        if accepted:
            accepted_snapshot = state_root / "accepted" / f"iteration-{candidate_index:03d}"
            accepted_snapshot.parent.mkdir(parents=True, exist_ok=True)
            accepted_hash = _copy_rtl_snapshot(
                workspace,
                self.rtl_config.language,
                rtl_files,
                accepted_snapshot,
            )
            record["accepted_snapshot"] = accepted_snapshot.relative_to(workspace).as_posix()
            record["accepted_snapshot_sha256"] = accepted_hash
            state["accepted_iteration"] = candidate_index
            state["accepted_report_id"] = report_id
            state["accepted_report_sha256"] = record["ppa_report_sha256"]
            state["accepted_rtl_sha256"] = rtl_hash
            state["accepted_snapshot"] = accepted_snapshot.relative_to(workspace).as_posix()
            state["no_improvement_count"] = 0
            if candidate_index >= max_iterations:
                stop_reason = "max_iterations_reached"
                record["stop_reason"] = stop_reason
                state["status"] = "complete"
                state["stop_reason"] = stop_reason
            elif no_improvement_count >= self.no_improvement_patience:
                # An accepted candidate clears the patience counter, so this
                # branch is defensive and only documents the invariant.
                state["status"] = "awaiting_candidate"
            else:
                state["status"] = "awaiting_candidate"
        else:
            restored_hash = self._restore(workspace, state, rtl_files)
            record["restored_rtl_sha256"] = restored_hash
            if stop_reason:
                state["status"] = "complete"
                state["stop_reason"] = stop_reason
            elif candidate_index >= max_iterations:
                stop_reason = "max_iterations_reached"
                record["stop_reason"] = stop_reason
                state["status"] = "complete"
                state["stop_reason"] = stop_reason
            else:
                state["status"] = "awaiting_candidate"
        best_record = select_best_accepted_record(
            [*ledger["records"], record],
            rel_tol=self.rel_tolerance,
            abs_tol=self.abs_tolerance,
            categories=self.no_regression_categories,
        )
        state["best_iteration"] = best_record["iteration"]
        state["best_report_id"] = best_record["ppa_report_id"]
        state["best_rtl_sha256"] = best_record["rtl_sha256"]
        best_snapshot = best_record.get("accepted_snapshot") or best_record.get(
            "snapshot"
        )
        if not isinstance(best_snapshot, str):
            raise ValueError("selected best record has no immutable RTL snapshot")
        state["best_snapshot"] = best_snapshot
        ledger["best_iteration"] = best_record["iteration"]
        ledger["best_report_id"] = best_record["ppa_report_id"]
        ledger["best_selection_reason"] = (
            "selected from every complete accepted version by Pareto dominance "
            "over the protected no-regression metrics "
            f"({','.join(self.no_regression_categories) or 'none'})"
        )
        ledger["stop_reason"] = state.get("stop_reason")
        ledger["no_improvement_count"] = state.get("no_improvement_count", 0)
        ledger["records"].append(record)
        history_commit = self._persist(
            workspace,
            state,
            ledger,
            f"DesignWithPPA candidate iteration {candidate_index:03d} ({'accepted' if accepted else 'rejected'})",
        )
        if state["status"] == "complete":
            return True, {
                "message": "PPA optimization reached a verified terminal state.",
                "accepted": accepted,
                "rejection_reason": rejection_reason,
                "stop_reason": state["stop_reason"],
                "accepted_iteration": state["accepted_iteration"],
                "best_iteration": state.get("best_iteration"),
                "ppa_score": record["ppa_score"],
                "best_ppa_score": best_record.get("ppa_score")
                or _ppa_selection_score(
                    base_record["ppa_metrics"],
                    best_record["ppa_metrics"],
                    weights=self.score_weights,
                ),
                "no_improvement_count": state.get("no_improvement_count", 0),
                "analysis": _public_ppa_summary(
                    cached_report if accepted else previous_report
                ),
                "metric_changes_to_previous": metric_changes_to_previous,
                "metric_changes_to_base": metric_changes_to_base,
                "metric_changes_to_best": metric_changes_to_best,
            }
        return False, diagnostic(
            "ppa_next_candidate_required",
            "The current candidate was recorded and additional optimization rounds remain.",
            (
                "Review metric_changes_to_previous/base/best and the PPA summaries in observed. "
                "For every regressed metric, avoid repeating that tradeoff; choose one remaining "
                "hotspot, write the exact next iteration in candidate_hypothesis.yaml, modify the "
                "currently restored or accepted selected-language RTL, then call Check."
            ),
            artifact=self.rtl_config.source_glob,
            location=self.rtl_config.source_glob,
            observed={
                "candidate_iteration": candidate_index,
                "accepted": accepted,
                "rejection_reason": rejection_reason,
                "accepted_iteration": state["accepted_iteration"],
                "analysis": _public_ppa_summary(
                    cached_report if accepted else previous_report
                ),
                "ppa_score": record["ppa_score"],
                "best_ppa_score": best_record.get("ppa_score")
                or _ppa_selection_score(
                    base_record["ppa_metrics"],
                    best_record["ppa_metrics"],
                    weights=self.score_weights,
                ),
                "metric_changes_to_previous": metric_changes_to_previous,
                "metric_changes_to_base": metric_changes_to_base,
                "metric_changes_to_best": metric_changes_to_best,
                "minimum_iterations_remaining": max(0, min_iterations - candidate_index),
                "patience_remaining": max(
                    0,
                    self.no_improvement_patience
                    - int(state.get("no_improvement_count", 0)),
                ),
            },
            expected={
                "next_candidate": candidate_index + 1,
                "minimum_candidates": min_iterations,
                "maximum_candidates": max_iterations,
                "no_improvement_patience": self.no_improvement_patience,
                "no_regression_metrics": list(self.no_regression_categories),
            },
        )


class PPABaseCharacterizationChecker(PPAIterationChecker):
    """Create and validate only the immutable round-0 PPA base."""

    def __init__(self, **kwargs: Any) -> None:
        """Bind the shared PPA engine to its base-only phase."""

        super().__init__(phase="base", **kwargs)


class PPACandidateOptimizationChecker(PPAIterationChecker):
    """Evaluate consecutive optimization candidates after a verified base exists."""

    def __init__(self, **kwargs: Any) -> None:
        """Bind the shared PPA engine to its iterative optimization phase."""

        super().__init__(phase="optimization", **kwargs)
