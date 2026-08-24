"""Messages summarization middleware."""

import math
import time
from collections import OrderedDict
from typing import Any, Dict, Union

from langchain.agents.middleware import SummarizationMiddleware
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langmem.short_term import SummarizationNode
from pydantic import BaseModel
from typing_extensions import override

from ucagent.util.functions import fill_dlist_none
from ucagent.util.log import info, warning


class MessageStatistic:
    """Track message characters and provider-reported token usage."""

    def __init__(self):
        """Initialize message statistics."""
        self.recorded_messages = set()
        self.count_human_messages = 0
        self.count_ai_messages = 0
        self.count_tool_messages = 0
        self.count_system_messages = 0
        self.text_size_human_messages = 0
        self.text_size_ai_messages = 0
        self.text_size_tool_messages = 0
        self.text_size_system_messages = 0
        self.count_unknown_messages = 0
        self.text_size_unknown_messages = 0
        self.recorded_usage = set()
        self.usage_without_metadata = set()
        self.provider_usage = {
            "main": self._empty_usage(),
            "summary": self._empty_usage(),
        }

    @staticmethod
    def _empty_usage():
        return {
            "responses": 0,
            "responses_with_usage": 0,
            "responses_without_usage": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cache_read_tokens": 0,
        }

    def get_message_text_size(self, msg: BaseMessage) -> int:
        """Get the text size of a message."""
        return len(msg.text)

    def _record_provider_usage(self, msg: BaseMessage, usage_source: str) -> None:
        if not isinstance(msg, AIMessage):
            return
        usage_key = (usage_source, msg.id if msg.id is not None else id(msg))
        if (
            usage_key in self.recorded_usage
            and usage_key not in self.usage_without_metadata
        ):
            return
        usage = self.provider_usage.setdefault(usage_source, self._empty_usage())
        if usage_key not in self.recorded_usage:
            self.recorded_usage.add(usage_key)
            usage["responses"] += 1
        if not msg.usage_metadata:
            if usage_key not in self.usage_without_metadata:
                self.usage_without_metadata.add(usage_key)
                usage["responses_without_usage"] += 1
            return
        if usage_key in self.usage_without_metadata:
            self.usage_without_metadata.remove(usage_key)
            usage["responses_without_usage"] -= 1
        usage["responses_with_usage"] += 1
        input_tokens = msg.usage_metadata.get("input_tokens", 0) or 0
        output_tokens = msg.usage_metadata.get("output_tokens", 0) or 0
        total_tokens = msg.usage_metadata.get("total_tokens")
        if not isinstance(total_tokens, int):
            total_tokens = input_tokens + output_tokens
        input_details = msg.usage_metadata.get("input_token_details") or {}
        cache_read = input_details.get("cache_read", 0) or 0
        usage["input_tokens"] += input_tokens
        usage["output_tokens"] += output_tokens
        usage["total_tokens"] += total_tokens
        usage["cache_read_tokens"] += cache_read

    def update_message(self, messages, usage_source="main"):
        """Update message statistics based on the provided messages."""
        if messages is None:
            return
        if not isinstance(messages, list):
            messages = [messages]
        for msg in messages:
            self._record_provider_usage(msg, usage_source)
            message_key = msg.id if msg.id is not None else id(msg)
            if message_key in self.recorded_messages:
                continue
            if isinstance(msg, RemoveMessage):
                continue
            self.recorded_messages.add(message_key)
            if isinstance(msg, HumanMessage):
                self.count_human_messages += 1
                self.text_size_human_messages += self.get_message_text_size(msg)
            elif isinstance(msg, AIMessage):
                self.count_ai_messages += 1
                self.text_size_ai_messages += self.get_message_text_size(msg)
            elif isinstance(msg, ToolMessage):
                self.count_tool_messages += 1
                self.text_size_tool_messages += self.get_message_text_size(msg)
            elif isinstance(msg, SystemMessage):
                self.count_system_messages += 1
                self.text_size_system_messages += self.get_message_text_size(msg)
            else:
                # Unknown message type
                self.count_unknown_messages += 1
                self.text_size_unknown_messages += self.get_message_text_size(msg)

    def reset_statistics(self):
        """Reset all message statistics."""
        self.recorded_messages.clear()
        self.count_human_messages = 0
        self.count_ai_messages = 0
        self.count_tool_messages = 0
        self.count_system_messages = 0
        self.text_size_human_messages = 0
        self.text_size_ai_messages = 0
        self.text_size_tool_messages = 0
        self.text_size_system_messages = 0
        self.count_unknown_messages = 0
        self.text_size_unknown_messages = 0
        self.recorded_usage.clear()
        self.usage_without_metadata.clear()
        self.provider_usage = {
            "main": self._empty_usage(),
            "summary": self._empty_usage(),
        }

    def get_statistics(self) -> dict:
        """Get the current message statistics."""
        message_in_count = (
            self.count_human_messages
            + self.count_tool_messages
            + self.count_system_messages
            + self.count_unknown_messages
        )
        message_out_count = self.count_ai_messages
        message_in_size = (
            self.text_size_human_messages
            + self.text_size_tool_messages
            + self.text_size_system_messages
            + self.text_size_unknown_messages
        )
        message_out_size = self.text_size_ai_messages
        provider_usage = {
            source: dict(usage) for source, usage in self.provider_usage.items()
        }
        provider_usage["all"] = {
            key: sum(usage[key] for usage in self.provider_usage.values())
            for key in self._empty_usage()
        }
        return OrderedDict(
            {
                "count": {
                    "human": self.count_human_messages,
                    "ai": self.count_ai_messages,
                    "tool": self.count_tool_messages,
                    "system": self.count_system_messages,
                    "unknown": self.count_unknown_messages,
                },
                "size": {
                    "human": self.text_size_human_messages,
                    "ai": self.text_size_ai_messages,
                    "tool": self.text_size_tool_messages,
                    "system": self.text_size_system_messages,
                    "unknown": self.text_size_unknown_messages,
                },
                "total_count_messages": message_in_count + message_out_count,
                "total_text_size_messages": message_in_size + message_out_size,
                "message_in": message_in_size,
                "message_out": message_out_size,
                "provider_usage": provider_usage,
            }
        )


class StreamedOutputCallbackHandler(BaseCallbackHandler):
    """Track streamed output characters without presenting them as tokens."""

    def __init__(self):
        super().__init__()
        self.total_characters = 0
        self.last_characters = 0
        self.last_access_time = 0.0
        self.last_character_speed = 0.0

    def on_llm_new_token(self, token: str, **kwargs) -> None:
        self.total_characters += len(token)
        chunk = kwargs.get("chunk")
        message = getattr(chunk, "message", None)
        if message and hasattr(message, "tool_call_chunks"):
            for tool_call in message.tool_call_chunks:
                tool_name = tool_call.get("name")
                args = tool_call.get("args")
                if tool_name:
                    self.total_characters += len(tool_name)
                if args:
                    self.total_characters += len(args)

    def get_speed(self) -> float:
        if self.last_access_time == 0.0:
            self.last_access_time = time.time()
            self.last_characters = self.total_characters
            return 0.0
        now_time = time.time()
        delta_time = now_time - self.last_access_time
        if delta_time < 1.0:
            return self.last_character_speed
        delta_characters = self.total_characters - self.last_characters
        self.last_access_time = now_time
        self.last_character_speed = delta_characters / delta_time
        self.last_characters = self.total_characters
        return self.last_character_speed

    def total(self) -> int:
        return self.total_characters


# Backward-compatible import name. Values from this callback are characters.
TokenSpeedCallbackHandler = StreamedOutputCallbackHandler


def _raw_estimated_tokens(messages, tools=None) -> int:
    """Estimate message and tool-schema tokens using LangChain's generic counter."""
    if isinstance(messages, str):
        messages = [HumanMessage(content=messages)]
    return count_tokens_approximately(messages, tools=tools or None)


def _usage_input_tokens(message: BaseMessage) -> int | None:
    if not isinstance(message, AIMessage) or not message.usage_metadata:
        return None
    value = message.usage_metadata.get("input_tokens")
    return value if isinstance(value, int) and value > 0 else None


def _summary_text(response_content) -> str:
    if isinstance(response_content, str):
        return response_content
    if isinstance(response_content, list):
        return "".join(
            block.get("text", "")
            for block in response_content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(response_content)


def _truncate_to_token_budget(text: str, token_budget: int) -> str:
    """Deterministically cap text when a provider ignores its output limit."""
    if token_budget < 1:
        return ""
    if _raw_estimated_tokens(text) <= token_budget:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if _raw_estimated_tokens(text[:middle]) <= token_budget:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip()


def _summary_invoke_kwargs(model, token_budget: int) -> dict:
    """Map the summary output budget to the supported chat-model call option."""
    model_module = type(model).__module__.lower()
    if "google_genai" in model_module:
        return {"max_output_tokens": token_budget}
    return {"max_tokens": token_budget}


def fix_tool_call_args(input: Union[Dict[str, Any], BaseModel]) -> Dict[str, Any]:
    for msg in input["messages"][-4:]:
        if not isinstance(msg, AIMessage):
            continue
        if hasattr(msg, "additional_kwargs"):
            msg.additional_kwargs = fill_dlist_none(msg.additional_kwargs, '{}', "arguments", ["arguments"])
        if hasattr(msg, "invalid_tool_calls"):
            msg.invalid_tool_calls = fill_dlist_none(msg.invalid_tool_calls, '{}', "args", ["args"])


def _strip_thinking_blocks(messages):
    """Remove Anthropic 'thinking' content blocks from AIMessage content.

    When extended thinking is enabled, Anthropic models return AIMessages whose
    ``content`` is a list that includes dicts of the form
    ``{'type': 'thinking', 'thinking': '...', 'index': N}``.  LangChain's
    message-coercion logic does not recognise these dicts (they lack ``role``
    and ``content`` keys) and raises ``ValueError`` when the messages are
    reused as model input.  This function strips those blocks so that only
    ``text``-type content remains.
    """
    result = []
    for msg in messages:
        if isinstance(msg, AIMessage) and isinstance(msg.content, list):
            clean_content = [
                block for block in msg.content
                if not (isinstance(block, dict) and block.get("type") == "thinking")
            ]
            if not clean_content:
                clean_content = ""
            msg = msg.model_copy(update={"content": clean_content})
        result.append(msg)
    return result


def summarize_messages(messages, summarization_size, model, msg_stat=None):
    """Summarize messages to reduce their token count."""
    if not isinstance(summarization_size, int) or summarization_size < 1:
        raise ValueError("max_summary_tokens must be a positive integer")
    # Strip Anthropic thinking blocks before passing messages to the model to
    # avoid LangChain message-coercion errors.
    messages = _strip_thinking_blocks(messages)
    instruction = (f"Summarize the conversation in less than {summarization_size} tokens, keeping the important information and context. Be concise and clear. "
                   "You must follow the rules below:\n"
                   "1. The system message should be preserved as much as possible.\n"
                   "2. The tool call results should be concise and clear, need removal of unnecessary details (e.g. file content, irrelevant context, code snippets).\n"
                   "3. Record current task status if any.\n"
                   "4. Record the verification experience you have learned.\n"
                   "5. Record the tools behavior you have learned.\n"
                   "6. Record the tools error handle suggestions you have learned.\n"
                   "7. Record only the relevant SKILL name/path and current constraints; do not copy the full SKILL content.\n"
                   "8. Record the important actions you have taken and their outcomes.\n"
                   "9. Record any other important information and context.\n"
                   "You need to define the format of the summary which should be friendly to any LLMs.\n"
                   "Note: the first followed message may be the previous summary you provided before, you need to incorporate it into the new summary.\n"
                   "The result you provide should be only the summary, no other explanations or additional information."
                   )
    summary_messages = messages + [HumanMessage(content=instruction)]
    estimated_input_tokens = _raw_estimated_tokens(summary_messages)
    warning(
        "Summarizing message prefix "
        f"({estimated_input_tokens} estimated tokens, {len(messages)} messages) ..."
    )
    summary_response = model.invoke(
        summary_messages,
        **_summary_invoke_kwargs(model, summarization_size),
    )
    if msg_stat is not None:
        msg_stat.update_message(summary_response, usage_source="summary")
    # The summarization response may itself contain thinking blocks; extract
    # only the text parts to produce a plain string for the HumanMessage.
    response_content = _summary_text(summary_response.content)
    estimated_output_tokens = _raw_estimated_tokens(response_content)
    provider_output_tokens = None
    if summary_response.usage_metadata:
        value = summary_response.usage_metadata.get("output_tokens")
        if isinstance(value, int) and value > 0:
            provider_output_tokens = value
    measured_output_tokens = max(
        provider_output_tokens or 0, estimated_output_tokens
    )
    if measured_output_tokens > summarization_size:
        warning(
            "Summary model exceeded its output budget "
            f"({measured_output_tokens} tokens > {summarization_size}); "
            "applying a deterministic fallback cap."
        )
        if provider_output_tokens:
            character_budget = max(
                1,
                math.floor(
                    len(response_content)
                    * summarization_size
                    / provider_output_tokens
                    * 0.9
                ),
            )
            response_content = response_content[:character_budget].rstrip()
        response_content = _truncate_to_token_budget(
            response_content, summarization_size
        )
        estimated_output_tokens = _raw_estimated_tokens(response_content)
    warning(
        "Summarization done: "
        f"estimated_output_tokens={estimated_output_tokens}, "
        f"provider_output_tokens={provider_output_tokens or 'unavailable'}, "
        f"max_summary_tokens={summarization_size}."
    )
    return HumanMessage(content=response_content)


def remove_messages(messages, max_keep_msgs):
    """Remove older messages to keep the most recent max_keep_msgs messages."""
    if len(messages) <= max_keep_msgs:
        return messages, []
    index = (-max_keep_msgs) % len(messages)
    # system messages are not removed
    return messages[index:], [RemoveMessage(id=msg.id) for msg in messages[:index] if msg.type != "system"]


def retain_skill_read_messages_as_human(messages, use_skill=False, skill_list=None):
    """Retain SKILL.md reads as HumanMessage when skill usage is enabled."""
    if not use_skill or not skill_list:
        return []
    pending_tool_call_ids = []
    rebuilt_messages = []
    propmt_of_skill = "Use this skill to complete tasks:\n"
    rebuilt_contents = set()
    for msg in messages:
        if isinstance(msg, HumanMessage):
            if msg.content.startswith(propmt_of_skill):
                if msg.content not in rebuilt_contents:
                    rebuilt_messages.append(msg)
                    rebuilt_contents.add(msg.content)
        if isinstance(msg, AIMessage):
            for tool_call in msg.tool_calls:
                if tool_call.get("name") != "ReadTextFile":
                    continue
                path = tool_call.get("args", {}).get("path", "")
                if not isinstance(path, str) or not path.endswith("SKILL.md"):
                    continue
                tool_call_id = tool_call.get("id")
                if tool_call_id:
                    pending_tool_call_ids.append(tool_call_id)
    for msg in messages:
        if isinstance(msg, ToolMessage):
            tool_call_id = getattr(msg, "tool_call_id", None)
            if tool_call_id in pending_tool_call_ids:
                content = propmt_of_skill + msg.content
                if content not in rebuilt_contents:
                    rebuilt_messages.append(HumanMessage(content=content))
                    rebuilt_contents.add(content)
                pending_tool_call_ids.remove(tool_call_id)
    return rebuilt_messages


class SummarizationAndFixToolCall(SummarizationNode):
    """Custom summarization node that fixes tool call arguments."""

    def set_max_keep_msgs(self, msg_stat: MessageStatistic, max_keep_msgs: int):
        self.max_keep_msgs = max_keep_msgs
        self.msg_stat = msg_stat
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
        if "llm_input_messages" in ret:
            self.msg_stat.update_message(ret["llm_input_messages"])
        else:
            self.msg_stat.update_message(ret["messages"])
        return ret

    def set_max_token(self, max_token: int):
        self.max_token = max_token
        return self

    def get_max_token(self) -> int:
        return self.max_token

    def get_max_keep_msgs(self) -> int:
        return self.max_keep_msgs


class TrimAndSummaryMiddleware(AgentMiddleware):
    """trim and summarize older context for managing conversation context."""
    def __init__(self, msg_stat: MessageStatistic, max_summary_tokens: int,
                 max_keep_msgs: int, max_tokens: int, tail_keep_msgs: int, model,
                 tools=None):
        if not isinstance(max_summary_tokens, int) or max_summary_tokens < 1:
            raise ValueError("max_summary_tokens must be a positive integer")
        if any(
            not isinstance(value, int) or value < 0
            for value in (max_keep_msgs, max_tokens, tail_keep_msgs)
        ):
            raise ValueError(
                "max_keep_msgs, max_tokens, and tail_keep_msgs must be non-negative integers"
            )
        if max_keep_msgs > 0 and tail_keep_msgs > max_keep_msgs:
            raise ValueError(
                "tail_keep_msgs cannot exceed an enabled max_keep_msgs limit"
            )
        self.msg_stat = msg_stat
        self.max_summary_tokens = max_summary_tokens
        self.max_keep_msgs = max_keep_msgs
        self.max_tokens = max_tokens
        self.tail_keep_msgs = tail_keep_msgs
        self.summary_data = []
        self.model = model
        self.arbit_summary_data = None
        self._is_reset_chat = False
        self._is_reset_force = False
        self.system_message = None
        self.vagent = None
        self.tools = list(tools or [])
        self.token_estimate_scale = 1.0
        self.last_context_tokens_estimated = 0
        self.last_context_message_count = 0
        self.last_compression = None
        self.stale_calibration_messages = set()

    def set_tools(self, tools):
        """Bind the final tool set used for context-token estimation."""
        self.tools = list(tools or [])
        return self

    @staticmethod
    def _calibration_message_key(message: AIMessage):
        if message.id is not None:
            return ("id", message.id)
        usage = message.usage_metadata or {}
        return (
            "content",
            repr(message.content),
            repr(message.tool_calls),
            usage.get("input_tokens"),
            usage.get("output_tokens"),
        )

    def _mark_existing_usage_stale(self, messages) -> None:
        for message in messages:
            if isinstance(message, AIMessage) and message.usage_metadata:
                self.stale_calibration_messages.add(
                    self._calibration_message_key(message)
                )

    def _update_token_estimate_scale(self, messages) -> None:
        """Calibrate the generic estimate with the latest provider input usage."""
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if not isinstance(message, AIMessage):
                continue
            if (
                self._calibration_message_key(message)
                in self.stale_calibration_messages
            ):
                continue
            provider_input_tokens = _usage_input_tokens(message)
            if provider_input_tokens is None:
                continue
            raw_tokens = _raw_estimated_tokens(
                messages[:index], tools=self.tools
            )
            if raw_tokens > 0:
                self.token_estimate_scale = min(
                    8.0, max(0.25, provider_input_tokens / raw_tokens)
                )
            return

    def estimate_context_tokens(self, messages, calibrate=True) -> int:
        """Return a tool-aware estimate calibrated by recent provider usage."""
        if calibrate:
            self._update_token_estimate_scale(messages)
        raw_tokens = _raw_estimated_tokens(messages, tools=self.tools)
        return math.ceil(raw_tokens * self.token_estimate_scale)

    def get_context_metrics(self, messages=None) -> dict:
        """Expose current estimates, limits, and the latest compression reason."""
        if messages is not None:
            effective_messages = list(messages)
            if (
                self.system_message
                and not (
                    effective_messages
                    and isinstance(effective_messages[0], SystemMessage)
                )
            ):
                effective_messages.insert(0, self.system_message)
            self.last_context_tokens_estimated = self.estimate_context_tokens(
                effective_messages
            )
            system_count = bool(
                effective_messages
                and isinstance(effective_messages[0], SystemMessage)
            )
            self.last_context_message_count = (
                len(effective_messages) - system_count
            )
        return {
            "context_tokens_estimated": self.last_context_tokens_estimated,
            "context_message_count": self.last_context_message_count,
            "token_estimate_scale": self.token_estimate_scale,
            "max_tokens": self.max_tokens,
            "max_keep_msgs": self.max_keep_msgs,
            "max_summary_tokens": self.max_summary_tokens,
            "tail_keep_msgs": self.tail_keep_msgs,
            "last_compression": self.last_compression,
        }

    def reset_chat(self, force=False):
        self._is_reset_chat = True
        self._is_reset_force = force
        return self

    def set_system_message(self, system_message: SystemMessage):
        self.system_message = system_message
        return self

    @override
    async def abefore_model(self, state, runtime) -> dict[str, Any] | None:
        return self.before_model(state)

    @override
    def before_model(self, state: AgentState[Any]) -> dict[str, Any] | None:
        fix_tool_call_args(state)
        messages = state["messages"]
        system_was_missing = not (
            messages and isinstance(messages[0], SystemMessage)
        )
        if system_was_missing and self.system_message:
            warning("System message is missing, adding it back to the context.")
            role_info = [self.system_message]
            llm_input_msgs = messages
        elif system_was_missing:
            role_info = []
            llm_input_msgs = messages
        else:
            role_info = messages[:1]
            llm_input_msgs = messages[1:]
        effective_messages = role_info + llm_input_msgs
        current_token_size = self.estimate_context_tokens(effective_messages)
        current_message_count = len(llm_input_msgs)
        self.last_context_tokens_estimated = current_token_size
        self.last_context_message_count = current_message_count
        tail_msgs = llm_input_msgs
        rebuilt_skill_msgs = []
        ret = {}
        if self._is_reset_chat:
            self.summary_data = []
            # Remove all previous messages except system message and the most recent Human/Tool message
            tail_index = SummarizationMiddleware._find_safe_cutoff_point(llm_input_msgs, max(0, len(llm_input_msgs) - 2))
            # Ensure tail_msgs starts with a HumanMessage: some LLM APIs (e.g. Anthropic) require
            # the first non-system message to be a human/user message. _find_safe_cutoff_point may
            # backtrack past a HumanMessage to keep AIMessage/ToolMessage pairs together, leaving
            # tail_msgs starting with an AIMessage which causes "No generations found in stream".
            humam_msg_index = max(0, tail_index)
            while humam_msg_index > 0 and not isinstance(llm_input_msgs[humam_msg_index], HumanMessage):
                humam_msg_index -= 1
            humam_msg_index = max(0, humam_msg_index)
            tail_msgs = llm_input_msgs[tail_index:]
            if humam_msg_index < tail_index:
                tail_msgs = [llm_input_msgs[humam_msg_index], *tail_msgs]
            if self._is_reset_force:
                # find the last HumanMessage
                force_human_list = -1
                for i in range(len(tail_msgs)-1, -1, -1):
                    if isinstance(tail_msgs[i], HumanMessage):
                        force_human_list = i
                        break
                if force_human_list >= 0:
                    tail_msgs = [tail_msgs[force_human_list]]
                else:
                    warning(f"No HumanMessage found in tails messages (size={len(tail_msgs)}), cannot force reset to human message, falling back to normal behavior.")
            ret["messages"] = [RemoveMessage(id=REMOVE_ALL_MESSAGES)] + role_info + tail_msgs
            warning(f"Chat reset [force={self._is_reset_force}], all messages ({len(llm_input_msgs) - len(tail_msgs)}) messages are removed except system and the most recent {len(tail_msgs)} messages.")
            self.last_compression = {
                "reason": "stage_reset",
                "before_tokens_estimated": current_token_size,
                "before_messages": current_message_count,
                "after_tokens_estimated": self.estimate_context_tokens(
                    role_info + tail_msgs, calibrate=False
                ),
                "after_messages": len(tail_msgs),
            }
            self._mark_existing_usage_stale(role_info + tail_msgs)
            self._is_reset_chat = False
            self._is_reset_force = False
        elif self.arbit_summary_data is None:
            token_limit_exceeded = (
                self.max_tokens > 0 and current_token_size > self.max_tokens
            )
            message_limit_exceeded = (
                self.max_keep_msgs > 0
                and current_message_count > self.max_keep_msgs
            )
            if message_limit_exceeded or token_limit_exceeded:
                trigger_reasons = []
                if token_limit_exceeded:
                    trigger_reasons.append("token_limit")
                if message_limit_exceeded:
                    trigger_reasons.append("message_limit")
                trigger_reason = "+".join(trigger_reasons)
                warning(
                    "Context compression triggered: "
                    f"reason={trigger_reason}, "
                    f"context_tokens_estimated={current_token_size}, "
                    f"max_tokens={self.max_tokens}, "
                    f"context_messages={current_message_count}, "
                    f"max_keep_msgs={self.max_keep_msgs}."
                )
                # get tail start index
                tail_msgs_start_index = SummarizationMiddleware._find_safe_cutoff_point(llm_input_msgs, max(0, len(llm_input_msgs) - self.tail_keep_msgs))
                if tail_msgs_start_index > 0:
                    tail_msgs = llm_input_msgs[tail_msgs_start_index:]
                    use_skill = bool(getattr(getattr(self.vagent, "cfg", None), "skill", None) and self.vagent.cfg.skill.use_skill)
                    skill_list = None
                    if self.vagent and getattr(self.vagent, "stage_manager", None):
                        current_stage = self.vagent.stage_manager.get_current_stage()
                        if current_stage is not None:
                            skill_list = getattr(current_stage, "skill_list", None)
                    rebuilt_skill_msgs = retain_skill_read_messages_as_human(
                        llm_input_msgs[:tail_msgs_start_index],
                        use_skill=use_skill,
                        skill_list=skill_list,
                    )
                    self.summary_data = [summarize_messages(
                        llm_input_msgs[:tail_msgs_start_index],
                        self.max_summary_tokens,
                        self.model,
                        msg_stat=self.msg_stat,
                    )]
                    compressed_messages = (
                        role_info
                        + rebuilt_skill_msgs
                        + self.summary_data
                        + tail_msgs
                    )
                    after_tokens = self.estimate_context_tokens(
                        compressed_messages, calibrate=False
                    )
                    after_message_count = len(compressed_messages) - len(role_info)
                    self.last_compression = {
                        "reason": trigger_reason,
                        "before_tokens_estimated": current_token_size,
                        "before_messages": current_message_count,
                        "after_tokens_estimated": after_tokens,
                        "after_messages": after_message_count,
                        "summarized_messages": tail_msgs_start_index,
                    }
                    self.last_context_tokens_estimated = after_tokens
                    self.last_context_message_count = after_message_count
                    self._mark_existing_usage_stale(compressed_messages)
                    warning(
                        "Context compression complete: "
                        f"reason={trigger_reason}, "
                        f"before_tokens_estimated={current_token_size}, "
                        f"after_tokens_estimated={after_tokens}, "
                        f"summarized_messages={tail_msgs_start_index}, "
                        f"kept_tail_messages={len(tail_msgs)}, "
                        f"retained_skill_messages={len(rebuilt_skill_msgs)}."
                    )
                    ret["messages"] = [RemoveMessage(id=REMOVE_ALL_MESSAGES)] + compressed_messages
                else:
                    tail_msgs = llm_input_msgs
                    self.last_compression = {
                        "reason": f"{trigger_reason}_deferred_no_safe_prefix",
                        "before_tokens_estimated": current_token_size,
                        "before_messages": current_message_count,
                        "after_tokens_estimated": current_token_size,
                        "after_messages": current_message_count,
                    }
                    warning(
                        "Context compression deferred because no safe message "
                        "prefix can be summarized while preserving the configured tail."
                    )
        else:
            warning(f"Using arbitrary provided summary.")
            assert isinstance(self.arbit_summary_data, list), f"Need List, but find: {type(self.arbit_summary_data)}: {self.arbit_summary_data}"
            self.summary_data = self.arbit_summary_data
            self.arbit_summary_data = None
            ret["messages"] = (
                [RemoveMessage(id=REMOVE_ALL_MESSAGES)]
                + role_info
                + self.summary_data
            )
            tail_msgs = []
            self.last_compression = {
                "reason": "manual",
                "before_tokens_estimated": current_token_size,
                "before_messages": current_message_count,
                "after_tokens_estimated": self.estimate_context_tokens(
                    role_info + self.summary_data, calibrate=False
                ),
                "after_messages": len(self.summary_data),
            }
            self._mark_existing_usage_stale(role_info + self.summary_data)
        if system_was_missing and self.system_message and "messages" not in ret:
            ret["messages"] = (
                [RemoveMessage(id=REMOVE_ALL_MESSAGES)] + effective_messages
            )
        self.msg_stat.update_message(role_info + rebuilt_skill_msgs + self.summary_data + tail_msgs)
        return ret
    
    def set_arbit_summary(self, summary_text):
        """Set chat summary"""
        if isinstance(summary_text, str):
            info("Arbit Summary:\n" + summary_text)
            self.arbit_summary_data = [HumanMessage(content=summary_text)]
        else:
            assert isinstance(summary_text, list)
            for m in summary_text:
                assert isinstance(m, BaseMessage), f"Need BaseMessage, but find: {type(m)}: {m}"
            info("Arbit Summary:\n" + "\n".join([x.content for x in summary_text]))
            self.arbit_summary_data = summary_text
        return self

    def force_summary(self, messages):
        """Generate chat summary from hist messages"""
        return self.set_arbit_summary([summarize_messages(messages,
                                                          self.max_summary_tokens,
                                                          self.model,
                                                          msg_stat=self.msg_stat)])

    def set_max_keep_msgs(self, max_keep_msgs: int):
        self.max_keep_msgs = max_keep_msgs
        return self

    def set_max_token(self, max_token: int):
        self.max_tokens = max_token
        self.max_token = max_token
        return self

    def get_max_token(self) -> int:
        return self.max_tokens

    def get_max_keep_msgs(self) -> int:
        return self.max_keep_msgs
    
class State(AgentState):
    """Agent state with additional context information."""
    # NOTE: we're adding this key to keep track of previous summary information
    # to make sure we're not summarizing on every LLM call
    context: Dict[str, Any]
