"""Collect pytest nodes and create the V3 full replay skeleton."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ucagent.util.config import load_runtime_config

from bug_review.review_collection import CollectionFailure, create_records
from bug_review.workflow import safe_name


def main() -> None:
    """Create full collection and original claim pointers without conclusions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", help="Selected workspace label")
    args = parser.parse_args()
    name = safe_name(args.workspace)
    root = Path.cwd().resolve()
    runtime = load_runtime_config(root)
    output = (root / runtime["OUT"]).resolve()
    if not output.is_relative_to(root) or output == root:
        raise ValueError("Resolved OUT must be a child of the current workspace")
    try:
        result = create_records(root, output, expected_name=name)
    except CollectionFailure as error:
        print(json.dumps({"success": False, "error_code": "PYTEST_COLLECTION_FAILED",
                          "exit_code": error.exit_code, "log_path": str(error.log_path),
                          "diagnostic": error.diagnostic}, ensure_ascii=False))
        raise SystemExit(2) from None
    print(json.dumps({"success": True, **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
