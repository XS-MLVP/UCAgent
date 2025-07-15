#coding=utf-8


from langchain_core.tools import BaseTool
from langchain_core.tools.base import ArgsSchema
from pydantic import Field, BaseModel
from typing import Callable, Optional


class EmptyArgs(BaseModel):
    """Empty arguments for tools that do not require any input."""
    pass


class UCTool(BaseTool):
    call_count: int = Field(
        default=0,
        description="Number of times the tool has been called.")

    pre_call_back: callable = Field(
        default=None,
        description="A callback function to be executed before each call to the tool."
    )

    def invoke(self, input, config = None, **kwargs):
        self.call_count += 1
        return super().invoke(input, config, **kwargs)

    def ainvoke(self, input, config = None, **kwargs):
        self.call_count += 1
        return super().ainvoke(input, config, **kwargs)

    def pre_call(self, *args, **kwargs):
        if self.pre_call_back is None:
            return
        self.pre_call_back(*args, **kwargs)

    def set_pre_call_back(self, func):
        self.pre_call_back = func
        return self


class RoleInfo(UCTool):
    """A tool to provide role information."""
    args_schema: Optional[ArgsSchema] = EmptyArgs
    name: str = "RoleInfo"
    description: str = (
        "Returns the role information of you. "
    )

    # custom info
    role_info: str = Field(
        default="You are an expert AI software/hardware engineering agent.",
        description="The role information to be returned by the tool."
    )

    def _run(self, *args, **kwargs):
        return self.role_info

    def __init__(self, role_info: str = None, **kwargs):
        super().__init__(**kwargs)
        if role_info:
            self.role_info = role_info
