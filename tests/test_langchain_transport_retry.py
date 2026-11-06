"""Transport retry is bounded to model calls, never tool execution or auth errors."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from ucagent.abackend.langchain.middleware.transport import TransportRetryMiddleware, call_with_transport_retry


def test_partial_response_is_discarded_and_completed_result_returned():
    """Only the complete response may flow into the graph's tool execution node."""
    attempts = []
    completed = SimpleNamespace(tool_calls=[{'name': 'write_once'}])
    def model():
        """Simulate incomplete chunks followed by one full response."""
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx.RemoteProtocolError('incomplete chunked read')
        return completed
    assert call_with_transport_retry(model, delay=0) is completed
    assert len(attempts) == 3


@pytest.mark.parametrize('error', [ValueError('invalid model'), httpx.HTTPStatusError(
    'unauthorized', request=httpx.Request('POST', 'http://test'), response=httpx.Response(401))])
def test_non_transport_errors_are_not_retried(error):
    """Configuration and authentication errors remain actionable failures."""
    attempts = []
    def model():
        """Raise a permanent request failure."""
        attempts.append(1);raise error
    with pytest.raises(type(error)):
        call_with_transport_retry(model, delay=0)
    assert len(attempts) == 1


def test_retry_limit_and_stop_are_respected():
    """An exhausted or stopped request fails without producing a fake success."""
    for stopped, count in [(False, 3), (True, 1)]:
        attempts = []
        def model():
            """Raise a repeated transport failure."""
            attempts.append(1);raise httpx.ReadTimeout('read')
        with pytest.raises(httpx.ReadTimeout):
            call_with_transport_retry(model, cancelled=lambda: stopped, delay=0)
        assert len(attempts) == count


def test_async_retry_uses_same_boundary():
    """Async retry also returns a complete model response after a transport error."""
    calls = []
    async def handler(request):
        """Fail once before a completed response."""
        calls.append(request)
        if len(calls) == 1: raise httpx.RemoteProtocolError('cut')
        return 'complete'
    result = asyncio.run(TransportRetryMiddleware(delay=0).awrap_model_call('request', handler))
    assert result == 'complete' and len(calls) == 2


def test_real_graph_does_not_execute_partial_or_duplicate_tool_calls():
    """A cut streamed tool call is discarded before the real LangGraph tool node."""
    from langchain.agents import create_agent
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessageChunk, ToolMessage
    from langchain_core.outputs import ChatGenerationChunk
    from langchain_core.tools import tool

    executed = []
    @tool
    def write_once(value: int) -> str:
        """Record one completed tool execution."""
        executed.append(value)
        return 'saved'

    class CutModel(BaseChatModel):
        """Emit an incomplete first attempt followed by a valid tool call."""
        attempts: int = 0

        @property
        def _llm_type(self):
            """Identify the local deterministic test model."""
            return 'cut-model'

        def bind_tools(self, tools, **kwargs):
            """Accept the graph's tool binding without contacting any provider."""
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            """Require streaming so this test exercises the incomplete reply path."""
            raise AssertionError('streaming expected')

        def _stream(self, messages, stop=None, run_manager=None, **kwargs):
            """Fail after partial tool arguments, then provide one full invocation."""
            if any(isinstance(message, ToolMessage) for message in messages):
                yield ChatGenerationChunk(message=AIMessageChunk(content='done'))
                return
            self.attempts += 1
            arguments = '{"value":' if self.attempts == 1 else '{"value":7}'
            yield ChatGenerationChunk(message=AIMessageChunk(content='', tool_call_chunks=[
                {'name': 'write_once', 'args': arguments, 'id': 'call-1', 'index': 0}]))
            if self.attempts == 1:
                raise httpx.RemoteProtocolError('cut after partial tool arguments')

    model = CutModel()
    graph = create_agent(model, tools=[write_once], middleware=[TransportRetryMiddleware(delay=0)])
    values = [data for mode, data in graph.stream({'messages': [('user', 'write')]},
              stream_mode=['messages', 'values']) if mode == 'values']
    assert executed == [7] and model.attempts == 2
    assert values[-1]['messages'][-1].content == 'done'
