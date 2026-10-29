# -*- coding: utf-8 -*-
"""UnityTest workflow-document Checkers."""

import ast
import copy
import glob
import os
from collections import OrderedDict
from typing import Tuple

import ucagent.util.functions as fc
from ucagent.checkers.base import Checker, BatchTask, format_stage_args_examples
from ucagent.util.log import info, warning
from .unity_test import (
    UnityChipCheckerLabelStructure,
    _normalize_checkpoint_prefixes,
    _normalize_test_prefixes,
    _test_name_matches_prefixes,
)
from ucagent_common.doc_marks import get_doc_marks


# ---------------------------------------------------------------------------
# Checker - workflow markdown file format
# ---------------------------------------------------------------------------

class UnityChipCheckerMarkdownFileFormat(Checker):
    def __init__(self, markdown_file_list, no_line_break=False, **kw):
        super().__init__()
        self.markdown_file_list = markdown_file_list if isinstance(markdown_file_list, list) else [markdown_file_list]
        self.no_line_break = no_line_break

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Check the markdown file format."""
        msg = f"{self.__class__.__name__} check pass."
        for markdown_file in self.markdown_file_list:
            info(f"check file: {markdown_file}")
            real_file = self.get_path(markdown_file)
            if not os.path.exists(real_file):
                return False, {"error": f"Markdown file '{markdown_file}' does not exist."}
            try:
                with open(real_file) as f:
                    lines  = f.readlines()
                    if len(lines) == 1 and "\\n" in lines[0]:
                        return False, {"error": "Markdown file is not properly formatted. You may mistake '\n' as '\\n'."}
                    for i, l in enumerate(lines):
                        if "\\n" in l:
                            return False, {"error": f"Find '\\n' in: {markdown_file}:{i}. content: {l}. Do you mean '\n' instead ?"}
            except Exception as e:
                return False, {"error": f"Failed to read markdown file '{markdown_file}': {str(e)}."}
        return True, {"message": msg}


# ---------------------------------------------------------------------------
# Checker - workflow doc label structure refinement
# ---------------------------------------------------------------------------

class UnityChipCheckerLabelStructureRefine(UnityChipCheckerLabelStructure):
    accepted_stage_args = ("refined",)

    def __init__(self,
                 doc_file,
                 leaf_node,
                 data_key,
                 min_count=1, must_have_prefix="FG-API", need_human_check=False,
                 batch_size = 10,
                 **kw):
        super().__init__(doc_file, leaf_node, min_count, must_have_prefix, data_key, need_human_check, **kw)
        assert data_key, "data_key must be provided for UnityChipCheckerLabelStructureRefine."
        self.need_save_data = False
        self.batch_size = batch_size
        self.refine_result = {}
        self.batch_task = BatchTask("CK", self)

    def on_init(self):
        source_task_list = self.smanager_get_value(self.data_key, [])
        if not isinstance(source_task_list, list) or not source_task_list:
            try:
                source_task_list = get_doc_marks(
                    self.get_path(self.doc_file),
                    self.leaf_node,
                    self.min_count,
                )
                self.smanager_set_value(self.data_key, copy.deepcopy(source_task_list))
                info(f"Initialized CK refine source from '{self.doc_file}' "
                     f"(size={len(source_task_list)}) to data key '{self.data_key}'.")
            except Exception as e:
                warning(f"Failed to initialize CK refine source from '{self.doc_file}': {e}")
                source_task_list = []
        note_msg = []
        self.batch_task.sync_source_task(
            copy.deepcopy(source_task_list),
            note_msg,
            f"Original CK list in data key '{self.data_key}' changed.",
        )
        saved_refine_result = self.smanager_get_value("_CK_REFINE_RESULT", {})
        if isinstance(saved_refine_result, dict):
            self.refine_result = copy.deepcopy(saved_refine_result)
        self.batch_task.update_current_tbd()
        return super().on_init()

    def get_template_data(self):
        super_data = super().get_template_data()
        data = self.batch_task.get_template_data(
            "TOTAL_POINTS", "COMPLETED_POINTS", "LIST_CURRENT_POINTS"
        )
        super_data.update(data)
        return super_data

    def do_check(self, timeout=0, is_complete=False, refined=None, **kw):
        """Refine CK labels by requiring every original CK to be explicitly reviewed."""
        ck_pass, ck_error = super().do_check(timeout, **kw)
        if not ck_pass:
            return ck_pass, ck_error
        error_mesg = []
        if not self.batch_task.source_task_list:
            return False, {
                "error": f"No original CK labels were loaded from data key '{self.data_key}'. "
                         "Please complete the previous CK label structure stage before refining CK labels."
            }
        if refined is None:
            refined_map = {}
        elif not isinstance(refined, dict):
            return False, {
                "error": "stage_args.refined must be a JSON object like {'FG-.../FC-.../CK-...': 'refine note'}; "
                         "pass it as stage_args={'refined': {...}}." + \
                         f" But find type(refined)={type(refined)}. value={refined}"
            }
        else:
            refined_map = OrderedDict()
            for key, value in refined.items():
                if key is None:
                    continue
                ck = str(key).strip()
                if ck:
                    refined_map[ck] = value

        unknown_tasks = [key for key in refined_map if key not in self.batch_task.source_task_list]
        if unknown_tasks:
            error_mesg.extend([
                "The following refined CK labels are not in the original list of labels. Please ensure that you are refining the correct labels:",
                *unknown_tasks
            ])

        current_batch = set(self.batch_task.tbd_task_list)
        out_of_batch_tasks = [
            key for key in refined_map
            if key in self.batch_task.source_task_list and key not in current_batch
        ]
        if out_of_batch_tasks and current_batch:
            error_mesg.extend([
                "The following refined CK labels are valid, but they are not in the current batch. Please refine the current batch first:",
                *out_of_batch_tasks
            ])

        if unknown_tasks or out_of_batch_tasks:
            if self.batch_task.tbd_task_list:
                error_mesg.append(f"Current batch CK labels: {', '.join(self.batch_task.tbd_task_list)}")
            return False, {"error": error_mesg}

        valid_tasks = [
            key for key in refined_map
            if key in current_batch
        ]
        self.batch_task.update_current_tbd()
        if len(valid_tasks) < 1 and self.batch_task.tbd_task_list:
            error_mesg.append(
                "No valid CK labels were refined in the current batch (pass a CK mapping in stage_args.refined). "
                f"Please refine at least one of these CK labels: {', '.join(self.batch_task.tbd_task_list)}."
            )
            return False, {"error": error_mesg}

        for ck in valid_tasks:
            self.refine_result[ck] = refined_map[ck]
        self.smanager_set_value(
            "_CK_REFINE_RESULT",
            copy.deepcopy(self.refine_result),
            persist=True,
        )

        completed_tasks = [ck for ck in self.batch_task.gen_task_list if ck in self.batch_task.source_task_list]
        for ck in valid_tasks:
            if ck not in completed_tasks:
                completed_tasks.append(ck)
        self.batch_task.sync_gen_task(completed_tasks, error_mesg, f"Refined CKs changed.")
        ck_pass, ck_error = self.batch_task.do_complete(error_mesg, is_complete,
                                                        f"in Origin",
                                                        f"in Newly Refined",
                                                        " Please refine and mask the CKs by the task needs.")
        if ck_pass and is_complete:
            self.smanager_set_value(self.data_key, self.data_val)
        return ck_pass, ck_error


# ---------------------------------------------------------------------------
# Checker - batch test case refinement
# ---------------------------------------------------------------------------

class UnityChipCheckerRefineTestCases(Checker):
    accepted_stage_args = ("refined",)

    def __init__(self,
                 doc_func_check,
                 test_dir=None,
                 ignore_tc_prefix="",
                 batch_size=10,
                 data_key=None,
                 ignore_ck_prefix="",
                 **extra_kwargs):
        super().__init__()
        self.doc_func_check = doc_func_check
        self.test_dir = test_dir
        self.ignore_tc_prefix = ignore_tc_prefix
        self.ignore_ck_prefix = _normalize_checkpoint_prefixes(ignore_ck_prefix)
        self.batch_size = batch_size
        self.data_key = data_key
        self.refine_result = OrderedDict()
        self.cached_ck_file_blocks = OrderedDict()
        self.ck_test_cases_map = OrderedDict()
        self.unresolved_mark_function = []
        self.total_test_cases_count = -1
        self._refine_result_key = "_TC_REFINE_RESULT"
        self.batch_task = BatchTask("CK", self)

    def _load_doc_cks(self, min_count=1):
        doc_path = self.get_path(self.doc_func_check)
        if not os.path.exists(doc_path):
            raise FileNotFoundError(
                f"Function and check documentation file {self.doc_func_check} does not exist in workspace."
            )
        checkpoints, file_blocks = get_doc_marks(
            doc_path,
            leaf_node="CK",
            mini_leaf_count=min_count,
            return_line_block=True,
        )
        checkpoints = [
            checkpoint
            for checkpoint in checkpoints
            if not any(
                checkpoint.startswith(prefix) for prefix in self.ignore_ck_prefix
            )
        ]
        if min_count > 0 and len(checkpoints) < min_count:
            raise ValueError(
                "No in-scope CK remains after applying ignore_ck_prefix."
            )
        return checkpoints, file_blocks

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
        saved_refine_result = {}
        if self.stage_manager is not None:
            saved_refine_result = self.smanager_get_value(self._refine_result_key, {})
        if isinstance(saved_refine_result, dict):
            self.refine_result = OrderedDict(saved_refine_result)
        try:
            current_doc_ck_list, self.cached_ck_file_blocks = self._load_doc_cks(min_count=0)
            self._sync_source_from_doc(current_doc_ck_list)
            if self.test_dir and os.path.exists(self.get_path(self.test_dir)):
                self.ck_test_cases_map = self.get_ck_test_cases_info(current_doc_ck_list)
        except Exception as e:
            warning(f"Failed to initialize test-case refine context: {e}")
        return super().on_init()

    def _build_current_ck_infos(self, ck_list):
        ck_infos = []
        for ck in ck_list:
            ck_infos.append(OrderedDict({
                "CK": ck,
                "doc_block": self.cached_ck_file_blocks.get(ck, []),
                "related_test_cases": self.ck_test_cases_map.get(ck, []),
            }))
        return ck_infos

    def get_template_data(self):
        data = self.batch_task.get_template_data("TOTAL_CKS", "COMPLETED_CKS", "LIST_CURRENT_CKS")
        data["LIST_CURRENT_CKS"] = self._build_current_ck_infos(data["LIST_CURRENT_CKS"])
        data["TOTAL_TCS"] = self.total_test_cases_count if self.total_test_cases_count >= 0 else "-"
        if self.unresolved_mark_function:
            data["UNRESOLVED_MARK_FUNCTION"] = self.unresolved_mark_function
        return data

    def get_ck_test_cases_info(self, doc_ck_list=None):
        """
        Statically collect test cases related to each CK from test_dir.

        Returns:
            OrderedDict: {"FG-X/FC-Y/CK-Z": ["tests/test_x.py:12-20::test_case"]}
        """
        if doc_ck_list is None:
            doc_ck_list, _ = self._load_doc_cks(min_count=0)
        test_dir_full_path = self.get_path(self.test_dir)
        if not os.path.exists(test_dir_full_path):
            raise FileNotFoundError(f"test directory '{self.test_dir}' does not exist in workspace.")

        def literal_str(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            return None

        def literal_str_list(node):
            value = literal_str(node)
            if value is not None:
                return [value]
            if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                values = []
                for element in node.elts:
                    element_value = literal_str(element)
                    if element_value is None:
                        return []
                    values.append(element_value)
                return values
            return []

        def split_ck_key(ck_key):
            parts = ck_key.split("/")
            ck_idx = None
            for i in range(len(parts) - 1, -1, -1):
                if parts[i].startswith("CK-"):
                    ck_idx = i
                    break
            if ck_idx is None:
                return None, None, None
            fc_idx = None
            for i in range(ck_idx - 1, -1, -1):
                if parts[i].startswith("FC-"):
                    fc_idx = i
                    break
            fg_idx = None
            if fc_idx is not None:
                for i in range(fc_idx - 1, -1, -1):
                    if parts[i].startswith("FG-"):
                        fg_idx = i
                        break
            fg_name = parts[fg_idx] if fg_idx is not None else None
            fc_name = parts[fc_idx] if fc_idx is not None else None
            ck_name = parts[ck_idx]
            return fg_name, fc_name, ck_name

        def extract_fg_from_receiver(node):
            for sub_node in ast.walk(node):
                if not isinstance(sub_node, ast.Subscript):
                    continue
                slice_node = sub_node.slice
                if isinstance(slice_node, ast.Index):
                    slice_node = slice_node.value
                value = literal_str(slice_node)
                if value and value.startswith("FG-"):
                    return value
            return None

        def extract_keyword(call, names):
            for keyword in call.keywords:
                if keyword.arg in names:
                    return keyword.value
            return None

        def references_enclosing_test(node, expected_name):
            if isinstance(node, ast.Name):
                return node.id == expected_name
            if isinstance(node, ast.Attribute):
                return node.attr == expected_name
            if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                return any(
                    references_enclosing_test(element, expected_name)
                    for element in node.elts
                )
            return False

        def is_test_file(path):
            name = os.path.basename(path)
            return name.startswith("test_") and name.endswith(".py") or name.endswith("_test.py")

        def iter_test_functions(tree):
            class TestFunctionVisitor(ast.NodeVisitor):
                def __init__(self):
                    self.class_stack = []
                    self.test_functions = []

                def visit_ClassDef(self, node):
                    self.class_stack.append(node.name)
                    for body_node in node.body:
                        self.visit(body_node)
                    self.class_stack.pop()

                def visit_FunctionDef(self, node):
                    if node.name.startswith("test_"):
                        qualname = "::".join(self.class_stack + [node.name])
                        self.test_functions.append((node, qualname))

                visit_AsyncFunctionDef = visit_FunctionDef

            visitor = TestFunctionVisitor()
            visitor.visit(tree)
            return visitor.test_functions

        ck_test_cases_map = OrderedDict((ck, []) for ck in doc_ck_list)
        fc_ck_index = {}
        fg_fc_ck_index = {}
        for ck_key in doc_ck_list:
            fg_name, fc_name, ck_name = split_ck_key(ck_key)
            if fc_name and ck_name:
                fc_ck_index.setdefault((fc_name, ck_name), []).append(ck_key)
            if fg_name and fc_name and ck_name:
                fg_fc_ck_index.setdefault((fg_name, fc_name, ck_name), []).append(ck_key)

        unresolved_mark_function = []
        total_test_cases_count = 0
        test_files = sorted(
            f for f in glob.glob(os.path.join(test_dir_full_path, "**", "*.py"), recursive=True)
            if is_test_file(f)
        )
        for test_file in test_files:
            rel_file = fc.rm_workspace_prefix(self.workspace, test_file)
            try:
                with open(test_file, "r", encoding="utf-8") as fr:
                    source = fr.read()
                tree = ast.parse(source, filename=rel_file)
            except SyntaxError as e:
                unresolved_mark_function.append(OrderedDict({
                    "file": rel_file,
                    "line": e.lineno,
                    "reason": f"SyntaxError: {e.msg}",
                }))
                continue
            except Exception as e:
                unresolved_mark_function.append(OrderedDict({
                    "file": rel_file,
                    "line": None,
                    "reason": f"Failed to parse file: {e}",
                }))
                continue

            for func_node, qualname in iter_test_functions(tree):
                test_func_name = qualname.split("::")[-1]
                if _test_name_matches_prefixes(
                    test_func_name,
                    _normalize_test_prefixes(self.ignore_tc_prefix),
                ):
                    continue
                total_test_cases_count += 1
                line_to = getattr(func_node, "end_lineno", func_node.lineno)
                test_case = f"{rel_file}:{func_node.lineno}-{line_to}::{qualname}"
                for call in ast.walk(func_node):
                    if not (isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and call.func.attr == "mark_function"):
                        continue
                    fc_arg = call.args[0] if len(call.args) >= 1 else extract_keyword(call, ["fc_name"])
                    test_arg = call.args[1] if len(call.args) >= 2 else extract_keyword(
                        call,
                        [
                            "test_function_or_list", "test_function", "test_functions",
                            "test_func", "test_funcs", "func", "functions",
                        ],
                    )
                    ck_arg = call.args[2] if len(call.args) >= 3 else extract_keyword(
                        call,
                        [
                            "ck_name", "ck_names", "ck_list", "ck_points",
                            "check_point_names", "check_points", "checks",
                            "bins", "checkpoints",
                        ],
                    )
                    fc_name = literal_str(fc_arg) if fc_arg is not None else None
                    ck_names = literal_str_list(ck_arg) if ck_arg is not None else []
                    fg_name = extract_fg_from_receiver(call.func.value)
                    if not references_enclosing_test(test_arg, test_func_name):
                        unresolved_mark_function.append(OrderedDict({
                            "test_case": test_case,
                            "line": getattr(call, "lineno", func_node.lineno),
                            "fg": fg_name,
                            "fc": fc_name,
                            "cks": ck_names,
                            "reason": "mark_function does not statically reference the enclosing test function.",
                        }))
                        continue
                    if not fc_name or not fc_name.startswith("FC-") or not ck_names:
                        unresolved_mark_function.append(OrderedDict({
                            "test_case": test_case,
                            "line": getattr(call, "lineno", func_node.lineno),
                            "fg": fg_name,
                            "fc": fc_name,
                            "cks": ck_names,
                            "reason": "Cannot statically parse FC/CK names from mark_function call.",
                        }))
                        continue
                    for ck_name in ck_names:
                        if not ck_name.startswith("CK-"):
                            unresolved_mark_function.append(OrderedDict({
                                "test_case": test_case,
                                "line": getattr(call, "lineno", func_node.lineno),
                                "fg": fg_name,
                                "fc": fc_name,
                                "ck": ck_name,
                                "reason": "Parsed checkpoint name does not start with CK-.",
                            }))
                            continue
                        matches = fc_ck_index.get((fc_name, ck_name), [])
                        matched_ck = None
                        reason = "No matching CK in documentation."
                        if fg_name:
                            exact_matches = fg_fc_ck_index.get((fg_name, fc_name, ck_name), [])
                            matched_ck = exact_matches[0] if len(exact_matches) == 1 else None
                            if matched_ck is None and matches:
                                reason = (
                                    "FG does not match the documented FG for this FC/CK, "
                                    "or the full FG/FC/CK path is ambiguous."
                                )
                        elif len(matches) == 1:
                            matched_ck = matches[0]
                        elif len(matches) > 1:
                            reason = "Ambiguous CK in documentation; FG is required to disambiguate."
                        if matched_ck is None:
                            unresolved_mark_function.append(OrderedDict({
                                "test_case": test_case,
                                "line": getattr(call, "lineno", func_node.lineno),
                                "fg": fg_name,
                                "fc": fc_name,
                                "ck": ck_name,
                                "reason": reason,
                            }))
                            continue
                        if test_case not in ck_test_cases_map.setdefault(matched_ck, []):
                            ck_test_cases_map[matched_ck].append(test_case)

        self.ck_test_cases_map = ck_test_cases_map
        self.unresolved_mark_function = unresolved_mark_function
        self.total_test_cases_count = total_test_cases_count
        return ck_test_cases_map

    def do_check(self, timeout=0, is_complete=False, refined=None, **kw):
        """Refine test cases in batches and check their implementation status."""
        try:
            current_doc_ck_list, self.cached_ck_file_blocks = self._load_doc_cks(min_count=1)
        except Exception as e:
            return False, {
                "error": f"Failed to parse the function and check documentation file {self.doc_func_check}: {str(e)}. "
                         "Review the file format and ensure it contains valid <FG-*>, <FC-*>, and <CK-*> labels."
            }
        try:
            self.ck_test_cases_map = self.get_ck_test_cases_info(current_doc_ck_list)
        except Exception as e:
            return False, {"error": str(e)}

        note_msg = []
        self._sync_source_from_doc(current_doc_ck_list, note_msg)
        completed_tasks = [
            ck for ck in self.batch_task.gen_task_list
            if ck in current_doc_ck_list
        ]
        for ck in self.refine_result.keys():
            if ck in current_doc_ck_list and ck not in completed_tasks:
                completed_tasks.append(ck)
        self.batch_task.sync_gen_task(
            completed_tasks,
            note_msg,
            "Refined test-case CK records changed.",
        )
        self.batch_task.update_current_tbd()

        current_batch = list(self.batch_task.tbd_task_list)
        tool_name = "Complete" if is_complete else "Check"

        def refined_call_guidance(candidate_cks=None):
            """Build an executable refined argument example for error messages."""
            has_current_batch = bool(current_batch)
            candidates = list(candidate_cks or current_batch or current_doc_ck_list)
            if candidates:
                example_ck = candidates[0]
                example_note = (
                    "Reviewed the related test cases and updated coverage for this checkpoint."
                )
                object_example, string_example = format_stage_args_examples(
                    tool_name,
                    {"refined": {example_ck: example_note}},
                )
                guidance = (
                    f"Call the {tool_name} tool with the stage_args JSON object. "
                    "For this stage, stage_args.refined maps each full CK path to a review/update note. "
                    f"Object example: {object_example} "
                    f"JSON-string fallback: {string_example} "
                )
                if has_current_batch or candidate_cks:
                    guidance += (
                        f"Allowed current-batch CK labels: {', '.join(candidates)}. "
                        "Do not submit CK labels outside the current batch. "
                    )
                else:
                    guidance += "There are currently no pending CK labels in the batch. "
                return guidance + (
                    "Pass stage_args directly as shown; do not use a top-level refined field, "
                    "or nest stage_args under args or parameters."
                )
            object_example, string_example = format_stage_args_examples(
                tool_name,
                {"refined": {"FG-.../FC-.../CK-...": "review note"}},
            )
            return (
                f"Call the {tool_name} tool with {object_example}. "
                f"If nested object serialization fails, use {string_example}."
            )

        if refined is None:
            refined_map = OrderedDict()
        elif not isinstance(refined, dict):
            return False, {
                "error": (
                    "stage_args.refined must be a JSON object whose keys are CK labels and whose values "
                    "are review/update notes. "
                    f"{refined_call_guidance()} "
                    f"Received type(refined)={type(refined)}; value={refined}"
                )
            }
        else:
            refined_map = OrderedDict()
            for key, value in refined.items():
                if key is None:
                    continue
                ck = str(key).strip()
                if ck:
                    refined_map[ck] = value

        error_mesg = []
        unknown_tasks = [key for key in refined_map if key not in current_doc_ck_list]
        if unknown_tasks:
            error_mesg.extend([
                "The following refined CK labels are not in the current function/check document. "
                "Please ensure that you are refining the correct labels:",
                *unknown_tasks,
            ])

        current_batch_set = set(current_batch)
        out_of_batch_tasks = [
            key for key in refined_map
            if key in current_doc_ck_list and key not in current_batch_set
        ]
        if out_of_batch_tasks and current_batch_set:
            error_mesg.extend([
                "The following refined CK labels are valid, but they are not in the current batch. "
                "Please refine the current batch first:",
                *out_of_batch_tasks,
            ])

        if unknown_tasks or (out_of_batch_tasks and current_batch_set):
            error_mesg.append(refined_call_guidance())
            if self.batch_task.tbd_task_list:
                error_mesg.append(f"Current batch CK labels: {', '.join(self.batch_task.tbd_task_list)}")
                error_mesg.append({"current_batch": self._build_current_ck_infos(self.batch_task.tbd_task_list)})
            return False, {"error": error_mesg}

        valid_tasks = [
            key for key in refined_map
            if key in current_batch_set
        ]
        remaining_current_batch = [
            ck for ck in self.batch_task.tbd_task_list
            if ck not in completed_tasks
        ]
        if len(valid_tasks) < 1 and remaining_current_batch:
            return False, {
                "error": [
                    "No valid CK labels were refined in the current batch. "
                    f"Please refine at least one of these CK labels: {', '.join(remaining_current_batch)}.",
                    {"current_batch": self._build_current_ck_infos(remaining_current_batch)},
                    refined_call_guidance(remaining_current_batch),
                ]
            }

        for ck in valid_tasks:
            self.refine_result[ck] = refined_map[ck]
            if ck not in completed_tasks:
                completed_tasks.append(ck)

        self.batch_task.sync_gen_task(
            completed_tasks,
            note_msg,
            "Refined test-case CK records changed.",
        )

        if self.stage_manager is not None:
            self.smanager_set_value(
                self._refine_result_key,
                copy.deepcopy(self.refine_result),
                persist=not bool(self.data_key),
            )
            if self.data_key:
                self.smanager_set_value(self.data_key, OrderedDict({
                    "source_ck_list": current_doc_ck_list,
                    "refine_result": copy.deepcopy(self.refine_result),
                    "ck_test_cases_map": copy.deepcopy(self.ck_test_cases_map),
                    "unresolved_mark_function": copy.deepcopy(self.unresolved_mark_function),
                    "total_test_cases_count": self.total_test_cases_count,
                }), persist=True)

        ck_pass, ck_error = self.batch_task.do_complete(
            note_msg,
            is_complete,
            f"in file: {self.doc_func_check}",
            f"in dir: {self.test_dir}",
            " Please review and refine the related test cases, then confirm with stage_args={refined: {CK: note}}.",
        )
        if isinstance(ck_error, dict):
            if self.batch_task.tbd_task_list:
                ck_error["current_batch"] = self._build_current_ck_infos(self.batch_task.tbd_task_list)
            if self.unresolved_mark_function:
                ck_error["unresolved_mark_function"] = self.unresolved_mark_function
        return ck_pass, ck_error

