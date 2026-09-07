# -*- coding: utf-8 -*-
"""
MCP server lifecycle wrapper for VerifyPDB.

Provides :class:`PdbMcpServer` which manages starting and stopping the
FastMCP/uvicorn server that exposes UCAgent tools via the Model Context
Protocol (MCP).  The class follows the same lifecycle pattern as
:class:`PdbCmdApiServer`.
"""

import threading
import time
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

if TYPE_CHECKING:
    from ucagent.verify_pdb import VerifyPDB


def _collect_mcp_tools(agent: Any, no_file_ops: bool) -> List[Any]:
    """Return configuration-filtered MCP tools, optionally without file operations."""

    tools = (
        agent.tool_list_base
        + agent.tool_list_task
        + agent.tool_list_ext
        + getattr(agent, "tool_list_waveform", [])
        + getattr(agent, "tool_list_plugin", [])
    )
    if not no_file_ops:
        tools += agent.tool_list_file
    tool_config = getattr(getattr(agent, "cfg", None), "tools", None)
    if tool_config is not None:
        if hasattr(tool_config, "as_dict"):
            tool_config = tool_config.as_dict()
        if isinstance(tool_config, dict):
            from ucagent.util.functions import get_tools_from_cfg

            tools = get_tools_from_cfg(tools, tool_config)
    return tools


class PdbMcpServer:
    """
    Lifecycle wrapper for the FastMCP/uvicorn MCP server.

    Creates and manages a FastMCP server in a background daemon thread,
    exposing the agent's tools via the Model Context Protocol.

    Usage
    -----
    ::

        server = PdbMcpServer(pdb, host="127.0.0.1", port=5000)
        ok, msg = server.start()
        ...
        ok, msg = server.stop()
    """

    def __init__(
        self,
        pdb_instance: "VerifyPDB",
        host: str = "127.0.0.1",
        port: int = 5000,
        no_file_ops: bool = False,
    ) -> None:
        """
        Parameters
        ----------
        pdb_instance : VerifyPDB
            The active VerifyPDB instance (used to access the underlying agent).
        host : str
            TCP address on which the MCP HTTP server will listen.
        port : int
            TCP port for the MCP HTTP server.
        no_file_ops : bool
            When True, file-operation tools are excluded from the MCP server.
        """
        try:
            import uvicorn  # noqa: F401
            from mcp.server.fastmcp import FastMCP  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "FastMCP and uvicorn are required for the MCP server. "
                "Install them with:  pip install mcp uvicorn"
            ) from exc

        self.pdb = pdb_instance
        self.host = host
        self.port = port
        self.no_file_ops = no_file_ops
        self._server = None          # uvicorn.Server instance
        self._glogger = None         # saved logging.getLogger (for restore on stop)
        self._thread: Optional[threading.Thread] = None
        self._startup_error: Optional[BaseException] = None
        self._running = False
        self.started_at: Optional[float] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, timeout: float = 10.0) -> Tuple[bool, str]:
        """Build the tool list and start the MCP server in a background thread.

        Returns
        -------
        (success, message)
        """
        if self._running:
            return False, f"MCP server is already running at {self.url()}"
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            return False, "MCP server startup timeout must be a positive number"
        self._startup_error = None

        agent = self.pdb.agent

        tools = _collect_mcp_tools(agent, self.no_file_ops)

        agent.cfg.update_template(
            {"TOOLS": ", ".join([t.name for t in tools])}
        )

        from ucagent.util.functions import create_verify_mcps, start_verify_mcps
        from ucagent.util.log import info

        try:
            server, glogger = create_verify_mcps(
                tools,
                host=self.host,
                port=self.port,
                logger=getattr(agent, "_mcps_logger", None),
            )
        except Exception as exc:
            return False, f"Failed to create MCP server: {exc}"

        self._server = server
        self._glogger = glogger

        info("Init Prompt:\n" + agent.cfg.mcp_server.init_prompt)

        def _run():
            """Serve MCP requests on the lifecycle-managed background thread."""

            try:
                start_verify_mcps(self._server, self._glogger)
            except BaseException as exc:
                self._startup_error = exc

        self._thread = threading.Thread(target=_run, daemon=True, name="pdb-mcp-server")
        self._thread.start()

        deadline = time.monotonic() + float(timeout)
        while time.monotonic() < deadline:
            if self._startup_error is not None or not self._thread.is_alive():
                break
            if getattr(self._server, "started", False):
                # Keep agent attributes in sync for api_master heartbeat reporting.
                agent._mcps = server
                agent._mcp_server_thread = self._thread
                self._running = True
                self.started_at = time.time()
                return True, f"MCP server started at {self.url()}"
            time.sleep(0.01)

        self._server.should_exit = True
        self._thread.join(timeout=1.0)
        if self._startup_error is not None:
            detail = f": {self._startup_error}"
        elif not self._thread.is_alive():
            detail = ": server thread exited before becoming ready"
        else:
            detail = f" within {float(timeout):g} seconds"
        self._server = None
        self._thread = None
        return False, f"MCP server failed to start at {self.url()}{detail}"

    def stop(self) -> Tuple[bool, str]:
        """Stop the MCP server.

        Returns
        -------
        (success, message)
        """
        if not self._running:
            return False, "MCP server is not running"

        from ucagent.util.functions import stop_verify_mcps

        thread = self._thread
        stop_verify_mcps(self._server)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)
        self._server = None
        self._thread = None
        self._running = False
        self.started_at = None

        # Clear agent backward-compat attributes
        agent = self.pdb.agent
        agent._mcps = None
        agent._mcp_server_thread = None

        return True, "MCP server stopped"

    @property
    def is_running(self) -> bool:
        """Return whether the MCP server thread is currently alive."""

        return (
            self._running
            and self._thread is not None
            and self._thread.is_alive()
        )

    def url(self) -> str:
        """Return the MCP server URL."""
        return f"http://{self.host}:{self.port}"
