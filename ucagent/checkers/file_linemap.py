#coding=utf-8
"""File line mapping checkers for UCAgent."""

import hashlib
import os
import re
import traceback
from collections import OrderedDict
from ucagent.checkers.base import Checker, UnityChipBatchTask
import ucagent.util.functions as fc
from ucagent.util.log import info, warning


_TASK_DIGEST_SEPARATOR = "@sha256="


class LineMapValidationError(ValueError):
    """Carry a stable, task-facing diagnostic for one mapping-file line."""

    def __init__(self, error_code, error, *, artifact, line_no=None,
                 observed=None, expected=None, next_action=None):
        super().__init__(error)
        self.diagnostic = _line_map_failure(
            error_code,
            error,
            artifact=artifact,
            location=(
                f"{artifact}:{line_no}-{line_no}"
                if line_no is not None else artifact
            ),
            observed=observed,
            expected=expected,
            next_action=next_action,
        )


def _line_map_failure(error_code, error, *, artifact=None, location=None,
                      line_block=None, observed=None, expected=None,
                      next_action=None, **details):
    """Build the compact diagnostic contract consumed by stage failure summaries."""
    result = {
        "error_code": error_code,
        "error": error,
    }
    optional = {
        "artifact": artifact,
        "location": location,
        "line_block": line_block,
        "observed": observed,
        "expected": expected,
        "next_action": next_action,
        **details,
    }
    result.update({key: value for key, value in optional.items()
                   if value not in (None, "", [], {})})
    return result


def _raise_map_error(error_code, map_file, line_no, observed, expected,
                     next_action):
    location = f"{map_file}:{line_no}-{line_no}"
    raise LineMapValidationError(
        error_code,
        f"{location}: {observed}",
        artifact=map_file,
        line_no=line_no,
        observed=observed,
        expected=expected,
        next_action=next_action,
    )


def get_func_check_marks(workspace, func_check_file):
    """Get function check marks from the specified file."""
    real_path = os.path.abspath(workspace + os.path.sep + func_check_file)
    if not os.path.exists(real_path):
        return False, _line_map_failure(
            "LINE_MAP_FUNCTION_CHECK_FILE_MISSING",
            f"Function check file '{func_check_file}' does not exist.",
            artifact=func_check_file,
            location=func_check_file,
            expected="An existing functions-and-checks document with valid FG/FC/CK tags.",
            next_action=(
                f"Create or restore '{func_check_file}' in its canonical format, then call `Check` again."
            ),
        )
    try:
        ck_list = fc.get_unity_chip_doc_marks(real_path, "CK", 1)
    except Exception as e:
        error_details = str(e)
        warning(f"Error occurred while checking {func_check_file}: {error_details}")
        warning(traceback.format_exc())
        emsg = [f"Documentation parsing failed for file '{func_check_file}': {error_details}."]
        if "\\n" in error_details:
            emsg.append("Literal '\\n' characters detected - use actual line breaks instead of escaped characters")
        emsg.append({"check_list": [
                "Malformed tags: Ensure proper format. e.g., <FG-NAME>, <FC-NAME>, <CK-NAME>",
                *fc.description_func_doc(),
                "Invalid characters: Use only alphanumeric and hyphen in tag names",
                "Missing tag closure: All tags must be properly closed",
                "Encoding issues: Ensure file is saved in UTF-8 format",
            ]})
        return False, _line_map_failure(
            "LINE_MAP_FUNCTION_CHECK_DOCUMENT_INVALID",
            emsg,
            artifact=func_check_file,
            location=func_check_file,
            observed=error_details,
            expected="A parseable functions-and-checks document with valid FG/FC/CK nesting.",
            next_action=(
                f"Repair the malformed tags or line breaks in '{func_check_file}', then call `Check` again."
            ),
        )
    return True, ck_list


def _mapping_file_for_source(source_file, map_location, map_suffix):
    """Return the deterministic mapping-file path used by the line-map tools."""
    map_file_name = source_file.replace(os.path.sep, "_").replace(".", "_") + map_suffix
    return os.path.join(map_location + os.path.sep + map_file_name)


def _line_block_base(task):
    """Remove the internal source-content digest from a task token."""
    return str(task).split(_TASK_DIGEST_SEPARATOR, 1)[0]


def _line_block_digest(task):
    """Return the internal source-content digest from a task token, if present."""
    parts = str(task).split(_TASK_DIGEST_SEPARATOR, 1)
    return parts[1] if len(parts) == 2 else None


def _without_line_block_digests(value):
    """Remove internal source digests from values returned to the stage agent."""
    if isinstance(value, str):
        return re.sub(
            rf"{re.escape(_TASK_DIGEST_SEPARATOR)}[0-9a-fA-F]+",
            "",
            value,
        )
    if isinstance(value, dict):
        return value.__class__(
            (key, _without_line_block_digests(item))
            for key, item in value.items()
        )
    if isinstance(value, list):
        return [_without_line_block_digests(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_without_line_block_digests(item) for item in value)
    return value


def _parse_strict_line_map(workspace, map_file, source_line_count, max_block_lines,
                           require_ignore_reason=False):
    """Parse and validate raw line ranges without losing block-size information."""
    real_file_path = os.path.abspath(workspace + os.path.sep + map_file)
    if not os.path.exists(real_file_path):
        raise LineMapValidationError(
            "LINE_MAP_FILE_MISSING",
            f"Mapping file '{map_file}' does not exist.",
            artifact=map_file,
            expected="The canonical mapping file returned in the current line block's map_file field.",
            next_action=f"Create '{map_file}' for the current line block, then call `Check` again.",
        )

    ret = {}
    key_locations = {}
    with open(real_file_path, "r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, 1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            value, separator, comment = raw_line.partition("#")
            value = value.strip()
            comment = comment.strip() if separator else ""
            if ":" not in value:
                _raise_map_error(
                    "LINE_MAP_SEPARATOR_MISSING", map_file, line_no,
                    "The mapping entry has no ':' separator.",
                    "FG-*/FC-*/CK-*: start-end or IGNORE/FC-*/CK-*: start-end # concrete reason.",
                    f"Add the missing ':' and line range at '{map_file}:{line_no}-{line_no}', then call `Check` again."
                )
            key, line_ranges_str = value.split(":", 1)
            key = key.strip()
            parts = [part.strip() for part in key.split("/")]
            if len(parts) != 3 or any(not part for part in parts):
                _raise_map_error(
                    "LINE_MAP_KEY_INVALID", map_file, line_no,
                    f"Mapping key '{key}' does not have exactly three non-empty segments.",
                    "FG-*/FC-*/CK-* or IGNORE/FC-*/CK-*.",
                    f"Correct the mapping key at '{map_file}:{line_no}-{line_no}', then call `Check` again."
                )
            if parts[0] == "IGNORE":
                if not parts[1].startswith("FC-") or not parts[2].startswith("CK-"):
                    _raise_map_error(
                        "LINE_MAP_IGNORE_KEY_INVALID", map_file, line_no,
                        f"IGNORE key '{key}' is not in canonical form.",
                        "IGNORE/FC-*/CK-*.",
                        f"Correct the IGNORE key at '{map_file}:{line_no}-{line_no}', then call `Check` again."
                    )
                if require_ignore_reason and not comment:
                    _raise_map_error(
                        "LINE_MAP_IGNORE_REASON_MISSING", map_file, line_no,
                        "IGNORE mapping requires a reason comment after '#'.",
                        "IGNORE/FC-*/CK-*: start-end # concrete reason this non-functional content is excluded.",
                        f"Add a concrete inline reason at '{map_file}:{line_no}-{line_no}', then call `Check` again."
                    )
            elif parts[0] == "MISSMT":
                if not parts[1].startswith("FC-") or not parts[2].startswith("CK-"):
                    _raise_map_error(
                        "LINE_MAP_MISSMT_KEY_INVALID", map_file, line_no,
                        f"MISSMT key '{key}' is malformed.",
                        "A formal FG-*/FC-*/CK-* mapping after adding the missing CK to the functions-and-checks document.",
                        f"Replace the MISSMT entry at '{map_file}:{line_no}-{line_no}' with a formal CK mapping, then call `Check` again."
                    )
            elif not (
                parts[0].startswith("FG-")
                and parts[1].startswith("FC-")
                and parts[2].startswith("CK-")
            ):
                _raise_map_error(
                    "LINE_MAP_FUNCTION_KEY_INVALID", map_file, line_no,
                    f"Functional key '{key}' is not in canonical form.",
                    "FG-*/FC-*/CK-* using tags declared in the functions-and-checks document.",
                    f"Correct the functional key at '{map_file}:{line_no}-{line_no}', then call `Check` again."
                )

            line_list = []
            for raw_range in line_ranges_str.split(","):
                raw_range = raw_range.strip()
                if "-" not in raw_range:
                    _raise_map_error(
                        "LINE_MAP_RANGE_FORMAT_INVALID", map_file, line_no,
                        f"Line range '{raw_range}' does not use start-end format.",
                        "An inclusive physical line range such as 12-12 or 20-35.",
                        f"Rewrite the range at '{map_file}:{line_no}-{line_no}' in start-end form, then call `Check` again."
                    )
                start_str, end_str = raw_range.split("-", 1)
                if not start_str.strip().isdigit() or not end_str.strip().isdigit():
                    _raise_map_error(
                        "LINE_MAP_RANGE_FORMAT_INVALID", map_file, line_no,
                        f"Line range '{raw_range}' contains a non-integer endpoint.",
                        "An inclusive physical line range containing two positive integers.",
                        f"Correct the range at '{map_file}:{line_no}-{line_no}', then call `Check` again."
                    )
                start_line = int(start_str)
                end_line = int(end_str)
                if start_line < 1 or start_line > end_line:
                    _raise_map_error(
                        "LINE_MAP_RANGE_INVALID", map_file, line_no,
                        f"Line range '{raw_range}' has an invalid start or reversed endpoints.",
                        "A range with 1 <= start <= end.",
                        f"Correct the range at '{map_file}:{line_no}-{line_no}', then call `Check` again."
                    )
                if max_block_lines and end_line - start_line + 1 > max_block_lines:
                    _raise_map_error(
                        "LINE_MAP_RANGE_TOO_LARGE", map_file, line_no,
                        f"Line range '{raw_range}' exceeds the {max_block_lines}-line block limit.",
                        f"One or more ranges no longer than {max_block_lines} physical lines and aligned to reviewed line blocks.",
                        f"Split the range at '{map_file}:{line_no}-{line_no}' along the returned line-block boundaries, then call `Check` again."
                    )
                if source_line_count >= 0 and end_line > source_line_count:
                    _raise_map_error(
                        "LINE_MAP_RANGE_OUT_OF_BOUNDS", map_file, line_no,
                        f"Line range '{raw_range}' exceeds the source file length ({source_line_count}).",
                        f"A range ending at or before physical line {source_line_count}.",
                        f"Correct the range at '{map_file}:{line_no}-{line_no}' using the current source line numbers, then call `Check` again."
                    )
                line_list.append((start_line, end_line))

            pre_list = ret.get(key, [])
            ret[key] = fc.range_list_merge(pre_list, line_list)
            key_locations.setdefault(key, []).append(line_no)
    return ret, key_locations


def _mapped_lines(line_ck_map):
    """Expand a CK map into a set of covered line numbers."""
    ranges = []
    for line_ranges in line_ck_map.values():
        ranges.extend(line_ranges)
    merged_ranges = fc.range_list_merge([], ranges)
    mapped = set()
    for start_line, end_line in merged_ranges:
        mapped.update(range(start_line, end_line + 1))
    return mapped


def _unmapped_lines_for_ranges(source_lines, mapped_lines, required_ranges, ignore_blank_lines=True):
    """Return uncovered lines inside the requested physical line ranges."""
    missing = []
    for start_line, end_line in required_ranges:
        for line_num in range(start_line, end_line + 1):
            if ignore_blank_lines and not source_lines[line_num - 1].strip():
                continue
            if line_num not in mapped_lines:
                missing.append(line_num)
    return missing


def _line_numbers_to_blocks(line_numbers):
    """Compact physical line numbers into ordered ``start-end`` strings."""
    normalized = sorted(set(int(line_number) for line_number in line_numbers))
    if not normalized:
        return []
    blocks = []
    start_line = previous_line = normalized[0]
    for line_number in normalized[1:]:
        if line_number == previous_line + 1:
            previous_line = line_number
            continue
        blocks.append(f"{start_line}-{previous_line}")
        start_line = previous_line = line_number
    blocks.append(f"{start_line}-{previous_line}")
    return blocks


def _format_line_blocks(line_blocks, max_blocks):
    """Render a bounded summary of compact physical line ranges."""
    displayed = line_blocks[:max_blocks]
    values = list(displayed)
    if len(line_blocks) > max_blocks:
        values.append(f"... ({len(line_blocks) - max_blocks} more block(s))")
    return f"[{', '.join(values)}]"


def _indexed_line_content(source_lines, line_numbers):
    """Return source text keyed by its physical line number."""
    return OrderedDict(
        (
            line_number,
            source_lines[line_number - 1].rstrip("\r\n"),
        )
        for line_number in line_numbers
    )


def _format_indexed_line_content(indexed_content, max_lines):
    """Render a bounded numbered excerpt from indexed source content."""
    content_items = list(indexed_content.items())
    displayed_items = content_items[:max_lines]
    lines = [
        f"{line_number}: {line_content}"
        for line_number, line_content in displayed_items
    ]
    remaining_count = len(content_items) - len(displayed_items)
    if remaining_count:
        lines.append(
            f"... (and {remaining_count} more uncovered lines; see uncovered_content)"
        )
    return "\n".join(lines)


def line_map_check_one_file(workspace, source_file, map_file, ck_list, ck_list_file, map_suffix,
                            map_location, max_example_lines: int, must_has_no_miss_match: bool,
                            cb_unmatch_ck=None, cb_match_ck=None, max_block_lines=None,
                            strict_line_bounds=False, required_ranges=None,
                            ignore_blank_lines=True, require_ignore_reason=False,
                            include_line_detail_header=True,
                            compact_unmapped_blocks=False):
    """Check one file for unmapped lines based on line-function mapping."""
    info(f"Checking line-function mapping for file '{source_file}'...")
    abs_source_file = os.path.abspath(workspace + os.path.sep + source_file)
    if not os.path.exists(abs_source_file):
        diagnostic = _line_map_failure(
            "LINE_MAP_SOURCE_FILE_MISSING",
            f"Source file '{source_file}' does not exist.",
            artifact=source_file,
            source_block=source_file,
            expected="A source file selected by the current stage file_list.",
            next_action=f"Restore or correct the current source file '{source_file}', then call `Check` again.",
        )
        return False, diagnostic
    if not map_file:
        map_file = _mapping_file_for_source(source_file, map_location, map_suffix)
    if not os.path.exists(os.path.abspath(workspace + os.path.sep + map_file)):
        diagnostic = _line_map_failure(
            "LINE_MAP_FILE_MISSING",
            f"Mapping file '{map_file}' does not exist.",
            artifact=map_file,
            source_block=source_file,
            expected="The canonical mapping file returned in the current line block's map_file field.",
            next_action=f"Create '{map_file}' for the current line block, then call `Check` again.",
        )
        return False, diagnostic
    try:
        with open(abs_source_file, "r", encoding="utf-8") as source_handle:
            source_lines = source_handle.readlines()
        strict = max_block_lines is not None or strict_line_bounds or require_ignore_reason
        key_locations = {}
        if strict:
            line_ck_map, key_locations = _parse_strict_line_map(
                workspace,
                map_file,
                len(source_lines) if strict_line_bounds else -1,
                max_block_lines,
                require_ignore_reason=require_ignore_reason,
            )
        else:
            line_ck_map = fc.parse_line_CK_map_file(workspace, map_file)
    except LineMapValidationError as e:
        warning(f"Error occurred while parsing mapping file {map_file}: {e}")
        return False, e.diagnostic
    except Exception as e:
        error_details = str(e)
        warning(f"Error occurred while parsing mapping file {map_file}: {error_details}")
        warning(traceback.format_exc())
        diagnostic = _line_map_failure(
            "LINE_MAP_PARSE_ERROR",
            f"Mapping file parsing failed for file '{map_file}': {error_details}.",
            artifact=map_file,
            expected="A canonical, parseable line-map entry.",
            next_action=f"Repair the syntax at '{map_file}', then call `Check` again.",
        )
        return False, diagnostic
    # compare ck_list and line_ck_map
    miss_matched_lines = []
    erro_lines_keys = []
    for k in line_ck_map.keys():
        if k not in ck_list:
            if str(k).startswith("IGNORE/"):
                continue
            if str(k).startswith("MISSMT/"):
                miss_matched_lines.append((k, line_ck_map[k]))
                continue
            erro_lines_keys.append((k, line_ck_map[k]))
            if cb_unmatch_ck:
                cb_unmatch_ck(k, line_ck_map[k])
        else:
            if cb_match_ck:
                cb_match_ck(k, line_ck_map[k])
    if len(erro_lines_keys) > 0:
        emsg = [f"Found {len(erro_lines_keys)} mapping entr{'y' if len(erro_lines_keys) == 1 else 'ies'} in '{map_file}' that do not have corresponding CK tags:"]
        for ck_name, _ in erro_lines_keys[:max_example_lines]:
            emsg.append(f"  '{ck_name}' which is not found in documentation file '{ck_list_file}'.")
        if len(erro_lines_keys) > max_example_lines:
            emsg.append(f"  ... and {len(erro_lines_keys) - max_example_lines} more.")
        emsg.append("Validate CKs are:")
        for ck in ck_list[:max_example_lines]:
            emsg.append(f"  '{ck}'")
        if len(ck_list) > max_example_lines:
            emsg.append(f"  ... and {len(ck_list) - max_example_lines} more.")
        first_ck_name = erro_lines_keys[0][0]
        first_line = next(iter(key_locations.get(first_ck_name, [])), None)
        location = (
            f"{map_file}:{first_line}-{first_line}"
            if first_line is not None else map_file
        )
        diagnostic = _line_map_failure(
            "LINE_MAP_UNKNOWN_CK",
            f"{location}: Mapping entry '{first_ck_name}' is not declared in '{ck_list_file}'.",
            artifact=map_file,
            location=location,
            observed=first_ck_name,
            expected="A precise FG-*/FC-*/CK-* path declared in the functions-and-checks document.",
            next_action=(
                f"At '{location}', replace the entry with the exact declared CK path; "
                f"if the specification proves the CK is missing, add it to '{ck_list_file}' first. "
                "Then call `Check` again."
            ),
            issue_count=len(erro_lines_keys),
        )
        return False, {
            "error": emsg,
            "diagnostic": diagnostic,
            "details": emsg,
        }
    if must_has_no_miss_match and len(miss_matched_lines) > 0:
        emsg = [f"Found {len(miss_matched_lines)} line block(s) in mapping file '{map_file}' that are marked as MISSMT (miss-matched):"]
        for ck_name, _ in miss_matched_lines[:max_example_lines]:
            emsg.append(f"  '{ck_name}' which is not matched in documentation file '{ck_list_file}'.")
        if len(miss_matched_lines) > max_example_lines:
            emsg.append(f"  ... and {len(miss_matched_lines) - max_example_lines} more.")
        emsg.append(f"You need to add those missing CKs to file '{ck_list_file}' or correct the mapping.")
        first_ck_name = miss_matched_lines[0][0]
        first_line = next(iter(key_locations.get(first_ck_name, [])), None)
        location = (
            f"{map_file}:{first_line}-{first_line}"
            if first_line is not None else map_file
        )
        diagnostic = _line_map_failure(
            "LINE_MAP_MISSMT_FORBIDDEN",
            f"{location}: Mapping entry '{first_ck_name}' uses MISSMT, which is not allowed as a final result.",
            artifact=map_file,
            location=location,
            observed=first_ck_name,
            expected="A formal FG-*/FC-*/CK-* mapping after the missing CK is added to the functions-and-checks document.",
            next_action=(
                f"Add the missing formal CK to '{ck_list_file}', replace the MISSMT entry at '{location}', then call `Check` again."
            ),
            issue_count=len(miss_matched_lines),
        )
        return False, {
            "error": emsg,
            "diagnostic": diagnostic,
            "details": emsg,
        }
    # Find unmapped lines.  ``required_ranges`` is used by the batch checker so
    # a partially completed file can be validated one line block at a time.
    uncovered_content = OrderedDict()
    if required_ranges is None:
        un_mapped_lines, detail_msg = fc.get_un_mapped_lines(
            workspace, source_file, line_ck_map, max_example_lines
        )
    else:
        mapped_lines = _mapped_lines(line_ck_map)
        un_mapped_lines = _unmapped_lines_for_ranges(
            source_lines, mapped_lines, required_ranges, ignore_blank_lines
        )
        if un_mapped_lines and compact_unmapped_blocks:
            uncovered_line_blocks = _line_numbers_to_blocks(un_mapped_lines)
            uncovered_content = _indexed_line_content(
                source_lines, un_mapped_lines
            )
            detail_msg = (
                "Uncovered blocks: "
                f"{_format_line_blocks(uncovered_line_blocks, max_example_lines)}\n"
                "Uncovered source lines:\n"
                f"{_format_indexed_line_content(uncovered_content, max_example_lines)}"
            )
        elif un_mapped_lines:
            detail_msg = "\n".join(
                f"{line_num}: {source_lines[line_num - 1].rstrip()}"
                for line_num in un_mapped_lines[:max_example_lines]
            )
            if include_line_detail_header:
                detail_msg = "line: line_content\n" + detail_msg
            if len(un_mapped_lines) > max_example_lines:
                detail_msg += f"\n... (and {len(un_mapped_lines) - max_example_lines} more lines)"
        else:
            detail_msg = "All requested lines are mapped."
    if len(un_mapped_lines) > 0:
        if compact_unmapped_blocks:
            uncovered_line_blocks = _line_numbers_to_blocks(un_mapped_lines)
            if not uncovered_content:
                uncovered_content = _indexed_line_content(
                    source_lines, un_mapped_lines
                )
            emsg = (
                f"Found {len(un_mapped_lines)} un-mapped line(s), grouped into "
                f"{len(uncovered_line_blocks)} block(s), in source file "
                f"'{source_file}':\n{detail_msg}"
            )
            diagnostic = _line_map_failure(
                "LINE_MAP_UNCOVERED_LINES",
                f"{source_file} has {len(un_mapped_lines)} uncovered non-blank line(s) in the current block.",
                artifact=map_file,
                source_block=source_file,
                observed=f"uncovered blocks: {uncovered_line_blocks}",
                expected="Every non-blank physical line in the current line block has a formal CK or a reasoned IGNORE mapping.",
                next_action=(
                    f"Add mappings to '{map_file}' for blocks {uncovered_line_blocks}, then call `Check` again."
                ),
                uncovered_line_count=len(un_mapped_lines),
                uncovered_blocks=uncovered_line_blocks,
                uncovered_content=uncovered_content,
            )
            return False, {
                "error": emsg,
                "diagnostic": diagnostic,
                "details": emsg,
                "uncovered_line_count": len(un_mapped_lines),
                "uncovered_line_blocks": uncovered_line_blocks,
                "uncovered_content": uncovered_content,
            }
        emsg = (
            f"Found {len(un_mapped_lines)} un-mapped line block(s) in source file "
            f"'{source_file}':\n{detail_msg}"
        )
        diagnostic = _line_map_failure(
            "LINE_MAP_UNCOVERED_LINES",
            f"{source_file} has {len(un_mapped_lines)} uncovered non-blank line(s) in the current block.",
            artifact=map_file,
            source_block=source_file,
            observed=detail_msg,
            expected="Every non-blank physical line in the current line block has a formal CK or a reasoned IGNORE mapping.",
            next_action=f"Add mappings to '{map_file}' for the uncovered lines, then call `Check` again.",
            uncovered_line_count=len(un_mapped_lines),
        )
        return False, {"error": emsg, "diagnostic": diagnostic, "details": emsg}
    info(f"All lines in file '{source_file}' are properly mapped.")
    return True, f"All lines in file '{source_file}' are properly mapped."


class FileLineMapChecker(Checker):
    """Check unmapped lines in file based on line-function mapping."""

    def __init__(self, source_file, func_check_file,
                 map_file=None,
                 map_suffix="_line_func_map.txt",
                 map_location="line_map",
                 max_example_lines=20, need_human_check=False, must_has_no_miss_match=False, **kw):
        self.source_file = source_file
        self.func_check_file = func_check_file
        self.map_file = map_file
        self.map_suffix = map_suffix
        self.map_location = map_location
        self.max_example_lines = max_example_lines
        self.must_has_no_miss_match = must_has_no_miss_match
        self.set_human_check_needed(need_human_check)

    def do_check(self, **kw) -> tuple[bool, object]:
        """Check file for unmapped lines."""
        success, ck_list_or_msg = get_func_check_marks(
            self.workspace, self.func_check_file
        )
        if not success:
            return False, ck_list_or_msg
        success, result_msg = line_map_check_one_file(
            self.workspace,
            self.source_file,
            self.map_file,
            ck_list_or_msg,
            self.func_check_file,
            self.map_suffix,
            self.map_location,
            self.max_example_lines,
            self.must_has_no_miss_match
        )
        return success, result_msg


class UnityChipBatchCheckerFileLineMap(Checker):
    """Batch-check every non-blank line block in a configured file set.

    ``UnityChipBatchTask`` owns the active batch and persists validated progress
    in its checkpoint.  Source documents and canonical mapping files remain the
    validation ground truth; no LLM-authored progress document is consumed.
    """

    def __init__(self, name, file_list, func_check_file,
                 map_location="line_map", map_suffix="_line_func_map.txt",
                 batch_size=1, max_block_lines=100, max_example_lines=20,
                 ignore_blank_lines=True, must_has_no_miss_match=True,
                 need_human_check=False, data_key=None, **kw):
        self.name = name
        self.file_list = file_list if isinstance(file_list, list) else [file_list]
        self.func_check_file = func_check_file
        self.map_location = map_location
        self.map_suffix = map_suffix
        self.data_key = data_key
        self.batch_size = int(batch_size)
        self.max_block_lines = int(max_block_lines)
        self.max_example_lines = int(max_example_lines)
        self.ignore_blank_lines = bool(ignore_blank_lines)
        self.must_has_no_miss_match = bool(must_has_no_miss_match)
        if self.batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        if self.max_block_lines < 1:
            raise ValueError("max_block_lines must be a positive integer")
        # Checker keeps callback storage on the class for historical reasons;
        # isolate this batcher's lifecycle callbacks per instance.
        self._cb_list = {}
        self.batch_task = UnityChipBatchTask(name, self)
        self._task_errors = []
        self._completed_validation_errors = []
        self._unexpected_mapping_files = []
        self._source_files = []
        self._ck_count = "-"
        self._is_init = False
        self.set_human_check_needed(need_human_check)

    def _get_all_source_files(self):
        files = []
        for pattern in self.file_list:
            files.extend(fc.find_files_by_pattern(self.workspace, pattern, ignore_warn=True))
        files = sorted(set(files))
        seen_mapping_files = {}
        for source_file in files:
            map_file = _mapping_file_for_source(
                source_file, self.map_location, self.map_suffix
            )
            previous_source = seen_mapping_files.get(map_file)
            if previous_source is not None and previous_source != source_file:
                self._task_errors.append(
                    f"Source files '{previous_source}' and '{source_file}' map to the same "
                    f"mapping file '{map_file}'. Rename one source or choose a safer map naming scheme."
                )
            seen_mapping_files[map_file] = source_file
        return files

    def _get_all_line_blocks(self):
        blocks = []
        self._source_files = self._get_all_source_files()
        for source_file in self._source_files:
            source_path = os.path.abspath(self.workspace + os.path.sep + source_file)
            try:
                with open(source_path, "r", encoding="utf-8") as source_handle:
                    source_lines = source_handle.readlines()
            except Exception as exc:
                self._task_errors.append(f"Cannot read source file '{source_file}': {exc}")
                continue
            source_digest = hashlib.sha256(
                "".join(source_lines).encode("utf-8")
            ).hexdigest()
            for start_line in range(1, len(source_lines) + 1, self.max_block_lines):
                end_line = min(start_line + self.max_block_lines - 1, len(source_lines))
                if self.ignore_blank_lines and all(
                    not source_lines[line_num - 1].strip()
                    for line_num in range(start_line, end_line + 1)
                ):
                    continue
                blocks.append(
                    f"{source_file}:{start_line}-{end_line}"
                    f"{_TASK_DIGEST_SEPARATOR}{source_digest}"
                )
        return blocks

    @staticmethod
    def _split_line_block(task):
        task = _line_block_base(task)
        try:
            source_file, line_range = task.rsplit(":", 1)
            start_text, end_text = line_range.split("-", 1)
            start_line = int(start_text)
            end_line = int(end_text)
        except (ValueError, AttributeError):
            raise ValueError(f"Invalid line-block task '{task}', expected file:start-end.")
        if start_line < 1 or start_line > end_line:
            raise ValueError(f"Invalid line-block task '{task}'.")
        return source_file, start_line, end_line

    def _sync_batch_state(self, source_tasks, completed_tasks):
        notes = []
        self.batch_task.sync_source_task(source_tasks, notes, "Line-block source list changed.")
        self.batch_task.sync_gen_task(completed_tasks, notes, "Line-block progress updated.")
        completed_set = set(completed_tasks)
        remaining_tasks = [
            task for task in source_tasks if task not in completed_set
        ]
        self.batch_task.tbd_task_list = remaining_tasks[:self.batch_size]
        self.batch_task.cmp_task_list = []
        return notes

    def _find_unexpected_mapping_files(self):
        """Find range-suffixed mapping files that the checker will never consume."""
        map_directory = os.path.abspath(
            self.workspace + os.path.sep + self.map_location
        )
        if not os.path.isdir(map_directory):
            return []
        available_files = sorted(os.listdir(map_directory))
        unexpected = {}
        for source_file in self._source_files:
            expected_map = _mapping_file_for_source(
                source_file, self.map_location, self.map_suffix
            )
            expected_name = os.path.basename(expected_map)
            if not expected_name.endswith(self.map_suffix):
                continue
            source_prefix = expected_name[:-len(self.map_suffix)] + "_"
            range_suffixed_name = re.compile(
                rf"^{re.escape(source_prefix)}\d+_\d+{re.escape(self.map_suffix)}$"
            )
            for candidate in available_files:
                if candidate != expected_name and range_suffixed_name.fullmatch(candidate):
                    unexpected_file = os.path.join(self.map_location, candidate)
                    unexpected[unexpected_file] = expected_map
        return [
            {"file": unexpected_file, "expected_map_file": unexpected[unexpected_file]}
            for unexpected_file in sorted(unexpected)
        ]

    def _validate_line_block(self, task, ck_list):
        source_file, start_line, end_line = self._split_line_block(task)
        map_file = _mapping_file_for_source(source_file, self.map_location, self.map_suffix)
        return line_map_check_one_file(
            self.workspace,
            source_file,
            map_file,
            ck_list,
            self.func_check_file,
            self.map_suffix,
            self.map_location,
            self.max_example_lines,
            self.must_has_no_miss_match,
            max_block_lines=self.max_block_lines,
            strict_line_bounds=True,
            required_ranges=[(start_line, end_line)],
            ignore_blank_lines=self.ignore_blank_lines,
            require_ignore_reason=True,
            include_line_detail_header=False,
            compact_unmapped_blocks=True,
        )

    @staticmethod
    def _new_diagnostics():
        """Create the stable diagnostic fields returned by the batch checker."""
        return {
            "missing_mapping_files": [],
            "uncovered_lines": [],
            "unknown_ck": [],
            "oversized_ranges": [],
            "unexplained_ignore": [],
            "progress_state_mismatches": [],
            "unexpected_mapping_files": [],
            "configuration_errors": [],
            "parse_errors": [],
            "forbidden_missmt": [],
            "actionable_diagnostics": [],
        }

    @staticmethod
    def _visible_diagnostics(diagnostics):
        """Return only non-empty public categories, without duplicating primary issues."""
        return {
            key: value
            for key, value in diagnostics.items()
            if key != "actionable_diagnostics" and value not in (None, "", [], {})
        }

    def _add_validation_diagnostics(self, diagnostics, task, message):
        """Translate a line-map validation error into structured batch details."""
        if isinstance(message, dict):
            error_value = message.get("error", message)
        else:
            error_value = message
        error_text = str(error_value)
        task_base = _line_block_base(task)
        map_file = _mapping_file_for_source(
            self._split_line_block(task)[0], self.map_location, self.map_suffix
        )
        diagnostic = None
        if isinstance(message, dict) and isinstance(message.get("diagnostic"), dict):
            diagnostic = dict(message["diagnostic"])
        elif isinstance(message, dict) and message.get("error_code"):
            diagnostic = dict(message)
        if diagnostic is not None:
            diagnostic.setdefault("line_block", task_base)
            diagnostic.setdefault("source_block", task_base)
            diagnostic.setdefault("artifact", map_file)
            diagnostics["actionable_diagnostics"].append(diagnostic)
            code = diagnostic["error_code"]
            classified = {"line_block": task_base, "details": diagnostic}
            if code == "LINE_MAP_UNKNOWN_CK":
                diagnostics["unknown_ck"].append(classified)
            elif code == "LINE_MAP_MISSMT_FORBIDDEN":
                diagnostics["forbidden_missmt"].append(classified)
            elif code == "LINE_MAP_IGNORE_REASON_MISSING":
                diagnostics["unexplained_ignore"].append(classified)
            elif code in {"LINE_MAP_RANGE_TOO_LARGE", "LINE_MAP_RANGE_OUT_OF_BOUNDS"}:
                diagnostics["oversized_ranges"].append(classified)
            elif code.startswith("LINE_MAP_") and code not in {
                "LINE_MAP_FILE_MISSING",
                "LINE_MAP_UNCOVERED_LINES",
            }:
                diagnostics["parse_errors"].append(classified)
        if "Mapping file '" in error_text and "does not exist" in error_text:
            diagnostics["missing_mapping_files"].append(map_file)
        if "un-mapped line" in error_text:
            uncovered_blocks = (
                message.get("uncovered_line_blocks", [])
                if isinstance(message, dict)
                else []
            )
            uncovered_count = (
                message.get("uncovered_line_count", 0)
                if isinstance(message, dict)
                else 0
            )
            uncovered_content = (
                OrderedDict(message.get("uncovered_content", {}).items())
                if isinstance(message, dict)
                and isinstance(message.get("uncovered_content"), dict)
                else OrderedDict()
            )
            if not uncovered_blocks:
                line_numbers = [
                    int(value)
                    for value in re.findall(r"(?:^|\n)\s*(\d+):", error_text)
                ]
                uncovered_blocks = _line_numbers_to_blocks(line_numbers)
                uncovered_count = len(line_numbers)
            diagnostics["uncovered_lines"].append({
                "line_block": task_base,
                "uncovered_line_count": uncovered_count,
                "uncovered_blocks": uncovered_blocks,
                "uncovered_content": uncovered_content,
            })
        if diagnostic is None and "not found in documentation" in error_text:
            diagnostics["unknown_ck"].append({
                "line_block": task_base,
                "details": error_value,
            })
        if diagnostic is None and ("block limit" in error_text or ("exceeds the" in error_text and "line" in error_text)):
            diagnostics["oversized_ranges"].append({
                "line_block": task_base,
                "details": error_value,
            })
        if diagnostic is None and "IGNORE mapping requires a reason comment" in error_text:
            diagnostics["unexplained_ignore"].append({
                "line_block": task_base,
                "details": error_value,
            })

        if diagnostic is None and error_text:
            code = None
            next_action = None
            expected = None
            if "does not exist" in error_text and "Mapping file" in error_text:
                code = "LINE_MAP_FILE_MISSING"
                expected = "The canonical mapping file returned in the current line block's map_file field."
                next_action = f"Create '{map_file}' for the current line block, then call `Check` again."
            elif "IGNORE mapping requires a reason comment" in error_text:
                code = "LINE_MAP_IGNORE_REASON_MISSING"
                expected = "IGNORE/FC-*/CK-*: start-end # concrete reason."
                next_action = f"Add a concrete inline reason to '{map_file}', then call `Check` again."
            if code:
                diagnostics["actionable_diagnostics"].append(
                    _line_map_failure(
                        code,
                        error_text,
                        artifact=map_file,
                        line_block=task_base,
                        source_block=task_base,
                        expected=expected,
                        next_action=next_action,
                    )
                )

    def _line_block_content(self, task):
        """Return the physical lines for a task so Check can guide the LLM directly."""
        source_file, start_line, end_line = self._split_line_block(task)
        map_file = _mapping_file_for_source(
            source_file, self.map_location, self.map_suffix
        )
        source_path = os.path.abspath(self.workspace + os.path.sep + source_file)
        try:
            with open(source_path, "r", encoding="utf-8") as source_handle:
                source_lines = source_handle.readlines()
        except Exception as exc:
            return {
                "line_block": _line_block_base(task),
                "file": source_file,
                "start_line": start_line,
                "end_line": end_line,
                "map_file": map_file,
                "error": f"Cannot read source file '{source_file}': {exc}",
            }
        if end_line > len(source_lines):
            return {
                "line_block": _line_block_base(task),
                "file": source_file,
                "start_line": start_line,
                "end_line": end_line,
                "map_file": map_file,
                "error": (
                    f"Line block ends at {end_line}, but source file '{source_file}' "
                    f"has only {len(source_lines)} physical lines."
                ),
            }
        indexed_content = OrderedDict(
            (
                line_number,
                source_lines[line_number - 1].rstrip("\r\n"),
            )
            for line_number in range(start_line, end_line + 1)
        )
        return {
            "line_block": _line_block_base(task),
            "file": source_file,
            "start_line": start_line,
            "end_line": end_line,
            "map_file": map_file,
            "content": indexed_content,
        }

    def _attach_line_block_content(self, result, tasks, key="current_line_block_contents"):
        """Attach source context to a structured Check/Complete response."""
        if not isinstance(result, dict):
            return result
        result[key] = [self._line_block_content(task) for task in tasks]
        return result

    def _save_final_ck_list(self, ck_list):
        """Persist the final CK paths for downstream stages."""
        if not self.data_key:
            return
        final_ck_list = list(ck_list)
        self.smanager_set_value(self.data_key, final_ck_list)
        info(
            f"Cache final CK marks(size={len(final_ck_list)}) "
            f"to data key '{self.data_key}'."
        )

    def on_init(self):
        success, ck_list = get_func_check_marks(self.workspace, self.func_check_file)
        self._ck_count = len(ck_list) if success else "-"
        self._refresh_batch_state(ck_list if success else None)
        super().on_init()
        return self

    def _refresh_batch_state(self, ck_list=None):
        self._task_errors = []
        self._completed_validation_errors = []
        source_tasks = self._get_all_line_blocks()
        current_by_base = {_line_block_base(task): task for task in source_tasks}
        previous_tasks = list(self.batch_task.gen_task_list)
        previous_by_base = {}
        for task in previous_tasks:
            task_base = _line_block_base(task)
            if task_base in previous_by_base:
                self._task_errors.append(
                    f"Recorded progress contains duplicate completed line block '{task_base}'."
                )
                continue
            previous_by_base[task_base] = task
        for task_base in sorted(set(previous_by_base) - set(current_by_base)):
            self._task_errors.append(
                f"Recorded completed line block '{task_base}' does not match a current target."
            )

        completed_tasks = []
        found_incomplete = False
        checkpoint_gap = False
        for current_task in source_tasks:
            task_base = _line_block_base(current_task)
            previous_task = previous_by_base.get(task_base)
            if previous_task is None:
                found_incomplete = True
                checkpoint_gap = True
                continue
            if found_incomplete:
                if checkpoint_gap:
                    self._task_errors.append(
                        f"Recorded completed line block '{task_base}' appears after an incomplete earlier block."
                    )
                continue
            if _line_block_digest(previous_task) != _line_block_digest(current_task):
                self._task_errors.append(
                    f"Completed line block '{task_base}' is stale because the target document "
                    "changed outside this stage after the progress was recorded. "
                    "Re-read the target document and review its current line blocks; "
                    "do not modify the target document to preserve old progress."
                )
                found_incomplete = True
                continue
            if ck_list is not None:
                valid, message = self._validate_line_block(current_task, ck_list)
                if not valid:
                    self._completed_validation_errors.append({
                        "line_block": task_base,
                        "details": message,
                    })
                    found_incomplete = True
                    continue
            completed_tasks.append(current_task)

        self._unexpected_mapping_files = self._find_unexpected_mapping_files()
        if self._unexpected_mapping_files:
            replacements = ", ".join(
                f"{item['file']} -> {item['expected_map_file']}"
                for item in self._unexpected_mapping_files
            )
            self._task_errors.append(
                "Found mapping files with line-range suffixes that are not read by "
                f"this stage: {replacements}. Merge their valid mappings into the "
                "listed canonical files and remove the unexpected files."
            )
        self._sync_batch_state(source_tasks, completed_tasks)

    def get_template_data(self):
        """Return cached progress without scanning files or mutating batch state."""
        if not self._is_init:
            return {
                "TOTAL_LINE_BLOCKS": "-",
                "COMPLETED_LINE_BLOCKS": "-",
                "LINE_MAP_PROGRESS": "-/-",
                "COUNT_CK": "-",
                "CURRENT_LINE_BLOCKS": "",
                "MAX_LINE_BLOCK_LINES": self.max_block_lines,
            }
        source_tasks = self.batch_task.source_task_list
        completed_tasks = self.batch_task.gen_task_list
        total = len(source_tasks) if self._source_files else "-"
        completed = len(completed_tasks) if self._source_files else "-"
        return {
            "TOTAL_LINE_BLOCKS": total,
            "COMPLETED_LINE_BLOCKS": completed,
            "LINE_MAP_PROGRESS": f"{completed}/{total}",
            "COUNT_CK": self._ck_count,
            "CURRENT_LINE_BLOCKS": ", ".join(
                _line_block_base(task) for task in self.batch_task.tbd_task_list
            ),
            "MAX_LINE_BLOCK_LINES": self.max_block_lines,
        }

    def do_check(self, is_complete=False, **kw) -> tuple[bool, object]:
        """Validate the current line-map batch and advance the resumable task."""
        if not self._is_init:
            return False, _line_map_failure(
                "LINE_MAP_STAGE_NOT_READY",
                "UnityChipBatchCheckerFileLineMap has not been initialized; the line-map stage is not ready to validate its current batch.",
                expected="An initialized current stage with a rendered line-block batch.",
                next_action="Call `CurrentTips` after stage initialization, then retry `Check` once.",
            )

        success, ck_list_or_msg = get_func_check_marks(
            self.workspace, self.func_check_file
        )
        if not success:
            return False, self._attach_line_block_content(
                ck_list_or_msg, self.batch_task.tbd_task_list
            )
        ck_list = ck_list_or_msg
        self._ck_count = len(ck_list)
        self._refresh_batch_state(ck_list)
        diagnostics = self._new_diagnostics()
        source_tasks = self.batch_task.source_task_list
        current_by_base = {_line_block_base(task): task for task in source_tasks}

        diagnostics["unexpected_mapping_files"].extend(
            self._unexpected_mapping_files
        )
        if self._task_errors:
            for error in self._task_errors:
                if error.startswith(("Recorded ", "Completed line block ")):
                    diagnostics["progress_state_mismatches"].append(error)
                elif "line-range suffixes" not in error:
                    diagnostics["configuration_errors"].append(error)
            if diagnostics["configuration_errors"]:
                diagnostics["actionable_diagnostics"].append(
                    _line_map_failure(
                        "LINE_MAP_CONFIGURATION_ERROR",
                        diagnostics["configuration_errors"][0],
                        artifact=self.map_location,
                        expected="A valid configured file set and canonical mapping-file layout.",
                        next_action="Correct the reported configuration or mapping-file layout, then call `Check` again.",
                    )
                )
            if diagnostics["progress_state_mismatches"]:
                diagnostics["actionable_diagnostics"].insert(
                    0,
                    _line_map_failure(
                        "LINE_MAP_PROGRESS_STATE_INVALID",
                        diagnostics["progress_state_mismatches"][0],
                        artifact=self.map_location,
                        expected="Recorded completed blocks still match the current source and canonical mappings.",
                        next_action="Re-read the affected source block, repair its canonical mapping, then call `Check` again.",
                    ),
                )
            if diagnostics["unexpected_mapping_files"]:
                item = diagnostics["unexpected_mapping_files"][0]
                diagnostics["actionable_diagnostics"].append(
                    _line_map_failure(
                        "LINE_MAP_UNEXPECTED_FILE",
                        f"Mapping file '{item['file']}' uses line-range suffixes and is not a canonical file consumed by this stage.",
                        artifact=item["file"],
                        expected=f"Use canonical mapping file '{item['expected_map_file']}'.",
                        next_action=(
                            f"Merge valid entries into '{item['expected_map_file']}', remove '{item['file']}', then call `Check` again."
                        ),
                    )
                )
            primary = diagnostics["actionable_diagnostics"][0] if diagnostics["actionable_diagnostics"] else None
            visible_diagnostics = self._visible_diagnostics(diagnostics)
            return False, self._attach_line_block_content(
                {
                    "error": primary["error"] if primary else self._task_errors,
                    **(primary if primary else {}),
                    "issue_count": max(1, len(diagnostics["actionable_diagnostics"])),
                    **visible_diagnostics,
                },
                self.batch_task.tbd_task_list,
            )

        if self._completed_validation_errors:
            invalid_tasks = []
            for item in self._completed_validation_errors:
                task = current_by_base.get(item["line_block"])
                if task is not None:
                    invalid_tasks.append(task)
                    self._add_validation_diagnostics(
                        diagnostics, task, item["details"]
                    )
            primary = diagnostics["actionable_diagnostics"][0] if diagnostics["actionable_diagnostics"] else None
            visible_diagnostics = self._visible_diagnostics(diagnostics)
            return False, self._attach_line_block_content({
                "error": primary["error"] if primary else "A previously completed line-block mapping is no longer valid.",
                **(primary if primary else {}),
                "invalid_completed_mappings": self._completed_validation_errors,
                "progress": (
                    f"{len(self.batch_task.gen_task_list)}/{len(source_tasks)}"
                ),
                "completed_line_blocks": len(self.batch_task.gen_task_list),
                "total_line_blocks": len(source_tasks),
                "remaining_line_blocks": (
                    len(source_tasks) - len(self.batch_task.gen_task_list)
                ),
                "issue_count": max(1, len(diagnostics["actionable_diagnostics"])),
                **visible_diagnostics,
            }, invalid_tasks or self.batch_task.tbd_task_list)

        if not source_tasks:
            if self._source_files:
                self._save_final_ck_list(ck_list)
                if is_complete:
                    return True, "Complete success."
                return True, {
                    "success": (
                        "All matched source files contain only blank lines; "
                        "call `Complete` to next stage."
                    ),
                    "progress": "0/0",
                    "completed_line_blocks": 0,
                    "total_line_blocks": 0,
                    "remaining_line_blocks": 0,
                    "current_batch": [],
                    "current_line_block_contents": [],
                }
            diagnostics["configuration_errors"].append(
                "No files matched the configured file_list."
            )
            return False, _line_map_failure(
                "LINE_MAP_TARGETS_NOT_FOUND",
                "No target line blocks were found for this stage.",
                observed="No source file matched the configured target patterns.",
                expected="At least one non-blank target document selected by the current workflow.",
                next_action="Confirm the DUT input documents exist at their configured workspace paths, then call `Check` again.",
            )

        current_batch = list(self.batch_task.tbd_task_list)
        current_batch_bases = [_line_block_base(task) for task in current_batch]
        if not current_batch:
            self._save_final_ck_list(ck_list)
            if is_complete:
                return True, "Complete success."
            return True, {
                "success": "All line blocks are done; call `Complete` to next stage.",
                "progress": f"{len(source_tasks)}/{len(source_tasks)}",
                "completed_line_blocks": len(source_tasks),
                "total_line_blocks": len(source_tasks),
                "remaining_line_blocks": 0,
                "current_batch": [],
                "current_line_block_contents": [],
            }

        invalid_current = []
        for task in current_batch:
            valid, message = self._validate_line_block(task, ck_list)
            if not valid:
                invalid_current.append({
                    "line_block": _line_block_base(task),
                    "details": message,
                })
                self._add_validation_diagnostics(diagnostics, task, message)
        if invalid_current:
            primary = diagnostics["actionable_diagnostics"][0] if diagnostics["actionable_diagnostics"] else None
            result = {
                "error": primary["error"] if primary else "The current line-block batch is not complete.",
                **(primary if primary else {}),
            }
            result["invalid_mappings"] = invalid_current
            result["current_batch"] = current_batch_bases
            result["progress"] = (
                f"{len(self.batch_task.gen_task_list)}/{len(source_tasks)}"
            )
            result["issue_count"] = max(
                len(invalid_current), len(diagnostics["actionable_diagnostics"])
            )
            result.update(self._visible_diagnostics(diagnostics))
            self._attach_line_block_content(result, current_batch)
            return False, result

        notes = []
        completed_tasks = list(self.batch_task.gen_task_list)
        for task in current_batch:
            if task not in completed_tasks:
                completed_tasks.append(task)
        self.batch_task.sync_gen_task(completed_tasks, notes, "Line-block progress updated.")
        passed, result = self.batch_task.do_complete(
            notes,
            is_complete,
            "in the configured file_list",
            f"in canonical mapping files under {self.map_location}",
            " Use each line block's map_file field and call Check after finishing the current batch.",
        )
        result = _without_line_block_digests(result)
        if passed:
            self._save_final_ck_list(ck_list)
        if isinstance(result, dict):
            completed_count = len(self.batch_task.gen_task_list)
            result["current_batch"] = current_batch_bases
            result["progress"] = f"{completed_count}/{len(source_tasks)}"
            result["completed_line_blocks"] = completed_count
            result["total_line_blocks"] = len(source_tasks)
            result["remaining_line_blocks"] = len(source_tasks) - completed_count
            self._attach_line_block_content(result, current_batch)
            if self.batch_task.tbd_task_list:
                result["next_line_blocks"] = [
                    _line_block_base(task) for task in self.batch_task.tbd_task_list
                ]
                self._attach_line_block_content(
                    result, self.batch_task.tbd_task_list, "next_line_block_contents"
                )
        return passed, result
