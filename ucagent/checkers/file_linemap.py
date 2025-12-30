#coding=utf-8
"""File line mapping checkers for UCAgent."""

import os
import traceback
from ucagent.checkers.base import Checker
import ucagent.util.functions as fc
from ucagent.util.log import info, warning


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


def line_map_check_one_file(workspace, source_file, map_file, ck_list, ck_list_file, map_suffix,
                            map_location, max_example_lines: int, must_has_no_miss_match: bool, cb_unmatch_ck=None, cb_match_ck=None):
    """Check one file for unmapped lines based on line-function mapping."""
    info(f"Checking line-function mapping for file '{source_file}'...")
    abs_source_file = os.path.abspath(workspace + os.path.sep + source_file)
    if not os.path.exists(abs_source_file):
        return False, {"error": f"Source file '{source_file}' does not exist."}
    if not map_file:
        map_file_name = source_file.replace(os.path.sep, "_").replace(".", "_") + map_suffix
        map_file = os.path.join(map_location + os.path.sep + map_file_name)
    if not os.path.exists(os.path.abspath(workspace + os.path.sep + map_file)):
        return False, {"error": f"Mapping file '{map_file}' does not exist. You should create it first."}
    try:
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
    # find un-mapped lines
    un_mapped_lines, detail_msg = fc.get_un_mapped_lines(
        workspace, source_file, line_ck_map, max_example_lines
    )
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
