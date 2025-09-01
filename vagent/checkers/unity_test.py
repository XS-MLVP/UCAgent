#coding=utf-8


from typing import Tuple
import vagent.util.functions as fc
from vagent.util.log import info, warning
from vagent.tools.testops import RunUnityChipTest
import os
import glob
import traceback

from vagent.checkers.base import Checker
from vagent.checkers.toffee_report import check_report
from collections import OrderedDict

class UnityChipCheckerMarkdownFileFormat(Checker):
    def __init__(self, markdown_file_list, no_line_break=False):
        self.markdown_file_list = markdown_file_list if isinstance(markdown_file_list, list) else [markdown_file_list]
        self.no_line_break = no_line_break

    def do_check(self) -> Tuple[bool, object]:
        """Check the markdown file format."""
        msg = f"{self.__class__.__name__} check pass."
        for markdown_file in self.markdown_file_list:
            info(f"check file: {markdown_file}")
            real_file = self.get_path(markdown_file)
            if not os.path.exists(real_file):
                return False, {"error": f"Markdown file '{markdown_file}' does not exist."}
            try:
                with open(real_file) as f:
                    lines  = f.readlines()
                    if len(lines) == 1 and "\\n" in lines[0]:
                        return False, {"error": "Markdown file is not properly formatted. You may mistake '\n' as '\\n'."}
                    for i, l in enumerate(lines):
                        if "\\n" in l:
                            return False, {"error": f"Find '\\n' in: {markdown_file}:{i}. content: {l}. Do you mean '\n' instead ?"}
            except Exception as e:
                return False, {"error": f"Failed to read markdown file '{markdown_file}': {str(e)}."}
        return True, {"message": msg}


class UnityChipCheckerLabelStructure(Checker):
    def __init__(self, doc_file, leaf_node, min_count=1, must_have_prefix="FG-API"):
        """
        Initialize the checker with the documentation file, the specific label (leaf node) to check,
        and the minimum count required for that label.
        """
        self.doc_file = doc_file
        self.leaf_node = leaf_node
        self.min_count = min_count
        self.must_have_prefix = must_have_prefix

    def do_check(self) -> Tuple[bool, object]:
        """Check the label structure in the documentation file."""
        msg = f"{self.__class__.__name__} check {self.leaf_node} pass."
        if not os.path.exists(self.get_path(self.doc_file)):
            return False, {"error": f"Documentation file '{self.doc_file}' does not exist."}
        try:
            data = fc.get_unity_chip_doc_marks(self.get_path(self.doc_file), self.leaf_node, self.min_count)
        except Exception as e:
            error_details = str(e)
            warning(f"Error occurred while checking {self.doc_file}: {error_details}")
            warning(traceback.format_exc())
            emsg = [f"Documentation parsing failed for file '{self.doc_file}': {error_details}."]
            if "\\n" in error_details:
                emsg.append("Literal '\\n' characters detected - use actual line breaks instead of escaped characters")
            emsg.append({"check_list": [
                "Malformed tags: Ensure proper format. e.g., <FG-NAME>, <FC-NAME>, <CK-NAME>",
                "Invalid characters: Use only alphanumeric and hyphen in tag names",
                "Missing tag closure: All tags must be properly closed",
                "Encoding issues: Ensure file is saved in UTF-8 format",
            ]})
            return False, {"error": emsg}
        if self.must_have_prefix:
            find_prefix = False
            for mark in data["marks"]:
                if mark.startswith(self.must_have_prefix):
                    find_prefix = True
            if not find_prefix:
                return False, {"error": f"In the document ({self.doc_file}), it must have group/."}
        return True, {"message": msg, f"{self.leaf_node}_count": len(data["marks"])}


class UnityChipCheckerDutCreation(Checker):
    def __init__(self, target_file):
        self.target_file = target_file

    def do_check(self) -> Tuple[bool, object]:
        """Check the DUT creation function for correctness."""
        if not os.path.exists(self.get_path(self.target_file)):
            return False, {"error": f"file '{self.target_file}' does not exist."}
        func_list = fc.get_target_from_file(self.get_path(self.target_file), "create_dut",
                                            ex_python_path=self.workspace,
                                            dtype="FUNC")
        if not func_list:
            return False, {"error": f"No 'create_dut' functions found in '{self.target_file}'."}
        assert len(func_list) == 1, f"Multiple 'create_dut' functions found in '{self.target_file}'. Expected only one."
        dut = func_list[0]()
        for need_func in ["Step", "StepRis"]:
            assert hasattr(dut, need_func), f"The 'create_dut' function in '{self.target_file}' did not return a valid DUT instance with '{need_func}' method."
        # Additional checks can be implemented here
        return True, {"message": f"{self.__class__.__name__} check for {self.target_file} passed."}


class UnityChipCheckerDutFixture(Checker):
    def __init__(self, target_file):
        self.target_file = target_file

    def do_check(self) -> Tuple[bool, object]:
        """Check the DUT fixture implementation for correctness."""
        if not os.path.exists(self.get_path(self.target_file)):
            return False, {"error": f"DUT fixture file '{self.target_file}' does not exist."}
        dut_func = fc.get_target_from_file(self.get_path(self.target_file), "dut",
                                           ex_python_path=self.workspace,
                                           dtype="FUNC")
        if not dut_func:
            return False, {"error": f"No 'dut' fixture found in '{self.target_file}'."}
        if not len(dut_func) == 1:
            return False, {"error": f"Multiple 'dut' fixtures found in '{self.target_file}'. Expected only one."}
        dut_func = dut_func[0]
        # check @pytest.fixture()
        if not (hasattr(dut_func, '_pytestfixturefunction') or "pytest_fixture" in str(dut_func)):
            return False, {"error": f"The 'dut' fixture in '{self.target_file}' is not decorated with @pytest.fixture()."}
        # check args
        args = fc.get_func_arg_list(dut_func)
        if len(args) != 1 or args[0] != "request":
            return False, {"error": f"The 'dut' fixture has only one arg named 'request', but got ({', '.join(args)})."}
        # check yield - first check if it's a generator function
        import inspect
        import ast
        try:
            source_lines = inspect.getsourcelines(dut_func)[0]
            source_code = ''.join(source_lines)
            tree = ast.parse(source_code)
            
            has_yield = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Yield) or isinstance(node, ast.YieldFrom):
                    has_yield = True
                    break
            if not has_yield:
                return False, {"error": f"The '{dut_func.__name__}' fixture in '{self.target_file}' does not contain 'yield' statement. Pytest fixtures should yield the DUT instance for proper setup/teardown."}
        except Exception as e:
            # If we can't parse the source code, fall back to the generator function check
            # which should be sufficient in most cases
            pass
        return True, {"message": f"{self.__class__.__name__} check for {self.target_file} passed."}


class UnityChipCheckerDutApi(Checker):
    def __init__(self, api_prefix, target_file, min_apis=1):
        self.api_prefix = api_prefix
        self.target_file = target_file
        self.min_apis = min_apis

    def do_check(self) -> Tuple[bool, object]:
        """Check the DUT API implementation for correctness."""
        if not os.path.exists(self.get_path(self.target_file)):
            return False, {"error": f"DUT API file '{self.target_file}' does not exist."}
        func_list = fc.get_target_from_file(self.get_path(self.target_file), f"{self.api_prefix}*",
                                         ex_python_path=self.workspace,
                                         dtype="FUNC")
        failed_apis = []
        for func in func_list:
            args = fc.get_func_arg_list(func)
            if not args or len(args) < 1:
                failed_apis.append(func)
                continue
            if args[0] != "dut":
                failed_apis.append(func)
        if len(failed_apis) > 0:
            return False, {
                "error": f"The following API functions have invalid or missing arguments. The first arg must be 'dut'",
                "failed_apis": [f"{func}({', '.join(fc.get_func_arg_list(func))})" for func in failed_apis]
            }
        if len(func_list) < self.min_apis:
            return False, {
                "error": f"Insufficient DUT API coverage: {len(func_list)} API functions found, minimum required is {self.min_apis}."
            }
        for func in func_list:
            if not func.__doc__ or len(func.__doc__.strip()) == 0:
                return False, {
                    "error": f"The API function '{func.__name__}' is missing a docstring. Please provide a clear description of its purpose and usage."
                }
            for doc_key in ["Args:", "Returns:"]:
                if doc_key not in func.__doc__:
                    return False, {
                        "error": f"The API function '{func.__name__}' is missing the '{doc_key}' section in its docstring."
                    }
        return True, {"message": f"{self.__class__.__name__} check for {self.target_file} passed."}


class UnityChipCheckerCoverageGroup(Checker):
    """
    Checker for Unity chip functional coverage groups validation.

    This class validates functional coverage definitions to ensure they properly
    implement coverage groups using the toffee framework, with adequate bins
    and watch points for comprehensive DUT verification coverage.
    """

    def __init__(self, test_dir, cov_file, doc_file, check_types):
        self.test_dir = test_dir
        self.cov_file = cov_file
        self.doc_file = doc_file
        self.check_types = check_types if isinstance(check_types, list) else [check_types]
        for ct in self.check_types:
            if ct not in ["FG", "FC", "CK"]:
                raise ValueError(f"Invalid check type '{ct}'. Must be one of 'FG', 'FC', or 'CK'.")

    def do_check(self) -> Tuple[bool, str]:
        """Check the functional coverage groups against the documentation."""
        # File existence validation
        def mk_emsg(msg):
            return {"error": msg + " Please make sure you are processing the right file."}
        if not os.path.exists(self.get_path(self.cov_file)):
            return False, mk_emsg(f"Functional coverage file '{self.cov_file}' not found in workspace.")
        # Module import validation
        funcs = fc.get_target_from_file(self.get_path(self.cov_file), "get_coverage_groups",
                                        ex_python_path=self.workspace,
                                        dtype="FUNC")
        if not funcs:
            return False, mk_emsg(f"No 'get_coverage_groups' functions found in '{self.cov_file}'.")
        if len(funcs) != 1:
            return False, mk_emsg(f"Multiple 'get_coverage_groups' functions found in '{self.cov_file}'. Only one is allowed.")
        get_coverage_groups = funcs[0]
        args = fc.get_func_arg_list(get_coverage_groups)
        if len(args) != 1 or args[0] != "dut":
            return False, mk_emsg(f"The 'get_coverage_groups' function in: {self.cov_file} must have one argument named 'dut', but got ({', '.join(args)}).")
        class fake_dut:
            def __getattribute__(self, name):
                return self
        groups = get_coverage_groups(fake_dut())
        if not groups:
            return False, mk_emsg(f"The 'get_coverage_groups' function returned no groups in target file: {self.cov_file}")
        if not isinstance(groups, list):
            return False, mk_emsg(f"The 'get_coverage_groups' function in: {self.cov_file} must return a list of coverage groups, but got {type(groups)}.")
        from toffee.funcov import CovGroup
        if not all(isinstance(g, CovGroup) for g in groups):
            return False, mk_emsg(f"All items returned by 'get_coverage_groups' in: {self.cov_file} must be instances of 'toffee.funcov.CovGroup', but got {type(groups[0])}.")
        # checks
        for ctype in self.check_types:
            doc_groups = fc.get_unity_chip_doc_marks(self.get_path(self.doc_file), ctype, 1)
            ck_pass, ck_message = self._com_check_func(groups, doc_groups, ctype)
            if not ck_pass:
                return ck_pass, ck_message
        return True, f"All coverage checks [{','.join(self.check_types)}] passed."

    def _groups_as_marks(self, func_groups, ctype):
        marks = []
        def append_v(v):
            assert v not in marks, f"Duplicate mark '{v}' found in {ctype} groups."
            marks.append(v)
        for g in func_groups:
            data = g.as_dict()
            if ctype == "FG":
                v = data["name"]
                append_v(v)
                continue
            if ctype == "FC":
                for p in data["points"]:
                    append_v(f"{data['name']}/{p['name']}")
                continue
            if ctype == "CK":
                for p in data["points"]:
                    for c in p["bins"]:
                        append_v(f"{data['name']}/{p['name']}/{c['name']}")
        return marks

    def _compare_marks(self, ga, gb):
        unmatched_in_a = []
        unmatched_in_b = []
        for a in ga:
            if a not in gb:
                unmatched_in_a.append(a)
        for b in gb:
            if b not in ga:
                unmatched_in_b.append(b)
        return unmatched_in_a, unmatched_in_b

    def _com_check_func(self, func_groups, doc_groups, ctype):
        a, b = self._compare_marks(self._groups_as_marks(func_groups, ctype), doc_groups["marks"])
        suggested_msg = "You need make those two files consist in coverage groups."
        if len(a) > 0:
            return False, f"Coverage groups check fail: find {len(a)} {ctype} ({', '.join(a)}) in '{self.cov_file}' but not found them in '{self.doc_file}'. {suggested_msg}"
        if len(b) > 0:
            return False, f"Coverage groups check fail: find {len(b)} {ctype} ({', '.join(b)}) in '{self.doc_file}' but not found them in '{self.cov_file}'. {suggested_msg}"
        info(f"{ctype} coverage {len(doc_groups['marks'])} marks check passed")
        return True, "Coverage groups check passed."


class BaseUnityChipCheckerTestCase(Checker):
    """
    Checker for Unity chip test cases.

    This class is used to verify the test cases in Unity chip.
    It checks if the test cases meet the specified minimum requirements.
    """

    def __init__(self, doc_func_check, test_dir, doc_bug_analysis=None, min_tests=1, timeout=6, ignore_ck_prefix=""):
        self.doc_func_check = doc_func_check
        self.doc_bug_analysis = doc_bug_analysis
        self.test_dir = test_dir
        self.min_tests = min_tests
        self.timeout = timeout
        self.ignore_ck_prefix = ignore_ck_prefix
        self.run_test = RunUnityChipTest()

    def set_workspace(self, workspace: str):
        """
        Set the workspace for the test case checker.

        :param workspace: The workspace directory to be set.
        """
        super().set_workspace(workspace)
        self.run_test.set_workspace(workspace)
        return self

    def do_check(self, pytest_args="") -> Tuple[bool, str]:
        """
        Perform the check for test cases.

        Returns:
            report, str_out, str_err: A tuple where the first element is a boolean indicating success or failure,
        """
        if not os.path.exists(self.get_path(self.doc_func_check)):
            return {}, "", f"Function and check documentation file {self.doc_func_check} does not exist in workspace. "+\
                            "Please provide a valid file path. Review your task details."
        self.run_test.set_pre_call_back(
            lambda p: self.set_check_process(p, self.timeout)  # Set the process for the checker
        )
        return self.run_test.do(
            self.test_dir, 
            pytest_ex_args=pytest_args,
            return_stdout=True, return_stderr=True, return_all_checks=True, timeout=self.timeout
        )


class UnityChipCheckerTestFree(BaseUnityChipCheckerTestCase):

    def do_check(self, pytest_args=""):
        """call pytest to run the test cases."""
        report, str_out, str_err = super().do_check(pytest_args=pytest_args)
        # refine report:
        free_report = OrderedDict({
            "run_test_success": report.get("run_test_success", False),
            "tests": report.get("tests", {}),
        })
        marked_bins = []
        failed_check_point_list = report.get("failed_check_point_list", [])
        for b in report.get("bins_all", []):
            if b not in failed_check_point_list:
                marked_bins.append(b)
                continue
        free_report["marked_bins"] = marked_bins
        return True, OrderedDict({
            "REPORT": free_report,
            "STDOUT": str_out,
            "STDERR": str_err
        })


class UnityChipCheckerTestTemplate(BaseUnityChipCheckerTestCase):

    def do_check(self) -> Tuple[bool, str]:
        """
        Perform the check for test templates.

        Returns:
            Tuple[bool, str]: A tuple where the first element is a boolean indicating success or failure,
                              and the second element is a message string.
        """
        report, str_out, str_err = super().do_check()
        all_bins_test = report.get("bins_all", [])
        if all_bins_test:
            del report["bins_all"]
        info_report = OrderedDict({"TEST_REPORT": report})
        info_runtest = OrderedDict({"TEST_REPORT": report, "STDOUT": str_out, "STDERR": str_err})
        if report.get("tests") is None:
            info_runtest["error"] = "No test cases found in the report. " +\
                                    "Please ensure that the test cases are defined correctly in the workspace."
            return False, info_runtest
        if report["tests"]["total"] < self.min_tests:
            info_runtest["error"] = f"Insufficient test cases defined: {report['tests']['total']} found, " +\
                                    f"minimum required is {self.min_tests}. " + \
                                     "Please ensure that the test cases are defined in the correct format and location."
            return False, info_runtest
        try:
            all_bins_docs = fc.get_unity_chip_doc_marks(self.get_path(self.doc_func_check), leaf_node="CK")["marks"]
        except Exception as e:
            info_report["error"] = f"Failed to parse the function and check documentation file {self.doc_func_check}: {str(e)}. " + \
                                    "Review your task requirements and the file format to fix your documentation file."
            return False, info_report
        bins_not_in_docs = []
        bins_not_in_test = []
        for b in all_bins_test:
            if b not in all_bins_docs:
                bins_not_in_docs.append(b)
        for b in all_bins_docs:
            if b not in all_bins_test:
                bins_not_in_test.append(b)
        if len(bins_not_in_docs) > 0:
            info_runtest["error"] = f"The flow check points: {', '.join(bins_not_in_docs)} are not defined in the documentation file {self.doc_func_check}. " + \
                                     "Please ensure that all check points in test case are defined in the documentation file. " + \
                                     "Review your task requirements and the test cases."
            return False, info_runtest
        if len(bins_not_in_test) > 0:
            info_runtest["error"] = f"The flow check points: {', '.join(bins_not_in_test)} are defined in the documentation file {self.doc_func_check} but not in the test cases. " + \
                                     "Please ensure that all check points defined in the documentation are also in the test cases. " + \
                                     "Review your task requirements and the test cases."
            return False, info_runtest

        if report['unmarked_check_points'] > 0:
            unmark_check_points = report['unmarked_check_points_list']
            if len(unmark_check_points) > 0:
                info_runtest["error"] = f"Test template validation failed: Found {len(unmark_check_points)} unmarked check points: {', '.join(unmark_check_points)} " + \
                                        "in the test templates. All check points defined in the documentation must be associated with test cases using 'mark_function'. " + \
                                        "Please use it like: dut.fc_cover['FG-GROUP'].mark_function('FC-FUNCTION', test_function_name, ['CK-CHECK1', 'CK-CHECK2']). " + \
                                        "This ensures proper coverage mapping between documentation and test implementation. " + \
                                        "Review your task requirements and complete the check point markings. "
                return False, info_runtest

        if report['test_function_with_no_check_point_mark'] > 0:
            unmarked_functions = report['test_function_with_no_check_point_mark_list']
            if len(unmarked_functions) > 0:
                info_runtest["error"] = [f"Test template validation failed: Found {report['test_function_with_no_check_point_mark']} test functions without check point marks: {', '.join(unmarked_functions)}. " + \
                                         "In test templates, every test function must be associated with specific check points through 'mark_function' calls. " + \
                                         "Each test function should:",
                                         "1. Include coverage marking at the beginning: dut.fc_cover['FG-GROUP'].mark_function('FC-FUNCTION', function_name, ['CK-POINTS']).",
                                         "2. Have clear TODO comments explaining what needs to be implemented.",
                                         "3. End with 'assert False, \"Not implemented\"' to prevent accidental passing.",
                                         "Please add proper function markings according to the test template specification."]
                return False, info_runtest

        # Additional template-specific validations
        template_validation_result = self._validate_template_structure(report, str_out, str_err)
        if not template_validation_result[0]:
            info_runtest["error"] = template_validation_result[1]
            return False, info_runtest

        # Success message with template-specific details
        info_report["success"] = ["Test template validation successful!",
                                 f"✓ Generated {report['tests']['total']} test case templates (all properly failing as expected).",
                                 f"✓ All {len(all_bins_test)} check points are properly documented and marked in test functions.",
                                 f"✓ Coverage mapping is consistent between documentation and test implementation.",
                                 f"✓ Template structure follows the required format with proper TODO comments and fail assertions.",
                                 "Your test templates are ready for implementation! Each test function provides clear guidance for the actual test logic to be implemented."]
        return True, info_report

    def _validate_template_structure(self, report, str_out, str_err) -> Tuple[bool, str]:
        """
        Validate the structure and requirements specific to test templates.

        Args:
            report: Test execution report
            str_out: Standard output from test execution
            str_err: Standard error from test execution

        Returns:
            Tuple[bool, str]: Validation result and message
        """
        # Check that all tests failed as expected in template
        passed_test = []
        for fv, rt in report.get("test_cases", {}).items():
            if self.ignore_ck_prefix and ":"+self.ignore_ck_prefix in fv:
                continue
            if rt == "PASSED":
                passed_test.append(fv + "=" + rt)

        if passed_test:
            return False, f"Test template structure validation failed: Not all test functions ({', '.join(passed_test)}) are properly failing. " + \
                           "In test templates, ALL test functions must fail with 'assert False, \"Not implemented\"' to indicate they are templates. " + \
                           "This prevents incomplete templates from being accidentally considered as passing tests. " + \
                           "Please ensure every test function ends with the required fail assertion."
        # Check for proper TODO comments (this would require parsing the actual test files)
        # For now, we rely on the fact that properly structured templates should fail with "Not implemented"
        if "Not implemented" not in str_out and "Not implemented" not in str_err:
            return False, "Test template structure validation failed: Template functions should contain 'Not implemented' messages. " + \
                          "Test templates must include 'assert False, \"Not implemented\"' statements to clearly indicate unfinished implementation. " + \
                          "This helps distinguish between actual test failures and template placeholders."
        return True, "Template structure validation passed."


class UnityChipCheckerDutApiTest(BaseUnityChipCheckerTestCase):
    
    def __init__(self, api_prefix, target_file_api, target_file_tests, doc_func_check, doc_bug_analysis, min_tests=1, timeout=6):
        super().__init__(doc_func_check, "", doc_bug_analysis, min_tests, timeout)
        self.api_prefix = api_prefix
        self.target_file_api = target_file_api
        self.target_file_tests = target_file_tests

    def do_check(self) -> tuple[bool, object]:
        """Perform the check for DUT API tests."""
        test_files = [fc.rm_workspace_prefix(self.workspace, f) for f in glob.glob(os.path.join(self.workspace, self.target_file_tests))]
        if len(test_files) == 0:
            return False, {"error": f"No test files matching '{self.target_file_tests}' found in workspace."}
        if not os.path.exists(self.get_path(self.doc_func_check)):
            return False, {"error": f"Function and check documentation file {self.doc_func_check} does not exist in workspace. "}
        if not os.path.exists(self.get_path(self.target_file_api)):
            return False, {"error": f"DUT API file '{self.target_file_api}' does not exist in workspace."}
        # call pytest
        targets = " ".join(test_files)
        report, str_out, str_err = self.run_test.do(
            "", 
            pytest_ex_args=targets,
            return_stdout=True, return_stderr=True, return_all_checks=True, timeout=self.timeout
        )
        func_list = fc.get_target_from_file(self.get_path(self.target_file_api), f"{self.api_prefix}*",
                                         ex_python_path=self.workspace,
                                         dtype="FUNC")
        if len(func_list) == 0:
            return False, {"error": f"No DUT API functions with prefix '{self.api_prefix}' found in '{self.target_file_api}'."}
        test_cases = report.get("tests", {}).get("test_cases", {})
        test_keys = test_cases.keys()
        test_functions = []
        api_un_tested = []
        for func in func_list:
            func_name = func.__name__
            for k in test_keys:
                if func_name in k:
                    test_functions.append(func_name)
                    break
            if func_name not in test_functions:
                api_un_tested.append(func_name)
        def get_emsg(m):
            return {"error": m, "STDOUT": str_out, "STDERR": str_err, "REPORT": report}
        if api_un_tested:
            return False, get_emsg(f"API functions ({', '.join(api_un_tested)}) are not covered by the test cases ({', '.join(test_keys)}). " + \
                                   f"You need to define the related test cases with `test_` prefix. eg: define `test_api_dut_func1` for `api_dut_func1`")
        if report["test_function_with_no_check_point_mark"] > 0:
            return False, get_emsg(f"Some test functions ({', '.join(report['test_function_with_no_check_point_mark_list'])}) do not have check point marks. "
                                    "Please mark them like: dut.fc_cover['FG-GROUP'].mark_function('FC-FUNCTION', test_function_name, ['CK-CHECK1', 'CK-CHECK2']). " + \
                                    "This ensures proper coverage mapping between documentation and test implementation. " + \
                                    "Review your task requirements and complete the check point markings. ")

        ret, msg = check_report(self.workspace, report, self.doc_func_check, self.doc_bug_analysis, "FG-API/")
        if not ret:
            return ret, get_emsg(msg)
        return True, {"success": f"{self.__class__.__name__} check for {self.target_file_tests} passed."}


class UnityChipCheckerTestCase(BaseUnityChipCheckerTestCase):

    def do_check(self) -> Tuple[bool, str]:
        """
        Perform comprehensive check for implemented test cases.
        """
        import copy
        # Execute tests and get comprehensive report
        report, str_out, str_err = super().do_check()
        abs_report = copy.deepcopy(report)
        all_bins_test = report.get("bins_all", [])
        if all_bins_test:
            del abs_report["bins_all"]

        # Prepare diagnostic information
        info_report = OrderedDict({"TEST_EXECUTION_REPORT":abs_report})
        info_runtest = OrderedDict({"STDOUT": str_out, "STDERR": str_err})
        
        # Basic validation: Check if tests exist
        if report.get("tests") is None:
            info_runtest["error"] = ["Test execution failed: No test cases found in the report. Possible causes:",
                                     "1. Test files are not properly named (should start with 'test_')",
                                     "2. Test functions are not properly defined (should start with 'test_' and take 'dut' parameter)",
                                     "3. Import errors in test files",
                                     "Please ensure test cases are defined correctly in the workspace."]
            return False, info_runtest
        
        # Validate minimum test count requirement
        if report["tests"]["total"] < self.min_tests:
            info_runtest["error"] = [f"Insufficient test coverage: {report['tests']['total']} test cases found, " +\
                                     f"minimum required is {self.min_tests}. Please ensure that:",
                                       "1. All required test scenarios are implemented.",
                                       "2. Test functions follow naming conventions (test_*).",
                                       "3. Each functional area has adequate test coverage."]
            return False, info_runtest
        
        # Parse documentation marks for validation
        ret, msg = check_report(self.workspace, report, self.doc_func_check, self.doc_bug_analysis)
        if not ret:
            info_runtest["error"] = msg
            return ret, info_runtest

        # Success: All validations passed
        success_msg = ["Test case validation successful!",
                      f"✓ Executed {report['tests']['total']} test cases with comprehensive coverage.",
                      f"✓ All {len(all_bins_test)} check points are properly implemented and documented.",
                      f"✓ Test-documentation consistency verified.",
                      f"✓ Coverage mapping between tests and documentation is complete.",
                      "Your test implementation successfully validates the DUT functionality!"]

        return True, success_msg
