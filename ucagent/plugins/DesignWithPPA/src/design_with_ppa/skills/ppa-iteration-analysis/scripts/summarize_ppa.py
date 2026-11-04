"""Summarize the current PPA report and its highest-value optimization evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ucagent.util.config import load_runtime_config


def _inside_workspace(workspace: Path, value: str) -> Path:
    """Resolve one configured path without allowing workspace traversal."""

    candidate = (workspace / value).resolve()
    if not candidate.is_relative_to(workspace):
        raise ValueError("Resolved OUT escapes the active workspace")
    return candidate


def _load_report(path: Path) -> dict[str, Any]:
    """Load one PPA JSON report and require a mapping root."""

    with path.open("r", encoding="utf-8") as file_obj:
        value = json.load(file_obj)
    if not isinstance(value, dict):
        raise ValueError("PPA report root must be a JSON object")
    return value


def _area_hotspots(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Return at most five largest numeric area-by-cell entries."""

    cells = report.get("details", {}).get("area_by_cell_type", {})
    if not isinstance(cells, dict):
        return []
    numeric = [
        {"cell_type": name, "area": value}
        for name, value in cells.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    return sorted(numeric, key=lambda row: (-float(row["area"]), row["cell_type"]))[:5]


def main() -> None:
    """Print a bounded PPA hotspot/diff summary without writing workflow state."""

    workspace = Path(os.getcwd()).resolve()
    runtime = load_runtime_config(str(workspace))
    output = _inside_workspace(workspace, runtime["OUT"])
    report_path = output / "reports" / "ppa" / "current.json"
    if not report_path.is_file() or report_path.is_symlink():
        print(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "status": "missing_report",
                    "next_action": "Call Check/Complete to analyze the current RTL and complete waveform set automatically.",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    try:
        report = _load_report(report_path)
        details = report.get("details", {})
        details = details if isinstance(details, dict) else {}
        payload = {
            "schema_version": "1.1",
            "status": report.get("status"),
            "summary": report.get("summary", {}),
            "comparison": {
                key: report.get("comparison", {}).get(key)
                for key in ("status", "compatibility", "summary", "metrics")
                if key in report.get("comparison", {})
            },
            "area_hotspots": _area_hotspots(report),
            "power_groups": details.get("power_groups", {}),
            "diagnostics": (
                report.get("diagnostics", [])[:10]
                if isinstance(report.get("diagnostics"), list)
                else []
            ),
            "resolved_optimization_minimum": runtime.get("plugin_options", {}).get(
            "design_with_ppa.min_optimization_iterations"
        ),
            "resolved_optimization_maximum": runtime.get("plugin_options", {}).get(
                "design_with_ppa.max_optimization_iterations"
            ),
            "no_improvement_patience": runtime.get("plugin_options", {}).get(
                "design_with_ppa.no_improvement_patience"
            ),
            "no_regression_metrics": runtime.get("plugin_options", {}).get(
                "design_with_ppa.no_regression_metrics"
            ),
            "score_weights": {
                dimension: runtime.get("plugin_options", {}).get(
                    f"design_with_ppa.score_weights.{dimension}"
                )
                for dimension in ("timing", "area", "power")
            },
            "next_action": (
                "Record one bounded hypothesis for the dominant source-level hotspot before editing RTL."
                if report.get("status") == "success"
                else "Repair the reported analysis failure before proposing an optimization."
            ),
        }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        payload = {
            "schema_version": "1.0",
            "status": "invalid_report",
            "error": str(exc),
            "next_action": "Call Check/Complete to regenerate the current PPA report automatically.",
        }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
