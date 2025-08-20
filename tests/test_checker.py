#coding=utf-8

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))


from vagent.stage.checkers import *
from vagent.util.functions import yam_str


def test_checker_functions_and_checks():
    """Test the UnityChipCheckerFunctionsAndChecks class."""
    workspace = os.path.join(current_dir, "../examples/ALU")
    checker = UnityChipCheckerLabelStructure("unity_test/ALU_functions_and_checks.md", "FG").set_workspace(workspace)
    p, m = checker.do_check()
    print(p)
    print(yam_str(m))


def test_checker_dut_api():
    """Test the UnityChipCheckerDutApi class."""
    workspace = os.path.join(current_dir, "../examples/ALU")
    checker = UnityChipCheckerDutApi("unity_test/tests/ALU_api.py", 1).set_workspace(workspace)
    p, m = checker.do_check()
    print(p)
    print(yam_str(m))
    checker_creation = UnityChipCheckerDutCreation("unity_test/tests/ALU_api.py").set_workspace(workspace)
    p_creation, m_creation = checker_creation.do_check()
    print(p_creation)
    print(yam_str(m_creation))
    checker_fixture = UnityChipCheckerDutFixture("unity_test/tests/ALU_api.py").set_workspace(workspace)
    p_fixture, m_fixture = checker_fixture.do_check()
    print(p_fixture)
    print(yam_str(m_fixture))


def test_checker_test_case():
    """Test the UnityChipCheckerTestCase class."""
    workspace = os.path.join(current_dir, "../examples/ALU")
    checker = UnityChipCheckerTestCase("unity_test/alu_functions_and_checks.md", "unity_test/alu_bug_analysis.md", "unity_test/tests", 2).set_workspace(workspace)
    p, m = checker.do_check()
    print(p)
    print(m)


if __name__ == "__main__":
    #test_checker_functions_and_checks()
    test_checker_dut_api()
    #test_checker_test_case()
