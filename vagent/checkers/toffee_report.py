# -*- coding: utf-8 -*-
"""Toffee report checker for UCAgent verification."""

from vagent.util.log import warning, info
import vagent.util.functions as fc
import os
import traceback


def get_bug_ck_list_from_doc(workspace: str, bug_analysis_file: str, target_ck_prefix:str):
    """Parse bug analysis documentation to extract marked bug analysis points."""
    try:
        marked_bugs = fc.get_unity_chip_doc_marks(os.path.join(workspace, bug_analysis_file), leaf_node="BUG-RATE")
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
    for c in marked_bugs["marks"]:
        if not c.startswith(target_ck_prefix):
            continue
        labels = c.split("/")
        if not labels[-1].startswith("BUG-RATE-"):
            return False, f"Invalid bug analysis format in '{bug_analysis_file}': mark '{c}' missing 'BUG-RATE-' prefix. " + \
                           "Correct format: <FG-GROUP>/<FC-FUNCTION>/<CK-CHECK>/<BUG-RATE-XX>. " + \
                           "Example: <BUG-RATE-80> indicates 80% confidence that this is a DUT bug. " + \
                           "Please ensure all bug analysis marks follow this format. "
        try:
            confidence = int(labels[-1].split("BUG-RATE-")[1])
            if not (0 <= confidence <= 100):
                raise ValueError("Confidence must be 0-100")
        except (IndexError, ValueError):
            return False, f"Invalid confidence rating in '{bug_analysis_file}': '{labels[-1]}'. " + \
                           "Confidence ratings must be integers between 0-100. " + \
                           "Example: <BUG-RATE-75> for 75% confidence. "
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
    return True, [v for v in marked_checks["marks"] if v.startswith(target_ck_prefix)]


def check_bug_analysis(failed_check: list, marked_bug_checks:list, bug_analysis_file: str,
                       check_tc_in_doc=True, check_doc_in_tc=True,
                       failed_funcs_failed_bins: dict=None, failed_funcs_passed_bins: dict=None, target_ck_prefix=""):
    """Check failed checkpoint in bug analysis documentation."""
    bin_in_failed_tc = []
    if failed_funcs_failed_bins:
        for _, cks in failed_funcs_failed_bins.items():
            for cb in cks:
                if cb not in bin_in_failed_tc:
                    bin_in_failed_tc.append(cb.strip())
    if failed_funcs_passed_bins:
        for _, cks in failed_funcs_passed_bins.items():
            for cb in cks:
                if cb not in bin_in_failed_tc:
                    bin_in_failed_tc.append(cb.strip())
    bin_in_failed_tc = list(set(bin_in_failed_tc))
    if check_doc_in_tc:
        un_related_bug_marks = []
        un_failedt_bug_marks = []
        for ck in marked_bug_checks:
            if ck not in failed_check:
                un_related_bug_marks.append(ck)
            if ck not in bin_in_failed_tc:
                un_failedt_bug_marks.append(ck)
        if len(un_related_bug_marks) > 0 and False: # FIXME: disable this check for now, bug related marks no need to be failed in test report
            info(f"All check points in test report: {', '.join(failed_check)}")
            return False, [f"Documentation inconsistency: Bug analysis documentation '{bug_analysis_file}' contains bug check points: {', '.join(un_related_bug_marks)} they are not failed in test cases. " + \
                            "Please ensure all bug analysis marks correspond to actual test failures. Action required:",
                            "1. Update the bug analysis documentation to include all relevant test failures.",
                            "2. Ensure that all bug analysis marks are properly linked to their corresponding test cases.",
                            "3. Review the test cases to ensure they are correctly identifying and reporting DUT bugs."
                            ]
        if len(un_failedt_bug_marks) > 0:
            info(f"Bins in failed tests: {', '.join(bin_in_failed_tc)}")
            return False, [f"Documentation inconsistency: Bug analysis documentation '{bug_analysis_file}' contains {len(un_failedt_bug_marks)} bug check points ({', '.join(un_failedt_bug_marks)}) which are not found in the failed test case functions. " + \
                            "Please ensure all bug analysis marks correspond to actual test failures. Action required:",
                            "1. Check if they are mistakenly added in the bug analysis documentation. If so, remove them from the documentation.",
                            "2. If they are valid bug analysis marks, ensure they are properly marked (use mark_function) to their corresponding test cases (those test functions need to be failed).",
                            "3. Make sure you have called CovGroup.sample() to sample the coverage group in your test function or in StepRis/StepFail callback, otherwise the coverage cannot be collected correctly.",
                            "4. If the checkpoints related bug is not consistently reproducible by the test case, please consider mark them in a must `Fail` test function with description (eg: Assert False, '<bug description>').",
                           f"Note: Bug related checkpoints described in '{bug_analysis_file}' must be marked in at least one `Failed` test function, otherwise it is meaningless."
                            ]

    if check_tc_in_doc:
        un_related_tc_marks = []
        for ck in failed_check:
            if ck not in marked_bug_checks:
                un_related_tc_marks.append(ck)
        if len(un_related_tc_marks) > 0:
                return False, [f"{len(un_related_tc_marks)} Unanalyzed failed checkpoints (its check function is not called/sampled or the return not true) detected: {', '.join(un_related_tc_marks)}. " + \
                                "The failed checkpoints must be properly analyzed and documented. Options:",
                                "1. Make sure you have called CovGroup.sample() to sample the failed check points in your test function or in StepRis/StepFail callback, otherwise the coverage cannot be collected correctly.",
                                "2. Make sure the check function of these checkpoints to ensure they are correctly implemented and returning the expected results.",
                                "3. If these are actual DUT bugs, document them use marks '<FG-*>, <FC-*>, <CK-*>, <BUG-RATE-*>' in '{}' with confidence ratings.".format(bug_analysis_file),
                                *fc.description_bug_doc(),
                                "5. If these are implicitly covered the marked test cases, you can use arbitrary <checkpoint> function 'lambda x:True' to force pass them (need document it in the comments).",
                                "6. Review the related checkpoint's check function, the test implementation and the DUT behavior to determine root cause.",
                                "Note: Checkpoint is always referenced like `FG-*/FC-*/CK-*` by the `Check` and `Complete` tools, eg: `FG-LOGIC/FC-ADD/CK-BASIC`， but in the `*.md` file you should use the format: '<FG-*>, <FC-*>, <CK-*>"
                                ]
    if failed_funcs_failed_bins is not None:
        un_buged_cks = {}
        for func, checks in failed_funcs_failed_bins.items():
            for cb in checks:
                if not cb.startswith(target_ck_prefix):
                    continue
                if cb not in marked_bug_checks:
                    # record the function name for each unbuged checkpoint
                    if cb not in un_buged_cks:
                        un_buged_cks[cb] = []
                    un_buged_cks[cb].append(func)
        if len(un_buged_cks) > 0:
            info(f"Current analyzed checkpoints: {', '.join(marked_bug_checks)} in '{bug_analysis_file}'")
            return False, [f"The following ({len(un_buged_cks)}) failed checkpoints marked in failed test functions are not unanalyzed in the bug analysis file '{bug_analysis_file}':",
                         *[f"  Failed check point `{k}` in failed test functions: {', '.join(v)}" for k, v in un_buged_cks.items()],
                           "You need:",
                           "1. Make sure you have called CovGroup.sample() to sample the failed check points in your test function or in StepRis/StepFail callback, otherwise the coverage cannot be collected correctly.",
                           "2. Make sure the check function of these checkpoints to ensure they are correctly implemented and returning the expected results.",
                           "3. If these checkpoints are valid and indicate DUT bugs, document them in the bug analysis file with appropriate marks.",
                           "4. If these checkpoints are not related to the test function, delete them in 'mark_function' and make them `Pass` in other ways (eg: use a lambda check function that always returns True).",
                           "5. Review the failed test cases to ensure they are correctly identifying and reporting DUT bugs.",
                           "when you document the checkpoints need use the correct format: <FG-*>, <FC-*>, <CK-*>, <BUG-RATE-*>",
                           *fc.description_bug_doc()
                           ]
    return True, f"Bug analysis documentation '{bug_analysis_file}' is consistent with test results."


def check_doc_struct(test_case_checks:list, doc_checks:list, doc_file:str, check_tc_in_doc=True, check_doc_in_tc=True):
    if check_tc_in_doc:
        ck_not_in_doc = []
        for ck in test_case_checks:
            if ck not in doc_checks:
                ck_not_in_doc.append(ck)
        if len(ck_not_in_doc) > 0:
            return False, [f"Documentation inconsistency: Test implementation contains {len(ck_not_in_doc)} undocumented check points: {', '.join(ck_not_in_doc)}. " + \
                            "These check points are used in tests but not defined in documentation file '{}'. ".format(doc_file) + \
                            "Action required:",
                            "1. Add missing check points to the documentation with proper <CK-*> tags.",
                            "2. Or remove unused check points from test implementation.",
                            "3. Ensure consistency between test logic and functional requirements."]
    if check_doc_in_tc:
        ck_not_in_tc = []
        for ck in doc_checks:
            if ck not in test_case_checks:
                ck_not_in_tc.append(ck)
        if len(ck_not_in_tc) > 0:
            info(f"Check points in test function: {', '.join(test_case_checks)}")
            return False, [f"Test coverage gap: Documentation({doc_file}) defines {len(ck_not_in_tc)} check points not implemented in tests: {', '.join(ck_not_in_tc)} " + \
                            "These check points are documented but missing from test implementation. " + \
                            "Action required:",
                            "1. Implement test cases that cover these check points.",
                            "2. Use proper mark_function() calls to associate tests with check points. In the test case function like: dut.fc_cover['FG-GROUP'].mark_function('FC-FUNCTION', test_function_name, ['CK-CHECK1', 'CK-CHECK2']).",
                            "3. Ensure complete functional coverage as specified in documentation."]

    return True, f"Function/check points documentation ({doc_file}) is consistent with test cases."


def check_report(workspace, report, doc_file, bug_file, target_ck_prefix="", check_tc_in_doc=True, check_doc_in_tc=True, post_checker=None, only_marked_ckp_in_tc=False):
    """Check the test report against documentation and bug analysis.

    Args:
        workspace: The workspace directory.
        report: The test report to check.
        doc_file: The documentation file to check against.
        bug_file: The bug analysis file to check against.
        target_ck_prefix: The target check point prefix to filter checks.
        need_check_bug_analysis: Whether to check bug analysis.
        check_tc_in_doc: Whether to check test cases in documentation.
        check_doc_in_tc: Whether to check documentation in test cases.
        post_checker: An optional post-checker function.
        only_marked_ckp_in_tc: Whether to only consider marked check points in test cases.

    Returns:
        A tuple indicating the success or failure of the check, along with an optional message.
    """

    ret, doc_ck_list = get_doc_ck_list_from_doc(workspace, doc_file, target_ck_prefix)
    if not ret:
        return ret, doc_ck_list
    if report["test_function_with_no_check_point_mark"] > 0:
        unmarked_functions = report['test_function_with_no_check_point_mark_list']
        return False, [f"Test function mapping incomplete: {report['test_function_with_no_check_point_mark']} test functions not associated with check points: {', '.join(unmarked_functions)}. " + \
                        "Action required:",
                        "1. Add mark_function() calls to associate these functions with appropriate check points, like: dut.fc_cover['FG-GROUP'].mark_function('FC-FUNCTION', test_function_name, ['CK-CHECK1', 'CK-CHECK2']).",
                        "2. Ensure every test function validates specific documented functionality.",
                        "3. Review test organization and ensure complete traceability."]

    checks_in_tc  = [b for b in report.get("bins_all", []) if b.startswith(target_ck_prefix)]
    if len(checks_in_tc) == 0:
        warning(f"No test functions found for check point prefix '{target_ck_prefix}'. Please ensure test cases are correctly marked with this prefix.")
        warning(f"Current test check points: {', '.join(report.get('bins_all', []))}")
    ret, msg = check_doc_struct(checks_in_tc, doc_ck_list, doc_file, check_tc_in_doc=check_tc_in_doc, check_doc_in_tc=check_doc_in_tc)
    if not ret:
        return ret, msg

    checks_tc_fail = [b for b in report.get("failed_check_point_list", []) if b.startswith(target_ck_prefix)]
    marked_check_points = [c for c in checks_in_tc if c not in report.get("unmarked_check_points_list", [])]
    if only_marked_ckp_in_tc:
        checks_tc_fail = [b for b in checks_tc_fail if b in marked_check_points]
    failed_funcs_failed_bins = report.get("failed_funcs_failed_bins", {})
    failed_funcs_passed_bins = report.get("failed_funcs_passed_bins", {})
    if len(checks_tc_fail) > 0 or os.path.exists(os.path.join(workspace, bug_file)) or failed_funcs_failed_bins:
        ret, bug_ck_list = get_bug_ck_list_from_doc(workspace, bug_file, target_ck_prefix)
        if not ret:
            return ret, bug_ck_list

        ret, msg = check_bug_analysis(checks_tc_fail, bug_ck_list, bug_file,
                                      check_tc_in_doc=check_tc_in_doc, check_doc_in_tc=(check_doc_in_tc and not only_marked_ckp_in_tc),
                                      failed_funcs_failed_bins=failed_funcs_failed_bins,
                                      failed_funcs_passed_bins=failed_funcs_passed_bins,
                                      target_ck_prefix=target_ck_prefix)
        if not ret:
            return ret, msg

    if report['unmarked_check_points'] > 0 and not only_marked_ckp_in_tc:
        unmark_check_points = [ck for ck in report['unmarked_check_points_list'] if ck.startswith(target_ck_prefix)]
        if len(unmark_check_points) > 0:
            return False, f"Test template validation failed, cannot find the follow {len(unmark_check_points)} check points: `{', '.join(unmark_check_points)}` " + \
                           "in the test templates. All check points defined in the documentation must be associated with test cases using 'mark_function'. " + \
                           "Please use it in the correct test case function like: dut.fc_cover['FG-GROUP'].mark_function('FC-FUNCTION', test_function_name, ['CK-CHECK1', 'CK-CHECK2']). " + \
                           "This ensures proper coverage mapping between documentation and test implementation. " + \
                           "Review your task requirements and complete the check point markings. "

    failed_check_point_passed_funcs = report.get("failed_check_point_passed_funcs", {})
    if failed_check_point_passed_funcs:
        fmsg = [f"Test logic inconsistency: {len(failed_check_point_passed_funcs)} Check points failed, but all of the related test cases passed (fail check point should has at least one related failed test case function):"]
        for k, v in failed_check_point_passed_funcs.items():
            fmsg.append(f"  Check point `{k}` failed, but related test cases: `{', '.join(v)}` passed" )
        fmsg.append("Under normal conditions, if a check point fails, the corresponding test cases should also fail. Action required:")
        fmsg.append("1. Review the test logic to ensure that check points are correctly associated with their test functions.")
        fmsg.append("2. Ensure that each check point accurately reflects the intended functionality and failure conditions.")
        fmsg.append("3. Fix any inconsistencies to ensure reliable and accurate test results.")
        fmsg.append("4. Make sure you have called CovGroup.sample() to sample the coverage group in your test function or in StepRis/StepFail callback, otherwise the coverage cannot be collected correctly.")
        fmsg.append("5. If the test case is marked with multiple check points and some of them failed, some of them unfailed, it is also a problem of test logic. You should split the test case to make sure each check point is independent.")
        return False, fmsg

    if callable(post_checker):
        ret, msg = post_checker(report)
        if not ret:
            return ret, msg

    return True, "All failed test functions are properly marked in bug analysis documentation."



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
        igs = fc.parse_line_ignore_file(file_ignore_path).get("marks", [])
        if len(igs) > 0:
            file_analyze_md_path = os.path.join(workspace, file_analyze_md)
            if not os.path.exists(file_analyze_md_path):
                return False, f"Line coverage analysis documentation file ({file_analyze_md}) not found in workspace `{workspace}`. Please ensure the documentation is available. " + \
                              f"Note if there are patterns (find: `{', '.join(igs)}`) in ignore file ({file_ignore}), the analysis document ({file_analyze_md}) is required to explain why these lines are ignored.", \
                                0.0
            doc_igs = fc.parse_marks_from_file(file_analyze_md_path, "LINE_IGNORE").get("marks", [])
            un_doced_igs = []
            for ig in igs:
                if ig not in doc_igs:
                    un_doced_igs.append(ig)
            if len(un_doced_igs) > 0:
                return False, f"Line coverage analysis documentation ({file_analyze_md}) does not contain those 'LINE_IGNORE' marks: `{', '.join(un_doced_igs)}`. " + \
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

    return True, f"Line coverage check passed (line coverage: {cover_rate:.2f}% >= {min_line_coverage*100.0:.2f}%).", cover_rate
