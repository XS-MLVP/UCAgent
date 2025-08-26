#coding=utf-8

import vagent.util.functions as fc
import os


def get_bug_ck_list_from_doc(workspace: str, bug_analysis_file: str, target_ck_prefix:str):
    """Parse bug analysis documentation to extract marked bug analysis points."""
    try:
        marked_bugs = fc.get_unity_chip_doc_marks(os.path.join(workspace, bug_analysis_file), leaf_node="BUG-RATE")
    except Exception as e:
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


def check_bug_analysis(failed_check: list, marked_bug_checks:list, bug_analysis_file: str, check_tc_in_doc=True, check_doc_in_tc=True):
    """Check failed checkpoint in bug analysis documentation."""
    if check_doc_in_tc:
        un_related_bug_marks = []
        for ck in marked_bug_checks:
            if ck not in failed_check:
                un_related_bug_marks.append(ck)
        if len(un_related_bug_marks) > 0:
            return False, [f"Documentation inconsistency: Bug analysis documentation '{bug_analysis_file}' contains marks not related to any failed test cases: {', '.join(un_related_bug_marks)}. " + \
                            "Please ensure all bug analysis marks correspond to actual test failures.",
                            "Action required:",
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
            return False, [f"Test coverage gap: Documentation({doc_file}) defines check points not implemented in tests: {', '.join(ck_not_in_tc)} " + \
                            "These check points are documented but missing from test implementation. " + \
                            "Action required:",
                            "1. Implement test cases that cover these check points.",
                            "2. Use proper mark_function() calls to associate tests with check points.",
                            "3. Ensure complete functional coverage as specified in documentation."]

    return True, f"Function/check points documentation ({doc_file}) is consistent with test cases."


def check_report(workspace, report, doc_file, bug_file, target_ck_prefix="", check_tc_in_doc=True, check_doc_in_tc=True, post_checker=None):
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
    if len(checks_tc_fail) > 0 or os.path.exists(os.path.join(workspace, bug_file)):
        ret, bug_ck_list = get_bug_ck_list_from_doc(workspace, bug_file, target_ck_prefix)
        if not ret:
            return ret, bug_ck_list

        ret, msg = check_bug_analysis(checks_tc_fail, bug_ck_list, bug_file, check_tc_in_doc=check_tc_in_doc, check_doc_in_tc=check_doc_in_tc)
        if not ret:
            return ret, msg

    for func, checks in report.get("failed_funcs_bins", {}).items():
        marked_checks = []
        for ck in checks:
            if not ck.startswith(target_ck_prefix):
                continue
            if ck in bug_ck_list:
                marked_checks.append(ck)
        if len(marked_checks) == 0:
            return False, [f"Unanalyzed test failures detected: failed test function '{func}' needs at least one function/check is marked in bug analysis documentation '{bug_file}'. " + \
                            "Test failures must be properly analyzed and documented. Options:",
                            "1. If these are actual DUT bugs, document them use marks '<FG-*>, <FC-*>, <CK-*>, <<BUG-RATE-*>' in '{}' with confidence ratings.".format(bug_file),
                            "2. If these are test issues, fix the test logic to make them pass.",
                            "3. Review test implementation and DUT behavior to determine root cause.",
                            "Note: Checkpoint is always represents like `FG-*/FC-*/CK-*`, eg: `FG-LOGIC/FC-ADD/CK-BASIC`"]

    if callable(post_checker):
        ret, msg = post_checker(report)
        if not ret:
            return ret, msg

    return True, "All failed test functions are properly marked in bug analysis documentation."
