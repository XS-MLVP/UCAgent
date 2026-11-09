"""Agent recovery and repeated-validation stall diagnostics independent of frontends."""

import os
import types
from types import SimpleNamespace
import pytest
from ucagent import VerifyAgent
from ucagent.util.config import Config, load_yaml_with_env_vars
current_dir = os.path.dirname(__file__)

def test_do_work_recovers_pending_tool_calls_before_reraising():
    class _Backend:
        def __init__(self):
            self.errors = []

        def recover_pending_tool_calls(self, error):
            self.errors.append(error)
            return 1

    agent = VerifyAgent.__new__(VerifyAgent)
    agent._exit_on_completion_pending = False
    agent._is_work_busy = False
    agent.stream_output = False
    agent.backend = _Backend()

    def fail_work(_instructions, _config):
        raise RuntimeError("tool execution failed")

    agent.do_work_values = fail_work

    with pytest.raises(RuntimeError, match="tool execution failed"):
        agent.do_work({}, {})

    assert len(agent.backend.errors) == 1
    assert agent.is_work_busy() is False


def _failure_result(error="same actionable failure"):
    return {
        "check_pass": False,
        "failure_summary": {
            "stage_index": 19,
            "stage_name": "generate_random_test_cases",
            "failed_validation_gate_index": 0,
            "error_code": "TEST_REPORT_MISMATCH",
            "error": error,
            "next_action": "Repair the reported artifact and call Check again.",
        },
    }


def _stall_probe(max_stalled_rounds=3):
    agent = VerifyAgent.__new__(VerifyAgent)
    agent._max_stalled_rounds = max_stalled_rounds
    agent._stalled_rounds = 0
    agent._last_stall_signature = None
    agent._need_human = False
    agent.stage_manager = SimpleNamespace(
        validation_revision=0,
        stage_index=19,
        last_check_info={},
    )
    return agent


def _record_validation_round(agent, result, stage_index=19):
    previous_revision = agent.stage_manager.validation_revision
    previous_stage_index = agent.stage_manager.stage_index
    agent.stage_manager.validation_revision += 1
    agent.stage_manager.stage_index = stage_index
    agent.stage_manager.last_check_info = result
    agent._update_stalled_rounds(previous_revision, previous_stage_index)


def test_unchanged_checker_diagnostic_pauses_agent_loop():
    agent = _stall_probe(max_stalled_rounds=3)

    for _ in range(3):
        _record_validation_round(agent, _failure_result())

    assert agent._stalled_rounds == 3
    assert agent._need_human is True


def test_changed_checker_diagnostic_resets_stalled_round_count():
    agent = _stall_probe(max_stalled_rounds=3)

    _record_validation_round(agent, _failure_result())
    _record_validation_round(agent, _failure_result("different actionable failure"))

    assert agent._stalled_rounds == 1
    assert agent._need_human is False


def test_dynamic_summary_metadata_does_not_hide_unchanged_failure():
    agent = _stall_probe(max_stalled_rounds=2)
    first = _failure_result()
    second = _failure_result()
    first["failure_summary"]["details"] = {"attempt": 1}
    second["failure_summary"]["details"] = {"attempt": 2}

    _record_validation_round(agent, first)
    _record_validation_round(agent, second)

    assert agent._stalled_rounds == 2
    assert agent._need_human is True


def test_validation_progress_resets_stalled_round_count():
    agent = _stall_probe(max_stalled_rounds=3)
    _record_validation_round(agent, _failure_result())

    _record_validation_round(
        agent,
        {"check_pass": False, "progress_summary": {"status": "batch_advanced"}},
    )

    assert agent._stalled_rounds == 0
    assert agent._last_stall_signature is None


def test_round_without_new_validation_does_not_count_as_stalled():
    agent = _stall_probe(max_stalled_rounds=2)
    _record_validation_round(agent, _failure_result())

    revision = agent.stage_manager.validation_revision
    agent._update_stalled_rounds(revision, agent.stage_manager.stage_index)

    assert agent._stalled_rounds == 1
    assert agent._need_human is False


def test_disabled_stall_protection_does_not_pause_agent():
    agent = _stall_probe(max_stalled_rounds=0)

    for _ in range(4):
        _record_validation_round(agent, _failure_result())

    assert agent._stalled_rounds == 0
    assert agent._need_human is False


def test_default_config_disables_stalled_checker_pause():
    """Keep automatic Checker-stall escalation opt-in at repository defaults."""
    config_path = os.path.join(current_dir, "..", "ucagent", "setting.yaml")

    config = load_yaml_with_env_vars(config_path)

    assert config["loop_settings"]["max_stalled_rounds"] == 0


def test_swarm_launch_does_not_force_human_check():
    """Keep the example human-check injection documented but inactive."""

    makefile_path = os.path.join(current_dir, "..", "make", "master.mk")
    with open(makefile_path, encoding="utf-8") as makefile_handle:
        makefile = makefile_handle.read()
    override = (
        "--override launch.default_args.extra_args[0:0]=@base64:"
        "LS1vdmVycmlkZQpzdGFnZVstMV0ubmVlZF9odW1hbl9jaGVjaz1UcnVl"
    )
    active_lines = [
        line for line in makefile.splitlines() if not line.lstrip().startswith("#")
    ]

    assert override not in "\n".join(active_lines)
    assert any(
        override in line and line.lstrip().startswith("#")
        for line in makefile.splitlines()
    )


@pytest.mark.parametrize("value", [True, -1, 1.5, "3", None])
def test_max_stalled_rounds_rejects_ambiguous_values(value):
    with pytest.raises(ValueError, match="max_stalled_rounds"):
        VerifyAgent._validated_max_stalled_rounds(value)


@pytest.mark.parametrize("value", [0, 1, 3])
def test_max_stalled_rounds_accepts_non_negative_integers(value):
    assert VerifyAgent._validated_max_stalled_rounds(value) == value
