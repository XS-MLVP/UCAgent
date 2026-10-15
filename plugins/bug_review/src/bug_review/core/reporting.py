"""Render and verify localized module, case, Bug, and source report pages."""

from __future__ import annotations

import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import parse_qs, unquote, urlsplit

import ucagent
from ucagent.util.waveform_viewer import decode_waveform_viewer_token

from .json_io import read_object
from .layout import resolve_logical_path
from .records import REF_PATTERN, load_record, source_lines, source_root as prepared_source_root
from .validation import ReviewIssues, review_incomplete
from .narrative import narrative_issues, RTL_SUFFIXES
from .evidence import (case_waveforms, decode_fields, read_event_value, root_page,
                       signal_identity, snapshot_preview, waveform_timescale)

LABELS = json.loads((Path(__file__).parent.parent / "lang/zh/report.json").read_text(encoding="utf-8"))
CONFIDENCE_FLOOR = 0.8
SURFER_SOURCE = Path(ucagent.__file__).resolve().parent / "server/static/surfer"
SURFER_BRIDGE = Path(__file__).parent.parent / "lang/zh/report-surfer.js"


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
            "<style>:root{color-scheme:dark;--bg:#0c121b;--ink:#e8eff8;--muted:#92a5bc;"
            "--brand:#70c8ff;--line:#2a3a4d}*{box-sizing:border-box}"
            "body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,sans-serif;overflow-wrap:anywhere}"
            "main{max-width:1400px;margin:auto;padding:28px 20px 72px}h1{font-size:clamp(1.7rem,3vw,2.5rem);"
            "line-height:1.2;margin:8px 0 12px;overflow-wrap:anywhere}h2{font-size:1.25rem;margin:0 0 14px}"
            "p{margin:8px 0 14px}a{color:var(--brand);text-underline-offset:3px;overflow-wrap:anywhere}"
            "a:focus-visible,summary:focus-visible{outline:3px solid #84CAFF;outline-offset:3px}"
            ".crumb{font-size:.9rem;color:var(--muted);margin-bottom:18px}"
            ".hero,.card{background:#131e2b;border:1px solid #2a3a4d;border-radius:16px;box-shadow:0 3px 16px #14223509}"
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
            ".tile{background:#131e2b;border:1px solid #2a3a4d;border-radius:12px;padding:16px;min-width:0}"
            ".tile strong{display:block;font-size:1.65rem;line-height:1.2}.tile small{color:var(--muted)}"
            ".table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%}th,td{padding:11px 12px;"
            "text-align:left;border-bottom:1px solid #2a3a4d;vertical-align:top;overflow-wrap:anywhere}"
            "th{color:var(--muted);font-size:.84rem}tr:hover td{background:#192636}"
            "details{border-top:1px solid #2a3a4d;padding:11px 0}summary{cursor:pointer;font-weight:650}"
            ".section-disclosure{border:0;padding:0}.section-disclosure>summary{font-size:1.25rem}"
            ".section-disclosure[open]>summary{margin-bottom:14px}"
            "pre{white-space:pre-wrap;background:#192636;border-radius:10px;padding:14px;font-size:.84rem}"
            "ol,ul{padding-left:22px}li{margin:7px 0}.chain li{padding:4px 0}"
            ".source-table td:first-child{width:44%;font-family:ui-monospace,SFMono-Regular,monospace}"
            ".root-note{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}"
            ".action{display:inline-block;background:var(--brand);color:#0c2335;text-decoration:none;border-radius:9px;"
            "padding:8px 13px;font-weight:700;margin:5px 0}.action:hover{background:#1249ab}"
            ".source-code{background:#0e1927;border:1px solid var(--line);border-radius:10px;overflow:auto}"
            ".src-line{display:flex;white-space:pre;width:max-content;min-width:100%;font:13px/1.6 ui-monospace,SFMono-Regular,monospace}"
            ".src-line .line-no{position:sticky;left:0;display:inline-block;width:5.5em;padding:0 .8em;text-align:right;"
            "color:#92a5bc;background:#192636;user-select:none;margin-right:1em}"
            ".src-line.marked{background:#3f351e}.src-line.marked .line-no{background:#574424;color:#f2cd84}"
            "@media(max-width:760px){main{padding:18px 12px 48px}.hero{padding:20px}.card{padding:17px}"
            ".kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.three{grid-template-columns:1fr}}"
            ".detail-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,.95fr);gap:28px;align-items:start}.report-text{min-width:0;font-size:14px}.root-mechanism{margin-top:20px;border-left:2px solid #f2cd84;padding-left:14px}.root-mechanism .chain{font-size:14px}.chain p{margin:5px 0}.member-scenario>h3{color:var(--muted)}.report-text header{padding-bottom:20px;border-bottom:1px solid var(--line)}.report-text section{padding:22px 0;border-bottom:1px solid var(--line)}.report-text h2{font-size:18px}.report-text h3{font-size:14px;margin:18px 0 9px}.report-context{position:sticky;top:18px;min-width:0}.report-context section{padding-bottom:20px;margin-bottom:18px;border-bottom:1px solid var(--line)}.report-context h2{font-size:15px}.report-context p,.report-context li{font-size:12px}.wave-preview{display:block;background:#0a1520;border:1px solid var(--line);border-radius:6px;overflow:hidden}.wave-thumb{display:block;width:100%;height:auto;min-height:200px}.wave-thumb text{font-family:ui-monospace,SFMono-Regular,monospace}.wave-links{list-style:none;padding:0}.wave-links li{padding:8px 0;border-bottom:1px solid var(--line)}@media(max-width:860px){.detail-layout{grid-template-columns:1fr}.report-context{position:static;display:grid;grid-template-columns:1fr 1fr;gap:20px}}@media(max-width:560px){.report-context{grid-template-columns:1fr}.report-text h3{overflow-wrap:anywhere}}"
            "</style><main>" + body + "</main></html>")


def badge(value: str) -> str:
    """Show an accessible state label with semantic color."""
    tone = value if re.fullmatch(r"[a-z_]+", value) else "refuted"
    return f"<span class='badge {tone}'>{escape(label(value))}</span>"


def prepare_waveform_bundle(output: Path, cases: dict) -> dict[str, int]:
    """Snapshot receipt-selected waveforms and the static Surfer frontend into a report."""
    run = output.parent.parent.resolve()
    store = run / ".ucagent/waveinfo_receipts.json"
    signed = [(case, wave) for case in cases.values() for wave in case_waveforms(case) if wave.viewer_url]
    if not signed:
        return {"available": 0, "unavailable": 0}
    receipts = {item["receipt_id"]: item for item in read_object(store)["receipts"]}
    wave_dir = output.parent / "report/waveforms"
    wave_dir.mkdir(parents=True, exist_ok=True)
    available = unavailable = 0
    exports = {}
    for case, wave in signed:
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
                    and stat.st_mtime_ns == selection.get("modified_time_ns")
                    and not snapshot.exists()):
                shutil.copy2(original, snapshot)
        if snapshot.is_file():
            stat = snapshot.stat()
            if stat.st_size != selection.get("size_bytes") or stat.st_mtime_ns != selection.get("modified_time_ns"):
                raise ValueError(f"archived snapshot differs from receipt identity: {wave.receipt_id}")
            available += 1
            export = {"status": "unavailable", "reason": "fst2vcd is unavailable"}
            if snapshot.suffix == ".vcd":
                export = {"status": "available", "file": f"waveforms/{snapshot.name}", "converter": "original"}
            elif shutil.which("fst2vcd"):
                import wavekit
                directory = output.parent / "report/downloads"
                directory.mkdir(parents=True, exist_ok=True)
                destination = directory / f"{wave.receipt_id}.vcd"
                fd, temporary = tempfile.mkstemp(suffix=".vcd", dir=directory)
                os.close(fd)
                staged = Path(temporary)
                try:
                    converter = shutil.which("fst2vcd")
                    converted = subprocess.run([converter, "-f", str(snapshot), "-o", str(staged)],
                                               capture_output=True, timeout=60)
                    if converted.returncode != 0:
                        raise ValueError("fst2vcd failed: " + converted.stderr.decode(errors="replace")[:300])
                    with wavekit.FstReader(str(snapshot)) as original_reader, wavekit.VcdReader(str(staged)) as converted_reader:
                        original_catalog = {signal_identity(signal.full_name): signal.width
                            for signal in original_reader.get_matched_signals("**").values()}
                        converted_catalog = {signal_identity(signal.full_name): signal.width
                            for signal in converted_reader.get_matched_signals("**").values()}
                        scale = waveform_timescale(snapshot, original_reader)
                        if (original_catalog != converted_catalog or scale != waveform_timescale(staged, converted_reader)
                                or original_reader.begin_time != converted_reader.begin_time
                                or original_reader.end_time != converted_reader.end_time):
                            raise ValueError("VCD conversion changed hierarchy, widths, range or timescale")
                    for event in case.events:
                        if event.receipt_id == wave.receipt_id and read_event_value(snapshot, event) != read_event_value(staged, event):
                            raise ValueError("VCD conversion changed a recorded event")
                    os.replace(staged, destination)
                    export = {"status": "available", "file": "downloads/" + destination.name,
                              "converter": "fst2vcd", "timescale": scale,
                              "converter_sha256": hashlib.sha256(Path(converter).read_bytes()).hexdigest()}
                except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                    export = {"status": "unavailable", "reason": str(error)[:300]}
                finally:
                    staged.unlink(missing_ok=True)
            export["source_sha256"] = hashlib.sha256(snapshot.read_bytes()).hexdigest()
            if export["status"] == "available":
                export["sha256"] = hashlib.sha256((output.parent / "report" / export["file"]).read_bytes()).hexdigest()
            exports[wave.receipt_id] = export
        else:
            unavailable += 1
    if available:
        target = output.parent / "report/surfer"
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
        (output.parent / "report/waveform_exports.json").write_text(
            json.dumps({"schema": "bug_review_exports.v1", "exports": exports}, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"available": available, "unavailable": unavailable}


def render_pages(output: Path, index, cases: dict, bugs: dict, roots, coverage) -> tuple[dict[str, str], dict]:
    """Build public pages and their exact cross-check manifest from active records."""
    name = index.workspace["name"]
    source_root = prepared_source_root(output)
    explanation_errors = narrative_issues(index, cases, bugs, roots, source_root)
    if explanation_errors:
        raise ReviewIssues(explanation_errors)
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
    receipt_links, snapshot_paths = {}, {}
    preview_manifest = []
    for case_id, case in cases.items():
        for wave in case_waveforms(case):
            if not wave.viewer_url:
                continue
            token = parse_qs(urlsplit(wave.viewer_url).query).get("wave", [""])[0]
            payload = decode_waveform_viewer_token(token)
            if payload["v"] != 2:
                raise ValueError("report requires a signed v2 viewer")
            snapshots = [output.parent / "report/waveforms" / f"{wave.receipt_id}{extension}"
                         for extension in (".fst", ".vcd")]
            existing = [path for path in snapshots if path.is_file()]
            if len(existing) > 1:
                raise ValueError(f"multiple waveform snapshots for receipt: {wave.receipt_id}")
            if not existing:
                continue
            snapshot = existing[0]
            receipt_links[wave.receipt_id] = f"../surfer/index.html?wave={token}&snapshot={snapshot.name}"
            snapshot_paths[wave.receipt_id] = snapshot
            if wave.receipt_id == case.waveform.receipt_id:
                preview_links[case_id] = receipt_links[wave.receipt_id]
            stat = snapshot.stat()
            preview_manifest.append({"case_id": case_id, "receipt_id": wave.receipt_id,
                                     "file": snapshot.relative_to(output.parent / "report").as_posix(),
                                     "size_bytes": stat.st_size, "modified_time_ns": stat.st_mtime_ns,
                                     "sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest()})
    navigation = {}
    export_index = output.parent / "report/waveform_exports.json"
    exports = read_object(export_index).get("exports", {}) if export_index.is_file() else {}

    def source_link(reference: str, prefix: str = "../sources/", compact: bool = False) -> str:
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
            target = resolve_logical_path(source_root, relative)
            text_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
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
        text = f"{Path(relative).name}:{start}" + (f"–{end}" if end != start else "") if compact else reference
        return f"<a href='{escape(href)}' title='{escape(reference)}'>{escape(text)}</a>"

    def source_list(references: list[str]) -> str:
        """Render a bounded source-reference list with full-file links."""
        return "".join(f"<li>{source_link(ref)}</li>" for ref in references if ref) or f"<li>{escape(LABELS['no_refs'])}</li>"

    case_names = {case_id: f"case_{position:04d}.html"
                  for position, case_id in enumerate(index.cases, 1)
                  if cases[case_id].replay.status in {"failed", "error", "xpassed"}}
    for case_id, filename in case_names.items():
        case = cases[case_id]
        analysis, wave = case.failure_analysis, case.waveform
        scenario_text = analysis.scenario.summary or analysis.unresolved or LABELS["unresolved"]
        spec_text = analysis.spec_expected.summary or LABELS["unresolved"]
        test_text = analysis.test_expected.summary or LABELS["unresolved"]
        actual_text = analysis.actual.summary or LABELS["unresolved"]
        rationale_text = analysis.rationale.attribution_reason or LABELS["unresolved"]
        evidence_refs = [*analysis.scenario.source_refs, *analysis.spec_expected.source_refs,
                         *analysis.test_expected.source_refs, *analysis.actual.evidence_refs]
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
                f"<p class='lead'>{escape(scenario_text)}</p></header>"
                f"<section class='three'><div class='tile'><div class='eyebrow'>{escape(LABELS['spec_expected'])}</div>"
                f"<p>{escape(spec_text)}</p></div>"
                f"<div class='tile'><div class='eyebrow'>{escape(LABELS['test_expected'])}</div>"
                f"<p>{escape(test_text)}</p></div>"
                f"<div class='tile'><div class='eyebrow'>{escape(LABELS['observed'])}</div>"
                f"<p>{escape(actual_text)}</p></div></section>"
                f"<section class='card'><h2>{escape(LABELS['failure_reason'])}</h2><p>{escape(rationale_text)}</p>"
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
                f"<ul>{source_list(evidence_refs)}</ul></section>")
        pages[f"report/cases/{filename}"] = page(f"{name}: {case_id}", body)
        manifest_cases.append({"case_id": case_id, "page": f"cases/{filename}",
                               "category": analysis.category, "receipt": wave.receipt_id,
                               "viewer": wave.viewer_url, "bug_ids": case.bug_ids})

    visible_bugs: dict[str, list[tuple[str, str, object]]] = {}
    bug_anchors = {bug_id: "phenomenon_" + hashlib.sha256(bug_id.encode()).hexdigest()
                   for bug_id in index.bug_order}
    bug_pages = {bug_id: ("roots/" + root_page(bugs[bug_id].decision.root_id)
                         if bugs[bug_id].decision.root_id in root_by_id
                         else "phenomena/" + hashlib.sha256(bug_id.encode()).hexdigest() + ".html")
                 for bug_id in index.bug_order}
    root_manifest = []

    def detail_page(root, members):
        """Render sourced DUT context, defect scenarios and root-local RTL propagation."""
        goals, scenarios, comparisons, technical = [], [], [], []
        wave_links, references, bindings, observations, downloads = [], [], {}, {}, {}
        case_number = {case_id: number for number, case_id in enumerate(dict.fromkeys(
            case_id for bug_id in members for case_id in bugs[bug_id].case_ids), 1)}
        member_number = {bug_id: number for number, bug_id in enumerate(members, 1)}
        available_direct = set()
        for bug_id in members:
            bug, number = bugs[bug_id], member_number[bug_id]
            phenomenon = bug.phenomenon
            caption = f"{LABELS['phenomenon']} {number}"
            member_heading = (f"<h3 id='{bug_anchors[bug_id]}'>{escape(caption)} {badge(bug.decision.verdict)}</h3>")
            goals.append(member_heading + f"<p>{escape(phenomenon.spec_expected.summary or phenomenon.spec_expected.requirement or LABELS['not_recorded'])}</p>")
            points = list(dict.fromkeys([*index.bugs[bug_id].fc_ids, *index.bugs[bug_id].ck_ids]))
            if points:
                goals[-1] += f"<p class='muted mono'>{escape(' · '.join(points))}</p>"
            scenario = (f"<div class='member-scenario'><h3>{escape(caption)}</h3>"
                        f"<p>{escape(phenomenon.scenario.summary or LABELS['not_recorded'])}</p>")
            if phenomenon.scenario.conditions:
                scenario += "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in phenomenon.scenario.conditions) + "</ul>"
            if phenomenon.signal_explanations:
                scenario += f"<details><summary>{escape(LABELS['signal_explanations'])}</summary><ul>"
                for explanation in phenomenon.signal_explanations:
                    alias = f"<code>{escape(explanation.test_name)}</code> → " if explanation.test_name else ""
                    scenario += (f"<li>{alias}<code>{escape(explanation.rtl_name)}</code>: {escape(explanation.meaning)}"
                                 + (f"<p class='muted mono'>{escape(explanation.signal_path)}</p>" if explanation.signal_path else "")
                                 + "<p>" + " · ".join(source_link(ref, compact=True) for ref in explanation.source_refs) + "</p></li>")
                scenario += "</ul></details>"
            scenarios.append(scenario + "</div>")
            comparisons.append(f"<tr><td>{escape(caption)}</td><td>{escape(phenomenon.spec_expected.summary or LABELS['not_recorded'])}</td>"
                               f"<td>{escape(phenomenon.actual.summary or LABELS['not_recorded'])}</td></tr>")
            details = f"<h3><code>{escape(bug_id)}</code> {badge(bug.decision.verdict)}</h3>"
            details += "<p>" + "<br>".join(escape(item) for item in [*phenomenon.scenario.setup, *phenomenon.scenario.stimulus]) + "</p>"
            for case_id in bug.case_ids:
                case = cases[case_id]
                link = (f"<a href='../cases/{case_names[case_id]}'>{escape(case_id)}</a>" if case_id in case_names else escape(case_id))
                details += f"<p class='mono'>{LABELS['case']} {case_number[case_id]} · {link}</p>"
                executions = {event.execution_id for binding in bug.evidence_bindings if binding.case_id == case_id
                              for event in case.events if event.event_id == binding.event_id}
                if case.scenario_steps:
                    rows = "".join(f"<tr><td>{escape(step.action)}</td><td>{escape(step.receiver_setting)}</td><td>{escape(step.expected)}</td>"
                                   f"<td>{escape(label(step.status))}<br><code>{escape(step.execution_id)}</code></td></tr>"
                                   for step in case.scenario_steps if not executions or step.execution_id in executions)
                    details += (f"<div class='table-wrap'><table><tr><th>{escape(LABELS['operation'])}</th><th>{escape(LABELS['receiver_setting'])}</th>"
                                f"<th>{escape(LABELS['expected'])}</th><th>{escape(LABELS['execution_reach'])}</th></tr>{rows}</table></div>")
                else:
                    facts = case.failure_analysis.scenario
                    details += "<p>" + "<br>".join(escape(item) for item in [*facts.setup, *facts.stimulus, *facts.conditions]) + "</p>"
                details += (f"<p>{escape(LABELS['test_assertion'])}: <code>{escape(case.failure_analysis.test_expected.assertion)}</code></p>"
                            + "<p>" + " · ".join(source_link(ref, compact=True) for ref in case.failure_analysis.test_expected.source_refs) + "</p>")
                gap = case.failure_analysis.rationale.remaining_gap or case.failure_analysis.unresolved
                if gap:
                    details += f"<p class='muted'>{escape(LABELS['remaining_gap'])}: {escape(gap)}</p>"
            for binding in bug.evidence_bindings:
                case = cases[binding.case_id]
                event = next((item for item in case.events if item.event_id == binding.event_id), None)
                bindings[binding.evidence_id] = (bug_id, binding, event, case)
                details += f"<p>{badge(binding.role)} {escape(binding.reason)}"
                if event:
                    details += f" · {escape(label(event.source_kind))}: {escape(event.description)}"
                    if event.source_ref:
                        details += " · " + source_link(event.source_ref, compact=True)
                    if event.source_kind == "waveform":
                        details += (f"<br><code>{escape(event.signal_path)}</code> · {escape(LABELS['raw_time'])}: {event.time}"
                                    f"<br><code>{escape(event.raw_value)}</code> · {escape(event.condition)}")
                        for field in decode_fields(event.raw_value, event.fields):
                            meaning = LABELS['unknown_enum'] if field['enum_status'] == 'unknown' else field['meaning']
                            details += f"<br><code>{escape(field['name'])}={escape(field['value'])}</code> {escape(meaning)}"
                        if event.receipt_id in receipt_links:
                            nav_id = hashlib.sha256((binding.evidence_id + event.receipt_id).encode()).hexdigest()
                            wave = next(item for item in case_waveforms(case) if item.receipt_id == event.receipt_id)
                            token = parse_qs(urlsplit(wave.viewer_url).query)["wave"][0]
                            payload = decode_waveform_viewer_token(token)
                            navigation[nav_id] = {"snapshot": snapshot_paths[event.receipt_id].name,
                                "wave": token, "start": payload["start"], "end": payload["end"],
                                "cursor": str(event.time), "signals": payload["signals"],
                                "description": event.description, "signal_path": event.signal_path,
                                "fields": decode_fields(event.raw_value, event.fields), "sources": []}
                            for reference in [*event.rtl_refs, *(field.source_ref for field in event.fields)]:
                                rendered = source_link(reference)
                                match = re.search(r"href='([^']+)'", rendered)
                                if match:
                                    navigation[nav_id]["sources"].append({"title": reference, "url": html.unescape(match.group(1))})
                            url = receipt_links[event.receipt_id] + "&event=" + nav_id
                            caption_event = f"{caption} · {LABELS['case']} {case_number[case.case_id]} · {label(event.kind)} · {event.time}"
                            event_link = f"<a href='{escape(url)}' target='_blank' rel='noopener'>{escape(caption_event)}</a>"
                            wave_links.append(f"<li>{event_link}</li>")
                            observations[binding.evidence_id] = event_link
                            downloads[event.receipt_id] = (case, snapshot_paths[event.receipt_id])
                            if binding.role == "direct":
                                available_direct.add(bug_id)
                        else:
                            details += f"<br>{escape(LABELS['wave_preview_unavailable'])}"
                    else:
                        observations[binding.evidence_id] = (f"{escape(caption)} · {escape(LABELS['case'])} {case_number[case.case_id]} · "
                            f"{escape(label(event.source_kind))}: " + (source_link(event.source_ref, compact=True) if event.source_ref else escape(event.description)))
                if binding.remaining_gap:
                    details += f"<br>{escape(LABELS['remaining_gap'])}: {escape(binding.remaining_gap)}"
                details += "</p>"
            technical.append(details)
            references.extend([bug.decision.spec_ref, *phenomenon.spec_expected.source_refs, *bug.spec_refs])
            references.extend([bug.decision.rtl_ref, *bug.rtl_refs])
            references.extend(ref for binding in bug.evidence_bindings for event in cases[binding.case_id].events
                              if event.event_id == binding.event_id for ref in event.rtl_refs)
        selected = bindings.get(root.primary_evidence_id) if root else None
        thumbnail = f"<p class='muted'>{escape(LABELS['no_primary_preview'])}</p>"
        preview_status, preview_gap = "unavailable", ""
        if selected:
            bug_id, binding, event, case = selected
            if event and event.receipt_id in snapshot_paths:
                wave = next(item for item in case_waveforms(case) if item.receipt_id == event.receipt_id)
                try:
                    measured = snapshot_preview(snapshot_paths[event.receipt_id], wave, event)
                    nav_id = hashlib.sha256((binding.evidence_id + event.receipt_id).encode()).hexdigest()
                    url = receipt_links[event.receipt_id] + "&event=" + nav_id
                    thumbnail = (f"<p class='muted'>{escape(LABELS['phenomenon'])} {member_number[bug_id]} · "
                                 f"{escape(LABELS['case'])} {case_number[case.case_id]} · {measured['start']}–{measured['end']}</p>"
                                 f"<a class='wave-preview' href='{escape(url)}' target='_blank' rel='noopener'>{measured['svg']}</a>"
                                 f"<p class='muted'>{escape(LABELS['raw_time'])}: {event.time} · {escape(LABELS['timescale'])}: "
                                 f"{escape(measured['timescale'] or LABELS['not_recorded'])}</p>")
                    preview_status = "available"
                except (ValueError, RuntimeError, OSError, ImportError) as error:
                    preview_gap = str(error)[:300]
                    thumbnail += f"<p class='muted'>{escape(preview_gap)}</p>"
        download_items = []
        for receipt_id, (case, snapshot) in downloads.items():
            item = (f"<li>{escape(LABELS['case'])} {case_number[case.case_id]} · <code>{escape(receipt_id)}</code>"
                    f" · <a href='../waveforms/{snapshot.name}' download>{escape(LABELS['download_original'])}</a>")
            exported = exports.get(receipt_id, {})
            if exported.get("status") == "available":
                fragment = Path(exported.get("file", ""))
                target = (output.parent / "report" / fragment).resolve()
                if (fragment.is_absolute() or ".." in fragment.parts or not target.is_relative_to((output.parent / "report").resolve())
                        or not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != exported.get("sha256")
                        or hashlib.sha256(snapshot.read_bytes()).hexdigest() != exported.get("source_sha256")):
                    raise ValueError("VCD export identity or path is invalid")
                item += f" · <a href='../{escape(fragment.as_posix())}' download>{escape(LABELS['download_vcd'])}</a>"
            download_items.append(item + "</li>")
        root_status = "complete" if set(members) <= available_direct else "incomplete"
        context_gap = not index.dut_context.text or bool(root and not root.affected_behavior.text)
        if root:
            root_manifest.append({"root_id": root.root_id, "page": "roots/" + root_page(root.root_id),
                                  "phenomenon_ids": list(members), "primary_evidence_id": root.primary_evidence_id,
                                  "preview_status": preview_status, "preview_gap": preview_gap,
                                  "evidence_status": root_status, "context_status": "incomplete" if context_gap else "complete"})
        identity = root.root_id if root else members[0]
        heading = root.title if root else bugs[members[0]].phenomenon.actual.summary
        mechanism = ""
        if root:
            rows = []
            for step in root.causal_steps:
                refs = " · ".join(source_link(ref, compact=True) for ref in step.rtl_refs)
                observed = "<br>".join(observations[eid] for eid in step.evidence_ids if eid in observations)
                rows.append(f"<li><p>{escape(step.summary)}</p><p class='muted'>{escape(LABELS['rtl_reasoning'])} · {refs}</p>"
                            + (f"<p>{observed}</p>" if observed else "") + "</li>")
                references.extend(step.rtl_refs)
            mechanism = (f"<div class='root-mechanism'><h3>{escape(LABELS['shared_mechanism'])}</h3><ol class='chain'>{''.join(rows)}</ol>"
                         f"<details><summary>{escape(LABELS['cause_details'])}</summary><p>{escape(root.first_error)}</p>"
                         f"<p>{escape(root.causal_chain)}</p></details></div>")
        provenance = "".join(f"<li><code>{escape(bug_id)}</code> {source_link(ref, compact=True)}</li>" for bug_id in members
                             for ref in [index.bugs[bug_id].summary_ref, *index.bugs[bug_id].analysis_refs] if ref)
        key_sources = []
        for reference in dict.fromkeys(ref for ref in references if ref):
            match = REF_PATTERN.fullmatch(reference)
            suffix = Path(match.group(1)).suffix.lower() if match else ""
            kind = "RTL" if suffix in RTL_SUFFIXES else "CASE" if suffix == ".py" else LABELS['document_basis']
            key_sources.append(f"<li>{escape(kind)} · {source_link(reference, compact=True)}</li>")
        reference_html = "".join(key_sources[:6])
        if len(key_sources) > 6:
            reference_html += f"<li><details><summary>{escape(LABELS['more_sources'])}</summary><ul>{''.join(key_sources[6:])}</ul></details></li>"
        context = index.dut_context
        context_html = (f"<p>{escape(context.text or context.unavailable_reason)}</p>"
                        + "<p class='muted'>" + " · ".join(source_link(ref, compact=True) for ref in context.source_refs) + "</p>")
        if root:
            affected = root.affected_behavior
            context_html += (f"<p><strong>{escape(LABELS['affected_behavior'])}:</strong> {escape(affected.text or affected.unavailable_reason)}</p>"
                             + "<p class='muted'>" + " · ".join(source_link(ref, compact=True) for ref in affected.source_refs) + "</p>")
        comparison_table = (f"<div class='table-wrap'><table><thead><tr><th>{escape(LABELS['phenomenon'])}</th>"
                            f"<th>{escape(LABELS['expected'])}</th><th>{escape(LABELS['observed'])}</th></tr></thead><tbody>{''.join(comparisons)}</tbody></table></div>")
        body = (f"<nav class='crumb'><a href='../index.html'>{escape(LABELS['module'])}</a> / <code>{escape(identity)}</code></nav>"
                "<div class='detail-layout'><article class='report-text'>"
                f"<header><small class='mono'>{escape(identity)}</small><h1>{escape(heading or identity)}</h1>{badge(root_status if root else bugs[members[0]].decision.verdict)}</header>"
                f"<section data-section='dut'><h2>01 {escape(LABELS['dut_overview'])}</h2>{context_html}</section>"
                f"<section data-section='goal'><h2>02 {escape(LABELS['verification_goal'])}</h2>{''.join(goals)}</section>"
                f"<section data-section='scenario'><h2>03 {escape(LABELS['scenario_analysis'])}</h2>{''.join(scenarios)}"
                f"<details class='case-details'><summary>{escape(LABELS['case_details'])}</summary>{''.join(technical)}</details></section>"
                f"<section data-section='rtl'><h2>04 {escape(LABELS['rtl_analysis'])}</h2>{comparison_table}{mechanism}</section></article>"
                f"<aside class='report-context'><section><h2>{escape(LABELS['key_wave'])}</h2>{thumbnail}"
                f"<ul class='wave-links'>{''.join(wave_links)}</ul>"
                f"<details><summary>{escape(LABELS['snapshot_downloads'])}</summary><ul>{''.join(download_items)}</ul></details>"
                f"<p class='muted'>{escape(LABELS['wave_preview_server_hint'])}</p></section>"
                f"<section><h2>{escape(LABELS['key_sources'])}</h2><ul>{reference_html}</ul>"
                f"<details class='original-report'><summary>{escape(LABELS['original_report'])}</summary><ul>{provenance or none_li}</ul></details>"
                "</section></aside></div>")
        return page(f"{name}: {identity}", body)

    for root in roots.roots:
        pages["report/roots/" + root_page(root.root_id)] = detail_page(root, root.bug_ids)
    for position, bug_id in enumerate(index.bug_order, 1):
        bug = bugs[bug_id]
        target = bug_pages[bug_id]
        if bug.decision.root_id in root_by_id:
            target += "#" + bug_anchors[bug_id]
        else:
            pages["report/" + target] = detail_page(None, [bug_id])
        filename = f"bug_{position:04d}.html"
        pages[f"report/bugs/{filename}"] = page(bug_id,
            f"<nav class='crumb'><a href='../index.html'>{escape(LABELS['module'])}</a></nav>"
            f"<p><a href='../{escape(target)}'>{escape(LABELS['open_root_detail'])} · <code>{escape(bug_id)}</code></a></p>"
            f"<script>location.replace({json.dumps('../' + target)});</script>")
        if bug.decision.verdict == "confirmed" and bug.decision.review_confidence is not None and bug.decision.review_confidence >= CONFIDENCE_FLOOR:
            if bug.decision.root_id not in root_by_id:
                raise ValueError(f"confirmed phenomenon has no root: {bug_id}")
            visible_bugs.setdefault(bug.decision.root_id, []).append((bug_id, filename, bug))
        manifest_bugs.append({"bug_id": bug_id, "page": target, "root_id": bug.decision.root_id,
                              "receipts": [wave.receipt_id for case_id in bug.case_ids for wave in case_waveforms(cases[case_id])],
                              "viewers": [wave.viewer_url for case_id in bug.case_ids for wave in case_waveforms(cases[case_id])],
                              "spec_refs": bug.spec_refs, "rtl_refs": bug.rtl_refs})
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
                          f"<tr><td><a class='mono' href='roots/{root_page(root_id)}'>{escape(root_id)}</a>"
                          f"<div class='muted root-note'>{escape(root.title)}</div>"
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
    incomplete = (review_incomplete(manifest, cases, environment)
                  or not index.dut_context.text
                  or any(item["context_status"] != "complete" for item in root_manifest)
                  or any(item["evidence_status"] != "complete" for item in root_manifest)
                  or any(bug.decision.verdict == "inconclusive" for bug in bugs.values()))
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
    overview = (f"<nav class='crumb'><a href='../../../index.html'>{escape(LABELS['all_modules'])}</a> / {escape(LABELS['module'])}</nav>"
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
    all_rows = "".join(f"<tr><td><a href='{escape(item['page'])}'><code>{escape(item['bug_id'])}</code></a></td>"
                       f"<td>{badge(bugs[item['bug_id']].decision.verdict)}</td><td>{escape(item['root_id'] or LABELS['none'])}</td></tr>"
                       for item in manifest_bugs)
    overview += (f"<section class='card'><h2>{escape(LABELS['all_decisions'])}</h2>"
                 f"<p>{escape(LABELS['root_count'])}: {len(roots.roots)} · {escape(LABELS['phenomenon_count'])}: {len(bugs)} · {escape(LABELS['cases'])}: {len(cases)}</p>"
                 f"<div class='table-wrap'><table><tr><th>{escape(LABELS['phenomenon'])}</th><th>{escape(LABELS['verdict'])}</th><th>{escape(LABELS['root'])}</th></tr>{all_rows}</table></div></section>")
    pages["report/surfer/report-events.json"] = json.dumps({"schema": "bug_review_navigation.v1", "events": navigation}, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    pages["report/index.html"] = page(f"{name} {LABELS['bug_review']}", overview)
    report_manifest = {"schema": "bug_review_report.v4", "workspace": name,
                       "detail_layout": "scenario_rtl.v1",
                       "review_status": status, "pages": sorted(p.removeprefix("report/") for p in pages),
                       "high_confidence_root_count": len(root_rows),
                       "bugs": manifest_bugs, "cases": manifest_cases, "roots": root_manifest,
                       "root_count": len(roots.roots), "phenomenon_count": len(bugs),
                       "waveform_exports": {key: value for key, value in exports.items() if key in snapshot_paths},
                       "waveform_previews": sorted(preview_manifest, key=lambda item: item["case_id"]),
                       "sources": sorted(source_catalog.values(), key=lambda item: item["path"]),
                       "collected": len(manifest.collected), "unexecuted": missing}
    return pages, report_manifest


def verify_pages(output: Path, index, cases: dict, bugs: dict, roots) -> None:
    """Compare rendered pages, source anchors, and links with active records."""
    coverage = load_record(output, index.coverage_path, "coverage")
    pages, expected_manifest = render_pages(output, index, cases, bugs, roots, coverage)
    if expected_manifest["waveform_previews"]:
        surfer = output.parent / "report/surfer"
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
        path = output.parent / filename
        if not path.is_file() or path.read_text(encoding="utf-8") != expected:
            raise ValueError(f"report page missing or differs from review records: {filename}")
        if not filename.endswith(".html"):
            continue
        for href in re.findall(r"href='([^']+)'", expected):
            if href.startswith(("http://", "https://", "/surfer/", "#")):
                continue
            if filename == "report/index.html" and href == "../../../index.html":
                continue
            parsed = urlsplit(html.unescape(href))
            target = (path.parent / unquote(parsed.path)).resolve()
            if not target.is_relative_to((output.parent / "report").resolve()) or not target.is_file():
                raise ValueError(f"broken report link in {filename}: {href}")
            if parsed.query and target == (output.parent / "report/surfer/index.html").resolve():
                query = parse_qs(parsed.query)
                payload = decode_waveform_viewer_token(query.get("wave", [""])[0])
                snapshot = query.get("snapshot", [""])[0]
                if (payload["v"] != 2 or re.fullmatch(r"[0-9a-f]{32}\.(?:fst|vcd)", snapshot) is None
                        or not (output.parent / "report/waveforms" / snapshot).is_file()):
                    raise ValueError(f"invalid report waveform preview link: {href}")
                if set(query) - {"wave", "snapshot", "event"}:
                    raise ValueError(f"unexpected waveform navigation fields: {href}")
                if "event" in query:
                    events = json.loads(pages["report/surfer/report-events.json"])["events"]
                    event = events.get(query["event"][0])
                    if not event or event["wave"] != query["wave"][0] or event["snapshot"] != snapshot:
                        raise ValueError(f"waveform event identity mismatch: {href}")
            elif parsed.query:
                raise ValueError(f"unexpected report query link in {filename}: {href}")
            if parsed.fragment:
                match = re.fullmatch(r"L(\d+)-L(\d+)", parsed.fragment)
                content = pages.get(str(target.relative_to(output.parent)))
                if match is None:
                    if content is None or parsed.fragment not in re.findall(r"id=['\"]([^'\"]+)['\"]", content):
                        raise ValueError(f"broken report anchor in {filename}: {href}")
                    continue
                if (match is None or content is None or int(match.group(1)) > int(match.group(2))
                        or f"id='L{match.group(1)}'" not in content
                        or f"id='L{match.group(2)}'" not in content):
                    raise ValueError(f"broken source range in {filename}: {href}")
    if read_object(output.parent / "report/report_manifest.json") != expected_manifest:
        raise ValueError("report/report_manifest.json differs from current pages")
