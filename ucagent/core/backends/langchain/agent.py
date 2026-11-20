#coding=utf-8
"""LangChain backend integration for UCAgent."""

import threading
from concurrent.futures import CancelledError
from ucagent.util.output import output_source, output_context

from ucagent.core.backends.base import AgentBackendBase, BackendCapabilities
from ucagent.core.backends.langchain.cancellation import AsyncModelView, CancellableModelCalls, ModelRequests
from ucagent.core.backends.langchain.content import content_text, format_message, new_messages
from ucagent.util.log import info, warning
from ucagent.core.backends.langchain.middleware import (
    MessageStatistic,
    TokenSpeedCallbackHandler,
    TrimAndSummaryMiddleware,
)
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver
from ucagent.util.models import get_chat_model, negotiate_openai_api_mode
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from ucagent.util.functions import get_ai_message_tool_call


class UCAgentLangChainBackend(AgentBackendBase):
    """
    LangChain-based agent backend implementation.
    """

    capabilities = BackendCapabilities(managed_sessions=True, model_rounds=True, resume=True)

    def __init__(self, vagent, config, **kwargs):
        """Create local message/context state without constructing model clients."""
        super().__init__(vagent, config, **kwargs)
        self.message_statistic = MessageStatistic()
        self.cb_stream_output = TokenSpeedCallbackHandler()
        self.cb_summary_stream_output = TokenSpeedCallbackHandler()
        self.cb_runtime_output = TokenSpeedCallbackHandler()
        # Retain the old attribute for callers that inspect the backend directly.
        self.cb_token_speed = self.cb_runtime_output
        # Stream events replace this tuple atomically, keeping status rendering
        # independent from the graph's live state lock.
        self._status_messages = ()
        self.openai_api_mode = None
        self.model = None
        self.sumary_model = None
        self.agent = None
        self._prepare_lock = threading.Lock()
        self._prepare_error = None
        self.requests = ModelRequests(vagent)
        if vagent.context_management_strategy == "TrimAndSummaryMiddleware":
            message_manage_node = TrimAndSummaryMiddleware(
                msg_stat=self.message_statistic,
                max_summary_tokens=vagent.max_summary_tokens,
                max_keep_msgs=vagent.max_keep_msgs,
                max_tokens=vagent.max_token,
                tail_keep_msgs=vagent.tail_keep_msgs,
                model=None,
            )
        else:
            raise ValueError(f"Unsupported context_management_strategy: {vagent.context_management_strategy}")
        message_manage_node.vagent = vagent
        self.message_manage_node = message_manage_node

    def set_debug(self, debug):
        from langchain_core.globals import set_debug
        set_debug(debug)

    def init(self):
        """Bind the final tool list without preparing models or probing a provider."""
        self.message_manage_node.set_tools(self.vagent.test_tools)
        from .middleware.execution import ExecutionBudget
        session = getattr(self.vagent, "execution_session", None)
        self._session_middleware = [ExecutionBudget(session=session)] if session else []

    def prepare(self):
        """Prepare models and graph once at the first explicit model operation."""
        with self._prepare_lock:
            if self.agent is not None:
                return
            if self._prepare_error is not None:
                raise self._prepare_error
            try:
                if self.config.get_value("model_type", "openai") == "openai":
                    self.openai_api_mode = negotiate_openai_api_mode(self.config, invoke=self.requests.invoke)
                self.model = get_chat_model(
                    self.config, [self.cb_stream_output, self.cb_runtime_output],
                    openai_api_mode=self.openai_api_mode, streaming=self.vagent.stream_output,
                )
                self.sumary_model = get_chat_model(
                    self.config, [self.cb_summary_stream_output, self.cb_runtime_output],
                    openai_api_mode=self.openai_api_mode, streaming=self.vagent.stream_output,
                )
                self.message_manage_node.model = AsyncModelView(self.sumary_model, self.requests, "summary")
                self.agent = create_agent(
                    model=self.model, tools=self.vagent.test_tools,
                    checkpointer=MemorySaver(), middleware=[*getattr(self.vagent, "additional_middleware", []), *self._session_middleware,
                        CancellableModelCalls(self.requests), self.message_manage_node],
                )
            except Exception as error:
                # Configuration remains fixed for this instance; repeated status/work
                # calls must not keep probing a broken provider configuration.
                if not isinstance(error, CancelledError):
                    self._prepare_error = error
                raise

    def cancel(self):
        """Interrupt only an active provider request, leaving tools to reach a safe boundary."""
        self.requests.cancel()

    def exit(self):
        """Drain backend-owned network resources after model and tool execution has stopped."""
        self.requests.close()

    def reset_chat(self, force=False):
        self.message_manage_node.reset_chat(force)

    def on_stage_complete(self, stage):
        """Preserve conversation history across stage boundaries for now."""
        # Temporarily disabled: self.reset_chat(force=False).
        # Explicit reset/summary and context-limit compression remain available.
        pass

    def get_human_message(self, text, *, display_text=None):
        """Keep the full model prompt and optionally attach a separate display body."""
        metadata = {"ucagent_display_text": display_text} if display_text is not None else {}
        return HumanMessage(content=text, response_metadata=metadata)

    def get_system_message(self, text):
        msg = SystemMessage(content=text)
        self.message_manage_node.set_system_message(msg)
        return msg

    def state_record_mesg(self, msg):
        if isinstance(msg, AIMessage):
            self._stat_msg_count_ai += 1
        elif isinstance(msg, ToolMessage):
            self._stat_msg_count_tool += 1
        elif isinstance(msg, SystemMessage):
            self._stat_msg_count_system += 1
        self.message_statistic.update_message(msg, usage_source="main")

    def get_message_manage_node(self):
        return self.message_manage_node

    def _process_msg_content(self, msg):
        """Extract only text from provider content blocks."""
        return content_text(msg)

    def format_message(self, msg):
        """Apply tool-owned display policies to live output and history views alike."""
        body = None
        if isinstance(msg, ToolMessage):
            tool = next((tool for tool in getattr(self.vagent, "test_tools", ()) if tool.name == msg.name), None)
            formatter = getattr(tool, "display_result", None)
            if formatter is not None:
                body = formatter(content_text(msg.content))
        return format_message(msg, body=body)

    def echo_message(self, msg):
        """Emit one complete text message under its model/tool output attribution."""
        with output_context(source="tool" if isinstance(msg, ToolMessage) else "model",
                            kind="result" if isinstance(msg, ToolMessage) else "message"):
            rendered = self.format_message(msg)
            if rendered:
                self.vagent.message_echo(rendered)

    @output_source("model")
    def do_work_stream(self, instructions, config):
        """Render each main-model response with a separate header and intact text lines."""
        self.prepare()
        seen = set()
        streamed_text = ""
        line_open = False
        try:
            for event, data in self.agent.stream(instructions, config, stream_mode=["values", "messages"]):
                if self.vagent.is_break() and not (getattr(self.vagent, "execution_session", None)
                    and self.vagent.execution_session.yielded()):
                    break
                if event == "messages":
                    msg, metadata = data
                    if not isinstance(msg, AIMessage) or metadata.get("langgraph_node") not in {None, "model"}:
                        continue
                    if msg.id is not None and msg.id in seen:
                        continue
                    text = self._process_msg_content(msg.content)
                    if not text:
                        continue
                    # This graph has one serial main-model node. Its final values
                    # event commits the response; provider chunk IDs may change.
                    if not streamed_text:
                        self.vagent.message_echo("\n" + " AI Message ".center(80, "=") + "\n")
                    self.vagent.message_echo(text, end="")
                    streamed_text += text
                    line_open = not text.endswith("\n")
                    continue
                self._status_messages = tuple(data["messages"])
                for msg in new_messages(data["messages"], seen):
                    self.state_record_mesg(msg)
                    if isinstance(msg, AIMessage) and streamed_text:
                        # A provider may only stream a prefix. Preserve the rest
                        # of the committed body without printing another heading.
                        final_text = content_text(msg.content)
                        if final_text.startswith(streamed_text):
                            tail = final_text[len(streamed_text):]
                            if tail:
                                self.vagent.message_echo(tail, end="")
                                line_open = not tail.endswith("\n")
                        if line_open:
                            self.vagent.message_echo("")
                            line_open = False
                        tool_call = get_ai_message_tool_call(msg)
                        if tool_call:
                            with output_context(source="tool", kind="call"):
                                self.vagent.message_echo("\n" + tool_call)
                        streamed_text = ""
                    else:
                        if line_open:
                            self.vagent.message_echo("")
                            line_open = False
                        self.echo_message(msg)
        finally:
            if line_open:
                self.vagent.message_echo("")

    @output_source("model")
    def do_work_values(self, instructions, config):
        """Emit complete text messages without serializing provider block dictionaries."""
        self.prepare()
        seen = set()
        for _, step in self.agent.stream(instructions, config, stream_mode=["values"]):
            if self.vagent.is_break() and not (getattr(self.vagent, "execution_session", None)
                    and self.vagent.execution_session.yielded()):
                break
            self._status_messages = tuple(step["messages"])
            for msg in new_messages(step["messages"], seen):
                self.state_record_mesg(msg)
                self.echo_message(msg)

    def messages_get_raw(self):
        """Read existing history without creating a graph or model client."""
        if self.agent is None:
            return []
        try:
            values = self.agent.get_state(self.get_work_config()).values
            messages = values.get("messages", [])
            self._status_messages = tuple(messages)
            return messages
        except Exception as e:
            warning(f"Failed to get messages from agent state: {e}")
        return []

    def messages_get_status(self):
        """Return the latest stream snapshot without acquiring graph state."""
        return list(self._status_messages)

    @staticmethod
    def _pending_tool_calls(messages):
        pending = {}
        for msg in messages:
            if isinstance(msg, AIMessage):
                for call in msg.tool_calls:
                    tool_call_id = call.get("id")
                    if not tool_call_id:
                        continue
                    pending[tool_call_id] = call.get("name") or "unknown"
            elif isinstance(msg, ToolMessage):
                pending.pop(msg.tool_call_id, None)
        return pending

    def recover_pending_tool_calls(self, error) -> int:
        pending = self._pending_tool_calls(self.messages_get_raw())
        if not pending:
            return 0
        reason = str(error).strip().splitlines()[0]
        if len(reason) > 500:
            reason = reason[:497] + "..."
        recovery_messages = [
            ToolMessage(
                content=(
                    "[ERROR] The tool call ended before producing a usable result. "
                    f"Reason: {reason or type(error).__name__}. Review the arguments "
                    "and retry."
                ),
                tool_call_id=tool_call_id,
                name=name,
                status="error",
            )
            for tool_call_id, name in pending.items()
        ]
        try:
            self.agent.update_state(
                self.get_work_config(),
                {"messages": recovery_messages},
                as_node="tools",
            )
        except Exception as recovery_error:
            warning(f"Failed to recover pending tool calls: {recovery_error}")
            return 0
        warning(f"Recovered {len(recovery_messages)} pending tool call(s).")
        return len(recovery_messages)

    def get_work_config(self):
        """Attach the session callback and optional worker correlation to every graph run."""
        work_config = {
            "configurable": {"thread_id": f"{self.vagent.thread_id}"},
            "recursion_limit": self.config.get_value("recursion_limit", 100000),
        }
        if self.vagent.langfuse_enable:
            work_config["callbacks"] = [self.vagent.langfuse_handler]
            work_config["metadata"] = {
                "langfuse_session_id": self.vagent.session_id.hex,
                **getattr(self.vagent, "langfuse_metadata", {}),
            }
            if hasattr(self.vagent, "multi_agent"):
                work_config["metadata"].update(ucagent_agent="super-agent", langfuse_tags=["super-agent"])
                work_config["run_name"] = "Super-Agent"
            elif getattr(self.vagent, "langfuse_run_name", None):
                work_config["run_name"] = self.vagent.langfuse_run_name
        return work_config

    def model_name(self):
        """Describe the selected model without preparing it for status queries."""
        if self.model is None:
            provider = self.config.get_value("model_type", "openai")
            return self.config.get_value(f"{provider}.model_name", "unconfigured")
        # ChatOpenAI stores the name as `model_name`; ChatAnthropic uses `model`.
        return getattr(self.model, "model_name", None) or getattr(self.model, "model", "unknown")

    def temperature(self):
        """Read configured temperature until a prepared model is available."""
        if self.model is None:
            provider = self.config.get_value("model_type", "openai")
            return self.config.get_value(f"{provider}.temperature", None)
        return self.model.temperature

    def get_statistics(self):
        return self.message_statistic.get_statistics()

    def token_speed(self):
        return self.cb_runtime_output.get_speed()

    def idle(self):
        return self.cb_runtime_output.get_idle()

    def token_total(self):
        usage = self.get_statistics()["provider_usage"]["all"]
        if usage["responses_with_usage"] < 1:
            return -1
        return usage["total_tokens"]

    def stream_character_speed(self):
        return self.cb_stream_output.get_speed()

    def stream_character_total(self):
        return self.cb_stream_output.total()

    def summary_stream_character_total(self):
        return self.cb_summary_stream_output.total()
