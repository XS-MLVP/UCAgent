#coding=utf-8

from .util.config import get_config
from .util.log import info
from .util.functions import fmt_time_deta, get_template_path, render_template_dir

from .tools.fileops import *
from .tools.human import *
from .stage.vstage import StageManager

import time
import random
import signal

from langchain.globals import set_debug
from langchain_openai import ChatOpenAI
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langmem.short_term import SummarizationNode
from langgraph.prebuilt.chat_agent_executor import AgentState
from typing import Any, Dict


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
        if model is not None:
            self.model = model
        else:
            self.model = ChatOpenAI(openai_api_key=self.cfg.openai.openai_api_key,
                                    openai_api_base=self.cfg.openai.openai_api_base,
                                    model=self.cfg.openai.model_name,
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
                           ] + self.stage_manager.new_tools()

        summarization_node = SummarizationNode( 
            token_counter=count_tokens_approximately,
            model=self.model,
            max_tokens=40000,
            max_summary_tokens=1000,
            output_messages_key="llm_input_messages",
        )

        self.agent = create_react_agent(
            model=self.model,
            tools=self.test_tools + (ex_tools if ex_tools is not None else []),
            checkpointer=MemorySaver(),
            pre_model_hook=summarization_node, 
            state_schema=State,
        )
        # flags
        self.invoke_round = 0
        self._is_exit = False
        self._tip_index = 0
        self._need_human_input = False
        self._evnt_human_input = False
        self.original_sigint = signal.getsignal(signal.SIGINT)
        self._sigint_count = 0
        self.handle_sigint()

    def handle_sigint(self):
        def _sigint_handler(s, f):
            self._sigint_count += 1
            if self._sigint_count > 3:
                info("SIGINT received again, exiting...")
                self.exit()
                return
            if self._sigint_count > 1:
                #self.original_sigint(s, f)
                info("SIGINT received again, more times will exit directly")
                return
            info("SIGINT received, entering human input mode")
            self.set_human_input()
        signal.signal(signal.SIGINT, _sigint_handler)

    def set_human_input(self):
        self._need_human_input = True

    def get_human_input(self):
        self._need_human_input = False
        self._evnt_human_input = True
        text = ""
        while True:
            text = input()
            try:
                text = text.strip().encode("utf-8")
            except UnicodeEncodeError:
                warning("Input contains non-UTF-8 characters, please re-enter.")
                continue
            if len(text) == 0:
                warning("Input is empty, please re-enter.")
                continue
            break
        self._sigint_count = 0
        if text.strip().lower() in ["exit", "quit"]:
            self.exit()
            return {"messages": [SystemMessage(content="Exiting the agent...")]}
        return {"messages": [HumanMessage(content=text)]}

    def get_current_tips(self):
        if self._need_human_input:
            return self.get_human_input()
        messages = self.stage_manager.get_current_tips()
        self._tip_index += 1
        assert isinstance(messages, str), "StageManager should return a str type messages"
        return {"messages": HumanMessage(content=messages)}

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
        while not self.is_exit():
            tips = self.get_current_tips()
            info("Tips: " + str(tips))
            if self.is_exit():
                break
            self.do_work(tips, self.get_work_config())
        time_end = time.time()
        info("Verify Agent finished at: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time_end)))
        info(f"Total time taken: {fmt_time_deta(time_end - time_start)}")

    def do_work(self, instructions, config):
        """Perform the work using the agent."""
        stream = self.agent.stream(instructions, config, stream_mode=["values", "messages"])
        last_msg_index = None
        last_value_output = True
        for data in stream:
            mtype, mdata = data
            if mtype == "messages":
                chunk, cfg = mdata
                if last_value_output:
                    print("\n ================================= AI Message =================================== ", flush=True)
                last_value_output = False
                print(chunk.content, end="", flush=True)
                if self._need_human_input:
                    self._evnt_human_input = False
                    print("\n\n[Human Input ]:", end="", flush=True)
                    break
            else:
                last_value_output = True
                msg_index = len(mdata["messages"])
                if last_msg_index == msg_index:
                    continue
                last_msg_index = msg_index
                msg = mdata["messages"][-1]
                if not isinstance(msg, AIMessage):
                    print(f"\n\n[MIndex: {msg_index} start]\n",
                          msg.pretty_repr(),
                          f"\n[MIndex: {msg_index} end]\n\n", flush=True)
        self.invoke_round += 1
