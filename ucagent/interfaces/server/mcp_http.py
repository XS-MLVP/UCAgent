"""Construct and serve MCP transports with per-instance notification draining and logging."""

import logging
import threading

import anyio
from ucagent.core.tools.uctool import to_mcp_tool
from ucagent.util.log import info
import uvicorn
from starlette.responses import PlainTextResponse


class _DrainableMcpApp:
    """Own cancellation scopes for GET streams without interrupting POST tools."""

    def __init__(self, app):
        """Wrap the SDK application without accessing its private session state."""
        self.app = app
        self._streams = set()
        self._stopping = False

    def drain(self) -> None:
        """End this instance's notification streams on their owning event loop."""
        self._stopping = True
        for scope in tuple(self._streams):
            scope.cancel()

    async def __call__(self, scope, receive, send) -> None:
        """Finish drained HTTP responses normally while preserving external errors."""
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        if self._stopping:
            await PlainTextResponse('MCP server is shutting down.', status_code=503)(scope, receive, send)
            return
        if scope['method'] != 'GET':
            await self.app(scope, receive, send)
            return

        response_started = False
        response_complete = False

        async def track_send(message):
            """Track response framing so a drained stream gets exactly one ending."""
            nonlocal response_started, response_complete
            await send(message)
            if message['type'] == 'http.response.start':
                response_started = True
            elif message['type'] == 'http.response.body' and not message.get('more_body', False):
                response_complete = True

        with anyio.CancelScope() as stream_scope:
            self._streams.add(stream_scope)
            try:
                await self.app(scope, receive, track_send)
            finally:
                self._streams.discard(stream_scope)
        # Only our own drain is consumed by CancelScope. Uvicorn timeouts and
        # other external cancellations still propagate. Complete the real HTTP
        # response instead of fabricating a client disconnect for a live socket.
        if stream_scope.cancel_called and not response_complete:
            if response_started:
                await send({'type': 'http.response.body', 'body': b'', 'more_body': False})
            else:
                await PlainTextResponse('MCP server is shutting down.', status_code=503)(scope, receive, send)


class McpHttpServer(uvicorn.Server):
    """Close idle GET streams before waiting for active MCP tool requests."""

    def __init__(self, config):
        """Attach one drain controller to this server's SDK application."""
        self._mcp_app = _DrainableMcpApp(config.app)
        config.app = self._mcp_app
        super().__init__(config)

    async def shutdown(self, sockets=None) -> None:
        """Drain on the server loop, then let Uvicorn finish requests and lifespan."""
        self._mcp_app.drain()
        await super().shutdown(sockets=sockets)


def create_verify_mcps(mcp_tools: list, host: str, port: int, logger=None):
    """Build an instance-drained MCP server without replacing global logging."""
    from mcp.server.mcpserver import MCPServer

    converted_tools = [to_mcp_tool(tool) for tool in mcp_tools]
    info(f"create MCP server with tools: {[tool.name for tool in converted_tools]}")
    mcp = MCPServer("UCAgent", tools=converted_tools)
    config = uvicorn.Config(
        mcp.streamable_http_app(host=host),
        host=host,
        port=port,
        # All embedded servers share logging with the enclosing application.
        # Configuring Uvicorn's global handlers here would affect other services.
        log_config=None,
        log_level=None,
        ws="none",
        timeout_keep_alive=300,
        timeout_graceful_shutdown=60,
    )
    server = McpHttpServer(config)
    server.ui_logger = logger
    return server


def start_verify_mcps(server):
    """Serve MCP and forward only this thread's Uvicorn logs to its UI."""

    thread_id = threading.get_ident()

    class _BridgeHandler(logging.Handler):
        """Forward this server's Uvicorn records to its configured UI."""

        def emit(self, record):
            """Route only records emitted by the owning server thread."""
            if record.thread == thread_id:
                try:
                    server.ui_logger.log(record.levelno, record.getMessage(), exc_info=record.exc_info)
                except Exception:
                    # A TUI may have exited while the server is still running.
                    pass

    from ucagent.runtime.output import OUTPUT_OWNER
    from ucagent.util.output import OUTPUT_SINK
    output = getattr(server.ui_logger, "runtime_output", None)
    owner_token = OUTPUT_OWNER.set(output)
    sink_token = OUTPUT_SINK.set(output.events.append if output is not None else None)
    # Runtime captures service records before formatting; legacy custom UI loggers
    # still receive diagnostics, but never HTTP access records as model messages.
    bridge = _BridgeHandler() if server.ui_logger is not None and output is None else None
    loggers = [logging.getLogger(name) for name in ("uvicorn.error",)]
    if bridge is not None:
        for logger in loggers:
            logger.addHandler(bridge)
    try:
        anyio.run(server.serve)
    except Exception as error:
        info(f"MCP server exit with: {error}")
        raise
    finally:
        if bridge is not None:
            for logger in loggers:
                logger.removeHandler(bridge)
            bridge.close()
        info("MCP server stopped.")
        OUTPUT_SINK.reset(sink_token)
        OUTPUT_OWNER.reset(owner_token)


def stop_verify_mcps(server):
    """Request graceful shutdown of a running MCP HTTP server."""
    if server is not None:
        info("Stopping MCP server...")
        server.should_exit = True
    else:
        info("MCP server is not running.")
