"""Render and verify a self-contained V3 module report from indexed records."""

from __future__ import annotations

import html
import json
from pathlib import Path
import re

from .json_io import read_object
from .review_store import load_record, source_lines
from .review_validation import review_incomplete


def escape(value: object) -> str:
    """Escape one displayed value without dropping non-ASCII source text."""
    return html.escape(str(value if value is not None else ""))


def page(title: str, body: str) -> str:
    """Wrap one report page with accessible shared colors and responsive layout."""
    return ("<!doctype html><html lang='en'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width'>"
            f"<title>{escape(title)}</title>"
            "<style>:root{color-scheme:light;--bg:#F7F9FC;--ink:#101828;--muted:#475467;"
            "--line:#D0D5DD;--brand:#1E3A5F}*{box-sizing:border-box}body{margin:0;background:var(--bg);"
            "color:var(--ink);font:16px/1.55 system-ui,-apple-system,sans-serif}main{max-width:1180px;"
            "margin:auto;padding:28px 20px 72px}h1{font-size:clamp(1.7rem,3vw,2.5rem);line-height:1.2;"
            "margin:8px 0 12px;overflow-wrap:anywhere}h2{font-size:1.25rem;margin:0 0 14px}"
            "p{margin:8px 0 14px}a{color:#175CD3;text-underline-offset:3px}a:focus-visible,summary:focus-visible"
            "{outline:3px solid #84CAFF;outline-offset:3px}.crumb{font-size:.9rem;color:var(--muted);margin-bottom:18px}"
            ".hero,.card{background:#fff;border:1px solid #E4E7EC;border-radius:16px;box-shadow:0 3px 16px #10182808}"
            ".hero{padding:28px;margin-bottom:18px;border-top:5px solid var(--brand)}.card{padding:22px;margin:18px 0}"
            ".eyebrow{color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.06em;font-size:.75rem}"
            ".lead{font-size:1.1rem;max-width:85ch}.muted{color:var(--muted)}.mono,code,pre{font-family:ui-monospace,SFMono-Regular,monospace;overflow-wrap:anywhere}"
            ".badge{display:inline-block;border-radius:999px;padding:3px 10px;font-size:.82rem;font-weight:700;margin-right:7px}"
            ".confirmed,.confirmed_dut,.dut_bug,.failed{color:#B42318;background:#FEECEB}.inconclusive,.suspected_dut,.insufficient_evidence,.spec_ambiguous,.incomplete{color:#B54708;background:#FFF2D8}"
            ".environment,.test_implementation,.spec_misread{color:#6941C6;background:#F1EBFF}.passed,.complete{color:#027A48;background:#DFF7E9}"
            ".refuted,.not_dut_bug,.not_run,.skipped,.xfailed{color:#475467;background:#EAECF0}.error,.xpassed{color:#B42318;background:#FEECEB}"
            ".kpis,.three,.two{display:grid;gap:14px}.kpis{grid-template-columns:repeat(6,minmax(0,1fr))}"
            ".three{grid-template-columns:repeat(3,minmax(0,1fr))}.two{grid-template-columns:repeat(2,minmax(0,1fr))}"
            ".tile{background:#fff;border:1px solid #E4E7EC;border-radius:12px;padding:16px;min-width:0}"
            ".tile strong{display:block;font-size:1.65rem;line-height:1.2}.tile small{color:var(--muted)}"
            ".table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%}th,td{padding:11px 12px;text-align:left;"
            "border-bottom:1px solid #EAECF0;vertical-align:top;overflow-wrap:anywhere}th{color:var(--muted);font-size:.8rem;text-transform:uppercase}"
            "tr:hover td{background:#F9FAFB}details{border-top:1px solid #EAECF0;padding:11px 0}summary{cursor:pointer;font-weight:650}"
            "pre{white-space:pre-wrap;background:#F2F4F7;border-radius:10px;padding:14px;font-size:.84rem}"
            "ol,ul{padding-left:22px}li{margin:7px 0}.chain li{padding:4px 0}"
            "@media(max-width:760px){main{padding:18px 12px 48px}.hero{padding:20px}.card{padding:17px}"
            ".kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.three,.two{grid-template-columns:1fr}}"
            "</style><main>" + body + "</main></html>")


def badge(label: str, tone: str) -> str:
    """Show a semantic state with both visible text and color."""
    safe_tone = tone if re.fullmatch(r"[a-z_]+", tone) else "refuted"
    return f"<span class='badge {safe_tone}'>{escape(label)}</span>"


def source_item(reference: str, source_root: Path) -> str:
    """Embed an exact source excerpt so public pages do not depend on run files."""
    if not reference:
        return ""
    try:
        excerpt = source_lines(source_root, reference, max_lines=12)
    except (ValueError, OSError):
        return f"<li>{escape(reference)} (unverified source)</li>"
    return (f"<li><details><summary class='mono'>{escape(reference)}</summary>"
            f"<pre>{escape(excerpt['text'])}</pre></details></li>")


def render_pages(output: Path, index, cases: dict, bugs: dict, roots, coverage) -> tuple[dict[str, str], dict]:
    """Build module, failed-case and Bug pages plus a cross-check manifest."""
    name = index.workspace["name"]
    source_root = output / "inputs" / name
    manifest = load_record(output, index.manifest_path, "manifest")
    summary = load_record(output, index.replay_summary_path, "replay_summary")
    environment = load_record(output, index.environment_path, "environment")
    reconciliation = load_record(output, index.reconciliation_path, "reconciliation")
    root_by_id = {root.root_id: root for root in roots.roots}
    pages: dict[str, str] = {}
    manifest_bugs, manifest_cases = [], []
    case_names = {case_id: f"case_{position:04d}.html"
                  for position, case_id in enumerate(index.cases, 1)
                  if cases[case_id].replay.status in {"failed", "error", "xpassed"}}
    for case_id, filename in case_names.items():
        case = cases[case_id]
        analysis = case.failure_analysis
        wave = case.waveform
        bug_links = "".join(f"<li><a href='../bugs/bug_{index.bug_order.index(bug_id) + 1:04d}.html'>"
                            f"{escape(bug_id)}</a></li>" for bug_id in case.bug_ids)
        viewer = (f"<a href='{html.escape(wave.viewer_url, quote=True)}'>Open signed waveform</a>"
                  if wave.viewer_url.startswith(("http://", "https://", "/surfer/")) else "Unavailable")
        body = ("<nav class='crumb'><a href='../index.html'>Module overview</a> / Failed case</nav>"
                "<header class='hero'><div class='eyebrow'>Case analysis</div>"
                f"<h1 class='mono'>{escape(case_id)}</h1>"
                f"{badge(case.replay.status, case.replay.status)}{badge(analysis.category, analysis.category)}"
                f"<p class='muted'>Failure phase: {escape(analysis.phase)}; "
                f"baseline: {escape(case.replay.baseline_id or 'unavailable')}</p>"
                f"<p class='lead'>{escape(analysis.scenario or analysis.unresolved or 'Scenario unavailable')}</p></header>"
                "<section class='three'><div class='tile'><div class='eyebrow'>Spec expected</div>"
                f"<p>{escape(analysis.spec_expected or 'Unresolved')}</p></div>"
                "<div class='tile'><div class='eyebrow'>Test expected</div>"
                f"<p>{escape(analysis.test_expected or 'Unresolved')}</p></div>"
                "<div class='tile'><div class='eyebrow'>Observed</div>"
                f"<p>{escape(analysis.actual or 'Unresolved')}</p></div></section>"
                f"<section class='card'><h2>Why this case failed</h2><p>{escape(analysis.rationale)}</p>"
                f"<p class='muted'>Remaining gap: {escape(analysis.unresolved or 'None recorded')}</p></section>"
                "<section class='card'><h2>Waveform evidence</h2>"
                f"{badge(wave.conclusion, wave.conclusion)} {viewer}"
                f"<p>Observed: {escape(wave.observed_behavior or wave.diagnostic or 'No waveform conclusion')}</p>"
                f"<p>Alignment: {escape(wave.alignment_evidence or 'Unavailable')}</p>"
                f"<p class='muted mono'>Receipt: {escape(wave.receipt_id or 'Unavailable')}</p>"
                "<details><summary>Window and signal groups</summary>"
                f"<pre>{escape(json.dumps({'window': wave.analysis_window, 'signal_groups': wave.signal_groups}, ensure_ascii=False, indent=2))}</pre>"
                "</details></section>"
                f"<section class='card'><h2>Associated Bugs</h2><ul>{bug_links or '<li>None</li>'}</ul></section>"
                "<section class='card'><h2>Supporting records</h2>"
                f"<p>Test review: {escape(case.test_review.classification)}; "
                f"correctness confirmed: {escape(case.test_review.correctness_confirmed)}</p>"
                f"<ul>{''.join(source_item(ref, source_root) for ref in analysis.evidence_refs) or '<li>No source references</li>'}</ul>"
                "</section>")
        pages[f"report/cases/{filename}"] = page(f"{name}: {case_id}", body)
        manifest_cases.append({"case_id": case_id, "page": f"cases/{filename}",
                               "category": analysis.category, "receipt": wave.receipt_id,
                               "viewer": wave.viewer_url, "bug_ids": case.bug_ids})
    bug_rows = []
    for position, bug_id in enumerate(index.bug_order, 1):
        entry, bug = index.bugs[bug_id], bugs[bug_id]
        decision = bug.decision
        filename = f"bug_{position:04d}.html"
        spec_refs = list(dict.fromkeys(filter(None, [decision.spec_ref, *bug.spec_refs, *entry.spec_candidates])))
        rtl_refs = list(dict.fromkeys(filter(None, [decision.rtl_ref, *bug.rtl_refs, *entry.rtl_candidates])))
        case_links = []
        receipts, viewers = [], []
        for case_id in bug.case_ids:
            case = cases[case_id]
            case_link = (f"<a href='../cases/{case_names[case_id]}'>{escape(case_id)}</a>"
                         if case_id in case_names else escape(case_id))
            case_links.append(f"<li>{case_link}: {escape(case.replay.status)}; "
                              f"attribution {escape(case.failure_analysis.category)}; "
                              f"receipt {escape(case.waveform.receipt_id)}</li>")
            if case.waveform.receipt_id:
                receipts.append(case.waveform.receipt_id)
                viewers.append(case.waveform.viewer_url)
        root = root_by_id.get(decision.root_id)
        aggregate_only = sorted(set(entry.aggregate_case_ids) - set(entry.case_ids))
        body = ("<nav class='crumb'><a href='../index.html'>Module overview</a> / Bug decision</nav>"
                "<header class='hero'><div class='eyebrow'>Bug review</div>"
                f"<h1 class='mono'>{escape(bug_id)}</h1>{badge(decision.verdict, decision.verdict)}"
                f"<span class='muted'>Review confidence: {escape(decision.review_confidence if decision.review_confidence is not None else 'undetermined')}"
                f" · reported: {escape(entry.reported_confidence if entry.reported_confidence is not None else 'unavailable')}"
                f" · origin: {escape(entry.origin)}</span>"
                f"<p class='lead'>{escape(decision.rationale or 'Decision rationale unavailable')}</p>"
                f"<p class='muted'>Root group: {escape(decision.root_id or 'None')}</p></header>"
                "<section class='three'><div class='tile'><div class='eyebrow'>Validation scenario</div>"
                f"<p>{escape(bug.validation_scenario or 'Unresolved')}</p></div>"
                "<div class='tile'><div class='eyebrow'>Expected</div>"
                f"<p>{escape(bug.expected_behavior or 'Unresolved')}</p></div>"
                "<div class='tile'><div class='eyebrow'>Observed</div>"
                f"<p>{escape(bug.observed_behavior or 'Unresolved')}</p></div></section>"
                "<section class='card'><h2>Evidence chain</h2><ol class='chain'>"
                f"<li><strong>Reproduced cases</strong><ul>{''.join(case_links) or '<li>None</li>'}</ul></li>"
                f"<li><strong>Signed waveforms</strong>: {escape(', '.join(receipts) or 'Unavailable')}</li>"
                f"<li><strong>Spec requirement</strong>: {escape(decision.spec_ref or 'Unresolved')}</li>"
                f"<li><strong>RTL first error</strong>: {escape(decision.rtl_ref or 'Unresolved')}"
                f" — {escape(decision.first_error or 'Unresolved')}</li>"
                f"<li><strong>Causal chain</strong>: {escape(decision.causal_chain or 'Unresolved')}</li>"
                "</ol></section>"
                "<section class='card'><h2>Root cause</h2>"
                f"<p class='mono'>{escape(root.root_id if root else 'None')}</p>"
                f"<p>{escape(root.first_error if root else 'No confirmed root cause')}</p>"
                f"<p>{escape(root.causal_chain if root else '')}</p></section>"
                "<section class='card'><h2>Source evidence</h2>"
                f"<details><summary>Spec references ({len(spec_refs)})</summary><ul>{''.join(source_item(ref, source_root) for ref in spec_refs)}</ul></details>"
                f"<details><summary>RTL references ({len(rtl_refs)})</summary><ul>{''.join(source_item(ref, source_root) for ref in rtl_refs)}</ul></details>"
                f"<details><summary>Original claims ({len(entry.analysis_refs) + bool(entry.summary_ref)})</summary>"
                f"<ul>{''.join(source_item(ref, source_root) for ref in [entry.summary_ref, *entry.analysis_refs])}</ul></details>"
                f"<details><summary>Report-level case list ({len(entry.aggregate_case_ids)})</summary>"
                f"<p>Listed only by the aggregate report: {escape(', '.join(aggregate_only) or 'None')}</p>"
                f"<ul>{''.join(source_item(ref, source_root) for ref in entry.aggregate_refs)}</ul></details>"
                "</section>")
        pages[f"report/bugs/{filename}"] = page(f"{name}: {bug_id}", body)
        bug_rows.append(f"<tr><td><a class='mono' href='bugs/{filename}'>{escape(bug_id)}</a>"
                        f"<div class='muted'>{escape(bug.validation_scenario)}</div></td>"
                        f"<td>{escape(entry.origin)}</td><td>{badge(decision.verdict, decision.verdict)}</td>"
                        f"<td>{escape(decision.root_id or '—')}</td><td>{len(bug.case_ids)}</td></tr>")
        manifest_bugs.append({"bug_id": bug_id, "page": f"bugs/{filename}",
                              "root_id": decision.root_id, "receipts": receipts,
                              "viewers": viewers, "spec_refs": spec_refs, "rtl_refs": rtl_refs})
    case_rows = "".join(f"<tr><td><a class='mono' href='{item['page']}'>{escape(item['case_id'])}</a></td>"
                        f"<td>{badge(item['category'], item['category'])}</td>"
                        f"<td>{escape(', '.join(item['bug_ids']) or 'None')}</td></tr>"
                        for item in manifest_cases)
    metric_items = []
    for key in ("line", "functional"):
        metric = coverage.metrics.get(key)
        if metric and metric.status == "available":
            value = f"{metric.numerator}/{metric.denominator}" if metric.denominator is not None else metric.value
            metric_items.append(f"<li>{escape(key)}: {escape(value)}; {escape(metric.run_scope)}; "
                                f"{escape(metric.basis)}; {escape(metric.source_ref)}</li>")
        else:
            metric_items.append(f"<li>{escape(key)}: unavailable; {escape(metric.reason if metric else '')}</li>")
    missing = [case_id for case_id in manifest.collected if summary.outcomes.get(case_id) == "not_run"]
    incomplete = review_incomplete(manifest, cases, environment)
    status = "incomplete" if incomplete else "complete"
    findings = "".join(
        f"<li>{escape(item.category)} ({escape(item.status)}): {escape(item.observation)}; "
        f"impact: {escape(item.impact)}; cases: {escape(', '.join(item.case_ids))}</li>"
        for item in environment.findings)
    quality = "".join(
        f"<li>{escape(label)}: {escape(getattr(environment, field))}</li>"
        for label, field in (("Collection", "collection_review"),
                             ("Execution", "execution_review"),
                             ("Fixture/reset", "fixture_reset_review"),
                             ("Driver/sampling", "driver_sampling_review"),
                             ("Reference model", "reference_model_review"),
                             ("Seed/reproducibility", "seed_reproducibility_review")))
    confirmed_count = sum(bug.decision.verdict == "confirmed" for bug in bugs.values())
    unresolved_count = sum(bug.decision.verdict == "inconclusive" for bug in bugs.values())
    overview = ("<nav class='crumb'><a href='../../index.html'>All modules</a> / Module report</nav>"
                "<header class='hero'><div class='eyebrow'>Verification review</div>"
                f"<h1>{escape(name)}</h1>{badge(status, status)}"
                f"<p class='lead'>Complete replay, failure attribution and Bug decisions for this module.</p>"
                f"<p class='muted'>Collection errors: {len(manifest.collection_errors)}; "
                f"new DUT candidates: {len(reconciliation.discovered_bug_ids)}</p></header>"
                "<section class='kpis'>"
                f"<div class='tile'><small>Collected</small><strong>{len(manifest.collected)}</strong></div>"
                f"<div class='tile'><small>Executed</small><strong>{len(manifest.collected) - len(missing)}</strong></div>"
                f"<div class='tile'><small>Failed / error / xpass</small><strong>{len(case_names)}</strong></div>"
                f"<div class='tile'><small>Confirmed Bugs</small><strong>{confirmed_count}</strong></div>"
                f"<div class='tile'><small>Unexecuted</small><strong>{len(missing)}</strong></div>"
                f"<div class='tile'><small>Undecided Bugs</small><strong>{unresolved_count}</strong></div>"
                "</section>"
                "<section class='card'><h2>Coverage and scope</h2>"
                f"<ul>{''.join(metric_items)}</ul></section>"
                "<section class='card'><h2>Bug decisions</h2><div class='table-wrap'>"
                "<table><tr><th>Bug and scenario</th><th>Origin</th><th>Decision</th><th>Root</th><th>Cases</th></tr>"
                f"{''.join(bug_rows)}</table></div></section>"
                "<section class='card'><h2>Failed cases</h2><div class='table-wrap'>"
                f"<table><tr><th>Case</th><th>Attribution</th><th>Bugs</th></tr>{case_rows}</table></div></section>"
                "<section class='card'><h2>Environment quality</h2>"
                f"<details><summary>Six quality reviews</summary><ul>{quality}</ul></details>"
                f"<ul>{findings or '<li>No findings recorded</li>'}</ul></section>"
                "<section class='card'><h2>Original report reconciliation</h2>"
                f"<p>{escape(reconciliation.statistics_review)}</p>"
                f"<p>Failed cases without a Bug: {escape(', '.join(reconciliation.unreported_failed_cases) or 'None')}</p>"
                f"<p>Earlier failures now passing: {escape(', '.join(reconciliation.previously_failed_now_passed) or 'None')}</p>"
                f"<details><summary>Run source and collection diagnostics</summary>"
                f"<p class='mono'>{escape(index.workspace.get('source_path', ''))}</p>"
                f"<pre>{escape(chr(10).join(manifest.collection_errors) or 'None')}</pre></details></section>")
    pages["report/index.html"] = page(f"{name} Bug Review", overview)
    report_manifest = {"schema": "bug_review_report.v2", "workspace": name,
                       "review_status": status, "pages": sorted(p.removeprefix("report/") for p in pages),
                       "bugs": manifest_bugs, "cases": manifest_cases,
                       "collected": len(manifest.collected), "unexecuted": missing}
    return pages, report_manifest


def verify_pages(output: Path, index, cases: dict, bugs: dict, roots) -> None:
    """Compare each page and its internal links with the active indexed records."""
    coverage = load_record(output, index.coverage_path, "coverage")
    pages, expected_manifest = render_pages(output, index, cases, bugs, roots, coverage)
    for filename, expected in pages.items():
        path = output / filename
        if not path.is_file() or path.read_text(encoding="utf-8") != expected:
            raise ValueError(f"report page missing or differs from review records: {filename}")
        for href in re.findall(r"href='([^']+)'", expected):
            if href.startswith(("http://", "https://", "/surfer/", "#")):
                continue
            if filename == "report/index.html" and href == "../../index.html":
                continue
            target = (path.parent / href).resolve()
            if not target.is_file():
                raise ValueError(f"broken report link in {filename}: {href}")
    if read_object(output / "report/report_manifest.json") != expected_manifest:
        raise ValueError("report/report_manifest.json differs from current pages")
