"""Exercise the failed-tool guard inside a real LangGraph loop."""
from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool, InjectedToolCallId
from typing import Annotated
from ucagent.abackend.langchain.middleware.tool_errors import ToolErrorGuard


class RepeatingModel(BaseChatModel):
    """Always request the failing tool, exposing unbounded graph loops."""
    calls: int = 0

    @property
    def _llm_type(self):
        """Identify this deterministic test model."""
        return 'repeating-test'

    def bind_tools(self, tools, **kwargs):
        """Return the tool-aware test model unchanged."""
        return self

    def _generate(self, messages, **kwargs):
        """Emit one invocation and fail if the guard does not terminate it."""
        self.calls += 1
        assert self.calls <= 3
        msg = AIMessage(content='', tool_calls=[{'name':'broken','args':{},'id':str(self.calls),'type':'tool_call'}])
        return ChatResult(generations=[ChatGeneration(message=msg)])


@tool
def broken(tool_call_id: Annotated[str, InjectedToolCallId]) -> str:
    """Return a tool validation failure through its normal status channel."""
    return ToolMessage(content='missing required path', tool_call_id=tool_call_id, status='error')


def test_real_graph_stops_before_fourth_failed_tool_round():
    """An inner graph cannot bypass the outer loop's retry limit."""
    paused = []
    model = RepeatingModel()
    graph = create_agent(model, tools=[broken], middleware=[ToolErrorGuard(on_pause=lambda: paused.append(True))])
    result = graph.invoke({'messages':[HumanMessage(content='work')]})
    assert model.calls == 3
    assert paused == [True]
    assert isinstance(result['messages'][-1], ToolMessage)


def test_success_and_disabled_guard_do_not_pause():
    """Successful tool work resets consecutive failures; zero disables the guard."""
    messages = []
    for i in range(3):
        messages.extend([AIMessage(content='',tool_calls=[{'name':'x','args':{},'id':str(i),'type':'tool_call'}]),
                         ToolMessage(content='result',tool_call_id=str(i),status='success' if i==1 else 'error')])
    assert ToolErrorGuard().before_model({'messages':messages}) is None
    assert ToolErrorGuard(max_rounds=0).before_model({'messages':messages}) is None
