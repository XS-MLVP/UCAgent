# -*- coding: utf-8 -*-
"""UnityTest DUT source generation Checkers."""

import ast
import os
from typing import Tuple

import ucagent.util.functions as fc
from ucagent.checkers.base import Checker
from ucagent.util.log import info
from .unity_test import (
    UnityChipCheckerBaseFixture,
    _ast_qualified_name,
    _python_definition_source,
    _python_positional_args,
    _python_source_definitions,
)
from unitytest_plugin.report_utils import tips_of_get_coverage_data_path


# ---------------------------------------------------------------------------
# Checker - DUT top-level creation
# ---------------------------------------------------------------------------

class UnityChipCheckerDutCreation(Checker):
    def __init__(self, target_file, **kw):
        super().__init__()
        self.target_file = target_file
        self.update_dut_name(kw["cfg"])
        ucagent_msg = f"You need use:\n`from ucagent_common import test_utils`\n`if test_utils.is_imp_test_template():\n" + \
                      f"    return test_utils.get_fake_dut(DUT{self.dut_name})`\n in 'create_dut' function."
        self.source_code_need = {
            "get_coverage_data_path": (f"The 'create_dut' function in '{self.target_file}' must call 'get_coverage_data_path(request, dut, new_path=True)' to get a new coverage file path.", tips_of_get_coverage_data_path),
            "test_utils.is_imp_test_template": (ucagent_msg, None),
            "test_utils.get_fake_dut":(ucagent_msg, None)
        }

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Check the DUT creation function for correctness."""
        if not os.path.exists(self.get_path(self.target_file)):
            return False, {"error": f"file '{self.target_file}' does not exist."}
        source, func_list = _python_source_definitions(
            self.get_path(self.target_file), "create_dut", "function"
        )
        if not func_list:
            return False, {"error": f"No 'create_dut' functions found in '{self.target_file}'."}
        if len(func_list) != 1:
            return False, {"error": f"Multiple 'create_dut' functions found in '{self.target_file}'. Expected only one."}
        cdut_func = func_list[0]
        args = _python_positional_args(cdut_func)
        # check args
        if len(args) != 1 or args[0] != "request":
            return False, {"error": f"The 'create_dut' fixture has only one arg named 'request', but got ({', '.join(args)})."}
        # check 'get_coverage_data_path'
        func_source = _python_definition_source(source, cdut_func)
        for k, (v, f) in self.source_code_need.items():
            message = v
            if f:
                message += f" {f(self.dut_name)}"
            if k not in func_source:
                return False, {"error":  message}
        # Additional checks can be implemented here
        return True, {"message": f"{self.__class__.__name__} check for {self.target_file} passed."}


# ---------------------------------------------------------------------------
# Checker - mock components
# ---------------------------------------------------------------------------

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
        """Statically validate Mock classes in one workspace source file."""

        if not os.path.exists(self.get_path(mock_file)):
            return False, {"error": f"Mock component file '{mock_file}' does not exist. " + \
                           f"You need to define Mock components like: 'class Mock<COMPONENT_NAME>:' in the target file: {mock_file}. "}
        _, class_list = _python_source_definitions(
            self.get_path(mock_file), "Mock*", "class"
        )
        if len(class_list) < 1:
            return False, {
                "error": f"No Mock component class found in file: {mock_file}, You need to define Mock components like: 'class Mock<COMPONENT_NAME>:' in the file: {mock_file}.  ",
            }
        # check on_clock_edge
        for cls in class_list:
            methods = [
                node
                for node in cls.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "on_clock_edge"
            ]
            if not methods:
                return False, {
                    "error": f"The Mock class '{cls.name}' in file: {mock_file} is missing the required method 'on_clock_edge(self, cycles)'. Please implement this method to handle clock edge events."
                }
            args = _python_positional_args(methods[0])
            if len(args) != 2 or args[0] != "self" or args[1] != "cycles":
                return False, {
                    "error": f"The 'on_clock_edge' method in Mock class '{cls.name}' in file {mock_file} must have exactly two arguments: 'self' and 'cycles', but got ({', '.join(args)})."
                }
        info(f"find {len(class_list)} Mock classes in file: {mock_file}.")
        return len(class_list), {"message": f"{self.__class__.__name__} check for {mock_file} passed."}


# ---------------------------------------------------------------------------
# Checker - bundle wrappers
# ---------------------------------------------------------------------------

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
        _, class_list = _python_source_definitions(
            self.get_path(self.target_file), "*", "class"
        )
        bundle_list = [
            definition
            for definition in class_list
            if "Bundle" in {
                _ast_qualified_name(base).rsplit(".", 1)[-1]
                for base in definition.bases
            }
        ]
        if len(bundle_list) < self.min_bundles:
            return False, {
                "error": f"Insufficient Bundle wrapper coverage: {len(bundle_list)} Bundle classes found, minimum required is {self.min_bundles}. " +\
                         f"You need to define Bundle wrappers like: 'class <Name>(Bundle):' in the target file: {self.target_file}. " + \
                         f"Please refer to the documentation for more details."
            }
        return True, {"message": f"{self.__class__.__name__} check for {self.target_file} passed."}


# ---------------------------------------------------------------------------
# Checker - mock fixture
# ---------------------------------------------------------------------------

class UnityChipCheckerMockFixture(UnityChipCheckerBaseFixture):
    def __init__(self, target_file, min_count=1, **kw):
        super().__init__(target_file, "mock_dut", min_count=min_count, **kw)
        self.update_dut_name(kw["cfg"])
        ucagent_msg = f"You need use:\n`from ucagent_common import test_utils`\n`def mock_dut():\n    return test_utils.get_mock_dut_from(DUT{self.dut_name})\n` in 'mock_dut' fixture."
        self.source_code_need = {
            "test_utils.get_mock_dut_from": (ucagent_msg, None)
        }

