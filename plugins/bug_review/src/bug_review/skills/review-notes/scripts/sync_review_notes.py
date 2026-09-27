"""Refresh a human-readable Bug Review summary from completed stage artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from ucagent.util.config import load_runtime_config
from bug_review.review_store import load_record


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
    if job.get("schema") != "bug_review_job.v7":
        raise ValueError("review_job.json must use bug_review_job.v7")
    names = [job["source_run"][0]]
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
        target = output
        lines.extend([f"### {name}", ""])
        review = target / "review_index.json"
        if review.is_file():
            data = load_record(target, "review_index.json", "index")
            bug_records = [load_record(target, entry.review_path, "bug")
                           for entry in data.bugs.values() if entry.review_path]
            counts = {verdict: sum(row.decision.verdict == verdict for row in bug_records)
                      for verdict in ("confirmed", "refuted", "inconclusive")}
            cases = [load_record(target, entry.record_path, "case") for entry in data.cases.values()]
            replayed = sum(case.replay.status != "not_run"
                           for case in cases)
            signed = sum(bool(case.waveform.receipt_id) for case in cases)
            roots = load_record(target, data.root_path, "roots") if data.root_path else None
            lines.append(f"- Decisions: {counts['confirmed']} confirmed, "
                         f"{counts['refuted']} refuted, {counts['inconclusive']} inconclusive; "
                         f"{len(roots.roots) if roots else 0} root groups.")
            lines.append(f"- Cases: {replayed} replayed; {signed} signed WaveInfo receipts.")
        report = target / "report/index.html"
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
