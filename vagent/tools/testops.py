#coding=utf-8

from langchain_core.callbacks import (
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field

import os
from typing import List
from vagent.util.functions import get_sub_str, str_remove_blank, str_replace_to


def parse_nested_keys(target_file: str, keyname_list: List[str], prefix_list: List[str], subfix_list: List[str],
                      ignore_chars: List[str] = ["/", "<", ">"]) -> dict:
    """Parse the function points and checkpoints from a file."""
    assert os.path.exists(target_file), f"File {target_file} does not exist. You need to provide a valid file path."
    assert len(keyname_list) > 0, "Prefix must be provided."
    assert len(prefix_list) == len(subfix_list), "Prefix and subfix lists must have the same length."
    assert len(prefix_list) == len(keyname_list), "Prefix and keyname lists must have the same length."
    pre_values = [None] * len(prefix_list)
    key_dict = {}
    def get_pod_next_key(i: int):
        nkey = keyname_list[i+1] if i < len(keyname_list) - 1 else None
        if i == 0:
            return key_dict, nkey
        return pre_values[i - 1][keyname_list[i]], nkey
    with open(target_file, 'r') as f:
        index = 0
        lines = f.readlines()
        for line in lines:
            line = str_remove_blank(line.strip())
            for i, key in enumerate(keyname_list):
                prefix = prefix_list[i]
                subfix = subfix_list[i]
                pre_key = keyname_list[i - 1] if i > 0 else None
                pre_prf = prefix_list[i - 1] if i > 0 else None
                if not prefix in line:
                    continue
                assert line.count(prefix) == 1, f"at line ({index}): '{line}' should contain exactly one {key} '{prefix}'"
                current_key = str_replace_to(get_sub_str(line, prefix, subfix), ignore_chars, "")
                pod, next_key = get_pod_next_key(i)
                assert pod is not None, f"at line ({index}): contain {key} '{prefix}' but it do not find its parent {pre_key} '{pre_prf}' in previous lines."
                assert next_key != "line", f"at line ({index}): '{line}' should not contain 'line' as a key, it is reserved for line numbers."
                assert current_key not in pod, f"{key} '{prefix}' is defined multiple times. find it in line {index} again."
                pod[current_key] = {"line": index}
                if next_key is not None:
                    pod[current_key][next_key] = {}
                pre_values[i] = pod[current_key]
            index += 1
    return key_dict


class ArgRunPyTest(BaseModel):
    """Arguments for running a Python test."""
    test_dir_or_file: str = Field(
        ...,
        description="The directory or file containing the Python tests to run."
    )


class RunPyTest(BaseTool):
    """Tool to run pytest tests in a specified directory or a test file."""

    name: str = "RunPyTest"
    description: str = "Run pytest tests in a specified directory or a test file."
    args_schema: ArgsSchema = ArgRunPyTest
    return_direct: bool = False

    # custom variables
    pytest_args: dict = Field(
        default={},
        description="Additional arguments to pass to pytest, e.g., {'verbose': True, 'capture': 'no'}."
    )

    def _run(self, test_dir_or_file: str, run_manager: CallbackManagerForToolRun = None) -> str:
        """Run the Python tests."""
        import subprocess

        try:
            result = subprocess.run(
                ["pytest", test_dir_or_file, *self.get_pytest_args()],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            return f"Error running tests: {e.stderr}"
    
    def get_pytest_args(self) -> list:
        """Get additional arguments for pytest."""
        args = []
        for key, value in self.pytest_args.items():
            if isinstance(value, bool):
                if value:
                    args.append(f"--{key}")
            else:
                args.append(f"--{key}={value}")
        return args

    def set_pytest_args(self, **kwargs):
        """Set additional arguments for pytest."""
        self.pytest_args.update(kwargs)
        return self


class RunUnityChipTest(RunPyTest):
    """Tool to run tests in a specified directory or a test file."""

    name: str = "RunUnityChipTest"
    description: str = ("Run tests in a specified directory or a test file. "
                        "This tool is specifically designed for Unity chip tests, "
                        "which are typically run using the Unity test framework.\n"
                        "Afert running the tests, it will return:\n"
                        "- The terminal output of the test run.\n"
                        "- How many function points and its checkpoints are captured.\n"
                        "- The functional coverage of the tests.\n"
                        "- The code coverage of the tests.\n"
                        "- If the tests pass or fail.\n"
                        )

    # custom variables
    result_json_path: str = Field(
        default="unity_test_results.json",
        description="Path to save the JSON results of the Unity tests."
    )
    result_function_list_file: str = Field(
        default="unity_function_list.md",
        description="Path to the function point list file, which contains the function points and checkpoints defined to the tests."
    )
    min_function_points: int = Field(
        default=0,
        description="Minimum number of function points expected to be captured by the tests."
    )
    min_checkpoints: int = Field(
        default=0,
        description="Minimum number of checkpoints for each function point expected to be captured by the tests."
    )
    def _run(self, test_dir_or_file: str, run_manager: CallbackManagerForToolRun = None) -> str:
        """Run the Unity chip tests."""
        # Assuming Unity tests are run with a specific command
        stdout = super(RunPyTest, self)._run(test_dir_or_file, run_manager)
