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
    names = [name for name, _ in job["runs"]]
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
        inventory = target / "bug_inventory.json"
        if inventory.is_file():
            bugs = read_object(inventory)["bugs"]
            lines.append(f"- Input: {len(bugs)} reported Bug claims.")
        replay = target / "replay_results.json"
        if replay.is_file():
            data = read_object(replay)
            lines.append(f"- Replay: {data['suite_test_count']} tests, {data['suite_failed_count']} failures.")
        waveform = target / "waveform_reviews.json"
        if waveform.is_file():
            cases = read_object(waveform)["cases"]
            signed = sum(row["waveform"].get("verified_evidence", {}).get("success") is True
                         for row in cases)
            lines.append(f"- Waveform: {len(cases)} reviewed failures, {signed} with signed evidence.")
        reviews = target / "bug_reviews.json"
        if reviews.is_file():
            bugs = read_object(reviews)["bugs"]
            counts = {verdict: sum(row["verdict"] == verdict for row in bugs)
                      for verdict in ("confirmed", "refuted", "inconclusive")}
            groups = read_object(target / "root_groups.json")["groups"]
            lines.append(f"- Decisions: {counts['confirmed']} confirmed, "
                         f"{counts['refuted']} refuted, {counts['inconclusive']} inconclusive; "
                         f"{len(groups)} root groups.")
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
