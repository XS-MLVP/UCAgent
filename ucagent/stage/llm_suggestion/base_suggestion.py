#coding: utf-8

from ucagent.util.functions import import_class_from_str
from ucagent.util.config import Config
from ucagent.util.log import info, warning
from ucagent.stage.vstage import VerifyStage


class BaseLLMSuggestion:

    def set_vmanager(self, vmanager):
        self.vmanager = vmanager
        return self

    def get_vmanager(self):
        if not hasattr(self, 'vmanager'):
            raise None
        return self.vmanager

    def _remove_ignore_labels(self, text: str, ignore_labels: list) -> str:
        for start_label, end_label in ignore_labels:
            while True:
                start_idx = text.find(start_label)
                end_idx = text.find(end_label, start_idx + len(start_label))
                if start_idx != -1 and end_idx != -1:
                    text = text[:start_idx] + text[end_idx + len(end_label):]
                else:
                    break
        return text

    def interrupt_handler(self):
        warning("LLM Suggestion interrupt received.")
        self._interrupted = True

    def is_interrupted(self):
        return hasattr(self, '_interrupted') and self._interrupted

    def unset_interrupted(self):
        self._interrupted = False

    def message_echo(self, msg: str):
        vmanager = self.get_vmanager()
        if vmanager:
            vmanager.agent.message_echo(msg)

    def bind_tools(self, tools: list,
                   system_prompt: str,
                   suggestion_prompt: str): # return self
        raise NotImplementedError("Subclasses must implement this method. return self.")

    def suggest(self, prompts: list, stage: VerifyStage) -> str:
        raise NotImplementedError("Subclasses must implement this method.")


def get_llm_check_instance(refinement_cfg: Config, vmanager, tools) -> BaseLLMSuggestion:
    import ucagent.stage.llm_suggestion as llm_suggestion_module
    if refinement_cfg.enable != True:
        return None
    class_name = refinement_cfg.clss
    clss = import_class_from_str(class_name, llm_suggestion_module)
    args = refinement_cfg.args.as_dict()
    info(f"Instantiate LLM Suggestion: {class_name}")
    system_prompt = refinement_cfg.system_prompt
    suggestion_prompt = refinement_cfg.suggestion_prompt
    return clss(**args).set_vmanager(vmanager).bind_tools(tools,
                                                          system_prompt=system_prompt,
                                                          suggestion_prompt=suggestion_prompt)
