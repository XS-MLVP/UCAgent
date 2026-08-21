#!/usr/bin/env python3
"""Dynamic/static Bug namespace boundaries in workflow skill scripts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RECORD_SCRIPTS = (
    REPO_ROOT
    / "ucagent/lang/zh/skills/unitytest/dynamic-bug-recording/scripts/record_dynamic_bug.py",
)
LINK_SCRIPT = (
    REPO_ROOT
    / "ucagent/lang/zh/skills/unitytest/static-bug-validation/scripts/linkbug.py"
)
STATIC_RECORD_SCRIPT = (
    REPO_ROOT
    / "ucagent/lang/zh/skills/unitytest/static-bug-analysis/scripts/record_static_bug.py"
)


def test_bug_record_scripts_have_distinct_owners_and_names():
    assert RECORD_SCRIPTS[0].is_file()
    assert STATIC_RECORD_SCRIPT.is_file()
    assert not list(
        (REPO_ROOT / "ucagent/lang/zh/skills/unitytest").glob(
            "*/scripts/recordbug.py"
        )
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
@pytest.mark.parametrize(
    ("tc_tag", "report_key"),
    (
        (
            "TC-tests/test_adder.py::test_overflow",
            "unity_test/tests/test_adder.py:12-18::test_overflow",
        ),
        (
            "TC-unity_test/tests/test_adder.py::test_overflow",
            "unity_test/tests/test_adder.py:12::test_overflow",
        ),
    ),
)
def test_dynamic_bug_record_script_resolves_test_dir_relative_report_key(
    script_path, tc_tag, report_key, tmp_path, monkeypatch
):
    module = _load_script(script_path)
    out_dir = tmp_path / "unity_test"
    out_dir.mkdir()
    report = {
        "failed_test_case_with_check_point_list": {
            report_key: ["FG-ARITHMETIC/FC-ADD/CK-OVERFLOW"]
        }
    }
    (out_dir / ".TEST_TEMPLATE_IMP_REPORT.json").write_text(
        json.dumps(report), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    assert module.resolve_fg_fc_ck_list_by_tc(tc_tag, "unity_test") == [
        ("FG-ARITHMETIC", "FC-ADD", "CK-OVERFLOW")
    ]


@pytest.mark.parametrize("script_path", RECORD_SCRIPTS)
def test_dynamic_bug_record_script_resolves_absolute_class_test_report_key(
    script_path, tmp_path, monkeypatch
):
    module = _load_script(script_path)
    out_dir = tmp_path / "unity_test"
    out_dir.mkdir()
    report_key = (
        f"{out_dir.as_posix()}/tests/test_adder.py:20-30"
        "::TestAdder::test_overflow"
    )
    report = {
        "failed_test_case_with_check_point_list": {
            report_key: ["FG-ARITHMETIC/FC-ADD/CK-OVERFLOW"]
        }
    }
    (out_dir / ".TEST_TEMPLATE_IMP_REPORT.json").write_text(
        json.dumps(report), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    assert module.resolve_fg_fc_ck_list_by_tc(
        "TC-tests/test_adder.py::TestAdder::test_overflow",
        out_dir.as_posix(),
    ) == [("FG-ARITHMETIC", "FC-ADD", "CK-OVERFLOW")]


@pytest.mark.parametrize("script_path", RECORD_SCRIPTS)
def test_dynamic_bug_record_script_generates_incomplete_analysis_scaffold(script_path):
    module = _load_script(script_path)
    lines = module.bug_analysis_template.format(
        DUT="Adder",
        DYNAMIC_BUGS_MARKER=module.DYNAMIC_BUGS_MARKER,
        DYNAMIC_BUGS_END_MARKER=module.DYNAMIC_BUGS_END_MARKER,
        WAVEFORM_EVIDENCE_MARKER=module.WAVEFORM_EVIDENCE_MARKER,
        WAVEFORM_EVIDENCE_END_MARKER=module.WAVEFORM_EVIDENCE_END_MARKER,
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

    document = "".join(lines)
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
    assert document.count(module.TODO_MARKER) == 7
    assert "waveform_analysis:" not in document
    assert document.count("<WAVEFORM-REF>") == 1
    assert document.index("<BG-CIN-OVERFLOW-98>") < document.index("</DYNAMIC-BUGS>")
    assert document.index("</DYNAMIC-BUGS>") < document.index("<WAVEFORM-EVIDENCE>")
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
    assert document.count("<WAVEFORM-REF>") == 2
    assert document.count("<WAVEFORM-VIEWER>") == 0


@pytest.mark.parametrize("script_path", RECORD_SCRIPTS)
def test_dynamic_bug_record_script_rejects_unsupported_analysis_arguments(
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
            "unsupported root cause argument",
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


def test_static_bug_link_script_does_not_accept_noncanonical_title_label():
    module = _load_script(LINK_SCRIPT)

    assert module.collect_bg_tags_from_bug_analysis(
        ["**Bug标签**: BG-DIV-INF-BY-NUM-95\n"]
    ) == set()


def test_static_bug_link_script_rejects_incomplete_dynamic_scaffold(tmp_path):
    module = _load_script(LINK_SCRIPT)
    bug_file = tmp_path / "bugs.md"
    bug_file.write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DIV-INF-BY-NUM-95>\n"
        "<TC-tests/test_a.py::test_a>\n"
        "<WAVEFORM-REF> [WAVEFORM-EVIDENCE](#waveform-placeholder)\n"
        "<BUG-TODO>\n</DYNAMIC-BUGS>\n"
        "<WAVEFORM-EVIDENCE>\n</WAVEFORM-EVIDENCE>\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="only an incomplete scaffold"):
        module.ensure_link_targets_exist_in_bug_analysis(
            ["BG-DIV-INF-BY-NUM-95"], str(bug_file)
        )


def test_static_bug_link_script_accepts_filled_dynamic_analysis(tmp_path):
    module = _load_script(LINK_SCRIPT)
    test_tag = "TC-tests/test_a.py::test_a"
    reference = module.waveform_reference(test_tag)
    anchor = reference.rsplit("#", 1)[1].rstrip(")")
    sections = "\n".join(
        f"{marker}\n**Localized {key} title**\ncompleted evidence-backed content"
        for key, marker in module.DYNAMIC_BUG_SECTION_MARKERS
    )
    bug_file = tmp_path / "bugs.md"
    bug_file.write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DIV-INF-BY-NUM-95>\n"
        f"<{test_tag}>\n"
        f"{reference}\n"
        f"{sections}\n</DYNAMIC-BUGS>\n"
        "<WAVEFORM-EVIDENCE>\n"
        f"<a id=\"{anchor}\"></a>\n"
        f"### <WAVEFORM-{test_tag}>\n"
        "```yaml\nwaveform_analysis:\n"
        f"  test_case: {test_tag}\n"
        "  bug_tags: [BG-DIV-INF-BY-NUM-95]\n"
        "  status: confirmed\n"
        "  alignment_evidence: completed\n"
        "  bug_evidence:\n"
        "    BG-DIV-INF-BY-NUM-95:\n"
        "      required_signals: [TOP.dut.valid]\n"
        "      observed_behavior: completed\n"
        "      source_correlation: completed\n"
        "```\n"
        "<WAVEFORM-VIEWER> [viewer](/surfer/?wave=eyJ2IjoxfQ)\n"
        "</WAVEFORM-EVIDENCE>\n",
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
    test_tag = "TC-tests/test_a.py::test_a"
    reference = module.waveform_reference(test_tag)
    sections = "\n".join(
        f"{marker}\ncompleted evidence-backed content"
        for _key, marker in module.DYNAMIC_BUG_SECTION_MARKERS
    )
    bug_file = tmp_path / "bugs.md"
    bug_file.write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DIV-INF-BY-NUM-95>\n"
        f"<{test_tag}>\n"
        f"{reference}\n"
        "waveform_analysis: status: confirmed\n"
        f"{sections}\n</DYNAMIC-BUGS>\n"
        "<WAVEFORM-EVIDENCE>\n</WAVEFORM-EVIDENCE>\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="central evidence"):
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
