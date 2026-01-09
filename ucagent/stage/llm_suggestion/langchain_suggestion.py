#coding=utf-8

from ucagent.stage.llm_suggestion.base_suggestion import BaseLLMSuggestion
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from ucagent.util.functions import make_llm_tool_ret


class OpenAILLMSuggestion(BaseLLMSuggestion):

    def __init__(self, model_name,
                 openai_api_key,
                 openai_api_base,
                 ignore_labels: list = [("<think>", "</think>")],
                 use_inspect_tool: bool = True,
                 min_fail_count: int = 3,
                 **kwargs):
        self.model_name = model_name
        self.openai_api_key = openai_api_key
        self.openai_api_base = openai_api_base
        self.ignore_labels = ignore_labels
        self.use_inspect_tool = use_inspect_tool
        self.min_fail_count = min_fail_count
        self.llm = ChatOpenAI(model_name=self.model_name,
                              openai_api_key=self.openai_api_key,
                              openai_api_base=self.openai_api_base,
                              **kwargs)
        self.agent = None

    def bind_tools(self, tools: list):
        if tools and self.use_inspect_tool:
            self.agent = create_agent(self.llm,
                                      tools=tools)
        return self

    def suggest(self, prompts: list, fail_count:int) -> str:
        if fail_count < self.min_fail_count:
            return prompts[2]  # return error_str directly
        # system prompt + current_task + error_str
        user_text = "Task Information:\n" + make_llm_tool_ret(prompts[1]) + \
                    "Error Information:\n" + make_llm_tool_ret(prompts[2]) + \
                    "\n\nplease provide your suggestions based on the above information."
        messages = [
            ("system", prompts[0]),
            ("user", user_text),
        ]
        if self.agent:
            result = self.agent.invoke({"messages":messages})
            sg_msg = result['messages'][-1].text
        else:
            sg_msg = self.llm.invoke(messages).text
        return self._remove_ignore_labels(sg_msg)

    def _remove_ignore_labels(self, text: str) -> str:
        for start_label, end_label in self.ignore_labels:
            while True:
                start_idx = text.find(start_label)
                end_idx = text.find(end_label, start_idx + len(start_label))
                if start_idx != -1 and end_idx != -1:
                    text = text[:start_idx] + text[end_idx + len(end_label):]
                else:
                    break
        return text
