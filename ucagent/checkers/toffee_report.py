# -*- coding: utf-8 -*-
"""Toffee report checker for UCAgent verification."""

from ucagent.util.log import warning, info
import ucagent.util.functions as fc
import os
import traceback


def get_bug_ck_list_from_doc(workspace: str, bug_analysis_file: str, target_ck_prefix:str):
    """Parse bug analysis documentation to extract marked bug analysis points."""
    try:
        marked_bugs = fc.get_unity_chip_doc_marks(os.path.join(workspace, bug_analysis_file), leaf_node="BG")
    except Exception as e:
        warning(traceback.format_exc())
        return False, [f"Bug analysis documentation parsing failed for file '{bug_analysis_file}': {str(e)}. " + \
                        "Common issues:",
                        "1. Malformed bug analysis tags.",
                        *fc.description_bug_doc(),
                        "2. Invalid confidence rating format.",
                        "3. Encoding or syntax errors.",
                        "Please review and fix the bug analysis documentation format."]
    marked_bug_checks = []
    # bugs: FG/FC/CK/BG
    for c in marked_bugs:
        if not c.startswith(target_ck_prefix):
            continue
        labels = c.split("/")
        if not labels[-1].startswith("BG-"):
            return False, f"Invalid bug analysis format in '{bug_analysis_file}': mark '{c}' missing 'BG-' prefix. " + \
                           "Correct format: <FG-GROUP>/<FC-FUNCTION>/<CK-CHECK>/<BG-NAME-XX>/<TC-TESTCASE>. " + \
                           "Example: <BG-NAME-80> indicates 80% confidence that this is a DUT bug. " + \
                           "Please ensure all bug analysis marks follow this format. "
        try:
            confidence = int(labels[-1].split("-")[-1])
            if not (0 <= confidence <= 100):
                raise ValueError("Confidence must be 0-100")
        except (IndexError, ValueError):
            return False, f"Invalid confidence rating in '{bug_analysis_file}': '{labels[-1]}'. " + \
                           "Confidence ratings must be integers between 0-100. " + \
                           "Example: <BG-ERROR-OVERFLOW-75> for 75% confidence for bug 'ERROR-OVERFLOW'. "
        marked_bug_checks.append("/".join(labels[:-1]))
    return True, marked_bug_checks


def get_doc_ck_list_from_doc(workspace: str, doc_file: str, target_ck_prefix:str):
    try:
        marked_checks = fc.get_unity_chip_doc_marks(os.path.join(workspace, doc_file), leaf_node="CK")
    except Exception as e:
        return False, [f"Documentation parsing failed for file '{doc_file}': {str(e)}. Common issues:",
                        "1. Malformed tags (ensure proper <FG-*>, <FC-*>, <CK-*> format).",
                        *fc.description_func_doc(),
                        "2. Encoding issues or special characters.",
                        "3. Invalid document structure.",
                        "Please review your documentation format and fix any syntax errors."]
    return True, [v for v in marked_checks if v.startswith(target_ck_prefix)]


def check_bug_tc_analysis(workspace:str, checks_in_tc:list, bug_file:str, target_ck_prefix:str, failed_tc_and_cks: dict, passed_tc_list: list, only_marked_ckp_in_tc: bool):
    try:
        tc_list = [t for t in fc.get_unity_chip_doc_marks(os.path.join(workspace, bug_file), leaf_node="TC") \
                           if t.startswith(target_ck_prefix)]
    except Exception as e:
        warning(traceback.format_exc())
        return False, [f"Bug analysis documentation parsing failed for file '{bug_file}': {str(e)}. " + \
                        "Common issues:",
                        "1. Malformed bug analysis tags.",
                        *fc.description_bug_doc(),
                        "2. Invalid confidence rating format.",
                        "3. Encoding or syntax errors.",
                        "Please review and fix the bug analysis documentation format."]
    failed_tc_names = failed_tc_and_cks.keys()
    failed_tc_maps = {k:False for k in failed_tc_names}
    def is_in_target_tc_names(fracs, name_list):
        for fname in name_list:
            all_in = True
            for p in fracs:
                if p not in fname:
                    all_in = False
                    break
            if all_in:
                return True, fname
        return False, ""
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
            return False, f"Bug ({bug_label}) confidence parse fail ({str(e)}), its format should be: <BG-NAME-XX> where XX is the confidence rate from 0 to 100."
        if len(tc_name_parts) < 2:
            return False, f"Test case ({tc_name}) parse fail, its format shuold be: <TC-test_file.py::[ClassName]::test_case_name> where ClassName is optional, eg: <TC-test_file.py::test_my_case>."
        is_zero_bug = (bug_rate == 0)
        is_fail_tc, fail_tc_name = is_in_target_tc_names(tc_name_parts, failed_tc_names)
        # failed tc
        if is_fail_tc:
            failed_tc_maps[fail_tc_name] = True
            if checkpoint not in failed_tc_and_cks[fail_tc_name]:
                tc_not_mark_the_cks_list.append((fail_tc_name, checkpoint))
        else:
            if not is_zero_bug:
                tc_not_found_in_ftc_list.append((tc_name, bug_label))
        # passed tc
        is_pass_tc, pass_tc_name = is_in_target_tc_names(tc_name_parts, passed_tc_list)
        if is_pass_tc and not is_fail_tc and not is_zero_bug:
            tc_found_in_ptc_list.append((tc_name, pass_tc_name))

    if len(ck_not_found_in_report) > 0:
        msg = fc.list_str_abbr(ck_not_found_in_report)
        return False, f"Bug analysis documentation '{bug_file}' contains {len(ck_not_found_in_report)} check points ({msg}) which are not found in the test report. " + \
                       "Ensure the check point labels (include the <FG-*>, <FC-*> labels) in the bug analysis documentation are defined in the function coverage."

    # tc in pass tc
    tc_found_in_ptc_list = list(set(tc_found_in_ptc_list))
    if len(tc_found_in_ptc_list) > 0:
        ptc_msg = fc.list_str_abbr([f"{x[0]}(location: {x[1]})" for x in tc_found_in_ptc_list])
        return False, [f"Bug analysis documentation '{bug_file}' contains {len(tc_found_in_ptc_list)} test cases ({ptc_msg}) which should be 'FAILED' but found to be 'PASSED'.",
                       "Actions required:",
                        "1. Make sure the bug analysis documentation marks the right test cases for each bug.",
                        "2. Ensure the test cases is working correctly and 'FAILED' as expected.",
                        "3. If the test cases are not related to any bugs, please remove them from the bug analysis documentation.",
                        "4. If this is a placeholder for failed checkpoints, please set the bug confidence to zero using <BG-NAME-0>.",
                       "Note: those test cases indicate a bug must be 'FAILED'"
                       ]
    # tc not found in fail tcs
    tc_not_found_in_ftc_list = list(set(tc_not_found_in_ftc_list))
    if len(tc_not_found_in_ftc_list) > 0 and not only_marked_ckp_in_tc:
        ftc_msg = fc.list_str_abbr([f"{x[0]}(documented below {x[1]})" for x in tc_not_found_in_ftc_list])
        return False, [f"Bug analysis documentation '{bug_file}' contains {len(tc_not_found_in_ftc_list)} test cases ({ftc_msg}) which are not found in the failed test cases.",
                       "Actions required:",
                          "1. Ensure the test case names in the documentation match exactly with those in the test python file.",
                          "2. If the test cases are based on classes, ensure the class names are included in the <TC-*> tags, e.g., <TC-test_example.py::TestClassName::test_function_name>.",
                          "3. If the test cases have no relation to the bug, please remove them from the bug analysis documentation.",
                          "4. The test python file in <TC-*> must be the same as the actual test file name.",
                          "5. If this is a placeholder for failed test cases, please set the bug confidence to zero using <BG-NAME-0>.",
                       "Note: those test cases indicate a bug must be 'FAILED'"
                       ]
    # tc not mark their checkpoints
    tc_not_mark_the_cks_list = list(set(tc_not_mark_the_cks_list))
    if len(tc_not_mark_the_cks_list) > 0:
        ftc_msg = fc.list_str_abbr([f"{x[0]}(need mark: {x[1]})" for x in tc_not_mark_the_cks_list])
        return False, [f"Bug analysis documentation '{bug_file}' contains {len(tc_not_mark_the_cks_list)} test cases ({ftc_msg}) which are not marking the checkpoints which reference them in the analysis file.",
                       "Actions required:",
                          "1. Make sure you have placed the test case analysis in the right position under the corresponding checkpoint in the bug analysis documentation.",
                          "2. Ensure the test cases in the bug analysis documentation are marking all relevant checkpoints that they are testing.",
                          "3. If a test case is supposed to validate a bug related specific checkpoint, ensure it use 'mark_function' to mark the checkpoint.",
                          "4. If a test case is related to multiple function points, ensure all relevant function and checkpoint are marked (call 'mark_function' for each function point).",
                          "5. If the test case does not relate to any specific checkpoint, consider deleting it from the bug analysis documentation.",
                        "Note: those failed test cases must mark their bug related checkpoint"
                       ]
    # fail tc not in bug doc
    if not target_ck_prefix:
        failed_tc = [k for k, v in failed_tc_maps.items() if not v]
        if failed_tc:
            return False, [f"Find undocumented failed test cases: {fc.list_str_abbr(failed_tc)}",
                           *fc.description_bug_doc(),
                           "Actions required:",
                           "1. Make sure the failed test cases are properly implemented and are indeed failing due to DUT bugs.",
                           "2. If they are valid failed test cases, document them in the bug analysis documentation using <TC-*> tags.",
                           "3. If they are not related to any bugs, consider fixing the test cases or removing them if they are obsolete.",
                           f"Note: all failed test cases must indicate bugs and be documented in file '{bug_file}' witch <TC-*> marks"
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
                return False, [f"{len(un_related_tc_marks)} unanalyzed failed checkpoints (its check function is not called/sampled or the return not true) detected: {fc.list_str_abbr(un_related_tc_marks)}. " + \
                               f"The failed checkpoints must be properly analyzed and documented in file '{bug_analysis_file}'. Options:",
                                "1. Make sure you have called CovGroup.sample() to sample the failed check points in your test function or in StepRis/StepFail callback, otherwise the coverage cannot be collected correctly.",
                                "2. Make sure the check function of these checkpoints to ensure they are correctly implemented and returning the expected results.",
                                "3. If these are actual DUT bugs, document them use marks '<FG-*>, <FC-*>, <CK-*>, <BG-*>, <TC-*>' in '{}' with confidence bug ratings.".format(bug_analysis_file),
                                *fc.description_bug_doc(),
                                "4. If these are implicitly covered the marked test cases, you can use arbitrary <checkpoint> function 'lambda x:True' to force pass them (need document it in the comments).",
                                "5. Review the related checkpoint's check function, the test implementation and the DUT behavior to determine root cause.",
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
            return False, [f"Documentation inconsistency: Test implementation contains {len(ck_not_in_doc)} undocumented check points: {fc.list_str_abbr(ck_not_in_doc)}. " + \
                            "These check points are used in tests but not defined in documentation file '{}'. ".format(doc_file) + \
                            "Action required:",
                            "1. Add missing check points to the documentation with proper <CK-*> tags.",
                            "2. Or remove unused check points from test implementation (defined in the function coverage groups).",
                            "3. Ensure consistency between test logic and the documentation."]
    if check_doc_in_tc:
        ck_not_in_tc = []
        for ck in doc_checks:
            if ck not in test_case_checks:
                ck_not_in_tc.append(ck)
        if len(ck_not_in_tc) > 0:
            info(f"Check points in test function: {fc.list_str_abbr(test_case_checks)}")
            return False, [f"Test coverage gap: Documentation({doc_file}) has defined {len(ck_not_in_tc)} check points, but they are not defined in the test coverage groups: {fc.list_str_abbr(ck_not_in_tc)} " + \
                            "These check points are documented but missing from test implementation. " + \
                            "Action required:",
                            "1. Define those check points in the function coverage groups.",
                            "2. Or delete obsolete check points from documentation.",
                            "3. Ensure the check points in both test cases and documentation are consistent."]

    return True, f"Function/check points documentation ({doc_file}) is consistent with test cases."


def check_report(workspace, report, doc_file, bug_file, target_ck_prefix="",
                 check_tc_in_doc=True, check_doc_in_tc=True, post_checker=None, only_marked_ckp_in_tc=False,
                 check_fail_ck_in_bug=True, func_RunTestCases=None, timeout_RunTestCases=0):
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
    Returns:
        A tuple indicating the success or failure of the check, along with an optional message.
    """

    ret, doc_ck_list = get_doc_ck_list_from_doc(workspace, doc_file, target_ck_prefix)
    if not ret:
        return ret, doc_ck_list, -1
    if report["test_function_with_no_check_point_mark"] > 0:
        unmarked_functions = report['test_function_with_no_check_point_mark_list']
        mark_function_desc = fc.description_mark_function_doc(unmarked_functions, workspace, func_RunTestCases=func_RunTestCases, timeout_RunTestCases=timeout_RunTestCases)
        return False, f"Test function mapping incomplete: {report['test_function_with_no_check_point_mark']} test functions not associated with check points. " + \
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
        return False, "Test report structure validation failed: No test cases found in the report. " +\
                      "Please ensure that the test report is generated correctly.", -1
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

    if report['unmarked_check_points'] > 0 and not only_marked_ckp_in_tc:
        unmark_check_points = [ck for ck in report['unmarked_check_point_list'] if ck.startswith(target_ck_prefix)]
        if len(unmark_check_points) > 0:
            return False, f"Test case validation failed, cannot find the follow {len(unmark_check_points)} check points: `{fc.list_str_abbr(unmark_check_points)}` " + \
                           "in the test cases. All check points defined in the documentation must be associated with test cases using 'mark_function'. " + \
                            fc.description_mark_function_doc() + \
                           "This ensures proper coverage mapping between documentation and test implementation. " + \
                           "Review your task requirements and complete the check point markings. ", -1

    if callable(post_checker):
        ret, msg = post_checker(report)
        if not ret:
            return ret, msg, -1

    return True, "All failed test functions are properly marked in bug analysis documentation.", bug_ck_list_size



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
        return False, f"Line coverage result json file `{file_cover_json}` not found in workspace `{workspace}`. Please ensure the coverage data is generated and available." , 0.0

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
                return False, f"Line coverage ignore file ({file_ignore}) contains {len(error_igs)} invalid ignore patterns (must start with '*/'): `{emessage}`. " + \
                              "Please correct the ignore patterns to start with '*/', e.g., '*/{DUT}/{DUT}.v:18-20,50-50' which means the lines from 18-20 and line 50 in file {DUT}/{DUT}.v should be ignored.", \
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
                return False, f"Line coverage ignore file ({file_ignore}) contains {len(error_igs)} invalid ignore patterns (line number format error): `{emessage}`. " + \
                              "Please correct the ignore patterns to use the format 'line_number_start-line_number_end', e.g., '*/{DUT}/{DUT}.v:18-20,50-50' which means the lines from 18-20 and line 50 in file {DUT}/{DUT}.v should be ignored.", \
                                0.0
            file_analyze_md_path = os.path.join(workspace, file_analyze_md)
            if not os.path.exists(file_analyze_md_path):
                return False, f"Line coverage analysis documentation file ({file_analyze_md}) not found in workspace `{workspace}`. Please ensure the documentation is available. " + \
                              f"Note if there are patterns (find: `{fc.list_str_abbr(igs)}`) in ignore file ({file_ignore}), the analysis document ({file_analyze_md}) is required to explain why these lines are ignored.", \
                                0.0
            doc_igs = fc.parse_marks_from_file(file_analyze_md_path, "LINE_IGNORE").get("marks", [])
            un_doced_igs = []
            for ig in igs:
                if ig not in doc_igs:
                    un_doced_igs.append(ig)
            if len(un_doced_igs) > 0:
                return False, f"Line coverage analysis documentation ({file_analyze_md}) does not contain those 'LINE_IGNORE' marks: `{fc.list_str_abbr(un_doced_igs)}`. " + \
                              f"Please document the ignore patterns in the analysis document to explain why these lines are ignored by <LINE_IGNORE>pattern</LINE_IGNORE>.", \
                                0.0

    cover_data = fc.parse_un_coverage_json(file_cover_json, workspace)  # just to check if the json is valid
    cover_rate = cover_data.get("coverage_rate", 0.0)
    if cover_rate < min_line_coverage:
        return False, {"error": [f"Line coverage {cover_rate*100.0:.2f}% is below the minimum threshold of {min_line_coverage*100.0:.2f}%. Please improve the test coverage to meet the required standard."
                                  "Actionable steps to improve coverage:",
                                  "1. Review the un-covered lines in the coverage report.",
                                  "2. Identify missing test cases that can cover these lines or find the existing test cases that should be enhanced.",
                                  "3. Implement additional test cases to cover the un-covered lines or refine existing ones.",
                                  "4. If certain lines are intentionally un-covered (e.g., deprecated code, third-party libraries), " + \
                                      f"ignore them in the ignore file ({file_ignore}) and document the reasons in the analysis documentation ({file_analyze_md}) using <LINE_IGNORE> tags.",
                                  "5. Re-run the tests and coverage analysis to verify that the coverage meets or exceeds the minimum threshold.",
                                  "Note: When ignoring lines, ensure that the ignore patterns start with '*/', like '*/{DUT}/{DUT}.v:18-20,50-60' which means the lines from 18-20,50-60 in file {DUT}/{DUT}.v should be ignored."
                                 ],
                       "uncoverage_info": cover_data
                       }, cover_rate

    if callable(post_checker):
        ret, msg = post_checker(cover_data)
        if not ret:
            return ret, msg, cover_rate

    return True, f"Line coverage check passed (line coverage: {cover_rate*100.0:.2f}% >= {min_line_coverage*100.0:.2f}%).", cover_rate
