"""Permanent backend rejections stop the owned retry loop."""

from types import SimpleNamespace

import pytest

from ucagent import VerifyAgent
from ucagent.core.backends.base import NonRetryableBackendError
from ucagent.core.backends.langchain.agent import UCAgentLangChainBackend
from ucagent.runtime.operations import OperationContext, OperationExecutor, OperationRecord, RetryPolicy


class _HTTPError(RuntimeError):
    """Represent a provider rejection without making a network request."""

    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}: rejected request")
        self.status_code = status_code


@pytest.mark.parametrize("status,retry", [
    (400, False), (401, False), (403, False), (404, False), (413, False),
    (422, False), (408, True), (409, True), (429, True),
    (500, True), (502, True), (503, True), (None, True),
])
def test_langchain_backend_classifies_permanent_and_transient_errors(status, retry):
    error = RuntimeError("request failed") if status is None else _HTTPError(status)
    backend = UCAgentLangChainBackend.__new__(UCAgentLangChainBackend)
    assert backend.should_retry_loop_error(error) is retry
    if status == 400:
        assert backend.should_retry_loop_error(error, recovered_tool_calls=1) is True


def test_agent_converts_unrepaired_permanent_provider_error():
    agent = VerifyAgent.__new__(VerifyAgent)
    agent._is_work_busy = False
    agent._tool__call_error = []
    agent.stream_output = False
    agent.do_work_values = lambda *_args: (_ for _ in ()).throw(_HTTPError(400))
    backend = UCAgentLangChainBackend.__new__(UCAgentLangChainBackend)
    backend.recover_pending_tool_calls = lambda _error: 0
    agent.backend = backend

    with pytest.raises(NonRetryableBackendError, match="Correct the rejected backend request"):
        agent.do_work({}, {})
    assert agent.is_work_busy() is False


def _loop_executor(one_loop, attempts=3):
    agent = SimpleNamespace(
        cfg=SimpleNamespace(as_dict=lambda: {}), stage_manager=SimpleNamespace(validation_revision=0, stage_index=0),
        invoke_round=0, _need_human=False, _operation_owner=None,
        is_exit=lambda: False, is_break=lambda: False,
        set_continue_msg=lambda _message: None, one_loop=one_loop,
        _update_stalled_rounds=lambda *_args: None,
    )
    controller = SimpleNamespace(agent=agent, operations=None)
    executor = OperationExecutor(controller, retry_policy=RetryPolicy(attempts, 0, 0, 0))
    record = OperationRecord("retry-test", "loop", True)
    return executor, OperationContext(executor, record)


def test_operation_loop_does_not_retry_nonretryable_backend_error():
    calls = []

    def reject():
        calls.append(1)
        raise NonRetryableBackendError("bad request")

    executor, context = _loop_executor(reject)
    with pytest.raises(NonRetryableBackendError, match="bad request"):
        executor._loop(context, "")
    assert calls == [1]
    assert context.record.attempts == 1


def test_operation_loop_keeps_bounded_retries_for_transient_errors():
    calls = []

    def fail_transiently():
        calls.append(1)
        raise RuntimeError("temporary provider failure")

    executor, context = _loop_executor(fail_transiently, attempts=3)
    with pytest.raises(RuntimeError, match="temporary provider failure"):
        executor._loop(context, "")
    assert len(calls) == 3
    assert context.record.attempts == 3
