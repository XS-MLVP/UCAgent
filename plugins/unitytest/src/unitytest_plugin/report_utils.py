"""UnityTest-only report, coverage, and markdown parsing helpers.

UnityChip coverage JSON parsing, test-report key cleanup, CK line-map and
markdown-header diffing used only by this plugin's checkers."""

import copy
import json
import os
import re
from collections import OrderedDict
from typing import List
from ucagent.util.functions import rm_workspace_prefix
from ucagent_common.doc_marks import rm_blank_in_str

def del_report_keys(report: dict, keys: List[str]) -> dict:
    """
    Delete specified keys from a report dictionary.
    :param report: The report dictionary.
    :param keys: List of keys to be deleted.
    :return: The modified report dictionary.
    """
    if not keys:
        return report
    for key in keys:
        if "." in key:
            sub_report = report
            parts = key.split(".")
            for p in parts[:-1]:
                if p in sub_report and isinstance(sub_report[p], dict):
                    sub_report = sub_report[p]
                else:
                    sub_report = None
                    break
            if sub_report is not None and parts[-1] in sub_report:
                del sub_report[parts[-1]]
        else:
            if key in report:
                del report[key]
    return report


def parse_line_ignore_file(file_path: str) -> dict:
    """Parse ignore lines from a file.

    Args:
        file_path (str): The path to the file to parse.
    Returns:
        dict: A dictionary with the ignore lines and their count.
    """
    ret = {
        "detail": [],
    }
    assert os.path.exists(file_path), f"File {file_path} does not exist."
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        for i, line in enumerate(lines):
            line = rm_blank_in_str(line).strip()
            if not line or line.startswith("#"):
                continue
            value = line.split("#", 1)[0].strip()
            ret["detail"].append({
                "line": i + 1,
                "value": value,
            })
    ret["count"] = len(ret["detail"])
    ret["marks"] = [d["value"] for d in ret["detail"]]
    return ret


def parse_un_coverage_json(file_path: str, workspace: str) -> dict:
    """Parse Unity test coverage data from a file.

    Args:
        file_path (str): The path to the file to parse (related to workspace).

    Returns:
        dict: A dictionary with the coverage data and statistics.
    """
    ret = OrderedDict({
        "lines_total": 0,
        "lines_covered": 0,
        "lines_uncovered": 0,
        "coverage_rate": 0.0,
        "uncoverage_detail": [],
    })
    if file_path.startswith(os.sep):
        file_path = file_path[1:]
    file_path = os.path.abspath(os.path.join(workspace, file_path))
    assert os.path.exists(file_path), f"File {file_path} does not exist."
    data = json.load(open(file_path, "r", encoding="utf-8"))
    ret["lines_total"] = data["overview"]["total"]["line"]
    ret["lines_uncovered"] = data["overview"]["miss"]["line"]
    ret["lines_covered"] = ret["lines_total"] - ret["lines_uncovered"]
    # Parse uncovered lines details
    un_covered = data.get("uncovered", {}).get("data", {})
    if ret["lines_total"] > 0:
        ret["coverage_rate"] = float(ret["lines_covered"]) / float(ret["lines_total"])
    if ret["lines_uncovered"] > 0 and un_covered:
        for cpath, data in un_covered.items():
            if data["total"]["line"] == 0:
                continue
            for module_name, cover_lines in data["modules"].items():
                if cover_lines["miss"]["line"] == 0:
                    continue
                cpath = rm_workspace_prefix(workspace, cpath)
                lines = cover_lines["line"]
                ret["uncoverage_detail"].append(OrderedDict({
                        "module_name": module_name,
                        "lines_uncovered": cpath  + ":" + ','.join(lines),
                    }))
    return ret


def clean_report_with_keys(
    report: dict,
    keys: list = None,
    default_keys=["all_check_point_list", "test_case_with_check_point_list"],
) -> dict:
    data = copy.deepcopy(report)
    target_keys = []
    if keys is not None:
        target_keys = keys
    return del_report_keys(data, list(set(target_keys + default_keys)))


def tips_of_get_coverage_data_path(dut_name: str):
    """Show the canonical per-test coverage path helper for fixture repairs."""
    return f"""
If 'get_coverage_data_path' not find in the template, you should define it like this (keep `from ucagent_common import test_utils` imported in this file):
def get_coverage_data_path(request, dut, new_path:bool):
    tc_name = request.node.name if request is not None else "{dut_name}"
    suffix = test_utils.get_default_subfix(dut, "coverage")
    return get_file_in_tmp_dir(request, current_path_file("data/"), f"{{tc_name}}.{{suffix}}", new_path=new_path)
"""


def markdown_headers(workspace, markdown_file, levels=(1, 2, 3, 4, 5, 6)):
    """Extract headers from a markdown file.
    Args:
        markdown_file: The path to the markdown file.
    Returns:
        A list of headers found in the markdown file.
    """
    if isinstance(levels, int):
        levels = (levels,)
    file_path = os.path.abspath(workspace + os.sep + markdown_file)
    if not os.path.isfile(file_path):
        raise Exception(f"File not found: {file_path}")
    pattern = re.compile(r"^(#{1,6})\s+(.*)", re.MULTILINE)
    headers = []
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
        matches = pattern.findall(content)
        for match in matches:
            level = len(match[0])
            if level in levels:
                title = match[1].strip()
                headers.append((level, title))
    return headers


def markdown_get_miss_headers(workspace, markdown_file, ref_markdown_file, levels=2):
    """Get missing headers from a markdown file.
    Args:
        markdown_file: The path to the markdown file.
        ref_markdown_file: The path to the reference markdown file.
        levels: The header levels to check (default is 2).
    Returns:
        A list of missing headers and diff messages.
    """

    def has_head(s_list, lev, t_head):
        for k, v in s_list:
            if k == lev and t_head in v:
                return True
        return False

    missed_msg = "Target headers:\n"
    missed_headers = []
    source_headers = markdown_headers(workspace, markdown_file, levels)
    for lev, head in markdown_headers(workspace, ref_markdown_file, levels):
        if not has_head(source_headers, lev, head):
            missed_headers.append((lev, head))
            missed_msg += f"Level {lev}, {head}: Missed\n"
        else:
            missed_msg += f"Level {lev}, {head}: Present\n"
    if missed_headers:
        missed_msg += "Source headers:\n"
        for lev, head in source_headers:
            missed_msg += f"Level {lev}, {head}\n"
    return missed_headers, missed_msg


def range_list_merge(range1: list, range2: list) -> list:
    """Merge two lists of ranges.

    Args:
        range1 (list): The first list of ranges.
        range2 (list): The second list of ranges.

    Returns:
        list: The merged list of ranges.
    """
    all_ranges = range1 + range2
    if not all_ranges:
        return []
    # Sort ranges by start line
    all_ranges.sort(key=lambda x: x[0])
    merged_ranges = []
    current_start, current_end = all_ranges[0]
    for start, end in all_ranges[1:]:
        if start <= current_end + 1:
            current_end = max(current_end, end)
        else:
            merged_ranges.append((current_start, current_end))
            current_start, current_end = start, end
    merged_ranges.append((current_start, current_end))
    return merged_ranges


def parse_line_CK_map_file(workspace, file_path: str) -> dict:
    """Parse mapped lines of CK from a file.

    Args:
        file_path (str): The path to the file to parse.
    Returns:
        dict: A dictionary with the CK and its mapped lines.
    """
    # mapped lines format:
    # FGROUP/FC-FUNCTION/CK-CHECK: line_start1-line_end1,line_start2-line_end2,...
    # eg:
    #  FGROUP1/FC-FUNCTION1/CK-CHECK1: 10-20,30-40,45-45
    ret = {}
    real_file_path = os.path.abspath(workspace + os.sep + file_path)
    assert os.path.exists(real_file_path), f"File {real_file_path} does not exist."
    with open(real_file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        for i, line in enumerate(lines):
            line = rm_blank_in_str(line).strip()
            if not line or line.startswith("#"):
                continue
            value = line.split("#", 1)[0].strip()
            assert ":" in value, f"{file_path} at line {i+1}: Missing ':' separator. Expected format 'FG-GROUP/FC-FUNCTION/CK-CHECK: line_start1-line_end1,...'"
            key, line_ranges_str = value.split(":", 1)
            key = key.strip()
            assert "/" in key, f"{file_path} at line {i+1}: Invalid key format. Expected 'FG-GROUP/FC-FUNCTION/CK-CHECK'. key: {key}"
            line_ranges = line_ranges_str.split(",")
            line_list = []
            for lr in line_ranges:
                lr = lr.strip()
                assert "-" in lr, f"{file_path} at line {i+1}: Invalid line range format '{lr}'. Expected 'line_start-line_end', eg: 10-20, 14-14"
                start_str, end_str = lr.split("-", 1)
                assert start_str.isdigit() and end_str.isdigit(), f"{file_path} at line {i+1}: Line range '{lr}' must contain integers"
                start_line = int(start_str)
                end_line = int(end_str)
                assert start_line <= end_line, f"{file_path} at line {i+1}: Line range '{lr}' start line must be less than or equal to end line"
                line_list.append((start_line, end_line))
            # Merge line ranges
            pre_list = []
            if key in ret:
                pre_list = ret[key]
            ret[key] = range_list_merge(pre_list, line_list)
    return ret


def get_un_mapped_lines(
    workspace, source_file: str, ck_line_map: dict, max_example_lines: int = 20
) -> list:
    """Get unmapped lines from a source file based on CK line mapping.

    Args:
        source_file (str): The path to the source file.
        ck_line_map (dict): The CK line mapping.

    Returns:
        list: A list of unmapped line numbers.
        example_str: eg: "1000: line_content\n1005: line_content\n..."
    """
    real_file_path = os.path.abspath(workspace + os.sep + source_file)
    assert os.path.exists(real_file_path), f"File {real_file_path} does not exist."
    with open(real_file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        total_lines = len(lines)
    range_list = []
    for _, v in ck_line_map.items():
        range_list.extend(v)
    range_list = range_list_merge([], range_list)
    mapped_lines = set()
    for start_line, end_line in range_list:
        for line_num in range(start_line, end_line + 1):
            mapped_lines.add(line_num)
    unmapped_lines = [line_num for line_num in range(1, total_lines + 1) if line_num not in mapped_lines]
    unmapped_lines = [line_num for line_num in unmapped_lines if lines[line_num -1].strip()]
    tline = "line"
    line_size = max([len(f"{line_num}") for line_num in unmapped_lines[:max_example_lines]] + [len(tline)])
    if len(unmapped_lines) > 0:
        example_str = f"{tline}: line_content\n"
        example_str += "\n".join(f"{line_num:>{line_size}}: {lines[line_num-1].rstrip()}" for line_num in unmapped_lines[:max_example_lines])
        if len(unmapped_lines) > max_example_lines:
            example_str += f"\n... (and {len(unmapped_lines) - max_example_lines} more lines)"
    else:
        example_str = "All lines are mapped."
    return unmapped_lines, example_str
