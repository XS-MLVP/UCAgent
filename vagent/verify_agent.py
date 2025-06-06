#coding=utf-8

from .util.config import get_config
from .util.log import info
from .util.functions import fmt_time_deta

from .tools.fileops import *
from .stage.vstage import StageManager

import time
import random

from langchain.globals import set_debug
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, SystemMessage


class VerifyAgent(object):

    def __init__(self, workspace, dut_name, output,
                 config_file=None,
                 cfg_override=None,
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
        self.stage_manager = StageManager(self.workspace, self.cfg, self)
        self.test_tools = [# file operations
                           # read:
                           PathList(self.workspace),
                           ReadBinFile(self.workspace),
                           ReadTextFile(self.workspace),
                           # write:
                           TextFileReplaceLines(self.workspace),
                           TextFileMultiLinesEdit(self.workspace),
                           WriteToFile(self.workspace),
                           AppendToFile(self.workspace),
                           # test:
                           # ...
                           ] + self.stage_manager.new_tools()
        self.agent = create_react_agent(
            model=self.model,
            tools=self.test_tools + (ex_tools if ex_tools is not None else []),
            checkpointer=MemorySaver()
        )
        self._is_exit = False
        self._tip_index = 0

    def get_current_tips(self):
        messages = self.stage_manager.get_current_tips()
        self._tip_index += 1
        return {"messages": messages}

    def is_exit(self):
        return self._is_exit

    def exit(self):
        self._is_exit = True

    def get_work_config(self):
        return {"configurable": {"thread_id": f"{self.thread_id}"}}

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
        stream = self.agent.stream(instructions, config, stream_mode="values")
        for step in stream:
            step["messages"][-1].pretty_print()
