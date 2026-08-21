#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for UnityChipCheckerTestTemplate assertion-failure validation."""

import json
import os
import sys
from types import SimpleNamespace

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.checkers.unity_test import (
    BaseUnityChipCheckerTestCase,
    UnityChipCheckerTestTemplate,
)
from ucagent.util.config import load_yaml_with_env_vars
from ucagent.util.functions import list_str_abbr, load_toffee_report


ASSERT_EXAMPLE = 'Correct example: assert False, "Not implemented"'


def _checker(template_must_fail=True):
    return UnityChipCheckerTestTemplate(template_must_fail=template_must_fail)


def _report(cases, details=None):
    return {
        "tests": {
            "total": len(cases),
            "test_cases": cases,
            "test_case_details": details or {},
        }
    }


def _assertion_detail(message="Not implemented"):
    return {
        "status": "FAILED",
        "phase": "call",
        "exception_type": "AssertionError",
        "exception": f"AssertionError('{message}')",
    }


def test_template_validation_accepts_expected_assertion_failure_per_test():
    cases = {
        "tests/test_template.py:1-2::test_a": "FAILED",
        "tests/test_template.py:4-5::test_b": "FAILED",
    }
    details = {test_case: _assertion_detail() for test_case in cases}

    passed, message = _checker()._validate_template_structure(
        _report(cases, details), "", ""
    )

    assert passed is True
    assert message == "Template structure validation passed."


def test_template_validation_reports_runtime_exception_in_mixed_failures():
    expected_case = "tests/test_template.py:1-2::test_expected"
    broken_case = "tests/test_template.py:4-6::test_broken"
    cases = {expected_case: "FAILED", broken_case: "FAILED"}
    details = {
        expected_case: _assertion_detail(),
        broken_case: {
            "status": "FAILED",
            "phase": "call",
            "exception_type": "NameError",
            "exception": "NameError(\"name 'missing_value' is not defined\")",
        },
    }

    passed, message = _checker()._validate_template_structure(
        _report(cases, details), "AssertionError: Not implemented", ""
    )

    assert passed is False
    assert "unexpected exceptions" in message
    assert "NameError" in message
    assert "test_broken" in message
    assert "called component" in message
    assert "APIs, reference models, the DUT/simulator" in message
    assert "owning module" in message
    assert ASSERT_EXAMPLE in message
    assert message.index(ASSERT_EXAMPLE) - message.index("AssertionError") < 80


def test_template_validation_reports_setup_error_with_environment_guidance():
    test_case = "tests/test_template.py:1-2::test_setup_error"
    cases = {test_case: "ERROR"}
    details = {
        test_case: {
            "status": "ERROR",
            "phase": "setup",
            "exception_type": "UnboundLocalError",
            "exception": "UnboundLocalError('DUT initialization failed')",
        }
    }

    passed, message = _checker()._validate_template_structure(
        _report(cases, details), "", ""
    )

    assert passed is False
    assert "execution or lifecycle errors" in message
    assert "setup: UnboundLocalError" in message
    assert "not necessarily caused by the test function itself" in message
    assert "test body may not have run" in message
    assert "fixtures" in message
    assert "DUT/simulator environment initialization" in message
    assert "build artifacts" in message
    assert ASSERT_EXAMPLE in message
    assert message.index(ASSERT_EXAMPLE) - message.index("AssertionError") < 80


def test_template_validation_limits_same_category_errors_to_first_twenty():
    cases = {
        f"tests/test_template.py:{index + 1}-{index + 1}::test_error_{index}": "ERROR"
        for index in range(25)
    }
    details = {
        test_case: {
            "status": "ERROR",
            "phase": "setup",
            "exception_type": "RuntimeError",
            "exception": f"RuntimeError('setup failed {index}')",
        }
        for index, test_case in enumerate(cases)
    }

    passed, message = _checker()._validate_template_structure(
        _report(cases, details), "", ""
    )

    assert passed is False
    assert "Total: 25." in message
    assert "First 20:" in message
    assert "Remaining: 5 not shown." in message
    assert "::test_error_0=ERROR" in message
    assert "::test_error_19=ERROR" in message
    assert "::test_error_20=ERROR" not in message
    assert "::test_error_24=ERROR" not in message


def test_list_str_abbr_count_summary_shows_all_when_count_is_twenty_or_less():
    items = [f"error-{index}" for index in range(20)]

    summary = list_str_abbr(items, max_items=20, show_counts=True)

    assert "Total: 20." in summary
    assert "Details:" in summary
    assert "Remaining:" not in summary
    assert "error-19" in summary


def test_list_str_abbr_default_output_remains_backward_compatible():
    assert list_str_abbr(["a", "b"], max_items=1) == "a, ..."


def test_template_execution_guidance_handles_teardown_and_unknown_phases():
    teardown_case = "tests/test_template.py:1-2::test_teardown_error"
    teardown_guidance = _checker()._get_template_execution_guidance(
        [teardown_case],
        {teardown_case: {"phase": "teardown"}},
    )
    unknown_guidance = _checker()._get_template_execution_guidance(
        ["tests/test_template.py:4-5::test_unknown"],
        {},
    )

    assert "fixture finalizers" in teardown_guidance
    assert "resource release" in teardown_guidance
    assert "simulator shutdown" in teardown_guidance
    assert "failing phase is unknown" in unknown_guidance
    assert "DUT/environment initialization" in unknown_guidance
    assert "owning module" in teardown_guidance
    assert "owning module" in unknown_guidance


def test_template_validation_requires_not_implemented_assertion_message():
    test_case = "tests/test_template.py:1-2::test_wrong_assert"

    passed, message = _checker()._validate_template_structure(
        _report(
            {test_case: "FAILED"},
            {test_case: _assertion_detail("different assertion")},
        ),
        "",
        "",
    )

    assert passed is False
    assert "without the required 'Not implemented' message" in message
    assert ASSERT_EXAMPLE in message


def test_template_validation_skips_assertion_check_when_disabled():
    test_case = "tests/test_template.py:1-2::test_runtime_error"

    passed, _message = _checker(template_must_fail=False)._validate_template_structure(
        _report(
            {test_case: "FAILED"},
            {
                test_case: {
                    "status": "FAILED",
                    "exception_type": "NameError",
                    "exception": "NameError('broken')",
                }
            },
        ),
        "",
        "",
    )

    assert passed is True


def test_template_collection_syntax_error_has_execution_error_message():
    stdout = """
    ERROR collecting tests/test_invalid.py
    E   SyntaxError: invalid syntax
    Interrupted: 1 error during collection
    """

    message = _checker()._get_pytest_collection_error(stdout, "")

    assert "SyntaxError" in message
    assert "collection error" in message
    assert "not a missing template assertion" in message
    assert "imported module, dependency, plugin, or configuration" in message
    assert "owning file/module" in message


def test_template_do_check_prioritizes_collection_syntax_error(monkeypatch):
    captured_kwargs = {}
    stdout = """
    ERROR collecting tests/test_invalid.py
    E   SyntaxError: invalid syntax
    Interrupted: 1 error during collection
    """

    def fake_base_check(_self, **kwargs):
        captured_kwargs.update(kwargs)
        return {"run_test_success": True}, stdout, ""

    monkeypatch.setattr(BaseUnityChipCheckerTestCase, "do_check", fake_base_check)

    passed, message = _checker().do_check()

    assert passed is False
    assert "SyntaxError" in message["error"]
    assert "not a missing template assertion" in message["error"]
    assert captured_kwargs["return_test_details"] is True


def test_template_do_check_prioritizes_missing_functional_coverage(monkeypatch):
    test_case = "tests/test_template.py:1-2::test_template"
    report = {
        "run_test_success": True,
        "tests": {
            "total": 1,
            "fails": 1,
            "test_cases": {test_case: "FAILED"},
            "test_case_details": {test_case: _assertion_detail()},
        },
        "total_funct_point": 0,
        "total_check_point": 0,
        "unmarked_check_points": 0,
        "test_function_with_no_check_point_mark": 1,
        "test_function_with_no_check_point_mark_list": [test_case],
    }

    monkeypatch.setattr(
        BaseUnityChipCheckerTestCase,
        "do_check",
        lambda _self, **_kwargs: (report, "", ""),
    )

    passed, message = _checker().do_check()

    assert passed is False
    assert "[Functional Coverage Missing]" in message["error"]
    assert "do not duplicate" in message["error"]
    assert "Not all 'check_points'" not in message["error"]


def test_template_do_check_prioritizes_execution_error_over_missing_coverage(
    monkeypatch,
):
    test_case = "tests/test_template.py:1-2::test_setup_error"
    report = {
        "run_test_success": True,
        "tests": {
            "total": 1,
            "fails": 1,
            "test_cases": {test_case: "ERROR"},
            "test_case_details": {
                test_case: {
                    "status": "ERROR",
                    "phase": "setup",
                    "exception_type": "RuntimeError",
                    "exception": "RuntimeError('fixture failed')",
                }
            },
        },
        "total_funct_point": 0,
        "total_check_point": 0,
        "unmarked_check_points": 0,
        "test_function_with_no_check_point_mark": 1,
        "test_function_with_no_check_point_mark_list": [test_case],
    }
    monkeypatch.setattr(
        BaseUnityChipCheckerTestCase,
        "do_check",
        lambda _self, **_kwargs: (report, "", ""),
    )

    passed, message = _checker().do_check()

    assert passed is False
    assert "execution or lifecycle errors" in message["error"]
    assert "setup: RuntimeError" in message["error"]
    assert "[Functional Coverage Missing]" not in message["error"]


def test_template_do_check_reports_checkpoint_relation_before_batch(
    tmp_path, monkeypatch
):
    checkpoint = "FG-A/FC-A/CK-A"
    test_case = "tests/test_template.py:1-2::test_template"
    (tmp_path / "tests").mkdir()
    (tmp_path / "functions.md").write_text(
        "<FG-A>\n<FC-A>\n<CK-A>\n",
        encoding="utf-8",
    )
    report = {
        "run_test_success": True,
        "tests": {
            "total": 1,
            "fails": 0,
            "test_cases": {test_case: "PASSED"},
            "test_case_details": {},
        },
        "total_funct_point": 1,
        "total_check_point": 1,
        "all_check_point_list": [checkpoint],
        "unmarked_check_points": 1,
        "unmarked_check_point_list": [checkpoint],
        "test_function_with_no_check_point_mark": 0,
    }
    monkeypatch.setattr(
        BaseUnityChipCheckerTestCase,
        "do_check",
        lambda _self, **_kwargs: (report, "", ""),
    )
    checker = UnityChipCheckerTestTemplate(
        doc_func_check="functions.md",
        test_dir="tests",
        template_must_fail=False,
    ).set_workspace(str(tmp_path))

    passed, message = checker.do_check()

    assert passed is False
    assert "[Checkpoint Association Missing]" in message["error"]
    assert "does not identify why the association was not recorded" in message["error"]
    assert "mark_function" not in message["error"]
    assert "Not all 'check_points'" not in message["error"]


def test_base_checker_supports_multiple_infrastructure_ignore_prefixes(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "functions.md").write_text(
        "<FG-A>\n<FC-A>\n<CK-A>\n",
        encoding="utf-8",
    )

    class CaptureRunner:
        def __init__(self):
            self.pytest_args = None

        def set_workspace(self, _workspace):
            return self

        def set_pre_call_back(self, _callback):
            return self

        def do(self, *_args, **kwargs):
            self.pytest_args = kwargs["pytest_ex_args"]
            return {"run_test_success": True}, "", ""

    checker = BaseUnityChipCheckerTestCase(
        doc_func_check="functions.md",
        test_dir="tests",
        ignore_tc_prefix=[
            "test_api_Demo_env_",
            "test_api_Demo_reference_model_",
            "test_api_Demo_mock_",
        ],
    ).set_workspace(str(tmp_path))
    runner = CaptureRunner()
    checker.run_test = runner

    checker.do_check()

    assert runner.pytest_args == [
        "-k",
        "not test_api_Demo_env_ and not test_api_Demo_reference_model_ and not test_api_Demo_mock_",
        ".",
    ]
    assert checker._is_ignored_test_case(
        "tests/test_env.py:1-2::test_api_Demo_env_basic"
    )
    assert not checker._is_ignored_test_case(
        "tests/test_api.py:1-2::test_api_Demo_operate_add"
    )


def test_template_scope_excludes_only_configured_api_checkpoints(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "functions.md").write_text(
        "<FG-API>\n<FC-OP>\n<CK-API>\n"
        "<FG-DATA>\n<FC-RESULT>\n<CK-NON-API>\n",
        encoding="utf-8",
    )
    checker = UnityChipCheckerTestTemplate(
        doc_func_check="functions.md",
        test_dir="tests",
        ignore_tc_prefix="test_api_Demo_",
        ignore_ck_prefix="FG-API/",
        template_must_fail=True,
    ).set_workspace(str(tmp_path)).set_stage(
        SimpleNamespace(name="create_test_case_templates")
    )

    checker.on_init()

    assert checker.ignored_source_checkpoints == ["FG-API/FC-OP/CK-API"]
    assert checker.batch_task.source_task_list == [
        "FG-DATA/FC-RESULT/CK-NON-API"
    ]
    assert checker.get_template_data()["TOTAL_CKS"] == 1


def test_template_accepts_api_checkpoint_unmarked_when_api_scope_is_excluded(
    tmp_path, monkeypatch
):
    api_checkpoint = "FG-API/FC-OP/CK-API"
    normal_checkpoint = "FG-DATA/FC-RESULT/CK-NON-API"
    test_case = "tests/test_result.py:1-3::test_result"
    (tmp_path / "tests").mkdir()
    (tmp_path / "functions.md").write_text(
        "<FG-API>\n<FC-OP>\n<CK-API>\n"
        "<FG-DATA>\n<FC-RESULT>\n<CK-NON-API>\n",
        encoding="utf-8",
    )
    report = {
        "run_test_success": True,
        "tests": {
            "total": 1,
            "fails": 1,
            "test_cases": {test_case: "FAILED"},
            "test_case_details": {test_case: _assertion_detail()},
        },
        "total_funct_point": 2,
        "total_check_point": 2,
        "all_check_point_list": [api_checkpoint, normal_checkpoint],
        "failed_check_point": 2,
        "failed_check_point_list": [api_checkpoint, normal_checkpoint],
        "unmarked_check_points": 1,
        "unmarked_check_point_list": [api_checkpoint],
        "test_function_with_no_check_point_mark": 0,
        "failed_test_case_with_check_point_list": {
            test_case: [normal_checkpoint],
        },
    }
    monkeypatch.setattr(
        BaseUnityChipCheckerTestCase,
        "do_check",
        lambda _self, **_kwargs: (report, "", ""),
    )
    checker = UnityChipCheckerTestTemplate(
        doc_func_check="functions.md",
        test_dir="tests",
        ignore_tc_prefix="test_api_Demo_",
        ignore_ck_prefix="FG-API/",
        template_must_fail=True,
    ).set_workspace(str(tmp_path)).set_stage(
        SimpleNamespace(name="create_test_case_templates")
    )
    checker.on_init()

    passed, message = checker.do_check(is_complete=True)

    assert passed is True
    assert "All 1 in-scope check points" in " ".join(message["success"])
    assert checker.batch_task.source_task_list == [normal_checkpoint]
    assert checker.batch_task.gen_task_list == [normal_checkpoint]


def _iter_stage_checkers(stages, parent=""):
    for stage in stages:
        stage_path = f"{parent}/{stage['name']}" if parent else stage["name"]
        for checker in stage.get("checker", []):
            yield stage_path, checker
        yield from _iter_stage_checkers(stage.get("stage", []), stage_path)


def test_workflows_keep_api_tests_and_ignore_only_infrastructure():
    repo_root = os.path.abspath(os.path.join(current_dir, ".."))
    config_dir = os.path.join(repo_root, "ucagent/lang/zh/config")
    default_config = load_yaml_with_env_vars(
        os.path.join(config_dir, "default.yaml")
    )
    stages = {stage["name"]: stage for stage in default_config["stage"]}
    template_checker = next(
        checker
        for checker in stages["create_test_case_templates"]["checker"]
        if checker["name"] == "template_check"
    )
    assert template_checker["args"]["ignore_tc_prefix"] == "test_api_{DUT}_"
    assert template_checker["args"]["ignore_ck_prefix"] == "FG-API/"

    expected_infrastructure_prefixes = [
        "test_api_{DUT}_env_",
        "test_api_{DUT}_reference_model_",
        "test_api_{DUT}_mock_",
    ]
    checked_later_stages = []
    for config_name in ("default.yaml", "inc.yaml", "vibe.yaml"):
        config = load_yaml_with_env_vars(os.path.join(config_dir, config_name))
        for stage_path, checker in _iter_stage_checkers(config["stage"]):
            ignored_prefixes = checker.get("args", {}).get("ignore_tc_prefix")
            if ignored_prefixes is None or checker["clss"] == "UnityChipCheckerTestTemplate":
                continue
            assert ignored_prefixes == expected_infrastructure_prefixes, (
                config_name,
                stage_path,
                checker["name"],
            )
            assert "test_api_{DUT}_" not in ignored_prefixes
            checked_later_stages.append((config_name, stage_path, checker["name"]))

    assert {item[0] for item in checked_later_stages} == {
        "default.yaml",
        "inc.yaml",
        "vibe.yaml",
    }


def test_load_toffee_report_optionally_extracts_failure_type(tmp_path):
    test_file = tmp_path / "test_template.py"
    test_file.write_text(
        "def test_template():\n    assert False, 'Not implemented'\n",
        encoding="utf-8",
    )
    test_id = f"{test_file}:1-2::test_template"
    report_file = tmp_path / "toffee_report.json"
    report_file.write_text(
        json.dumps(
            {
                "test_abstract_info": {test_id: "FAILED"},
                "tests": [
                    {
                        "phases": [
                            {
                                "call": (
                                    "<CallInfo when='call' excinfo=<ExceptionInfo "
                                    "AssertionError('Not implemented') tblen=5>>"
                                ),
                                "status": {"word": "FAILED"},
                            }
                        ]
                    }
                ],
                "coverages": {"functional": {}},
            }
        ),
        encoding="utf-8",
    )

    report = load_toffee_report(
        str(report_file),
        str(tmp_path),
        run_test_success=True,
        return_all_checks=True,
        return_test_details=True,
    )

    details = next(iter(report["tests"]["test_case_details"].values()))
    assert details["phase"] == "call"
    assert details["exception_type"] == "AssertionError"
    assert "Not implemented" in details["exception"]
