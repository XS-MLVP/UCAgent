#coding=utf-8


from typing import Tuple
from vagent.util.functions import render_template, parse_nested_keys
from vagent.util.functions import import_python_file
from vagent.tools.testops import RunUnityChipTest
import os


class Checker(object):

    workspace = None

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
                           "Please provide a valid file path. Please review your task details."
        # parse
        keynames = ["group", "function", "checkpoint", "bug_rate"]
        prefix   = ["<FG-",  "<FC-",     "<CK-",       "<BUG-RATE-"]
        subfix   = [">"]* len(prefix)
        try:
            data = parse_nested_keys(
                self.get_path(self.doc_file), keynames, prefix, subfix
            )
        except Exception as e:
            return False, f"Failed to parse the documentation file {self.doc_file}: {str(e)}\n" + \
                           "Please review your task requirements and the file format."
        count_function = 0
        count_check = 0
        for g, g_data in data.items():
            if "function" in g_data:
                for f, f_data in g_data["function"].items():
                    count_function += 1
                    if "checkpoint" in f_data:
                        count_check += len(f_data["checkpoint"])
        if count_function < self.min_functions:
            return False, f"Insufficient functions defined: {count_function} found, " +\
                           f"minimum required is {self.min_functions}."
        if count_check < self.min_checks:
            return False, f"Insufficient checks defined: {count_check} found, " +\
                           f"minimum required is {self.min_checks}."
        # Check success
        return True, "Function and check coverage is sufficient."


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
                           "Please provide a valid file path. Please review your task details."
        api_count = 0
        with open(self.get_path(self.api_file), 'r') as file:
            for api_line in file.readlines():
                line = api_line.strip()
                if line.startswith("def "):
                    if api_line[4:].strip().startswith("api_"):
                        api_count += 1
        if api_count < self.min_apis:
            return False, f"Insufficient DUT APIs defined: {api_count} found, " +\
                           f"minimum required is {self.min_apis}."
        # Check success
        return True, "DUT API coverage is sufficient."


class UnityChipCheckerCoverGroup(Checker):
    """
    Checker for Unity chip coverage groups.

    This class is used to verify the coverage groups in Unity chip.
    It checks if the coverage groups meet the specified minimum requirements.
    """

    def __init__(self, group_file, min_groups):
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
                           "Please provide a valid file path. Please review your task details."
        try:
            mode = import_python_file(self.get_path(self.group_file), self.workspace)
        except Exception as e:
            return False, f"Failed to import coverage group file {self.group_file}: {str(e)}\n" + \
                           "Please review your task requirements and the file format."
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
                           "Please provide a valid file path. Please review your task details."
        report, str_out, str_err = self.run_test.do(
            self.test_dir, return_stdout=True, return_stderr=True,
        )
        test_info = "[STDOUT]\n" + str_out + "\n[STDERR]\n" + str_err
        if report.get("tests") is None:
            return False, "No test cases found in the report. " +\
                           "Please ensure that the test cases are defined correctly in the workspace." + \
                           "\n" + test_info
        if report["tests"]["total"] < self.min_tests:
            return False, f"Insufficient test cases defined: {report['tests']['total']} found, " +\
                           f"minimum required is {self.min_tests}.\n" + \
                           "Please ensure that the test cases are defined in the correct format and location.\n"+ \
                            test_info
        # Check report['uncovered_check_points']
        # check report['faild_check_point_list']
        # Check report['test_function_with_no_check_point]

        # This should check the test cases against the minimum requirement
        return True, "Test cases are sufficient."
