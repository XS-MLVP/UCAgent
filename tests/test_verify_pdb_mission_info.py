"""Keep text-only mission polling independent of stage history comparisons."""

from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from ucagent.verify_pdb import VerifyPDB


@pytest.mark.parametrize("return_dict", [
    pytest.param(None, id="default-text"),
    pytest.param(False, id="explicit-text"),
    pytest.param(True, id="structured-details"),
])
def test_mission_info_only_collects_outcomes_for_structured_details(return_dict):
    """Text polling skips outcomes; structured details retain past/current results."""
    stages = [Mock() for _ in range(3)]
    for index, stage in enumerate(stages):
        stage.is_completed.return_value = index == 0
        stage.get_stage_outcome.return_value = {"changed_files": [f"stage-{index}.txt"]}
    manager = SimpleNamespace(
        get_current_stage=lambda: stages[1],
        get_stage=lambda index: stages[index],
        llm_fail_suggestion=None,
        llm_pass_suggestion=None,
    )
    pdb = VerifyPDB.__new__(VerifyPDB)
    pdb.agent = SimpleNamespace(
        stage_manager=manager,
        cfg=SimpleNamespace(skill=SimpleNamespace(use_skill=False)),
    )
    pdb.api_task_list = lambda: {
        "mission_name": "Polling regression",
        "task_index": 1,
        "task_list": {"stage_list": [
            {
                "title": f"stage-{index}",
                "fail_count": 0,
                "need_fail_llm_suggestion": False,
                "need_pass_llm_suggestion": False,
                "needs_human_check": index == 1,
            }
            for index in range(3)
        ]},
    }

    for _ in range(3):
        result = (
            pdb.api_mission_info()
            if return_dict is None else pdb.api_mission_info(return_dict)
        )
        if return_dict:
            assert result["current_index"] == 1
            assert [stage["out_come"] for stage in result["stages"]] == [
                {"changed_files": ["stage-0.txt"]},
                {"changed_files": ["stage-1.txt"]},
                None,
            ]
        else:
            assert isinstance(result, list)
            assert all(any(f"stage-{index}" in line for line in result) for index in range(3))

    if return_dict:
        assert stages[0].get_stage_outcome.call_args_list == [call(True)] * 3
        assert stages[1].get_stage_outcome.call_args_list == [call(False)] * 3
    else:
        stages[0].get_stage_outcome.assert_not_called()
        stages[1].get_stage_outcome.assert_not_called()
    stages[2].get_stage_outcome.assert_not_called()
