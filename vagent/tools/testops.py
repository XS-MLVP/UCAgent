#coding=utf-8

from langchain_core.callbacks import (
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field


from vagent.util.functions import load_json_file, rm_workspace_prefix
from vagent.util.functions import get_toffee_json_test_case
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
    return_stdout: bool = Field(
        default=False,
        description="Whether to return the standard output of the test run."
    )
    return_stderr: bool = Field(
        default=False,
        description="Whether to return the standard error of the test run."
    )


class RunPyTest(BaseTool):
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
             return_stdout: bool = False,
             return_stderr: bool = False,
             run_manager: CallbackManagerForToolRun = None) -> Tuple[int, str, str]:
        """Run the Python tests."""
        assert os.path.exists(test_dir_or_file), \
            f"Test directory or file does not exist: {test_dir_or_file}"
        ret_stdout, ret_stderr = None, None
        try:
            result = subprocess.run(
                ["pytest", os.path.abspath(test_dir_or_file), *self.get_pytest_args()],
                capture_output=True,
                text=True,
                check=True
            )
            if return_stdout:
                ret_stdout = result.stdout
            if return_stderr:
                ret_stderr = result.stderr
            return True, ret_stdout, ret_stderr
        except subprocess.CalledProcessError as e:
            if return_stdout:
                ret_stdout = e.stdout
            if return_stderr:
                ret_stderr = e.stderr
            return False, ret_stdout, ret_stderr
        except Exception as e:
            if return_stderr:
                ret_stderr = str(e)
            return False, "Test Fail", return_stderr

    def _run(self,
             test_dir_or_file: str,
             return_stdout: bool = False,
             return_stderr: bool = False,
             run_manager: CallbackManagerForToolRun = None) -> str:
        """Run the Python tests and return the output."""
        all_pass, pyt_out, pyt_err = self.do(
            test_dir_or_file,
            return_stdout,
            return_stderr,
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
             return_stdout: bool = False,
             return_stderr: bool = False,
             run_manager: CallbackManagerForToolRun = None) -> dict:
        """Run the Unity chip tests."""
        shutil.rmtree(self.result_dir, ignore_errors=True)
        all_pass, pyt_out, pyt_err = RunPyTest.do(self,
                                          os.path.join(self.workspace, test_dir_or_file),
                                          return_stdout,
                                          return_stderr,
                                          run_manager)
        ret_data = {
            "all_test_pass": all_pass,
        }
        result_json_path = os.path.join(self.result_dir, self.result_json_path)
        if os.path.exists(result_json_path):
            data = load_json_file(result_json_path)
            # Extract relevant information from the JSON data
            # test
            tests = get_toffee_json_test_case(self.workspace, data.get("test_abstract_info", {}))
            fails =  [k[0] for k in tests if k[1] == "FAILED"]
            ret_data["tests"] = {
                "total": len(tests),
                "fails": len(fails),
            }
            if len(fails) > 0:
                ret_data["tests"]["fails_list"] = fails,
            # coverages
            # functional coverage
            fc_data = data.get("coverages", {}).get("functional", {})
            ret_data["total_funct_point"] = fc_data.get("point_num_total", 0)
            ret_data["total_check_point"] = fc_data.get("bin_num_total",   0)
            ret_data["faild_funct_point"] = ret_data["total_funct_point"] - fc_data.get("point_num_hints", 0)
            ret_data["faild_check_point"] = ret_data["total_check_point"] - fc_data.get("bin_num_hints",   0)
            # failed bins:
            # groups->points->bins
            bins_fail = []
            bins_uncovered = []
            bins_funcs = {}
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
                            bins_uncovered.append(bin_full_name)
                        else:
                            for tf in test_funcs:
                                func_key = rm_workspace_prefix(self.workspace, tf)
                                if func_key not in bins_funcs:
                                    bins_funcs[func_key] = []
                                bins_funcs[func_key].append(bin_full_name)
            if len(bins_fail) > 0:
                ret_data["faild_check_point_list"] = bins_fail
            ret_data["uncovered_check_points"] = len(bins_uncovered)
            if len(bins_uncovered) > 0:
                ret_data["uncovered_check_points_list"] = bins_uncovered
            # functions with no check points
            test_fc_no_check_points = []
            for f, _ in tests:
                if f not in bins_funcs:
                    test_fc_no_check_points.append(f)
            ret_data["test_function_with_no_check_point"] = len(test_fc_no_check_points)
            if len(test_fc_no_check_points) > 0:
                ret_data["test_function_with_no_check_point_list"] = test_fc_no_check_points
            # FIXME: more data
        return ret_data, pyt_out, pyt_err

    def _run(self,
             test_dir_or_file: str,
             return_stdout: bool = False,
             return_stderr: bool = False,
             run_manager: CallbackManagerForToolRun = None) -> str:
        """Run the Unity chip tests and return the output."""
        data, pyt_out, pyt_err = self.do(
            test_dir_or_file,
            return_stdout,
            return_stderr,
            run_manager
        )
        ret_str = "[Test Report]:\n" + json.dumps(data, indent=2) + "\n"
        if return_stdout:
            ret_str += f"[Stdout]:\n{pyt_out}\n"
        if return_stderr:
            ret_str += f"[Stderr]:\n{pyt_err}\n"
        return ret_str

    def __init__(self, workspace:str, report_dir: str = "uc_test_report", **kwargs):
        """Initialize the tool with custom arguments."""
        super().__init__(**kwargs)
        self.workspace = os.path.abspath(workspace)
        self.result_dir = os.path.join(self.workspace, report_dir)
        self.set_pytest_args({
            "toffee-report": True,
            "report-dump-json": True,
            "report-name": "index.html",
            "report-dir": self.result_dir
        })
