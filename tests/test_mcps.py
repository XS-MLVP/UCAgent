#coding=utf-8

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from langchain_core.tools import tool
from vagent.verify_mcps import start_verify_mcps


@tool
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b


def test_start_verify_mcps():
    """Test starting the MCP server with a simple add tool."""
    mcp_tools = [add]
    start_verify_mcps(mcp_tools, host="0.0.0.0", port=3376)


if __name__ == "__main__":
    test_start_verify_mcps()
    print("MCP server started with add tool.")
