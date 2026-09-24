"""Normalized, auditable coverage metrics for one benchmark run."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, Iterable, Sequence

from .line_coverage_refresh import load_line_coverage_snapshot
from .paths import default_configs


def _coverage_status(available: bool, total: int, executions: Sequence[object]) -> str:
    if not available or total <= 0:
        return "UNAVAILABLE_COVERAGE"
    outcomes = {
        str(item.outcome or "").lower()
        for item in executions
        if hasattr(item, "outcome")
    }
    if outcomes & {"passed", "failed", "error"}:
        return "VALIDATED_COVERAGE"
    return "PARTIAL_COVERAGE"


def _scope_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _functional_scope(functional: Dict[str, object]) -> str:
    catalog = []
    for group in functional.get("groups", []) or []:
        if not isinstance(group, dict):
            continue
        points = []
        for point in group.get("points", []) or []:
            if not isinstance(point, dict):
                continue
            funcs = point.get("functions", {})
            if isinstance(funcs, dict) and funcs:
                bin_list = sorted(str(k) for k in funcs.keys())
            else:
                bin_list = sorted(str(item.get("name") or "") for item in point.get("bins", []) or [] if isinstance(item, dict))
            points.append({
                "name": point.get("name"),
                "bins": bin_list,
            })
        catalog.append({"name": group.get("name"), "points": sorted(points, key=lambda item: str(item["name"]))})
    return _scope_hash(sorted(catalog, key=lambda item: str(item["name"]))) if catalog else ""


def _functional_bin_catalog(functional: Dict[str, object]) -> list[Dict[str, object]]:
    catalog = []
    for group in functional.get("groups", []) or []:
        if not isinstance(group, dict):
            continue
        group_name = str(group.get("name") or "")
        for point in group.get("points", []) or []:
            if not isinstance(point, dict):
                continue
            point_name = str(point.get("name") or "")
            point_hinted = bool(point.get("hinted"))
            point_once = bool(point.get("once"))
            funcs = point.get("functions", {})
            if isinstance(funcs, dict) and funcs:
                for ck_name, tests in funcs.items():
                    bin_name = str(ck_name)
                    if not all((group_name, point_name, bin_name)):
                        continue
                    hit = bool(tests) if isinstance(tests, list) else bool(tests)
                    catalog.append({
                        "bin_id": "/".join((group_name, point_name, bin_name)),
                        "group": group_name, "point": point_name, "bin": bin_name,
                        "hit": hit,
                    })
            else:
                for item in point.get("bins", []) or []:
                    if not isinstance(item, dict):
                        continue
                    bin_name = str(item.get("name") or "")
                    if not all((group_name, point_name, bin_name)):
                        continue
                    hit = bool(item.get("hints", 0) > 0) if point_hinted else point_once
                    catalog.append({
                        "bin_id": "/".join((group_name, point_name, bin_name)),
                        "group": group_name, "point": point_name, "bin": bin_name,
                        "hit": hit,
                    })
    return sorted(catalog, key=lambda item: str(item["bin_id"]))


def _count_functional_coverage(functional: Dict[str, object]) -> Dict[str, object]:
    """Walk the group/point/bin tree to compute actual coverage counts.

    Toffee has two coverage collection modes:
    - **hinted** (point.hinted=True): per-bin ``hints`` field is populated;
      ``hints > 0`` means the bin was exercised.
    - **non-hinted** (point.hinted=False): per-bin data is NOT collected;
      ``once=True`` at the point level is the only coverage signal.
      When a non-hinted point is covered, all its bins are considered hit.
    - **functions/checkpoints**: point contains a dict mapping CK names to executed tests.
    """
    groups = functional.get("groups", []) or []
    group_total = 0
    group_hit = 0
    point_total = 0
    point_hit = 0
    bin_total = 0
    bin_hit = 0
    for g in groups:
        if not isinstance(g, dict):
            continue
        group_total += 1
        group_has_hit = bool(g.get("has_once") or g.get("hinted"))
        for p in g.get("points", []) or []:
            if not isinstance(p, dict):
                continue
            point_total += 1
            funcs = p.get("functions", {})
            if isinstance(funcs, dict) and funcs:
                point_has_hit = False
                for ck_name, tests in funcs.items():
                    bin_total += 1
                    is_hit = bool(tests) if isinstance(tests, list) else bool(tests)
                    if is_hit:
                        bin_hit += 1
                        point_has_hit = True
                if point_has_hit:
                    point_hit += 1
                    group_has_hit = True
            else:
                p_hit = bool(p.get("once") or p.get("hinted"))
                if p_hit:
                    point_hit += 1
                    group_has_hit = True
                bins = p.get("bins", []) or []
                n_bins = len(bins)
                bin_total += n_bins
                if p.get("hinted"):
                    bin_hit += sum(1 for b in bins if isinstance(b, dict) and b.get("hints", 0) > 0)
                elif p.get("once"):
                    bin_hit += n_bins
        if group_has_hit:
            group_hit += 1
    return {
        "group_total": group_total, "group_hit": group_hit,
        "point_total": point_total, "point_hit": point_hit,
        "bin_total": bin_total, "bin_hit": bin_hit,
    }


def load_ground_truth_catalog(dut_name: str, base_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Look for Ground Truth catalog generated from Spec Generator."""
    if not dut_name:
        return None
    from pathlib import Path
    search_dirs = [
        Path(base_dir) if base_dir else None,
        default_configs() / "specs" / dut_name,
        Path(f"spec_generator/outputs/{dut_name}"),
    ]
    for directory in search_dirs:
        if not directory:
            continue
        cat_file = directory / "ground_truth_catalog.json"
        if cat_file.is_file():
            try:
                with cat_file.open(encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return None


def evaluate_ground_truth_coverage(
    bin_catalog: Sequence[Dict[str, object]],
    catalog: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    import re
    if not catalog or not isinstance(catalog, dict) or not catalog.get("cks"):
        return {
            "available": False,
            "status": "UNAVAILABLE",
            "ground_truth_total_ck": 0,
            "ground_truth_hit_ck": 0,
            "ground_truth_ck_rate": None,
            "ground_truth_total_fg": 0,
            "ground_truth_hit_fg": 0,
            "ground_truth_fg_rate": None,
        }

    hit_bins = [b for b in bin_catalog if b.get("hit")]
    hit_bin_ids = {str(b.get("bin_id") or "") for b in hit_bins}
    hit_bin_names = {str(b.get("bin") or "").upper() for b in hit_bins}
    hit_point_names = {str(b.get("point") or "").upper() for b in hit_bins}
    hit_group_names = {str(b.get("group") or "").upper() for b in hit_bins}

    ck_results = []
    hit_ck_count = 0
    hit_fcs = set()

    for ck in catalog.get("cks", []):
        ck_id = str(ck.get("ck_id") or "").upper()
        fc_id = str(ck.get("fc_id") or "").upper()

        ck_clean = ck_id.replace("CK-", "")
        keywords = set(re.findall(r"[A-Za-z0-9]+", ck_clean.upper()))

        matched = False
        if ck_id in hit_bin_names or any(ck_clean in b for b in hit_bin_names):
            matched = True
        elif any(ck_id in b for b in hit_bin_ids):
            matched = True
        elif fc_id in hit_point_names or fc_id in hit_group_names:
            matched = True
        else:
            for b in hit_bin_names:
                b_tokens = set(re.findall(r"[A-Za-z0-9]+", b))
                if keywords and len(keywords & b_tokens) >= max(1, len(keywords) // 2):
                    matched = True
                    break

        if matched:
            hit_ck_count += 1
            hit_fcs.add(ck.get("fc_id"))

        ck_results.append({
            "ck_id": ck.get("ck_id"),
            "fc_id": ck.get("fc_id"),
            "hit": matched,
        })

    total_ck = len(catalog.get("cks", []))
    total_fg = int(catalog.get("total_fg") or len(catalog.get("fgs", [])) or 1)
    hit_fg_count = len({fc.split("-")[1] if "-" in fc else fc for fc in hit_fcs}) if hit_fcs else 0
    hit_fg_count = min(hit_fg_count, total_fg)

    return {
        "available": True,
        "status": "VALIDATED",
        "ground_truth_total_ck": total_ck,
        "ground_truth_hit_ck": hit_ck_count,
        "ground_truth_ck_rate": round(hit_ck_count / total_ck * 100, 1) if total_ck else 0.0,
        "ground_truth_total_fg": total_fg,
        "ground_truth_hit_fg": hit_fg_count,
        "ground_truth_fg_rate": round(hit_fg_count / total_fg * 100, 1) if total_fg else 0.0,
        "ck_details": ck_results,
    }


def functional_coverage_summary(
    report_data: Dict[str, object],
    source_path: str,
    executions: Sequence[object],
    dut: str = "",
) -> Dict[str, object]:
    functional = report_data.get("coverages", {}).get("functional", {}) if isinstance(report_data, dict) else {}
    if not isinstance(functional, dict):
        functional = {}
    counts = _count_functional_coverage(functional)
    group_total = counts["group_total"]
    group_hit = counts["group_hit"]
    point_total = counts["point_total"]
    point_hit = counts["point_hit"]
    bin_total = counts["bin_total"]
    bin_hit = counts["bin_hit"]
    # Fall back to summary fields when tree-walk yields nothing (legacy format).
    if bin_total == 0:
        group_total = int(functional.get("group_num_total") or 0)
        group_hit = int(functional.get("group_num_hints") or 0)
        point_total = int(functional.get("point_num_total") or 0)
        point_hit = int(functional.get("point_num_hints") or 0)
        bin_total = int(functional.get("bin_num_total") or 0)
        bin_hit = int(functional.get("bin_num_hints") or 0)
    available = bool(functional) and bin_total > 0
    execution_catalog = sorted({
        (
            str(getattr(execution, "nodeid", "") or ""),
            str(getattr(execution, "outcome", "unknown") or "unknown").lower(),
        )
        for execution in executions
        if str(getattr(execution, "nodeid", "") or "")
    })
    bin_cat = _functional_bin_catalog(functional) if available else []
    gt_catalog = load_ground_truth_catalog(dut)
    gt_metrics = evaluate_ground_truth_coverage(bin_cat, gt_catalog)

    return {
        "available": available,
        "status": _coverage_status(available, bin_total, executions),
        "group_total": group_total,
        "group_hit": min(group_hit, group_total),
        "point_total": point_total,
        "point_hit": min(point_hit, point_total),
        "bin_total": bin_total,
        "bin_hit": min(bin_hit, bin_total),
        "rate": round(min(bin_hit, bin_total) / bin_total * 100, 1) if bin_total else None,
        "ground_truth_coverage": gt_metrics,
        "source": "toffee_report.json" if available else "none",
        "artifact_path": source_path if available else "",
        "scope_signature": _functional_scope(functional) if available else "",
        "bin_catalog": bin_cat,
        # Keep the minimum execution ledger needed to validate future common
        # target mappings. This stays in the existing coverage summary.
        "execution_catalog": [
            {"nodeid": nodeid, "outcome": outcome}
            for nodeid, outcome in execution_catalog
        ],
    }


def line_coverage_summary(workspace_root: str, executions: Sequence[object]) -> Dict[str, object]:
    snapshot = load_line_coverage_snapshot(workspace_root)
    total = int(snapshot.get("total") or 0)
    hit = int(snapshot.get("hit") or 0)
    available = bool(snapshot.get("available")) and total > 0
    raw_line_map = snapshot.get("source_line_map") or snapshot.get("line_map") or {}
    line_map = [
        {"file": str(file_name), "line": int(line_no), "count": int(count)}
        for (file_name, line_no), count in sorted(raw_line_map.items())
    ]
    return {
        "available": available,
        "status": _coverage_status(available, total, executions),
        "total_lines": total,
        "hit_lines": min(hit, total),
        "miss_lines": max(0, total - hit),
        "rate": float(snapshot.get("rate")) if available else None,
        "source": str(snapshot.get("source") or "none"),
        "artifact_path": str(snapshot.get("artifact_path") or ""),
        "line_map_source": str(snapshot.get("line_map_source") or "none"),
        "line_map_error": snapshot.get("line_map_error"),
        # A summary-only artifact cannot be used to claim local RTL execution.
        # Preserve the normalized map for later root-local evidence calculation.
        "line_map": line_map,
        "line_map_available": bool(line_map),
        "scope_signature": _scope_hash(sorted((str(path), int(line)) for path, line in (snapshot.get("line_map") or {}))) if snapshot.get("line_map") else (_scope_hash(f"summary_{total}_{hit}") if available else ""),
    }


def root_local_line_coverage(
    line_coverage: Dict[str, object],
    root_anchor: Dict[str, object],
    window_radius: int = 10,
) -> Dict[str, object]:
    """Measure LCOV-covered RTL lines in a fixed window around one root."""
    base = {
        "available": False,
        "status": "UNAVAILABLE_ROOT_LOCAL_COVERAGE",
        "reason": "line_map_unavailable",
        "window_radius": window_radius,
        "source": str(line_coverage.get("source") or "none") if isinstance(line_coverage, dict) else "none",
    }
    if not isinstance(line_coverage, dict) or not isinstance(root_anchor, dict):
        return base
    entries = line_coverage.get("line_map")
    if not isinstance(entries, list) or not entries:
        return base
    anchor_path = root_anchor.get("path") or root_anchor.get("file")
    line_start = root_anchor.get("line_start")
    line_end = root_anchor.get("line_end", line_start)
    if not anchor_path or line_start is None or line_end is None:
        base["reason"] = "rtl_root_anchor_unavailable"
        return base
    try:
        line_start, line_end = int(line_start), int(line_end)
    except (TypeError, ValueError):
        base["reason"] = "rtl_root_anchor_invalid"
        return base

    anchor_normalized = os.path.normpath(str(anchor_path).replace("\\", "/"))
    anchor_file = os.path.basename(anchor_normalized)
    window_start = max(1, min(line_start, line_end) - window_radius)
    window_end = max(line_start, line_end) + window_radius
    parsed_entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            entry_line, count = int(entry.get("line")), int(entry.get("count"))
        except (TypeError, ValueError):
            continue
        entry_path = os.path.normpath(str(entry.get("file") or "").replace("\\", "/"))
        parsed_entries.append((entry_path, entry_line, count))
    exact_entries = [item for item in parsed_entries if item[0] == anchor_normalized]
    if exact_entries:
        matching_entries = exact_entries
    else:
        basename_entries = [item for item in parsed_entries if os.path.basename(item[0]) == anchor_file]
        source_paths = {item[0] for item in basename_entries}
        if len(source_paths) > 1:
            base.update({
                "reason": "ambiguous_root_file_basename",
                "anchor_file": anchor_file,
                "anchor_line_start": line_start,
                "anchor_line_end": line_end,
            })
            return base
        matching_entries = basename_entries
    coverable = [
        (entry_line, count)
        for _, entry_line, count in matching_entries
        if window_start <= entry_line <= window_end
    ]
    if not coverable:
        base.update({
            "reason": "no_coverable_lines_in_root_window",
            "anchor_file": anchor_file,
            "anchor_line_start": line_start,
            "anchor_line_end": line_end,
            "window_start": window_start,
            "window_end": window_end,
        })
        return base

    hit_lines = sum(1 for _, count in coverable if count > 0)
    total_lines = len(coverable)
    return {
        "available": True,
        "status": "VALIDATED_ROOT_LOCAL_COVERAGE" if line_coverage.get("status") == "VALIDATED_COVERAGE" else "PARTIAL_ROOT_LOCAL_COVERAGE",
        "reason": "root_window_lcov_line_map",
        "window_radius": window_radius,
        "anchor_file": anchor_file,
        "anchor_line_start": line_start,
        "anchor_line_end": line_end,
        "window_start": window_start,
        "window_end": window_end,
        "total_lines": total_lines,
        "hit_lines": hit_lines,
        "miss_lines": total_lines - hit_lines,
        "rate": round(hit_lines / total_lines * 100, 1),
        "source": str(line_coverage.get("source") or "none"),
    }


def attach_root_local_coverage(
    root_payload: Dict[str, object],
    coverage_by_model: Dict[str, object],
    window_radius: int = 10,
) -> Dict[str, object]:
    """Attach local coverage evidence without altering the root rank order."""
    root_bugs = root_payload.get("rtl_root_bugs", []) if isinstance(root_payload, dict) else []
    root_scoring = root_payload.get("rtl_root_scoring", {}) if isinstance(root_payload, dict) else {}
    if not isinstance(root_bugs, list) or not isinstance(root_scoring, dict):
        return root_payload
    per_model = root_scoring.get("per_model", {})
    if not isinstance(per_model, dict):
        return root_payload
    for model, summary in per_model.items():
        rates = []
        for root_bug in root_bugs:
            if not isinstance(root_bug, dict):
                continue
            models = root_bug.get("models", {})
            details = models.get(model, {}) if isinstance(models, dict) else {}
            if not isinstance(details, dict) or not details.get("found"):
                continue
            model_coverage = coverage_by_model.get(model, {}) if isinstance(coverage_by_model, dict) else {}
            line_coverage = model_coverage.get("line_coverage", {}) if isinstance(model_coverage, dict) else {}
            local = root_local_line_coverage(line_coverage, root_bug.get("root_anchor", {}), window_radius)
            details["root_local_line_coverage"] = local
            if local.get("available"):
                rates.append(float(local["rate"]))
        summary["root_local_coverage_root_count"] = len(rates)
        summary["root_local_line_coverage_rate"] = round(sum(rates) / len(rates), 1) if rates else None

    # Ranking rows copy per-model data; add display fields but leave sort keys intact.
    for row in root_scoring.get("ranking", []) or []:
        if isinstance(row, dict) and row.get("model") in per_model:
            summary = per_model[row["model"]]
            row["root_local_coverage_root_count"] = summary.get("root_local_coverage_root_count", 0)
            row["root_local_line_coverage_rate"] = summary.get("root_local_line_coverage_rate")
    return root_payload


def run_coverage_summary(
    report_data: Dict[str, object],
    toffee_report_path: str,
    workspace_root: str,
    executions: Sequence[object],
    dut: str = "",
) -> Dict[str, object]:
    return {
        "functional_coverage": functional_coverage_summary(report_data, toffee_report_path, executions, dut=dut),
        "line_coverage": line_coverage_summary(workspace_root, executions),
    }


def summarize_coverage_by_model(run_graphs: Iterable[Dict[str, object]], model_names: Sequence[str]) -> Dict[str, object]:
    by_model = {model: [] for model in model_names}
    for graph in run_graphs:
        manifest = graph.get("manifest", {}) if isinstance(graph, dict) else {}
        model = str(manifest.get("model") or "") if isinstance(manifest, dict) else ""
        if model in by_model:
            by_model[model].append(graph.get("coverage_metrics", {}))

    per_model = {}
    for model, summaries in by_model.items():
        summary = summaries[0] if len(summaries) == 1 and isinstance(summaries[0], dict) else {}
        per_model[model] = {
            "functional_coverage": summary.get("functional_coverage", {"available": False, "status": "UNAVAILABLE_COVERAGE"}),
            "line_coverage": summary.get("line_coverage", {"available": False, "status": "UNAVAILABLE_COVERAGE"}),
        }

    return {
        "per_model": per_model,
        "coverage_comparability": coverage_comparability(per_model, model_names),
    }


def coverage_comparability(
    per_model: Dict[str, object],
    model_names: Sequence[str],
) -> Dict[str, object]:
    """Compare normalized coverage scopes across model runs."""
    dimensions = ("functional_coverage", "line_coverage")
    comparability = {}
    for dimension in dimensions:
        entries = [
            per_model.get(model, {}).get(dimension, {})
            if isinstance(per_model.get(model, {}), dict)
            else {}
            for model in model_names
        ]
        valid = [item for item in entries if item.get("status") == "VALIDATED_COVERAGE"]
        signatures = {str(item.get("scope_signature") or "") for item in valid}
        if len(model_names) <= 1:
            comparable = len(valid) == len(model_names) and len(valid) > 0
            reason = "single_model_validated_coverage" if comparable else "coverage_not_comparable"
        else:
            comparable = len(valid) == len(model_names) and len(signatures) == 1 and bool(signatures - {""})
            reason = "same_validated_scope" if comparable else "coverage_not_comparable"
        comparability[dimension] = {
            "comparable": comparable,
            "reason": reason,
        }
    return comparability
