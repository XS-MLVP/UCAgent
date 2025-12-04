# -*- coding: utf-8 -*-
"""Test operations tools for UCAgent."""

from langchain_core.callbacks import (
    CallbackManagerForToolRun,
)
from .uctool import UCTool
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field


from ucagent.util.test_tools import ucagent_lib_path
from ucagent.util.functions import get_toffee_json_test_case, load_toffee_report
from ucagent.util.log import debug, info, warning
import os
import shutil
import psutil
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
        default=15,
        description="Timeout for the test run in seconds. Default is 15 seconds."
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
             timeout: int = 15,
             run_manager: CallbackManagerForToolRun = None, python_paths: list = None) -> Tuple[int, str, str]:
        """Run the Python tests."""
        assert os.path.exists(test_dir_or_file), \
            f"Test directory or file does not exist: {test_dir_or_file}"
        ret_stdout, ret_stderr = "", ""
        env = os.environ.copy()
        pythonpath = env.get("PYTHONPATH", "")
        python_path_str = os.path.abspath(os.getcwd()) + ":" + ucagent_lib_path()
        if python_paths is not None:
            for p in python_paths:
                if os.path.exists(p):
                    python_path_str += ":" + os.path.abspath(p)
                    debug(f"Add python path: {p}")
        env["PYTHONPATH"] = python_path_str + ((":" + pythonpath) if pythonpath else "")
        if "XSPCOMM_LOG_LEVEL" not in env:
            env["XSPCOMM_LOG_LEVEL"] = "4"  # 1-DEBUG, 2-INFO, 3-WARNING, 4-ERROR, 5-FATAL
        # Determine the correct working directory and test target
        abs_test_path = os.path.abspath(test_dir_or_file)
        if os.path.isdir(abs_test_path):
            # If it's a directory, set cwd to the directory itself and use relative path
            work_dir = abs_test_path
            test_target = ["."] if pytest_ex_args == "" else pytest_ex_args.split()
        else:
            # If it's a file, set cwd to the directory containing the file
            work_dir = os.path.dirname(abs_test_path)
            file_basename = os.path.basename(abs_test_path)
            test_target = [file_basename]
            # Handle pytest_ex_args that may contain absolute paths
            if pytest_ex_args:
                test_target.extend(pytest_ex_args.split())

        cmd = ["pytest", "-s", *self.get_pytest_args(), *test_target]
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
            try:
                worker.terminate()
                _, alive = psutil.wait_procs([worker], timeout=3)
                if alive:
                    worker.kill()
            except Exception as ex:
                warning(f"Error terminating process: {ex}")
            ret_stdout, ret_stderr = worker.communicate()
            return False, ret_stdout, ret_stderr + f"\nTest run timed out after {e.timeout} seconds. You may try increasing the timeout argment."
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
             timeout: int = 15,
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
             timeout: int = 15,
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
        result_json_path = os.path.join(self.result_dir, self.result_json_path)
        ret_data = {
            "run_test_success": all_pass,
        }
        if os.path.exists(result_json_path):
            ret_data = load_toffee_report(result_json_path, self.workspace, all_pass, return_all_checks)
        info(f"Run UnityChip test report:\n{json.dumps(ret_data, indent=2)}\n")
        return ret_data, pyt_out, pyt_err

    def _run(self,
             test_dir_or_file: str,
             pytest_ex_args: str = "",
             return_stdout: bool = False,
             return_stderr: bool = False,
             timeout: int = 15,
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
        self.result_dir = report_dir
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
