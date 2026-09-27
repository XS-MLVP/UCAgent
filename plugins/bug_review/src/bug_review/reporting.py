"""Render and verify localized module, case, Bug, and source report pages."""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import unquote, urldefrag

from .json_io import read_object
from .review_store import REF_PATTERN, load_record, source_lines
from .review_validation import review_incomplete

LABELS = json.loads((Path(__file__).parent / "lang/zh/report.json").read_text(encoding="utf-8"))
CONFIDENCE_FLOOR = 0.8


def escape(value: object) -> str:
    """Escape a value inserted into HTML text or a quoted attribute."""
    return html.escape(str(value if value is not None else ""), quote=True)


def label(value: str) -> str:
    """Return the localized display name of a stable record value."""
    return LABELS.get(value, value)


def page(title: str, body: str) -> str:
    """Wrap a report page with shared responsive layout and semantic colors."""
    return ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width'>"
            f"<title>{escape(title)}</title>"
            "<style>:root{color-scheme:light;--bg:#F5F7FB;--ink:#142235;--muted:#52647A;"
            "--brand:#175CD3;--line:#D8E2EE}*{box-sizing:border-box}"
            "body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,sans-serif}"
            "main{max-width:1180px;margin:auto;padding:28px 20px 72px}h1{font-size:clamp(1.7rem,3vw,2.5rem);"
            "line-height:1.2;margin:8px 0 12px;overflow-wrap:anywhere}h2{font-size:1.25rem;margin:0 0 14px}"
            "p{margin:8px 0 14px}a{color:var(--brand);text-underline-offset:3px}"
            "a:focus-visible,summary:focus-visible{outline:3px solid #84CAFF;outline-offset:3px}"
            ".crumb{font-size:.9rem;color:var(--muted);margin-bottom:18px}"
            ".hero,.card{background:#fff;border:1px solid #DCE5F0;border-radius:16px;box-shadow:0 3px 16px #14223509}"
            ".hero{padding:28px;margin-bottom:18px;border-top:5px solid var(--brand)}.card{padding:22px;margin:18px 0}"
            ".eyebrow{color:var(--muted);font-weight:700;letter-spacing:.035em;font-size:.82rem}"
            ".lead{font-size:1.1rem;max-width:85ch}.muted{color:var(--muted)}"
            ".mono,code,pre{font-family:ui-monospace,SFMono-Regular,monospace;overflow-wrap:anywhere}"
            ".badge{display:inline-block;border-radius:999px;padding:3px 10px;font-size:.82rem;font-weight:700;margin-right:7px}"
            ".confirmed,.confirmed_dut,.dut_bug,.failed{color:#B42318;background:#FEECEB}"
            ".inconclusive,.suspected_dut,.insufficient_evidence,.spec_ambiguous,.incomplete{color:#B54708;background:#FFF2D8}"
            ".environment,.test_implementation,.spec_misread{color:#6941C6;background:#F1EBFF}"
            ".passed,.complete{color:#027A48;background:#DFF7E9}"
            ".refuted,.not_dut_bug,.not_run,.skipped,.xfailed{color:#475467;background:#EAECF0}"
            ".error,.xpassed{color:#B42318;background:#FEECEB}"
            ".kpis,.three{display:grid;gap:14px}.kpis{grid-template-columns:repeat(6,minmax(0,1fr))}"
            ".three{grid-template-columns:repeat(3,minmax(0,1fr))}"
            ".tile{background:#fff;border:1px solid #DCE5F0;border-radius:12px;padding:16px;min-width:0}"
            ".tile strong{display:block;font-size:1.65rem;line-height:1.2}.tile small{color:var(--muted)}"
            ".table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%}th,td{padding:11px 12px;"
            "text-align:left;border-bottom:1px solid #E8EDF3;vertical-align:top;overflow-wrap:anywhere}"
            "th{color:var(--muted);font-size:.84rem}tr:hover td{background:#F6F9FD}"
            "details{border-top:1px solid #E8EDF3;padding:11px 0}summary{cursor:pointer;font-weight:650}"
            "pre{white-space:pre-wrap;background:#F2F5F9;border-radius:10px;padding:14px;font-size:.84rem}"
            "ol,ul{padding-left:22px}li{margin:7px 0}.chain li{padding:4px 0}"
            ".source-table td:first-child{width:44%;font-family:ui-monospace,SFMono-Regular,monospace}"
            ".source-code{background:#F7F9FC;border:1px solid var(--line);border-radius:10px;overflow:auto}"
            ".src-line{display:flex;white-space:pre;width:max-content;min-width:100%;font:13px/1.6 ui-monospace,SFMono-Regular,monospace}"
            ".src-line .line-no{position:sticky;left:0;display:inline-block;width:5.5em;padding:0 .8em;text-align:right;"
            "color:#667085;background:#E9EEF5;user-select:none;margin-right:1em}"
            ".src-line.marked{background:#FFF0B5}.src-line.marked .line-no{background:#F9DB75;color:#593E00}"
            "@media(max-width:760px){main{padding:18px 12px 48px}.hero{padding:20px}.card{padding:17px}"
            ".kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.three{grid-template-columns:1fr}}"
            "</style><main>" + body + "</main></html>")


def badge(value: str) -> str:
    """Show an accessible state label with semantic color."""
    tone = value if re.fullmatch(r"[a-z_]+", value) else "refuted"
    return f"<span class='badge {tone}'>{escape(label(value))}</span>"


def render_pages(output: Path, index, cases: dict, bugs: dict, roots, coverage) -> tuple[dict[str, str], dict]:
    """Build public pages and their exact cross-check manifest from active records."""
    name = index.workspace["name"]
    source_root = output / "inputs" / name
    manifest = load_record(output, index.manifest_path, "manifest")
    summary = load_record(output, index.replay_summary_path, "replay_summary")
    environment = load_record(output, index.environment_path, "environment")
    reconciliation = load_record(output, index.reconciliation_path, "reconciliation")
    root_by_id = {root.root_id: root for root in roots.roots}
    pages: dict[str, str] = {}
    source_catalog: dict[str, dict] = {}
    manifest_bugs, manifest_cases = [], []
    none_li = f"<li>{escape(LABELS['none'])}</li>"

    def source_link(reference: str, prefix: str = "../sources/") -> str:
        """Create one full source page and link to its exact highlighted line range."""
        match = REF_PATTERN.fullmatch(reference) if isinstance(reference, str) else None
        if match is None:
            return escape(reference)
        try:
            source_lines(source_root, reference, max_lines=1)
        except (ValueError, OSError):
            return f"{escape(reference)} ({escape(LABELS['unverified_source'])})"
        relative, start, end = match.group(1), int(match.group(2)), int(match.group(3) or match.group(2))
        if relative not in source_catalog:
            text_lines = (source_root / relative).read_text(encoding="utf-8", errors="replace").splitlines()
            filename = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16] + ".html"
            rows = "".join(f"<div class='src-line' id='L{number}'><span class='line-no'>{number}</span>"
                           f"<span>{escape(line) or ' '}</span></div>"
                           for number, line in enumerate(text_lines, 1))
            body = (f"<nav class='crumb'><a href='../index.html'>{escape(LABELS['module'])}</a></nav>"
                    f"<header class='hero'><div class='eyebrow'>{escape(LABELS['source_preview'])}</div>"
                    f"<h1 class='mono'>{escape(relative)}</h1><p>{escape(LABELS['source_hint'])}</p></header>"
                    f"<section class='source-code'>{rows}</section>"
                    "<script>const m=/^#L(\\d+)(?:-L(\\d+))?$/.exec(location.hash);"
                    "if(m){const a=+m[1],b=+(m[2]||m[1]);for(let i=a;i<=b;i++){"
                    "const e=document.getElementById('L'+i);if(e)e.classList.add('marked')}"
                    "document.getElementById('L'+a)?.scrollIntoView({block:'center'})}</script>")
            pages[f"report/sources/{filename}"] = page(relative, body)
            source_catalog[relative] = {"path": relative, "page": f"sources/{filename}",
                                        "line_count": len(text_lines)}
        filename = source_catalog[relative]["page"].removeprefix("sources/")
        href = f"{prefix}{filename}#L{start}-L{end}"
        return f"<a href='{escape(href)}'>{escape(reference)}</a>"

    def source_list(references: list[str]) -> str:
        """Render a bounded source-reference list with full-file links."""
        return "".join(f"<li>{source_link(ref)}</li>" for ref in references if ref) or f"<li>{escape(LABELS['no_refs'])}</li>"

    case_names = {case_id: f"case_{position:04d}.html"
                  for position, case_id in enumerate(index.cases, 1)
                  if cases[case_id].replay.status in {"failed", "error", "xpassed"}}
    for case_id, filename in case_names.items():
        case = cases[case_id]
        analysis, wave = case.failure_analysis, case.waveform
        bug_links = "".join(f"<li><a href='../bugs/bug_{index.bug_order.index(bug_id) + 1:04d}.html'>"
                            f"{escape(bug_id)}</a></li>" for bug_id in case.bug_ids)
        viewer = (f"<a href='{escape(wave.viewer_url)}'>{escape(LABELS['open_wave'])}</a>"
                  if wave.viewer_url.startswith(("http://", "https://", "/surfer/"))
                  else escape(LABELS["unavailable"]))
        body = (f"<nav class='crumb'><a href='../index.html'>{escape(LABELS['module'])}</a> / {escape(LABELS['failed_case'])}</nav>"
                f"<header class='hero'><div class='eyebrow'>{escape(LABELS['case_analysis'])}</div>"
                f"<h1 class='mono'>{escape(case_id)}</h1>{badge(case.replay.status)}{badge(analysis.category)}"
                f"<p class='muted'>{escape(LABELS['failure_phase'])}: {escape(analysis.phase)}; "
                f"{escape(LABELS['baseline'])}: {escape(case.replay.baseline_id or LABELS['unavailable'])}</p>"
                f"<p class='lead'>{escape(analysis.scenario or analysis.unresolved or LABELS['unresolved'])}</p></header>"
                f"<section class='three'><div class='tile'><div class='eyebrow'>{escape(LABELS['spec_expected'])}</div>"
                f"<p>{escape(analysis.spec_expected or LABELS['unresolved'])}</p></div>"
                f"<div class='tile'><div class='eyebrow'>{escape(LABELS['test_expected'])}</div>"
                f"<p>{escape(analysis.test_expected or LABELS['unresolved'])}</p></div>"
                f"<div class='tile'><div class='eyebrow'>{escape(LABELS['observed'])}</div>"
                f"<p>{escape(analysis.actual or LABELS['unresolved'])}</p></div></section>"
                f"<section class='card'><h2>{escape(LABELS['failure_reason'])}</h2><p>{escape(analysis.rationale)}</p>"
                f"<p class='muted'>{escape(LABELS['remaining_gap'])}: {escape(analysis.unresolved or LABELS['none'])}</p></section>"
                f"<section class='card'><h2>{escape(LABELS['waveform'])}</h2>{badge(wave.conclusion)} {viewer}"
                f"<p>{escape(LABELS['wave_observed'])}: {escape(wave.observed_behavior or wave.diagnostic or LABELS['unresolved'])}</p>"
                f"<p>{escape(LABELS['alignment'])}: {escape(wave.alignment_evidence or LABELS['unavailable'])}</p>"
                f"<p class='muted mono'>{escape(LABELS['receipt'])}: {escape(wave.receipt_id or LABELS['unavailable'])}</p>"
                f"<details><summary>{escape(LABELS['window_signals'])}</summary>"
                f"<pre>{escape(json.dumps({'window': wave.analysis_window, 'signal_groups': wave.signal_groups}, ensure_ascii=False, indent=2))}</pre>"
                "</details></section>"
                f"<section class='card'><h2>{escape(LABELS['associated_bugs'])}</h2><ul>{bug_links or none_li}</ul></section>"
                f"<section class='card'><h2>{escape(LABELS['supporting'])}</h2>"
                f"<p>{escape(LABELS['test_review'])}: {escape(label(case.test_review.classification))}; "
                f"{escape(LABELS['confirmed_correct'])}: {escape(case.test_review.correctness_confirmed)}</p>"
                f"<ul>{source_list(analysis.evidence_refs)}</ul></section>")
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
        case_links, receipts, viewers = [], [], []
        for case_id in bug.case_ids:
            case = cases[case_id]
            case_link = (f"<a href='../cases/{case_names[case_id]}'>{escape(case_id)}</a>"
                         if case_id in case_names else escape(case_id))
            case_links.append(f"<li>{case_link}: {escape(label(case.replay.status))}; "
                              f"{escape(LABELS['attribution'])} {escape(label(case.failure_analysis.category))}; "
                              f"{escape(LABELS['receipt'])} {escape(case.waveform.receipt_id)}</li>")
            if case.waveform.receipt_id:
                receipts.append(case.waveform.receipt_id)
                viewers.append(case.waveform.viewer_url)
        root = root_by_id.get(decision.root_id)
        aggregate_only = sorted(set(entry.aggregate_case_ids) - set(entry.case_ids))
        source_rows = []
        for kind, references, primary, primary_note, candidate_note in (
                ("Spec", spec_refs, decision.spec_ref,
                 f"{LABELS['decision_spec']}: {bug.expected_behavior}", LABELS["candidate_spec"]),
                ("RTL", rtl_refs, decision.rtl_ref,
                 f"{LABELS['decision_rtl']}: {decision.first_error}; {decision.causal_chain}",
                 LABELS["candidate_rtl"])):
            for reference in references:
                note = primary_note if reference == primary else candidate_note
                source_rows.append(f"<tr><td>{source_link(reference)}</td><td><strong>{kind}</strong> · {escape(note)}</td></tr>")
        source_table = (f"<div class='table-wrap'><table class='source-table'><thead><tr><th>{escape(LABELS['source_file'])}</th>"
                        f"<th>{escape(LABELS['source_analysis'])}</th></tr></thead><tbody>{''.join(source_rows)}</tbody></table></div>")
        body = (f"<nav class='crumb'><a href='../index.html'>{escape(LABELS['module'])}</a> / {escape(LABELS['bug_review'])}</nav>"
                f"<header class='hero'><div class='eyebrow'>{escape(LABELS['bug_review'])}</div>"
                f"<h1 class='mono'>{escape(bug_id)}</h1>{badge(decision.verdict)}"
                f"<span class='muted'>{escape(LABELS['confidence'])}: {escape(decision.review_confidence if decision.review_confidence is not None else LABELS['unresolved'])}"
                f" · {escape(LABELS['reported_confidence'])}: {escape(entry.reported_confidence if entry.reported_confidence is not None else LABELS['unavailable'])}"
                f" · {escape(LABELS['origin'])}: {escape(label(entry.origin))}</span>"
                f"<p class='lead'>{escape(decision.rationale or LABELS['unresolved'])}</p>"
                f"<p class='muted'>{escape(LABELS['root_group'])}: {escape(decision.root_id or LABELS['none'])}</p></header>"
                f"<section class='three'><div class='tile'><div class='eyebrow'>{escape(LABELS['scenario'])}</div>"
                f"<p>{escape(bug.validation_scenario or LABELS['unresolved'])}</p></div>"
                f"<div class='tile'><div class='eyebrow'>{escape(LABELS['expected'])}</div>"
                f"<p>{escape(bug.expected_behavior or LABELS['unresolved'])}</p></div>"
                f"<div class='tile'><div class='eyebrow'>{escape(LABELS['observed'])}</div>"
                f"<p>{escape(bug.observed_behavior or LABELS['unresolved'])}</p></div></section>"
                f"<section class='card'><h2>{escape(LABELS['evidence_chain'])}</h2><ol class='chain'>"
                f"<li><strong>{escape(LABELS['reproduced_cases'])}</strong><ul>{''.join(case_links) or none_li}</ul></li>"
                f"<li><strong>{escape(LABELS['signed_waves'])}</strong>: {escape(', '.join(receipts) or LABELS['unavailable'])}</li>"
                f"<li><strong>{escape(LABELS['spec_requirement'])}</strong>: {source_link(decision.spec_ref) if decision.spec_ref else escape(LABELS['unresolved'])}</li>"
                f"<li><strong>{escape(LABELS['rtl_first_error'])}</strong>: {source_link(decision.rtl_ref) if decision.rtl_ref else escape(LABELS['unresolved'])}"
                f" — {escape(decision.first_error or LABELS['unresolved'])}</li>"
                f"<li><strong>{escape(LABELS['causal_chain'])}</strong>: {escape(decision.causal_chain or LABELS['unresolved'])}</li>"
                "</ol></section>"
                f"<section class='card'><h2>{escape(LABELS['root_cause'])}</h2>"
                f"<p class='mono'>{escape(root.root_id if root else LABELS['none'])}</p>"
                f"<p>{escape(root.first_error if root else LABELS['unresolved'])}</p>"
                f"<p>{escape(root.causal_chain if root else '')}</p></section>"
                f"<section class='card'><h2>{escape(LABELS['source_evidence'])}</h2>{source_table}"
                f"<details><summary>{escape(LABELS['original_claims'])} ({len(entry.analysis_refs) + bool(entry.summary_ref)})</summary>"
                f"<ul>{source_list([entry.summary_ref, *entry.analysis_refs])}</ul></details>"
                f"<details><summary>{escape(LABELS['aggregate_cases'])} ({len(entry.aggregate_case_ids)})</summary>"
                f"<p>{escape(LABELS['aggregate_only'])}: {escape(', '.join(aggregate_only) or LABELS['none'])}</p>"
                f"<ul>{source_list(entry.aggregate_refs)}</ul></details></section>")
        pages[f"report/bugs/{filename}"] = page(f"{name}: {bug_id}", body)
        if decision.verdict == "confirmed" and decision.review_confidence is not None and decision.review_confidence >= CONFIDENCE_FLOOR:
            bug_rows.append((decision.review_confidence,
                             f"<tr><td><a class='mono' href='bugs/{filename}'>{escape(bug_id)}</a>"
                             f"<div class='muted'>{escape(bug.validation_scenario)}</div></td>"
                             f"<td>{escape(label(entry.origin))}</td><td><strong>{decision.review_confidence:.2f}</strong></td>"
                             f"<td>{escape(decision.root_id or '—')}</td><td>{len(bug.case_ids)}</td></tr>"))
        manifest_bugs.append({"bug_id": bug_id, "page": f"bugs/{filename}",
                              "root_id": decision.root_id, "receipts": receipts,
                              "viewers": viewers, "spec_refs": spec_refs, "rtl_refs": rtl_refs})
    bug_rows.sort(key=lambda item: item[0], reverse=True)
    case_rows = "".join(f"<tr><td><a class='mono' href='{item['page']}'>{escape(item['case_id'])}</a></td>"
                        f"<td>{badge(item['category'])}</td>"
                        f"<td>{escape(', '.join(item['bug_ids']) or LABELS['none'])}</td></tr>"
                        for item in manifest_cases)
    metric_items = []
    for key in ("line", "functional"):
        metric = coverage.metrics.get(key)
        if metric and metric.status == "available":
            value = f"{metric.numerator}/{metric.denominator}" if metric.denominator is not None else metric.value
            metric_items.append(f"<li>{escape(label(key))}: {escape(value)}; {escape(metric.run_scope)}; "
                                f"{escape(metric.basis)}; {escape(metric.source_ref)}</li>")
        else:
            metric_items.append(f"<li>{escape(label(key))}: {escape(LABELS['unavailable'])}; "
                                f"{escape(metric.reason if metric else '')}</li>")
    missing = [case_id for case_id in manifest.collected if summary.outcomes.get(case_id) == "not_run"]
    incomplete = review_incomplete(manifest, cases, environment)
    status = "incomplete" if incomplete else "complete"
    findings = "".join(f"<li>{escape(label(item.category))} ({escape(label(item.status))}): "
                       f"{escape(item.observation)}; {escape(LABELS['impact'])}: {escape(item.impact)}; "
                       f"{escape(LABELS['cases'])}: {escape(', '.join(item.case_ids))}</li>"
                       for item in environment.findings)
    quality = "".join(f"<li>{escape(LABELS[key])}: {escape(getattr(environment, field))}</li>"
                      for key, field in (("collection", "collection_review"),
                                         ("execution", "execution_review"),
                                         ("fixture_reset", "fixture_reset_review"),
                                         ("driver_sampling", "driver_sampling_review"),
                                         ("reference_model", "reference_model_review"),
                                         ("seed_repro", "seed_reproducibility_review")))
    confirmed_count = sum(bug.decision.verdict == "confirmed" for bug in bugs.values())
    unresolved_count = sum(bug.decision.verdict == "inconclusive" for bug in bugs.values())
    kpis = (("collected", len(manifest.collected)), ("executed", len(manifest.collected) - len(missing)),
            ("failed_count", len(case_names)), ("high_confidence", len(bug_rows)),
            ("unexecuted", len(missing)), ("undecided", unresolved_count))
    kpi_html = "".join(f"<div class='tile'><small>{escape(LABELS[key])}</small><strong>{value}</strong></div>"
                       for key, value in kpis)
    no_findings = f"<li>{escape(LABELS['not_recorded'])}</li>"
    overview = (f"<nav class='crumb'><a href='../../index.html'>{escape(LABELS['all_modules'])}</a> / {escape(LABELS['module'])}</nav>"
                f"<header class='hero'><div class='eyebrow'>{escape(LABELS['verification_review'])}</div>"
                f"<h1>{escape(name)}</h1>{badge(status)}<p class='lead'>{escape(LABELS['lead'])}</p>"
                f"<p class='muted'>{escape(LABELS['collection_errors'])}: {len(manifest.collection_errors)}; "
                f"{escape(LABELS['new_candidates'])}: {len(reconciliation.discovered_bug_ids)}</p></header>"
                f"<section class='kpis'>{kpi_html}</section>"
                f"<section class='card'><h2>{escape(LABELS['coverage_scope'])}</h2><ul>{''.join(metric_items)}</ul></section>"
                f"<section class='card'><h2>{escape(LABELS['bug_list'])}</h2>"
                f"<p class='muted'>{escape(LABELS['bug_list_note'])} {escape(LABELS['hidden_bugs'])}: {len(bugs) - len(bug_rows)}; "
                f"{escape(LABELS['confirmed'])}: {confirmed_count}.</p><div class='table-wrap'>"
                f"<table><tr><th>{escape(LABELS['bug_scenario'])}</th><th>{escape(LABELS['origin'])}</th>"
                f"<th>{escape(LABELS['confidence'])}</th><th>{escape(LABELS['root'])}</th><th>{escape(LABELS['cases'])}</th></tr>"
                f"{''.join(row for _, row in bug_rows)}</table></div></section>"
                f"<section class='card'><h2>{escape(LABELS['failed_cases'])}</h2><div class='table-wrap'>"
                f"<table><tr><th>{escape(LABELS['case'])}</th><th>{escape(LABELS['attribution'])}</th>"
                f"<th>{escape(LABELS['bugs'])}</th></tr>{case_rows}</table></div></section>"
                f"<section class='card'><h2>{escape(LABELS['environment_quality'])}</h2>"
                f"<details><summary>{escape(LABELS['quality_reviews'])}</summary><ul>{quality}</ul></details>"
                f"<ul>{findings or no_findings}</ul></section>"
                f"<section class='card'><h2>{escape(LABELS['original_reconciliation'])}</h2>"
                f"<p>{escape(reconciliation.statistics_review)}</p>"
                f"<p>{escape(LABELS['unreported_failed'])}: {escape(', '.join(reconciliation.unreported_failed_cases) or LABELS['none'])}</p>"
                f"<p>{escape(LABELS['now_passing'])}: {escape(', '.join(reconciliation.previously_failed_now_passed) or LABELS['none'])}</p>"
                f"<details><summary>{escape(LABELS['run_source'])}</summary>"
                f"<p class='mono'>{escape(index.workspace.get('source_path', ''))}</p>"
                f"<pre>{escape(chr(10).join(manifest.collection_errors) or LABELS['none'])}</pre></details></section>")
    pages["report/index.html"] = page(f"{name} {LABELS['bug_review']}", overview)
    report_manifest = {"schema": "bug_review_report.v3", "workspace": name,
                       "review_status": status, "pages": sorted(p.removeprefix("report/") for p in pages),
                       "bugs": manifest_bugs, "cases": manifest_cases,
                       "sources": sorted(source_catalog.values(), key=lambda item: item["path"]),
                       "collected": len(manifest.collected), "unexecuted": missing}
    return pages, report_manifest


def verify_pages(output: Path, index, cases: dict, bugs: dict, roots) -> None:
    """Compare rendered pages, source anchors, and links with active records."""
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
            link, fragment = urldefrag(html.unescape(href))
            target = (path.parent / unquote(link)).resolve()
            if not target.is_relative_to((output / "report").resolve()) or not target.is_file():
                raise ValueError(f"broken report link in {filename}: {href}")
            if fragment:
                match = re.fullmatch(r"L(\d+)-L(\d+)", fragment)
                content = pages.get(str(target.relative_to(output)))
                if (match is None or content is None or int(match.group(1)) > int(match.group(2))
                        or f"id='L{match.group(1)}'" not in content
                        or f"id='L{match.group(2)}'" not in content):
                    raise ValueError(f"broken source range in {filename}: {href}")
    if read_object(output / "report/report_manifest.json") != expected_manifest:
        raise ValueError("report/report_manifest.json differs from current pages")
