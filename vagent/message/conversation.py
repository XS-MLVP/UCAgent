# --- coding: utf-8 ---
"""Message and state utilities for UCAgent."""

from vagent.util.functions import fill_dlist_none
from vagent.util.log import warning

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


def summarize_messages(messages, summarization_size, model):
    """Summarize messages to reduce their token count."""
    from langchain_core.messages import HumanMessage
    instruction = (f"Summarize the following conversation in less than {summarization_size} tokens, keeping the important information and context. Be concise and clear. "
                   "You must follow the rules below:\n"
                   "1. The system message should be preserved as much as possible.\n"
                   "2. The tool call results should be concise and clear, need removal of unnecessary details (e.g. file content, irrelevant context, code snippets).\n"
                   "3. Record current task status if any.\n"
                   "4. Record the verification experience you have learned.\n"
                   "5. Record the tools behavior you have learned.\n"
                   "6. Record the tools error handle suggestions you have learned.\n"
                   "7. Record the important actions you have taken and their outcomes.\n"
                   "8. Record any other important information and context.\n"
                   "You need to define the format of the summary which should be friendly to any LLMs.\n"
                   "Note: the first followed message may be the previous summary you provided before, you need to incorporate it into the new summary.\n"
                   "The result you provide should be only the summary, no other explanations or additional information."
                   )
    warning(f"Summarizing messages({count_tokens_approximately(messages)} tokens, {len(messages)} messages) to reduce context size ...")
    summary_response = model.invoke([HumanMessage(content=instruction)] + messages)
    warning(f"Summarization done, summary length: {count_tokens_approximately(summary_response.content)} tokens.")
    return summary_response


def remove_messages(messages, max_keep_msgs):
    """Remove older messages to keep the most recent max_keep_msgs messages."""
    if len(messages) <= max_keep_msgs:
        return messages, []
    index = (-max_keep_msgs) % len(messages)
    # system messages are not removed
    return messages[index:], [RemoveMessage(id=msg.id) for msg in messages[:index] if msg.type != "system"]


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

    def set_max_keep_msgs(self, max_keep_msgs: int):
        self.max_keep_msgs = max_keep_msgs
        return self

    def set_max_token(self, max_token: int):
        self.max_token = max_token
        return self

    def get_max_token(self) -> int:
        return self.max_token

    def get_max_keep_msgs(self) -> int:
        return self.max_keep_msgs


class UCMessagesNode:
    """
    Node to trim and summarize messages.
    Messages layout:
      local memory: role_info(system) + history_msgs
      llm input: summary_msgs(summarized by max_summary_tokens) + role_info + history_msg
    """

    def __init__(self, max_summary_tokens: int, max_keep_msgs: int, tail_keep_msgs: int, model):
        self.max_summary_tokens = max_summary_tokens
        self.max_keep_msgs = max_keep_msgs
        self.tail_keep_msgs = tail_keep_msgs
        self.summary_data = []
        self.model = model

    def __call__(self, state):
        fix_tool_call_args(state)
        messages = state["messages"]
        role_info = messages[:1]
        llm_input_msgs = messages[1:]
        tail_msgs = llm_input_msgs
        ret = {}
        if len(llm_input_msgs) > self.max_keep_msgs:
            # get init start index
            tail_msgs_start_index = (-self.tail_keep_msgs) % len(llm_input_msgs)
            start_msg = llm_input_msgs[tail_msgs_start_index]
            # search for the last not tool message
            while start_msg.type == "tool" and tail_msgs_start_index > 0:
                tail_msgs_start_index -= 1
                start_msg = llm_input_msgs[tail_msgs_start_index]
            tail_msgs = llm_input_msgs[tail_msgs_start_index:]
            if tail_msgs_start_index > 0:
                self.summary_data = [summarize_messages(self.summary_data + llm_input_msgs[:tail_msgs_start_index], self.max_summary_tokens, self.model)]
                deleted_msgs = [RemoveMessage(id=msg.id) for msg in llm_input_msgs[:tail_msgs_start_index]]
                warning(f"Trimmed {len(deleted_msgs)} messages, kept {len(tail_msgs)} tail messages and 1 summary message.")
                ret["messages"] = deleted_msgs
            else:
                tail_msgs = llm_input_msgs
        ret["llm_input_messages"] = self.summary_data + role_info + tail_msgs
        return ret

    def set_max_keep_msgs(self, max_keep_msgs: int):
        self.max_keep_msgs = max_keep_msgs
        return self

    def set_max_token(self, max_token: int):
        self.max_token = max_token
        return self

    def get_max_token(self) -> int:
        return self.max_token

    def get_max_keep_msgs(self) -> int:
        return self.max_keep_msgs


class State(AgentState):
    """Agent state with additional context information."""
    # NOTE: we're adding this key to keep track of previous summary information
    # to make sure we're not summarizing on every LLM call
    context: Dict[str, Any]
