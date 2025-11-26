#coding=utf-8
"""Custom tools for UCAgent."""

from ucagent.tools.uctool import UCTool


class MyCustomTool(UCTool):
    """A custom tool that performs a specific task."""
    name: str = "MyCustomTool"
    description: str = "This tool performs a custom operation defined by the user."

    def _run(self, run_manager=None) -> str:
        # Implement the custom logic here
        return "MyCustomTool has been executed successfully."
