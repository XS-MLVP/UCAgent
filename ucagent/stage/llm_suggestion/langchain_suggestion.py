#coding=utf-8

from ucagent.stage.llm_suggestion.base_suggestion import BaseLLMSuggestion
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from ucagent.stage.vstage import VerifyStage
from ucagent.util.functions import make_llm_tool_ret
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import RemoveMessage
from langgraph.runtime import Runtime
from langchain.agents.middleware.types import AgentState
from typing import Any
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.checkpoint.memory import MemorySaver
from collections import OrderedDict


class KeepFirstSummarizationMiddleware(SummarizationMiddleware):
    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:  # noqa: ARG002
        """Process messages before model invocation, potentially triggering summarization."""
        messages = state["messages"]
        self._ensure_message_ids(messages)
        total_tokens = self.token_counter(messages)
        if (
            self.max_tokens_before_summary is not None
            and total_tokens < self.max_tokens_before_summary
        ):
            return None

        cutoff_index = self._find_safe_cutoff(messages)

        if cutoff_index <= 0:
            return None

        messages_to_summarize, preserved_messages = self._partition_messages(messages, cutoff_index)

        summary = self._create_summary(messages_to_summarize)
        new_messages = self._build_new_messages(summary)

        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                messages_to_summarize[0],  # keep the very first message
                *new_messages,
                *preserved_messages,
            ]
        }

class OpenAILLMFailSuggestion(BaseLLMSuggestion):

    def __init__(self, model_name,
                 openai_api_key,
                 openai_api_base,
                 ignore_labels: list = [("<think>", "</think>")],
                 use_inspect_tool: bool = True,
                 min_fail_count: int = 3,
                 summary_trigger_tokens: int = 32*1024,
                 summary_keep_messages: int = 10,
                 **kwargs):
        self.model_name = model_name
        self.openai_api_key = openai_api_key
        self.openai_api_base = openai_api_base
        self.ignore_labels = ignore_labels
        self.use_inspect_tool = use_inspect_tool
        self.min_fail_count = min_fail_count
        self.summary_trigger_tokens = summary_trigger_tokens
        self.summary_keep_messages = summary_keep_messages
        self.llm = ChatOpenAI(model_name=self.model_name,
                              openai_api_key=self.openai_api_key,
                              openai_api_base=self.openai_api_base,
                              **kwargs)
        self.agent = None
        self.mem_saver = MemorySaver()
        self.current_vstage = None
        self.system_prompt = None
        self.suggestion_prompt = "Extract key details from the test information above (such as critical errors or important prompts) and present them to the tester."

    def bind_tools(self, tools: list,
                   system_prompt: str,
                   suggestion_prompt: str):  # return self
        self.system_prompt = system_prompt
        self.suggestion_prompt = suggestion_prompt
        if tools and self.use_inspect_tool:
            self.agent = create_agent(self.llm,
                                      tools=tools,
                                      middleware=[
                                            KeepFirstSummarizationMiddleware(
                                              model=self.llm,
                                              max_tokens_before_summary=self.summary_trigger_tokens,
                                              messages_to_keep=self.summary_keep_messages,
                                            ),
                                      ],
                                      system_prompt=system_prompt,
                                      checkpointer=self.mem_saver,
                                    )
        return self

    def get_work_cfg(self):
        return {"configurable": {"thread_id": self.get_thread_id()}}

    def get_thread_id(self):
        return f"suggestion_agent_{id(self)}"

    def suggest(self, prompts: list, vstage: VerifyStage) -> str:
        if vstage.continue_fail_count < self.min_fail_count:
            return prompts[1]  # return test_info directly
        if self.current_vstage != vstage and self.current_vstage is not None:
            if self.agent:
                self.mem_saver.delete_thread(self.get_thread_id())
        self.current_vstage = vstage
        # current_task + test_info
        user_text = "Task Information:\n<task>\n" + make_llm_tool_ret(prompts[0]) + \
                    "\n</task>\n\nTest Information:\n<report>\n" + make_llm_tool_ret(prompts[1]) + \
                    "\n</report>\n\n" + \
                    self.suggestion_prompt
        messages = [
            ("system", self.system_prompt),
            ("user", user_text),
        ]
        if self.agent:
            result = self.agent.invoke({"messages": messages},
                                       config=self.get_work_cfg())
            sg_msg = result['messages'][-1].text
        else:
            sg_msg = self.llm.invoke(messages).text
        sg_msg = self._remove_ignore_labels(sg_msg)
        ret_text = ""
        err_data = self.get_uc_raw_error(prompts[1])
        if err_data:
            ret_text += f"Check_Fail_Message:\n{make_llm_tool_ret(err_data)}\n"
        ret_text += f"Assistant_Suggestion:\n{sg_msg}\n"
        return ret_text

    def get_uc_raw_error(self, data, main_key="check_info", key="last_msg.error"):
        d_list = data.get(main_key, [])
        if not d_list:
            return None
        if not isinstance(d_list, list):
            d_list = [d_list]
        error_list = []
        for d in d_list:
            err = d
            for k in key.split('.'):
                err = err.get(k, {})
            if err:
                error_list.append(err)
        if not error_list:
            return None
        return error_list

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
