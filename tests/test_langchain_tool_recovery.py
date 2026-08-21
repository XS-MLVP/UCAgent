import os
import sys
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ucagent.abackend.langchain.agent import UCAgentLangChainBackend


class _InvalidOutputTool(BaseTool):
    name: str = "InvalidOutputTool"
    description: str = "Return an invalid raw tool output."

    def _run(self):
        return "unused"

    def invoke(self, input, config=None, **kwargs):
        return "invalid raw output"


class _GraphState:
    def __init__(self, messages):
        self.messages = messages
        self.updates = []

    def get_state(self, _config):
        return SimpleNamespace(values={"messages": self.messages})

    def update_state(self, config, values, as_node=None):
        self.updates.append((config, values, as_node))
        self.messages.extend(values["messages"])


def _backend_with_messages(messages):
    backend = UCAgentLangChainBackend.__new__(UCAgentLangChainBackend)
    backend.agent = _GraphState(messages)
    backend.get_work_config = lambda: {"configurable": {"thread_id": "test"}}
    return backend


def test_recover_pending_tool_calls_adds_only_missing_results():
    messages = [
        HumanMessage(content="update the file"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "ReadTextFile",
                    "args": {"path": "a.txt"},
                    "id": "read-call",
                    "type": "tool_call",
                },
                {
                    "name": "ReplaceStringInFile",
                    "args": {"path": "a.txt"},
                    "id": "replace-call",
                    "type": "tool_call",
                },
            ],
        ),
        ToolMessage(
            content="read complete",
            name="ReadTextFile",
            tool_call_id="read-call",
        ),
    ]
    backend = _backend_with_messages(messages)

    recovered = backend.recover_pending_tool_calls(
        TypeError("Tool ReplaceStringInFile returned unexpected type")
    )

    assert recovered == 1
    assert len(backend.agent.updates) == 1
    config, values, as_node = backend.agent.updates[0]
    assert config == {"configurable": {"thread_id": "test"}}
    assert as_node == "tools"
    assert len(values["messages"]) == 1
    result = values["messages"][0]
    assert isinstance(result, ToolMessage)
    assert result.tool_call_id == "replace-call"
    assert result.name == "ReplaceStringInFile"
    assert result.status == "error"
    assert "Review the arguments and retry" in result.content


def test_recover_pending_tool_calls_is_idempotent():
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "ReplaceStringInFile",
                    "args": {},
                    "id": "replace-call",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content="validation failed",
            name="ReplaceStringInFile",
            tool_call_id="replace-call",
            status="error",
        ),
    ]
    backend = _backend_with_messages(messages)

    assert backend.recover_pending_tool_calls(RuntimeError("ignored")) == 0
    assert backend.agent.updates == []


def test_recover_pending_tool_calls_repairs_langgraph_checkpoint():
    call = {
        "name": "InvalidOutputTool",
        "args": {},
        "id": "invalid-output-call",
        "type": "tool_call",
    }

    def model_node(_state):
        return {"messages": [AIMessage(content="", tool_calls=[call])]}

    builder = StateGraph(MessagesState)
    builder.add_node("model", model_node)
    builder.add_node("tools", ToolNode([_InvalidOutputTool()]))
    builder.add_edge(START, "model")
    builder.add_edge("model", "tools")
    builder.add_edge("tools", END)
    graph = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "recovery-test"}}

    try:
        graph.invoke({"messages": [HumanMessage(content="run")]}, config)
    except TypeError as error:
        tool_error = error
    else:
        raise AssertionError("The invalid tool output should fail before recovery")

    backend = UCAgentLangChainBackend.__new__(UCAgentLangChainBackend)
    backend.agent = graph
    backend.get_work_config = lambda: config

    assert backend.recover_pending_tool_calls(tool_error) == 1

    messages = graph.get_state(config).values["messages"]
    assert [type(message) for message in messages] == [
        HumanMessage,
        AIMessage,
        ToolMessage,
    ]
    assert messages[-1].tool_call_id == call["id"]
    assert messages[-1].status == "error"
    assert backend._pending_tool_calls(messages) == {}
