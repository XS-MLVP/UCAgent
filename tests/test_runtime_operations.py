"""Operation ownership and cancellation tests without models or runtime startup."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ucagent.runtime.control.commands import CommandSession, create_registry
from ucagent.runtime.control.controller import Controller, ControlError
from ucagent.runtime.operations import OperationExecutor, OperationFailure, RetryPolicy, TERMINAL_STATES
from ucagent.util.config import Config
from ucagent.util.functions import PROCESS_CANCELLATION


class Agent:
    """A controllable model boundary preserving the agent's progress contract."""

    def __init__(self, workspace):
        """Initialize state only, without model, services or debugger construction."""
        self.workspace = str(workspace)
        self.cfg = Config({"cmd_timeout": 2, "loop_settings": {
            "max_loop_retry": 2, "retry_delay_start": 0, "retry_delay_end": 0, "loop_alive_time": 10},
            "vibe_coding": {"short_prompts": {"inspect": "Inspect evidence"}}})
        self.stage_manager = SimpleNamespace(stage_index=0, validation_revision=0)
        self.invoke_round = 0
        self.round_messages = []
        self.chat_messages = []
        self.continue_messages = []
        self.stall_updates = []
        self._break = False
        self._need_human = False
        self.exited = False
        self.round_hook = None

    def set_break(self, value):
        """Expose cooperative pause state to the executor and backend."""
        self._break = value

    def is_break(self):
        """Read cooperative pause state."""
        return self._break

    def is_exit(self):
        """Read the domain's completion signal."""
        return self.exited

    def set_continue_msg(self, message):
        """Track whether retries accidentally enqueue the same message again."""
        self.continue_messages.append(message)

    def one_loop(self, message=None):
        """Run an injected action; only completed rounds advance progress."""
        self.round_messages.append(message)
        if self.round_hook is not None:
            self.round_hook(self)
        self.invoke_round += 1

    def custom_chat(self, message):
        """Record a custom-chat call separately from verification rounds."""
        self.chat_messages.append(message)

    def _update_stalled_rounds(self, revision, index):
        """Record delivery of the stage snapshot to the domain progress detector."""
        self.stall_updates.append((revision, index))

    def status_info(self):
        """Allow read-only queries while the model is blocked."""
        return {"invoke_round": self.invoke_round}


@pytest.fixture
def runtime(tmp_path):
    """Own one executor and ensure every test leaves its workers finished."""
    control = Controller(Agent(tmp_path))
    owner = OperationExecutor(control)
    yield control, owner, CommandSession(tmp_path)
    assert owner.close(3)["closed"], "Test left an operation running"


def test_single_round_chat_and_short_prompt_use_their_exact_domain_calls(runtime):
    """One-round commands never accidentally enter the conversation loop."""
    control, owner, session = runtime
    registry = create_registry(control, executors={"operations": owner})
    for command in ('nr', 'nrm "with a message"', 'short_prompt inspect "extra detail"', 'chat "hello"'):
        accepted = registry.execute(command, session).data
        assert owner.wait(accepted["id"], 2)["state"] == "succeeded"
    assert control.agent.round_messages == [None, "with a message"]
    assert control.agent.invoke_round == 2
    assert control.agent.chat_messages == ["Inspect evidence\nextra detail", "hello"]
    assert control.agent.stall_updates == []
    assert PROCESS_CANCELLATION.get() is None


def test_cancellation_keeps_busy_until_uncancellable_model_returns(runtime):
    """Cancellation is an observable request, not a fabricated completed call."""
    control, owner, session = runtime
    entered, release = threading.Event(), threading.Event()

    def blocking(agent):
        """Simulate a model transport without a cancellation API."""
        entered.set()
        assert release.wait(3)

    control.agent.round_hook = blocking
    accepted = owner.execute("next_round", {}, session)
    try:
        assert entered.wait(2)
        assert control.status() == {"invoke_round": 0}
        assert control.cancel_operation(accepted["id"])["state"] == "cancelling"
        assert owner.cancel(accepted["id"])["state"] == "cancelling"
        assert owner.wait(accepted["id"], 0)["finished_at"] is None
        for command in ("next_round", "chat", "messages_summary", "tool_invoke"):
            with pytest.raises(ControlError) as caught:
                owner.execute(command, {"message": "hello", "name": "Tool"}, session)
            assert caught.value.code == "busy"
        with pytest.raises(ControlError, match="Cancellation"):
            owner.execute("agent_unbreak", {}, session)
        pending = owner.close(0)
        assert pending == {"closed": False, "pending": [accepted["id"]]}
    finally:
        release.set()
    result = owner.wait(accepted["id"], 2)
    assert result["state"] == "cancelled" and result["finished_at"] is not None
    assert control.agent.invoke_round == 1
    assert owner.cancel(accepted["id"]) == result
    assert owner.close(1) == {"closed": True, "pending": []}
    with pytest.raises(ControlError) as closing:
        owner.execute("next_round", {}, session)
    assert closing.value.code == "closing"


def test_simultaneous_model_admission_accepts_only_one(runtime):
    """Concurrent callers contend atomically; querying never takes the model slot."""
    control, owner, session = runtime
    start = threading.Barrier(3)
    entered, release = threading.Event(), threading.Event()
    results, errors = [], []

    def block(agent):
        """Keep the winning model call alive until both requests are observed."""
        entered.set()
        assert release.wait(3)

    def request():
        """Submit from an independent frontend at the same barrier."""
        start.wait(timeout=2)
        try:
            results.append(owner.execute("next_round", {}, session))
        except ControlError as error:
            errors.append(error)

    control.agent.round_hook = block
    threads = [threading.Thread(target=request) for _ in range(2)]
    for thread in threads:
        thread.start()
    try:
        start.wait(timeout=2)
        assert entered.wait(2)
        for thread in threads:
            thread.join(2)
            assert not thread.is_alive()
        assert len(results) == 1 and len(errors) == 1 and errors[0].code == "busy"
        assert control.operation_status(results[0]["id"])["state"] == "running"
        assert len(control.operation_list()) == 1
    finally:
        release.set()
    assert owner.wait(results[0]["id"], 2)["state"] == "succeeded"


def test_failure_releases_slot_and_result_snapshots_are_independent(runtime):
    """Failures remain inspectable and do not poison subsequent admission."""
    control, owner, session = runtime
    control.agent.round_hook = Mock(side_effect=RuntimeError("model unavailable"))
    failed = owner.wait(owner.execute("next_round", {}, session)["id"], 2)
    assert failed["state"] == "failed" and failed["error"]["message"] == "model unavailable"
    failed["error"]["message"] = "client mutation"
    assert owner.get(failed["id"])["error"]["message"] == "model unavailable"
    control.agent.round_hook = None
    succeeded = owner.wait(owner.execute("next_round", {}, session)["id"], 2)
    assert succeeded["state"] == "succeeded"
    assert owner.cancel(succeeded["id"]) == succeeded


def test_pause_and_resume_only_start_work_when_explicitly_requested(runtime):
    """Pause waits for a safe boundary; unbreak does not create another worker."""
    control, owner, session = runtime
    entered, release = threading.Event(), threading.Event()

    def block(agent):
        """Expose the model boundary at which pause may be requested."""
        entered.set()
        assert release.wait(3)

    control.agent.round_hook = block
    operation = owner.execute("loop", {"message": ""}, session)
    try:
        assert entered.wait(2)
        assert owner.execute("agent_break", {}, session) == {"is_break": True}
        assert owner.get(operation["id"])["state"] == "running"
    finally:
        release.set()
    assert owner.wait(operation["id"], 2)["result"]["reason"] == "paused"
    assert owner.execute("agent_unbreak", {}, session) == {"is_break": False}
    assert len(owner.list()) == 1
    control.agent.round_hook = None
    owner.wait(owner.execute("next_round", {}, session)["id"], 2)
    assert control.agent.invoke_round == 2


def test_loop_preserves_stall_detection_and_human_wait_reason(runtime):
    """A human gate stops scheduling without setting mission completion."""
    control, owner, session = runtime

    def require_human(agent):
        """Model a domain gate reporting that human review is needed."""
        agent._need_human = True

    control.agent.round_hook = require_human
    result = owner.wait(owner.execute("continue_with_message", {"message": "review"}, session)["id"], 2)
    assert result["state"] == "succeeded"
    assert result["result"] == {"reason": "waiting_human", "invoke_round": 1}
    assert control.agent.stall_updates == [(0, 0)]
    assert control.agent.continue_messages == ["review"]
    assert control.agent.exited is False


@pytest.mark.parametrize("completed_round", [False, True])
def test_retry_budget_resets_only_with_sustained_completed_work(runtime, completed_round):
    """Elapsed time alone cannot refresh retries; completed rounds can."""
    control, owner, session = runtime
    now = [0.0]
    owner._clock = lambda: now[0]
    steps = []

    def attempt(agent):
        """Script one completed round between failures only in the progress case."""
        steps.append(len(steps))
        now[0] += 20
        if completed_round and len(steps) == 2:
            return
        raise RuntimeError("retry failure")

    control.agent.round_hook = attempt
    result = owner.wait(owner.execute("loop", {"message": "once"}, session)["id"], 2)
    assert result["state"] == "failed"
    assert result["attempts"] == (4 if completed_round else 2)
    assert len(steps) == (5 if completed_round else 2)
    assert control.agent.continue_messages == ["once"]


def test_completed_work_below_alive_threshold_does_not_reset_budget(runtime):
    """A completed round alone does not bypass the configured alive-time threshold."""
    control, owner, session = runtime
    owner._clock = lambda: 0
    calls = []

    def step(agent):
        """Complete one round, with no elapsed qualifying interval."""
        calls.append(1)
        if len(calls) != 2:
            raise RuntimeError("failure")

    control.agent.round_hook = step
    result = owner.wait(owner.execute("loop", {"message": ""}, session)["id"], 2)
    assert result["attempts"] == 2 and result["state"] == "failed"
    assert control.agent.invoke_round == 1


def test_cancel_during_retry_wait_stops_without_another_attempt(runtime):
    """A long retry delay must remain interruptible through its operation token."""
    control, owner, session = runtime
    owner.retry_policy = RetryPolicy(3, 60, 60, 120)
    failed = threading.Event()

    def reject(agent):
        """Signal the first failed attempt before the executor enters retry wait."""
        failed.set()
        raise RuntimeError("retry later")

    control.agent.round_hook = reject
    operation = owner.execute("loop", {"message": ""}, session)
    assert failed.wait(2)
    owner.cancel(operation["id"])
    result = owner.wait(operation["id"], 2)
    assert result["state"] == "cancelled" and result["attempts"] == 1
    assert len(control.agent.round_messages) == 1


def test_owner_isolation_sleep_and_cancellation_by_id(runtime, tmp_path):
    """Cancelling one operation neither cancels its neighbor nor another instance."""
    control, owner, session = runtime
    other = OperationExecutor(Controller(Agent(tmp_path)))
    try:
        first = control.start_operation("sleep", {"seconds": 60}, session)
        second = owner.execute("sleep", {"seconds": 60}, session)
        owner.cancel(first["id"])
        assert owner.wait(first["id"], 2)["state"] == "cancelled"
        assert owner.get(second["id"])["state"] not in TERMINAL_STATES
        with pytest.raises(ControlError) as caught:
            other.cancel(second["id"])
        assert caught.value.code == "unknown_operation"
        owner.cancel(second["id"])
        assert owner.wait(second["id"], 2)["state"] == "cancelled"
        done = other.execute("next_round", {}, CommandSession(tmp_path))
        assert other.wait(done["id"], 2)["state"] == "succeeded"
    finally:
        assert other.close(2)["closed"]


def test_thread_start_failure_is_recorded_without_leaking_reservation(runtime, monkeypatch):
    """Failure to start a worker is not accepted as running work."""
    _, owner, session = runtime
    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, "start", Mock(side_effect=RuntimeError("cannot start")))
        with pytest.raises(ControlError) as caught:
            owner.execute("next_round", {}, session)
    assert caught.value.code == "start_failed"
    assert owner.get(caught.value.details["operation_id"])["state"] == "failed"
    assert owner.wait(owner.execute("next_round", {}, session)["id"], 2)["state"] == "succeeded"


def test_long_business_commands_use_the_same_slot(runtime):
    """Tool invocation and message summary cannot bypass model ownership."""
    control, owner, session = runtime
    control.tool_invoke = Mock(return_value={"actual": "tool result"})
    control.messages_summary = Mock(return_value={"count": 1})
    registry = create_registry(control, executors={"operations": owner})
    for line, expected in [("tool_invoke Example", {"actual": "tool result"}),
                           ("messages_summary", {"count": 1})]:
        accepted = registry.execute(line, session).data
        result = owner.wait(accepted["id"], 2)
        assert result["model"] is True and result["result"] == expected
    control.tool_invoke.assert_called_once_with(name="Example", arguments=None)
    control.messages_summary.assert_called_once_with()


def test_settings_and_invalid_requests_do_not_start_workers(runtime):
    """Validate numeric configuration and missing capabilities before admission."""
    control, owner, session = runtime
    with pytest.raises(ControlError, match="already"):
        OperationExecutor(control)
    with pytest.raises(ControlError, match="already"):
        OperationExecutor(Controller(control.agent))
    for value in (-1, True, float("inf"), float("nan"), "bad"):
        with pytest.raises(ControlError):
            owner.execute("sleep", {"seconds": value}, session)
    for settings in ({"max_attempts": 0}, {"delay_min": -1}, {"delay_min": 3, "delay_max": 2}):
        with pytest.raises(ValueError):
            RetryPolicy(**settings)
    with pytest.raises(ControlError):
        owner.execute("short_prompt", {"name": "unknown"}, session)
    with pytest.raises(ControlError):
        owner.execute("chat", {"message": ""}, session)
    assert owner.list() == []


def test_completed_loop_reports_domain_completion_without_an_extra_round(runtime):
    """A domain exit signal finishes the loop after exactly the completing round."""
    control, owner, session = runtime

    def finish(agent):
        """Simulate successful domain completion during one round."""
        agent.exited = True

    control.agent.round_hook = finish
    result = owner.wait(owner.execute("continue", {}, session)["id"], 2)
    assert result["state"] == "succeeded"
    assert result["result"] == {"reason": "completed", "invoke_round": 1}
    assert len(control.agent.round_messages) == 1


def test_error_after_cancellation_is_retained_without_releasing_slot_early(runtime):
    """A transport error after cancellation remains available in the terminal record."""
    control, owner, session = runtime
    entered, release = threading.Event(), threading.Event()

    def fail_after_release(agent):
        """Keep the failing call alive until the cancellation request is observed."""
        entered.set()
        assert release.wait(3)
        raise RuntimeError("transport stopped")

    control.agent.round_hook = fail_after_release
    operation = owner.execute("next_round", {}, session)
    try:
        assert entered.wait(2)
        owner.cancel(operation["id"])
        assert owner.get(operation["id"])["finished_at"] is None
    finally:
        release.set()
    result = owner.wait(operation["id"], 2)
    assert result["state"] == "cancelled"
    assert result["error"]["message"] == "transport stopped"


@pytest.mark.parametrize("error", [
    ControlError("domain_failure", "Bad diagnostic", payload=object()),
    OperationFailure("domain_failure", "Bad result", object()),
    SystemExit("Worker exited"),
])
def test_worker_error_boundaries_always_record_failure_and_release_slot(runtime, error):
    """Unserializable diagnostics and worker exit cannot appear as successful work."""
    _, owner, session = runtime

    def fail(context):
        """Raise a domain boundary failure inside the actual operation worker."""
        raise error

    operation = owner.submit("failure_boundary", fail, model=True)
    result = owner.wait(operation["id"], 2)
    assert result["state"] == "failed"
    assert result["error"]["message"] == str(error)
    expected_code = "execution_failed" if isinstance(error, SystemExit) else "unsupported_result"
    assert result["error"]["code"] == expected_code
    assert owner.wait(owner.execute("next_round", {}, session)["id"], 2)["state"] == "succeeded"


@pytest.mark.parametrize("cancel", [False, True])
def test_pause_or_cancel_before_worker_start_is_not_lost(runtime, cancel):
    """Requests arriving after admission remain effective at the first safe boundary."""
    control, owner, session = runtime
    # Hold the admission lock to control worker startup without scheduler sleeps.
    with owner._lock:
        operation = owner.execute("loop", {}, session)
        assert operation["state"] == "queued"
        if cancel:
            owner.cancel(operation["id"])
        else:
            owner.execute("agent_break", {}, session)
    result = owner.wait(operation["id"], 2)
    assert result["state"] == ("cancelled" if cancel else "succeeded")
    if not cancel:
        assert result["result"]["reason"] == "paused"
    assert control.agent.round_messages == []
    assert control.agent.is_break() is True
