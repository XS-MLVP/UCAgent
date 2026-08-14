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


_LINE_BLOCK_PROGRESS_RE = re.compile(r"<file>\s*(.*?)\s*</file>", re.DOTALL)
_TASK_DIGEST_SEPARATOR = "@sha256="


def get_func_check_marks(workspace, func_check_file):
    """Get function check marks from the specified file."""
    real_path = os.path.abspath(workspace + os.path.sep + func_check_file)
    if not os.path.exists(real_path):
        return False, {"error": f"Function check file '{func_check_file}' does not exist."}
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
        return False, {"error": emsg}
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


def _parse_strict_line_map(workspace, map_file, source_line_count, max_block_lines,
                           require_ignore_reason=False):
    """Parse and validate raw line ranges without losing block-size information."""
    real_file_path = os.path.abspath(workspace + os.path.sep + map_file)
    if not os.path.exists(real_file_path):
        raise ValueError(f"Mapping file '{map_file}' does not exist.")

    ret = {}
    with open(real_file_path, "r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, 1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            value, separator, comment = raw_line.partition("#")
            value = value.strip()
            comment = comment.strip() if separator else ""
            if ":" not in value:
                raise ValueError(
                    f"{map_file} at line {line_no}: Missing ':' separator."
                )
            key, line_ranges_str = value.split(":", 1)
            key = key.strip()
            parts = [part.strip() for part in key.split("/")]
            if len(parts) != 3 or any(not part for part in parts):
                raise ValueError(
                    f"{map_file} at line {line_no}: key must have exactly three "
                    "segments (FG/FC/CK, IGNORE/FC/CK, or MISSMT/FC/CK)."
                )
            if parts[0] == "IGNORE":
                if not parts[1].startswith("FC-") or not parts[2].startswith("CK-"):
                    raise ValueError(
                        f"{map_file} at line {line_no}: IGNORE key must be "
                        "IGNORE/FC-*/CK-*."
                    )
                if require_ignore_reason and not comment:
                    raise ValueError(
                        f"{map_file} at line {line_no}: IGNORE mapping requires a reason comment."
                    )
            elif parts[0] == "MISSMT":
                if not parts[1].startswith("FC-") or not parts[2].startswith("CK-"):
                    raise ValueError(
                        f"{map_file} at line {line_no}: MISSMT key must be "
                        "MISSMT/FC-*/CK-*."
                    )
            elif not (
                parts[0].startswith("FG-")
                and parts[1].startswith("FC-")
                and parts[2].startswith("CK-")
            ):
                raise ValueError(
                    f"{map_file} at line {line_no}: functional key must be FG-*/FC-*/CK-*."
                )

            line_list = []
            for raw_range in line_ranges_str.split(","):
                raw_range = raw_range.strip()
                if "-" not in raw_range:
                    raise ValueError(
                        f"{map_file} at line {line_no}: line range '{raw_range}' "
                        "must use start-end format."
                    )
                start_str, end_str = raw_range.split("-", 1)
                if not start_str.strip().isdigit() or not end_str.strip().isdigit():
                    raise ValueError(
                        f"{map_file} at line {line_no}: line range '{raw_range}' "
                        "must contain integers."
                    )
                start_line = int(start_str)
                end_line = int(end_str)
                if start_line < 1 or start_line > end_line:
                    raise ValueError(
                        f"{map_file} at line {line_no}: invalid line range '{raw_range}'."
                    )
                if max_block_lines and end_line - start_line + 1 > max_block_lines:
                    raise ValueError(
                        f"{map_file} at line {line_no}: range '{raw_range}' exceeds "
                        f"the {max_block_lines}-line block limit."
                    )
                if source_line_count >= 0 and end_line > source_line_count:
                    raise ValueError(
                        f"{map_file} at line {line_no}: range '{raw_range}' exceeds "
                        f"source file length ({source_line_count})."
                    )
                line_list.append((start_line, end_line))

            pre_list = ret.get(key, [])
            ret[key] = fc.range_list_merge(pre_list, line_list)
    return ret


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


def line_map_check_one_file(workspace, source_file, map_file, ck_list, ck_list_file, map_suffix,
                            map_location, max_example_lines: int, must_has_no_miss_match: bool,
                            cb_unmatch_ck=None, cb_match_ck=None, max_block_lines=None,
                            strict_line_bounds=False, required_ranges=None,
                            ignore_blank_lines=True, require_ignore_reason=False,
                            include_line_detail_header=True):
    """Check one file for unmapped lines based on line-function mapping."""
    info(f"Checking line-function mapping for file '{source_file}'...")
    abs_source_file = os.path.abspath(workspace + os.path.sep + source_file)
    if not os.path.exists(abs_source_file):
        return False, {"error": f"Source file '{source_file}' does not exist."}
    if not map_file:
        map_file = _mapping_file_for_source(source_file, map_location, map_suffix)
    if not os.path.exists(os.path.abspath(workspace + os.path.sep + map_file)):
        return False, {"error": f"Mapping file '{map_file}' does not exist. You should create it first."}
    try:
        with open(abs_source_file, "r", encoding="utf-8") as source_handle:
            source_lines = source_handle.readlines()
        strict = max_block_lines is not None or strict_line_bounds or require_ignore_reason
        if strict:
            line_ck_map = _parse_strict_line_map(
                workspace,
                map_file,
                len(source_lines) if strict_line_bounds else -1,
                max_block_lines,
                require_ignore_reason=require_ignore_reason,
            )
        else:
            line_ck_map = fc.parse_line_CK_map_file(workspace, map_file)
    except Exception as e:
        error_details = str(e)
        warning(f"Error occurred while parsing mapping file {map_file}: {error_details}")
        warning(traceback.format_exc())
        return False, {"error": f"Mapping file parsing failed for file '{map_file}': {error_details}."}
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
        emsg = [f"Found {len(erro_lines_keys)} line block(s) in mapping file '{map_file}' that do not have corresponding CK tags:"]
        for ck_name, _ in erro_lines_keys[:max_example_lines]:
            emsg.append(f"  '{ck_name}' which is not found in documentation file '{ck_list_file}'.")
        if len(erro_lines_keys) > max_example_lines:
            emsg.append(f"  ... and {len(erro_lines_keys) - max_example_lines} more.")
        emsg.append("Validate CKs are:")
        for ck in ck_list[:max_example_lines]:
            emsg.append(f"  '{ck}'")
        if len(ck_list) > max_example_lines:
            emsg.append(f"  ... and {len(ck_list) - max_example_lines} more.")
        return False, {"error": emsg}
    if must_has_no_miss_match and len(miss_matched_lines) > 0:
        emsg = [f"Found {len(miss_matched_lines)} line block(s) in mapping file '{map_file}' that are marked as MISSMT (miss-matched):"]
        for ck_name, _ in miss_matched_lines[:max_example_lines]:
            emsg.append(f"  '{ck_name}' which is not matched in documentation file '{ck_list_file}'.")
        if len(miss_matched_lines) > max_example_lines:
            emsg.append(f"  ... and {len(miss_matched_lines) - max_example_lines} more.")
        emsg.append(f"You need to add those missing CKs to file '{ck_list_file}' or correct the mapping.")
        return False, {"error": emsg}
    # Find unmapped lines.  ``required_ranges`` is used by the batch checker so
    # a partially completed file can be validated one line block at a time.
    if required_ranges is None:
        un_mapped_lines, detail_msg = fc.get_un_mapped_lines(
            workspace, source_file, line_ck_map, max_example_lines
        )
    else:
        mapped_lines = _mapped_lines(line_ck_map)
        un_mapped_lines = _unmapped_lines_for_ranges(
            source_lines, mapped_lines, required_ranges, ignore_blank_lines
        )
        if un_mapped_lines:
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
        emsg = f"Found {len(un_mapped_lines)} un-mapped line block(s) in source file '{source_file}':\n" + detail_msg        
        return False, {"error": emsg}
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

    Progress is persisted in the progress document as markers of the form
    ``<file>path/to/file:1-100</file>``.  ``UnityChipBatchTask`` remains the
    source of truth for the active batch and its resumable checkpoint, while
    the document markers make progress auditable and portable.
    """

    def __init__(self, name, file_list, func_check_file, progress_file,
                 map_location="line_map", map_suffix="_line_func_map.txt",
                 batch_size=1, max_block_lines=100, max_example_lines=20,
                 ignore_blank_lines=True, must_has_no_miss_match=True,
                 need_human_check=False, **kw):
        self.name = name
        self.file_list = file_list if isinstance(file_list, list) else [file_list]
        self.func_check_file = func_check_file
        self.progress_file = progress_file
        self.map_location = map_location
        self.map_suffix = map_suffix
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
        self._source_files = []
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

    def _progress_markers(self):
        progress_path = os.path.abspath(self.workspace + os.path.sep + self.progress_file)
        if not os.path.exists(progress_path):
            return [], []
        try:
            with open(progress_path, "r", encoding="utf-8") as progress_handle:
                content = progress_handle.read()
        except Exception as exc:
            return [], [f"Cannot read progress file '{self.progress_file}': {exc}"]
        markers = []
        errors = []
        for match in _LINE_BLOCK_PROGRESS_RE.finditer(content):
            marker = match.group(1).strip()
            if marker in markers:
                errors.append(f"Duplicate progress marker '{marker}'.")
            markers.append(marker)
        return markers, errors

    def _sync_batch_state(self, source_tasks, completed_tasks):
        notes = []
        self.batch_task.sync_source_task(source_tasks, notes, "Line-block source list changed.")
        self.batch_task.sync_gen_task(completed_tasks, notes, "Line-block progress updated.")
        self.batch_task.update_tbd_from_source()
        self.batch_task.update_cmp_from_tbd()
        if not self.batch_task.tbd_task_list:
            self.batch_task.update_current_tbd()
        return notes

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
            "progress_marker_mismatches": [],
            "configuration_errors": [],
        }

    def _add_validation_diagnostics(self, diagnostics, task, message):
        """Translate a line-map validation error into structured batch details."""
        if isinstance(message, dict):
            error_value = message.get("error", message)
        else:
            error_value = message
        error_text = str(error_value)
        if "Mapping file '" in error_text and "does not exist" in error_text:
            map_file = _mapping_file_for_source(
                self._split_line_block(task)[0], self.map_location, self.map_suffix
            )
            diagnostics["missing_mapping_files"].append(map_file)
        if "un-mapped line" in error_text:
            line_numbers = [int(value) for value in re.findall(r"(?:^|\n)\s*(\d+):", error_text)]
            diagnostics["uncovered_lines"].append({
                "line_block": _line_block_base(task),
                "lines": line_numbers,
            })
        if "not found in documentation" in error_text:
            diagnostics["unknown_ck"].append({
                "line_block": _line_block_base(task),
                "details": error_value,
            })
        if "block limit" in error_text or ("exceeds the" in error_text and "line" in error_text):
            diagnostics["oversized_ranges"].append({
                "line_block": _line_block_base(task),
                "details": error_value,
            })
        if "IGNORE mapping requires a reason comment" in error_text:
            diagnostics["unexplained_ignore"].append({
                "line_block": _line_block_base(task),
                "details": error_value,
            })

    def _line_block_content(self, task):
        """Return the physical lines for a task so Check can guide the LLM directly."""
        source_file, start_line, end_line = self._split_line_block(task)
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
                "error": f"Cannot read source file '{source_file}': {exc}",
            }
        if end_line > len(source_lines):
            return {
                "line_block": _line_block_base(task),
                "file": source_file,
                "start_line": start_line,
                "end_line": end_line,
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
            "content": indexed_content,
        }

    def _attach_line_block_content(self, result, tasks, key="current_line_block_contents"):
        """Attach source context to a structured Check/Complete response."""
        if not isinstance(result, dict):
            return result
        result[key] = [self._line_block_content(task) for task in tasks]
        return result

    def on_init(self):
        super().on_init()
        self._refresh_batch_state()
        return self

    def _refresh_batch_state(self):
        self._task_errors = []
        source_tasks = self._get_all_line_blocks()
        markers, marker_errors = self._progress_markers()
        self._task_errors.extend(marker_errors)
        current_by_base = {_line_block_base(task): task for task in source_tasks}
        previous_by_base = {
            _line_block_base(task): task for task in self.batch_task.gen_task_list
        }
        completed_tasks = []
        for marker in markers:
            current_task = current_by_base.get(marker)
            if current_task is None:
                continue
            previous_task = previous_by_base.get(marker)
            if previous_task is not None and _line_block_digest(previous_task) != _line_block_digest(current_task):
                self._task_errors.append(
                    f"Progress marker '{marker}' is stale because the source file content changed."
                )
                continue
            completed_tasks.append(current_task)
        self._sync_batch_state(source_tasks, completed_tasks)

    def get_template_data(self):
        """Return cached progress without scanning files or mutating batch state."""
        if not self._is_init:
            return {
                "TOTAL_LINE_BLOCKS": "-",
                "COMPLETED_LINE_BLOCKS": "-",
                "LINE_MAP_PROGRESS": "-/-",
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
            "CURRENT_LINE_BLOCKS": ", ".join(
                _line_block_base(task) for task in self.batch_task.tbd_task_list
            ),
            "MAX_LINE_BLOCK_LINES": self.max_block_lines,
        }

    def do_check(self, is_complete=False, **kw) -> tuple[bool, object]:
        """Validate the current line-map batch and advance the resumable task."""
        if not self._is_init:
            return False, {
                "error": (
                    "UnityChipBatchCheckerFileLineMap has not been initialized. "
                    "Wait for the stage on_init lifecycle before calling Check or Complete."
                ),
                "configuration_errors": ["Checker on_init has not run."],
            }
        self._refresh_batch_state()
        diagnostics = self._new_diagnostics()
        source_tasks = self.batch_task.source_task_list
        if self._task_errors:
            diagnostics["configuration_errors"].extend(
                error for error in self._task_errors
                if "Progress marker" not in error
            )
            diagnostics["progress_marker_mismatches"].extend(
                error for error in self._task_errors
                if "Progress marker" in error
            )
            return False, self._attach_line_block_content(
                {"error": self._task_errors, **diagnostics},
                self.batch_task.tbd_task_list,
            )
        if not source_tasks:
            markers, marker_errors = self._progress_markers()
            if markers or marker_errors:
                errors = list(marker_errors)
                errors.extend(
                    f"Progress marker '{marker}' does not match a current line block."
                    for marker in markers
                )
                diagnostics["progress_marker_mismatches"].extend(errors)
                return False, {"error": errors, **diagnostics}
            if self._source_files:
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
                    **diagnostics,
                }
            diagnostics["configuration_errors"].append(
                "No files matched the configured file_list."
            )
            return False, {
                "error": "No target line blocks found. Check the configured file_list and DUT files.",
                **diagnostics,
            }

        success, ck_list_or_msg = get_func_check_marks(self.workspace, self.func_check_file)
        if not success:
            return False, self._attach_line_block_content(
                ck_list_or_msg, self.batch_task.tbd_task_list
            )
        ck_list = ck_list_or_msg
        markers, marker_errors = self._progress_markers()
        current_by_base = {_line_block_base(task): task for task in source_tasks}
        unknown_markers = [marker for marker in markers if marker not in current_by_base]
        if marker_errors or unknown_markers:
            errors = list(marker_errors)
            errors.extend(f"Progress marker '{marker}' does not match a current line block." for marker in unknown_markers)
            diagnostics["progress_marker_mismatches"].extend(errors)
            return False, self._attach_line_block_content(
                {"error": errors, **diagnostics}, self.batch_task.tbd_task_list
            )

        current_batch = list(self.batch_task.tbd_task_list)
        current_batch_bases = [_line_block_base(task) for task in current_batch]
        source_bases = [_line_block_base(task) for task in source_tasks]
        current_indexes = [source_bases.index(task) for task in current_batch_bases if task in source_bases]
        first_current_index = min(current_indexes) if current_indexes else len(source_bases)
        allowed_marker_bases = set(source_bases[:first_current_index]) | set(current_batch_bases)
        future_markers = [marker for marker in markers if marker not in allowed_marker_bases]
        if future_markers:
            errors = [
                f"Progress marker '{marker}' belongs to a future line block; "
                "complete the current batch first."
                for marker in future_markers
            ]
            diagnostics["progress_marker_mismatches"].extend(errors)
            return False, {
                "error": errors,
                "current_batch": current_batch_bases,
                "progress": f"{len(markers)}/{len(source_tasks)}",
                **diagnostics,
                "current_line_block_contents": [
                    self._line_block_content(task) for task in current_batch
                ],
            }

        invalid_completed = []
        for task in markers:
            current_task = current_by_base.get(task)
            if current_task is None:
                continue
            valid, message = self._validate_line_block(current_task, ck_list)
            if not valid:
                invalid_completed.append({"line_block": task, "details": message})
                self._add_validation_diagnostics(diagnostics, current_task, message)
        if invalid_completed:
            diagnostics["progress_marker_mismatches"].extend(
                item["line_block"] for item in invalid_completed
            )
            return False, self._attach_line_block_content({
                "error": "Completed progress markers have invalid mappings.",
                "details": invalid_completed,
                **diagnostics,
            }, current_batch)

        missing_markers = [task for task in current_batch_bases if task not in markers]
        invalid_current = []
        for task in current_batch:
            valid, message = self._validate_line_block(task, ck_list)
            if not valid:
                invalid_current.append({"line_block": task, "details": message})
                self._add_validation_diagnostics(diagnostics, task, message)
        if missing_markers or invalid_current:
            result = {"error": "The current line-block batch is not complete."}
            if missing_markers:
                result["missing_progress_markers"] = missing_markers
                diagnostics["progress_marker_mismatches"].extend(
                    f"Missing progress marker for '{task}'." for task in missing_markers
                )
            if invalid_current:
                result["invalid_mappings"] = invalid_current
            result["current_batch"] = [_line_block_base(task) for task in current_batch]
            result["progress"] = f"{len(markers)}/{len(source_tasks)}"
            result.update(diagnostics)
            self._attach_line_block_content(result, current_batch)
            return False, result

        notes = []
        completed_tasks = [current_by_base[marker] for marker in markers]
        self.batch_task.sync_gen_task(completed_tasks, notes, "Line-block progress updated.")
        passed, result = self.batch_task.do_complete(
            notes,
            is_complete,
            "in the configured file_list",
            f"in {self.progress_file} and {self.map_location}",
            " Use the current line blocks shown in the task description.",
        )
        if isinstance(result, dict):
            result["current_batch"] = [_line_block_base(task) for task in current_batch]
            result["progress"] = f"{len(markers)}/{len(source_tasks)}"
            result["completed_line_blocks"] = len(markers)
            result["total_line_blocks"] = len(source_tasks)
            result["remaining_line_blocks"] = len(source_tasks) - len(markers)
            result.update(diagnostics)
            self._attach_line_block_content(result, current_batch)
            if self.batch_task.tbd_task_list:
                result["next_line_blocks"] = [
                    _line_block_base(task) for task in self.batch_task.tbd_task_list
                ]
                self._attach_line_block_content(
                    result, self.batch_task.tbd_task_list, "next_line_block_contents"
                )
        return passed, result
