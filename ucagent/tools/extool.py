# -*- coding: utf-8 -*-
"""External tools integration for UCAgent."""

from .uctool import UCTool

# Extool is a class that extends UCTool to provide additional functionality.


def SqThink():
    """Sequential thinking tool for step-by-step reasoning"""
    from sequential_thinking_tool import SequentialThinkingTool
    return SequentialThinkingTool()


def ReflectionTool():
    """Reflection tool for self-assessment and improvement"""
    try:
        from reflection_tool import ReflectionTool as RT
        return RT()
    except ImportError:
        # Fallback to a simple reflection implementation
        return SimpleReflectionTool()


class SimpleReflectionTool(UCTool):
    """Simple reflection tool for self-assessment"""
    name: str = "Reflect"
    description: str = (
        "Reflect on the current progress, identify potential issues, and suggest improvements. "
        "Use this tool to pause and think about what has been accomplished and what might need adjustment."
    )
    
    def _run(self, run_manager=None) -> str:
        return (
            "Please take a moment to reflect on:\n"
            "1. What has been accomplished so far?\n"
            "2. What challenges or obstacles have been encountered?\n"
            "3. Are there any gaps in understanding or approach?\n"
            "4. What adjustments or improvements could be made?\n"
            "5. What are the next most important steps?\n\n"
            "Consider using MemoryPut to save important insights from this reflection."
        )

