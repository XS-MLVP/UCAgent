"""Canonical root-cause relations in dynamic Bug documents."""

from pathlib import Path

import pytest

from ucagent.checkers.toffee_report import check_dynamic_bug_analysis_content
from ucagent.util.bug_analysis_contract import (
    dynamic_bug_anchor_id,
    related_bug_reference,
    root_cause_anchor_id,
    root_cause_reference,
)


CHECKPOINT = "FG-ARITHMETIC/FC-ADD/CK-RESULT"
ROOT_TAG = "ROOT-RESULT-WIDTH"
ROOT_TITLE = "Result intermediate width is insufficient"


def _analysis(root_tag: str = ROOT_TAG, root_title: str = ROOT_TITLE) -> str:
    return f"""###### Bug 概述
<BUG-OVERVIEW>
The result is truncated.
###### 现象与严重度
<BUG-SYMPTOMS>
The reproduced transaction returns a wrong result.
###### 触发条件与影响
<BUG-TRIGGER>
The boundary input exposes the error.
{root_cause_reference(root_tag, root_title)}
"""


def _write_document(
    tmp_path: Path,
    bugs: tuple[str, ...] = ("BG-RESULT-TRUNCATED-90",),
    *,
    root_tag: str = ROOT_TAG,
    root_title: str = ROOT_TITLE,
    related_bugs: tuple[str, ...] | None = None,
) -> Path:
    related_bugs = bugs if related_bugs is None else related_bugs
    lines = [
        "<DYNAMIC-BUGS>",
        "### Arithmetic <FG-ARITHMETIC>",
        "#### Addition <FC-ADD>",
        "##### Result <CK-RESULT>",
    ]
    for index, bug in enumerate(bugs):
        lines.extend(
            [
                f'<a id="{dynamic_bug_anchor_id(CHECKPOINT, bug)}"></a>',
                f"###### Reproduced result defect（{bug.rsplit('-', 1)[-1]}%） <{bug}>",
                f"- Boundary reproducer <TC-tests/test_add.py::test_result_{index}>",
                _analysis(root_tag, root_title),
            ]
        )
    lines.extend(
        [
            "</DYNAMIC-BUGS>",
            "<ROOT-CAUSES>",
            f'<a id="{root_cause_anchor_id(root_tag)}"></a>',
            f"### {root_title} <{root_tag}>",
            "#### 根因分析",
            "<ROOT-CAUSE-ANALYSIS>",
            "The intermediate value drops the most-significant result bit before output assignment.",
            "#### 源码证据",
            "<ROOT-SOURCE-EVIDENCE>",
            "<ROOT-SOURCE-UNAVAILABLE>",
            "The workspace has no accessible HDL source, so the cause is bounded by interface evidence.",
            "#### 因果链",
            "<ROOT-CAUSAL-CHAIN>",
            "The accepted input reaches the result path and produces each associated wrong output.",
            "#### 修复建议",
            "<ROOT-FIX>",
            "Preserve the complete result width.",
            "#### 风险与复验",
            "<ROOT-RETEST>",
            "Retest boundary values and every affected result path.",
            "#### 关联 Bug",
            "<RELATED-BUGS>",
            *(related_bug_reference(CHECKPOINT, bug) for bug in related_bugs),
            "</ROOT-CAUSES>",
            "<WAVEFORM-EVIDENCE>",
            "</WAVEFORM-EVIDENCE>",
        ]
    )
    target = tmp_path / "bugs.md"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def test_one_root_cause_can_link_multiple_checkpoint_scoped_bugs(tmp_path):
    _write_document(
        tmp_path,
        bugs=("BG-RESULT-TRUNCATED-90", "BG-CARRY-DROPPED-92"),
    )

    passed, message = check_dynamic_bug_analysis_content(str(tmp_path), "bugs.md")

    assert passed, message


def test_empty_root_cause_container_is_valid_without_dynamic_bugs(tmp_path):
    (tmp_path / "bugs.md").write_text(
        "<DYNAMIC-BUGS>\n</DYNAMIC-BUGS>\n"
        "<ROOT-CAUSES>\n</ROOT-CAUSES>\n"
        "<WAVEFORM-EVIDENCE>\n</WAVEFORM-EVIDENCE>\n",
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(str(tmp_path), "bugs.md")

    assert passed, message


def test_no_bug_document_requires_empty_root_cause_container(tmp_path):
    (tmp_path / "bugs.md").write_text(
        "<DYNAMIC-BUGS>\n</DYNAMIC-BUGS>\n"
        "<WAVEFORM-EVIDENCE>\n</WAVEFORM-EVIDENCE>\n",
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(str(tmp_path), "bugs.md")

    assert passed is False
    assert message["error_code"] == "ROOT_CAUSE_CONTAINER_MISSING"
    assert "including when no Bug was found" in message["error"]


def test_no_bug_document_rejects_prose_inside_root_cause_container(tmp_path):
    (tmp_path / "bugs.md").write_text(
        "<DYNAMIC-BUGS>\n</DYNAMIC-BUGS>\n"
        "<ROOT-CAUSES>\nNo root cause because no Bug was found.\n</ROOT-CAUSES>\n"
        "<WAVEFORM-EVIDENCE>\n</WAVEFORM-EVIDENCE>\n",
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(str(tmp_path), "bugs.md")

    assert passed is False
    assert message["error_code"] == "ROOT_CAUSE_CONTAINER_UNPARSEABLE_CONTENT"
    assert "bugs.md:4-4" in message["error"]


def test_root_cause_entity_without_dynamic_bug_is_rejected(tmp_path):
    target = _write_document(tmp_path, bugs=())
    content = target.read_text(encoding="utf-8")
    target.write_text(
        content.replace(
            "### Arithmetic <FG-ARITHMETIC>\n"
            "#### Addition <FC-ADD>\n"
            "##### Result <CK-RESULT>\n",
            "",
        ),
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(str(tmp_path), "bugs.md")

    assert not passed
    assert "Related Bug List Empty" in message["error"]


def test_root_cause_requires_reverse_link_for_every_bug(tmp_path):
    bugs = ("BG-RESULT-TRUNCATED-90", "BG-CARRY-DROPPED-92")
    _write_document(tmp_path, bugs=bugs, related_bugs=(bugs[0],))

    passed, message = check_dynamic_bug_analysis_content(str(tmp_path), "bugs.md")

    assert not passed
    assert "Root Cause Reverse Link Missing" in message["error"]
    assert related_bug_reference(CHECKPOINT, bugs[1]) in message["error"]


def test_bug_reference_error_lists_exact_available_root_links(tmp_path):
    target = _write_document(tmp_path)
    content = target.read_text(encoding="utf-8")
    content = content.replace(
        root_cause_reference(ROOT_TAG, ROOT_TITLE),
        "The boundary input exposes the error.",
        1,
    )
    target.write_text(content, encoding="utf-8")

    passed, message = check_dynamic_bug_analysis_content(str(tmp_path), "bugs.md")

    assert not passed
    assert "Root Cause Reference Error" in message["error"]
    assert root_cause_reference(ROOT_TAG, ROOT_TITLE) in message["error"]


def test_root_cause_tags_are_document_wide_unique(tmp_path):
    target = _write_document(tmp_path)
    content = target.read_text(encoding="utf-8")
    root_entity = content.split("<ROOT-CAUSES>\n", 1)[1].split(
        "</ROOT-CAUSES>", 1
    )[0]
    target.write_text(
        content.replace("</ROOT-CAUSES>", root_entity + "</ROOT-CAUSES>"),
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(str(tmp_path), "bugs.md")

    assert not passed
    assert "Duplicate Root Cause" in message["error"]


@pytest.mark.parametrize(
    "reserved_tag",
    (
        "ROOT-SOURCE-EVIDENCE",
        "ROOT-SOURCE-UNAVAILABLE",
        "ROOT-CAUSAL-CHAIN",
        "ROOT-FIX",
        "ROOT-RETEST",
    ),
)
def test_root_cause_tags_cannot_reuse_control_markers(reserved_tag):
    with pytest.raises(ValueError, match="unique ROOT-NAME form"):
        root_cause_anchor_id(reserved_tag)


def test_root_cause_rejects_inline_unfinished_marker(tmp_path):
    target = _write_document(tmp_path)
    content = target.read_text(encoding="utf-8")
    target.write_text(
        content.replace(
            "The intermediate value drops the most-significant result bit before output assignment.",
            "The analysis is still pending <BUG-TODO>.",
        ),
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(str(tmp_path), "bugs.md")

    assert not passed
    assert "Root Cause Field Incomplete" in message["error"]


def test_bug_rejects_references_to_two_distinct_root_causes(tmp_path):
    target = _write_document(tmp_path)
    content = target.read_text(encoding="utf-8")
    first_reference = root_cause_reference(ROOT_TAG, ROOT_TITLE)
    second_reference = root_cause_reference(
        "ROOT-RESULT-SIGN",
        "Result sign extension is incorrect",
    )
    target.write_text(
        content.replace(first_reference, first_reference + "\n" + second_reference),
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(str(tmp_path), "bugs.md")

    assert not passed
    assert "must contain exactly one <CAUSE-REF-ROOT-NAME>" in message["error"]


def test_related_bug_embedded_path_must_match_link_path(tmp_path):
    target = _write_document(tmp_path)
    content = target.read_text(encoding="utf-8")
    target.write_text(
        content.replace(
            "<RELATED-BUG-FG-ARITHMETIC/FC-ADD/CK-RESULT/BG-RESULT-TRUNCATED-90>",
            "<RELATED-BUG-FG-ARITHMETIC/FC-ADD/CK-WRONG/BG-RESULT-TRUNCATED-90>",
        ),
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(str(tmp_path), "bugs.md")

    assert not passed
    assert "Related Bug Path Error" in message["error"]


@pytest.mark.parametrize("target", ("root", "bug"))
def test_bidirectional_links_require_exact_generated_anchor(tmp_path, target):
    document = _write_document(tmp_path)
    content = document.read_text(encoding="utf-8")
    if target == "root":
        content = content.replace("(#root-cause-result-width)", "(#root-cause-wrong)", 1)
    else:
        bug_anchor = dynamic_bug_anchor_id(CHECKPOINT, "BG-RESULT-TRUNCATED-90")
        content = content.replace(f"(#{bug_anchor})", "(#bug-wrong)", 1)
    document.write_text(content, encoding="utf-8")

    passed, message = check_dynamic_bug_analysis_content(str(tmp_path), "bugs.md")

    assert not passed
    assert (
        "Link Error" in message["error"]
        or "Target Error" in message["error"]
        or "Root Cause Reference Target Error" in message["error"]
    )


def test_related_bug_link_errors_are_reported_in_one_batch(tmp_path):
    bugs = ("BG-RESULT-TRUNCATED-90", "BG-CARRY-DROPPED-92")
    document = _write_document(tmp_path, bugs=bugs)
    content = document.read_text(encoding="utf-8")
    expected_replacements = []
    for index, bug in enumerate(bugs):
        canonical = related_bug_reference(CHECKPOINT, bug)
        expected_replacements.append(canonical)
        anchor = dynamic_bug_anchor_id(CHECKPOINT, bug)
        content = content.replace(
            canonical,
            canonical.replace(f"(#{anchor})", f"(#bug-wrong-{index})"),
        )
    document.write_text(content, encoding="utf-8")

    passed, message = check_dynamic_bug_analysis_content(str(tmp_path), "bugs.md")

    assert not passed
    assert message["error_code"] == "ROOT_CAUSE_RELATION_INVALID"
    assert "[Root Cause Relation Errors] Found 2" in message["error"]
    assert message["details"]["remaining_issue_count"] == 0
    assert len(message["details"]["issues"]) == 2
    assert {
        issue["code"] for issue in message["details"]["issues"]
    } == {"RELATED_BUG_LINK_ERROR"}
    for bug, replacement in zip(bugs, expected_replacements):
        assert f"{CHECKPOINT}/{bug}" in message["error"]
        assert replacement in message["error"]
    assert message["details"]["skill_repair_call"] == {
        "tool": "RunSkillScript",
        "commands": [[
            "unitytest/dynamic-bug-recording",
            "record_dynamic_bug.py",
            "-MODE repair",
        ]],
    }
    assert "If CurrentTips lists unitytest/dynamic-bug-recording" in (
        message["next_action"][0]
    )


@pytest.mark.parametrize("closing_marker", ("</RELATED-BUGS>", "</ROOT>"))
def test_unsupported_root_closing_marker_requests_exact_removal(
    tmp_path, closing_marker
):
    target = _write_document(tmp_path)
    content = target.read_text(encoding="utf-8")
    target.write_text(
        content.replace("</ROOT-CAUSES>", closing_marker + "\n</ROOT-CAUSES>"),
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(str(tmp_path), "bugs.md")

    assert not passed
    assert message["error_code"] == "ROOT_CAUSE_RELATION_INVALID"
    issue = message["details"]["issues"][0]
    assert issue["code"] == "UNSUPPORTED_ROOT_CLOSING_MARKER"
    assert issue["observed"] == closing_marker
    assert "Remove the exact line" in issue["message"]
    assert "available entry" not in issue["message"]


def test_merged_root_container_end_routes_to_skill_repair(tmp_path):
    target = _write_document(tmp_path)
    content = target.read_text(encoding="utf-8")
    target.write_text(
        content.replace(
            "</ROOT-CAUSES>",
            "</RELATED-BUGS></ROOT-CAUSES>",
        ),
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(str(tmp_path), "bugs.md")

    assert not passed
    assert message["error_code"] == "ROOT_CAUSE_CONTAINER_FORMAT_INVALID"
    assert message["details"]["merged_end_marker_lines"]
    assert message["details"]["skill_repair_call"]["commands"] == [[
        "unitytest/dynamic-bug-recording",
        "record_dynamic_bug.py",
        "-MODE repair",
    ]]
    assert "do not edit the dynamic Bug document" in message["next_action"]
