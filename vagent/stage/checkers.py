#coding=utf-8


from typing import Tuple
from vagent.util.functions import render_template, get_unity_chip_doc_marks
from vagent.util.functions import import_python_file
from vagent.tools.testops import RunUnityChipTest
import os
import json


class Checker(object):

    workspace = None

    def set_extra(self, **kwargs):
        """
        Set extra parameters for the checker.
        This method can be overridden in subclasses to handle additional parameters.

        :param kwargs: Additional parameters to be set.
        """
        for key, value in kwargs.items():
            if hasattr(self, key):
                raise ValueError(f"Cannot overwrite existing attribute '{key}' in {self.__class__.__name__}.")
            setattr(self, key, value)
        return self

    def check(self) -> Tuple[bool, str]:
        p, m = self.do_check()
        if p:
            p_msg = self.get_default_message_pass()
            if p_msg:
                m += "\n\n" + p_msg
        else:
            f_msg = self.get_default_message_fail()
            if f_msg:
                m += "\n\n" + f_msg
        return p, render_template(m, self)

    def get_default_message_fail(self) -> str:
        return getattr(self, "fail_msg", None)

    def get_default_message_pass(self) -> str:
        return getattr(self, "pass_msg", None)

    def do_check(self) -> Tuple[bool, str]:
        """
        Base method for performing checks.
        Perform the check and return a tuple containing the result and a message.
        
        Returns:
            Tuple[bool, str]: A tuple where the first element is a boolean indicating success or failure,
                              and the second element is a message string.
        """
        raise NotImplementedError("This method should be implemented in a subclass.")

    def __str__(self):
        return render_template(self.do_check.__doc__.strip(), self) or \
            "No description provided for this checker."

    def set_workspace(self, workspace: str):
        """
        Set the workspace for the checker.

        :param workspace: The workspace directory to be set.
        """
        self.workspace = os.path.abspath(workspace)
        assert os.path.exists(self.workspace), \
            f"Workspace {self.workspace} does not exist. Please provide a valid workspace path."
        return self

    def get_path(self, path: str) -> str:
        """
        Get the absolute path for a given relative path within the workspace.

        :param path: The relative path to be resolved.
        :return: The absolute path within the workspace.
        """
        return os.path.join(self.workspace, path)


class UnityChipCheckerFunctionsAndChecks(Checker):
    """
    Checker for Unity chip functions and checks.
    
    This class is used to define and manage function coverage groups and their associated checks.
    It allows for the initialization of coverage groups with specific watch points for different operations.
    """

    def __init__(self, doc_file, min_functions, min_checks):
        self.doc_file = doc_file
        self.min_functions = min_functions
        self.min_checks = min_checks

    def do_check(self) -> Tuple[bool, str]:
        """
        Perform the check for function and check coverage.
        target doc: {doc_file}
        need as least {min_functions} functions and {min_checks} checks in target doc.

        Returns:
            Tuple[bool, str]: A tuple where the first element is a boolean indicating success or failure,
                              and the second element is a message string.
        """
        if not os.path.exists(self.get_path(self.doc_file)):
            return False, f"Documentation file {self.doc_file} does not exist in workspace. "+\
                           "Please provide a valid file path. Review your task details."
        try:
            data = get_unity_chip_doc_marks(self.get_path(self.doc_file))
        except Exception as e:
            return False, f"Failed to parse the documentation file {self.doc_file}: {str(e)}\n" + \
                           "Review your task requirements and the file format."
        check_list = data.get("marks", [])
        check_info = "\n\n[Current_Checks]:\n" + "\n".join(check_list)
        count_function = data["count_function"]
        count_check = data["count_checkpoint"]
        if count_function < self.min_functions:
            return False, f"Insufficient functions defined: {count_function} found, " +\
                           f"minimum required is {self.min_functions}." + check_info
        if count_check < self.min_checks:
            return False, f"Insufficient checks defined: {count_check} found, " +\
                           f"minimum required is {self.min_checks}." + check_info
        # Check success
        return True, "Function and check coverage is sufficient." + check_info


class UnityChipCheckerDutApi(Checker):
    """
    Checker for Unity chip DUT API.

    This class is used to verify the API coverage of the DUT (Device Under Test) in Unity chip.
    It checks if the API coverage meets the specified minimum requirements.
    """

    def __init__(self, api_file, min_apis):
        self.api_file = api_file
        self.min_apis = min_apis

    def do_check(self) -> Tuple[bool, str]:
        """
        Perform the check for DUT API coverage.
        Target API file: {api_file}
        Minimum required APIs: {min_apis}
        Returns:
            Tuple[bool, str]: A tuple where the first element is a boolean indicating success or failure,
                              and the second element is a message string.
        """
        if not os.path.exists(self.get_path(self.api_file)):
            return False, f"API file {self.api_file} does not exist in workspace. "+\
                           "Please provide a valid file path. Review your task details."
        api_count = 0
        api_list = []
        with open(self.get_path(self.api_file), 'r') as file:
            for i, api_line in enumerate(file.readlines()):
                line = api_line.strip()
                if line.startswith("def "):
                    func_name = api_line[4:].strip()
                    if func_name.startswith("api_"):
                        api_count += 1
                        api_list.append("at line %d: %s"%(i, func_name))
        info_api = "\n\n[Current_APIs]:\n" + "\n".join(api_list)
        if api_count < self.min_apis:
            return False, f"Insufficient DUT APIs defined: {api_count} found, " +\
                           f"minimum required is {self.min_apis}." + info_api
        # Check success
        return True, "DUT API coverage is sufficient." + info_api


class UnityChipCheckerCoverGroup(Checker):
    """
    Checker for Unity chip coverage groups.

    This class is used to verify the coverage groups in Unity chip.
    It checks if the coverage groups meet the specified minimum requirements.
    """

    def __init__(self, test_path, group_file, min_groups):
        self.test_path = test_path
        self.group_file = group_file
        self.min_groups = min_groups

    def do_check(self) -> Tuple[bool, str]:
        """
        Perform the check for coverage groups.
        target group file: {group_file}
        need at least {min_groups} coverage groups defined.
        Returns:
            Tuple[bool, str]: A tuple where the first element is a boolean indicating success or failure,
                              and the second element is a message string.
        """
        if not os.path.exists(self.get_path(self.group_file)):
            return False, f"Coverage group file {self.group_file} does not exist in workspace. "+\
                           "Please provide a valid file path. Review your task details."
        try:
            mode = import_python_file(self.get_path(self.group_file),
                                      [self.workspace, self.get_path(self.test_path)])
        except Exception as e:
            return False, f"Failed to import coverage group file {self.group_file}: {str(e)}\n" + \
                           "Review your task requirements and the file format."
        get_coverage_groups = getattr(mode, "get_coverage_groups", None)
        if get_coverage_groups is None:
            return False, f"Coverage group file {self.group_file} does not define 'coverage_groups'. " +\
                           "Please ensure the file contains the required coverage group definitions."
        try:
            if len(get_coverage_groups()) < self.min_groups:
                return False, f"Insufficient coverage groups defined: " +\
                               f"{len(get_coverage_groups())} found, minimum required is {self.min_groups}."
        except Exception as e:
            return False, f"Error while checking coverage groups: {str(e)}\n" + \
                           "Please ensure the coverage group definitions are correct."
        # Check success
        return True, "Coverage groups are sufficient."


class UnityChipCheckerTestCase(Checker):
    """
    Checker for Unity chip test cases.

    This class is used to verify the test cases in Unity chip.
    It checks if the test cases meet the specified minimum requirements.
    """

    def __init__(self, doc_func_check, doc_bug_analysis, test_dir, min_tests):
        self.doc_func_check = doc_func_check
        self.doc_bug_analysis = doc_bug_analysis
        self.test_dir = test_dir
        self.min_tests = min_tests
        self.run_test = RunUnityChipTest()

    def set_workspace(self, workspace: str):
        """
        Set the workspace for the test case checker.

        :param workspace: The workspace directory to be set.
        """
        super().set_workspace(workspace)
        self.run_test.set_workspace(workspace)
        return self

    def do_check(self) -> Tuple[bool, str]:
        """
        Perform the check for test cases.

        Returns:
            Tuple[bool, str]: A tuple where the first element is a boolean indicating success or failure,
                              and the second element is a message string.
        """
        if not os.path.exists(self.get_path(self.doc_func_check)):
            return False, f"Function and check documentation file {self.doc_func_check} does not exist in workspace. "+\
                           "Please provide a valid file path. Review your task details."
        report, str_out, str_err = self.run_test.do(
            self.test_dir, return_stdout=True, return_stderr=True, return_all_checks=True,
        )
        all_bins_test = report.get("bins_all", [])
        if all_bins_test:
            del report["bins_all"]
        info_report = "\n\n[TEST_REPORT]:\n" + json.dumps(report, indent=4)
        info_runtest = info_report + "\n[STDOUT]:\n" + str_out + "\n[STDERR]:\n" + str_err
        if report.get("tests") is None:
            return False, "No test cases found in the report. " +\
                           "Please ensure that the test cases are defined correctly in the workspace." + \
                           "\n" + info_runtest
        if report["tests"]["total"] < self.min_tests:
            return False, f"Insufficient test cases defined: {report['tests']['total']} found, " +\
                           f"minimum required is {self.min_tests}.\n" + \
                           "Please ensure that the test cases are defined in the correct format and location.\n"+ \
                            info_runtest
        try:
            all_bins_docs = get_unity_chip_doc_marks(self.get_path(self.doc_func_check))["marks"]
        except Exception as e:
            return False, f"Failed to parse the function and check documentation file {self.doc_func_check}: {str(e)}\n" + \
                           "Review your task requirements and the file format to fix your documentation file.\n"
        bins_not_in_docs = []
        bins_not_in_test = []
        for b in all_bins_test:
            if b not in all_bins_docs:
                bins_not_in_docs.append(b)
        for b in all_bins_docs:
            if b not in all_bins_test:
                bins_not_in_test.append(b)
        if len(bins_not_in_docs) > 0:
            return False, f"The flow check points: {', '.join(bins_not_in_docs)} are not defined in the documentation file {self.doc_func_check}.\n" + \
                           "Please ensure that all check points in test case are defined in the documentation file.\n" + \
                           "Review your task requirements and the test cases.\n" + info_runtest
        if len(bins_not_in_test) > 0:
            return False, f"The flow check points: {', '.join(bins_not_in_test)} are defined in the documentation file {self.doc_func_check} but not in the test cases.\n" + \
                           "Please ensure that all check points defined in the documentation are also in the test cases.\n" + \
                           "Review your task requirements and the test cases.\n" + info_runtest
        failed_check = report.get('faild_check_point_list', [])
        fails_with_no_mark = []
        marked_checks = []
        if failed_check:
            if os.path.exists(self.get_path(self.doc_bug_analysis)):
                try:
                    marked_bugs = get_unity_chip_doc_marks(self.get_path(self.doc_bug_analysis))
                except Exception as e:
                    return False, f"Failed to parse the bug analysis documentation file '{self.doc_bug_analysis}': {str(e)}\n" + \
                                   "Review your task requirements and the file format."
                # check marks
                for c in marked_bugs["marks"]:
                    labels = c.split("/")
                    if not labels[-1].startswith("BUG-RATE-"):
                        return False, f"Bug analysis documentation '{self.doc_bug_analysis}' contains a mark '{c}' without 'BUG-RATE-'. " +\
                                       "Please ensure that all bug analysis marks start with 'BUG-RATE-'. "+\
                                       "eg <BUG-RATE-80> means it should be a bug least `80%` confidence for the corresponding CHECK-POINT."
                    marked_checks.append("/".join(labels[:-1]))
                for fail_check in failed_check:
                    if fail_check not in marked_checks:
                        fails_with_no_mark.append(fail_check)
        else:
            fails_with_no_mark = failed_check
        if len(fails_with_no_mark) > 0:
            return False, f"Find Failed check points: {', '.join(fails_with_no_mark)}." + \
                           "Correct test cases should pass all check points. Or if you find a bug, please ensure that all failed check points are marked with confidence in the bug analysis documentation.\n" + \
                           "If you have not defined any bug analysis documentation, please do so to ensure proper tracking of issues.\n" + \
                           "Review your task requirements and the test cases.\n" + info_runtest
        if report['unmarked_check_points'] > 0:
            unmark_check_points = []
            for m in report['unmarked_check_points_list']:
                if m not in marked_checks:
                    unmark_check_points.append(m)
            if len(unmark_check_points) > 0:
                return False, f"The flow check points: {', '.join(unmark_check_points)} are not associated with any test cases.\n" + \
                               "Please use 'mark_function' to mark the check points with its test cases.\n" + \
                               "Review your task requirements and the test cases.\n" + info_runtest
        if report['test_function_with_no_check_point_mark'] > 0:
            return False, f"Find {report['test_function_with_no_check_point_mark']} test functions without check points ({', '.join(report['test_function_with_no_check_point_mark_list'])}). " +\
                           "Please ensure that all functions are associated with appropriate check points (use 'mark_function').\n" + \
                           "Review your task requirements and the test cases.\n" + info_runtest

        return True, "Test cases are sufficient. You did a good job!" + info_report
