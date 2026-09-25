"""Refresh a human-readable Bug Review summary from completed stage artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from ucagent.util.config import load_runtime_config


START = "<!-- BUG-REVIEW-SUMMARY-START -->"
END = "<!-- BUG-REVIEW-SUMMARY-END -->"


def read_object(path: Path) -> dict:
    """Read one completed JSON artifact as an object."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def main() -> None:
    """Replace only the generated notes section using resolved workflow paths."""
    workspace = Path.cwd().resolve()
    runtime = load_runtime_config(workspace)
    output = (workspace / runtime["OUT"]).resolve()
    if not output.is_relative_to(workspace) or output == workspace:
        raise ValueError("Resolved OUT must be inside the current workspace")
    job = read_object(workspace / "review_job.json")
    if output != (workspace / job["output_dir"]).resolve():
        raise ValueError("Resolved OUT differs from the prepared Bug Review output")
    names = [name for name, _ in job["source_runs"]]
    notes = workspace / "notes/bug_review_notes.md"
    notes.parent.mkdir(parents=True, exist_ok=True)
    if notes.is_file():
        original = notes.read_text(encoding="utf-8")
        if original.count(START) != 1 or original.count(END) != 1:
            raise ValueError("notes/bug_review_notes.md requires one summary marker pair")
    else:
        original = ("\n# Bug Review Notes\n\n## Analyst Notes\n\n"
                    f"## Stage Summary\n\n{START}\n\n{END}\n")
    lines = []
    for name in names:
        target = output / "workspaces" / name
        lines.extend([f"### {name}", ""])
        review = target / "bug_review.json"
        if review.is_file():
            data = read_object(review)
            bugs = data["suspected_bugs"]
            counts = {verdict: sum(row.get("decision", {}).get("verdict") == verdict for row in bugs)
                      for verdict in ("confirmed", "refuted", "inconclusive")}
            cases = list(data.get("cases", {}).values())
            replayed = sum(case.get("replay", {}).get("status") in
                           {"reproduced", "passed", "not_collected", "execution_error"} for case in cases)
            signed = sum(bool(case.get("waveform", {}).get("receipt_id")) for case in cases)
            lines.append(f"- Decisions: {counts['confirmed']} confirmed, "
                         f"{counts['refuted']} refuted, {counts['inconclusive']} inconclusive; "
                         f"{len(data.get('root_causes', []))} root groups.")
            lines.append(f"- Cases: {replayed} replayed; {signed} signed WaveInfo receipts.")
        report = target / "index.html"
        if report.is_file():
            relative = report.relative_to(workspace).as_posix()
            lines.append(f"- Report: [workspace page](../{relative}).")
        if lines[-1] == "":
            lines.append("- No completed stages yet.")
        lines.append("")
    generated = "\n".join(lines).rstrip() or "No completed stages yet."
    before, rest = original.split(START, 1)
    _, after = rest.split(END, 1)
    updated = before + START + "\n\n" + generated + "\n\n" + END + after
    descriptor, temporary = tempfile.mkstemp(prefix=".bug_review_notes.", dir=notes.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(updated)
        os.replace(temporary, notes)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(notes.relative_to(workspace))


if __name__ == "__main__":
    main()
