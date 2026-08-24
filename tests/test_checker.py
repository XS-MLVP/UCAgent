#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-contained tests for representative checker modules."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ucagent.checkers import (
    UnityChipCheckerCoverageGroup,
    UnityChipCheckerDutApi,
    UnityChipCheckerDutApiTest,
    UnityChipCheckerDutCreation,
    UnityChipCheckerDutFixture,
    UnityChipCheckerLabelStructure,
    UnityChipCheckerMarkdownFileFormat,
    UnityChipCheckerTestCase,
    UnityChipCheckerTestCaseWithLineCoverage,
    UnityChipCheckerTestFree,
    UnityChipCheckerTestTemplate,
)
from ucagent.checkers.base import Checker


CHECKPOINT = "FG-API/FC-OPERATE/CK-BASIC"
TEST_NODE = "unity_test/tests/test_Demo.py:1-2::test_demo"
API_TEST_NODE = "unity_test/tests/test_Demo_api.py:1-2::test_api_Demo_operate"


def _write_workspace_files(tmp_path):
    test_dir = tmp_path / "unity_test" / "tests"
    test_dir.mkdir(parents=True)
    (tmp_path / "unity_test" / "Demo_functions_and_checks.md").write_text(
        "# Demo functions and checks\n\n"
        "### API group <FG-API>\n"
        "#### Operate <FC-OPERATE>\n"
        "##### Basic operation <CK-BASIC>\n",
        encoding="utf-8",
    )
    (tmp_path / "unity_test" / "Demo_bug_analysis.md").write_text(
        "# Demo bug analysis\n\n"
        "<DYNAMIC-BUGS>\n"
        "</DYNAMIC-BUGS>\n\n"
        "<WAVEFORM-EVIDENCE>\n"
        "</WAVEFORM-EVIDENCE>\n",
        encoding="utf-8",
    )
    (test_dir / "test_Demo.py").write_text(
        "def test_demo(env):\n"
        "    assert env is not None\n",
        encoding="utf-8",
    )
    (test_dir / "test_Demo_api.py").write_text(
        "def test_api_Demo_operate(env):\n"
        "    assert env is not None\n",
        encoding="utf-8",
    )
    return test_dir


def _passing_report(test_node=TEST_NODE):
    return {
        "run_test_success": True,
        "total_funct_point": 1,
        "total_check_point": 1,
        "test_function_with_no_check_point_mark": 0,
        "test_function_with_no_check_point_mark_list": [],
        "all_check_point_list": [CHECKPOINT],
        "failed_check_point_list": [],
        "failed_test_case_with_check_point_list": {},
        "test_case_with_check_point_list": {test_node: [CHECKPOINT]},
        "unmarked_check_points": 0,
        "unmarked_check_point_list": [],
        "tests": {
            "total": 1,
            "fails": 0,
            "test_cases": {test_node: "PASSED"},
        },
    }


def _set_report(checker, report):
    checker.run_test = SimpleNamespace(
        set_workspace=lambda _workspace: None,
        set_pre_call_back=lambda _callback: None,
        do=lambda *args, **kwargs: (report, "", ""),
    )


def test_markdown_checker_uses_temporary_workspace(tmp_path):
    _write_workspace_files(tmp_path)
    checker = UnityChipCheckerMarkdownFileFormat(
        markdown_file_list=["unity_test/Demo_functions_and_checks.md"]
    ).set_workspace(str(tmp_path))

    passed, message = checker.do_check()

    assert passed is True
    assert "check pass" in message["message"]


def test_checker_functions_and_checks_uses_temporary_workspace(tmp_path):
    _write_workspace_files(tmp_path)
    checker = UnityChipCheckerLabelStructure(
        "unity_test/Demo_functions_and_checks.md",
        "FG",
    ).set_workspace(str(tmp_path))

    passed, message = checker.do_check()

    assert passed is True
    assert message["FG_count"] == 1


def test_checker_dut_api_and_fixtures_use_temporary_workspace(tmp_path):
    test_dir = _write_workspace_files(tmp_path)
    api_file = test_dir / "Demo_api.py"
    api_file.write_text(
        "import pytest\n\n"
        "class FakeDUT:\n"
        "    def Step(self):\n"
        "        pass\n\n"
        "    def StepRis(self):\n"
        "        pass\n\n"
        "class DUTDemo:\n"
        "    pass\n\n"
        "class UCAgentStub:\n"
        "    @staticmethod\n"
        "    def is_imp_test_template():\n"
        "        return False\n\n"
        "    @staticmethod\n"
        "    def get_fake_dut(_dut_class):\n"
        "        return FakeDUT()\n\n"
        "ucagent = UCAgentStub()\n\n"
        "def get_coverage_data_path(request, new_path):\n"
        "    return 'coverage.dat'\n\n"
        "def set_func_coverage(request, groups):\n"
        "    pass\n\n"
        "def create_dut(request):\n"
        "    get_coverage_data_path(request, new_path=True)\n"
        "    if ucagent.is_imp_test_template():\n"
        "        return ucagent.get_fake_dut(DUTDemo)\n"
        "    return FakeDUT()\n\n"
        "@pytest.fixture(scope='function')\n"
        "def dut(request):\n"
        "    groups = []\n"
        "    get_coverage_data_path(request, new_path=False)\n"
        "    yield FakeDUT()\n"
        "    set_func_coverage(request, groups)\n\n"
        "def api_Demo_operate(env, value, max_cycles=10):\n"
        "    \"\"\"Run one operation.\n\n"
        "    Args:\n"
        "        env: Verification environment.\n"
        "        value: Input value.\n"
        "        max_cycles: Timeout.\n\n"
        "    Returns:\n"
        "        The input value.\n"
        "    \"\"\"\n"
        "    return value\n",
        encoding="utf-8",
    )
    target = "unity_test/tests/Demo_api.py"
    cfg = {"_temp_cfg": {"DUT": "Demo"}}
    checkers = (
        UnityChipCheckerDutApi("api_Demo", target, 1),
        UnityChipCheckerDutCreation(target, cfg=cfg),
        UnityChipCheckerDutFixture(target, cfg=cfg),
    )

    results = [checker.set_workspace(str(tmp_path)).do_check() for checker in checkers]

    assert all(passed for passed, _message in results)
    assert all("passed" in str(message) for _passed, message in results)


def test_coverage_checker_uses_temporary_workspace(tmp_path):
    test_dir = _write_workspace_files(tmp_path)
    (test_dir / "Demo_function_coverage_def.py").write_text(
        "from toffee.funcov import CovGroup\n\n"
        "def get_coverage_groups(dut):\n"
        "    group = CovGroup('FG-API')\n"
        "    group.add_watch_point(\n"
        "        dut,\n"
        "        {'CK-BASIC': lambda target: True},\n"
        "        name='FC-OPERATE',\n"
        "    )\n"
        "    return [group]\n",
        encoding="utf-8",
    )
    checker = UnityChipCheckerCoverageGroup(
        "unity_test/tests",
        "unity_test/tests/Demo_function_coverage_def.py",
        "unity_test/Demo_functions_and_checks.md",
        ["FG", "FC", "CK"],
    ).set_workspace(str(tmp_path))

    passed, message = checker.do_check()

    assert passed is True
    assert message == "All coverage checks [FG,FC,CK] passed."


def test_test_case_checkers_use_mocked_report_in_temporary_workspace(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(Checker, "_cb_list", {})
    _write_workspace_files(tmp_path)
    functions_doc = "unity_test/Demo_functions_and_checks.md"
    tests_dir = "unity_test/tests"
    bug_doc = "unity_test/Demo_bug_analysis.md"

    free_checker = UnityChipCheckerTestFree(
        functions_doc,
        tests_dir,
        bug_doc,
    ).set_workspace(str(tmp_path))
    _set_report(free_checker, _passing_report())
    free_passed, free_message = free_checker.do_check()

    template_report = _passing_report()
    template_report["tests"]["test_cases"][TEST_NODE] = "FAILED"
    template_report["tests"]["fails"] = 1
    template_report["tests"]["test_case_details"] = {
        TEST_NODE: {
            "status": "FAILED",
            "phase": "call",
            "exception_type": "AssertionError",
            "exception": "AssertionError('Not implemented')",
        }
    }
    template_checker = UnityChipCheckerTestTemplate(
        functions_doc,
        tests_dir,
        bug_doc,
    ).set_workspace(str(tmp_path))
    template_checker.on_init()
    _set_report(template_checker, template_report)
    template_passed, template_message = template_checker.do_check()

    case_checker = UnityChipCheckerTestCase(
        functions_doc,
        tests_dir,
        bug_doc,
    ).set_workspace(str(tmp_path))
    _set_report(case_checker, _passing_report())
    case_passed, case_message = case_checker.do_check()

    assert free_passed is True
    assert "REPORT" in free_message
    assert template_passed is True
    assert "success" in template_message
    assert case_passed is True, case_message
    assert "Test case verification passed" in " ".join(case_message)


def test_checker_api_test_uses_mocked_report_in_temporary_workspace(tmp_path):
    test_dir = _write_workspace_files(tmp_path)
    (test_dir / "Demo_api.py").write_text(
        "def api_Demo_operate(env, max_cycles=10):\n"
        "    return None\n",
        encoding="utf-8",
    )
    checker = UnityChipCheckerDutApiTest(
        "api_Demo_",
        "unity_test/tests/Demo_api.py",
        "unity_test/tests/test_Demo_api*.py",
        "unity_test/Demo_functions_and_checks.md",
        "unity_test/Demo_bug_analysis.md",
    ).set_workspace(str(tmp_path))
    _set_report(checker, _passing_report(API_TEST_NODE))

    passed, message = checker.do_check()

    assert passed is True, message
    assert "passed" in message["success"]


def test_checker_line_coverage_uses_temporary_workspace(tmp_path, monkeypatch):
    coverage_file = tmp_path / "uc_test_report" / "line_dat" / "code_coverage.json"
    coverage_file.parent.mkdir(parents=True)
    coverage_file.write_text(
        json.dumps({
            "overview": {
                "total": {"line": 10},
                "miss": {"line": 1},
            },
            "uncovered": {"data": {}},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        UnityChipCheckerTestCase,
        "do_check",
        lambda self, timeout=0, **kwargs: (True, "Test case check passed."),
    )
    checker = UnityChipCheckerTestCaseWithLineCoverage(
        "unity_test/Demo_functions_and_checks.md",
        "unity_test/tests",
        "unity_test/Demo_bug_analysis.md",
        cfg={"_temp_cfg": {"DUT": "Demo"}},
        min_line_coverage=0.8,
    ).set_workspace(str(tmp_path))

    passed, message = checker.do_check()

    assert passed is True
    assert "90.00% >= 80.00%" in message
    assert checker.cur_line_coverage == 0.9
