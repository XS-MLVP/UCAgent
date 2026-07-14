#coding=utf-8

import ast
import copy
import json
import os
from collections import OrderedDict
from typing import Tuple

import ucagent.util.functions as fc
from ucagent.checkers.base import UnityChipBatchTask
from ucagent.checkers.unity_test import BaseUnityChipCheckerTestCase
from typing import Tuple
import inspect
from ucagent.checkers.toffee_report import check_report
from ucagent.util.log import warning


class RandomTestCasesChecker(BaseUnityChipCheckerTestCase):
    """Batch checker for random test-case generation records.

    The checker does not inspect random test-file structure. A CK is considered
    done when it appears in the current batch's ``generated`` argument. Matching
    random test files are still executed when they exist.
    """

    def __init__(self, target_test_file, mini_file_count=1, min_test_count=1,
                 test_case_name_pattern="test_random_*",
                 must_func_code_snippet={"ucagent.repeat_count": "you must use this function to set the repeat count for random test cases.",
                                         ".mark_function": "you must use this function to mark the function coverage and check points."
                                         },
                 batch_size=10,
                 **kw):
        kw["min_tests"] = min_test_count
        super().__init__(batch_size=batch_size, **kw)
        self.target_test_file = target_test_file
        self.mini_file_count = mini_file_count
        self.min_test_count = min_test_count
        self.test_case_name_pattern = test_case_name_pattern
        self.must_func_code_snippet = must_func_code_snippet
        self.total_random_test_count = 0
        self.batch_size = batch_size
        self.random_result = OrderedDict()
        self.cached_ck_file_blocks = OrderedDict()
        self._random_result_key = "_RANDOM_TEST_CASES_RESULT"
        self.batch_task = UnityChipBatchTask("CK", self)

    def test_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Check random test cases"""
        test_files = fc.find_files_by_pattern(self.workspace, self.target_test_file)
        if len(test_files) < self.mini_file_count:
            return False, f"Random test cases check fail: found {len(test_files)} test files, " \
                          f"expected at least {self.mini_file_count} files with pattern: {self.target_test_file}."
        total_test_count = 0
        for tfile in test_files:
            random_tc_list = fc.get_target_from_file(self.get_path(tfile), self.test_case_name_pattern,
                                           ex_python_path=self.workspace,
                                           dtype="FUNC")
            total_test_count += len(random_tc_list)
            for tfunc in random_tc_list:
                args = fc.get_func_arg_list(tfunc)
                if len(args) < 1 or args[0] != "env":
                    return False, {"error": f"The '{tfile + ':' + tfunc.__name__}' Env test function's first arg must be 'env', but got ({', '.join(args)})."}
                func_source = inspect.getsource(tfunc)
                for mc, v in self.must_func_code_snippet.items():
                    if mc not in func_source:
                        return False, {"error": f"The '{tfile + ':' + tfunc.__name__}' Env test function must contain "
                                                f"'{mc}', {v}"}
        if total_test_count < self.min_test_count:
            return False, f"Random test cases check fail: found {total_test_count} test cases, " \
                          f"expected at least {self.min_test_count} cases."
        self.total_random_test_count = total_test_count
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

    def _load_doc_cks(self, min_count=1):
        doc_path = self.get_path(self.doc_func_check)
        if not os.path.exists(doc_path):
            raise FileNotFoundError(
                f"Function and check documentation file {self.doc_func_check} does not exist in workspace."
            )
        return fc.get_unity_chip_doc_marks(
            doc_path,
            leaf_node="CK",
            mini_leaf_count=min_count,
            return_line_block=True,
        )

    def _sync_source_from_doc(self, current_doc_ck_list, note_msg=None):
        if note_msg is None:
            note_msg = []
        self.batch_task.sync_source_task(
            current_doc_ck_list,
            note_msg,
            f"{self.doc_func_check} file CK points changed.",
        )
        self.batch_task.update_tbd_and_cmp()
        self.batch_task.gen_task_list = [
            ck for ck in self.batch_task.gen_task_list
            if ck in current_doc_ck_list
        ]
        self.batch_task.update_current_tbd()

    def on_init(self):
        saved_random_result = {}
        if self.stage_manager is not None:
            saved_random_result = self.smanager_get_value(self._random_result_key, {})
        if isinstance(saved_random_result, dict):
            self.random_result = OrderedDict(saved_random_result)
        try:
            current_doc_ck_list, self.cached_ck_file_blocks = self._load_doc_cks(min_count=0)
            self._sync_source_from_doc(current_doc_ck_list)
        except Exception as e:
            warning(f"Failed to initialize random test-case context: {e}")
        return super().on_init()

    def _build_current_ck_infos(self, ck_list):
        ck_infos = []
        for ck in ck_list:
            ck_infos.append(OrderedDict({
                "CK": ck,
                "doc_block": self.cached_ck_file_blocks.get(ck, []),
                "generated_record": self.random_result.get(ck),
            }))
        return ck_infos

    def get_template_data(self):
        data = self.batch_task.get_template_data("TOTAL_CKS", "COMPLETED_CKS", "LIST_CURRENT_CKS")
        data["LIST_CURRENT_CKS"] = self._build_current_ck_infos(data["LIST_CURRENT_CKS"])
        data["TOTAL_RANDOM_TEST_COUNT"] = self.total_random_test_count if self.total_random_test_count > 0 else "-"
        return data

    def _run_random_tests(self, timeout=0, **kw):
        return self.test_check(timeout=timeout, **kw)

    @staticmethod
    def _parse_generated_arg(generated):
        if isinstance(generated, str):
            generated_text = generated.strip()
            if generated_text.startswith("```") and generated_text.endswith("```"):
                generated_lines = generated_text.splitlines()
                if len(generated_lines) >= 2:
                    generated_text = "\n".join(generated_lines[1:-1]).strip()
            for prefix in ["generated=", "generated:"]:
                if generated_text.startswith(prefix):
                    generated_text = generated_text.split(prefix[-1], 1)[1].strip()
                    break
            try:
                generated = json.loads(generated_text)
            except json.JSONDecodeError:
                try:
                    generated = ast.literal_eval(generated_text)
                except (SyntaxError, ValueError):
                    raise ValueError(
                        "The 'generated' argument was received as a string and could not be parsed as a dictionary. "
                        'Pass generated as a real top-level JSON object, for example '
                        '{"generated": {"FG-.../FC-.../CK-...": "record note"}}. '
                        f"value={generated}"
                    )

        if generated is None:
            return OrderedDict()
        if not isinstance(generated, dict):
            raise TypeError(
                "The 'generated' argument must be a dictionary like "
                "{'FG-.../FC-.../CK-...': 'record note'}. "
                f"But find type(generated)={type(generated)}. value={generated}"
            )

        generated_map = OrderedDict()
        for key, value in generated.items():
            if key is None:
                continue
            ck = str(key).strip()
            if ck:
                generated_map[ck] = value
        return generated_map

    def do_check(self, timeout=0, is_complete=False, generated=None, **kw) -> Tuple[bool, object]:
        """Check random test-case generation records."""
        try:
            current_doc_ck_list, self.cached_ck_file_blocks = self._load_doc_cks(min_count=1)
        except Exception as e:
            return False, {
                "error": f"Failed to parse the function and check documentation file {self.doc_func_check}: {str(e)}. "
                         "Review the file format and ensure it contains valid <FG-*>, <FC-*>, and <CK-*> labels."
            }

        note_msg = []
        self._sync_source_from_doc(current_doc_ck_list, note_msg)

        completed_tasks = [
            ck for ck in self.batch_task.gen_task_list
            if ck in current_doc_ck_list
        ]
        for ck in self.random_result.keys():
            if ck in current_doc_ck_list and ck not in completed_tasks:
                completed_tasks.append(ck)
        self.batch_task.sync_gen_task(
            completed_tasks,
            note_msg,
            "Random test-case CK records changed.",
        )
        self.batch_task.update_current_tbd()

        try:
            generated_map = self._parse_generated_arg(generated)
        except (TypeError, ValueError) as e:
            return False, {"error": str(e)}

        error_mesg = []
        unknown_tasks = [key for key in generated_map if key not in current_doc_ck_list]
        if unknown_tasks:
            error_mesg.extend([
                "The following random-test CK labels are not in the current function/check document. "
                "Please ensure that you are analyzing the correct labels:",
                *unknown_tasks,
            ])

        current_batch = set(self.batch_task.tbd_task_list)
        out_of_batch_tasks = [
            key for key in generated_map
            if key in current_doc_ck_list and key not in current_batch
        ]
        if out_of_batch_tasks and current_batch:
            error_mesg.extend([
                "The following random-test CK labels are valid, but they are not in the current batch. "
                "Please analyze the current batch first:",
                *out_of_batch_tasks,
            ])

        if unknown_tasks or (out_of_batch_tasks and current_batch):
            if self.batch_task.tbd_task_list:
                error_mesg.append(f"Current batch CK labels: {', '.join(self.batch_task.tbd_task_list)}")
                error_mesg.append({"current_batch": self._build_current_ck_infos(self.batch_task.tbd_task_list)})
            return False, {"error": error_mesg}

        valid_tasks = [
            key for key in generated_map
            if key in current_batch
        ]
        remaining_current_batch = [
            ck for ck in self.batch_task.tbd_task_list
            if ck not in completed_tasks
        ]
        if len(valid_tasks) < 1 and remaining_current_batch:
            return False, {
                "error": [
                    "No valid CK labels were recorded in the current random-test batch (need use args `generated: dict` "
                    "to pass CK processing records). Please analyze at least one of these CK labels: "
                    f"{', '.join(remaining_current_batch)}.",
                    {"current_batch": self._build_current_ck_infos(remaining_current_batch)},
                ]
            }

        for ck in valid_tasks:
            self.random_result[ck] = generated_map[ck]
            if ck not in completed_tasks:
                completed_tasks.append(ck)

        self.batch_task.sync_gen_task(
            completed_tasks,
            note_msg,
            "Random test-case CK records changed.",
        )

        if self.stage_manager is not None:
            self.smanager_set_value(self._random_result_key, copy.deepcopy(self.random_result))
            if self.data_key:
                self.smanager_set_value(self.data_key, OrderedDict({
                    "source_ck_list": current_doc_ck_list,
                    "generated_result": copy.deepcopy(self.random_result),
                }))

        random_test_pass, random_test_msg = self._run_random_tests(timeout=timeout, **kw)
        if not random_test_pass:
            return random_test_pass, random_test_msg

        ck_pass, ck_error = self.batch_task.do_complete(
            note_msg,
            is_complete,
            f"in file: {self.doc_func_check}",
            f"in generated argument for random test cases",
            " Please record generated={CK: note} for the current batch.",
        )
        if isinstance(ck_error, dict) and self.batch_task.tbd_task_list:
            ck_error["current_batch"] = self._build_current_ck_infos(self.batch_task.tbd_task_list)
        return ck_pass, ck_error
