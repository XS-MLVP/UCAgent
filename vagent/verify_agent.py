#coding=utf-8

from .util.config import get_config
from .util.log import info, message, warning, error
from .util.functions import fmt_time_deta, get_template_path, render_template_dir, append_time_str
from .util.functions import fill_dlist_none, dump_as_json, get_ai_message_tool_call

from .tools.fileops import *
from .tools.human import *
from .stage.vstage import StageManager
from .verify_pdb import VerifyPDB

import time
import random
import signal
import openai
import copy

from langchain.globals import set_debug
from langchain_openai import ChatOpenAI
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langmem.short_term import SummarizationNode
from langgraph.prebuilt.chat_agent_executor import AgentState
from typing import Any, Dict


class SummarizationAndIgnoreNoneNode(SummarizationNode):
    def _func(self, input: dict[str, Any] | BaseModel) -> dict[str, Any]:
        for msg in input["messages"][-4:]:
            if not isinstance(msg, AIMessage):
                continue
            if hasattr(msg, "additional_kwargs"):
                msg.additional_kwargs = fill_dlist_none(msg.additional_kwargs, '{}', "arguments")
            if hasattr(msg, "invalid_tool_calls"):
                msg.invalid_tool_calls = fill_dlist_none(msg.invalid_tool_calls, '{}', "args")
        return super()._func(input)


class State(AgentState):
    # NOTE: we're adding this key to keep track of previous summary information
    # to make sure we're not summarizing on every LLM call
    context: dict[str, Any] 


class VerifyAgent(object):

    def __init__(self, workspace, dut_name, output,
                 config_file=None,
                 cfg_override=None,
                 tmp_overwrite=False,
                 template_dir=None,
                 stream_output=False,
                 seed = None,
                 model=None,
                 ex_tools=None,
                 thread_id=None):
        """Initialize the Verify Agent with configuration and an optional agent.

        Args:
            config_file (str): Path to the configuration file.
            cfg_override (dict): Dictionary to override configuration settings.
            agent (VLLMOpenAI, optional): An instance of VLLMOpenAI. If not provided, a new instance will be created using the configuration.
            ex_tools (list, optional): Extern list of tools to be used by the agent. 
        """
        #set_debug(True)
        self.cfg = get_config(config_file, cfg_override)
        self.cfg.update_template({
            "OUT": output,
            "DUT": dut_name
        })
        self.thread_id = thread_id if thread_id is not None else random.randint(100000, 999999)
        self.seed = seed if seed is not None else random.randint(1, 999999)
        if model is not None:
            self.model = model
        else:
            self.model = ChatOpenAI(openai_api_key=self.cfg.openai.openai_api_key,
                                    openai_api_base=self.cfg.openai.openai_api_base,
                                    model=self.cfg.openai.model_name,
                                    seed=42,
                                    )
        self.workspace = os.path.abspath(workspace)
        template = get_template_path(self.cfg.template, template_dir)
        if template is not None:
            tmep_dir = os.path.join(self.workspace, os.path.basename(template))
            if not os.path.exists(tmep_dir) or tmp_overwrite:
                render_template_dir(self.workspace, template, {"DUT": dut_name})
        self.tool_read_text = ReadTextFile(self.workspace)
        self.stage_manager = StageManager(self.workspace, self.cfg, self, self.tool_read_text)
        self.test_tools = [# file operations
                           # read:
                           PathList(self.workspace),
                           ReadBinFile(self.workspace),
                           DeleteFile(self.workspace,             write_dirs=self.cfg.write_dirs, un_write_dirs=self.cfg.un_write_dirs),
                           self.tool_read_text,
                           # write:
                           TextFileReplaceLines(self.workspace,   write_dirs=self.cfg.write_dirs, un_write_dirs=self.cfg.un_write_dirs),
                           TextFileMultiLinesEdit(self.workspace, write_dirs=self.cfg.write_dirs, un_write_dirs=self.cfg.un_write_dirs),
                           WriteToFile(self.workspace,            write_dirs=self.cfg.write_dirs, un_write_dirs=self.cfg.un_write_dirs),
                           AppendToFile(self.workspace,           write_dirs=self.cfg.write_dirs, un_write_dirs=self.cfg.un_write_dirs),
                           # test:
                           # ...
                           # HumanHelp(),
                           ] + self.stage_manager.new_tools() + (ex_tools if ex_tools is not None else [])

        summarization_node = SummarizationAndIgnoreNoneNode(
            token_counter=count_tokens_approximately,
            model=self.model,
            max_tokens=self.cfg.get_value("max_tokens", 3000),
            max_summary_tokens=self.cfg.get_value("max_summary_tokens", 1000),
            output_messages_key="llm_input_messages",
        )

        self.agent = create_react_agent(
            model=self.model,
            tools=self.test_tools,
            checkpointer=MemorySaver(),
            pre_model_hook=summarization_node,
            state_schema=State,
        )
        # state
        self._system_message = ""
        self._stat_msg_count_ai = 0
        self._stat_msg_count_tool = 0
        self._stat_msg_count_system = 0
        # flags
        self.stream_output = stream_output
        self.invoke_round = 0
        self._tool__call_error = []
        self._is_exit = False
        self._tip_index = 0
        self._need_human_input = False
        self._force_trace = False
        self._continue_msg = None
        self.original_sigint = signal.getsignal(signal.SIGINT)
        self._sigint_count = 0
        self.handle_sigint()
        self.pdb = VerifyPDB(self)

    def handle_sigint(self):
        def _sigint_handler(s, f):
            self._sigint_count += 1
            if self._sigint_count > 4:
                return self.original_sigint(s, f)
            if self._sigint_count > 3:
                info("SIGINT received again, exiting...")
                self.exit()
                return
            if self._sigint_count > 1:
                #self.original_sigint(s, f)
                info("SIGINT received again, more times will exit directly")
                return
            info("SIGINT received, entering human input mode")
            self.set_human_input(True)
        signal.signal(signal.SIGINT, _sigint_handler)

    def set_force_trace(self, value):
        self._force_trace = value

    def check_pdb_trace(self):
        if self._force_trace:
            self.pdb.set_trace()
        elif self.is_human_input():
            self.pdb.set_trace()

    def set_human_input(self, value=True):
        self._need_human_input = value

    def is_human_input(self):
        return self._need_human_input

    def get_current_tips(self):
        if self._tool__call_error:
            return {"messages": copy.deepcopy(self._tool__call_error)}
        tips = self._continue_msg
        if self._continue_msg is None:
            tips = self.stage_manager.get_current_tips()
        else:
            self._continue_msg = None
        self._tip_index += 1
        assert isinstance(tips, str), "StageManager should return a str type tips"
        msg = []
        if self._system_message:
            msg.append(SystemMessage(content=self._system_message))
        msg.append(HumanMessage(content=tips))
        return {"messages": msg}

    def set_continue_msg(self, msg: str):
        """Set the continue message for the agent."""
        if not isinstance(msg, str):
            raise ValueError("Continue message must be a string")
        try:
            msg.encode("utf-8").decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("Continue message must be a valid UTF-8 string")
        self._continue_msg = msg

    def is_exit(self):
        return self._is_exit

    def exit(self):
        self._is_exit = True

    def get_work_config(self):
        return {"configurable": {"thread_id": f"{self.thread_id}"},
                "recursion_limit": self.cfg.get_value("recursion_limit", 100000),
                }

    def run(self):
        time_start = time.time()
        info("Verify Agent started at: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time_start)))
        info("Seed: " + str(self.seed))
        self.check_pdb_trace()
        while not self.is_exit():
            tips = self.get_current_tips()
            if self.is_exit():
                break
            self.do_work(tips, self.get_work_config())
            self.check_pdb_trace()
        time_end = time.time()
        info("Verify Agent finished at: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time_end)))
        info(f"Total time taken: {fmt_time_deta(time_end - time_start)}")

    def do_work(self, instructions, config):
        """Perform the work using the agent."""
        self._tool__call_error = []
        if self.stream_output:
            self.do_work_stream(instructions, config)
        else:
            self.do_work_values(instructions, config)

    def state_record_mesg(self, msg):
        if isinstance(msg, AIMessage):
            self._stat_msg_count_ai += 1
        elif isinstance(msg, ToolMessage):
            self._stat_msg_count_tool += 1
        elif isinstance(msg, SystemMessage):
            self._stat_msg_count_system += 1

    def do_work_values(self, instructions, config):
        last_msg_index = None
        for _, step in self.agent.stream(instructions, config, stream_mode=["values"]):
            index = len(step["messages"])
            if index == last_msg_index:
                continue
            last_msg_index = index
            msg = step["messages"][-1]
            self.check_tool_call_error(msg)
            self.state_record_mesg(msg)
            message(msg.pretty_repr())
            if self._need_human_input:
                break

    def do_work_stream(self, instructions, config):
        last_msg_index = None
        fist_ai_message = True
        for v, data in self.agent.stream(instructions, config, stream_mode=["values", "messages"]):
            if v == "messages":
                if fist_ai_message:
                    fist_ai_message = False
                    message("\n\n================================== AI Message ==================================")
                msg = data[0]
                message(msg.content, end="")
                if self._need_human_input:
                    break
            else:
                index = len(data["messages"])
                if index == last_msg_index:
                    continue
                last_msg_index = index
                msg = data["messages"][-1]
                self.state_record_mesg(msg)
                if isinstance(msg, AIMessage):
                    message(get_ai_message_tool_call(msg))
                    self.check_tool_call_error(msg)
                    continue
                message(msg.pretty_repr())

    def check_tool_call_error(self, msg):
        if not isinstance(msg, AIMessage):
            return
        if not hasattr(msg, "invalid_tool_calls"):
            return
        if len(msg.invalid_tool_calls) < 1:
            return
        for call in msg.invalid_tool_calls:
            name = call.get("name")
            tool = next((tool for tool in self.test_tools if tool.name == name), None)
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
            self._tool__call_error.append(ToolMessage(
                content=result,
                tool_call_id=call["id"],
                name=name,
                status=status
            ))
        warning(f"Tool call error: {msg.invalid_tool_calls}, have re-called them in custom way")
