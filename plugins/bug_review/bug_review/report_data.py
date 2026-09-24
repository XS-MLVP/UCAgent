"""Build the report-facing data contract from adjudication and run evidence."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCHEMA = "benchmark_report_data.v1"


def _confidence(value: object, default: str = "low") -> str:
    """Normalize legacy confidence values to the public high/medium/low scale."""
    text = str(value or "").strip().lower()
    if text in {"high", "高", "confirmed", "strong"}:
        return "high"
    if text in {"medium", "中", "moderate", "likely"}:
        return "medium"
    if text in {"low", "低", "weak", "unknown"}:
        return "low"
    try:
        score = float(text.rstrip("%"))
    except (TypeError, ValueError):
        return default
    return "high" if score >= 80 else "medium" if score >= 50 else "low"


def load_report_profile(dut: str, config_root: Path) -> dict[str, Any]:
    path = Path(config_root) / f"{dut}.json"
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("dut") != dut:
        raise ValueError(f"invalid report profile: {path}")
    return value


def _waveform_by_case(report_view: dict) -> dict[str, dict]:
    output = {}
    for row in report_view.get("waveform_reviews", []):
        case_id = row.get("case", {}).get("case_id")
        if not case_id:
            continue
        result = row.get("waveform", {}).get("result", {})
        selection = result.get("waveform_selection", {})
        output[case_id] = {
            "evidence_id": row.get("review", {}).get("evidence_id", ""),
            "conclusion": row.get("review", {}).get("conclusion", ""),
            "waveform_file": selection.get("waveform_file", ""),
            "waveform_format": selection.get("format", ""),
            "waveform_size_bytes": selection.get("size_bytes", 0),
            "session_started_at": selection.get("session_started_at", ""),
            "modified_at": selection.get("modified_at", ""),
            "is_latest_session": selection.get("is_latest_session", False),
            "selection_rule": selection.get("selection_rule", ""),
            "signal_count": result.get("waveform_info", {}).get("signal_count", 0),
            "analysis_window": result.get("analysis_window", {}),
            "viewer": result.get("waveform_viewer", {}),
        }
    return output


def build_report_data(report_view: dict, profile: dict | None = None) -> dict[str, Any]:
    """Create the stable data consumed by report renderers.

    Machine-derived counts, cases and waveform metadata always come from the
    analysis payload. Human-authored explanatory text comes from the optional
    versioned report profile.
    """
    profile = profile or {}
    dut = str(report_view.get("dut") or profile.get("dut") or "")
    if not dut:
        raise ValueError("report data requires a DUT")
    if profile and profile.get("dut") != dut:
        raise ValueError(f"report profile DUT mismatch: {profile.get('dut')} != {dut}")

    final = report_view.get("final_bug_analysis") or {}
    bugs = {b.get("bug_id"): b for b in final.get("bugs", []) if isinstance(b, dict)}
    gt = report_view.get("ground_truth_rtl_defects") or report_view.get("_gt_file") or {}
    waves = _waveform_by_case(report_view)
    details = profile.get("defect_details", {})
    formal_bugs = []
    formal_case_ids = set()
    formal_root_ids = set()
    for defect in gt.get("defects", []):
        root_id = defect.get("source_root_id")
        source = bugs.get(root_id, {})
        detail = details.get(root_id, {})
        formal_root_ids.add(root_id)
        cases = []
        for case in source.get("cases", []):
            case_id = case.get("case_id")
            formal_case_ids.add(case_id)
            cases.append({
                **case,
                "test_name": str(case.get("nodeid") or "").split("::")[-1],
                "waveform": waves.get(case_id, {}),
                "waveform_summary": detail.get("case_waveform_summaries", {}).get(case_id, ""),
            })
        formal_bugs.append({
            "gt_id": defect.get("gt_id"),
            "global_gt_id": defect.get("global_gt_id"),
            "source_root_id": root_id,
            "title": detail.get("title") or source.get("title") or defect.get("description"),
            "summary": detail.get("summary") or defect.get("description"),
            "bug_id": root_id or defect.get("gt_id"),
            "confidence": _confidence(defect.get("source_anchor_confidence", "high")),
            "status": "suspected_bug",
            "severity": defect.get("severity", "unknown"),
            "failure_mode": defect.get("failure_mode") or source.get("failure_mode"),
            "root_cause": source.get("root_cause", ""),
            "evidence_summary": source.get("evidence_summary", ""),
            "rtl_regions": source.get("rtl_regions", []),
            "impact": detail.get("impact", ""),
            "reproduction_count": len(cases),
            "cases": cases,
            "rtl": {
                "primary": f"{defect.get('rtl_file')}:{defect.get('rtl_line_start')}-{defect.get('rtl_line_end')}",
                "related": defect.get("related_rtl_locations", []),
            },
            "evidence_types": detail.get("evidence_types", ["test_oracle", "waveform", "rtl", "spec"]),
            "scenario": detail.get("scenario", {}),
            "mechanism_steps": detail.get("mechanism_steps", []),
            "specification_basis": source.get("spec_violation", ""),
            "fix_recommendation": detail.get("fix_recommendation", {}),
            "evidence_boundary": detail.get("evidence_boundary", ""),
        })

    dispositions = profile.get("review_dispositions", {})
    review_items = []
    review_case_ids = set()
    for root_id, source in bugs.items():
        if root_id in formal_root_ids:
            continue
        decision = dispositions.get(root_id, {})
        case_ids = [c.get("case_id") for c in source.get("cases", []) if c.get("case_id")]
        review_case_ids.update(case_ids)
        review_items.append({
            "bug_id": root_id,
            "source_root_id": root_id,
            "title": source.get("title", ""),
            "case_count": len(case_ids),
            "case_ids": case_ids,
            "status": decision.get("status", "needs_review"),
            "short_reason": decision.get("short_reason", "证据链尚未闭环"),
            "reason": decision.get("reason", "证据链仍需补充或复核。"),
            "root_cause": source.get("root_cause", ""),
            "evidence_summary": source.get("evidence_summary", ""),
            "spec_violation": source.get("spec_violation", ""),
            "rtl_regions": source.get("rtl_regions", []),
            "cases": [
                {**case, "test_name": str(case.get("nodeid") or "").split("::")[-1],
                 "waveform": waves.get(case.get("case_id"), {})}
                for case in source.get("cases", [])
            ],
            "confidence": _confidence(decision.get("confidence") or source.get("confidence") or "low"),
            "scenario": decision.get("scenario", {}),
            "specification_basis": source.get("spec_violation", ""),
            "evidence_boundary": decision.get("evidence_boundary", ""),
        })

    failed_cases = []
    category_counts = {"bug": 0, "needs_review": 0, "false_positive": 0, "environment": 0}
    for row in report_view.get("failure_case_reviews", []):
        case, review = row.get("case", {}), row.get("review", {})
        case_id = case.get("case_id")
        if case_id in formal_case_ids:
            category, basis = "bug", next((b.get("bug_id") or b.get("gt_id") for b in formal_bugs if case_id in {c.get("case_id") for c in b["cases"]}), "")
        elif case_id in review_case_ids:
            category = "needs_review"
            basis = next((r["source_root_id"] for r in review_items if case_id in r["case_ids"]), "")
        elif review.get("classification") == "spec_misunderstanding":
            category, basis = "false_positive", "spec_or_interface_contract"
        else:
            category, basis = "environment", "test_or_environment"
        category_counts[category] += 1
        execution = (case.get("original_executions") or [{}])[0]
        failed_cases.append({
            "case_id": case_id,
            "nodeid": case.get("nodeid", ""),
            "test_name": str(case.get("nodeid") or "").split("::")[-1],
            "category": category,
            "basis": basis,
            "replay_status": row.get("replay", {}).get("status", ""),
            "symptom": execution.get("exception_message") or review.get("dut_actual") or "n/a",
        })

    verification = profile.get("verification_status", {})
    verification = {
        **verification,
        "formal_gt_count": 0,
        "suspected_bug_count": len(formal_bugs) + len(review_items),
        "suspected_bug_counts": {
            level: sum(1 for bug in [*formal_bugs, *review_items] if bug.get("confidence") == level)
            for level in ("high", "medium", "low")
        },
        "failed_case_count": len(failed_cases),
        "failure_category_counts": category_counts,
    }
    return {
        "schema": SCHEMA,
        "dut": dut,
        "sources": {
            "analysis_schema": report_view.get("analysis_schema"),
            "final_bug_analysis_schema": final.get("schema"),
            "ground_truth_schema": gt.get("schema_version"),
            "profile_schema": profile.get("schema"),
        },
        "verification_status": verification,
        "final_bugs": [*formal_bugs, *review_items],
        "suspected_bugs": [*formal_bugs, *review_items],
        "review_items": review_items,
        "failed_cases": failed_cases,
        "reported_bug_inventory": report_view.get("reported_bug_inventory", {}),
        "reported_replay_validation": report_view.get("reported_replay_validation", {}),
        "presentation": profile.get("presentation", {}),
    }
