# -*- coding: utf-8 -*-
"""Regression for Builder-owned runtime directories and package imports."""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.workflow_builder.tools.workflow_builder.core import build_workflow


def main() -> int:
    source = Path(__file__).resolve().parents[1] / "tools/workflow_builder/test_data/workflow_build.yaml"
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    data["root"]["path"] = "./generated"
    data["root"]["overwrite"] = False
    data["directories"]["internal"] = [
        item
        for item in data["directories"]["internal"]
        if item != ".workflow/tool_tests/logs"
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        config = temp / "workflow_build.yaml"
        config.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        report = build_workflow(config, temp)
        root = Path(report.root_path)
        assert (root / ".workflow/tool_tests/logs").is_dir()
        assert ".workflow/tool_tests/logs" in report.created_dirs

    print("[PASS] Builder creates tool test logs for legacy configs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
