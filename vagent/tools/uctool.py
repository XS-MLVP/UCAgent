#coding=utf-8


from langchain_core.tools import BaseTool
from pydantic import Field


class UCTool(BaseTool):
    call_count: int = Field(
        default=0,
        description="Number of times the tool has been called.")

    def invoke(self, input, config = None, **kwargs):
        self.call_count += 1
        return super().invoke(input, config, **kwargs)

    def ainvoke(self, input, config = None, **kwargs):
        self.call_count += 1
        return super().ainvoke(input, config, **kwargs)

