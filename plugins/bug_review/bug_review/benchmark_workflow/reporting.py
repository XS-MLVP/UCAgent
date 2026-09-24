"""Reporting for the Bug Review workflow."""
import csv
import html
import json
from typing import Dict, List, Optional

from .matrix_enrichment import attach_matrix_record_evidence
from .html_reporting import (
    benchmark_html as _html_benchmark,
    benchmark_audit_html as _html_audit,
    model_score_summary_html as _html_score_summary,
    _benchmark_page_css as _html_benchmark_page_css,
    _t as _html_t,
)


def _primary_artifact_evidence(record: Dict[str, object]) -> Dict[str, object]:
    artifact_evidence = record.get("artifact_evidence", [])
    if not isinstance(artifact_evidence, list):
        return {}
    dict_items = [item for item in artifact_evidence if isinstance(item, dict)]
    for item in dict_items:
        if item.get("waveform_summary") or item.get("waveform_conversion_summary") or item.get("waveform_observations"):
            return item
    return dict_items[0] if dict_items else {}


def _evidence_support_tags(record: Dict[str, object]) -> List[str]:
    tags: List[str] = []
    coverage_summary = str(record.get("coverage_evidence_summary") or "").strip()
    if coverage_summary and coverage_summary != "none":
        tags.append(f"coverage:{coverage_summary}")

    artifact_evidence = _primary_artifact_evidence(record)
    waveform_summary = artifact_evidence.get("waveform_summary", {}) if artifact_evidence else {}
    waveform_observations = artifact_evidence.get("waveform_observations", []) if artifact_evidence else []
    if (
        (isinstance(waveform_summary, dict) and waveform_summary)
        or waveform_observations
        or record.get("waveform_summary")
        or record.get("waveform_observation_preview")
        or record.get("waveform_observations")
        or record.get("waveform_observation_count")
    ):
        tags.append("waveform")

    if record.get("rtl_regions") or record.get("rtl_region_preview") or record.get("rtl_dependency_preview"):
        tags.append("rtl")

    replay_statuses = []
    for result in record.get("replay_results", []) or []:
        if isinstance(result, dict) and result.get("status"):
            replay_statuses.append(str(result.get("status")))
    if replay_statuses:
        replay_status = replay_statuses[0]
        if "reproduced" in replay_statuses:
            replay_status = "reproduced"
        elif "not_reproduced" in replay_statuses:
            replay_status = "not_reproduced"
        tags.append(f"replay:{replay_status}")

    if record.get("replay_manifests"):
        tags.append("replay_candidate")

    return tags


def _evidence_support_summary(record: Dict[str, object]) -> str:
    tags = _evidence_support_tags(record)
    return ", ".join(tags) if tags else "n/a"


def benchmark_html(data: Dict[str, object], lang: str = "zh") -> str:
    """Generate HTML dashboard. Delegates to html_reporting."""
    return _html_benchmark(data, lang=lang)

def benchmark_audit_html(
    data: Dict[str, object],
    main_report_href: str = "index.html",
    lang: str = "zh",
) -> str:
    """Cross-model non-merge audit page. Delegates to html_reporting."""
    return _html_audit(data, main_report_href=main_report_href, lang=lang)


def _semantic_review_payload(data: Dict[str, object]) -> Dict[str, object]:
    appeal_entries = []
    conflict_entries = []
    replay_review_entries = []
    audit_by_pair: Dict[tuple, Dict[str, object]] = {}
    pair_id_by_pair: Dict[tuple, str] = {}
    for index, item in enumerate(data.get("semantic_judgements", []) or [], start=1):
        if not isinstance(item, dict):
            continue
        left_id = item.get("left_candidate_id")
        right_id = item.get("right_candidate_id")
        if not left_id or not right_id:
            continue
        pair_id = f"LLM-P{index:04d}"
        pair_id_by_pair[(left_id, right_id)] = pair_id
        pair_id_by_pair[(right_id, left_id)] = pair_id
    for audit in data.get("cross_model_non_merge_audit", []) or []:
        if not isinstance(audit, dict):
            continue
        left_id = audit.get("left_candidate_id")
        right_id = audit.get("right_candidate_id")
        if left_id and right_id:
            audit_by_pair[(left_id, right_id)] = audit
            audit_by_pair[(right_id, left_id)] = audit

    def _pair_audit(left_id: object, right_id: object) -> Dict[str, object]:
        return audit_by_pair.get((left_id, right_id), {})

    def _pair_id(left_id: object, right_id: object) -> str:
        return pair_id_by_pair.get((left_id, right_id), "")

    source_appeals = data.get("semantic_appeals", []) or []
    if not source_appeals:
        for item in data.get("semantic_judgements", []) or []:
            if not isinstance(item, dict):
                continue
            judgement = item.get("judgement", {}) if isinstance(item.get("judgement"), dict) else {}
            if judgement.get("relation") != "same bug" or int(item.get("score", 0) or 0) >= 2:
                continue
            appeal = judgement.get("appeal", {}) if isinstance(judgement.get("appeal"), dict) else {}
            audit = _pair_audit(item.get("left_candidate_id"), item.get("right_candidate_id"))
            source_appeals.append(
                {
                    "appeal_id": f"{item.get('left_candidate_id')}__{item.get('right_candidate_id')}",
                    "left_candidate_id": item.get("left_candidate_id"),
                    "right_candidate_id": item.get("right_candidate_id"),
                    "left_model": item.get("left_model"),
                    "right_model": item.get("right_model"),
                    "dut": item.get("dut") or audit.get("dut"),
                    "base_score": item.get("score", 0),
                    "base_relation": judgement.get("relation", "same bug"),
                    "appeal": appeal,
                    "appeal_supported": bool(judgement.get("appeal_merge_supported")),
                    "left_signature": audit.get("left_signature", {}),
                    "right_signature": audit.get("right_signature", {}),
                }
            )

    for index, item in enumerate(source_appeals, start=1):
        if not isinstance(item, dict):
            continue
        appeal = item.get("appeal", {}) if isinstance(item.get("appeal"), dict) else {}
        audit = _pair_audit(item.get("left_candidate_id"), item.get("right_candidate_id"))
        appeal_entries.append(
            {
                "review_kind": "appeal",
                "llm_pair_id": item.get("llm_pair_id") or _pair_id(item.get("left_candidate_id"), item.get("right_candidate_id")),
                "review_id": item.get("appeal_id") or f"APPEAL-{index:04d}",
                "review_status": "pending",
                "review_source": "llm_second_pass",
                "dut": item.get("dut") or audit.get("dut"),
                "left_model": item.get("left_model"),
                "left_candidate_id": item.get("left_candidate_id"),
                "right_model": item.get("right_model"),
                "right_candidate_id": item.get("right_candidate_id"),
                "base_score": item.get("base_score", item.get("score", 0)),
                "base_relation": item.get("base_relation", "same bug"),
                "review_relation": appeal.get("relation", "insufficient evidence"),
                "review_confidence": appeal.get("confidence", 0.0),
                "review_supported": bool(item.get("appeal_supported", False)),
                "review_risk": appeal.get("merge_risk", "medium"),
                "review_rationale": appeal.get("rationale", ""),
                "review_evidence_links": appeal.get("evidence_links", []),
                "review_missing_evidence": appeal.get("missing_evidence", []),
                "left_signature": item.get("left_signature", {}) or audit.get("left_signature", {}),
                "right_signature": item.get("right_signature", {}) or audit.get("right_signature", {}),
            }
        )

    for item in data.get("semantic_judgements", []) or []:
        if not isinstance(item, dict):
            continue
        judgement = item.get("judgement", {}) if isinstance(item.get("judgement"), dict) else {}
        if judgement.get("relation") != "different bugs" or int(item.get("score", 0) or 0) < 4:
            continue
        audit = _pair_audit(item.get("left_candidate_id"), item.get("right_candidate_id"))
        conflict_entries.append(
            {
                "review_kind": "conflict",
                "llm_pair_id": _pair_id(item.get("left_candidate_id"), item.get("right_candidate_id")),
                "review_id": f"CONFLICT-{item.get('left_candidate_id')}__{item.get('right_candidate_id')}",
                "review_status": "pending",
                "review_source": "semantic_conflict_filter",
                "dut": item.get("dut") or audit.get("dut"),
                "left_model": item.get("left_model"),
                "left_candidate_id": item.get("left_candidate_id"),
                "right_model": item.get("right_model"),
                "right_candidate_id": item.get("right_candidate_id"),
                "base_score": item.get("score", 0),
                "base_relation": judgement.get("relation", "different bugs"),
                "review_relation": judgement.get("relation", "different bugs"),
                "review_confidence": judgement.get("confidence", 0.0),
                "review_supported": False,
                "review_risk": "high",
                "review_rationale": "LLM says different bugs but heuristic score is high enough for review",
                "review_evidence_links": [],
                "review_missing_evidence": [],
                "left_signature": audit.get("left_signature", {}),
                "right_signature": audit.get("right_signature", {}),
            }
        )

    for record in data.get("benchmark_records", []) or []:
        if not isinstance(record, dict) or record.get("status") != "found":
            continue
        if record.get("evidence_tier") != "replay_contradicted_review":
            continue
        replay_results = record.get("replay_results", []) or []
        replay_statuses = [str(item.get("status")) for item in replay_results if isinstance(item, dict) and item.get("status")]
        replay_review_entries.append(
            {
                "review_kind": "replay_review",
                "review_id": f"REPLAY-{record.get('canonical_bug')}__{record.get('model')}",
                "review_status": "pending",
                "review_source": "replay_not_reproduced",
                "dut": record.get("dut"),
                "model": record.get("model"),
                "canonical_bug": record.get("canonical_bug"),
                "candidate_id": ",".join(record.get("candidate_ids", []) or []) or "n/a",
                "review_relation": "not reproduced with structural support",
                "review_confidence": 0.0,
                "review_supported": True,
                "review_risk": "high",
                "review_rationale": record.get("score_reason", ""),
                "review_evidence_links": [
                    tag for tag in [
                        "rtl" if (record.get("rtl_regions") or record.get("rtl_region_preview") or record.get("rtl_dependency_preview")) else "",
                        "waveform" if (record.get("waveform_focus_signals") or record.get("waveform_observation_preview") or record.get("waveform_observations")) else "",
                        "coverage" if str(record.get("coverage_evidence_summary") or "").strip() not in {"", "none"} else "",
                    ] if tag
                ],
                "review_missing_evidence": replay_statuses,
                "rtl_regions": record.get("rtl_regions", []),
                "rtl_dependency_preview": record.get("rtl_dependency_preview", []),
                "coverage_evidence_summary": record.get("coverage_evidence_summary", "none"),
                "score": record.get("evidence_score", 0),
                "score_reason": record.get("score_reason", ""),
                "replay_results": replay_results,
                "waveform_focus_signals": record.get("waveform_focus_signals", []),
                "tests": record.get("tests", []),
            }
        )

    combined_entries = appeal_entries + conflict_entries
    return {
        "schema": "cross_model_semantic_review.v1",
        "purpose": "Unified semantic review queue for cross-model disagreements and low-support same-bug appeals.",
        "notes": [
            "Appeal rows are same-bug candidates with low structural support and need human follow-up.",
            "Conflict rows are different-bug candidates with strong heuristic support and need human review.",
            "Replay review rows are not-reproduced candidates with structural evidence and need review.",
            "These rows are review material, not primary clustering decisions.",
        ],
        "appeal_entries": appeal_entries,
        "conflict_entries": conflict_entries,
        "replay_review_entries": replay_review_entries,
        "entries": combined_entries,
    }


def _semantic_review_table(
    entries: List[Dict[str, object]],
    lang: str,
    empty_text: str,
    show_evidence_columns: bool,
) -> str:
    colspan = 11 if show_evidence_columns else 9
    if not entries:
        return f"<tr><td colspan='{colspan}' class='muted'>{html.escape(empty_text)}</td></tr>"

    def esc(value: object) -> str:
        return html.escape("" if value is None else str(value))

    rows = []
    for item in entries:
        pair = (
            f"{item.get('left_model')}/{item.get('left_candidate_id')} "
            f"vs {item.get('right_model')}/{item.get('right_candidate_id')}"
        )
        support_risk = f"{item.get('review_supported')} ({item.get('review_risk') or 'n/a'})"
        evidence_cells = ""
        if show_evidence_columns:
            evidence_cells = (
                f"<td class='review-wide-col'>{esc(', '.join(item.get('review_evidence_links', [])) or 'n/a')}</td>"
                f"<td class='review-wide-col'>{esc(', '.join(item.get('review_missing_evidence', [])) or 'n/a')}</td>"
            )
        rows.append(
            "<tr>"
            f"<td class='review-pair-id-col'>{esc(item.get('llm_pair_id') or 'n/a')}</td>"
            f"<td class='review-id-col'>{esc(item.get('review_id'))}</td>"
            f"<td class='review-status-col'>{esc(item.get('review_status'))}</td>"
            f"<td class='review-source-col'>{esc(item.get('review_source'))}</td>"
            f"<td class='review-dut-col'>{esc(item.get('dut'))}</td>"
            f"<td class='review-pair-col'>{esc(pair)}</td>"
            f"<td class='review-score-col as'>{esc(item.get('base_score'))}</td>"
            f"<td class='review-relation-col'>{esc(item.get('review_relation') or 'n/a')}</td>"
            f"<td class='review-compact-col'>{esc(item.get('review_confidence'))}</td>"
            f"<td class='review-compact-col'>{esc(support_risk)}</td>"
            f"{evidence_cells}"
            "</tr>"
        )
    return "\n".join(rows)


def cross_model_semantic_review_markdown(data: Dict[str, object], lang: str = "en") -> str:
    payload = _semantic_review_payload(data)
    show_evidence_columns = any(
        item.get("review_evidence_links") or item.get("review_missing_evidence")
        for item in payload["entries"]
    )
    headers = [
        _html_t("review_th_pair_id", lang),
        _html_t("review_th_id", lang),
        _html_t("review_th_status", lang),
        _html_t("review_th_source", lang),
        _html_t("review_th_dut", lang),
        _html_t("review_th_pair", lang),
        _html_t("review_th_base_score", lang),
        _html_t("review_th_review_relation", lang),
        _html_t("review_th_confidence", lang),
        _html_t("review_th_support_risk", lang),
    ]
    if show_evidence_columns:
        headers.extend([
            _html_t("review_th_evidence", lang),
            _html_t("review_th_missing", lang),
        ])
    header_line = "| " + " | ".join(headers) + " |"
    divider_line = "|" + "|".join("---" for _ in headers) + "|"

    def _review_row(item: Dict[str, object]) -> str:
        pair = (
            f"{item.get('left_model')}/{item.get('left_candidate_id')} "
            f"vs {item.get('right_model')}/{item.get('right_candidate_id')}"
        )
        cells = [
            f"`{item.get('llm_pair_id') or 'n/a'}`",
            f"`{item.get('review_id')}`",
            f"`{item.get('review_status')}`",
            f"`{item.get('review_source')}`",
            f"`{item.get('dut') or ''}`",
            f"`{pair}`",
            f"`{item.get('base_score', 0)}`",
            f"`{item.get('review_relation') or 'n/a'}`",
            f"`{item.get('review_confidence', 0)}`",
            f"`{item.get('review_supported')} ({item.get('review_risk') or 'n/a'})`",
        ]
        if show_evidence_columns:
            cells.extend([
                f"`{', '.join(item.get('review_evidence_links', [])) or 'n/a'}`",
                f"`{', '.join(item.get('review_missing_evidence', [])) or 'n/a'}`",
            ])
        return "| " + " | ".join(cells) + " |"

    lines = [
        f"# {_html_t('review_page_title', lang)}",
        "",
        f"- Schema: `{payload['schema']}`",
        f"- {_html_t('review_page_desc', lang)}",
        f"- {_html_t('review_note', lang)}",
        "",
        f"## {_html_t('review_section_appeal', lang)}",
        f"- {_html_t('review_section_appeal_desc', lang)}",
        "",
        header_line,
        divider_line,
    ]
    for item in payload["appeal_entries"]:
        lines.append(_review_row(item))
    lines.extend([
        "",
        f"## {_html_t('review_section_conflict', lang)}",
        f"- {_html_t('review_section_conflict_desc', lang)}",
        "",
        header_line,
        divider_line,
    ])
    for item in payload["conflict_entries"]:
        lines.append(_review_row(item))
    replay_entries = payload.get("replay_review_entries", []) or []
    if replay_entries:
        lines.extend([
            "",
            f"## {_html_t('review_section_replay', lang)}",
            f"- {_html_t('review_section_replay_desc', lang)}",
            "",
            "| " + " | ".join([
                _html_t("review_th_candidate", lang),
                _html_t("review_th_dut", lang),
                _html_t("review_th_status", lang),
                _html_t("review_th_replay_status", lang),
                _html_t("review_th_base_score", lang),
                _html_t("review_th_replay_support", lang),
                _html_t("review_th_replay_rtl", lang),
                _html_t("review_th_replay_coverage", lang),
                _html_t("review_th_replay_reason", lang),
            ]) + " |",
            "|" + "|".join("---" for _ in range(9)) + "|",
        ])
        for item in replay_entries:
            rtl_preview = item.get("rtl_dependency_preview") or []
            rtl_text = ", ".join((rtl_preview[:3] or item.get("review_evidence_links", []))) or "n/a"
            coverage_text = item.get("coverage_evidence_summary") or "n/a"
            lines.append(
                "| " + " | ".join([
                    f"`{item.get('candidate_id') or 'n/a'}`",
                    f"`{item.get('dut') or ''}`",
                    f"`{item.get('review_status')}`",
                    f"`{', '.join(result.get('status', '') for result in item.get('replay_results', []) if result.get('status')) or 'not_reproduced'}`",
                    f"`{item.get('score', 0)}`",
                    f"`{', '.join(item.get('review_evidence_links', [])) or 'n/a'}`",
                    f"`{rtl_text}`",
                    f"`{coverage_text}`",
                    f"`{item.get('review_rationale') or item.get('score_reason') or 'n/a'}`",
                ]) + " |"
            )
    return "\n".join(lines) + "\n"


def cross_model_semantic_review_html(data: Dict[str, object], lang: str = "zh") -> str:
    payload = _semantic_review_payload(data)
    html_lang = "en" if lang == "en" else "zh-CN"

    def esc(value: object) -> str:
        return html.escape("" if value is None else str(value))

    sections = [
        ("appeal", payload["appeal_entries"], _html_t("review_section_appeal", lang), _html_t("review_section_appeal_desc", lang)),
        ("conflict", payload["conflict_entries"], _html_t("review_section_conflict", lang), _html_t("review_section_conflict_desc", lang)),
    ]
    show_evidence_columns = any(
        item.get("review_evidence_links") or item.get("review_missing_evidence")
        for item in payload["entries"]
    )
    headers = [
        ("review_th_pair_id", "review-pair-id-col"),
        ("review_th_id", "review-id-col"),
        ("review_th_status", "review-status-col"),
        ("review_th_source", "review-source-col"),
        ("review_th_dut", "review-dut-col"),
        ("review_th_pair", "review-pair-col"),
        ("review_th_base_score", "review-score-col"),
        ("review_th_review_relation", "review-relation-col"),
        ("review_th_confidence", "review-compact-col"),
        ("review_th_support_risk", "review-compact-col"),
    ]
    if show_evidence_columns:
        headers.extend([
            ("review_th_evidence", "review-wide-col"),
            ("review_th_missing", "review-wide-col"),
        ])
    header_html = "".join(
        f"<th class='{css_class}'>{esc(_html_t(label_key, lang))}</th>"
        for label_key, css_class in headers
    )
    body_sections = []
    for kind, entries, section_title, section_desc in sections:
        rows = _semantic_review_table(entries, lang, _html_t("review_no_entries", lang), show_evidence_columns)
        body_sections.append(
            "<section class=\"section\">"
            "<div class=\"section-header\">"
            f"<div><h2>{esc(section_title)}</h2><p>{esc(section_desc)}</p></div>"
            "</div>"
            "<div class=\"audit-wrap audit-wrap-full\">"
            "<table class=\"audit-table review-table\">"
            "<thead><tr>"
            f"{header_html}"
            "</tr></thead>"
            f"<tbody>{rows}</tbody>"
            "</table>"
            "</div>"
            "</section>"
        )

    replay_entries = payload.get("replay_review_entries", []) or []
    if replay_entries:
        replay_rows = []
        for item in replay_entries:
            rtl_preview = item.get("rtl_dependency_preview") or []
            rtl_text = ", ".join((rtl_preview[:3] or item.get("review_evidence_links", []))) or "n/a"
            coverage_text = item.get("coverage_evidence_summary") or "n/a"
            replay_statuses = ", ".join(
                result.get("status", "") for result in item.get("replay_results", []) if isinstance(result, dict) and result.get("status")
            ) or "not_reproduced"
            replay_rows.append(
                "<tr>"
                f"<td class='review-id-col'>{esc(item.get('review_id'))}</td>"
                f"<td class='review-source-col'>{esc(item.get('review_status'))}</td>"
                f"<td class='review-dut-col'>{esc(item.get('dut'))}</td>"
                f"<td class='review-pair-col'>{esc(item.get('candidate_id'))}</td>"
                f"<td class='review-score-col as'>{esc(item.get('score'))}</td>"
                f"<td class='review-compact-col'>{esc(item.get('review_rationale') or item.get('score_reason') or 'n/a')}</td>"
                f"<td class='review-compact-col'>{esc(replay_statuses)}</td>"
                f"<td class='review-compact-col'>{esc(', '.join(item.get('review_evidence_links', [])) or 'n/a')}</td>"
                f"<td class='review-wide-col'>{esc(rtl_text)}</td>"
                f"<td class='review-wide-col'>{esc(coverage_text)}</td>"
                "</tr>"
            )
        body_sections.append(
            "<section class=\"section\">"
            "<div class=\"section-header\">"
            f"<div><h2>{esc(_html_t('review_section_replay', lang))}</h2><p>{esc(_html_t('review_section_replay_desc', lang))}</p></div>"
            "</div>"
            "<div class=\"audit-wrap audit-wrap-full\">"
            "<table class=\"audit-table review-table\">"
            "<thead><tr>"
            f"<th>{esc(_html_t('review_th_id', lang))}</th>"
            f"<th>{esc(_html_t('review_th_status', lang))}</th>"
            f"<th>{esc(_html_t('review_th_dut', lang))}</th>"
            f"<th>{esc(_html_t('review_th_candidate', lang))}</th>"
            f"<th>{esc(_html_t('review_th_base_score', lang))}</th>"
            f"<th>{esc(_html_t('review_th_replay_reason', lang))}</th>"
            f"<th>{esc(_html_t('review_th_replay_status', lang))}</th>"
            f"<th>{esc(_html_t('review_th_replay_support', lang))}</th>"
            f"<th>{esc(_html_t('review_th_replay_rtl', lang))}</th>"
            f"<th>{esc(_html_t('review_th_replay_coverage', lang))}</th>"
            "</tr></thead>"
            f"<tbody>{''.join(replay_rows)}</tbody>"
            "</table>"
            "</div>"
            "</section>"
        )

    return """<!DOCTYPE html>
<html lang="{html_lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{page_title}</title>
  <style>{css}</style>
</head>
<body>
  <div class="page">
    <div class="top-nav">
      <a class="back-link" href="index.html">{back_text}</a>
      <div class="meta-text">{queue_text}: {appeal_count} + {conflict_count}</div>
    </div>
    <section class="hero">
      <h1>{title}</h1>
      <p>{desc}</p>
    </section>
    {body_sections}
  </div>
</body>
</html>
""".format(
        css=_html_benchmark_page_css(audit_full=True),
        html_lang=html_lang,
        page_title=esc(_html_t("review_page_title", lang)),
        back_text=esc(_html_t("appeal_back_to_main", lang)),
        queue_text=esc(_html_t("review_queue_label", lang)),
        appeal_count=len(payload["appeal_entries"]),
        conflict_count=len(payload["conflict_entries"]),
        title=esc(_html_t("review_page_title", lang)),
        desc=esc(_html_t("review_page_desc", lang)),
        body_sections="\n".join(body_sections),
    )


def cross_model_semantic_appeal_payload(data: Dict[str, object]) -> Dict[str, object]:
    return _semantic_review_payload(data)


def cross_model_semantic_review_payload(data: Dict[str, object]) -> Dict[str, object]:
    return _semantic_review_payload(data)


def cross_model_semantic_appeal_markdown(data: Dict[str, object], lang: str = "en") -> str:
    return cross_model_semantic_review_markdown(data, lang=lang)


def cross_model_semantic_appeal_html(data: Dict[str, object], lang: str = "zh") -> str:
    title = _html_t("review_page_title", lang)
    back = _html_t("appeal_back_to_main", lang)
    target = "cross_model_semantic_review.html"
    return f"""<!DOCTYPE html>
<html lang="{ 'en' if lang == 'en' else 'zh-CN' }">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="0;url={target}">
  <title>{html.escape(title)}</title>
</head>
<body>
  <p><a href="{target}">{html.escape(back)}</a></p>
</body>
</html>
"""


def write_cross_model_semantic_review_csv(path: str, data: Dict[str, object]) -> None:
    write_cross_model_semantic_appeal_csv(path, data)


def benchmark_markdown(data: Dict[str, object]) -> str:
    model_names = data.get("model_names", [])
    lines = [
        "# Model x Canonical RTL Bug Matrix",
        "",
    ]
    if data.get("model_score_summary", {}).get("ranking"):
        lines.extend(["## Model Score Summary", ""])
        lines.append(
            f"- Policy version: `{data.get('model_score_summary', {}).get('policy_version') or 'n/a'}`"
        )
        for item in data["model_score_summary"]["ranking"]:
            lines.append(
                f"- `{item.get('model')}`: score=`{item.get('total_score')}/{item.get('max_score')}`, "
                f"normalized=`{item.get('normalized_score')}`, found=`{item.get('found_count')}`, "
                f"tiers=`{item.get('tier_counts')}`, reasons=`{item.get('score_reason_counts', {})}`"
            )
        lines.append("")
    if data.get("replay_merge_summary"):
        replay_summary = data["replay_merge_summary"]
        lines.extend(
            [
                "## Replay Merge Summary",
                "",
                f"- Matched candidates: `{replay_summary.get('matched_candidate_count', 0)}`",
                f"- Input replay results: `{replay_summary.get('input_result_count', 0)}`",
                "",
            ]
        )
    semantic_llm_config = data.get("semantic_llm_config", {})
    if isinstance(semantic_llm_config, dict) and semantic_llm_config:
        lines.extend(["## Semantic LLM Config", ""])
        for key in ("provider", "model", "base_url", "api_key"):
            value = semantic_llm_config.get(key)
            if key == "api_key":
                lines.append(f"- {key}: `{'set' if value else 'unset'}`")
            elif value:
                lines.append(f"- {key}: `{value}`")
        lines.append("")
    semantic_pair_config = data.get("semantic_pair_config", {})
    if isinstance(semantic_pair_config, dict) and semantic_pair_config:
        lines.extend(["## Semantic Pair Config", ""])
        for key in ("mode", "budget", "recall", "source"):
            value = semantic_pair_config.get(key)
            if value is not None and value != "":
                lines.append(f"- {key}: `{value}`")
        lines.append("")
    if data.get("rationale_source_counts"):
        lines.extend(["## Rationale Source Counts", ""])
        lines.append("### Total")
        for kind, count in data["rationale_source_counts"].items():
            lines.append(f"- `{kind}`: {count}")
        for scope_key in ("intra_model", "cross_model"):
            scope_counts = data.get("rationale_scope_counts", {}).get(scope_key, {})
            if scope_counts:
                lines.extend(["", f"### {scope_key}"])
                for kind, count in scope_counts.items():
                    lines.append(f"- `{kind}`: {count}")
        lines.append("")
    lines.extend([
        "| Canonical bug | DUT | Property | Model statuses |",
        "|---|---|---|---|",
    ])
    for row in data["matrix"]:
        model_parts = []
        for model_name in model_names:
            details = row["per_model"][model_name]
            if details["found"]:
                validation = details.get("validation_summary") or "unknown"
                coverage_source = details.get("coverage_evidence_summary") or "none"
                evidence_score = details.get("evidence_score", 0)
                evidence_tier = details.get("evidence_tier", "n/a")
                replay_statuses = ",".join(
                    result.get("status", "unknown")
                    for result in details.get("replay_results", [])
                    if isinstance(result, dict)
                ) or "n/a"
                observations = "; ".join(details.get("observation_preview", [])) or "n/a"
                waveform_summary = details.get("waveform_summary", {}) if isinstance(details.get("waveform_summary", {}), dict) else {}
                waveform_observations = "; ".join(details.get("waveform_observation_preview", [])) or "n/a"
                aux_evidence = _evidence_support_summary(details)
                model_parts.append(
                    f"{model_name}=found[{validation};coverage={coverage_source};replay={replay_statuses};tier={evidence_tier};score={evidence_score}], "
                    f"tests={details.get('test_count', 0)}, obs={observations}, "
                    f"waveform={waveform_summary.get('status') or 'n/a'}, waveform_focus={','.join(details.get('waveform_focus_signals', [])) or 'n/a'}, waveform_obs={waveform_observations}, aux={aux_evidence}"
                )
            else:
                model_parts.append(f"{model_name}=not_found")
        model_summary = " ; ".join(model_parts)
        lines.append(
            f"| `{row['canonical_bug']}` | `{row['dut']}` | {row['property_text']} | {model_summary} |"
        )
    lines.extend(["", "## Per-Model Details", ""])
    for row in data["matrix"]:
        lines.append(f"### `{row['canonical_bug']}` `{row['dut']}`")
        lines.append(f"- Property: {row['property_text']}")
        lines.append(f"- Signals: {', '.join(row.get('signals', [])) or 'n/a'}")
        lines.append(f"- Cluster rationale: {'; '.join(row.get('cluster_rationale', []))}")
        if row.get("cluster_rationale_details"):
            lines.append(
                "- Cluster rationale details: "
                + "; ".join(
                    f"{item.get('kind')}={','.join(item.get('values', [])) if item.get('values') else item.get('value')}"
                    for item in row["cluster_rationale_details"]
                )
            )
        rtl_refs = ", ".join(
            f"{item['path'].split('/')[-1]}:{item['line_start']}-{item['line_end']}"
            for item in row.get("rtl_regions", [])[:6]
        )
        lines.append(f"- Canonical RTL regions: {rtl_refs or 'n/a'}")
        for model_name in model_names:
            details = row["per_model"][model_name]
            if details["found"]:
                replay_statuses = ", ".join(
                    result.get("status", "unknown")
                    for result in details.get("replay_results", [])
                    if isinstance(result, dict)
                ) or "n/a"
                lines.append(
                f"- {model_name}: found, validation={details.get('validation_summary') or 'unknown'}, "
                f"coverage={details.get('coverage_evidence_summary') or 'none'}, "
                f"tier={details.get('evidence_tier') or 'n/a'}, "
                f"score={details.get('evidence_score', 0)}, "
                f"reason={details.get('score_reason') or 'n/a'}, "
                f"replay={replay_statuses}, "
                f"tests={', '.join(details.get('test_preview', [])) or 'n/a'}"
                f"{' ...' if details.get('test_count', 0) > len(details.get('test_preview', [])) else ''}, "
                f"observations={'; '.join(details.get('observation_preview', [])) or 'n/a'}, "
                f"waveform_focus={', '.join(details.get('waveform_focus_signals', [])) or 'n/a'}, "
                f"rtl={', '.join(details.get('rtl_region_preview', [])) or 'n/a'}, "
                f"rtl_dependency={'; '.join(details.get('rtl_dependency_preview', [])) or 'n/a'}, "
                f"aux_evidence={_evidence_support_summary(details)}"
            )
            else:
                lines.append(f"- {model_name}: not_found")
    if data.get("cross_model_non_merge_audit"):
        lines.extend(["", "## Cross-Model Non-Merge Audit", ""])
        if data.get("cross_model_non_merge_reason_counts"):
            lines.append("### Top Blocking Reasons")
            for reason, count in list(data["cross_model_non_merge_reason_counts"].items())[:10]:
                lines.append(f"- `{reason}`: {count}")
            lines.append("")
        for item in data["cross_model_non_merge_audit"]:
            reasons = ", ".join(item.get("blocking_reasons", [])) or "n/a"
            left_sig = item.get("left_signature", {})
            right_sig = item.get("right_signature", {})
            lines.append(
                f"- `{item['left_candidate_id']}` vs `{item['right_candidate_id']}`: "
                f"score={item['score']}, semantic={item.get('semantic_relation') or 'none'}, "
                f"reasons={reasons}"
            )
            lines.append(
                f"  left={left_sig.get('fg') or 'n/a'}/{left_sig.get('fc') or 'n/a'} "
                f"spec={','.join(left_sig.get('spec_property_ids', [])) or 'n/a'} "
                f"cov={','.join(left_sig.get('coverage_region_preview', [])) or 'n/a'}"
            )
            lines.append(
                f"  right={right_sig.get('fg') or 'n/a'}/{right_sig.get('fc') or 'n/a'} "
                f"spec={','.join(right_sig.get('spec_property_ids', [])) or 'n/a'} "
                f"cov={','.join(right_sig.get('coverage_region_preview', [])) or 'n/a'}"
            )
    if data.get("semantic_judgements"):
        lines.extend(["", "## Semantic Judgements", ""])
        for item in data["semantic_judgements"]:
            judgement = item["judgement"]
            lines.append(
                f"- `{item['left_candidate_id']}` vs `{item['right_candidate_id']}`: "
                f"{judgement['relation']} (confidence={judgement['confidence']})"
            )
    return "\n".join(lines) + "\n"


def inventory_markdown(data: Dict[str, object]) -> str:
    lines = [
        "# Repository Inventory",
        "",
        f"- Root: `{data['root']}`",
        f"- Files: `{data['file_count']}`",
        "",
        "## Top-level counts",
    ]
    for name, count in data["top_level_counts"].items():
        lines.append(f"- `{name}`: {count}")
    lines.extend(["", "## Extension counts"])
    for extension, count in list(data["extension_counts"].items())[:15]:
        lines.append(f"- `{extension}`: {count}")
    lines.extend(["", "## Reusable components"])
    for item in data["reusable_components"]:
        lines.append(f"- `{item['path']}`: {item['reuse']}")
    lines.extend(["", "## Notes"])
    for note in data["notes"]:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def records_markdown(data: Dict[str, object]) -> str:
    lines = [
        "# BugReview Result Library",
        "",
        "| Canonical bug | DUT | Model | Status | Property | Expected / Observed |",
        "|---|---|---|---|---|---|",
    ]
    for item in data.get("benchmark_records", []):
        expected = item.get("expected") or "n/a"
        observed = item.get("observed") or "n/a"
        lines.append(
            f"| `{item['canonical_bug']}` | `{item['dut']}` | `{item['model']}` | `{item['status']}` | "
            f"{item.get('property_text') or 'n/a'} | {expected} / {observed} |"
        )
    lines.extend(["", "## Record Details", ""])
    for item in data.get("benchmark_records", []):
        lines.append(f"### `{item['canonical_bug']}` `{item['model']}` `{item['status']}`")
        lines.append(f"- DUT: `{item['dut']}`")
        lines.append(f"- Property: {item.get('property_text') or 'n/a'}")
        lines.append(f"- Signals: {', '.join(item.get('signals', [])) or 'n/a'}")
        lines.append(f"- Expected: {item.get('expected') or 'n/a'}")
        lines.append(f"- Observed: {item.get('observed') or 'n/a'}")
        lines.append(f"- Trigger: {item.get('trigger') or 'n/a'}")
        lines.append(f"- Failure mode: {item.get('failure_mode') or 'n/a'}")
        lines.append(f"- Root cause: {item.get('root_cause') or 'n/a'}")
        lines.append(f"- Root cause validation: `{item.get('root_cause_validation') or 'missing'}`")
        lines.append(f"- Candidate disposition: `{item.get('candidate_disposition') or 'active'}`")
        lines.append(f"- Waveform focus signals: {', '.join(item.get('waveform_focus_signals', [])) or 'n/a'}")
        lines.append(f"- Validation: {item.get('validation_summary') or 'n/a'}")
        lines.append(
            f"- Evidence score: `{item.get('evidence_score', 0)}` "
            f"(`{item.get('evidence_tier') or 'n/a'}`)"
        )
        lines.append(f"- Score reason: {item.get('score_reason') or 'n/a'}")
        lines.append(f"- Coverage evidence: {item.get('coverage_evidence_summary') or 'none'}")
        replay_manifests = item.get("replay_manifests", [])
        if replay_manifests:
            for manifest in replay_manifests[:3]:
                lines.append(
                    f"- Replay manifest: preferred_test=`{manifest.get('preferred_test') or 'n/a'}`, "
                    f"feasible=`{manifest.get('replay_feasible')}`"
                )
        else:
            lines.append("- Replay manifest: n/a")
        replay_results = item.get("replay_results", [])
        if replay_results:
            for result in replay_results[:3]:
                lines.append(
                    f"- Replay result: status=`{result.get('status') or 'n/a'}`, "
                    f"probe_status=`{result.get('probe_status') or 'n/a'}`"
                )
        else:
            lines.append("- Replay result: n/a")
        claim_sources = item.get("claim_sources", [])
        if claim_sources:
            for claim in claim_sources[:4]:
                source = claim.get("source_report", {})
                lines.append(
                    f"- Claim source: `{claim.get('claim_id')}` {claim.get('bug_identity') or 'n/a'} "
                    f"@ `{source.get('path')}`:{source.get('line_start')}-{source.get('line_end')}"
                )
        else:
            lines.append("- Claim source: n/a")
        tests = item.get("tests", [])
        lines.append(
            f"- Test classification: bug-specific=`{len(item.get('bug_specific_tests', []))}`, "
            f"infrastructure=`{len(item.get('supporting_infrastructure_tests', []))}`"
        )
        if tests:
            for test in tests[:4]:
                lines.append(
                    f"- Test: `{test.get('nodeid')}` @ `{test.get('source_file')}`:{test.get('source_lines', [None, None])[0]}-"
                    f"{test.get('source_lines', [None, None])[1]}, outcome={test.get('outcome') or 'n/a'}"
                )
        else:
            lines.append("- Test: n/a")
        spec_matches = item.get("spec_matches", [])
        if spec_matches:
            for spec in spec_matches[:4]:
                lines.append(
                    f"- Spec: `{spec.get('property_id')}` @ `{spec.get('source_path')}`:{spec.get('line_start')}-{spec.get('line_end')}"
                )
        else:
            lines.append("- Spec: n/a")
        rtl_regions = item.get("rtl_regions", [])
        if rtl_regions:
            lines.append(
                "- RTL: " + ", ".join(
                    f"{region['path'].split('/')[-1]}:{region['line_start']}-{region['line_end']}"
                    for region in rtl_regions[:6]
                )
            )
        else:
            lines.append("- RTL: n/a")
        rtl_dependency_preview = item.get("rtl_dependency_preview", [])
        if rtl_dependency_preview:
            lines.append("- RTL dependency preview: " + "; ".join(rtl_dependency_preview[:6]))
        else:
            lines.append("- RTL dependency preview: n/a")
        artifact_evidence = _primary_artifact_evidence(item)
        waveform_summary = artifact_evidence.get("waveform_summary", {}) if artifact_evidence else {}
        if waveform_summary:
            lines.append(
                "- Waveform summary: "
                f"status=`{waveform_summary.get('status') or 'n/a'}`, "
                f"files=`{waveform_summary.get('waveform_file_count', 0)}`, "
                f"signals=`{', '.join(waveform_summary.get('focus_signals', [])) or 'n/a'}`, "
                f"decode_supported=`{waveform_summary.get('decode_supported')}`"
            )
            if waveform_summary.get("notes"):
                lines.append(f"- Waveform notes: {', '.join(waveform_summary.get('notes', []))}")
        else:
            lines.append("- Waveform summary: n/a")
        waveform_conversion_summary = artifact_evidence.get("waveform_conversion_summary", {}) if artifact_evidence else {}
        if waveform_conversion_summary:
            conversion_parts = [
                "- Waveform conversion: ",
                f"status=`{waveform_conversion_summary.get('status') or 'n/a'}`",
                f"total=`{waveform_conversion_summary.get('total', 0)}`",
                f"converted=`{waveform_conversion_summary.get('converted', 0)}`",
                f"observations=`{waveform_conversion_summary.get('observation_count', 0)}`",
                f"report=`{waveform_conversion_summary.get('report_path') or 'n/a'}`",
            ]
            if waveform_conversion_summary.get("summary_path"):
                conversion_parts.append(f"summary=`{waveform_conversion_summary.get('summary_path')}`")
            lines.append(
                ", ".join(conversion_parts)
            )
        else:
            lines.append("- Waveform conversion: n/a")
        if artifact_evidence:
            observations = artifact_evidence.get("waveform_observations", [])
            if observations:
                lines.append(
                    "- Waveform observations: "
                    + ", ".join(
                        f"{obs.get('signal')}@{obs.get('window')}={obs.get('pattern')}"
                        for obs in observations[:4]
                    )
                )
            else:
                lines.append("- Waveform observations: n/a")
        else:
            lines.append("- Waveform observations: n/a")
        lines.append(f"- Auxiliary evidence: {_evidence_support_summary(item)}")
    return "\n".join(lines) + "\n"


def replay_candidates_markdown(data: Dict[str, object]) -> str:
    manifest = data.get("manifest", {})
    title = "# Replay Candidates"
    header_lines = [title, ""]
    if manifest:
        header_lines.extend(
            [
                f"- DUT: `{manifest.get('dut') or 'n/a'}`",
                f"- Model: `{manifest.get('model') or 'n/a'}`",
                f"- Run key: `{manifest.get('run_key') or 'n/a'}`",
            ]
        )
    else:
        header_lines.append("- BugReview comparison replay candidates")
    lines = [
        *header_lines,
        f"- Replay candidates: `{len(data.get('replay_candidates', []))}`",
        "",
        "| Candidate | Preferred Test | Feasible | Replay Status |",
        "|---|---|---|---|",
    ]
    for item in data.get("replay_candidates", []):
        replay_manifest = item.get("replay_manifest", {})
        replay_result = item.get("replay_result", {})
        lines.append(
            f"| `{item['candidate_id']}` | `{replay_manifest.get('preferred_test') or 'n/a'}` | "
            f"`{replay_manifest.get('replay_feasible')}` | `{replay_result.get('status') or 'n/a'}` |"
        )
    return "\n".join(lines) + "\n"


def replay_records_markdown(data: Dict[str, object]) -> str:
    lines = [
        "# Replay Merge Results",
        "",
        f"- Replay records: `{len(data.get('replay_records', []))}`",
        "",
        "| Candidate | Preferred Test | Replay Status |",
        "|---|---|---|",
    ]
    for item in data.get("replay_records", []):
        result = item.get("replay_result", {})
        lines.append(
            f"| `{item.get('candidate_id')}` | `{item.get('preferred_test') or 'n/a'}` | `{result.get('status') or 'n/a'}` |"
        )
    return "\n".join(lines) + "\n"


def replay_merge_summary_markdown(data: Dict[str, object]) -> str:
    summary = data.get("replay_merge_summary", {})
    lines = [
        "# Replay Merge Summary",
        "",
        f"- Matched candidates: `{summary.get('matched_candidate_count', 0)}`",
        f"- Matched replay candidates: `{summary.get('matched_replay_candidate_count', 0)}`",
        f"- Replay candidates: `{summary.get('replay_candidate_count', 0)}`",
        f"- Input replay results: `{summary.get('input_result_count', 0)}`",
    ]
    return "\n".join(lines) + "\n"


def replay_results_markdown(data: Dict[str, object], benchmark_records: Optional[List[Dict[str, object]]] = None) -> str:
    summary = data.get("summary", {})
    status_counts = summary.get("status_counts", {})
    results = data.get("results", [])

    # 构建 candidate_id → canonical_bug 映射
    cid_to_bug: Dict[str, str] = {}
    if benchmark_records:
        for rec in benchmark_records:
            bug = rec.get("canonical_bug", "")
            for cid in rec.get("candidate_ids", []) or []:
                if bug and cid:
                    cid_to_bug[cid] = bug

    # 从每个 result 的 contract.input 提取 model / preferred_test
    rich_items = []
    for item in results:
        result = item.get("result", {})
        contract = item.get("replay_runner_contract", {})
        inp = contract.get("input", {}) if isinstance(contract.get("input"), dict) else {}
        cid = item.get("candidate_id") or ""
        rich_items.append({
            "candidate_id": cid,
            "model": inp.get("model") or "?",
            "test": inp.get("preferred_test") or "",
            "status": result.get("status") or "?",
            "phase": result.get("phase") or "",
            "reason": result.get("reason") or "",
            "canonical_bug": cid_to_bug.get(cid, ""),
        })

    # 按 model → status 分组
    by_model: Dict[str, Dict[str, List[Dict]]] = {}
    models_order = []
    for item in rich_items:
        model = item["model"]
        status = item["status"]
        if model not in by_model:
            by_model[model] = {}
            models_order.append(model)
        by_model[model].setdefault(status, []).append(item)

    # 从 benchmark_records 收集未参与 replay 的 bug（found 但 replay_results 为空）
    no_replay_bugs: Dict[str, List[Dict[str, str]]] = {}
    if benchmark_records:
        for rec in benchmark_records:
            if rec.get("status") != "found":
                continue
            if rec.get("replay_results"):
                continue
            model = rec.get("model", "")
            if not model:
                continue
            no_replay_bugs.setdefault(model, []).append({
                "canonical_bug": rec.get("canonical_bug", ""),
                "validation": rec.get("validation_summary", ""),
            })

    lines = [
        "# Replay Results",
        "",
        f"**Total contracts**: {summary.get('input_contract_count', len(results))}",
        f"**Total results**: {summary.get('result_count', len(results))}",
    ]

    for st, cnt in sorted(status_counts.items()):
        lines.append(f"- `{st}`: {cnt}")

    lines.append("")

    # Explanation for not_reproduced
    if "not_reproduced" in status_counts:
        lines.extend([
            "> **What `not_reproduced` means**:",
            "> - Replay execution ran (pytest actually executed the test)",
            "> - But the test **passed**, meaning the claimed bug was not reproduced",
            "> - Therefore marked as `not_reproduced`",
            "",
        ])

    # Group by model
    for model in models_order:
        grouped = by_model[model]
        model_replay_total = sum(len(v) for v in grouped.values())
        missing = no_replay_bugs.get(model, [])
        model_bug_total = model_replay_total + len(missing)

        lines.append(f"## {model} ({model_replay_total} replay contracts, {model_bug_total} bugs)")
        lines.append("")

        # Show not_reproduced first, then reproduced, then others
        for status in ["not_reproduced", "reproduced"]:
            items = grouped.get(status, [])
            if not items:
                continue
            lines.append(f"### {status}")
            lines.append("")
            for it in items:
                bug_tag = f" / `{it['canonical_bug']}`" if it["canonical_bug"] else ""
                lines.append(f"- **{it['candidate_id']}**{bug_tag}")
                if it["test"]:
                    lines.append(f"  - test: `{it['test']}`")
                if it["reason"]:
                    lines.append(f"  - reason: {it['reason']}")
                if it["phase"]:
                    lines.append(f"  - phase: `{it['phase']}`")
            lines.append("")

        # Other statuses
        other = {k: v for k, v in grouped.items() if k not in ("not_reproduced", "reproduced")}
        for status, items in sorted(other.items()):
            lines.append(f"### {status}")
            lines.append("")
            for it in items:
                bug_tag = f" / `{it['canonical_bug']}`" if it["canonical_bug"] else ""
                lines.append(f"- **{it['candidate_id']}**{bug_tag}")
                if it["test"]:
                    lines.append(f"  - test: `{it['test']}`")
                if it["reason"]:
                    lines.append(f"  - reason: {it['reason']}")
            lines.append("")

        # Bugs found but not replayed
        if missing:
            lines.append("### not replayed (insufficient evidence)")
            lines.append("")
            for m in missing:
                lines.append(f"- `{m['canonical_bug']}`: {m['validation']}")
            lines.append("")

    return "\n".join(lines) + "\n"


def replay_runner_contracts_markdown(data: Dict[str, object]) -> str:
    manifest = data.get("manifest", {})
    header_lines = ["# Replay Runner Contracts", ""]
    if manifest:
        header_lines.extend(
            [
                f"- DUT: `{manifest.get('dut') or 'n/a'}`",
                f"- Model: `{manifest.get('model') or 'n/a'}`",
                f"- Run key: `{manifest.get('run_key') or 'n/a'}`",
            ]
        )
    else:
        header_lines.append("- BugReview comparison replay contracts")
    lines = [
        *header_lines,
        f"- Contracts: `{len(data.get('replay_candidates', []))}`",
        "",
        "| Candidate | Runner Kind | Preferred Test | Placeholder Status |",
        "|---|---|---|---|",
    ]
    for item in data.get("replay_candidates", []):
        contract = item.get("replay_runner_contract", {})
        contract_input = contract.get("input", {})
        placeholder = contract.get("current_placeholder_result", {})
        lines.append(
            f"| `{item['candidate_id']}` | `{contract.get('runner_kind') or 'n/a'}` | "
            f"`{contract_input.get('preferred_test') or 'n/a'}` | `{placeholder.get('status') or 'n/a'}` |"
        )
    return "\n".join(lines) + "\n"


def run_markdown(data: Dict[str, object]) -> str:
    manifest = data["manifest"]
    lines = [
        "# Single Run Graph",
        "",
        f"- DUT: `{manifest['dut']}`",
        f"- Model: `{manifest['model']}`",
        f"- Run key: `{manifest['run_key']}`",
        f"- Workspace root: `{manifest['workspace_root']}`",
        f"- Claims: `{len(data['claims'])}`",
        f"- Executed tests: `{len(data['tests'])}`",
        f"- Spec properties: `{len(data.get('spec_properties', []))}`",
        f"- Candidate bugs: `{len(data['candidate_bugs'])}`",
        f"- Replay candidates: `{len(data.get('replay_candidates', []))}`",
        "",
        "## Problems",
    ]
    for problem in manifest["problems"]:
        lines.append(f"- {problem}")
    lines.extend(["", "## Candidate bugs"])
    for candidate in data["candidate_bugs"]:
        lines.append(
            f"- `{candidate['candidate_id']}`: {candidate['property_text']} "
            f"(tests={len(candidate['related_tests'])}, signals={', '.join(candidate['signal_names'])}, "
            f"spec_matches={len(candidate.get('spec_matches', []))}, "
            f"validation={candidate.get('validation_status', 'unknown')})"
        )
    if data.get("replay_candidates"):
        lines.extend(["", "## Replay Candidates"])
        for item in data["replay_candidates"][:20]:
            manifest = item.get("replay_manifest", {})
            result = item.get("replay_result", {})
            lines.append(
                f"- `{item['candidate_id']}`: preferred_test=`{manifest.get('preferred_test') or 'n/a'}`, "
                f"feasible=`{manifest.get('replay_feasible')}`, replay_status=`{result.get('status') or 'n/a'}`"
            )
        if len(data["replay_candidates"]) > 20:
            lines.append(f"- ... {len(data['replay_candidates']) - 20} more")
    return "\n".join(lines) + "\n"


def benchmark_replay_merge_markdown(data: Dict[str, object]) -> str:
    lines = [
        "# BugReview Replay Merge",
        "",
        f"- Matched candidates: `{data.get('replay_merge_summary', {}).get('matched_candidate_count', 0)}`",
        f"- Matched replay candidates: `{data.get('replay_merge_summary', {}).get('matched_replay_candidate_count', 0)}`",
        f"- Replay candidates: `{data.get('replay_merge_summary', {}).get('replay_candidate_count', 0)}`",
        f"- Input replay results: `{data.get('replay_merge_summary', {}).get('input_result_count', 0)}`",
        "",
        "## Records",
    ]
    for item in data.get("benchmark_records", []):
        if item.get("status") != "found":
            continue
        replay_results = item.get("replay_results", [])
        if not replay_results:
            continue
        replay_statuses = ",".join(result.get("status", "") for result in replay_results if result.get("status"))
        lines.append(
            f"- `{item.get('canonical_bug')}` / `{item.get('model')}`: "
            f"validation=`{item.get('validation_summary') or 'n/a'}`, replay=`{replay_statuses or 'n/a'}`"
        )
    return "\n".join(lines) + "\n"


def model_score_summary_markdown(data: Dict[str, object]) -> str:
    summary = data.get("model_score_summary", {})
    lines = [
        "# Model Score Summary",
        "",
        f"- Policy version: `{summary.get('policy_version') or 'n/a'}`",
        "",
    ]
    policy = summary.get("policy", {})
    if policy:
        lines.extend(["## Policy", ""])
        for key, value in policy.items():
            lines.append(f"- `{key}`: `{value}`")
        lines.append("")
    semantic_pair_config = data.get("semantic_pair_config", {})
    if isinstance(semantic_pair_config, dict) and semantic_pair_config:
        lines.extend(["## Semantic Pair Config", ""])
        for key in ("mode", "budget", "recall", "source"):
            value = semantic_pair_config.get(key)
            if value is not None and value != "":
                lines.append(f"- `{key}`: `{value}`")
        lines.append("")
    lines.extend([
        "| Model | Total Score | Max Score | Normalized | Found | Tier Counts |",
        "|---|---|---|---|---|---|",
    ])
    for item in summary.get("ranking", []):
        lines.append(
            f"| `{item.get('model')}` | `{item.get('total_score', 0)}` | `{item.get('max_score', 0)}` | "
            f"`{item.get('normalized_score', 0.0)}` | `{item.get('found_count', 0)}` | "
            f"`{item.get('tier_counts', {})}` / `{item.get('score_reason_counts', {})}` |"
        )
    if not summary.get("ranking"):
        lines.append("| `n/a` | `0` | `0` | `0.0` | `0` | `{}` |")
    return "\n".join(lines) + "\n"


def model_score_summary_html(data: Dict[str, object], lang: str = "zh") -> str:
    """Model score summary page. Delegates to html_reporting."""
    return _html_score_summary(data, lang=lang)


def write_matrix_csv(path: str, data: Dict[str, object]) -> None:
    matrix = data.get("matrix", [])
    needs_enrichment = False
    for row in matrix:
        if not isinstance(row, dict):
            continue
        for details in row.get("per_model", {}).values():
            if isinstance(details, dict) and not (
                details.get("waveform_observation_preview")
                or details.get("waveform_observations")
                or details.get("waveform_observation_count")
            ):
                needs_enrichment = True
                break
        if needs_enrichment:
            break
    if needs_enrichment:
        data = attach_matrix_record_evidence(data)
    model_names = data.get("model_names", [])
    records_by_key = {
        (item.get("canonical_bug"), item.get("model")): item
        for item in data.get("benchmark_records", [])
        if isinstance(item, dict)
    }
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        header = [
            "canonical_bug",
            "dut",
            "property_text",
            "cluster_rationale",
            "cluster_rationale_details",
            "canonical_rtl_regions",
        ]
        for model_name in model_names:
            header.extend(
                [
                    f"{model_name}:status",
                    f"{model_name}:validation_statuses",
                    f"{model_name}:evidence_tier",
                    f"{model_name}:evidence_score",
                    f"{model_name}:score_reason",
                    f"{model_name}:waveform_summary",
                    f"{model_name}:waveform_observations",
                    f"{model_name}:replay_statuses",
                    f"{model_name}:test_count",
                    f"{model_name}:tests_preview",
                    f"{model_name}:observations_preview",
                    f"{model_name}:waveform_focus_signals",
                    f"{model_name}:rtl_regions_preview",
                    f"{model_name}:rtl_dependency_preview",
                    f"{model_name}:coverage_evidence",
                ]
            )
        writer.writerow(header)
        for row in data["matrix"]:
            values = [
                row["canonical_bug"],
                row["dut"],
                row["property_text"],
                "|".join(row.get("cluster_rationale", [])),
                "|".join(
                    f"{item.get('kind')}={','.join(item.get('values', [])) if item.get('values') else item.get('value')}"
                    for item in row.get("cluster_rationale_details", [])
                ),
                "; ".join(
                    f"{item['path'].split('/')[-1]}:{item['line_start']}-{item['line_end']}"
                    for item in row.get("rtl_regions", [])
                ),
            ]
            for model_name in model_names:
                details = row["per_model"][model_name]
                record = records_by_key.get((row["canonical_bug"], model_name), {})
                waveform_summary = details.get("waveform_summary", {}) if isinstance(details.get("waveform_summary", {}), dict) else {}
                if not waveform_summary:
                    artifact_evidence = record.get("artifact_evidence", []) if isinstance(record, dict) else []
                    waveform_summary = artifact_evidence[0].get("waveform_summary", {}) if artifact_evidence else {}
                waveform_summary_text = (
                    f"status={waveform_summary.get('status') or 'n/a'};"
                    f"files={waveform_summary.get('waveform_file_count', 0)};"
                    f"signals={','.join(waveform_summary.get('focus_signals', [])) or 'n/a'};"
                    f"decode_supported={waveform_summary.get('decode_supported')}"
                )
                waveform_observations_text = "|".join(details.get("waveform_observation_preview", []))
                values.extend(
                    [
                        details["status"],
                        details.get("validation_summary", ""),
                        details.get("evidence_tier", ""),
                        details.get("evidence_score", 0),
                        details.get("score_reason", ""),
                        waveform_summary_text,
                        waveform_observations_text,
                        "|".join(
                            result.get("status", "")
                            for result in details.get("replay_results", [])
                            if isinstance(result, dict)
                        ),
                        details.get("test_count", 0),
                        "|".join(details.get("test_preview", [])),
                        "|".join(details.get("observation_preview", [])),
                        "|".join(details.get("waveform_focus_signals", [])),
                        "|".join(details.get("rtl_region_preview", [])),
                        "|".join(details.get("rtl_dependency_preview", [])),
                        details.get("coverage_evidence_summary", "none"),
                    ]
                )
            writer.writerow(values)


def write_records_csv(path: str, data: Dict[str, object]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "canonical_bug",
                "dut",
                "model",
                "status",
                "property_text",
                "expected",
                "observed",
                "validation_summary",
                "evidence_tier",
                "evidence_score",
                "score_reason",
                "coverage_evidence_summary",
                "waveform_summary",
                "waveform_conversion",
                "waveform_observations",
                "replay_manifests",
                "replay_results",
                "claim_sources",
                "tests",
                "spec_matches",
                "waveform_focus_signals",
                "rtl_regions",
                "rtl_dependency_preview",
            ]
        )
        for item in data.get("benchmark_records", []):
            artifact_evidence = _primary_artifact_evidence(item)
            waveform_summary = artifact_evidence.get("waveform_summary", {}) if artifact_evidence else {}
            waveform_conversion = artifact_evidence.get("waveform_conversion_summary", {}) if artifact_evidence else {}
            waveform_observations = artifact_evidence.get("waveform_observations", []) if artifact_evidence else []
            waveform_summary_text = (
                f"status={waveform_summary.get('status') or 'n/a'};"
                f"files={waveform_summary.get('waveform_file_count', 0)};"
                f"signals={','.join(waveform_summary.get('focus_signals', [])) or 'n/a'};"
                f"decode_supported={waveform_summary.get('decode_supported')}"
            )
            waveform_conversion_text = (
                f"status={waveform_conversion.get('status') or 'n/a'};"
                f"total={waveform_conversion.get('total', 0)};"
                f"converted={waveform_conversion.get('converted', 0)};"
                f"report={waveform_conversion.get('report_path') or 'n/a'}"
            )
            if waveform_conversion.get("summary_path"):
                waveform_conversion_text += f";summary={waveform_conversion.get('summary_path')}"
            waveform_observations_text = "|".join(
                f"{item.get('signal')}@{item.get('window')}={item.get('pattern')}"
                for item in waveform_observations
            )
            writer.writerow(
                [
                    item.get("canonical_bug"),
                    item.get("dut"),
                    item.get("model"),
                    item.get("status"),
                    item.get("property_text"),
                    item.get("expected"),
                    item.get("observed"),
                    item.get("validation_summary"),
                    item.get("evidence_tier"),
                    item.get("evidence_score"),
                    item.get("score_reason"),
                    item.get("coverage_evidence_summary"),
                    waveform_summary_text,
                    waveform_conversion_text,
                    waveform_observations_text,
                    "|".join(
                        f"{manifest.get('preferred_test')}|feasible={manifest.get('replay_feasible')}"
                        for manifest in item.get("replay_manifests", [])
                    ),
                    "|".join(
                        f"{result.get('status')}|probe={result.get('probe_status')}"
                        for result in item.get("replay_results", [])
                    ),
                    "|".join(
                        f"{claim.get('claim_id')}@{claim.get('source_report', {}).get('path')}:{claim.get('source_report', {}).get('line_start')}"
                        for claim in item.get("claim_sources", [])
                    ),
                    "|".join(
                        f"{test.get('nodeid')}@{test.get('source_file')}:{test.get('source_lines', [None, None])[0]}"
                        for test in item.get("tests", [])
                    ),
                    "|".join(
                        f"{spec.get('property_id')}@{spec.get('source_path')}:{spec.get('line_start')}"
                        for spec in item.get("spec_matches", [])
                    ),
                    "|".join(item.get("waveform_focus_signals", [])),
                    "|".join(
                        f"{region.get('path')}:{region.get('line_start')}-{region.get('line_end')}"
                        for region in item.get("rtl_regions", [])
                    ),
                    "|".join(item.get("rtl_dependency_preview", [])),
                    item.get("trigger"),
                    item.get("failure_mode"),
                    item.get("root_cause"),
                    item.get("root_cause_validation"),
                    item.get("candidate_disposition"),
                    item.get("declared_confidence_percent"),
                ]
            )


def write_model_score_summary_csv(path: str, data: Dict[str, object]) -> None:
    summary = data.get("model_score_summary", {})
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "policy_version",
                "model",
                "total_score",
                "max_score",
                "normalized_score",
                "found_count",
                "tier_counts",
                "score_reason_counts",
            ]
        )
        for item in summary.get("ranking", []):
            writer.writerow(
                [
                    summary.get("policy_version", ""),
                    item.get("model"),
                    item.get("total_score", 0),
                    item.get("max_score", 0),
                    item.get("normalized_score", 0.0),
                    item.get("found_count", 0),
                    json.dumps(item.get("tier_counts", {}), ensure_ascii=False, sort_keys=True),
                    json.dumps(item.get("score_reason_counts", {}), ensure_ascii=False, sort_keys=True),
                ]
            )


def write_cross_model_semantic_appeal_csv(path: str, data: Dict[str, object]) -> None:
    payload = cross_model_semantic_appeal_payload(data)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "review_id",
                "review_kind",
                "review_status",
                "review_source",
                "dut",
                "left_model",
                "left_candidate_id",
                "right_model",
                "right_candidate_id",
                "base_score",
                "base_relation",
                "review_relation",
                "review_confidence",
                "review_supported",
                "review_risk",
                "review_evidence_links",
                "review_missing_evidence",
                "left_bug_identity",
                "right_bug_identity",
            ]
        )
        for item in payload.get("entries", []):
            writer.writerow(
                [
                    item.get("review_id", ""),
                    item.get("review_kind", ""),
                    item.get("review_status", "pending"),
                    item.get("review_source", "llm_second_pass"),
                    item.get("dut", ""),
                    item.get("left_model", ""),
                    item.get("left_candidate_id", ""),
                    item.get("right_model", ""),
                    item.get("right_candidate_id", ""),
                    item.get("base_score", 0),
                    item.get("base_relation", ""),
                    item.get("review_relation", ""),
                    item.get("review_confidence", ""),
                    item.get("review_supported", ""),
                    item.get("review_risk", ""),
                    "|".join(item.get("review_evidence_links", [])),
                    "|".join(item.get("review_missing_evidence", [])),
                    item.get("left_signature", {}).get("bug_identity", ""),
                    item.get("right_signature", {}).get("bug_identity", ""),
                ]
            )
