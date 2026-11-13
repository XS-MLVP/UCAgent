"""Offline model decisions for the real two-plugin workflow relay acceptance path."""

import json
import re
from typing import Any
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


def decision(tips):
    """Model policy for tests only: choose the sink when the original goal requests increment."""
    handoff = tips.get("handoff")
    if tips.get("stage") is not None:
        return "SubAgentTool", {"plan_id": "work-" + uuid4().hex[:8], "planning_token": tips["planning_token"],
            "tasks": [{"id": "produce", "instruction": "Read the guide and input, produce the required JSON, journal, Check and submit."}]}
    args = {"transition_token": handoff["transition_token"], "reason": "Follow the original goal", "summary": "Validated artifact produced"}
    if handoff["workflow_ref"] == "relay-source:produce" and "increment" in handoff["original_goal"]:
        args.update(workflow_ref="relay-sink:consume", inputs={"inputs/payload.json": "result_a/payload.json"})
        return "RequestNextWorkflow", args
    return "CompleteWorkflowChain", args


def worker_action(index, tips, source):
    """Drive file and stage tools using their public context and actual input contents."""
    sink = bool(tips["handoff_inputs"])
    folder, filename, guide = ("result_b", "result", "sink") if sink else ("result_a", "payload", "source")
    input_path = "inputs/payload.json" if sink else "inputs/request.json"
    if index == 0:
        return "ReadTextFile", {"path": f"Guide_Doc/{guide}.md"}
    if index == 1:
        return "ReadTextFile", {"path": input_path, "include_line_numbers": False}
    if index == 2:
        payload = json.loads(re.search(r'\{[^{}]*"value"[^{}]*\}', source).group())
        content = {"value": payload["value"] + 1, "source_sha256": tips["handoff_inputs"][0]["sha256"]} if sink else payload
        return "EditTextFile", {"path": f"{folder}/{filename}.json", "content": json.dumps(content)}
    if index == 3:
        return "SetCurrentStageJournal", {"journal": "Read input and guide; produced the exact JSON artifact."}
    if index == 4:
        return "Check", {}
    return "SubmitTaskResult", {"summary": "Artifact checked and ready for final acceptance"}


class RelayModel(BaseChatModel):
    """Exercise production LangChain graph/tool dispatch with deterministic offline decisions."""

    supervisor: bool = False
    index: int = 0
    tips: dict = Field(default_factory=dict)
    contexts: list = Field(default_factory=list)

    @property
    def _llm_type(self):
        """Identify the offline relay provider."""
        return "offline-relay"

    def bind_tools(self, tools, **kwargs):
        """Recognize the authorized tool view without reaching into runtime implementation."""
        self.supervisor = "SubAgentTool" in {tool.name for tool in tools}
        return self

    def get_num_tokens_from_messages(self, messages, tools=None):
        """Avoid tokenizer downloads for this tiny deterministic model."""
        return 30

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        """Read current public context and return one real tool invocation."""
        if self.supervisor:
            context = json.loads(next(m.content for m in reversed(messages) if isinstance(m, HumanMessage)))
            self.contexts.append(context)
            name, arguments = decision(context)
        else:
            if not self.tips:
                human = next(m.content for m in messages if isinstance(m, HumanMessage))
                self.tips = json.loads(human[human.index("\n{") + 1:])
            source = "\n".join(str(m.content) for m in messages if isinstance(m, ToolMessage) and m.name == "ReadTextFile")
            name, arguments = worker_action(self.index, self.tips, source)
            self.index += 1
        message = AIMessage(content="", tool_calls=[{"name": name, "args": arguments, "id": uuid4().hex}])
        return ChatResult(generations=[ChatGeneration(message=message)])
