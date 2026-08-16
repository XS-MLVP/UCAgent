# -*- coding: utf-8 -*-
"""Toffee report checker for UCAgent verification."""

from ucagent.util.log import warning, info
import ucagent.util.functions as fc
from ucagent.checkers.base import Checker
from datetime import datetime
import os
import re
import textwrap
import traceback
import yaml


_WAVEFORM_BLOCK_KEY = "waveform_analysis"
_WAVEFORM_FENCE_OPEN = "```yaml"
_WAVEFORM_FENCE_CLOSE = "```"


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


def _parse_waveform_analysis_blocks(
    workspace: str,
    bug_file: str,
) -> tuple[bool, dict, object]:
    """Parse fenced ``waveform_analysis`` mappings directly following BG/TC tags."""

    path = os.path.join(workspace, bug_file)
    if not os.path.isfile(path):
        return False, {}, {
            "error": f"[Bug Analysis Missing] Dynamic bug document '{bug_file}' does not exist."
        }

    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    current_bug = None
    current_test = None
    pending_test = None
    opened = None
    payload_lines: list[str] = []
    blocks = {}
    tag_pattern = re.compile(r"<(FG|FC|CK|BG|TC)-([^<>]+)>")

    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if "<WAVEFORM-ANALYSIS>" in stripped or "</WAVEFORM-ANALYSIS>" in stripped:
            return False, {}, {
                "error": (
                    f"[Legacy Waveform Analysis Format] Line {line_number} in '{bug_file}' "
                    "uses the unsupported <WAVEFORM-ANALYSIS> tag. Put a ```yaml fence "
                    "directly after the corresponding <TC-*> and use 'waveform_analysis:' "
                    "as the only top-level YAML key."
                )
            }

        if opened is not None:
            if stripped.startswith("```") and stripped != _WAVEFORM_FENCE_CLOSE:
                return False, {}, {
                    "error": (
                        f"[Waveform Analysis Fence Error] Nested or malformed fence "
                        f"{stripped!r} at line {line_number} in '{bug_file}'. Close the "
                        "current YAML block with a standalone ``` first."
                    )
                }
            if stripped != _WAVEFORM_FENCE_CLOSE:
                payload_lines.append(line)
                continue

            payload_ok, payload, payload_error = _extract_waveform_yaml_payload(
                payload_lines,
                block_line=opened["line"],
                bug_file=bug_file,
            )
            if not payload_ok:
                return False, {}, payload_error
            pair = (opened["bug"], opened["test_case"])
            if pair in blocks:
                return False, {}, {
                    "error": (
                        f"[Duplicate Waveform Analysis] '{pair[0]}/{pair[1]}' has more "
                        f"than one {_WAVEFORM_BLOCK_KEY} block in '{bug_file}'."
                    )
                }
            blocks[pair] = {
                "line": opened["line"],
                "data": payload,
            }
            opened = None
            payload_lines = []
            continue

        if pending_test is not None:
            if not stripped:
                continue
            if stripped.lower() == _WAVEFORM_FENCE_OPEN:
                opened = {
                    "line": line_number,
                    "test_line": pending_test["line"],
                    "bug": pending_test["bug"],
                    "test_case": pending_test["test_case"],
                }
                pending_test = None
                payload_lines = []
                continue
            if stripped.startswith("```"):
                return False, {}, {
                    "error": (
                        f"[Waveform Analysis Fence Error] The first non-empty content after "
                        f"<{pending_test['test_case']}> at line {line_number} in "
                        f"'{bug_file}' must be ```yaml, not {stripped!r}."
                    )
                }
            if stripped == f"{_WAVEFORM_BLOCK_KEY}:":
                return False, {}, {
                    "error": (
                        f"[Waveform Analysis Fence Required] Bare '{_WAVEFORM_BLOCK_KEY}:' "
                        f"at line {line_number} in '{bug_file}' is not accepted. Put the "
                        "mapping inside a ```yaml ... ``` block."
                    )
                }
            pending_test = None

        if stripped.lower() == _WAVEFORM_FENCE_OPEN:
            if current_bug is not None and current_test is not None:
                pair = (current_bug, current_test)
                if pair in blocks:
                    return False, {}, {
                        "error": (
                            f"[Duplicate Waveform Analysis] '{pair[0]}/{pair[1]}' has more "
                            f"than one {_WAVEFORM_BLOCK_KEY} block in '{bug_file}'."
                        )
                    }
                return False, {}, {
                    "error": (
                        f"[Waveform Analysis Cascade Error] YAML fence at line "
                        f"{line_number} in '{bug_file}' is not the first non-empty content "
                        f"after <{current_test}>. Put ```yaml immediately after its exact "
                        "<TC-*> tag and use 'waveform_analysis:' as the top-level key."
                    )
                }
            return False, {}, {
                "error": (
                    f"[Waveform Analysis Association Missing] YAML fence at line "
                    f"{line_number} must be the first non-empty content after a dynamic "
                    "<BG-*>/<TC-*> entry."
                )
            }

        for match in tag_pattern.finditer(line):
            kind, value = match.groups()
            label = f"{kind}-{value}"
            if kind in {"FG", "FC", "CK"}:
                current_bug = None
                current_test = None
            elif kind == "BG":
                current_bug = label
                current_test = None
            elif kind == "TC":
                current_test = label
                if current_bug is not None:
                    pending_test = {
                        "line": line_number,
                        "bug": current_bug,
                        "test_case": current_test,
                    }

    if opened is not None:
        return False, {}, {
            "error": (
                f"[Waveform Analysis Fence Error] YAML block opened at line "
                f"{opened['line']} in '{bug_file}' is missing a standalone closing ```."
            )
        }
    return True, blocks, ""


def _required_waveform_pairs(
    workspace: str,
    bug_file: str,
    target_ck_prefix: str,
    failed_tc_and_cks: dict,
) -> tuple[bool, list[dict], object]:
    valid_labels, label_error = _validate_dynamic_bug_document_labels(
        workspace, bug_file
    )
    if not valid_labels:
        return False, [], label_error
    if not failed_tc_and_cks:
        return True, [], ""
    try:
        tc_marks = fc.get_unity_chip_doc_marks(
            os.path.join(workspace, bug_file), leaf_node="TC"
        )
    except Exception as error:
        return False, [], {
            "error": f"[Waveform Analysis Parse Error] Cannot parse '{bug_file}': {error}"
        }

    required = {}
    for mark in tc_marks:
        segments = mark.split("/")
        bug_label = next(
            (segment for segment in reversed(segments[:-1]) if segment.startswith("BG-")),
            None,
        )
        test_label = segments[-1] if segments[-1].startswith("TC-") else None
        if bug_label is None or test_label is None:
            continue
        try:
            _bug_name, confidence = parse_bug_label(bug_label)
        except ValueError as error:
            return False, [], {"error": f"[Invalid Bug Label] {error}"}
        if confidence == 0:
            continue
        test_case = test_label[3:]
        matched, report_name = _find_matching_test_case(
            test_case.split("::"), failed_tc_and_cks.keys()
        )
        if not matched:
            continue
        checkpoint = mark.split("/BG-", 1)[0]
        if checkpoint not in failed_tc_and_cks.get(report_name, []):
            continue
        pair = (bug_label, test_label)
        required[pair] = {
            "bug": bug_label,
            "test_label": test_label,
            "test_case": test_case,
            "report_test_case": report_name,
        }
    return True, list(required.values()), ""


def _waveform_error(message: str, **details) -> tuple[bool, object]:
    result = {"error": message}
    if details:
        result["details"] = details
    return False, result


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
    if len(issues) == 1:
        issue = issues[0]
        return _waveform_error(issue["message"], **issue.get("details", {}))

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
        "receipt. Do not invent receipt fields.",
        issues=[
            {
                "message": issue["message"],
                **issue.get("details", {}),
            }
            for issue in issues
        ],
    )


def check_waveform_bug_analysis(
    workspace: str,
    bug_file: str,
    target_ck_prefix: str,
    failed_tc_and_cks: dict,
    waveform_tool=None,
    waveform_test_dir: str | None = None,
) -> tuple[bool, object]:
    """Require verified WaveInfo receipts for every non-zero dynamic Bug/TC pair."""

    ok, required, error = _required_waveform_pairs(
        workspace, bug_file, target_ck_prefix, failed_tc_and_cks
    )
    if not ok:
        return False, error
    if not required:
        return True, "No dynamically reproduced non-zero-confidence bugs require waveform analysis."

    ok, blocks, error = _parse_waveform_analysis_blocks(workspace, bug_file)
    if not ok:
        return False, error
    missing = [
        f"{item['bug']}/{item['test_label']}"
        for item in required
        if (item["bug"], item["test_label"]) not in blocks
    ]
    if missing:
        return _waveform_error(
            f"[Waveform Analysis Missing] {len(missing)} dynamic Bug/test association(s) "
            f"lack a fenced '{_WAVEFORM_BLOCK_KEY}' mapping: {fc.list_str_abbr(missing)}. "
            "Call WaveInfo for each failing test, then put a ```yaml block as the first "
            "non-empty content after the corresponding <TC-*>. The block must contain only "
            "the top-level 'waveform_analysis:' key and its structured evidence. Static-only findings "
            "belong in the separate static Bug document and cannot be represented here with "
            "a <BG-STATIC-*> tag.",
            missing=missing,
        )

    status_issues = []
    for item in required:
        pair = (item["bug"], item["test_label"])
        block = blocks[pair]
        if block["data"].get("status") != "confirmed":
            status_issues.append(
                {
                    "message": (
                        f"[Waveform Confirmation Required] Block at line {block['line']} for "
                        f"'{item['bug']}/{item['test_label']}' must use status: confirmed. "
                        "A non-zero-confidence Bug cannot be completed with status: unavailable. "
                        "Rerun the failing test, call WaveInfo, and record event-level evidence."
                    ),
                    "details": {
                        "bug": item["bug"],
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
            "[WaveInfo Tool Required] Dynamic Bug waveform validation cannot proceed because "
            "the active WaveInfo tool instance is unavailable. Enable WaveInfo and call it "
            "before Check/Complete; document-only waveform data is not accepted."
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
                "[WaveInfo Test Directory Mismatch] The active WaveInfo instance searches "
                f"'{configured_test_dir}', but this checker executed tests in "
                f"'{expected_test_dir}'. Waveform receipts from another test directory cannot "
                "be used as Bug evidence."
            )

    issues = []
    for item in required:
        pair = (item["bug"], item["test_label"])
        block = blocks[pair]
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
                        "bug": item["bug"],
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
                        "was not found in the active WaveInfo instance or its signed workspace "
                        "checkpoint store. If this is a resumed run, verify that the same "
                        "workspace/test directory is used; otherwise call WaveInfo again for "
                        "this test and replace the block. Copied or invented waveform data "
                        "cannot pass this checker."
                    ),
                    "details": {
                        "bug": item["bug"],
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
                        "bug": item["bug"],
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
                        "context_steps, and max_points; then replace the receipt and copy the "
                        "new bug_document_fields."
                    ),
                    "details": {
                        "bug": item["bug"],
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
        for key in ("alignment_evidence", "observed_behavior", "source_correlation"):
            if not _is_nonempty_string(data.get(key)):
                errors.append(f"'{key}' must be a non-empty string")

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
                        "bug": item["bug"],
                        "test_case": item["test_case"],
                        "line": line,
                        "field_differences": field_differences,
                    },
                }
            )
            continue

        replay = waveform_tool.analyze(**receipt_args)
        if replay.get("success") is not True or replay.get("evidence_usable") is not True:
            issues.append(
                {
                    "message": (
                        f"[Waveform Analysis No Longer Reproduces] Current WaveInfo replay for "
                        f"'{item['test_case']}' returned status '{replay.get('status')}'. The "
                        "documented pattern is not valid evidence for the waveform generated "
                        "by this Check; call WaveInfo again and update the block."
                    ),
                    "details": {
                        "bug": item["bug"],
                        "test_case": item["test_case"],
                        "line": line,
                        "current_waveinfo": replay,
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
                            "bug": item["bug"],
                            "test_case": item["test_case"],
                            "line": line,
                            "field_differences": candidate_differences,
                            "current_waveinfo": replay,
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
                            "bug": item["bug"],
                            "test_case": item["test_case"],
                            "line": line,
                            "documented_wave_step": data.get("wave_step"),
                            "current_event_steps": current_event_steps,
                            "current_waveinfo": replay,
                        },
                    }
                )

    if issues:
        return _waveform_issue_result(issues)

    return True, f"Validated WaveInfo receipts for {len(required)} dynamic Bug/test association(s)."


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
    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    valid_labels, label_error = _validate_dynamic_bug_document_labels(
        workspace, bug_file
    )
    if not valid_labels:
        return False, {}, label_error

    hierarchy = {"FG": None, "FC": None, "CK": None, "BG": None}
    required_bug_paths = {}
    documented_test_map = {}
    bugs_with_tests = set()
    tag_pattern = re.compile(r"<(FG|FC|CK|BG|TC)-([^<>]+)>")
    inside_waveform_block = False
    for line in lines:
        stripped = line.strip()
        if not inside_waveform_block and stripped.lower() == _WAVEFORM_FENCE_OPEN:
            inside_waveform_block = True
            continue
        if inside_waveform_block and stripped == _WAVEFORM_FENCE_CLOSE:
            inside_waveform_block = False
            continue
        if inside_waveform_block:
            continue

        for match in tag_pattern.finditer(line):
            kind, value = match.groups()
            label = f"{kind}-{value}"
            if kind == "FG":
                hierarchy.update({"FG": label, "FC": None, "CK": None, "BG": None})
            elif kind == "FC":
                hierarchy.update({"FC": label, "CK": None, "BG": None})
            elif kind == "CK":
                hierarchy.update({"CK": label, "BG": None})
            elif kind == "BG":
                hierarchy["BG"] = label
                try:
                    _bug_name, confidence = parse_bug_label(label)
                except ValueError as error:
                    return False, {}, {"error": f"[Invalid Bug Label] {error}"}
                if confidence == 0:
                    continue
                bug_path = "/".join(
                    item
                    for item in (
                        hierarchy["FG"],
                        hierarchy["FC"],
                        hierarchy["CK"],
                        hierarchy["BG"],
                    )
                    if item is not None
                )
                required_bug_paths[bug_path] = label
            elif kind == "TC":
                bug_path = "/".join(
                    item
                    for item in (
                        hierarchy["FG"],
                        hierarchy["FC"],
                        hierarchy["CK"],
                        hierarchy["BG"],
                    )
                    if item is not None
                )
                if bug_path not in required_bug_paths:
                    continue
                test_case = value.strip()
                if not test_case:
                    return False, {}, {
                        "error": (
                            f"[Waveform Analysis Test Format Error] Dynamic Bug "
                            f"'{required_bug_paths[bug_path]}' contains an empty <TC-*> label."
                        )
                    }
                checkpoint = bug_path.split("/BG-", 1)[0]
                documented_test_map.setdefault(test_case, []).append(checkpoint)
                bugs_with_tests.add(bug_path)

    if not required_bug_paths:
        return True, {}, (
            "No documented non-zero-confidence dynamic Bugs require final waveform validation."
        )

    missing_tests = [
        required_bug_paths[bug_path]
        for bug_path in required_bug_paths
        if bug_path not in bugs_with_tests
    ]
    if missing_tests:
        return False, {}, {
            "error": (
                f"[Waveform Analysis Test Missing] {len(missing_tests)} non-zero-confidence "
                "dynamic Bug(s) have no <TC-*> reproducer and therefore cannot have verified "
                f"waveform evidence: {fc.list_str_abbr(missing_tests)}."
            ),
            "details": {"bugs_without_test_cases": missing_tests},
        }
    return True, documented_test_map, ""


def check_all_documented_waveform_bug_analysis(
    workspace: str,
    bug_file: str,
    waveform_tool=None,
    waveform_test_dir: str | None = None,
) -> tuple[bool, object]:
    """Validate every documented dynamic Bug at a workflow boundary."""

    ok, documented_test_map, message = _get_documented_dynamic_test_map(
        workspace, bug_file
    )
    if not ok:
        return False, message
    if not documented_test_map:
        return True, message
    return check_waveform_bug_analysis(
        workspace,
        bug_file,
        "",
        documented_test_map,
        waveform_tool=waveform_tool,
        waveform_test_dir=waveform_test_dir,
    )


class UnityChipCheckerWaveformBugAnalysis(Checker):
    """Independent waveform-evidence gate for the dynamic Bug document."""

    def __init__(self, bug_file: str, test_dir: str, **kwargs):
        del kwargs
        self.bug_file = bug_file
        self.test_dir = test_dir

    def do_check(self, **kwargs) -> tuple[bool, object]:
        """Validate dynamic Bug waveform evidence using active WaveInfo receipts."""
        del kwargs
        waveform_tool = None
        if self.stage_manager is not None:
            waveform_tool = self.get_tool_by_name("WaveInfo")
        passed, message = check_all_documented_waveform_bug_analysis(
            self.workspace,
            self.bug_file,
            waveform_tool=waveform_tool,
            waveform_test_dir=self.test_dir,
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
