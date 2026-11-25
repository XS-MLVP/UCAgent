#coding: utf-8

from importlib import import_module

from ucagent.core.stage.llm_suggestion.base_suggestion import *

# ``langchain_suggestion`` imports the langchain agent/model stack
# (``langchain_openai`` and friends) at module level. Re-exporting it eagerly
# here would make every ``import ucagent.core.stage.*`` pull that stack through
# ``vmanager``, so the suggestion classes stay lazy: the YAML contract
# ``clss: ucagent.core.stage.llm_suggestion.OpenAILLM*`` resolves through
# ``__getattr__`` below at instantiation time only.
_EXPORTS = {
    "OpenAILLMFailSuggestion": "langchain_suggestion",
    "OpenAILLMPassSuggestion": "langchain_suggestion",
    "RemoveAllSummarizationMiddleware": "langchain_suggestion",
    "do_work_values": "langchain_suggestion",
}


def __getattr__(name):
    """Resolve a lazily exported suggestion name from its owning submodule."""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{module_name}")
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__():
    """List the eager and lazy package names together for introspection."""
    return sorted(set(globals()) | set(_EXPORTS))
