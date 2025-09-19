# --- coding: utf-8 ---
"""Message and state utilities for UCAgent."""

from vagent.util.functions import fill_dlist_none

from langchain_core.messages.utils import count_tokens_approximately, trim_messages
from langchain_core.messages import AIMessage, RemoveMessage
from langmem.short_term import SummarizationNode
from langgraph.prebuilt.chat_agent_executor import AgentState
from typing import Any, Dict, Union
from pydantic import BaseModel



def fix_tool_call_args(input: Union[Dict[str, Any], BaseModel]) -> Dict[str, Any]:
        for msg in input["messages"][-4:]:
            if not isinstance(msg, AIMessage):
                continue
            if hasattr(msg, "additional_kwargs"):
                msg.additional_kwargs = fill_dlist_none(msg.additional_kwargs, '{}', "arguments", ["arguments"])
            if hasattr(msg, "invalid_tool_calls"):
                msg.invalid_tool_calls = fill_dlist_none(msg.invalid_tool_calls, '{}', "args", ["args"])


def remove_messages(messages, max_keep_msgs):
    """Remove older messages to keep the most recent max_keep_msgs messages."""
    if len(messages) <= max_keep_msgs:
        return messages, []
    index = (-max_keep_msgs) % len(messages)
    return messages[index:], [RemoveMessage(id=msg.id) for msg in messages[:index]]


class SummarizationAndFixToolCall(SummarizationNode):
    """Custom summarization node that fixes tool call arguments."""

    def set_max_keep_msgs(self, max_keep_msgs: int):
        self.max_keep_msgs = max_keep_msgs
        return self

    def _func(self, input: Union[Dict[str, Any], BaseModel]) -> Dict[str, Any]:
        fix_tool_call_args(input)
        deleted_msg = []
        if hasattr(self, "max_keep_msgs"):
            messages, deleted_msg = remove_messages(input["messages"], self.max_keep_msgs)
            input["messages"] = messages
        ret = super()._func(input)
        if deleted_msg:
            ret["messages"] = deleted_msg
        return ret


class TrimMessagesNode:
    """Node to trim messages to a maximum count."""

    def __init__(self, max_token: int, max_keep_msgs: int):
        self.max_token = max_token
        self.max_keep_msgs = max_keep_msgs

    def __call__(self, state):
        fix_tool_call_args(state)
        messages, deleted_msg = remove_messages(state["messages"], self.max_keep_msgs)
        msg = trim_messages(
                messages,
                strategy="last",
                token_counter=count_tokens_approximately,
                max_tokens=self.max_token,
                start_on="human",
                end_on=("human", "tool"),
                include_system=True,
                allow_partial=False,
        )
        ret = {"llm_input_messages": msg}
        if deleted_msg:
            ret["messages"] = deleted_msg
        return ret


class State(AgentState):
    """Agent state with additional context information."""
    # NOTE: we're adding this key to keep track of previous summary information
    # to make sure we're not summarizing on every LLM call
    context: Dict[str, Any]
