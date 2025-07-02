#coding=utf-8

from .util.config import get_config
from .util.log import info, message, warning, error, msg_msg
from .util.functions import fmt_time_deta, get_template_path, render_template_dir, import_and_instance_tools
from .util.functions import fill_dlist_none, dump_as_json, get_ai_message_tool_call
from .util.functions import start_verify_mcps, create_verify_mcps, stop_verify_mcps, rm_workspace_prefix

import vagent.tools
from .tools import *
from .stage.vstage import StageManager
from .verify_pdb import VerifyPDB

import time
import random
import signal
import copy

from langchain.globals import set_debug
from langchain_openai import ChatOpenAI
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langmem.short_term import SummarizationNode
from langgraph.prebuilt.chat_agent_executor import AgentState
from typing import Any


class SummarizationAndFixToolCall(SummarizationNode):
    def _func(self, input: dict[str, Any] | BaseModel) -> dict[str, Any]:
        for msg in input["messages"][-4:]:
            if not isinstance(msg, AIMessage):
                continue
            if hasattr(msg, "additional_kwargs"):
                msg.additional_kwargs = fill_dlist_none(msg.additional_kwargs, '{}', "arguments", ["arguments"])
            if hasattr(msg, "invalid_tool_calls"):
                msg.invalid_tool_calls = fill_dlist_none(msg.invalid_tool_calls, '{}', "args", ["args"])
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
                 init_cmd=None,
                 seed=None,
                 sys_tips="",
                 model=None,
                 ex_tools=None,
                 thread_id=None,
                 debug=False,
                 no_embed_tools=False,
                 force_stage_index=0,
                 no_write_targets=None
                 ):
        """Initialize the Verify Agent with configuration and an optional agent.

        Args:
            workspace (str): The workspace directory where the agent will operate.
            dut_name (str): The name of the device under test (DUT).
            output (str): The output directory for the agent's results.
            config_file (str, optional): Path to the configuration file. Defaults to None.
            cfg_override (dict, optional): Dictionary to override configuration settings. Defaults to None.
            tmp_overwrite (bool, optional): Whether to overwrite existing templates in the workspace. Defaults to False.
            template_dir (str, optional): Path to the template directory. Defaults to None.
            stream_output (bool, optional): Whether to stream output to the console. Defaults to False.
            init_cmd (list, optional): Initial commands to run in the agent. Defaults to None.
            seed (int, optional): Seed for random number generation. Defaults to None.
            sys_tips (str, optional): Set of system tips to be used in the agent.
                                      Defaults to an empty string.
            model (ChatOpenAI, optional): An instance of ChatOpenAI to use as the agent model.
                                          If None, a default model will be created using the configuration.
                                          Defaults to None.
            ex_tools (list, optional): List of external tools class to be used by the agent, e.g., `--ex-tools SqThink`.
                                       Defaults to None.
            thread_id (int, optional): Thread ID for the agent. If None, a random ID will be generated.
                                       Defaults to None.
            debug (bool, optional): Whether to enable debug mode. Defaults to False.
        """
        if debug:
            set_debug(True)
        self.cfg = get_config(config_file, cfg_override)
        self.cfg.update_template({
            "OUT": output,
            "DUT": dut_name
        })
        self.thread_id = thread_id if thread_id is not None else random.randint(100000, 999999)
        self.dut_name = dut_name
        self.seed = seed if seed is not None else random.randint(1, 999999)
        if model is not None:
            self.model = model
        else:
            self.model = ChatOpenAI(openai_api_key=self.cfg.openai.openai_api_key,
                                    openai_api_base=self.cfg.openai.openai_api_base,
                                    model=self.cfg.openai.model_name,
                                    seed=self.seed,
                                    )
        self.workspace = os.path.abspath(workspace)
        self.output_dir = os.path.join(self.workspace, output)
        self.template = get_template_path(self.cfg.template, template_dir)
        self.render_template(tmp_overwrite=tmp_overwrite)
        self.tool_read_text = ReadTextFile(self.workspace)
        self.stage_manager = StageManager(self.workspace, self.cfg, self, self.tool_read_text, force_stage_index)
        self.tool_list_base = [
            self.tool_read_text
        ]
        if not no_embed_tools:
            self.tool_reference = SearchInGuidDoc(self.cfg.embed, workspace=self.workspace, doc_path="Guide_Doc")
            self.tool_memory_put = MemoryPut().set_store(self.cfg.embed)
            self.tool_memory_get = MemoryGet().set_store(store=self.tool_memory_put.get_store())
            self.tool_list_base += [
                self.tool_reference,
                self.tool_memory_put,
                self.tool_memory_get,
            ]
        if no_write_targets is not None:
            assert isinstance(no_write_targets, list), "no_write_targets must be a list of directories or files"
            for f in no_write_targets:
                abs_f = os.path.abspath(f)
                assert os.path.exists(abs_f), f"Specified no-write target {abs_f} does not exist"
                assert abs_f.startswith(os.path.abspath(self.workspace)), \
                    f"Specified no-write target {abs_f} must be under the workspace {self.workspace}"
                self.cfg.un_write_dirs.append(rm_workspace_prefix(self.workspace, abs_f))
        self.tool_list_file = [
                           PathList(self.workspace),
                           ReadBinFile(self.workspace),
                           DeleteFile(self.workspace,             write_dirs=self.cfg.write_dirs, un_write_dirs=self.cfg.un_write_dirs),
                           TextFileReplace(self.workspace,        write_dirs=self.cfg.write_dirs, un_write_dirs=self.cfg.un_write_dirs),
                           TextFileMultiReplace(self.workspace,   write_dirs=self.cfg.write_dirs, un_write_dirs=self.cfg.un_write_dirs),
                           WriteToFile(self.workspace,            write_dirs=self.cfg.write_dirs, un_write_dirs=self.cfg.un_write_dirs),
                           AppendToFile(self.workspace,           write_dirs=self.cfg.write_dirs, un_write_dirs=self.cfg.un_write_dirs),
        ]
        self.tool_list_task = self.stage_manager.new_tools()
        self.tool_list_ext = import_and_instance_tools(self.cfg.get_value("ex_tools", []), vagent.tools) \
                           + import_and_instance_tools(ex_tools, vagent.tools)
        self.test_tools = self.tool_list_base + self.tool_list_file + self.tool_list_task + self.tool_list_ext

        summarization_node = SummarizationAndFixToolCall(
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
        self.message_echo_handler = None
        self.update_handler = None
        self._time_start = time.time()
        self._time_end = None
        # state
        self._msg_buffer = ""
        self._system_message = sys_tips
        self._stat_msg_count_ai = 0
        self._stat_msg_count_tool = 0
        self._stat_msg_count_system = 0
        # flags
        self.stream_output = stream_output
        self.invoke_round = 0
        self._tool__call_error = []
        self._is_exit = False
        self._tip_index = 0
        self._need_break = False
        self._force_trace = False
        self._continue_msg = None
        self._mcps = None
        self._mcps_logger = None
        self.original_sigint = signal.getsignal(signal.SIGINT)
        self._sigint_count = 0
        self.handle_sigint()
        self.pdb = VerifyPDB(self, init_cmd=init_cmd)

    def render_template(self, tmp_overwrite=False):
        if self.template is not None:
            tmp_dir = os.path.join(self.workspace, os.path.basename(self.template))
            if not os.path.exists(tmp_dir) or tmp_overwrite:
                render_template_dir(self.workspace, self.template, {"DUT": self.dut_name})

    def start_mcps(self, no_file_ops=False, host="127.0.0.1", port=5000):
        tools = self.tool_list_base + self.tool_list_task + self.tool_list_ext
        if not no_file_ops:
            tools += self.tool_list_file
        self.cfg.update_template({
            "TOOLS": ", ".join([t.name for t in tools]),
        })
        self._mcps, glogger = create_verify_mcps(tools, host=host, port=port, logger=self._mcps_logger)
        info("Init Prompt:\n" + self.cfg.mcp_server.init_prompt)
        start_verify_mcps(self._mcps, glogger)
        self._mcps = None

    def stop_mcps(self):
        """Stop the MCPs server if it is running."""
        stop_verify_mcps(self._mcps)

    def set_message_echo_handler(self, handler):
        """Set a custom message echo handler to process messages."""
        if not callable(handler):
            raise ValueError("Message echo handler must be callable")
        self.message_echo_handler = handler

    def unset_message_echo_handler(self):
        """Unset the custom message echo handler."""
        self.message_echo_handler = None

    def message_echo(self, msg, end="\n"):
        """Echo a message using the custom message echo handler if set."""
        if self.message_echo_handler is not None:
            self.message_echo_handler(msg, end)
            if msg:
                self._msg_buffer = self._msg_buffer + msg + end
            if end == "\n":
                msg_msg(self._msg_buffer)
                self._msg_buffer = ""
        else:
            message(msg, end=end)

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
            info("SIGINT received")
            self.set_break(True)
        signal.signal(signal.SIGINT, _sigint_handler)

    def set_force_trace(self, value):
        self._force_trace = value

    def check_pdb_trace(self):
        if self._force_trace:
            self.pdb.set_trace()
        elif self.is_break():
            self.pdb.set_trace()

    def set_break(self, value=True):
        self._need_break = value
        if value and self._mcps is not None:
            self.stop_mcps()

    def is_break(self):
        return self._need_break

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

    def set_system_message(self, msg: str):
        self._system_message = msg

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
        if self._is_exit:
            info("Verify Agent is exited.")
        return self._is_exit

    def exit(self):
        self._is_exit = True

    def get_work_config(self):
        return {"configurable": {"thread_id": f"{self.thread_id}"},
                "recursion_limit": self.cfg.get_value("recursion_limit", 100000),
                }

    def run(self):
        self.pre_run()
        self.run_loop()

    def pre_run(self):
        time_start = self._time_start = time.time()
        info("Verify Agent started at: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time_start)))
        info("Seed: " + str(self.seed))
        self.check_pdb_trace()
        return self

    def run_loop(self, with_break=False, msg=None):
        if msg:
            self.set_continue_msg(msg)
        while not self.is_exit():
            self.one_loop()
            if self.is_exit():
                break
            if with_break:
                if self.is_break():
                    info("Break at loop: " + str(self.invoke_round))
                    return
            self.check_pdb_trace()
        time_end = self._time_end = time.time()
        info("Verify Agent finished at: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time_end)))
        info(f"Total time taken: {fmt_time_deta(time_end - self._time_start)}")
        return self

    def one_loop(self, msg=None):
        if msg:
            self.set_continue_msg(msg)
        while True:
            tips = self.get_current_tips()
            if self.is_exit():
                return
            self.do_work(tips, self.get_work_config())
            if not self._tool__call_error:
                break
            if self.is_break():
                return
        self.invoke_round += 1
        return self

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

    def get_messages(self):
        """Get the messages from the agent's state."""
        values = self.agent.get_state(self.get_work_config()).values
        return values.get("messages", []) if values else []

    def pop_message(self, index):
        # FIXME
        values = self.agent.get_state(self.get_work_config()).values
        if "messages" not in values or index < 0 or index >= len(values["messages"]):
            warning(f"Invalid index {index} for messages, cannot pop message")
            return
        values["messages"].pop(index)
        info(f"Popped message at index {index}, remaining messages: {len(values['messages'])}")

    def do_work_values(self, instructions, config):
        last_msg_index = None
        for _, step in self.agent.stream(instructions, config, stream_mode=["values"]):
            if self._need_break:
                break
            index = len(step["messages"])
            if index == last_msg_index:
                continue
            last_msg_index = index
            msg = step["messages"][-1]
            self.check_tool_call_error(msg)
            self.state_record_mesg(msg)
            self.message_echo(msg.pretty_repr())

    def do_work_stream(self, instructions, config):
        last_msg_index = None
        fist_ai_message = True
        for v, data in self.agent.stream(instructions, config, stream_mode=["values", "messages"]):
            if self._need_break:
                    break
            if v == "messages":
                if fist_ai_message:
                    fist_ai_message = False
                    self.message_echo("\n\n================================== AI Message ==================================")
                msg = data[0]
                self.message_echo(msg.content, end="")
            else:
                index = len(data["messages"])
                if index == last_msg_index:
                    continue
                last_msg_index = index
                msg = data["messages"][-1]
                self.state_record_mesg(msg)
                if isinstance(msg, AIMessage):
                    self.message_echo(get_ai_message_tool_call(msg))
                    self.check_tool_call_error(msg)
                    continue
                self.message_echo("\n"+msg.pretty_repr())

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
