"""Authenticated WebSocket relaying shared by CMD and Master Xpra routes."""

import asyncio
import base64
import hashlib
import hmac
import re
import secrets
import time
from urllib.parse import urlsplit

import aiohttp
from starlette.websockets import WebSocketDisconnect


class XpraBrowserAccess:
    """Sign short-lived browser grants for one session's WebSocket path only."""

    cookie_name = "ucagent_xpra_ws"
    lifetime = 300

    def __init__(self, password):
        """Keep a per-app signing key so credentials expire on service restart."""
        self._key = secrets.token_bytes(32)
        self._password = password

    def _signature(self, path, expires):
        """Bind the grant to its exact proxy path, deadline and current password."""
        value = f"{path}\0{expires}\0{self._password}".encode()
        return hmac.new(self._key, value, hashlib.sha256).hexdigest()

    def grant(self, request, response):
        """Add a scoped cookie only to successful, already-authenticated viewers."""
        match = re.fullmatch(r"(.*/api/xpra/sessions/[0-9a-f]{32})/(?:view/?|connect)", request.url.path)
        if match and 200 <= response.status_code < 300:
            path = match[1] + "/client/"
            expires = str(int(time.time()) + self.lifetime)
            # Master replaces the child grant with its own externally scoped one.
            if "set-cookie" in response.headers:
                del response.headers["set-cookie"]
            response.set_cookie(self.cookie_name, expires + "." + self._signature(path, expires),
                                max_age=self.lifetime, path=path, httponly=True, samesite="strict",
                                secure=request.url.scheme == "https")
            response.headers["Cache-Control"] = "no-store"
        return response

    def authorized(self, websocket):
        """Validate a browser grant without granting HTTP API or other-session access."""
        value = websocket.cookies.get(self.cookie_name, "")
        if not websocket.headers.get("origin") or len(value) > 100:
            return False
        expires, separator, signature = value.partition(".")
        if (not separator or not expires.isascii() or not expires.isdigit()
                or not re.fullmatch(r"[0-9a-f]{64}", signature)):
            return False
        remaining = int(expires) - time.time()
        return (0 < remaining <= self.lifetime
                and secrets.compare_digest(signature, self._signature(websocket.url.path, expires)))


def basic_authorized(password, authorization):
    """Apply the CMD password policy without exposing credential values."""
    if not password:
        return True
    if not authorization.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(authorization[6:], validate=True).decode("utf-8")
        _, separator, supplied = decoded.partition(":")
        return bool(separator) and secrets.compare_digest(supplied.encode(), password.encode())
    except (ValueError, UnicodeError):
        return False


async def authorize_websocket(websocket, password, browser_access=None):
    """Check credentials and browser Origin before accepting any connection."""
    if not basic_authorized(password, websocket.headers.get("authorization", "")) and not (
            browser_access and browser_access.authorized(websocket)):
        await websocket.close(code=4401, reason="Authentication required.")
        return False
    origin = websocket.headers.get("origin")
    if origin:
        try:
            parsed = urlsplit(origin)
            expected = urlsplit(str(websocket.url))
            same_origin = (parsed.scheme in ("http", "https") and parsed.hostname == expected.hostname
                           and (parsed.port or (443 if parsed.scheme == "https" else 80))
                           == (expected.port or (443 if expected.scheme == "wss" else 80))
                           and (parsed.scheme == "https") == (expected.scheme == "wss"))
        except ValueError:
            same_origin = False
        if not same_origin:
            await websocket.close(code=4403, reason="A same-origin connection is required.")
            return False
    return True


async def relay_websocket(websocket, target_url, headers=None, socket_path=None):
    """Relay negotiated text/binary traffic and cancel both pumps on disconnect."""
    upstream_headers = {k: v for k, v in (headers or {}).items()
                        if k.lower() not in {"sec-websocket-protocol", "cookie", "forwarded"}
                        and not k.lower().startswith("x-forwarded-")}
    parsed = urlsplit(target_url)
    upstream_headers["Origin"] = f"{parsed.scheme.replace('ws', 'http')}://{parsed.netloc}"
    connector = aiohttp.UnixConnector(path=socket_path) if socket_path else None
    timeout = aiohttp.ClientTimeout(total=None, connect=5, sock_connect=5)
    accepted = False
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.ws_connect(target_url, headers=upstream_headers,
                                          protocols=websocket.scope.get("subprotocols", []),
                                          heartbeat=20, max_msg_size=100 * 1024 * 1024) as upstream:
                await websocket.accept(subprotocol=upstream.protocol)
                accepted = True

                async def to_upstream():
                    """Copy browser messages without interpreting the Xpra protocol."""
                    while True:
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            return
                        if message.get("text") is not None:
                            await upstream.send_str(message["text"])
                        elif message.get("bytes") is not None:
                            await upstream.send_bytes(message["bytes"])

                async def to_browser():
                    """Copy server frames and propagate a valid upstream close code."""
                    async for message in upstream:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            await websocket.send_text(message.data)
                        elif message.type == aiohttp.WSMsgType.BINARY:
                            await websocket.send_bytes(message.data)
                        elif message.type == aiohttp.WSMsgType.ERROR:
                            return

                tasks = [asyncio.create_task(to_upstream()), asyncio.create_task(to_browser())]
                try:
                    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    if websocket.client_state.name != "DISCONNECTED":
                        code = upstream.close_code or 1000
                        await websocket.close(code=code if code not in (1005, 1006, 1015) else 1011)
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        if websocket.client_state.name != "DISCONNECTED":
            await websocket.close(code=1011 if accepted else 4502, reason="Xpra connection unavailable. Check the session status and retry.")
    except (WebSocketDisconnect, RuntimeError):
        return
