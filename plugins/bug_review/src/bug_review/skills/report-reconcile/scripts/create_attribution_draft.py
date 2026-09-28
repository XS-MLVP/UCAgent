"""Create an empty Bug attribution JSON format for LLM-authored findings."""

from __future__ import annotations

import json
from pathlib import Path

from ucagent.util.config import load_runtime_config

from bug_review.review_attribution import create_attribution_draft


def main() -> None:
    """Write only the draft structure in the resolved private output directory."""
    root = Path.cwd().resolve()
    output = (root / load_runtime_config(root)["OUT"]).resolve()
    if not output.is_relative_to(root) or output == root:
        raise ValueError("Resolved OUT must be a child of the current workspace")
    print(json.dumps(create_attribution_draft(output), ensure_ascii=False))


if __name__ == "__main__":
    main()
