#coding=utf-8

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
                        "2. Encoding issues or special characters.",
                        "3. Invalid document structure.",
                        "Please review your documentation format and fix any syntax errors."]
    return True, [v for v in marked_checks["marks"] if v.startswith(target_ck_prefix)]


def check_bug_analysis(failed_check: list, marked_bug_checks:list, bug_analysis_file: str,
                       check_tc_in_doc=True, check_doc_in_tc=True,
                       failed_funcs_bins: dict=None, target_ck_prefix=""):
    """Check failed checkpoint in bug analysis documentation."""
    failed_fb = []
    if failed_funcs_bins:
        failed_fb = [cb for cks in failed_funcs_bins.values() for cb in cks if cb not in failed_check]
    if check_doc_in_tc:
        un_related_bug_marks = []
        for ck in marked_bug_checks:
            if ck not in failed_check + failed_fb:
                un_related_bug_marks.append(ck)
        if len(un_related_bug_marks) > 0:
            return False, [f"Documentation inconsistency: Bug analysis documentation '{bug_analysis_file}' contains marks not related to any failed test cases: {', '.join(un_related_bug_marks)}. " + \
                            "Please ensure all bug analysis marks correspond to actual test failures. Action required:",
                            "1. Update the bug analysis documentation to include all relevant test failures.",
                            "2. Ensure that all bug analysis marks are properly linked to their corresponding test cases.",
                            "3. Review the test cases to ensure they are correctly identifying and reporting DUT bugs."
                            ]

    if check_tc_in_doc:
        un_related_tc_marks = []
        for ck in failed_check:
            if ck not in marked_bug_checks:
                un_related_tc_marks.append(ck)
        if len(un_related_tc_marks) > 0:
                return False, [f"Unanalyzed test failures detected: {', '.join(un_related_tc_marks)}. " + \
                                "Test failures must be properly analyzed and documented. Options:",
                                "1. If these are actual DUT bugs, document them use marks '<FG-*>, <FC-*>, <CK-*>, <<BUG-RATE-*>' in '{}' with confidence ratings.".format(bug_analysis_file),
                                "2. If these are test issues, fix the test logic to make them pass.",
                                "3. Review test implementation and DUT behavior to determine root cause.",
                                "Note: Checkpoint is always represents like `FG-*/FC-*/CK-*`, eg: `FG-LOGIC/FC-ADD/CK-BASIC`"
                                ]
    if failed_funcs_bins is not None:
        for func, checks in failed_funcs_bins.items():
            un_buged_cks = []
            for cb in checks:
                if not cb.startswith(target_ck_prefix):
                    continue
                if cb not in marked_bug_checks:
                    un_buged_cks.append(cb)
            if len(un_buged_cks) > 0:
                return False, [f"Checkpoint ({','.join(un_buged_cks)}) in failed test function: {func} are not unanalyzed in the bug analysis file <{bug_analysis_file}>. You need:",
                               "1. Document these checkpoints in the bug analysis file with appropriate marks.",
                               "2. if this checkpoints are not related to the test function, delete it in 'mark_function'",
                               "3. Review the test cases to ensure they are correctly identifying and reporting DUT bugs.",
                               f"Current analyzed checkpoints: {', '.join(marked_bug_checks)} in <{bug_analysis_file}>",
                               "when you document the checkpoints need use the correct format: <FG-*>, <FC-*>, <CK-*>, <BUG-RATE-*>"
                               ]
    return True, f"Bug analysis documentation '{bug_analysis_file}' is consistent with test results."


def check_doc_struct(test_case_checks:list, doc_checks:list, doc_file:str, check_tc_in_doc=True, check_doc_in_tc=True):
    if check_tc_in_doc:
        ck_not_in_doc = []
        for ck in test_case_checks:
            if ck not in doc_checks:
                ck_not_in_doc.append(ck)
        if len(ck_not_in_doc) > 0:
            return False, [f"Documentation inconsistency: Test implementation contains undocumented check points: {', '.join(ck_not_in_doc)}. " + \
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
            return False, [f"Test coverage gap: Documentation({doc_file}) defines check points not implemented in tests: {', '.join(ck_not_in_tc)} " + \
                            "These check points are documented but missing from test implementation. " + \
                            "Action required:",
                            "1. Implement test cases that cover these check points.",
                            "2. Use proper mark_function() calls to associate tests with check points.",
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
                        "1. Add mark_function() calls to associate these functions with appropriate check points.",
                        "2. Ensure every test function validates specific documented functionality.",
                        "3. Review test organization and ensure complete traceability."]

    checks_in_tc  = [b for b in report.get("bins_all", []) if b.startswith(target_ck_prefix)]
    ret, msg = check_doc_struct(checks_in_tc, doc_ck_list, doc_file, check_tc_in_doc=check_tc_in_doc, check_doc_in_tc=check_doc_in_tc)
    if not ret:
        return ret, msg

    checks_tc_fail = [b for b in report.get("failed_check_point_list", []) if b.startswith(target_ck_prefix)]
    marked_check_points = [c for c in checks_in_tc if c not in report.get("unmarked_check_points_list", [])]
    if only_marked_ckp_in_tc:
        checks_tc_fail = [b for b in checks_tc_fail if b in marked_check_points]
    failed_funcs_bins = report.get("failed_funcs_bins", {})
    if len(checks_tc_fail) > 0 or os.path.exists(os.path.join(workspace, bug_file)) or failed_funcs_bins:
        ret, bug_ck_list = get_bug_ck_list_from_doc(workspace, bug_file, target_ck_prefix)
        if not ret:
            return ret, bug_ck_list

        ret, msg = check_bug_analysis(checks_tc_fail, bug_ck_list, bug_file,
                                      check_tc_in_doc=check_tc_in_doc, check_doc_in_tc=(check_doc_in_tc and not only_marked_ckp_in_tc),
                                      failed_funcs_bins=failed_funcs_bins,
                                      target_ck_prefix=target_ck_prefix)
        if not ret:
            return ret, msg

    if report['unmarked_check_points'] > 0 and not only_marked_ckp_in_tc:
        unmark_check_points = [ck for ck in report['unmarked_check_points_list'] if ck.startswith(target_ck_prefix)]
        if len(unmark_check_points) > 0:
            return False, f"Test template validation failed: Found {len(unmark_check_points)} unmarked check points: {', '.join(unmark_check_points)} " + \
                           "in the test templates. All check points defined in the documentation must be associated with test cases using 'mark_function'. " + \
                           "Please use it like: dut.fc_cover['FG-GROUP'].mark_function('FC-FUNCTION', test_function_name, ['CK-CHECK1', 'CK-CHECK2']). " + \
                           "This ensures proper coverage mapping between documentation and test implementation. " + \
                           "Review your task requirements and complete the check point markings. "

    failed_check_point_passed_funcs = report.get("failed_check_point_passed_funcs", {})
    if failed_check_point_passed_funcs:
        fmsg = [f"Test logic inconsistency: Check points failed, but some of the related test cases passed:"]
        for k, v in failed_check_point_passed_funcs.items():
            fmsg.append(f"  Check point `{k}` failed, but related test cases passed: {', '.join(v)}")
        fmsg.append("Under normal conditions, if a check point fails, the corresponding test cases should also fail. Action required:")
        fmsg.append("1. Review the test logic to ensure that check points are correctly associated with their test functions.")
        fmsg.append("2. Ensure that each check point accurately reflects the intended functionality and failure conditions.")
        fmsg.append("3. Fix any inconsistencies to ensure reliable and accurate test results.")
        fmsg.append("4. Make sure you have called CovGroup.sample() to sample the coverage group in your test function or in StepRis/StepFail callback, otherwise the coverage cannot be collected correctly.")
        return False, fmsg

    if callable(post_checker):
        ret, msg = post_checker(report)
        if not ret:
            return ret, msg

    return True, "All failed test functions are properly marked in bug analysis documentation."
