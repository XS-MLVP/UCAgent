"""Ensure rejected model requests stop loop retries while recoverable failures can resume."""

from types import SimpleNamespace

import pytest

from ucagent.abackend.langchain.agent import UCAgentLangChainBackend
from ucagent.abackend.base import AgentBackendBase, NonRetryableBackendError
from ucagent.verify_agent import VerifyAgent
from ucagent.verify_pdb import VerifyPDB


class _HTTPError(RuntimeError):
    """Represent a provider rejection without making a network request."""

    def __init__(self, status_code: int) -> None:
        """Attach the numeric HTTP status exposed by provider SDK exceptions."""
        super().__init__(f"HTTP {status_code}: rejected request")
        self.status_code = status_code


@pytest.fixture
def retry_probe(monkeypatch):
    """Run real work and loop error handling with in-memory requests and simulated waits."""
    agent = VerifyAgent.__new__(VerifyAgent)
    agent._exit_on_completion_pending = False
    agent.stream_output = False
    agent.invoke_round = 0
    agent._need_break = False
    agent.set_break = lambda value: setattr(agent, "_need_break", value)
    agent.is_break = lambda: agent._need_break
    agent.set_force_trace = lambda value: None
    backend = UCAgentLangChainBackend.__new__(UCAgentLangChainBackend)
    backend.recover_pending_tool_calls = lambda error: 0
    agent.backend = backend
    controller = VerifyPDB.__new__(VerifyPDB)
    controller.agent = agent
    controller.max_loop_retry = 10
    controller.retry_delay_start = 0
    controller.retry_delay_end = 0
    controller.loop_alive_time = 30
    waits, messages = [], []
    controller._interruptible_sleep = lambda seconds: waits.append(seconds) or True
    for name in ("echo_y", "echo_r", "echo_g"):
        monkeypatch.setattr(f"ucagent.verify_pdb.{name}", messages.append)
    agent.run_loop = lambda message: agent.do_work({}, {})
    return SimpleNamespace(agent=agent, backend=backend, controller=controller, waits=waits, messages=messages)


def test_unchanged_bad_request_stops_after_first_attempt(retry_probe) -> None:
    """An unrepaired HTTP 400 must not resend the same rejected request ten times."""
    calls = []

    def rejected_request(*args):
        """Count repeated submissions of an unchanged invalid request."""
        calls.append(400)
        raise _HTTPError(400)

    retry_probe.agent.do_work_values = rejected_request
    retry_probe.controller.do_loop("")
    assert calls == [400]
    assert retry_probe.waits == []
    assert retry_probe.agent.is_work_busy() is False


@pytest.mark.parametrize("status", [400, 401, 403, 404, 405, 410, 413, 415, 422, 499])
def test_permanent_http_failures_do_not_consume_retry_waits(retry_probe, status: int) -> None:
    """Reject permanent HTTP errors before the loop schedules any backoff."""
    calls = []
    retry_probe.controller.retry_delay_start = 5
    retry_probe.controller.retry_delay_end = 5

    def rejected_request(*args):
        """Raise one provider rejection per attempted work call."""
        calls.append(status)
        raise _HTTPError(status)

    retry_probe.agent.do_work_values = rejected_request
    retry_probe.controller.do_loop("")
    assert calls == [status] and retry_probe.waits == []
    assert any("retries stopped" in message for message in retry_probe.messages)


@pytest.mark.parametrize("status", [408, 409, 429, 500, 502, 503, 599, None])
def test_transient_and_unknown_failures_keep_bounded_retries(retry_probe, status) -> None:
    """Temporary and unknown failures retain the existing loop budget and delays."""
    calls = []
    retry_probe.controller.max_loop_retry = 3
    retry_probe.controller.retry_delay_start = 1
    retry_probe.controller.retry_delay_end = 1

    def failed_request(*args):
        """Raise a transient provider error or an unclassified local error."""
        calls.append(status)
        if status is None:
            raise RuntimeError("unknown failure")
        raise _HTTPError(status)

    retry_probe.agent.do_work_values = failed_request
    retry_probe.controller.do_loop("")
    assert calls == [status] * 3
    assert retry_probe.waits == [1] * 3
    assert any("Max loop retry" in message for message in retry_probe.messages)


@pytest.mark.parametrize("streaming", [True, False])
def test_transient_failure_can_recover_on_next_attempt(retry_probe, streaming: bool) -> None:
    """Both streaming modes can resume normally after a temporary provider failure."""
    calls = []
    retry_probe.agent.stream_output = streaming

    def temporary_failure(*args):
        """Fail once then finish successfully."""
        calls.append(1)
        if len(calls) == 1:
            raise _HTTPError(503)

    retry_probe.agent.do_work_stream = temporary_failure
    retry_probe.agent.do_work_values = temporary_failure
    retry_probe.controller.do_loop("")
    assert len(calls) == 2
    assert retry_probe.agent.is_work_busy() is False


def test_repaired_tool_sequence_can_retry_then_stops_if_still_rejected(retry_probe) -> None:
    """Allow HTTP 400 after real recovery progress, then stop when no further progress occurs."""
    calls, recoveries = [], []

    def recover_once(error):
        """Report a checkpoint repair only on the first failure."""
        recoveries.append(error)
        return 1 if len(recoveries) == 1 else 0

    def rejected_request(*args):
        """Keep rejecting to detect a retry loop after the one permitted repair."""
        calls.append(400)
        raise _HTTPError(400)

    retry_probe.backend.recover_pending_tool_calls = recover_once
    retry_probe.agent.do_work_values = rejected_request
    retry_probe.controller.do_loop("")
    assert calls == [400, 400] and len(recoveries) == 2


@pytest.mark.parametrize("status", [401, 403, 404, 422])
def test_other_request_rejections_stop_after_recovery_progress_ends(retry_probe, status: int) -> None:
    """Allow recorded tool failures to reach the model, then stop unchanged provider errors."""
    calls = []
    retry_probe.backend.recover_pending_tool_calls = lambda error: int(len(calls) == 1)

    def rejected_request(*args):
        """Reject regardless of the repaired conversation state."""
        calls.append(status)
        raise _HTTPError(status)

    retry_probe.agent.do_work_values = rejected_request
    retry_probe.controller.do_loop("")
    assert calls == [status, status]


def test_fatal_work_error_preserves_cause_and_busy_cleanup(retry_probe) -> None:
    """Keep the original provider diagnosis while unwinding normal agent work state."""
    original = _HTTPError(400)

    def rejected_request(*args):
        """Raise the exact instance used to verify exception chaining."""
        raise original

    retry_probe.agent.do_work_values = rejected_request
    with pytest.raises(NonRetryableBackendError) as captured:
        retry_probe.agent.do_work({}, {})
    assert captured.value.__cause__ is original
    assert "resume with loop" in str(captured.value)
    assert retry_probe.agent.is_work_busy() is False


@pytest.mark.parametrize("link", ["cause", "context", "response", "suppressed", "cycle", "outer_transient"])
def test_status_classification_handles_wrapped_errors(retry_probe, link: str) -> None:
    """Follow visible exception chains safely and honor an outer HTTP status when available."""
    inner = _HTTPError(400)
    outer = RuntimeError("wrapped failure")
    if link == "cause":
        outer.__cause__ = inner
    elif link == "context":
        outer.__context__ = inner
    elif link == "response":
        outer.response = SimpleNamespace(status_code=400)
    elif link == "suppressed":
        outer.__context__ = inner
        outer.__suppress_context__ = True
    elif link == "cycle":
        outer.__cause__ = outer
    else:
        outer = _HTTPError(503)
        outer.__cause__ = inner
    assert retry_probe.backend.should_retry_loop_error(outer) is (link in {"suppressed", "cycle", "outer_transient"})


def test_real_provider_sdk_and_httpx_errors_are_classified(retry_probe) -> None:
    """Recognize actual SDK status attributes and response-only HTTPX failures offline."""
    import httpx
    from openai import BadRequestError

    response = httpx.Response(400, request=httpx.Request("POST", "https://example.test/v1/responses"))
    sdk_error = BadRequestError("missing tool result", response=response, body={"error": "invalid request"})
    http_error = httpx.HTTPStatusError("invalid request", request=response.request, response=response)
    assert not retry_probe.backend.should_retry_loop_error(sdk_error)
    assert not retry_probe.backend.should_retry_loop_error(http_error)
    assert retry_probe.backend.should_retry_loop_error(sdk_error, recovered_tool_calls=1)


def test_base_backend_preserves_existing_retry_policy() -> None:
    """Other backend implementations keep bounded retries until they define a stricter policy."""
    backend = AgentBackendBase(None, None)
    assert backend.should_retry_loop_error(_HTTPError(400))


def test_failed_recovery_does_not_retry_rejected_request(retry_probe) -> None:
    """A failed checkpoint repair provides no progress that could justify another HTTP 400."""
    calls = []

    def failed_recovery(error):
        """Fail before recording any replacement tool result."""
        raise RuntimeError("checkpoint update failed")

    def rejected_request(*args):
        """Count invalid work calls while recovery itself fails."""
        calls.append(400)
        raise _HTTPError(400)

    retry_probe.backend.recover_pending_tool_calls = failed_recovery
    retry_probe.agent.do_work_values = rejected_request
    retry_probe.controller.do_loop("")
    assert calls == [400]


@pytest.mark.parametrize("status", [400, 401])
def test_http_error_can_resume_after_real_tool_result_recovery(retry_probe, status: int) -> None:
    """Repair only missing tool results, preserve valid history, and retry the changed request."""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from test_langchain_tool_recovery import _backend_with_messages

    valid_result = ToolMessage(content="real result", name="ReadTextFile", tool_call_id="done")
    messages = [HumanMessage(content="inspect input"), AIMessage(content="", tool_calls=[
        {"name": "ReadTextFile", "args": {}, "id": "done", "type": "tool_call"},
        {"name": "ReadTextFile", "args": {}, "id": "missing", "type": "tool_call"},
    ]), valid_result]
    backend = _backend_with_messages(messages)
    retry_probe.agent.backend = backend
    calls = []

    def request_with_tool_history(*args):
        """Reject the malformed sequence, then accept the explicitly recorded failure result."""
        calls.append(1)
        if backend._pending_tool_calls(backend.messages_get_raw()):
            raise _HTTPError(status)

    retry_probe.agent.do_work_values = request_with_tool_history
    retry_probe.controller.do_loop("")
    assert len(calls) == 2 and len(backend.agent.updates) == 1
    assert len(messages) == 4 and messages[2] is valid_result
    assert isinstance(messages[0], HumanMessage) and len(messages[1].tool_calls) == 2
    assert messages[-1].tool_call_id == "missing" and messages[-1].status == "error"
    assert backend._pending_tool_calls(messages) == {}
