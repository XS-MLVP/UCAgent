# -*- coding: utf-8 -*-
"""Unity test checker for UCAgent verification."""

import re
from typing import Tuple
import ucagent.util.functions as fc
from ucagent.util.config import Config
from ucagent.util.log import info, warning
from ucagent.tools.testops import RunUnityChipTest
import os
import glob
import traceback
import copy
import inspect
import ast

from ucagent.checkers.base import Checker, UnityChipBatchTask, format_stage_args_examples
from ucagent.checkers.toffee_report import check_report, check_line_coverage
from collections import OrderedDict

DEFAULT_RESERVED_TEST_FUNCTION_PREFIXES = (
    "test_api_",
    "test_static_",
    "test_random_",
)


def _set_checker_failure(result, message):
    """Attach one Checker failure while preserving its explicit diagnostic contract."""

    if (
        isinstance(message, dict)
        and {"error_code", "error", "next_action"}.issubset(message)
    ):
        result["diagnostic"] = copy.deepcopy(message)
        result["error"] = message["error"]
    else:
        result["error"] = message
    return result


def _report_failure_message(
    message,
    report,
    *,
    stdout="",
    stderr="",
    include_stdout=False,
    include_stderr=False,
):
    """Wrap a Checker failure with its test report and optional process output."""

    result = _set_checker_failure({"REPORT": report}, message)
    if include_stdout:
        result["STDOUT"] = stdout
    if include_stderr:
        result["STDERR"] = stderr
    if "Signal bind error" in stderr:
        result["WARNING"] = (
            "The DUT signals are not handled properly by toffee Bundle, you should "
            "fix this issue first."
        )
    return result


def _normalize_test_prefixes(prefixes, field_name="test function prefix"):
    if prefixes in (None, ""):
        return []
    if isinstance(prefixes, str):
        values = [prefixes]
    elif isinstance(prefixes, (list, tuple)):
        values = list(prefixes)
    else:
        raise TypeError(
            f"{field_name} must be a string or a list/tuple of strings."
        )
    normalized = []
    for prefix in values:
        if not isinstance(prefix, str):
            raise TypeError(
                f"{field_name} entries must be strings."
            )
        prefix = prefix.strip()
        if prefix and prefix not in normalized:
            normalized.append(prefix)
    return normalized


def _normalize_checkpoint_prefixes(prefixes):
    if prefixes in (None, ""):
        return []
    if isinstance(prefixes, str):
        values = [prefixes]
    elif isinstance(prefixes, (list, tuple)):
        values = list(prefixes)
    else:
        raise TypeError(
            "ignore_ck_prefix must be a string or a list/tuple of strings."
        )
    normalized = []
    for prefix in values:
        if not isinstance(prefix, str):
            raise TypeError("ignore_ck_prefix entries must be strings.")
        prefix = prefix.strip()
        if prefix and prefix not in normalized:
            normalized.append(prefix)
    return normalized


def _test_name_matches_prefixes(test_name, prefixes):
    return any(test_name.startswith(prefix) for prefix in prefixes)


def _test_name_has_required_prefix(test_name, prefixes):
    """Require both a stage prefix and a nonempty descriptive suffix."""
    return any(
        test_name.startswith(prefix) and len(test_name) > len(prefix)
        for prefix in prefixes
    )


def _test_function_contract_failure(error_cases, retry_tool="Check"):
    """Return every deterministic test-function contract violation."""
    issues = list(error_cases)
    diagnostic = OrderedDict({
        "error_code": "TEST_FUNCTION_CONTRACT_VIOLATION",
        "error": (
            f"[Test Function Contract Violation] Found {len(issues)} test-function "
            "contract issue(s). Every issue is listed in observed.issues."
        ),
        "observed": OrderedDict({
            "issue_count": len(issues),
            "issues": issues,
        }),
        "expected": (
            "Every matched pytest function must satisfy the configured file location, "
            "name prefix, fixture argument order, and minimum per-file test count."
        ),
        "next_action": (
            "Fix every item in observed.issues without weakening test assertions, then "
            f"call `{retry_tool}` again."
        ),
        "issue_count": len(issues),
    })
    return {
        "error": diagnostic["error"],
        "diagnostic": diagnostic,
        "details": issues,
    }


def _test_function_contract_report(error_cases, retry_tool="Check"):
    """Represent a naming failure in the base pytest report contract."""
    return {
        "run_test_success": False,
        "test_function_contract": _test_function_contract_failure(
            error_cases,
            retry_tool=retry_tool,
        ),
    }


def _iter_test_function_defs(test_file):
    """Read pytest function definitions without importing or executing a module."""
    try:
        with open(test_file, "r", encoding="utf-8") as source_file:
            tree = ast.parse(source_file.read(), filename=test_file)
    except (OSError, UnicodeError, SyntaxError) as exc:
        return [], exc

    class _Visitor(ast.NodeVisitor):
        def __init__(self):
            self.class_stack = []
            self.functions = []

        def visit_ClassDef(self, node):
            if not node.name.startswith("Test"):
                return
            self.class_stack.append(node.name)
            self.generic_visit(node)
            self.class_stack.pop()

        def _visit_function(self, node):
            if node.name.startswith("test_"):
                self.functions.append({
                    "name": node.name,
                    "qualname": "::".join(self.class_stack + [node.name]),
                    "line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "args": [
                        arg.arg for arg in (
                            list(node.args.posonlyargs) + list(node.args.args)
                        )
                    ],
                })
            # Pytest does not collect nested functions. Do not descend into a
            # test body and report helper functions as stage test cases.

        visit_FunctionDef = _visit_function
        visit_AsyncFunctionDef = _visit_function

    visitor = _Visitor()
    visitor.visit(tree)
    return visitor.functions, None


def _test_function_name_issues_for_files(
    workspace,
    test_files,
    prefixes,
    ignored_prefixes=None,
    forbidden_prefixes=None,
    contract_name=None,
):
    """Validate test names in files using a side-effect-free source scan."""
    prefixes = _normalize_test_prefixes(prefixes, field_name="test_func_prefix")
    ignored_prefixes = _normalize_test_prefixes(
        ignored_prefixes, field_name="ignore_tc_prefix"
    )
    forbidden_prefixes = _normalize_test_prefixes(
        forbidden_prefixes, field_name="forbidden_test_func_prefix"
    )
    if not prefixes and not forbidden_prefixes:
        return []
    issues = []
    contract_context = (
        f" under the '{contract_name}' contract" if contract_name else ""
    )
    for test_file in test_files:
        real_file = (
            test_file
            if os.path.isabs(test_file)
            else os.path.join(workspace, test_file)
        )
        definitions, parse_error = _iter_test_function_defs(real_file)
        if parse_error is not None:
            line = getattr(parse_error, "lineno", "?")
            issues.append(
                f"{test_file}:{line}-{line}: unable to inspect test function names: {parse_error}"
            )
            continue
        for definition in definitions:
            name = definition["name"]
            if _test_name_matches_prefixes(name, ignored_prefixes):
                continue
            reserved_prefix = next(
                (prefix for prefix in forbidden_prefixes if name.startswith(prefix)),
                None,
            )
            allowed = bool(prefixes and _test_name_has_required_prefix(name, prefixes))
            if reserved_prefix:
                issues.append(
                    f"{test_file}:{definition['line']}-{definition['line']}: The "
                    f"'{name}' test function uses reserved prefix '{reserved_prefix}'"
                    f"{contract_context}. Put it in the dedicated stage/file and use "
                    "that stage's complete prefix, or rename this ordinary test so it "
                    "does not use a reserved prefix."
                )
                continue
            if allowed:
                continue
            if prefixes and not allowed:
                issues.append(
                    f"{test_file}:{definition['line']}-{definition['line']}: The "
                    f"'{name}' test function's name{contract_context} must start with one of: "
                    f"{', '.join(prefixes)}, followed by a nonempty descriptive suffix."
                )
    return issues


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


class UnityChipCheckerLabelStructure(Checker):
    def __init__(self, doc_file, leaf_node, min_count=1, must_have_prefix="FG-API", data_key=None, need_human_check=False, **kw):
        """
        Initialize the checker with the documentation file, the specific label (leaf node) to check,
        and the minimum count required for that label.
        """
        super().__init__()
        self.doc_file = doc_file
        self.leaf_node = leaf_node
        self.min_count = min_count
        self.must_have_prefix = must_have_prefix
        self.data_key = data_key
        self.data_val = []
        self.need_save_data = True if data_key else False
        self.leaf_count = None
        self.set_human_check_needed(need_human_check)

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Check the label structure in the documentation file."""
        self.leaf_count = None
        msg = f"{self.__class__.__name__} check {self.leaf_node} pass."
        data = []
        data_fmap = {}
        for dfile in fc.find_files_by_pattern(self.workspace, self.doc_file): # Suport multiple doc files
            if not os.path.exists(self.get_path(dfile)):
                return False, {"error": f"Documentation file '{dfile}' does not exist."}
            try:
                data_sub = fc.get_unity_chip_doc_marks(self.get_path(dfile), self.leaf_node, self.min_count)
            except Exception as e:
                error_details = str(e)
                warning(f"Error occurred while checking {dfile}: {error_details}")
                warning(traceback.format_exc())
                emsg = [f"Documentation parsing failed for file '{dfile}': {error_details}."]
                if "\\n" in error_details:
                    emsg.append("Literal '\\n' characters detected - use actual line breaks instead of escaped characters")
                emsg.append({"check_list": [
                    "Malformed tags: Ensure proper format. e.g., <FG-NAME>, <FC-NAME>, <CK-NAME>",
                    *fc.description_func_doc(),
                    "Invalid characters: Use only alphanumeric and hyphen in tag names",
                    "Missing tag closure: All tags must be properly closed",
                    "Encoding issues: Ensure file is saved in UTF-8 format",
                ]})
                return False, {"error": emsg}
            for d in data_sub:
                if d in data_fmap:
                    return False, {"error": f"Duplicate {self.leaf_node} '{d}' found in documentation files: '{data_fmap[d]}' and '{dfile}'." + \
                                            f"All labels must be unique across documentation files ({self.doc_file})."}
                data.append(d)
                data_fmap[d] = dfile
        if self.must_have_prefix:
            find_prefix = False
            for mark in data:
                if mark.startswith(self.must_have_prefix):
                    find_prefix = True
            if not find_prefix:
                return False, {"error": f"In the document ({self.doc_file}), it must have group/."}
        self.data_val = copy.deepcopy(data)
        if self.data_key and self.need_save_data:
            self.smanager_set_value(self.data_key, self.data_val)
            info(f"Cache {self.leaf_node} marks(size={len(data)}) to data key '{self.data_key}'.")
        self.leaf_count = len(data)
        return True, {"message": msg, f"{self.leaf_node}_count": len(data)}

    def get_template_data(self):
        return {
            f"COUNT_{self.leaf_node}": f"{self.leaf_count}" if self.leaf_count else "-"
        }


class UnityChipCheckerLabelStructureRefine(UnityChipCheckerLabelStructure):
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
        self.batch_task = UnityChipBatchTask("CK", self)

    def on_init(self):
        source_task_list = self.smanager_get_value(self.data_key, [])
        if not isinstance(source_task_list, list) or not source_task_list:
            try:
                source_task_list = fc.get_unity_chip_doc_marks(
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


class UnityChipCheckerDutCreation(Checker):
    def __init__(self, target_file, **kw):
        super().__init__()
        self.target_file = target_file
        self.update_dut_name(kw["cfg"])
        ucagent_msg = f"You need use:\n`if ucagent.is_imp_test_template():\n" + \
                      f"    return ucagent.get_fake_dut(DUT{self.dut_name})`\n in 'create_dut' function."
        self.source_code_need = {
            "get_coverage_data_path": (f"The 'create_dut' function in '{self.target_file}' must call 'get_coverage_data_path(request, new_path=True)' to get a new coverage file path.", fc.tips_of_get_coverage_data_path),
            "ucagent.is_imp_test_template": (ucagent_msg, None),
            "ucagent.get_fake_dut":(ucagent_msg, None)
        }

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Check the DUT creation function for correctness."""
        if not os.path.exists(self.get_path(self.target_file)):
            return False, {"error": f"file '{self.target_file}' does not exist."}
        func_list = fc.get_target_from_file(self.get_path(self.target_file), "create_dut",
                                            ex_python_path=self.workspace,
                                            dtype="FUNC")
        if not func_list:
            return False, {"error": f"No 'create_dut' functions found in '{self.target_file}'."}
        if len(func_list) != 1:
            return False, {"error": f"Multiple 'create_dut' functions found in '{self.target_file}'. Expected only one."}
        cdut_func = func_list[0]
        args = fc.get_func_arg_list(cdut_func)
        # check args
        if len(args) != 1 or args[0] != "request":
            return False, {"error": f"The 'create_dut' fixture has only one arg named 'request', but got ({', '.join(args)})."}
        dut = func_list[0](None)
        for need_func in ["Step", "StepRis"]:
            assert hasattr(dut, need_func), f"The 'create_dut' function in '{self.target_file}' did not return a valid DUT instance with '{need_func}' method."
        # check 'get_coverage_data_path'
        func_source = inspect.getsource(cdut_func)
        for k, (v, f) in self.source_code_need.items():
            message = v
            if f:
                message += f" {f(self.dut_name)}"
            if k not in func_source:
                return False, {"error":  message}
        # Additional checks can be implemented here
        return True, {"message": f"{self.__class__.__name__} check for {self.target_file} passed."}


class UnityChipCheckerMockComponent(Checker):
    def __init__(self, target_file, min_mock=1, **kw):
        super().__init__()
        self.target_file = target_file
        self.min_mock = min_mock

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Check the Mock component implementation for correctness."""
        class_count = 0
        mock_file_list = fc.find_files_by_pattern(self.workspace, self.target_file)
        if not mock_file_list:
            return False, {
                "error": (
                    f"Mock component file pattern '{self.target_file}' does not exist "
                    "or matched no files in the workspace. Create the expected Mock "
                    "component file, or correct the configured workspace-relative pattern."
                ),
            }
        for mock_file in mock_file_list:
            ret, msg = self.do_check_one_file(mock_file)
            if ret == False:
                return False, msg
            class_count += ret
        if class_count < self.min_mock:
            return False, {
                "error": f"Insufficient Mock component coverage: {class_count} Mock classes found, minimum required is {self.min_mock}. " + \
                         f"You need to define Mock components like: 'class Mock<COMPONENT_NAME>:'. in files: {self.target_file}. " + \
                         f"Review your task details and ensure that the Mock components are defined correctly in the target files.",
            }
        return True, {"message": f"{self.__class__.__name__} check for {self.target_file} ({len(mock_file_list)} files) passed."}

    def do_check_one_file(self, mock_file):
        if not os.path.exists(self.get_path(mock_file)):
            return False, {"error": f"Mock component file '{mock_file}' does not exist. " + \
                           f"You need to define Mock components like: 'class Mock<COMPONENT_NAME>:' in the target file: {mock_file}. "}
        class_list = fc.get_target_from_file(self.get_path(mock_file), "Mock*",
                                            ex_python_path=self.workspace,
                                            dtype="CLASS")
        if len(class_list) < 1:
            return False, {
                "error": f"No Mock component class found in file: {mock_file}, You need to define Mock components like: 'class Mock<COMPONENT_NAME>:' in the file: {mock_file}.  ",
            }
        # check on_clock_edge
        for cls in class_list:
            if not hasattr(cls, "on_clock_edge"):
                return False, {
                    "error": f"The Mock class '{cls.__name__}' in file: {mock_file} is missing the required method 'on_clock_edge(self, cycles)'. Please implement this method to handle clock edge events."
                }
            method = getattr(cls, "on_clock_edge")
            args = fc.get_func_arg_list(method)
            if len(args) != 2 or args[0] != "self" or args[1] != "cycles":
                return False, {
                    "error": f"The 'on_clock_edge' method in Mock class '{cls.__name__}' in file {mock_file} must have exactly two arguments: 'self' and 'cycles', but got ({', '.join(args)})."
                }
        info(f"find {len(class_list)} Mock classes in file: {mock_file}.")
        return len(class_list), {"message": f"{self.__class__.__name__} check for {mock_file} passed."}


class UnityChipCheckerBundleWrapper(Checker):
    def __init__(self, target_file, min_bundles=1, **kw):
        super().__init__()
        self.target_file = target_file
        self.min_bundles = min_bundles

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Check the Bundle wrapper implementation for correctness."""
        if not os.path.exists(self.get_path(self.target_file)):
            return False, {"error": f"Bundle wrapper file '{self.target_file}' does not exist." + \
                           f"You need to define Bundle wrappers like: 'class <Name>(Bundle):' in the target file: {self.target_file}. "}
        bundle_list = fc.get_target_from_file(self.get_path(self.target_file), "*",
                                              ex_python_path=self.workspace,
                                              dtype="CLASS")
        for icls in bundle_list[:]:
            bases = [base.__name__ for base in icls.__bases__]
            if "Bundle" not in bases:
                bundle_list.remove(icls)
        if len(bundle_list) < self.min_bundles:
            return False, {
                "error": f"Insufficient Bundle wrapper coverage: {len(bundle_list)} Bundle classes found, minimum required is {self.min_bundles}. " +\
                         f"You need to define Bundle wrappers like: 'class <Name>(Bundle):' in the target file: {self.target_file}. " + \
                         f"Please refer to the documentation for more details."
            }
        return True, {"message": f"{self.__class__.__name__} check for {self.target_file} passed."}


class UnityChipCheckerBaseFixture(Checker):
    def __init__(self, target_file,
                 fixture_name,
                 first_arg=None,
                 last_arg=None,
                 scope="function",
                 min_count=1,
                 fix_count=-1,
                 **kw):
        super().__init__()
        self.target_file = target_file
        self.fixture_name = fixture_name
        self.first_arg = first_arg
        self.last_arg = last_arg
        self.scope = scope
        self.min_count = max(1, min_count)
        self.fix_count = fix_count
        self.source_code_need = {}
        self.source_code_cb = None

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Check the fixture implementation for correctness."""
        if not os.path.exists(self.get_path(self.target_file)):
            return False, {"error": f"fixture file '{self.target_file}' does not exist."}
        fixture_func_list = fc.get_target_from_file(self.get_path(self.target_file), self.fixture_name,
                                             ex_python_path=self.workspace,
                                             dtype="FUNC")
        for fx_func in fixture_func_list:
            args = fc.get_func_arg_list(fx_func)
            if self.first_arg is not None and (len(args) < 1 or args[0] != self.first_arg):
                return False, {"error": f"The '{fx_func.__name__}' fixture's first arg must be '{self.first_arg}', but got ({', '.join(args)})."}
            if self.last_arg is not None and (len(args) < 1 or args[-1] != self.last_arg):
                return False, {"error": f"The '{fx_func.__name__}' fixture's last arg must be '{self.last_arg}', but got ({', '.join(args)})."}
            if not (hasattr(fx_func, '_pytestfixturefunction') or "pytest_fixture" in str(fx_func)):
                return False, {"error": f"The '{fx_func.__name__}' fixture in '{self.target_file}' is not decorated with @pytest.fixture()."}
            scope_value = fc.get_fixture_scope(fx_func)
            if isinstance(scope_value, str):
                if scope_value != self.scope:
                    return False, {"error": f"The '{fx_func.__name__}' fixture in '{self.target_file}' has invalid scope '{scope_value}'. The expected scope is '{self.scope}'."}
            func_source = inspect.getsource(fx_func)
            for k, (v, f) in self.source_code_need.items():
                message = v
                if f:
                    message += f" {f(self.dut_name)}"
                if k not in func_source:
                    info(f"[{self.__class__.__name__}]Check source code of fixture '{fx_func.__name__}' in file '{self.target_file}': missing '{k}' in source:\n{func_source}\n.")
                    return False, {"error":  message}
            if self.source_code_cb:
                ret, msg = self.source_code_cb(func_source, fx_func)
                if not ret:
                    return False, msg
        if len(fixture_func_list) < self.min_count:
            return False, {"error": f"Insufficient fixture coverage: {len(fixture_func_list)} fixtures found, minimum required is {self.min_count}. "+\
                                    f"You have defined {len(fixture_func_list)} fixtures: {', '.join([f.__name__ for f in fixture_func_list])} in file '{self.target_file}'."}
        if self.fix_count > 0 and len(fixture_func_list) != self.fix_count:
            return False, {"error": f"Incorrect fixture count: {len(fixture_func_list)} fixtures found, expected exactly {self.fix_count}. "+\
                                    f"You have defined {len(fixture_func_list)} fixtures: {', '.join([f.__name__ for f in fixture_func_list])} in file '{self.target_file}'."}
        return True, {"message": f"{self.__class__.__name__} fixture check for {self.target_file} passed."}


class UnityChipCheckerDutFixture(UnityChipCheckerBaseFixture):
    def __init__(self, target_file, min_count=1, **kw):
        super().__init__(target_file, "dut", first_arg="request", min_count=min_count, **kw)
        self.update_dut_name(kw["cfg"])
        msg = f"The 'dut' fixture in '{self.target_file}' must call 'get_coverage_data_path(request, new_path=False)' to get existed coverage file path. {fc.tips_of_get_coverage_data_path(self.dut_name)}"
        self.source_code_need = {
            "get_coverage_data_path": (msg, None)
        }
        self.source_code_cb = self._check_lifecycle

    @staticmethod
    def _call_name(node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    @staticmethod
    def _is_valid_set_func_coverage_call(call):
        positional_request = (
            len(call.args) >= 1
            and isinstance(call.args[0], ast.Name)
            and call.args[0].id == "request"
        )
        keyword_names = {keyword.arg for keyword in call.keywords}
        has_request = positional_request or "request" in keyword_names
        has_groups = len(call.args) >= 2 or "g" in keyword_names
        return has_request and has_groups

    def _check_lifecycle(self, source_code, dut_func):
        tree = ast.parse(source_code)
        fixture_node = next(
            (
                node for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == dut_func.__name__
            ),
            None,
        )
        if fixture_node is None:
            return False, {
                "error": f"Cannot parse the '{dut_func.__name__}' fixture body in "
                         f"'{self.target_file}'."
            }

        class LifecycleVisitor(ast.NodeVisitor):
            conditional_nodes = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Match)

            def __init__(self, root):
                self.root = root
                self.conditional_depth = 0
                self.yields = []
                self.func_coverage_calls = []

            def visit_FunctionDef(self, node):
                if node is self.root:
                    for statement in node.body:
                        self.visit(statement)

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Lambda(self, node):
                return

            def generic_visit(self, node):
                is_conditional = isinstance(node, self.conditional_nodes)
                if is_conditional:
                    self.conditional_depth += 1
                super().generic_visit(node)
                if is_conditional:
                    self.conditional_depth -= 1

            def visit_Yield(self, node):
                self.yields.append((node, self.conditional_depth))
                self.generic_visit(node)

            def visit_YieldFrom(self, node):
                self.yields.append((node, self.conditional_depth))
                self.generic_visit(node)

            def visit_Call(self, node):
                if UnityChipCheckerDutFixture._call_name(node.func) == "set_func_coverage":
                    self.func_coverage_calls.append((node, self.conditional_depth))
                self.generic_visit(node)

        visitor = LifecycleVisitor(fixture_node)
        visitor.visit(fixture_node)
        yield_lines = [node.lineno for node, _ in visitor.yields]
        if not yield_lines:
            return False, {"error": f"The '{dut_func.__name__}' fixture in '{self.target_file}' does not contain 'yield' statement. Pytest fixtures should yield the DUT instance for proper setup/teardown."}

        func_coverage_calls = [call for call, _ in visitor.func_coverage_calls]
        if not func_coverage_calls:
            return False, {
                "error":
                    f"The '{dut_func.__name__}' fixture in '{self.target_file}' must call "
                    "'set_func_coverage(request, func_coverage_group)' during teardown. "
                    "Calling mark_function in tests is not enough: without set_func_coverage, "
                    "Toffee reports no functional coverage groups and every test appears unmarked."
            }

        valid_func_coverage_calls = [
            (call, conditional_depth)
            for call, conditional_depth in visitor.func_coverage_calls
            if self._is_valid_set_func_coverage_call(call)
        ]
        if not valid_func_coverage_calls:
            return False, {
                "error":
                    f"The '{dut_func.__name__}' fixture in '{self.target_file}' must pass both "
                    "the pytest 'request' and the coverage group data to "
                    "'set_func_coverage(request, func_coverage_group)'."
            }

        unconditional_yield_lines = [
            node.lineno for node, conditional_depth in visitor.yields
            if conditional_depth == 0
        ]
        if not unconditional_yield_lines:
            return False, {
                "error":
                    f"The '{dut_func.__name__}' fixture in '{self.target_file}' must yield the "
                    "DUT on an unconditional fixture path; a yield nested under if/loop/match "
                    "cannot guarantee setup for every test."
            }

        first_yield_line = min(unconditional_yield_lines)
        teardown_calls = [
            call for call, conditional_depth in valid_func_coverage_calls
            if call.lineno > first_yield_line and conditional_depth == 0
        ]
        if not teardown_calls:
            return False, {
                "error":
                    f"The '{dut_func.__name__}' fixture in '{self.target_file}' must call "
                    "'set_func_coverage(request, func_coverage_group)' on an unconditional "
                    "teardown path after 'yield'. Calls before yield, inside nested functions, "
                    "or under if/loop/match branches cannot guarantee that final coverage "
                    "samples and mark_function mappings are attached to every test report."
            }
        return True, {}


class UnityChipCheckerEnvFixture(UnityChipCheckerBaseFixture):
    def __init__(self, target_file, min_count=1, **kw):
        super().__init__(target_file, "env*", first_arg="dut", min_count=min_count, **kw)


class UnityChipCheckerMockFixture(UnityChipCheckerBaseFixture):
    def __init__(self, target_file, min_count=1, **kw):
        super().__init__(target_file, "mock_dut", min_count=min_count, **kw)
        self.update_dut_name(kw["cfg"])
        ucagent_msg = f"You need use:\n`def mock_dut():\n    return ucagent.get_mock_dut_from(DUT{self.dut_name})\n` in 'mock_dut' fixture."
        self.source_code_need = {
            "ucagent.get_mock_dut_from": (ucagent_msg, None)
        }


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
        test_pass, test_msg = fc.is_run_report_pass(report, str_out, str_err)
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
        ret, msg = fc.check_has_assert_in_tc(self.workspace, report)
        if not ret:
            return ret, msg
        return True, {"message": f"{self.__class__.__name__} check passed."}


class UnityChipCheckerDutApi(Checker):
    def __init__(self, api_prefix, target_file, min_apis=1, **kw):
        super().__init__()
        self.api_prefix = api_prefix
        self.target_file = target_file
        self.min_apis = min_apis

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Check the DUT API implementation for correctness."""
        if not os.path.exists(self.get_path(self.target_file)):
            return False, {"error": f"DUT API file '{self.target_file}' does not exist."}
        func_list = fc.get_target_from_file(self.get_path(self.target_file), f"{self.api_prefix}*",
                                         ex_python_path=self.workspace,
                                         dtype="FUNC")
        failed_apis = []
        for func in func_list:
            args = fc.get_func_arg_list(func)
            if not args or len(args) < 2:
                failed_apis.append(func)
                continue
            if not args[0].startswith("env"):
                failed_apis.append(func)
            if not args[-1].startswith("max_cycles"):
                failed_apis.append(func)
        if len(failed_apis) > 0:
            return False, {
                "error": f"The following API functions in file '{self.target_file}' have invalid or missing arguments. The first arg must be 'env' and the last arg must be 'max_cycles=default_value'",
                "failed_apis": [f"{func}({', '.join(fc.get_func_arg_list(func))})" for func in failed_apis]
            }
        if len(func_list) < self.min_apis:
            return False, {
                "error": f"Insufficient DUT API coverage: {len(func_list)} API functions found, minimum required is {self.min_apis}. " + \
                         f"You need to define APIs like: 'def {self.api_prefix}<API_NAME>(env, ...)'. " + \
                         f"Review your task details and ensure that the API functions are defined correctly in the target file '{self.target_file}'.",
            }
        for func in func_list:
            if not func.__doc__ or len(func.__doc__.strip()) == 0:
                return False, {
                    "error": f"The API function '{func.__name__}' is missing a docstring. Please provide a clear description of its purpose and usage."
                }
            for doc_key in ["Args:", "Returns:"]:
                if doc_key not in func.__doc__:
                    return False, {
                        "error": f"The API function '{func.__name__}' is missing the '{doc_key}' section in its docstring."
                    }
        return True, {"message": f"{self.__class__.__name__} check for {self.target_file} passed."}


class UnityChipCheckerCoverageGroup(Checker):
    """
    Checker for Unity chip functional coverage groups validation.

    This class validates functional coverage definitions to ensure they properly
    implement coverage groups using the toffee framework, with adequate bins
    and watch points for comprehensive DUT verification coverage.
    """

    def __init__(self, test_dir, cov_file, doc_file, check_types, **kw):
        super().__init__()
        self.test_dir = test_dir
        self.cov_file = cov_file
        self.doc_file = doc_file
        self.check_types = check_types if isinstance(check_types, list) else [check_types]
        for ct in self.check_types:
            if ct not in ["FG", "FC", "CK"]:
                raise ValueError(f"Invalid check type '{ct}'. Must be one of 'FG', 'FC', or 'CK'.")

    def basic_check(self):
        # File existence validation
        def mk_emsg(msg):
            return {"error": msg + " Please make sure you are processing the right file."}
        if not os.path.exists(self.get_path(self.cov_file)):
            return False, mk_emsg(f"Functional coverage file '{self.cov_file}' not found in workspace.")
        # Module import validation
        funcs = fc.get_target_from_file(self.get_path(self.cov_file), "get_coverage_groups",
                                        ex_python_path=self.workspace,
                                        dtype="FUNC")
        if not funcs:
            return False, mk_emsg(f"No 'get_coverage_groups' functions found in '{self.cov_file}'.")
        if len(funcs) != 1:
            return False, mk_emsg(f"Multiple 'get_coverage_groups' functions found in '{self.cov_file}'. Only one is allowed.")
        get_coverage_groups = funcs[0]
        args = fc.get_func_arg_list(get_coverage_groups)
        if len(args) != 1 or args[0] != "dut":
            return False, mk_emsg(f"The 'get_coverage_groups' function in: {self.cov_file} must have one argument named 'dut', but got ({', '.join(args)}).")
        class fake_dut:
            def __getattribute__(self, name):
                return self
        groups = get_coverage_groups(fake_dut())
        if not groups:
            return False, mk_emsg(f"The 'get_coverage_groups' function returned no groups in target file: {self.cov_file}")
        if not isinstance(groups, list):
            return False, mk_emsg(f"The 'get_coverage_groups' function in: {self.cov_file} must return a list of coverage groups, but got {type(groups)}.")
        from toffee.funcov import CovGroup
        if not all(isinstance(g, CovGroup) for g in groups):
            return False, mk_emsg(f"All items returned by 'get_coverage_groups' in: {self.cov_file} must be instances of 'toffee.funcov.CovGroup', but got {type(groups[0])}.")
        return True, groups

    def do_check(self, timeout=0, **kw) -> Tuple[bool, str]:
        """Check the functional coverage groups against the documentation."""
        basic_pass, groups_or_msg = self.basic_check()
        if not basic_pass:
            return basic_pass, groups_or_msg
        groups = groups_or_msg
        # checks
        for ctype in self.check_types:
            doc_groups = fc.get_unity_chip_doc_marks(self.get_path(self.doc_file), ctype, 1)
            ck_pass, ck_message = self._com_check_func(groups, doc_groups, ctype)
            if not ck_pass:
                return ck_pass, ck_message
        return True, f"All coverage checks [{','.join(self.check_types)}] passed."

    def _groups_as_marks(self, func_groups, ctype):
        marks = []
        def append_v(v):
            assert v not in marks, f"Duplicate mark '{v}' found in {ctype} groups."
            marks.append(v)
        for g in func_groups:
            data = g.as_dict()
            if ctype == "FG":
                v = data["name"]
                append_v(v)
                continue
            if ctype == "FC":
                for p in data["points"]:
                    append_v(f"{data['name']}/{p['name']}")
                continue
            if ctype == "CK":
                for p in data["points"]:
                    for c in p["bins"]:
                        append_v(f"{data['name']}/{p['name']}/{c['name']}")
        return marks

    def _compare_marks(self, ga, gb):
        unmatched_in_a = []
        unmatched_in_b = []
        for a in ga:
            if a not in gb:
                unmatched_in_a.append(a)
        for b in gb:
            if b not in ga:
                unmatched_in_b.append(b)
        return unmatched_in_a, unmatched_in_b

    def _com_check_func(self, func_groups, doc_groups, ctype):
        a, b = self._compare_marks(self._groups_as_marks(func_groups, ctype), doc_groups)
        suggested_msg = "You need make those two files consist in coverage groups."
        if len(a) > 0:
            return False, f"Coverage groups check fail: find {len(a)} {ctype} ({fc.list_str_abbr(a)}) in '{self.cov_file}' but not found them in '{self.doc_file}'. {suggested_msg}"
        if len(b) > 0:
            return False, f"Coverage groups check fail: find {len(b)} {ctype} ({fc.list_str_abbr(b)}) in '{self.doc_file}' but not found them in '{self.cov_file}'. {suggested_msg}"
        info(f"{ctype} coverage {len(doc_groups)} marks check passed")
        return True, "Coverage groups check passed."


class UnityChipCheckerCoverageGroupBatchImplementation(UnityChipCheckerCoverageGroup):
    """
    Checker for Unity chip functional coverage groups batch implementation validation.

    This class validates that all functional coverage groups defined in the documentation
    are implemented in the coverage definition file, ensuring comprehensive DUT verification coverage.
    """

    def __init__(self, test_dir, cov_file, doc_file, batch_size, data_key, **kw):
        super().__init__(test_dir, cov_file, doc_file, "CK", **kw)
        self.data_key = data_key
        assert self.data_key, "data_key is required."
        self.batch_size = batch_size
        self.cached_ck_file_blocks = None
        self.batch_task = UnityChipBatchTask("check_points", self)

    def get_template_data(self):
        data = self.batch_task.get_template_data(
            "TOTAL_POINTS", "COMPLETED_POINTS", "LIST_CURRENT_POINTS"
        )
        data["LIST_CK_FILE_BLOCKS"] = "Error: CK content not find"
        if self.cached_ck_file_blocks:
            data["LIST_CK_FILE_BLOCKS"] = fc.merge_file_blocks([{k:self.cached_ck_file_blocks.get(k, ["Error, file content not found"])} for k in data["LIST_CURRENT_POINTS"]])
        return data

    def on_init(self):
        source_task_list = self.smanager_get_value(self.data_key, [])
        note_msg = []
        self.batch_task.sync_source_task(
            source_task_list,
            note_msg,
            f"CK source list in data key '{self.data_key}' changed.",
        )
        self.batch_task.update_current_tbd()
        try:
            _, self.cached_ck_file_blocks = fc.get_unity_chip_doc_marks(self.get_path(self.doc_file), "CK", 0, return_line_block=True)
        except Exception as e:
            warning(f"Error occurred while loading cached doc ck list from '{self.doc_file}': {str(e)}. Will not use cache and re-parse the document.")
        info(f"Load cached doc ck list(size={len(self.batch_task.source_task_list)}) from data key '{self.data_key}'.")
        return super().on_init()

    def do_check(self, timeout=0, is_complete=False, **kw) -> Tuple[bool, str]:
        """Check the functional coverage groups against the documentation."""
        basic_pass, groups_or_msg = self.basic_check()
        if not basic_pass:
            return basic_pass, groups_or_msg
        current_doc_ck_list, self.cached_ck_file_blocks = fc.get_unity_chip_doc_marks(self.get_path(self.doc_file), "CK", 1, return_line_block=True)
        note_msg = []
        self.batch_task.sync_source_task(
            current_doc_ck_list,
            note_msg,
            f"Documentation '{self.doc_file}' CK points changed."
        )
        current_imp_ck_list = self._groups_as_marks(groups_or_msg, "CK")
        self.batch_task.sync_gen_task(
            current_imp_ck_list,
            note_msg,
            "Completed CK points changed."
        )
        return self.batch_task.do_complete(note_msg, is_complete,
                                           f"in file: {self.doc_file}",
                                           f"in file: {self.cov_file}",
                                           " Please implement the check points in its related coverage groups follow the guid documents.")


class BaseUnityChipCheckerTestCase(Checker):
    """
    Checker for Unity chip test cases.

    This class is used to verify the test cases in Unity chip.
    It checks if the test cases meet the specified minimum requirements.
    """

    def __init__(self, doc_func_check=None, test_dir=None, doc_bug_analysis=None, min_tests=1, timeout=15, ignore_tc_prefix="",
                 data_key=None, ret_std_error=True, ret_std_out=True, batch_size=1000, need_human_check=False,
                 args_check=False, args_pattern=None, args_test_func_prefix=None,
                 args_error_msg=None, test_func_prefix=None, test_func_file=None,
                 test_func_rules=None, forbidden_test_func_prefix=None,
                 **extra_kwargs):
        super().__init__()
        self.doc_func_check = doc_func_check
        self.doc_bug_analysis = doc_bug_analysis
        self.test_dir = test_dir
        self.min_tests = min_tests
        self.timeout = timeout
        self.ignore_tc_prefix = ignore_tc_prefix
        self.data_key = data_key
        self.extra_kwargs = extra_kwargs
        self.ret_std_error = ret_std_error
        self.ret_std_out = ret_std_out
        self.batch_size = batch_size
        self.run_test = RunUnityChipTest()
        self.set_human_check_needed(need_human_check)
        self.args_check = args_check
        self.args_pattern = args_pattern
        self.args_test_func_prefix = args_test_func_prefix
        self.args_error_msg = args_error_msg
        # ``test_func_prefix`` is the naming contract for this stage.  Keep it
        # separate from argument validation so a stage can validate names even
        # when it does not validate fixture parameters.
        self.test_func_prefix = test_func_prefix
        self.test_func_file = test_func_file
        if (
            test_func_rules is None
            and test_func_prefix is None
            and test_dir
            and extra_kwargs.get("cfg") is not None
        ):
            test_func_rules = "standard"
        if test_func_rules not in (None, "standard") and not isinstance(
            test_func_rules, (list, tuple)
        ):
            raise TypeError(
                "test_func_rules must be 'standard' or a list/tuple of mappings."
            )
        self.test_func_rules = test_func_rules
        self.forbidden_test_func_prefix = forbidden_test_func_prefix

    def set_workspace(self, workspace: str):
        """
        Set the workspace for the test case checker.

        :param workspace: The workspace directory to be set.
        """
        super().set_workspace(workspace)
        self.run_test.set_workspace(workspace)
        if self.test_dir:
            if not os.path.exists(self.get_path(self.test_dir)):
                warning(f"Test directory '{self.test_dir}' does not exist in workspace.")
        return self

    def get_waveform_tool_for_checker(self):
        """Return the active WaveInfo instance whose real calls carry receipts."""

        if self.stage_manager is None:
            return None
        return self.get_tool_by_name("WaveInfo")

    def get_configured_test_output_dir(self):
        """Return the resolved TC output directory from the active stage manager."""

        cfg = getattr(self.stage_manager, "cfg", None)
        if cfg is None:
            cfg = self.extra_kwargs.get("cfg")
        if cfg is None:
            return self.test_dir or ""
        try:
            return cfg.get_value(
                "tools.RunTestCases.test_dir", self.test_dir or ""
            )
        except AttributeError:
            return self.test_dir or ""

    def _ignored_test_prefixes(self):
        return _normalize_test_prefixes(self.ignore_tc_prefix)

    def _is_ignored_test_case(self, test_case):
        test_name = str(test_case).rsplit("::", 1)[-1]
        return _test_name_matches_prefixes(test_name, self._ignored_test_prefixes())

    def _pytest_ignore_expression(self):
        prefixes = self._ignored_test_prefixes()
        if not prefixes:
            return None
        return " and ".join(f"not {prefix}" for prefix in prefixes)

    def _test_function_name_issues(self, test_files):
        """Return naming violations for the configured stage test scope."""
        rules = self._resolved_test_func_rules()
        if rules is None and self.test_func_rules == "standard":
            return [
                "test_func_rules='standard' cannot be resolved: the checker requires "
                "a non-empty resolved DUT name and a configured test_dir. Check the "
                "stage's resolved configuration before retrying the stage check."
            ]
        if rules:
            issues = []
            configured_files = set(test_files)
            for rule in rules:
                if not isinstance(rule, dict):
                    raise TypeError("test_func_rules entries must be mappings.")
                pattern = rule.get("file_pattern", rule.get("pattern"))
                if not isinstance(pattern, str) or not pattern.strip():
                    raise ValueError(
                        "test_func_rules entries require a non-empty file_pattern."
                    )
                rule_files = set(fc.find_files_by_glob(self.workspace, pattern))
                for test_file in sorted(configured_files & rule_files):
                    issues.extend(
                        _test_function_name_issues_for_files(
                            self.workspace,
                            [test_file],
                            rule.get("prefixes", rule.get("test_func_prefix", "")),
                            ignored_prefixes=rule.get("ignored_prefixes", ""),
                            forbidden_prefixes=rule.get("forbidden_prefixes", ""),
                            contract_name=rule.get("contract"),
                        )
                    )
                    configured_files.remove(test_file)
            # A rule set is an explicit file/function contract. Any test file
            # outside the declared patterns is reported instead of silently
            # allowing it to enter a later stage with an unknown identity.
            for test_file in sorted(configured_files):
                issues.append(
                    f"{test_file}: no test function naming rule matched this file; "
                    "add it to the correct stage-specific test file pattern or move "
                    "the tests to the stage that owns them."
                )
            return issues
        return _test_function_name_issues_for_files(
            self.workspace,
            test_files,
            self.test_func_prefix,
            ignored_prefixes=self._ignored_test_prefixes(),
            forbidden_prefixes=self.forbidden_test_func_prefix,
        )

    def _resolved_test_func_rules(self):
        """Resolve the built-in mixed-stage naming contract from the DUT config."""
        if self.test_func_rules != "standard":
            return self.test_func_rules
        cfg = self.extra_kwargs.get("cfg")
        dut_name = None
        if cfg is not None:
            try:
                temp_cfg = cfg.get_value("_temp_cfg", {})
            except AttributeError:
                temp_cfg = cfg.get("_temp_cfg", {}) if isinstance(cfg, dict) else {}
            if isinstance(temp_cfg, dict):
                dut_name = temp_cfg.get("DUT")
            elif isinstance(temp_cfg, Config):
                dut_name = temp_cfg.get_value("DUT")
        if not isinstance(dut_name, str) or not dut_name.strip():
            return None
        if self.test_dir is None:
            return None
        root = self.test_dir.rstrip("/")

        def test_pattern(name):
            return f"{root}/{name}" if root else name

        return [
            {
                "contract": "env fixture tests",
                "file_pattern": test_pattern(f"test_{dut_name}_env_fixture.py"),
                "prefixes": f"test_api_{dut_name}_env_",
            },
            {
                "contract": "reference-model tests",
                "file_pattern": test_pattern(
                    f"test_{dut_name}_reference_model*.py"
                ),
                "prefixes": f"test_api_{dut_name}_reference_model_",
            },
            {
                "contract": "Mock tests",
                "file_pattern": test_pattern(f"test_{dut_name}_mock_*.py"),
                "prefixes": f"test_api_{dut_name}_mock_",
            },
            {
                "contract": "API tests",
                "file_pattern": test_pattern(f"test_{dut_name}_api*.py"),
                "prefixes": f"test_api_{dut_name}_",
                "forbidden_prefixes": [
                    f"test_api_{dut_name}_env_",
                    f"test_api_{dut_name}_reference_model_",
                    f"test_api_{dut_name}_mock_",
                ],
            },
            {
                "contract": "static-Bug tests",
                "file_pattern": test_pattern(
                    f"test_{dut_name}_static_verify_*.py"
                ),
                "prefixes": f"test_static_{dut_name}_",
            },
            {
                "contract": "random tests",
                "file_pattern": test_pattern(f"test_{dut_name}_random*.py"),
                "prefixes": "test_random_",
            },
            {
                "contract": "ordinary directed tests",
                "file_pattern": test_pattern("**/test_*.py"),
                "prefixes": "test_",
                "forbidden_prefixes": DEFAULT_RESERVED_TEST_FUNCTION_PREFIXES,
            },
        ]

    def _stage_test_files(self):
        """Return files whose function names belong to the current stage scope."""
        rules = self._resolved_test_func_rules()
        if rules is None and self.test_func_rules == "standard":
            return []
        if rules:
            patterns = []
            for rule in rules:
                if isinstance(rule, dict):
                    pattern = rule.get("file_pattern", rule.get("pattern"))
                    if pattern:
                        patterns.append(pattern)
            return fc.find_files_by_glob(self.workspace, patterns)
        if self.test_func_file:
            return fc.find_files_by_pattern(self.workspace, self.test_func_file)
        if not self.test_dir:
            return []
        return fc.find_files_by_pattern(
            self.workspace,
            f"{self.test_dir.rstrip('/')}/test_*.py",
        )

    def _set_test_report_context(self):
        """Identify the active stage/checker in the shared current report."""
        stage = self.get_stage()
        context = {
            "source": "checker",
            "checker_class": self.__class__.__name__,
        }
        if stage is not None:
            context["stage_name"] = stage.name
        if self.stage_manager is not None:
            context["stage_index"] = self.stage_manager.stage_index
        self.run_test.set_report_context(context)

    def _check_test_func_args(self, report, str_out, str_err):
        """
        Check test function argument names against self.args_pattern.

        For each test case in the report whose name starts with self.args_test_func_prefix
        (or all test cases if args_test_func_prefix is None), verify that the positional
        argument names match self.args_pattern.  For example, args_pattern=["env", "ref_model"]
        requires position-0 to be "env" and position-1 to be "ref_model".

        On failure, report["run_test_success"] is set to False and the failure reasons
        are appended to str_err.
        """
        if report.get("run_test_success") is False:
            return report, str_out, str_err
        if not self.args_check or not self.args_pattern:
            return report, str_out, str_err
        test_cases = report.get("tests", {}).get("test_cases", {})
        if not test_cases:
            return report, str_out, str_err
        tc_blocks = fc.tc_list_as_loc_blocks(test_cases.keys(),
                                             target_tc_prefix=self.args_test_func_prefix,
                                             workspace=self.workspace)
        failures = []
        def check_args(func_code_str):
            arg_list = fc.get_func_params_regex(func_code_str)
            warning(f"find mis-match args: {arg_list}")
            if len(arg_list) < len(self.args_pattern):
                return False
            for i, arg_pt in enumerate(self.args_pattern):
                if not fc.match_pattern_list(arg_list[i],
                                             arg_pt if isinstance(arg_pt, list) else [arg_pt]):
                    return False
            return True
        for _, v in fc.check_file_block(tc_blocks,
                                        self.workspace,
                                        check_args).items():
            for func_name, is_pass in v.items():
                if is_pass:
                    continue
                failures.append(func_name)
        if len(failures) > 0:
            report["run_test_success"] = False
            max_show = 10
            error_msg = self.args_error_msg
            if not error_msg:
                error_msg = f"do not match the required argument pattern {self.args_pattern}"
            str_err  = f"Argument name check failed for {len(failures)} test functions. " + \
                       f"The flollowing test functions have argument names that {error_msg}: {', '.join(failures[:max_show])}" + \
                       (f", etc." if len(failures) > max_show else "") + \
                        " Please fix the arguments of those test functions to match the required pattern."
            str_out = ""
        return report, str_out, str_err

    def do_check(self, pytest_args="", timeout=0, is_complete=False, **kw) -> Tuple[bool, str]:
        """
        Perform the check for test cases.

        Returns:
            report, str_out, str_err: A tuple where the first element is a boolean indicating success or failure,
        """
        naming_issues = self._test_function_name_issues(self._stage_test_files())
        if naming_issues:
            retry_tool = "Complete" if is_complete else "Check"
            return (
                _test_function_contract_report(naming_issues, retry_tool=retry_tool),
                "",
                "",
            )
        if not os.path.exists(self.get_path(self.doc_func_check)):
            return {}, "", f"[Document Missing] Functions and checkpoints document {self.doc_func_check} does not exist in the workspace. "+\
                            "Please verify the document path is correct and check if the function description stage task has been completed (see Guide_Doc/dut_functions_and_checks.md)."
        self.run_test.set_pre_call_back(
            lambda p: self.set_check_process(p, self.timeout)  # Set the process for the checker
        )
        timeout = timeout if timeout > 0 else self.timeout
        ignore_expression = self._pytest_ignore_expression()
        if ignore_expression:
            pytest_args = pytest_args if pytest_args else "."
            pytest_args = pytest_args.split()
            pytest_args = ["-k", ignore_expression] + pytest_args
        self._set_test_report_context()
        report, str_out, str_err = self.run_test.do(
            self.test_dir,
            pytest_ex_args=pytest_args,
            return_stdout=True, return_stderr=True, return_all_checks=True, timeout=timeout,
            **kw
        )
        report, str_out, str_err = self._check_test_func_args(report, str_out, str_err)
        return report, str_out, str_err


class UnityChipCheckerTestFree(BaseUnityChipCheckerTestCase):

    def do_check(self, pytest_args="", timeout=0, return_line_coverage=False, detail=False, **kw):
        """call pytest to run the test cases."""
        report, str_out, str_err = super().do_check(pytest_args=pytest_args, timeout=timeout, **kw)
        test_pass, test_msg = fc.is_run_report_pass(report, str_out, str_err)
        if not test_pass:
            return False, test_msg
        # refine report:
        free_report = OrderedDict({
            "run_test_success": report.get("run_test_success", False),
            "tests": report.get("tests", {}),
            "failed_ck": report.get("failed_check_point_list", {}),
            "failed_tc": report.get("failed_test_case_with_check_point_list",{})
        })
        marked_bins = []
        failed_check_point_list = report.get("failed_check_point_list", [])
        for b in report.get("all_check_point_list", []):
            if b not in failed_check_point_list:
                marked_bins.append(b)
                continue
        free_report["marked_check_point_list"] = marked_bins
        if return_line_coverage:
            line_coverage_data = {}
            line_coverage_file = self.extra_kwargs.get("coverage_json", "uc_test_report/line_dat/code_coverage.json")
            if not os.path.exists(self.get_path(line_coverage_file)):
                line_coverage_data["error"] = f"Line coverage file '{line_coverage_file}' does not exist in workspace."
            else:
                try:
                    line_coverage_data = fc.parse_un_coverage_json(
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


class UnityChipCheckerTestTemplate(BaseUnityChipCheckerTestCase):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.total_tests_count = 0
        self.cached_ck_file_blocks = None
        self.ignored_source_checkpoints = []
        self.batch_task = UnityChipBatchTask("check_points", self)

    def _load_checkpoint_scope(self):
        all_doc_checkpoints, file_blocks = fc.get_unity_chip_doc_marks(
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
                data["LIST_CK_FILE_BLOCKS"] = fc.merge_file_blocks([{k:self.cached_ck_file_blocks.get(k, ["Error, file content not found"])} for k in data["LIST_CKS_TO_BE_COVERED"]])
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
        test_pass, test_msg = fc.is_run_report_pass(report, str_out, str_err)
        if not test_pass:
            return False, test_msg
        raw_report = copy.deepcopy(report)
        all_bins_test = report.get("all_check_point_list", [])
        msg_report = fc.clean_report_with_keys(report,
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

        missing_coverage_message = fc.get_missing_functional_coverage_message(report)
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
            info_runtest["error"] = f"The follow {len(bins_not_in_docs)} check points: {fc.list_str_abbr(bins_not_in_docs)} are not defined in the documentation file {self.doc_func_check} but defined in the test cover group. " + \
                                     "Please ensure that all check points in the test cover group are defined in the documentation file. " + \
                                     "Review your task requirements and the test cases."
            return False, info_runtest
        if len(bins_not_in_test) > 0:
            info_runtest["error"] = f"The follow {len(bins_not_in_test)} check points: {fc.list_str_abbr(bins_not_in_test)} are defined in the documentation file {self.doc_func_check} but not defined in the test cover group. " + \
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
            mark_function_desc = fc.description_mark_function_doc(
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
        if unmarked_doc_checkpoints:
            info_runtest["error"] = fc.description_checkpoint_association_missing(
                unmarked_doc_checkpoints
            )
            return False, info_runtest

        # All structural and association checks passed; batch progress can now
        # be derived without masking the reason a checkpoint was omitted.
        target_bins_test = [
            checkpoint
            for checkpoint in all_bins_test
            if checkpoint in target_bins_docs
        ]
        note_msg = []
        self.batch_task.sync_source_task(
            target_bins_docs,
            note_msg,
            f"{self.doc_func_check} file CK points changed.",
        )
        self.batch_task.sync_gen_task(
            target_bins_test,
            note_msg,
            "Test cases CK points changed.",
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
                                 f"✓ All {len(target_bins_test)} in-scope check points are properly documented and marked in test functions.",
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
                f"{fc.list_str_abbr(execution_errors, max_items=20, show_counts=True)} "
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
                f"{fc.list_str_abbr(passed_tests, max_items=20, show_counts=True)} "
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
                f"{fc.list_str_abbr(unexpected_failures, max_items=20, show_counts=True)} "
                "The underlying exception may come from "
                f"the test, a called component, or the execution environment. {guidance}"
            )
        if missing_failure_details:
            return False, (
                "Test template assertion validation failed: Could not determine the exception type "
                "for these tests: "
                f"{fc.list_str_abbr(missing_failure_details, max_items=20, show_counts=True)} "
                "Review the first relevant "
                "traceback in STDOUT/STDERR and fix the component that owns the failing frame. "
                f"Required outcome: {expected_assertion}."
            )
        if wrong_assert_messages:
            return False, (
                "Test template structure validation failed: The following tests raised AssertionError "
                "without the required 'Not implemented' message: "
                f"{fc.list_str_abbr(wrong_assert_messages, max_items=20, show_counts=True)} "
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


class UnityChipCheckerDutApiTest(BaseUnityChipCheckerTestCase):

    def __init__(self, api_prefix, target_file_api, target_file_tests, doc_func_check,
                 doc_bug_analysis, min_tests=1, timeout=15,
                 api_ck_prefix="FG-API/", **kw):
        if kw.get("test_func_prefix") is None:
            kw["test_func_prefix"] = f"test_{api_prefix}"
        super().__init__(
            doc_func_check,
            os.path.dirname(target_file_tests),
            doc_bug_analysis,
            min_tests,
            timeout,
            **kw,
        )
        self.api_prefix = api_prefix
        self.target_file_api = target_file_api
        self.target_file_tests = target_file_tests
        self.api_ck_prefix = api_ck_prefix.rstrip("/") + "/"

    @staticmethod
    def _missing_functional_coverage_message(report):
        return fc.get_missing_functional_coverage_message(report)

    def _missing_api_checkpoint_association_message(self, report):
        """Require every executed API test to include an API-group checkpoint."""

        test_cases = report.get("tests", {}).get("test_cases", {})
        associations = report.get("test_case_with_check_point_list")
        if not isinstance(associations, dict):
            return (
                "[API Checkpoint Mapping Unavailable] The Toffee report does not contain "
                "per-test checkpoint associations. Rerun the API tests, then call Check or "
                "Complete to generate a current report; do not infer completion from global "
                "checkpoint totals."
            )

        missing = []
        for test_case in test_cases:
            checkpoints = associations.get(test_case, [])
            if not isinstance(checkpoints, list):
                checkpoints = []
            if any(
                isinstance(checkpoint, str)
                and checkpoint.startswith(self.api_ck_prefix)
                for checkpoint in checkpoints
            ):
                continue
            missing.append(
                f"{test_case} -> {fc.list_str_abbr(checkpoints) if checkpoints else '[]'}"
            )

        if not missing:
            return None
        return (
            f"[API Checkpoint Association Missing] {len(missing)} API test function(s) "
            f"have no checkpoint association under '{self.api_ck_prefix}': "
            f"{fc.list_str_abbr(missing)}. Every API test must call mark_function for the "
            "corresponding API-group FG/FC/CK defined in the functions-and-checks document. "
            "Checkpoint associations from other functional groups are optional additions: "
            "keep every valid extra relation, but it cannot replace the required API-group "
            "relation. Do not mark unrelated API checkpoints merely to satisfy this check."
        )

    def do_check(self, timeout=0, **kw) -> tuple[bool, object]:
        """Perform the check for DUT API tests."""
        test_files = [fc.rm_workspace_prefix(self.workspace, f) for f in glob.glob(os.path.join(self.workspace, self.target_file_tests))]
        if len(test_files) == 0:
            return False, {"error": f"No test files matching '{self.target_file_tests}' found in workspace."}
        if not os.path.exists(self.get_path(self.doc_func_check)):
            return False, {"error": f"Function and check documentation file {self.doc_func_check} does not exist in workspace. "}
        if not os.path.exists(self.get_path(self.target_file_api)):
            return False, {"error": f"DUT API file '{self.target_file_api}' does not exist in workspace."}
        naming_files = (
            self._stage_test_files() if self.test_func_rules else test_files
        )
        naming_issues = self._test_function_name_issues(naming_files)
        if naming_issues:
            retry_tool = "Complete" if kw.get("is_complete", False) else "Check"
            return False, _test_function_contract_failure(
                naming_issues,
                retry_tool=retry_tool,
            )
        # call pytest
        targets = " ".join(test_files)
        assert isinstance(timeout, int), f"timeout must be an integer. But got {type(timeout)}:{timeout}."
        timeout = timeout if timeout > 0 else self.timeout
        self._set_test_report_context()
        report, str_out, str_err = self.run_test.do(
            "", 
            pytest_ex_args=targets,
            return_stdout=True, return_stderr=True, return_all_checks=True, timeout=timeout
        )
        report, str_out, str_err = self._check_test_func_args(report, str_out, str_err)
        test_pass, test_msg = fc.is_run_report_pass(report, str_out, str_err)
        if not test_pass:
            return False, test_msg
        report_copy = fc.clean_report_with_keys(report)
        func_list = fc.get_target_from_file(self.get_path(self.target_file_api), f"{self.api_prefix}*",
                                         ex_python_path=self.workspace,
                                         dtype="FUNC")
        if len(func_list) == 0:
            return False, {"error": f"No DUT API functions with prefix '{self.api_prefix}' found in '{self.target_file_api}'. "+\
                                     "Note: the api name is case-sensitive."}
        test_cases = report.get("tests", {}).get("test_cases", {})
        test_keys = test_cases.keys()
        test_functions = []
        api_un_tested = []
        for func in func_list:
            func_name = func.__name__
            for k in test_keys:
                if func_name in k:
                    test_functions.append(func_name)
                    break
            if func_name not in test_functions:
                api_un_tested.append(func_name)
        def get_emsg(m):
            return _report_failure_message(
                m,
                report_copy,
                stdout=str_out,
                stderr=str_err,
                include_stdout=self.ret_std_out,
                include_stderr=self.ret_std_error,
            )
        missing_coverage_message = self._missing_functional_coverage_message(report)
        if missing_coverage_message:
            return False, get_emsg(missing_coverage_message)
        if api_un_tested:
            info(f"Missed APIs: {','.join(api_un_tested)}")
            info(f"Found test APIs: {','.join(test_functions)}")
            info(f"All test cases: {','.join(test_keys)}")
            return False, get_emsg(f"Missing test functions for {len(api_un_tested)} API(s): {fc.list_str_abbr(api_un_tested)} (Defined in file: {self.target_file_api}). " + \
                                   f"Please create the missing functions: {fc.list_str_abbr(['test_' + f for f in api_un_tested])} (format: test_<api_name>, add prefix 'test_' to the API name). " + \
                                   f"Note: All dut APIs must be defined in: {self.target_file_api}. ")
        test_count_no_check_point_mark = report.get("test_function_with_no_check_point_mark", 0)
        if test_count_no_check_point_mark > 0:
            unmarked_functions = report.get(
                "test_function_with_no_check_point_mark_list", []
            )
            mark_function_desc = fc.description_mark_function_doc(
                unmarked_functions,
                self.workspace,
            )
            return False, get_emsg(
                "[Checkpoint Association Missing] Toffee did not record any checkpoint "
                f"association for {test_count_no_check_point_mark} executed API test "
                f"function(s): {fc.list_str_abbr(unmarked_functions)}. "
                f"{mark_function_desc}"
            )

        api_association_message = self._missing_api_checkpoint_association_message(
            report
        )
        if api_association_message:
            return False, get_emsg(api_association_message)

        ret, msg, _ = check_report(
            self.workspace,
            report,
            self.doc_func_check,
            self.doc_bug_analysis,
            self.api_ck_prefix,
            waveform_tool=self.get_waveform_tool_for_checker(),
            waveform_test_dir=os.path.dirname(self.target_file_api),
            test_output_dir=self.get_configured_test_output_dir(),
        )
        if not ret:
            return ret, get_emsg(msg)
        ret, msg = fc.check_has_assert_in_tc(self.workspace, report)
        if not ret:
            return ret, get_emsg(msg["error"])
        return True, {"success": f"{self.__class__.__name__} check for {self.target_file_tests} passed."}


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
        self._last_batch_progress = None
        self._batch_checkpoint_error = None
        self.batch_task = UnityChipBatchTask("test_cases", self)
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

    def get_run_args(self, test_dir=None):
        failed_tests_files = set()
        target_tests = ""
        for t in self.current_test_cases:
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
            "failed_checkpoints": report.get("failed_check_point_list", []),
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
            for k,v in pre_report.get("tests", {}).get("test_cases", {}).items():
                if self._is_ignored_test_case(k):
                    info(f"{self.__class__.__name__} ignore test case: {k}")
                    continue
                if v == "PASSED":
                    passed_tc.append(k)
                else:
                    failed_tc.append(k)
            if len(passed_tc) != 0:
                warning(f"No test cases defined for implementation. However, {len(passed_tc)} test cases are already passing: {fc.list_str_abbr(passed_tc)}. ")
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
        info(f"Current batch: {len(self.current_test_cases)} test cases to implement: {fc.list_str_abbr(self.current_test_cases)}")
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
            return False, {"error": f"The following test files do not exist: {fc.list_str_abbr(failed_tests_files)}. " + \
                            "Please check your test case names and ensure they are correct."}
        info(f"Checking {len(self.current_test_cases)} test cases: {target_tests}")
        report, str_out, str_err = super().do_check(pytest_args=target_tests, timeout=timeout, **kw)
        test_pass, test_msg = fc.is_run_report_pass(report, str_out, str_err)
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
            info(f"implemented cases: {fc.list_str_abbr(return_tests.keys())}")
            error_msgs["error"] = f"The following test cases: `{fc.list_str_abbr(missing_tests)}` are missing in the tests implementation. " + \
                                   "Please ensure that all test cases are properly implemented and reported."
            return False, error_msgs
        if len(extends_tests) > 0:
            error_msgs["error"] = (
                f"The test run returned {len(extends_tests)} case(s) outside the current "
                f"batch: {fc.list_str_abbr(extends_tests)}. Run exactly the current batch "
                "targets before retrying Check."
            )
            return False, error_msgs

        ret, msg, _ = check_report(
            self.workspace,
            report,
            self.doc_func_check,
            self.doc_bug_analysis,
            only_marked_ckp_in_tc=True,
            waveform_tool=self.get_waveform_tool_for_checker(),
            waveform_test_dir=self.test_dir,
            test_output_dir=self.get_configured_test_output_dir(),
            require_all_documented_tests=False,
        )
        error_msgs["REPORT"] = self._compact_validation_report(report, return_tests)
        if not ret:
            batch_progress = self._set_batch_progress(
                return_tests,
                validation="document_failed",
                test_run="executed",
            )
            contextual_failure = self._with_batch_context(
                msg,
                validation_mode="fresh_test_run",
                batch_progress=batch_progress,
                batch_report=error_msgs["REPORT"],
            )
            _set_checker_failure(error_msgs, contextual_failure)
            return ret, error_msgs
        ret, msg = fc.check_has_assert_in_tc(self.workspace, report)
        if not ret:
            batch_progress = self._set_batch_progress(
                return_tests,
                validation="assertion_failed",
                test_run="executed",
            )
            error_msgs["error"] = self._with_batch_context(
                msg["error"],
                validation_mode="fresh_test_run",
                batch_progress=batch_progress,
                batch_report=error_msgs["REPORT"],
            )
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
                                  f"Next, please proceed to implement the following {len(self.current_test_cases)} test cases: {fc.list_str_abbr(self.current_test_cases)}. " + \
                                  f"Test case implemention progress: {sum([t[1] for t in self.total_test_cases])}/{len(self.total_test_cases)}. "}


class UnityChipCheckerTestCase(BaseUnityChipCheckerTestCase):

    def get_zero_bug_rate_list(self):
        zero_list = []
        if not self._is_init:
            return zero_list
        try:
            for bg in fc.get_unity_chip_doc_marks(os.path.join(self.workspace, self.doc_bug_analysis), leaf_node="BG"):
                try:
                    rate = int(bg.split("-")[-1])
                    if rate == 0:
                        zero_list.append(bg)
                except Exception as e:
                    pass
        except Exception as e:
            pass
        return zero_list

    def get_template_data(self):
        zero_rate = ""
        zero_list = self.get_zero_bug_rate_list()
        if len(zero_list) > 0:
            zero_rate = f"(Find {len(zero_list)}: {', '.join(zero_list[:10])}{' ... ' if len(zero_list) > 10 else ''})"
        return {
                "BUG_ZERO_RATE_LIST": zero_rate
            }

    def do_check(self, timeout=0, **kw) -> Tuple[bool, str]:
        """
        Perform comprehensive check for implemented test cases.
        """
        # Execute tests and get comprehensive report
        report, str_out, str_err = super().do_check(timeout=timeout, **kw)
        test_pass, test_msg = fc.is_run_report_pass(report, str_out, str_err)
        if not test_pass:
            return False, test_msg
        abs_report = copy.deepcopy(report)
        all_bins_test = report.get("all_check_point_list", [])
        abs_report = fc.clean_report_with_keys(report)

        # Prepare diagnostic information
        info_runtest = OrderedDict()
        if self.ret_std_out:
            info_runtest["STDOUT"] = str_out
        if self.ret_std_error:
            info_runtest["STDERR"] = str_err
        info_runtest["TEST_REPORT"] = abs_report

        # Basic validation: Check if tests exist
        if report.get("tests") is None:
            info_runtest["error"] = {
                "error": "[Test Report Missing] The test run produced no tests mapping.",
                "observed": "report.tests is missing",
                "required": (
                    "The run must collect the intended test_*.py files and return a tests "
                    "mapping with exact pytest node IDs and statuses."
                ),
                "next_action": (
                    "Read the first concrete collection/import error in STDOUT/STDERR and "
                    "fix that exact file and line. If no such error exists, rename the "
                    "intended file/function to test_*, preserve its required fixture "
                    "signature from Guide_Doc/dut_test_case.md, then rerun Check."
                ),
            }
            return False, info_runtest
        
        # Validate minimum test count requirement
        if report["tests"]["total"] < self.min_tests:
            current_total = report["tests"]["total"]
            info_runtest["error"] = {
                "error": (
                    f"[Insufficient Test Cases] Collected {current_total} test case(s); "
                    f"the required minimum is {self.min_tests}."
                ),
                "observed": current_total,
                "required": self.min_tests,
                "next_action": (
                    f"Add or restore at least {self.min_tests - current_total} meaningful "
                    "test case(s) for the uncovered specification scenarios, ensure each "
                    "file/function uses the test_* naming contract, then rerun Check. See "
                    "Guide_Doc/dut_test_case.md."
                ),
            }
            return False, info_runtest
        
        # Parse documentation marks for validation
        zero_list = self.get_zero_bug_rate_list()
        zero_rate_msg = f"Note: Found {len(zero_list)} invalid zero-confidence dynamic Bug placeholder(s): {', '.join(zero_list[:10])}{' ... ' if len(zero_list) > 10 else '.'}" + \
                         " They cannot explain failed tests. Fix non-DUT failures to Pass, or promote a confirmed DUT Bug to non-zero confidence and add all required dynamic evidence."

        ret, msg, marked_bugs = check_report(
            self.workspace,
            report,
            self.doc_func_check,
            self.doc_bug_analysis,
            waveform_tool=self.get_waveform_tool_for_checker(),
            waveform_test_dir=self.test_dir,
            test_output_dir=self.get_configured_test_output_dir(),
        )
        if not ret:
            _set_checker_failure(info_runtest, msg)
            if len(zero_list) > 0:
                if isinstance(info_runtest["error"], list):
                    info_runtest["error"].append(zero_rate_msg)
                elif isinstance(info_runtest["error"], str):
                    info_runtest["error"] += " " + zero_rate_msg
                else:
                    warning(f"Cannot append zero rate message to error of type {type(info_runtest['error'])}.")
            return ret, info_runtest

        ret, msg = fc.check_has_assert_in_tc(self.workspace, report)
        if not ret:
            _set_checker_failure(info_runtest, msg)
            return False, info_runtest

        # Success: All validations passed
        failed_count = report["tests"].get("fails", 0)
        passed_count = report["tests"]["total"] - failed_count
        success_msg = ["Test case verification passed!",
                      f"+ Executed {report['tests']['total']} test case(s).",
                      f"+ {passed_count} case(s) passed; {failed_count} remaining failed case(s) are confirmed DUT Bug reproducers with complete required evidence.",
                      f"+ All {len(all_bins_test)} checkpoint(s) correctly implemented and consistent with documentation.",
                      f"+ Test-documentation consistency check passed.",
                      f"+ {marked_bugs} bug(s) marked in bug analysis document {self.doc_bug_analysis}.",
                      "Completion does not require confirmed DUT Bug reproducers to pass; every other case must pass."]
        if len(zero_list) > 0:
            success_msg.append(zero_rate_msg)
        if marked_bugs == 0:
            success_msg.append("Warning: No bugs marked in the bug analysis document. If issues were found during testing, ensure they are properly documented in the bug analysis document (see Guide_Doc/dut_bug_analysis.md).")
            success_msg.extend(fc.description_bug_doc())
        return True, success_msg


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


class UnityChipCheckerRefineTestCases(Checker):
    def __init__(self,
                 doc_func_check,
                 test_dir=None,
                 ignore_tc_prefix="",
                 batch_size=10,
                 data_key=None,
                 **extra_kwargs):
        super().__init__()
        self.doc_func_check = doc_func_check
        self.test_dir = test_dir
        self.ignore_tc_prefix = ignore_tc_prefix
        self.batch_size = batch_size
        self.data_key = data_key
        self.refine_result = OrderedDict()
        self.cached_ck_file_blocks = OrderedDict()
        self.ck_test_cases_map = OrderedDict()
        self.unresolved_mark_function = []
        self.total_test_cases_count = -1
        self._refine_result_key = "_TC_REFINE_RESULT"
        self.batch_task = UnityChipBatchTask("CK", self)

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
