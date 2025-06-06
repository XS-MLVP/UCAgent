#coding=utf-8

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))


from vagent.stage.checkers import UnityChipCheckerFunctionsAndChecks
from vagent.stage.checkers import UnityChipCheckerDutApi
from vagent.stage.checkers import UnityChipCheckerCoverGroup
from vagent.stage.checkers import UnityChipCheckerTestCase


def test_checker_functions_and_checks():
    """Test the UnityChipCheckerFunctionsAndChecks class."""
    workspace = os.path.join(current_dir, "../examples/ALU")
    checker = UnityChipCheckerFunctionsAndChecks("unity_test/alu_functions_and_checks.md", 2, 2).set_workspace(workspace)
    p, m = checker.do_check()
    print(p)
    print(m)


def test_checker_dut_api():
    """Test the UnityChipCheckerDutApi class."""
    workspace = os.path.join(current_dir, "../examples/ALU")
    checker = UnityChipCheckerDutApi("unity_test/tests/alu_api.py", 1).set_workspace(workspace)
    p, m = checker.do_check()
    print(p)
    print(m)


def test_checker_cover_group():
    """Test the UnityChipCheckerCoverGroup class."""
    workspace = os.path.join(current_dir, "../examples/ALU")
    checker = UnityChipCheckerCoverGroup("unity_test/tests", "unity_test/tests/alu_function_coverage_def.py", 1).set_workspace(workspace)
    p, m = checker.do_check()
    print(p)
    print(m)


def test_checker_test_case():
    """Test the UnityChipCheckerTestCase class."""
    workspace = os.path.join(current_dir, "../examples/ALU")
    checker = UnityChipCheckerTestCase("unity_test/alu_functions_and_checks.md", "unity_test/alu_bug_analysis.md", "unity_test/tests", 2).set_workspace(workspace)
    p, m = checker.do_check()
    print(p)
    print(m)


if __name__ == "__main__":
    test_checker_functions_and_checks()
    test_checker_dut_api()
    test_checker_cover_group()
    test_checker_test_case()
