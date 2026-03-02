#coding=utf-8


import ucagent.util.functions as fc
from ucagent.checkers.unity_test import BaseUnityChipCheckerTestCase
from typing import Tuple
import inspect
from ucagent.checkers.toffee_report import check_report


class RandomTestCasesChecker(BaseUnityChipCheckerTestCase):
    """
    Check random test cases in Unity test files.

    This checker verifies the presence and correctness of random test cases
    in Unity test files. It performs the following checks:
    1. Ensures test files match the pattern 'test_{DUT}_random*.py'.
    2. Ensures test functions match the pattern 'test_random_<name>'.
    3. Checks that the first argument of test functions is 'env'.
    4. Verifies the use of 'ucagent.repeat_count' for setting repeat counts.
    5. Verifies the use of '.mark_function' for marking function coverage and check points.
    6. Runs the random test cases and checks the test report.

    Attributes:
        target_test_file (str): Pattern to match target test files.
        mini_file_count (int): Minimum number of test files required.
        min_test_count (int): Minimum number of test cases required.
        test_case_name_pattern (str): Pattern to match test case function names.
        must_func_code_snippet (dict): Required code snippets in test functions.
    """

    def __init__(self, target_test_file, mini_file_count=1, min_test_count=1,
                 test_case_name_pattern="test_random_*",
                 must_func_code_snippet={"ucagent.repeat_count": "you must use this function to set the repeat count for random test cases.",
                                         ".mark_function": "you must use this function to mark the function coverage and check points."
                                         },
                 **kw):
        kw["min_tests"] = min_test_count
        super().__init__(**kw)
        self.target_test_file = target_test_file
        self.mini_file_count = mini_file_count
        self.min_test_count = min_test_count
        self.test_case_name_pattern = test_case_name_pattern
        self.must_func_code_snippet = must_func_code_snippet

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Check random test cases"""
        test_files = fc.find_files_by_pattern(self.workspace, self.target_test_file)
        if len(test_files) < self.mini_file_count:
            return False, f"Random test cases check fail: found {len(test_files)} test files, " \
                          f"expected at least {self.mini_file_count} files with pattern: {self.target_test_file}."
        total_test_count = 0
        for tfile in test_files:
            if self.check_script_env:
                # When check_script_env is set, run inspection in a subprocess
                # with LD_PRELOAD so the DUT .so is loaded before Python starts.
                # This prevents Adder/__init__.py from calling os.execve() in the
                # parent UCAgent process (which would restart it and trigger the
                # git LD_PRELOAD symbol-lookup error).
                ret, func_infos = self._inspect_funcs_subprocess(self.get_path(tfile))
                if not ret:
                    return False, func_infos  # func_infos is the error dict here
            else:
                # Original direct-import path (no DUT .so involved)
                raw_list = fc.get_target_from_file(self.get_path(tfile), self.test_case_name_pattern,
                                                   ex_python_path=self.workspace,
                                                   dtype="FUNC")
                func_infos = [
                    (f.__name__,
                     fc.get_func_arg_list(f),
                     inspect.getsource(f))
                    for f in raw_list
                ]
            total_test_count += len(func_infos)
            for func_name, args, func_source in func_infos:
                if len(args) < 1 or args[0] != "env":
                    return False, {"error": f"The '{tfile + ':' + func_name}' Env test function's first arg must be 'env', but got ({', '.join(args)})."}
                for mc, v in self.must_func_code_snippet.items():
                    if mc not in func_source:
                        return False, {"error": f"The '{tfile + ':' + func_name}' Env test function must contain "
                                                f"'{mc}', {v}"}
        if total_test_count < self.min_test_count:
            return False, f"Random test cases check fail: found {total_test_count} test cases, " \
                          f"expected at least {self.min_test_count} cases."
        # Run test cases
        pytest_args = " ".join([str(f).split("/")[-1] for f in test_files])
        report, str_out, str_err = super().do_check(pytest_args=pytest_args, timeout=timeout, **kw)
        test_pass, test_msg = fc.is_run_report_pass(report, str_out, str_err)
        if not test_pass:
            return False, test_msg
        report_copy = fc.clean_report_with_keys(report)
        def get_emsg(m):
            msg =  {"error": m, "REPORT": report_copy}
            if self.ret_std_out:
                msg["STDOUT"] = str_out
            if self.ret_std_error:
                msg["STDERR"] = str_err
            if "Signal bind error" in str_err:
                msg["WARNING"] = "The DUT signals are not handled properly by toffee Bundle, you should fix this issue first."
            return msg
        ret, msg, _ = check_report(self.workspace,
                                   report, self.doc_func_check, self.doc_bug_analysis,
                                   only_marked_ckp_in_tc=True,
                                   check_fail_ck_in_bug=False,
                                   func_RunTestCases=self.stage_manager.tool_run_test_cases, timeout_RunTestCases=timeout
                                   )
        if not ret:
            return ret, get_emsg(msg)
        ret, msg = fc.check_has_assert_in_tc(self.workspace, report)
        if not ret:
            return ret, get_emsg(msg["error"])
        return True, f"Random test cases({total_test_count}) check Pass"

    def _inspect_funcs_subprocess(self, target_file: str):
        """
        Run function inspection inside a fresh subprocess that has LD_PRELOAD
        set before Python starts (via _run_subprocess_check), so DUT .so files
        load correctly without triggering os.execve() in the parent process.

        Returns:
            (True,  list of (name, args, source))   on success
            (False, {"error": ...})                  on failure
        """
        success, result = self._run_subprocess_check(
            "run_check_random_funcs.py",
            target_file,
            self.workspace,
            self.test_case_name_pattern,
        )
        if not success:
            return False, {"error": result.get("error", str(result))}
        func_infos = [
            (f["name"], f["args"], f["source"])
            for f in result.get("functions", [])
        ]
        return True, func_infos
