"""Render and verify localized module, case, Bug, and source report pages."""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import re
import shutil
from urllib.parse import parse_qs, unquote, urlsplit

import ucagent
from ucagent.util.waveform_viewer import decode_waveform_viewer_token

from .json_io import read_object
from .review_store import REF_PATTERN, load_record, source_lines
from .review_validation import review_incomplete

LABELS = json.loads((Path(__file__).parent / "lang/zh/report.json").read_text(encoding="utf-8"))
CONFIDENCE_FLOOR = 0.8
SURFER_SOURCE = Path(ucagent.__file__).resolve().parent / "server/static/surfer"
SURFER_BRIDGE = Path(__file__).parent / "lang/zh/report-surfer.js"


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
            ".section-disclosure{border:0;padding:0}.section-disclosure>summary{font-size:1.25rem}"
            ".section-disclosure[open]>summary{margin-bottom:14px}"
            "pre{white-space:pre-wrap;background:#F2F5F9;border-radius:10px;padding:14px;font-size:.84rem}"
            "ol,ul{padding-left:22px}li{margin:7px 0}.chain li{padding:4px 0}"
            ".source-table td:first-child{width:44%;font-family:ui-monospace,SFMono-Regular,monospace}"
            ".root-note{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}"
            ".action{display:inline-block;background:var(--brand);color:#fff;text-decoration:none;border-radius:9px;"
            "padding:8px 13px;font-weight:700;margin:5px 0}.action:hover{background:#1249ab}"
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


def prepare_waveform_bundle(output: Path, cases: dict) -> dict[str, int]:
    """Snapshot receipt-selected waveforms and the static Surfer frontend into a report."""
    run = output.parent.resolve()
    store = run / ".ucagent/waveinfo_receipts.json"
    signed = [case for case in cases.values() if case.waveform.receipt_id and case.waveform.viewer_url]
    if not signed:
        return {"available": 0, "unavailable": 0}
    receipts = {item["receipt_id"]: item for item in read_object(store)["receipts"]}
    wave_dir = output / "report/waveforms"
    wave_dir.mkdir(parents=True, exist_ok=True)
    available = unavailable = 0
    for case in signed:
        wave = case.waveform
        if re.fullmatch(r"[0-9a-f]{32}", wave.receipt_id) is None:
            raise ValueError(f"invalid waveform receipt ID: {case.case_id}")
        receipt = receipts.get(wave.receipt_id)
        if receipt is None or (receipt.get("result", {}).get("waveform_viewer") or {}).get("url") != wave.viewer_url:
            raise ValueError(f"waveform receipt or viewer mismatch: {case.case_id}")
        selection = receipt["result"].get("waveform_selection") or {}
        relative = selection.get("waveform_file", "")
        extension = Path(relative).suffix.lower()
        if extension not in {".fst", ".vcd"}:
            unavailable += 1
            continue
        snapshot = wave_dir / f"{wave.receipt_id}{extension}"
        original = (run / relative).resolve()
        if original.is_relative_to(run) and original.is_file():
            stat = original.stat()
            if (stat.st_size == selection.get("size_bytes")
                    and stat.st_mtime_ns == selection.get("modified_time_ns")):
                shutil.copy2(original, snapshot)
        if snapshot.is_file():
            available += 1
        else:
            unavailable += 1
    if available:
        target = output / "report/surfer"
        target.mkdir(parents=True, exist_ok=True)
        marker = '<script src="deep-link.js"></script>'
        for asset in SURFER_SOURCE.iterdir():
            if not asset.is_file():
                continue
            destination = target / asset.name
            if asset.name == "index.html":
                content = asset.read_text(encoding="utf-8")
                if content.count(marker) != 1:
                    raise ValueError("Surfer bootstrap script marker is missing")
                destination.write_text(content.replace(
                    marker, marker + '\n    <script src="report-surfer.js"></script>'), encoding="utf-8")
            else:
                shutil.copy2(asset, destination)
        shutil.copy2(SURFER_BRIDGE, target / "report-surfer.js")
    return {"available": available, "unavailable": unavailable}


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
    preview_links: dict[str, str] = {}
    preview_manifest = []
    for case_id, case in cases.items():
        wave = case.waveform
        if not wave.receipt_id or not wave.viewer_url:
            continue
        token = parse_qs(urlsplit(wave.viewer_url).query).get("wave", [""])[0]
        payload = decode_waveform_viewer_token(token)
        if payload["v"] != 2:
            continue
        snapshots = [output / "report/waveforms" / f"{wave.receipt_id}{extension}"
                     for extension in (".fst", ".vcd")]
        existing = [path for path in snapshots if path.is_file()]
        if len(existing) > 1:
            raise ValueError(f"multiple waveform snapshots for receipt: {wave.receipt_id}")
        if not existing:
            continue
        snapshot = existing[0]
        relative = snapshot.relative_to(output / "report").as_posix()
        preview_links[case_id] = f"../surfer/index.html?wave={token}&snapshot={snapshot.name}"
        stat = snapshot.stat()
        preview_manifest.append({"case_id": case_id, "receipt_id": wave.receipt_id,
                                 "file": relative, "size_bytes": stat.st_size,
                                 "modified_time_ns": stat.st_mtime_ns})

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
        viewer = (f"<a class='action' href='{escape(preview_links[case_id])}' target='_blank' rel='noopener'>"
                  f"{escape(LABELS['open_wave'])}</a>"
                  f"<p class='muted'>{escape(LABELS['wave_preview_server_hint'])}</p>"
                  if case_id in preview_links
                  else escape(LABELS["wave_preview_unavailable"]))
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

    visible_bugs: dict[str, list[tuple[str, str, object]]] = {}
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
        wave_cases = [(case_id, cases[case_id]) for case_id in bug.case_ids
                      if cases[case_id].waveform.receipt_id]
        if wave_cases:
            representative_id, representative = next(
                ((case_id, case) for case_id, case in wave_cases if case_id in preview_links),
                wave_cases[0])
            wave = representative.waveform
            window = wave.analysis_window
            start = window.get("effective_start_step", LABELS["unavailable"])
            end = window.get("effective_end_step", LABELS["unavailable"])
            observation = wave.observed_behavior or wave.diagnostic or LABELS["unresolved"]
            sentences = re.split(r"(?<=[。！？.!?])\s+", observation, maxsplit=2)
            if len(sentences) > 2:
                observation = " ".join(sentences[:2]) + "…"
            if len(observation) > 500:
                observation = observation[:500].rsplit(" ", 1)[0].rstrip() + "…"
            preview = (f"<a class='action' href='{escape(preview_links[representative_id])}' "
                       f"target='_blank' rel='noopener'>{escape(LABELS['open_wave'])}</a>"
                       f"<p class='muted'>{escape(LABELS['wave_preview_server_hint'])}</p>"
                       if representative_id in preview_links else escape(LABELS["wave_preview_unavailable"]))
            other_waves = "".join(
                f"<li>{escape(case_id)} · {escape(case.waveform.receipt_id)} "
                + (f"<a href='{escape(preview_links[case_id])}' target='_blank' rel='noopener'>"
                   f"{escape(LABELS['open_wave'])}</a>" if case_id in preview_links
                   else escape(LABELS["wave_preview_unavailable"])) + "</li>"
                for case_id, case in wave_cases if case_id != representative_id)
            wave_evidence = (f"<p>{escape(LABELS['signed_wave_count'])}: {len(wave_cases)}; "
                             f"{escape(LABELS['representative_case'])}: {escape(representative_id)}; "
                             f"{escape(LABELS['wave_window'])}: {escape(start)}–{escape(end)}</p>"
                             f"<p>{escape(observation)}</p>{preview}"
                             + (f"<details><summary>{escape(LABELS['other_wave_evidence'])} "
                                f"({len(wave_cases) - 1})</summary><ul>{other_waves}</ul></details>"
                                if other_waves else ""))
        else:
            wave_evidence = escape(LABELS["unavailable"])
        root = root_by_id.get(decision.root_id)
        aggregate_rows = []
        for case_id in dict.fromkeys([*bug.case_ids, *entry.aggregate_case_ids]):
            case_link = (f"<a href='../cases/{case_names[case_id]}'>{escape(case_id)}</a>"
                         if case_id in case_names else escape(case_id))
            if case_id in bug.case_ids:
                relation = (LABELS["reviewed_aggregate_case"] if case_id in entry.aggregate_case_ids
                            else LABELS["reviewed_case"])
            else:
                relation = LABELS["aggregate_only"]
            replay = label(cases[case_id].replay.status) if case_id in cases else LABELS["not_collected"]
            aggregate_rows.append(f"<tr><td>{case_link}</td><td>{escape(relation)}</td><td>{escape(replay)}</td></tr>")
        aggregate_table = (f"<div class='table-wrap'><table><thead><tr><th>{escape(LABELS['case'])}</th>"
                           f"<th>{escape(LABELS['case_relation'])}</th><th>{escape(LABELS['replay_result'])}</th>"
                           f"</tr></thead><tbody>{''.join(aggregate_rows) or f'<tr><td colspan="3">{escape(LABELS["none"])}</td></tr>'}"
                           "</tbody></table></div>")
        source_rows = []
        for reference in rtl_refs:
            note = (f"{LABELS['decision_rtl']}: {decision.first_error}; {decision.causal_chain}"
                    if reference == decision.rtl_ref else LABELS["candidate_rtl"])
            source_rows.append(f"<tr><td>{source_link(reference)}</td><td>{escape(note)}</td></tr>")
        source_table = (f"<div class='table-wrap'><table class='source-table'><thead><tr><th>{escape(LABELS['source_file'])}</th>"
                        f"<th>{escape(LABELS['source_analysis'])}</th></tr></thead><tbody>{''.join(source_rows) or f'<tr><td colspan="2">{escape(LABELS["no_refs"])}</td></tr>'}</tbody></table></div>")
        spec_documents = [reference for reference in spec_refs
                          if (match := REF_PATTERN.fullmatch(reference)) and Path(match.group(1)).suffix.lower() == ".md"]
        summary_key = "attribution_root_summary" if root else "attribution_root_unresolved"
        attribution_root_summary = LABELS[summary_key].format(
            verdict=label(decision.verdict), count=len(bug.case_ids),
            root_id=root.root_id if root else "",
            rtl_ref=root.rtl_ref if root else "",
            observed=bug.observed_behavior or LABELS["unresolved"])
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
                f"<section class='card'><h2>{escape(LABELS['attribution_root'])}</h2>"
                f"<p>{escape(attribution_root_summary)}</p></section>"
                f"<section class='card'><h2>{escape(LABELS['evidence_chain'])}</h2><ol class='chain'>"
                f"<li><strong>{escape(LABELS['reproduced_cases'])}</strong><ul>{''.join(case_links) or none_li}</ul></li>"
                f"<li><strong>{escape(LABELS['signed_waves'])}</strong>{wave_evidence}</li>"
                f"<li><strong>{escape(LABELS['spec_requirement'])}</strong>: {source_link(decision.spec_ref) if decision.spec_ref else escape(LABELS['unresolved'])}</li>"
                f"<li><strong>{escape(LABELS['rtl_first_error'])}</strong>: {source_link(decision.rtl_ref) if decision.rtl_ref else escape(LABELS['unresolved'])}"
                f" — {escape(decision.first_error or LABELS['unresolved'])}</li>"
                f"<li><strong>{escape(LABELS['causal_chain'])}</strong>: {escape(decision.causal_chain or LABELS['unresolved'])}</li>"
                "</ol></section>"
                f"<section class='card'><details class='section-disclosure' open>"
                f"<summary>{escape(LABELS['related_documents'])}</summary>"
                f"<p class='muted'>{escape(LABELS['original_report'])}</p>"
                f"<ul>{source_list([entry.summary_ref, *entry.analysis_refs])}</ul>"
                f"<p class='muted'>{escape(LABELS['related_specs'])}</p>"
                f"<ul>{source_list(spec_documents)}</ul>"
                f"<details><summary>{escape(LABELS['aggregate_cases'])} ({len(entry.aggregate_case_ids)})</summary>"
                f"{aggregate_table}<p class='muted'>{escape(LABELS['report_source'])}</p>"
                f"<ul>{source_list(entry.aggregate_refs)}</ul></details></details></section>"
                f"<section class='card'><details class='section-disclosure'>"
                f"<summary>{escape(LABELS['related_source'])}</summary>{source_table}</details></section>")
        pages[f"report/bugs/{filename}"] = page(f"{name}: {bug_id}", body)
        if decision.verdict == "confirmed" and decision.review_confidence is not None and decision.review_confidence >= CONFIDENCE_FLOOR:
            if decision.root_id not in root_by_id:
                raise ValueError(f"confirmed Bug has no root group: {bug_id}")
            visible_bugs.setdefault(decision.root_id, []).append((bug_id, filename, bug))
        manifest_bugs.append({"bug_id": bug_id, "page": f"bugs/{filename}",
                              "root_id": decision.root_id, "receipts": receipts,
                              "viewers": viewers, "spec_refs": spec_refs, "rtl_refs": rtl_refs})
    root_rows = []
    for root_id, members in visible_bugs.items():
        root = root_by_id[root_id]
        confidence_values = [bug.decision.review_confidence for _, _, bug in members]
        confidence_min, confidence_max = min(confidence_values), max(confidence_values)
        confidence = (f"{confidence_min:.2f}" if confidence_min == confidence_max
                      else f"{confidence_min:.2f}–{confidence_max:.2f}")
        member_links = "".join(
            f"<li><a class='mono' href='bugs/{filename}'>{escape(bug_id)}</a></li>"
            for bug_id, filename, _ in members)
        group_cases = set().union(*(bug.case_ids for _, _, bug in members))
        root_rows.append((confidence_min,
                          f"<tr><td><strong class='mono'>{escape(root_id)}</strong>"
                          f"<div class='muted root-note'>{escape(root.first_error)}</div>"
                          f"<div>{source_link(root.rtl_ref, prefix='sources/')}</div></td>"
                          f"<td><ul>{member_links}</ul></td><td>{confidence}</td>"
                          f"<td>{len(group_cases)}</td></tr>"))
    root_rows.sort(key=lambda item: item[0], reverse=True)
    high_bug_count = sum(map(len, visible_bugs.values()))
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
    refuted_count = sum(bug.decision.verdict == "refuted" for bug in bugs.values())
    unresolved_count = sum(bug.decision.verdict == "inconclusive" for bug in bugs.values())
    kpis = (("collected", len(manifest.collected)), ("executed", len(manifest.collected) - len(missing)),
            ("failed_count", len(case_names)), ("high_confidence", len(root_rows)),
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
                f"<p class='muted'>{escape(LABELS['bug_list_note'])} "
                f"{escape(LABELS['high_bug_count'])}: {high_bug_count}; "
                f"{escape(LABELS['hidden_bugs'])}: {len(bugs) - high_bug_count}; "
                f"{escape(LABELS['confirmed'])}: {confirmed_count}; "
                f"{escape(LABELS['refuted'])}: {refuted_count}.</p><div class='table-wrap'>"
                f"<table><tr><th>{escape(LABELS['root'])}</th><th>{escape(LABELS['bug_members'])}</th>"
                f"<th>{escape(LABELS['member_confidence'])}</th><th>{escape(LABELS['cases'])}</th></tr>"
                f"{''.join(row for _, row in root_rows)}</table></div></section>"
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
                       "high_confidence_root_count": len(root_rows),
                       "bugs": manifest_bugs, "cases": manifest_cases,
                       "waveform_previews": sorted(preview_manifest, key=lambda item: item["case_id"]),
                       "sources": sorted(source_catalog.values(), key=lambda item: item["path"]),
                       "collected": len(manifest.collected), "unexecuted": missing}
    return pages, report_manifest


def verify_pages(output: Path, index, cases: dict, bugs: dict, roots) -> None:
    """Compare rendered pages, source anchors, and links with active records."""
    coverage = load_record(output, index.coverage_path, "coverage")
    pages, expected_manifest = render_pages(output, index, cases, bugs, roots, coverage)
    if expected_manifest["waveform_previews"]:
        surfer = output / "report/surfer"
        marker = '<script src="deep-link.js"></script>'
        for asset in SURFER_SOURCE.iterdir():
            if not asset.is_file():
                continue
            target = surfer / asset.name
            if not target.is_file():
                raise ValueError(f"missing report Surfer asset: {target}")
            if asset.name == "index.html":
                expected = asset.read_text(encoding="utf-8").replace(
                    marker, marker + '\n    <script src="report-surfer.js"></script>')
                if target.read_text(encoding="utf-8") != expected:
                    raise ValueError("report Surfer entry differs from bundled asset")
            elif target.read_bytes() != asset.read_bytes():
                raise ValueError(f"report Surfer asset differs from source: {asset.name}")
        if (surfer / "report-surfer.js").read_bytes() != SURFER_BRIDGE.read_bytes():
            raise ValueError("report Surfer bridge differs from source")
    for filename, expected in pages.items():
        path = output / filename
        if not path.is_file() or path.read_text(encoding="utf-8") != expected:
            raise ValueError(f"report page missing or differs from review records: {filename}")
        for href in re.findall(r"href='([^']+)'", expected):
            if href.startswith(("http://", "https://", "/surfer/", "#")):
                continue
            if filename == "report/index.html" and href == "../../index.html":
                continue
            parsed = urlsplit(html.unescape(href))
            target = (path.parent / unquote(parsed.path)).resolve()
            if not target.is_relative_to((output / "report").resolve()) or not target.is_file():
                raise ValueError(f"broken report link in {filename}: {href}")
            if parsed.query and target == (output / "report/surfer/index.html").resolve():
                query = parse_qs(parsed.query)
                payload = decode_waveform_viewer_token(query.get("wave", [""])[0])
                snapshot = query.get("snapshot", [""])[0]
                if (payload["v"] != 2 or re.fullmatch(r"[0-9a-f]{32}\.(?:fst|vcd)", snapshot) is None
                        or not (output / "report/waveforms" / snapshot).is_file()):
                    raise ValueError(f"invalid report waveform preview link: {href}")
            elif parsed.query:
                raise ValueError(f"unexpected report query link in {filename}: {href}")
            if parsed.fragment:
                match = re.fullmatch(r"L(\d+)-L(\d+)", parsed.fragment)
                content = pages.get(str(target.relative_to(output)))
                if (match is None or content is None or int(match.group(1)) > int(match.group(2))
                        or f"id='L{match.group(1)}'" not in content
                        or f"id='L{match.group(2)}'" not in content):
                    raise ValueError(f"broken source range in {filename}: {href}")
    if read_object(output / "report/report_manifest.json") != expected_manifest:
        raise ValueError("report/report_manifest.json differs from current pages")
