# -*- coding: utf-8 -*-
"""Human interaction tools for UCAgent."""

from langchain_core.callbacks import (
    CallbackManagerForToolRun,
)
from .uctool import UCTool
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field
from typing import Optional


class ArgHumanHelp(BaseModel):
    message: str = Field(
        default=".",
        description="Message to human for help. If empty, the tool will not be run.",
    )


class HumanHelp(UCTool):
    """Tool for human help."""

    name: str = "HumanHelp"
    description: str = ("Ask human for help. You are an excellent agent. "
                        "Normally, do not use this tool unless you have tried every method you can "
                        "and still cannot solve the problem, in which case you can seek help from a human")
    args_schema: Optional[ArgsSchema] = ArgHumanHelp

    def _run(
        self,
        message: str,
        run_manager: CallbackManagerForToolRun = None,
    ) -> str:
        """Run the tool."""
        if not message:
            return "No message provided for human help."
        text = input(
            f"Human help requested with message: {message}\n"
            "Please provide your input and press Enter to continue:\n"
        )
        return f"Human response: {text}"
