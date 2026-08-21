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
    BUG_SOURCE_EVIDENCE_MARKERS as _BUG_SOURCE_EVIDENCE_MARKERS,
    BUG_SOURCE_UNAVAILABLE_MARKER as _BUG_SOURCE_UNAVAILABLE_MARKER,
    BUG_TODO_MARKER as _BUG_TODO_MARKER,
    DOCUMENT_TAG_PATTERN as _DOCUMENT_TAG_PATTERN,
    DYNAMIC_BUGS_END_MARKER as _DYNAMIC_BUGS_END_MARKER,
    DYNAMIC_BUGS_MARKER as _DYNAMIC_BUGS_MARKER,
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
    r"[\w./\\-]+\.(?:sv|svh|v|vh|vhd|vhdl|scala):\d+(?:-\d+)?",
    re.IGNORECASE,
)
_HDL_FENCED_BLOCK = re.compile(
    r"^[ \t]*```(?:systemverilog|verilog|vhdl|scala|chisel)[ \t]*\r?\n"
    r"(?P<body>.*?)^[ \t]*```[ \t]*$",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)


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
    for name in name_list:
        if all(part in name for part in parts):
            return True, name
    return False, ""


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

    hierarchy = {"FG": None, "FC": None, "CK": None}
    records = []
    current = None
    fence_open = False
    dynamic_container_lines = []
    first_bug_line = None
    in_dynamic_container = False

    def close_current(end_index: int):
        nonlocal current
        if current is None:
            return
        current["content"] = "\n".join(lines[current["start"] + 1 : end_index])
        records.append(current)
        current = None

    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            fence_open = not fence_open
            continue
        if fence_open:
            continue
        matches = list(_DOCUMENT_TAG_PATTERN.finditer(line))
        if first_bug_line is None and any(
            match.group(1) == "BG" for match in matches
        ):
            first_bug_line = index + 1
        if stripped == _DYNAMIC_BUGS_MARKER:
            dynamic_container_lines.append(index + 1)
            in_dynamic_container = True
            continue
        if stripped == _DYNAMIC_BUGS_END_MARKER:
            close_current(index)
            in_dynamic_container = False
            continue
        if not in_dynamic_container:
            continue
        if not matches:
            continue
        if current is not None and any(
            match.group(1) in {"FG", "FC", "CK", "BG"} for match in matches
        ):
            close_current(index)

        for match in matches:
            kind, value = match.groups()
            label = f"{kind}-{value}"
            if kind == "FG":
                hierarchy.update({"FG": label, "FC": None, "CK": None})
            elif kind == "FC":
                hierarchy.update({"FC": label, "CK": None})
            elif kind == "CK":
                hierarchy["CK"] = label
            elif kind == "BG":
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
                    "tests": [],
                }
            elif kind == "TC" and current is not None:
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
                        "line": index + 1,
                    }
                )

    close_current(len(lines))
    if len(dynamic_container_lines) != 1:
        location_requirement = (
            "before the first BG entry" if first_bug_line is not None else "in the document"
        )
        return False, [], {
            "error": (
                f"[Dynamic Bug Container Format Error] Existing dynamic Bug document "
                f"'{bug_file}' must contain standalone marker {_DYNAMIC_BUGS_MARKER!r} "
                f"exactly once {location_requirement}; found "
                f"{len(dynamic_container_lines)} occurrence(s)."
            ),
            "details": {
                "marker": _DYNAMIC_BUGS_MARKER,
                "marker_lines": dynamic_container_lines,
                "first_bug_line": first_bug_line,
            },
        }
    if first_bug_line is not None:
        if dynamic_container_lines[0] > first_bug_line:
            return False, [], {
                "error": (
                    f"[Dynamic Bug Container Order Error] Standalone marker "
                    f"{_DYNAMIC_BUGS_MARKER!r} at line {dynamic_container_lines[0]} "
                    f"must appear before the first BG entry at line {first_bug_line}."
                ),
                "details": {
                    "marker": _DYNAMIC_BUGS_MARKER,
                    "marker_line": dynamic_container_lines[0],
                    "first_bug_line": first_bug_line,
                },
            }
    return True, records, ""


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
    heading_pattern = re.compile(r"^###\s+<(WAVEFORM-TC-[^<>]+)>\s*$")
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
        heading_match = (
            heading_pattern.fullmatch(stripped_lines[index])
            if index < evidence_end
            else None
        )
        if heading_match is None:
            return False, {}, {
                "error": (
                    f"[Waveform Record Tag Error] Anchor at line {anchor_line} in "
                    f"'{bug_file}' must be followed by ### <WAVEFORM-TC-...>."
                )
            }
        raw_test_label = heading_match.group(1)[len("WAVEFORM-") :]
        try:
            test_label = _normalize_test_case_tag(raw_test_label)
        except ValueError as parse_error:
            return False, {}, {
                "error": (
                    f"[Waveform Record Tag Error] Invalid tag at line {index + 1} in "
                    f"'{bug_file}': {parse_error}."
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
        summaries = [
            f"- {item['bug']}/TC-{item['test_case']} (line {item['line']}): "
            f"{item['reason']}; checkpoint={item['checkpoint'] or '<missing>'}"
            for item in unmatched[:20]
        ]
        if len(unmatched) > len(summaries):
            summaries.append(f"- ... and {len(unmatched) - len(summaries)} more pair(s)")
        return False, [], {
            "error": (
                f"[Waveform Analysis Association Incomplete] {len(unmatched)} documented "
                "dynamic Bug/test pair(s) could not be mapped for validation:\n"
                + "\n".join(summaries)
                + "\nEvery non-zero dynamic Bug/TC pair must map to its exact failing "
                "test and checkpoint before Check/Complete can pass."
            ),
            "details": {"unmatched_pairs": unmatched},
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


def _parse_bug_analysis_sections(content: str) -> tuple[dict[str, str], list[str]]:
    """Split one Bug block using the canonical language-independent markers."""

    matches_by_key = {}
    problems = []
    for key, marker in _BUG_ANALYSIS_SECTION_MARKERS:
        matches = list(
            re.finditer(
                rf"(?m)^[ \t]*{re.escape(marker)}[ \t]*$",
                content,
            )
        )
        if len(matches) != 1:
            problems.append(
                f"marker {marker!r} occurs {len(matches)} time(s); exactly one is required"
            )
        else:
            matches_by_key[key] = matches[0]

    if len(matches_by_key) != len(_BUG_ANALYSIS_SECTION_MARKERS):
        return {}, problems

    expected_keys = [key for key, _marker in _BUG_ANALYSIS_SECTION_MARKERS]
    ordered = sorted(matches_by_key.items(), key=lambda item: item[1].start())
    actual_keys = [key for key, _match in ordered]
    if actual_keys != expected_keys:
        expected_markers = " -> ".join(
            marker for _key, marker in _BUG_ANALYSIS_SECTION_MARKERS
        )
        problems.append(
            "analysis markers are out of canonical order; expected "
            + expected_markers
        )
        return {}, problems

    sections = {}
    for index, (key, match) in enumerate(ordered):
        content_end = (
            ordered[index + 1][1].start()
            if index + 1 < len(ordered)
            else len(content)
        )
        sections[key] = content[match.end() : content_end].strip()
    return sections, problems


def _normalized_bug_analysis_field_text(content: str) -> str:
    """Remove display/control markers before checking whether a field is empty."""

    without_display_headings = re.sub(
        r"(?m)^[ \t]*(?:#{1,6}[ \t]+.+|\*\*[^*\n]+\*\*)[ \t]*$",
        "",
        content,
    )
    without_optional_markers = re.sub(
        rf"(?m)^[ \t]*(?:{re.escape(_BUG_SOURCE_UNAVAILABLE_MARKER)}|"
        rf"{re.escape(_BUG_TODO_MARKER)})[ \t]*$",
        "",
        without_display_headings,
    )
    return re.sub(r"\s+", "", without_optional_markers)


def check_dynamic_bug_analysis_content(
    workspace: str,
    bug_file: str,
) -> tuple[bool, object]:
    """Require every non-zero dynamic Bug scaffold to contain completed analysis."""

    ok, blocks, error = _documented_dynamic_bug_blocks(workspace, bug_file)
    if not ok:
        return False, error
    if not blocks:
        return True, (
            "No documented non-zero-confidence dynamic Bugs require content validation."
        )

    issues = []
    for block in blocks:
        content = block["content"]
        sections, section_problems = _parse_bug_analysis_sections(content)
        for problem in section_problems:
            issues.append(
                {
                    "bug": block["bug"],
                    "path": block["path"],
                    "line": block["line"],
                    "problem": problem,
                }
            )

        if _BUG_TODO_MARKER in content:
            issues.append(
                {
                    "bug": block["bug"],
                    "path": block["path"],
                    "line": block["line"],
                    "problem": f"unfinished marker {_BUG_TODO_MARKER!r} remains",
                }
            )

        if sections:
            markers_by_key = dict(_BUG_ANALYSIS_SECTION_MARKERS)
            titles_by_key = dict(_BUG_ANALYSIS_SECTION_TITLES)
            for key, section_content in sections.items():
                content_lines = [
                    line.strip()
                    for line in section_content.splitlines()
                    if line.strip()
                ]
                expected_title = titles_by_key[key]
                if not content_lines or content_lines[0] != expected_title:
                    issues.append(
                        {
                            "bug": block["bug"],
                            "path": block["path"],
                            "line": block["line"],
                            "problem": (
                                f"field {key!r} after {markers_by_key[key]!r} "
                                f"must start with canonical title {expected_title!r}"
                            ),
                        }
                    )
                if not _normalized_bug_analysis_field_text(section_content):
                    issues.append(
                        {
                            "bug": block["bug"],
                            "path": block["path"],
                            "line": block["line"],
                            "problem": (
                                f"field {key!r} after {markers_by_key[key]!r} "
                                "has no content beyond display/control markers"
                            ),
                        }
                    )

            source_content = sections["source_evidence"]
            unavailable_markers = list(
                re.finditer(
                    rf"(?m)^[ \t]*{re.escape(_BUG_SOURCE_UNAVAILABLE_MARKER)}[ \t]*$",
                    source_content,
                )
            )
            if len(unavailable_markers) > 1:
                issues.append(
                    {
                        "bug": block["bug"],
                        "path": block["path"],
                        "line": block["line"],
                        "problem": (
                            f"marker {_BUG_SOURCE_UNAVAILABLE_MARKER!r} occurs "
                            f"{len(unavailable_markers)} time(s); at most one is allowed"
                        ),
                    }
                )
            elif unavailable_markers:
                conflicting_evidence = []
                if _HDL_FENCED_BLOCK.search(source_content) is not None:
                    conflicting_evidence.append("HDL fenced code block")
                present_source_markers = [
                    marker
                    for marker in _BUG_SOURCE_EVIDENCE_MARKERS
                    if marker in source_content
                ]
                if present_source_markers:
                    conflicting_evidence.append(
                        "source marker(s) " + ", ".join(present_source_markers)
                    )
                if conflicting_evidence:
                    issues.append(
                        {
                            "bug": block["bug"],
                            "path": block["path"],
                            "line": block["line"],
                            "problem": (
                                f"marker {_BUG_SOURCE_UNAVAILABLE_MARKER!r} is mutually "
                                "exclusive with " + " and ".join(conflicting_evidence)
                            ),
                        }
                    )
            else:
                missing_source_evidence = []
                if _HDL_SOURCE_LOCATION.search(source_content) is None:
                    missing_source_evidence.append("real HDL path and line range")
                hdl_blocks = list(_HDL_FENCED_BLOCK.finditer(source_content))
                if not hdl_blocks:
                    missing_source_evidence.append("complete HDL fenced code block")
                fenced_source = "\n".join(
                    match.group("body") for match in hdl_blocks
                )
                for marker in _BUG_SOURCE_EVIDENCE_MARKERS:
                    marker_count = source_content.count(marker)
                    if marker_count != 1:
                        missing_source_evidence.append(
                            f"marker {marker!r} exactly once (found {marker_count})"
                        )
                    elif fenced_source.count(marker) != 1:
                        missing_source_evidence.append(
                            f"marker {marker!r} inside an HDL fenced code block"
                        )
                if missing_source_evidence:
                    issues.append(
                        {
                            "bug": block["bug"],
                            "path": block["path"],
                            "line": block["line"],
                            "problem": (
                                "source analysis lacks "
                                + ", ".join(missing_source_evidence)
                            ),
                        }
                    )

    if issues:
        summaries = [
            f"- {issue['path']} (line {issue['line']}): {issue['problem']}"
            for issue in issues[:20]
        ]
        if len(issues) > len(summaries):
            summaries.append(f"- ... and {len(issues) - len(summaries)} more issue(s)")
        return False, {
            "error": (
                f"[Dynamic Bug Analysis Incomplete] {len(issues)} content issue(s) in "
                f"'{bug_file}':\n"
                + "\n".join(summaries)
                + "\nCreate the BG/TC scaffold with a text-editing tool using "
                "the complete canonical example in Guide_Doc/dut_bug_analysis.md "
                "section 5.1, or use the optional "
                "record_dynamic_bug.py helper when available. Then read the failing assertion, "
                "confirmed WaveInfo timeline, and RTL/HDL source; replace "
                "every scaffold field with evidence-backed analysis inside that BG before "
                "calling Check/Complete."
            ),
            "details": {"issues": issues},
        }
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
    """Return one concise error for one or many invalid waveform blocks."""
    if not issues:
        return True, ""
    deletion_guard = (
        " Do not delete a TC, BG, or enclosing FG/FC/CK branch merely to remove this "
        "validation error while the correctly implemented test still fails. Rerun the "
        "test and WaveInfo, then replace the central evidence record. Remove a dynamic record only "
        "after a correct test passes or other evidence proves it is not a DUT Bug."
    )
    if len(issues) == 1:
        issue = issues[0]
        return _waveform_error(
            issue["message"] + deletion_guard,
            **issue.get("details", {}),
        )

    summaries = []
    for issue in issues:
        details = issue.get("details", {})
        location = (
            f"{details.get('bug', '?')}/{details.get('test_case', '?')}"
            f" (line {details.get('line', '?')})"
        )
        summaries.append(f"- {location}: {issue['message']}")
    return _waveform_error(
        f"[Waveform Analysis Batch Validation] {len(issues)} waveform block(s) "
        "failed validation in one pass:\n"
        + "\n".join(summaries)
        + "\nFix every listed block before calling Check/Complete again. Follow each "
        "block's stated action. In particular, an exploratory receipt requires a new "
        "WaveInfo call with the recommended explicit window; copying effective window "
        "values into the document cannot change that receipt's original arguments. For "
        "ordinary field mismatches, copy exact values from the referenced final-evidence "
        "receipt. Do not invent receipt fields."
        + deletion_guard,
        issues=[
            {
                "message": issue["message"],
                **issue.get("details", {}),
            }
            for issue in issues
        ],
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
        missing = [
            f"{item['bug']}/{item['test_label']}" for item in missing_items
        ]
        recovery_calls = [
            {
                "tool": "ApplyWaveInfoEvidence",
                "arguments": {
                    "target_file": bug_file,
                    "bug_tag": item["bug"],
                    "test_case_tag": item["test_label"],
                    "receipt_id": "",
                },
            }
            for item in missing_items
        ]
        return _waveform_error(
            f"[Waveform Analysis Missing] {len(missing)} dynamic Bug/test association(s) "
            f"lack a central '{_WAVEFORM_BLOCK_KEY}' record: {fc.list_str_abbr(missing)}. "
            "Call final WaveInfo for each failing test, then invoke the corresponding "
            "ApplyWaveInfoEvidence recovery call below. The tool creates the WAVEFORM-REF "
            "and the TC's unique central WAVEFORM-TC record. "
            "Static-only findings belong in the separate static Bug document and cannot "
            "be represented here with a <BG-STATIC-*> tag.",
            missing=missing,
            recovery_calls=recovery_calls,
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
        errors = _validate_receipt_identity(data, receipt, field_differences)
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

        if receipt_result.get("success") is not True:
            errors.append("the referenced WaveInfo call did not succeed")
        if receipt_result.get("evidence_usable") is not True:
            errors.append("the referenced WaveInfo result was not usable as final evidence")
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
        if (receipt_result.get("event_summary") or {}).get("timeline_truncated") is not False:
            errors.append("the referenced WaveInfo timeline was truncated")
        for key in _WAVEFORM_LLM_ANALYSIS_FIELDS:
            value = data.get(key)
            if not _is_nonempty_string(value) or _BUG_TODO_MARKER in value:
                errors.append(f"'{key}' must be a completed non-empty string")

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
                    errors.append(
                        f"bug_evidence.{associated_bug}.{field_name} must be a completed "
                        "non-empty string"
                    )

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
            issues.append(
                {
                    "message": (
                        f"[Waveform Analysis Evidence Invalid] Block at line {line}: "
                        + "; ".join(errors)
                    ),
                    "details": {
                        "bugs": item["bugs"],
                        "test_case": item["test_case"],
                        "line": line,
                        "field_differences": field_differences,
                    },
                }
            )
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
        return True, {}, (
            f"Bug analysis document '{bug_file}' does not exist; no dynamic Bugs require "
            "final waveform validation."
        )
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
                        "[Possible Causes]",
                        "1. Malformed tags (e.g., missing angle brackets, unclosed tags, nesting errors)",
                        *fc.description_bug_doc(),
                        "2. Invalid confidence format (should be <BG-NAME-XX>, XX is integer 0-100)",
                        "3. File encoding or special character issues",
                        "[Solution] Please check and fix the document format according to Guide_Doc/dut_bug_analysis.md."]
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
                        "[Possible Causes]",
                        "1. Malformed tags (should be <FG-*>, <FC-*>, <CK-*>, tags must be on separate lines)",
                        *fc.description_func_doc(),
                        "2. File encoding or special character issues",
                        "3. Invalid document structure",
                        "[Solution] Please check and fix the document format according to Guide_Doc/dut_functions_and_checks.md."]
    return True, [v for v in marked_checks if v.startswith(target_ck_prefix)]


def check_bug_tc_analysis(workspace:str, checks_in_tc:list, bug_file:str, target_ck_prefix:str, failed_tc_and_cks: dict, passed_tc_list: list, only_marked_ckp_in_tc: bool):
    try:
        all_tc_list = fc.get_unity_chip_doc_marks(
            os.path.join(workspace, bug_file), leaf_node="TC"
        )
        tc_list = [tc for tc in all_tc_list if tc.startswith(target_ck_prefix)]
    except Exception as e:
        warning(traceback.format_exc())
        return False, [f"[Parse Error] Bug analysis document '{bug_file}' failed to parse: {str(e)}",
                        "[Possible Causes]",
                        "1. Malformed tags (e.g., missing angle brackets, unclosed tags, nesting errors)",
                        *fc.description_bug_doc(),
                        "2. Invalid confidence format (should be <BG-NAME-XX>, XX is integer 0-100)",
                        "3. File encoding or special character issues",
                        "[Solution] Please check and fix the document format according to Guide_Doc/dut_bug_analysis.md."]
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
        is_fail_tc, fail_tc_name = _find_matching_test_case(tc_name_parts, failed_tc_names)
        # failed tc
        if is_fail_tc:
            if not is_zero_bug and checkpoint not in failed_tc_and_cks[fail_tc_name]:
                tc_not_mark_the_cks_list.append((fail_tc_name, checkpoint))
        else:
            if not is_zero_bug:
                tc_not_found_in_ftc_list.append((tc_name, bug_label))
        # passed tc
        is_pass_tc, pass_tc_name = _find_matching_test_case(tc_name_parts, passed_tc_list)
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
                       "[Cause] Test cases marked in bug analysis must be FAILED (failure proves the bug exists).",
                       "[Solution]",
                        "1. Verify the <TC-*> tags in the bug analysis document reference the correct test cases",
                        "2. If the test still reproduces a confirmed DUT Bug, restore only the correct strong assertion so the DUT behavior—not an artificial failure—causes Fail",
                        "3. If the test case is unrelated to the bug, remove the corresponding <TC-*> tag from the bug analysis document",
                        "4. Do not create an artificial Fail or use a zero-confidence placeholder to preserve a non-Bug failure",
                       "Note: Test cases marked as bug-triggering must have FAILED status (see Guide_Doc/dut_bug_analysis.md)"
                       ]
    # tc not found in fail tcs
    tc_not_found_in_ftc_list = list(set(tc_not_found_in_ftc_list))
    if len(tc_not_found_in_ftc_list) > 0 and not only_marked_ckp_in_tc:
        ftc_msg = fc.list_str_abbr([f"{x[0]}(documented under {x[1]})" for x in tc_not_found_in_ftc_list])
        return False, [f"[Test Case Not Found] Bug analysis document '{bug_file}' contains {len(tc_not_found_in_ftc_list)} test case(s) ({ftc_msg}) not found in the failed test list.",
                       "[Possible Causes & Solutions]",
                          "1. Test case name in <TC-*> does not match the actual Python test file name (case-sensitive)",
                          "2. If the test case is class-based, include the class name, e.g.: <TC-test_example.py::TestClassName::test_func>",
                          "3. If the test case is unrelated to the bug, remove the corresponding <TC-*> tag from the bug analysis document",
                          "4. The test filename in <TC-*> must exactly match the actual filename",
                          "5. Do not create an artificial Fail or use a zero-confidence placeholder to preserve a non-Bug failure",
                       "Note: Bug-triggering test cases must have FAILED status (see Guide_Doc/dut_bug_analysis.md)"
                       ]
    # tc not mark their checkpoints
    tc_not_mark_the_cks_list = list(set(tc_not_mark_the_cks_list))
    if len(tc_not_mark_the_cks_list) > 0:
        ftc_msg = fc.list_str_abbr([
            f"{test_case}(expected checkpoint relation: {checkpoint})"
            for test_case, checkpoint in tc_not_mark_the_cks_list
        ])
        return False, [f"[Bug Checkpoint Association Missing] Bug analysis document '{bug_file}' contains {len(tc_not_mark_the_cks_list)} test case(s) ({ftc_msg}) that the Toffee report does not associate with the documented checkpoint.",
                       "[Cause] The report relation is missing. This does not by itself prove that the source lacks a mark_function call.",
                       "[Solution]",
                          "1. Ensure the test case is placed under the correct checkpoint in the bug analysis document",
                          "2. Before adding another call, inspect any existing mark_function call and verify its FG/FC/CK names, current-test-function argument, execution path, and non-empty checkpoint list",
                          "3. Verify that the fixture reports the same coverage-group objects after yield so Toffee can retain the association",
                          "4. If no call exists, add mark_function at the beginning of the test, e.g.: env.dut.fc_cover['FG-XXX'].mark_function('FC-YYY', test_func, ['CK-ZZZ'])",
                          "5. If the test case is unrelated to this checkpoint, remove the corresponding <TC-*> tag from the bug analysis document",
                        "Note: Failed test cases must mark the checkpoints related to the bugs they trigger (see Guide_Doc/dut_bug_analysis.md and Guide_Doc/dut_test_case.md)"
                       ]
    # fail tc not in bug doc
    failed_tc = [k for k, v in failed_tc_maps.items() if not v]
    if failed_tc:
        return False, [f"[Unresolved Failed Cases] Found {len(failed_tc)} failed test case(s) without a non-zero-confidence confirmed DUT Bug record: {fc.list_str_abbr(failed_tc)}",
                       *fc.description_bug_doc(),
                       "[Solution]",
                       "1. First validate the expected behavior, assertion, stimulus, fixture/API, reference model, reset/timing, and environment",
                       "2. If a test or infrastructure problem caused the failure, fix that problem and rerun until the case passes; do not record it as a DUT Bug",
                       "3. If correct testing stably reproduces a DUT design defect, keep the strong assertion failing and add a non-zero-confidence dynamic Bug with CK relation, source root cause, and confirmed WaveInfo evidence",
                       "4. A <BG-*-0> placeholder does not explain a failed test and cannot make this check pass",
                       f"Completion invariant: every non-DUT-Bug case passes, and every remaining failed case is a fully analyzed DUT Bug reproducer in '{bug_file}'."
                       ]
    return True, ""

def check_bug_ck_analysis(workspace:str, bug_analysis_file:str, failed_check: list,
                          check_fail_ck_in_bug=True, target_ck_prefix:str =""):
    """Check failed checkpoint in bug analysis documentation."""

    ret, marked_bug_checks = get_bug_ck_list_from_doc(workspace, bug_analysis_file, target_ck_prefix)
    if not ret:
        return False, marked_bug_checks, -1

    if check_fail_ck_in_bug:
        un_related_tc_marks = []
        for ck in failed_check:
            if ck not in marked_bug_checks:
                un_related_tc_marks.append(ck)
        # failed checkpoints must be analyzed in bug doc
        if len(un_related_tc_marks) > 0:
                return False, [f"[Unanalyzed Failed Checkpoints] {len(un_related_tc_marks)} failed checkpoint(s) are not associated with a non-zero-confidence DUT Bug: {fc.list_str_abbr(un_related_tc_marks)}. " + \
                               f"The failed checkpoints must be properly analyzed and documented in file '{bug_analysis_file}'. Options:",
                                "1. Make sure you have called CovGroup.sample() to sample the failed check points in your test function or in StepRis/StepFal callback, otherwise the coverage cannot be collected correctly.",
                                "2. Make sure the check function of these checkpoints to ensure they are correctly implemented and returning the expected results.",
                                "3. If a test, expected-value, coverage-check, fixture/API, reference-model, timing, or environment issue caused the failure, fix it and rerun until the checkpoint passes.",
                                "4. If correct testing confirms an actual DUT design Bug, keep the strict check failing and document it with '<FG-*>, <FC-*>, <CK-*>, <BG-*>, <TC-*>' in '{}', using non-zero confidence and complete dynamic evidence.".format(bug_analysis_file),
                                *fc.description_bug_doc(),
                                "5. Never use 'lambda x: True', assert False, a weakened check, or <BG-*-0> to force a classification result.",
                                "6. Review the related checkpoint's check function, the test implementation and the DUT behavior to determine root cause.",
                                "Note: Checkpoint is always referenced like `FG-*/FC-*/CK-*` by the `Check` and `Complete` tools, eg: `FG-LOGIC/FC-ADD/CK-BASIC`， but in the `*.md` file you should use the format: '<FG-*>, <FC-*>, <CK-*>"
                                "Important: If it is determined to be a sampling or checking logic issue, you MUST fix it to ensure correct coverage collection and checking."
                                ], -1

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
                 waveform_tool=None, waveform_test_dir=None):
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
    if test_cases is None:
        return False, "[Test Report Structure Error] No test cases found in the report. Please ensure the test report was generated correctly. " +\
                      "Possible causes: test files not prefixed with test_, import errors, or test execution timeout.", -1
    passed_tc_list = [k for k,v in test_cases.items() if v == "PASSED"]

    bug_ck_list_size = -1
    if len(failed_checks_in_tc) > 0 or os.path.exists(os.path.join(workspace, bug_file)) or failed_funcs_bins:

        ret, msg = check_bug_tc_analysis(
            workspace, checks_in_tc, bug_file, target_ck_prefix, failed_funcs_bins, passed_tc_list, only_marked_ckp_in_tc
        )
        if not ret:
            return ret, msg, -1

        ret, msg, bug_ck_list_size = check_bug_ck_analysis(workspace, bug_file, failed_checks_in_tc,
                                                           check_fail_ck_in_bug=check_fail_ck_in_bug, target_ck_prefix=target_ck_prefix)
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
