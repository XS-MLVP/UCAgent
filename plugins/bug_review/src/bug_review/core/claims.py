"""List source Bug blocks without assigning their semantic ownership."""

from __future__ import annotations

from pathlib import Path
import re
from .layout import resolve_logical_path


BG_TAG = re.compile(r"<BG-([A-Za-z0-9_-]+)>")
SECTION_HEADING = re.compile(r"^#{1,5}\s")


def normalize_tc_label(label: str) -> str:
    """Map one original-report TC label to the canonical ``tests/`` case ID."""
    prefix = "unity_test/tests/"
    return "tests/" + label.removeprefix(prefix) if label.startswith(prefix) else label


def report_claim_blocks(source: Path, name: str) -> list[dict]:
    """Return exact tagged Markdown blocks as source references, without joining Bugs."""
    dut = name
    relative = Path("unity_test") / f"{dut}_bug_analysis.md"
    path = resolve_logical_path(source, relative.as_posix())
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    headings = [number for number, line in enumerate(lines, 1)
                if SECTION_HEADING.match(line) or (line.startswith("###### ") and BG_TAG.search(line))]
    blocks = []
    for position, start in enumerate(headings):
        if not lines[start - 1].startswith("###### "):
            continue
        label = BG_TAG.search(lines[start - 1])
        if label is None:
            continue
        end = headings[position + 1] - 1 if position + 1 < len(headings) else len(lines)
        raw_cases = sorted(set(re.findall(r"<TC-([^>]+)>", "\n".join(lines[start - 1:end]))))
        case_labels = [normalize_tc_label(case) for case in raw_cases]
        blocks.append({"ref": f"{relative.as_posix()}:{start}-{end}",
                       "source_label": f"BG-{label.group(1)}",
                       "heading": lines[start - 1].strip()[:240],
                       "tc_labels": sorted(set(case_labels))})
    return blocks


def source_role(reference: str) -> str:
    """Label reported conclusions so they are not mistaken for independent proof."""
    name = Path(reference.split(":", 1)[0]).name.lower()
    return ("original_report_claim" if re.search(r"bug_(?:summary|analysis)|issues", name)
            else "source_material")
