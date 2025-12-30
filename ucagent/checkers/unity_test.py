# -*- coding: utf-8 -*-
"""Unity test checker for UCAgent verification."""

import re
from typing import Tuple
import ucagent.util.functions as fc
from ucagent.util.config import Config
from ucagent.util.log import info, warning
from ucagent.tools.testops import RunUnityChipTest
import os
import glob
import traceback
import copy
import inspect
import ast

from ucagent.checkers.base import Checker, UnityChipBatchTask
from ucagent.checkers.toffee_report import check_report, check_line_coverage
from collections import OrderedDict

class UnityChipCheckerMarkdownFileFormat(Checker):
    def __init__(self, markdown_file_list, no_line_break=False, **kw):
        self.markdown_file_list = markdown_file_list if isinstance(markdown_file_list, list) else [markdown_file_list]
        self.no_line_break = no_line_break

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
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
    def __init__(self, doc_file, leaf_node, min_count=1, must_have_prefix="FG-API", data_key=None, need_human_check=False, **kw):
        """
        Initialize the checker with the documentation file, the specific label (leaf node) to check,
        and the minimum count required for that label.
        """
        self.doc_file = doc_file
        self.leaf_node = leaf_node
        self.min_count = min_count
        self.must_have_prefix = must_have_prefix
        self.data_key = data_key
        self.leaf_count = None
        self.set_human_check_needed(need_human_check)

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Check the label structure in the documentation file."""
        self.leaf_count = None
        msg = f"{self.__class__.__name__} check {self.leaf_node} pass."
        data = []
        data_fmap = {}
        for dfile in fc.find_files_by_pattern(self.workspace, self.doc_file): # Suport multiple doc files
            if not os.path.exists(self.get_path(dfile)):
                return False, {"error": f"Documentation file '{dfile}' does not exist."}
            try:
                data_sub = fc.get_unity_chip_doc_marks(self.get_path(dfile), self.leaf_node, self.min_count)
            except Exception as e:
                error_details = str(e)
                warning(f"Error occurred while checking {dfile}: {error_details}")
                warning(traceback.format_exc())
                emsg = [f"Documentation parsing failed for file '{dfile}': {error_details}."]
                if "\\n" in error_details:
                    emsg.append("Literal '\\n' characters detected - use actual line breaks instead of escaped characters")
                emsg.append({"check_list": [
                    "Malformed tags: Ensure proper format. e.g., <FG-NAME>, <FC-NAME>, <CK-NAME>",
                    *fc.description_func_doc(),
                    "Invalid characters: Use only alphanumeric and hyphen in tag names",
                    "Missing tag closure: All tags must be properly closed",
                    "Encoding issues: Ensure file is saved in UTF-8 format",
                ]})
                return False, {"error": emsg}
            for d in data_sub:
                if d in data_fmap:
                    return False, {"error": f"Duplicate {self.leaf_node} '{d}' found in documentation files: '{data_fmap[d]}' and '{dfile}'." + \
                                            f"All labels must be unique across documentation files ({self.doc_file})."}
                data.append(d)
                data_fmap[d] = dfile
        if self.must_have_prefix:
            find_prefix = False
            for mark in data:
                if mark.startswith(self.must_have_prefix):
                    find_prefix = True
            if not find_prefix:
                return False, {"error": f"In the document ({self.doc_file}), it must have group/."}
        if self.data_key:
            self.smanager_set_value(self.data_key, data)
            info(f"Cache {self.leaf_node} marks(size={len(data)}) to data key '{self.data_key}'.")
        self.leaf_count = len(data)
        return True, {"message": msg, f"{self.leaf_node}_count": len(data)}

    def get_template_data(self):
        return {
            f"COUNT_{self.leaf_node}": f"[{self.leaf_count}]" if self.leaf_count else ""
        }


class UnityChipCheckerDutCreation(Checker):
    def __init__(self, target_file, **kw):
        self.target_file = target_file
        self.update_dut_name(kw["cfg"])

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Check the DUT creation function for correctness."""
        if not os.path.exists(self.get_path(self.target_file)):
            return False, {"error": f"file '{self.target_file}' does not exist."}
        func_list = fc.get_target_from_file(self.get_path(self.target_file), "create_dut",
                                            ex_python_path=self.workspace,
                                            dtype="FUNC")
        if not func_list:
            return False, {"error": f"No 'create_dut' functions found in '{self.target_file}'."}
        if len(func_list) != 1:
            return False, {"error": f"Multiple 'create_dut' functions found in '{self.target_file}'. Expected only one."}
        cdut_func = func_list[0]
        args = fc.get_func_arg_list(cdut_func)
        # check args
        if len(args) != 1 or args[0] != "request":
            return False, {"error": f"The 'create_dut' fixture has only one arg named 'request', but got ({', '.join(args)})."}
        dut = func_list[0](None)
        for need_func in ["Step", "StepRis"]:
            assert hasattr(dut, need_func), f"The 'create_dut' function in '{self.target_file}' did not return a valid DUT instance with '{need_func}' method."
        # check 'get_coverage_data_path'
        func_source = inspect.getsource(cdut_func)
        if "get_coverage_data_path" not in func_source:
            return False, {"error": f"The 'create_dut' function in '{self.target_file}' must call 'get_coverage_data_path(request, new_path=True)' to get a new coverage file path. {fc.tips_of_get_coverage_data_path(self.dut_name)}"}
        # Additional checks can be implemented here
        return True, {"message": f"{self.__class__.__name__} check for {self.target_file} passed."}


class UnityChipCheckerDutFixture(Checker):
    def __init__(self, target_file, **kw):
        self.target_file = target_file
        self.update_dut_name(kw["cfg"])

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Check the fixture implementation for correctness."""
        if not os.path.exists(self.get_path(self.target_file)):
            return False, {"error": f"fixture file '{self.target_file}' does not exist."}
        dut_func = fc.get_target_from_file(self.get_path(self.target_file), "dut",
                                           ex_python_path=self.workspace,
                                           dtype="FUNC")
        if not dut_func:
            return False, {"error": f"No 'dut' fixture found in '{self.target_file}'."}
        if not len(dut_func) == 1:
            return False, {"error": f"Multiple 'dut' fixtures found in '{self.target_file}'. Expected only one."}
        dut_func = dut_func[0]
        # check @pytest.fixture("function")
        if not (hasattr(dut_func, '_pytestfixturefunction') or "pytest_fixture" in str(dut_func)):
            return False, {"error": f"The 'dut' fixture in '{self.target_file}' is not decorated with @pytest.fixture(\"function\")."}
        scope_value = fc.get_fixture_scope(dut_func)
        if isinstance(scope_value, str):
            if scope_value != "function":
                return False, {"error": f"The 'dut' fixture in '{self.target_file}' has invalid scope '{scope_value}'. The expected scope is 'function'."}
        # check args
        args = fc.get_func_arg_list(dut_func)
        if len(args) != 1 or args[0] != "request":
            return False, {"error": f"The 'dut' fixture has only one arg named 'request', but got ({', '.join(args)})."}
        # check yield - first check if it's a generator function
        try:
            source_lines = inspect.getsourcelines(dut_func)[0]
            source_code = ''.join(source_lines)
            # check 'get_coverage_data_path'
            if "get_coverage_data_path" not in source_code:
                return False, {"error": f"The 'dut' fixture in '{self.target_file}' must call 'get_coverage_data_path(request, new_path=False)' to get existed coverage file path. {fc.tips_of_get_coverage_data_path(self.dut_name)}"}
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


class UnityChipCheckerMockComponent(Checker):
    def __init__(self, target_file, min_mock=1, **kw):
        self.target_file = target_file
        self.min_mock = min_mock

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Check the Mock component implementation for correctness."""
        class_count = 0
        mock_file_list = fc.find_files_by_pattern(self.workspace, self.target_file)
        for mock_file in mock_file_list:
            ret, msg = self.do_check_one_file(mock_file)
            if ret == False:
                return False, msg
            class_count += ret
        if class_count < self.min_mock:
            return False, {
                "error": f"Insufficient Mock component coverage: {class_count} Mock classes found, minimum required is {self.min_mock}. " +\
                         f"You need to define Mock components like: 'class Mock<COMPONENT_NAME>:'. in files: {self.target_file}. " + \
                         f"Review your task details and ensure that the Mock components are defined correctly in the target files.",
            }
        return True, {"message": f"{self.__class__.__name__} check for {self.target_file} ({len(mock_file_list)} files) passed."}

    def do_check_one_file(self, mock_file):
        if not os.path.exists(self.get_path(mock_file)):
            return False, {"error": f"Mock component file '{mock_file}' does not exist. " + \
                           f"You need to define Mock components like: 'class Mock<COMPONENT_NAME>:' in the target file: {mock_file}. "}
        class_list = fc.get_target_from_file(self.get_path(mock_file), "Mock*",
                                            ex_python_path=self.workspace,
                                            dtype="CLASS")
        if len(class_list) < 1:
            return False, {
                "error": f"No Mock component class found in file: {mock_file}, You need to define Mock components like: 'class Mock<COMPONENT_NAME>:' in the file: {mock_file}.  ",
            }
        # check on_clock_edge
        for cls in class_list:
            if not hasattr(cls, "on_clock_edge"):
                return False, {
                    "error": f"The Mock class '{cls.__name__}' in file: {mock_file} is missing the required method 'on_clock_edge(self, cycles)'. Please implement this method to handle clock edge events."
                }
            method = getattr(cls, "on_clock_edge")
            args = fc.get_func_arg_list(method)
            if len(args) != 2 or args[0] != "self" or args[1] != "cycles":
                return False, {
                    "error": f"The 'on_clock_edge' method in Mock class '{cls.__name__}' in file {mock_file} must have exactly two arguments: 'self' and 'cycles', but got ({', '.join(args)})."
                }
        info(f"find {len(class_list)} Mock classes in file: {mock_file}.")
        return len(class_list), {"message": f"{self.__class__.__name__} check for {mock_file} passed."}


class UnityChipCheckerBundleWrapper(Checker):
    def __init__(self, target_file, min_bundles=1, **kw):
        self.target_file = target_file
        self.min_bundles = min_bundles

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Check the Bundle wrapper implementation for correctness."""
        if not os.path.exists(self.get_path(self.target_file)):
            return False, {"error": f"Bundle wrapper file '{self.target_file}' does not exist." + \
                           f"You need to define Bundle wrappers like: 'class <Name>(Bundle):' in the target file: {self.target_file}. "}
        bundle_list = fc.get_target_from_file(self.get_path(self.target_file), "*",
                                              ex_python_path=self.workspace,
                                              dtype="CLASS")
        for icls in bundle_list[:]:
            bases = [base.__name__ for base in icls.__bases__]
            if "Bundle" not in bases:
                bundle_list.remove(icls)
        if len(bundle_list) < self.min_bundles:
            return False, {
                "error": f"Insufficient Bundle wrapper coverage: {len(bundle_list)} Bundle classes found, minimum required is {self.min_bundles}. " +\
                         f"You need to define Bundle wrappers like: 'class <Name>(Bundle):' in the target file: {self.target_file}. " + \
                         f"Please refer to the documentation for more details."
            }
        return True, {"message": f"{self.__class__.__name__} check for {self.target_file} passed."}

class UnityChipCheckerEnvFixture(Checker):
    def __init__(self, target_file, min_env=1, force_bundle=False, **kw):
        self.target_file = target_file
        self.min_env = max(1, min_env)
        self.force_bundle = force_bundle # FIXME: currently not used

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Check the Env fixture implementation for correctness."""
        if not os.path.exists(self.get_path(self.target_file)):
            return False, {"error": f"fixture file '{self.target_file}' does not exist."}
        env_func_list = fc.get_target_from_file(self.get_path(self.target_file), "env*",
                                             ex_python_path=self.workspace,
                                             dtype="FUNC")
        for env_func in env_func_list:
            args = fc.get_func_arg_list(env_func)
            if len(args) < 1 or args[0] != "dut":
                return False, {"error": f"The '{env_func.__name__}' Env fixture's first arg must be 'dut', but got ({', '.join(args)})."}
            if not (hasattr(env_func, '_pytestfixturefunction') or "pytest_fixture" in str(env_func)):
                return False, {"error": f"The '{env_func.__name__}' fixture in '{self.target_file}' is not decorated with @pytest.fixture()."}
            scope_value = fc.get_fixture_scope(env_func)
            if isinstance(scope_value, str):
                if scope_value != "function":
                    return False, {"error": f"The '{env_func.__name__}' fixture in '{self.target_file}' has invalid scope '{scope_value}'. The expected scope is 'function'."}
        if len(env_func_list) < self.min_env:
            return False, {"error": f"Insufficient env fixture coverage: {len(env_func_list)} env fixtures found, minimum required is {self.min_env}. "+\
                                    f"You have defined {len(env_func_list)} env fixtures: {', '.join([f.__name__ for f in env_func_list])} in file '{self.target_file}'."}
        return True, {"message": f"{self.__class__.__name__} Env fixture check for {self.target_file} passed."}


class UnityChipCheckerEnvFixtureTest(Checker):
    def __init__(self, target_file, test_dir, min_env_tests=1, timeout=15, **kw):
        self.target_file = target_file
        self.min_env_tests = max(1, min_env_tests)
        self.run_test = RunUnityChipTest()
        self.test_dir = test_dir
        self.timeout = timeout
        self.update_dut_name(kw["cfg"])

    def set_workspace(self, workspace: str):
        """
        Set the workspace for the test case checker.

        :param workspace: The workspace directory to be set.
        """
        super().set_workspace(workspace)
        self.run_test.set_workspace(workspace)
        self.test_dir = self.get_path(self.test_dir)
        assert os.path.exists(self.test_dir), f"Test directory '{self.test_dir}' does not exist in workspace."
        return self

    def do_check(self, timeout, **kw) -> Tuple[bool, object]:
        """Check the Env fixture test implementation for correctness."""
        if not os.path.exists(self.get_path(self.target_file)):
            return False, {"error": f"fixture test file '{self.target_file}' does not exist."}
        env_test_func_list = fc.get_target_from_file(self.get_path(self.target_file), f"test*",
                                             ex_python_path=self.workspace,
                                             dtype="FUNC")
        test_prefix = f"test_api_{self.dut_name}_env_"
        for env_test_func in env_test_func_list:
            if env_test_func.__name__.startswith(test_prefix) is False:
                return False, {"error": f"The Env test function '{env_test_func.__name__}' name must start with '{test_prefix}', but got '{env_test_func.__name__}'."}
            args = fc.get_func_arg_list(env_test_func)
            if len(args) < 1 or args[0] != "env":
                return False, {"error": f"The '{env_test_func.__name__}' Env test function's first arg must be 'env', but got ({', '.join(args)})."}
        if len(env_test_func_list) < self.min_env_tests:
            return False, {"error": f"Insufficient env fixture test coverage: {len(env_test_func_list)} env test functions found, minimum required is {self.min_env_tests}. "+\
                                    f"You have defined {len(env_test_func_list)} env test functions: {', '.join([f.__name__ for f in env_test_func_list])} in file '{self.target_file}'."}
        # run test
        self.run_test.set_pre_call_back(
            lambda p: self.set_check_process(p, self.timeout)  # Set the process for the checker
        )
        timeout = timeout if timeout > 0 else self.timeout
        report, str_out, str_err = self.run_test.do(
            self.test_dir,
            pytest_ex_args=os.path.basename(self.target_file),
            return_stdout=True, return_stderr=True, return_all_checks=True,
            timeout=timeout
        )
        test_pass, test_msg = fc.is_run_report_pass(report, str_out, str_err)
        if not test_pass:
            return False, test_msg
        if not report or "tests" not in report:
            return False, {
                "error": f"Env fixture test execution failed or returned invalid report.",
                "STD_OUT": str_out,
                "STD_ERR": str_err,
            }
        tc_total = report["tests"]["total"]
        tc_failed = report["tests"]["fails"]
        if tc_failed > 0:
            return False, {
                "error": f"Env fixture test failed: {tc_failed}/{tc_total} test cases failed. Need all test cases to pass.",
                "STD_OUT": str_out,
                "STD_ERR": str_err,
            }
        ret, msg = fc.check_has_assert_in_tc(self.workspace, report)
        if not ret:
            return ret, msg
        return True, {"message": f"{self.__class__.__name__} Env fixture test check for {self.target_file} passed."}


class UnityChipCheckerDutApi(Checker):
    def __init__(self, api_prefix, target_file, min_apis=1, **kw):
        self.api_prefix = api_prefix
        self.target_file = target_file
        self.min_apis = min_apis

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Check the DUT API implementation for correctness."""
        if not os.path.exists(self.get_path(self.target_file)):
            return False, {"error": f"DUT API file '{self.target_file}' does not exist."}
        func_list = fc.get_target_from_file(self.get_path(self.target_file), f"{self.api_prefix}*",
                                         ex_python_path=self.workspace,
                                         dtype="FUNC")
        failed_apis = []
        for func in func_list:
            args = fc.get_func_arg_list(func)
            if not args or len(args) < 2:
                failed_apis.append(func)
                continue
            if not args[0].startswith("env"):
                failed_apis.append(func)
            if not args[-1].startswith("max_cycles"):
                failed_apis.append(func)
        if len(failed_apis) > 0:
            return False, {
                "error": f"The following API functions in file '{self.target_file}' have invalid or missing arguments. The first arg must be 'env' and the last arg must be 'max_cycles=default_value'",
                "failed_apis": [f"{func}({', '.join(fc.get_func_arg_list(func))})" for func in failed_apis]
            }
        if len(func_list) < self.min_apis:
            return False, {
                "error": f"Insufficient DUT API coverage: {len(func_list)} API functions found, minimum required is {self.min_apis}. " + \
                         f"You need to define APIs like: 'def {self.api_prefix}<API_NAME>(env, ...)'. " + \
                         f"Review your task details and ensure that the API functions are defined correctly in the target file '{self.target_file}'.",
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

    def __init__(self, test_dir, cov_file, doc_file, check_types, **kw):
        self.test_dir = test_dir
        self.cov_file = cov_file
        self.doc_file = doc_file
        self.check_types = check_types if isinstance(check_types, list) else [check_types]
        for ct in self.check_types:
            if ct not in ["FG", "FC", "CK"]:
                raise ValueError(f"Invalid check type '{ct}'. Must be one of 'FG', 'FC', or 'CK'.")

    def basic_check(self):
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
        return True, groups

    def do_check(self, timeout=0, **kw) -> Tuple[bool, str]:
        """Check the functional coverage groups against the documentation."""
        basic_pass, groups_or_msg = self.basic_check()
        if not basic_pass:
            return basic_pass, groups_or_msg
        groups = groups_or_msg
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
        a, b = self._compare_marks(self._groups_as_marks(func_groups, ctype), doc_groups)
        suggested_msg = "You need make those two files consist in coverage groups."
        if len(a) > 0:
            return False, f"Coverage groups check fail: find {len(a)} {ctype} ({fc.list_str_abbr(a)}) in '{self.cov_file}' but not found them in '{self.doc_file}'. {suggested_msg}"
        if len(b) > 0:
            return False, f"Coverage groups check fail: find {len(b)} {ctype} ({fc.list_str_abbr(b)}) in '{self.doc_file}' but not found them in '{self.cov_file}'. {suggested_msg}"
        info(f"{ctype} coverage {len(doc_groups)} marks check passed")
        return True, "Coverage groups check passed."


class UnityChipCheckerCoverageGroupBatchImplementation(UnityChipCheckerCoverageGroup):
    """
    Checker for Unity chip functional coverage groups batch implementation validation.

    This class validates that all functional coverage groups defined in the documentation
    are implemented in the coverage definition file, ensuring comprehensive DUT verification coverage.
    """

    def __init__(self, test_dir, cov_file, doc_file, batch_size, data_key, **kw):
        super().__init__(test_dir, cov_file, doc_file, "CK", **kw)
        self.data_key = data_key
        assert self.data_key, "data_key is required."
        self.batch_size = batch_size
        self.batch_task = UnityChipBatchTask("check_points", self)

    def get_template_data(self):
        return self.batch_task.get_template_data(
            "TOTAL_POINTS", "COMPLETED_POINTS", "LIST_CURRENT_POINTS"
        )

    def on_init(self):
        self.batch_task.source_task_list = self.smanager_get_value(self.data_key, [])
        self.batch_task.update_current_tbd()
        info(f"Load cached doc ck list(size={len(self.batch_task.source_task_list)}) from data key '{self.data_key}'.")
        return super().on_init()

    def do_check(self, timeout=0, is_complete=False, **kw) -> Tuple[bool, str]:
        """Check the functional coverage groups against the documentation."""
        basic_pass, groups_or_msg = self.basic_check()
        if not basic_pass:
            return basic_pass, groups_or_msg
        current_doc_ck_list = fc.get_unity_chip_doc_marks(self.get_path(self.doc_file), "CK", 1)
        note_msg = []
        self.batch_task.sync_source_task(
            current_doc_ck_list,
            note_msg,
            f"Documentation '{self.doc_file}' CK points changed."
        )
        current_imp_ck_list = self._groups_as_marks(groups_or_msg, "CK")
        self.batch_task.sync_gen_task(
            current_imp_ck_list,
            note_msg,
            "Completed CK points changed."
        )
        return self.batch_task.do_complete(note_msg, is_complete,
                                           f"in file: {self.doc_file}",
                                           f"in file: {self.cov_file}",
                                           " Please implement the check points in its related coverage groups follow the guid documents.")


class BaseUnityChipCheckerTestCase(Checker):
    """
    Checker for Unity chip test cases.

    This class is used to verify the test cases in Unity chip.
    It checks if the test cases meet the specified minimum requirements.
    """

    def __init__(self, doc_func_check=None, test_dir=None, doc_bug_analysis=None, min_tests=1, timeout=15, ignore_ck_prefix="",
                 data_key=None, ret_std_error=True, ret_std_out=True, batch_size=1000, need_human_check=False, **extra_kwargs):
        self.doc_func_check = doc_func_check
        self.doc_bug_analysis = doc_bug_analysis
        self.test_dir = test_dir
        self.min_tests = min_tests
        self.timeout = timeout
        self.ignore_ck_prefix = ignore_ck_prefix
        self.data_key = data_key
        self.extra_kwargs = extra_kwargs
        self.ret_std_error = ret_std_error
        self.ret_std_out = ret_std_out
        self.batch_size = batch_size
        self.run_test = RunUnityChipTest()
        self.set_human_check_needed(need_human_check)

    def set_workspace(self, workspace: str):
        """
        Set the workspace for the test case checker.

        :param workspace: The workspace directory to be set.
        """
        super().set_workspace(workspace)
        self.run_test.set_workspace(workspace)
        if self.test_dir:
            if not os.path.exists(self.get_path(self.test_dir)):
                warning(f"Test directory '{self.test_dir}' does not exist in workspace.")
        return self

    def do_check(self, pytest_args="", timeout=0, **kw) -> Tuple[bool, str]:
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
        timeout = timeout if timeout > 0 else self.timeout
        return self.run_test.do(
            self.test_dir,
            pytest_ex_args=pytest_args,
            return_stdout=True, return_stderr=True, return_all_checks=True, timeout=timeout
        )


class UnityChipCheckerTestFree(BaseUnityChipCheckerTestCase):

    def do_check(self, pytest_args="", timeout=0, return_line_coverage=False, detail=False, **kw):
        """call pytest to run the test cases."""
        report, str_out, str_err = super().do_check(pytest_args=pytest_args, timeout=timeout, **kw)
        test_pass, test_msg = fc.is_run_report_pass(report, str_out, str_err)
        if not test_pass:
            return False, test_msg
        # refine report:
        free_report = OrderedDict({
            "run_test_success": report.get("run_test_success", False),
            "tests": report.get("tests", {}),
        })
        marked_bins = []
        failed_check_point_list = report.get("failed_check_point_list", [])
        for b in report.get("all_check_point_list", []):
            if b not in failed_check_point_list:
                marked_bins.append(b)
                continue
        free_report["marked_check_point_list"] = marked_bins
        if return_line_coverage:
            line_coverage_data = {}
            line_coverage_file = self.extra_kwargs.get("coverage_json", "uc_test_report/line_dat/code_coverage.json")
            if not os.path.exists(self.get_path(line_coverage_file)):
                line_coverage_data["error"] = f"Line coverage file '{line_coverage_file}' does not exist in workspace."
            else:
                try:
                    line_coverage_data = fc.parse_un_coverage_json(
                        line_coverage_file,
                        self.workspace
                    )
                except Exception as e:
                    line_coverage_data["error"] = f"Failed to parse line coverage file '{line_coverage_file}': {str(e)}."
        ret = OrderedDict({
            "REPORT": free_report})
        if not detail:
            if self.ret_std_out:
                ret.update({"STDOUT": str_out})
            if self.ret_std_error:
                ret.update({"STDERR": str_err})
        else:
            ret.update({
                "STDOUT": str_out,
                "STDERR": str_err,
            })
        if return_line_coverage:
            ret["LINE_COVERAGE"] = line_coverage_data
        return True, ret


class UnityChipCheckerTestTemplate(BaseUnityChipCheckerTestCase):

    def get_template_data(self):
        if hasattr(self, "batch_task"):
            data = self.batch_task.get_template_data("TOTAL_CKS", "COVERED_CKS", "LIST_CKS_TO_BE_COVERED")
            data["CASE_TESTS_COUNT"] = self.total_tests_count if hasattr(self, "total_tests_count") else "-"
            return data
        return {
            "TOTAL_CKS":      "-",
            "COVERED_CKS":    "-",
            "LIST_CKS_TO_BE_COVERED": [],
            "CASE_TESTS_COUNT":    "-",
        }

    def on_init(self):
        self.total_tests_count = 0
        self.batch_task = UnityChipBatchTask("check_points", self)
        self.batch_task.source_task_list = fc.get_unity_chip_doc_marks(self.get_path(self.doc_func_check), leaf_node="CK")
        self.batch_task.update_current_tbd()
        info(f"Load all doc ck list(size={len(self.batch_task.source_task_list)}) from doc file '{self.doc_func_check}'.")
        return super().on_init()

    def do_check(self, timeout=0, is_complete=False, **kw) -> Tuple[bool, str]:
        """
        Perform the check for test templates.

        Returns:
            Tuple[bool, str]: A tuple where the first element is a boolean indicating success or failure,
                              and the second element is a message string.
        """
        report, str_out, str_err = super().do_check(timeout=timeout, **kw)
        test_pass, test_msg = fc.is_run_report_pass(report, str_out, str_err)
        if not test_pass:
            return False, test_msg
        raw_report = copy.deepcopy(report)
        all_bins_test = report.get("all_check_point_list", [])
        msg_report = fc.clean_report_with_keys(report,
                                               ["tests.test_cases",
                                                "failed_test_case_with_check_point_list"])
        info_report = OrderedDict({"TEST_REPORT": msg_report})
        info_runtest = OrderedDict({"TEST_REPORT": msg_report})
        test_cases = report.get("tests", {}).get("test_cases", None)
        if test_cases is None:
            info_runtest["error"] = "No test cases found in the report. " +\
                                    "Please ensure that the test report is generated correctly."
            return False, info_runtest
        self.total_tests_count = len([k for k, _ in test_cases.items() if not (self.ignore_ck_prefix in k or ":"+self.ignore_ck_prefix in k)])
        if self.ret_std_out:
            info_report.update({"STDOUT": str_out})
            info_runtest.update({"STDOUT": str_out})
        if self.ret_std_error:
            info_report.update({"STDERR": str_err})
            info_runtest.update({"STDERR": str_err})
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
            all_bins_docs = fc.get_unity_chip_doc_marks(self.get_path(self.doc_func_check), leaf_node="CK")
        except Exception as e:
            info_report["error"] = f"Failed to parse the function and check documentation file {self.doc_func_check}: {str(e)}. " + \
                                    "Review your task requirements and the file format to fix your documentation file."
            return False, info_report

        # Additional template-specific validations
        template_validation_result = self._validate_template_structure(report, str_out, str_err)
        if not template_validation_result[0]:
            info_runtest["error"] = template_validation_result[1]
            return False, info_runtest

        # check batch
        if not is_complete:
            note_msg = []
            if report['unmarked_check_points'] > 0:
                marked_bins = [ck for ck in all_bins_test if ck not in report['unmarked_check_point_list']]
            else:
                marked_bins = all_bins_test
            self.batch_task.sync_source_task(all_bins_docs, note_msg, f"{self.doc_func_check} file CK points changed.")
            self.batch_task.sync_gen_task(marked_bins, note_msg, "Test cases CK points changed.")
            ckpass, emssage = self.batch_task.do_complete(note_msg,
                                                          is_complete,
                                                          f"in file: {self.doc_func_check}",
                                                          f"in dir: {self.test_dir}",
                                                          " Please mark the check points in its related test functions using 'mark_function' correctly.")
            if not ckpass:
                return ckpass, emssage

        # complete check
        bins_not_in_docs = []
        bins_not_in_test = []
        for b in all_bins_test:
            if b not in all_bins_docs:
                bins_not_in_docs.append(b)
        for b in all_bins_docs:
            if b not in all_bins_test:
                bins_not_in_test.append(b)
        if len(bins_not_in_docs) > 0:
            info_runtest["error"] = f"The follow {len(bins_not_in_docs)} check points: {fc.list_str_abbr(bins_not_in_docs)} are not defined in the documentation file {self.doc_func_check} but defined in the test cover group. " + \
                                     "Please ensure that all check points in the test cover group are defined in the documentation file. " + \
                                     "Review your task requirements and the test cases."
            return False, info_runtest
        if len(bins_not_in_test) > 0:
            info_runtest["error"] = f"The follow {len(bins_not_in_test)} check points: {fc.list_str_abbr(bins_not_in_test)} are defined in the documentation file {self.doc_func_check} but not defined in the test cover group. " + \
                                     "Please ensure that all check points defined in the documentation are also in the the test cover group. " + \
                                     "Review your task requirements and the test cases."
            return False, info_runtest

        if report['unmarked_check_points'] > 0:
            unmark_check_points = report['unmarked_check_point_list']
            if len(unmark_check_points) > 0:
                info_runtest["error"] = f"Test template validation failed, cannot find the follow {len(unmark_check_points)} check points: `{fc.list_str_abbr(unmark_check_points)}` " + \
                                         "in the test templates. All check points defined in the documentation must be associated with test cases using 'mark_function'. " + \
                                         fc.description_mark_function_doc() + \
                                         "This ensures proper coverage mapping between documentation and test implementation. " + \
                                         "Review your task requirements and complete the check point markings. "
                return False, info_runtest

        if report['test_function_with_no_check_point_mark'] > 0:
            unmarked_functions = report['test_function_with_no_check_point_mark_list']
            if len(unmarked_functions) > 0:
                mark_function_desc = fc.description_mark_function_doc(unmarked_functions, self.workspace, self.stage_manager.tool_run_test_cases, timeout)
                info_runtest["error"] = f"Test template validation failed: Found {report['test_function_with_no_check_point_mark']} test functions without correct check point marks. " + \
                                         mark_function_desc
                return False, info_runtest

        # Success message with template-specific details
        info_report["success"] = ["Test template validation successful!",
                                 f"✓ Generated {report['tests']['total']} test case templates (all properly failing as expected).",
                                 f"✓ All {len(all_bins_test)} check points are properly documented and marked in test functions.",
                                 f"✓ Coverage mapping is consistent between documentation and test implementation.",
                                 f"✓ Template structure follows the required format with proper TODO comments and fail assertions.",
                                 "Your test templates are ready for implementation! Each test function provides clear guidance for the actual test logic to be implemented."]
        if self.data_key:
            self.smanager_set_value(self.data_key, raw_report)
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
        test_cases = report.get("tests", {}).get("test_cases", None)
        if test_cases is None:
            return False, "Test template structure validation failed: No test cases found in the report. " +\
                          "Please ensure that the test report is generated correctly."
        for fv, rt in test_cases.items():
            if self.ignore_ck_prefix and ":"+self.ignore_ck_prefix in fv:
                continue
            if rt == "PASSED":
                passed_test.append(fv + "=" + rt)

        must_fail = self.extra_kwargs.get("template_must_fail", True)
        if passed_test and must_fail:
            return False, f"Test template structure validation failed: Not all test functions ({fc.list_str_abbr(passed_test)}) are properly failing. " + \
                          f"In test templates, ALL test functions (except test functions with prefix '{self.ignore_ck_prefix}') must fail with 'assert False, \"Not implemented\"' to indicate they are templates. " + \
                           "This prevents incomplete templates from being accidentally considered as passing tests. " + \
                           "Please ensure every test function ends with the required fail assertion."
        # Check for proper TODO comments (this would require parsing the actual test files)
        # For now, we rely on the fact that properly structured templates should fail with "Not implemented"
        if self.ret_std_out and self.ret_std_error:
            if must_fail:
                if "Not implemented" not in str_out and "Not implemented" not in str_err:
                    info(f"STDOUT: {str_out}")
                    info(f"STDERR: {str_err}")
                    return False, "Test template structure validation failed: Template functions should contain 'Not implemented' messages. " + \
                                  "Test templates must include 'assert False, \"Not implemented\"' statements to clearly indicate unfinished implementation. " + \
                                  "This helps distinguish between actual test failures and template placeholders. " + \
                                  "If you have implemented as the template requires, please make sure the `mark_function` works correctly."
        return True, "Template structure validation passed."


class UnityChipCheckerDutApiTest(BaseUnityChipCheckerTestCase):

    def __init__(self, api_prefix, target_file_api, target_file_tests, doc_func_check, doc_bug_analysis, min_tests=1, timeout=15, **kw):
        super().__init__(doc_func_check, "", doc_bug_analysis, min_tests, timeout, **kw)
        self.api_prefix = api_prefix
        self.target_file_api = target_file_api
        self.target_file_tests = target_file_tests

    def do_check(self, timeout=0, **kw) -> tuple[bool, object]:
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
        assert isinstance(timeout, int), f"timeout must be an integer. But got {type(timeout)}:{timeout}."
        timeout = timeout if timeout > 0 else self.timeout
        report, str_out, str_err = self.run_test.do(
            "", 
            pytest_ex_args=targets,
            return_stdout=True, return_stderr=True, return_all_checks=True, timeout=timeout
        )
        test_pass, test_msg = fc.is_run_report_pass(report, str_out, str_err)
        if not test_pass:
            return False, test_msg
        report_copy = fc.clean_report_with_keys(report)
        func_list = fc.get_target_from_file(self.get_path(self.target_file_api), f"{self.api_prefix}*",
                                         ex_python_path=self.workspace,
                                         dtype="FUNC")
        if len(func_list) == 0:
            return False, {"error": f"No DUT API functions with prefix '{self.api_prefix}' found in '{self.target_file_api}'. "+\
                                     "Note: the api name is case-sensitive."}
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
            msg =  {"error": m, "REPORT": report_copy}
            if self.ret_std_out:
                msg["STDOUT"] = str_out
            if self.ret_std_error:
                msg["STDERR"] = str_err
            if "Signal bind error" in str_err:
                msg["WARNING"] = "The DUT signals are not handled properly by toffee Bundle, you should fix this issue first."
            return msg
        if api_un_tested:
            info(f"Missed APIs: {','.join(api_un_tested)}")
            info(f"Found test APIs: {','.join(test_functions)}")
            info(f"All test cases: {','.join(test_keys)}")
            return False, get_emsg(f"Missing test functions for {len(api_un_tested)} API(s): {fc.list_str_abbr(api_un_tested)} (Defined in file: {self.target_file_api}). " + \
                                   f"Please create the missing functions: {fc.list_str_abbr(['test_' + f for f in api_un_tested])} (format: test_<api_name>, add prefix 'test_' to the API name). " + \
                                   f"Note: All dut APIs must be defined in: {self.target_file_api}. ")
        test_count_no_check_point_mark = report["test_function_with_no_check_point_mark"]
        if test_count_no_check_point_mark > 0:
            func_list = report['test_function_with_no_check_point_mark_list']
            mark_function_desc = fc.description_mark_function_doc(func_list, self.workspace, self.stage_manager.tool_run_test_cases, timeout)
            return False, get_emsg(f"Find {test_count_no_check_point_mark} functions do not have correct check point marks. " + \
                                     mark_function_desc + \
                                    "This ensures proper coverage mapping between documentation and test implementation. " + \
                                    "Review your task requirements and complete the check point markings. ")

        ret, msg, _ = check_report(self.workspace, report, self.doc_func_check, self.doc_bug_analysis, "FG-API/", func_RunTestCases=self.stage_manager.tool_run_test_cases, timeout_RunTestCases=timeout)
        if not ret:
            return ret, get_emsg(msg)
        ret, msg = fc.check_has_assert_in_tc(self.workspace, report)
        if not ret:
            return ret, get_emsg(msg["error"])
        return True, {"success": f"{self.__class__.__name__} check for {self.target_file_tests} passed."}


class UnityChipCheckerBatchTestsImplementation(BaseUnityChipCheckerTestCase):

    def __init__(self, **kw):
        super().__init__(**kw)
        assert self.data_key, "data_key is required."
        self.current_test_cases = [
            # "test_case_name"
        ]
        self.total_test_cases = [
            # (test_case_name, is_completed: boolean)
        ]
        self.pre_report_file = self.extra_kwargs.get("pre_report_file", None)
        info(f"{self.__class__.__name__} Batch size: {self.batch_size}")
        assert self.test_dir is not None, f"Need set test directory '{self.test_dir}'."

    def get_template_data(self):
        completed = sum([t[1] for t in self.total_test_cases])
        total = len(self.total_test_cases)
        is_valid = total > 0
        return {
            "COMPLETED_CASES":    completed if is_valid else "-",
            "TOTAL_CASES":        total if is_valid else "-",
            "LIST_CURRENT_CASES": self.current_test_cases,
            "TEST_BATCH_RUN_ARGS": self.get_run_args(self.test_dir)[0] if is_valid else "-",
        }

    def get_run_args(self, test_dir=None):
        failed_tests_files = set()
        target_tests = ""
        for t in self.current_test_cases:
            args = t.split(":")
            test_file, test_parm = args[0], (":"+":".join(args[1:])) if len(args) > 1 else ""
            test_path = self.get_path(test_file)
            if not os.path.exists(test_path):
                failed_tests_files.add(test_file)
            f = self.get_relative_path(test_file, test_dir)
            target_tests += f"{f}{test_parm} "
        return target_tests.strip(), list(failed_tests_files)

    def rm_line_no(self, s):
        return re.sub(r":\d+-\d+", "", s)

    def on_init(self):
        self.check_data()
        return super().on_init()

    def check_data(self):
        if len(self.total_test_cases) == 0 and not self._is_init:
            pre_report = self.smanager_get_value(self.data_key, None)
            if pre_report is None:
                assert self.pre_report_file is not None, "Need set 'pre_report_file' to load previous test report from a file."
                assert os.path.exists(self.get_path(self.pre_report_file)), f"Previous report file '{self.pre_report_file}' does not exist."
                info(f"Loading previous test report from file '{self.pre_report_file}'...")
                pre_report = fc.load_json_file(self.get_path(self.pre_report_file))
            else:
                if self.pre_report_file is not None:
                    fc.save_json_file(self.get_path(self.pre_report_file), pre_report)
                    info(f"Saved previous test report to file '{self.pre_report_file}'.")
            info(f"Loaded previous test report complete.")
            passed_tc = []
            failed_tc = []
            for k,v in pre_report.get("tests", {}).get("test_cases", {}).items():
                if ":"+self.ignore_ck_prefix in k:
                    info(f"{self.__class__.__name__} ignore test case: {k}")
                    continue
                if v == "PASSED":
                    passed_tc.append(k)
                else:
                    failed_tc.append(k)
            if len(passed_tc) != 0:
                warning(f"No test cases defined for implementation. However, {len(passed_tc)} test cases are already passing: {fc.list_str_abbr(passed_tc)}. ")
            self.total_test_cases = [(self.rm_line_no(k), False) for k in sorted(failed_tc)]
            if len(self.total_test_cases) == 0:
                return False, "No test cases found for implementation. All test cases are already passing. Nothing to do."
            info(f"Total {len(self.total_test_cases)} test cases need to be implemented.")
        if len(self.current_test_cases) == 0:
            self.current_test_cases = [t[0] for t in self.total_test_cases if not t[1]][:self.batch_size]
        info(f"Current batch: {len(self.current_test_cases)} test cases to implement: {fc.list_str_abbr(self.current_test_cases)}")
        info(f"Completed {sum([t[1] for t in self.total_test_cases])} out of {len(self.total_test_cases)} test cases.")
        return True, ""

    def do_check(self, timeout=0, is_complete=False, **kw) -> Tuple[bool, str]:
        """run batch of tests and check result."""
        success, msg = self.check_data()
        if not success:
            return False, {"error": msg}
        if len(self.current_test_cases) == 0:
            return True, {"success": "All test cases have been implemented! Use tool `Complete to` finish this stage."}
        target_tests, failed_tests_files = self.get_run_args(self.test_dir)
        if len(failed_tests_files) > 0:
            return False, {"error": f"The following test files do not exist: {fc.list_str_abbr(failed_tests_files)}. " + \
                            "Please check your test case names and ensure they are correct."}
        info(f"Checking {len(self.current_test_cases)} test cases: {target_tests}")
        report, str_out, str_err = super().do_check(pytest_args=target_tests, timeout=timeout, **kw)
        test_pass, test_msg = fc.is_run_report_pass(report, str_out, str_err)
        if not test_pass:
            return False, test_msg
        error_msgs = {}
        if self.ret_std_out:
            error_msgs["STDOUT"] = str_out
        if self.ret_std_error:
            error_msgs["STDERR"] = str_err
        return_tests = {self.rm_line_no(k):v for k, v in report.get("tests", {}).get("test_cases", {}).items()}
        if len(return_tests) == 0:
            error_msgs["error"] = "No test cases found in the report. Please ensure that the test cases are defined correctly in the workspace."
            return False, error_msgs
        # check missing test cases
        missing_tests = [k for k in self.current_test_cases if k not in return_tests.keys()]
        extends_tests = [k for k in return_tests.keys() if k not in self.current_test_cases]
        info(f"Returned {len(return_tests)} test cases, missing {len(missing_tests)}, extends {len(extends_tests)}")
        if len(missing_tests) > 0:
            info(f"implemented cases: {fc.list_str_abbr(return_tests.keys())}")
            error_msgs["error"] = f"The following test cases: `{fc.list_str_abbr(missing_tests)}` are missing in the tests implementation. " + \
                                   "Please ensure that all test cases are properly implemented and reported."
            return False, error_msgs

        ret, msg, _ = check_report(self.workspace, report, self.doc_func_check, self.doc_bug_analysis, only_marked_ckp_in_tc=True, func_RunTestCases=self.stage_manager.tool_run_test_cases, timeout_RunTestCases=timeout)
        report  = fc.clean_report_with_keys(report, ["all_check_point_list", "unmarked_check_points", "unmarked_check_point_list", "failed_check_point_list"])
        error_msgs["REPORT"] = report
        if not ret:
            error_msgs["error"] = msg
            return ret, error_msgs
        ret, msg = fc.check_has_assert_in_tc(self.workspace, report)
        if not ret:
            error_msgs["error"] = msg["error"]
            return ret, error_msgs
        # update total test cases status
        for i, (tc, _) in enumerate(self.total_test_cases):
            if tc in return_tests:
                self.total_test_cases[i] = (tc, True)
        self.current_test_cases = [t[0] for t in self.total_test_cases if not t[1]][:self.batch_size]
        if len(self.current_test_cases) == 0:
            return True, {"success": "Congratulations! All test cases have been implemented! Use tool `Complete to` finish this stage."}
        if is_complete:
            return False, {"error": f"There are still {len(self.current_test_cases)} test cases remaining to be implemented: {fc.list_str_abbr(self.current_test_cases)}. " + \
                                    f"Test case implemention progress: {sum([t[1] for t in self.total_test_cases])}/{len(self.total_test_cases)}. " + \
                                     "Please continue implementing the remaining test cases before completing this stage."}
        return False, {"success": f"Great! {len(self.current_test_cases)} test cases have been successfully implemented. " + \
                                  f"Next, please proceed to implement the following {len(self.current_test_cases)} test cases: {fc.list_str_abbr(self.current_test_cases)}. " + \
                                  f"Test case implemention progress: {sum([t[1] for t in self.total_test_cases])}/{len(self.total_test_cases)}. "}


class UnityChipCheckerTestCase(BaseUnityChipCheckerTestCase):

    def get_zero_bug_rate_list(self):
        zero_list = []
        if not self._is_init:
            return zero_list
        try:
            for bg in fc.get_unity_chip_doc_marks(os.path.join(self.workspace, self.doc_bug_analysis), leaf_node="BG"):
                try:
                    rate = int(bg.split("-")[-1])
                    if rate == 0:
                        zero_list.append(bg)
                except Exception as e:
                    pass
        except Exception as e:
            pass
        return zero_list

    def get_template_data(self):
        zero_rate = ""
        zero_list = self.get_zero_bug_rate_list()
        if len(zero_list) > 0:
            zero_rate = f"(Find {len(zero_list)}: {', '.join(zero_list[:10])}{' ... ' if len(zero_list) > 10 else ''})"
        return {
                "BUG_ZERO_RATE_LIST": zero_rate
            }

    def do_check(self, timeout=0, **kw) -> Tuple[bool, str]:
        """
        Perform comprehensive check for implemented test cases.
        """
        # Execute tests and get comprehensive report
        report, str_out, str_err = super().do_check(timeout=timeout, **kw)
        test_pass, test_msg = fc.is_run_report_pass(report, str_out, str_err)
        if not test_pass:
            return False, test_msg
        abs_report = copy.deepcopy(report)
        all_bins_test = report.get("all_check_point_list", [])
        abs_report = fc.clean_report_with_keys(report)

        # Prepare diagnostic information
        info_runtest = OrderedDict()
        if self.ret_std_out:
            info_runtest["STDOUT"] = str_out
        if self.ret_std_error:
            info_runtest["STDERR"] = str_err
        info_runtest["TEST_REPORT"] = abs_report

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
        zero_list = self.get_zero_bug_rate_list()
        zero_rate_msg = f"Note: Find {len(zero_list)} bugs are marked with zero occurrence rate in the bug analysis document: {', '.join(zero_list[:10])}{' ... ' if len(zero_list) > 10 else '. '}" + \
                         "You may want to review and update their occurrence rates if they were encountered during testing. If these bugs are not applicable, you can ignore this message."

        ret, msg, marked_bugs = check_report(self.workspace, report, self.doc_func_check, self.doc_bug_analysis, func_RunTestCases=self.stage_manager.tool_run_test_cases, timeout_RunTestCases=timeout)
        if not ret:
            info_runtest["error"] = msg
            if len(zero_list) > 0:
                if isinstance(info_runtest["error"], list):
                    info_runtest["error"].append(zero_rate_msg)
                elif isinstance(info_runtest["error"], str):
                    info_runtest["error"] += " " + zero_rate_msg
                else:
                    warning(f"Cannot append zero rate message to error of type {type(info_runtest['error'])}.")
            return ret, info_runtest

        ret, msg = fc.check_has_assert_in_tc(self.workspace, report)
        if not ret:
            info_runtest["error"] = msg
            return False, info_runtest

        # Success: All validations passed
        success_msg = ["Test case validation successful!",
                      f"✓ Executed {report['tests']['total']} test cases with comprehensive coverage.",
                      f"✓ All {len(all_bins_test)} check points are properly implemented and documented.",
                      f"✓ Test-documentation consistency verified.",
                      f"✓ Marked {marked_bugs} bugs in file: {self.doc_bug_analysis}.",
                      "Your test implementation successfully validates the DUT functionality!"]
        if len(zero_list) > 0:
            success_msg.append(zero_rate_msg)
        if marked_bugs == 0:
            success_msg.append("Warning: No bugs were marked in the bug analysis document. If issues were found during testing, please ensure they are documented appropriately.")
            success_msg.extend(fc.description_bug_doc())
        return True, success_msg


class UnityChipCheckerTestCaseWithLineCoverage(UnityChipCheckerTestCase):

    def __init__(self, doc_func_check=None,
                 test_dir=None, doc_bug_analysis=None, cfg=None,
                 min_tests=1, timeout=15, ignore_ck_prefix="", data_key=None,
                 **extra_kwargs):
        super().__init__(doc_func_check, test_dir, doc_bug_analysis, min_tests, timeout, ignore_ck_prefix, data_key, **extra_kwargs)
        self.extra_kwargs = extra_kwargs
        assert cfg is not None, "cfg is required."
        self.update_dut_name(cfg)
        dut_name = self.dut_name
        self.coverage_json =     self.extra_kwargs.get("coverage_json",    "uc_test_report/line_dat/code_coverage.json")
        self.coverage_analysis = self.extra_kwargs.get("coverage_analysis", f"unity_test/{dut_name}_line_coverage_analysis.md")
        self.coverage_ignore =   self.extra_kwargs.get("coverage_ignore",   f"unity_test/tests/{dut_name}.ignore")
        self.min_line_coverage = self.extra_kwargs.get("min_line_coverage", 0.8)
        self.cur_line_coverage = None

    def on_init(self):
        self.cur_line_coverage = 0.0
        return super().on_init()

    def get_template_data(self):
        if self.cur_line_coverage is None:
            cov = f"({self.min_line_coverage*100:.2f})"
        else:
            cov = f"({self.cur_line_coverage*100:.2f}/{self.min_line_coverage*100:.2f})"
        return {
            "COVERAGE_COMPLETE": cov
        }

    def do_check(self, timeout=0, **kw) -> Tuple[bool, str]:
        """check test case and line coverage."""
        ret, msg = super().do_check(timeout=timeout, **kw)
        if not ret:
            return ret, msg
        ret, msg, self.cur_line_coverage = check_line_coverage(self.workspace, self.coverage_json, self.coverage_ignore, self.coverage_analysis, self.min_line_coverage)
        return ret, msg
