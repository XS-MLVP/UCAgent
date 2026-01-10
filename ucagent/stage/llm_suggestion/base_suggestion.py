#coding: utf-8

from ucagent.util.functions import import_class_from_str
from ucagent.util.config import Config
from ucagent.util.log import info


class BaseLLMSuggestion:

    def set_vmanager(self, vmanager):
        self.vmanager = vmanager
        return self

    def get_vmanager(self):
        if not hasattr(self, 'vmanager'):
            raise None
        return self.vmanager

    def bind_tools(self, tools: list, system_prompt: str): # return self
        raise NotImplementedError("Subclasses must implement this method. return self.")

    def suggest(self, prompts: list, fail_count:int) -> str:
        raise NotImplementedError("Subclasses must implement this method.")


def get_llm_suggestion_instance(cfg: Config, vmanager) -> BaseLLMSuggestion:
    import ucagent.stage.llm_suggestion as llm_suggestion_module
    if cfg.vmanager.llm_suggestion.enable != True:
        return None
    class_name = cfg.vmanager.llm_suggestion.clss
    clss = import_class_from_str(class_name, llm_suggestion_module)
    args = cfg.vmanager.llm_suggestion.args.as_dict()
    info(f"Instantiate LLM Suggestion: {class_name}")
    system_prompt = cfg.vmanager.llm_suggestion.system_prompt
    return clss(**args).set_vmanager(vmanager).bind_tools(vmanager.tool_inspect_file,
                                                          system_prompt=system_prompt)