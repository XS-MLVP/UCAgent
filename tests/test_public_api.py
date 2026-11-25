"""The package root exposes a small, lazy framework API."""

import subprocess
import sys

from ucagent import (
    Argument,
    BaseReadWrite,
    BatchTask,
    Checker,
    CommandRequirement,
    CommandSpec,
    Config,
    ManagerTool,
    Plugin,
    PluginContext,
    PluginError,
    PluginWorkflow,
    PreparationOptions,
    UCTool,
    WorkspacePreparation,
    load_runtime_config,
    to_mcp_tool,
)
from ucagent.core.checkers.base import Checker as CheckerImplementation
from ucagent.core.tools.uctool import UCTool as ToolImplementation


def test_root_exports_stable_extension_contract():
    """Public names resolve to the existing implementations."""
    assert Checker is CheckerImplementation
    assert UCTool is ToolImplementation
    assert issubclass(ManagerTool, UCTool)
    assert all(callable(value) for value in (
        Argument, BaseReadWrite, BatchTask, CommandRequirement, CommandSpec, Config,
        Plugin, PluginContext, PluginError, PluginWorkflow, PreparationOptions,
        WorkspacePreparation, load_runtime_config, to_mcp_tool,
    ))


def test_importing_ucagent_does_not_eagerly_load_agent_execution():
    """The convenience facade keeps package import lightweight."""
    subprocess.run(
        [sys.executable, "-c",
         "import sys, ucagent; assert 'ucagent.core.agent.execution' not in sys.modules"],
        check=True,
    )
