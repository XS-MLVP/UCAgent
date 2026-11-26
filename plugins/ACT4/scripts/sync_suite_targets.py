"""Render or check the target document from the packaged progress-sheet catalog."""

import argparse
from pathlib import Path

from ucagent_act4.suite_catalog import load_suite_catalog


START = "<!-- ACT4-SUITES:START -->"
END = "<!-- ACT4-SUITES:END -->"
TARGET_DOC = Path(__file__).resolve().parents[1] / "docs" / "test-suites.md"


def render_catalog() -> str:
    """Render a compact suite list with CLI targets and distinct original labels."""
    catalog = load_suite_catalog()
    lines = [
        f"Snapshot: **{catalog['retrieved_on']}**. "
        f"**{len(catalog['targets'])}** CLI targets / **{catalog['record_count']}** nonempty Test Suite cells.",
        "",
        "| Test Suite | Description |",
        "| --- | --- |",
    ]
    for target, entry in catalog["targets"].items():
        descriptions = dict.fromkeys(row["description"] for row in entry["rows"] if row["description"])
        label = f"`{target}`"
        if entry["test_suite"] != target:
            label += f"<br>{entry['test_suite']}"
        fields = [
            label,
            "; ".join(descriptions) or "Not specified in sheet",
        ]
        lines.append("| " + " | ".join(" ".join(field.split()).replace("|", "&#124;") for field in fields) + " |")
    lines.extend(["", "Non-target labels (headings or unspecified scope):", "",
                  "| Test Suite cell | Reason |", "| --- | --- |"])
    for name, entry in catalog["excluded"].items():
        lines.append(f"| {name} | {entry['reason']} |")
    return "\n".join(lines)


def main() -> int:
    """Update only the marked target list, or fail if it is out of sync."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check without modifying the target document")
    args = parser.parse_args()
    text = TARGET_DOC.read_text(encoding="utf-8")
    if text.count(START) != 1 or text.count(END) != 1:
        raise ValueError("Target document must contain exactly one pair of ACT4-SUITES markers")
    prefix, remainder = text.split(START)
    _, suffix = remainder.split(END)
    expected = prefix + START + "\n\n" + render_catalog() + "\n\n" + END + suffix
    if text != expected:
        if args.check:
            print("ACT4 target document is stale; run scripts/sync_suite_targets.py.")
            return 1
        TARGET_DOC.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
