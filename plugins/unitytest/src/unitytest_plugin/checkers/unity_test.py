# -*- coding: utf-8 -*-
"""UnityTest Checker bases and helpers shared by the UnityTest plugin.

This module owns the label-structure, fixture, DutApi, coverage-group, and
test-case checker classes that the UnityTest workflows wire through ``clss``
and that other workflow plugins (for example DesignWithPPA) build on.
"""

import hashlib
import fnmatch
import json
import re
import subprocess
import sys
import tempfile
from typing import Tuple
import ucagent.util.functions as fc
from ucagent_common.str_utils import list_str_abbr
from ucagent.util.config import Config, load_current_test_report
from ucagent.util.log import info, warning
from ..testops import RunUnityChipTest
import os
import glob
import traceback
import copy
import ast

from ucagent.checkers.base import Checker, BatchTask, format_stage_args_examples
from .toffee_report import (
    check_line_coverage,
    check_report,
    get_missing_functional_coverage_message,
)
from .descriptions import (
    description_bug_doc,
    description_func_doc,
    description_mark_function_doc,
)
from collections import OrderedDict
from ucagent_common.doc_marks import get_doc_marks, merge_file_blocks
from ucagent_common.test_report import (
    check_file_block,
    check_has_assert_in_tc,
    is_run_report_pass,
    tc_list_as_loc_blocks,
)
from unitytest_plugin.report_utils import (
    clean_report_with_keys,
    tips_of_get_coverage_data_path,
)

DEFAULT_RESERVED_TEST_FUNCTION_PREFIXES = (
    "test_api_",
    "test_static_",
    "test_random_",
)


def _python_source_definitions(target_file, pattern, definition_type):
    """Parse top-level Python definitions without importing workspace code."""

    with open(target_file, "r", encoding="utf-8") as source_file:
        source = source_file.read()
    tree = ast.parse(source, filename=target_file)
    if definition_type == "function":
        node_types = (ast.FunctionDef, ast.AsyncFunctionDef)
    elif definition_type == "class":
        node_types = (ast.ClassDef,)
    else:
        raise ValueError("definition_type must be 'function' or 'class'")
    definitions = [
        node
        for node in tree.body
        if isinstance(node, node_types) and fnmatch.fnmatch(node.name, pattern)
    ]
    return source, definitions


def _python_positional_args(definition):
    """Return positional argument names from one AST function definition."""

    return [
        argument.arg
        for argument in [*definition.args.posonlyargs, *definition.args.args]
    ]


def _python_definition_source(source, definition):
    """Return the exact source segment for one parsed Python definition."""

    return ast.get_source_segment(source, definition) or ""


def _ast_qualified_name(node):
    """Return a dotted static name for an AST name or attribute expression."""

    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _ast_qualified_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _pytest_fixture_contract(definition):
    """Return whether a function has a pytest fixture decorator and its scope."""

    for decorator in definition.decorator_list:
        call = decorator if isinstance(decorator, ast.Call) else None
        target = call.func if call is not None else decorator
        if _ast_qualified_name(target).rsplit(".", 1)[-1] != "fixture":
            continue
        scope = None
        if call is not None:
            for keyword in call.keywords:
                if (
                    keyword.arg == "scope"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    scope = keyword.value.value
        return True, scope
    return False, None


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
                data_sub = get_doc_marks(self.get_path(dfile), self.leaf_node, self.min_count)
            except Exception as e:
                error_details = str(e)
                warning(f"Error occurred while checking {dfile}: {error_details}")
                warning(traceback.format_exc())
                emsg = [f"Documentation parsing failed for file '{dfile}': {error_details}."]
                if "\\n" in error_details:
                    emsg.append("Literal '\\n' characters detected - use actual line breaks instead of escaped characters")
                emsg.append({"check_list": [
                    "Malformed tags: Ensure proper format. e.g., <FG-NAME>, <FC-NAME>, <CK-NAME>",
                    *description_func_doc(),
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
        source, fixture_func_list = _python_source_definitions(
            self.get_path(self.target_file), self.fixture_name, "function"
        )
        for fx_func in fixture_func_list:
            args = _python_positional_args(fx_func)
            if self.first_arg is not None and (len(args) < 1 or args[0] != self.first_arg):
                return False, {"error": f"The '{fx_func.name}' fixture's first arg must be '{self.first_arg}', but got ({', '.join(args)})."}
            if self.last_arg is not None and (len(args) < 1 or args[-1] != self.last_arg):
                return False, {"error": f"The '{fx_func.name}' fixture's last arg must be '{self.last_arg}', but got ({', '.join(args)})."}
            is_fixture, scope_value = _pytest_fixture_contract(fx_func)
            if not is_fixture:
                return False, {"error": f"The '{fx_func.name}' fixture in '{self.target_file}' is not decorated with @pytest.fixture()."}
            effective_scope = scope_value or "function"
            if effective_scope != self.scope:
                return False, {"error": f"The '{fx_func.name}' fixture in '{self.target_file}' has invalid scope '{effective_scope}'. The expected scope is '{self.scope}'."}
            func_source = _python_definition_source(source, fx_func)
            for k, (v, f) in self.source_code_need.items():
                message = v
                if f:
                    message += f" {f(self.dut_name)}"
                if k not in func_source:
                    info(f"[{self.__class__.__name__}]Check source code of fixture '{fx_func.name}' in file '{self.target_file}': missing '{k}' in source:\n{func_source}\n.")
                    return False, {"error":  message}
            if self.source_code_cb:
                ret, msg = self.source_code_cb(func_source, fx_func.name)
                if not ret:
                    return False, msg
        if len(fixture_func_list) < self.min_count:
            return False, {"error": f"Insufficient fixture coverage: {len(fixture_func_list)} fixtures found, minimum required is {self.min_count}. "+\
                                    f"You have defined {len(fixture_func_list)} fixtures: {', '.join([f.name for f in fixture_func_list])} in file '{self.target_file}'."}
        if self.fix_count > 0 and len(fixture_func_list) != self.fix_count:
            return False, {"error": f"Incorrect fixture count: {len(fixture_func_list)} fixtures found, expected exactly {self.fix_count}. "+\
                                    f"You have defined {len(fixture_func_list)} fixtures: {', '.join([f.name for f in fixture_func_list])} in file '{self.target_file}'."}
        return True, {"message": f"{self.__class__.__name__} fixture check for {self.target_file} passed."}


class UnityChipCheckerDutFixture(UnityChipCheckerBaseFixture):
    def __init__(self, target_file, min_count=1, **kw):
        super().__init__(target_file, "dut", first_arg="request", min_count=min_count, **kw)
        self.update_dut_name(kw["cfg"])
        msg = f"The 'dut' fixture in '{self.target_file}' must call 'get_coverage_data_path(request, dut, new_path=False)' to get existed coverage file path. {tips_of_get_coverage_data_path(self.dut_name)}"
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

    def _check_lifecycle(self, source_code, dut_func_name):
        tree = ast.parse(source_code)
        fixture_node = next(
            (
                node for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == dut_func_name
            ),
            None,
        )
        if fixture_node is None:
            return False, {
                "error": f"Cannot parse the '{dut_func_name}' fixture body in "
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
            return False, {"error": f"The '{dut_func_name}' fixture in '{self.target_file}' does not contain 'yield' statement. Pytest fixtures should yield the DUT instance for proper setup/teardown."}

        func_coverage_calls = [call for call, _ in visitor.func_coverage_calls]
        if not func_coverage_calls:
            return False, {
                "error":
                    f"The '{dut_func_name}' fixture in '{self.target_file}' must call "
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
                    f"The '{dut_func_name}' fixture in '{self.target_file}' must pass both "
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
                    f"The '{dut_func_name}' fixture in '{self.target_file}' must yield the "
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
                    f"The '{dut_func_name}' fixture in '{self.target_file}' must call "
                    "'set_func_coverage(request, func_coverage_group)' on an unconditional "
                    "teardown path after 'yield'. Calls before yield, inside nested functions, "
                    "or under if/loop/match branches cannot guarantee that final coverage "
                    "samples and mark_function mappings are attached to every test report."
            }
        return True, {}


class UnityChipCheckerEnvFixture(UnityChipCheckerBaseFixture):
    def __init__(self, target_file, min_count=1, **kw):
        super().__init__(target_file, "env*", first_arg="dut", min_count=min_count, **kw)


class UnityChipCheckerDutApi(Checker):
    """Validate the public DUT API surface without importing workspace code."""

    def __init__(self, api_prefix, target_file, min_apis=1, **kw):
        """Store the expected API prefix, source path, and minimum API count."""

        super().__init__()
        self.api_prefix = api_prefix
        self.target_file = target_file
        self.min_apis = min_apis

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Check the DUT API implementation for correctness."""
        target_path = self.get_path(self.target_file)
        if not os.path.exists(target_path):
            return False, {
                "error_code": "DUT_API_FILE_MISSING",
                "error": f"DUT API file '{self.target_file}' does not exist.",
                "next_action": f"Create '{self.target_file}' and define the required public DUT APIs.",
                "artifact": self.target_file,
                "location": self.target_file,
                "observed": {"exists": False},
                "expected": {"exists": True, "api_prefix": self.api_prefix},
            }
        try:
            _, func_list = _python_source_definitions(
                target_path, f"{self.api_prefix}*", "function"
            )
        except (OSError, SyntaxError, UnicodeError) as exc:
            location = self.target_file
            if isinstance(exc, SyntaxError) and exc.lineno:
                location = f"{self.target_file}:{exc.lineno}"
            return False, {
                "error_code": "DUT_API_PARSE_FAILED",
                "error": f"DUT API file '{self.target_file}' could not be parsed as Python source.",
                "next_action": "Fix the reported source error, then run Check again.",
                "artifact": self.target_file,
                "location": location,
                "observed": str(exc),
                "expected": "A UTF-8 Python source file accepted by ast.parse.",
            }
        failed_apis = []
        for func in func_list:
            args = _python_positional_args(func)
            if not args or len(args) < 2:
                failed_apis.append(func)
                continue
            if not args[0].startswith("env"):
                failed_apis.append(func)
            if not args[-1].startswith("max_cycles"):
                failed_apis.append(func)
        if len(failed_apis) > 0:
            signatures = [
                f"{func.name}({', '.join(_python_positional_args(func))})"
                for func in failed_apis[:20]
            ]
            return False, {
                "error_code": "DUT_API_SIGNATURE_INVALID",
                "error": f"DUT API functions in '{self.target_file}' have invalid or missing arguments.",
                "next_action": "Make every public DUT API start with 'env' and end with 'max_cycles=default_value'.",
                "artifact": self.target_file,
                "location": self.target_file,
                "observed": {
                    "invalid_api_count": len(failed_apis),
                    "signatures": signatures,
                    "truncated": len(failed_apis) > len(signatures),
                },
                "expected": "Every matching API has first argument 'env' and last argument 'max_cycles=default_value'.",
                "failed_apis": signatures,
            }
        if len(func_list) < self.min_apis:
            return False, {
                "error_code": "DUT_API_COUNT_INSUFFICIENT",
                "error": f"Found {len(func_list)} DUT API functions in '{self.target_file}'; at least {self.min_apis} are required.",
                "next_action": f"Define at least {self.min_apis} public functions whose names start with '{self.api_prefix}'.",
                "artifact": self.target_file,
                "location": self.target_file,
                "observed": {"api_count": len(func_list)},
                "expected": {
                    "minimum_api_count": self.min_apis,
                    "api_prefix": self.api_prefix,
                },
            }
        for func in func_list:
            docstring = ast.get_docstring(func, clean=False)
            if not docstring or len(docstring.strip()) == 0:
                return False, {
                    "error_code": "DUT_API_DOCSTRING_MISSING",
                    "error": f"DUT API function '{func.name}' is missing a docstring.",
                    "next_action": f"Add a docstring with 'Args:' and 'Returns:' sections to '{func.name}'.",
                    "artifact": self.target_file,
                    "location": f"{self.target_file}:{func.lineno}",
                    "observed": {"function": func.name, "docstring": None},
                    "expected": "A non-empty docstring containing 'Args:' and 'Returns:' sections.",
                }
            for doc_key in ["Args:", "Returns:"]:
                if doc_key not in docstring:
                    return False, {
                        "error_code": "DUT_API_DOCSTRING_SECTION_MISSING",
                        "error": f"DUT API function '{func.name}' is missing the '{doc_key}' docstring section.",
                        "next_action": f"Add the '{doc_key}' section to the docstring for '{func.name}'.",
                        "artifact": self.target_file,
                        "location": f"{self.target_file}:{func.lineno}",
                        "observed": {
                            "function": func.name,
                            "missing_section": doc_key,
                        },
                        "expected": "A docstring containing both 'Args:' and 'Returns:' sections.",
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
        """Validate and materialize coverage definitions outside the agent process."""

        # File existence validation
        def mk_emsg(msg):
            return {"error": msg + " Please make sure you are processing the right file."}
        target_file = self.get_path(self.cov_file)
        if not os.path.exists(target_file):
            return False, mk_emsg(f"Functional coverage file '{self.cov_file}' not found in workspace.")
        _, funcs = _python_source_definitions(
            target_file, "get_coverage_groups", "function"
        )
        if not funcs:
            return False, mk_emsg(f"No 'get_coverage_groups' functions found in '{self.cov_file}'.")
        if len(funcs) != 1:
            return False, mk_emsg(f"Multiple 'get_coverage_groups' functions found in '{self.cov_file}'. Only one is allowed.")
        get_coverage_groups = funcs[0]
        args = _python_positional_args(get_coverage_groups)
        if len(args) != 1 or args[0] != "dut":
            return False, mk_emsg(f"The 'get_coverage_groups' function in: {self.cov_file} must have one argument named 'dut', but got ({', '.join(args)}).")

        marker = "__UCAGENT_COVERAGE_PROBE_RESULT__="
        probe = r'''
import importlib.util
import json
import os
import sys

target_file, workspace, marker, import_paths_json = sys.argv[1:5]
target_dir = os.path.dirname(target_file)
import_paths = json.loads(import_paths_json)
for import_path in (target_dir, workspace):
    if import_path and import_path not in import_paths:
        import_paths.append(import_path)
sys.path[:0] = [path for path in import_paths if path not in sys.path]


class FakeDut:
    """Resolve arbitrary DUT signals without requiring a live simulator."""

    def __getattr__(self, _name):
        return self

    def __getitem__(self, _key):
        return self


try:
    from toffee.funcov import CovGroup

    spec = importlib.util.spec_from_file_location(
        "_ucagent_coverage_probe_target", target_file
    )
    if spec is None or spec.loader is None:
        raise ImportError("unable to create a module loader")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factory = getattr(module, "get_coverage_groups")
    groups = factory(FakeDut())
    if not isinstance(groups, list):
        raise TypeError(
            "get_coverage_groups must return list, got "
            + type(groups).__name__
        )
    if not groups:
        raise ValueError("get_coverage_groups returned an empty list")
    invalid = [type(group).__name__ for group in groups if not isinstance(group, CovGroup)]
    if invalid:
        raise TypeError("coverage entries must be CovGroup instances, got " + invalid[0])
    result = {"ok": True, "groups": [group.as_dict() for group in groups]}
except Exception as exc:
    result = {
        "ok": False,
        "error_type": type(exc).__name__,
        "error": str(exc)[:2000],
    }
print(marker + json.dumps(result, sort_keys=True))
'''
        child_env = os.environ.copy()
        child_env["PYTHONDONTWRITEBYTECODE"] = "1"
        current_ucagent_root = os.path.realpath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        probe_import_paths = [current_ucagent_root]
        for import_path in sys.path:
            resolved = os.path.realpath(import_path or os.getcwd())
            if os.path.isdir(resolved) and resolved not in probe_import_paths:
                probe_import_paths.append(resolved)
        try:
            with tempfile.TemporaryDirectory(
                prefix="ucagent-coverage-probe-"
            ) as pycache_dir:
                child_env["PYTHONPYCACHEPREFIX"] = pycache_dir
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        "-B",
                        "-c",
                        probe,
                        os.path.abspath(target_file),
                        os.path.abspath(self.workspace),
                        marker,
                        json.dumps(probe_import_paths),
                    ],
                    cwd=self.workspace,
                    env=child_env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
        except subprocess.TimeoutExpired:
            return False, mk_emsg(
                f"The coverage definition probe timed out for '{self.cov_file}'."
            )
        marker_index = completed.stdout.rfind(marker)
        if marker_index < 0:
            return False, mk_emsg(
                f"The isolated coverage definition probe failed for '{self.cov_file}' "
                f"with exit code {completed.returncode}. stderr: "
                f"{completed.stderr[-2000:]}"
            )
        try:
            probe_result = json.loads(
                completed.stdout[marker_index + len(marker):].strip()
            )
        except json.JSONDecodeError as exc:
            return False, mk_emsg(
                f"The isolated coverage definition probe returned invalid JSON for "
                f"'{self.cov_file}': {exc}."
            )
        if not isinstance(probe_result, dict) or not probe_result.get("ok"):
            error_type = (
                probe_result.get("error_type", "ProbeError")
                if isinstance(probe_result, dict)
                else "ProbeError"
            )
            error_message = (
                probe_result.get("error", "invalid probe result")
                if isinstance(probe_result, dict)
                else "invalid probe result"
            )
            return False, mk_emsg(
                f"The isolated coverage definition probe failed for '{self.cov_file}': "
                f"{error_type}: {error_message}"
            )
        groups = probe_result.get("groups")
        if not isinstance(groups, list) or not all(
            isinstance(group, dict) for group in groups
        ):
            return False, mk_emsg(
                f"The isolated coverage definition probe returned malformed groups for "
                f"'{self.cov_file}'."
            )
        if not groups:
            return False, mk_emsg(f"The 'get_coverage_groups' function returned no groups in target file: {self.cov_file}")
        return True, groups

    def do_check(self, timeout=0, **kw) -> Tuple[bool, str]:
        """Check the functional coverage groups against the documentation."""
        basic_pass, groups_or_msg = self.basic_check()
        if not basic_pass:
            return basic_pass, groups_or_msg
        groups = groups_or_msg
        # checks
        for ctype in self.check_types:
            doc_groups = get_doc_marks(self.get_path(self.doc_file), ctype, 1)
            ck_pass, ck_message = self._com_check_func(groups, doc_groups, ctype)
            if not ck_pass:
                return ck_pass, ck_message
        return True, f"All coverage checks [{','.join(self.check_types)}] passed."

    def _groups_as_marks(self, func_groups, ctype):
        marks = []
        def append_v(v):
            assert v not in marks, f"Duplicate mark '{v}' found in {ctype} groups."
            marks.append(v)
        for data in func_groups:
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
            return False, f"Coverage groups check fail: find {len(a)} {ctype} ({list_str_abbr(a)}) in '{self.cov_file}' but not found them in '{self.doc_file}'. {suggested_msg}"
        if len(b) > 0:
            return False, f"Coverage groups check fail: find {len(b)} {ctype} ({list_str_abbr(b)}) in '{self.doc_file}' but not found them in '{self.cov_file}'. {suggested_msg}"
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
        self.batch_task = BatchTask("check_points", self)

    def get_template_data(self):
        data = self.batch_task.get_template_data(
            "TOTAL_POINTS", "COMPLETED_POINTS", "LIST_CURRENT_POINTS"
        )
        data["LIST_CK_FILE_BLOCKS"] = "Error: CK content not find"
        if self.cached_ck_file_blocks:
            data["LIST_CK_FILE_BLOCKS"] = merge_file_blocks([{k:self.cached_ck_file_blocks.get(k, ["Error, file content not found"])} for k in data["LIST_CURRENT_POINTS"]])
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
            _, self.cached_ck_file_blocks = get_doc_marks(self.get_path(self.doc_file), "CK", 0, return_line_block=True)
        except Exception as e:
            warning(f"Error occurred while loading cached doc ck list from '{self.doc_file}': {str(e)}. Will not use cache and re-parse the document.")
        info(f"Load cached doc ck list(size={len(self.batch_task.source_task_list)}) from data key '{self.data_key}'.")
        return super().on_init()

    def do_check(self, timeout=0, is_complete=False, **kw) -> Tuple[bool, str]:
        """Check the functional coverage groups against the documentation."""
        basic_pass, groups_or_msg = self.basic_check()
        if not basic_pass:
            return basic_pass, groups_or_msg
        current_doc_ck_list, self.cached_ck_file_blocks = get_doc_marks(self.get_path(self.doc_file), "CK", 1, return_line_block=True)
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


def _get_func_params_regex(source_code: str) -> list[str]:
    """
    Extract function parameter names from the source code of a Python function using regular expressions.
    """
    pattern = r'def\s+\w+\s*\(([^)]*)\)'
    match = re.search(pattern, source_code)
    if not match:
        return []
    params_str = match.group(1).strip()
    if not params_str:
        return []
    params = []
    current = ""
    bracket_count = 0
    for char in params_str:
        if char == ',' and bracket_count == 0:
            params.append(current.strip())
            current = ""
        else:
            if char in '([{':
                bracket_count += 1
            elif char in ')]}':
                bracket_count -= 1
            current += char
    if current:
        params.append(current.strip())
    return params


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

    def _test_report_context_details(self):
        """Return Checker-specific identities for the shared current report."""

        return {}

    def _build_test_report_context(self):
        """Build the active stage/checker identity for the shared current report."""

        stage = self.get_stage()
        context = {
            "source": "checker",
            "checker_class": self.__class__.__name__,
        }
        if stage is not None:
            context["stage_name"] = stage.name
        if self.stage_manager is not None:
            context["stage_index"] = self.stage_manager.stage_index
        context.update(self._test_report_context_details())
        return context

    def _set_test_report_context(self):
        """Publish the active stage/checker identity with the next test report."""

        # Lightweight test doubles used by callers may implement only ``do``;
        # the real RunUnityChipTest runner always exposes this optional context
        # hook.  Reporting must remain usable without requiring a workspace
        # object to be imported in the checker process.
        set_context = getattr(self.run_test, "set_report_context", None)
        if set_context is not None:
            set_context(self._build_test_report_context())

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
        tc_blocks = tc_list_as_loc_blocks(test_cases.keys(),
                                             target_tc_prefix=self.args_test_func_prefix,
                                             workspace=self.workspace)
        failures = []
        def check_args(func_code_str):
            arg_list = _get_func_params_regex(func_code_str)
            warning(f"find mis-match args: {arg_list}")
            if len(arg_list) < len(self.args_pattern):
                return False
            for i, arg_pt in enumerate(self.args_pattern):
                if not fc.match_pattern_list(arg_list[i],
                                             arg_pt if isinstance(arg_pt, list) else [arg_pt]):
                    return False
            return True
        for _, v in check_file_block(tc_blocks,
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
        configured_pytest_options = self.extra_kwargs.get("pytest_options", [])
        if not isinstance(configured_pytest_options, list) or any(
            not isinstance(option, str) or not option.strip()
            for option in configured_pytest_options
        ):
            return (
                _test_function_contract_report(
                    ["pytest_options must be a list of non-empty command arguments."],
                    retry_tool="Complete" if is_complete else "Check",
                ),
                "",
                "",
            )
        if isinstance(pytest_args, str):
            pytest_args = pytest_args.split() if pytest_args else []
        else:
            pytest_args = list(pytest_args)
        pytest_args = list(configured_pytest_options) + pytest_args
        ignore_expression = self._pytest_ignore_expression()
        if ignore_expression:
            pytest_args = pytest_args if pytest_args else ["."]
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
        return get_missing_functional_coverage_message(report)

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
                f"{test_case} -> {list_str_abbr(checkpoints) if checkpoints else '[]'}"
            )

        if not missing:
            return None
        return (
            f"[API Checkpoint Association Missing] {len(missing)} API test function(s) "
            f"have no checkpoint association under '{self.api_ck_prefix}': "
            f"{list_str_abbr(missing)}. Every API test must call mark_function for the "
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
        test_pass, test_msg = is_run_report_pass(report, str_out, str_err)
        if not test_pass:
            return False, test_msg
        report_copy = clean_report_with_keys(report)
        _, func_list = _python_source_definitions(
            self.get_path(self.target_file_api), f"{self.api_prefix}*", "function"
        )
        if len(func_list) == 0:
            return False, {"error": f"No DUT API functions with prefix '{self.api_prefix}' found in '{self.target_file_api}'. "+\
                                     "Note: the api name is case-sensitive."}
        test_cases = report.get("tests", {}).get("test_cases", {})
        test_keys = test_cases.keys()
        test_functions = []
        api_un_tested = []
        for func in func_list:
            func_name = func.name
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
            return False, get_emsg(f"Missing test functions for {len(api_un_tested)} API(s): {list_str_abbr(api_un_tested)} (Defined in file: {self.target_file_api}). " + \
                                   f"Please create the missing functions: {list_str_abbr(['test_' + f for f in api_un_tested])} (format: test_<api_name>, add prefix 'test_' to the API name). " + \
                                   f"Note: All dut APIs must be defined in: {self.target_file_api}. ")
        test_count_no_check_point_mark = report.get("test_function_with_no_check_point_mark", 0)
        if test_count_no_check_point_mark > 0:
            unmarked_functions = report.get(
                "test_function_with_no_check_point_mark_list", []
            )
            mark_function_desc = description_mark_function_doc(
                unmarked_functions,
                self.workspace,
            )
            return False, get_emsg(
                "[Checkpoint Association Missing] Toffee did not record any checkpoint "
                f"association for {test_count_no_check_point_mark} executed API test "
                f"function(s): {list_str_abbr(unmarked_functions)}. "
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
        ret, msg = check_has_assert_in_tc(self.workspace, report)
        if not ret:
            return ret, get_emsg(msg["error"])
        return True, {"success": f"{self.__class__.__name__} check for {self.target_file_tests} passed."}


class UnityChipCheckerTestCase(BaseUnityChipCheckerTestCase):

    def get_zero_bug_rate_list(self):
        zero_list = []
        if not self._is_init:
            return zero_list
        try:
            for bg in get_doc_marks(os.path.join(self.workspace, self.doc_bug_analysis), leaf_node="BG"):
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
        test_pass, test_msg = is_run_report_pass(report, str_out, str_err)
        if not test_pass:
            return False, test_msg
        abs_report = copy.deepcopy(report)
        all_bins_test = report.get("all_check_point_list", [])
        abs_report = clean_report_with_keys(report)

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
            ignore_ck_prefix=self.extra_kwargs.get("ignore_ck_prefix", ""),
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

        ret, msg = check_has_assert_in_tc(self.workspace, report)
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
            success_msg.extend(description_bug_doc())
        return True, success_msg
