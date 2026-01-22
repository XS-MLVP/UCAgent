#coding=utf-8

from ucagent.abackend.base import AgentBackendBase
from ucagent.util.log import info, warning, error
from .middleware import MessageStatistic, TokenSpeedCallbackHandler, SummarizationMiddleware, SummarizationAndFixToolCall, State
from langchain_core.messages.utils import count_tokens_approximately
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver
from ucagent.util.models import get_chat_model
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from ucagent.util.functions import dump_as_json, get_ai_message_tool_call


class UCAgentLangChainBackend(AgentBackendBase):
    """
    LangChain-based agent backend implementation.
    """

    def __init__(self, vagent, config, **kwargs):
        super().__init__(vagent, config, **kwargs)
        self.message_statistic = MessageStatistic()
        self.cb_token_speed = TokenSpeedCallbackHandler()
        self.model = get_chat_model(self.config, [self.cb_token_speed] if vagent.stream_output else None)
        self.sumary_model = get_chat_model(self.config, [self.cb_token_speed] if vagent.stream_output else None)

        message_manage_node = SummarizationMiddleware(
            msg_stat=self.message_statistic,
            max_summary_tokens=vagent.max_summary_tokens,
            max_keep_msgs=vagent.max_keep_msgs,
            max_tokens=vagent.max_token,
            tail_keep_msgs=vagent.cfg.get_value("conversation_summary.tail_keep_msgs", 20),
            model=self.sumary_model
        )
        self.message_manage_node = message_manage_node

    def set_debug(self, debug):
        from langchain_core.globals import set_debug
        set_debug(debug)

    def init(self):
        self.agent = create_agent(
            model=self.model,
            tools=self.vagent.test_tools,
            checkpointer=MemorySaver(),
            middleware=[self.message_manage_node]
        )

    def get_human_message(self, text):
        return HumanMessage(content=text)

    def get_system_message(self, text):
        return SystemMessage(content=text)

    def state_record_mesg(self, msg):
        if isinstance(msg, AIMessage):
            self._stat_msg_count_ai += 1
        elif isinstance(msg, ToolMessage):
            self._stat_msg_count_tool += 1
        elif isinstance(msg, SystemMessage):
            self._stat_msg_count_system += 1
        self.message_statistic.update_message(msg)

    def get_message_manage_node(self):
        return self.message_manage_node

    def do_work_stream(self, instructions, config):
        last_msg_index = None
        fist_ai_message = True
        for v, data in self.agent.stream(instructions, config, stream_mode=["values", "messages"]):
            if self.vagent.is_break():
                    break
            if v == "messages":
                if fist_ai_message:
                    fist_ai_message = False
                    self.vagent.message_echo("\n\n================================== AI Message ==================================")
                msg = data[0]
                self.vagent.message_echo(msg.content, end="")
            else:
                index = len(data["messages"])
                if index == last_msg_index:
                    continue
                last_msg_index = index
                msg = data["messages"][-1]
                self.state_record_mesg(msg)
                if isinstance(msg, AIMessage):
                    self.vagent.message_echo(get_ai_message_tool_call(msg))
                    self.check_tool_call_error(msg)
                    continue
                self.vagent.message_echo("\n"+msg.pretty_repr())

    def do_work_values(self, instructions, config):
        last_msg_index = None
        for _, step in self.agent.stream(instructions, config, stream_mode=["values"]):
            if self.vagent.is_break():
                break
            index = len(step["messages"])
            if index == last_msg_index:
                continue
            last_msg_index = index
            msg = step["messages"][-1]
            self.check_tool_call_error(msg)
            self.state_record_mesg(msg)
            self.vagent.message_echo(msg.pretty_repr())

    def check_tool_call_error(self, msg):
        if not isinstance(msg, AIMessage):
            return
        if not hasattr(msg, "invalid_tool_calls"):
            return
        if len(msg.invalid_tool_calls) < 1:
            return
        for call in msg.invalid_tool_calls:
            name = call.get("name")
            tool = next((tool for tool in self.vagent.test_tools if tool.name == name), None)
            args = call.get("args") or {}
            status = "success"
            try:
                assert tool is not None, f"Tool {name} not found"
                result = tool._run(*(), **args)
            except Exception as e:
               error(f"Error executing tool {call}: {e}")
               result = str(e)
               status = "error"
            if not isinstance(result, str):
                result = dump_as_json(result)
            self.vagent._tool__call_error.append(ToolMessage(
                content=result,
                tool_call_id=call["id"],
                name=name,
                status=status
            ))
        warning(f"Tool call error: {msg.invalid_tool_calls}, have re-called them in custom way")

    def messages_get_raw(self):
        try:
            values = self.agent.get_state(self.get_work_config()).values
            return values.get("messages", [])
        except Exception as e:
            warning(f"Failed to get messages from agent state: {e}")
        return []

    def get_work_config(self):
        work_config = {
            "configurable": {"thread_id": f"{self.vagent.thread_id}"},
            "recursion_limit": self.config.get_value("recursion_limit", 100000),
        }
        if self.vagent.langfuse_enable:
            work_config["callbacks"] = [self.vagent.langfuse_handler]
            work_config["metadata"] = {
                # "langfuse_user_id": "user_id",
                "langfuse_session_id": self.vagent.session_id.hex,
                # "langfuse_tags": ["some-tag",]
            }
        return work_config

    def model_name(self):
        return self.model.model_name

    def temperature(self):
        return self.model.temperature

    def get_statistics(self):
        return self.message_statistic.get_statistics()

    def token_speed(self):
        return self.cb_token_speed.get_speed()

    def token_total(self):
        return self.cb_token_speed.total()
