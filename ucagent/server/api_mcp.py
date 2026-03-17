# -*- coding: utf-8 -*-
"""
MCP server lifecycle wrapper for VerifyPDB.

Provides :class:`PdbMcpServer` which manages starting and stopping the
FastMCP/uvicorn server that exposes UCAgent tools via the Model Context
Protocol (MCP).  The class follows the same lifecycle pattern as
:class:`PdbCmdApiServer`.
"""

import threading
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from ucagent.verify_pdb import VerifyPDB


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
        self._running = False
        self.started_at: Optional[float] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> Tuple[bool, str]:
        """Build the tool list and start the MCP server in a background thread.

        Returns
        -------
        (success, message)
        """
        if self._running:
            return False, f"MCP server is already running at {self.url()}"

        agent = self.pdb.agent

        # Collect tools from the agent
        tools = agent.tool_list_base + agent.tool_list_task + agent.tool_list_ext
        if not self.no_file_ops:
            tools += agent.tool_list_file

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
            start_verify_mcps(self._server, self._glogger)

        self._thread = threading.Thread(target=_run, daemon=True, name="pdb-mcp-server")
        self._thread.start()

        # Keep agent attributes in sync for backward-compat
        # (api_master.py uses agent._mcps and agent._mcp_server_thread to report
        # mcp_running in heartbeats)
        agent._mcps = server
        agent._mcp_server_thread = self._thread

        self._running = True
        self.started_at = __import__('time').time()
        return True, f"MCP server started at {self.url()}"

    def stop(self) -> Tuple[bool, str]:
        """Stop the MCP server.

        Returns
        -------
        (success, message)
        """
        if not self._running:
            return False, "MCP server is not running"

        from ucagent.util.functions import stop_verify_mcps

        stop_verify_mcps(self._server)
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
        return (
            self._running
            and self._thread is not None
            and self._thread.is_alive()
        )

    def url(self) -> str:
        """Return the MCP server URL."""
        return f"http://{self.host}:{self.port}"
