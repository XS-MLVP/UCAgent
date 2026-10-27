"""REST, HTML5 assets and WebSocket routes under the single /api/xpra prefix."""

from pathlib import Path
import posixpath
from typing import Literal
from urllib.parse import quote, unquote, urlsplit

import aiohttp
from fastapi import APIRouter, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictStr, TypeAdapter, ValidationError, field_validator

from ucagent.util.config import Config

from .transport import XpraBrowserAccess, authorize_websocket, relay_websocket
from .xpra import XpraError


class _CreateSession(BaseModel):
    """Launch one application, with explicit working directory and environment."""

    model_config = ConfigDict(extra="forbid")
    command: StrictStr = Field(min_length=1, max_length=16384, description="Program and quoted arguments; use an explicit shell for shell syntax.")
    mode: Literal["gui", "console"] = "gui"
    name: StrictStr = Field(default="", max_length=200)
    cwd: StrictStr = Field(default=".", max_length=4096)
    env: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    idle_timeout: int = Field(default=-1, strict=True, ge=-1, le=4_294_967,
                              description="Seconds without a connected client before exiting; -1 disables the timeout.")

    @field_validator("idle_timeout")
    @classmethod
    def validate_idle_timeout(cls, value):
        """Require a disabled timeout or a positive whole number of seconds."""
        if value == 0:
            raise ValueError("Use -1 or a positive number of seconds.")
        return value


class _WaveSession(BaseModel):
    """Open exact waveform metadata using the operator-configured application."""
    model_config = ConfigDict(extra="forbid")
    wave_meta: StrictStr = Field(min_length=1)


class _SessionPreset(_CreateSession):
    """An explicitly published form preset using the normal session fields."""

    label: StrictStr = Field(min_length=1, max_length=80, pattern=r"\S")


class _XpraRoute(APIRoute):
    """Keep feature validation errors structured without echoing request secrets."""

    def get_route_handler(self):
        """Translate feature errors and request validation into actionable JSON."""
        original = super().get_route_handler()

        async def handle(request):
            """Catch only expected feature errors; preserve normal FastAPI behavior."""
            try:
                return await original(request)
            except XpraError as exc:
                return JSONResponse(status_code=exc.status, content={"detail": exc.detail})
            except RequestValidationError as exc:
                errors = exc.errors()
                # Report the chosen public request branch without internal union names.
                if isinstance(exc.body, dict):
                    branch = "_WaveSession" if "wave_meta" in exc.body else "_CreateSession"
                    errors = [error for error in errors if len(error["loc"]) < 2
                              or error["loc"][1] not in {"_WaveSession", "_CreateSession"}
                              or error["loc"][1] == branch]
                return JSONResponse(status_code=422, content={"detail": dict(
                    error_code="XPRA_REQUEST_INVALID", message="The Xpra request has invalid fields.",
                    next_action="Correct the named fields using the API schema.",
                    fields=[".".join(str(part) for part in error["loc"]
                                      if part not in {"_WaveSession", "_CreateSession"})
                            for error in errors[:10]])})
        return handle


def register_xpra_routes(app, server):
    """Attach feature routes, resolving the current manager after server restarts."""
    router = APIRouter(prefix="/api/xpra", tags=["Xpra"], route_class=_XpraRoute)
    templates = Path(__file__).resolve().parents[1] / "templates"
    browser_access = XpraBrowserAccess(server.password)

    @router.get("", response_class=HTMLResponse, include_in_schema=False)
    @router.get("/", response_class=HTMLResponse, summary="Xpra session manager")
    def manager_page():
        """Serve the interactive session manager even when Xpra is unavailable."""
        return HTMLResponse((templates / "xpra.html").read_text(encoding="utf-8"))

    @router.get("/status")
    def status():
        """Report installed runtime prerequisites and actionable failures."""
        return server._xpra.status()

    @router.get("/presets")
    def presets():
        """Publish configured form defaults without launching or probing programs."""
        cfg = getattr(server.pdb.agent, "cfg", None)
        try:
            configured = cfg.get_value("cmd_api.xpra.presets", []) if cfg is not None else []
        except AttributeError:
            configured = []
        if isinstance(configured, list):
            configured = [item.as_dict() if isinstance(item, Config) else item for item in configured]
        try:
            validated = TypeAdapter(list[_SessionPreset]).validate_python(configured)
        except ValidationError as exc:
            # Validation errors may contain configured env values; return only locations.
            raise XpraError(503, "XPRA_PRESETS_INVALID", "The configured Xpra session presets have invalid fields.",
                            "Correct cmd_api.xpra.presets in the config and restart the CMD service. Manual session creation remains available.",
                            fields=[".".join(str(part) for part in error["loc"]) for error in exc.errors()[:10]]) from None
        return JSONResponse({"presets": [item.model_dump() for item in validated]},
                            headers={"Cache-Control": "no-store"})

    @router.get("/sessions")
    def sessions():
        """List only sessions owned by this CMD service."""
        return server._xpra.list()

    @router.post("/sessions", status_code=201)
    def create(body: _CreateSession | _WaveSession, request: Request):
        """Launch a session and return only after its HTML5 endpoint is ready."""
        if isinstance(body, _WaveSession):
            return server._waveform_launch.create(body.wave_meta, request)
        return server._xpra.create(**body.model_dump())

    @router.get("/sessions/{session_id}")
    def details(session_id: str):
        """Return state, diagnostics and a bounded log tail for one owned session."""
        return server._xpra.get(session_id)

    @router.delete("/sessions/{session_id}")
    def delete(session_id: str):
        """Stop and delete one owned session without touching other services."""
        return server._xpra.delete(session_id)

    @router.post("/sessions/{session_id}/connect", status_code=204)
    def connect(session_id: str, request: Request):
        """Renew an authenticated browser's grant before each connection attempt."""
        server._xpra.socket_path(session_id)
        return browser_access.grant(request, Response(status_code=204))

    @router.get("/sessions/{session_id}/view", response_class=HTMLResponse)
    def viewer(session_id: str, request: Request):
        """Render the automatic viewer; the authenticated preflight resolves the ID."""
        response = HTMLResponse((templates / "xpra_view.html").read_text(encoding="utf-8"),
                                headers={"Cache-Control": "no-store", "Referrer-Policy": "same-origin"})
        return browser_access.grant(request, response)

    @router.api_route("/sessions/{session_id}/client/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def client_asset(session_id: str, path: str, request: Request):
        """Proxy installed HTML5 content to a fixed private socket destination."""
        decoded = unquote(path)
        if any(part in (".", "..") for part in decoded.split("/")) or "\\" in decoded or "\0" in decoded:
            raise XpraError(422, "XPRA_PATH_INVALID", "The requested client path is invalid.", "Open the session display page again.")
        socket_path = server._xpra.socket_path(session_id)
        # Own the connection UI instead of exposing Xpra's separate login flow.
        # Relative locations keep both direct and Master-prefixed URLs intact.
        if path in ("", "index.html", "connect.html"):
            return RedirectResponse("../view", status_code=307)
        local = {"display.html": ("xpra_client.html", "text/html"),
                 "ucagent.js": ("xpra_client.js", "text/javascript")}.get(path)
        if local:
            body = (templates / local[0]).read_bytes()
            return Response(body if request.method == "GET" else b"", media_type=local[1],
                            headers={"Cache-Control": "no-store", "Content-Length": str(len(body)),
                                     "Referrer-Policy": "same-origin"})
        target = "http://localhost/" + quote(path, safe="/")
        if request.url.query:
            target += "?" + request.url.query
        headers = {key: value for key, value in request.headers.items()
                   if key.lower() in ("accept", "accept-encoding", "if-modified-since", "if-none-match", "range")}
        try:
            async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=socket_path),
                                             timeout=aiohttp.ClientTimeout(total=30), auto_decompress=False) as session:
                async with session.request(request.method, target, headers=headers, allow_redirects=False) as upstream:
                    body = await upstream.read()
                    response_headers = {key: value for key, value in upstream.headers.items()
                                        if key.lower() not in ("connection", "transfer-encoding", "keep-alive", "content-length", "set-cookie")}
                    if request.method == "HEAD" and "Content-Length" in upstream.headers:
                        response_headers["Content-Length"] = upstream.headers["Content-Length"]
                    if "Location" in response_headers:
                        location = urlsplit(response_headers["Location"])
                        # Relative redirects retain both CMD and any Master prefix.
                        relative = posixpath.relpath(location.path or "/", posixpath.dirname("/" + path))
                        response_headers["Location"] = relative + ("?" + location.query if location.query else "")
                    return Response(body, status_code=upstream.status, headers=response_headers)
        except (aiohttp.ClientError, TimeoutError, OSError):
            raise XpraError(502, "XPRA_PROXY_UNAVAILABLE", "The Xpra HTML5 service could not be reached.",
                            "Check the session status and log tail, then reconnect or create a new session.") from None

    @router.websocket("/sessions/{session_id}/client/")
    async def client_websocket(websocket: WebSocket, session_id: str):
        """Authenticate the upgrade and relay Xpra without sharing terminal state."""
        if not await authorize_websocket(websocket, server.password, browser_access):
            return
        try:
            socket_path = server._xpra.socket_path(session_id)
        except XpraError as exc:
            await websocket.close(code=4404 if exc.status == 404 else 4503, reason=exc.detail["message"])
            return
        await relay_websocket(websocket, "http://localhost/" + ("?" + websocket.url.query if websocket.url.query else ""),
                              socket_path=socket_path)

    app.include_router(router)
