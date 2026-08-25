#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for StageManager progress loading behavior."""

import os
import sys
import asyncio
import pytest
from types import SimpleNamespace

current_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(current_dir, ".."))
repo_package_root = os.path.join(repo_root, "ucagent")
sys.path.insert(0, repo_root)

loaded_ucagent = sys.modules.get("ucagent")
loaded_ucagent_path = os.path.abspath(getattr(loaded_ucagent, "__file__", "") or "")
if loaded_ucagent is not None and not loaded_ucagent_path.startswith(repo_package_root + os.sep):
    for module_name in list(sys.modules):
        if module_name == "ucagent" or module_name.startswith("ucagent."):
            del sys.modules[module_name]

import ucagent.stage.vmanager as vmanager
from ucagent.stage.vstage import VerifyStage
from ucagent.stage.vmanager import (
    ArgsDoCheck,
    StageManager,
    ToolDoCheck,
    ToolDoComplete,
    ToolRunTestCases,
)
from ucagent.tools.uctool import to_fastmcp
from ucagent.util import functions as fc


def test_run_test_cases_contract_rejects_non_test_scripts():
    description = ToolRunTestCases().description

    assert "real pytest verification tests" in description
    assert "not a Python script runner" in description
    assert "temporary pytest test" in description
    assert "maintenance script" in description
    assert "file-editing tools" in description
    assert "RunSkillScript" in description


class _FakeStage:
    def __init__(self, index):
        self.index = index
        self.name = f"stage-{index}"
        self.fail_count = 0
        self.time_prev_cost = 0.0
        self.is_complete = False
        self.meta_data = {}
        self._is_reached = False
        self._is_skipped = False
        self.reference_file_status = {}
        self.init_count = 0
        self.hist_init_count = 0
        self.stage_manager = None

    def title(self):
        return self.name

    def is_skipped(self):
        return self._is_skipped

    def set_skip(self, value):
        self._is_skipped = value

    def is_reached(self):
        return self._is_reached

    def set_reached(self, value):
        self._is_reached = value

    def set_fail_count(self, value):
        self.fail_count = value

    def set_time_prev_cost(self, value):
        self.time_prev_cost = value

    def is_completed(self):
        return self.is_complete

    def set_reference_file_status(self, status):
        self.reference_file_status = status

    def set_stage_manager(self, manager):
        self.stage_manager = manager

    def on_init(self):
        self.init_count += 1

    def hist_init(self):
        self.hist_init_count += 1

    def get_time_cost(self):
        return self.time_prev_cost

    def is_wait_human_check(self):
        return False

    def detail(self):
        return {
            "task": {"reference_files": self.reference_file_status},
            "reached": self.is_reached(),
            "is_completed": self.is_completed(),
            "fail_count": self.fail_count,
            "is_skipped": self.is_skipped(),
        }


class _FakeRootStage:
    def __init__(self, stages):
        self._stages = stages

    def get_substages(self):
        return self._stages


class _FakeAgent:
    def __init__(self, cfg, is_exit=False):
        self.cfg = cfg
        self._is_exit = is_exit

    def is_break(self):
        return False

    def is_exit(self):
        return self._is_exit

    def get_stat_info(self):
        return {"version": "test"}


class _FakeCurrentStageManager:
    def __init__(self, current_stage):
        self._current_stage = current_stage

    def get_current_stage(self):
        return self._current_stage


class _RecordingCheckStage:
    name = "recording-stage"

    def __init__(self):
        self.calls = []
        self._is_reached = False
        self.init_count = 0

    def do_check(self, **kwargs):
        self.calls.append(kwargs)
        return True, {"seen": kwargs}

    def meta_get_journal(self):
        return "journal"

    def get_approved(self):
        return True

    def is_hmcheck_needed(self):
        return False

    def on_complete(self):
        pass

    def set_reached(self, value):
        self._is_reached = value

    def on_init(self):
        self.init_count += 1


def _cfg():
    return SimpleNamespace(
        tools=SimpleNamespace(RunTestCases=SimpleNamespace(test_dir="tests")),
        mission=SimpleNamespace(name="mission"),
        vmanager=SimpleNamespace(
            llm_suggestion=SimpleNamespace(
                check_fail_refinement=None,
                check_pass_refinement=None,
            ),
        ),
        skill=SimpleNamespace(use_skill=False),
    )


def _saved_info():
    return {
        "stage_index": 3,
        "all_completed": True,
        "time_begin": 100.0,
        "time_end": 200.0,
        "is_agent_exit": True,
        "is_wait_human_check": True,
        "stages_info": {
            str(index): {
                "fail_count": index + 1,
                "time_cost": float((index + 1) * 10),
                "reached": True,
                "is_skipped": False,
                "is_completed": True,
                "task": {"reference_files": {"ref.md": "Readed"}},
                "meta_data": {"journal": f"journal-{index}"},
            }
            for index in range(4)
        },
    }


def test_force_stage_rewind_truncates_loaded_stage_progress(monkeypatch, tmp_path):
    stages = [_FakeStage(index) for index in range(4)]
    cfg = _cfg()
    workspace = str(tmp_path)

    monkeypatch.setattr(vmanager, "get_root_stage", lambda *_args: _FakeRootStage(stages))
    monkeypatch.setattr(vmanager, "get_llm_check_instance", lambda *_args: None)

    manager = StageManager(
        workspace,
        cfg,
        _FakeAgent(cfg),
        tool_read_text=None,
        ucagent_info=_saved_info(),
        force_stage_index=1,
        tool_inspect_file=[],
    )
    manager.force_stage_index_explicit = True

    manager.init_stage()

    assert manager.stage_index == 1
    assert manager.all_completed is False
    assert manager.time_end is None

    assert stages[0].is_completed() is True
    assert stages[0].fail_count == 1
    assert stages[0].time_prev_cost == 10.0
    assert stages[0].meta_data == {"journal": "journal-0"}

    for stage in stages[1:]:
        assert stage.is_completed() is False
        assert stage.fail_count == 0
        assert stage.time_prev_cost == 0.0
        assert stage.meta_data == {}

    saved = fc.load_ucagent_info(workspace)
    assert saved["stage_index"] == 1
    assert saved["all_completed"] is False
    assert saved["time_end"] is None
    assert saved["is_agent_exit"] is False
    assert saved["is_wait_human_check"] is False
    assert saved["stages_info"]["0"]["is_completed"] is True
    assert saved["stages_info"]["0"]["meta_data"] == {"journal": "journal-0"}
    assert saved["stages_info"]["1"]["is_completed"] is False
    assert saved["stages_info"]["1"]["fail_count"] == 0
    assert saved["stages_info"]["1"]["time_cost"] == 0.0
    assert saved["stages_info"]["1"]["meta_data"] == {}


def test_save_stage_info_persists_mission_name_and_exit_state(tmp_path):
    cfg = _cfg()
    cfg.mission.name = "Formal Coverage Mission"
    agent = _FakeAgent(cfg, is_exit=True)
    stage = _FakeStage(0)
    manager = StageManager(
        str(tmp_path),
        cfg,
        agent,
        tool_read_text=None,
        ucagent_info={},
        force_stage_index=0,
        tool_inspect_file=[],
    )
    manager.stages = [stage]
    manager.stage_index = 0
    manager.time_begin = 10.0
    manager.time_end = None

    manager.save_stage_info()

    saved = fc.load_ucagent_info(str(tmp_path))
    assert saved["mission_name"] == "Formal Coverage Mission"
    assert saved["is_agent_exit"] is True
    assert saved["all_completed"] is False


def _make_verify_stage(name, reference_files, parent=None):
    stage = VerifyStage.__new__(VerifyStage)
    stage.name = name
    stage.reference_files = dict(reference_files)
    stage.parent = parent
    stage.force_unactive = False
    stage.skill_list = {}
    stage.workspace = ""
    stage.vmanager = None
    stage.is_skill_path = lambda _file_path: False
    return stage


def test_on_file_read_marks_only_the_current_stage_reference():
    root = _make_verify_stage("root", {"shared.md": False, "root_only.md": False})
    parent = _make_verify_stage("parent", {"shared.md": False}, parent=root)
    child = _make_verify_stage("child", {"shared.md": False, "child_only.md": False}, parent=parent)
    manager = _FakeCurrentStageManager(child)
    root.vmanager = manager
    parent.vmanager = manager
    child.vmanager = manager

    child.on_file_read(True, "shared.md", "")

    assert root.reference_files["shared.md"] is False
    assert parent.reference_files["shared.md"] is False
    assert child.reference_files["shared.md"] is True
    assert root.reference_files["root_only.md"] is False
    assert child.reference_files["child_only.md"] is False


def test_tool_do_check_passes_stage_args_to_function():
    calls = []

    def check_func(timeout, **kwargs):
        calls.append((timeout, kwargs))
        return "ok"

    tool = ToolDoCheck().set_function(check_func)

    result = tool.invoke({
        "timeout": 12,
        "stage_args": {
            "refined": {"CK-1": "done"},
            "note": "extra",
            "detail": True,
        },
    })

    assert result == "ok"
    assert calls == [(
        12,
        {
            "stage_args": {
                "refined": {"CK-1": "done"},
                "note": "extra",
                "detail": True,
            },
        },
    )]


def test_fastmcp_check_preserves_stage_args():
    calls = []

    def check_func(timeout, **kwargs):
        calls.append((timeout, kwargs))
        return "ok"

    tool = ToolDoCheck().set_function(check_func)
    mcp_tool = to_fastmcp(tool)

    result = asyncio.run(mcp_tool.run({
        "timeout": 13,
        "stage_args": {
            "refined": {"CK-2": "done"},
            "detail": False,
        },
    }))

    assert result == "ok"
    assert calls == [(
        13,
        {
            "stage_args": {
                "refined": {"CK-2": "done"},
                "detail": False,
            },
        },
    )]


def test_check_and_complete_schemas_expose_one_stage_args_object():
    expected_properties = {"timeout", "stage_args"}
    schemas = [
        ArgsDoCheck.model_json_schema(),
        to_fastmcp(ToolDoCheck()).parameters,
        to_fastmcp(ToolDoComplete()).parameters,
    ]

    for schema in schemas:
        assert set(schema["properties"]) == expected_properties
        assert schema["additionalProperties"] is False
        stage_arg_types = {
            item.get("type")
            for item in schema["properties"]["stage_args"]["anyOf"]
        }
        assert stage_arg_types == {"object", "string"}
        assert "is_complete" not in str(schema)


def test_check_arguments_accept_only_stage_args_json_object():
    structured = ArgsDoCheck.model_validate({
        "stage_args": {
            "refined": {"FG-A/FC-A/CK-A": "reviewed"},
            "generated": {"FG-A/FC-A/CK-A": "generated"},
            "bug_list": [{"bug_name": "overflow"}],
        },
    })

    assert structured.stage_args == {
        "refined": {"FG-A/FC-A/CK-A": "reviewed"},
        "generated": {"FG-A/FC-A/CK-A": "generated"},
        "bug_list": [{"bug_name": "overflow"}],
    }
    with pytest.raises(ValueError):
        ArgsDoCheck.model_validate({"refined": {"CK": "reviewed"}})


def test_check_accepts_json_string_stage_args_fallback():
    calls = []

    def check_func(timeout, **kwargs):
        calls.append((timeout, kwargs))
        return "ok"

    result = ToolDoCheck().set_function(check_func).invoke({
        "timeout": 15,
        "stage_args": '{"refined":{"FG-A/FC-A/CK-A":"reviewed"}}',
    })

    assert result == "ok"
    assert calls == [(
        15,
        {"stage_args": {"refined": {"FG-A/FC-A/CK-A": "reviewed"}}},
    )]


def test_fastmcp_check_accepts_json_string_stage_args_fallback():
    calls = []

    def check_func(timeout, **kwargs):
        calls.append((timeout, kwargs))
        return "ok"

    mcp_tool = to_fastmcp(ToolDoCheck().set_function(check_func))
    result = asyncio.run(mcp_tool.run({
        "timeout": 16,
        "stage_args": '{"generated":{"FG-A/FC-A/CK-A":"generated"}}',
    }))

    assert result == "ok"
    assert calls == [(
        16,
        {"stage_args": {"generated": {"FG-A/FC-A/CK-A": "generated"}}},
    )]


def test_check_rejects_invalid_or_non_object_stage_args_string():
    tool = ToolDoCheck().set_function(lambda timeout, **kwargs: "not called")

    invalid_json = tool.invoke({"stage_args": "not-json"})
    json_array = tool.invoke({"stage_args": '[{"refined":{}}]'})

    assert "must contain a valid JSON object" in invalid_json
    assert "must be a JSON object or a string containing one" in json_array


def test_fastmcp_complete_preserves_stage_args():
    calls = []

    def complete_func(timeout, **kwargs):
        calls.append((timeout, kwargs))
        return "ok"

    tool = ToolDoComplete().set_function(complete_func)
    mcp_tool = to_fastmcp(tool)
    result = asyncio.run(mcp_tool.run({
        "timeout": 14,
        "stage_args": {
            "generated": {"CK-3": "done"},
            "bug_list": [{"bug_name": "overflow"}],
            "detail": True,
        },
    }))

    assert result == "ok"
    assert calls == [(
        14,
        {
            "stage_args": {
                "generated": {"CK-3": "done"},
                "bug_list": [{"bug_name": "overflow"}],
                "detail": True,
            },
        },
    )]


def test_stage_manager_check_and_complete_forward_stage_args():
    stage = _RecordingCheckStage()
    next_stage = _RecordingCheckStage()
    manager = StageManager.__new__(StageManager)
    manager.stage_index = 0
    manager.stages = [stage, next_stage]
    manager.last_check_info = None
    manager.llm_fail_suggestion = None
    manager.llm_pass_suggestion = None
    manager.all_completed = False
    manager.gen_fail_suggestion = lambda data: data
    manager.gen_pass_suggestion = lambda ck_info: ""
    manager._stage_complete = lambda _stage: None

    def next_stage_func():
        manager.stage_index += 1
        manager.all_completed = manager.stage_index >= len(manager.stages)
        return None if manager.all_completed else manager.stages[manager.stage_index]

    manager.next_stage = next_stage_func

    check_ret = manager.check(9, stage_args={
        "refined": {"CK": "check"},
        "detail": True,
    })
    complete_ret = manager.complete(10, stage_args={
        "refined": {"CK": "complete"},
    })

    assert check_ret["check_pass"] is True
    assert complete_ret["complete"] is True
    assert stage.calls == [
        {
            "stage_args": {"refined": {"CK": "check"}, "detail": True},
            "timeout": 9,
        },
        {
            "stage_args": {"refined": {"CK": "complete"}},
            "timeout": 10,
            "is_complete": True,
        },
    ]


def test_verify_stage_expands_stage_args_at_checker_boundary(tmp_path):
    calls = []

    class _Checker:
        def check(self, **kwargs):
            calls.append(kwargs)
            return True, "ok"

    stage = VerifyStage.__new__(VerifyStage)
    stage.cfg = SimpleNamespace(skill=SimpleNamespace(use_skill=False))
    stage.skill_list = {}
    stage.reference_files = {}
    stage.output_files = []
    stage.workspace = str(tmp_path)
    stage._is_reached = False
    stage.check_pass = False
    stage.checker = [_Checker()]
    stage._checker = [SimpleNamespace(name="fake_checker")]
    stage.check_info = [None]
    stage.fail_count = 0
    stage.continue_fail_count = 0
    stage.succ_count = 0
    stage.is_batch_success = False

    passed, _info = stage._do_check(
        timeout=9,
        stage_args={
            "refined": {"FG-A/FC-A/CK-A": "done"},
            "detail": True,
        },
    )

    assert passed is True
    assert calls == [{
        "timeout": 9,
        "refined": {"FG-A/FC-A/CK-A": "done"},
        "detail": True,
    }]


def test_check_failure_summary_precedes_verbose_diagnostics():
    class FailingStage:
        name = "comprehensive_verification_and_bug_analysis"

        @staticmethod
        def do_check(**_kwargs):
            return False, [{
                "name": "UnityChipCheckerTestCase",
                "checker_name": "test_check",
                "checker_class": "UnityChipCheckerTestCase",
                "checked_in_last_run": True,
                "last_check_pass": False,
                "count_fail": 866,
                "last_msg": {
                    "STDOUT": "verbose pytest output" * 5000,
                    "error": (
                        "[Test Association Missing] Toffee recorded 8 executed tests without "
                        "checkpoint associations: test_Demo_env_fixture.py::test_env_input."
                    ),
                },
            }]

    manager = StageManager.__new__(StageManager)
    manager.stage_index = 25
    manager.stages = [None] * 25 + [FailingStage()]
    manager.last_check_info = None
    manager.gen_fail_suggestion = lambda data: data

    result = manager.check(30)
    rendered = fc.make_llm_tool_ret(result)

    assert next(iter(result)) == "failure_summary"
    assert result["failure_summary"]["stage_index"] == 25
    assert result["failure_summary"]["failed_checker_name"] == "test_check"
    assert result["failure_summary"]["failed_checker_class"] == "UnityChipCheckerTestCase"
    assert result["failure_summary"]["error_code"] == "TEST_ASSOCIATION_MISSING"
    assert "test_Demo_env_fixture.py::test_env_input" in result["failure_summary"]["error"]
    assert rendered.index("failure_summary:") < rendered.index("verbose pytest output")


def test_line_map_failure_summary_preserves_concrete_repair_fields():
    class FailingStage:
        name = "functional_line_mapping_gap_analysis"

        @staticmethod
        def do_check(**_kwargs):
            return False, [{
                "name": "UnityChipBatchCheckerFileLineMap",
                "checker_name": "functional_line_mapping_batch_check",
                "checker_class": "UnityChipBatchCheckerFileLineMap",
                "checked_in_last_run": True,
                "last_check_pass": False,
                "last_msg": {
                    "error": "generic batch error",
                    "diagnostic": {
                        "error_code": "LINE_MAP_IGNORE_REASON_MISSING",
                        "error": "map.txt:5-5: IGNORE mapping requires a reason comment after '#'.",
                        "artifact": "out/line_map/map.txt",
                        "location": "out/line_map/map.txt:5-5",
                        "line_block": "docs/spec.md:1-10",
                        "observed": "IGNORE mapping requires a reason comment after '#'.",
                        "expected": "IGNORE/FC-*/CK-*: start-end # concrete reason.",
                        "next_action": "Add a concrete inline reason at 'out/line_map/map.txt:5-5', then call `Check` again.",
                    },
                    "invalid_mappings": [{
                        "line_block": "docs/spec.md:1-10@sha256=internal",
                        "details": {"error": "large duplicate diagnostics" * 100},
                    }],
                },
            }]

    manager = StageManager.__new__(StageManager)
    manager.stage_index = 8
    manager.stages = [None] * 8 + [FailingStage()]
    manager.last_check_info = None
    manager.stage_need_llm_fail_suggestion = lambda _stage: False
    manager.gen_fail_suggestion = StageManager.gen_fail_suggestion.__get__(
        manager, StageManager
    )

    result = manager.check(30)
    summary = result["failure_summary"]

    assert summary["error_code"] == "LINE_MAP_IGNORE_REASON_MISSING"
    assert summary["error"].startswith("map.txt:5-5:")
    assert summary["artifact"] == "out/line_map/map.txt"
    assert summary["location"] == "out/line_map/map.txt:5-5"
    assert summary["line_block"] == "docs/spec.md:1-10"
    assert summary["next_action"].startswith("Add a concrete inline reason")
    assert "check_info" not in result
    assert "@sha256=" not in str(summary)


def test_line_map_failure_summary_keeps_complete_uncovered_content():
    uncovered_content = {
        3: "first uncovered requirement",
        4: "second uncovered requirement",
    }
    check_info = [{
        "checker_name": "functional_line_mapping_batch_check",
        "checker_class": "UnityChipBatchCheckerFileLineMap",
        "checked_in_last_run": True,
        "last_check_pass": False,
        "last_msg": {
            "error_code": "LINE_MAP_UNCOVERED_LINES",
            "error": "docs/spec.md has 2 uncovered non-blank lines.",
            "artifact": "out/line_map/docs_spec_md_line_func_map.txt",
            "line_block": "docs/spec.md:1-10",
            "uncovered_line_count": 2,
            "uncovered_blocks": ["3-4"],
            "uncovered_content": uncovered_content,
            "next_action": "Add mappings for block 3-4, then call `Check` again.",
        },
    }]

    summary = StageManager._build_failure_summary(
        SimpleNamespace(name="functional_line_mapping_gap_analysis"),
        check_info,
        "generic remediation",
        stage_index=8,
    )

    assert summary["error_code"] == "LINE_MAP_UNCOVERED_LINES"
    assert summary["uncovered_line_count"] == 2
    assert summary["uncovered_blocks"] == ["3-4"]
    assert summary["uncovered_content"] == uncovered_content
    assert summary["next_action"] == (
        "Add mappings for block 3-4, then call `Check` again."
    )


def test_check_reports_batch_advance_as_progress_not_failure():
    class BatchStage:
        name = "generate_random_test_cases"
        is_batch_success = True

        @staticmethod
        def do_check(**_kwargs):
            return False, [{
                "name": "RandomTestCasesChecker",
                "checker_name": "random_test_check",
                "checker_class": "RandomTestCasesChecker",
                "checked_in_last_run": True,
                "last_check_pass": False,
                "last_msg": {
                    "success": "The current batch completed.",
                    "current_batch": [{"CK": "FG-A/FC-A/CK-NEXT"}],
                },
            }]

    manager = StageManager.__new__(StageManager)
    manager.stage_index = 3
    manager.stages = [None] * 3 + [BatchStage()]
    manager.last_check_info = None
    manager.gen_fail_suggestion = lambda _data: pytest.fail(
        "batch progress must not invoke failure suggestions"
    )

    result = manager.check(30)

    assert result["check_pass"] is False
    assert "failure_summary" not in result
    assert result["progress_summary"]["status"] == "batch_advanced"
    assert result["progress_summary"]["checker_name"] == "random_test_check"
    assert result["progress_summary"]["progress"]["current_batch"] == [
        {"CK": "FG-A/FC-A/CK-NEXT"}
    ]
    assert "not a validation failure" in result["progress_summary"]["diagnostic_note"]
    assert "Do not redo the completed batch" in result["action"]
    assert "check_info" not in result


def test_complete_reports_batch_advance_as_progress_not_failure():
    class BatchStage:
        name = "batch_stage"
        is_batch_success = True

        @staticmethod
        def do_check(**_kwargs):
            return False, [{
                "name": "BatchChecker",
                "checker_name": "batch_check",
                "checker_class": "BatchChecker",
                "checked_in_last_run": True,
                "last_check_pass": False,
                "last_msg": {
                    "success": "The current batch completed.",
                    "current_batch": ["next-item"],
                },
            }]

    manager = StageManager.__new__(StageManager)
    manager.stage_index = 1
    manager.stages = [None, BatchStage()]
    manager.last_check_info = None
    manager.gen_fail_suggestion = lambda _data: pytest.fail(
        "batch progress must not invoke failure suggestions"
    )

    result = manager.complete(30)

    assert result["complete"] is False
    assert result["check_pass"] is False
    assert result["message"] == "The current batch passed. Continue with the next batch."
    assert result["progress_summary"]["status"] == "batch_advanced"
    assert result["progress_summary"]["progress"]["current_batch"] == [
        "next-item"
    ]
    assert "failure_summary" not in result
    assert "check_info" not in result


def test_failure_summary_uses_current_run_not_historical_count_fail():
    check_info = [
        {
            "name": "HistoricalChecker",
            "checker_name": "historical_check",
            "checked_in_last_run": False,
            "last_check_pass": False,
            "count_fail": 100,
            "last_msg": {"error": "[Old Failure] stale diagnostic"},
        },
        {
            "name": "CurrentChecker",
            "checker_name": "current_check",
            "checked_in_last_run": True,
            "last_check_pass": False,
            "count_fail": 1,
            "last_msg": {"error": "[Current Failure] concrete current diagnostic"},
        },
        None,
    ]

    summary = StageManager._build_failure_summary(
        SimpleNamespace(name="stage"), check_info, "fix current failure", stage_index=7
    )

    assert summary["failed_checker_index"] == 1
    assert summary["failed_checker_name"] == "current_check"
    assert summary["error_code"] == "CURRENT_FAILURE"
    assert summary["remaining_checkers_not_run"] == 1


def test_compact_check_result_keeps_legacy_diagnostics():
    legacy_result = {
        "check_pass": False,
        "check_info": [{"last_msg": {"error": "legacy concrete error"}}],
    }

    assert StageManager._compact_check_result(legacy_result) is legacy_result


def test_disabled_fail_suggestion_omits_duplicate_check_info():
    manager = StageManager.__new__(StageManager)
    manager.stage_index = 0
    manager.stages = [
        SimpleNamespace(
            name="test_case_implementation_in_batch",
            need_fail_llm_suggestion=False,
        )
    ]
    manager.llm_fail_suggestion = None
    raw_result = {
        "failure_summary": {"error": "[Current Failure] repair this"},
        "check_pass": False,
        "action": "repair this",
        "check_info": [
            {
                "last_msg": {
                    "error": "[Current Failure] repair this",
                    "STDOUT": "duplicate verbose output" * 100,
                }
            }
        ],
    }

    compact = manager.gen_fail_suggestion(raw_result)

    assert compact == {
        "failure_summary": {"error": "[Current Failure] repair this"},
        "check_pass": False,
        "action": "repair this",
    }
    assert "check_info" not in compact


def test_verify_stage_marks_only_current_checker_as_run():
    class StubChecker:
        def __init__(self, passed, message):
            self.passed = passed
            self.message = message

        def check(self, *_args, **_kwargs):
            return self.passed, self.message

    stage = VerifyStage.__new__(VerifyStage)
    stage.cfg = SimpleNamespace(skill=SimpleNamespace(use_skill=False))
    stage.skill_list = {}
    stage._is_reached = False
    stage.reference_files = {}
    stage.output_files = []
    stage.workspace = ""
    stage.checker = [StubChecker(False, {"error": "current"}), StubChecker(True, "unused")]
    stage._checker = [SimpleNamespace(name="current"), SimpleNamespace(name="later")]
    stage.check_info = [
        {
            "name": "OldChecker",
            "checker_name": "old",
            "checker_class": "OldChecker",
            "checked_in_last_run": True,
            "last_check_pass": False,
            "last_msg": {"error": "old"},
            "count_pass": 0,
            "count_fail": 5,
            "count_check": 5,
        },
        {
            "name": "LaterChecker",
            "checker_name": "later",
            "checker_class": "LaterChecker",
            "checked_in_last_run": True,
            "last_check_pass": True,
            "last_msg": "previous",
            "count_pass": 1,
            "count_fail": 0,
            "count_check": 1,
        },
    ]
    stage.is_batch_success = False
    stage.fail_count = 0
    stage.continue_fail_count = 0
    stage.succ_count = 0

    passed, check_info = stage._do_check()

    assert passed is False
    assert check_info[0]["checked_in_last_run"] is True
    assert check_info[0]["last_check_pass"] is False
    assert check_info[0]["last_msg"] == {"error": "current"}
    assert check_info[1]["checked_in_last_run"] is False
    assert check_info[1]["count_check"] == 1


def _make_output_gate_stage(tmp_path, checker, output_files):
    stage = VerifyStage.__new__(VerifyStage)
    stage.name = "generic-output-stage"
    stage.cfg = SimpleNamespace(skill=SimpleNamespace(use_skill=False))
    stage.skill_list = {}
    stage._is_reached = False
    stage.reference_files = {}
    stage.output_files = output_files
    stage.workspace = str(tmp_path)
    stage.checker = [checker]
    stage._checker = [SimpleNamespace(name="configured_check")]
    stage.check_info = [None]
    stage.is_batch_success = False
    stage.fail_count = 0
    stage.continue_fail_count = 0
    stage.succ_count = 0
    stage.last_do_check_info_pass = None
    stage.last_do_check_info_fail = None
    return stage


def test_verify_stage_checker_diagnostic_precedes_missing_output_gate(tmp_path):
    class LineMapLikeChecker:
        def check(self, **_kwargs):
            return False, {
                "error_code": "LINE_MAP_FILE_MISSING",
                "error": "The current mapping file is missing.",
                "artifact": "resolved/line_map/docs_spec_md_line_func_map.txt",
                "line_block": "docs/spec.md:1-10",
                "expected": "Create the canonical mapping file for this line block.",
                "next_action": (
                    "Create 'resolved/line_map/docs_spec_md_line_func_map.txt', "
                    "then call `Check` again."
                ),
                "current_line_block_contents": [{
                    "line_block": "docs/spec.md:1-10",
                    "map_file": "resolved/line_map/docs_spec_md_line_func_map.txt",
                }],
            }

    stage = _make_output_gate_stage(
        tmp_path,
        LineMapLikeChecker(),
        ["resolved/line_map/*_line_func_map.txt"],
    )

    passed, check_info = stage._do_check()

    assert passed is False
    assert len(check_info) == 1
    assert check_info[0]["checker_name"] == "configured_check"
    assert check_info[0]["last_msg"]["current_line_block_contents"][0][
        "map_file"
    ] == "resolved/line_map/docs_spec_md_line_func_map.txt"
    summary = StageManager._build_failure_summary(
        stage,
        check_info,
        "generic remediation",
        stage_index=5,
    )
    assert summary["failed_checker_name"] == "configured_check"
    assert summary["failed_checker_class"] == "LineMapLikeChecker"
    assert summary["error_code"] == "LINE_MAP_FILE_MISSING"
    assert summary["artifact"] == (
        "resolved/line_map/docs_spec_md_line_func_map.txt"
    )
    assert summary["line_block"] == "docs/spec.md:1-10"
    assert summary["next_action"].startswith(
        "Create 'resolved/line_map/docs_spec_md_line_func_map.txt'"
    )


def test_output_gate_reports_all_resolved_patterns_and_matches(tmp_path):
    class PassingChecker:
        def check(self, **_kwargs):
            return True, "ok"

    (tmp_path / "resolved").mkdir()
    (tmp_path / "resolved" / "ready.md").write_text("ready\n", encoding="utf-8")
    output_files = [
        "resolved/ready.md",
        "resolved/line_map/*_line_func_map.txt",
        "resolved/reports/*.json",
    ]
    stage = _make_output_gate_stage(
        tmp_path,
        PassingChecker(),
        output_files,
    )
    manager = StageManager.__new__(StageManager)
    manager.stage_index = 0
    manager.stages = [stage]
    manager.last_check_info = None
    manager.gen_fail_suggestion = lambda data: data

    result = manager.check(30)
    summary = result["failure_summary"]

    assert result["check_pass"] is False
    assert result["check_info"][-1]["last_msg"]["error"] == summary["error"]
    assert summary["failed_checker_index"] == 1
    assert summary["failed_checker_name"] == "stage_output_files"
    assert summary["failed_checker_class"] == "OutputFileGate"
    assert summary["error_code"] == "OUTPUT_FILE_PATTERN_MISSING"
    assert summary["remaining_checkers_not_run"] == 0
    assert "2 of 3" in summary["error"]
    assert "resolved/line_map/*_line_func_map.txt" in summary["error"]
    assert "resolved/reports/*.json" in summary["error"]
    assert summary["observed"]["matches_by_pattern"] == {
        "resolved/ready.md": ["resolved/ready.md"],
        "resolved/line_map/*_line_func_map.txt": [],
        "resolved/reports/*.json": [],
    }
    assert summary["observed"]["workspace"] == str(tmp_path)
    assert summary["expected"]["required_patterns"] == output_files
    assert summary["expected"]["missing_patterns"] == output_files[1:]
    assert "literal '*'" in summary["next_action"]
    assert summary["next_action"].endswith("Then call `Check` again.")


def test_output_gate_complete_failure_names_complete_as_next_action(tmp_path):
    class PassingChecker:
        def check(self, **_kwargs):
            return True, "ok"

    stage = _make_output_gate_stage(
        tmp_path,
        PassingChecker(),
        ["resolved/final.md"],
    )

    passed, check_info = stage._do_check(is_complete=True)

    assert passed is False
    diagnostic = check_info[-1]["last_msg"]["diagnostic"]
    assert diagnostic["error_code"] == "OUTPUT_FILE_PATTERN_MISSING"
    assert diagnostic["next_action"].endswith("Then call `Complete` again.")
