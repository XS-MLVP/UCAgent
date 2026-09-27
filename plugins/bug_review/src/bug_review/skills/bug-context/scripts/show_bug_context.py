"""Print bounded source and evidence context for one exact Bug ID."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ucagent.util.config import load_runtime_config

from bug_review.review_context import SECTIONS, bug_context


def main() -> None:
    """Resolve the active module output and emit requested sections as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bug_id")
    parser.add_argument("sections", nargs="*", choices=SECTIONS)
    parser.add_argument("--max-lines", type=int, default=20)
    parser.add_argument("--max-chars", type=int, default=16000)
    parser.add_argument("--case-offset", type=int, default=0)
    parser.add_argument("--ref-offset", type=int, default=0)
    args = parser.parse_args()
    workspace = Path.cwd().resolve()
    runtime = load_runtime_config(workspace)
    output = (workspace / runtime["OUT"]).resolve()
    if not output.is_relative_to(workspace):
        raise ValueError("Resolved OUT must remain inside the active workspace")
    print(json.dumps(bug_context(output, args.bug_id, args.sections, args.max_lines,
                                 args.max_chars, args.case_offset, args.ref_offset),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
