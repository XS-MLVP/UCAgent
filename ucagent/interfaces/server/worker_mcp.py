"""Application-injected, ready and authenticated task-specific MCP endpoints."""

from contextlib import contextmanager
import secrets

from ucagent.interfaces.server.api_mcp import McpServer
from ucagent.util.config import Config


@contextmanager
def worker_endpoint(tools, cfg):
    """Own a loopback server until all in-flight calls and its HTTP thread exit."""
    token = secrets.token_urlsafe(32)
    server = McpServer(tools, cfg=Config({"tools": {}, "mcp_server": {"init_prompt": ""}}),
                       host="127.0.0.1", port=0, bearer_token=token)
    try:
        ok, message = server.start()
        if not ok:
            raise RuntimeError(message)
        yield {"url": server.url() + "/mcp", "token": token, "responses_idle": server.responses_idle}
    finally:
        # A timed-out tool may still be writing. Do not release the worker slot
        # while its endpoint owns such a call; host shutdown reports it as pending.
        while server.is_running:
            server.stop(timeout=1)
