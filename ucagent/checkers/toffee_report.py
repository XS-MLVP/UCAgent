# -*- coding: utf-8 -*-
"""Toffee report checker for UCAgent verification."""

from ucagent.util.log import warning, info
import ucagent.util.functions as fc
from ucagent.util.waveform_viewer import (
    WaveformViewerProtocolError,
    WAVEFORM_VIEWER_MARKER,
    build_waveform_viewer_url,
    parse_waveform_viewer_markdown_link,
)
from ucagent.util.bug_analysis_contract import (
    BUG_ANALYSIS_SECTION_MARKERS as _BUG_ANALYSIS_SECTION_MARKERS,
    BUG_ANALYSIS_SECTION_TITLES as _BUG_ANALYSIS_SECTION_TITLES,
    ROOT_ANALYSIS_SECTION_MARKERS as _ROOT_ANALYSIS_SECTION_MARKERS,
    ROOT_ANALYSIS_SECTION_TITLES as _ROOT_ANALYSIS_SECTION_TITLES,
    ROOT_SOURCE_EVIDENCE_MARKERS as _ROOT_SOURCE_EVIDENCE_MARKERS,
    ROOT_SOURCE_UNAVAILABLE_MARKER as _ROOT_SOURCE_UNAVAILABLE_MARKER,
    BUG_TODO_MARKER as _BUG_TODO_MARKER,
    DOCUMENT_TAG_PATTERN as _DOCUMENT_TAG_PATTERN,
    DYNAMIC_BUG_DOCUMENT_PATH as _DYNAMIC_BUG_DOCUMENT_PATH,
    DYNAMIC_BUGS_END_MARKER as _DYNAMIC_BUGS_END_MARKER,
    DYNAMIC_BUGS_MARKER as _DYNAMIC_BUGS_MARKER,
    ROOT_CAUSE_REFERENCE_MARKER as _ROOT_CAUSE_REFERENCE_MARKER,
    ROOT_CAUSE_REFERENCE_TAG_PREFIX as _ROOT_CAUSE_REFERENCE_TAG_PREFIX,
    ROOT_CAUSES_END_MARKER as _ROOT_CAUSES_END_MARKER,
    ROOT_CAUSES_MARKER as _ROOT_CAUSES_MARKER,
    ROOT_ENTITY_TAG_PATTERN as _ROOT_ENTITY_TAG_PATTERN,
    TEST_CASE_SERIALIZATION as _TEST_CASE_SERIALIZATION,
    RELATED_BUG_TAG_PREFIX as _RELATED_BUG_TAG_PREFIX,
    RELATED_BUGS_MARKER as _RELATED_BUGS_MARKER,
    RELATED_BUGS_TITLE as _RELATED_BUGS_TITLE,
    dynamic_bug_anchor_id as _dynamic_bug_anchor_id,
    normalize_display_title as _normalize_display_title,
    related_bug_reference as _related_bug_reference,
    root_cause_anchor_id as _root_cause_anchor_id,
    root_cause_reference as _root_cause_reference,
    WAVEFORM_BUG_ANALYSIS_FIELDS as _WAVEFORM_BUG_ANALYSIS_FIELDS,
    WAVEFORM_BLOCK_KEY as _WAVEFORM_BLOCK_KEY,
    WAVEFORM_EVIDENCE_END_MARKER as _WAVEFORM_EVIDENCE_END_MARKER,
    WAVEFORM_EVIDENCE_MARKER as _WAVEFORM_EVIDENCE_MARKER,
    WAVEFORM_FENCE_CLOSE as _WAVEFORM_FENCE_CLOSE,
    WAVEFORM_FENCE_OPEN as _WAVEFORM_FENCE_OPEN,
    WAVEFORM_LLM_ANALYSIS_FIELDS as _WAVEFORM_LLM_ANALYSIS_FIELDS,
    WAVEFORM_REFERENCE_MARKER as _WAVEFORM_REFERENCE_MARKER,
    WAVEFORM_SIGNAL_GROUP_FIELDS as _WAVEFORM_SIGNAL_GROUP_FIELDS,
    normalize_test_case_tag as _normalize_test_case_tag,
    parse_dynamic_tag_heading as _parse_dynamic_tag_heading,
    parse_waveform_record_heading as _parse_waveform_record_heading,
    waveform_anchor_id as _waveform_anchor_id,
    waveform_record_tag as _waveform_record_tag,
    waveform_reference as _waveform_reference,
)
from ucagent.checkers.base import Checker
import copy
from datetime import datetime
import os
import re
import textwrap
import traceback
import yaml


_HDL_SOURCE_LOCATION = re.compile(
    r"[\w./\\-]+\.(?:sv|svh|v|vh|vhd|vhdl|scala):\d+-\d+",
    re.IGNORECASE,
)
_MALFORMED_HDL_SOURCE_LOCATION = re.compile(
    r"(?P<path>[\w./\\-]+\.(?:sv|svh|v|vh|vhd|vhdl|scala)):"
    r"L?(?P<start>\d+)(?:-L?(?P<end>\d+))?",
    re.IGNORECASE,
)
_HDL_FENCED_BLOCK = re.compile(
    r"^[ \t]*```(?:systemverilog|verilog|vhdl|scala|chisel)[ \t]*\r?\n"
    r"(?P<body>.*?)^[ \t]*```[ \t]*$",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
_MAX_ROOT_RELATION_DIAGNOSTICS = 50
_MAX_DYNAMIC_CONTAINER_DIAGNOSTICS = 50


def _missing_dynamic_bug_document_error(bug_file: str) -> dict:
    """Return the exact canonical recovery for a missing dynamic Bug document."""

    return {
        "error_code": "DYNAMIC_BUG_DOCUMENT_MISSING",
        "error": (
            f"[Dynamic Bug Document Missing] Required canonical document '{bug_file}' "
            "does not exist. A no-Bug result still requires this document."
        ),
        "next_action": (
            f"Create only '{bug_file}' using the generated dynamic Bug template. If no "
            "dynamic Bug was found, use the exact completed empty structure in "
            "Guide_Doc/dut_bug_analysis.md section 2.1: keep the canonical title and "
            "ordered empty DYNAMIC-BUGS, ROOT-CAUSES, and WAVEFORM-EVIDENCE containers. "
            "Do not derive another filename from the title, then call `Check`/`Complete` "
            "again."
        ),
    }


def _strip_html_comments(lines: list[str]) -> tuple[list[str], int | None]:
    """Remove HTML comment blocks while preserving source-line positions."""

    cleaned_lines = []
    in_comment = False
    comment_start = None
    for index, line in enumerate(lines):
        remainder = line
        fragments = []
        while remainder:
            if in_comment:
                comment_end = remainder.find("-->")
                if comment_end < 0:
                    remainder = ""
                    break
                remainder = remainder[comment_end + 3 :]
                in_comment = False
                comment_start = None
                continue

            comment_start_index = remainder.find("<!--")
            if comment_start_index < 0:
                fragments.append(remainder)
                remainder = ""
                break
            fragments.append(remainder[:comment_start_index])
            comment_end = remainder.find("-->", comment_start_index + 4)
            if comment_end < 0:
                in_comment = True
                comment_start = index + 1
                remainder = ""
                break
            remainder = remainder[comment_end + 3 :]

        cleaned_lines.append("".join(fragments))

    return cleaned_lines, comment_start if in_comment else None


def _substantive_lines_without_html_comments(
    lines: list[str], start_index: int, end_index: int
) -> list[tuple[int, str]]:
    """Return nonblank container lines after removing complete HTML comments."""

    cleaned_lines, unclosed_comment_line = _strip_html_comments(lines)
    substantive = [
        (index + 1, cleaned_lines[index].strip())
        for index in range(start_index, end_index)
        if cleaned_lines[index].strip()
    ]

    if (
        unclosed_comment_line is not None
        and start_index < unclosed_comment_line <= end_index
    ):
        substantive.append(
            (unclosed_comment_line, "<!-- (unclosed HTML comment)")
        )
    return substantive


def _dynamic_container_format_error(
    bug_file: str,
    start_indexes: list[int],
    end_indexes: list[int],
) -> dict:
    """Return a Checker-authored repair for malformed dynamic container markers."""

    start_lines = [index + 1 for index in start_indexes]
    end_lines = [index + 1 for index in end_indexes]
    return {
        "error_code": "DYNAMIC_BUG_CONTAINER_FORMAT",
        "error": (
            f"[Dynamic Bug Container Format Error] '{bug_file}' must contain exactly "
            f"one standalone {_DYNAMIC_BUGS_MARKER} and one standalone "
            f"{_DYNAMIC_BUGS_END_MARKER}, in that order. Found opening marker line(s) "
            f"{start_lines or '(none)'} and closing marker line(s) "
            f"{end_lines or '(none)'}."
        ),
        "next_action": (
            f"Repair the marker pair in '{bug_file}' so one closed DYNAMIC-BUGS body "
            "remains. If no dynamically reproduced DUT Bug exists, leave that body "
            "empty and preserve the empty ROOT-CAUSES and WAVEFORM-EVIDENCE "
            "containers, then call `Check`/`Complete` again."
        ),
    }


def _unparseable_dynamic_container_error(
    bug_file: str,
    substantive_lines: list[tuple[int, str]],
) -> dict:
    """Return every bounded malformed line when no dynamic machine tag is parseable."""

    malformed_lines = _render_container_line_diagnostics(
        bug_file, substantive_lines
    )
    return {
        "error_code": "DYNAMIC_BUG_CONTAINER_UNPARSEABLE_CONTENT",
        "error": (
            f"[Dynamic Bug Container Unparseable Content] '{bug_file}' contains "
            f"{len(substantive_lines)} substantive line(s) inside DYNAMIC-BUGS but no "
            "canonical <FG-*>, <FC-*>, <CK-*>, <BG-*>, or <TC-*> machine tag. The "
            "content cannot be accepted as an empty/no-Bug result or as Bug records:\n"
            f"{malformed_lines}"
        ),
        "next_action": (
            f"Edit only the configured dynamic Bug document '{bug_file}' (contract path "
            f"{_DYNAMIC_BUG_DOCUMENT_PATH}); do not derive another filename from its "
            "visible Markdown title. If no Bug was found, remove all content from the "
            "DYNAMIC-BUGS, ROOT-CAUSES, and WAVEFORM-EVIDENCE bodies. Otherwise rebuild "
            "the DYNAMIC-BUGS body with Guide_Doc/dut_bug_analysis.md section 5.1. Use "
            f"Markdown `{_TEST_CASE_SERIALIZATION['markdown_tag']}`, record/Apply arguments "
            f"and waveform YAML test_case `{_TEST_CASE_SERIALIZATION['tool_or_yaml']}`, "
            f"and WaveInfo test_case_name `{_TEST_CASE_SERIALIZATION['waveinfo']}`. Repair "
            "every listed line before calling `Check`/`Complete` again."
        ),
    }


def _dynamic_container_without_bug_error(
    bug_file: str,
    substantive_lines: list[tuple[int, str]],
) -> dict:
    """Reject a nonempty container that has tags but defines no BG record."""

    malformed_lines = _render_container_line_diagnostics(
        bug_file, substantive_lines
    )
    return {
        "error_code": "DYNAMIC_BUG_CONTAINER_NO_BUG_RECORD",
        "error": (
            f"[Dynamic Bug Container Has No Bug Record] '{bug_file}' contains "
            "machine-tagged content inside DYNAMIC-BUGS but no canonical <BG-*> "
            f"record:\n{malformed_lines}"
        ),
        "next_action": (
            "If no dynamically reproduced DUT Bug exists, remove all content from the "
            "DYNAMIC-BUGS, ROOT-CAUSES, and WAVEFORM-EVIDENCE bodies. Otherwise rebuild "
            "the incomplete hierarchy as FG -> FC -> CK -> BG -> TC using "
            "Guide_Doc/dut_bug_analysis.md section 5.1. Do not leave standalone FG/FC/CK/TC "
            "scaffolds in a completed no-Bug document. Repair every listed line before "
            "calling `Check`/`Complete` again."
        ),
    }


def _render_container_line_diagnostics(
    bug_file: str,
    substantive_lines: list[tuple[int, str]],
) -> str:
    """Render one bounded list of exact file/line excerpts."""

    shown = substantive_lines[:_MAX_DYNAMIC_CONTAINER_DIAGNOSTICS]
    remaining = len(substantive_lines) - len(shown)
    rendered = []
    for line_number, content in shown:
        excerpt = re.sub(r"\s+", " ", content).strip()
        if len(excerpt) > 180:
            excerpt = excerpt[:177] + "..."
        rendered.append(f"- {bug_file}:{line_number}-{line_number}: `{excerpt}`")
    if remaining:
        rendered.append(
            f"- {remaining} additional substantive line(s) omitted from this bounded batch."
        )
    return "\n".join(rendered)


def _root_relation_issue_result(issues: list[dict], bug_file: str) -> tuple[bool, dict]:
    """Return a bounded batch of independently repairable ROOT/BG relation errors."""

    shown = issues[:_MAX_ROOT_RELATION_DIAGNOSTICS]
    remaining = len(issues) - len(shown)
    rendered = "\n".join(f"- {issue['message']}" for issue in shown)
    suppressed = (
        f"\n- {remaining} additional relation error(s) were omitted; repair the listed "
        "items and run Check/Complete once to obtain the next bounded batch."
        if remaining
        else ""
    )
    return False, {
        "error": (
            f"[Root Cause Relation Errors] Found {len(issues)} independently repairable "
            f"ROOT/BG relation error(s) in '{bug_file}':\n{rendered}{suppressed}"
        ),
        "details": {
            "issues": shown,
            "remaining_issue_count": remaining,
        },
        "next_action": [
            "Apply every listed exact line replacement or relation repair before calling "
            "Check/Complete again. These Markdown relation repairs do not require rerunning "
            "pytest, WaveInfo, or ApplyWaveInfoEvidence."
        ],
    }


def _missing_hdl_location_issue(source_content: str) -> dict:
    """Return a deterministic repair for a missing canonical HDL location."""

    malformed = _MALFORMED_HDL_SOURCE_LOCATION.search(source_content)
    if malformed is None:
        return {
            "code": "HDL_SOURCE_LOCATION_MISSING",
            "problem": (
                "source analysis must include a real HDL location in exact "
                "`path:start-end` format"
            ),
            "required": "path/to/source.sv:10-12",
            "next_action": (
                "Add the real source path and inclusive line range using the exact "
                "`path:start-end` format; repeat the number for one line, for example "
                "`path/to/source.sv:10-10`. Do not rerun WaveInfo or reclassify the Bug."
            ),
        }

    start = int(malformed.group("start"))
    end_text = malformed.group("end")
    end = int(end_text) if end_text is not None else start
    fenced_line_numbers = [
        int(match.group(1))
        for block in _HDL_FENCED_BLOCK.finditer(source_content)
        for match in re.finditer(r"(?m)^[ \t]*(\d+):", block.group("body"))
    ]
    if fenced_line_numbers:
        start = min(start, min(fenced_line_numbers))
        end = max(end, max(fenced_line_numbers))
    observed = malformed.group(0)
    replacement = f"{malformed.group('path')}:{start}-{end}"
    return {
        "code": "HDL_SOURCE_LOCATION_FORMAT",
        "problem": f"replace `{observed}` with `{replacement}`",
        "observed": observed,
        "required": "path:start-end (use start=end for one line)",
        "replacement": replacement,
        "next_action": (
            f"Replace `{observed}` with `{replacement}` in the owning "
            "<ROOT-SOURCE-EVIDENCE> field. "
            "The existing assertion, WaveInfo evidence, classification, and analysis fields "
            "do not need to be regenerated."
        ),
    }


def _extract_waveform_yaml_payload(
    payload_lines: list[str],
    *,
    block_line: int,
    bug_file: str,
) -> tuple[bool, object, object]:
    """Parse the canonical fenced YAML waveform marker and return its mapping."""

    yaml_text = textwrap.dedent("\n".join(payload_lines))
    try:
        payload = yaml.safe_load(yaml_text)
    except yaml.YAMLError as error:
        return False, "", {
            "error": (
                f"[Waveform Analysis YAML Error] Block at line {block_line} in "
                f"'{bug_file}' is invalid YAML: {error}"
            )
        }
    if not isinstance(payload, dict) or set(payload) != {_WAVEFORM_BLOCK_KEY}:
        return False, "", {
            "error": (
                f"[Waveform Analysis Marker Error] YAML block at line {block_line} in "
                f"'{bug_file}' must contain exactly one top-level key named "
                f"'{_WAVEFORM_BLOCK_KEY}'."
            )
        }
    analysis = payload[_WAVEFORM_BLOCK_KEY]
    if not isinstance(analysis, dict):
        return False, "", {
            "error": (
                f"[Waveform Analysis Format Error] '{_WAVEFORM_BLOCK_KEY}' at line "
                f"{block_line} in '{bug_file}' must contain a YAML mapping."
            )
        }
    return True, analysis, ""


def parse_bug_label(label: str) -> tuple[str, float]:
    """Parse a ``BG-NAME-XX`` label into its name and 0.0-1.0 confidence."""
    raw = str(label or "").strip().strip("<>")
    match = re.fullmatch(r"BG-(.+)-(\d{1,3})", raw)
    if not match or not match.group(1).strip():
        raise ValueError(
            f"'{label}' must use BG-NAME-XX format with an integer confidence from 0 to 100."
        )
    confidence = int(match.group(2))
    if not 0 <= confidence <= 100:
        raise ValueError(f"'{label}' confidence must be between 0 and 100.")
    return match.group(1), confidence / 100.0


def _find_matching_test_case(parts: list[str], name_list) -> tuple[bool, str]:
    """Match one documented pytest node to an exact report node ID."""

    if len(parts) not in (2, 3):
        return False, ""
    documented_node = "::".join(part.strip() for part in parts)
    for name in name_list:
        report_parts = str(name).split("::")
        if len(report_parts) != len(parts):
            continue
        report_file = re.sub(
            r":\d+(?:-\d+)?$", "", report_parts[0]
        )
        report_node = "::".join(
            [report_file.strip(), *(part.strip() for part in report_parts[1:])]
        )
        if report_node == documented_node:
            return True, name
    return False, ""


def _similar_report_test_cases(documented_test: str, name_list) -> list[str]:
    """Return bounded report-node hints without creating identity aliases."""

    documented_parts = documented_test.split("::")
    documented_file = documented_parts[0]
    documented_basename = os.path.basename(documented_file)
    documented_function = documented_parts[-1]
    candidates = []
    for name in name_list:
        report_parts = str(name).split("::")
        if len(report_parts) not in (2, 3):
            continue
        report_file = re.sub(r":\d+(?:-\d+)?$", "", report_parts[0])
        report_node = "::".join(
            [report_file.strip(), *(part.strip() for part in report_parts[1:])]
        )
        report_function = report_parts[-1].strip()
        if (
            os.path.basename(report_file) == documented_basename
            or report_function == documented_function
            or documented_function.startswith(report_function + "[")
            or report_function.startswith(documented_function + "[")
        ):
            candidates.append(report_node)
    return sorted(dict.fromkeys(candidates))[:10]


def _validate_dynamic_bug_document_labels(
    workspace: str,
    bug_file: str,
) -> tuple[bool, object]:
    """Reject static-analysis labels placed in the dynamic Bug document."""

    path = os.path.join(workspace, bug_file)
    if not os.path.isfile(path):
        return True, ""
    static_labels = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            for match in re.finditer(r"<(BG-STATIC-[^<>]+)>", line):
                static_labels.append(
                    {"line": line_number, "label": match.group(1)}
                )
    if not static_labels:
        return True, ""
    dynamic_suffix = "_bug_analysis.md"
    if bug_file.endswith(dynamic_suffix):
        static_bug_file = (
            bug_file[: -len(dynamic_suffix)] + "_static_bug_analysis.md"
        )
    else:
        static_bug_file = "{OUT}/{DUT}_static_bug_analysis.md"
    return False, {
        "error": (
            f"[Static Bug Label In Dynamic Document] Dynamic Bug document '{bug_file}' "
            f"contains {len(static_labels)} <BG-STATIC-*> label(s). Static findings belong "
            f"only in '{static_bug_file}'. When a test fails and confirms a static finding, "
            "create a distinct <BG-NAME-XX> entry in the dynamic Bug document, attach every "
            "failing <TC-*> and confirmed WaveInfo receipt, then link that dynamic label from "
            "the static document with <LINK-BUG-[BG-NAME-XX]>."
        ),
        "details": {"invalid_static_labels": static_labels},
    }


def _parse_documented_dynamic_bug_records(
    workspace: str,
    bug_file: str,
) -> tuple[bool, list[dict], object]:
    """Parse canonical non-zero dynamic Bug records without serializing tag paths."""

    path = os.path.join(workspace, bug_file)
    if not os.path.isfile(path):
        return True, [], ""
    valid_labels, label_error = _validate_dynamic_bug_document_labels(
        workspace, bug_file
    )
    if not valid_labels:
        return False, [], label_error

    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    uncommented_lines, _unclosed_comment_line = _strip_html_comments(lines)
    stripped_lines = [line.strip() for line in uncommented_lines]
    dynamic_start_indexes = [
        index
        for index, value in enumerate(stripped_lines)
        if value == _DYNAMIC_BUGS_MARKER
    ]
    dynamic_end_indexes = [
        index
        for index, value in enumerate(stripped_lines)
        if value == _DYNAMIC_BUGS_END_MARKER
    ]
    if (
        len(dynamic_start_indexes) != 1
        or len(dynamic_end_indexes) != 1
        or dynamic_start_indexes[0] >= dynamic_end_indexes[0]
    ):
        return False, [], _dynamic_container_format_error(
            bug_file, dynamic_start_indexes, dynamic_end_indexes
        )
    dynamic_start = dynamic_start_indexes[0]
    dynamic_end = dynamic_end_indexes[0]
    substantive_dynamic_lines = _substantive_lines_without_html_comments(
        lines, dynamic_start + 1, dynamic_end
    )
    if substantive_dynamic_lines and not any(
        _DOCUMENT_TAG_PATTERN.search(content)
        for _line_number, content in substantive_dynamic_lines
    ):
        return False, [], _unparseable_dynamic_container_error(
            bug_file, substantive_dynamic_lines
        )

    hierarchy = {"FG": None, "FC": None, "CK": None}
    records = []
    current = None
    fence_open = False
    first_bug_line = None
    documented_bug_count = 0
    in_dynamic_container = False
    analysis_markers = {marker for _key, marker in _BUG_ANALYSIS_SECTION_MARKERS}
    analysis_titles = {title for _key, title in _BUG_ANALYSIS_SECTION_TITLES}

    def close_current(end_index: int):
        nonlocal current
        if current is None:
            return
        current["content"] = "\n".join(lines[current["start"] + 1 : end_index])
        references = re.findall(
            rf"(?m)^[ \t]*<"
            rf"{re.escape(_ROOT_CAUSE_REFERENCE_TAG_PREFIX)}"
            rf"({_ROOT_ENTITY_TAG_PATTERN.pattern})>[ \t]+"
            rf"\[([^\]\n]+)\]\(#([^)]+)\)[ \t]*$",
            current["content"],
        )
        current["root_cause_references"] = [
            {"title": title, "anchor": anchor, "tag": tag}
            for tag, title, anchor in references
        ]
        records.append(current)
        current = None

    for index, line in enumerate(lines):
        parse_line = uncommented_lines[index]
        stripped = parse_line.strip()
        if stripped.startswith("```"):
            fence_open = not fence_open
            continue
        if fence_open:
            continue
        matches = list(_DOCUMENT_TAG_PATTERN.finditer(parse_line))
        if first_bug_line is None and any(
            match.group(1) == "BG" for match in matches
        ):
            first_bug_line = index + 1
        if stripped == _DYNAMIC_BUGS_MARKER:
            in_dynamic_container = True
            continue
        if stripped == _DYNAMIC_BUGS_END_MARKER:
            close_current(index)
            in_dynamic_container = False
            continue
        if not in_dynamic_container:
            continue
        if current is not None and re.fullmatch(r'<a id="bug-[0-9a-f]{16}"></a>', stripped):
            close_current(index)
            continue
        if current is not None and stripped in analysis_markers | analysis_titles:
            if current["analysis_start_line"] is None:
                current["analysis_start_line"] = index + 1
        if not matches:
            continue
        if current is not None and any(
            match.group(1) in {"FG", "FC", "CK", "BG"} for match in matches
        ):
            close_current(index)

        for match in matches:
            kind, value = match.groups()
            label = f"{kind}-{value}"
            try:
                display_title = _parse_dynamic_tag_heading(parse_line, kind, label)
            except ValueError as heading_error:
                return False, [], {
                    "error": (
                        f"[Dynamic Bug Heading Format Error] <{label}> at line "
                        f"{index + 1} in '{bug_file}' needs meaningful visible text: "
                        f"{heading_error}. Follow Guide_Doc/dut_bug_analysis.md "
                        "section 5.1."
                    ),
                    "details": {"tag": label, "line": index + 1},
                }
            if kind == "FG":
                hierarchy.update({"FG": label, "FC": None, "CK": None})
            elif kind == "FC":
                hierarchy.update({"FC": label, "CK": None})
            elif kind == "CK":
                hierarchy["CK"] = label
            elif kind == "BG":
                documented_bug_count += 1
                try:
                    _bug_name, confidence = parse_bug_label(label)
                except ValueError as error:
                    return False, [], {"error": f"[Invalid Bug Label] {error}"}
                if confidence == 0:
                    continue
                checkpoint = "/".join(
                    item
                    for item in (
                        hierarchy["FG"],
                        hierarchy["FC"],
                        hierarchy["CK"],
                    )
                    if item is not None
                )
                current = {
                    "bug": label,
                    "path": "/".join(
                        item for item in (checkpoint, label) if item
                    ),
                    "checkpoint": checkpoint,
                    "line": index + 1,
                    "start": index,
                    "display_title": display_title,
                    "tests": [],
                    "analysis_start_line": None,
                    "root_cause_references": [],
                }
            elif kind == "TC" and current is not None:
                if current["analysis_start_line"] is not None:
                    return False, [], {
                        "error": (
                            f"[Dynamic Bug Child Order Error] <{label}> at line "
                            f"{index + 1} in '{bug_file}' appears after Bug analysis "
                            f"started at line {current['analysis_start_line']}. Put every "
                            "TC and its WAVEFORM-REF immediately under the owning BG, then "
                            "place the three canonical BG fields after the final TC."
                        ),
                        "details": {
                            "bug": current["bug"],
                            "test": label,
                            "line": index + 1,
                            "analysis_start_line": current["analysis_start_line"],
                        },
                    }
                test_case = value.strip()
                if not test_case:
                    return False, [], {
                        "error": (
                            f"[Waveform Analysis Test Format Error] Dynamic Bug "
                            f"'{current['bug']}' contains an empty <TC-*> label at "
                            f"line {index + 1}."
                        )
                    }
                current["tests"].append(
                    {
                        "test_label": f"TC-{test_case}",
                        "test_case": test_case,
                        "display_title": display_title,
                        "line": index + 1,
                    }
                )

    close_current(len(lines))
    if substantive_dynamic_lines and documented_bug_count == 0:
        return False, [], _dynamic_container_without_bug_error(
            bug_file, substantive_dynamic_lines
        )
    if first_bug_line is not None:
        if dynamic_start + 1 > first_bug_line:
            return False, [], {
                "error": (
                    f"[Dynamic Bug Container Order Error] Standalone marker "
                    f"{_DYNAMIC_BUGS_MARKER!r} at line {dynamic_start + 1} "
                    f"must appear before the first BG entry at line {first_bug_line}."
                ),
                "details": {
                    "marker": _DYNAMIC_BUGS_MARKER,
                    "marker_line": dynamic_start + 1,
                    "first_bug_line": first_bug_line,
                },
            }
    return True, records, ""


def _parse_root_cause_relations(
    workspace: str,
    bug_file: str,
    records: list[dict],
) -> tuple[bool, object]:
    """Validate the canonical root-cause graph and its BG back-links.

    Every non-zero BG in a canonical root-cause document has exactly one
    root-cause reference and every related-Bug entry points back to that same
    checkpoint-scoped BG path.
    """

    path = os.path.join(workspace, bug_file)
    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    uncommented_lines, _unclosed_comment_line = _strip_html_comments(lines)
    stripped = [line.strip() for line in uncommented_lines]
    records_by_path = {record["path"]: record for record in records}
    available_bug_paths = sorted(records_by_path)[:5]

    def root_reference_candidates(root_titles: dict[str, str]) -> str:
        candidates = [
            _root_cause_reference(tag, title)
            for tag, title in list(root_titles.items())[:5]
        ]
        return (
            " | ".join(candidates)
            if candidates
            else "(none; create a ROOT entity first)"
        )

    def related_bug_candidates(paths: list[str] | None = None) -> str:
        candidates = []
        for bug_path in (available_bug_paths if paths is None else paths)[:5]:
            checkpoint, bug = bug_path.rsplit("/", 1)
            candidates.append(_related_bug_reference(checkpoint, bug))
        return (
            " | ".join(candidates)
            if candidates
            else "(none; add a real non-zero BG first)"
        )

    canonical_root_fields = " -> ".join(
        marker for _key, marker in _ROOT_ANALYSIS_SECTION_MARKERS
    ) + " -> " + _RELATED_BUGS_MARKER
    starts = [i for i, value in enumerate(stripped) if value == _ROOT_CAUSES_MARKER]
    ends = [i for i, value in enumerate(stripped) if value == _ROOT_CAUSES_END_MARKER]
    if not starts and not ends:
        return False, {
            "error_code": "ROOT_CAUSE_CONTAINER_MISSING",
            "error": (
                f"[Root Cause Container Missing] '{bug_file}' must contain one closed "
                f"{_ROOT_CAUSES_MARKER} container, including when no Bug was found."
            ),
            "next_action": (
                f"Add one empty {_ROOT_CAUSES_MARKER} ... {_ROOT_CAUSES_END_MARKER} "
                "section after DYNAMIC-BUGS and before WAVEFORM-EVIDENCE when there are "
                "no dynamic Bugs. Otherwise add the canonical root-cause entities from "
                "Guide_Doc/dut_bug_analysis.md section 5.1, then call `Check`/`Complete` "
                "again."
            ),
        }
    if len(starts) != 1 or len(ends) != 1 or not starts[0] < ends[0]:
        return False, {
            "error": (
                f"[Root Cause Container Format Error] '{bug_file}' must contain exactly "
                f"one closed {_ROOT_CAUSES_MARKER} container."
            )
        }
    start, end = starts[0], ends[0]
    dynamic_end_indexes = [
        index for index, value in enumerate(stripped) if value == _DYNAMIC_BUGS_END_MARKER
    ]
    waveform_start_indexes = [
        index for index, value in enumerate(stripped) if value == _WAVEFORM_EVIDENCE_MARKER
    ]
    if (
        len(dynamic_end_indexes) != 1
        or len(waveform_start_indexes) != 1
        or not dynamic_end_indexes[0] < start < end < waveform_start_indexes[0]
    ):
        return False, {
            "error": (
                f"[Root Cause Container Order Error] '{bug_file}' must place the closed "
                f"{_ROOT_CAUSES_MARKER} container after DYNAMIC-BUGS and before "
                "WAVEFORM-EVIDENCE."
            )
        }
    if end >= len(stripped) or any(
        value == _DYNAMIC_BUGS_MARKER for value in stripped[start + 1 : end]
    ):
        return False, {"error": "[Root Cause Container Format Error] nested DYNAMIC-BUGS is not allowed."}

    entity_matches = []
    entity_pattern = re.compile(
        rf"^###\s+(.+?)\s+<({_ROOT_ENTITY_TAG_PATTERN.pattern})>\s*$"
    )
    for index in range(start + 1, end):
        match = entity_pattern.match(stripped[index])
        if match:
            entity_matches.append((index, match.group(2)))
    root_tags = [root_tag for _line_index, root_tag in entity_matches]
    duplicate_root_tags = sorted(
        root_tag for root_tag in set(root_tags) if root_tags.count(root_tag) > 1
    )
    if duplicate_root_tags:
        return False, {
            "error": (
                "[Duplicate Root Cause] Every root cause must use one document-wide "
                f"unique <ROOT-...> tag; duplicated: <{duplicate_root_tags[0]}>."
            )
        }
    if not entity_matches:
        if not records:
            substantive_root_lines = _substantive_lines_without_html_comments(
                lines, start + 1, end
            )
            if substantive_root_lines:
                return False, {
                    "error_code": "ROOT_CAUSE_CONTAINER_UNPARSEABLE_CONTENT",
                    "error": (
                        f"[Root Cause Container Unparseable Content] '{bug_file}' has no "
                        "dynamic Bug or canonical <ROOT-*> entity, but ROOT-CAUSES is not "
                        "empty:\n"
                        f"{_render_container_line_diagnostics(bug_file, substantive_root_lines)}"
                    ),
                    "next_action": (
                        "For a no-Bug result, remove all content from the ROOT-CAUSES body. "
                        "If a dynamic Bug exists, first repair DYNAMIC-BUGS, then add one "
                        "canonical ROOT entity for each distinct cause using "
                        "Guide_Doc/dut_bug_analysis.md section 5.1. Repair every listed "
                        "line before calling `Check`/`Complete` again."
                    ),
                }
            return True, ""
        return False, {
            "error": (
                f"[Root Cause Entity Missing] '{bug_file}' has an empty "
                f"{_ROOT_CAUSES_MARKER} container; add one <ROOT-...> entity "
                "for each distinct root cause. Available BG path(s): "
                f"{', '.join(available_bug_paths) if available_bug_paths else '(none)'}."
            ),
            "next_action": [
                "Create one ROOT entity for each distinct cause, then use one of the "
                f"available BG entries under <RELATED-BUGS>: {related_bug_candidates()}"
            ],
        }

    dynamic_start = next(
        (index for index, value in enumerate(stripped) if value == _DYNAMIC_BUGS_MARKER),
        -1,
    )
    dynamic_end = next(
        (index for index, value in enumerate(stripped) if value == _DYNAMIC_BUGS_END_MARKER),
        len(stripped),
    )
    dynamic_anchors = [
        value[7:-6]
        for value in stripped[dynamic_start + 1 : dynamic_end]
        if value.startswith('<a id="bug-') and value.endswith('"></a>')
    ]
    for record in records:
        expected_bug_anchor = _dynamic_bug_anchor_id(record["checkpoint"], record["bug"])
        heading_index = record["line"] - 1
        adjacent_anchor = stripped[heading_index - 1] if heading_index > 0 else ""
        if (
            dynamic_anchors.count(expected_bug_anchor) != 1
            or adjacent_anchor != f'<a id="{expected_bug_anchor}"></a>'
        ):
            return False, {
                "error": (
                    f"[Dynamic Bug Anchor Missing] {record['path']} must have one generated "
                    f"anchor '#{expected_bug_anchor}' before its BG heading so related root "
                    "cause links can jump to the exact CK-scoped entry. Add this exact line "
                    f"immediately before the BG heading: <a id=\"{expected_bug_anchor}\"></a>."
                )
            }
    related_paths: dict[str, set[str]] = {}
    root_titles: dict[str, str] = {}
    relation_issues = []
    for entity_index, (line_index, root_tag) in enumerate(entity_matches):
        try:
            root_titles[root_tag] = _normalize_display_title(
                entity_pattern.match(stripped[line_index]).group(1)
            )
        except ValueError as title_error:
            return False, {
                "error": f"[Root Cause Heading Format Error] <{root_tag}> needs meaningful visible text: {title_error}."
            }
        entity_end = (
            entity_matches[entity_index + 1][0] - 1
            if entity_index + 1 < len(entity_matches)
            else end
        )
        entity_lines = stripped[line_index + 1 : entity_end]
        expected_root_anchor = f'<a id="{_root_cause_anchor_id(root_tag)}"></a>'
        anchor_count = stripped[start + 1 : end].count(expected_root_anchor)
        if anchor_count != 1 or stripped[line_index - 1] != expected_root_anchor:
            return False, {
                "error": (
                    f"[Root Cause Anchor Error] <{root_tag}> must have one generated "
                    f"anchor '#{_root_cause_anchor_id(root_tag)}'. Add this exact line "
                    f"immediately before the ROOT heading: "
                    f"<a id=\"{_root_cause_anchor_id(root_tag)}\"></a>."
                )
            }
        root_field_titles = dict(_ROOT_ANALYSIS_SECTION_TITLES)
        field_positions = {}
        for field_key, field_marker in _ROOT_ANALYSIS_SECTION_MARKERS:
            marker_indexes = [
                i for i, value in enumerate(entity_lines) if value == field_marker
            ]
            title_indexes = [
                i for i, value in enumerate(entity_lines) if value == root_field_titles[field_key]
            ]
            if len(marker_indexes) != 1 or len(title_indexes) != 1:
                return False, {
                    "error": (
                        f"[Root Cause Field Format Error] <{root_tag}> must contain exactly "
                        f"one '{root_field_titles[field_key]}' immediately followed by "
                        f"'{field_marker}'. Required ROOT order: {canonical_root_fields}."
                    )
                }
            title_index, marker_index = title_indexes[0], marker_indexes[0]
            if title_index + 1 != marker_index:
                return False, {
                    "error": (
                        f"[Root Cause Field Order Error] '{root_field_titles[field_key]}' must "
                        f"immediately precede {field_marker} under <{root_tag}>. "
                        f"Required ROOT order: {canonical_root_fields}."
                    )
                }
            field_positions[field_key] = (title_index, marker_index)
        ordered_positions = [field_positions[key][0] for key, _marker in _ROOT_ANALYSIS_SECTION_MARKERS]
        if ordered_positions != sorted(ordered_positions):
            return False, {
                "error": (
                    f"[Root Cause Field Order Error] <{root_tag}> must keep ROOT "
                    f"analysis fields in this order: {canonical_root_fields}."
                )
            }
        related_title_index = next(
            (i for i, value in enumerate(entity_lines) if value == _RELATED_BUGS_TITLE),
            None,
        )
        related_index = next(
            (i for i, value in enumerate(entity_lines) if value == _RELATED_BUGS_MARKER),
            None,
        )
        if related_title_index is None or related_index is None:
            return False, {
                "error": (
                    f"[Related Bug List Missing] <{root_tag}> must contain "
                    f"{_RELATED_BUGS_TITLE} followed by {_RELATED_BUGS_MARKER}. "
                    f"Add at least one exact entry, for example: {related_bug_candidates()}"
                )
            }
        if related_title_index + 1 != related_index:
            return False, {
                "error": (
                    f"[Related Bug List Order Error] '{_RELATED_BUGS_TITLE}' must "
                    f"immediately precede {_RELATED_BUGS_MARKER}. Use this order: "
                    f"{canonical_root_fields}."
                )
            }
        if related_title_index <= ordered_positions[-1]:
            return False, {
                "error": (
                    f"[Related Bug List Order Error] {_RELATED_BUGS_TITLE} must follow "
                    f"all ROOT analysis fields under <{root_tag}>. Use this order: "
                    f"{canonical_root_fields}."
                )
            }
        for field_index, (field_key, field_marker) in enumerate(_ROOT_ANALYSIS_SECTION_MARKERS):
            body_start = field_positions[field_key][1] + 1
            body_end = (
                field_positions[_ROOT_ANALYSIS_SECTION_MARKERS[field_index + 1][0]][0]
                if field_index + 1 < len(_ROOT_ANALYSIS_SECTION_MARKERS)
                else related_title_index
            )
            body = entity_lines[body_start:body_end]
            body_for_completeness = body
            if field_key == "source_evidence":
                body_for_completeness = [
                    value
                    for value in body
                    if value != _ROOT_SOURCE_UNAVAILABLE_MARKER
                ]
            if not re.sub(r"\s+", "", "".join(body_for_completeness)) or any(
                _BUG_TODO_MARKER in value for value in body
            ):
                return False, {
                    "error": (
                        f"[Root Cause Field Incomplete] {field_marker} for <{root_tag}> "
                        f"is empty or still contains {_BUG_TODO_MARKER}. Fill this ROOT "
                        f"field before validating the next one; required order is "
                        f"{canonical_root_fields}."
                    )
                }
            if field_key == "source_evidence":
                source_content = "\n".join(body)
                unavailable = re.findall(
                    rf"(?m)^[ \t]*{re.escape(_ROOT_SOURCE_UNAVAILABLE_MARKER)}[ \t]*$",
                    source_content,
                )
                if len(unavailable) > 1:
                    return False, {
                        "error": (
                            f"[Root Source Evidence Error] {field_marker} for <{root_tag}> "
                            f"contains {_ROOT_SOURCE_UNAVAILABLE_MARKER} more than once. "
                            f"Keep exactly one standalone {_ROOT_SOURCE_UNAVAILABLE_MARKER} "
                            "and remove every HDL block and ROOT-SOURCE-* marker."
                        ),
                        "next_action": [
                            f"Use either a complete HDL block with all {_ROOT_SOURCE_EVIDENCE_MARKERS} "
                            f"or one {_ROOT_SOURCE_UNAVAILABLE_MARKER} plus black-box evidence; do not mix them."
                        ],
                    }
                if unavailable:
                    if _HDL_FENCED_BLOCK.search(source_content) or any(
                        marker in source_content for marker in _ROOT_SOURCE_EVIDENCE_MARKERS
                    ):
                        return False, {
                            "error": (
                                f"[Root Source Evidence Error] {_ROOT_SOURCE_UNAVAILABLE_MARKER} "
                                f"is mutually exclusive with HDL evidence under <{root_tag}>. "
                                "Remove the unavailable marker if source is accessible, or "
                                "remove the HDL fence and all ROOT-SOURCE-* markers for the black-box branch."
                            ),
                            "next_action": [
                                "Choose exactly one source branch, then call Check/Complete again; "
                                "WaveInfo and pytest evidence do not need to be rerun for this format repair."
                            ],
                        }
                else:
                    if _HDL_SOURCE_LOCATION.search(source_content) is None:
                        issue = _missing_hdl_location_issue(source_content)
                        return False, {
                            "error": (
                                f"[Root Source Evidence Error] {issue['problem']} under "
                                f"<ROOT-SOURCE-EVIDENCE> of <{root_tag}>. "
                                f"Use `{issue['required']}`; for one line repeat the number, "
                                "for example `path/to/source.sv:10-10`."
                            ),
                            "details": issue,
                            "next_action": [issue["next_action"]],
                        }
                    blocks = list(_HDL_FENCED_BLOCK.finditer(source_content))
                    fenced_source = "\n".join(match.group("body") for match in blocks)
                    if not blocks:
                        return False, {
                            "error": (
                                f"[Root Source Evidence Error] {field_marker} for <{root_tag}> "
                                "requires one complete HDL fenced code block. Add the real "
                                "source location and put all ROOT-SOURCE-* markers inside it."
                            ),
                            "next_action": [
                                "Edit only <ROOT-SOURCE-EVIDENCE>; do not move source markers to BG or waveform YAML."
                            ],
                        }
                    for marker in _ROOT_SOURCE_EVIDENCE_MARKERS:
                        if source_content.count(marker) != 1 or fenced_source.count(marker) != 1:
                            return False, {
                                "error": (
                                    f"[Root Source Evidence Error] {marker} must occur exactly once "
                                    f"inside the HDL fence under <{root_tag}>. Add or move the "
                                    f"literal {marker} into a source-code comment; keep the other "
                                    f"markers {_ROOT_SOURCE_EVIDENCE_MARKERS} in that same fence."
                                ),
                                "next_action": [
                                    "Repair only <ROOT-SOURCE-EVIDENCE>, then call Check/Complete; "
                                    "no pytest, WaveInfo, or ApplyWaveInfoEvidence rerun is required."
                                ],
                            }
        related_lines = entity_lines[related_index + 1 :]
        if any(value == _RELATED_BUGS_MARKER for value in related_lines):
            return False, {"error": f"[Related Bug List Duplicate] <{root_tag}> contains more than one {_RELATED_BUGS_MARKER}."}
        paths = set()
        nonempty_related_lines = 0
        for related_offset, value in enumerate(related_lines):
            if not value:
                continue
            nonempty_related_lines += 1
            document_line = line_index + related_index + related_offset + 3
            related_match = re.fullmatch(
                r"-\s+<RELATED-BUG-([^<>]+)>\s+"
                r"\[([^\]\n]+)\]\(#([^)]+)\)",
                value,
            )
            if related_match is None:
                relation_issues.append(
                    {
                        "code": "RELATED_BUG_FORMAT_ERROR",
                        "root": root_tag,
                        "line": document_line,
                        "observed": value,
                        "message": (
                            f"[Related Bug Format Error] Invalid related-Bug entry under "
                            f"<{root_tag}> at line {document_line}: {value}. Replace it with "
                            f"one exact available entry: {related_bug_candidates()}"
                        ),
                    }
                )
                continue
            tagged_path = related_match.group(1)
            visible_path = related_match.group(2)
            path_parts = visible_path.split("/")
            if (
                len(path_parts) != 4
                or not re.fullmatch(r"FG-[^<>/]+", path_parts[0])
                or not re.fullmatch(r"FC-[^<>/]+", path_parts[1])
                or not re.fullmatch(r"CK-[^<>/]+", path_parts[2])
                or not re.fullmatch(r"BG-[^<>/]+", path_parts[3])
                or tagged_path != visible_path
            ):
                relation_issues.append(
                    {
                        "code": "RELATED_BUG_PATH_ERROR",
                        "root": root_tag,
                        "line": document_line,
                        "tagged_path": tagged_path,
                        "visible_path": visible_path,
                        "message": (
                            f"[Related Bug Path Error] <{_RELATED_BUG_TAG_PREFIX}...> must "
                            "embed the same exact FG/FC/CK/BG path as its link text; "
                            f"line {document_line} under <{root_tag}> has visible path "
                            f"'{visible_path}' and tagged path '{tagged_path}'. Replace the "
                            "whole line with one exact available entry: "
                            f"{related_bug_candidates()}"
                        ),
                    }
                )
                continue
            checkpoint_path = "/".join(path_parts[:3])
            bug_tag = path_parts[3]
            bug_path = visible_path
            expected_anchor = _dynamic_bug_anchor_id(checkpoint_path, bug_tag)
            exact_relation = _related_bug_reference(checkpoint_path, bug_tag)
            if related_match.group(3) != expected_anchor:
                relation_issues.append(
                    {
                        "code": "RELATED_BUG_LINK_ERROR",
                        "root": root_tag,
                        "line": document_line,
                        "path": bug_path,
                        "expected_anchor": expected_anchor,
                        "replacement": exact_relation,
                        "message": (
                            f"[Related Bug Link Error] {bug_path} must link to "
                            f"'#{expected_anchor}' at line {document_line} under "
                            f"<{root_tag}>. Replace the whole line with: {exact_relation}"
                        ),
                    }
                )
            if bug_path in paths:
                relation_issues.append(
                    {
                        "code": "DUPLICATE_RELATED_BUG",
                        "root": root_tag,
                        "line": document_line,
                        "path": bug_path,
                        "message": (
                            f"[Duplicate Related Bug] {bug_path} is listed more than once "
                            f"under <{root_tag}> at line {document_line}. Keep one exact "
                            "<RELATED-BUG-...> line."
                        ),
                    }
                )
                continue
            paths.add(bug_path)
        if not nonempty_related_lines:
            relation_issues.append(
                {
                    "code": "RELATED_BUG_LIST_EMPTY",
                    "root": root_tag,
                    "line": line_index + related_index + 2,
                    "message": (
                        f"[Related Bug List Empty] <{root_tag}> must link at least one BG "
                        f"path. Add one of these exact entries: {related_bug_candidates()}"
                    ),
                }
            )
        related_paths[root_tag] = paths

    if relation_issues:
        return _root_relation_issue_result(relation_issues, bug_file)

    relation_issues = []
    valid_record_roots = {}
    for record in records:
        references = record.get("root_cause_references", [])
        if len(references) != 1:
            candidate_text = (
                " Available exact reference(s): "
                + root_reference_candidates(root_titles)
            )
            relation_issues.append(
                {
                    "code": "ROOT_CAUSE_REFERENCE_ERROR",
                    "path": record["path"],
                    "line": record["line"],
                    "message": (
                        f"[Root Cause Reference Error] {record['path']} must contain exactly "
                        f"one {_ROOT_CAUSE_REFERENCE_MARKER} at the end of <BUG-TRIGGER>, "
                        f"pointing to its unique root cause.{candidate_text}"
                    ),
                }
            )
            continue
        reference = references[0]
        expected_anchor = _root_cause_anchor_id(reference["tag"])
        if (
            reference["anchor"] != expected_anchor
            or reference["tag"] not in root_titles
            or reference["title"] != root_titles.get(reference["tag"])
        ):
            relation_issues.append(
                {
                    "code": "ROOT_CAUSE_REFERENCE_TARGET_ERROR",
                    "path": record["path"],
                    "line": record["line"],
                    "message": (
                        f"[Root Cause Reference Target Error] {record['path']} points to "
                        f"undefined or invalid root cause <{reference['tag']}>. Replace it "
                        "with one exact available reference: "
                        + root_reference_candidates(root_titles)
                    ),
                }
            )
            continue
        valid_record_roots[record["path"]] = reference["tag"]
        listed_roots = [
            root_tag
            for root_tag, paths in related_paths.items()
            if record["path"] in paths
        ]
        if not listed_roots:
            exact_relation = (
                f"- <{_RELATED_BUG_TAG_PREFIX}{record['path']}> "
                f"[{record['path']}](#{_dynamic_bug_anchor_id(record['checkpoint'], record['bug'])})"
            )
            relation_issues.append(
                {
                    "code": "ROOT_CAUSE_REVERSE_LINK_MISSING",
                    "root": reference["tag"],
                    "path": record["path"],
                    "line": record["line"],
                    "replacement": exact_relation,
                    "message": (
                        f"[Root Cause Reverse Link Missing] <{reference['tag']}> must list "
                        f"{record['path']} under {_RELATED_BUGS_MARKER}. Add this exact line: "
                        f"{exact_relation}"
                    ),
                }
            )
    for root_tag, paths in related_paths.items():
        unknown = sorted(paths - set(records_by_path))
        for path in unknown:
            relation_issues.append(
                {
                    "code": "RELATED_BUG_TARGET_MISSING",
                    "root": root_tag,
                    "path": path,
                    "message": (
                        f"[Related Bug Target Missing] <{root_tag}> references undocumented "
                        f"BG path: {path}. Replace the invalid line with one exact available "
                        f"entry: {related_bug_candidates()}"
                    ),
                }
            )
        mismatched = sorted(
            path
            for path in paths - set(unknown)
            if path in valid_record_roots and valid_record_roots[path] != root_tag
        )
        for path in mismatched:
            target_root = valid_record_roots[path]
            relation_issues.append(
                {
                    "code": "ROOT_CAUSE_BIDIRECTIONAL_LINK_MISMATCH",
                    "root": root_tag,
                    "path": path,
                    "message": (
                        f"[Root Cause Bidirectional Link Mismatch] <{root_tag}> lists "
                        f"{path}, but that BG points to <{target_root}>. Remove this line "
                        f"from <{root_tag}> and add it under <{target_root}>: "
                        f"{related_bug_candidates([path])}. If <{root_tag}> is semantically "
                        "correct instead, replace the BG-side reference with "
                        f"{_root_cause_reference(root_tag, root_titles[root_tag])}."
                    ),
                }
            )
    if relation_issues:
        return _root_relation_issue_result(relation_issues, bug_file)
    return True, ""


def _parse_waveform_analysis_blocks(
    workspace: str,
    bug_file: str,
) -> tuple[bool, dict, object]:
    """Parse one central waveform record per documented failing test case."""

    path = os.path.join(workspace, bug_file)
    if not os.path.isfile(path):
        return False, {}, {
            "error": f"[Bug Analysis Missing] Dynamic bug document '{bug_file}' does not exist."
        }
    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    stripped_lines = [line.strip() for line in lines]
    marker_indexes = {
        marker: [index for index, value in enumerate(stripped_lines) if value == marker]
        for marker in (
            _DYNAMIC_BUGS_MARKER,
            _DYNAMIC_BUGS_END_MARKER,
            _WAVEFORM_EVIDENCE_MARKER,
            _WAVEFORM_EVIDENCE_END_MARKER,
        )
    }
    for marker, indexes in marker_indexes.items():
        if len(indexes) != 1:
            return False, {}, {
                "error": (
                    f"[Waveform Container Format Error] '{bug_file}' must contain exactly "
                    f"one standalone {marker}; found {len(indexes)}."
                )
            }
    dynamic_start = marker_indexes[_DYNAMIC_BUGS_MARKER][0]
    dynamic_end = marker_indexes[_DYNAMIC_BUGS_END_MARKER][0]
    evidence_start = marker_indexes[_WAVEFORM_EVIDENCE_MARKER][0]
    evidence_end = marker_indexes[_WAVEFORM_EVIDENCE_END_MARKER][0]
    if not dynamic_start < dynamic_end < evidence_start < evidence_end:
        return False, {}, {
            "error": (
                f"[Waveform Container Order Error] '{bug_file}' must place the closed "
                "DYNAMIC-BUGS container before the closed WAVEFORM-EVIDENCE container."
            )
        }

    ok, records, error = _parse_documented_dynamic_bug_records(workspace, bug_file)
    if not ok:
        return False, {}, error
    associations: dict[str, set[str]] = {}
    association_lines: dict[tuple[str, str], int] = {}
    reference_indexes: set[int] = set()
    for record in records:
        for test in record["tests"]:
            try:
                test_label = _normalize_test_case_tag(test["test_label"])
            except ValueError as parse_error:
                return False, {}, {
                    "error": (
                        f"[Waveform Test Tag Error] Invalid TC tag at line {test['line']} "
                        f"in '{bug_file}': {parse_error}."
                        )
                    }
            pair = (record["bug"], test_label)
            if pair in association_lines:
                return False, {}, {
                    "error": (
                        f"[Duplicate Waveform Association] <{record['bug']}> references "
                        f"<{test_label}> more than once. Keep one BG/TC association and one "
                        "generated WAVEFORM-REF."
                    )
                }
            associations.setdefault(test_label, set()).add(record["bug"])
            association_lines[pair] = test["line"]
            next_index = test["line"]
            while next_index < dynamic_end and not stripped_lines[next_index]:
                next_index += 1
            expected_reference = _waveform_reference(test_label)
            if next_index >= dynamic_end or stripped_lines[next_index] != expected_reference:
                return False, {}, {
                    "error": (
                        f"[Waveform Reference Missing] <{test_label}> at line {test['line']} "
                        f"under <{record['bug']}> must be followed by exact reference "
                        f"'{expected_reference}'. Call ApplyWaveInfoEvidence to create or "
                        "repair the association."
                    ),
                    "details": {
                        "bug": record["bug"],
                        "test_case": test_label,
                        "line": test["line"],
                    },
                }
            reference_indexes.add(next_index)

    for index in range(dynamic_start + 1, dynamic_end):
        stripped = stripped_lines[index]
        if _WAVEFORM_REFERENCE_MARKER in stripped and index not in reference_indexes:
            return False, {}, {
                "error": (
                    f"[Waveform Reference Unexpected] Line {index + 1} in '{bug_file}' "
                    "contains an extra WAVEFORM-REF. Keep exactly one generated reference "
                    "as the first non-empty content after its BG/TC association."
                )
            }
        if (
            (
                stripped.startswith("<WAVEFORM-")
                and _WAVEFORM_REFERENCE_MARKER not in stripped
            )
            or stripped == f"{_WAVEFORM_BLOCK_KEY}:"
            or WAVEFORM_VIEWER_MARKER in stripped
            or "/surfer/?wave=" in stripped
        ):
            return False, {}, {
                "error": (
                    f"[Waveform Placement Error] Line {index + 1} in '{bug_file}' contains "
                    "waveform data inside DYNAMIC-BUGS. Keep only WAVEFORM-REF there and "
                    "store one WAVEFORM-TC record in WAVEFORM-EVIDENCE."
                )
            }

    blocks = {}
    index = evidence_start + 1
    while index < evidence_end:
        if not stripped_lines[index]:
            index += 1
            continue
        anchor_match = re.fullmatch(r'<a id="([^"]+)"></a>', stripped_lines[index])
        if anchor_match is None:
            return False, {}, {
                "error": (
                    f"[Waveform Record Anchor Error] Unexpected content at line {index + 1} "
                    f"in '{bug_file}'. Every central record must start with its generated "
                    "waveform anchor."
                )
            }
        anchor_line = index + 1
        index += 1
        while index < evidence_end and not stripped_lines[index]:
            index += 1
        try:
            test_label, record_title = _parse_waveform_record_heading(
                stripped_lines[index] if index < evidence_end else ""
            )
        except ValueError as heading_error:
            return False, {}, {
                "error": (
                    f"[Waveform Record Tag Error] Anchor at line {anchor_line} in "
                    f"'{bug_file}' must be followed by a semantic waveform heading: "
                    f"{heading_error}."
                )
            }
        expected_anchor = _waveform_anchor_id(test_label)
        if anchor_match.group(1) != expected_anchor:
            return False, {}, {
                "error": (
                    f"[Waveform Record Anchor Error] Record <{_waveform_record_tag(test_label)}> "
                    f"must use anchor '{expected_anchor}', not '{anchor_match.group(1)}'."
                )
            }
        if test_label in blocks:
            return False, {}, {
                "error": (
                    f"[Duplicate Waveform Record] <{test_label}> has more than one central "
                    f"record in '{bug_file}'."
                )
            }
        referenced_titles = {
            test["display_title"]
            for record in records
            for test in record["tests"]
            if test["test_label"] == test_label
        }
        if referenced_titles and referenced_titles != {record_title}:
            return False, {}, {
                "error": (
                    f"[Waveform Record Title Error] Record "
                    f"<{_waveform_record_tag(test_label)}> at line {index + 1} must "
                    "reuse the associated TC's visible description exactly. Update the "
                    "record heading to match the TC heading."
                )
            }
        heading_line = index + 1
        index += 1
        while index < evidence_end and not stripped_lines[index]:
            index += 1
        if index >= evidence_end or stripped_lines[index].lower() != _WAVEFORM_FENCE_OPEN:
            return False, {}, {
                "error": (
                    f"[Waveform Analysis Fence Error] Record at line {heading_line} in "
                    f"'{bug_file}' must contain a ```yaml block."
                )
            }
        block_line = index + 1
        index += 1
        payload_lines = []
        while index < evidence_end and stripped_lines[index] != _WAVEFORM_FENCE_CLOSE:
            if stripped_lines[index].startswith("```"):
                return False, {}, {
                    "error": f"[Waveform Analysis Fence Error] Malformed fence at line {index + 1}."
                }
            payload_lines.append(lines[index])
            index += 1
        if index >= evidence_end:
            return False, {}, {
                "error": f"[Waveform Analysis Fence Error] Block at line {block_line} is unclosed."
            }
        payload_ok, payload, payload_error = _extract_waveform_yaml_payload(
            payload_lines,
            block_line=block_line,
            bug_file=bug_file,
        )
        if not payload_ok:
            return False, {}, payload_error
        expected_bugs = sorted(associations.get(test_label, set()))
        recovery_call = {
            "tool": "ApplyWaveInfoEvidence",
            "arguments": {
                "target_file": bug_file,
                "bug_tag": expected_bugs[0] if expected_bugs else "",
                "test_case_tag": test_label,
                "receipt_id": payload.get("receipt_id", ""),
            },
        }
        index += 1
        while index < evidence_end and not stripped_lines[index]:
            index += 1
        if index >= evidence_end:
            return False, {}, {
                "error": (
                    f"[Waveform Viewer Link Missing] Central record for <{test_label}> "
                    "has no tool-generated WAVEFORM-VIEWER link."
                ),
                "details": {"recovery_call": recovery_call},
            }
        try:
            viewer_token, viewer_payload = parse_waveform_viewer_markdown_link(
                stripped_lines[index]
            )
        except WaveformViewerProtocolError as viewer_error:
            return False, {}, {
                "error": (
                    f"[Waveform Viewer Link Invalid] Line {index + 1} for <{test_label}> "
                    f"must be the tool-generated WAVEFORM-VIEWER link: {viewer_error}."
                ),
                "details": {"recovery_call": recovery_call},
            }
        documented_bugs = payload.get("bug_tags")
        bug_evidence = payload.get("bug_evidence")
        if payload.get("test_case") != test_label:
            return False, {}, {
                "error": (
                    f"[Waveform Record Test Mismatch] Block at line {block_line} must set "
                    f"test_case to '{test_label}'."
                )
            }
        if documented_bugs != expected_bugs or not expected_bugs:
            return False, {}, {
                "error": (
                    f"[Waveform Bug Association Mismatch] Record <{test_label}> must list "
                    "exactly the Bugs that reference it. Delete the record when its final Bug "
                    "association is removed."
                ),
                "details": {
                    "documented_bug_tags": documented_bugs,
                    "expected_bug_tags": expected_bugs,
                },
            }
        if not isinstance(bug_evidence, dict) or sorted(bug_evidence) != expected_bugs:
            return False, {}, {
                "error": (
                    f"[Waveform Bug Evidence Mismatch] bug_evidence for <{test_label}> must "
                    "contain exactly one mapping for every associated Bug."
                )
            }
        blocks[test_label] = {
            "line": block_line,
            "anchor_line": anchor_line,
            "heading_line": heading_line,
            "data": payload,
            "bugs": expected_bugs,
            "association_lines": {
                bug: association_lines[(bug, test_label)] for bug in expected_bugs
            },
            "viewer_line": index + 1,
            "viewer_token": viewer_token,
            "viewer_payload": viewer_payload,
            "viewer_url": build_waveform_viewer_url(viewer_payload),
        }
        index += 1

    orphan_records = sorted(set(blocks) - set(associations))
    if orphan_records:
        return False, {}, {
            "error": (
                f"[Orphan Waveform Record] Central records have no BG/TC reference: "
                f"{fc.list_str_abbr(orphan_records)}. Delete them."
            )
        }
    return True, blocks, ""


def _required_waveform_pairs(
    workspace: str,
    bug_file: str,
    target_ck_prefix: str,
    failed_tc_and_cks: dict,
    require_all_documented: bool = False,
) -> tuple[bool, list[dict], object]:
    ok, records, error = _parse_documented_dynamic_bug_records(
        workspace, bug_file
    )
    if not ok:
        return False, [], error
    if not failed_tc_and_cks and not require_all_documented:
        return True, [], ""

    required = {}
    unmatched = []
    for record in records:
        for test in record["tests"]:
            matched, report_name = _find_matching_test_case(
                test["test_case"].split("::"), failed_tc_and_cks.keys()
            )
            if not matched:
                if require_all_documented:
                    unmatched.append(
                        {
                            "bug": record["bug"],
                            "test_case": test["test_case"],
                            "checkpoint": record["checkpoint"],
                            "line": test["line"],
                            "reason": "test case is absent from the validation set",
                            "similar_report_test_cases": _similar_report_test_cases(
                                test["test_case"],
                                failed_tc_and_cks.keys(),
                            ),
                        }
                    )
                continue
            if record["checkpoint"] not in failed_tc_and_cks.get(report_name, []):
                if require_all_documented:
                    unmatched.append(
                        {
                            "bug": record["bug"],
                            "test_case": test["test_case"],
                            "checkpoint": record["checkpoint"],
                            "line": test["line"],
                            "reason": (
                                "documented checkpoint is absent from the test's "
                                "validation set"
                            ),
                        }
                    )
                continue
            pair = (record["bug"], test["test_label"])
            required[pair] = {
                "bug": record["bug"],
                "test_label": test["test_label"],
                "test_case": test["test_case"],
                "report_test_case": report_name,
                "checkpoint": record["checkpoint"],
                "line": test["line"],
            }
    if unmatched:
        item = unmatched[0]
        remaining_pair_count = len(unmatched) - 1
        return False, [], {
            "error": (
                "[Waveform Analysis Association Incomplete] First blocking documented "
                f"pair: {item['bug']}/TC-{item['test_case']} (line {item['line']}): "
                f"{item['reason']}; checkpoint={item['checkpoint'] or '<missing>'}. "
                f"{remaining_pair_count} later pair(s) are intentionally suppressed. "
                "Repair this exact test/checkpoint association, then call Check/Complete "
                "again."
            ),
            "details": {
                "unmatched_pairs": [item],
                "remaining_pair_count": remaining_pair_count,
            },
        }
    return True, list(required.values()), ""


def _waveform_error(message: str, **details) -> tuple[bool, object]:
    result = {"error": message}
    if details:
        result["details"] = details
    return False, result


def _documented_dynamic_bug_blocks(
    workspace: str,
    bug_file: str,
) -> tuple[bool, list[dict], object]:
    """Return line-bounded blocks for each non-zero dynamic Bug occurrence."""

    return _parse_documented_dynamic_bug_records(workspace, bug_file)


def _parse_bug_analysis_sections(content: str) -> tuple[dict[str, dict], list[dict]]:
    """Split canonical title-marker-content fields and retain field line offsets."""

    markers = dict(_BUG_ANALYSIS_SECTION_MARKERS)
    titles = dict(_BUG_ANALYSIS_SECTION_TITLES)
    pairs = {}
    problems = []

    def line_offset(position: int) -> int:
        return content.count("\n", 0, position)

    for key, marker in _BUG_ANALYSIS_SECTION_MARKERS:
        marker_matches = list(
            re.finditer(rf"(?m)^[ \t]*{re.escape(marker)}[ \t]*$", content)
        )
        title = titles[key]
        title_matches = list(
            re.finditer(rf"(?m)^[ \t]*{re.escape(title)}[ \t]*$", content)
        )
        if len(marker_matches) != 1:
            nearest_match = (
                marker_matches[0]
                if marker_matches
                else (title_matches[0] if title_matches else None)
            )
            problems.append(
                {
                    "line_offset": (
                        line_offset(nearest_match.start())
                        if nearest_match is not None
                        else None
                    ),
                    "problem": (
                        f"marker {marker!r} occurs {len(marker_matches)} time(s); "
                        "exactly one is required"
                    ),
                }
            )
            continue
        marker_match = marker_matches[0]
        if len(title_matches) != 1:
            problems.append(
                {
                    "line_offset": line_offset(marker_match.start()),
                    "problem": (
                        f"field {key!r} must use its exact level-6 title "
                        f"immediately before marker {marker!r}; found "
                        f"{len(title_matches)} matching title occurrence(s). See "
                        "Guide_Doc/dut_bug_analysis.md section 5.1"
                    ),
                }
            )
            continue
        title_match = title_matches[0]
        if title_match.end() > marker_match.start() or content[
            title_match.end() : marker_match.start()
        ].strip():
            problems.append(
                {
                    "line_offset": line_offset(marker_match.start()),
                    "problem": (
                        f"field {key!r} must place its exact level-6 title "
                        f"immediately before marker {marker!r}. See "
                        "Guide_Doc/dut_bug_analysis.md section 5.1"
                    ),
                }
            )
            continue
        pairs[key] = (title_match, marker_match)

    if len(pairs) != len(_BUG_ANALYSIS_SECTION_MARKERS):
        return {}, problems

    expected_keys = [key for key, _marker in _BUG_ANALYSIS_SECTION_MARKERS]
    ordered = sorted(pairs.items(), key=lambda item: item[1][0].start())
    actual_keys = [key for key, _pair in ordered]
    if actual_keys != expected_keys:
        expected_markers = " -> ".join(markers[key] for key in expected_keys)
        problems.append(
            {
                "line_offset": line_offset(ordered[0][1][0].start()),
                "problem": (
                    "analysis fields are out of canonical order; expected "
                    + expected_markers
                ),
            }
        )
        return {}, problems

    sections = {}
    for index, (key, (title_match, marker_match)) in enumerate(ordered):
        content_end = (
            ordered[index + 1][1][0].start()
            if index + 1 < len(ordered)
            else len(content)
        )
        sections[key] = {
            "content": content[marker_match.end() : content_end].strip(),
            "title_line_offset": line_offset(title_match.start()),
            "marker_line_offset": line_offset(marker_match.start()),
        }
    return sections, problems


def _normalized_bug_analysis_field_text(content: str) -> str:
    """Remove display/control markers before checking whether a field is empty."""

    without_display_headings = re.sub(
        r"(?m)^[ \t]*(?:#{1,6}[ \t]+.+|\*\*[^*\n]+\*\*)[ \t]*$",
        "",
        content,
    )
    without_optional_markers = re.sub(
        rf"(?m)^[ \t]*{re.escape(_BUG_TODO_MARKER)}[ \t]*$",
        "",
        without_display_headings,
    )
    return re.sub(r"\s+", "", without_optional_markers)


def check_dynamic_bug_analysis_content(
    workspace: str,
    bug_file: str,
) -> tuple[bool, object]:
    """Require every non-zero dynamic Bug scaffold to contain completed analysis."""

    if not os.path.isfile(os.path.join(workspace, bug_file)):
        return False, _missing_dynamic_bug_document_error(bug_file)
    ok, blocks, error = _documented_dynamic_bug_blocks(workspace, bug_file)
    if not ok:
        return False, error
    if not blocks:
        root_ok, root_error = _parse_root_cause_relations(workspace, bug_file, blocks)
        if not root_ok:
            return False, root_error
        return True, (
            "No documented non-zero-confidence dynamic Bugs require content validation."
        )

    issues = []
    for block in blocks:
        content = block["content"]
        sections, section_problems = _parse_bug_analysis_sections(content)
        for problem in section_problems:
            problem_line = block["line"]
            if problem["line_offset"] is not None:
                problem_line += problem["line_offset"] + 1
            issues.append(
                {
                    "bug": block["bug"],
                    "path": block["path"],
                    "line": problem_line,
                    "problem": problem["problem"],
                }
            )

        if _BUG_TODO_MARKER in content:
            todo_offset = content.count(
                "\n", 0, content.index(_BUG_TODO_MARKER)
            )
            issues.append(
                {
                    "bug": block["bug"],
                    "path": block["path"],
                    "line": block["line"] + todo_offset + 1,
                    "problem": f"unfinished marker {_BUG_TODO_MARKER!r} remains",
                }
            )

        if sections:
            markers_by_key = dict(_BUG_ANALYSIS_SECTION_MARKERS)
            references = block.get("root_cause_references", [])
            expected_reference = ""
            if len(references) == 1:
                expected_reference = (
                    f"<{_ROOT_CAUSE_REFERENCE_TAG_PREFIX}{references[0]['tag']}> "
                    f"[{references[0]['title']}](#{references[0]['anchor']})"
                )
            for key, section in sections.items():
                section_content = section["content"]
                field_text = section_content
                if key == "trigger" and expected_reference:
                    if not field_text.rstrip().endswith(expected_reference):
                        issues.append(
                            {
                                "bug": block["bug"],
                                "path": block["path"],
                                "line": block["line"] + section["marker_line_offset"] + 1,
                                "problem": (
                                    "the trigger field must end with its only canonical "
                                    f"root-cause reference: {expected_reference!r}"
                                ),
                            }
                        )
                    else:
                        field_text = field_text.rstrip()[: -len(expected_reference)]
                if not _normalized_bug_analysis_field_text(field_text):
                    issues.append(
                        {
                            "bug": block["bug"],
                            "path": block["path"],
                            "line": (
                                block["line"] + section["marker_line_offset"] + 1
                            ),
                            "problem": (
                                f"field {key!r} after {markers_by_key[key]!r} "
                                "has no content beyond display/control markers"
                            ),
                        }
                    )

            legacy_markers = [
                marker
                for marker in (
                    "<BUG-ROOT-CAUSE>",
                    "<BUG-SOURCE-EVIDENCE>",
                    "<BUG-CAUSAL-CHAIN>",
                    "<BUG-FIX>",
                    "<BUG-RETEST>",
                )
                if marker in content
            ]
            if legacy_markers:
                issues.append(
                    {
                        "bug": block["bug"],
                        "path": block["path"],
                        "line": block["line"],
                        "problem": (
                            "moved ROOT-owned field marker(s) remain in the BG entry: "
                            + ", ".join(legacy_markers)
                        ),
                    }
                )

    if issues:
        issue = issues[0]
        remaining_issue_count = len(issues) - 1
        if issue.get("code") in {
            "HDL_SOURCE_LOCATION_FORMAT",
            "HDL_SOURCE_LOCATION_MISSING",
        }:
            next_action = [issue["next_action"]]
            remediation = (
                "\nThis is a deterministic source-location format repair. Apply the "
                "listed replacement, then call Check/Complete again. Do not recreate the "
                "BG/TC scaffold, rerun WaveInfo, or redo Bug classification."
            )
        else:
            next_action = [
                issue.get("next_action")
                or (
                    "Repair this one blocking issue in the owning full FG/FC/CK/BG path "
                    "using the complete canonical example in "
                    "Guide_Doc/dut_bug_analysis.md section 5.1. Every occurrence of a BG "
                    "under a different checkpoint is an independently complete path entry."
                )
            ]
            remediation = (
                "\nRepair only this reported blocker, then call Check/Complete for the next "
                "validation result. "
                "Use record_dynamic_bug.py only when the path scaffold itself is absent; "
                "otherwise follow the complete canonical example in "
                "Guide_Doc/dut_bug_analysis.md section 5.1. Do not restart evidence "
                "collection for a field-format error."
            )
        suppressed = (
            f" {remaining_issue_count} later issue(s) are intentionally suppressed until "
            "this blocker is repaired."
            if remaining_issue_count
            else ""
        )
        return False, {
            "error": (
                f"[Dynamic Bug Analysis Incomplete] First blocking content issue in "
                f"'{bug_file}':\n- {issue['path']} (line {issue['line']}): "
                f"{issue['problem']}."
                + suppressed
                + remediation
            ),
            "details": {
                "issues": [issue],
                "remaining_issue_count": remaining_issue_count,
            },
            "next_action": next_action,
        }
    root_ok, root_error = _parse_root_cause_relations(workspace, bug_file, blocks)
    if not root_ok:
        return False, root_error
    return True, f"Validated completed analysis for {len(blocks)} dynamic Bug entry(s)."


def _is_nonempty_string(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_int(value, *, minimum=None, maximum=None) -> bool:
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    if minimum is not None and value < minimum:
        return False
    if maximum is not None and value > maximum:
        return False
    return True


def _recommended_explicit_waveinfo_call(
    receipt_args: dict,
    receipt_result: dict,
) -> dict:
    """Build an MCP-callable explicit-window retry for exploratory receipts."""

    stored = receipt_result.get("recommended_evidence_call")
    if isinstance(stored, dict) and stored:
        return stored
    window = receipt_result.get("analysis_window") or {}
    patterns = []
    for item in receipt_args.get("pattern") or []:
        patterns.append(
            {
                "signal": item.get("signal", ""),
                "event": item.get("event", "change"),
                "value": item.get("value") or "",
            }
        )
    return {
        "test_case_name": receipt_args.get("test_case_name") or "",
        "pattern": patterns,
        "signal_groups": copy.deepcopy(receipt_args.get("signal_groups") or {}),
        "logged_cycle": -1,
        "clock_signal": "",
        "start_step": window.get("effective_start_step", -1),
        "end_step": window.get("effective_end_step", -1),
        "context_steps": receipt_args.get("context_steps", 1),
        "max_points": receipt_args.get("max_points", 200),
    }


def _is_iso_time(value) -> bool:
    if not _is_nonempty_string(value):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _validate_receipt_identity(
    data: dict,
    receipt: dict,
    field_differences: dict[str, dict[str, object]] | None = None,
) -> list[str]:
    """Validate copied waveform identity fields against an actual receipt.

    ``field_differences`` is optional so callers can return actionable values without
    weakening the exact equality checks used for evidence validation.
    """
    errors = []
    receipt_result = receipt.get("result", {})
    selection = receipt_result.get("waveform_selection")

    def compare(key: str, expected: object, message: str):
        if data.get(key) == expected:
            return
        if field_differences is not None:
            field_differences[key] = {
                "documented": data.get(key),
                "receipt": expected,
            }
        errors.append(
            f"{message} (documented={data.get(key)!r}; receipt={expected!r})"
        )

    for key in ("receipt_id", "result_fingerprint"):
        if not _is_nonempty_string(data.get(key)):
            errors.append(f"'{key}' must be a non-empty string")
    compare(
        "result_fingerprint",
        receipt_result.get("result_fingerprint"),
        "result_fingerprint does not match the WaveInfo call receipt",
    )
    if not isinstance(selection, dict):
        errors.append("the WaveInfo receipt has no waveform_selection metadata")
        return errors
    identity_fields = (
        "waveform_file",
        "freshness_identity",
        "size_bytes",
        "modified_at",
        "modified_time_ns",
        "session_started_at",
        "observed_at",
    )
    for key in identity_fields:
        compare(
            key,
            selection.get(key),
            f"'{key}' does not match the referenced WaveInfo receipt",
        )
    if not _is_int(data.get("size_bytes"), minimum=1):
        errors.append("'size_bytes' must be a positive integer")
    if not _is_int(data.get("modified_time_ns"), minimum=1):
        errors.append("'modified_time_ns' must be a positive integer")
    for key in ("modified_at", "session_started_at", "observed_at"):
        if not _is_iso_time(data.get(key)):
            errors.append(f"'{key}' must be an ISO-8601 timestamp with timezone")
    expected_identity = (
        f"{data.get('waveform_file')}:{data.get('size_bytes')}:"
        f"{data.get('modified_time_ns')}"
    )
    if data.get("freshness_identity") != expected_identity:
        if field_differences is not None:
            field_differences["freshness_identity"] = {
                "documented": data.get("freshness_identity"),
                "expected_from_documented_fields": expected_identity,
            }
        errors.append("freshness_identity is inconsistent with waveform_file/size/mtime")
    return errors


def _waveform_issue_result(issues: list[dict]) -> tuple[bool, object]:
    """Return only the first blocking waveform error with later issues suppressed."""
    if not issues:
        return True, ""
    issue = issues[0]
    remaining_issue_count = len(issues) - 1
    details = copy.deepcopy(issue.get("details", {}))
    details["remaining_issue_count"] = remaining_issue_count
    if issue.get("repair_kind") == "semantic_field":
        next_action = details["next_action"]
        later_note = (
            f" {remaining_issue_count} other waveform blocker(s) are not part of the "
            "current action and must not be edited yet."
            if remaining_issue_count
            else ""
        )
        return _waveform_error(
            issue["message"]
            + " "
            + next_action
            + " Do not rerun pytest or WaveInfo, do not call ApplyWaveInfoEvidence, "
            "and do not edit any other field or waveform record."
            + later_note
            + " Then call Check/Complete again.",
            **details,
        )

    deletion_guard = (
        " Do not delete a TC, BG, or enclosing FG/FC/CK branch merely to remove this "
        "validation error while the correctly implemented test still fails. Follow the "
        "blocker-specific action above. Rerun the test or WaveInfo only when that action "
        "explicitly says the receipt or waveform evidence is missing, stale, or unusable. "
        "Remove a dynamic record only after a correct test passes or other evidence proves "
        "it is not a DUT Bug."
    )
    return _waveform_error(
        issue["message"]
        + (
            f" {remaining_issue_count} later waveform issue(s) are intentionally "
            "suppressed until this blocker is repaired."
            if remaining_issue_count
            else ""
        )
        + " Repair only this waveform blocker, then call Check/Complete again."
        + deletion_guard,
        **details,
    )


_DEFERRED_WAVEFORM_REPLAY_STATUSES = frozenset(
    {
        "test_directory_missing",
        "waveform_data_directory_missing",
        "waveform_session_missing",
        "waveform_not_found_in_latest_session",
        "stale_waveform_only",
    }
)


def _viewer_replay_contract(viewer: object) -> dict[str, object] | None:
    """Return viewer fields that describe behavior rather than a volatile file path."""

    if not isinstance(viewer, dict):
        return None
    payload = viewer.get("payload")
    if not isinstance(payload, dict):
        return None
    contract = {
        key: copy.deepcopy(payload.get(key))
        for key in ("v", "start", "end", "cursor", "signals")
    }
    if payload.get("v") == 2:
        contract["test_dir"] = copy.deepcopy(payload.get("test_dir"))
        contract["test_case"] = copy.deepcopy(payload.get("test_case"))
    return contract


def check_waveform_bug_analysis(
    workspace: str,
    bug_file: str,
    target_ck_prefix: str,
    failed_tc_and_cks: dict,
    waveform_tool=None,
    waveform_test_dir: str | None = None,
    require_all_documented: bool = False,
    require_current_replay: bool = False,
) -> tuple[bool, object]:
    """Require verified WaveInfo receipts for every non-zero dynamic Bug/TC pair."""

    ok, required, error = _required_waveform_pairs(
        workspace,
        bug_file,
        target_ck_prefix,
        failed_tc_and_cks,
        require_all_documented=require_all_documented,
    )
    if not ok:
        return False, error
    if not required:
        if os.path.isfile(os.path.join(workspace, bug_file)):
            structure_ok, _blocks, structure_error = _parse_waveform_analysis_blocks(
                workspace, bug_file
            )
            if not structure_ok:
                return False, structure_error
        content_ok, content_message = check_dynamic_bug_analysis_content(
            workspace, bug_file
        )
        if not content_ok:
            return False, content_message
        return True, "No dynamically reproduced non-zero-confidence bugs require waveform analysis."

    ok, blocks, error = _parse_waveform_analysis_blocks(workspace, bug_file)
    if not ok:
        return False, error
    missing_items = [
        item
        for item in required
        if item["test_label"] not in blocks
    ]
    if missing_items:
        item = missing_items[0]
        missing = f"{item['bug']}/{item['test_label']}"
        recovery_call = {
            "tool": "ApplyWaveInfoEvidence",
            "arguments": {
                "target_file": bug_file,
                "bug_tag": item["bug"],
                "test_case_tag": item["test_label"],
                "checkpoint_path": item["checkpoint"],
                "receipt_id": "",
            },
        }
        remaining_item_count = len(missing_items) - 1
        return _waveform_error(
            f"[Waveform Analysis Missing] First blocking dynamic Bug/test association "
            f"lacks a central '{_WAVEFORM_BLOCK_KEY}' record: {missing}. "
            f"{remaining_item_count} later association(s) are intentionally suppressed. "
            "Call final WaveInfo for this failing test, then invoke the exact "
            "ApplyWaveInfoEvidence recovery call below. The tool creates the WAVEFORM-REF "
            "and the TC's unique central WAVEFORM-TC record. "
            "Static-only findings belong in the separate static Bug document and cannot "
            "be represented here with a <BG-STATIC-*> tag.",
            missing=[missing],
            recovery_calls=[recovery_call],
            remaining_item_count=remaining_item_count,
        )

    validation_items = []
    for item in required:
        if any(existing["test_label"] == item["test_label"] for existing in validation_items):
            continue
        central_item = dict(item)
        central_item["bugs"] = blocks[item["test_label"]]["bugs"]
        validation_items.append(central_item)

    status_issues = []
    for item in validation_items:
        block = blocks[item["test_label"]]
        if block["data"].get("status") != "confirmed":
            status_issues.append(
                {
                    "message": (
                        f"[Waveform Confirmation Required] Block at line {block['line']} for "
                        f"'{item['test_label']}' must use status: confirmed. "
                        "A non-zero-confidence Bug cannot be completed with status: unavailable. "
                        "Rerun the failing test, call WaveInfo, and record event-level evidence."
                    ),
                    "details": {
                        "bugs": item["bugs"],
                        "test_case": item["test_case"],
                        "line": block["line"],
                    },
                }
            )
    if status_issues:
        return _waveform_issue_result(status_issues)

    if waveform_tool is None or not callable(
        getattr(waveform_tool, "get_analysis_receipt", None)
    ):
        return _waveform_error(
            "[WaveInfo Required] Dynamic Bug waveform validation requires WaveInfo. Enable and "
            "call WaveInfo before Check/Complete; document-only waveform data is not accepted."
        )
    if waveform_test_dir:
        expected_test_dir = (
            os.path.abspath(waveform_test_dir)
            if os.path.isabs(waveform_test_dir)
            else os.path.abspath(os.path.join(workspace, waveform_test_dir))
        )
        configured_test_dir = os.path.abspath(str(getattr(waveform_tool, "test_dir", "")))
        if configured_test_dir != expected_test_dir:
            return _waveform_error(
                "[WaveInfo Test Directory Mismatch] WaveInfo searches "
                f"'{configured_test_dir}', but the current test artifacts are in "
                f"'{expected_test_dir}'. Waveform receipts from another test directory cannot "
                "be used as Bug evidence."
            )

    issues = []
    for item in validation_items:
        block = blocks[item["test_label"]]
        data = block["data"]
        line = block["line"]
        receipt_id = data.get("receipt_id")
        if not _is_nonempty_string(receipt_id):
            issues.append(
                {
                    "message": (
                        f"[WaveInfo Receipt Missing] Block at line {line} must contain the "
                        "receipt_id returned by an actual WaveInfo call."
                    ),
                    "details": {
                        "bugs": item["bugs"],
                        "test_case": item["test_case"],
                        "line": line,
                    },
                }
            )
            continue
        receipt = waveform_tool.get_analysis_receipt(receipt_id)
        if receipt is None:
            issues.append(
                {
                    "message": (
                        f"[WaveInfo Receipt Not Found] receipt_id '{receipt_id}' at line {line} "
                        "was not found in this workspace's signed WaveInfo receipt store. Verify "
                        "the workspace/test directory, or call final WaveInfo again for this test "
                        "and pass the new receipt to ApplyWaveInfoEvidence. Copied or invented "
                        "waveform data cannot satisfy validation."
                    ),
                    "details": {
                        "bugs": item["bugs"],
                        "test_case": item["test_case"],
                        "line": line,
                    },
                }
            )
            continue

        receipt_args = receipt.get("arguments", {})
        receipt_result = receipt.get("result", {})
        receipt_test = str(receipt_args.get("test_case_name", "")).split("::")[-1]
        documented_test = item["test_case"].split("::")[-1]
        if receipt_test != documented_test:
            issues.append(
                {
                    "message": (
                        f"[WaveInfo Receipt Test Mismatch] Receipt '{receipt_id}' analyzed "
                        f"'{receipt_args.get('test_case_name')}', not '{item['test_case']}'."
                    ),
                    "details": {
                        "bugs": item["bugs"],
                        "test_case": item["test_case"],
                        "line": line,
                    },
                }
            )
            continue

        receipt_has_explicit_window = all(
            _is_int(receipt_args.get(key), minimum=0)
            for key in ("start_step", "end_step")
        )
        receipt_has_cycle_alignment = (
            _is_int(receipt_args.get("logged_cycle"), minimum=0)
            and _is_nonempty_string(receipt_args.get("clock_signal"))
        )
        receipt_window = receipt_result.get("analysis_window") or {}
        receipt_has_recommended_window = all(
            _is_int(receipt_window.get(key), minimum=0)
            for key in ("effective_start_step", "effective_end_step")
        )
        receipt_is_untruncated_event_search = (
            receipt_result.get("success") is True
            and receipt_result.get("status")
            in {"events_found", "evidence_window_required"}
            and (receipt_result.get("event_summary") or {}).get(
                "timeline_truncated"
            )
            is False
        )
        if (
            isinstance(receipt_args.get("pattern"), list)
            and receipt_args.get("pattern")
            and not receipt_has_explicit_window
            and not receipt_has_cycle_alignment
            and receipt_has_recommended_window
            and receipt_is_untruncated_event_search
        ):
            recommendation = _recommended_explicit_waveinfo_call(
                receipt_args, receipt_result
            )
            start_step = recommendation.get("start_step")
            end_step = recommendation.get("end_step")
            issues.append(
                {
                    "message": (
                        f"[WaveInfo Explicit Window Required] Receipt '{receipt_id}' at "
                        f"line {line} came from a whole-waveform exploratory pattern call, "
                        "not a final-evidence call. It cannot be made valid by writing null "
                        "or by copying analysis_window.effective_* into this document. Call "
                        f"WaveInfo again for '{receipt_args.get('test_case_name')}' with "
                        f"start_step={start_step!r}, end_step={end_step!r}, the same pattern, "
                        "context_steps, and max_points; then pass the new receipt to "
                        "ApplyWaveInfoEvidence."
                    ),
                    "details": {
                        "bugs": item["bugs"],
                        "test_case": item["test_case"],
                        "line": line,
                        "receipt_id": receipt_id,
                        "recommended_evidence_call": recommendation,
                    },
                }
            )
            continue

        field_differences = {}
        errors = []
        if receipt_result.get("success") is not True:
            errors.append("the referenced WaveInfo call did not succeed")
        if (receipt_result.get("event_summary") or {}).get("timeline_truncated") is True:
            errors.append("the referenced WaveInfo timeline was truncated")
        if receipt_result.get("evidence_usable") is not True:
            errors.append("the referenced WaveInfo result was not usable as final evidence")
        errors.extend(
            _validate_receipt_identity(data, receipt, field_differences)
        )
        semantic_field_repairs = {}
        receipt_viewer = receipt_result.get("waveform_viewer")
        documented_viewer = {
            "payload": block.get("viewer_payload"),
            "url": block.get("viewer_url"),
        }
        if (
            not isinstance(receipt_viewer, dict)
            or not isinstance(receipt_viewer.get("payload"), dict)
            or not _is_nonempty_string(receipt_viewer.get("url"))
        ):
            errors.append(
                "the WaveInfo receipt has no complete signed waveform_viewer; it may "
                "come from an older or interrupted WaveInfo call. Session cleanup or a "
                "changed current waveform path cannot alter an immutable signed receipt. "
                "Rerun final WaveInfo and replace both the YAML block and viewer link"
            )
            field_differences["waveform_viewer"] = {
                "documented": documented_viewer,
                "receipt": receipt_viewer,
            }
        elif documented_viewer != receipt_viewer:
            errors.append(
                "the online viewer link payload does not match the signed WaveInfo receipt"
            )
            field_differences["waveform_viewer"] = {
                "documented": documented_viewer,
                "receipt": receipt_viewer,
            }

        result_signal_groups = receipt_result.get("signal_groups")
        if isinstance(receipt_viewer, dict) and isinstance(
            receipt_viewer.get("payload"), dict
        ):
            viewer_signals = receipt_viewer["payload"].get("signals") or []
            expected_signals = []
            resolved_clock = (
                (receipt_result.get("cycle_alignment") or {}).get("clock") or {}
            ).get("signal")
            if isinstance(resolved_clock, str) and resolved_clock:
                expected_signals.append(resolved_clock)
            if isinstance(result_signal_groups, dict):
                for field_name in _WAVEFORM_SIGNAL_GROUP_FIELDS:
                    for signal in result_signal_groups.get(field_name) or []:
                        if signal not in expected_signals:
                            expected_signals.append(signal)
            for signal in (receipt_result.get("signals") or {}):
                if signal not in expected_signals:
                    expected_signals.append(signal)
            if viewer_signals != expected_signals:
                field_differences["waveform_viewer_signals"] = {
                    "documented": viewer_signals,
                    "expected": expected_signals,
                }
                errors.append(
                    "the online viewer signal list does not contain the complete signed "
                    "clock/input/output/protocol/key-signal context"
                )

        def compare_receipt_value(key: str, expected: object, message: str):
            if data.get(key) == expected:
                return
            field_differences[key] = {
                "documented": data.get(key),
                "receipt": expected,
            }
            errors.append(
                f"{message} (documented={data.get(key)!r}; receipt={expected!r})"
            )

        receipt_signal_groups = receipt_args.get("signal_groups")
        documented_signal_groups = data.get("signal_groups")
        result_signal_groups = receipt_result.get("signal_groups")
        if not isinstance(receipt_signal_groups, dict) or not receipt_signal_groups:
            errors.append(
                "the referenced WaveInfo receipt has no complete signal_groups contract; "
                "rerun final WaveInfo with the DUT clock mode, relevant inputs, outputs, "
                "protocol controls, and function-specific key signals"
            )
        else:
            try:
                normalized_signal_groups = waveform_tool.normalize_analysis_arguments(
                    test_case_name=receipt_args.get("test_case_name"),
                    pattern=receipt_args.get("pattern"),
                    signal_groups=receipt_signal_groups,
                )["signal_groups"]
            except Exception as error:
                normalized_signal_groups = None
                errors.append(f"signal_groups is invalid: {error}")
            if normalized_signal_groups != receipt_signal_groups:
                field_differences["signal_groups"] = {
                    "documented": normalized_signal_groups,
                    "receipt": receipt_signal_groups,
                }
                errors.append("signal_groups does not match the referenced WaveInfo call")
            if documented_signal_groups != receipt_signal_groups:
                field_differences["signal_groups"] = {
                    "documented": documented_signal_groups,
                    "receipt": receipt_signal_groups,
                }
                errors.append("documented signal_groups do not match the referenced WaveInfo call")
            if result_signal_groups != receipt_signal_groups:
                field_differences["signal_groups_result"] = {
                    "receipt_arguments": receipt_signal_groups,
                    "receipt_result": result_signal_groups,
                }
                errors.append(
                    "the signed WaveInfo result does not contain the declared signal_groups"
                )
        pattern = data.get("pattern")
        if not isinstance(pattern, list) or not pattern:
            errors.append("'pattern' must be a non-empty structured WaveInfo pattern list")
        else:
            try:
                normalized_pattern = waveform_tool.normalize_analysis_arguments(
                    test_case_name=receipt_args.get("test_case_name"),
                    pattern=pattern,
                )["pattern"]
            except Exception as error:
                normalized_pattern = None
                errors.append(f"pattern is invalid: {error}")
            if normalized_pattern != receipt_args.get("pattern"):
                field_differences["pattern"] = {
                    "documented": normalized_pattern,
                    "receipt": receipt_args.get("pattern"),
                }
                errors.append("pattern does not match the referenced WaveInfo call")
        if data.get("timeline_truncated") is not False:
            errors.append("timeline_truncated must be false")
        for key in _WAVEFORM_LLM_ANALYSIS_FIELDS:
            value = data.get(key)
            if not _is_nonempty_string(value) or _BUG_TODO_MARKER in value:
                error = f"'{key}' must be a completed non-empty string"
                errors.append(error)
                semantic_field_repairs[error] = {
                    "field": key,
                    "observed": value,
                    "required": (
                        "A completed conclusion grounded in this record's signed receipt "
                        "and timeline, the associated failing test, and the specification."
                    ),
                }

        signal_group_mapping = (
            documented_signal_groups
            if isinstance(documented_signal_groups, dict)
            else {}
        )
        documented_signal_set = {
            signal
            for field_name in _WAVEFORM_SIGNAL_GROUP_FIELDS
            for signal in signal_group_mapping.get(field_name, [])
            if isinstance(signal, str) and signal
        }
        bug_evidence = data.get("bug_evidence")
        for associated_bug in item["bugs"]:
            fields = (
                bug_evidence.get(associated_bug)
                if isinstance(bug_evidence, dict)
                else None
            )
            if not isinstance(fields, dict):
                errors.append(
                    f"bug_evidence.{associated_bug} must be a mapping"
                )
                continue
            required_signals = fields.get("required_signals")
            if (
                not isinstance(required_signals, list)
                or not required_signals
                or not all(
                    isinstance(signal, str) and bool(signal.strip())
                    for signal in required_signals
                )
                or len(required_signals) != len(set(required_signals))
            ):
                errors.append(
                    f"bug_evidence.{associated_bug}.required_signals must be a non-empty "
                    "list of unique exact signal paths"
                )
            else:
                missing_signals = sorted(set(required_signals) - documented_signal_set)
                if missing_signals:
                    errors.append(
                        f"bug_evidence.{associated_bug}.required_signals are absent from the "
                        f"signed signal_groups: {missing_signals}"
                    )
            for field_name in _WAVEFORM_BUG_ANALYSIS_FIELDS[1:]:
                value = fields.get(field_name)
                if not _is_nonempty_string(value) or _BUG_TODO_MARKER in value:
                    field = f"bug_evidence.{associated_bug}.{field_name}"
                    error = f"{field} must be a completed non-empty string"
                    errors.append(error)
                    semantic_field_repairs[error] = {
                        "field": field,
                        "observed": value,
                        "required": (
                            "A completed Bug-specific conclusion grounded in this record's "
                            "signed receipt and timeline, the associated failing test, the "
                            "specification, and the relevant source when available."
                        ),
                    }

        mode = data.get("analysis_mode")
        if mode == "clock_aligned":
            argument_fields = (
                "logged_cycle",
                "cycle_tolerance",
                "clock_signal",
                "clock_edge",
                "cycle_origin",
                "context_steps",
                "max_points",
            )
            for key in argument_fields:
                compare_receipt_value(
                    key,
                    receipt_args.get(key),
                    f"'{key}' does not match the referenced WaveInfo call",
                )
            if not _is_int(data.get("logged_cycle"), minimum=0):
                errors.append("logged_cycle must be a non-negative integer")
            if not _is_int(data.get("cycle_tolerance"), minimum=0, maximum=100):
                errors.append("cycle_tolerance must be an integer from 0 to 100")
            if not _is_nonempty_string(data.get("clock_signal")):
                errors.append("clock_signal must be a non-empty exact signal path")
            if data.get("clock_edge") not in {"rising", "falling"}:
                errors.append("clock_edge must be rising or falling")
            expected_candidate = {
                key: data.get(key)
                for key in ("clock_occurrence_index", "cycle_delta", "wave_step")
            }
            receipt_candidate = (
                (receipt_result.get("cycle_alignment") or {}).get("selected_candidate") or {}
            )
            for key, value in expected_candidate.items():
                if not _is_int(value, minimum=0 if key != "cycle_delta" else None):
                    errors.append(f"'{key}' must be an integer")
                if value != receipt_candidate.get(key):
                    field_differences[key] = {
                        "documented": value,
                        "receipt": receipt_candidate.get(key),
                    }
                    errors.append(
                        f"'{key}' does not match the WaveInfo receipt candidate "
                        f"(documented={value!r}; receipt={receipt_candidate.get(key)!r})"
                    )
            if receipt_result.get("status") != "candidate_selected":
                errors.append("the receipt did not select a unique clock-aligned candidate")
        elif mode == "explicit_window":
            argument_fields = (
                "start_step",
                "end_step",
                "context_steps",
                "max_points",
            )
            for key in argument_fields:
                compare_receipt_value(
                    key,
                    receipt_args.get(key),
                    f"'{key}' does not match the referenced WaveInfo call",
                )
            evidence_step = data.get("wave_step")
            if not _is_int(data.get("start_step"), minimum=0):
                errors.append("start_step must be a non-negative integer")
            if not _is_int(data.get("end_step"), minimum=0):
                errors.append("end_step must be a non-negative integer")
            if not _is_int(evidence_step, minimum=0):
                errors.append("wave_step must be a non-negative integer")
            if evidence_step not in receipt_result.get("event_steps", []):
                field_differences["wave_step"] = {
                    "documented": evidence_step,
                    "receipt_event_steps": receipt_result.get("event_steps", []),
                }
                errors.append("wave_step is not a triggered event in the WaveInfo receipt")
            if receipt_result.get("status") != "events_found":
                errors.append("the receipt did not find events in the explicit window")
        else:
            errors.append("analysis_mode must be clock_aligned or explicit_window")

        if errors:
            current_error = errors[0]
            current_field_differences = {
                key: value
                for key, value in field_differences.items()
                if key in current_error
            }
            details = {
                "bugs": item["bugs"],
                "test_case": item["test_case"],
                "line": line,
                "field_differences": current_field_differences,
            }
            issue = {
                "message": (
                    f"[Waveform Analysis Evidence Invalid] Block at line {line}: "
                    + current_error
                ),
                "details": details,
            }
            semantic_repair = semantic_field_repairs.get(current_error)
            if semantic_repair is not None:
                field = semantic_repair["field"]
                details.update(
                    {
                        "code": "WAVEFORM_SEMANTIC_FIELD_INCOMPLETE",
                        **semantic_repair,
                        "next_action": (
                            f"Edit only '{field}' in the central YAML record at line "
                            f"{line}, using that record's existing signed receipt/timeline "
                            "and the corresponding test, specification, and source evidence."
                        ),
                        "rerun_test": False,
                        "rerun_waveinfo": False,
                        "apply_evidence": False,
                    }
                )
                issue["repair_kind"] = "semantic_field"
            issues.append(issue)
            continue

        if not require_current_replay:
            continue

        replay_method = getattr(waveform_tool, "replay_analysis", None)
        if not callable(replay_method):
            replay_method = waveform_tool.analyze
        replay = replay_method(**receipt_args)
        update_call = {
            "tool": "ApplyWaveInfoEvidence",
            "arguments": {
                "target_file": bug_file,
                "bug_tag": item["bugs"][0],
                "test_case_tag": item["test_label"],
                "receipt_id": "",
                "replace_existing": True,
            },
        }
        if replay.get("success") is not True or replay.get("evidence_usable") is not True:
            replay_status = replay.get("status")
            if replay_status in _DEFERRED_WAVEFORM_REPLAY_STATUSES:
                replay_message = (
                    f"[Waveform Current Replay Required] The latest test session does not "
                    f"contain a current waveform for '{item['test_case']}' (status "
                    f"'{replay_status}'). The signed receipt and logical viewer link "
                    "remain valid signed evidence, but this final gate requires a fresh "
                    "all-tests run that emits every documented Bug waveform in one session."
                )
            else:
                replay_message = (
                    f"[Waveform Analysis No Longer Reproduces] Current WaveInfo replay for "
                    f"'{item['test_case']}' returned status '{replay_status}'. The "
                    "documented pattern is not valid evidence for the waveform generated "
                    "by this Check; call final WaveInfo again and use ApplyWaveInfoEvidence "
                    "to update the central record."
                )
            issues.append(
                {
                    "message": replay_message,
                    "details": {
                        "bugs": item["bugs"],
                        "test_case": item["test_case"],
                        "line": line,
                        "current_waveinfo": replay,
                        "update_call_after_final_waveinfo": update_call,
                    },
                }
            )
            continue
        current_viewer = replay.get("waveform_viewer")
        documented_replay_contract = _viewer_replay_contract(documented_viewer)
        current_replay_contract = _viewer_replay_contract(current_viewer)
        if current_replay_contract != documented_replay_contract:
            issues.append(
                {
                    "message": (
                        f"[Waveform Viewer Link Changed] Current WaveInfo replay for "
                        f"'{item['test_case']}' produced a different window, cursor, or "
                        "signal list than the link at line "
                        f"{block.get('viewer_line')}. Call final WaveInfo again and pass the "
                        "new receipt to ApplyWaveInfoEvidence."
                    ),
                    "details": {
                        "bugs": item["bugs"],
                        "test_case": item["test_case"],
                        "line": line,
                        "viewer_line": block.get("viewer_line"),
                        "documented_waveform_viewer": documented_viewer,
                        "current_waveform_viewer": current_viewer,
                        "documented_replay_contract": documented_replay_contract,
                        "current_replay_contract": current_replay_contract,
                        "update_call_after_final_waveinfo": update_call,
                    },
                }
            )
            continue
        if mode == "clock_aligned":
            current_candidate = (
                (replay.get("cycle_alignment") or {}).get("selected_candidate") or {}
            )
            candidate_errors = []
            candidate_differences = {}
            for key in ("clock_occurrence_index", "cycle_delta", "wave_step"):
                if current_candidate.get(key) != data.get(key):
                    candidate_errors.append(
                        f"[Waveform Candidate Changed] Current '{key}' is "
                        f"{current_candidate.get(key)}, documented value is {data.get(key)}."
                    )
                    candidate_differences[key] = {
                        "documented": data.get(key),
                        "current_waveinfo": current_candidate.get(key),
                    }
            if candidate_errors:
                issues.append(
                    {
                        "message": "; ".join(candidate_errors) + " Call WaveInfo again and update the analysis.",
                        "details": {
                            "bugs": item["bugs"],
                            "test_case": item["test_case"],
                            "line": line,
                            "field_differences": candidate_differences,
                            "current_waveinfo": replay,
                            "update_call_after_final_waveinfo": update_call,
                        },
                    }
                )
        else:
            current_event_steps = [
                int(step)
                for step, entry in replay.get("timeline", {}).items()
                if isinstance(entry, dict) and entry.get("triggers")
            ]
            if data.get("wave_step") not in current_event_steps:
                issues.append(
                    {
                        "message": (
                            f"[Waveform Event Changed] Documented wave_step {data.get('wave_step')} "
                            "is not a triggered event in the current waveform. Call WaveInfo "
                            "again and update the analysis."
                        ),
                        "details": {
                            "bugs": item["bugs"],
                            "test_case": item["test_case"],
                            "line": line,
                            "documented_wave_step": data.get("wave_step"),
                            "current_event_steps": current_event_steps,
                            "current_waveinfo": replay,
                            "update_call_after_final_waveinfo": update_call,
                        },
                    }
                )

    if issues:
        return _waveform_issue_result(issues)

    content_ok, content_message = check_dynamic_bug_analysis_content(
        workspace, bug_file
    )
    if not content_ok:
        return False, content_message

    message = (
        f"Validated {len(validation_items)} central WaveInfo record(s) for {len(required)} "
        "dynamic Bug/test association(s)."
    )
    if not require_current_replay:
        message += (
            " Current waveform replay is disabled for this stage; later waveform file "
            "changes do not invalidate the verified receipts."
        )
    return True, message


def _get_documented_dynamic_test_map(
    workspace: str,
    bug_file: str,
) -> tuple[bool, dict, object]:
    """Build a synthetic failed-test map for every documented dynamic Bug/TC pair."""

    path = os.path.join(workspace, bug_file)
    if not os.path.isfile(path):
        return False, {}, _missing_dynamic_bug_document_error(bug_file)
    ok, records, error = _parse_documented_dynamic_bug_records(
        workspace, bug_file
    )
    if not ok:
        return False, {}, error
    if not records:
        return True, {}, (
            "No documented non-zero-confidence dynamic Bugs require final waveform validation."
        )

    documented_test_map = {}
    missing_tests = [record["bug"] for record in records if not record["tests"]]
    if missing_tests:
        return False, {}, {
            "error": (
                f"[Waveform Analysis Test Missing] {len(missing_tests)} non-zero-confidence "
                "dynamic Bug(s) have no <TC-*> reproducer and therefore cannot have verified "
                f"waveform evidence: {fc.list_str_abbr(missing_tests)}."
            ),
            "details": {"bugs_without_test_cases": missing_tests},
        }
    for record in records:
        for test in record["tests"]:
            checkpoints = documented_test_map.setdefault(test["test_case"], [])
            if record["checkpoint"] not in checkpoints:
                checkpoints.append(record["checkpoint"])
    return True, documented_test_map, ""


def check_all_documented_waveform_bug_analysis(
    workspace: str,
    bug_file: str,
    waveform_tool=None,
    waveform_test_dir: str | None = None,
    require_current_replay: bool = False,
) -> tuple[bool, object]:
    """Validate analysis content and waveform evidence at a workflow boundary."""

    ok, documented_test_map, message = _get_documented_dynamic_test_map(
        workspace, bug_file
    )
    if not ok:
        return False, message
    if not documented_test_map:
        if os.path.isfile(os.path.join(workspace, bug_file)):
            structure_ok, _blocks, structure_error = _parse_waveform_analysis_blocks(
                workspace, bug_file
            )
            if not structure_ok:
                return False, structure_error
        content_ok, content_message = check_dynamic_bug_analysis_content(
            workspace, bug_file
        )
        if not content_ok:
            return False, content_message
        return True, message
    content_ok, content_message = check_dynamic_bug_analysis_content(
        workspace, bug_file
    )
    if not content_ok:
        return False, content_message
    return check_waveform_bug_analysis(
        workspace,
        bug_file,
        "",
        documented_test_map,
        waveform_tool=waveform_tool,
        waveform_test_dir=waveform_test_dir,
        require_all_documented=True,
        require_current_replay=require_current_replay,
    )


class UnityChipCheckerWaveformBugAnalysis(Checker):
    """Independent analysis-and-waveform gate for the dynamic Bug document."""

    def __init__(
        self,
        bug_file: str,
        test_dir: str,
        require_current_replay: bool = False,
        **kwargs,
    ):
        del kwargs
        if type(require_current_replay) is not bool:
            raise ValueError("require_current_replay must be a boolean")
        self.bug_file = bug_file
        self.test_dir = test_dir
        self.require_current_replay = require_current_replay

    def do_check(self, **kwargs) -> tuple[bool, object]:
        """Validate dynamic Bug analysis and active WaveInfo receipts."""
        del kwargs
        waveform_tool = None
        if self.stage_manager is not None:
            waveform_tool = self.get_tool_by_name("WaveInfo")
        passed, message = check_all_documented_waveform_bug_analysis(
            self.workspace,
            self.bug_file,
            waveform_tool=waveform_tool,
            waveform_test_dir=self.test_dir,
            require_current_replay=self.require_current_replay,
        )
        if passed:
            return True, {"success": message}
        return False, message


def get_bug_ck_list_from_doc(workspace: str, bug_analysis_file: str, target_ck_prefix:str):
    """Parse bug analysis documentation to extract marked bug analysis points."""
    try:
        marked_bugs = fc.get_unity_chip_doc_marks(os.path.join(workspace, bug_analysis_file), leaf_node="BG")
    except Exception as e:
        warning(traceback.format_exc())
        return False, [f"[Parse Error] Bug analysis document '{bug_analysis_file}' failed to parse: {str(e)}",
                        "[Required] Use the canonical FG/FC/CK/BG hierarchy, non-zero BG confidence, and closed dynamic/waveform containers.",
                        "[Next action] Repair the first malformed or missing tag reported above, then rerun Check. Use Guide_Doc/dut_bug_analysis.md section 5.1 as the exact reference.",
                        *fc.description_bug_doc(),
                        ]
    marked_bug_checks = []
    # bugs: FG/FC/CK/BG
    for c in marked_bugs:
        if not c.startswith(target_ck_prefix):
            continue
        labels = c.split("/")
        if not labels[-1].startswith("BG-"):
            return False, f"[Format Error] Bug analysis document '{bug_analysis_file}': mark '{c}' is missing 'BG-' prefix. " + \
                           "[Correct Format] <FG-GROUP>/<FC-FUNCTION>/<CK-CHECKPOINT>/<BG-BUGNAME-CONFIDENCE>. " + \
                           "[Example] <BG-OVERFLOW-80> means bug named OVERFLOW with 80% confidence. " + \
                           "Please fix according to Guide_Doc/dut_bug_analysis.md."
        try:
            _bug_name, confidence = parse_bug_label(labels[-1])
        except ValueError:
            return False, f"[Invalid Confidence] Bug analysis document '{bug_analysis_file}': '{labels[-1]}' has invalid confidence value. " + \
                           "[Requirement] Confidence must be an integer between 0 and 100. " + \
                           "[Example] <BG-ERROR-OVERFLOW-75> means bug ERROR-OVERFLOW with 75% confidence."
        if confidence > 0:
            marked_bug_checks.append("/".join(labels[:-1]))
    return True, marked_bug_checks


def get_doc_ck_list_from_doc(workspace: str, doc_file: str, target_ck_prefix:str):
    try:
        marked_checks = fc.get_unity_chip_doc_marks(os.path.join(workspace, doc_file), leaf_node="CK")
    except Exception as e:
        return False, [f"[Parse Error] Functions document '{doc_file}' failed to parse: {str(e)}",
                        "[Required] Use one canonical <FG-*> -> <FC-*> -> <CK-*> hierarchy with each tag on its own semantic heading line.",
                        "[Next action] Repair the first malformed hierarchy or tag reported above, then rerun Check. Use Guide_Doc/dut_functions_and_checks.md as the exact reference.",
                        *fc.description_func_doc(),
                        ]
    return True, [v for v in marked_checks if v.startswith(target_ck_prefix)]


def check_failed_checkpoint_reproducers(
    failed_checks: list,
    failed_tc_and_cks: dict,
    test_case_with_cks: dict,
    test_cases: dict,
    bug_file: str,
):
    """Require every failed checkpoint to be associated with a failed test."""

    failed_tc_and_cks = failed_tc_and_cks if isinstance(failed_tc_and_cks, dict) else {}
    test_case_with_cks = test_case_with_cks if isinstance(test_case_with_cks, dict) else {}
    test_cases = test_cases if isinstance(test_cases, dict) else {}
    reproduced_checkpoints = {
        checkpoint
        for test_case, checkpoints in failed_tc_and_cks.items()
        if test_cases.get(test_case) == "FAILED"
        if isinstance(checkpoints, list)
        for checkpoint in checkpoints
    }
    missing = list(dict.fromkeys(
        checkpoint
        for checkpoint in failed_checks
        if checkpoint not in reproduced_checkpoints
    ))
    if not missing:
        return True, ""

    association_details = []
    for checkpoint in missing:
        associated_tests = []
        for test_case, checkpoints in test_case_with_cks.items():
            if not isinstance(checkpoints, list) or checkpoint not in checkpoints:
                continue
            associated_tests.append({
                "test_case": test_case,
                "status": test_cases.get(test_case, "UNKNOWN"),
            })
        association_details.append({
            "checkpoint": checkpoint,
            "associated_tests": associated_tests,
        })

    return False, {
        "error": (
            f"[Failed Checkpoint Reproducer Missing] {len(missing)} failed checkpoint(s) "
            "have no FAILED test associated with the same exact checkpoint: "
            f"{fc.list_str_abbr(missing)}."
        ),
        "details": {
            "failed_checkpoints_without_failed_test": association_details,
        },
        "required": (
            "Every remaining failed checkpoint must have at least one correctly implemented "
            "FAILED test that the current report associates with that exact FG/FC/CK path. "
            f"That same CK/BG/TC relation must be recorded in '{bug_file}'."
        ),
        "next_action": [
            "For a targeted test, derive an independent expected value from the specification, an independent reference model, or a verifiable formula. Compare exact input, specification expected, test expected, and DUT actual. If the expected values differ, fix the test and rerun; do not record a Bug.",
            "If expected values agree, validate the stimulus/driver, API callbacks and Step ordering, valid sampling condition and latency, fixture/reference model/reset/environment, then this checkpoint's coverage/check predicate, CovGroup.sample call, and sample timing. Fix the identified verification error and rerun. If the checkpoint was merely uncovered, add correct targeted stimulus; do not add an unrelated test or manufacture a failure.",
            "Do not modify a currently PASSED associated test solely to make it fail for this gate. If the CK predicate, coverage association, sample timing, or stimulus is wrong, repair that verification logic. A correct repair may make the CK pass; in that case no FAILED reproducer is required for that CK. Only when the CK contract is valid and the DUT actually violates it should a correct test naturally fail.",
            "After any stimulus transformation such as complementing, encoding, masking, packetizing, or adding a carry/borrow input, compute specification_expected from the actual driven values and the documented operation. Do not compare transformed inputs against an expected value derived from the untransformed operands.",
            "Only if all verification is correct and DUT actual still violates the specification, keep the strong reproducer assertion naturally failing, rerun until the report associates that FAILED test with this exact checkpoint, then obtain confirmed WaveInfo evidence and add the non-zero BG/TC record.",
        ],
    }


def check_bug_tc_analysis(
    workspace: str,
    checks_in_tc: list,
    bug_file: str,
    target_ck_prefix: str,
    failed_tc_and_cks: dict,
    passed_tc_list: list,
    only_marked_ckp_in_tc: bool,
    test_output_dir: str = "",
):
    try:
        all_tc_list = fc.get_unity_chip_doc_marks(
            os.path.join(workspace, bug_file), leaf_node="TC"
        )
        tc_list = [tc for tc in all_tc_list if tc.startswith(target_ck_prefix)]
    except Exception as e:
        warning(traceback.format_exc())
        return False, [f"[Parse Error] Bug analysis document '{bug_file}' failed to parse: {str(e)}",
                        "[Required] Use the canonical FG/FC/CK/BG/TC hierarchy, exact test node IDs, and valid BG confidence.",
                        "[Next action] Repair the first malformed or missing tag reported above, then rerun Check. Use Guide_Doc/dut_bug_analysis.md section 5.1 as the exact reference.",
                        *fc.description_bug_doc(),
                        ]
    failed_tc_names = failed_tc_and_cks.keys()
    failed_tc_maps = {k:False for k in failed_tc_names}
    for tc in all_tc_list:
        checkpoint = tc.split("/BG-", 1)[0]
        bug_label = tc.split("/TC-", 1)[0].split("/")[-1]
        try:
            _bug_name, confidence = parse_bug_label(bug_label)
        except ValueError:
            continue
        if confidence <= 0:
            continue
        tc_name_parts = tc.split("/TC-", 1)[-1].split("::")
        is_fail_tc, fail_tc_name = _find_matching_test_case(
            tc_name_parts, failed_tc_names
        )
        if is_fail_tc and checkpoint in failed_tc_and_cks[fail_tc_name]:
            failed_tc_maps[fail_tc_name] = True
    # fmt: FG/FC/CK/BG/TC-path/to/test_file.py::[ClassName]::test_case_name
    ck_not_found_in_report = []
    tc_not_found_in_ftc_list = []
    tc_not_mark_the_cks_list = []
    tc_found_in_ptc_list = []
    configured_test_dir = ""
    if test_output_dir:
        configured_test_dir = str(test_output_dir).replace("\\", "/").rstrip("/")
        if os.path.isabs(configured_test_dir):
            configured_test_dir = os.path.relpath(
                configured_test_dir, workspace
            ).replace("\\", "/")
    for tc in tc_list:
        checkpoint = tc.split("/BG-")[0]
        bug_label = tc.split("/TC-")[0]
        tc_name = tc.split("/TC-")[-1]
        tc_name_parts = tc_name.split("::")
        tc_name = "<TC-" + tc_name + ">"
        info(f"Check TC: {tc} ({tc_name}) for bug analysis")
        if checkpoint not in checks_in_tc:
            ck_not_found_in_report.append(checkpoint)
            continue
         # parse bug rate
        try:
            bug_rate = int(bug_label.split("-")[-1])
        except Exception as e:
            return False, f"[Confidence Parse Error] '{bug_label}' failed to parse ({str(e)}). [Correct Format] <BG-NAME-XX> where XX is a confidence integer from 0 to 100. Example: <BG-OVERFLOW-80> means 80% confidence."
        if len(tc_name_parts) < 2:
            return False, f"[Test Case Format Error] '{tc_name}' has incorrect format. [Correct Format] <TC-test_file.py::[ClassName::]test_case_name> where ClassName is optional. Example: <TC-test_add.py::test_overflow> or <TC-test_add.py::TestAdd::test_overflow>."
        is_zero_bug = (bug_rate == 0)
        has_configured_prefix = not configured_test_dir or tc_name_parts[0].startswith(
            configured_test_dir + "/"
        )
        is_fail_tc, fail_tc_name = (
            _find_matching_test_case(tc_name_parts, failed_tc_names)
            if has_configured_prefix
            else (False, "")
        )
        # failed tc
        if is_fail_tc:
            if not is_zero_bug and checkpoint not in failed_tc_and_cks[fail_tc_name]:
                tc_not_mark_the_cks_list.append((fail_tc_name, checkpoint))
        else:
            if not is_zero_bug:
                tc_not_found_in_ftc_list.append(
                    (
                        tc_name,
                        bug_label,
                        tuple(
                            _similar_report_test_cases(
                                "::".join(tc_name_parts),
                                failed_tc_names,
                            )
                        ),
                        checkpoint,
                    )
                )
        # passed tc
        is_pass_tc, pass_tc_name = (
            _find_matching_test_case(tc_name_parts, passed_tc_list)
            if has_configured_prefix
            else (False, "")
        )
        if is_pass_tc and not is_fail_tc and not is_zero_bug:
            tc_found_in_ptc_list.append((tc_name, pass_tc_name))

    if len(ck_not_found_in_report) > 0:
        msg = fc.list_str_abbr(ck_not_found_in_report)
        return False, f"[Checkpoint Not Found] Bug analysis document '{bug_file}' references {len(ck_not_found_in_report)} checkpoint(s) ({msg}) that do not exist in the test report. " + \
                       "[Solution] Ensure the <FG-*>, <FC-*>, <CK-*> tags in the bug analysis document exactly match those in the functional coverage definition (case-sensitive). See Guide_Doc/dut_bug_analysis.md."

    # tc in pass tc
    tc_found_in_ptc_list = list(set(tc_found_in_ptc_list))
    if len(tc_found_in_ptc_list) > 0:
        ptc_msg = fc.list_str_abbr([f"{x[0]}(actual: {x[1]})" for x in tc_found_in_ptc_list])
        return False, [f"[Test Case Status Mismatch] Bug analysis document '{bug_file}' contains {len(tc_found_in_ptc_list)} test case(s) ({ptc_msg}) expected to be FAILED but actually PASSED.",
                       "[Observed] The current report classifies the listed tests as PASSED, so they cannot serve as dynamic DUT Bug reproducers.",
                       "[Required] Every <TC-*> under a non-zero BG must be a correctly implemented current FAILED test associated with the same checkpoint.",
                       "[Next action] Remove the stale BG/TC association if the test no longer reproduces the Bug. If the tag names the wrong test, replace it with the exact current failing pytest node ID. If a confirmed DUT defect should still reproduce, restore only the correct strong assertion and rerun; never manufacture a Fail or use BG-*-0."
                       ]
    # tc not found in fail tcs
    tc_not_found_in_ftc_list = list(dict.fromkeys(tc_not_found_in_ftc_list))
    if tc_not_found_in_ftc_list:
        documented_tc, bug_path, similar_nodes, checkpoint = tc_not_found_in_ftc_list[0]
        similar_hint = (
            fc.list_str_abbr(list(similar_nodes)) if similar_nodes else "None"
        )
        configured_requirement = (
            f"confirm that its file path begins with '{configured_test_dir}/' from "
            "agent.cfg, "
            if configured_test_dir
            else ""
        )
        return False, [
            (
                f"[Test Case Node ID Mismatch] '{bug_file}' uses {documented_tc} under "
                f"'{bug_path}', but that exact node ID is not a current FAILED report node. "
                f"Fix this first mismatch before the remaining "
                f"{len(tc_not_found_in_ftc_list) - 1} mismatch(es)."
            ),
            (
                f"[Configured TC output directory] {configured_test_dir}. This resolved "
                "agent.cfg value is the required file-path prefix for every TC in this "
                "stage."
                if configured_test_dir
                else "[Configured TC output directory] Unavailable in this direct checker call."
            ),
            f"[Checkpoint] {checkpoint}",
            (
                "[Similar current FAILED report node IDs] "
                f"{similar_hint}. Similar nodes are lookup hints only; they are not "
                "equivalent identities and are never matched automatically."
            ),
            (
                "[Required] Copy the intended pytest node ID verbatim from the current "
                "RunTestCases/Check/Complete report, "
                f"{configured_requirement}remove only the file ':start-end' "
                "or ':line' range, and add the 'TC-' prefix. Do not add, remove, or rewrite "
                "the configured directory prefix."
            ),
            (
                "[Next action] If one similar node is the intended test, replace this stale "
                "BG/TC identity with that exact report node ID, obtain a new WaveInfo receipt "
                "using the same exact node ID, and use ApplyWaveInfoEvidence to rebuild its "
                "central evidence. Do not hand-edit signed receipt/viewer fields and do not "
                "call Check/Complete again until this identity is corrected. If no candidate "
                "is the intended test, restore the missing failing test or remove the stale "
                "BG/TC association."
            ),
        ]
    # tc not mark their checkpoints
    tc_not_mark_the_cks_list = list(set(tc_not_mark_the_cks_list))
    if len(tc_not_mark_the_cks_list) > 0:
        ftc_msg = fc.list_str_abbr([
            f"{test_case}(expected checkpoint relation: {checkpoint})"
            for test_case, checkpoint in tc_not_mark_the_cks_list
        ])
        return False, [f"[Bug Checkpoint Association Missing] Bug analysis document '{bug_file}' contains {len(tc_not_mark_the_cks_list)} test case(s) ({ftc_msg}) that the Toffee report does not associate with the documented checkpoint.",
                       "[Observed] The report relation is missing. This does not by itself prove that the source lacks a mark_function call.",
                       "[Required] The failed-test report and Bug document must associate the TC with the same exact FG/FC/CK path.",
                       "[Next action] Move the TC under its actual report checkpoint if the document path is wrong. Otherwise inspect the existing mark_function arguments, execution path, non-empty CK list, and fixture coverage objects; add a mark_function call only when none exists, then rerun Check. Remove the BG/TC association if the test is unrelated to this checkpoint."
                       ]
    # fail tc not in bug doc
    failed_tc = [k for k, v in failed_tc_maps.items() if not v]
    if failed_tc:
        first_failed = failed_tc[0]
        associated_checkpoints = failed_tc_and_cks.get(first_failed, [])
        return False, [
            (
                f"[Unresolved Failed Cases] Found {len(failed_tc)} current FAILED test "
                "case(s) without a matching non-zero dynamic Bug record. First unresolved "
                f"node: {first_failed}."
            ),
            f"[Report-associated checkpoints] {fc.list_str_abbr(associated_checkpoints)}",
            (
                "[Next action 1] Classify this first test only: derive an independent "
                "expected value from the specification and compare exact input, specification "
                "expected, test expected, and DUT actual. Fix and rerun the test if its "
                "expected value is wrong."
            ),
            (
                "[Next action 2] If expected values agree, verify stimulus/driver, API and "
                "Step ordering, sampling condition and latency, fixture/reference model/reset/"
                "environment, and the associated checkpoint coverage/check predicate and "
                "sample timing. Fix any "
                "verification error and rerun until Pass."
            ),
            (
                "[Next action 3] Only if all verification is correct and the DUT still violates "
                "the specification, keep the strong assertion naturally failing, obtain "
                "confirmed WaveInfo evidence, and record the exact CK/BG/TC and ROOT relation "
                "using Guide_Doc/dut_bug_analysis.md section 5.1. A <BG-*-0> placeholder does "
                "not classify a failed test."
            ),
        ]
    return True, ""

def check_bug_ck_analysis(workspace:str, bug_analysis_file:str, failed_check: list,
                          check_fail_ck_in_bug=True, target_ck_prefix:str ="",
                          failed_tc_and_cks=None):
    """Check failed checkpoint in bug analysis documentation."""

    ret, marked_bug_checks = get_bug_ck_list_from_doc(workspace, bug_analysis_file, target_ck_prefix)
    if not ret:
        return False, marked_bug_checks, -1

    if check_fail_ck_in_bug:
        un_related_tc_marks = [
            ck for ck in failed_check if ck not in marked_bug_checks
        ]
        # failed checkpoints must be analyzed in bug doc
        if un_related_tc_marks:
            return False, [
                f"[Unanalyzed Failed Checkpoints] {len(un_related_tc_marks)} failed checkpoint(s) have no non-zero-confidence DUT Bug record in '{bug_analysis_file}': {fc.list_str_abbr(un_related_tc_marks)}.",
                "[Observed] The current report marks these checkpoints as failed, but the Bug document has no non-zero BG under the exact checkpoint paths.",
                "[Required] Every remaining failed checkpoint must be documented under its exact FG/FC/CK path and must retain at least one report-associated FAILED TC.",
                "[Next action 1] Use a targeted test to derive an independent expected value from the specification, an independent reference model, or a verifiable formula; compare exact input, specification expected, test expected, and DUT actual. Correct an inconsistent test expected and rerun.",
                "[Next action 2] Validate the stimulus/driver, API callbacks and Step ordering, valid sampling condition and latency, fixture/reference model/reset/environment, then the CK coverage/check predicate, CovGroup.sample call, and sample timing. Fix the identified verification error or add correct stimulus for an uncovered CK, then rerun.",
                "[Next action 3] Only if all verification is correct and DUT actual still violates the specification, keep the strict check and reproducer naturally failing, obtain confirmed WaveInfo evidence, and add the exact FG/FC/CK/BG/TC relation.",
                *fc.description_bug_doc(),
                "Never use 'lambda x: True', assert False, a weakened check, an unrelated TC, or <BG-*-0> to force a classification result.",
            ], -1

        if failed_tc_and_cks is not None:
            failed_tc_and_cks = (
                failed_tc_and_cks
                if isinstance(failed_tc_and_cks, dict)
                else {}
            )
            documented_reproducers = set()
            failed_test_names = failed_tc_and_cks.keys()
            parsed, records, parse_error = _parse_documented_dynamic_bug_records(
                workspace, bug_analysis_file
            )
            if not parsed:
                return False, parse_error, -1
            for record in records:
                checkpoint = record["checkpoint"]
                for documented_test in record["tests"]:
                    test_name_parts = documented_test["test_case"].split("::")
                    is_failed, failed_test = _find_matching_test_case(
                        test_name_parts, failed_test_names
                    )
                    if is_failed and checkpoint in failed_tc_and_cks[failed_test]:
                        documented_reproducers.add(checkpoint)

            missing_documented_reproducers = [
                checkpoint
                for checkpoint in failed_check
                if checkpoint not in documented_reproducers
            ]
            if missing_documented_reproducers:
                details = [
                    {
                        "checkpoint": checkpoint,
                        "report_failed_tests": [
                            test_case
                            for test_case, checkpoints in failed_tc_and_cks.items()
                            if isinstance(checkpoints, list) and checkpoint in checkpoints
                        ],
                    }
                    for checkpoint in missing_documented_reproducers
                ]
                return False, {
                    "error": (
                        f"[Failed Checkpoint Bug Relation Missing] "
                        f"{len(missing_documented_reproducers)} failed checkpoint(s) "
                        "have no non-zero BG/FAILED TC relation under the same exact "
                        f"checkpoint in '{bug_analysis_file}': "
                        f"{fc.list_str_abbr(missing_documented_reproducers)}."
                    ),
                    "details": {"missing_checkpoint_relations": details},
                    "required": (
                        "For every remaining failed checkpoint, the Bug document must place "
                        "at least one current report-associated FAILED TC under a non-zero BG "
                        "within that exact FG/FC/CK branch."
                    ),
                    "next_action": [
                        "CK failure alone does not prove a DUT Bug. For a targeted listed test, derive an independent expected value from the specification, an independent reference model, or a verifiable formula; compare exact input, specification expected, test expected, and DUT actual. Fix an inconsistent test expected and rerun.",
                        "If expected values agree, validate the stimulus/driver, API callbacks and Step ordering, valid sampling condition and latency, fixture/reference model/reset/environment, then this CK's coverage/check predicate, CovGroup.sample call, and sample timing. Fix the identified verification error and rerun.",
                        "Only if all verification is correct and DUT actual still violates the specification, place the naturally failing report-associated TC under the non-zero BG in this exact CK branch and complete confirmed WaveInfo evidence; do not add an unrelated or artificial failure.",
                    ],
                }, -1

    return True, f"Bug analysis documentation '{bug_analysis_file}' is consistent with test results.", len(marked_bug_checks)


def check_doc_struct(test_case_checks:list, doc_checks:list, doc_file:str, check_tc_in_doc=True, check_doc_in_tc=True):
    if check_tc_in_doc:
        ck_not_in_doc = []
        for ck in test_case_checks:
            if ck not in doc_checks:
                ck_not_in_doc.append(ck)
        if len(ck_not_in_doc) > 0:
            return False, [f"[Documentation Inconsistency] Test code contains {len(ck_not_in_doc)} checkpoint(s) not defined in the document: {fc.list_str_abbr(ck_not_in_doc)}. " +
                            f"These checkpoints are used in tests but not defined in '{doc_file}'.",
                            "[Solution]",
                            "1. Add the missing checkpoints to the document (using <CK-*> tags)",
                            "2. Or remove the extra checkpoints from the functional coverage group in test code",
                            "3. Ensure checkpoints are fully consistent between test code and documentation (see Guide_Doc/dut_functions_and_checks.md)"]
    if check_doc_in_tc:
        ck_not_in_tc = []
        for ck in doc_checks:
            if ck not in test_case_checks:
                ck_not_in_tc.append(ck)
        if len(ck_not_in_tc) > 0:
            info(f"Check points in test function: {fc.list_str_abbr(test_case_checks)}")
            return False, [f"[Test Coverage Gap] Document ({doc_file}) defines {len(ck_not_in_tc)} checkpoint(s) not defined in the test coverage group: {fc.list_str_abbr(ck_not_in_tc)}",
                            "These checkpoints are defined in the document but lack test implementation.",
                            "[Solution]",
                            "1. Define these checkpoints in the functional coverage group (see Guide_Doc/dut_function_coverage_def.md)",
                            "2. Or remove outdated checkpoints from the document",
                            "3. Ensure checkpoints remain consistent between test code and documentation"]

    return True, f"Function/check points documentation ({doc_file}) is consistent with test cases."


def check_report(workspace, report, doc_file, bug_file, target_ck_prefix="",
                 check_tc_in_doc=True, check_doc_in_tc=True, post_checker=None, only_marked_ckp_in_tc=False,
                 check_fail_ck_in_bug=True, func_RunTestCases=None, timeout_RunTestCases=0,
                 waveform_tool=None, waveform_test_dir=None, test_output_dir=None):
    """Check the test report against documentation and bug analysis.

    Args:
        workspace: The workspace directory.
        report: The test report to check.
        doc_file: The documentation file to check against.
        bug_file: The bug analysis file to check against.
        target_ck_prefix: The target check point prefix to filter checks.
        check_tc_in_doc: Whether to check test cases in documentation.
        check_doc_in_tc: Whether to check documentation in test cases.
        post_checker: An optional post-checker function.
        only_marked_ckp_in_tc: Whether to only consider marked check points in test cases (enable this in batch testing mode).
        check_fail_ck_in_bug: Whether to check failed check points in bug analysis document.
        func_RunTestCases: Retained for caller compatibility; no diagnostic rerun is performed.
        timeout_RunTestCases: Retained for caller compatibility; no diagnostic rerun is performed.
        waveform_tool: The active WaveInfo tool instance used to verify in-memory call receipts.
        waveform_test_dir: Test directory searched by WaveInfo for the newest waveform session.
        test_output_dir: Resolved agent.cfg TC output directory shown in diagnostics.
    Returns:
        A tuple indicating the success or failure of the check, along with an optional message.
    """

    ret, doc_ck_list = get_doc_ck_list_from_doc(workspace, doc_file, target_ck_prefix)
    if not ret:
        return ret, doc_ck_list, -1
    missing_coverage_message = fc.get_missing_functional_coverage_message(report)
    if missing_coverage_message:
        return False, missing_coverage_message, -1
    if report.get("test_function_with_no_check_point_mark", 0) > 0:
        unmarked_functions = report.get('test_function_with_no_check_point_mark_list', [])
        mark_function_desc = fc.description_mark_function_doc(unmarked_functions, workspace)
        return False, f"[Test Association Missing] Toffee recorded {report['test_function_with_no_check_point_mark']} executed test function(s) without any checkpoint association. " + \
                       mark_function_desc, -1

    checks_in_tc  = [b for b in report.get("all_check_point_list", []) if b.startswith(target_ck_prefix)]
    if len(checks_in_tc) == 0:
        warning(f"No test functions found for check point prefix '{target_ck_prefix}'. Please ensure test cases are correctly marked with this prefix.")
        warning(f"Current test check points: {fc.list_str_abbr(report.get('bins_all', []))}")
    ret, msg = check_doc_struct(checks_in_tc, doc_ck_list, doc_file, check_tc_in_doc=check_tc_in_doc, check_doc_in_tc=check_doc_in_tc)
    if not ret:
        return ret, msg, -1

    failed_checks_in_tc = [b for b in report.get("failed_check_point_list", []) if b.startswith(target_ck_prefix)]
    marked_checks_in_tc = [c for c in checks_in_tc if c not in report.get("unmarked_check_point_list", [])]
    if only_marked_ckp_in_tc:
        failed_checks_in_tc = [b for b in failed_checks_in_tc if b in marked_checks_in_tc]

    failed_funcs_bins = report.get("failed_test_case_with_check_point_list", {})
    test_cases = report.get("tests", {}).get("test_cases", None)
    if not isinstance(test_cases, dict):
        return False, [
            "[Test Report Structure Error] The current report has no valid tests.test_cases mapping.",
            f"[Observed] tests.test_cases has type {type(test_cases).__name__}; Check/Complete cannot classify test status or validate CK/BG/TC relations.",
            "[Required] The test run must collect the intended test_*.py modules and return a tests.test_cases status mapping.",
            "[Next action] Read the current pytest STDOUT/STDERR, fix the first collection/import/timeout error or test naming problem, rerun the intended tests, then call Check/Complete again.",
        ], -1
    if not isinstance(failed_funcs_bins, dict):
        return False, {
            "error": (
                "[Test Report Structure Error] "
                "failed_test_case_with_check_point_list must be a mapping."
            ),
            "observed": type(failed_funcs_bins).__name__,
            "required": (
                "The report must map each FAILED pytest node ID to the exact FG/FC/CK "
                "paths associated with that test."
            ),
            "next_action": (
                "Rerun the intended tests to regenerate the Toffee report, then call "
                "Check/Complete again."
            ),
        }, -1

    failed_status_tests = {
        test_case for test_case, status in test_cases.items() if status == "FAILED"
    }
    relation_status_mismatches = [
        {
            "test_case": test_case,
            "status": test_cases.get(test_case, "UNKNOWN"),
            "checkpoints": checkpoints,
        }
        for test_case, checkpoints in failed_funcs_bins.items()
        if test_case not in failed_status_tests
    ]
    failed_tests_without_relations = [
        test_case
        for test_case in failed_status_tests
        if not isinstance(failed_funcs_bins.get(test_case), list)
        or not failed_funcs_bins[test_case]
    ]
    if relation_status_mismatches or failed_tests_without_relations:
        return False, {
            "error": (
                "[Test Report Relation Inconsistent] tests.test_cases statuses and "
                "failed-test checkpoint relations disagree."
            ),
            "details": {
                "non_failed_tests_in_failed_relations": relation_status_mismatches,
                "failed_tests_without_checkpoint_relations": (
                    failed_tests_without_relations
                ),
            },
            "required": (
                "Every tests.test_cases entry with status FAILED must have a non-empty "
                "failed_test_case_with_check_point_list relation, and every key in that "
                "relation mapping must have status FAILED."
            ),
            "next_action": (
                "Treat this as stale or invalid test-report evidence. Rerun the intended "
                "tests and regenerate functional coverage before editing the Bug document."
            ),
        }, -1
    passed_tc_list = [k for k,v in test_cases.items() if v == "PASSED"]

    bug_ck_list_size = -1
    if len(failed_checks_in_tc) > 0 or os.path.exists(os.path.join(workspace, bug_file)) or failed_funcs_bins:
        if check_fail_ck_in_bug:
            ret, msg = check_failed_checkpoint_reproducers(
                failed_checks_in_tc,
                failed_funcs_bins,
                report.get("test_case_with_check_point_list", {}),
                test_cases,
                bug_file,
            )
            if not ret:
                return ret, msg, -1

        ret, msg, bug_ck_list_size = check_bug_ck_analysis(
            workspace,
            bug_file,
            failed_checks_in_tc,
            check_fail_ck_in_bug=check_fail_ck_in_bug,
            target_ck_prefix=target_ck_prefix,
            failed_tc_and_cks=failed_funcs_bins,
        )
        if not ret:
            return ret, msg, -1

        ret, msg = check_bug_tc_analysis(
            workspace,
            checks_in_tc,
            bug_file,
            target_ck_prefix,
            failed_funcs_bins,
            passed_tc_list,
            only_marked_ckp_in_tc,
            test_output_dir=test_output_dir or "",
        )
        if not ret:
            return ret, msg, -1

        ret, msg = check_waveform_bug_analysis(
            workspace,
            bug_file,
            target_ck_prefix,
            failed_funcs_bins,
            waveform_tool=waveform_tool,
            waveform_test_dir=waveform_test_dir,
            require_current_replay=False,
        )
        if not ret:
            return ret, msg, -1

    if report.get('unmarked_check_points', 0) > 0 and not only_marked_ckp_in_tc:
        unmark_check_points = [
            ck for ck in report.get('unmarked_check_point_list', [])
            if ck.startswith(target_ck_prefix)
        ]
        if len(unmark_check_points) > 0:
            return False, fc.description_checkpoint_association_missing(
                unmark_check_points
            ), -1

    if callable(post_checker):
        ret, msg = post_checker(report)
        if not ret:
            return ret, msg, -1

    return True, (
        "Test-result classification is consistent: every non-DUT-Bug case passed, and "
        "every remaining failed case is a documented DUT Bug reproducer."
    ), bug_ck_list_size



def check_line_coverage(workspace, file_cover_json, file_ignore, file_analyze_md, min_line_coverage, post_checker=None):
    """Check the line coverage report against analysis documentation.

    Args:
        workspace: The workspace directory.
        file_cover_json: The line coverage JSON file.
        file_ignore: The line coverage ignore file.
        file_analyze_md: The line coverage analysis documentation file.
        min_line_coverage: The minimum acceptable line coverage percentage.
        post_checker: An optional post-checker function.

    Returns:
        A tuple indicating the success or failure of the check, along with an optional message and coverage rate.
    """
    if not os.path.exists(os.path.join(workspace, file_cover_json)):
        return False, f"[Line Coverage File Missing] Line coverage result file `{file_cover_json}` does not exist in workspace `{workspace}`. Please ensure coverage data has been generated correctly." , 0.0

    file_ignore_path = os.path.join(workspace, file_ignore)
    if file_ignore and os.path.exists(file_ignore_path):
        line_cov = fc.parse_line_ignore_file(file_ignore_path)
        igs = line_cov.get("marks", [])
        if len(igs) > 0:
            # check format
            clines = [(x["line"], x["value"]) for x in line_cov["detail"]]
            error_igs = []
            for line, ig in clines:
                if not ig.startswith("*/"):
                    error_igs.append((line, ig))
            if len(error_igs) > 0:
                emessage = fc.list_str_abbr([f"line {x[0]}: '{x[1]}'" for x in error_igs])
                return False, f"[Ignore Pattern Format Error] Line coverage ignore file ({file_ignore}) contains {len(error_igs)} invalid pattern(s) (must start with '*/'): `{emessage}`. " + \
                              "[Correct Format] '*/{DUT}/{DUT}.v:18-20,50-50' means ignoring lines 18-20 and line 50 of {DUT}.v. Please fix and retry.", \
                                0.0
            error_igs = []
            for line, ig in clines:
                if ":" in ig:
                    line_part = ig.split(":")[-1]
                    line_ranges = line_part.split(",")
                    for lr in line_ranges:
                        if "-" not in lr:
                            error_igs.append((line, ig))
                            break
            if len(error_igs) > 0:
                emessage = fc.list_str_abbr([f"line {x[0]}: '{x[1]}'" for x in error_igs])
                return False, f"[Ignore Line Number Format Error] Line coverage ignore file ({file_ignore}) contains {len(error_igs)} invalid pattern(s) (line number format error): `{emessage}`. " + \
                              "[Correct Format] Line numbers must be in 'start-end' format, e.g., '*/{DUT}/{DUT}.v:18-20,50-50'. Please fix and retry.", \
                                0.0
            file_analyze_md_path = os.path.join(workspace, file_analyze_md)
            if not os.path.exists(file_analyze_md_path):
                return False, f"[Analysis Document Missing] Line coverage analysis document ({file_analyze_md}) does not exist in workspace `{workspace}`. " + \
                              f"[Cause] Ignore file ({file_ignore}) contains patterns like `{fc.list_str_abbr(igs)}` that require an analysis document explaining the ignore reasons. " + \
                              f"[Solution] Create {file_analyze_md} and document each ignore pattern with <LINE_IGNORE>pattern</LINE_IGNORE> tags (see Guide_Doc/dut_line_coverage.md).", \
                                0.0
            doc_igs = fc.parse_marks_from_file(file_analyze_md_path, "LINE_IGNORE").get("marks", [])
            un_doced_igs = []
            for ig in igs:
                if ig not in doc_igs:
                    un_doced_igs.append(ig)
            if len(un_doced_igs) > 0:
                return False, f"[Undocumented Ignore Patterns] Line coverage analysis document ({file_analyze_md}) is missing the following LINE_IGNORE mark(s): `{fc.list_str_abbr(un_doced_igs)}`. " + \
                              f"[Solution] Add <LINE_IGNORE>pattern</LINE_IGNORE> tags in the analysis document to explain each ignore reason.", \
                                0.0

    cover_data = fc.parse_un_coverage_json(file_cover_json, workspace)  # just to check if the json is valid
    cover_rate = cover_data.get("coverage_rate", 0.0)
    if cover_rate < min_line_coverage:
        return False, {"error": [f"[Insufficient Line Coverage] Current line coverage {cover_rate*100.0:.2f}% is below the minimum threshold {min_line_coverage*100.0:.2f}%.",
                                  "[Steps to Improve Coverage]",
                                  "1. Review uncovered lines in the coverage report",
                                  "2. Identify missing test cases that would cover those lines, or enhance existing ones",
                                  "3. Implement additional test cases to cover uncovered lines",
                                  "4. If some lines do not need coverage (e.g., deprecated code, third-party libraries), " + \
                                      f"add ignore patterns in the ignore file ({file_ignore}) and document the reasons with <LINE_IGNORE> tags in the analysis document ({file_analyze_md})",
                                  "5. Re-run tests and coverage analysis to confirm the threshold is met",
                                  f"Note: Ignore pattern format is '*/{'{DUT}'}/{'{DUT}'}.v:18-20,50-60', meaning ignore lines 18-20 and 50-60 of that file (see Guide_Doc/dut_line_coverage.md)"
                                 ],
                       "uncoverage_info": cover_data
                       }, cover_rate

    if callable(post_checker):
        ret, msg = post_checker(cover_data)
        if not ret:
            return ret, msg, cover_rate

    return True, f"Line coverage check passed (line coverage: {cover_rate*100.0:.2f}% >= {min_line_coverage*100.0:.2f}%).", cover_rate
