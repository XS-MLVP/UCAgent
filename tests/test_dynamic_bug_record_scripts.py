#!/usr/bin/env python3
"""Dynamic/static Bug namespace boundaries in workflow skill scripts."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RECORD_SCRIPTS = (
    REPO_ROOT
    / "ucagent/lang/zh/skills/unitytest/test-case-implementation-in-batch/scripts/recordbug.py",
    REPO_ROOT
    / "ucagent/lang/zh/skills/unitytest/static-bug-validation/scripts/recordbug.py",
)
LINK_SCRIPT = (
    REPO_ROOT
    / "ucagent/lang/zh/skills/unitytest/static-bug-validation/scripts/linkbug.py"
)


def _load_script(path: Path):
    spec = importlib.util.spec_from_file_location(
        f"test_{path.parent.parent.name}_{path.stem}", path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("script_path", RECORD_SCRIPTS)
def test_dynamic_bug_record_script_rejects_static_tag(script_path):
    module = _load_script(script_path)

    with pytest.raises(ValueError, match=r"cannot use the BG-STATIC-\* namespace"):
        module.validate_dynamic_bg_tag("BG-STATIC-DIV-INF-BY-NUM-95")

    module.validate_dynamic_bg_tag("BG-DIV-INF-BY-NUM-95")


def test_static_bug_link_script_requires_distinct_dynamic_target():
    module = _load_script(LINK_SCRIPT)

    with pytest.raises(ValueError, match="is a static Bug tag"):
        module.parse_link_targets("BG-STATIC-DIV-INF-BY-NUM-95")

    assert module.parse_link_targets("BG-DIV-INF-BY-NUM-95") == [
        "BG-DIV-INF-BY-NUM-95"
    ]
