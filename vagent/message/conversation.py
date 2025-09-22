# --- coding: utf-8 ---
"""Message and state utilities for UCAgent."""

from vagent.util.functions import fill_dlist_none

from langchain_core.messages.utils import count_tokens_approximately, trim_messages
from langchain_core.messages import AIMessage, RemoveMessage
from langchain_core.callbacks import BaseCallbackHandler
from langmem.short_term import SummarizationNode
from langgraph.prebuilt.chat_agent_executor import AgentState
from typing import Any, Dict, Union
from pydantic import BaseModel
import time


class TokenSpeedCallbackHandler(BaseCallbackHandler):
    """Callback handler to monitor token generation speed."""

    def __init__(self):
        super().__init__()
        self.total_tokens_size = 0
        self.last_tokens_size = 0
        self.last_access_time = 0.0
        self.last_token_speed = 0.0

    def on_llm_new_token(self, token: str, **kwargs) -> None:
        self.total_tokens_size += len(token)
        message = kwargs["chunk"].message
        if message and hasattr(message, "tool_call_chunks"):
            for tool_call in message.tool_call_chunks:
                tool_name = tool_call["name"]
                args = tool_call["args"]
                if tool_name:
                    self.total_tokens_size += len(tool_name)
                if args:
                    self.total_tokens_size += len(args)

    def get_speed(self) -> float:
        if self.last_access_time == 0.0:
            self.last_access_time = time.time()
            self.last_tokens_size = self.total_tokens_size
            return 0.0
        now_time = time.time()
        delta_time = now_time - self.last_access_time
        if delta_time < 1.0:
            return self.last_token_speed
        delta_tokens = self.total_tokens_size - self.last_tokens_size
        self.last_access_time = now_time
        self.last_token_speed = delta_tokens / delta_time
        self.last_tokens_size = self.total_tokens_size
        return self.last_token_speed

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
