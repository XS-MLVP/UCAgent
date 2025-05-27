#coding=utf-8

from .util.config import get_config
from .util.log import info
from .util.functions import fmt_time_deta

from .tools.fileops import get_weather

import time

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent


class VerifyAgent(object):

    def __init__(self, config_file=None, cfg_override=None, model=None, ex_tools=None):
        """Initialize the Verify Agent with configuration and an optional agent.

        Args:
            config_file (str): Path to the configuration file.
            cfg_override (dict): Dictionary to override configuration settings.
            agent (VLLMOpenAI, optional): An instance of VLLMOpenAI. If not provided, a new instance will be created using the configuration.
            ex_tools (list, optional): Extern list of tools to be used by the agent. 
        """
        self.cfg = get_config(config_file, cfg_override)
        if model is not None:
            self.model = model
        else:
            self.model = ChatOpenAI(openai_api_key=self.cfg.openai.openai_api_key,
                                    openai_api_base=self.cfg.openai.openai_api_base,
                                    model=self.cfg.openai.model_name,
                                    )
        self.test_tools = [get_weather]
        self.agent = create_react_agent(
            model=self.model,
            tools=self.test_tools + (ex_tools if ex_tools is not None else []),
        )
        self._is_exit = False
        self._tip_index = 0

    def get_tool_list(self):
        pass

    def get_stage_list(self):
        pass

    def get_stage_current(self):
        pass

    def stage_next(self):
        self._is_exit = True

    def get_current_tips(self):
        self._tip_index += 1
        return {"messages": [{"role": "user", "content": "what is the weather in sf?"}]}

    def is_exit(self):
        return self._is_exit

    def exit(self):
        self._is_exit = True

    def run(self):
        time_start = time.time()
        info("Verify Agent started at: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time_start)))
        while not self.is_exit():
            tips = self.get_current_tips()
            info("Tips: " + str(tips))
            rsp = self.agent.invoke(tips)
            info("Response: " + str(rsp))
            self.stage_next()
        time_end = time.time()
        info("Verify Agent finished at: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time_end)))
        info(f"Total time taken: {fmt_time_deta(time_end - time_start)}")
