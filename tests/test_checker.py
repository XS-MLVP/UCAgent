#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-contained tests for representative checker modules."""

import json
import pytest
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
from ucagent.checkers.base import Checker, UnityChipBatchTask
from ucagent.checkers.unity_test import BaseUnityChipCheckerTestCase
from ucagent.util.config import Config


CHECKPOINT = "FG-API/FC-OPERATE/CK-BASIC"
TEST_NODE = "unity_test/tests/test_Demo.py:1-2::test_demo"
API_TEST_NODE = "unity_test/tests/test_Demo_api.py:1-2::test_api_Demo_operate"


def test_checker_lifecycle_callbacks_are_isolated_per_instance():
    class _BatchChecker(Checker):
        def __init__(self, batch_name):
            super().__init__()
            assert self._cb_list == {}
            self.batch_size = 1
            self.batch_task = UnityChipBatchTask(batch_name, self)

    first = _BatchChecker("first")
    second = _BatchChecker("second")
    calls = []
    first.batch_task.on_init = lambda: calls.append("first")
    second.batch_task.on_init = lambda: calls.append("second")

    first.set_stage(SimpleNamespace(name="first-stage"))
    assert calls == ["first"]

    second.set_stage(SimpleNamespace(name="second-stage"))
    assert calls == ["first", "second"]
    assert first._cb_list is not second._cb_list


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
        "\n# Demo dynamic Bug analysis\n\n"
        "## Dynamic Bug records\n\n"
        "<DYNAMIC-BUGS>\n"
        "</DYNAMIC-BUGS>\n\n"
        "## Root cause analysis\n\n"
        "<ROOT-CAUSES>\n"
        "</ROOT-CAUSES>\n\n"
        "## Waveform evidence\n\n"
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
        "unhit_check_point_list": [],
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
        "def get_coverage_data_path(request, dut, new_path):\n"
        "    return 'coverage.dat'\n\n"
        "def set_func_coverage(request, groups):\n"
        "    pass\n\n"
        "def create_dut(request):\n"
        "    get_coverage_data_path(request, dut, new_path=True)\n"
        "    if ucagent.is_imp_test_template():\n"
        "        return ucagent.get_fake_dut(DUTDemo)\n"
        "    return FakeDUT()\n\n"
        "@pytest.fixture(scope='function')\n"
        "def dut(request):\n"
        "    groups = []\n"
        "    get_coverage_data_path(request, dut, new_path=False)\n"
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


def test_dut_api_checker_returns_structured_failure_diagnostics(tmp_path):
    """Every DUT API source failure provides a bounded, actionable diagnostic."""

    test_dir = tmp_path / "unity_test" / "tests"
    test_dir.mkdir(parents=True)
    target = "unity_test/tests/Demo_api.py"
    target_path = tmp_path / target
    checker = UnityChipCheckerDutApi("api_Demo", target, 1).set_workspace(str(tmp_path))

    passed, diagnostic = checker.do_check()
    assert passed is False
    assert diagnostic["error_code"] == "DUT_API_FILE_MISSING"

    failure_cases = (
        (
            "def api_Demo_bad(:\n",
            "DUT_API_PARSE_FAILED",
        ),
        (
            "def unrelated(env, max_cycles=1):\n    return None\n",
            "DUT_API_COUNT_INSUFFICIENT",
        ),
        (
            "def api_Demo_bad(value):\n    return value\n",
            "DUT_API_SIGNATURE_INVALID",
        ),
        (
            "def api_Demo_bad(env, max_cycles=1):\n    return None\n",
            "DUT_API_DOCSTRING_MISSING",
        ),
        (
            "def api_Demo_bad(env, max_cycles=1):\n"
            "    \"\"\"Run one operation.\n\n"
            "    Args:\n"
            "        env: Verification environment.\n"
            "    \"\"\"\n"
            "    return None\n",
            "DUT_API_DOCSTRING_SECTION_MISSING",
        ),
    )
    for source, error_code in failure_cases:
        target_path.write_text(source, encoding="utf-8")
        passed, diagnostic = checker.do_check()
        assert passed is False
        assert diagnostic["error_code"] == error_code
        assert diagnostic["error"]
        assert diagnostic["next_action"]
        assert diagnostic["artifact"] == target
        assert diagnostic["location"].startswith(target)
        assert "observed" in diagnostic
        assert "expected" in diagnostic


def test_dut_api_checker_bounds_invalid_signature_details(tmp_path):
    """A large invalid API set is summarized instead of flooding stage context."""

    target = "Demo_api.py"
    (tmp_path / target).write_text(
        "\n".join(
            f"def api_Demo_bad_{index}(value):\n    return value"
            for index in range(25)
        ),
        encoding="utf-8",
    )
    checker = UnityChipCheckerDutApi("api_Demo", target, 1).set_workspace(str(tmp_path))

    passed, diagnostic = checker.do_check()

    assert passed is False
    assert diagnostic["error_code"] == "DUT_API_SIGNATURE_INVALID"
    assert diagnostic["observed"]["invalid_api_count"] == 25
    assert len(diagnostic["observed"]["signatures"]) == 20
    assert diagnostic["observed"]["truncated"] is True


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
):
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


def test_api_checker_rejects_nonconforming_test_function_name_before_pytest(tmp_path):
    test_dir = _write_workspace_files(tmp_path)
    (test_dir / "Demo_api.py").write_text(
        "def api_Demo_operate(env, max_cycles=10):\n"
        "    return None\n",
        encoding="utf-8",
    )
    (test_dir / "test_Demo_api_basic.py").write_text(
        "raise AssertionError('test module must not be imported before naming validation')\n\n"
        "def test_api_basic(env):\n"
        "    assert True\n",
        encoding="utf-8",
    )
    (test_dir / "test_api_Demo_wrong_file.py").write_text(
        "def test_api_Demo_operate_extra(env):\n"
        "    assert True\n",
        encoding="utf-8",
    )
    checker = UnityChipCheckerDutApiTest(
        "api_Demo_",
        "unity_test/tests/Demo_api.py",
        "unity_test/tests/test_Demo_api*.py",
        "unity_test/Demo_functions_and_checks.md",
        "unity_test/Demo_bug_analysis.md",
        test_func_prefix="test_api_Demo_",
        test_func_rules="standard",
        cfg=Config({"_temp_cfg": {"DUT": "Demo"}}),
    ).set_workspace(str(tmp_path))

    class _UnexpectedRunner:
        def do(self, *_args, **_kwargs):
            raise AssertionError("pytest must not run for an invalid test name")

    checker.run_test = _UnexpectedRunner()
    passed, message = checker.do_check(timeout=10)

    assert passed is False
    assert message["diagnostic"]["error_code"] == (
        "TEST_FUNCTION_CONTRACT_VIOLATION"
    )
    assert message["diagnostic"]["observed"]["issue_count"] == 2
    assert any(
        "test_api_basic" in issue and "test_api_Demo_" in issue
        for issue in message["details"]
    )
    assert any(
        "test_api_Demo_wrong_file.py:1-1" in issue
        and "reserved prefix 'test_api_'" in issue
        for issue in message["details"]
    )


def test_standard_test_naming_contract_separates_stage_namespaces(tmp_path):
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    (test_dir / "test_Demo_env_fixture.py").write_text(
        "def test_api_Demo_env_reset(env):\n"
        "    assert True\n",
        encoding="utf-8",
    )
    (test_dir / "test_Demo_api_math.py").write_text(
        "def test_api_basic(env):\n"
        "    assert True\n",
        encoding="utf-8",
    )
    (test_dir / "test_Demo_arithmetic.py").write_text(
        "def test_add(env):\n"
        "    assert True\n\n"
        "def test_random_misplaced(env):\n"
        "    assert True\n",
        encoding="utf-8",
    )
    (test_dir / "test_Demo_random_stress.py").write_text(
        "def test_random_stress(env):\n"
        "    assert True\n\n"
        "def test_random_(env):\n"
        "    assert True\n",
        encoding="utf-8",
    )
    (test_dir / "test_api_Demo_wrong_file.py").write_text(
        "def test_api_Demo_add(env):\n"
        "    assert True\n",
        encoding="utf-8",
    )
    checker = BaseUnityChipCheckerTestCase(
        test_dir="tests",
        cfg=Config({"_temp_cfg": {"DUT": "Demo"}}),
    ).set_workspace(str(tmp_path))

    class _UnexpectedRunner:
        def do(self, *_args, **_kwargs):
            raise AssertionError("pytest must not run for naming conflicts")

    checker.run_test = _UnexpectedRunner()
    report, stdout, stderr = checker.do_check()
    issues = report["test_function_contract"]["details"]

    assert checker.test_func_rules == "standard"
    assert report["run_test_success"] is False
    assert stdout == ""
    assert stderr == ""
    assert len(issues) == 4
    assert any(
        "tests/test_Demo_api_math.py:1-1" in issue
        and "test_api_Demo_" in issue
        for issue in issues
    )
    assert any(
        "tests/test_Demo_arithmetic.py:4-4" in issue
        and "reserved prefix 'test_random_'" in issue
        for issue in issues
    )
    assert any(
        "tests/test_api_Demo_wrong_file.py:1-1" in issue
        and "reserved prefix 'test_api_'" in issue
        for issue in issues
    )
    assert any(
        "tests/test_Demo_random_stress.py:4-4" in issue
        and "nonempty descriptive suffix" in issue
        for issue in issues
    )
    assert all("test_add" not in issue for issue in issues)


def test_standard_test_naming_contract_does_not_fail_open_without_dut(tmp_path):
    (tmp_path / "tests").mkdir()
    checker = BaseUnityChipCheckerTestCase(
        test_dir="tests",
        test_func_rules="standard",
        cfg=Config({}),
    ).set_workspace(str(tmp_path))

    issues = checker._test_function_name_issues(checker._stage_test_files())

    assert len(issues) == 1
    assert "cannot be resolved" in issues[0]
    assert "resolved DUT name and a configured test_dir" in issues[0]


def test_standard_test_naming_contract_supports_workspace_root(tmp_path):
    (tmp_path / "test_Demo_api.py").write_text(
        "def test_api_basic(env):\n"
        "    assert True\n",
        encoding="utf-8",
    )
    checker = BaseUnityChipCheckerTestCase(
        test_dir="",
        test_func_rules="standard",
        cfg=Config({"_temp_cfg": {"DUT": "Demo"}}),
    ).set_workspace(str(tmp_path))

    issues = checker._test_function_name_issues(checker._stage_test_files())

    assert len(issues) == 1
    assert "test_Demo_api.py:1-1" in issues[0]
    assert "test_api_Demo_" in issues[0]


def test_test_function_naming_scope_only_checks_configured_stage_files(tmp_path):
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    (test_dir / "test_Demo_directed.py").write_text(
        "def test_directed(env):\n"
        "    assert True\n",
        encoding="utf-8",
    )
    static_file = test_dir / "test_Demo_static_verify_width.py"
    static_file.write_text(
        "def test_static_Demo_width(env):\n"
        "    assert True\n",
        encoding="utf-8",
    )
    checker = BaseUnityChipCheckerTestCase(
        test_dir="tests",
        test_func_file="tests/test_Demo_static_verify_*.py",
        test_func_prefix="test_static_Demo_",
    ).set_workspace(str(tmp_path))

    assert checker._test_function_name_issues(checker._stage_test_files()) == []

    (test_dir / "test_Demo_static_verify_bad.py").write_text(
        "def test_width(env):\n"
        "    assert True\n",
        encoding="utf-8",
    )
    issues = checker._test_function_name_issues(checker._stage_test_files())

    assert len(issues) == 1
    assert "tests/test_Demo_static_verify_bad.py:1-1" in issues[0]
    assert "test_static_Demo_" in issues[0]


def test_checker_line_coverage_uses_temporary_workspace(tmp_path, monkeypatch):
    report_dir = tmp_path / "arbitrary reports" / "current"
    coverage_file = report_dir / "observations" / "measured.json"
    coverage_file.parent.mkdir(parents=True)
    coverage_file.write_text(
        json.dumps({
            "overview": {
                "total": {"line": 10},
                "miss": {"line": 1},
            },
            "uncovered": {"data": {}},
            "artifacts": {},
        }),
        encoding="utf-8",
    )
    (report_dir / "execution.json").write_text(json.dumps({
        "coverages": {"line": {"coverage_json": "observations/measured.json"}, "functional": {}},
    }), encoding="utf-8")
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

    checker.run_test.result_dir = str(report_dir)
    checker.run_test.result_json_path = "execution.json"
    assert checker.test_func_rules == "standard"
    assert checker._resolved_test_func_rules()[0]["prefixes"] == (
        "test_api_Demo_env_"
    )

    passed, message = checker.do_check()

    assert passed is True
    assert "90.00% >= 80.00%" in message
    assert checker.cur_line_coverage == 0.9


def _publish(report, name="observations/current.json", misses=1, error=None):
    """Write a real report and independent full checker JSON in arbitrary folders."""
    report.parent.mkdir(parents=True, exist_ok=True)
    summary = report.parent / name
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps({
        "overview": {"total": {"line": 10}, "miss": {"line": misses}},
        "uncovered": {"data": {}}, "artifacts": {},
    }), encoding="utf-8")
    line = {"coverage_json": name}
    if error:
        line["error"] = error
    report.write_text(json.dumps({"coverages": {"line": line, "functional": {}}}), encoding="utf-8")
    return summary


def _checker(tmp_path, monkeypatch, kind, **options):
    """Create a real runner while replacing only the preceding functional gate."""
    if kind == "threshold":
        checker = UnityChipCheckerTestCaseWithLineCoverage(
            cfg={"_temp_cfg": {"DUT": "Demo"}}, min_line_coverage=0.8,
            **options,
        ).set_workspace(str(tmp_path))
        monkeypatch.setattr(UnityChipCheckerTestCase, "do_check", lambda self, **kw: (True, "passed"))
    else:
        checker = UnityChipCheckerTestFree(**options).set_workspace(str(tmp_path))
        monkeypatch.setattr(BaseUnityChipCheckerTestCase, "do_check", lambda self, **kw: (
            {"run_test_success": True, "tests": {"total": 1, "fails": 0}}, "stdout", "stderr",
        ))
    checker.run_test.result_dir = str(tmp_path / "custom execution" / "reports")
    checker.run_test.result_json_path = "test-result.json"
    report = Path(checker.run_test.result_dir) / checker.run_test.result_json_path
    return checker, report


def _run(checker, kind):
    """Request optional coverage in the free checker and required coverage otherwise."""
    return checker.do_check(**({"return_line_coverage": True} if kind == "free" else {}))


@pytest.mark.parametrize("kind", ["free", "threshold"])
def test_current_report_paths_refresh_between_runs_and_remain_read_only(tmp_path, monkeypatch, kind):
    """Repeated checks follow new references, preserving both original JSON files."""
    checker, report = _checker(tmp_path, monkeypatch, kind)
    first = _publish(report, "first data/stats.json", misses=1)
    original = first.read_bytes()
    report_bytes = report.read_bytes()
    passed, result = _run(checker, kind)
    assert passed is True
    assert first.read_bytes() == original
    assert report.read_bytes() == report_bytes
    if kind == "free":
        assert result["LINE_COVERAGE"]["coverage_rate"] == 0.9
    else:
        assert checker.cur_line_coverage == 0.9
        assert checker.coverage_json == first.relative_to(tmp_path).as_posix()
    second = _publish(report, "second output/new-statistics.json", misses=5)
    second_original = second.read_bytes()
    passed, result = _run(checker, kind)
    if kind == "free":
        assert passed is True
        assert result["LINE_COVERAGE"]["coverage_rate"] == 0.5
    else:
        assert passed is False
        assert checker.cur_line_coverage == 0.5
        assert checker.coverage_json == second.relative_to(tmp_path).as_posix()
        assert "Insufficient Line Coverage" in str(result)
    assert first.read_bytes() == original
    assert second.read_bytes() == second_original


@pytest.mark.parametrize("kind", ["free", "threshold"])
@pytest.mark.parametrize("failure", ["missing", "unsupported", "conversion", "mismatch"])
def test_coverage_lookup_failures_are_diagnostic_not_stale_success(tmp_path, monkeypatch, kind, failure):
    """Unavailable current artifacts never read old output or bypass path assertions."""
    options = {"coverage_json": "unrelated/old.json"} if failure == "mismatch" else {}
    checker, report = _checker(tmp_path, monkeypatch, kind, **options)
    summary = _publish(report, error="native converter failed" if failure == "conversion" else None)
    if kind == "threshold":
        checker.cur_line_coverage = 0.99
    if failure == "missing":
        report.write_text(json.dumps({"coverages": {"line": {"coverage_json": "missing.json"}, "functional": {}}}))
    elif failure == "unsupported":
        report.write_text(json.dumps({"coverages": {"line": {}, "functional": {}}}))
    before = summary.read_bytes()
    passed, result = _run(checker, kind)
    if kind == "free":
        assert passed is True
        assert isinstance(result["LINE_COVERAGE"]["error"], str)
        assert result["LINE_COVERAGE"]["error"]
    else:
        assert passed is False
        assert isinstance(result, dict)
        assert result.get("error_code") or result.get("diagnostic", {}).get("error_code")
        assert checker.cur_line_coverage is None
    if failure == "conversion":
        assert "native converter failed" in str(result)
    assert summary.read_bytes() == before


@pytest.mark.parametrize("kind", ["free", "threshold"])
def test_original_functional_failure_is_not_masked_by_coverage_lookup(tmp_path, monkeypatch, kind):
    """No report is needed after the functional gate already rejected the run."""
    checker, report = _checker(tmp_path, monkeypatch, kind)
    if kind == "threshold":
        original = {"error": "original DUT assertion failure"}
        monkeypatch.setattr(UnityChipCheckerTestCase, "do_check", lambda self, **kw: (False, original))
        checker.cur_line_coverage = 0.99
        passed, result = _run(checker, kind)
        assert passed is False
        assert result is original
        assert checker.cur_line_coverage is None
    else:
        original = {"error": "original runtime failure"}
        monkeypatch.setattr(BaseUnityChipCheckerTestCase, "do_check", lambda self, **kw: ({}, "", "original runtime failure"))
        monkeypatch.setattr("ucagent.checkers.unity_test.fc.is_run_report_pass", lambda *args: (False, original))
        passed, result = _run(checker, kind)
        assert passed is False
        assert result is original
    assert not report.exists()
