"""Drain one MCP server's notification streams before Uvicorn waits for requests."""

import anyio
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
