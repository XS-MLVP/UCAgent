"""Shared pytest-report and test-case source checks for workflow plugins.

Report pass/fail gating, assert-presence validation, and test-case
location/block parsing shared by the unitytest and DesignWithPPA plugins."""

import os
import re
import traceback
from ucagent_common.str_utils import list_str_abbr
from ucagent.util.log import warning

def workspace_relative_path(workspace: str, path: str) -> str:
    """
    Convert an absolute or workspace-relative path to a workspace-relative path.

    Report producers may canonicalize symlinked directories differently from the
    UCAgent workspace path (for example /private/tmp/... vs /tmp/... on macOS).
    Prefer realpath/commonpath for strict prefix removal, then fall back to a
    unique path-suffix match inside the workspace for container/host path drift.
    """
    workspace_abs = os.path.abspath(workspace)
    workspace_real = os.path.realpath(workspace_abs)

    def _rel_if_under(abs_path: str, base_path: str):
        try:
            if os.path.commonpath([base_path, abs_path]) == base_path:
                rel_path = os.path.relpath(abs_path, base_path)
                return "." if rel_path == "." else rel_path
        except ValueError:
            return None
        return None

    def _path_parts(value: str):
        return [p for p in os.path.normpath(value).split(os.sep) if p and p != "."]

    def _common_path_suffix_len(left: str, right: str) -> int:
        left_parts = _path_parts(left)
        right_parts = _path_parts(right)
        score = 0
        for lpart, rpart in zip(reversed(left_parts), reversed(right_parts)):
            if lpart != rpart:
                break
            score += 1
        return score

    def _unique_suffix_match(path_for_match: str):
        if not os.path.isdir(workspace_abs):
            return None
        target_name = os.path.basename(path_for_match)
        if not target_name or target_name in (".", ".."):
            return None

        matches = []
        skip_dirs = {".git", ".pytest_cache", "__pycache__"}
        for root, dirs, files in os.walk(workspace_abs):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            if target_name not in files:
                continue
            rel_path = os.path.relpath(os.path.join(root, target_name), workspace_abs)
            score = _common_path_suffix_len(path_for_match, rel_path)
            if score > 0:
                matches.append((score, rel_path))
        if matches:
            max_score = max(score for score, _ in matches)
            best_matches = sorted({rel_path for score, rel_path in matches if score == max_score})
            if len(best_matches) == 1:
                return best_matches[0]
        return None

    normalized_path = os.path.normpath(str(path).replace("\\", os.sep))
    if os.path.isabs(normalized_path):
        path_abs = os.path.abspath(normalized_path)
        rel_path = _rel_if_under(path_abs, workspace_abs)
        if rel_path is not None:
            return rel_path

        path_real = os.path.realpath(path_abs)
        rel_path = _rel_if_under(path_real, workspace_real)
        if rel_path is not None:
            return rel_path

    else:
        rel_candidate = os.path.normpath(normalized_path)
        direct_path = os.path.abspath(os.path.join(workspace_abs, rel_candidate))
        rel_path = _rel_if_under(direct_path, workspace_abs)
        if rel_path is not None and os.path.exists(direct_path):
            return rel_path

    suffix_match = _unique_suffix_match(normalized_path.lstrip(os.sep))
    if suffix_match is not None:
        return suffix_match

    return normalized_path.lstrip(os.sep) if os.path.isabs(normalized_path) else normalized_path


def check_file_block(file_blocks, workspace, checker=None, strip_comments=True):
    """
    Check if the file blocks exist in the workspace.

    Args:
        file_blocks (dict): The file blocks to check. eg: {'file1.py': {"k1": [line_from, line_to], 'k2': [line_from, line_to]}, ...}
        workspace (str): The workspace directory.
        checker (callable, optional): A function to further check each code block. It should accept the file block string as input.
        strip_comments (bool): Remove comments before invoking checker. Disable for syntax-aware checkers.
    """
    assert isinstance(file_blocks, dict), "file_blocks must be a dictionary."
    ret_map = {}
    for f, blocks in file_blocks.items():
        f = workspace_relative_path(workspace, f)
        fpath = os.path.abspath(os.path.join(workspace, f))
        assert os.path.exists(fpath), f"File {f} does not exist in workspace {workspace}."
        if not blocks:
            continue
        assert isinstance(blocks, dict), f"Blocks for file {f} must be a dictionary."
        with open(fpath, "r", encoding="utf-8") as fr:
            lines = fr.readlines()
            line_count = len(lines)
        for k, v in blocks.items():
            assert isinstance(v, list) and len(v) == 2, f"Block {k} in file {f} must be a list of two integers [line_from, line_to]."
            line_from, line_to = v
            assert isinstance(line_from, int) and isinstance(line_to, int), f"Block {k} in file {f} must contain integers."
            assert 1 <= line_from <= line_count, f"Block {k} in file {f}: line_from {line_from} is out of range (1-{line_count})."
            assert 1 <= line_to <= line_count, f"Block {k} in file {f}: line_to {line_to} is out of range (1-{line_count})."
            assert line_from <= line_to, f"Block {k} in file {f}: line_from {line_from} must be less than or equal to line_to {line_to}."
        def _get_code_block_key(line_index):
            for k, v in blocks.items():
                line_from, line_to = v
                if line_from <= line_index <= line_to:
                    return k
            return None

        record_map = {k: "" for k in blocks.keys()}
        for index, line in enumerate(lines, start=1):
            block_key = _get_code_block_key(index)
            if block_key is None:
                continue
            # Text-based checkers historically ignore comments. Syntax-aware
            # checkers need the original line so strings containing '#' remain valid.
            if strip_comments:
                line = line.split("#", 1)[0]
            if not line.strip():
                continue
            if not line.endswith("\n"):
                line += "\n"
            record_map[block_key] += line
        if callable(checker):
            for k in blocks.keys():
                record_map[k] = checker(record_map[k])
        ret_map[f] = record_map
    return ret_map


def parse_test_case_location(tc, workspace=None):
    # file.py:xx-yy::[ClassName::]test_func
    tc_file, tc_name = tc.split("::", 1)
    tc_rfile, line_range = tc_file.rsplit(":", 1)
    if workspace is not None:
        tc_rfile = workspace_relative_path(workspace, tc_rfile)
    a, b = line_range.split("-", 1)
    assert a.isdigit() and b.isdigit(), f"Invalid line range in test case '{tc}'."
    return tc_rfile, int(a), int(b), tc_name


def tc_list_as_loc_blocks(func_list, target_tc_prefix="", ignore_tc_prefix="", workspace=None):
    func_file_blocks = {}
    for tc in func_list:
        tc_fname, (file_path, line_from, line_to) = parse_test_case_name(tc, workspace)
        tc_name = tc_fname.split("::", 1)[-1]
        if target_tc_prefix and not tc_name.startswith(target_tc_prefix):
            continue
        if ignore_tc_prefix and tc_name.startswith(ignore_tc_prefix):
            continue
        if file_path not in func_file_blocks:
            func_file_blocks[file_path] = {}
        func_file_blocks[file_path][tc] = [line_from, line_to]
    return func_file_blocks


def parse_test_case_name(tc, workspace=None):
    tc_rfile, line_from, line_to, tc_name = parse_test_case_location(tc, workspace)
    tc_file = tc_rfile.split("/tests/", 1)[-1]
    return f"{tc_file}::{tc_name}", (tc_rfile, line_from, line_to)


def check_source_code_in_tc(
    workspace, report, checker, target_tc_prefix="", ignore_tc_preifx=""
):
    """Check source code in test cases"""
    test_cases = report.get("tests", {}).get("test_cases", {})
    if target_tc_prefix:
        test_cases = {k : v for k, v in test_cases.items() if str(k.split("::")[-1]).startswith(target_tc_prefix)}
    if ignore_tc_preifx:
        test_cases = {k : v for k, v in test_cases.items() if not str(k.split("::")[-1]).startswith(ignore_tc_preifx)}
    if not test_cases:
        warning(f"no test cases find in test report")
        warning("target_tc_prefix: " + target_tc_prefix)
        warning("ignore_tc_preifx: " + ignore_tc_preifx)
        warning("raw test cases: " + ", ".join(report.get("tests", {}).get("test_cases", {}).keys()))
        return False, {"error": "[No Test Cases] No matching test cases found in the test report. Please check that test files exist and are named with 'test_' prefix, and that the filter prefix settings are correct."}
    # file.py:line1-line2::[class::]test_case_name
    # block fmt: {'file1.py': {"k1": [line_from, line_to], 'k2': [line_from, line_to]}, ...}
    file_blocks = {}
    for k in test_cases.keys():
        try:
            path, line_s, line_t, _ = parse_test_case_location(k, workspace)
            if path not in file_blocks:
                file_blocks[path] = {}
            file_blocks[path][k] = [int(line_s), int(line_t)]
        except Exception as e:
            raise ValueError(f"Invalid test case format '{k}'. Expected format: 'file.py:line1-line2::[class::]test_case_name'. Error: {e}")
    ret = {}
    for _, b in check_file_block(file_blocks, workspace, checker).items():
        ret.update(b)
    return True, ret


def check_has_assert_in_tc(workspace, report, target_tc_prefix="", ignore_tc_preifx=""):
    """Check tc has assert or not"""

    def has_assert(text_str):
        # Match real assertions only: full-line comments, identifier fragments
        # like ``asserted_count``, and unittest methods such as ``assertEqual``
        # must not satisfy the gate that the diagnostic text below promises.
        for line in text_str.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if re.search(r"\bassert\b|pytest\.raises\b", line):
                return True
        return False

    try:
        failed_tc = []
        ret, msg = check_source_code_in_tc(
            workspace, report, has_assert, target_tc_prefix, ignore_tc_preifx
        )
        if not ret:
            return ret, msg
        for k, v in msg.items():
            if not v:
                failed_tc.append(k)
        if not failed_tc:
            return True, "All test cases have assert statements."
        failed_str = list_str_abbr(failed_tc)
        return False, {
            "error": f"[Missing Assertions] The following {len(failed_tc)} test cases do not contain assert statements: {failed_str}. "
            + "[Problem] Every test case MUST contain at least one assert statement to verify DUT behavior, otherwise it cannot be determined whether the test truly passes. "
            + "[Solution] Add assertions in test functions, format: assert output == expected_output, 'error description'. "
            + "You can also use 'with pytest.raises(ExpectedException): ...' to verify exceptions. "
            + "Note: Do not use 'self.assertEqual' or other unittest methods; this framework only supports assert and pytest.raises.",
        }
    except Exception as e:
        warning(f"check_has_assert_in_tc error: {e}")
        warning(traceback.format_exc())
        return False, {"error": str(e)}


def is_run_report_pass(report, stdout, stderr):
    contract_failure = report.get("test_function_contract") if isinstance(report, dict) else None
    if contract_failure:
        return False, contract_failure
    run_pass = report.get("run_test_success", False)
    if run_pass:
        return True, ""
    return False, {
        "error": (
            "[Run Failed] Test execution or report generation failed. Read STDERR and "
            "STDOUT, fix the first concrete error at its reported file and line, then "
            "rerun the same tests. Do not edit the Bug document until "
            "run_test_success is true."
        ),
        "STDOUT": stdout,
        "STDERR": stderr,
    }
