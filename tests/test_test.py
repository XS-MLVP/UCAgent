#coding=utf-8

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))


def test_run_unity_tests():
    """Test running Unity tests."""
    from ucagent.tools.testops import RunUnityChipTest
    tool = RunUnityChipTest(workspace=os.path.join(current_dir, "../examples/template"))
    print("Tool Name    :", tool.name)
    print("Description  :", tool.description)
    print("Args Schema  :", tool.args_schema)
    print("Return Direct:", tool.return_direct)
    
    # Invoke the tool with a test directory
    data = tool.invoke({"test_dir_or_file": "unity_tests",
                        "return_stdout": True,
                        "return_stderr": True,})
    print(data)


if __name__ == "__main__":
    test_run_unity_tests()

