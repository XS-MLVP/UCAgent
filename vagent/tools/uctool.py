#coding=utf-8


from langchain_core.tools import BaseTool
from pydantic import Field


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
