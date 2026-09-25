"""Render HTML directly from canonical Bug Review JSON documents."""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import quote

from ucagent.util.config import load_runtime_config


def read_review(path: Path) -> dict:
    """Load and validate the canonical review document header."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != "bug_review.v3":
        raise ValueError(f"bug_review.v3 JSON required: {path}")
    if not isinstance(value.get("suspected_bugs"), list) or not isinstance(value.get("cases"), dict):
        raise ValueError(f"Bug and case collections are malformed: {path}")
    return value


def page(title: str, body: str) -> str:
    """Wrap report content in a compact HTML document."""
    return ("<!doctype html><html lang='en'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width'>"
            f"<title>{html.escape(title)}</title>"
            "<style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:16px}"
            "table{border-collapse:collapse;width:100%}td,th{border:1px solid #bbb;padding:8px;vertical-align:top}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere}li{margin:6px 0}</style>"
            f"<h1>{html.escape(title)}</h1>{body}</html>")


def text(value: object) -> str:
    """Return an escaped compact text representation for an HTML cell."""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, indent=2)
    return html.escape(str(value if value is not None else ""))


def source_links(name: str, refs: object, *, tests: bool = False) -> str:
    """Render source-relative evidence references as links to their staged copies."""
    if not isinstance(refs, list):
        return "<ul></ul>"
    items = []
    for entry in refs:
        ref = entry.get("ref", "") if isinstance(entry, dict) else str(entry)
        raw_path = str(ref).rsplit(":", 1)[0] if ":" in str(ref) else str(ref)
        path = Path(raw_path)
        if path.is_absolute() or ".." in path.parts:
            items.append(f"<li>{text(ref)}</li>")
            continue
        parts = list(path.parts)
        if parts and parts[0] == name:
            parts = parts[1:]
        relative = Path(*parts).as_posix()
        if tests and relative.startswith("unity_test/tests/"):
            relative = relative.removeprefix("unity_test/tests/")
            href = f"../../tests/{quote(name, safe='')}/unity_test/tests/{quote(relative, safe='/')}"
        elif tests:
            items.append(f"<li>{text(ref)}</li>")
            continue
        else:
            href = f"../../inputs/{quote(name, safe='')}/{quote(relative, safe='/')}"
        label = text(ref)
        items.append(f"<li><a href='{html.escape(href, quote=True)}'>{label}</a></li>")
    return "<ul>" + "".join(items) + "</ul>"


def render_workspace(target: Path, document: dict) -> None:
    """Render a workspace index and one detail page per Bug."""
    name = document["workspace"]["name"]
    bugs = document["suspected_bugs"]
    cases = document["cases"]
    roots = {root["root_id"]: root for root in document.get("root_causes", [])}
    rows = []
    for index, bug in enumerate(bugs, 1):
        filename = f"bug_{index:04d}.html"
        decision = bug.get("decision", {})
        summary = bug.get("bug_summary", {})
        evidence = bug.get("evidence", {})
        linked_cases = [cases[case_id] for case_id in evidence.get("case_ids", []) if case_id in cases]
        details = [
            f"<p><strong>{text(decision.get('verdict', 'inconclusive'))}</strong> · "
            f"review confidence {text(decision.get('review_confidence'))} · "
            f"root {text(decision.get('root_id') or 'none')}</p>",
            f"<h2>Original summary</h2><p>{text(summary.get('text', ''))}</p>",
            f"<h2>Analysis and decision</h2><p>{text(decision.get('rationale', ''))}</p>",
            f"<h2>Spec evidence</h2>{source_links(name, evidence.get('spec', []))}",
            f"<h2>RTL evidence</h2>{source_links(name, evidence.get('rtl', []))}",
            f"<h2>Functional test points</h2>{source_links(name, evidence.get('test_points', []), tests=True)}",
            f"<h2>Check points</h2><pre>{text(evidence.get('check_points', []))}</pre>",
            "<h2>Cases and waveform evidence</h2>",
        ]
        for case in linked_cases:
            replay, review, wave = case.get("replay", {}), case.get("test_review", {}), case.get("waveform", {})
            result = wave.get("result") if isinstance(wave.get("result"), dict) else {}
            viewer = result.get("waveform_viewer", {})
            viewer_url = viewer.get("url") if isinstance(viewer, dict) else None
            link = (f" · <a href='{html.escape(viewer_url, quote=True)}'>Open waveform</a>"
                    if isinstance(viewer_url, str) and viewer_url.startswith(("http://", "https://")) else "")
            details.append(
                f"<h3>{text(case.get('nodeid'))}</h3><p>Replay: {text(replay.get('status'))} · "
                f"Test review: {text(review.get('classification'))} · Waveform: {text(wave.get('conclusion'))} · "
                f"Receipt: {text(wave.get('receipt_id') or 'none')}{link}</p>"
                f"<details><summary>Case evidence</summary><pre>{text(case)}</pre></details>"
            )
        root_id = decision.get("root_id")
        if root_id in roots:
            details.append(f"<h2>Shared root cause</h2><pre>{text(roots[root_id])}</pre>")
        details.append("<details><summary>Complete Bug record</summary><pre>" + text(bug) + "</pre></details>")
        detail_body = ("<p><a href='index.html'>Workspace index</a> · "
                       "<a href='bug_review.json'>Canonical JSON</a></p>" + "".join(details))
        (target / filename).write_text(page(f"{name}: {bug['bug_id']}", detail_body), encoding="utf-8")
        rows.append(
            f"<tr><td><a href='{filename}'>{text(bug['bug_id'])}</a></td>"
            f"<td>{text(bug.get('origin'))}</td><td>{text(decision.get('verdict'))}</td>"
            f"<td>{text(decision.get('review_confidence'))}</td><td>{text(root_id)}</td></tr>"
        )
    verdicts = [bug.get("decision", {}).get("verdict", "inconclusive") for bug in bugs]
    counts = {key: verdicts.count(key) for key in ("confirmed", "refuted", "inconclusive")}
    body = ("<p><a href='../../index.html'>All workspaces</a> · "
            "<a href='bug_review.json'>Canonical JSON</a></p>"
            f"<p>Confirmed {counts['confirmed']} · Refuted {counts['refuted']} · "
            f"Inconclusive {counts['inconclusive']}</p>"
            "<table><tr><th>Bug</th><th>Origin</th><th>Verdict</th><th>Review confidence</th><th>Root group</th></tr>"
            + "".join(rows) + "</table>")
    (target / "index.html").write_text(page(f"{name} Bug Review", body), encoding="utf-8")


def main() -> None:
    """Render every selected workspace and the cross-workspace index."""
    workspace = Path.cwd().resolve()
    runtime = load_runtime_config(workspace)
    output = (workspace / runtime["OUT"]).resolve()
    if not output.is_relative_to(workspace) or output == workspace:
        raise ValueError("Resolved OUT must be inside the current workspace")
    job = json.loads((workspace / "review_job.json").read_text(encoding="utf-8"))
    if job.get("schema") != "bug_review_job.v4" or output != (workspace / job["output_dir"]).resolve():
        raise ValueError("Resolved OUT differs from the prepared Bug Review job")
    workspace_items = []
    for name, _ in job["source_runs"]:
        target = output / "workspaces" / name
        document = read_review(target / "bug_review.json")
        if document["workspace"].get("name") != name:
            raise ValueError(f"Workspace identity mismatch in {target / 'bug_review.json'}")
        render_workspace(target, document)
        verdicts = [bug.get("decision", {}).get("verdict", "inconclusive") for bug in document["suspected_bugs"]]
        confirmed, refuted = verdicts.count("confirmed"), verdicts.count("refuted")
        inconclusive = verdicts.count("inconclusive")
        workspace_items.append(
            f"<li><a href='workspaces/{html.escape(name)}/index.html'>{html.escape(name)}</a>: "
            f"{confirmed} confirmed, {refuted} refuted, {inconclusive} inconclusive</li>"
        )
    (output / "index.html").write_text(page("Bug Review", "<ul>" + "".join(workspace_items) + "</ul>"),
                                        encoding="utf-8")


if __name__ == "__main__":
    main()
