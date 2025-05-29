#coding=utf-8

from langchain_core.callbacks import (
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field

import os

from vagent.util.functions import get_sub_str, str_remove_blank, str_replace_to


def parse_function_points_and_checkpoints(function_list_file: str,
                                          func_prefix: str,
                                          func_subfix: str,
                                          check_prefix: str,
                                          check_subfix: str,
                                          ignore_chars: list = ["/", "<", ">"]
                                          ) -> dict:
    """Parse the function points and checkpoints from a file."""
    assert os.path.exists(function_list_file), f"Function list file {function_list_file} does not exist. You need to provide a valid file path."
    assert func_prefix, "Function prefix must be provided."
    assert check_prefix, "Checkpoint prefix must be provided."
    function_points = {}
    with open(function_list_file, 'r') as f:
        index = 0
        lines = f.readlines()
        current_function = None
        for line in lines:
            line = str_remove_blank(line.strip())
            if func_prefix in line:
                # New function point
                assert not check_prefix in line, f"Function point line ({index}): '{line}' should not contain check point prefix: '{check_prefix}'"
                assert line.count(func_prefix) == 1, f"Function point line ({index}): '{line}' should contain exactly one '{func_prefix}'"
                current_function = str_replace_to(get_sub_str(line, func_prefix, func_subfix), ignore_chars, "")
                assert current_function not in function_points, f"Function point '{current_function}' is defined multiple times. find it in line {index} again."
                function_points[current_function] = {"line": index,
                                                     "checkpoints": {}}
            elif check_prefix in line:
                # Checkpoint for the current function point
                assert current_function is not None, f"Checkpoint line ({index}): '{line}' should be after a function point line."
                assert line.count(check_prefix) == 1, f"Checkpoint line ({index}): '{line}' should contain exactly one '{check_prefix}'"
                check_point = str_replace_to(get_sub_str(line, check_prefix, check_subfix), ignore_chars, "")
                assert check_point not in function_points[current_function]["checkpoints"], f"Checkpoint '{check_point}' "+\
                                                   f"is defined multiple times for function point '{current_function}'."
                function_points[current_function]["checkpoints"][check_point] = index
            index += 1
    return function_points


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
