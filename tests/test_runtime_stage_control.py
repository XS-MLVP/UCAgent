"""Stage coordination against real domain gates, persistence and threaded tool calls."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from ucagent.checkers.base import BatchTask, Checker
from ucagent.control.commands import CommandSession, create_registry
from ucagent.control.controller import Controller, ControlError
from ucagent.control.runtime.operations import OperationExecutor
from ucagent.stage.vmanager import StageManager, ToolDoCheck, ToolDoComplete
from ucagent.util.config import Config
from ucagent.util.functions import load_ucagent_info


class Gate(Checker):
    """A real Checker with controllable results and optional real batch progression."""

    def __init__(self, cfg, batch=False):
        """Register the standard Checker lifecycle before constructing batch state."""
        super().__init__()
        self.cfg = cfg
        self.passed = True
        self.entered = None
        self.release = None
        self.calls = 0
        self.batch_size = 1
        self.batch = BatchTask("items", self) if batch else None
        self.generated = ["a"]

    def on_init(self):
        """Initialize batch goals once the stage and workspace are available."""
        if self.batch is not None:
            self.batch.sync_source_task(["a", "b"], [], "Initialize goals")
            self.batch.update_current_tbd()
        return super().on_init()

    def do_check(self, is_complete=False, **kwargs):
        """Keep an optional blocking check alive, then evaluate actual gate state."""
        self.calls += 1
        if self.entered is not None:
            self.entered.set()
            assert self.release.wait(5), "Test did not release the checker"
        if self.batch is not None:
            self.batch.sync_gen_task(list(self.generated), [], "Observed results")
            return self.batch.do_complete([], is_complete, "missing source", "extra results", "")
        return self.passed, "Evidence accepted" if self.passed else "Evidence missing"


class Agent:
    """Expose the real manager's agent interfaces without loading a model or services."""

    def __init__(self, workspace, cfg):
        """Initialize model scheduling, pause and checkpoint state."""
        self.workspace = str(workspace)
        self.output_dir = str(workspace / "out")
        self.cfg = cfg
        self.backend = SimpleNamespace(on_stage_complete=Mock())
        self._break = False
        self._need_human = False
        self._exited = False
        self._exit_on_completion = False
        self.invoke_round = 0
        self.round_hook = None
        self.test_tools = []

    def is_break(self):
        """Read the cooperative pause state."""
        return self._break

    def set_break(self, value=True):
        """Set pause without interrupting checker or model threads."""
        self._break = value

    def is_exit(self):
        """Read mission exit independently from human review."""
        return self._exited

    def exit(self):
        """Record the domain's successful mission exit."""
        self._exited = True

    def try_exit_on_completion(self):
        """Keep this test process alive after mission completion."""
        return None

    def get_stat_info(self):
        """Supply detached statistics for actual checkpoint serialization."""
        return {"invoke_round": self.invoke_round}

    def status_info(self):
        """Keep control queries independent of blocked model and checker work."""
        return self.get_stat_info()

    def one_loop(self, message=None):
        """Run one controllable call and default to a safe human wait boundary."""
        if self.round_hook is not None:
            self.round_hook()
        self.invoke_round += 1
        self._need_human = True

    def _update_stalled_rounds(self, revision, index):
        """Accept the scheduler's progress snapshot without another execution loop."""
        return None


def build_runtime(workspace, *, saved=None, batch=False):
    """Assemble real stages, Checker and persistence in a temporary workspace."""
    workspace.mkdir(exist_ok=True)
    (workspace / "out").mkdir(exist_ok=True)
    cfg = Config({
        "mission": {"name": "Stage control tests"}, "skill": {"use_skill": False},
        "hist_ignore_pattern": [], "cmd_timeout": 2,
        "vmanager": {"llm_suggestion": {"check_fail_refinement": {"enable": False},
                                        "check_pass_refinement": {"enable": False}}},
        "stage": [{"name": f"stage-{i}", "desc": "Evidence review", "task": ["Verify evidence"],
                   "need_human_check": i == 0,
                   "checker": [{"name": "Evidence", "clss": "Gate", "args": {"batch": batch and i == 0},
                                "extra_args": {}}]} for i in range(3)],
    })
    cfg._temp_cfg = {"OUT": "out"}
    agent = Agent(workspace, cfg)
    manager = StageManager(str(workspace), cfg, agent, None, saved or {},
                           force_stage_index=(saved or {}).get("stage_index", 0),
                           tool_inspect_file=[], checker_registry={"Gate": Gate})
    agent.stage_manager = manager
    manager.init_stage()
    control = Controller(agent)
    owner = OperationExecutor(control)
    return SimpleNamespace(agent=agent, manager=manager, control=control, owner=owner,
                           session=CommandSession(workspace), gate=manager.stages[0].checker[0])


@pytest.fixture
def runtime(tmp_path):
    """Release all owned work at the end of each stage-control test."""
    runtime = build_runtime(tmp_path)
    yield runtime
    assert runtime.owner.close(5)["closed"], "Test left a model or stage mutation running"


def test_control_revision_is_independent_and_queries_are_detached(runtime):
    """Flags and approval invalidate controls without claiming a validation occurred."""
    control, manager = runtime.control, runtime.manager
    before = control.stage_state()
    result = control.update_stage_flags([1], before["control_revision"], hmcheck_needed=True)
    assert result["control_revision"] > before["control_revision"]
    assert manager.validation_revision == 0
    result["updated"][0]["needs_human_check"] = False
    assert control.stage_state()["stages"][1]["needs_human_check"] is True
    review = control.review_stage(0, result["control_revision"], True, "Checked evidence")
    assert review["control_revision"] > result["control_revision"]
    assert manager.validation_revision == 0
    manager.check(1)
    assert manager.validation_revision == 1
    assert control.stage_state()["control_revision"] > review["control_revision"]


@pytest.mark.parametrize("tool_class", [ToolDoCheck, ToolDoComplete])
def test_model_can_wait_for_stage_tool_on_another_thread(runtime, tool_class):
    """MCP-style tool calls must finish while their parent model operation remains live."""
    manager, control, owner = runtime.manager, runtime.control, runtime.owner
    control.review_stage(0, control.stage_state()["control_revision"], True, "Ready")
    manager.set_current_stage_journal("Evidence reviewed")
    entered, release = threading.Event(), threading.Event()

    def model():
        """Represent a model waiting for a separately dispatched tool response."""
        entered.set()
        assert release.wait(5)

    runtime.agent.round_hook = model
    operation = owner.execute("next_round", {}, runtime.session)
    try:
        assert entered.wait(2)
        function = manager.tool_check if tool_class is ToolDoCheck else manager.tool_complete
        tool = tool_class().set_function(function)
        with ThreadPoolExecutor(max_workers=1) as pool:
            response = pool.submit(tool.invoke, {"timeout": 1}).result(timeout=3)
        data = yaml.safe_load(response)
        assert data["check_pass" if tool_class is ToolDoCheck else "complete"] is True
        assert owner.get(operation["id"])["state"] == "running"
    finally:
        release.set()
    assert owner.wait(operation["id"], 3)["state"] == "succeeded"


@pytest.mark.parametrize("operation", ["check", "complete"])
def test_blocked_check_rejects_conflicts_but_allows_queries(runtime, operation):
    """One stage mutation owns admission while its actual Checker remains blocked."""
    manager, control, owner = runtime.manager, runtime.control, runtime.owner
    runtime.gate.entered, runtime.gate.release = threading.Event(), threading.Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        checking = pool.submit(getattr(manager, operation), 1)
        try:
            assert runtime.gate.entered.wait(2)
            snapshot = pool.submit(control.stage_state).result(timeout=1)
            assert snapshot["mutation"] == "validation"
            assert pool.submit(control.status).result(timeout=1) == {"invoke_round": 0}
            for action in (lambda: manager.complete(1), lambda: manager.go_to_stage(1),
                           lambda: manager.stages[0].do_hmcheck_pass("Race"),
                           lambda: control.update_stage_flags([1], snapshot["control_revision"], skip=True),
                           lambda: owner.execute("next_round", {}, runtime.session)):
                with pytest.raises(ControlError) as caught:
                    action()
                assert caught.value.code == "busy"
            assert runtime.gate.calls == 1
        finally:
            runtime.gate.release.set()
        checking.result(timeout=3)
    assert control.stage_state()["mutation"] is None


def test_cancelled_model_retains_reservation_until_mcp_check_finishes(runtime):
    """A cancelled model transport returning early cannot abandon its live tool check."""
    owner, manager, control = runtime.owner, runtime.manager, runtime.control
    model_entered, model_release = threading.Event(), threading.Event()
    runtime.gate.entered, runtime.gate.release = threading.Event(), threading.Event()

    def model():
        """Let the transport return independently from its outstanding MCP request."""
        model_entered.set()
        assert model_release.wait(5)

    runtime.agent.round_hook = model
    operation = owner.execute("next_round", {}, runtime.session)
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            assert model_entered.wait(2)
            checking = pool.submit(manager.check, 1)
            assert runtime.gate.entered.wait(2)
            owner.cancel(operation["id"])
            model_release.set()
            assert owner.wait(operation["id"], 0.05)["state"] == "cancelling"
            with pytest.raises(ControlError):
                owner.execute("next_round", {}, runtime.session)
            with pytest.raises(ControlError):
                control.review_stage(0, control.stage_state()["control_revision"], True)
            assert owner.close(0)["closed"] is False
        finally:
            model_release.set()
            runtime.gate.release.set()
        assert checking.result(timeout=3)["check_pass"] is True
    assert owner.wait(operation["id"], 3)["state"] == "cancelled"
    assert owner.close(1)["closed"] is True


def test_stale_review_does_not_change_state_or_checkpoint(runtime):
    """A validation or stage switch invalidates an approval prepared from older data."""
    control, manager = runtime.control, runtime.manager
    revision = control.stage_state()["control_revision"]
    manager.check(1)
    snapshot = control.stage_state()
    checkpoint = load_ucagent_info(runtime.agent.workspace)
    with pytest.raises(ControlError) as caught:
        control.review_stage(0, revision, True, "Old review")
    assert caught.value.code == "stale_revision"
    assert control.stage_state() == snapshot
    assert load_ucagent_info(runtime.agent.workspace) == checkpoint
    manager.force_go_to_stage(1)
    snapshot = control.stage_state()
    with pytest.raises(ControlError) as caught:
        control.review_stage(0, snapshot["control_revision"], True)
    assert caught.value.code == "stale_stage"
    assert control.stage_state() == snapshot


def test_human_approval_cannot_bypass_checker_or_journal_gates(runtime):
    """Approval never replaces Checker's evidence validation or the stage journal gate."""
    control, manager = runtime.control, runtime.manager
    control.review_stage(0, control.stage_state()["control_revision"], True, "Human approved")
    runtime.gate.passed = False
    assert manager.complete(1)["check_pass"] is False
    assert manager.stage_index == 0 and not manager.stages[0].is_completed()
    runtime.gate.passed = True
    assert manager.complete(1)["complete"] is False
    manager.set_current_stage_journal("Actual evidence recorded")
    assert manager.complete(1)["complete"] is True
    assert manager.stage_index == 1 and manager.stages[0].is_completed()


def test_human_rejection_and_missing_review_block_completion(runtime):
    """Required review retains the workflow gate and the reviewer's explanation."""
    control, manager = runtime.control, runtime.manager
    manager.set_current_stage_journal("Evidence pending review")
    assert manager.complete(1)["complete"] is False
    control.review_stage(0, control.stage_state()["control_revision"], False, "Missing coverage")
    rejected = manager.complete(1)
    assert rejected["complete"] is False
    assert rejected["human_review_msg"] == "Missing coverage"
    assert runtime.agent._need_human is True
    assert manager.stage_index == 0


def test_approve_and_continue_starts_only_after_successful_persistence(runtime, monkeypatch):
    """The resumed round observes saved approval and an available stage reservation."""
    control, manager, owner = runtime.control, runtime.manager, runtime.owner
    revision = control.stage_state()["control_revision"]
    with pytest.raises(ControlError):
        control.review_stage(0, revision - 1, True, resume=True, session=runtime.session)
    assert owner.list() == []
    with monkeypatch.context() as patch:
        patch.setattr(manager, "save_stage_info", Mock(side_effect=OSError("Checkpoint unavailable")))
        with pytest.raises(OSError, match="Checkpoint unavailable"):
            control.review_stage(0, revision, True, resume=True, session=runtime.session)
    assert owner.list() == []
    observations = []

    def round_after_review():
        """Read the actual checkpoint and call Check from the newly admitted model."""
        saved = load_ucagent_info(runtime.agent.workspace)
        observations.append(saved["stages_info"]["0"]["last_human_check_result"])
        observations.append(manager.check(1)["check_pass"])

    runtime.agent.round_hook = round_after_review
    result = control.review_stage(0, control.stage_state()["control_revision"], True, "Approved",
                                  resume=True, session=runtime.session)
    assert owner.wait(result["operation"]["id"], 3)["state"] == "succeeded"
    assert observations == [True, True]
    assert runtime.agent.invoke_round == 1


def test_completed_stages_and_mixed_invalid_flag_updates_are_rejected(runtime):
    """Validate every requested target before writing any flag in a batch update."""
    control, manager = runtime.control, runtime.manager
    revision = control.stage_state()["control_revision"]
    with pytest.raises(ControlError):
        control.update_stage_flags([1, 0], revision, skip=True)
    assert not manager.stages[1].is_skipped()
    control.review_stage(0, control.stage_state()["control_revision"], True)
    manager.set_current_stage_journal("Complete evidence")
    assert manager.complete(1)["complete"] is True
    with pytest.raises(ControlError):
        control.update_stage_flags([2, 0], control.stage_state()["control_revision"], hmcheck_needed=True)
    assert not manager.stages[2].is_hmcheck_needed()
    manager.go_to_stage(0)
    with pytest.raises(ControlError):
        control.review_stage(0, control.stage_state()["control_revision"], False)
    assert manager.stages[0].get_hmcheck_state()[0] is True
    for action in (lambda: manager.stages[0].do_hmcheck_fail("Late review"),
                   lambda: manager.stages[0].do_set_hmcheck_needed(False),
                   lambda: manager.skip_stage(0)):
        with pytest.raises(ControlError):
            action()


def test_stage_commands_have_real_handlers_and_nullable_llm_flags(runtime):
    """Command dispatch supports reads, review, flags, skip/unskip and inheritance reset."""
    registry = create_registry(runtime.control, executors={"stages": runtime.owner.stages})
    session = runtime.session
    assert registry.execute("hmcheck_cstat", session).data["stages"][0]["index"] == 0
    assert len(registry.execute("hmcheck_list", session).data["stages"]) == 1
    registry.execute("hmcheck_set all true", session)
    assert all(stage.is_hmcheck_needed() for stage in runtime.manager.stages)
    registry.execute("lmcheck_pset 1 true", session)
    registry.execute("lmcheck_pset 1 None", session)
    assert runtime.manager.stages[1].need_pass_llm_suggestion is None
    before = runtime.control.stage_state()["control_revision"]
    registry.execute("lmcheck_pset 1", session)
    registry.execute("hmcheck_set 1", session)
    assert runtime.control.stage_state()["control_revision"] == before
    registry.execute("skip_stage 2", session)
    assert runtime.manager.stages[2].is_skipped()
    registry.execute("unskip_stage 2", session)
    assert not runtime.manager.stages[2].is_skipped()
    registry.execute('hmcheck_fail "Missing evidence"', session)
    assert runtime.manager.stages[0].get_hmcheck_state() == (False, "Missing evidence")
    registry.execute('hmcheck_pass "Reviewed"', session)
    assert runtime.manager.stages[0].get_hmcheck_state() == (True, "Reviewed")


def test_flags_review_and_revision_survive_real_checkpoint_restore(runtime):
    """Restart keeps review evidence and overrides while invalidating earlier requests."""
    control = runtime.control
    control.update_stage_flags([1], control.stage_state()["control_revision"],
                               hmcheck_needed=True, skip=True, llm_fail_suggestion=False,
                               llm_pass_suggestion=True)
    review = control.review_stage(0, control.stage_state()["control_revision"], False, "Needs evidence")
    saved = load_ucagent_info(runtime.agent.workspace)
    assert saved["control_revision"] == review["control_revision"]
    assert runtime.owner.close(1)["closed"]
    restored = build_runtime(Path(runtime.agent.workspace), saved=saved)
    try:
        state = restored.control.stage_state()
        assert state["control_revision"] > review["control_revision"]
        assert state["stages"][0]["human_review"] == {"approved": False, "message": "Needs evidence"}
        assert state["stages"][1]["needs_human_check"] is True
        assert state["stages"][1]["is_skipped"] is True
        assert state["stages"][1]["need_fail_llm_suggestion"] is False
        assert state["stages"][1]["need_pass_llm_suggestion"] is True
        with pytest.raises(ControlError):
            restored.control.review_stage(0, review["control_revision"], True)
    finally:
        assert restored.owner.close(2)["closed"]


def test_real_batch_progress_does_not_complete_stage_early(tmp_path):
    """The existing BatchTask advances batches while Complete retains every gate."""
    runtime = build_runtime(tmp_path, batch=True)
    try:
        control, manager = runtime.control, runtime.manager
        control.review_stage(0, control.stage_state()["control_revision"], True)
        manager.set_current_stage_journal("Batch evidence")
        first = manager.complete(1)
        assert first["complete"] is False and "progress_summary" in first
        assert runtime.gate.batch.tbd_task_list == ["b"]
        assert not manager.stages[0].is_completed() and manager.stage_index == 0
        runtime.gate.generated = ["a", "b"]
        assert manager.complete(1)["complete"] is True
        assert manager.stage_index == 1
    finally:
        assert runtime.owner.close(3)["closed"]


def test_control_revision_tracks_direct_stage_edits_and_checker_attributes(runtime):
    """Direct migrated setters cannot escape revision tracking or conflict admission."""
    control, manager = runtime.control, runtime.manager
    before = control.stage_state()["control_revision"]
    manager.stages[1].do_set_hmcheck_needed(True)
    changed = control.stage_state()["control_revision"]
    assert changed > before
    control.checker_attr(0, "passed", False)
    assert control.stage_state()["control_revision"] > changed
    assert runtime.gate.passed is False


def test_close_reports_standalone_mcp_mutation_until_actual_completion(runtime):
    """A tool request without a model record still belongs to coordinated shutdown."""
    runtime.gate.entered, runtime.gate.release = threading.Event(), threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        checking = pool.submit(runtime.manager.check, 1)
        try:
            assert runtime.gate.entered.wait(2)
            assert runtime.owner.close(0) == {
                "closed": False, "pending": [], "pending_stage_mutation": "validation"}
        finally:
            runtime.gate.release.set()
        assert checking.result(timeout=3)["check_pass"] is True
    assert runtime.owner.close(1) == {"closed": True, "pending": []}
    with pytest.raises(ControlError) as caught:
        runtime.manager.check(1)
    assert caught.value.code == "closing"
