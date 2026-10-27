"""Dispatch validated waveform JSON to unchanged browser or GUI viewers."""

import hashlib
import json
from pathlib import Path
import shlex
import sys
import tempfile
import threading
import time
from urllib.parse import urlencode

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from ucagent.util.waveform_formats import DEFAULT_WAVEFORM_ANALYSIS_FORMAT_PRIORITY
from ucagent.util.waveform_viewer import (
    decode_waveform_viewer_token, encode_waveform_viewer_payload,
    normalize_waveform_test_dir, normalize_waveform_viewer_payload, resolve_latest_waveform_file,
)
from .xpra import XpraError


def register_wave_routes(app, server, request_workspace):
    """Register a single authenticated dispatcher; only POST may launch a tool."""
    scripts = Path(__file__).resolve().parents[2] / "scripts" / "sim"
    lock = threading.Lock()
    sessions = {}
    server._wave_files = []

    @app.get("/wave/", response_class=HTMLResponse, tags=["Waveform"])
    def viewer():
        """Open a proxy-relative landing page without launching a process on GET."""
        return HTMLResponse('''<!doctype html><meta charset="utf-8">
<title>Waveform</title><p id="status">Opening waveform…</p>
<button onclick="location.reload()">Retry</button><script>
(async()=>{try{
const response=await fetch(location.pathname+location.search,{method:"POST"});
const data=await response.json();
if(!response.ok)throw Error(JSON.stringify(data.detail||data));
location.replace(new URL(data.viewer_path,location.href));
}catch(error){document.getElementById("status").textContent=error.message;}})();
</script>''', headers={"Cache-Control": "no-store"})

    @app.post("/wave/", tags=["Waveform"])
    def launch(request: Request, wave: str | None = None, config: str | None = None):
        """Resolve a token or workspace JSON file and dispatch through trusted presets."""
        try:
            workspace_root, workspace_rel, _ = request_workspace(request)
            workspace = Path(workspace_root).resolve()
            if (wave is None) == (config is None):
                raise ValueError("Provide exactly one of wave or config")
            if config is not None:
                manifest = (workspace / normalize_waveform_test_dir(config)).resolve()
                manifest.relative_to(workspace)
                with manifest.open("rb") as stream:
                    raw = stream.read(65537)
                if len(raw) > 65536:
                    raise ValueError("Waveform JSON must not exceed 64 KiB")
                payload = normalize_waveform_viewer_payload(json.loads(raw))
            else:
                if len(wave) > 65536:
                    raise ValueError("Waveform token must not exceed 64 KiB")
                payload = decode_waveform_viewer_token(wave)
            agent = server.pdb.agent
            if payload["v"] == 1:
                waveform = (workspace / payload["file"]).resolve()
                waveform.relative_to(workspace)
            else:
                waveform = resolve_latest_waveform_file(
                    workspace, payload["test_dir"], payload["test_case"],
                    getattr(getattr(agent, "tool_waveinfo", None), "format_priority",
                            DEFAULT_WAVEFORM_ANALYSIS_FORMAT_PRIORITY))
            if waveform is None or not waveform.is_file():
                raise HTTPException(404, "Waveform not found; rerun the associated test")
            defaults = json.loads((scripts / "viewers.json").read_text(encoding="utf-8"))
            cfg = getattr(agent, "cfg", None)
            options = cfg.as_dict().get("cmd_api", {}).get("wave", {}).get("viewers", defaults) if cfg else defaults
            preset = options.get(waveform.suffix.lower().lstrip(".")) if isinstance(options, dict) else None
            if not isinstance(preset, dict):
                raise HTTPException(503, "No configured viewer for this waveform format")
            resolved = {key: value for key, value in payload.items()
                        if key in ("start", "end", "cursor", "signals")}
            if preset.get("viewer") == "surfer":
                token = encode_waveform_viewer_payload(
                    {"v": 1, "file": waveform.relative_to(workspace).as_posix(), **resolved})
                query = {"wave": token}
                if workspace_rel:
                    query["sub_worspace"] = workspace_rel
                return {"viewer_path": "../surfer/?" + urlencode(query)}
            command = preset.get("command")
            if preset.get("viewer") != "xpra" or not isinstance(command, list) or not command or any(
                    not isinstance(arg, str) or not arg for arg in command):
                raise HTTPException(503, "Configure a viewer and a nonempty command argument list")
            resolved["file"] = str(waveform)
            if "daidir" in payload:
                database = (workspace / payload["daidir"]).resolve()
                database.relative_to(workspace)
                if not database.is_dir():
                    raise HTTPException(404, "Design database directory not found")
                for candidate in database.rglob("*"):
                    if candidate.is_symlink():
                        candidate.resolve().relative_to(workspace)
                resolved["daidir"] = str(database)
            elif preset.get("database_glob"):
                databases = set()
                for candidate in workspace.rglob(preset["database_glob"]):
                    candidate = candidate.resolve()
                    candidate.relative_to(workspace)
                    if candidate.is_file():
                        databases.add(candidate.parent)
                if len(databases) != 1:
                    raise HTTPException(409, "Provide daidir in the waveform JSON to select one design database")
                resolved["daidir"] = str(databases.pop())
            stamp = waveform.stat()
            identity = [str(workspace), resolved, preset, stamp.st_mtime_ns, stamp.st_size]
            key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            with lock:
                current = sessions.get(key)
                if current:
                    try:
                        server._xpra.socket_path(current)
                        return {"viewer_path": f"../api/xpra/sessions/{current}/view"}
                    except XpraError:
                        sessions.pop(key, None)
                directory = tempfile.TemporaryDirectory(prefix="ucagent-wave-")
                output = Path(directory.name)
                session = None
                try:
                    context = {**resolved, "scripts": str(scripts), "output": str(output)}
                    manifest = output / "wave.json"
                    manifest.write_text(json.dumps({**resolved, "command": [arg.format_map(context) for arg in command]}), encoding="utf-8")
                    session = server._xpra.create(
                        command=shlex.join([sys.executable, str(scripts / "launch.py"), str(manifest)]),
                        name=f"Waveform: {waveform.stem}", cwd=str(workspace), idle_timeout=-1)
                    deadline = time.monotonic() + (cfg.get_value("cmd_api.xpra.startup_timeout", 20) if cfg else 20)
                    while not (output / "ready.txt").is_file():
                        if (output / "error.txt").is_file():
                            raise HTTPException(502, (output / "error.txt").read_text(encoding="utf-8")[:1000])
                        server._xpra.socket_path(session["id"])
                        if time.monotonic() >= deadline:
                            raise HTTPException(504, "Viewer startup timed out; check the CMD host and viewer log")
                        time.sleep(.1)
                    sessions[key] = session["id"]
                    server._wave_files.append(directory)
                    return {"viewer_path": f"../api/xpra/sessions/{session['id']}/view"}
                except Exception:
                    try:
                        if session is not None:
                            server._xpra.delete(session["id"])
                    finally:
                        directory.cleanup()
                    raise
        except (ValueError, KeyError) as error:
            raise HTTPException(400, str(error)) from None
        except XpraError as error:
            raise HTTPException(error.status, error.detail) from None
        except OSError:
            raise HTTPException(404, "Unable to read waveform configuration or artifacts") from None
