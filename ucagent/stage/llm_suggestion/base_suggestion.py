#coding: utf-8

from ucagent.util.functions import import_class_from_str
from ucagent.util.config import Config
from ucagent.util.log import info
from ucagent.stage.vstage import VerifyStage


class BaseLLMSuggestion:

    def set_vmanager(self, vmanager):
        self.vmanager = vmanager
        return self

    def get_vmanager(self):
        if not hasattr(self, 'vmanager'):
            raise None
        return self.vmanager

    def bind_tools(self, tools: list,
                   system_prompt: str,
                   suggestion_prompt: str): # return self
        raise NotImplementedError("Subclasses must implement this method. return self.")

    def suggest(self, prompts: list, stage: VerifyStage) -> str:
        raise NotImplementedError("Subclasses must implement this method.")


def get_llm_check_fail_refinement_instance(cfg: Config, vmanager) -> BaseLLMSuggestion:
    import ucagent.stage.llm_suggestion as llm_suggestion_module
    fail_refinement_cfg = cfg.vmanager.llm_suggestion.check_fail_refinement
    if fail_refinement_cfg.enable != True:
        return None
    class_name = fail_refinement_cfg.clss
    clss = import_class_from_str(class_name, llm_suggestion_module)
    args = fail_refinement_cfg.args.as_dict()
    info(f"Instantiate LLM Suggestion: {class_name}")
    system_prompt = fail_refinement_cfg.system_prompt
    suggestion_prompt = fail_refinement_cfg.suggestion_prompt
    return clss(**args).set_vmanager(vmanager).bind_tools(vmanager.tool_inspect_file,
                                                          system_prompt=system_prompt,
                                                          suggestion_prompt=suggestion_prompt)
