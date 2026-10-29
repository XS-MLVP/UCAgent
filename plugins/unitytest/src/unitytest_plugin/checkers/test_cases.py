# -*- coding: utf-8 -*-
"""UnityTest test-class family Checkers."""

import copy
import hashlib
import json
import os
import re
import traceback
from collections import OrderedDict
from typing import Tuple

import ucagent.util.functions as fc
from ucagent_common.str_utils import list_str_abbr
from ucagent.util.config import load_current_test_report
from ucagent.util.log import info, warning
from ..testops import RunUnityChipTest
from ucagent.checkers.base import Checker, BatchTask
from .toffee_report import (
    check_line_coverage,
    check_report,
    get_missing_functional_coverage_message,
)
from .descriptions import (
    description_checkpoint_association_missing,
    description_mark_function_doc,
)
from .unity_test import (
    BaseUnityChipCheckerTestCase,
    UnityChipCheckerTestCase,
    _iter_test_function_defs,
    _normalize_checkpoint_prefixes,
    _set_checker_failure,
    _test_function_contract_failure,
    _test_name_has_required_prefix,
)
from ucagent_common.doc_marks import get_doc_marks, merge_file_blocks
from ucagent_common.test_report import check_has_assert_in_tc, is_run_report_pass
from unitytest_plugin.report_utils import clean_report_with_keys, parse_un_coverage_json


# ---------------------------------------------------------------------------
# Checker - all-Pass infrastructure self-test
# ---------------------------------------------------------------------------

class UnityChipCheckerTestMustPass(Checker):
    def __init__(self, target_file, test_dir, test_prefix,
                 first_arg="",
                 last_arg="",
                 min_file_tests=1, timeout=300, **kw):
        super().__init__()
        self.target_file_list = target_file if isinstance(target_file, list) else [target_file]
        self.min_file_tests = max(1, min_file_tests)
        self.run_test = RunUnityChipTest()
        self.test_dir = test_dir
        self.first_arg = first_arg
        self.last_arg = last_arg
        self.timeout = timeout
        self.test_prefix = test_prefix

    def set_workspace(self, workspace: str):
        """
        Set the workspace for the test case checker.

        :param workspace: The workspace directory to be set.
        """
        super().set_workspace(workspace)
        self.run_test.set_workspace(workspace)
        return self

    def do_check(self, timeout, **kw) -> Tuple[bool, object]:
        """Check the ptest test implementation for correctness."""
        test_dir_full_path = self.get_path(self.test_dir)
        if not os.path.exists(test_dir_full_path):
            return False, {"error": f"test directory '{self.test_dir}' does not exist in workspace."}
        test_files = fc.find_files_by_pattern(self.workspace, self.target_file_list)
        if len(test_files) == 0:
            tfiles = ', '.join(self.target_file_list)
            return False, {"error": f"target test files '{tfiles}' does not exist."}
        error_cases = []
        for tfile in test_files:
            if test_dir_full_path not in self.get_path(tfile):
                error_cases.append(f"The test file '{tfile}' is not under the test directory '{self.test_dir}'.")
                continue
            test_func_list, parse_error = _iter_test_function_defs(self.get_path(tfile))
            if parse_error is not None:
                line = getattr(parse_error, "lineno", "?")
                error_cases.append(
                    f"{tfile}:{line}-{line}: unable to inspect test functions: {parse_error}"
                )
                continue
            for test_func in test_func_list:
                location = f"{tfile}:{test_func['line']}-{test_func['line']}"
                if not _test_name_has_required_prefix(
                    test_func["name"], [self.test_prefix]
                ):
                    error_cases.append(
                        f"{location}: The '{test_func['name']}' test function's name "
                        f"must start with '{self.test_prefix}' followed by a nonempty "
                        "descriptive suffix."
                    )
                args = test_func["args"]
                if self.first_arg and (len(args) < 1 or args[0] != self.first_arg):
                    error_cases.append(
                        f"{location}: The '{test_func['name']}' test function's first "
                        f"arg must be '{self.first_arg}', but got ({', '.join(args)})."
                    )
                if self.last_arg and (len(args) < 1 or args[-1] != self.last_arg):
                    error_cases.append(
                        f"{location}: The '{test_func['name']}' test function's last "
                        f"arg must be '{self.last_arg}', but got ({', '.join(args)})."
                    )
            if len(test_func_list) < self.min_file_tests:
                error_cases.append(f"Insufficient testcases: {len(test_func_list)} test functions found, minimum required is {self.min_file_tests} in file '{tfile}'. "+
                                    "Please ensure the file contains enough pytest test definitions.")
        if len(error_cases) > 0:
            retry_tool = "Complete" if kw.get("is_complete", False) else "Check"
            return False, _test_function_contract_failure(
                error_cases, retry_tool=retry_tool
            )
        # run test
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
        test_pass, test_msg = is_run_report_pass(report, str_out, str_err)
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
                "error": (
                    f"[Infrastructure Self-Test Failure] {tc_failed}/{tc_total} test "
                    "case(s) failed. UnityChipCheckerTestMustPass validates mock, fixture, "
                    "or reference-model infrastructure, so every case in this stage must "
                    "pass. Fix the verification infrastructure; do not record these failures "
                    "as DUT Bugs. This all-Pass rule does not apply to correctly implemented "
                    "tests that reproduce real DUT design Bugs in DUT verification stages."
                ),
                "STD_OUT": str_out,
                "STD_ERR": str_err,
            }
        ret, msg = check_has_assert_in_tc(self.workspace, report)
        if not ret:
            return ret, msg
        return True, {"message": f"{self.__class__.__name__} check passed."}


# ---------------------------------------------------------------------------
# Checker - free-form runner tests
# ---------------------------------------------------------------------------

class UnityChipCheckerTestFree(BaseUnityChipCheckerTestCase):

    def do_check(self, pytest_args="", timeout=0, return_line_coverage=False, detail=False, **kw):
        """call pytest to run the test cases."""
        report, str_out, str_err = super().do_check(pytest_args=pytest_args, timeout=timeout, **kw)
        test_pass, test_msg = is_run_report_pass(report, str_out, str_err)
        if not test_pass:
            return False, test_msg
        # refine report:
        # ``unhit_checkpoints`` are coverage bins never hit in this run; they are
        # not test failures.  ``hit_checkpoints`` are bins with at least one
        # coverage hit; mark_function associations live in
        # ``test_case_with_check_point_list`` and are a different dimension.
        free_report = OrderedDict({
            "run_test_success": report.get("run_test_success", False),
            "tests": report.get("tests", {}),
            "unhit_checkpoints": report.get("unhit_check_point_list", []),
            "failed_test_case_checkpoints": report.get("failed_test_case_with_check_point_list",{})
        })
        unhit_checkpoints = report.get("unhit_check_point_list", [])
        free_report["hit_checkpoints"] = [
            b for b in report.get("all_check_point_list", [])
            if b not in unhit_checkpoints
        ]
        if return_line_coverage:
            line_coverage_data = {}
            line_coverage_file = self.extra_kwargs.get("coverage_json", "uc_test_report/line_dat/code_coverage.json")
            if not os.path.exists(self.get_path(line_coverage_file)):
                line_coverage_data["error"] = f"Line coverage file '{line_coverage_file}' does not exist in workspace."
            else:
                try:
                    line_coverage_data = parse_un_coverage_json(
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


# ---------------------------------------------------------------------------
# Checker - test template files
# ---------------------------------------------------------------------------

class UnityChipCheckerTestTemplate(BaseUnityChipCheckerTestCase):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.total_tests_count = 0
        self.cached_ck_file_blocks = None
        self.ignored_source_checkpoints = []
        self.batch_task = BatchTask("check_points", self)

    def _load_checkpoint_scope(self):
        all_doc_checkpoints, file_blocks = get_doc_marks(
            self.get_path(self.doc_func_check),
            leaf_node="CK",
            return_line_block=True,
        )
        ignored_prefixes = _normalize_checkpoint_prefixes(
            self.extra_kwargs.get("ignore_ck_prefix", "")
        )
        ignored_checkpoints = [
            checkpoint
            for checkpoint in all_doc_checkpoints
            if any(
                checkpoint.startswith(prefix)
                for prefix in ignored_prefixes
            )
        ]
        target_checkpoints = [
            checkpoint
            for checkpoint in all_doc_checkpoints
            if checkpoint not in ignored_checkpoints
        ]
        self.ignored_source_checkpoints = ignored_checkpoints
        return all_doc_checkpoints, target_checkpoints, file_blocks

    def get_template_data(self):
        if hasattr(self, "batch_task"):
            data = self.batch_task.get_template_data("TOTAL_CKS", "COVERED_CKS", "LIST_CKS_TO_BE_COVERED")
            data["CASE_TESTS_COUNT"] = self.total_tests_count if hasattr(self, "total_tests_count") else "-"
            data["LIST_CK_FILE_BLOCKS"] = "Error: CK content not find"
            if hasattr(self, "cached_ck_file_blocks") and self.cached_ck_file_blocks is not None:
                data["LIST_CK_FILE_BLOCKS"] = merge_file_blocks([{k:self.cached_ck_file_blocks.get(k, ["Error, file content not found"])} for k in data["LIST_CKS_TO_BE_COVERED"]])
            return data
        return {
            "TOTAL_CKS":      "-",
            "COVERED_CKS":    "-",
            "LIST_CKS_TO_BE_COVERED": [],
            "CASE_TESTS_COUNT":    "-",
            "LIST_CK_FILE_BLOCKS": "-",
        }

    def on_init(self):
        self.total_tests_count = 0
        _, target_checkpoints, self.cached_ck_file_blocks = self._load_checkpoint_scope()
        note_msg = []
        self.batch_task.sync_source_task(
            target_checkpoints,
            note_msg,
            f"{self.doc_func_check} file CK points changed.",
        )
        self.batch_task.update_current_tbd()
        info(
            f"Load template ck list(size={len(target_checkpoints)}, "
            f"ignored={len(self.ignored_source_checkpoints)}) from doc file "
            f"'{self.doc_func_check}'."
        )
        return super().on_init()

    def do_check(self, timeout=0, is_complete=False, **kw) -> Tuple[bool, str]:
        """
        Perform the check for test templates.

        Returns:
            Tuple[bool, str]: A tuple where the first element is a boolean indicating success or failure,
                              and the second element is a message string.
        """
        pytest_ex_env={"UC_IS_IMP_TEMPLATE":"true"}
        kw["return_test_details"] = True
        report, str_out, str_err = super().do_check(
            pytest_ex_env=pytest_ex_env,
            timeout=timeout,
            **kw,
        )
        test_pass, test_msg = is_run_report_pass(report, str_out, str_err)
        if not test_pass:
            return False, test_msg
        raw_report = copy.deepcopy(report)
        all_bins_test = report.get("all_check_point_list", [])
        msg_report = clean_report_with_keys(report,
                                               ["tests.test_cases",
                                                "tests.test_case_details",
                                                "failed_test_case_with_check_point_list"])
        info_report = OrderedDict({"TEST_REPORT": msg_report})
        info_runtest = OrderedDict({"TEST_REPORT": msg_report})
        if self.ret_std_out:
            info_report.update({"STDOUT": str_out})
            info_runtest.update({"STDOUT": str_out})
        if self.ret_std_error:
            info_report.update({"STDERR": str_err})
            info_runtest.update({"STDERR": str_err})
        collection_error = self._get_pytest_collection_error(str_out, str_err)
        if collection_error:
            info_runtest["error"] = collection_error
            return False, info_runtest
        test_cases = report.get("tests", {}).get("test_cases", None)
        if test_cases is None:
            info_runtest["error"] = "No test cases found in the report. " +\
                                    "Please ensure that the test report is generated correctly."
            return False, info_runtest
        self.total_tests_count = len([
            test_case
            for test_case in test_cases
            if not self._is_ignored_test_case(test_case)
        ])
        if report.get("tests") is None:
            info_runtest["error"] = "No test cases found in the report. " +\
                                    "Please ensure that the test cases are defined correctly in the workspace."
            return False, info_runtest
        if report["tests"]["total"] < self.min_tests:
            info_runtest["error"] = f"Insufficient test cases defined: {report['tests']['total']} found, " +\
                                    f"minimum required is {self.min_tests}. " + \
                                     "Please ensure that the test cases are defined in the correct format and location."
            return False, info_runtest
        # Additional template-specific validations
        template_validation_result = self._validate_template_structure(report, str_out, str_err)
        if not template_validation_result[0]:
            info_runtest["error"] = template_validation_result[1]
            return False, info_runtest

        missing_coverage_message = get_missing_functional_coverage_message(report)
        if missing_coverage_message:
            info_runtest["error"] = missing_coverage_message
            return False, info_runtest

        try:
            all_bins_docs, target_bins_docs, self.cached_ck_file_blocks = (
                self._load_checkpoint_scope()
            )
        except Exception as e:
            info_report["error"] = (
                "Failed to parse the function and check documentation file "
                f"{self.doc_func_check}: {str(e)}. Review your task requirements and the "
                "file format to fix your documentation file."
            )
            return False, info_report

        # Validate report/document consistency before updating batch progress so
        # a root-cause diagnostic is not hidden behind a generic incomplete batch.
        bins_not_in_docs = []
        bins_not_in_test = []
        for b in all_bins_test:
            if b not in all_bins_docs:
                bins_not_in_docs.append(b)
        for b in all_bins_docs:
            if b not in all_bins_test:
                bins_not_in_test.append(b)
        if len(bins_not_in_docs) > 0:
            info_runtest["error"] = f"The follow {len(bins_not_in_docs)} check points: {list_str_abbr(bins_not_in_docs)} are not defined in the documentation file {self.doc_func_check} but defined in the test cover group. " + \
                                     "Please ensure that all check points in the test cover group are defined in the documentation file. " + \
                                     "Review your task requirements and the test cases."
            return False, info_runtest
        if len(bins_not_in_test) > 0:
            info_runtest["error"] = f"The follow {len(bins_not_in_test)} check points: {list_str_abbr(bins_not_in_test)} are defined in the documentation file {self.doc_func_check} but not defined in the test cover group. " + \
                                     "Please ensure that all check points defined in the documentation are also in the the test cover group. " + \
                                     "Review your task requirements and the test cases."
            return False, info_runtest

        unassociated_test_count = report.get(
            'test_function_with_no_check_point_mark', 0
        )
        if unassociated_test_count > 0:
            unmarked_functions = report.get(
                'test_function_with_no_check_point_mark_list', []
            )
            mark_function_desc = description_mark_function_doc(
                unmarked_functions,
                self.workspace,
            )
            info_runtest["error"] = (
                "[Test Association Missing] Toffee recorded "
                f"{unassociated_test_count} executed test function(s) without any checkpoint "
                f"association. {mark_function_desc}"
            )
            return False, info_runtest

        unmarked_doc_checkpoints = [
            ck for ck in report.get('unmarked_check_point_list', [])
            if ck in target_bins_docs
        ]
        initialized_batch = bool(self.batch_task.source_task_list)
        required_associations = set(target_bins_docs)
        if initialized_batch:
            required_associations = set(self.batch_task.gen_task_list)
            required_associations.update(self.batch_task.tbd_task_list)
        missing_required_associations = [
            checkpoint
            for checkpoint in unmarked_doc_checkpoints
            if checkpoint in required_associations
        ]
        if missing_required_associations:
            info_runtest["error"] = description_checkpoint_association_missing(
                missing_required_associations
            )
            return False, info_runtest

        # All structural and association checks passed; batch progress can now
        # be derived from test associations rather than coverage declarations.
        associated_target_checkpoints = [
            checkpoint
            for checkpoint in target_bins_docs
            if checkpoint not in unmarked_doc_checkpoints
        ]
        if initialized_batch:
            allowed_associations = set(self.batch_task.gen_task_list)
            allowed_associations.update(self.batch_task.tbd_task_list)
            future_associations = [
                checkpoint
                for checkpoint in associated_target_checkpoints
                if checkpoint not in allowed_associations
            ]
            if future_associations:
                bounded_future = future_associations[:20]
                return False, {
                    "error_code": "TEST_TEMPLATE_FUTURE_BATCH_ASSOCIATION",
                    "error": (
                        "Test templates associate checkpoints outside the current batch."
                    ),
                    "next_action": (
                        "Remove templates for future checkpoints and create only the checkpoint "
                        "templates listed by CurrentTips, then call Check again."
                    ),
                    "artifact": self.test_dir,
                    "location": self.test_dir,
                    "observed": {
                        "future_checkpoint_count": len(future_associations),
                        "future_checkpoints": bounded_future,
                        "truncated": len(future_associations) > len(bounded_future),
                    },
                    "expected": {
                        "current_checkpoints": list(self.batch_task.tbd_task_list),
                        "previously_completed_checkpoints": list(
                            self.batch_task.gen_task_list
                        ),
                    },
                }
        note_msg = []
        self.batch_task.sync_source_task(
            target_bins_docs,
            note_msg,
            f"{self.doc_func_check} file CK points changed.",
        )
        self.batch_task.sync_gen_task(
            associated_target_checkpoints,
            note_msg,
            "Test checkpoint associations changed.",
        )
        ckpass, emssage = self.batch_task.do_complete(
            note_msg,
            is_complete,
            f"in file: {self.doc_func_check}",
            f"in dir: {self.test_dir}",
            " Please define and associate every required checkpoint with its related tests.",
        )
        if not ckpass:
            return ckpass, emssage

        # Success message with template-specific details
        info_report["success"] = ["Test template validation successful!",
                                 f"✓ Generated {report['tests']['total']} test case templates (all properly failing as expected).",
                                 f"✓ All {len(associated_target_checkpoints)} in-scope check points completed so far are properly documented and marked in test functions.",
                                 f"✓ Coverage mapping is consistent between documentation and test implementation.",
                                 f"✓ Template structure follows the required format with proper TODO comments and fail assertions.",
                                 "Your test templates are ready for implementation! Each test function provides clear guidance for the actual test logic to be implemented."]
        if self.data_key:
            self.smanager_set_value(self.data_key, raw_report, persist=True)
        if "STDOUT" in info_report:
            del info_report["STDOUT"]
        if "STDERR" in info_report:
            del info_report["STDERR"]
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
        test_cases = report.get("tests", {}).get("test_cases", None)
        if test_cases is None:
            return False, "Test template structure validation failed: No test cases found in the report. " +\
                          "Please ensure that the test report is generated correctly."

        must_fail = self.extra_kwargs.get("template_must_fail", True)
        if not must_fail:
            return True, "Template structure validation passed."
        assert_example = 'assert False, "Not implemented"'
        expected_assertion = (
            "AssertionError('Not implemented') "
            f"(Correct example: {assert_example})"
        )

        def is_ignored(test_case):
            return self._is_ignored_test_case(test_case)

        checked_cases = {
            test_case: status
            for test_case, status in test_cases.items()
            if not is_ignored(test_case)
        }
        test_details = report.get("tests", {}).get("test_case_details", {})

        def describe(test_case, status):
            detail = test_details.get(test_case, {})
            exception = detail.get("exception") or detail.get("exception_type")
            phase = detail.get("phase")
            description = f"{test_case}={status}"
            if exception:
                description += f" ({phase + ': ' if phase else ''}{exception})"
            return description

        execution_error_cases = [
            test_case
            for test_case, status in checked_cases.items()
            if status not in {"PASSED", "FAILED"}
        ]
        execution_errors = [
            describe(test_case, checked_cases[test_case])
            for test_case in execution_error_cases
        ]
        if execution_errors:
            guidance = self._get_template_execution_guidance(
                execution_error_cases, test_details
            )
            return False, (
                "Test template execution failed: Some tests ended with execution or lifecycle "
                f"errors instead of the required {expected_assertion}: "
                f"{list_str_abbr(execution_errors, max_items=20, show_counts=True)} "
                "These are not missing template assertions "
                f"and are not necessarily caused by the test function itself. {guidance}"
            )

        passed_tests = [
            describe(test_case, status)
            for test_case, status in checked_cases.items()
            if status == "PASSED"
        ]
        if passed_tests:
            return False, (
                "Test template structure validation failed: The following test functions passed "
                "instead of reaching the required fail assertion: "
                f"{list_str_abbr(passed_tests, max_items=20, show_counts=True)} "
                f"Required outcome: {expected_assertion}."
            )

        unexpected_failure_cases = []
        missing_failure_details = []
        wrong_assert_messages = []
        for test_case, status in checked_cases.items():
            if status != "FAILED":
                continue
            detail = test_details.get(test_case, {})
            exception_type = detail.get("exception_type")
            exception = detail.get("exception", "")
            if not exception_type:
                missing_failure_details.append(describe(test_case, status))
            elif exception_type != "AssertionError":
                unexpected_failure_cases.append(test_case)
            elif "Not implemented" not in exception:
                wrong_assert_messages.append(describe(test_case, status))

        if unexpected_failure_cases:
            unexpected_failures = [
                describe(test_case, checked_cases[test_case])
                for test_case in unexpected_failure_cases
            ]
            guidance = self._get_template_execution_guidance(
                unexpected_failure_cases, test_details
            )
            return False, (
                "Test template execution failed: Some tests raised unexpected exceptions instead "
                f"of the required {expected_assertion}: "
                f"{list_str_abbr(unexpected_failures, max_items=20, show_counts=True)} "
                "The underlying exception may come from "
                f"the test, a called component, or the execution environment. {guidance}"
            )
        if missing_failure_details:
            return False, (
                "Test template assertion validation failed: Could not determine the exception type "
                "for these tests: "
                f"{list_str_abbr(missing_failure_details, max_items=20, show_counts=True)} "
                "Review the first relevant "
                "traceback in STDOUT/STDERR and fix the component that owns the failing frame. "
                f"Required outcome: {expected_assertion}."
            )
        if wrong_assert_messages:
            return False, (
                "Test template structure validation failed: The following tests raised AssertionError "
                "without the required 'Not implemented' message: "
                f"{list_str_abbr(wrong_assert_messages, max_items=20, show_counts=True)} "
                f"Required outcome: {expected_assertion}."
            )
        return True, "Template structure validation passed."

    @staticmethod
    def _get_template_execution_guidance(test_cases, test_details):
        """Build ownership-aware advice from pytest lifecycle phases."""
        phases = {
            str(test_details.get(test_case, {}).get("phase", "")).lower()
            for test_case in test_cases
        }
        phases.discard("")
        suggestions = []
        if "setup" in phases:
            suggestions.append(
                "For setup-phase failures, the test body may not have run: check fixtures, "
                "DUT/simulator environment initialization, imports and dependencies, build "
                "artifacts, and configuration"
            )
        if "call" in phases:
            suggestions.append(
                "For call-phase failures, check both the test body and the code it invokes, "
                "including fixture objects, APIs, reference models, the DUT/simulator, and "
                "external dependencies"
            )
        if "teardown" in phases:
            suggestions.append(
                "For teardown-phase failures, check fixture finalizers, resource release, "
                "simulator shutdown, and cleanup hooks"
            )
        if not suggestions:
            suggestions.append(
                "The failing phase is unknown, so check collection/imports, fixtures, "
                "DUT/environment initialization, dependencies, and the test body"
            )
        return (
            "Resolution guidance: "
            + "; ".join(suggestions)
            + ". Follow the earliest relevant traceback frame to the owning module and fix that "
              "underlying issue before changing or adding the placeholder assertion."
        )

    @staticmethod
    def _get_pytest_collection_error(str_out, str_err):
        """Return a specific message for failures that prevent test collection."""
        output = "\n".join(part for part in (str_out, str_err) if part)
        collection_markers = (
            "ERROR collecting",
            "error during collection",
            "errors during collection",
            "ImportError while importing test module",
            "INTERNALERROR",
        )
        if not any(marker.lower() in output.lower() for marker in collection_markers):
            return None

        exception_types = re.findall(
            r"\b(SyntaxError|IndentationError|TabError|ImportError|ModuleNotFoundError)\b",
            output,
        )
        exception_desc = ", ".join(dict.fromkeys(exception_types)) or "pytest collection error"
        return (
            "Test template collection failed before the expected assertion failures could be "
            f"validated ({exception_desc}). This is a test execution/collection error, not a "
            "missing template assertion, and it may be in the test module or an imported module, "
            "dependency, plugin, or configuration. Follow the first collection traceback to the "
            "owning file/module and fix that underlying issue before checking assertions."
        )


# ---------------------------------------------------------------------------
# Checker - batch test implementation
# ---------------------------------------------------------------------------

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
        self.ignore_ck_prefix = _normalize_checkpoint_prefixes(
            self.extra_kwargs.get("ignore_ck_prefix", "")
        )
        self._last_batch_progress = None
        self._batch_checkpoint_error = None
        self.batch_task = BatchTask("test_cases", self)
        info(f"{self.__class__.__name__} Batch size: {self.batch_size}")
        assert self.test_dir is not None, f"Need set test directory '{self.test_dir}'."

    def get_template_data(self):
        completed = len(self.batch_task.gen_task_list)
        total = len(self.batch_task.source_task_list)
        is_valid = total > 0
        return {
            "COMPLETED_CASES":    completed if is_valid else "-",
            "TOTAL_CASES":        total if is_valid else "-",
            "LIST_CURRENT_CASES": list(self.batch_task.tbd_task_list),
            "TEST_BATCH_RUN_ARGS": self.get_run_args(self.test_dir)[0] if is_valid else "-",
            "BATCH_PROGRESS": self._format_batch_progress(),
        }

    @staticmethod
    def _duplicates(items):
        seen = set()
        duplicates = []
        for item in items:
            if item in seen and item not in duplicates:
                duplicates.append(item)
            seen.add(item)
        return duplicates

    def _sync_batch_views(self):
        completed = set(self.batch_task.gen_task_list)
        self.total_test_cases = [
            (test_case, test_case in completed)
            for test_case in self.batch_task.source_task_list
        ]
        self.current_test_cases = list(self.batch_task.tbd_task_list)

    def _reconcile_batch_checkpoint(self, source_test_cases):
        if self.batch_task.checkpoint_error is not None:
            self._batch_checkpoint_error = copy.deepcopy(
                self.batch_task.checkpoint_error
            )
            return

        self._batch_checkpoint_error = None
        loaded_source = list(self.batch_task.source_task_list)
        loaded_gen = list(self.batch_task.gen_task_list)
        loaded_tbd = list(self.batch_task.tbd_task_list)
        loaded_cmp = list(self.batch_task.cmp_task_list)

        duplicate_fields = {
            field: duplicates
            for field, items in (
                ("source_task_list", loaded_source),
                ("gen_task_list", loaded_gen),
                ("tbd_task_list", loaded_tbd),
                ("cmp_task_list", loaded_cmp),
            )
            if (duplicates := self._duplicates(items))
        }
        loaded_source_set = set(loaded_source)
        unknown_tasks = sorted({
            task
            for tasks in (loaded_gen, loaded_tbd, loaded_cmp)
            for task in tasks
            if task not in loaded_source_set
        })
        if duplicate_fields or unknown_tasks:
            self._batch_checkpoint_error = {
                "error_code": "BATCH_CHECKPOINT_INVALID",
                "error": (
                    "The persisted test-case batch checkpoint contains duplicate or "
                    "unknown task identities."
                ),
                "observed": {
                    "duplicate_fields": duplicate_fields,
                    "unknown_tasks": unknown_tasks,
                    "checkpoint_file": self.batch_task.checkpoint_file,
                },
                "expected": (
                    "Every persisted task identity must be unique and belong to the "
                    "checkpoint's source_task_list."
                ),
                "next_action": (
                    "Inspect the reported checkpoint and the initial template report, "
                    "regenerate the invalid checkpoint from the current source task list, "
                    "then restart UCAgent."
                ),
            }
            return

        source_set = set(source_test_cases)
        completed = [task for task in loaded_gen if task in source_set]
        completed_set = set(completed)
        current = [
            task
            for task in loaded_tbd
            if task in source_set and task not in completed_set
        ]
        current_set = set(current)
        current_completed = [
            task
            for task in loaded_cmp
            if task in current_set and task in completed_set
        ]

        previous_state = (
            loaded_source,
            loaded_gen,
            loaded_tbd,
            loaded_cmp,
        )
        self.batch_task.source_task_list = list(source_test_cases)
        self.batch_task.gen_task_list = completed
        self.batch_task.tbd_task_list = current
        self.batch_task.cmp_task_list = current_completed
        self.batch_task.update_current_tbd()
        current_state = (
            self.batch_task.source_task_list,
            self.batch_task.gen_task_list,
            self.batch_task.tbd_task_list,
            self.batch_task.cmp_task_list,
        )
        if current_state != previous_state:
            self.batch_task.savepoint_file()
        self._sync_batch_views()

    def get_run_args(self, test_dir=None, test_cases=None):
        failed_tests_files = set()
        target_tests = ""
        for t in (test_cases if test_cases is not None else self.current_test_cases):
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

    def _current_batch_source_sha256(self):
        """Hash every source file that owns a test in the current batch."""

        source_files = sorted({
            test_case.split("::", 1)[0]
            for test_case in self.current_test_cases
        })
        source_hashes = {}
        for source_file in source_files:
            with open(self.get_path(source_file), "rb") as handle:
                source_hashes[source_file] = hashlib.sha256(handle.read()).hexdigest()
        return source_hashes

    def _test_report_context_details(self):
        """Bind a published report to the exact current batch and test sources."""

        return {
            "batch_test_cases": list(self.current_test_cases),
            "test_source_sha256": self._current_batch_source_sha256(),
        }

    def _load_cached_batch_report(self, target_tests):
        """Return a persisted report only when every batch identity still matches."""

        try:
            payload = load_current_test_report(self.workspace)
        except (FileNotFoundError, OSError, TypeError, ValueError, RuntimeError):
            return None
        report = payload.get("report")
        context = payload.get("context")
        if not isinstance(report, dict) or not isinstance(context, dict):
            return None
        expected_context = {
            **self._build_test_report_context(),
            "test_dir_or_file": self.test_dir,
            "pytest_ex_args": target_tests,
        }
        if any(context.get(key) != value for key, value in expected_context.items()):
            return None
        execution = report.get("execution")
        if (
            report.get("run_test_success") is not True
            or not isinstance(execution, dict)
            or execution.get("invocation_success") is not True
        ):
            return None
        reported_cases = report.get("tests", {}).get("test_cases", {})
        if not isinstance(reported_cases, dict):
            return None
        return_tests = {
            self.rm_line_no(test_case): status
            for test_case, status in reported_cases.items()
        }
        if (
            len(return_tests) != len(reported_cases)
            or set(return_tests) != set(self.current_test_cases)
        ):
            return None
        return report, return_tests

    def _cached_document_preflight(self, target_tests):
        """Reject stale document defects without rerunning the unchanged test batch."""

        cached = self._load_cached_batch_report(target_tests)
        if cached is None:
            return None
        report, return_tests = cached
        ret, message, _ = check_report(
            self.workspace,
            report,
            self.doc_func_check,
            self.doc_bug_analysis,
            only_marked_ckp_in_tc=True,
            ignore_ck_prefix=self.extra_kwargs.get("ignore_ck_prefix", ""),
            waveform_tool=self.get_waveform_tool_for_checker(),
            waveform_test_dir=self.test_dir,
            test_output_dir=self.get_configured_test_output_dir(),
            require_all_documented_tests=False,
        )
        if ret:
            return None
        batch_report = self._compact_validation_report(report, return_tests)
        batch_progress = self._set_batch_progress(
            return_tests,
            validation="document_failed",
            test_run="not_run",
        )
        failure = self._with_batch_context(
            message,
            validation_mode="cached_report_document_preflight",
            batch_progress=batch_progress,
            batch_report=batch_report,
        )
        failure.setdefault("error_code", "BATCH_DOCUMENT_PREFLIGHT_FAILED")
        failure.setdefault(
            "error",
            "The current Bug document does not validate against the unchanged current batch report.",
        )
        failure.setdefault(
            "next_action",
            "Follow the first reported Bug-document diagnostic. Use the "
            "dynamic-bug-recording Skill's -MODE repair only for generated anchors, "
            "references, containers, or relations; use its matching bug/root mode for "
            "semantic fields. When the Skill cannot recover malformed structure, apply "
            "only the exact bounded manual repair. Then call Check again. Do not rerun "
            "pytest or WaveInfo for this document-only failure.",
        )
        failure.update({
            "rerun_test": False,
            "rerun_waveinfo": False,
            "batch_advanced": False,
        })
        result = {"REPORT": report}
        _set_checker_failure(result, failure)
        return False, result

    def _validate_current_batch_report(self, report):
        """Validate one executed batch using the verification workflow contract."""

        ret, message, _ = check_report(
            self.workspace,
            report,
            self.doc_func_check,
            self.doc_bug_analysis,
            only_marked_ckp_in_tc=True,
            ignore_ck_prefix=self.extra_kwargs.get("ignore_ck_prefix", ""),
            waveform_tool=self.get_waveform_tool_for_checker(),
            waveform_test_dir=self.test_dir,
            test_output_dir=self.get_configured_test_output_dir(),
            require_all_documented_tests=False,
        )
        if not ret:
            return False, message, "document_failed"
        ret, message = check_has_assert_in_tc(self.workspace, report)
        if not ret:
            if isinstance(message, dict) and "error" in message:
                message = message["error"]
            return False, message, "assertion_failed"
        return True, "", "passed"

    @staticmethod
    def _compact_validation_report(report, return_tests):
        tests = report.get("tests", {})
        unmarked_checkpoints = report.get("unmarked_check_point_list", [])
        if not isinstance(unmarked_checkpoints, list):
            unmarked_checkpoints = []
        return {
            "run_test_success": report.get("run_test_success", False),
            "tests": {
                "total": tests.get("total", len(return_tests)),
                "fails": tests.get(
                    "fails",
                    sum(status != "PASSED" for status in return_tests.values()),
                ),
                "test_cases": return_tests,
            },
            "unhit_checkpoints": report.get("unhit_check_point_list", []),
            "failed_test_case_checkpoints": report.get(
                "failed_test_case_with_check_point_list", {}
            ),
            "unmarked_checkpoints": {
                "count": len(unmarked_checkpoints),
                "items": unmarked_checkpoints[:10],
                "truncated": len(unmarked_checkpoints) > 10,
            },
        }

    def _format_batch_progress(self):
        if self._last_batch_progress is None:
            return "not run"
        progress = self._last_batch_progress
        return (
            f"committed {progress['committed']}/{progress['total']}; "
            f"current batch executed {progress['executed']}/{progress['batch_total']}; "
            f"passed {progress['passed']}; failed {progress['failed']}; "
            f"validation {progress['validation']}; test run {progress['test_run']}"
        )

    def _set_batch_progress(
        self,
        return_tests,
        *,
        validation,
        test_run,
    ):
        self._last_batch_progress = {
            "committed": sum(completed for _test, completed in self.total_test_cases),
            "total": len(self.total_test_cases),
            "batch_total": len(self.current_test_cases),
            "executed": len(return_tests),
            "passed": sum(status == "PASSED" for status in return_tests.values()),
            "failed": sum(status != "PASSED" for status in return_tests.values()),
            "validation": validation,
            "test_run": test_run,
        }
        return copy.deepcopy(self._last_batch_progress)

    @staticmethod
    def _with_batch_context(
        message,
        *,
        validation_mode,
        batch_progress,
        batch_report,
    ):
        if isinstance(message, dict):
            contextual = copy.deepcopy(message)
        else:
            contextual = {"error": message}
        contextual["validation_mode"] = validation_mode
        contextual["batch_progress"] = copy.deepcopy(batch_progress)
        contextual["batch_report"] = copy.deepcopy(batch_report)
        return contextual

    def on_init(self):
        self.check_data()
        return super().on_init()

    def check_data(self):
        if not self._is_init:
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
            checkpoint_associations = pre_report.get(
                "test_case_with_check_point_list", {}
            )
            if not isinstance(checkpoint_associations, dict):
                checkpoint_associations = {}
            for k,v in pre_report.get("tests", {}).get("test_cases", {}).items():
                if self._is_ignored_test_case(k):
                    info(f"{self.__class__.__name__} ignore test case: {k}")
                    continue
                associated_checkpoints = checkpoint_associations.get(k)
                if (
                    self.ignore_ck_prefix
                    and isinstance(associated_checkpoints, list)
                    and associated_checkpoints
                    and all(
                        isinstance(checkpoint, str)
                        and any(
                            checkpoint.startswith(prefix)
                            for prefix in self.ignore_ck_prefix
                        )
                        for checkpoint in associated_checkpoints
                    )
                ):
                    info(
                        f"{self.__class__.__name__} ignore test case outside the "
                        f"checkpoint scope: {k}"
                    )
                    continue
                if v == "PASSED":
                    passed_tc.append(k)
                else:
                    failed_tc.append(k)
            if len(passed_tc) != 0:
                warning(f"No test cases defined for implementation. However, {len(passed_tc)} test cases are already passing: {list_str_abbr(passed_tc)}. ")
            source_test_cases = [self.rm_line_no(k) for k in sorted(failed_tc)]
            if len(source_test_cases) == 0:
                return False, "No test cases found for implementation. All test cases are already passing. Nothing to do."
            self._reconcile_batch_checkpoint(source_test_cases)
            if self._batch_checkpoint_error is not None:
                return False, self._batch_checkpoint_error
            if self._last_batch_progress is None:
                self._set_batch_progress(
                    {},
                    validation="pending" if self.current_test_cases else "passed",
                    test_run="not_run",
                )
            info(f"Total {len(self.total_test_cases)} test cases need to be implemented.")
        elif self._batch_checkpoint_error is not None:
            return False, self._batch_checkpoint_error
        else:
            self._sync_batch_views()
        info(f"Current batch: {len(self.current_test_cases)} test cases to implement: {list_str_abbr(self.current_test_cases)}")
        info(f"Completed {sum([t[1] for t in self.total_test_cases])} out of {len(self.total_test_cases)} test cases.")
        return True, ""

    def do_check(self, timeout=0, is_complete=False, **kw) -> Tuple[bool, str]:
        """run batch of tests and check result."""
        success, msg = self.check_data()
        if not success:
            return False, msg if isinstance(msg, dict) else {"error": msg}
        if len(self.current_test_cases) == 0:
            return True, {"success": "All test cases have been implemented! Use tool `Complete to` finish this stage."}
        target_tests, failed_tests_files = self.get_run_args(self.test_dir)
        if len(failed_tests_files) > 0:
            return False, {"error": f"The following test files do not exist: {list_str_abbr(failed_tests_files)}. " + \
                            "Please check your test case names and ensure they are correct."}
        preflight_result = self._cached_document_preflight(target_tests)
        if preflight_result is not None:
            return preflight_result
        info(f"Checking {len(self.current_test_cases)} test cases: {target_tests}")
        report, str_out, str_err = super().do_check(pytest_args=target_tests, timeout=timeout, **kw)
        test_pass, test_msg = is_run_report_pass(report, str_out, str_err)
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
            info(f"implemented cases: {list_str_abbr(return_tests.keys())}")
            error_msgs["error"] = f"The following test cases: `{list_str_abbr(missing_tests)}` are missing in the tests implementation. " + \
                                   "Please ensure that all test cases are properly implemented and reported."
            return False, error_msgs
        if len(extends_tests) > 0:
            error_msgs["error"] = (
                f"The test run returned {len(extends_tests)} case(s) outside the current "
                f"batch: {list_str_abbr(extends_tests)}. Run exactly the current batch "
                "targets before retrying Check."
            )
            return False, error_msgs

        ret, msg, validation = self._validate_current_batch_report(report)
        batch_report = self._compact_validation_report(report, return_tests)
        error_msgs["REPORT"] = report
        if not ret:
            batch_progress = self._set_batch_progress(
                return_tests,
                validation=validation,
                test_run="executed",
            )
            contextual_failure = self._with_batch_context(
                msg,
                validation_mode="fresh_test_run",
                batch_progress=batch_progress,
                batch_report=batch_report,
            )
            if validation == "assertion_failed":
                error_msgs["error"] = contextual_failure
            else:
                _set_checker_failure(error_msgs, contextual_failure)
            return ret, error_msgs
        completed_batch_size = len(self.current_test_cases)
        completed_test_cases = list(self.batch_task.gen_task_list)
        for test_case in self.current_test_cases:
            if test_case not in completed_test_cases:
                completed_test_cases.append(test_case)
        note_msg = []
        self.batch_task.sync_gen_task(
            completed_test_cases,
            note_msg,
            "Validated test cases changed.",
        )
        batch_pass, batch_message = self.batch_task.do_complete(
            note_msg,
            is_complete,
            "in the initial template report",
            f"validated from {self.test_dir}",
            " Run and validate exactly the current test-case batch.",
        )
        self._sync_batch_views()
        self._last_batch_progress = {
            "committed": sum(completed for _test, completed in self.total_test_cases),
            "total": len(self.total_test_cases),
            "batch_total": len(self.current_test_cases),
            "executed": 0,
            "passed": 0,
            "failed": 0,
            "validation": "pending" if self.current_test_cases else "passed",
            "test_run": "not_run" if self.current_test_cases else "executed",
        }
        if batch_pass:
            return True, {"success": "Congratulations! All test cases have been implemented! Use tool `Complete to` finish this stage."}
        if not isinstance(batch_message, dict) or "success" not in batch_message:
            return batch_pass, batch_message
        return False, {"success": f"Great! {completed_batch_size} test cases have been successfully implemented. " + \
                                  f"Next, please proceed to implement the following {len(self.current_test_cases)} test cases: {list_str_abbr(self.current_test_cases)}. " + \
                                  f"Test case implemention progress: {sum([t[1] for t in self.total_test_cases])}/{len(self.total_test_cases)}. "}


# ---------------------------------------------------------------------------
# Checker - test case with line coverage
# ---------------------------------------------------------------------------

class UnityChipCheckerTestCaseWithLineCoverage(UnityChipCheckerTestCase):

    def __init__(self, doc_func_check=None,
                 test_dir=None, doc_bug_analysis=None, cfg=None,
                 min_tests=1, timeout=15, ignore_tc_prefix="", data_key=None,
                 **extra_kwargs):
        super().__init__(
            doc_func_check,
            test_dir,
            doc_bug_analysis,
            min_tests,
            timeout,
            ignore_tc_prefix,
            data_key,
            cfg=cfg,
            **extra_kwargs,
        )
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

