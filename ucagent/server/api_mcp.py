# -*- coding: utf-8 -*-
"""
MCP server lifecycle with explicit tools and resolved configuration.

Provides :class:`McpServer` which manages starting and stopping the
MCPServer/uvicorn server that exposes UCAgent tools via the Model Context
Protocol (MCP).  The class follows the same lifecycle pattern as
the other application services.
"""

import math
import threading
import time
from typing import Any, List, Optional, Tuple


def _collect_mcp_tools(agent: Any, no_file_ops: bool) -> List[Any]:
    """Return configuration-filtered MCP tools, optionally without file operations."""

    tools = (
        agent.tool_list_base
        + agent.tool_list_task
        + agent.tool_list_ext
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


class McpServer:
    """Own one ready MCP application and its graceful background-thread shutdown."""

    def __init__(self, tools, *, cfg, host="127.0.0.1", port=5000, no_file_ops=False, logger=None):
        """Accept filtered tools and configuration without constructing an agent or debugger."""
        self.tools = list(tools)
        self.cfg = cfg
        self.logger = logger
        self.host = host
        self.port = port
        self.no_file_ops = no_file_ops
        self._server = None
        self._thread = None
        self._startup_error = None
        self._lifecycle_lock = threading.RLock()
        self.started_at = None

    def _clear_stopped_state(self) -> None:
        """Release ownership only after the background thread has exited."""
        self._server = None
        self._thread = None
        self.started_at = None

    def start(self, timeout: float = 10.0) -> Tuple[bool, str]:
        """Start a fresh SDK application and report success only after HTTP readiness."""
        with self._lifecycle_lock:
            if self.is_running:
                state = "shutting down" if self.is_stopping else "already running"
                return False, f"MCP server is {state} at {self.url()}; wait for it to stop before restarting"
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
                return False, "MCP server startup timeout must be a positive finite number"
            self._clear_stopped_state()
            self._startup_error = None
            tools = self.tools
            self.cfg.update_template({"TOOLS": ", ".join(t.name for t in tools)})

            from ucagent.util.functions import create_verify_mcps, start_verify_mcps, stop_verify_mcps
            from ucagent.util.log import info

            try:
                server = create_verify_mcps(
                    tools, host=self.host, port=self.port,
                    logger=self.logger,
                )
            except Exception as error:
                return False, f"Failed to create MCP server: {error}"
            self._server = server
            info("Init Prompt:\n" + self.cfg.get_value("mcp_server.init_prompt", ""))

            def _run():
                """Serve the captured instance, retaining startup failures for the caller."""
                try:
                    start_verify_mcps(server)
                except BaseException as error:
                    self._startup_error = error

            self._thread = threading.Thread(target=_run, daemon=True, name="ucagent-mcp-server")
            # Preserve ownership even if startup times out before the loop exits.
            self._thread.start()
            deadline = time.monotonic() + float(timeout)
            while time.monotonic() < deadline:
                if self._startup_error is not None or not self._thread.is_alive():
                    break
                if server.started:
                    self.port = server.servers[0].sockets[0].getsockname()[1]
                    self.started_at = time.time()
                    return True, f"MCP server started at {self.url()}"
                time.sleep(0.01)

            stop_verify_mcps(server)
            self._thread.join(timeout=1.0)
            if self._startup_error is not None:
                detail = f": {self._startup_error}"
            elif not self._thread.is_alive():
                detail = ": server thread exited before becoming ready"
            else:
                detail = f" within {float(timeout):g} seconds; shutdown is still pending"
            if not self._thread.is_alive():
                self._clear_stopped_state()
            return False, f"MCP server failed to start at {self.url()}{detail}"

    def stop(self, timeout: float = 5.0) -> Tuple[bool, str]:
        """Drain idle streams and wait up to timeout seconds, retaining live ownership."""
        with self._lifecycle_lock:
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 0:
                return False, "MCP server shutdown timeout must be a non-negative finite number"
            if self._thread is None:
                return True, "MCP server is stopped"

            from ucagent.util.functions import stop_verify_mcps

            thread = self._thread
            if thread.is_alive():
                stop_verify_mcps(self._server)
                if thread is not threading.current_thread():
                    thread.join(timeout=timeout)
                if thread.is_alive():
                    return False, (
                        f"MCP server at {self.url()} is still shutting down; "
                        "its thread remains active. Wait for active calls to finish and retry stop."
                    )
            self._clear_stopped_state()
            return True, "MCP server stopped"

    @property
    def is_running(self) -> bool:
        """Return thread liveness, including startup and pending shutdown."""
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def is_ready(self) -> bool:
        """Expose an endpoint only after HTTP readiness and before shutdown begins."""
        return self.is_running and self._server is not None and self._server.started and not self._server.should_exit

    @property
    def is_stopping(self) -> bool:
        """Return whether a live server has received a shutdown request."""
        server = self._server
        return self.is_running and server is not None and server.should_exit

    def url(self) -> str:
        """Return the MCP server URL."""
        return f"http://{self.host}:{self.port}"
