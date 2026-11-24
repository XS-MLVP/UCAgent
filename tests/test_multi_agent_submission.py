"""Worker submission boundaries across batches, mutable evidence and completion gates."""

from pathlib import Path

import pytest

from test_multi_agent import finish, make_agent, stage, tool
from ucagent.core.checkers.base import BatchTask, Checker


class SubmissionBatchChecker(Checker):
    """Require two real output batches before a worker may submit its stage."""

    def __init__(self, cfg):
        """Allocate batch state without inspecting workspace files during construction."""
        super().__init__()
        self.batch_size = 1
        self.batch = BatchTask("outputs", self)

    def on_init(self):
        """Bind the batch goals after the production stage has attached its workspace."""
        self.batch.sync_source_task(["out/first.txt", "out/second.txt"], [], "Required outputs")
        self.batch.update_current_tbd()
        return super().on_init()

    def do_check(self, is_complete=False, **kwargs):
        """Advance only batches backed by nonempty files and retain completion semantics."""
        generated = [name for name in self.batch.source_task_list
                     if (Path(self.workspace) / name).is_file()
                     and (Path(self.workspace) / name).read_text().strip()]
        self.batch.sync_gen_task(generated, [], "Observed outputs")
        return self.batch.do_complete([], is_complete, "missing output", "extra output", "")


def batch_stage():
    """Declare the same real batch stage for local and MCP execution tests."""
    return stage("batches", checker=[{
        "name": "batch", "clss": "test_multi_agent_submission.SubmissionBatchChecker",
        "args": {}, "extra_args": {}}])


@pytest.mark.parametrize("scope", ["auto", "stage"])
def test_all_batches_stay_in_one_worker_and_submit_only_after_check(tmp_path, scope):
    """Early submission never tears down the worker or starts a new planning round."""
    agent = make_agent(tmp_path, stages=[batch_stage()])
    identities = []

    def run(worker):
        """Process both real batches, including rejected submissions at each boundary."""
        identities.append(worker.session_id)
        names = {entry.name for entry in worker.test_tools}
        assert "Check" in names and not names & {"Complete", "CompleteSubStage"}
        assert tool(worker, "CurrentTips")["next_action"] == "Check"
        rejected = tool(worker, "SubmitTaskResult", summary="Not checked")
        assert rejected["error_code"] == "STAGE_CHECK_REQUIRED" and not rejected["submitted"]
        tool(worker, "EditTextFile", path="out/first.txt", content="first evidence")
        checked = tool(worker, "Check")
        assert not checked["check_pass"]
        assert checked["progress_summary"]["status"] == "batch_advanced"
        assert checked["next_action"] == "Check" and not checked["submission"]["ready"]
        tool(worker, "SetCurrentStageJournal", journal="First batch checked")
        rejected = tool(worker, "SubmitTaskResult", summary="Only the first batch")
        assert not rejected["submitted"] and worker.record.result is None
        assert not worker.is_break() and worker.record.attempt == 1
        tool(worker, "EditTextFile", path="out/second.txt", content="second evidence")
        assert not tool(worker, "SubmitTaskResult", summary="Unchecked second batch")["submitted"]
        checked = tool(worker, "Check")
        assert checked["check_pass"] and checked["submission"]["ready"]
        assert checked["next_action"] == "SubmitTaskResult"
        tool(worker, "SetCurrentStageJournal", journal="Both batches checked")
        submitted = tool(worker, "SubmitTaskResult", summary="Both batches complete")
        assert submitted["submitted"] and submitted["validation_pending"]

    agent.multi_agent.runner_factory = run
    try:
        agent.multi_agent.submit({"plan_id": "batches", "scope": scope,
                                  "tasks": [{"id": "work", "instruction": "Complete every batch"}]})
        result = finish(agent.multi_agent, "batches")
        assert result["plans"]["batches"]["state"] == "completed", result
        assert len(identities) == result["metrics"]["worker_starts"] == 1
        assert result["tasks"][0]["attempt"] == 1
        assert not any(event["event"] == "task_retry_suppressed" for event in result["events"])
    finally:
        agent._startup_cleanup.close()


def test_ready_submission_requires_fresh_check_and_keeps_journal_step(tmp_path):
    """Writes revoke submission readiness, but read-only work and journals do not."""
    agent = make_agent(tmp_path)

    def run(worker):
        """Exercise all readiness transitions through public tools without another worker."""
        tool(worker, "EditTextFile", path="out/result.md", content="first version")
        checked = tool(worker, "Check", stage_args={"full_output": True})
        assert checked["check_pass"] and checked["next_action"] == "SetCurrentStageJournal"
        assert worker.record.result is None
        assert tool(worker, "SubmitTaskResult", summary="Missing journal")["error_code"] == "STAGE_JOURNAL_REQUIRED"
        tool(worker, "SetCurrentStageJournal", journal="  \n ")
        assert tool(worker, "SubmitTaskResult", summary="Blank journal")["error_code"] == "STAGE_JOURNAL_REQUIRED"
        tool(worker, "SetCurrentStageJournal", journal="Checked the first version")
        assert tool(worker, "CurrentTips")["submission"]["ready"]
        tool(worker, "ReadTextFile", path="out/result.md")
        assert tool(worker, "CurrentTips")["submission"]["ready"]
        tool(worker, "EditTextFile", path="out/result.md", content="second version")
        assert not tool(worker, "CurrentTips")["submission"]["ready"]
        assert tool(worker, "SubmitTaskResult", summary="Stale check")["error_code"] == "STAGE_CHECK_REQUIRED"
        assert tool(worker, "Check", stage_args={"full_output": True})["check_pass"]
        assert tool(worker, "SubmitTaskResult", summary="Checked the new version")["submitted"]
        assert worker.record.result["stage_args"] == {"full_output": True}
        with pytest.raises(PermissionError, match="stopped"):
            tool(worker, "Check")

    agent.multi_agent.runner_factory = run
    try:
        agent.multi_agent.submit({"plan_id": "fresh", "tasks": [{"id": "work", "instruction": "Revise evidence"}]})
        result = finish(agent.multi_agent, "fresh")
        assert result["plans"]["fresh"]["state"] == "completed", result
        assert result["metrics"]["worker_starts"] == 1
    finally:
        agent._startup_cleanup.close()


@pytest.mark.parametrize("use_skill", [False, True])
def test_check_keeps_worker_alive_for_skill_evidence_and_journal(tmp_path, use_skill):
    """Skill evidence is registered after Check without invalidating that successful check."""
    if use_skill:
        skill = tmp_path / ".ucagent/skills/probe/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: probe\ndescription: Verify evidence.\n---\nRead the assigned input.\n")
    agent = make_agent(tmp_path, stages=[stage("evidence", skill_list=["probe"], output_files=["out/result.md"])],
                       config_overrides={"skill.use_skill": use_skill})

    def run(worker):
        """Register only real list/read/check evidence and retain the same worker session."""
        tool(worker, "EditTextFile", path="out/result.md", content="evidence")
        if use_skill:
            tool(worker, "ListSkill")
            tool(worker, "ReadTextFile", path=".ucagent/skills/probe/SKILL.md")
        checked = tool(worker, "Check")
        assert checked["check_pass"] and worker.record.result is None
        if use_skill:
            assert checked["next_action"] == "SetSkillUsage"
            rejected = tool(worker, "SubmitTaskResult", summary="Skill not registered")
            assert not rejected["submitted"]
            assert worker.stage_manager.get_current_stage().check_pass
            tool(worker, "SetSkillUsage", skill_usage={"probe": {
                "list": True, "read": True, "use": False, "reason": "No applicable object in this stage"}})
        assert tool(worker, "CurrentTips")["next_action"] == "SetCurrentStageJournal"
        tool(worker, "SetCurrentStageJournal", journal="Verified evidence and recorded Skill applicability")
        assert tool(worker, "SubmitTaskResult", summary="Ready for final acceptance")["submitted"]

    agent.multi_agent.runner_factory = run
    try:
        agent.multi_agent.submit({"plan_id": "evidence", "tasks": [{"id": "work", "instruction": "Verify evidence"}]})
        result = finish(agent.multi_agent, "evidence")
        assert result["plans"]["evidence"]["state"] == "completed", result
        assert result["metrics"]["worker_starts"] == 1
    finally:
        agent._startup_cleanup.close()
