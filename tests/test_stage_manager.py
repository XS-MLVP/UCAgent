#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for StageManager progress loading behavior."""

import os
import sys
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
from ucagent.stage.vmanager import StageManager
from ucagent.util import functions as fc


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


def test_stage_time_event_id_includes_task_id(monkeypatch):
    monkeypatch.setenv("UCAGENT_TASK_ID", "task-123")
    cfg = _cfg()
    agent = _FakeAgent(cfg)
    stage = _FakeStage(0)
    stage.prefix = "1"

    manager = StageManager.__new__(StageManager)
    manager.agent = agent
    manager.stages = [stage]
    manager.stage_time_events = {}
    manager.ucagent_info = {}
    manager._stage_time_event_sent_ids = set()

    event = manager._record_stage_event("start", stage)
    client_event_id = "start:executable:1:0:stage-0"
    event_id = f"task-123|{client_event_id}"

    assert event["client_event_id"] == client_event_id
    assert event["event_id"] == event_id
    assert event["task_id"] == "task-123"
    assert list(manager.stage_time_events) == [event_id]
