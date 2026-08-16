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


@pytest.mark.parametrize("script_path", RECORD_SCRIPTS)
def test_dynamic_bug_record_script_colocates_root_cause_inside_bg(
    script_path, tmp_path
):
    module = _load_script(script_path)
    module.project_root = str(tmp_path)
    source = tmp_path / "rtl" / "Adder.sv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "logic [8:0] full_sum;\nassign full_sum = a + b + cin;\n",
        encoding="utf-8",
    )
    lines = module.bug_analysis_template.format(
        DUT="Adder",
        SECTION_TITLE=module.SECTION_TITLE,
    ).lstrip().splitlines(keepends=True)

    module.insert_content(
        lines,
        "FG-ARITHMETIC",
        "FC-ADD",
        "CK-OVERFLOW",
        "BG-CIN-OVERFLOW-98",
        "TC-tests/test_adder.py::test_overflow",
        "Overflow is not raised.",
    )
    result = module.insert_root_cause_content(
        lines,
        "FG-ARITHMETIC",
        "FC-ADD",
        "CK-OVERFLOW",
        "BG-CIN-OVERFLOW-98",
        "TC-tests/test_adder.py::test_overflow",
        "Overflow is not raised.",
        "The carry input is missing from overflow calculation.",
        "rtl/Adder.sv:1-2",
        "Drive sum and overflow from the same full-width expression.",
    )

    document = "".join(lines)
    assert "inside BG entry" in result
    assert "## 缺陷根因分析" not in document
    assert document.index("<BG-CIN-OVERFLOW-98>") < document.index("**根因分析**")
    assert document.index("**根因分析**") < document.index("**修复建议**")
    assert "rtl/Adder.sv:1-2" in document
    assert "**波形证据说明**" in document
    assert "本脚本不生成波形字段" in document

    module.insert_content(
        lines,
        "FG-ARITHMETIC",
        "FC-ADD",
        "CK-OVERFLOW",
        "BG-CIN-OVERFLOW-98",
        "TC-tests/test_adder.py::test_overflow_random",
        "Random overflow reproducer.",
    )
    document = "".join(lines)
    assert document.index("<TC-tests/test_adder.py::test_overflow_random>") < document.index(
        "**问题描述**"
    )


def test_static_bug_link_script_requires_distinct_dynamic_target():
    module = _load_script(LINK_SCRIPT)

    with pytest.raises(ValueError, match="is a static Bug tag"):
        module.parse_link_targets("BG-STATIC-DIV-INF-BY-NUM-95")

    assert module.parse_link_targets("BG-DIV-INF-BY-NUM-95") == [
        "BG-DIV-INF-BY-NUM-95"
    ]
