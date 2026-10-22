"""Master routes for authenticated Xpra upgrades inside existing CMD proxies."""

from fastapi import WebSocket

from .transport import authorize_websocket, relay_websocket


def register_master_xpra_routes(app, server, browser_access):
    """Add distinct task/agent Xpra paths without changing terminal routes."""

    async def connect(websocket, target, password):
        """Replace browser credentials with the target CMD service credentials."""
        if websocket.url.query:
            target += "?" + websocket.url.query
        headers = server._build_ws_proxy_headers(password, dict(websocket.headers))
        await relay_websocket(websocket, target, headers=headers)

    @app.websocket("/task/{task_id}/cmd/api/xpra/sessions/{session_id}/client/")
    async def task_client(websocket: WebSocket, task_id: str, session_id: str):
        """Authorize the Master caller before resolving an owned task's CMD URL."""
        if not await authorize_websocket(websocket, server.password, browser_access):
            return
        try:
            task = server._get_task(task_id)
        except KeyError:
            await websocket.close(code=4404, reason="Task not found.")
            return
        cmd = task.get("cmd_api") or {}
        if cmd.get("status") not in ("running", "starting", "unavailable"):
            await websocket.close(code=4503, reason="The task CMD service is unavailable.")
            return
        try:
            target = server._cmd_proxy_url(task, f"api/xpra/sessions/{session_id}/client/")
        except ValueError:
            await websocket.close(code=4503, reason="The task CMD service has no connection address.")
            return
        await connect(websocket, target, cmd.get("password", ""))

    @app.websocket("/agent/{agent_id}/cmd/api/xpra/sessions/{session_id}/client/")
    async def agent_client(websocket: WebSocket, agent_id: str, session_id: str):
        """Authorize the Master caller before resolving a registered agent."""
        if not await authorize_websocket(websocket, server.password, browser_access):
            return
        with server._agents_lock:
            agent = dict(server._agents.get(agent_id) or {})
        if not agent:
            await websocket.close(code=4404, reason="Agent not found.")
            return
        if server._agent_status(agent) != "online" or not agent.get("cmd_api_tcp"):
            await websocket.close(code=4503, reason="The agent CMD service is unavailable.")
            return
        target = server._agent_cmd_proxy_url(agent, f"api/xpra/sessions/{session_id}/client/")
        await connect(websocket, target, agent.get("cmd_api_password", ""))
