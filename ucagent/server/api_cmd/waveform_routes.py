"""Metadata-based waveform dispatch and configured, owned Xpra application launches."""

import hashlib
import inspect
import json
from pathlib import Path
import shlex
import sys
import threading
from typing import Literal
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr, TypeAdapter, ValidationError

import ucagent
from ucagent.util.config import Config
from ucagent.util.waveform_viewer import (
    WAVEFORM_METADATA_LOCK, WaveformMetadataIntegrityError, build_waveform_metadata, build_waveform_viewer_url,
    load_waveform_metadata, resolve_workspace_path, write_waveform_metadata,
)
from .xpra import XpraError
from .xpra_routes import _XpraRoute


class _WebViewer(BaseModel):
    """A same-origin viewer page that consumes the canonical meta query argument."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["web"]
    url: StrictStr


class _XpraViewer(BaseModel):
    """Trusted operator configuration for an application launcher and its argv."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["xpra"]
    script: StrictStr = Field(min_length=1)
    args: list[StrictStr] = Field(default_factory=lambda: ["--meta", "{wave_meta}"])
    env: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    idle_timeout: int = Field(default=-1, strict=True, ge=-1, le=4_294_967)


class _MetadataRequest(BaseModel):
    """Create ordinary viewing metadata for one explicitly selected waveform."""
    model_config = ConfigDict(extra="forbid")
    waveform_file: StrictStr


_DEFAULT_VIEWERS = {
    "fst": {"kind": "web", "url": "/surfer/"},
    "vcd": {"kind": "web", "url": "/surfer/"},
    "fsdb": {"kind": "xpra", "script": "verdi/launch_verdi.py",
             "args": ["--meta", "{wave_meta}", "--verdi", "verdi"]},
}


class WaveformLaunch:
    """Resolve viewer configuration and coalesce launches using the existing Xpra owner."""

    def __init__(self, server, request_workspace):
        """Keep service-scoped locks, session identities and the workspace resolver."""
        self.server = server
        self.request_workspace = request_workspace
        self.lock = threading.RLock()
        self.sessions = {}

    def viewers(self):
        """Validate the resolved mapping without probing optional application dependencies."""
        cfg = getattr(self.server.pdb.agent, "cfg", None)
        section = cfg.get_value("cmd_api", None) if cfg is not None else None
        value = section.get_value("waveform_viewers", _DEFAULT_VIEWERS) if section is not None else _DEFAULT_VIEWERS
        if isinstance(value, Config):
            value = value.as_dict()
        try:
            if not isinstance(value, dict) or any(not isinstance(key, str) or not key.isascii()
                    or not key or not key[0].isalpha() or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in key) for key in value):
                raise ValueError("format names must be lowercase extensions without dots")
            result = TypeAdapter(dict[str, _WebViewer | _XpraViewer]).validate_python(value)
            for viewer in result.values():
                if isinstance(viewer, _WebViewer):
                    url = urlsplit(viewer.url)
                    if (not viewer.url.startswith("/") or viewer.url.startswith("//") or url.netloc
                            or url.query or url.fragment or url.scheme or "\\" in viewer.url
                            or any(part in (".", "..") for part in url.path.split("/"))
                            or any(ord(char) < 33 for char in viewer.url)
                            or "%" in viewer.url or not viewer.url.endswith("/")
                            or url.path.rstrip("/") == "/wave"):
                        raise ValueError("web url must be a same-origin viewer path without a query")
                elif viewer.idle_timeout == 0:
                    raise ValueError("idle_timeout must be -1 or positive")
                elif any("\0" in item for item in [viewer.script, *viewer.args,
                                                   *viewer.env.keys(), *viewer.env.values()]):
                    raise ValueError("launch configuration must not contain NUL characters")
            return result
        except (ValueError, ValidationError):
            raise XpraError(503, "WAVEFORM_VIEWER_CONFIG_INVALID", "The waveform viewer mapping is invalid.",
                            "Correct cmd_api.waveform_viewers and restart the CMD service.") from None

    def metadata(self, meta, request):
        """Read only metadata whose files remain inside the selected workspace."""
        workspace, _, _ = self.request_workspace(request)
        try:
            target, payload = load_waveform_metadata(workspace, meta)
            return Path(workspace).resolve(), target, payload
        except FileNotFoundError as error:
            raise XpraError(404, "WAVEFORM_FILE_MISSING", str(error),
                            "Regenerate the exact waveform and its viewing metadata; then open the newly generated link.") from None
        except WaveformMetadataIntegrityError as error:
            raise XpraError(422, "WAVEFORM_METADATA_INTEGRITY_FAILED", str(error),
                            "Rerun final WaveInfo and ApplyWaveInfoEvidence; for ordinary viewing remove the modified JSON and reopen its waveform.") from None
        except (ValueError, OSError) as error:
            raise XpraError(422, "WAVEFORM_METADATA_INVALID", str(error),
                            "Regenerate metadata using WaveInfo; for ordinary viewing remove the invalid JSON and reopen its waveform.") from None

    def viewer(self, payload):
        """Select only the configured handler for the actual waveform suffix."""
        extension = Path(payload["waveform_file"]).suffix.lower().lstrip(".")
        viewer = self.viewers().get(extension)
        if viewer is None:
            raise XpraError(415, "WAVEFORM_FORMAT_UNCONFIGURED", f"No viewer is configured for '.{extension}'.",
                            f"Configure cmd_api.waveform_viewers.{extension} and reopen this link.")
        return viewer

    def create(self, meta, request):
        """Create or reuse one live, configured Xpra session for exact metadata contents."""
        workspace, target, payload = self.metadata(meta, request)
        viewer = self.viewer(payload)
        if not isinstance(viewer, _XpraViewer):
            raise XpraError(422, "WAVEFORM_XPRA_NOT_CONFIGURED", "This waveform uses a web viewer.",
                            "Open its /wave/?meta= link instead of creating an Xpra session.")
        scripts = Path(inspect.getfile(ucagent)).resolve().parent / "scripts"
        script = Path(viewer.script)
        relative_script = not script.is_absolute()
        try:
            script = (scripts / script if relative_script else script).resolve()
        except (OSError, RuntimeError, ValueError):
            raise XpraError(503, "WAVEFORM_SCRIPT_INVALID", "The waveform launch script path cannot be resolved.",
                            "Correct the configured script path and remove invalid symbolic links.") from None
        if relative_script and not script.is_relative_to(scripts.resolve()):
            raise XpraError(503, "WAVEFORM_SCRIPT_INVALID", "Relative launch scripts must remain inside ucagent/scripts.",
                            "Configure a package-relative script or an explicit absolute script path.")
        if not script.is_file():
            raise XpraError(503, "WAVEFORM_SCRIPT_MISSING", f"Waveform launch script was not found: {script}",
                            "Install the configured script under ucagent/scripts or set its absolute path.")
        args = [argument.replace("{wave_meta}", str(target)) for argument in viewer.args]
        argv = ([sys.executable, str(script)] if script.suffix.lower() == ".py" else [str(script)]) + args
        identity = hashlib.sha256(json.dumps([str(workspace), str(target), payload, viewer.model_dump(), str(script)],
                                            sort_keys=True).encode()).hexdigest()
        # Reserve creation under the same lock: simultaneous tabs share one owned session.
        with self.lock:
            session_id = self.sessions.get(identity)
            if session_id:
                try:
                    self.server._xpra.socket_path(session_id)
                    return self.server._xpra.get(session_id)
                except XpraError:
                    self.sessions.pop(identity, None)
            session = self.server._xpra.create(command=shlex.join(argv), mode="gui",
                name=payload["waveform_file"], cwd=str(workspace.relative_to(Path(self.server.pdb.agent.workspace).resolve())) or ".",
                env=viewer.env, idle_timeout=viewer.idle_timeout)
            self.sessions[identity] = session["id"]
            return session


def register_waveform_routes(app, server, request_workspace):
    """Attach waveform APIs and a side-effect-free dispatch page to the CMD service."""
    launch = WaveformLaunch(server, request_workspace)
    server._waveform_launch = launch
    router = APIRouter(route_class=_XpraRoute, tags=["Waveform"])

    @router.get("/api/waveform/viewers")
    def formats():
        """Expose configured extensions for file-browser viewing actions."""
        return JSONResponse({"formats": list(launch.viewers())}, headers={"Cache-Control": "no-store"})

    @router.get("/api/waveform/metadata")
    def metadata(meta: str, request: Request):
        """Return validated metadata for the viewer without rewriting its stored paths."""
        _, _, payload = launch.metadata(meta, request)
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @router.post("/api/waveform/metadata")
    def create_metadata(body: _MetadataRequest, request: Request):
        """Create missing ordinary metadata, preserving any existing final-evidence settings."""
        workspace, _, _ = request_workspace(request)
        cfg = getattr(server.pdb.agent, "cfg", None)
        try:
            wave = resolve_workspace_path(workspace, body.waveform_file)
            meta = wave.relative_to(Path(workspace).resolve()).as_posix() + ".json"
            with launch.lock, WAVEFORM_METADATA_LOCK:
                if (Path(workspace) / meta).is_file():
                    _, payload = load_waveform_metadata(workspace, meta)
                    launch.viewer(payload)
                else:
                    dut_name = getattr(server.pdb.agent, "dut_name", "")
                    if Path(workspace).resolve() != Path(server.pdb.agent.workspace).resolve():
                        from ucagent.util.config import load_runtime_config
                        dut_name = load_runtime_config(workspace)["DUT"]
                    _, payload, _ = build_waveform_metadata(workspace, body.waveform_file, dut_name=dut_name)
                    launch.viewer(payload)
                    # Evaluate the service's restrictions against its actual root path,
                    # including a selected child workspace rather than a bare child path.
                    from ucagent.tools.fileops import is_file_writeable
                    policy_path = (Path(workspace) / meta).relative_to(Path(server.pdb.agent.workspace).resolve()).as_posix()
                    allowed, reason = is_file_writeable(policy_path,
                        cfg.get_value("un_write_dirs", None) if cfg is not None else None,
                        cfg.get_value("write_dirs", None) if cfg is not None else None)
                    if not allowed:
                        raise PermissionError(reason)
                    write_waveform_metadata(workspace, meta, payload)
            return {"meta": meta, "url": build_waveform_viewer_url(meta)}
        except FileNotFoundError as error:
            raise XpraError(404, "WAVEFORM_FILE_MISSING", str(error), "Select an existing waveform in this workspace.") from None
        except WaveformMetadataIntegrityError as error:
            raise XpraError(422, "WAVEFORM_METADATA_INTEGRITY_FAILED", str(error),
                            "Rerun final WaveInfo and ApplyWaveInfoEvidence; for ordinary viewing remove the modified JSON and reopen its waveform.") from None
        except (ValueError, OSError) as error:
            raise XpraError(422, "WAVEFORM_METADATA_CREATE_FAILED", str(error), "Correct the waveform path or metadata write permissions.") from None

    @router.get("/wave/", response_class=HTMLResponse)
    def dispatch(meta: str, request: Request):
        """Choose a configured viewer; GET never starts an application."""
        _, _, payload = launch.metadata(meta, request)
        viewer = launch.viewer(payload)
        query = {"meta": meta}
        sub = request.query_params.get("sub_worspace") or request.query_params.get("sub_workspace")
        if sub:
            query["sub_worspace"] = sub
        if isinstance(viewer, _WebViewer):
            return RedirectResponse(".." + viewer.url + "?" + urlencode(query), status_code=303,
                                    headers={"Cache-Control": "no-store"})
        return HTMLResponse((Path(__file__).resolve().parents[1] / "templates" / "wave.html").read_text(encoding="utf-8"),
                            headers={"Cache-Control": "no-store"})

    app.include_router(router)
