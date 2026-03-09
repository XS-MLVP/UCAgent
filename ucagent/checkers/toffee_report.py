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
            confidence = int(labels[-1].split("-")[-1])
            if not (0 <= confidence <= 100):
                raise ValueError("Confidence must be 0-100")
        except (IndexError, ValueError):
            return False, f"[Invalid Confidence] Bug analysis document '{bug_analysis_file}': '{labels[-1]}' has invalid confidence value. " + \
                           "[Requirement] Confidence must be an integer between 0 and 100. " + \
                           "[Example] <BG-ERROR-OVERFLOW-75> means bug ERROR-OVERFLOW with 75% confidence."
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
        tc_list = [t for t in fc.get_unity_chip_doc_marks(os.path.join(workspace, bug_file), leaf_node="TC") \
                           if t.startswith(target_ck_prefix)]
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
            return False, f"[Confidence Parse Error] '{bug_label}' failed to parse ({str(e)}). [Correct Format] <BG-NAME-XX> where XX is a confidence integer from 0 to 100. Example: <BG-OVERFLOW-80> means 80% confidence."
        if len(tc_name_parts) < 2:
            return False, f"[Test Case Format Error] '{tc_name}' has incorrect format. [Correct Format] <TC-test_file.py::[ClassName::]test_case_name> where ClassName is optional. Example: <TC-test_add.py::test_overflow> or <TC-test_add.py::TestAdd::test_overflow>."
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
                        "2. Check if the test case should have failed but was incorrectly fixed (bug-triggering cases must fail)",
                        "3. If the test case is unrelated to the bug, remove the corresponding <TC-*> tag from the bug analysis document",
                        "4. If used as a placeholder, set the confidence to 0, e.g., <BG-NAME-0>",
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
                          "5. If used as a placeholder, set the confidence to 0, e.g., <BG-NAME-0>",
                       "Note: Bug-triggering test cases must have FAILED status (see Guide_Doc/dut_bug_analysis.md)"
                       ]
    # tc not mark their checkpoints
    tc_not_mark_the_cks_list = list(set(tc_not_mark_the_cks_list))
    if len(tc_not_mark_the_cks_list) > 0:
        ftc_msg = fc.list_str_abbr([f"{x[0]}(needs mark: {x[1]})" for x in tc_not_mark_the_cks_list])
        return False, [f"[Checkpoint Not Marked] Bug analysis document '{bug_file}' contains {len(tc_not_mark_the_cks_list)} test case(s) ({ftc_msg}) that have not called mark_function for their associated checkpoints.",
                       "[Cause] The test case is placed under a checkpoint in the bug analysis document, but the test code does not call mark_function for that checkpoint.",
                       "[Solution]",
                          "1. Ensure the test case is placed under the correct checkpoint in the bug analysis document",
                          "2. Call mark_function at the beginning of the test function, e.g.: env.dut.fc_cover['FG-XXX'].mark_function('FC-YYY', test_func, ['CK-ZZZ'])",
                          "3. If the test case relates to multiple function groups, call mark_function multiple times for each",
                          "4. If the test case is unrelated to this checkpoint, remove the corresponding <TC-*> tag from the bug analysis document",
                          "5. If the test case is unrelated to any checkpoint, consider removing it from the bug analysis document",
                        "Note: Failed test cases must mark the checkpoints related to the bugs they trigger (see Guide_Doc/dut_bug_analysis.md and Guide_Doc/dut_test_case.md)"
                       ]
    # fail tc not in bug doc
    if not target_ck_prefix:
        failed_tc = [k for k, v in failed_tc_maps.items() if not v]
        if failed_tc:
            return False, [f"[Undocumented Failed Cases] Found {len(failed_tc)} failed test case(s) not documented in the bug analysis file: {fc.list_str_abbr(failed_tc)}",
                           *fc.description_bug_doc(),
                           "[Solution]",
                           "1. Determine whether these failed cases actually triggered DUT bugs (failure = bug found)",
                           "2. If they are real bugs, document them with <TC-*> tags in the bug analysis document and perform root cause analysis",
                           "3. If they are not bugs but test code issues, fix the test cases so they pass",
                           f"Note: All failed test cases must be documented with <TC-*> tags in '{bug_file}', or the test code must be fixed to pass (see Guide_Doc/dut_bug_analysis.md)"
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
                                "1. Make sure you have called CovGroup.sample() to sample the failed check points in your test function or in StepRis/StepFal callback, otherwise the coverage cannot be collected correctly.",
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
        return False, f"[Unmarked Test Functions] {report['test_function_with_no_check_point_mark']} test function(s) are not associated with any checkpoint. " + \
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

    if report['unmarked_check_points'] > 0 and not only_marked_ckp_in_tc:
        unmark_check_points = [ck for ck in report['unmarked_check_point_list'] if ck.startswith(target_ck_prefix)]
        if len(unmark_check_points) > 0:
            return False, f"[Unassociated Checkpoints] The following {len(unmark_check_points)} checkpoint(s) have no associated test cases: `{fc.list_str_abbr(unmark_check_points)}`. " + \
                           "All checkpoints defined in the document must be associated with test cases via mark_function. " + \
                            fc.description_mark_function_doc() + \
                           "This ensures correct coverage mapping between documentation and test implementation. Please check the task requirements and complete the checkpoint marking.", -1

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
