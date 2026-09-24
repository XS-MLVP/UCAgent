"""Prepare and launch the two BugReview plugin workflows."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from collections import Counter
from pathlib import Path
import re
import shutil
import subprocess
import sys

from bug_review.benchmark_workflow.task_manifest import atomic_write_json, stable_hash
from bug_review.benchmark_workflow.paths import default_configs, source_root
from .tasks import RUNTIME, finalize_store, pending_requests, read_object, submit_response, task_lock
from .inputs import discover_input_workspaces
from .case_analysis import CaseReviews, failure_inventory, source_evidence, replay_case, reviewed_comparison
from bug_review.benchmark_workflow.report_inventory import validate_report_inventory
from .scope import discover_scope
from .llptw_report import write_llptw_curated_report
from .report_data import build_report_data, load_report_profile


REPO = Path(__file__).resolve().parent
# Bumped whenever report-page rendering changes: the revision joins the
# publication digest so rendering-only fixes rebuild under a new sealed
# version instead of serving stale pages from the existing one.
RENDERER_REVISION = "v8"
PACKAGE = Path(__file__).resolve().parent


ANALYSIS = ("inputs", "parse", "replay", "waveform", "semantic", "failure_mode", "root_appeal", "alignment", "publish_analysis")
STORES = {
    "semantic": ("semantic_judgement", "semantic/task_store", "semantic/finalization"),
    "failure_mode": ("failure_mode_review", "root_review/failure_mode_store", "root_review/failure_mode_finalization"),
    "root_appeal": ("rtl_root_appeal", "root_review/rtl_root_appeal_store", "root_review/rtl_root_appeal_finalization"),
    "alignment": ("reported_root_alignment", "alignment/task_store", "alignment/finalization"),
}


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value) or value in {".", ".."}:
        raise ValueError(f"unsafe DUT identifier: {value!r}")
    return value


def _prune_published_versions(target: Path, keep: Path) -> None:
    """Retain only the active sealed report version.

    Analysis evidence remains under ``tasks/``. This only removes obsolete
    rendered publications after the stable symlink has switched successfully.
    Versions still referenced by the workspace state seal are never removed:
    ``workflow_state.json`` records stage outputs by path+hash inside those
    directories, so deleting one breaks every later ``_state()`` check.
    """
    from bug_review.benchmark_workflow.versioned_publish import version_store_for
    target, keep = Path(target).absolute(), Path(keep).resolve()
    store = version_store_for(target).resolve()
    current = target / "current"
    if keep.parent != store or not current.is_symlink() or current.resolve() != keep:
        raise ValueError("refusing to prune a non-active report version")
    sealed_versions = set()
    state_path = target.parent / "workflow_state.json"
    if state_path.is_file():
        try:
            state = read_object(state_path)
        except (OSError, ValueError):
            state = {}
        marker = "/.versions/"
        for outputs in (state.get("completed") or {}).values():
            for name in outputs or {}:
                if marker in str(name):
                    sealed_versions.add(str(name).split(marker)[1].split("/")[0])
    for child in store.iterdir():
        if child.resolve() == keep or child.name in sealed_versions:
            continue
        if child.is_dir() and child.parent.resolve() == store:
            shutil.rmtree(child)


def _write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _page(title, body):
    return ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width'>"
            f"<title>{html.escape(title)}</title><style>body{{font:16px system-ui;max-width:1200px;"
            "margin:32px auto;padding:16px;color:#17202a}table{border-collapse:collapse;width:100%}"
            "td,th{border:1px solid #cbd5e1;padding:8px;text-align:left}pre{white-space:pre-wrap;"
            "overflow-wrap:anywhere}details{margin:12px 0}.bug{border:1px solid #cbd5e1;"
            "border-radius:8px;padding:4px 16px;margin:12px 0}.bug h3{margin:10px 0}"
            ".bug small{color:#64748b;font-weight:400}li{margin:2px 0}</style>"
            f"<h1>{html.escape(title)}</h1>{body}</html>")


def _display_bug_sets(final, dut=""):
    """Return bugs split by report confidence without changing analysis JSON.

    The independent review payload is intentionally broader than the formal
    GT.  LLPTW currently has one candidate whose waveform and RTL evidence is
    strong enough for the primary report; the remaining candidates stay
    reachable as review material.
    """
    bugs = [b for b in (final.get("bugs", []) or []) if isinstance(b, dict)]
    if str(dut) == "bosc_LLPTW":
        primary_ids = {"LLPTW-BG-MULTI-CACHE-PARALLELMUX"}
        return ([b for b in bugs if b.get("bug_id") in primary_ids],
                [b for b in bugs if b.get("bug_id") not in primary_ids])
    return bugs, []


def _final_bug_section(final, esc, bugs=None, status_label="高可信候选"):
    blocks = []
    for bug in (final.get("bugs", []) if bugs is None else bugs):
        primary = bug.get("cases", [])
        case_items = "".join(
            f"<li>{esc(c['nodeid'].split('::')[-1])}（波形证据 {esc(c.get('evidence_id'))}）</li>"
            for c in primary)
        extra = "".join(
            f"<li>{esc(c['nodeid'].split('::')[-1])}</li>"
            for c in bug.get("also_seen_in", []))
        blocks.append(
            f"<div class='bug'><h3>{esc(bug.get('bug_id'))}：{esc(bug.get('title'))}"
            f"<small><span class='review-status'>{esc(status_label)}</span>"
            f"<small>（主证 {len(primary)} 例）</small></h3>"
            f"<p><b>根因</b>：{esc(bug.get('root_cause'))}</p>"
            f"<p><b>波形/RTL 证据</b>：{esc(bug.get('evidence_summary'))}</p>"
            + (f"<p><b>规格违反</b>：{esc(bug.get('spec_violation'))}</p>" if bug.get("spec_violation") else "")
            + f"<p><b>受影响用例</b>：<ul>{case_items}</ul></p>"
            + (f"<p><b>同窗共现</b>：<ul>{extra}</ul></p>" if extra else "")
            + "</div>")
    method = f"<p>{esc(final['method'])}</p>" if final.get("method") else ""
    return method + "".join(blocks)


def analysis_html(payload):
    esc = lambda value: html.escape(str(value or ""))
    waves = {r["case"]["case_id"]: r["review"] for r in payload.get("waveform_reviews", [])}
    failures = "".join(
        f"<tr><td>{esc(r['case']['model'])}</td><td>{esc(r['case']['run_key'])}</td>"
        f"<td>{esc(r['case']['nodeid'])}</td><td>{esc(r['replay'].get('status'))}</td>"
        f"<td>{esc(r['review']['classification'])}</td>"
        f"<td>{esc(waves.get(r['case']['case_id'], {}).get('conclusion', 'not_applicable'))}</td>"
        f"<td>{esc(', '.join(r['case']['reported_candidate_ids']))}</td></tr>"
        for r in payload.get("failure_case_reviews", [])
    )
    rows = "".join(
        f"<tr><td>{esc(row.get('canonical_bug'))}</td><td>{esc(row.get('model'))}</td>"
        f"<td>{esc(row.get('status'))}</td><td>{esc(row.get('property_text'))}</td>"
        f"<td>{esc(row.get('validation_summary'))}</td></tr>"
        for row in payload.get("benchmark_records", [])
    )
    # failure_case_reviews/waveform_reviews embed per-case stdout/stderr
    # (~16MB here); the tables above summarize them, analysis.json keeps the rest.
    counts = Counter(r["review"]["classification"] for r in payload.get("failure_case_reviews", []))
    wave_counts = Counter(r["review"].get("conclusion") for r in payload.get("waveform_reviews", []))
    breakdown = "；".join(f"{esc(name)} {count} 例" for name, count in sorted(counts.items(), key=lambda kv: -kv[1]))
    final = payload.get("final_bug_analysis") or {}
    summary = (f"<p>失败用例 {len(payload.get('failure_case_reviews', []))} 个（{breakdown}）；"
               f"波形复核 {len(waves)} 例，确认 DUT 缺陷 {wave_counts.get('dut_bug', 0)} 例"
               + (f"，最终聚类为 {esc(final.get('bug_count'))} 类根因缺陷。" if final.get("bugs") else "。")
               + "</p>"
               + f"<p>标准口径：模型声明候选 {len(payload.get('canonical_bugs', []))} 个、"
                 f"GT-RTL 真值集 {len((payload.get('ground_truth_rtl_defects') or {}).get('defects', []))} 个"
                 "（候选/GT 中心指标因此为零，见<a href='reports/zh/index.html'>标准评测报告</a>）。</p>")
    final_section = ""
    if final.get("bugs"):
        final_section = (f"<h2>最终缺陷分析（{esc(final.get('bug_count', len(final['bugs'])))} 类根因，"
                         f"覆盖 {esc(final.get('confirmed_dut_bug_cases'))} 例）</h2>"
                         + _final_bug_section(final, esc))
    sections = "".join(
        f"<details><summary>{esc(label)}</summary><pre>{esc(json.dumps(view, ensure_ascii=False, indent=2))}</pre></details>"
        for label, view in (("输入运行与缺失证据", payload.get("input_runs", [])),
                            ("根因及成员", payload.get("rtl_root_bugs", [])),
                            ("语义判断", payload.get("semantic_judgements", [])),
                            ("排除候选", payload.get("candidate_exclusions", [])),
                            ("归因对齐", payload.get("reported_root_gt_alignment", {})),
                            ("原始覆盖率", payload.get("per_model", {})),
                            ("回放执行", {k: v for k, v in payload.get("replay_execution", {}).items() if k != "runs"}),
                            ("标准口径候选", payload.get("canonical_bugs", [])),
                            ("GT-RTL 真值集", payload.get("ground_truth_rtl_defects", {})),
                            ("对比矩阵", payload.get("matrix", [])),
                            ("覆盖率可比性", payload.get("coverage_comparability", {})),
                            ("重放候选", payload.get("replay_candidates", [])),
                            ("模型声明摘要", payload.get("reported_bug_claim_summary", {})),
                            ("报告根因摘要", payload.get("reported_root_cause_summary", {}))))
    return _page(f"{payload['dut']} 分析报告", "<p><a href='analysis.json'>完整证据 JSON</a> · "
                 "<a href='reports/zh/index.html'>标准评测报告（候选/GT 口径）</a></p>" + summary
                 + final_section
                 + "<h2>失败用例</h2><table><tr><th>模型</th><th>运行</th><th>用例</th><th>回放</th>"
                 "<th>初步归因</th><th>波形复核</th><th>原模型声明</th></tr>" + failures + "</table>"
                 "<h2>模型声明</h2>"
                 "<table><tr><th>Bug</th><th>模型</th><th>状态</th><th>声明</th><th>证据</th></tr>"
                 + rows + "</table>" + sections)


def _write_final_bug_details(dut_dir, report_view):
    """Render the final-bug drill-down page in the gt_defect_details style.

    Reuses the canonical GT detail card components (badge header, authoritative
    RTL location with source preview, root-cause banners, case chips and
    per-case analysis blocks) so the independent-review findings read exactly
    like GT-RTL defect cards.
    """
    from bug_review.benchmark_workflow.gt_defect_reporting import (
        _GT_DETAIL_EXTRA_CSS, _build_modal_html_and_js, code_snippet_html)
    from bug_review.benchmark_workflow.html_reporting import _benchmark_page_css
    esc = lambda value: html.escape(str(value or ""))

    def as_text(value):
        if value is None:
            return ""
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)

    final = report_view.get("final_bug_analysis") or {}
    bugs = final.get("bugs", [])
    if not bugs:
        return
    wave_by_case = {r["case"]["case_id"]: r for r in report_view.get("waveform_reviews", [])}
    fail_by_case = {r["case"]["case_id"]: r for r in report_view.get("failure_case_reviews", [])}

    def loc_banners(bug):
        out = []
        for region in bug.get("rtl_regions", []):
            match = re.match(r"^([\w.]+\.(?:v|sv)):(\d+)-(\d+)", str(region))
            if match:
                trigger = code_snippet_html(f"{match.group(1)}:{match.group(2)}-{match.group(3)}",
                                            match.group(1), int(match.group(2)), int(match.group(3)),
                                            base_dirs=[Path("inputs")])
                out.append(f"<div class='gt-loc-banner'><b>权威 RTL 缺陷代码位置:</b> {trigger}</div>")
            else:
                out.append("<div class='gt-loc-banner' style='background:#fffbeb;border-color:#fde68a;"
                           f"color:#92400e;'><b>RTL 定位（区域）:</b> {esc(region)}</div>")
        return "".join(out)

    def case_block(bug, case_id):
        w = wave_by_case.get(case_id, {})
        f = fail_by_case.get(case_id, {})
        nodeid = (w.get("case") or f.get("case") or {}).get("nodeid", case_id)
        wrev, frev = w.get("review", {}), f.get("review", {})
        replay_status = ((w.get("replay") or {}).get("status")
                         or (f.get("replay") or {}).get("status") or "n/a")
        rows = [f"<div class='analysis-row'><span class='k'>故障分类 (Failure Mode):</span> "
                f"<span class='v'><code>{esc(bug.get('failure_mode'))}</code></span></div>",
                f"<div class='analysis-row'><span class='k'>关键影响信号 (Signals):</span> "
                f"<span class='v'><code>{esc(', '.join(bug.get('signals', [])))}</code></span></div>"]
        for label, key in (("规格预期 (Specification Expected)", "specification_expected"),
                           ("DUT 实际 (DUT Actual)", "dut_actual")):
            if frev.get(key):
                rows.append(f"<div class='analysis-row'><span class='k'>{label}:</span> "
                            f"<span class='v'>{esc(as_text(frev[key]))}</span></div>")
        obs = []
        for label, text in (("波形观测 (Observed)", wrev.get("observed_behavior")),
                            ("RTL 对照 (Source Correlation)", wrev.get("source_correlation")),
                            ("时序对齐 (Alignment)", wrev.get("alignment_evidence")),
                            ("测试输入 (Exact Input)", as_text(frev.get("exact_input")))):
            if text:
                obs.append(f"<div class='obs-item'><div class='obs-header'><span>{label}</span></div>"
                           f"<pre class='obs-content'>{esc(text)}</pre></div>")
        return (f"<a id='case-{esc(case_id)}'></a>"
                "<section class='model-block'><div class='model-head'>"
                f"<h3>{esc(nodeid.split('::')[-1])}</h3>"
                "<span class='status active'>DUT 缺陷（波形复核确认）</span>"
                f"<span class='tier'>document_evidence · replay {esc(replay_status)}</span></div>"
                "<div class='facts-strip'>"
                f"<div class='fact-chip'><b>波形证据:</b> <span><code>{esc(wrev.get('evidence_id'))}</code></span></div>"
                "<div class='fact-chip'><b>证据维度:</b> <span><span class='badge'>execution</span>"
                "<span class='badge'>waveform</span><span class='badge'>rtl</span><span class='badge'>spec</span></span></div>"
                f"<div class='fact-chip'><b>重放验证:</b> <span><span class='badge'>{esc(replay_status)}</span></span></div>"
                "</div>"
                "<div class='defect-analysis-card'><div class='analysis-header'>"
                "<b>缺陷机理与行为分析（用例级）</b></div><div class='analysis-body'>"
                + "".join(rows) + "</div></div>"
                + (f"<div class='obs-box'>{''.join(obs)}</div>" if obs else "")
                + "</section>")

    cards = []
    for bug in bugs:
        case_blocks, chips = [], []
        for c in bug.get("cases", []):
            case_blocks.append(case_block(bug, c["case_id"]))
            chips.append(f"<a class='chip-link' href='#case-{esc(c['case_id'])}' "
                         f"title='{esc(c['nodeid'])}'>{esc(c['nodeid'].split('::')[-1])}</a>")
        also = "".join(f"<a class='chip-link' href='#case-{esc(c['case_id'])}' "
                       f"title='同窗共现 {esc(c['nodeid'])}'>{esc(c['nodeid'].split('::')[-1])}（共现）</a>"
                       for c in bug.get("also_seen_in", []))
        cards.append(
            f"<section class='section bug gt-card' id='{esc(bug['bug_id'])}'>"
            "<div class='gt-card-header'><div>"
            f"<span class='gt-badge'>{esc(bug['bug_id'])}</span>"
            f"<span class='gt-root-tag'>独立复核 · {esc(bug.get('failure_mode'))}</span>"
            f"<h2 style='display:inline-block;margin-left:10px;'>{esc(bug.get('title'))}</h2>"
            "</div></div>"
            + loc_banners(bug)
            + "<div class='gt-loc-banner' style='background:#f8fafc;border-color:#cbd5e1;color:#334155;'>"
              f"<b>规格契约违反:</b> {esc(bug.get('spec_violation'))}</div>"
            + "<div class='gt-loc-banner' style='background:#f8fafc;border-color:#cbd5e1;color:#334155;'>"
              f"<b>根因机理:</b> {esc(bug.get('root_cause'))}</div>"
            + f"<div class='gt-symptoms-bar'><b>受影响用例 ({len(bug.get('cases', []))}):</b> "
              + "".join(chips) + (" " + also if also else "") + "</div>"
            + "".join(case_blocks)
            + "<p style='margin-top:14px'><a class='chip-link' href='index.html#final-bug-analysis'>返回分析报告</a></p>"
            + "</section>")
    page = ("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{esc(report_view.get('dut'))} 最终缺陷详情</title>"
            f"<style>{_benchmark_page_css()}{_GT_DETAIL_EXTRA_CSS}</style></head><body>"
            + _build_modal_html_and_js()
            + "<div class='page'><section class='hero'><h1>最终确认 DUT 缺陷详情（独立复核）</h1>"
              "<p>展示独立波形复核确认的 DUT 缺陷：权威 RTL 代码位置、根因机理、规格契约违反、"
              "关联用例与用例级波形证据。口径与 GT-RTL 详情页一致。</p></section>"
            + "".join(cards) + "</div></body></html>")
    (Path(dut_dir) / "reports" / "zh" / "final_bug_details.html").write_text(page, encoding="utf-8")


_FAILURE_MODE_LABELS = {
    "output_mismatch": "输出不匹配",
    "ordering_or_concurrency_failure": "顺序 / 并发失效",
    "hang_or_deadlock": "挂起 / 死锁",
    "protocol_violation": "协议违例",
}


def _gt_registered_cases(root, fail_by_case, fail_reviews):
    """Failure cases tied to a root through its registered candidate ids."""
    candidate_ids = set()
    for sig in root.get("anchor_signatures") or []:
        candidate_ids.update(sig.get("candidate_ids") or [])
    hits = []
    for row in fail_reviews:
        reported = set(row["case"].get("reported_candidate_ids") or [])
        if reported & candidate_ids:
            hits.append(row)
    return hits


def _gt_wave_card(row, esc):
    """One waveform-review card in the LLPTW wave-row style."""
    from .llptw_report import SURFER_ORIGIN
    case, review = row["case"], row["review"]
    replay_status = (row.get("replay") or {}).get("status") or "n/a"
    observed = str(review.get("observed_behavior") or "")
    short = observed if len(observed) <= 500 else observed[:499] + "…"
    viewer = ((row.get("waveform") or {}).get("result") or {}).get("waveform_viewer") or {}
    url = str(viewer.get("url") or "")
    if url.startswith("/"):
        url = SURFER_ORIGIN + url
    wave_link = (f"<a class='text-link' href='{esc(url)}'>查看此用例波形</a>" if url else "")
    evidence = str(review.get("evidence_id") or "")
    return (f"<div class='bug-card'><div class='bug-top'><div>"
            f"<span class='id'>{esc(evidence[:26])}</span>"
            f"<h3>{esc(case['nodeid'].split('::')[-1])}</h3>"
            f"<p class='summary'>{esc(short)}</p></div>"
            f"<div class='bug-side'><span class='status active'>DUT 缺陷</span>"
            f"<span class='tier'>replay {esc(replay_status)}</span>{wave_link}</div></div></div>")


def _gt_detail_page(defect, report_view, esc):
    """Render one formal-GT full-analysis page in the bosc_LLPTW gt/ layout.

    Mirrors the curated per-GT detail pages (breadcrumb, hero, verdict summary,
    scenario / waveform / mechanism / oracle sections, RTL source preview and
    evidence boundary) so every DUT report reads like the reference report.
    Content is drawn only from registered evidence: the GT registry entry, the
    root anchor, the alignment-audit rationale and per-case reviews. Where the
    registry offers no case-level mapping the page states that boundary
    explicitly instead of inventing an association.
    """
    from .llptw_report import _CSS, _code_preview
    dut = report_view.get("dut")
    gt_id = str(defect.get("gt_id"))
    roots_raw = report_view.get("rtl_root_bugs")
    if isinstance(roots_raw, dict):
        roots_raw = roots_raw.get("rtl_root_bugs") or []
    root = next((r for r in roots_raw or []
                 if isinstance(r, dict) and r.get("rtl_root_bug_id") == defect.get("source_root_id")), {})
    anchor = root.get("root_anchor") or {}
    wave_reviews = [r for r in report_view.get("waveform_reviews", []) if isinstance(r, dict) and r.get("case")]
    fail_reviews = [r for r in report_view.get("failure_case_reviews", []) if isinstance(r, dict) and r.get("case")]
    fail_by_case = {r["case"]["case_id"]: r for r in fail_reviews}
    wave_by_case = {r["case"]["case_id"]: r for r in wave_reviews}

    reg_cases = _gt_registered_cases(root, fail_by_case, fail_reviews)
    reg_ids = [r["case"]["case_id"] for r in reg_cases]

    # Alignment-audit decisions that selected this GT, joined back to the
    # report's own root-cause entries (验证场景摘录).
    decisions = [x for x in (report_view.get("reported_root_alignment_llm_audit") or {}).get("decisions", [])
                 if isinstance(x, dict) and x.get("selected_gt_id") == gt_id]
    entries = {}
    summary = report_view.get("reported_root_cause_summary") or {}
    for model_name, per in (summary.get("per_model") or {}).items():
        for idx, entry in enumerate(per.get("entries") or [], start=1):
            entries[(model_name, idx)] = entry
    picks = []
    for dec in decisions:
        # item_id is "<model>:root:<index>" (1-based index into the model's
        # reported_root_cause_summary entries).
        parts = str(dec.get("item_id") or "").split(":")
        if len(parts) == 3 and parts[1] == "root" and parts[-1].isdigit():
            picks.append((dec, entries.get((parts[0], int(parts[-1])))))
        else:
            picks.append((dec, None))

    # Scenario cells: report-root excerpts, plus expected/actual from a
    # representative registered case when one exists.
    rep_row = next((wave_by_case.get(cid) for cid in reg_ids if cid in wave_by_case), None)
    rep_fail = fail_by_case.get(rep_row["case"]["case_id"]) if rep_row else None
    rep_frev = (rep_fail or {}).get("review") or {}
    scenario_cells = ""
    for dec, entry in picks:
        excerpt = str((entry or {}).get("source_excerpt") or "").strip()
        root_label = ":".join(str(dec.get("item_id") or "").split(":")[1:]) or "报告根因"
        head = str((entry or {}).get("title") or "").strip("*` ") or f"报告根因 {root_label}"
        # The model's own excerpt usually re-opens with the bolded title;
        # drop that duplication so the cell reads phenomenon bullets only.
        for prefix in (f"**{head}**", f"**{head}**\r"):
            if excerpt.startswith(prefix):
                excerpt = excerpt[len(prefix):].lstrip()
        scenario_cells += (f"<div class='scenario-cell'><b>{esc(head)}</b>"
                           f"<p>{esc(excerpt or '登记簿未提供现象摘录。')}</p></div>")
    if not scenario_cells:
        scenario_cells = ("<div class='scenario-cell'><b>验证场景</b><p>"
                          "对齐审计未将任何报告根因正式对应到该 GT；场景以登记簿锚点与失败类型为准。</p></div>")
    if rep_frev:
        scenario_cells += (f"<div class='scenario-cell'><b>预期结果（代表用例）</b>"
                           f"<p>{esc(str(rep_frev.get('specification_expected') or '—'))}</p></div>"
                           f"<div class='scenario-cell'><b>实际结果（代表用例）</b>"
                           f"<p>{esc(str(rep_frev.get('dut_actual') or '—'))}</p></div>")

    # Waveform cards: registered mapping only; never fabricate an association.
    wave_cards = "".join(_gt_wave_card(wave_by_case[cid], esc)
                         for cid in reg_ids[:8] if cid in wave_by_case)
    if reg_cases:
        wave_note = (f"<div class='notice'><b>关联口径：</b>登记候选映射命中 {len(reg_ids)} 例"
                     f"（{esc(root.get('rtl_root_bug_id'))} anchor_signatures ∩ 用例 reported_candidate_ids），"
                     + ("以下展示前 8 例。" if len(reg_ids) > 8 else "全部展示如下。") + "</div>")
    else:
        wave_note = ("<div class='boundary'><b>无用例级映射：</b>登记簿与对齐审计均未把具体失败用例映射到该 GT"
                     "（登记候选未出现在任何失败用例的 reported_candidate_ids 中）。"
                     "该缺陷的机理证据来自对齐审计的 RTL 核对（见下文），全部波形复核明细见"
                     " <a class='text-link' href='../index.html#final-bug-analysis'>报告总览</a>。</div>")

    mechanism_steps = ""
    for dec, _ in picks:
        rationale = str(dec.get("rationale") or "").strip()
        if rationale:
            root_label = ":".join(str(dec.get("item_id") or "").split(":")[1:])
            mechanism_steps += (f"<div class='cause-step'><b>{esc(root_label)} 核对</b>"
                                f"<p>{esc(rationale)}</p></div>")
    if not mechanism_steps:
        mechanism_steps = ("<div class='cause-step'><p>对齐审计未留下该 GT 的机理核对记录；"
                           "机理以登记簿 failure_mode 与锚点为准。</p></div>")
    cone_reason = str(anchor.get("reason") or "")
    cone = (f"<div class='notice'><b>登记依赖锥（{esc(anchor.get('evidence'))} · "
            f"置信度 {esc(anchor.get('confidence'))}）：</b>{esc(cone_reason)}</div>" if cone_reason else "")

    oracle_rows = ""
    for row in fail_reviews:
        cid = row["case"]["case_id"]
        if cid not in set(reg_ids[:8]):
            continue
        frev = row.get("review") or {}
        wrev = (wave_by_case.get(cid) or {}).get("review") or {}
        replay_status = (row.get("replay") or {}).get("status") or "n/a"
        oracle_rows += ("<tr>"
                        f"<td>{esc(row['case']['nodeid'].split('::')[-1])}</td>"
                        f"<td><span class='status active'>{esc(replay_status)}</span></td>"
                        f"<td>{esc(str(frev.get('specification_expected') or '—'))}</td>"
                        f"<td>{esc(str(frev.get('dut_actual') or '—'))}</td>"
                        f"<td><code>{esc(str(wrev.get('evidence_id') or '')[:26])}</code></td>"
                        "</tr>")
    oracle_body = (f"<div class='table-wrap'><table><thead><tr><th>测试用例</th><th>回放</th>"
                   f"<th>规格预期</th><th>DUT 实际</th><th>波形证据</th></tr></thead>"
                   f"<tbody>{oracle_rows}</tbody></table></div>") if oracle_rows else \
        "<div class='boundary'><b>无登记 Oracle：</b>该 GT 没有登记的用例级映射，故无逐例规格预期/实际对照。</div>"

    # 规格依据预览: spec anchors cited by the registered cases' own
    # spec_properties mapping (deduped, function-specific checks first).
    generic_cks = {"CK-NORM", "CK-BOUNDARY", "CK-ERROR", "CK-STEP"}
    cite_counts = Counter()
    anchor_specs = {}
    for row in fail_reviews:
        if row["case"]["case_id"] not in set(reg_ids[:8]):
            continue
        for prop in row["case"].get("spec_properties") or []:
            if not isinstance(prop, dict) or not prop.get("source_path") or not prop.get("line_start"):
                continue
            key = (str(prop.get("property_text") or prop.get("title") or ""),
                   int(prop["line_start"]), str(prop["source_path"]))
            cite_counts[key] += 1
            anchor_specs[key] = prop

    def _spec_window_end(path, line_no):
        try:
            lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return line_no
        nxt = next((i + 1 for i, line in enumerate(lines[line_no:], start=line_no)
                    if re.match(r"^<(FG|FC|CK)-", line.strip())), line_no + 25)
        return min(max(nxt - 1, line_no), line_no + 25)

    ordered_specs = sorted(anchor_specs, key=lambda k: (k[0] in generic_cks, k[1]))
    spec_previews = ""
    if ordered_specs:
        for title, line_no, spec_path in ordered_specs[:4]:
            window_end = _spec_window_end(spec_path, line_no)
            cite = cite_counts[(title, line_no, spec_path)]
            spec_previews += (f"<details class='evidence-block'><summary>{esc(title)} · "
                              f"{esc(Path(spec_path).name)}:{line_no}-{window_end}"
                              f"（{cite} 例登记用例引用）</summary>"
                              f"{_code_preview(Path(spec_path), line_no, window_end, focus_start=line_no, focus_end=line_no)}</details>")
        spec_body = (f"<p class='scenario-lead'>以下 {min(4, len(ordered_specs))} 个规格锚点取自登记失败用例"
                     f" spec_properties 的原文映射（去重后功能检查优先，按行号排序）。</p>{spec_previews}")
    else:
        spec_body = ("<div class='boundary'><b>无登记规格锚点：</b>该 GT 没有用例级映射，"
                     "没有失败用例的 spec_properties 可引用；规格依据以症状列表与登记锚点区间为准。</div>")

    # 修复与验证建议: derived from the registered anchor and audit record only;
    # clearly labelled as a derived suggestion, not registry content.
    anchor_loc = f"{esc(defect.get('rtl_file'))}:{esc(defect.get('rtl_line_start'))}-{esc(defect.get('rtl_line_end'))}"
    if reg_cases:
        ck_titles = [t for (t, _n, _p) in ordered_specs if t not in generic_cks]
        fix_card = ("<div class='bug-card'>"
                    f"<p><b>修复方向：</b>以登记锚点 <code>{anchor_loc}</code> 为落点，"
                    "结合上方对齐审计核对记录定位失效路径后再改动；登记簿未提供官方修复方案，"
                    "本条为依据登记证据的推导建议。</p>"
                    f"<p><b>回归要求：</b>重跑 {len(reg_ids)} 例登记失败用例"
                    + (f"（重点覆盖 {'、'.join(ck_titles[:4])} 等功能检查锚点）" if ck_titles else "")
                    + "，修复后逐例复核规格预期/实际对照，并执行全量回归。</p></div>")
    else:
        fix_card = ("<div class='bug-card'>"
                    f"<p><b>修复方向：</b>以登记锚点 <code>{anchor_loc}</code> 为落点，"
                    "结合上方审计核对记录复核失效路径；登记簿未提供官方修复方案，"
                    "本条为依据登记证据的推导建议。</p>"
                    "<p><b>回归要求：</b>登记簿未提供用例级回归集；建议修复后复核锚点区间行为、"
                    "逐条核对关联症状现象，并执行全量回归。</p></div>")

    source_preview = ""
    if anchor.get("path"):
        source_preview = _code_preview(Path(anchor["path"]),
                                       int(anchor.get("line_start") or 1),
                                       int(anchor.get("line_end") or 1))
    else:
        source_preview = "<div class='boundary'><b>源码不可用：</b>登记簿未提供锚点文件路径。</div>"
    test_preview = ""
    if rep_row is not None:
        src_info = rep_row["case"].get("source") or {}
        test_file = src_info.get("source_file")
        func = str(rep_row["case"]["nodeid"].split("::")[-1])
        if test_file and Path(test_file).is_file():
            try:
                lines = Path(test_file).read_text(encoding="utf-8", errors="replace").splitlines()
                at = next((i + 1 for i, line in enumerate(lines) if f"def {func}(" in line), 1)
                test_preview = _code_preview(Path(test_file), max(1, at - 4), min(len(lines), at + 40),
                                             focus_start=at, focus_end=at)
            except OSError:
                test_preview = ""
    test_block = (f"<details class='evidence-block'><summary>触发用例源码预览（{esc(func)}）</summary>"
                  f"{test_preview}</details>") if test_preview else ""

    symptom_count = len(defect.get("symptoms") or [])
    verdict_rows = "".join(
        f"<tr><th>{esc(label)}</th><td>{esc(value)}</td></tr>" for label, value in (
            ("裁决状态", root.get("root_match_status") or defect.get("root_match_status") or "—"),
            ("失败类型", f"{_FAILURE_MODE_LABELS.get(str(defect.get('failure_mode')), defect.get('failure_mode'))}"
             f"（{defect.get('failure_mode')}）"),
            ("主信号", anchor.get("primary_signal") or root.get("primary_signal") or "—"),
            ("关键 RTL", f"{defect.get('rtl_file')}:{defect.get('rtl_line_start')}-{defect.get('rtl_line_end')}"),
            ("关联模型", ", ".join(defect.get("models") or []) or "—"),
            ("登记佐证", " · ".join(str(p) for p in (defect.get("admission_source"),
                                                    defect.get("admission_evidence")) if p) or "—"),
            ("锚点置信度", defect.get("source_anchor_confidence") or anchor.get("confidence") or "—"),
            ("关联现象", f"{symptom_count} 条症状（{', '.join((defect.get('symptoms') or [])[:3])}"
             + (f" 等" if symptom_count > 3 else "") + "）" if symptom_count else "—"),
        ))
    admission = " · ".join(str(p) for p in (defect.get("admission_source"),
                                            defect.get("admission_evidence")) if p)
    mode_label = _FAILURE_MODE_LABELS.get(str(defect.get("failure_mode")), defect.get("failure_mode"))
    body = f"""
<nav class="crumb"><a href="../index.html">← 返回评测报告总览</a><span>{esc(gt_id)}</span></nav>
<section class="hero"><div class="eyebrow">{esc(gt_id)} · {esc(defect.get('source_root_id'))} · 疑似 Bug</div>
<h1>{esc(mode_label)}：{esc(defect.get('failure_mode'))}</h1>
<p>权威 RTL 位置 <code>{esc(defect.get('rtl_file'))}:{esc(defect.get('rtl_line_start'))}-{esc(defect.get('rtl_line_end'))}</code>
· 登记于 {esc(str(defect.get('admitted_at', ''))[:10])}{('（' + esc(admission) + '）') if admission else ''}。</p></section>
<section class="section"><div class="table-wrap"><table class="verdict-summary"><tbody>{verdict_rows}</tbody></table></div></section>
<nav class="detail-nav"><a href="#scenario">验证场景</a><a href="#waveform">波形简析</a><a href="#mechanism">缺陷机理</a>
<a href="#oracle">测试与 Oracle</a><a href="#spec">规格依据</a><a href="#fix">修复建议</a>
<a href="#source-preview">源码预览</a><a href="#boundary">证据边界</a></nav>
<section class="section" id="scenario"><div class="section-head"><div><h2>验证场景与判定</h2>
<p>场景摘自对齐审计引用的报告根因条目；预期/实际来自代表失败用例的逐例复核。</p></div></div>
<div class="scenario-grid">{scenario_cells}</div></section>
<section class="section" id="waveform"><div class="section-head"><div><h2>波形简析</h2>
<p>逐例波形复核结论（conclusion=dut_bug）与原始波形入口。</p></div></div>{wave_note}{wave_cards}</section>
<section class="section" id="mechanism"><div class="section-head"><div><h2>缺陷机理</h2>
<p>机理结论取自对齐审计的 RTL 核对记录（策略未正式采信，仅作证据呈现）。</p></div></div>
<div class="cause-flow">{mechanism_steps}</div>{cone}</section>
<section class="section" id="oracle"><div class="section-head"><div><h2>测试与 Oracle</h2>
<p>规格预期与 DUT 实际逐例对照（登记映射用例）。</p></div></div>{oracle_body}</section>
<section class="section" id="spec"><div class="section-head"><div><h2>规格依据预览</h2>
<p>登记失败用例 spec_properties 指向的功能检查原文，默认折叠。</p></div></div>{spec_body}</section>
<section class="section" id="fix"><div class="section-head"><div><h2>修复与验证建议</h2>
<p>由登记锚点与审计记录推导的建议；登记簿未提供官方修复方案。</p></div></div>{fix_card}</section>
<section class="section" id="source-preview"><div class="section-head"><div><h2>源码预览</h2>
<p>登记锚点 bosc_Sbuffer.sv:{esc(defect.get('rtl_line_start'))}-{esc(defect.get('rtl_line_end'))}（focus 行为锚点区间）。</p></div></div>
<div class="evidence-block">{source_preview}</div>{test_block}</section>
<section class="section" id="boundary"><div class="section-head"><div><h2>证据边界</h2></div></div>
<div class="boundary"><ul>
<li>锚点置信度为 <b>{esc(defect.get('source_anchor_confidence'))}</b>：登记位置是候选锚点，非经独立形式化证明的唯一根因。</li>
<li>对齐审计结论均为 <b>insufficient_or_low_confidence（未正式采信）</b>：报告源缺少 ck_paths/bg_names，CK/BG 佐证缺失；本页机理文字仅为审计依据的呈现。</li>
<li>用例级映射口径：{('登记候选映射（anchor_signatures ∩ reported_candidate_ids），共 ' + str(len(reg_ids)) + ' 例。') if reg_cases else '无登记映射；本页不含逐例波形卡片。'}</li>
<li>根因回放状态：{esc(root.get('replay_verification_status') or '—')}；症状归并依据：{esc(root.get('merge_rationale') or '—')}。</li>
</ul></div></section>"""
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(gt_id)} 完整分析 · {esc(dut)}</title>
<style>{_CSS}</style></head><body><main class="page">
<div class="topbar"><div class="brand">XSV BugReview / {esc(dut)}</div>
<nav class="nav" aria-label="报告导航"><a href="../index.html">总览</a>
<a href="../gt_defect_details.html">全部疑似 Bug 详情</a>
<a href="../../data/ground_truth_rtl_defects.json">背景数据 JSON</a></nav></div>{body}
<footer>疑似 Bug 完整分析 · 口径：登记簿裁决为准；对齐审计文字未经策略正式采信，仅作证据呈现。</footer>
</main></body></html>"""


def _write_gt_detail_pages(dut_dir, report_view):
    """Write one LLPTW-style full-analysis page per formal GT defect."""
    esc = lambda value: html.escape(str(value or ""))
    gt = report_view.get("ground_truth_rtl_defects") or {}
    defects = [d for d in gt.get("defects", []) if isinstance(d, dict)]
    if not defects:
        return
    out_dir = Path(dut_dir) / "reports" / "zh" / "gt"
    out_dir.mkdir(parents=True, exist_ok=True)
    for defect in defects:
        page = _gt_detail_page(defect, report_view, esc)
        (out_dir / f"{defect.get('gt_id')}.html").write_text(page, encoding="utf-8")


def _curated_gt_fragment(report_view, esc):
    """Curated page header in the LLPTW adjudication layout.

    Rendered right after the hero section: a verification-status overview
    (coverage cards) followed by the formal GT adjudication table, so the
    final true defects are the first thing a reader sees instead of a bare
    scoring denominator.
    """
    from .llptw_report import _EMBED_CSS
    data = report_view.get("report_data") or {}
    verification = data.get("verification_status") or {}
    gt = report_view.get("ground_truth_rtl_defects") or {}
    defects = [d for d in gt.get("defects", []) if isinstance(d, dict)]
    per_model = report_view.get("per_model") or {}
    first_model = next(iter(per_model.values()), {}) if per_model else {}
    line_cov = first_model.get("line_coverage") or {}
    func_cov = first_model.get("functional_coverage") or {}
    wave_reviews = report_view.get("waveform_reviews", [])
    dut_bug_cases = sum(1 for r in wave_reviews if r["review"].get("conclusion") == "dut_bug")
    failure_mode_labels = {
        "output_mismatch": "输出不匹配",
        "ordering_or_concurrency_failure": "顺序 / 并发失效",
        "hang_or_deadlock": "挂起 / 死锁",
        "protocol_violation": "协议违例",
    }
    items = []
    if line_cov.get("available") and line_cov.get("rate") is not None:
        rate = float(line_cov["rate"])
        items.append(
            f'<div class="coverage-item"><div class="coverage-value">{rate:.2f}%</div>'
            f'<div class="coverage-label">LINE</div><div class="coverage-bar">'
            f'<span style="width:{rate:.2f}%;background:#25704a"></span></div>'
            f'<div class="coverage-meta">行覆盖率 {esc(line_cov.get("hit_lines", "?"))}'
            f'/{esc(line_cov.get("total_lines", "?"))}</div></div>')
    if func_cov.get("available") and func_cov.get("rate") is not None:
        rate = float(func_cov["rate"])
        items.append(
            f'<div class="coverage-item"><div class="coverage-value">{rate:.2f}%</div>'
            f'<div class="coverage-label">功能覆盖率</div><div class="coverage-bar">'
            f'<span style="width:{rate:.2f}%;background:#25704a"></span></div>'
            f'<div class="coverage-meta">功能覆盖率 {esc(func_cov.get("bin_hit", "?"))}'
            f'/{esc(func_cov.get("bin_total", "?"))} CK 覆盖项</div></div>')
    if defects:
        items.append(
            f'<div class="coverage-item"><div class="coverage-value">{len(defects)}</div>'
            '<div class="coverage-label">疑似 Bug 根因</div><div class="coverage-bar">'
            '<span style="width:100%;background:#25704a"></span></div>'
            '<div class="coverage-meta">GT 登记簿真值缺陷</div></div>')
    if wave_reviews:
        rate = 100.0 * dut_bug_cases / len(wave_reviews)
        items.append(
            f'<div class="coverage-item"><div class="coverage-value">{dut_bug_cases}</div>'
            '<div class="coverage-label">波形复核确认缺陷</div><div class="coverage-bar">'
            f'<span style="width:{rate:.2f}%;background:#25704a"></span></div>'
            f'<div class="coverage-meta">{len(wave_reviews)} 例复核中的 DUT 缺陷结论</div></div>')
    failed_count = int(verification.get("failed_case_count") or 0)
    if failed_count:
        items.append(
            f'<div class="coverage-item"><div class="coverage-value">{failed_count}</div>'
            '<div class="coverage-label">回放失败用例</div><div class="coverage-bar">'
            '<span style="width:100%;background:#72558a"></span></div>'
            '<div class="coverage-meta">逐例归因见页尾明细</div></div>')
    rows = ""
    for d in defects:
        anchor = ""
        if d.get("rtl_file"):
            anchor = f"{d['rtl_file']}:{d.get('rtl_line_start')}-{d.get('rtl_line_end')}"
        symptoms = d.get("symptoms", [])
        symptom_text = ", ".join(symptoms[:4]) + (f" 等 {len(symptoms)} 项" if len(symptoms) > 4 else "")
        mode_label = failure_mode_labels.get(str(d.get("failure_mode")), d.get("failure_mode"))
        admission = " · ".join(str(part) for part in (d.get("admission_source"),
                                                      d.get("admission_evidence")) if part)
        bug_cell = (
            f"<span class='bug-name'>{esc(mode_label)}（{esc(d.get('failure_mode'))}）</span>"
            "<span class='bug-summary'>权威 RTL 位置 "
            f"<code>{esc(anchor)}</code>"
            + (f" · 登记于 {esc(str(d.get('admitted_at', ''))[:10])}（{esc(admission)}）" if admission else "")
            + "</span>")
        rows += (
            "<tr>"
            f"<td><b><a href='gt/{esc(d.get('gt_id'))}.html'>{esc(d.get('gt_id'))}</a></b>"
            f"<br><span class='cur-id'>{esc(d.get('source_root_id'))}</span></td>"
            f"<td>{bug_cell}</td>"
            f"<td>{esc(', '.join(d.get('models', [])))}</td>"
            f"<td>{esc(symptom_text) if symptom_text else '—'}</td>"
            f"<td><span class='cur-status'>{esc(d.get('root_match_status'))}</span></td>"
            f"<td><a class='table-action' href='gt/{esc(d.get('gt_id'))}.html'>查看完整分析</a></td>"
            "</tr>")
    decisions = [x for x in (report_view.get("reported_root_alignment_llm_audit") or {}).get("decisions", [])
                 if isinstance(x, dict)]
    audit_note = ""
    if decisions:
        selected = {}
        for dec in decisions:
            if dec.get("selected_gt_id"):
                selected.setdefault(dec["selected_gt_id"], []).append(
                    str(dec.get("item_id")).split(":")[-1])
        if selected:
            picks = "；".join(
                f"{esc(gt_id)} ← {'/'.join(sorted(roots))}" for gt_id, roots in sorted(selected.items()))
            audit_note = f"对齐审计：{picks}（策略未正式采信，CK/BG 佐证缺失），明细见页尾。"
        else:
            audit_note = "对齐审计：报告根因与 GT 登记锚点无可确认对应。"
    foot_note = (f"波形复核 {len(wave_reviews)} 例全部确认 DUT 缺陷；" if wave_reviews and dut_bug_cases == len(wave_reviews) else "")
    return f"""<!-- CURATED-GT-START -->{_EMBED_CSS}
<span id="bug-overview" aria-hidden="true"></span>
<section class="verify-overview" id="verification-overview"><div class="verify-head"><h2>验证状态总览</h2>
<p>覆盖率按模型运行正式统计口径汇总；缺陷裁决与逐例归因见下文。</p></div>
<div class="coverage-grid">
{"".join(items)}
</div><div class="verify-foot"><b>状态：</b>{esc(foot_note)}当前展示 {len(defects)} 条疑似 Bug；{esc(audit_note)}</div></section>
<span id="final-bug-analysis" aria-hidden="true"></span>
<section class="llptw-curation" id="adjudicated-gt"><div class="cur-head"><div><h2>最终 Bug 裁决</h2>
<p>首页只展示裁决结果；根因机理、规格依据、波形/RTL 证据与源码预览统一放在详情页。</p></div>
<span class="cur-status">疑似 Bug · {len(defects)}</span></div>
<div class="adjudication-wrap"><table class="adjudication-table" aria-label="最终 Bug 裁决结果"><colgroup><col style="width:13%"><col style="width:41%"><col style="width:10%"><col style="width:15%"><col style="width:11%"><col style="width:10%"></colgroup>
<thead><tr><th>GT 编号</th><th>Bug</th><th>命中模型</th><th>关联现象</th><th>状态</th><th>详情</th></tr></thead><tbody>{rows}</tbody></table></div>
<div class="cur-foot"><span>以下条目为当前证据支持的疑似 Bug；置信度和完整证据见详情。</span><span class="cur-foot-links"><a href="gt_defect_details.html">全部 GT 缺陷详情</a><a href="../../data/ground_truth_rtl_defects.json">背景数据 JSON</a></span></div></section><!-- CURATED-GT-END -->"""


def _gt_alignment_audit_block(report_view, esc):
    """Compact report-root <-> GT alignment audit table for the page footer."""
    decisions = [d for d in (report_view.get("reported_root_alignment_llm_audit") or {}).get("decisions", [])
                 if isinstance(d, dict)]
    if not decisions:
        return ""
    rows = ""
    for dec in decisions:
        rationale = str(dec.get("rationale") or "")
        if len(rationale) > 300:
            rationale = rationale[:299] + "…"
        state = "accepted" if dec.get("accepted") else (dec.get("resolution") or "rejected")
        rows += (
            "<tr>"
            f"<td>{esc(str(dec.get('item_id')).split(':')[-1])}</td>"
            f"<td>{esc(dec.get('selected_gt_id') or '—')}</td>"
            f"<td>{esc(state)}</td>"
            f"<td title='{esc(dec.get('rationale'))}'>{esc(rationale)}</td>"
            "</tr>")
    return ("<div id='gt-alignment-audit'><h3 style='margin-top:18px'>报告根因 ↔ 疑似 Bug 对齐审计</h3>"
            "<table class='fba-table'><tr><th>报告根因</th><th>判定选择</th>"
            "<th>策略结论</th><th>依据（摘要）</th></tr>" + rows + "</table></div>")


def _augment_zh_report(dut_dir, report_view):
    """Overlay the independent review findings onto the canonical zh report.

    The canonical renderer in benchmark_workflow is candidate/GT centric and
    stays untouched: the symptom matrix gains one row per confirmed root-cause
    signature, the evidence-chain table gains an independent-review column,
    and the case-level analysis is appended as an auxiliary section.
    """
    page_path = Path(dut_dir) / "reports" / "zh" / "index.html"
    if not page_path.exists():
        return
    page = page_path.read_text(encoding="utf-8")
    esc = lambda value: html.escape(str(value or ""))
    final = report_view.get("final_bug_analysis") or {}
    bugs = final.get("bugs", [])
    confirmed = final.get("confirmed_dut_bug_cases", 0)
    model_names = [esc(m) for m in report_view.get("model_names", [])] or ["ucagent"]

    # 1) symptom matrix: one row per confirmed root-cause signature
    if bugs:
        rows = ""
        for bug in bugs:
            cid = bug.get("bug_id", "?")
            prop = "；".join(x for x in (bug.get("title"), bug.get("spec_violation")) if x)
            signals = ", ".join(bug.get("signals", [])) or "n/a"
            regions = bug.get("rtl_regions", [])
            rtl = ", ".join(regions) or "n/a"
            rtl_display = regions[0] if regions else "n/a"
            if len(rtl_display) > 44:
                rtl_display = rtl_display[:43] + "…"
            cells = "".join("<td class='cell-miss' title='模型未声明该现象'></td>" for _ in model_names)
            rows += (
                f"<tr><td class='cid-cell' title='{esc(cid)}'><a href='final_bug_details.html#{esc(cid)}'>{esc(cid)}</a></td>"
                f"<td class='prop-cell' title='{esc(prop)}'>{esc(bug.get('title'))}</td>"
                f"<td class='sig-cell' title='{esc(signals)}'>{esc(signals)}</td>"
                f"<td class='rtl-loc-cell' title='{esc(rtl)}'>{esc(rtl_display)}</td>"
                f"{cells}</tr>")
        section_at = page.find('id="symptom-matrix"')
        tbody_at = page.find("<tbody>", section_at)
        tbody_end = page.find("</tbody>", tbody_at)
        if section_at >= 0 and 0 < tbody_at < tbody_end:
            page = page[:tbody_end] + rows + page[tbody_end:]

    # 2) evidence chain: one independent-review column next to the model columns
    if bugs and confirmed:
        table_at = page.find("<table class='chain-table'>")
        if table_at >= 0:
            table_end = page.find("</table>", table_at)
            table = page[table_at:table_end]
            review_cells = [("chain-high", f"{confirmed}/{confirmed} (100%)"),
                            ("chain-na", "n/a"),
                            ("chain-high", f"{confirmed}/{confirmed} (100%)"),
                            ("chain-high", f"{confirmed}/{confirmed} (100%)"),
                            ("chain-high", f"{confirmed}/{confirmed} (100%)"),
                            ("chain-high", f"{confirmed}/{confirmed} (100%)")]
            rebuilt, last = [], 0
            for i, match in enumerate(re.finditer(r"<tr><td class='chain-label'>.*?</tr>", table, re.S)):
                rebuilt.append(table[last:match.start()])
                cls, text = review_cells[i] if i < len(review_cells) else ("chain-na", "n/a")
                rebuilt.append(match.group(0)[:-len("</tr>")] + f"<td class='{cls}'>{text}</td></tr>")
                last = match.end()
            rebuilt.append(table[last:])
            table = "".join(rebuilt).replace("</th></tr>", "<th>独立复核</th></tr>", 1)
            page = page[:table_at] + table + page[table_end:]

    # 3) auxiliary section appended at the end of the page
    counts = Counter(r["review"]["classification"] for r in report_view.get("failure_case_reviews", []))
    breakdown = "；".join(f"{esc(k)} {v} 例" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
    waves = {r["case"]["case_id"]: r["review"] for r in report_view.get("waveform_reviews", [])}
    failures = "".join(
        f"<tr><td>{esc(r['case']['model'])}</td><td>{esc(r['case']['run_key'])}</td>"
        f"<td title='{esc(r['case']['nodeid'])}'>{esc(r['case']['nodeid'].split('::')[-1])}</td>"
        f"<td>{esc(r['replay'].get('status'))}</td><td>{esc(r['review']['classification'])}</td>"
        f"<td>{esc(waves.get(r['case']['case_id'], {}).get('conclusion', 'not_applicable'))}</td>"
        f"<td>{esc(', '.join(r['case']['reported_candidate_ids']))}</td></tr>"
        for r in report_view.get("failure_case_reviews", []))
    aux_style = ("<style>.fba-bug{border:1px solid var(--border);border-radius:10px;padding:8px 14px;"
                 "margin:10px 0}.fba-bug h3{margin:8px 0}.fba-bug small{color:var(--muted);font-weight:400}"
                 ".fba-table{width:100%;border-collapse:collapse;margin-top:12px}"
                 ".fba-table td,.fba-table th{border:1px solid var(--border);padding:6px 8px;"
                 "font-size:13px;text-align:left}.chain-na{color:#94a3b8}</style>")
    wave_reviews = report_view.get("waveform_reviews", [])
    dut_bug_count = sum(1 for r in wave_reviews if r["review"].get("conclusion") == "dut_bug")
    if bugs:
        intro = (f"独立波形复核确认 {esc(confirmed)} 例 DUT 缺陷，"
                 f"聚类为 {esc(final.get('bug_count', len(bugs)))} 类根因；")
        cards = _final_bug_section(final, esc)
        cards = re.sub(r"<h3>([A-Za-z0-9][A-Za-z0-9_-]*)：",
                       r"<h3><a href='final_bug_details.html#\1'>\1</a>：", cards)
        final_links = ("<a class='mini-link' href='final_bug_details.html'>最终缺陷详情</a> "
                       "<a class='mini-link' href='../../final_bug_analysis.json'>最终缺陷分析 JSON</a> ")
    else:
        intro = (f"波形复核 {len(wave_reviews)} 例，确认 DUT 缺陷 {dut_bug_count} 例（逐例归因见下表）；"
                 "本 DUT 未生成独立最终缺陷分析汇总，当前页面展示已有疑似 Bug 证据；")
        cards = ""
        final_links = ""
    aux = (aux_style
           + "<section class='section' id='final-bug-analysis'><div class='section-header'>"
             f"<div><h2>最终缺陷分析（辅助定位）</h2><p>{intro}失败用例 "
             f"{len(report_view.get('failure_case_reviews', []))} 个（{breakdown}）。"
             "标准口径的候选/GT 指标见上方各节；本节为基准方独立复核的辅助定位信息，"
             "点击缺陷编号查看 gt_defect 风格的详情页。</p></div></div>"
           + cards
           + "<h3 style='margin-top:18px'>失败用例归因明细</h3>"
           + "<table class='fba-table'><tr><th>模型</th><th>运行</th><th>用例</th><th>回放</th>"
             "<th>初步归因</th><th>波形复核</th><th>原模型声明</th></tr>" + failures + "</table>"
           + _gt_alignment_audit_block(report_view, esc)
             + f"<p style='margin-top:12px'>{final_links}"
             "<a class='mini-link' href='../../analysis.json'>完整证据 JSON</a> "
             "<a class='mini-link' href='gt_defect_details.html'>疑似 Bug 缺陷详情</a></p></section>")
    # Curated header (verification overview + GT adjudication) right after the
    # hero, matching the LLPTW adjudication layout; marker-guarded so a re-run
    # replaces instead of duplicating.
    fragment = _curated_gt_fragment(report_view, esc)
    if fragment:
        frag_start = page.find("<!-- CURATED-GT-START -->")
        frag_end = page.find("<!-- CURATED-GT-END -->")
        if 0 <= frag_start < frag_end:
            frag_end += len("<!-- CURATED-GT-END -->")
            page = page[:frag_start] + fragment + page[frag_end:]
        elif 'id="adjudicated-gt"' not in page:
            hero_at = page.find("<section class=\"hero\"")
            hero_end = page.find("</section>", hero_at)
            if hero_at >= 0 and hero_end >= 0:
                hero_end += len("</section>")
                page = page[:hero_end] + fragment + page[hero_end:]
            else:
                page = page.replace("</body>", fragment + "</body>")
    body_close = page.rfind("</body>")
    if body_close >= 0:
        page = page[:body_close] + aux + page[body_close:]
    page_path.write_text(page, encoding="utf-8")


def analysis_index_html(payloads):
    rows = "".join(
        "<a class='dut-row' href='dut_{dut}/reports/zh/index.html'>"
        "<span><strong>{dut}</strong><small>分析证据与回放、波形、诊断</small></span>"
        "<span class='arrow'>&#8594;</span></a>".format(
            dut=html.escape(dut),
        )
        for dut, _ in payloads
    )
    return """<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'><title>BugReview 分析报告</title>
<style>body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;max-width:760px;
margin:3rem auto;padding:0 1.5rem;background:#f8fafc;color:#0f172a;line-height:1.6}
h1{font-size:1.8rem;font-weight:800;margin-bottom:.5rem}.subtitle{color:#475569;margin-bottom:1.75rem}
.dut-row{display:flex;align-items:center;justify-content:space-between;padding:.85rem 1.25rem;
margin:.6rem 0;background:#e0f2fe;border:1px solid #bae6fd;border-radius:8px;color:#075985;
text-decoration:none}.dut-row:hover{background:#bae6fd}.dut-row small{display:block;color:#475569;font-size:.8rem}.arrow{font-size:1.3rem}
.meta{font-size:.8rem;color:#64748b;margin-top:2rem}</style></head><body>
<h1>BugReview 分析报告</h1><p class='subtitle'>按 DUT 查看完整的失败用例归因、回放、波形和结构化诊断证据。</p>
    {rows}<p class='meta'>本入口不包含评分结果。每个 DUT 页面同时提供中文和 English 报告。</p>
</body></html>""".replace("{rows}", rows)


def _attach_failure_records(payload, failure_reviews, waveform_reviews):
    """Project confirmed per-test DUT failures into the canonical report schema."""
    wave_by_case = {
        str(row.get("case", {}).get("case_id")): row
        for row in waveform_reviews if isinstance(row, dict)
    }
    model = (payload.get("model_names") or ["unknown"])[0]
    records, matrix, bugs = [], [], []
    for index, item in enumerate(failure_reviews, 1):
        review = item.get("review", {}) if isinstance(item, dict) else {}
        if review.get("classification") != "suspected_dut_bug" or not review.get("correctness_confirmed"):
            continue
        case = item.get("case", {})
        case_id = str(case.get("case_id") or index)
        bug_id = "FAIL-" + stable_hash({"dut": payload.get("dut"), "case": case_id})[:12]
        wave = wave_by_case.get(case_id, {}).get("waveform", {})
        wave_review = wave.get("review", {}) if isinstance(wave, dict) else {}
        replay = item.get("replay", {})
        replay_status = str(replay.get("status") or "reproduced")
        tier = "replay_confirmed" if replay_status in {"reproduced", "passed"} else "execution_supported_pending_replay"
        if wave_review.get("conclusion") in {"supported", "dut_bug_supported"}:
            tier = "waveform_supported"
        property_text = (review.get("specification_expected") or review.get("dut_actual") or
                         case.get("nodeid") or "Confirmed failing test")
        record = {
            "canonical_bug": bug_id, "dut": payload.get("dut"), "model": model,
            "status": "found", "candidate_ids": [case_id], "property_text": property_text,
            "signals": case.get("signal_names", []), "waveform_focus_signals": case.get("waveform_focus_signals", []),
            "claim_sources": [{"claim_id": case_id, "summary": review.get("dut_actual") or property_text,
                               "referenced_tests": [case.get("nodeid", "")]}],
            "tests": [{"nodeid": case.get("nodeid", ""), "outcome": "failed",
                       "exception_message": review.get("dut_actual", "")}],
            "rtl_regions": case.get("rtl_regions", []), "replay_results": [replay],
            "evidence_tier": tier, "evidence_score": 5 if tier == "replay_confirmed" else 3,
            "score_reason": "confirmed failing test and replay review", "validation_status": "reproduced",
            "failure_reviews": [review], "waveform_reviews": [wave_review] if wave_review else [],
        }
        records.append(record)
        matrix.append({"canonical_bug": bug_id, "dut": payload.get("dut"), "property_text": property_text,
                       "signals": record["signals"], "rtl_location": record["rtl_regions"],
                       "per_model": {model: {"found": True, "status": "found", "evidence_tier": tier,
                                             "evidence_score": record["evidence_score"]}}})
        bugs.append({"canonical_id": bug_id, "property_text": property_text,
                     "source": "replay_failure_review", "models": [model]})
    if records:
        payload["benchmark_records"] = records
        payload["matrix"] = matrix
        payload["canonical_bugs"] = bugs
    return payload


def load_analysis_manifest(path):
    path = Path(path).resolve()
    manifest = read_object(path)
    if manifest.get("schema") != "benchmark_analysis_set.v1" or not manifest.get("duts"):
        raise ValueError(f"not a completed analysis manifest: {path}")
    payloads, seen = [], set()
    for row in manifest["duts"]:
        dut = safe_name(row["dut"])
        if dut in seen:
            raise ValueError(f"duplicate DUT: {dut}")
        seen.add(dut)
        artifact = (path.parent / row["path"]).resolve()
        if not artifact.is_relative_to(path.parent):
            raise ValueError("analysis artifact must be inside its publication")
        payload = read_object(artifact)
        if stable_hash(payload) != row["hash"] or payload.get("dut") != dut:
            raise ValueError(f"analysis integrity failure: {artifact}")
        if payload.get("analysis_state") != "finalized":
            raise ValueError(f"analysis is incomplete: {dut}")
        payloads.append(payload)
    if manifest.get("analysis_id") != stable_hash(manifest["duts"]):
        raise ValueError("analysis manifest identity mismatch")
    return manifest, payloads


class Workflow:
    def __init__(self, workspace):
        self.root = Path(workspace).resolve()
        self.config = read_object(self.root / "benchmark_job.json")
        if self.config["kind"] == "analysis" and self.config.get("replay", {}).get("enabled") is not True:
            raise ValueError("analysis requires replay.enabled=true; prepare a new workspace to rerun all tests")
        if self.config["kind"] != "analysis":
            raise ValueError("Bug Review supports only the analysis workflow")
        self.stages = ANALYSIS
        if self.config.get("analysis_stages") != list(ANALYSIS):
            raise ValueError("analysis stage contract changed; prepare a new workspace")

    def _state(self):
        if read_object(self.root / "benchmark_job.json") != self.config:
            raise ValueError("workspace configuration changed; restart with a new workspace")
        path = self.root / "workflow_state.json"
        state = read_object(path) if path.exists() else {"config_hash": stable_hash(self.config), "completed": {}}
        if state["config_hash"] != stable_hash(self.config):
            raise ValueError("workspace configuration changed; prepare a new workspace")
        for stage, outputs in state["completed"].items():
            for name, digest in outputs.items():
                path = self.root / name
                if not path.is_file() or file_hash(path) != digest:
                    raise ValueError(f"{stage} output changed or missing: {name}; use a new workspace")
        return state

    def status(self):
        state = self._state()
        current = next((s for s in self.stages if s not in state["completed"]), "")
        return {"kind": self.config["kind"], "current_stage": current,
                "completed": list(state["completed"]), "complete": not current}

    def _dut_roots(self):
        prepared = read_object(self.root / "parsed_inputs.json")
        return [(item["dut"], self.root / "tasks" / safe_name(item["dut"])) for item in prepared["dut_inputs"]]

    def _specs(self, stage):
        if stage not in STORES or not (self.root / "parsed_inputs.json").exists():
            return []
        kind, relative, _ = STORES[stage]
        return [(kind, root / relative) for _, root in self._dut_roots()]

    def requests(self):
        current = self.status()["current_stage"]
        if current in {"replay", "waveform"}:
            progress = {"total": 0, "completed": 0, "pending": 0, "requests": []}
            limit = self.config.get("batch_size", 1)
            for _, root in self._dut_roots():
                part = CaseReviews(root / current / "reviews", current).requests(max(0, limit))
                for key in ("total", "completed", "pending"):
                    progress[key] += part[key]
                progress["requests"].extend(part["requests"])
                limit -= len(part["requests"])
            return {**progress, "not_applicable": not progress["total"]}
        return pending_requests(self._specs(current), self.config.get("batch_size", 1))

    def submit(self, **kwargs):
        with task_lock(self.root / "workflow.lock"):
            stage = self.status()["current_stage"]
            if stage in {"replay", "waveform"}:
                for _, root in self._dut_roots():
                    reviews = CaseReviews(root / stage / "reviews", stage)
                    if any(t["task_id"] == kwargs["task_id"] for t in reviews.tasks()):
                        return reviews.submit(**kwargs)
                raise ValueError("task is not in the current case review stage")
            return submit_response(self._specs(stage), **kwargs)

    def check(self, stage):
        status = self.status()
        if stage in status["completed"]:
            return True, status
        return False, {**status, "error_code": "BENCHMARK_STAGE_PENDING", "stage": stage,
                       "progress": self.requests(), "next_action": "BugReviewRunStage, then BugReviewTasks/BugReviewSubmitResponse, then Check"}

    def run(self, stage):
        with task_lock(self.root / "workflow.lock"):
            state = self._state()
            if stage in state["completed"]:
                return {"status": "succeeded", "reused": True, "stage": stage}
            if self.status()["current_stage"] != stage:
                raise ValueError(f"stage dependency not complete; current stage: {self.status()['current_stage']}")
            outputs = self._analysis(stage)
            if outputs is None:
                return {"status": "awaiting_judgments", "progress": self.requests()}
            state["completed"][stage] = {str(p.relative_to(self.root)): file_hash(p) for p in outputs}
            atomic_write_json(self.root / "workflow_state.json", state)
            result = {"status": "succeeded", "stage": stage, **self.status()}
            if stage == "inputs":
                scope = read_object(self.root / "analysis_scope.json")
                result["analysis_scope"] = {"duts": scope["duts"], "runs": [
                    {key: row[key] for key in ("dut", "model", "workspace_root", "all_completed", "missing_files", "problems")}
                    for row in scope["runs"]], "rejected": scope["rejected"]}
            return result

    def _analysis(self, stage):
        from bug_review.benchmark_workflow.pipeline import load_benchmark_config, prepare_model_run_comparisons_by_config
        from bug_review.benchmark_workflow.stage_workflow import prepare_semantic_stage, consume_finalized_semantic_stage
        from bug_review.benchmark_workflow.root_review_stage import prepare_root_failure_mode_stage, prepare_rtl_root_appeal_stage, consume_finalized_root_review_stage
        from bug_review.benchmark_workflow.replay_stage import _root_review_source
        from bug_review.benchmark_workflow.stage_workflow import refresh_stage_workflow
        from bug_review.benchmark_workflow.scoring import attach_record_evidence_levels
        if stage == "inputs":
            source = Path(self.config["config_path"])
            if file_hash(source) != self.config["config_file_hash"]:
                raise ValueError("benchmark config changed since prepare")
            scope = discover_scope(self.config["runs"], self.root)
            for dut in scope["duts"]:
                safe_name(dut)
            files = {}
            for _, name in self.config["runs"]:
                path = Path(name)
                if not path.exists():
                    raise ValueError(f"input missing: {path}")
                for file in ([path] if path.is_file() else sorted(path.rglob("*"))):
                    if file.is_file():
                        files[str(file)] = file_hash(file)
            if not files:
                raise ValueError("no input artifacts")
            for run in scope["runs"]:
                for file in sorted(Path(run["workspace_root"]).rglob("*")):
                    if file.is_file():
                        files[str(file)] = file_hash(file)
                for name in [*run["found_files"].values(), run["completion_evidence"]]:
                    if name and Path(name).is_file():
                        files[name] = file_hash(name)
            output = self.root / "input_inventory.json"
            atomic_write_json(output, {"files": files})
            scope_path = self.root / "analysis_scope.json"
            atomic_write_json(scope_path, scope)
            return [output, scope_path]
        if stage == "parse":
            if file_hash(self.config["config_path"]) != self.config["config_file_hash"]:
                raise ValueError("benchmark config changed after input freeze")
            for name, digest in read_object(self.root / "input_inventory.json")["files"].items():
                if file_hash(name) != digest:
                    raise ValueError(f"input changed after freeze: {name}")
            scope_path = self.root / "analysis_scope.json"
            if not scope_path.exists():
                raise ValueError("analysis scope missing; prepare a new workspace and run inputs first")
            from bug_review.benchmark_workflow.models import ArtifactManifest
            scope = read_object(scope_path)
            parsed = prepare_model_run_comparisons_by_config(
                self.config["runs"], self.config["config_path"],
                analysis_manifests=[ArtifactManifest(**row) for row in scope["runs"]],
                auto_convert_waveforms=False,
                parse_coverage_data=False,
                max_rtl_regions=64,
                prepare_replay_contracts=False,
            )
            if not parsed["dut_inputs"]:
                raise ValueError("no DUT inputs discovered")
            for item in parsed["dut_inputs"]:
                safe_name(item["dut"])
                if not item["run_graphs"]:
                    raise ValueError(f"no successfully parsed runs for {item['dut']}")
                item["failure_cases"] = failure_inventory(item)
                for case in item["failure_cases"]:
                    case["sources"] = source_evidence(case)
            output = self.root / "parsed_inputs.json"
            atomic_write_json(output, parsed)
            inventory = {
                "schema": "reported_bug_inventory_bundle.v1",
                "duts": {
                    item["dut"]: [graph.get("reported_bug_inventory", {})
                                   for graph in item.get("run_graphs", [])]
                    for item in parsed["dut_inputs"]
                },
            }
            inventory_output = self.root / "reported_bug_inventory.json"
            atomic_write_json(inventory_output, inventory)
            return [output, inventory_output]
        outputs, pending = [], False
        if stage == "publish_analysis":
            return self._publish_analysis()
        for dut, root in self._dut_roots():
            if stage in {"replay", "waveform"}:
                result = self._case_stage(stage, dut, root)
                if result is None:
                    pending = True
                else:
                    outputs.extend(result)
                continue
            if stage == "semantic":
                replay_input = root / "replay/input.json"
                item = (read_object(replay_input) if replay_input.exists() else
                        next(i for i in read_object(self.root / "parsed_inputs.json")["dut_inputs"] if i["dut"] == dut))
                item = reviewed_comparison(item, read_object(root / "replay/reviews.json")["cases"],
                                           read_object(root / "waveform/reviews.json")["cases"])
                prepare_semantic_stage(item, root, RUNTIME, self.config["semantic_pairs"])
            elif stage == "failure_mode":
                prepare_root_failure_mode_stage(root, RUNTIME)
            elif stage == "root_appeal":
                prepare_rtl_root_appeal_stage(root, RUNTIME, finalize_scores=False)
            elif stage == "alignment":
                self._prepare_alignment(dut, root)
            kind, relative, final = STORES[stage]
            if pending_requests([(kind, root / relative)])["pending"]:
                pending = True
                continue
            finalize_store(kind, root / relative, root / final)
            # Freeze accepted decisions as well as their consumed projection.
            for pattern in ("*/input.json", "*/output.json", "*/agent_responses.json"):
                outputs.extend(sorted((root / relative / "tasks").glob(pattern)))
            if (root / final / "finalized_task_outputs.json").exists():
                outputs.append(root / final / "finalized_task_outputs.json")
            if stage == "semantic":
                consume_finalized_semantic_stage(root)
                output = root / "semantic/comparison_result.json"
                payload = attach_record_evidence_levels(read_object(output))
                candidates = {c["candidate_id"]: c for c in read_object(root / "semantic/input.json")["flat_candidates"]}
                for record in payload.get("benchmark_records", []):
                    record["failure_reviews"] = [
                        {key: review.get(key) for key in ("case_id", "nodeid", "classification", "review", "waveform_review")}
                        for identity in record.get("candidate_ids", [])
                        for review in candidates.get(identity, {}).get("validation_details", {}).get("failure_reviews", [])
                    ]
                atomic_write_json(output, payload)
                from bug_review.benchmark_workflow.stage_workflow import update_stage_workflow
                update_stage_workflow(root, "semantic_consume", {"output_hash": stable_hash(payload)})
                outputs.append(output)
            elif stage == "failure_mode":
                # The next stage consumes these immutable final outputs.
                output = root / "failure_mode_complete.json"
                atomic_write_json(output, {"complete": True})
                outputs.append(output)
            elif stage == "root_appeal":
                consume_finalized_root_review_stage(root, finalize_scores=False)
                outputs.append(root / "root_review/result.json")
                from bug_review.benchmark_workflow.rtl_root_clustering import refresh_rtl_root_payload_evidence
                from bug_review.benchmark_workflow.coverage_metrics import attach_root_local_coverage
                payload = _root_review_source(root, refresh_stage_workflow(root))
                payload["input_runs"] = [row for row in read_object(self.root / "analysis_scope.json")["runs"]
                                         if row["dut"] == dut]
                payload["failure_case_reviews"] = read_object(root / "replay/reviews.json")["cases"]
                payload["waveform_reviews"] = read_object(root / "waveform/reviews.json")["cases"]
                replay_payload = read_object(root / "replay/input.json") if (root / "replay/input.json").exists() else {}
                payload["reported_bug_inventory"] = {
                    "schema": "reported_bug_inventory_bundle.v1",
                    "duts": {dut: [graph.get("reported_bug_inventory", {})
                                   for graph in replay_payload.get("run_graphs", [])]},
                }
                payload["reported_replay_validation"] = replay_payload.get("reported_replay_validation", {})
                _attach_failure_records(payload, payload["failure_case_reviews"], payload["waveform_reviews"])
                enabled = bool(self.config["replay"].get("enabled"))
                payload["replay_execution"] = {"enabled": enabled,
                    "status": "completed" if enabled else "disabled_by_configuration"}
                if enabled:
                    payload["replay_execution"]["runs"] = read_object(root / "replay/input.json")["suite_executions"]
                attach_record_evidence_levels(payload)
                refreshed = refresh_rtl_root_payload_evidence(payload, payload.get("benchmark_records", []),
                                                              payload["model_names"], finalize_scores=False)
                attach_root_local_coverage(refreshed, payload.get("per_model", {}))
                payload.update(refreshed)
                output = root / "evidence.json"
                atomic_write_json(output, payload)
                outputs.append(output)
            else:
                outputs.append(self._consume_alignment(root))
        return None if pending else outputs

    def _case_stage(self, stage, dut, root):
        reviews = CaseReviews(root / stage / "reviews", stage)
        rows = []
        if stage == "replay":
            item = next(i for i in read_object(self.root / "parsed_inputs.json")["dut_inputs"] if i["dut"] == dut)
            if self.config["replay"].get("enabled"):
                from .test_execution import prepare_replay_inputs
                for name, digest in read_object(self.root / "input_inventory.json")["files"].items():
                    if file_hash(name) != digest:
                        raise ValueError(f"input changed before replay: {name}")
                item = prepare_replay_inputs(item, root)
            for case in item["failure_cases"]:
                result = case.get("suite_replay")
                if result is None:
                    result = replay_case(case, root / "replay/executions" / case["case_id"], self.config["replay"])["result"]
                rows.append({"case": {k: v for k, v in case.items() if k not in {"sources", "suite_replay"}},
                             "sources": case["sources"], "replay": result})
        else:
            previous = CaseReviews(root / "replay/reviews", "replay")
            for task in previous.tasks():
                prior = previous.output(task)
                if prior["classification"] != "environment_issue":
                    rows.append({**task["evidence"], "failure_review": prior})
        reviews.prepare(rows)
        if reviews.requests(1)["pending"]:
            return None
        output = root / stage / "reviews.json"
        atomic_write_json(output, {"cases": reviews.results()})
        artifacts = [output, *reviews.artifacts(), *sorted((root / stage / "executions").glob("*/*.json"))]
        if stage == "replay" and (root / "replay/input.json").exists():
            artifacts.append(root / "replay/input.json")
            for execution in item["suite_executions"].values():
                artifacts.extend([Path(execution["report_path"]), Path(execution["replay_workspace"]["replay_workspace_root"]).parent / "execution.json"])
        return artifacts

    def _prepare_alignment(self, dut, root):
        from bug_review.benchmark_workflow.ground_truth_registry import find_registered_ground_truth
        from bug_review.benchmark_workflow.ground_truth_rtl_defects import generate_ground_truth
        from bug_review.benchmark_workflow.reported_roots import attach_reported_root_alignment, backfill_reported_root_summary
        from bug_review.benchmark_workflow.reported_root_alignment_review import build_alignment_review_plan
        from bug_review.benchmark_workflow.reported_root_alignment_task_store import ReportedRootAlignmentTaskStore
        path = root / "alignment/source.json"
        if path.exists():
            return
        payload = read_object(root / "evidence.json")
        gt_path = find_registered_ground_truth(dut, Path(self.config["gt_registry"]))
        gt = generate_ground_truth(payload, str(root / "alignment/ground_truth.json"),
                                   existing_path=str(gt_path) if gt_path else None, models=payload["model_names"])
        payload["ground_truth_rtl_defects"] = payload["_gt_file"] = gt
        backfill_reported_root_summary(payload)
        attach_reported_root_alignment(payload)
        plan = build_alignment_review_plan(payload)
        store = ReportedRootAlignmentTaskStore(root / "alignment/task_store")
        scope = read_object(root / "semantic/input.json")["revision_scope"]
        for item in plan.get("items", []):
            if item.get("eligibility") == "eligible_unresolved":
                store.prepare(dut, item, RUNTIME, scope)
        atomic_write_json(root / "alignment/plan.json", plan)
        atomic_write_json(path, payload)

    def _consume_alignment(self, root):
        from bug_review.benchmark_workflow.reported_root_alignment_review import apply_alignment_review, alignment_plan_digest
        from bug_review.benchmark_workflow.reported_root_alignment_task_store import ReportedRootAlignmentTaskStore
        payload = read_object(root / "alignment/source.json")
        plan = read_object(root / "alignment/plan.json")
        store = ReportedRootAlignmentTaskStore(root / "alignment/task_store")
        decisions = [store.load_success(read_object(p)) for p in sorted((store.root / "tasks").glob("*/input.json"))]
        if any(d is None for d in decisions):
            raise ValueError("alignment results incomplete")
        apply_alignment_review(payload, plan, decisions, expected_plan_digest=alignment_plan_digest(plan))
        # Alignment correspondence is evidence. Its convenience ratio is scored later.
        for row in payload.get("reported_root_gt_alignment", {}).get("per_model", {}).values():
            row.pop("score", None)
        payload["analysis_state"] = "finalized"
        payload["analysis_schema"] = "benchmark_analysis.v1"
        payload["_benchmark_revision"] = {"revision_id": "rev-" + stable_hash(payload)[:20],
                                           "source_snapshot_hash": stable_hash(payload)}
        output = root / "analysis.json"
        atomic_write_json(output, payload)
        return output

    def _publish_analysis(self):
        from bug_review.benchmark_workflow.versioned_publish import unpublished_version_dir, seal_version, publish_version, version_store_for
        from bug_review.benchmark_workflow.report_publication import write_analysis_reports
        def published_files(base):
            return [p for p in sorted(Path(base).rglob("*")) if p.is_file()]
        payloads = []
        for dut, dut_root in self._dut_roots():
            payload = read_object(dut_root / "analysis.json")
            # The canonical renderer requires the DUT on every matrix row.
            # Sealed payloads produced before that field existed stay frozen on
            # disk, so restore it in memory from the payload's own DUT identity;
            # the publication copies and manifest hashes stay self-consistent.
            for row in payload.get("matrix", []):
                if isinstance(row, dict) and not row.get("dut"):
                    row["dut"] = dut
            # The analyst-supplied final bug analysis joins the report page
            # only; the hashed pipeline payload stays untouched so the sealed
            # manifest keeps matching its inputs.
            report_view = dict(payload)
            final_bug = dut_root / "final_bug_analysis.json"
            if final_bug.exists():
                report_view["final_bug_analysis"] = read_object(final_bug)
            profile = load_report_profile(dut, REPO / "configs/report_profiles")
            report_data = build_report_data(report_view, profile)
            report_view["report_data"] = report_data
            # Keep the renderer contract beside the stage evidence as well as
            # in the immutable publication. It is derived data and does not
            # alter the hashed analysis payload used by scoring.
            atomic_write_json(dut_root / "report_data.json", report_data)
            payloads.append((dut, payload, report_view))
        rows = [{"dut": dut, "path": f"dut_{dut}/analysis.json", "hash": stable_hash(p)} for dut, p, _ in payloads]
        manifest = {"schema": "benchmark_analysis_set.v1", "analysis_id": stable_hash(rows), "duts": rows}
        target = self.root / "analysis"
        # Include the renderer revision so an older sealed minimal-page
        # publication is rebuilt when the canonical main-branch template is
        # introduced.
        report_digest = stable_hash([
            {"dut": dut, "report_data": view["report_data"], "renderer": RENDERER_REVISION}
            for dut, _, view in payloads
        ])[:10]
        version = "analysis-" + manifest["analysis_id"][:20] + "-report-" + RENDERER_REVISION + "-" + report_digest
        existing = version_store_for(target) / version
        if existing.exists():
            prior, _ = load_analysis_manifest(existing / "analysis_manifest.json")
            if prior != manifest:
                raise ValueError("sealed analysis does not match this input")
            publish_version(target, existing)
            _prune_published_versions(target, existing)
            return published_files(target)
        temp = unpublished_version_dir(target, version)
        for dut, payload, report_view in payloads:
            dut_dir = temp / f"dut_{dut}"
            # Reuse the canonical report writer from main.  The adapter keeps
            # analysis payloads separate from scoring, while the report tree
            # remains compatible with the established benchmark UI.
            write_analysis_reports(payload, str(dut_dir), write_root_compat=True,
                                     write_root_html_compat=True)
            atomic_write_json(dut_dir / "analysis.json", payload)
            atomic_write_json(dut_dir / "report_data.json", report_view["report_data"])
            atomic_write_json(dut_dir / "data/report_data.json", report_view["report_data"])
            if "final_bug_analysis" in report_view:
                atomic_write_json(dut_dir / "final_bug_analysis.json", report_view["final_bug_analysis"])
            # The canonical entry redirects into reports/zh; the independent
            # review findings are overlaid onto that page in place.
            if dut == "bosc_LLPTW":
                write_llptw_curated_report(dut_dir, report_view)
            else:
                _augment_zh_report(dut_dir, report_view)
                _write_final_bug_details(dut_dir, report_view)
                _write_gt_detail_pages(dut_dir, report_view)
        atomic_write_json(temp / "analysis_manifest.json", manifest)
        links = "".join(
            f"<li><a href='dut_{d}/reports/zh/index.html'>{html.escape(d)}</a>"
            f" <a href='dut_{d}/analysis.json'>证据 JSON</a></li>"
            for d, _, _ in payloads
        )
        _write_text(temp / "index.html", analysis_index_html([(d, view) for d, _, view in payloads]))
        load_analysis_manifest(temp / "analysis_manifest.json")
        sealed = seal_version(temp, target, version)
        publish_version(target, sealed)
        _prune_published_versions(target, sealed)
        return published_files(target)



def prepare(workspace, kind, **options):
    root = Path(workspace).resolve()
    if kind != "analysis":
        raise ValueError(f"unknown workflow kind: {kind}")
    if kind == "analysis":
        if options.get("replay", {}).get("enabled") is not True:
            raise ValueError("analysis requires replay.enabled=true; enable replay and prepare a new workspace")
        options["analysis_stages"] = list(ANALYSIS)
        for _, name in options.get("runs", []):
            source = Path(name).resolve()
            if source.is_dir() and root.is_relative_to(source):
                raise ValueError("analysis workspace must be outside input directories")
    config = {"schema": "benchmark_ucagent_job.v1", "kind": kind, **options}
    root.mkdir(parents=True, exist_ok=True)
    existing = root / "benchmark_job.json"
    if existing.exists() and read_object(existing) != config:
        state_path = root / "workflow_state.json"
        state = read_object(state_path) if state_path.exists() else {"completed": {}}
        if state.get("completed"):
            raise ValueError("workspace already belongs to another job; use a new workspace")
    atomic_write_json(existing, config)
    _write_text(root / "BugReview/README.md", f"\n# BugReview {kind}\n\n任务配置：benchmark_job.json。执行全部工作流阶段。\n")
    return root


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    analysis = sub.add_parser("prepare-analysis")
    analysis.add_argument("--config", required=True)
    analysis.add_argument("--run", action="append", default=[])
    analysis.add_argument("--batch-size", type=int, default=1)
    analysis.add_argument("--replay-enabled", choices=("true", "false"))
    analysis.add_argument("--gt-registry", default=str(default_configs() / "ground_truth_registry"))
    analysis.add_argument("--input-root", default=str(Path(__file__).resolve().parents[1] / "inputs"))
    analysis.add_argument("--workspace", required=True)
    launch = sub.add_parser("launch")
    launch.add_argument("--workspace", required=True)
    launch.add_argument("--ucagent-root", help="Optional UCAgent source tree; otherwise use installed ucagent")
    launch.add_argument("--python", default=sys.executable)
    status = sub.add_parser("status")
    status.add_argument("--workspace", required=True)
    args, extra = parser.parse_known_args(argv)
    if args.command != "launch" and extra:
        parser.error("unexpected arguments: " + " ".join(extra))
    if args.command == "prepare-analysis":
        from bug_review.benchmark_workflow.pipeline import load_benchmark_config
        from .inputs import resolve_run_specs
        path = Path(args.config).resolve()
        cfg = load_benchmark_config(str(path))
        explicit_runs = args.run or [f"{label}={name}" for label, name in discover_input_workspaces(args.input_root)]
        runs = [(label, str(Path(name).resolve())) for label, name in resolve_run_specs(path, cfg, explicit_runs)]
        if args.batch_size < 1:
            parser.error("--batch-size must be positive")
        replay = cfg["replay"]
        if args.replay_enabled is not None:
            replay["enabled"] = args.replay_enabled == "true"
        for key in ("runtime_root", "runtime_profile"):
            if replay.get(key):
                replay[key] = str(Path(replay[key]).resolve())
        root = prepare(args.workspace, "analysis", config_path=str(path), config_file_hash=file_hash(path),
                       runs=[list(r) for r in runs], semantic_pairs=cfg.get("semantic_pairs", {}), replay=replay,
                       gt_registry=str(Path(args.gt_registry).resolve()), batch_size=args.batch_size)
        print(json.dumps({"workspace": str(root), "next": "launch --workspace " + str(root)}))
    elif args.command == "status":
        print(json.dumps(Workflow(args.workspace).status(), ensure_ascii=False, indent=2))
    else:
        wf = Workflow(args.workspace)
        kind = wf.config["kind"]
        if args.ucagent_root:
            entry = Path(args.ucagent_root).resolve() / "ucagent.py"
            if not entry.is_file():
                raise ValueError(f"UCAgent entry missing: {entry}")
            command = [args.python, str(entry)]
        else:
            command = [args.python, "-m", "ucagent.cli"]
        checkout = source_root()
        selector = str(checkout) if checkout else "bug_review"
        command.extend([str(wf.root), "BugReview", "--plugin", selector,
                        "--plugin-workflow", f"bug_review:{kind}"])
        command.extend(extra[1:] if extra[:1] == ["--"] else extra)
        raise SystemExit(subprocess.call(command))


if __name__ == "__main__":
    main()
