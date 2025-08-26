#coding=utf-8

from langchain_core.callbacks import (
    CallbackManagerForToolRun,
)
from .uctool import UCTool
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field


from vagent.util.functions import load_json_file, rm_workspace_prefix
from vagent.util.functions import get_toffee_json_test_case
from vagent.util.log import debug, info
import os
import shutil
from typing import Tuple
import subprocess
import json


class ArgRunPyTest(BaseModel):
    """Arguments for running a Python test."""
    test_dir_or_file: str = Field(
        ...,
        description="The directory or file containing the Python tests to run."
    )
    pytest_ex_args: str = Field(
        default="",
        description="Additional arguments to pass to pytest, e.g., '-v --capture=no'."
    )
    return_stdout: bool = Field(
        default=False,
        description="Whether to return the standard output of the test run."
    )
    return_stderr: bool = Field(
        default=False,
        description="Whether to return the standard error of the test run."
    )
    timeout: int = Field(
        default=600,
        description="Timeout for the test run in seconds. Default is 600 seconds (10 minutes)."
    )


class RunPyTest(UCTool):
    """Tool to run pytest tests in a specified directory or a test file."""

    name: str = "RunPyTest"
    description: str = ("Run pytest tests in a specified directory or a test file."
                        "By default only return if all tests is pass or not.\n"
                        "If arg `return_stdout` is True, it will return the standard output of the test run.\n"
                        "If arg `return_stderr` is True, it will return the standard error of the test run.\n"
                        )
    args_schema: ArgsSchema = ArgRunPyTest
    return_direct: bool = False

    # custom variables
    pytest_args: dict = Field(
        default={},
        description="Additional arguments to pass to pytest, e.g., {'verbose': True, 'capture': 'no'}."
    )

    def do(self,
             test_dir_or_file: str,
             pytest_ex_args: str = "",
             return_stdout: bool = False,
             return_stderr: bool = False,
             timeout: int = 600,
             run_manager: CallbackManagerForToolRun = None, python_paths: list = None) -> Tuple[int, str, str]:
        """Run the Python tests."""
        assert os.path.exists(test_dir_or_file), \
            f"Test directory or file does not exist: {test_dir_or_file}"
        ret_stdout, ret_stderr = "", ""
        env = os.environ.copy()
        pythonpath = env.get("PYTHONPATH", "")
        python_path_str = os.path.abspath(os.getcwd())
        if python_paths is not None:
            for p in python_paths:
                if os.path.exists(p):
                    python_path_str += ":" + os.path.abspath(p)
                    debug(f"Add python path: {p}")
        env["PYTHONPATH"] = python_path_str + (":" + pythonpath if pythonpath else "")
        # Determine the correct working directory and test target
        abs_test_path = os.path.abspath(test_dir_or_file)
        if os.path.isdir(abs_test_path):
            # If it's a directory, set cwd to the directory itself and use relative path
            work_dir = abs_test_path
            test_target = "." if pytest_ex_args == "" else pytest_ex_args
        else:
            # If it's a file, set cwd to the directory containing the file
            work_dir = os.path.dirname(abs_test_path)
            test_target = os.path.basename(abs_test_path) + " " + pytest_ex_args

        cmd = ["pytest", "-s", *self.get_pytest_args(), test_target]
        info(f"Run command: PYTHONPATH={env['PYTHONPATH']} {' '.join(cmd)} (in {work_dir})\n")
        try:
            worker = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE if return_stdout else None,
                stderr=subprocess.PIPE if return_stderr else None,
                text=True,
                env=env,
                bufsize=10,
                cwd=work_dir
            )
            self.pre_call(worker)
            ret_stdout, ret_stderr = worker.communicate(timeout=timeout)  # Set a timeout for the test run
            if not return_stdout:
                ret_stdout = ""
            if not return_stderr:
                ret_stderr = ""
            return True, ret_stdout, ret_stderr
        except subprocess.TimeoutExpired as e:
            return False, ret_stdout, ret_stderr + f"\nTest run timed out after {e.timeout} seconds."
        except subprocess.CalledProcessError as e:
            if return_stdout:
                ret_stdout += e.stdout
            if return_stderr:
                ret_stderr += e.stderr
            return False, ret_stdout, ret_stderr + f"\nCalledProcessError: {e}"
        except Exception as e:
            return False, "Test Fail", ret_stderr + f"\Exception: {e}"

    def _run(self,
             test_dir_or_file: str,
             pytest_ex_args: str = "",
             return_stdout: bool = False,
             return_stderr: bool = False,
             timeout: int = 600,
             run_manager: CallbackManagerForToolRun = None) -> str:
        """Run the Python tests and return the output."""
        all_pass, pyt_out, pyt_err = self.do(
            test_dir_or_file,
            pytest_ex_args,
            return_stdout,
            return_stderr,
            timeout,
            run_manager
        )
        ret_str = "Test Pass" if all_pass else "Test Fail\n"
        if return_stdout:
            ret_str += f"Stdout:\n{pyt_out}\n"
        if return_stderr:
            ret_str += f"Stderr:\n{pyt_err}\n"
        return ret_str

    def get_pytest_args(self) -> list:
        """Get additional arguments for pytest."""
        args = []
        for key, value in self.pytest_args.items():
            if isinstance(value, bool):
                if value:
                    args.append(f"--{key}")
            else:
                args.append(f"--{key}={value}")
        return args

    def set_pytest_args(self, py_args):
        """Set additional arguments for pytest."""
        self.pytest_args.update(py_args)
        return self


class RunUnityChipTest(RunPyTest):
    """Tool to run tests in a specified directory or a test file."""

    name: str = "RunUnityChipTest"
    description: str = ("Run tests in a specified directory or a test file. "
                        "This tool is specifically designed for UnityChip tests.\n"
                        "Afert running the tests, it will return:\n"
                        "- The stdout/stderr output of the test run (default off).\n"
                        "- a json test report, include how many tests passed/failed, an overview of the functional coverage/un-coverage data.\n"
                        "If arg `return_stdout` is True, it will return the standard output of the test run.\n"
                        "If arg `return_stderr` is True, it will return the standard error of the test run.\n"
                        )

    # custom variables
    workspace: str = Field(
        default=".",
        description="The workspace directory where the Unity tests are located."
    )
    result_dir: str = Field(
        default="uc_test_report",
        description="Directory to save the Unity test results."
    )
    result_json_path: str = Field(
        default="toffee_report.json",
        description="Path to save the JSON results of the Unity tests."
    )

    def do(self,
             test_dir_or_file: str,
             pytest_ex_args: str = "",
             return_stdout: bool = False,
             return_stderr: bool = False,
             timeout: int = 600,
             run_manager: CallbackManagerForToolRun = None, return_all_checks=False) -> dict:
        """Run the Unity chip tests."""
        shutil.rmtree(self.result_dir, ignore_errors=True)
        all_pass, pyt_out, pyt_err = RunPyTest.do(self,
                                          os.path.join(self.workspace, test_dir_or_file),
                                          pytest_ex_args,
                                          return_stdout,
                                          return_stderr,
                                          timeout,
                                          run_manager,
                                          python_paths = [self.workspace, os.path.join(self.workspace, test_dir_or_file)])
        ret_data = {
            "run_test_success": all_pass,
        }
        result_json_path = os.path.join(self.result_dir, self.result_json_path)
        if os.path.exists(result_json_path):
            data = load_json_file(result_json_path)
            # Extract relevant information from the JSON data
            # test
            tests = get_toffee_json_test_case(self.workspace, data.get("test_abstract_info", {}))
            tests_map = {k[0]: k[1] for k in tests}
            fails =  [k[0] for k in tests if k[1] == "FAILED"]
            ret_data["tests"] = {
                "total": len(tests),
                "fails": len(fails),
            }
            ret_data["tests"]["test_cases"] = tests_map
            # coverages
            # functional coverage
            fc_data = data.get("coverages", {}).get("functional", {})
            ret_data["total_funct_point"] = fc_data.get("point_num_total", 0)
            ret_data["total_check_point"] = fc_data.get("bin_num_total",   0)
            ret_data["failed_funct_point"] = ret_data["total_funct_point"] - fc_data.get("point_num_hints", 0)
            ret_data["failed_check_point"] = ret_data["total_check_point"] - fc_data.get("bin_num_hints",   0)
            # failed bins:
            # groups->points->bins
            bins_fail = []
            bins_unmarked = []
            bins_funcs = {}
            funcs_bins = {}
            bins_funcs_reverse = {}
            bins_all = []
            for g in fc_data.get("groups", []):
                for p in g.get("points", []):
                    cv_funcs = p.get("functions", {})
                    for b in p.get("bins", []):
                        bin_full_name = "%s/%s/%s" % (g["name"], p["name"], b["name"])
                        bin_is_fail = b["hints"] == 0
                        if bin_is_fail:
                            bins_fail.append(bin_full_name)
                        test_funcs =cv_funcs.get(b["name"], [])
                        if len(test_funcs) < 1:
                            bins_unmarked.append(bin_full_name)
                        else:
                            for tf in test_funcs:
                                func_key = rm_workspace_prefix(self.workspace, tf)
                                if func_key not in bins_funcs:
                                    bins_funcs[func_key] = []
                                if func_key in fails:
                                    if func_key not in funcs_bins:
                                        funcs_bins[func_key] = []
                                    funcs_bins[func_key].append(bin_full_name)
                                bins_funcs[func_key].append(bin_full_name)
                                if bin_full_name not in bins_funcs_reverse:
                                    bins_funcs_reverse[bin_full_name] = []
                                bins_funcs_reverse[bin_full_name].append([
                                    func_key, tests_map.get(func_key, "Unknown")])
                        # all bins
                        bins_all.append(bin_full_name)
            ret_data["failed_funcs_bins"] = funcs_bins
            if return_all_checks:
                ret_data["bins_all"] = bins_all
            if len(bins_fail) > 0:
                ret_data["failed_check_point_list"] = bins_fail
                bins_fail_funcs = {}
                for b in bins_fail:
                    passed_func = [f[0] for f in bins_funcs_reverse.get(b, []) if f[1] == "PASSED"]
                    if passed_func:
                        bins_fail_funcs[b] = passed_func
                ret_data["failed_check_point_passed_funcs"] = bins_fail_funcs
            ret_data["unmarked_check_points"] = len(bins_unmarked)
            if len(bins_unmarked) > 0:
                ret_data["unmarked_check_points_list"] = bins_unmarked
            # functions with no check points
            test_fc_no_check_points = []
            for f, _ in tests:
                if f not in bins_funcs:
                    test_fc_no_check_points.append(f)
            ret_data["test_function_with_no_check_point_mark"] = len(test_fc_no_check_points)
            if len(test_fc_no_check_points) > 0:
                ret_data["test_function_with_no_check_point_mark_list"] = test_fc_no_check_points
            # FIXME: more data
        info(f"Run UnityChip test report:\n{json.dumps(ret_data, indent=2)}\n")
        return ret_data, pyt_out, pyt_err

    def _run(self,
             test_dir_or_file: str,
             pytest_ex_args: str = "",
             return_stdout: bool = False,
             return_stderr: bool = False,
             timeout: int = 600,
             run_manager: CallbackManagerForToolRun = None) -> str:
        """Run the Unity chip tests and return the output."""
        data, pyt_out, pyt_err = self.do(
            test_dir_or_file,
            pytest_ex_args,
            return_stdout,
            return_stderr,
            timeout,
            run_manager
        )
        ret_str = "[Test Report]:\n" + json.dumps(data, indent=2) + "\n"
        if return_stdout:
            ret_str += f"[Stdout]:\n{pyt_out}\n"
        if return_stderr:
            ret_str += f"[Stderr]:\n{pyt_err}\n"
        return ret_str

    def __init__(self, workspace:str=None, report_dir: str = "uc_test_report", **kwargs):
        """Initialize the tool with custom arguments."""
        super().__init__(**kwargs)
        self.set_pytest_args({
            "toffee-report": True,
            "report-dump-json": True,
            "report-name": "index.html",
        })
        if workspace is None:
            return
        self.set_workspace(workspace)

    def set_workspace(self, workspace: str):
        """Set the workspace directory."""
        self.workspace = os.path.abspath(workspace)
        self.result_dir = os.path.join(self.workspace, self.result_dir)
        self.set_pytest_args({
            "report-dir": self.result_dir
        })
        return self
