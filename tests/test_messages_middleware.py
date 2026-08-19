from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from ucagent.abackend.langchain.middleware.messages import (
    MessageStatistic,
    TrimAndSummaryMiddleware,
)


def test_reset_chat_keeps_human_as_first_non_system_message():
    middleware = TrimAndSummaryMiddleware(
        msg_stat=MessageStatistic(),
        max_summary_tokens=128,
        max_keep_msgs=20,
        max_tokens=4096,
        tail_keep_msgs=4,
        model=None,
    )
    messages = [
        SystemMessage(content="system"),
        HumanMessage(content="stage task"),
        AIMessage(
            content="",
            tool_calls=[{"name": "Check", "args": {}, "id": "call-1", "type": "tool_call"}],
        ),
        ToolMessage(content="passed", tool_call_id="call-1"),
        AIMessage(content="done"),
    ]

    result = middleware.reset_chat().before_model({"messages": messages})
    rebuilt = result["messages"][1:]

    assert isinstance(rebuilt[0], SystemMessage)
    assert isinstance(rebuilt[1], HumanMessage)


def test_force_reset_keeps_only_latest_human_after_system():
    middleware = TrimAndSummaryMiddleware(
        msg_stat=MessageStatistic(),
        max_summary_tokens=128,
        max_keep_msgs=20,
        max_tokens=4096,
        tail_keep_msgs=4,
        model=None,
    )
    messages = [
        SystemMessage(content="system"),
        HumanMessage(content="old stage"),
        AIMessage(content="old answer"),
        HumanMessage(content="new stage"),
        AIMessage(content="new answer"),
    ]

    result = middleware.reset_chat(force=True).before_model({"messages": messages})
    rebuilt = result["messages"][1:]

    assert [message.type for message in rebuilt] == ["system", "human"]
    assert rebuilt[1].content == "new stage"
