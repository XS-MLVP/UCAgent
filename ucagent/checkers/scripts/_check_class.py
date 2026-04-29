#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared check logic for class validation — extracted from origin/main do_check."""

import ucagent.util.functions as fc


def check_classes(target_file_path, workspace, class_pattern="*",
                  base_class_name=None, min_count=1):
    """Validate class definitions, returns (bool, dict).

    Args:
        target_file_path: Absolute path to the target file.
        workspace: Workspace directory path.
        class_pattern: Pattern to match class names.
        base_class_name: Filter by base class name (e.g. "Bundle").
        min_count: Minimum number of matching classes.

    Returns:
        (success: bool, result: dict)
    """
    class_list = fc.get_target_from_file(target_file_path, class_pattern,
                                         ex_python_path=workspace,
                                         dtype="CLASS")
    if base_class_name:
        class_list = [cls for cls in class_list
                      if base_class_name in [b.__name__ for b in cls.__bases__]]

    if len(class_list) < min_count:
        return False, {
            "error": f"Insufficient coverage: {len(class_list)} classes found matching "
                     f"pattern '{class_pattern}'"
                     + (f" with base '{base_class_name}'" if base_class_name else "")
                     + f", minimum required is {min_count}.",
            "classes_found": len(class_list),
            "class_names": [cls.__name__ for cls in class_list],
        }
    return True, {
        "classes_found": len(class_list),
        "class_names": [cls.__name__ for cls in class_list],
    }
