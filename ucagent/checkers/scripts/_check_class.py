# -*- coding: utf-8 -*-
"""Isolated checker: class-based validation (Mock components, Bundle wrappers).

Logic extracted from UnityChipCheckerMockComponent and UnityChipCheckerBundleWrapper
— kept exactly equivalent so that both paths run the same code.
"""

import os
import ucagent.util.functions as fc
from ucagent.util.log import info


def check_mock(workspace, target_file_pattern, min_mock=1,
               checker_class_name="", **kw):
    """Check Mock component classes — equivalent to UnityChipCheckerMockComponent.do_check.

    Args:
        workspace: Absolute path to the workspace.
        target_file_pattern: File pattern (glob/regex) to find mock files.
        min_mock: Minimum number of Mock classes expected.
        checker_class_name: Class name for messages.

    Returns:
        Tuple[bool, dict]
    """
    class_count = 0
    mock_file_list = fc.find_files_by_pattern(workspace, target_file_pattern)
    for mock_file in mock_file_list:
        ret, msg = _check_mock_one_file(workspace, mock_file)
        if ret is False:
            return False, msg
        class_count += ret
    if class_count < min_mock:
        return False, {
            "error": f"Insufficient Mock component coverage: {class_count} Mock classes found, minimum required is {min_mock}. " +
                     f"You need to define Mock components like: 'class Mock<COMPONENT_NAME>:'. in files: {target_file_pattern}. " +
                     f"Review your task details and ensure that the Mock components are defined correctly in the target files.",
        }
    return True, {"message": f"{checker_class_name} check for {target_file_pattern} ({len(mock_file_list)} files) passed."}


def _check_mock_one_file(workspace, mock_file):
    """Check Mock classes in a single file — equivalent to do_check_one_file."""
    abs_path = os.path.join(workspace, mock_file) if not os.path.isabs(mock_file) else mock_file
    if not os.path.exists(abs_path):
        return False, {"error": f"Mock component file '{mock_file}' does not exist. " +
                       f"You need to define Mock components like: 'class Mock<COMPONENT_NAME>:' in the target file: {mock_file}. "}

    class_list = fc.get_target_from_file(abs_path, "Mock*",
                                         ex_python_path=workspace, dtype="CLASS")
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
    return len(class_list), {"message": f"check for {mock_file} passed."}


def check_bundle(target_file_path, workspace, min_bundles=1,
                 checker_class_name="", **kw):
    """Check Bundle wrapper classes — equivalent to UnityChipCheckerBundleWrapper.do_check.

    Args:
        target_file_path: Absolute path to the bundle file.
        workspace: Absolute path to the workspace.
        min_bundles: Minimum number of Bundle classes expected.
        checker_class_name: Class name for messages.

    Returns:
        Tuple[bool, dict]
    """
    target_file = target_file_path
    if not os.path.exists(target_file_path):
        return False, {"error": f"Bundle wrapper file '{target_file}' does not exist." +
                       f"You need to define Bundle wrappers like: 'class <Name>(Bundle):' in the target file: {target_file}. "}

    bundle_list = fc.get_target_from_file(target_file_path, "*",
                                          ex_python_path=workspace, dtype="CLASS")
    for icls in bundle_list[:]:
        bases = [base.__name__ for base in icls.__bases__]
        if "Bundle" not in bases:
            bundle_list.remove(icls)

    if len(bundle_list) < min_bundles:
        return False, {
            "error": f"Insufficient Bundle wrapper coverage: {len(bundle_list)} Bundle classes found, minimum required is {min_bundles}. " +
                     f"You need to define Bundle wrappers like: 'class <Name>(Bundle):' in the target file: {target_file}. " +
                     f"Please refer to the documentation for more details."
        }
    return True, {"message": f"{checker_class_name} check for {target_file} passed."}
