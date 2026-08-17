#!/usr/bin/env python3
"""Dynamic/static Bug namespace boundaries in workflow skill scripts."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

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
STATIC_RECORD_SCRIPT = (
    REPO_ROOT
    / "ucagent/lang/zh/skills/unitytest/static-bug-analysis/scripts/recordbug.py"
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
    with pytest.raises(ValueError, match="confidence must be greater than 0"):
        module.validate_dynamic_bg_tag("BG-DIV-INF-BY-NUM-0")

    module.validate_dynamic_bg_tag("BG-DIV-INF-BY-NUM-95")


@pytest.mark.parametrize("script_path", RECORD_SCRIPTS)
def test_dynamic_bug_record_script_generates_incomplete_analysis_scaffold(script_path):
    module = _load_script(script_path)
    lines = module.bug_analysis_template.format(
        DUT="Adder",
        DYNAMIC_BUGS_MARKER=module.DYNAMIC_BUGS_MARKER,
    ).lstrip().splitlines(keepends=True)
    lines = [
        line.replace("## 未测试通过检测点分析", "## Dynamic Bug Entries")
        for line in lines
    ]

    module.insert_content(
        lines,
        "FG-ARITHMETIC",
        "FC-ADD",
        "CK-OVERFLOW",
        "BG-CIN-OVERFLOW-98",
        "TC-tests/test_adder.py::test_overflow",
        "Overflow is not raised.",
    )

    document = "".join(lines)
    assert "## 缺陷根因分析" not in document
    markers = (
        module.OVERVIEW_MARKER,
        "<BUG-SYMPTOMS>",
        "<BUG-TRIGGER>",
        "<BUG-ROOT-CAUSE>",
        "<BUG-SOURCE-EVIDENCE>",
        "<BUG-CAUSAL-CHAIN>",
        "<BUG-FIX>",
        "<BUG-RETEST>",
    )
    assert document.index("<BG-CIN-OVERFLOW-98>") < document.index(markers[0])
    assert [document.count(marker) for marker in markers] == [1] * len(markers)
    assert [document.index(marker) for marker in markers] == sorted(
        document.index(marker) for marker in markers
    )
    assert document.count(module.TODO_MARKER) >= 8
    assert "waveform_analysis:" in document
    assert "replace with WaveInfo" not in document
    assert "填写严重度" not in document
    assert "插入带真实路径" not in document

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
    assert document.index(
        "<TC-tests/test_adder.py::test_overflow_random>"
    ) < document.index(module.OVERVIEW_MARKER)
    assert document.count("waveform_analysis:") == 2


@pytest.mark.parametrize("script_path", RECORD_SCRIPTS)
def test_dynamic_bug_record_script_rejects_removed_analysis_arguments(
    script_path, monkeypatch
):
    module = _load_script(script_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script_path),
            "-BG",
            "BG-CIN-OVERFLOW-98",
            "-TC",
            "TC-tests/test_adder.py::test_overflow",
            "-BD",
            "Overflow is not raised.",
            "-ROOT",
            "legacy root cause",
        ],
    )

    with pytest.raises(SystemExit):
        module.parse_args()


def test_static_bug_link_script_requires_distinct_dynamic_target():
    module = _load_script(LINK_SCRIPT)

    with pytest.raises(ValueError, match="is a static Bug tag"):
        module.parse_link_targets("BG-STATIC-DIV-INF-BY-NUM-95")

    assert module.parse_link_targets("BG-DIV-INF-BY-NUM-95") == [
        "BG-DIV-INF-BY-NUM-95"
    ]


def test_static_bug_record_template_uses_markers_before_localizable_titles():
    module = _load_script(STATIC_RECORD_SCRIPT)
    document = module.static_bug_analysis_md_template.format(DUT="Adder")

    ordered_tokens = (
        module.STATIC_BUG_SUMMARY_MARKER,
        "## 一、潜在Bug汇总",
        module.STATIC_BUG_DETAILS_MARKER,
        "## 二、详细分析",
        module.STATIC_BUG_PROGRESS_MARKER,
        "## 三、批次分析进度",
    )
    assert [document.index(token) for token in ordered_tokens] == sorted(
        document.index(token) for token in ordered_tokens
    )


def test_static_bug_link_script_does_not_accept_legacy_title_label():
    module = _load_script(LINK_SCRIPT)

    assert module.collect_bg_tags_from_bug_analysis(
        ["**Bug标签**: BG-DIV-INF-BY-NUM-95\n"]
    ) == set()


def test_static_bug_link_script_rejects_incomplete_dynamic_scaffold(tmp_path):
    module = _load_script(LINK_SCRIPT)
    bug_file = tmp_path / "bugs.md"
    bug_file.write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DIV-INF-BY-NUM-95>\n"
        "<TC-tests/test_a.py::test_a>\n<BUG-TODO>\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="only an incomplete scaffold"):
        module.ensure_link_targets_exist_in_bug_analysis(
            ["BG-DIV-INF-BY-NUM-95"], str(bug_file)
        )


def test_static_bug_link_script_accepts_filled_dynamic_analysis(tmp_path):
    module = _load_script(LINK_SCRIPT)
    sections = "\n".join(
        f"{marker}\n**Localized {key} title**\ncompleted evidence-backed content"
        for key, marker in module.DYNAMIC_BUG_SECTION_MARKERS
    )
    bug_file = tmp_path / "bugs.md"
    bug_file.write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DIV-INF-BY-NUM-95>\n"
        "<TC-tests/test_a.py::test_a>\n"
        "```yaml\nwaveform_analysis:\n  status: confirmed\n```\n"
        f"{sections}\n",
        encoding="utf-8",
    )

    module.ensure_link_targets_exist_in_bug_analysis(
        ["BG-DIV-INF-BY-NUM-95"], str(bug_file)
    )
    blocks = module.collect_dynamic_bg_blocks(
        bug_file.read_text(encoding="utf-8").splitlines(keepends=True),
        "BG-DIV-INF-BY-NUM-95",
    )
    assert len(blocks) == 1
    assert "<TC-tests/test_a.py::test_a>" in blocks[0]
    assert "<BUG-RETEST>" in blocks[0]


def test_static_bug_link_script_rejects_missing_dynamic_container(tmp_path):
    module = _load_script(LINK_SCRIPT)
    bug_file = tmp_path / "bugs.md"
    bug_file.write_text("<BG-DIV-INF-BY-NUM-95>\n", encoding="utf-8")

    with pytest.raises(ValueError, match="<DYNAMIC-BUGS>.*exactly once"):
        module.ensure_link_targets_exist_in_bug_analysis(
            ["BG-DIV-INF-BY-NUM-95"], str(bug_file)
        )


def test_static_bug_link_script_requires_structured_confirmed_waveform(tmp_path):
    module = _load_script(LINK_SCRIPT)
    sections = "\n".join(
        f"{marker}\ncompleted evidence-backed content"
        for _key, marker in module.DYNAMIC_BUG_SECTION_MARKERS
    )
    bug_file = tmp_path / "bugs.md"
    bug_file.write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DIV-INF-BY-NUM-95>\n"
        "<TC-tests/test_a.py::test_a>\n"
        "waveform_analysis: status: confirmed\n"
        f"{sections}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="confirmed waveform_analysis is missing"):
        module.ensure_link_targets_exist_in_bug_analysis(
            ["BG-DIV-INF-BY-NUM-95"], str(bug_file)
        )


def test_static_bug_link_script_updates_tagged_localized_report(tmp_path):
    module = _load_script(LINK_SCRIPT)
    static_file = tmp_path / "static.md"
    static_file.write_text(
        "## Localized summary\n<STATIC-BUG-SUMMARY>\n"
        "| 序号 | Bug标签 | 功能路径 | 描述 | 置信度 | 文件 | 动态Bug关联 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| 001 | BG-STATIC-001-DIV | FG-A/FC-A/CK-A | desc | high | rtl/a.v | LINK-BUG-[BG-TBD] |\n"
        "## Localized details\n<STATIC-BUG-DETAILS>\n"
        "<FG-A>\n<FC-A>\n<CK-A>\n<BG-STATIC-001-DIV>\n"
        "<LINK-BUG-[BG-TBD]>\n<FILE-rtl/a.v:1>\n"
        "## Localized progress\n<STATIC-BUG-PROGRESS>\n",
        encoding="utf-8",
    )

    module.update_static_bug_link(
        str(static_file), "BG-STATIC-001-DIV", ["BG-DIV-INF-BY-NUM-95"]
    )

    updated = static_file.read_text(encoding="utf-8")
    assert "LINK-BUG-[BG-DIV-INF-BY-NUM-95]" in updated
    assert "<LINK-BUG-[BG-DIV-INF-BY-NUM-95]>" in updated
    assert "BG-TBD" not in updated
