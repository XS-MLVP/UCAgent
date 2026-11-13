"""Readable PPA experiment histories derived from measured versions and file identities."""

from __future__ import annotations

import difflib
from html import escape
import os
from pathlib import Path
from urllib.parse import quote

from .contracts import atomic_text, resolve_workspace_path


def changed_files(before: dict, after: dict) -> list[dict]:
    """Describe actual additions, modifications, and deletions, including mode changes."""

    return [
        {"path": name, "action": "add" if name not in before else
         "delete" if name not in after else "modify",
         "before": before.get(name), "after": after.get(name)}
        for name in sorted(before.keys() | after.keys())
        if before.get(name) != after.get(name)
    ]


def write_source_diff(path: Path, before: dict[str, Path], after: dict[str, Path]) -> None:
    """Write a review diff from retained files; identify binary or oversized files explicitly."""

    parts = []
    for name in sorted(before.keys() | after.keys()):
        old_size = before[name].stat().st_size if name in before else 0
        new_size = after[name].stat().st_size if name in after else 0
        if max(old_size, new_size) > 2_000_000:
            parts.append(f"Content diff omitted for binary/large file: {name}; "
                         f"{old_size} -> {new_size} bytes. See file identities in the optimization log.\n")
            continue
        old = before[name].read_bytes() if name in before else b""
        new = after[name].read_bytes() if name in after else b""
        if old == new:
            action = "Empty file added" if name not in before else "Empty file deleted" if name not in after else "File metadata changed"
            parts.append(f"{action}: {name}\n")
            continue
        try:
            if b"\0" in old + new:
                raise ValueError("binary content")
            old_text, new_text = old.decode("utf-8"), new.decode("utf-8")
        except (UnicodeError, ValueError):
            parts.append(f"Content diff omitted for binary/large file: {name}; "
                         f"{len(old)} -> {len(new)} bytes. See file identities in the optimization log.\n")
            continue
        for line in difflib.unified_diff(old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
                                         fromfile="a/" + name, tofile="b/" + name):
            parts.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    atomic_text(path, "".join(parts))


def write_optimization_log(
    path: Path, entries: list[dict], *, best_iteration: int | None, stop_reason: str | None,
) -> None:
    """Atomically replace Markdown and standalone HTML views of the same measured history.

    Callers supply task-facing fields from their validated records. These views
    never feed acceptance decisions or execute measurements. Escaping applies to
    both views because hypotheses and repository paths are authored inputs.
    """

    markdown = []
    html = []

    def markdown_text(value: str) -> str:
        """Keep authored markup, links, table separators, and headings inert."""

        text = escape(value)
        for char in "\\`*[]#!|~":
            text = text.replace(char, f"&#{ord(char)};")
        return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")

    def heading(level: int, title: str) -> None:
        """Append a spaced Markdown heading and its escaped HTML counterpart."""

        markdown.extend(["", "#" * level + " " + markdown_text(title), ""])
        html.append(f"<h{level}>{escape(title)}</h{level}>")

    def field(label: str, value: object) -> None:
        """Render authored text as inert content in both report formats."""

        text = str(value).strip() or "unavailable"
        markdown.extend([f"{label}: {markdown_text(text)}", ""])
        html.append(f"<p><strong>{escape(label)}:</strong> {escape(text)}</p>")

    def table(headers: list[str], rows: list[list]) -> None:
        """Render an escaped comparison table without interpreting authored markup."""

        markdown.append("| " + " | ".join(headers) + " |")
        markdown.append("| " + " | ".join("---" for _ in headers) + " |")
        html.append("<div class=table><table><thead><tr>" + "".join(
            f"<th>{escape(value)}</th>" for value in headers) + "</tr></thead><tbody>")
        for row in rows:
            cells = [str(value) if value is not None else "unavailable" for value in row]
            markdown.append("| " + " | ".join(
                markdown_text(value) for value in cells) + " |")
            html.append("<tr>" + "".join(f"<td>{escape(value)}</td>" for value in cells) + "</tr>")
        markdown.append("")
        html.append("</tbody></table></div>")

    heading(1, "PPA Optimization Log")
    field("Best measured version", f"v{best_iteration}" if best_iteration is not None else "unavailable")
    field("Stop reason", stop_reason or "in_progress")
    field("Scope", "Hypotheses describe intended effects; metric comparisons show observed effects. Unmeasured attempts do not count as measured rounds.")
    for entry in entries:
        heading(2, f"v{entry['iteration']} / {entry['label']} / {entry['decision']}")
        field("Recorded at (UTC)", entry["recorded_at"])
        field("Optimization direction and change", entry["hypothesis"])
        if entry.get("hotspot"):
            field("Target hotspot", entry["hotspot"])
        if entry.get("expected_metrics"):
            field("Expected metrics", ", ".join(entry["expected_metrics"]))
        field("Compared with", entry["compared_with"])
        field("Decision reason", entry["reason"])
        if entry.get("interface"):
            field("Interface version", entry["interface"])
        score = entry.get("score") or {}
        field("PPA selection score", score.get("value") if score.get("status") == "available" else "unavailable")
        changes = entry["changes"]
        if changes:
            table(["Changed file", "Operation", "Before", "After"], [
                [row["path"], row["action"], row["before"], row["after"]] for row in changes
            ])
        else:
            field("Changed files", "No source changes (baseline).")
        metrics = entry["metrics"]
        if metrics:
            previous = entry["changes_previous"] or {}
            base = entry["changes_base"] or {}
            table(["Metric", "Previous", "Measured", "Unit", "Change % vs previous", "Change % vs base", "Assessment vs previous"], [
                [key, previous.get(key, {}).get("baseline"), value["value"], value["unit"],
                 previous.get(key, {}).get("percent_change"), base.get(key, {}).get("percent_change"),
                 previous.get(key, {}).get("assessment", "baseline")]
                for key, value in sorted(metrics.items())
            ])
        else:
            field("Metrics", "Unavailable; this attempt has no complete PPA measurement.")
        evidence = entry["evidence"]
        href = quote(evidence, safe="/.")
        markdown.extend([f"[Measurement evidence]({href})", ""])
        html.append(f'<p><a href="{escape(href, quote=True)}">Measurement evidence</a></p>')
        if entry.get("diff"):
            href = quote(entry["diff"], safe="/.")
            markdown.extend([f"[Source diff]({href})", ""])
            html.append(f'<p><a href="{escape(href, quote=True)}">Source diff</a></p>')
    atomic_text(path, "\n".join(markdown))
    atomic_text(path.with_suffix(".html"), '<!doctype html>\n<html lang="en"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>PPA Optimization Log</title><style>'
                'body{font:15px/1.6 system-ui;margin:2rem auto;padding:0 1rem;max-width:1200px;color:#182330}'
                'h2{margin-top:2rem;border-top:1px solid #ccd5df;padding-top:1rem}'
                'p,td{white-space:pre-wrap;overflow-wrap:anywhere}.table{overflow-x:auto}'
                'table{border-collapse:collapse;width:100%;font-size:13px}'
                'th,td{padding:8px;border:1px solid #ccd5df;text-align:left}th{background:#edf3f9}'
                '</style><body>' + "\n".join(html) + '</body></html>\n')


def write_unit_optimization_log(workspace: Path, ledger: dict, ledger_file: str) -> Path:
    """Render the unit workflow's validated ledger as a readable measured history."""

    ledger_path = resolve_workspace_path(workspace, ledger_file)
    log_path = resolve_workspace_path(
        workspace, ledger_path.with_name(f"{ledger['dut']}_optimization_log.md").relative_to(workspace)
    )
    for record in ledger["records"]:
        if record.get("source_diff"):
            parent = next(row for row in ledger["records"] if row["iteration"] == record["parent_accepted_iteration"])
            before_root = resolve_workspace_path(workspace, parent.get("accepted_snapshot") or parent["snapshot"])
            after_root = resolve_workspace_path(workspace, record["candidate_snapshot"])
            write_source_diff(resolve_workspace_path(workspace, record["source_diff"]),
                              {row["path"]: resolve_workspace_path(before_root, row["path"], must_exist=True)
                               for row in record["source_changes"] if row["before"] is not None},
                              {row["path"]: resolve_workspace_path(after_root, row["path"], must_exist=True)
                               for row in record["source_changes"] if row["after"] is not None})
    entries = [{
        "iteration": row["iteration"], "label": row["kind"],
        "decision": "accepted" if row["accepted"] else "rejected",
        "recorded_at": row["recorded_at"], "hypothesis": row["optimization_hypothesis"],
        "hotspot": row.get("target_hotspot"), "expected_metrics": row.get("expected_metrics"),
        "compared_with": f"accepted v{row['parent_accepted_iteration']}" if row["kind"] != "base" else "baseline",
        "reason": row.get("rejection_reason") or "functional and PPA gates passed",
        "changes": row["source_changes"],
        "metrics": {**row["ppa_metrics"], **row["performance_metrics"]},
        "changes_previous": row.get("metric_changes_to_previous"),
        "changes_base": row.get("metric_changes_to_base"), "score": row.get("ppa_score"),
        "evidence": os.path.relpath(ledger_path, log_path.parent),
        "diff": os.path.relpath(resolve_workspace_path(workspace, row["source_diff"]), log_path.parent)
                if row.get("source_diff") else None,
    } for row in ledger["records"]]
    write_optimization_log(log_path, entries, best_iteration=ledger["best_iteration"],
                           stop_reason=ledger.get("stop_reason"))
    return log_path
