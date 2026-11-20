"""Regressions from stage 3 graph exhaustion, invalid completion and artifact paths."""

import pytest
from langchain_core.messages import AIMessage

from multi_agent_fakes import install_planner
from test_multi_agent import make_agent, stage, tool, finish
from test_multi_agent_supervisor import plan_message
from test_multi_agent_worker_context import ContextModel, call


def test_worker_can_use_authorized_model_rounds_without_graph_restart(tmp_path, monkeypatch):
    """Seventy-five real model/tool rounds fit the default eighty-round logical budget."""
    import ucagent.core.backends.langchain.agent as backend_module
    models = []

    def choose(model, messages):
        """Exercise enough real middleware nodes to reproduce the former 250-step cutoff."""
        if len(model.seen) < 73:
            return call("CurrentTips")
        if len(model.seen) == 73:
            return call("EditTextFile", path="out/result.md", content="evidence after long work")
        if len(model.seen) == 74:
            return call("SetCurrentStageJournal", journal="Long authorized task completed")
        return call("Complete")

    def factory(cfg, callbacks, **kwargs):
        """Allocate real graph providers without any online model calls."""
        model = ContextModel(choose=choose, callbacks=callbacks)
        models.append(model)
        return model

    monkeypatch.setattr(backend_module, "get_chat_model", factory)
    monkeypatch.setattr(backend_module, "negotiate_openai_api_mode", lambda cfg, **kwargs: None)
    value = make_agent(tmp_path)
    value.message_echo = lambda *args, **kwargs: None
    try:
        value.multi_agent.submit({"plan_id": "long", "tasks": [{"id": "t", "instruction": "Long work"}]})
        result = finish(value.multi_agent, "long", 15)
        assert result["plans"]["long"]["state"] == "completed", result["tasks"]
        assert result["metrics"]["worker_starts"] == 1
        assert value.multi_agent.records["long/t"].rounds == 75
    finally:
        value._startup_cleanup.close()


def test_supervisor_can_use_its_full_model_budget(tmp_path, monkeypatch):
    """The planner's graph step count must not cut short eight authorized model calls."""
    value = make_agent(tmp_path)
    value.message_echo = lambda *args, **kwargs: None

    def decide(context, turn):
        """Read current requirements seven times, delegate once, then summarize."""
        if context["workflow_complete"]:
            return AIMessage(content="Verified complete")
        if turn < 8:
            return call("CurrentTips")
        return plan_message(context, "eight", [{"id": "t", "instruction": "Write evidence"}])

    planner = install_planner(value, monkeypatch, decide)

    def run(worker):
        """Satisfy the actual stage gate after the full planning round budget."""
        tool(worker, "EditTextFile", path="out/result.md", content="evidence")
        tool(worker, "SubmitTaskResult", summary="Evidence ready")

    value.multi_agent.runner_factory = run
    try:
        value.one_loop()
        assert value.multi_agent.workflow_state == "completed", value.multi_agent.status()
        assert len(planner.contexts) == 9
    finally:
        value._startup_cleanup.close()


@pytest.mark.parametrize("field", ["inputs", "outputs"])
@pytest.mark.parametrize("path", ["out/*_map.txt", "out/?.txt", "out/[ab].txt", "out/directory"])
def test_artifact_patterns_and_directories_fail_before_worker_start(tmp_path, field, path):
    """A bad artifact contract is corrected before it can waste a complete worker attempt."""
    value = make_agent(tmp_path)
    (tmp_path / "out/directory").mkdir(parents=True, exist_ok=True)
    try:
        with pytest.raises(ValueError, match="concrete file"):
            value.multi_agent.submit({"plan_id": "bad", "tasks": [
                {"id": "t", "instruction": "Work", field: [path]}]})
        assert value.multi_agent.records == {}
        assert value.multi_agent.driver.active_lease is None
    finally:
        value._startup_cleanup.close()


@pytest.mark.parametrize("group", [True, False])
def test_scoped_complete_keeps_subtree_and_parent_gates(tmp_path, group):
    """Complete is usable, token-fenced, and cannot advance to the next unrelated root."""
    value = make_agent(tmp_path, stages=[stage("root", stage=[
        stage("child", output_files=["out/child.txt"])],
        **({} if group else {"output_files": ["out/child.txt"]})), stage("next")])
    observed = []

    def run(worker):
        """Use the compatibility tool while retaining real child validation and root ownership."""
        observed.append(worker.thread_id)
        current = tool(worker, "CurrentTips")
        no_token = tool(worker, "Complete")
        assert no_token["error_code"] == "STEP_TOKEN_REQUIRED"
        assert value.stage_manager.stage_index == 0
        failed = tool(worker, "Complete", step_token=current["step_token"])
        assert not failed["validation"].get("complete")
        tool(worker, "EditTextFile", path="out/child.txt", content="child evidence")
        tool(worker, "SetCurrentStageJournal", journal="Child evidence created")
        result = tool(worker, "Complete", step_token=failed["step_token"])
        assert result["validation"]["complete"] and result["scope_done"]
        stale = tool(worker, "Complete", step_token=failed["step_token"])
        assert stale["error_code"] == "STALE_STEP_TOKEN"
        done = tool(worker, "Complete")
        assert done["scope_done"] and done["next_action"] == "SubmitTaskResult"
        assert worker.record.result is None
        tool(worker, "SubmitTaskResult", summary="Authorized subtree complete")

    value.multi_agent.runner_factory = run
    try:
        value.multi_agent.submit({"plan_id": "subtree", "tasks": [{"id": "t", "instruction": "Work"}]})
        result = finish(value.multi_agent, "subtree")
        assert result["plans"]["subtree"]["state"] == "completed", result
        assert value.stage_manager.get_current_stage().name == "next"
        assert len(observed) == 1
    finally:
        value._startup_cleanup.close()


@pytest.mark.parametrize("valid", [True, False])
def test_stage_complete_submits_and_leaves_final_checker_authoritative(tmp_path, valid):
    """A scoped Complete submits a journal; it never declares acceptance before writer teardown."""
    value = make_agent(tmp_path, limits={"task_max_attempts": 1})
    submitted = []

    def run(worker):
        """Emulate the 3.4 finishing worker using a concrete output contract and Complete."""
        missing = tool(worker, "Complete")
        assert missing["error_code"] == "STAGE_JOURNAL_REQUIRED"
        if valid:
            tool(worker, "EditTextFile", path="out/result.md", content="evidence")
        tool(worker, "SetCurrentStageJournal", journal="Actual completion evidence")
        result = tool(worker, "Complete", timeout=500, stage_args={"full_output": True})
        assert result["submitted"] and result["validation_pending"]
        assert not result["complete"] and value.stage_manager.stage_index == 0
        assert worker.record.result["timeout"] == 500
        assert worker.record.result["stage_args"] == {"full_output": True}
        submitted.append(result)
        with pytest.raises(PermissionError, match="stopped"):
            tool(worker, "EditTextFile", path="out/late.txt", content="too late")

    value.multi_agent.runner_factory = run
    try:
        value.multi_agent.submit({"plan_id": "finish", "scope": "stage", "tasks": [{"id": "t", "instruction": "Close step"}]})
        result = finish(value.multi_agent, "finish")
        assert result["plans"]["finish"]["state"] == ("completed" if valid else "failed"), result
        assert len(submitted) == 1
    finally:
        value._startup_cleanup.close()


def test_graph_limit_configuration_is_preserved_and_failure_is_logged(tmp_path, monkeypatch):
    """An explicitly small graph guard remains effective and its exit is diagnosable."""
    import ucagent.core.backends.langchain.agent as backend_module
    monkeypatch.setattr(backend_module, "get_chat_model", lambda *args, **kwargs:
                        ContextModel(choose=lambda model, messages: call("CurrentTips")))
    monkeypatch.setattr(backend_module, "negotiate_openai_api_mode", lambda cfg, **kwargs: None)
    value = make_agent(tmp_path, config_overrides={"recursion_limit": 10}, limits={"task_max_attempts": 1})
    value.message_echo = lambda *args, **kwargs: None
    try:
        value.multi_agent.submit({"plan_id": "guard", "tasks": [{"id": "t", "instruction": "Read"}]})
        result = finish(value.multi_agent, "guard")
        event = next(e for e in result["events"] if e["event"] == "task_finished")
        assert event["state"] == "failed" and event["error_type"] == "GraphRecursionError"
        assert "Recursion limit of 10" in event["error"]
        assert event["stage_index"] == 0
        assert 0 < event["budget"]["model_rounds_used"] < event["budget"]["model_rounds_limit"]
        assert result["tasks"][0]["budget"]["model_rounds_limit"] == 80
    finally:
        value._startup_cleanup.close()


@pytest.mark.parametrize("gate", ["human", "skill"])
def test_scoped_complete_cannot_bypass_review_or_skill_gate(tmp_path, gate):
    """Compatibility with the tool name must retain real completion evidence requirements."""
    if gate == "skill":
        skill = tmp_path / ".ucagent/skills/probe/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: probe\ndescription: Check evidence.\n---\nRead evidence.\n")
    value = make_agent(tmp_path, limits={"task_max_attempts": 1},
        stages=[stage("gated", output_files=["out/result.md"], **(
            {"need_human_check": True} if gate == "human" else {"skill_list": ["probe"]}))],
        config_overrides={"skill.use_skill": gate == "skill"})
    submissions = []

    def run(worker):
        """Submit an actual output but deliberately leave the extra gate unsatisfied."""
        tool(worker, "EditTextFile", path="out/result.md", content="evidence")
        tool(worker, "SetCurrentStageJournal", journal="Evidence written; gate remains")
        submissions.append(tool(worker, "Complete"))

    value.multi_agent.runner_factory = run
    try:
        value.multi_agent.submit({"plan_id": "gated", "tasks": [{"id": "t", "instruction": "Close step"}]})
        result = finish(value.multi_agent, "gated")
        assert len(submissions) == 1 and submissions[0]["validation_pending"]
        assert result["plans"]["gated"]["state"] == ("waiting_human" if gate == "human" else "failed")
        assert not value.stage_manager.stages[0].is_completed()
    finally:
        value._startup_cleanup.close()
