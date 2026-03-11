from types import SimpleNamespace

import ucagent.util.functions as fc
from ucagent.stage.vmanager import StageManager


class DummyFreeChecker:
    def __init__(self, *args, **kwargs):
        pass

    def set_workspace(self, workspace):
        return self


class DummyAgent:
    def __init__(self):
        self.exited = False
        self._exit_on_completion = False

    def get_stat_info(self):
        return {}

    def is_exit(self):
        return self.exited

    def exit(self):
        self.exited = True

    def try_exit_on_completion(self):
        return None

    def is_break(self):
        return False

    def message_echo(self, msg):
        return None


class DummyStage:
    def __init__(self, name="stage-0", journal="done"):
        self.name = name
        self.fail_count = 0
        self.meta_data = {"journal": journal}
        self.need_fail_llm_suggestion = None
        self.need_pass_llm_suggestion = None
        self._reached = False
        self._skipped = False
        self.is_complete = False
        self.time_prev_cost = 0.0
        self.init_calls = 0
        self.hist_init_calls = 0
        self.vmanager = None

    def title(self):
        return self.name

    def detail(self):
        return {
            "task": {"reference_files": {}},
            "reached": self._reached,
            "is_completed": self.is_complete,
            "fail_count": self.fail_count,
            "is_skipped": self._skipped,
            "last_human_check_result": None,
            "last_human_check_msg": "",
        }

    def set_fail_count(self, value):
        self.fail_count = value

    def set_time_prev_cost(self, value):
        self.time_prev_cost = value

    def set_reference_file_status(self, status):
        return None

    def set_stage_manager(self, manager):
        self.vmanager = manager

    def on_init(self):
        self.init_calls += 1

    def hist_init(self):
        self.hist_init_calls += 1

    def meta_get_journal(self):
        return self.meta_data.get("journal")

    def do_check(self, **kwargs):
        return True, {"message": "ok"}

    def get_approved(self):
        return True

    def is_hmcheck_needed(self):
        return False

    def get_hmcheck_state(self):
        return None, ""

    def on_complete(self):
        self.is_complete = True

    def is_completed(self):
        return self.is_complete

    def set_reached(self, reached):
        self._reached = reached

    def is_reached(self):
        return self._reached

    def set_skip(self, skipped):
        self._skipped = skipped

    def is_skipped(self):
        return self._skipped

    def task_info(self):
        return "task"

    def get_time_start_str(self):
        return ""

    def get_time_end_str(self):
        return ""

    def get_time_cost_str(self):
        return ""

    def get_time_cost(self):
        return self.time_prev_cost


class DummyRootStage:
    def __init__(self, stages):
        self._stages = stages

    def get_substages(self):
        return self._stages


def make_cfg():
    return SimpleNamespace(
        mission=SimpleNamespace(name="demo-mission"),
        tools=SimpleNamespace(RunTestCases=SimpleNamespace(test_dir="tests")),
        vmanager=SimpleNamespace(
            llm_suggestion=SimpleNamespace(
                check_fail_refinement=None,
                check_pass_refinement=None,
            )
        ),
    )


def patch_manager_deps(monkeypatch, stages):
    monkeypatch.setattr("ucagent.stage.vmanager.UnityChipCheckerTestFree", DummyFreeChecker)
    monkeypatch.setattr("ucagent.stage.vmanager.get_root_stage", lambda cfg, workspace, tool_read_text: DummyRootStage(stages))
    monkeypatch.setattr("ucagent.stage.vmanager.get_llm_check_instance", lambda *args, **kwargs: None)


def test_complete_last_stage_persists_all_completed(monkeypatch, tmp_path):
    stage = DummyStage()
    patch_manager_deps(monkeypatch, [stage])

    manager = StageManager(
        str(tmp_path),
        make_cfg(),
        DummyAgent(),
        tool_read_text=object(),
        ucagent_info={},
        tool_inspect_file=[],
    )
    manager.init_stage()

    result = manager.complete(timeout=0)
    saved = fc.load_ucagent_info(str(tmp_path))

    assert result["complete"] is True
    assert manager.stage_index == 1
    assert manager.all_completed is True
    assert saved["all_completed"] is True
    assert saved["stage_index"] == 1
    assert saved["stages_info"]["0"]["is_completed"] is True


def test_init_stage_restores_completed_mission_from_stage_index(monkeypatch, tmp_path):
    stage = DummyStage()
    patch_manager_deps(monkeypatch, [stage])

    saved_info = {
        "stage_index": 1,
        "all_completed": False,
        "stages_info": {
            "0": {
                "task": {"reference_files": {}},
                "reached": True,
                "is_completed": True,
                "fail_count": 0,
                "is_skipped": False,
                "time_cost": 0.0,
            }
        },
    }

    manager = StageManager(
        str(tmp_path),
        make_cfg(),
        DummyAgent(),
        tool_read_text=object(),
        ucagent_info=saved_info,
        force_stage_index=1,
        tool_inspect_file=[],
    )
    manager.init_stage()

    assert manager.stage_index == 1
    assert manager.all_completed is True
    assert stage.init_calls == 0
    assert stage.hist_init_calls == 0
    assert manager.exit()["exit"] is True
