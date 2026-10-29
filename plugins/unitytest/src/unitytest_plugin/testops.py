# -*- coding: utf-8 -*-
"""UnityChip/toffee test runner tool for the UnityTest plugin.

``RunUnityChipTest`` wraps the framework's generic ``RunPyTest`` tool with
the toffee report contract: it runs the workspace tests, summarizes
``uc_test_report/toffee_report.json``, and publishes the current test
report snapshot consumed by the stage checkers.
"""

import json
import os
import shutil

from langchain_core.callbacks import CallbackManagerForToolRun
from pydantic import Field

from ucagent.tools.testops import RunPyTest, classify_pytest_execution
from ucagent.util.config import save_current_test_report
from ucagent.util.log import info, warning


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
    report_context: dict = Field(
        default_factory=dict,
        description="Identity of the stage or tool invocation publishing the report.",
    )

    def set_report_context(self, context):
        """Set diagnostic identity for the next published test report."""
        self.report_context = dict(context or {})
        return self

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
        # Imported here so this tool module does not import the checkers
        # package at import time; the checkers construct this tool, so a
        # module-level import here closes an import cycle.
        from .checkers.toffee_report import load_toffee_report

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
        execution = classify_pytest_execution(
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
        try:
            save_current_test_report(
                self.workspace,
                ret_data,
                context={
                    **self.report_context,
                    "test_dir_or_file": test_dir_or_file,
                    "pytest_ex_args": pytest_ex_args,
                    "result_path": result_json_path,
                },
            )
        except (OSError, TypeError, ValueError, RuntimeError) as error:
            # A report publication failure must remain visible but must not turn
            # a real pytest result into a different test result.
            warning(f"Failed to publish current test report: {error}")
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
