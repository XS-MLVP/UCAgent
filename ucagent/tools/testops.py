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
import re
import shlex


def _pytest_target_path(target: str) -> tuple[str, str]:
    """Split a pytest target into its filesystem path and node suffix."""

    text = str(target)
    if "::" not in text:
        return text, ""
    path, node = text.split("::", 1)
    return path, "::" + node


def _pytest_target_directory_errors(
    targets: list[str], work_dir: str
) -> list[dict]:
    """Diagnose redundant directory prefixes without rewriting test identity."""

    errors = []
    work_dir = os.path.abspath(work_dir)
    for target in targets:
        if not target or target.startswith("-"):
            continue
        path_part, node_suffix = _pytest_target_path(target)
        if not path_part.endswith((".py", ".pyc")) and not os.path.isabs(path_part):
            continue
        direct_candidate = os.path.abspath(os.path.join(work_dir, path_part))
        if not os.path.isabs(path_part) and os.path.isfile(direct_candidate):
            continue
        candidates = []
        if os.path.isabs(path_part):
            candidates.append(os.path.abspath(path_part))
        else:
            ancestor = os.path.dirname(work_dir)
            while ancestor and ancestor != os.path.dirname(ancestor):
                candidates.append(os.path.abspath(os.path.join(ancestor, path_part)))
                ancestor = os.path.dirname(ancestor)
        resolved = next((candidate for candidate in candidates if os.path.isfile(candidate)), None)
        if resolved is None:
            continue
        try:
            relative = os.path.relpath(resolved, work_dir)
        except ValueError:
            continue
        if relative == "." or relative.startswith("../"):
            continue
        correct_target = relative + node_suffix
        if correct_target != target:
            errors.append(
                {
                    "error_code": "PYTEST_TARGET_DIRECTORY_PREFIX",
                    "provided_target": target,
                    "pytest_working_directory": work_dir,
                    "correct_target": correct_target,
                    "message": (
                        "RunTestCases target paths are relative to pytest_working_directory. "
                        "Remove the duplicated configured test-directory prefix and retry "
                        "with correct_target exactly. This diagnostic does not make the two "
                        "node-ID strings equivalent."
                    ),
                }
            )
    return errors


def _classify_pytest_execution(
    returncode: int | None,
    stdout: str,
    stderr: str,
    *,
    report_exists: bool = False,
    report_has_tests: bool = False,
) -> dict:
    """Classify pytest process state without hiding its original output."""

    output = "\n".join(part for part in (stdout, stderr) if part)
    lowered = output.lower()
    if "timed out" in lowered:
        code = "PYTEST_TIMEOUT"
        success = False
    elif "file or directory not found" in lowered:
        code = "PYTEST_TARGET_NOT_FOUND"
        success = False
    elif re.search(
        r"error collecting|errors during collection|error during collection|"
        r"importerror while importing test module|internalerror|syntaxerror|"
        r"indentationerror|taberror",
        lowered,
    ):
        code = "PYTEST_COLLECTION_ERROR"
        success = False
    elif re.search(r"collected\s+0\s+items?|no tests ran", lowered):
        code = "PYTEST_NO_TESTS_COLLECTED"
        success = False
    elif returncode == 0 and report_exists and not report_has_tests:
        code = "PYTEST_NO_TESTS_COLLECTED"
        success = False
    elif returncode == 0:
        code = "OK"
        success = True
    elif returncode == 1:
        # A normal assertion failure is distinguishable from invocation failure;
        # RunUnityChipTest marks it usable only when a non-empty Toffee report is
        # available.  The report remains authoritative for DUT-vs-test analysis.
        code = "PYTEST_ASSERTION_FAILURE"
        success = report_exists and report_has_tests
    elif returncode in (2, 3, 4, 5):
        code = {
            2: "PYTEST_INTERRUPTED",
            3: "PYTEST_INTERNAL_ERROR",
            4: "PYTEST_USAGE_ERROR",
            5: "PYTEST_NO_TESTS_COLLECTED",
        }[returncode]
        success = False
    else:
        code = "PYTEST_PROCESS_ERROR"
        success = False
    return {
        "pytest_returncode": returncode,
        "invocation_success": success,
        "diagnostic_code": code,
        "report_exists": report_exists,
        "report_has_tests": report_has_tests,
    }


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
    last_execution: dict = Field(
        default_factory=dict,
        description="Structured state from the most recent pytest invocation.",
    )
    _last_process_stdout: str = ""
    _last_process_stderr: str = ""

    def do(self,
             test_dir_or_file: str,
             pytest_ex_args: str = "",
             return_stdout: bool = False,
             return_stderr: bool = False,
             timeout: int = 15,
             pytest_ex_env: dict = {},
             run_manager: CallbackManagerForToolRun = None, python_paths: list = None) -> Tuple[int, str, str]:
        """Run the Python tests."""
        if not os.path.exists(test_dir_or_file):
            diagnostic = {
                "error_code": "PYTEST_TARGET_NOT_FOUND",
                "provided_test_directory_or_file": test_dir_or_file,
                "resolved_path": os.path.abspath(test_dir_or_file),
                "message": "The configured pytest directory or file does not exist.",
            }
            self.last_execution = {
                "pytest_returncode": None,
                "invocation_success": False,
                "diagnostic_code": diagnostic["error_code"],
                "report_exists": False,
                "report_has_tests": False,
                "target_error": diagnostic,
            }
            self._last_process_stdout = ""
            self._last_process_stderr = json.dumps(diagnostic, indent=2)
            return False, "", self._last_process_stderr if return_stderr else ""
        ret_stdout, ret_stderr = "", ""
        invocation_stdout, invocation_stderr = "", ""
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
        env.update(pytest_ex_env)
        # Determine the correct working directory and test target
        abs_test_path = os.path.abspath(test_dir_or_file)
        if os.path.isdir(abs_test_path):
            # If it's a directory, set cwd to the directory itself and use relative path
            work_dir = abs_test_path
            if not pytest_ex_args:
                test_target = ["."]
            elif isinstance(pytest_ex_args, str):
                test_target = shlex.split(pytest_ex_args)
            elif isinstance(pytest_ex_args, list):
                test_target = pytest_ex_args
            else:
                raise ValueError(f"pytest_ex_args ({pytest_ex_args}) must be a string or a list.")
        else:
            # If it's a file, set cwd to the directory containing the file
            work_dir = os.path.dirname(abs_test_path)
            file_basename = os.path.basename(abs_test_path)
            test_target = [file_basename]
            # Handle pytest_ex_args that may contain absolute paths
            if pytest_ex_args:
                if isinstance(pytest_ex_args, str):
                    test_target.extend(shlex.split(pytest_ex_args))
                elif isinstance(pytest_ex_args, list):
                    test_target.extend(pytest_ex_args)
                else:
                    raise ValueError(f"pytest_ex_args ({pytest_ex_args}) must be a string or a list.")

        target_errors = _pytest_target_directory_errors(test_target, work_dir)
        if target_errors:
            diagnostic = target_errors[0]
            self.last_execution = {
                "pytest_returncode": None,
                "invocation_success": False,
                "diagnostic_code": diagnostic["error_code"],
                "report_exists": False,
                "report_has_tests": False,
                "working_directory": work_dir,
                "command_targets": test_target,
                "target_error": diagnostic,
            }
            self._last_process_stdout = ""
            self._last_process_stderr = json.dumps(diagnostic, indent=2)
            return (
                False,
                "",
                self._last_process_stderr if return_stderr else "",
            )
        ENV_ARGS = shlex.split(env.get("UCA_PYTEST_ARGS", "").replace(";", " ").strip())
        cmd = ["pytest", *ENV_ARGS, "-s", *self.get_pytest_args(), *test_target]
        info(f"Run command: PYTHONPATH={env['PYTHONPATH']} {' '.join(cmd)} (in {work_dir})\n")
        try:
            worker = subprocess.Popen(
                cmd,
                # Capture both streams internally so execution diagnostics can
                # distinguish assertion failures from collection/usage errors.
                # The public return values still honor return_stdout/return_stderr.
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                bufsize=10,
                cwd=work_dir
            )
            self.pre_call(worker)
            invocation_stdout, invocation_stderr = worker.communicate(timeout=timeout)
            self._last_process_stdout = invocation_stdout
            self._last_process_stderr = invocation_stderr
            self.last_execution = _classify_pytest_execution(
                worker.returncode, invocation_stdout, invocation_stderr
            )
            self.last_execution["working_directory"] = work_dir
            self.last_execution["command_targets"] = test_target
            ret_stdout = invocation_stdout if return_stdout else ""
            ret_stderr = invocation_stderr if return_stderr else ""
            return worker.returncode == 0, ret_stdout, ret_stderr
        except subprocess.TimeoutExpired as e:
            try:
                worker.terminate()
                _, alive = psutil.wait_procs([worker], timeout=3)
                if alive:
                    worker.kill()
            except Exception as ex:
                warning(f"Error terminating process: {ex}")
            invocation_stdout, invocation_stderr = worker.communicate()
            timeout_message = (
                f"\nTest run timed out after {e.timeout} seconds. "
                "You may try increasing the timeout argument."
            )
            invocation_stderr += timeout_message
            self._last_process_stdout = invocation_stdout
            self._last_process_stderr = invocation_stderr
            self.last_execution = _classify_pytest_execution(
                worker.returncode, invocation_stdout, invocation_stderr
            )
            self.last_execution["diagnostic_code"] = "PYTEST_TIMEOUT"
            ret_stdout = invocation_stdout if return_stdout else ""
            ret_stderr = invocation_stderr if return_stderr else ""
            return False, ret_stdout, ret_stderr
        except subprocess.CalledProcessError as e:
            invocation_stdout = (e.stdout or "") if isinstance(e.stdout, str) else ""
            invocation_stderr = (e.stderr or "") if isinstance(e.stderr, str) else ""
            invocation_stderr += f"\nCalledProcessError: {e}"
            self._last_process_stdout = invocation_stdout
            self._last_process_stderr = invocation_stderr
            self.last_execution = _classify_pytest_execution(
                getattr(e, "returncode", None), invocation_stdout, invocation_stderr
            )
            return False, invocation_stdout if return_stdout else "", invocation_stderr if return_stderr else ""
        except Exception as e:
            invocation_stderr = f"Exception: {e}"
            self._last_process_stdout = ""
            self._last_process_stderr = invocation_stderr
            self.last_execution = _classify_pytest_execution(
                None, "", invocation_stderr
            )
            self.last_execution["diagnostic_code"] = "PYTEST_INVOCATION_ERROR"
            return False, "Test Fail" if return_stdout else "", invocation_stderr if return_stderr else ""

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
            pytest_ex_args=pytest_ex_args,
            return_stdout=return_stdout,
            return_stderr=return_stderr,
            timeout=timeout,
            run_manager=run_manager,
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
             pytest_ex_env:dict = {},
             run_manager: CallbackManagerForToolRun = None, return_all_checks=False,
             **kw) -> dict:
        """Run the Unity chip tests."""
        return_test_details = kw.get("return_test_details", False)
        shutil.rmtree(self.result_dir, ignore_errors=True)
        all_pass, pyt_out, pyt_err = RunPyTest.do(self,
                                          os.path.join(self.workspace, test_dir_or_file),
                                          pytest_ex_args,
                                          return_stdout,
                                          return_stderr,
                                          timeout,
                                          pytest_ex_env,
                                          run_manager,
                                          python_paths = [self.workspace, os.path.join(self.workspace, test_dir_or_file)])
        result_json_path = os.path.join(self.result_dir, self.result_json_path)
        report_exists = os.path.exists(result_json_path)
        report_error_code = None
        ret_data = {
            "run_test_success": False,
        }
        if report_exists:
            try:
                ret_data = load_toffee_report(
                    result_json_path,
                    self.workspace,
                    all_pass,
                    return_all_checks,
                    return_test_details=return_test_details,
                )
            except (OSError, ValueError, RuntimeError, TypeError) as error:
                ret_data = {
                    "run_test_success": False,
                    "execution_error": {
                        "diagnostic_code": "TOFFEE_REPORT_INVALID",
                        "message": str(error),
                        "report_path": result_json_path,
                    },
                }
                report_error_code = "TOFFEE_REPORT_INVALID"
        report_has_tests = bool(
            isinstance(ret_data.get("tests"), dict)
            and ret_data["tests"].get("total", 0) > 0
        )
        execution = _classify_pytest_execution(
            self.last_execution.get("pytest_returncode"),
            self._last_process_stdout,
            self._last_process_stderr,
            report_exists=report_exists and report_error_code is None,
            report_has_tests=report_has_tests,
        )
        if (
            self.last_execution.get("pytest_returncode") is None
            and self.last_execution.get("diagnostic_code")
        ):
            execution.update(self.last_execution)
        execution.update(
            {
                key: value
                for key, value in self.last_execution.items()
                if key not in execution
            }
        )
        if report_error_code is not None:
            execution["pytest_diagnostic_code"] = execution["diagnostic_code"]
            execution["invocation_success"] = False
            execution["diagnostic_code"] = report_error_code
            execution["report_exists"] = report_exists
        elif (
            not report_exists
            and execution["diagnostic_code"]
            in {"OK", "PYTEST_ASSERTION_FAILURE"}
        ):
            execution["pytest_diagnostic_code"] = execution["diagnostic_code"]
            execution["invocation_success"] = False
            execution["diagnostic_code"] = "TOFFEE_REPORT_MISSING"
        ret_data["run_test_success"] = execution["invocation_success"]
        ret_data["execution"] = execution
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
            pytest_ex_args=pytest_ex_args,
            return_stdout=return_stdout,
            return_stderr=return_stderr,
            timeout=timeout,
            run_manager=run_manager,
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
