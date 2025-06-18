#coding=utf-8


from .uctool import UCTool

from sequential_thinking_tool import SequentialThinkingTool


class SqThinking(SequentialThinkingTool, UCTool):
    """
    A tool that combines the functionality of UCTool and SequentialThinkingTool.
    It inherits from both classes to provide a unified interface for sequential thinking tasks.
    """
    
    def invoke(self, input, config=None, **kwargs):
        return UCTool.invoke(self, input, config, **kwargs)

    def ainvoke(self, input, config=None, **kwargs):
        return UCTool.ainvoke(self, input, config, **kwargs)

