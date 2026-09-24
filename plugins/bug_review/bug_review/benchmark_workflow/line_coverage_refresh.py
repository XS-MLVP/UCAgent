"""Recover and normalize line coverage summaries from LCOV-style artifacts."""

from __future__ import annotations

import json
import os
from pathlib import PurePosixPath
import re
import shutil
import subprocess
import tempfile
from typing import Dict, Optional, Tuple


def normalize_rtl_source_path(path: object) -> str:
    """Normalize build-specific RTL paths to a stable repository-relative key."""
    text = str(path or "").replace("\\", "/")
    parts = [part for part in PurePosixPath(text).parts if part not in {"/", ""}]
    if not parts:
        return ""
    filename = parts[-1]
    stem = os.path.splitext(filename)[0]
    if len(parts) >= 2 and parts[-2] == stem:
        return f"{parts[-2]}/{filename}"
    for index in range(len(parts) - 2, -1, -1):
        lowered = parts[index].lower()
        if lowered == "rtl" or lowered.endswith("_rtl") or "rtl_" in lowered:
            suffix = parts[index + 1 :]
            return "/".join(["rtl", *suffix]) if suffix else f"rtl/{filename}"
    return filename


def parse_merged_dat(filepath: str) -> Dict[str, object]:
    """Best-effort line map fallback; never count raw C records as lines."""
    result = {"total_lines": 0, "hit_lines": 0, "miss_lines": 0, "line_map": {}, "source_line_map": {}}
    if not filepath or not os.path.exists(filepath):
        return result
    with open(filepath, "rb") as handle:
        data = handle.read()
    text = data.decode("utf-8", errors="replace")
    for raw in text.split("\n"):
        line = raw.strip()
        if not line.startswith("C '"):
            continue
        count_match = re.search(r"''\s*(\d+)$", line)
        if not count_match:
            continue
        count = int(count_match.group(1))
        file_match = re.search(r"\x01f\x02([^\x01]+)", line)
        line_match = re.search(r"\x01l\x02(\d+)", line)
        if not file_match or not line_match:
            continue
        file_path = normalize_rtl_source_path(file_match.group(1))
        line_no = int(line_match.group(1))
        key = (file_path, line_no)
        # Verilator emits multiple counters for one source line (instances,
        # scopes and point kinds). Aggregate them into one source-line entry.
        result["line_map"][key] = int(result["line_map"].get(key, 0)) + count
        result["source_line_map"][key] = result["line_map"][key]
    result["total_lines"] = len(result["line_map"])
    result["hit_lines"] = sum(1 for count in result["line_map"].values() if count > 0)
    result["miss_lines"] = result["total_lines"] - result["hit_lines"]
    return result


def parse_merged_info(filepath: str) -> Dict[str, object]:
    """Parse lcov merged.info output into a line coverage snapshot."""
    result = {"total_lines": 0, "hit_lines": 0, "miss_lines": 0, "line_map": {}, "source_line_map": {}}
    if not filepath or not os.path.exists(filepath):
        return result
    current_file = ""
    with open(filepath, encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if line.startswith("SF:"):
                current_file = normalize_rtl_source_path(line[3:])
            elif line.startswith("DA:"):
                parts = line[3:].split(",")
                if len(parts) != 2:
                    continue
                try:
                    line_no = int(parts[0])
                    count = int(parts[1])
                except ValueError:
                    continue
                key = (current_file, line_no)
                result["line_map"][key] = count
                result["source_line_map"][key] = count
                result["total_lines"] += 1
                if count > 0:
                    result["hit_lines"] += 1
                else:
                    result["miss_lines"] += 1
            elif line == "end_of_record":
                current_file = ""
    return result


def _convert_merged_dat_to_line_map(filepath: str) -> Tuple[Dict[str, object], Optional[str]]:
    """Convert Verilator data to a temporary LCOV map without persisting it."""
    empty = {"total_lines": 0, "hit_lines": 0, "miss_lines": 0, "line_map": {}, "source_line_map": {}}
    if not filepath or not os.path.exists(filepath):
        return empty, "merged.dat unavailable"
    converter = shutil.which("verilator_coverage")
    if not converter:
        return empty, "verilator_coverage unavailable"
    try:
        with tempfile.TemporaryDirectory(prefix="benchmark_coverage_") as temp_dir:
            output_path = os.path.join(temp_dir, "converted.info")
            completed = subprocess.run(
                [converter, "--write-info", output_path, filepath],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if completed.returncode != 0 or not os.path.exists(output_path):
                detail = (completed.stderr or completed.stdout or "conversion failed").strip()
                return empty, f"verilator_coverage failed: {detail}"
            return parse_merged_info(output_path), None
    except OSError as exc:
        return empty, f"verilator_coverage failed: {exc}"


def _coverage_paths(workspace_root: str) -> Dict[str, str]:
    line_dat_dir = os.path.join(workspace_root, "uc_test_report", "line_dat")
    return {
        "code_coverage_json": os.path.join(line_dat_dir, "code_coverage.json"),
        "merged_info": os.path.join(line_dat_dir, "merged.info"),
        "merged_dat": os.path.join(line_dat_dir, "merged.dat"),
    }


def load_line_coverage_snapshot(workspace_root: str) -> Dict[str, object]:
    """Load canonical totals from JSON and an optional map from merged.dat.

    Existing merged.info files are intentionally ignored: runs do not contain
    them consistently.  Raw Verilator C-record counts are instrumentation
    counters, not source-line totals.
    """
    paths = _coverage_paths(workspace_root)
    snapshot = {"total": 0, "hit": 0, "miss": 0, "rate": 0.0, "line_map": {}, "source_line_map": {}}
    source = "none"
    try:
        with open(paths["code_coverage_json"], "r", encoding="utf-8") as handle:
            coverage_json = json.load(handle)
        overview = coverage_json.get("overview", {})
        total = int(overview.get("total", {}).get("line", 0)) if isinstance(overview, dict) and "total" in overview else 0
        miss = int(overview.get("miss", {}).get("line", 0)) if isinstance(overview, dict) and "miss" in overview else 0
        hit = max(total - miss, 0)
        if total <= 0 and "total" in coverage_json:
            total = int(coverage_json.get("total") or 0)
            hit = int(coverage_json.get("hit") or 0)
            miss = max(total - hit, 0)
        if total > 0:
            rate_val = coverage_json.get("rate")
            if rate_val is not None and float(rate_val) <= 1.0:
                calc_rate = round(float(rate_val) * 100, 1)
            else:
                calc_rate = round(hit / total * 100, 1)
            snapshot.update({
                "total": total,
                "hit": hit,
                "miss": miss,
                "rate": calc_rate,
            })
            source = "code_coverage.json"
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        source = "none"

    converted, conversion_error = _convert_merged_dat_to_line_map(paths["merged_dat"])
    if converted["line_map"]:
        snapshot["line_map"] = dict(converted["line_map"])
        snapshot["source_line_map"] = dict(converted["source_line_map"])
        # code_coverage.json remains authoritative when present.  For legacy
        # runs containing only merged.dat, the generated LCOV summary is the
        # safe fallback; raw Verilator C-record counts are never used.
        if source == "none" and int(converted.get("total_lines") or 0) > 0:
            total = int(converted["total_lines"])
            hit = int(converted.get("hit_lines") or 0)
            snapshot.update({
                "total": total,
                "hit": hit,
                "miss": max(0, total - hit),
                "rate": round(hit / total * 100, 1),
            })
            source = "merged.dat:verilator_coverage"

    snapshot.update(
        {
            "source": source,
            "workspace_root": os.path.abspath(workspace_root),
            "paths": paths,
            "restored": bool(snapshot["line_map"]),
            "available": source != "none",
            "artifact_path": (
                paths["code_coverage_json"]
                if source == "code_coverage.json"
                else paths["merged_dat"] if source == "merged.dat:verilator_coverage" else ""
            ),
            "line_map_source": "merged.dat:verilator_coverage" if snapshot["line_map"] else "none",
            "line_map_error": conversion_error,
        }
    )
    return snapshot


def refresh_line_coverage_summary(workspace_root: str, output_path: Optional[str] = None) -> Dict[str, object]:
    """Write a normalized coverage summary file and return its payload."""
    snapshot = load_line_coverage_snapshot(workspace_root)
    line_dat_dir = os.path.join(workspace_root, "uc_test_report", "line_dat")
    target_path = output_path or os.path.join(line_dat_dir, "code_coverage.refresh.json")
    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
    payload = {
        "workspace_root": snapshot["workspace_root"],
        "source": snapshot["source"],
        "restored": snapshot["restored"],
        "overview": {
            "total": {"line": int(snapshot["total"])},
            "miss": {"line": int(snapshot["miss"])},
            "hit": {"line": int(snapshot["hit"])},
            "rate": float(snapshot["rate"]),
        },
        "line_map": [
            {"file": file_name, "line": line_no, "count": count}
            for (file_name, line_no), count in sorted((snapshot.get("source_line_map") or snapshot.get("line_map", {})).items())
        ],
        "paths": snapshot["paths"],
    }
    with open(target_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    payload["output_path"] = os.path.abspath(target_path)
    return payload
