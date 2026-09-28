"""Create an empty decision and root JSON format without filling evidence."""

from __future__ import annotations

import json
from pathlib import Path

from ucagent.util.config import load_runtime_config

from bug_review.analysis_core.task_manifest import atomic_write_json


def main() -> None:
    """Write only decisions[] and roots[] under the resolved private output."""
    root = Path.cwd().resolve()
    output = (root / load_runtime_config(root)["OUT"]).resolve()
    if not output.is_relative_to(root) or output == root:
        raise ValueError("Resolved OUT must be a child of the current workspace")
    target = output / "drafts/decisions.json"
    if target.exists():
        raise FileExistsError("drafts/decisions.json already exists")
    atomic_write_json(target, {"decisions": [], "roots": []})
    print(json.dumps({"draft_path": str(target.relative_to(root))}))


if __name__ == "__main__":
    main()
