# -*- coding: utf-8 -*-
"""Context management tools for UCAgent."""

from langchain_core.callbacks import (
    CallbackManagerForToolRun,
)

from .uctool import UCTool
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field
from typing import Any, Optional


class ArgArbitContextSummary(BaseModel):
    message: str = Field(
        description="Sumary of the chat history.",
    )


class ArbitContextSummary(UCTool):
    """Tool to set the arbitrary context summary."""

    name: str = "ArbitContextSummary"
    description: str = ("Set an arbitrary context summary. This tool allows you to provide a custom summary "
                        "of the context that passed to the LLM.\n"
                        "The chat message layout:\n"
                        " - Summary of previous conversation\n"
                        " - Role information\n"
                        " - Chat messages\n"
                        "In the verification task, most of the chat/log data is useless. Please only record the necessary information. "
                        "When this tool is successfully executed, the original summary will be replaced with the new one, "
                        "and other messages will be cleared except system message. You can use this tool flexibly to manage context."
                       )
    args_schema: Optional[ArgsSchema] = ArgArbitContextSummary
    conversation_manager: Any = None
    def _run(
        self,
        message: str,
        run_manager: CallbackManagerForToolRun = None,
    ) -> str:
        """Run the tool."""
        if not message:
            return "No summary message provided."
        if not hasattr(self, 'conversation_manager'):
            return "Conversation manager not bound. Please bind it before using this tool."
        self.conversation_manager.set_arbit_summary(message)
        return f"Set arbitrary context summary successfully ({len(message)} bytes)."

    def bind(self, conversation_manager):
        """Bind the conversation manager to set the arbitrary summary."""
        if not hasattr(conversation_manager, 'set_arbit_summary'):
            raise ValueError("The provided conversation manager does not support setting arbitrary summaries.")
        self.conversation_manager = conversation_manager
        return self
