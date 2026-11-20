"""Scripted Super models using the production LangChain graph and tool dispatch."""

import json
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


class PlannerModel(BaseChatModel):
    """Record model inputs and make a caller-supplied planning decision without networking."""

    decide: Any
    contexts: list = Field(default_factory=list)

    @property
    def _llm_type(self):
        """Identify this deterministic test model to the graph."""
        return "test-supervisor"

    def bind_tools(self, tools, **kwargs):
        """Assert the production Super capability boundary before binding tools."""
        assert not {"EditTextFile", "Complete", "Exit", "RunTestCases"} & {t.name for t in tools}
        return self

    def get_num_tokens_from_messages(self, messages, tools=None):
        """Avoid optional tokenizer downloads during deterministic acceptance."""
        return 20

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        """Read the newest structured planning context and exercise real tool calling."""
        context = json.loads(next(m.content for m in reversed(messages) if isinstance(m, HumanMessage)))
        self.contexts.append(context)
        message = self.decide(context, len(self.contexts))
        return ChatResult(generations=[ChatGeneration(message=message)])


def install_planner(agent, monkeypatch, decide=None):
    """Attach a real LangChain backend with scripted planning to an offline test Agent."""
    import ucagent.core.backends.langchain.agent as backend_module

    def sequential(context, turn):
        """Delegate actual stages and produce a final summary only after all gates pass."""
        if context["workflow_complete"]:
            return AIMessage(content="All stage checks passed.")
        return AIMessage(content="Delegate the authorized scope.", tool_calls=[{
            "name": "SubAgentTool", "id": f"plan-{turn}", "args": {
                "plan_id": f"plan-{turn}", "planning_token": context["planning_token"],
                "tasks": [{"id": "work", "instruction": "Complete the authorized stage."}]}}])

    planner = PlannerModel(decide=decide or sequential)
    monkeypatch.setattr(backend_module, "get_chat_model", lambda *args, **kwargs: planner)
    monkeypatch.setattr(backend_module, "negotiate_openai_api_mode", lambda cfg, **kwargs: None)
    agent.backend = backend_module.UCAgentLangChainBackend(agent, agent.cfg)
    agent.backend.init()
    agent._startup_cleanup.callback(agent.backend.exit)
    return planner
