# -*- coding: utf-8 -*-
"""The shared ``RunTestCases`` stage manager tool for pytest-based workflows.

The framework resolves declared manager tools by name; this module owns the
pytest-flavored one: it reads ``tools.RunTestCases.*`` from the resolved
config, drives the workflow's declared free-runner Checker, and publishes the
stage-scoped test report.
"""

import traceback
from typing import Any, Optional

from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field

from ucagent.core.stage.vmanager import ManagerTool
from ucagent.util.functions import import_class_from_str, make_llm_tool_ret
from ucagent.util.log import info

import ucagent.core.checkers


class ArgRunTestCases(BaseModel):
    target: str = Field(
        default="",
        description=(
            "Target test cases to run, supports pytest-style arguments for precise test selection. "
            "Examples:\n"
            "• '' (empty): Run all test cases in the test directory\n"
            "• 'test_file.py': Run all tests in a specific file\n"
            "• 'test_file.py::test_function': Run a specific test function\n"
            "• 'test_file.py::TestClass::test_method': Run a specific test method in a class\n"
            "• '-k pattern': Run tests matching the given pattern\n"
            "• '-m marker': Run tests with specific markers\n"
        )
    )
    timeout: int = Field(
        default=0,
        description="Timeout for the test run in seconds. Zero means use default cfg.call_time_out."
    )
    return_line_coverage: bool = Field(
        default=False,
        description="Whether to return line coverage information in the test results."
    )


def resolve_free_runner_clss(clss, checker_registry=None):
    """Resolve the free pytest runner checker declared by the workflow.

    Uses the same resolution as stage ``clss`` entries: a short name found in
    the (plugin) checker registry wins; anything else is imported through
    ``ucagent.core.checkers`` (fully-qualified class paths included).
    """
    registry = dict(checker_registry or {})
    if "." not in clss and clss in registry:
        return registry[clss]
    try:
        return import_class_from_str(clss, ucagent.core.checkers)
    except (AttributeError, ImportError) as e:
        raise ValueError(
            "Cannot resolve tools.RunTestCases.free_runner_clss "
            f"'{clss}' via the checker registry or ucagent.core.checkers: {e}"
        )


class RunTestCasesManagerTool(ManagerTool):
    """Run the workflow's declared pytest free-runner through the stage surface."""
    name: str = "RunTestCases"
    description: str = (
        "Run real pytest verification tests in the workspace and return their test and "
        "coverage report. Use this only for pytest test targets after implementing or "
        "modifying verification tests. It is not a Python script runner: never create or "
        "run a temporary pytest test, maintenance script, or document-migration script to "
        "edit workspace artifacts. Use the available file-editing tools for document and "
        "source changes, and RunSkillScript only for an existing declared skill script. "
        "The current pytest directory is '{TEST_DIR}'; every target path is relative to "
        "that directory. Do not repeat '{TEST_DIR}' in target. For example, a test below "
        "that directory is addressed as 'test_file.py::test_name'. This target syntax is "
        "different from workspace-relative TC tags and waveform node IDs. If the tool "
        "returns PYTEST_TARGET_DIRECTORY_PREFIX, retry with correct_target exactly."
    )
    args_schema: Optional[ArgsSchema] = ArgRunTestCases
    # Bound state: ``bind`` fills these from the declaring stage manager.
    manager: Any = None
    free_pytest_run: Any = None
    test_dir: Optional[str] = None

    def bind(self, manager):
        """Resolve the declared free runner and render the tool description."""
        self.manager = manager
        try:
            test_dir = manager.cfg.get_value("tools.RunTestCases.test_dir", None)
        except AttributeError:
            test_dir = None
        try:
            free_runner_clss = manager.cfg.get_value(
                "tools.RunTestCases.free_runner_clss", None
            )
        except AttributeError:
            free_runner_clss = None
        missing = [
            key
            for key, value in (
                ("tools.RunTestCases.test_dir", test_dir),
                ("tools.RunTestCases.free_runner_clss", free_runner_clss),
            )
            if not (isinstance(value, str) and value.strip())
        ]
        if missing:
            raise ValueError(
                "RunTestCases is declared in manager_tools but the workflow "
                "declares no " + " or ".join(missing) + "."
            )
        runner_clss = resolve_free_runner_clss(
            free_runner_clss, manager.checker_registry
        )
        self.free_pytest_run = runner_clss(
            "", test_dir, ""
        ).set_workspace(manager.workspace)
        self.free_pytest_run.run_test.set_extra_python_paths(
            manager.test_python_import_roots
        )
        self.test_dir = self.free_pytest_run.test_dir
        self.set_function(self.run_test_cases)
        self.render_desc({"TEST_DIR": self.test_dir})
        return self

    def _run(self, target="", timeout=0, return_line_coverage=False,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        try:
            if timeout <= 0:
                timeout = self.get_call_time_out()
            return self.function(target, timeout, return_line_coverage)
        except Exception as e:
            traceback.print_exc()
            error_msg = f"Test execution failed: {str(e)}"
            info(error_msg)
            return error_msg

    def run_test_cases(self, pytest_args="", timeout=0, return_line_coverage=False, raw_return=False, detail=False):
        """Run the declared free pytest runner for the active stage."""
        stage = self.manager.get_current_stage()
        self.free_pytest_run.run_test.set_report_context({
            "source": "RunTestCases",
            "stage_index": self.manager.stage_index,
            "stage_name": stage.name if stage is not None else None,
        })
        ret = self.free_pytest_run.do_check(pytest_args, timeout=timeout, return_line_coverage=return_line_coverage, detail=detail)
        if raw_return:
            return ret
        ret = make_llm_tool_ret(ret[1])
        info("RunTestCases:\n" + ret)
        return self.manager.attach_todo_summary(ret)
