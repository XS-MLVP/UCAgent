#coding: utf-8

import os
from ucagent.tools.testops import RunUnityChipTest
import ucagent.util.functions as fc
from ucagent.checkers.base import Checker, UnityChipBatchTask
from typing import Tuple
from ucagent.util.log import info
from collections import OrderedDict


class UnityChipCheckerTestMockTestBatch(Checker):

    def __init__(self, target_file, test_file_prefix, test_prefix, test_dir="tests",
                 first_arg="",
                 last_arg="",
                 batch_size=1, 
                 min_file_tests=1, timeout=300, **kw):
        self.target_file = target_file
        self.test_file_prefix = test_file_prefix
        self.test_prefix = test_prefix
        self.test_dir = test_dir
        self.first_arg = first_arg
        self.last_arg = last_arg
        self.batch_size = batch_size
        self.min_file_tests = min_file_tests
        self.timeout = timeout
        self.run_test = RunUnityChipTest()
        self.batch_task = UnityChipBatchTask("mock_test_file", self)
        self.update_dut_name(kw["cfg"])
        assert "*" in target_file, "The target_file must contain a wildcard '*' to match multiple Mock files."

    def get_template_data(self):
        ret = self.batch_task.get_template_data(
            "TOTAL_MOCKS", "COMPLETED_MOCKS", "LIST_CURRENT_MOCKS"
        )
        return ret

    def on_init(self):
        self.batch_task.source_task_list = fc.find_files_by_pattern(
            self.workspace, self.target_file
        )
        self.batch_task.update_current_tbd()
        info(f"Found {len(self.batch_task.source_task_list)} mock component files to check.")
        return super().on_init()

    def set_workspace(self, workspace: str):
        """
        Set the workspace for the test case checker.

        :param workspace: The workspace directory to be set.
        """
        super().set_workspace(workspace)
        self.run_test.set_workspace(workspace)
        return self

    def do_check(self, timeout=0, is_complete=False, **kw) -> Tuple[bool, object]:
        """Check the Mock test implementation for correctness."""
        test_dir_full_path = self.get_path(self.test_dir)
        if not os.path.exists(test_dir_full_path):
            return False, {"error": f"test directory '{self.test_dir}' does not exist in workspace."}
        # Sync source task
        self.batch_task.source_task_list = fc.find_files_by_pattern(self.workspace, self.target_file)
        self.batch_task.update_current_tbd()
        if len(self.batch_task.source_task_list) == 0:
            return False, {
                "error": f"No mock component files found with pattern '{self.target_file}' in workspace."
            }
        # Do check in batch
        task_map = OrderedDict()
        no_test_files = []
        mock_file_prefix = os.path.basename(self.target_file).split("*")[0]
        for task_file in self.batch_task.tbd_task_list:
            # {OUT}/tests/{DUT}_mock_*.py => {OUT}/tests/test_{DUT}_mock_*.py
            dir_path = os.path.dirname(task_file)
            base_name = os.path.basename(task_file)
            mock_name = base_name.split(".py")[0].replace(mock_file_prefix, "")
            if not mock_name:
                return False, {
                    "error": f"Cannot extract MockComponentName from file '{task_file}'. Please ensure the file name is correct: `{mock_file_prefix}<MockComponentName>.py`"
                }
            test_file = dir_path + "/" + self.test_file_prefix + mock_name + "*.py"
            test_file_list = fc.find_files_by_pattern(self.workspace, test_file)
            if not test_file_list:
                no_test_files.append(f"{task_file} => {test_file} (not found)")
                continue
            task_map[task_file] = test_file_list
        if len(no_test_files) > 0:
            return False, {
                "error": "No corresponding test files found for some mock component files.",
                "details": no_test_files
            }
        pass_results = []
        fail_results = OrderedDict()
        for target_mock, target_tests in task_map.items():
            info(f"Checking mock component test file(s) for '{target_mock}': {', '.join(target_tests)}")
            ret, msg = self.do_one_check(target_tests, test_dir_full_path, timeout)
            if not ret:
                fail_results[target_mock] = msg
            else:
                pass_results.append(target_mock)
        note_msg = []
        # Complete
        self.batch_task.sync_gen_task(
            self.batch_task.gen_task_list + pass_results,
            note_msg,
            "Completed file changed."
        )
        if fail_results:
            return False, {
                "error": "Some mock component test files check failed.",
                "details": fail_results
            }
        return self.batch_task.do_complete(note_msg, is_complete, "", "", "")


    def do_one_check(self, test_files, test_dir_full_path, timeout) -> Tuple[bool, object]:
        if len(test_files) == 0:
            tfiles = ', '.join(self.target_file)
            return False, {"error": f"No test files found with pattern '{tfiles}' in workspace."}
        error_cases = []
        for tfile in test_files:
            if test_dir_full_path not in self.get_path(tfile):
                error_cases.append(f"The test file '{tfile}' is not under the test directory '{self.test_dir}'.")
                continue
            test_func_list = fc.get_target_from_file(self.get_path(tfile), f"test*",
                                                         ex_python_path=self.workspace,
                                                         dtype="FUNC")
            for test_func in test_func_list:
                if test_func.__name__.startswith(self.test_prefix) is False:
                    error_cases.append(f"The '{test_func.__name__}' test function's name must start with '{self.test_prefix}'.")
                    continue
                args = fc.get_func_arg_list(test_func)
                if self.first_arg and (len(args) < 1 or args[0] != self.first_arg):
                    error_cases.append(f"The '{test_func.__name__}' test function's first arg must be '{self.first_arg}', but got ({', '.join(args)}).")
                if self.last_arg and (len(args) < 1 or args[-1] != self.last_arg):
                    error_cases.append(f"The '{test_func.__name__}' test function's last arg must be '{self.last_arg}', but got ({', '.join(args)}).")
            if len(test_func_list) < self.min_file_tests:
                error_cases.append(f"Insufficient testcases: {len(test_func_list)} test functions found, minimum required is {self.min_file_tests} in file '{tfile}'. "+
                                    "Please ensure you have implemented enough test cases (need pytest function based not class based).")
        if len(error_cases) > 0:
            return False, {
                "error": "Check test functions failed.",
                "details": error_cases
            }
        # Run test
        timeout = timeout if timeout > 0 else self.timeout
        self.run_test.set_pre_call_back(
            lambda p: self.set_check_process(p, timeout + 10)  # Set the process for the checker
        )
        py_case_files = [fc.rm_workspace_prefix(test_dir_full_path,
                                                self.get_path(t)) for t in test_files]
        report, str_out, str_err = self.run_test.do(
            test_dir_full_path,
            pytest_ex_args=" ".join(py_case_files),
            return_stdout=True, return_stderr=True, return_all_checks=True,
            timeout=timeout
        )
        test_pass, test_msg = fc.is_run_report_pass(report, str_out, str_err)
        if not test_pass:
            return False, test_msg
        if not report or "tests" not in report:
            return False, {
                "error": f"Test execution failed or returned invalid report.",
                "STD_OUT": str_out,
                "STD_ERR": str_err,
            }
        tc_total = report["tests"]["total"]
        tc_failed = report["tests"]["fails"]
        if tc_failed > 0:
            return False, {
                "error": f"Test failed: {tc_failed}/{tc_total} test cases failed. Need all test cases to pass.",
                "STD_OUT": str_out,
                "STD_ERR": str_err,
            }
        ret, msg = fc.check_has_assert_in_tc(self.workspace, report)
        if not ret:
            return ret, msg
        return True, {"message": f"{self.__class__.__name__} check passed."}
