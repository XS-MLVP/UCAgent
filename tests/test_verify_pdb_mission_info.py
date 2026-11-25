"""Controller mission details are structured and do not expose live stages."""

from types import SimpleNamespace
from unittest.mock import Mock, call

from ucagent.runtime.control.controller import Controller


def test_mission_info_returns_stage_outcomes_as_detached_data():
    stages = [Mock() for _ in range(3)]
    for index, stage in enumerate(stages):
        stage.get_stage_outcome.return_value = {"changed_files": [f"stage-{index}.txt"]}
    rows = [{"index": index, "title": f"stage-{index}", "fail_count": 0,
             "need_fail_llm_suggestion": False, "need_pass_llm_suggestion": False,
             "needs_human_check": index == 1} for index in range(3)]
    manager = SimpleNamespace(
        stage_index=1, stages=stages, get_current_stage=lambda: stages[1],
        status=lambda: {"stage_list": rows},
        llm_fail_suggestion=None, llm_pass_suggestion=None,
    )
    agent = SimpleNamespace(
        cfg=SimpleNamespace(get_value=lambda _key, default=None: "Polling regression" if default else default),
        stage_manager=manager,
    )
    controller = Controller.__new__(Controller)
    controller.agent = agent

    result = controller.mission_info()

    assert result["mission_name"] == "Polling regression"
    assert result["current_index"] == 1
    assert [stage["outcome"] for stage in result["stages"]] == [
        {"changed_files": ["stage-0.txt"]},
        {"changed_files": ["stage-1.txt"]},
        None,
    ]
    assert stages[0].get_stage_outcome.call_args_list == [call()]
    assert stages[1].get_stage_outcome.call_args_list == [call()]
    stages[2].get_stage_outcome.assert_not_called()
