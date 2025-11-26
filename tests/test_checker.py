#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test cases for checker modules."""

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))


from ucagent.checkers import *
from ucagent.util.functions import yam_str


def test_markdown_checker():
    workspace = os.path.join(current_dir, "../examples/ALU")
    checker = UnityChipCheckerMarkdownFileFormat(
        markdown_file_list=["unity_test/ALU_functions_and_checks.md"]
    ).set_workspace(workspace)
    p, m = checker.do_check()
    print(p)
    print(yam_str(m))


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
    checker = UnityChipCheckerDutApi("api_ALU", "unity_test/tests/ALU_api.py", 1).set_workspace(workspace)
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


def test_coverage():
    workspace = os.path.join(current_dir, "../examples/ALU")
    checker = UnityChipCheckerCoverageGroup("unity_test/tests",
                                            "unity_test/tests/ALU_function_coverage_def.py",
                                            "unity_test/ALU_functions_and_checks.md", "FG").set_workspace(workspace)
    p, m = checker.do_check()
    print(p)
    print(yam_str(m))
    checker = UnityChipCheckerCoverageGroup("unity_test/tests",
                                            "unity_test/tests/ALU_function_coverage_def.py",
                                            "unity_test/ALU_functions_and_checks.md", "FC").set_workspace(workspace)
    p, m = checker.do_check()
    print(p)
    print(yam_str(m))
    checker = UnityChipCheckerCoverageGroup("unity_test/tests",
                                            "unity_test/tests/ALU_function_coverage_def.py",
                                            "unity_test/ALU_functions_and_checks.md", ["FC", "CK"]).set_workspace(workspace)
    p, m = checker.do_check()
    print(p)
    print(yam_str(m))


def test_checker_test_case():
    """Test the UnityChipCheckerTestCase class."""
    workspace = os.path.join(current_dir, "../examples/ALU")

    for cls in [UnityChipCheckerTestTemplate,
                UnityChipCheckerTestFree,
                UnityChipCheckerTestCase]:
        print("cls:", cls.__name__)
        checker = cls("unity_test/ALU_functions_and_checks.md",
                      "unity_test/tests",
                      "unity_test/ALU_bug_analysis.md"
                      ).set_workspace(workspace)
        p, m = checker.do_check()
        print(p)
        print(yam_str(m))


def test_checker_api_test():
    workspace = os.path.join(current_dir, "../examples/ALU")
    Checker = UnityChipCheckerDutApiTest(
        "api_ALU_", "unity_test/tests/ALU_api.py", "unity_test/tests/test_ALU_api*.py", "unity_test/ALU_functions_and_checks.md", "unity_test/ALU_bug_analysis.md"
    ).set_workspace(workspace)
    p, m = Checker.do_check()
    print(p)
    print(yam_str(m))


def test_checker_line_coverage():
    workspace = os.path.join(current_dir, "../output")
    dut = "Adder"
    kw = {
        "min_line_coverage": 0.8,
        "dut_name": dut,
        "cfg": {
            "_temp_cfg.DUT": dut
        }
    }
    checker = UnityChipCheckerTestCaseWithLineCoverage(
        f"unity_test/{dut}_functions_and_checks.md",
        "unity_test/tests",
        f"unity_test/{dut}_bug_analysis.md",
        **kw
    ).set_workspace(workspace)
    p, m = checker.do_check()
    print(p)
    print(yam_str(m))


if __name__ == "__main__":
    #test_markdown_checker()
    #test_checker_functions_and_checks()
    #test_checker_dut_api()
    #test_coverage()
    #test_checker_test_case()
    #test_checker_api_test()
    test_checker_line_coverage()
