"""Bug detail reporting for the Bug Review workflow."""
import html
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .html_reporting import _benchmark_page_css as _html_benchmark_page_css
from .gt_defect_reporting import code_snippet_html, _GT_DETAIL_EXTRA_CSS, SourceRegistry, _build_modal_html_and_js

_BUG_DETAIL_EXTRA_CSS = """
html { scroll-behavior: smooth; }
:target {
  outline: 3px solid #06b6d4;
  outline-offset: 4px;
  box-shadow: 0 0 0 6px rgba(6, 182, 212, 0.25), 0 8px 24px rgba(6, 182, 212, 0.12) !important;
  border-color: #06b6d4 !important;
  transition: outline 0.2s ease, box-shadow 0.2s ease;
}
.bug .model-block{border-top:1px solid var(--border);margin-top:clamp(10px,1vw,20px);padding-top:clamp(10px,1vw,20px)}
.bug .model-head{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:clamp(6px,0.6vw,12px)}
.bug .status,.bug .tier,.bug .badge{display:inline-block;border:1px solid var(--border);border-radius:4px;padding:2px 8px;margin:2px;font-size:clamp(10px,0.72vw,13px);background:#f8fafc}
.bug .status.active{color:#047857;background:#ecfdf5}
.bug .status.excluded{color:#b45309;background:#fffbeb}
.bug .notice{margin:10px 0;padding:8px 12px;background:#fffbeb;border-left:3px solid #f59e0b;border-radius:0 var(--radius-sm) var(--radius-sm) 0;font-size:clamp(11px,0.8vw,14px)}
.bug .facts-strip{display:flex;flex-wrap:wrap;gap:8px 12px;margin:10px 0;align-items:center}
.bug .fact-chip{display:inline-flex;align-items:center;gap:6px;background:#f8fafc;border:1px solid var(--border);border-radius:6px;padding:4px 10px;font-size:clamp(11px,0.75vw,13px)}
.bug .fact-chip b{color:var(--muted);font-weight:600}
.bug .obs-box{margin:12px 0;display:flex;flex-direction:column;gap:10px}
.bug .obs-item{background:#f8fafc;border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px 14px}
.bug .obs-header{display:flex;align-items:center;justify-content:space-between;font-size:clamp(11px,0.75vw,13px);color:var(--muted);font-weight:700;margin-bottom:6px;text-transform:uppercase;letter-spacing:0.03em}
.bug .obs-content{white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;background:#ffffff;border:1px solid #e2e8f0;border-radius:4px;padding:8px 12px;margin:0;font-family:"SFMono-Regular",Consolas,monospace;font-size:clamp(11px,0.8vw,13px);line-height:1.55;color:#0f172a;max-height:360px;overflow-y:auto}
.bug details{border:1px solid var(--border);border-radius:var(--radius-sm);padding:8px 12px;margin:8px 0;background:#ffffff}
.bug details[open]{background:#fafbfc}
.bug details summary{cursor:pointer;font-weight:600;font-size:clamp(12px,0.85vw,15px);padding:4px 0;outline:none;user-select:none;color:#1e293b}
.bug details summary:hover{color:#0369a1}
.bug details pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f8fafc;padding:clamp(8px,0.8vw,14px);border-radius:var(--radius-sm);border:1px solid var(--border);max-height:360px;overflow:auto;font-size:clamp(11px,0.78vw,14px);margin-top:6px}
.bug .table-wrap{overflow-x:auto;margin-top:8px;-webkit-overflow-scrolling:touch}
.bug table{width:100%;border-collapse:collapse;font-size:clamp(11px,0.78vw,14px);table-layout:auto;border:1px solid var(--border);border-radius:var(--radius-sm)}
.bug th,.bug td{border:1px solid var(--border);padding:clamp(5px,0.5vw,9px) clamp(6px,0.6vw,12px);text-align:left;vertical-align:top;overflow-wrap:anywhere}
.bug th{background:#f1f5f9;white-space:nowrap;font-size:clamp(9px,0.68vw,12px);color:#475569;text-transform:uppercase;letter-spacing:0.03em}
.bug .muted{color:var(--muted)}
.bug-id.gt-badge{background:#0d9488}
.bug-id.root-badge{background:#0284c7}
.chip-link{display:inline-block;text-decoration:none;padding:2px 8px;margin:2px;border-radius:999px;background:#f1f5f9;color:#0369a1;font-family:"SFMono-Regular",Consolas,monospace;font-size:clamp(10px,0.7vw,12px);font-weight:600;border:1px solid #cbd5e1;transition:all 0.2s}
.chip-link:hover{background:#0284c7;color:#fff;border-color:#0284c7}
.gt-loc-box{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:6px;padding:8px 12px;margin:10px 0;font-size:clamp(11px,0.8vw,13px);color:#166534}
.gt-loc-box code{font-family:"SFMono-Regular",Consolas,monospace;font-weight:700;background:#dcfce7;padding:2px 6px;border-radius:4px;color:#15803d}
.test-outcome-passed{color:#15803d;font-weight:700}
.test-outcome-failed{color:#b91c1c;font-weight:700}
@media(max-width:700px){.bug .model-head{flex-direction:column;align-items:flex-start}}
"""


def _esc(value: object) -> str:
    return html.escape(str(value if value not in (None, "") else "n/a"), quote=True)


def _short_path(value: object) -> str:
    path = str(value or "")
    if not path:
        return "n/a"
    parts = path.replace("\\", "/").split("/")
    return "/".join(parts[-3:]) if len(parts) > 3 else path


def _badges(values: Iterable[object], empty: str = "n/a") -> str:
    items = [str(value) for value in values if value not in (None, "")]
    if not items:
        return f"<span class='muted'>{_esc(empty)}</span>"
    return "".join(f"<span class='badge'>{_esc(value)}</span>" for value in items)


def _rtl_rows(
    regions: List[Dict[str, object]],
    base_dirs: Optional[List[Path]] = None,
    registry: Optional[SourceRegistry] = None,
) -> str:
    rows = []
    seen = set()
    for region in regions:
        key = (region.get("path"), region.get("line_start"), region.get("line_end"))
        if key in seen:
            continue
        seen.add(key)
        path_val = str(region.get("path") or "")
        ls = region.get("line_start")
        le = region.get("line_end")
        location = f"{_short_path(path_val)}:{ls}-{le}"
        loc_html = code_snippet_html(location, path_val, ls, le, base_dirs=base_dirs, registry=registry)
        sha = str(region.get("sha256") or "")
        rows.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td title='{}'>{}</td></tr>".format(
                loc_html, _esc(region.get("reason")), _esc(region.get("evidence")),
                _esc(region.get("validation_status")), _esc(sha), _esc(sha[:12] if sha else "n/a")
            )
        )
    return "".join(rows)


def _test_rows(
    tests: List[Dict[str, object]],
    lang: str,
    base_dirs: Optional[List[Path]] = None,
    registry: Optional[SourceRegistry] = None,
) -> str:
    role_labels = {
        "bug_specific": "Bug 专属" if lang == "zh" else "Bug-specific",
        "supporting_infrastructure": "基础设施支持" if lang == "zh" else "Infrastructure support",
    }
    rows = []
    for test in tests:
        sf = str(test.get("source_file") or "")
        lines = test.get("source_lines", [None, None])
        location = f"{_short_path(sf)}:{lines[0]}-{lines[1]}"
        loc_html = code_snippet_html(location, sf, lines[0], lines[1], base_dirs=base_dirs, registry=registry)
        phases = ", ".join(
            f"{item.get('name')}={item.get('outcome')}"
            for item in test.get("phases", [])
            if isinstance(item, dict)
        )
        outcome_val = str(test.get("outcome") or "n/a")
        outcome_cls = "test-outcome-passed" if outcome_val.lower() == "passed" else ("test-outcome-failed" if outcome_val.lower() == "failed" else "")
        outcome_html = f"<span class='{outcome_cls}'>{_esc(outcome_val)}</span>"
        rows.append(
            "<tr><td title='{node}'><b>{node_short}</b></td><td>{role}</td><td>{outcome}</td>"
            "<td>{duration}</td><td>{location}</td><td>{phases}</td></tr>".format(
                node=_esc(test.get("nodeid")),
                node_short=_esc(str(test.get("nodeid") or "n/a").split("/")[-1]),
                role=_esc(role_labels.get(test.get("test_role"), test.get("test_role"))),
                outcome=outcome_html,
                duration=_esc(test.get("duration_seconds")),
                location=loc_html,
                phases=_esc(phases),
            )
        )
    return "".join(rows)


def _spec_rows(
    specs: List[Dict[str, object]],
    base_dirs: Optional[List[Path]] = None,
    registry: Optional[SourceRegistry] = None,
) -> str:
    rows = []
    for spec in specs:
        sp_path = str(spec.get("source_path") or "")
        ls = spec.get("line_start")
        le = spec.get("line_end")
        location = f"{_short_path(sp_path)}:{ls}-{le}"
        loc_html = code_snippet_html(location, sp_path, ls, le, base_dirs=base_dirs, registry=registry)
        rows.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                _esc(spec.get("property_id")),
                loc_html,
                _esc(spec.get("property_text")),
                _esc(spec.get("match_reason")),
            )
        )
    return "".join(rows)




def _quality_rows(quality: Dict[str, object], lang: str) -> str:
    if not isinstance(quality, dict):
        return "<tr><td colspan='2'>n/a</td></tr>"
    rows = []
    for key in (
        "execution_support",
        "oracle_quality",
        "qualification",
        "report_consistency",
        "rtl_traceability",
        "semantic_completeness",
        "spec_traceability",
    ):
        rows.append(
            "<tr><td><b>{}</b></td><td><code>{}</code></td></tr>".format(_esc(key), _esc(quality.get(key)))
        )
    return "".join(rows)


def _diagnostic_rows(diagnostics: List[Dict[str, object]]) -> str:
    rows = []
    for item in diagnostics:
        rows.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                _esc(item.get("code")),
                _esc(item.get("severity")),
                _esc(item.get("entity_id")),
                _esc(item.get("message")),
            )
        )
    return "".join(rows) or "<tr><td colspan='4'>n/a</td></tr>"


def _record_section(
    record: Dict[str, object],
    lang: str,
    base_dirs: Optional[List[Path]] = None,
    registry: Optional[SourceRegistry] = None,
) -> str:
    zh = lang == "zh"
    disposition = record.get("candidate_disposition", "active")
    disposition_label = {
        "active": "有效候选" if zh else "Active candidate",
        "excluded_declared_candidate": "原声明排除" if zh else "Excluded by declaration",
    }.get(disposition, str(disposition))
    disposition_class = "excluded" if disposition == "excluded_declared_candidate" else "active"
    dimensions = [key for key, enabled in record.get("evidence_dimensions", {}).items() if enabled]
    replay = [item.get("status") for item in record.get("replay_results", []) if isinstance(item, dict)]
    tests = [item for item in record.get("tests", []) if isinstance(item, dict)]

    # Multi-level root cause retrieval
    root_causes = [str(v) for v in (record.get("reported_root_causes") or []) if v not in (None, "", "n/a")]
    if not root_causes and record.get("root_cause") not in (None, "", "n/a"):
        root_causes.append(str(record.get("root_cause")))
    if not root_causes:
        for cs in record.get("claim_sources", []):
            if isinstance(cs, dict):
                if cs.get("summary") and str(cs["summary"]) not in root_causes:
                    root_causes.append(f"[模型报告摘要]: {cs['summary']}")
                if cs.get("root_cause") and str(cs["root_cause"]) not in root_causes:
                    root_causes.append(f"[根因分析]: {cs['root_cause']}")

    root_html = "".join(f"<pre>{_esc(value)}</pre>" for value in root_causes) if root_causes else "<span class='muted'>n/a</span>"
    quality = record.get("evidence_quality", {})
    diagnostics = [item for item in record.get("diagnostics", []) if isinstance(item, dict)]
    exclusion_html = ""
    if record.get("candidate_exclusions"):
        exclusion_html = (
            "<div class='notice'><b>{}</b> {}</div>".format(
                "排除理由：" if zh else "Exclusion reasons:",
                _esc(", ".join(record.get("exclusion_reason_codes", []))),
            )
        )

    expected_val = record.get("expected")
    observed_val = record.get("observed")
    trigger_val = record.get("trigger")

    obs_html = ""
    if any(v not in (None, "", "n/a") for v in (expected_val, observed_val)):
        obs_html = """
        <div class="obs-box">
          <div class="obs-item">
            <div class="obs-header"><b>{expected_label}</b></div>
            <pre class="obs-content">{expected}</pre>
          </div>
          <div class="obs-item">
            <div class="obs-header"><b>{observed_label}</b></div>
            <pre class="obs-content">{observed}</pre>
          </div>
        </div>
        """.format(
            expected_label="预期 (Expected)" if zh else "Expected",
            expected=_esc(expected_val) if expected_val not in (None, "", "n/a") else "<span class='muted'>n/a</span>",
            observed_label="观察 (Observed)" if zh else "Observed",
            observed=_esc(observed_val) if observed_val not in (None, "", "n/a") else "<span class='muted'>n/a</span>",
        )

    facts_strip_html = """
    <div class="facts-strip">
      <div class="fact-item"><span class="fact-label">{tier_label}</span><span class="fact-val tier-{tier_cls}">{tier}</span></div>
      <div class="fact-item"><span class="fact-label">{score_label}</span><span class="fact-val">{score}</span></div>
      <div class="fact-item"><span class="fact-label">{dims_label}</span><span class="fact-val">{dims}</span></div>
      <div class="fact-item"><span class="fact-label">{replay_label}</span><span class="fact-val">{replay}</span></div>
      <div class="fact-item"><span class="fact-label">{trigger_label}</span><span class="fact-val">{trigger}</span></div>
    </div>
    """.format(
        tier_label="证据层级" if zh else "Tier",
        tier_cls=str(record.get("evidence_tier", "")).lower(),
        tier=_esc(record.get("evidence_tier")),
        score_label="证据质量分" if zh else "Quality score",
        score=_esc(record.get("evidence_score")),
        dims_label="证据维度" if zh else "Dimensions",
        dims=_badges(dimensions) or "<span class='muted'>n/a</span>",
        replay_label="重放验证" if zh else "Replay status",
        replay=_badges(replay) or "<span class='muted'>n/a</span>",
        trigger_label="触发条件" if zh else "Trigger",
        trigger=_esc(trigger_val) if trigger_val not in (None, "", "n/a") else "<span class='muted'>n/a</span>",
    )

    return """
      <section class="model-block">
        <div class="model-header">
          <h3>{model}</h3>
          <span class="status-badge {disposition_class}">{disposition}</span>
        </div>
        {exclusion_html}
        {facts_strip}
        {obs_html}
        <details {root_open}><summary>{root_label}</summary>{root_html}</details>
        <details><summary>{quality_label}</summary>
          <div class="table-wrap"><table><thead><tr><th>{quality_key}</th><th>{quality_value}</th></tr></thead>
          <tbody>{quality_rows}</tbody></table></div>
        </details>
        <details {diag_open}><summary>{diagnostics_label} ({diagnostics_count})</summary>
          <div class="table-wrap"><table><thead><tr><th>{diag_code}</th><th>{diag_severity}</th><th>{diag_entity}</th><th>{diag_message}</th></tr></thead>
          <tbody>{diagnostics_rows}</tbody></table></div>
        </details>
        <details open><summary>{oracle_label} ({bug_tests}/{all_tests})</summary>
          <div class="table-wrap"><table><thead><tr><th>Node</th><th>{role_label}</th><th>{outcome_label}</th><th>{duration_label}</th><th>{source_label} (悬停预览/点击查看)</th><th>Phases</th></tr></thead>
          <tbody>{test_rows}</tbody></table></div>
        </details>
        <details><summary>Spec ({spec_count})</summary>
          <div class="table-wrap"><table><thead><tr><th>{property_label}</th><th>{source_label} (悬停预览/点击查看)</th><th>Text</th><th>{reason_label}</th></tr></thead>
          <tbody>{spec_rows}</tbody></table></div>
        </details>
        <details><summary>RTL ({rtl_count})</summary>
          <div class="table-wrap"><table><thead><tr><th>{source_label} (悬停预览/点击查看)</th><th>{reason_label}</th><th>{evidence_label}</th><th>Source validation</th><th>SHA-256</th></tr></thead>
          <tbody>{rtl_rows}</tbody></table></div>
        </details>
      </section>
    """.format(
        model=_esc(record.get("model")), disposition_class=disposition_class,
        disposition=_esc(disposition_label),
        exclusion_html=exclusion_html,
        facts_strip=facts_strip_html,
        obs_html=obs_html,
        root_label="根因声明 / 报告溯源" if zh else "Reported root cause & trace",
        root_open="open" if root_causes else "",
        root_html=root_html,
        quality_label="证据质量" if zh else "Evidence Quality",
        quality_key="字段" if zh else "Field",
        quality_value="值" if zh else "Value",
        quality_rows=_quality_rows(quality, lang) or "<tr><td colspan='2'>n/a</td></tr>",
        diagnostics_label="结构化诊断" if zh else "Diagnostics",
        diagnostics_count=len(diagnostics),
        diag_open="open" if len(diagnostics) > 0 else "",
        diagnostics_rows=_diagnostic_rows(diagnostics),
        diag_code="诊断码" if zh else "Code",
        diag_severity="级别" if zh else "Severity",
        diag_entity="对象" if zh else "Entity",
        diag_message="说明" if zh else "Message",
        oracle_label="测试与 Oracle" if zh else "Tests and Oracle",
        bug_tests=len(record.get("bug_specific_tests", [])), all_tests=len(tests),
        role_label="角色" if zh else "Role", outcome_label="结果" if zh else "Outcome",
        duration_label="耗时(s)" if zh else "Duration(s)", source_label="来源" if zh else "Source",
        test_rows=_test_rows(tests, lang, base_dirs=base_dirs, registry=registry) or "<tr><td colspan='6'>n/a</td></tr>",
        spec_count=len(record.get("spec_matches", [])), property_label="属性" if zh else "Property",
        reason_label="理由" if zh else "Reason",
        evidence_label="证据" if zh else "Evidence",
        spec_rows=_spec_rows(record.get("spec_matches", []), base_dirs=base_dirs, registry=registry) or "<tr><td colspan='4'>n/a</td></tr>",
        rtl_count=len(record.get("rtl_regions", [])),
        rtl_rows=_rtl_rows(record.get("rtl_regions", []), base_dirs=base_dirs, registry=registry) or "<tr><td colspan='5'>n/a</td></tr>",
    )


def bug_evidence_details_html(
    data: Dict[str, object],
    lang: str = "zh",
    base_dirs: Optional[List[Path]] = None,
) -> str:
    zh = lang == "zh"
    records_by_bug = defaultdict(list)
    for record in data.get("benchmark_records", []):
        if isinstance(record, dict) and record.get("status") == "found":
            records_by_bug[record.get("canonical_bug")].append(record)
    matrix_by_bug = {
        row.get("canonical_bug"): row
        for row in data.get("matrix", [])
        if isinstance(row, dict)
    }

    # Map symptoms to GT defect
    gt_source = data.get("ground_truth_rtl_defects", {})
    if isinstance(gt_source, dict):
        gt_defects = gt_source.get("defects", [])
    elif isinstance(gt_source, list):
        gt_defects = gt_source
    else:
        gt_defects = []

    symptom_to_gt = {}
    for defect in gt_defects:
        if isinstance(defect, dict):
            gt_id = str(defect.get("gt_id", ""))
            for s in defect.get("symptoms", []) or []:
                symptom_to_gt[str(s)] = gt_id

    registry = SourceRegistry(base_dirs=base_dirs)
    sections = []
    for bug_id in sorted(records_by_bug):
        row = matrix_by_bug.get(bug_id, {})
        models = "".join(_record_section(record, lang, base_dirs=base_dirs, registry=registry) for record in records_by_bug[bug_id])
        prop_text = row.get("property_text")
        prop_display = prop_text if prop_text not in (None, "", "n/a") else ("现象级 Bug 证据" if zh else "Symptom Bug Evidence")
        gt_ref = symptom_to_gt.get(str(bug_id))
        gt_link = (
            f"<a class='chip-link' href='gt_defect_details.html#{_esc(gt_ref)}' "
            f"title='跳转到 {gt_ref} 缺陷详情'>{'所属 GT 缺陷' if zh else 'GT Defect'}: {_esc(gt_ref)}</a>"
            if gt_ref else ""
        )

        sections.append(
            "<section class='section bug' id='{anchor}'><div class='section-header'>"
            "<div><span class='bug-id'>{bug}</span>{gt_link}<h2>{property}</h2><p>{signals}</p></div>"
            "</div>{models}</section>".format(
                anchor=_esc(bug_id), bug=_esc(bug_id), gt_link=gt_link,
                property=_esc(prop_display),
                signals=_badges(row.get("signals", [])), models=models,
            )
        )
    exclusion_rows = []
    for item in data.get("candidate_exclusions", []):
        sources = []
        for claim in item.get("claims", []):
            source = claim.get("source", {})
            sources.append(
                f"{_short_path(source.get('path'))}:{source.get('line_start')}-{source.get('line_end')}"
            )
        exclusion_rows.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                _esc(item.get("canonical_bug")), _esc(item.get("model")),
                _esc(", ".join(item.get("candidate_ids", []))),
                _esc(", ".join(item.get("reason_codes", []))),
                _esc("; ".join(sources)),
            )
        )
    exclusions_section = ""
    if exclusion_rows:
        exclusions_section = """
        <section class="section bug" id="explicit-exclusions"><div class="section-header">
        <div><span class="bug-id">{count}</span><h2>{heading}</h2><p>{description}</p></div></div>
        <div class="audit-wrap audit-wrap-full"><table class="audit-table review-table"><thead><tr><th>Bug</th><th>Model</th><th>Candidate</th><th>{reason}</th><th>{source}</th></tr></thead>
        <tbody>{rows}</tbody></table></div></section>
        """.format(
            count=len(exclusion_rows),
            heading="显式排除记录" if zh else "Explicit Candidate Exclusions",
            description=("这些声明保留完整追溯信息，但不进入有效 Bug 数和模型得分。" if zh else
                         "These declarations remain traceable but do not count as effective bugs or model score."),
            reason="理由" if zh else "Reason", source="来源" if zh else "Source",
            rows="".join(exclusion_rows),
    )
    title = "现象级 Bug 证据详情" if zh else "Symptom Bug Evidence Details"
    desc = "逐 Bug 展示模型声明、根因、Oracle、测试分类、Spec、RTL 与 replay 证据。测试总数保留不变，基础设施测试不再伪装成 Bug 专属证据。" if zh else "Per-bug model claims, root cause, oracle, classified tests, spec, RTL, and replay evidence. Infrastructure tests remain traceable without being presented as bug-specific evidence. Source evidence is preserved verbatim and may remain in its original language."

    body = "".join(sections) + exclusions_section
    return """<!DOCTYPE html>
<html lang="{html_lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>{css}</style>
</head>
<body>
  <div class="page">
    <div class="top-nav">
      <div style="display:flex; gap:10px; align-items:center;">
        <a class="back-link" href="index.html">{back_text}</a>
        <a class="mini-link" href="gt_defect_details.html">{gt_nav_text}</a>
      </div>
      <div class="meta-text">{meta_text}</div>
    </div>
    <section class="hero">
      <h1>{title}</h1>
      <p>{desc}</p>
    </section>
    {body}
  </div>
  {modal_js}
</body>
</html>""".format(
        html_lang="zh-CN" if zh else "en",
        title=html.escape(title),
        desc=html.escape(desc),
        back_text="返回 BugReview 主报告" if zh else "Back to BugReview",
        gt_nav_text="查看最终确认独立 RTL 缺陷" if zh else "View Finalized Independent RTL Defects",
        meta_text="现象级 Bug 证据详情" if zh else "Symptom Bug Evidence Details",
        css=_html_benchmark_page_css(audit_full=True) + _BUG_DETAIL_EXTRA_CSS + _GT_DETAIL_EXTRA_CSS,
        body=body,
        modal_js=_build_modal_html_and_js(registry),
    )



def candidate_exclusions_markdown(data: Dict[str, object]) -> str:
    lines = [
        "# Explicit Candidate Exclusions",
        "",
        "These entries remain traceable but are explicitly marked as excluded by the source declaration.",
        "",
        "| Canonical bug | DUT | Model | Candidate | Reasons | Source |",
        "|---|---|---|---|---|---|",
    ]
    for item in data.get("candidate_exclusions", []):
        claim_sources = []
        for claim in item.get("claims", []):
            source = claim.get("source", {})
            claim_sources.append(
                f"{source.get('path') or 'n/a'}:{source.get('line_start') or 'n/a'}-{source.get('line_end') or 'n/a'}"
            )
        lines.append(
            "| `{}` | `{}` | `{}` | `{}` | {} | {} |".format(
                item.get("canonical_bug") or "n/a",
                item.get("dut") or "n/a",
                item.get("model") or "n/a",
                ", ".join(item.get("candidate_ids", [])) or "n/a",
                ", ".join(item.get("reason_codes", [])) or "n/a",
                "<br>".join(claim_sources) or "n/a",
            )
        )
    if not data.get("candidate_exclusions"):
        lines.append("| n/a | n/a | n/a | n/a | n/a | n/a |")
    return "\n".join(lines) + "\n"
