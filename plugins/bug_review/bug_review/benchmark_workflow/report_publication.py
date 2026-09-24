"""Publish analysis evidence and reports without changing the reference registry."""
import json
import os
from pathlib import Path
from typing import Dict, Optional

from .evidence_enrichment import (enrich_benchmark_payload)
from .ground_truth_rtl_defects import (generate_ground_truth)
from .reported_roots import (attach_reported_root_alignment)
from .rtl_manual_audit import (build_rtl_manual_audit_queue, rtl_manual_audit_queue_markdown, write_rtl_manual_audit_queue_csv)
from .html_reporting import (rtl_manual_audit_queue_html)
from .bug_detail_reporting import (bug_evidence_details_html, candidate_exclusions_markdown)
from .gt_defect_reporting import (gt_defect_details_html)
from .reporting import (benchmark_audit_html as _benchmark_audit_html, benchmark_html as _benchmark_html, benchmark_markdown as _benchmark_markdown, cross_model_semantic_review_html as _cross_model_semantic_review_html, cross_model_semantic_review_markdown as _cross_model_semantic_review_markdown, cross_model_semantic_review_payload as _cross_model_semantic_review_payload, model_score_summary_html as _model_score_summary_html, model_score_summary_markdown as _model_score_summary_markdown, records_markdown as _records_markdown, replay_candidates_markdown as _replay_candidates_markdown, replay_runner_contracts_markdown as _replay_runner_contracts_markdown, write_matrix_csv as _write_matrix_csv, write_cross_model_semantic_review_csv as _write_cross_model_semantic_review_csv, write_model_score_summary_csv as _write_model_score_summary_csv, write_records_csv as _write_records_csv)
from .html_reporting import (benchmark_audit_html as _benchmark_audit_html_en, model_score_summary_html as _model_score_summary_html_en)

def _write_json(path: str, data: Dict[str, object]) -> None:
    """Write one UTF-8 report JSON artifact."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)

def _write_text(path: str, text: str) -> None:
    """Write one UTF-8 rendered report artifact."""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)

def _redirect_html(target_href: str, label: str = "Open report") -> str:
    """Render a report entry redirect with escaped link text."""
    escaped_target = target_href.replace("&", "&amp;").replace('"', "&quot;")
    escaped_label = label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        "<!DOCTYPE html>\n"
        "<html lang=\"zh-CN\">\n"
        "<head><meta charset=\"utf-8\">"
        f"<meta http-equiv=\"refresh\" content=\"0;url={escaped_target}\">"
        "</head>\n"
        f"<body><p><a href=\"{escaped_target}\">{escaped_label}</a></p></body>\n"
        "</html>"
    )

def _load_json(path: str):
    """Read a previously published JSON artifact."""
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)

def write_analysis_reports(
    payload: Dict[str, object],
    output_dir: str,
    write_matrix_json: bool = True,
    write_root_compat: bool = True,
    write_root_html_compat: bool = True,
    existing_ground_truth_path: Optional[str] = None,
) -> None:
    """Write all benchmark outputs into a tiered directory structure.

    output_dir/
    ├── index.html                         entry point
    ├── data/                              JSON machine-readable
    ├── tables/                            CSV flat tables
    ├── markdown/                          Markdown human-readable
    └── reports/{zh,en}/
        ├── index.html                     main report
        ├── bug_evidence_details.html      per-bug evidence drill-down
        ├── cross_model_non_merge_audit.html
        ├── cross_model_semantic_review.html
        └── benchmark_score_summary.html
    """
    payload = enrich_benchmark_payload(payload)

    data_dir = os.path.join(output_dir, "data")
    tables_dir = os.path.join(output_dir, "tables")
    md_dir = os.path.join(output_dir, "markdown")
    reports_dir = os.path.join(output_dir, "reports")
    report_zh = os.path.join(reports_dir, "zh")
    report_en = os.path.join(reports_dir, "en")
    for directory in (data_dir, tables_dir, md_dir, reports_dir, report_zh, report_en):
        os.makedirs(directory, exist_ok=True)

    # Refresh the machine-readable DUT GT from the current root audit.  An
    # existing GT file controls selection; new roots require explicit review.
    ground_truth_path = os.path.join(data_dir, "ground_truth_rtl_defects.json")
    explicit_gt_selection = payload.get("rtl_gt_selected_root_ids")
    existing_ground_truth = None
    if not isinstance(explicit_gt_selection, list):
        if existing_ground_truth_path and os.path.exists(existing_ground_truth_path):
            existing_ground_truth = existing_ground_truth_path
        elif os.path.exists(ground_truth_path):
            existing_ground_truth = ground_truth_path
        else:
            from .ground_truth_registry import find_registered_ground_truth
            reg_gt = find_registered_ground_truth(payload.get("dut") or "")
            if reg_gt and os.path.exists(reg_gt):
                existing_ground_truth = str(reg_gt)
    payload["ground_truth_rtl_defects"] = generate_ground_truth(
        payload,
        ground_truth_path,
        existing_path=existing_ground_truth,
        selected_root_ids=explicit_gt_selection,
        models=payload.get("model_names", []),
    )
    # Publications must not mutate the shared reference registry.
    attach_reported_root_alignment(payload)

    # Preserve an existing human-audit scope on ordinary full benchmark runs.
    # The queue intentionally survives GT exclusion, so it cannot be inferred
    # from ground_truth_rtl_defects.json on the next run.
    existing_audit_path = os.path.join(data_dir, "rtl_manual_audit_queue.json")
    if "rtl_manual_audit_root_ids" not in payload and os.path.exists(existing_audit_path):
        existing_audit = _load_json(existing_audit_path)
        queue_entries = existing_audit.get("rtl_manual_audit_queue", []) if isinstance(existing_audit, dict) else []
        if isinstance(queue_entries, list):
            payload["rtl_manual_audit_root_ids"] = [
                item.get("rtl_root_bug_id") for item in queue_entries
                if isinstance(item, dict) and item.get("rtl_root_bug_id")
            ]
    payload["rtl_manual_audit_queue"] = build_rtl_manual_audit_queue(payload)

    # ── data/ JSON ──
    if write_matrix_json:
        _write_json(os.path.join(data_dir, "benchmark_matrix.json"), payload)
    _write_json(os.path.join(data_dir, "benchmark_records.json"),
                {"benchmark_records": payload.get("benchmark_records", [])})
    _write_json(os.path.join(data_dir, "rtl_root_bugs.json"),
                {
                    "rtl_root_bugs": payload.get("rtl_root_bugs", []),
                    "rtl_root_scoring": payload.get("rtl_root_scoring", {}),
                    "rtl_root_review_queue": payload.get("rtl_root_review_queue", []),
                    "rtl_root_llm_review": payload.get("rtl_root_llm_review", []),
                    "rtl_root_failure_mode_reviews": payload.get("rtl_root_failure_mode_reviews", []),
                    "rtl_root_llm_policy": payload.get("rtl_root_llm_policy", {}),
                    "symptom_to_rtl_root_bug": payload.get("symptom_to_rtl_root_bug", {}),
                })
    _write_json(os.path.join(data_dir, "benchmark_score_summary.json"),
                {"model_score_summary": payload.get("model_score_summary", {})})
    _write_json(os.path.join(data_dir, "diagnostics.json"),
                {
                    "diagnostics": payload.get("diagnostics", []),
                    "diagnostics_summary": payload.get("diagnostics_summary", {}),
                })
    _write_json(os.path.join(data_dir, "non_rtl_claims.json"),
                {"non_rtl_claims": payload.get("non_rtl_claims", [])})
    _write_json(os.path.join(data_dir, "candidate_exclusions.json"),
                {"candidate_exclusions": payload.get("candidate_exclusions", [])})
    _write_json(os.path.join(data_dir, "replay_candidates.json"),
                {"replay_candidates": payload.get("replay_candidates", [])})
    _write_json(os.path.join(data_dir, "replay_runner_contracts.json"),
                {"replay_runner_contracts": payload.get("replay_runner_contracts", [])})

    review_payload = _cross_model_semantic_review_payload(payload)
    _write_json(os.path.join(data_dir, "cross_model_semantic_review.json"), review_payload)
    _write_json(os.path.join(data_dir, "cross_model_semantic_appeal.json"), review_payload)
    _write_json(os.path.join(data_dir, "rtl_manual_audit_queue.json"), {"rtl_manual_audit_queue": payload["rtl_manual_audit_queue"]})

    if write_root_compat:
        # ── root-level compatibility JSONs ──
        if write_matrix_json:
            _write_json(os.path.join(output_dir, "benchmark_matrix.json"), payload)
        _write_json(
            os.path.join(output_dir, "benchmark_records.json"),
            {"benchmark_records": payload.get("benchmark_records", [])},
        )
        _write_json(
            os.path.join(output_dir, "rtl_root_bugs.json"),
            {
                "rtl_root_bugs": payload.get("rtl_root_bugs", []),
                "rtl_root_scoring": payload.get("rtl_root_scoring", {}),
                "rtl_root_review_queue": payload.get("rtl_root_review_queue", []),
                "rtl_root_llm_review": payload.get("rtl_root_llm_review", []),
                "rtl_root_failure_mode_reviews": payload.get("rtl_root_failure_mode_reviews", []),
                "rtl_root_llm_policy": payload.get("rtl_root_llm_policy", {}),
                "symptom_to_rtl_root_bug": payload.get("symptom_to_rtl_root_bug", {}),
            },
        )
        _write_json(
            os.path.join(output_dir, "benchmark_score_summary.json"),
            {"model_score_summary": payload.get("model_score_summary", {})},
        )
        _write_json(
            os.path.join(output_dir, "diagnostics.json"),
            {
                "diagnostics": payload.get("diagnostics", []),
                "diagnostics_summary": payload.get("diagnostics_summary", {}),
            },
        )
        _write_json(
            os.path.join(output_dir, "non_rtl_claims.json"),
            {"non_rtl_claims": payload.get("non_rtl_claims", [])},
        )
        _write_json(
            os.path.join(output_dir, "candidate_exclusions.json"),
            {"candidate_exclusions": payload.get("candidate_exclusions", [])},
        )
        _write_json(
            os.path.join(output_dir, "replay_candidates.json"),
            {"replay_candidates": payload.get("replay_candidates", [])},
        )
        _write_json(
            os.path.join(output_dir, "replay_runner_contracts.json"),
            {"replay_runner_contracts": payload.get("replay_runner_contracts", [])},
        )
        _write_json(os.path.join(output_dir, "cross_model_semantic_review.json"), review_payload)
        _write_json(os.path.join(output_dir, "cross_model_semantic_appeal.json"), review_payload)
        _write_json(os.path.join(output_dir, "rtl_manual_audit_queue.json"), {"rtl_manual_audit_queue": payload["rtl_manual_audit_queue"]})

        # ── root-level compatibility Markdown/HTML ──
        _write_text(os.path.join(output_dir, "benchmark_matrix.md"), _benchmark_markdown(payload))
        _write_text(os.path.join(output_dir, "benchmark_records.md"), _records_markdown(payload))
        _write_text(os.path.join(output_dir, "benchmark_score_summary.md"), _model_score_summary_markdown(payload))
        _write_text(os.path.join(output_dir, "replay_candidates.md"), _replay_candidates_markdown(payload))
        _write_text(os.path.join(output_dir, "replay_runner_contracts.md"), _replay_runner_contracts_markdown(payload))
        _write_text(os.path.join(output_dir, "candidate_exclusions.md"), candidate_exclusions_markdown(payload))
        _write_text(os.path.join(output_dir, "cross_model_semantic_appeal.md"), _cross_model_semantic_review_markdown(payload))
        _write_text(os.path.join(output_dir, "cross_model_semantic_review.md"), _cross_model_semantic_review_markdown(payload))
        _write_text(os.path.join(output_dir, "rtl_manual_audit_queue.md"), rtl_manual_audit_queue_markdown(payload))
        _write_cross_model_semantic_review_csv(os.path.join(output_dir, "cross_model_semantic_appeal.csv"), payload)
        _write_cross_model_semantic_review_csv(os.path.join(output_dir, "cross_model_semantic_review.csv"), payload)
    raw_dut = str(payload.get("dut") or os.path.basename(output_dir))
    dut_name_clean = raw_dut[4:] if raw_dut.startswith("dut_") else raw_dut
    source_base_dirs = [
        Path(output_dir),
        Path("inputs"),
        Path(f"inputs/xiangshan/ucagent/{dut_name_clean}"),
        Path(f"inputs/xiangshan/ucagent/dut_{dut_name_clean}"),
    ]

    if write_root_compat:
        write_rtl_manual_audit_queue_csv(os.path.join(output_dir, "rtl_manual_audit_queue.csv"), payload)
        if write_root_html_compat:
            _write_text(os.path.join(output_dir, "index.html"), _benchmark_html(payload))
            _write_text(os.path.join(output_dir, "benchmark_score_summary.html"), _model_score_summary_html(payload))
            _write_text(os.path.join(output_dir, "cross_model_semantic_review.html"),
                        _cross_model_semantic_review_html(payload, lang="zh"))
            _write_text(os.path.join(output_dir, "cross_model_non_merge_audit.html"),
                        _benchmark_audit_html(payload, main_report_href="index.html#cross-model-audit"))
            _write_text(os.path.join(output_dir, "gt_defect_details.html"), gt_defect_details_html(payload, lang="zh", base_dirs=source_base_dirs))
            for root_bug in payload.get("rtl_root_bugs", []) or []:
                root_id = str(root_bug.get("rtl_root_bug_id") or "").strip() if isinstance(root_bug, dict) else ""
                if root_id:
                    _write_text(os.path.join(output_dir, f"suspected_bug_{root_id}.html"), gt_defect_details_html(payload, lang="zh", base_dirs=source_base_dirs, root_id=root_id))
            _write_text(os.path.join(output_dir, "bug_evidence_details.html"), bug_evidence_details_html(payload, lang="zh", base_dirs=source_base_dirs))
            _write_text(os.path.join(output_dir, "rtl_manual_audit_queue.html"), rtl_manual_audit_queue_html(payload, main_report_href="index.html#symptom-matrix", lang="zh"))

    # ── tables/ CSV ──
    _write_matrix_csv(os.path.join(tables_dir, "benchmark_matrix.csv"), payload)
    _write_records_csv(os.path.join(tables_dir, "benchmark_records.csv"), payload)
    _write_model_score_summary_csv(os.path.join(tables_dir, "benchmark_score_summary.csv"), payload)
    _write_cross_model_semantic_review_csv(os.path.join(tables_dir, "cross_model_semantic_review.csv"), payload)
    write_rtl_manual_audit_queue_csv(os.path.join(tables_dir, "rtl_manual_audit_queue.csv"), payload)
    if write_root_compat:
        _write_matrix_csv(os.path.join(output_dir, "benchmark_matrix.csv"), payload)
        _write_records_csv(os.path.join(output_dir, "benchmark_records.csv"), payload)
        _write_model_score_summary_csv(os.path.join(output_dir, "benchmark_score_summary.csv"), payload)
        _write_cross_model_semantic_review_csv(os.path.join(output_dir, "cross_model_semantic_review.csv"), payload)

    # ── markdown/ ──
    _write_text(os.path.join(md_dir, "benchmark_matrix.md"), _benchmark_markdown(payload))
    _write_text(os.path.join(md_dir, "benchmark_records.md"), _records_markdown(payload))
    _write_text(os.path.join(md_dir, "benchmark_score_summary.md"), _model_score_summary_markdown(payload))
    _write_text(os.path.join(md_dir, "replay_candidates.md"), _replay_candidates_markdown(payload))
    _write_text(os.path.join(md_dir, "replay_runner_contracts.md"), _replay_runner_contracts_markdown(payload))
    _write_text(os.path.join(md_dir, "candidate_exclusions.md"), candidate_exclusions_markdown(payload))
    _write_text(os.path.join(md_dir, "cross_model_semantic_review.md"), _cross_model_semantic_review_markdown(payload))
    _write_text(os.path.join(md_dir, "rtl_manual_audit_queue.md"), rtl_manual_audit_queue_markdown(payload))

    # ── reports/zh/ HTML ──
    benchmark_report_zh = _benchmark_html(payload, lang="zh")
    _write_text(os.path.join(report_zh, "index.html"), benchmark_report_zh)
    _write_text(os.path.join(report_zh, "gt_defect_details.html"), gt_defect_details_html(payload, lang="zh", base_dirs=source_base_dirs))
    for root_bug in payload.get("rtl_root_bugs", []) or []:
        root_id = str(root_bug.get("rtl_root_bug_id") or "").strip() if isinstance(root_bug, dict) else ""
        if root_id:
            _write_text(os.path.join(report_zh, f"suspected_bug_{root_id}.html"), gt_defect_details_html(payload, lang="zh", base_dirs=source_base_dirs, root_id=root_id))
    _write_text(os.path.join(report_zh, "bug_evidence_details.html"), bug_evidence_details_html(payload, lang="zh", base_dirs=source_base_dirs))
    _write_text(os.path.join(report_zh, "cross_model_non_merge_audit.html"),
                _benchmark_audit_html(payload, main_report_href="index.html#cross-model-audit", lang="zh"))
    _write_text(os.path.join(report_zh, "cross_model_semantic_review.html"),
                _cross_model_semantic_review_html(payload, lang="zh"))
    _write_text(os.path.join(report_zh, "benchmark_score_summary.html"), _model_score_summary_html(payload, lang="zh"))
    _write_text(os.path.join(report_zh, "rtl_manual_audit_queue.html"), rtl_manual_audit_queue_html(payload, main_report_href="index.html#symptom-matrix", lang="zh"))

    # ── reports/en/ HTML ──
    benchmark_report_en = _benchmark_html(payload, lang="en")
    _write_text(os.path.join(report_en, "index.html"), benchmark_report_en)
    _write_text(os.path.join(report_en, "gt_defect_details.html"), gt_defect_details_html(payload, lang="en", base_dirs=source_base_dirs))
    for root_bug in payload.get("rtl_root_bugs", []) or []:
        root_id = str(root_bug.get("rtl_root_bug_id") or "").strip() if isinstance(root_bug, dict) else ""
        if root_id:
            _write_text(os.path.join(report_en, f"suspected_bug_{root_id}.html"), gt_defect_details_html(payload, lang="en", base_dirs=source_base_dirs, root_id=root_id))
    _write_text(os.path.join(report_en, "bug_evidence_details.html"), bug_evidence_details_html(payload, lang="en", base_dirs=source_base_dirs))
    _write_text(os.path.join(report_en, "cross_model_non_merge_audit.html"),
                _benchmark_audit_html_en(payload, main_report_href="index.html#cross-model-audit", lang="en"))
    _write_text(os.path.join(report_en, "cross_model_semantic_review.html"),
                _cross_model_semantic_review_html(payload, lang="en"))
    _write_text(os.path.join(report_en, "benchmark_score_summary.html"), _model_score_summary_html_en(payload, lang="en"))
    _write_text(os.path.join(report_en, "rtl_manual_audit_queue.html"), rtl_manual_audit_queue_html(payload, main_report_href="index.html#symptom-matrix", lang="en"))


    # ── root index.html redirect ──
    if write_root_compat:
        _write_text(os.path.join(output_dir, "index.html"),
                    _redirect_html("reports/zh/index.html", "进入 Benchmark 报告"))
