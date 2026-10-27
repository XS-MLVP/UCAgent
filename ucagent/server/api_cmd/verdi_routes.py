"""Authenticated, on-demand Verdi playback through owned Xpra sessions."""

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import tempfile
import threading
import time

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from ucagent.util.config import Config
from ucagent.util.verdi import render_verdi_playback
from ucagent.util.waveform_viewer import (
    decode_waveform_viewer_token, resolve_latest_waveform_file, WaveformViewerProtocolError,
)
from .xpra import XpraError


def register_verdi_routes(app, server, request_workspace):
    """Register a safe landing page and explicit launch operation within CMD auth."""
    lock = threading.Lock()
    sessions = {}
    server._verdi_files = []

    @app.get("/api/waveform/verdi", response_class=HTMLResponse, tags=["Waveform"])
    def viewer():
        """Open the evidence viewer without starting a process from a GET request."""
        return HTMLResponse('''<!doctype html><meta charset="utf-8">
<title>Verdi waveform</title><p id="status">Opening Verdi…</p>
<button onclick="location.reload()">Retry</button><script>
(async()=>{try{
const response=await fetch(location.pathname+location.search,{method:"POST"});
const data=await response.json();
if(!response.ok)throw Error(JSON.stringify(data.detail||data));
location.replace(new URL(data.viewer_path,location.href));
}catch(error){document.getElementById("status").textContent=error.message;}})();
</script>''', headers={"Cache-Control": "no-store"})

    @app.post("/api/waveform/verdi", tags=["Waveform"])
    def launch(request: Request, wave: str):
        """Resolve workspace evidence and launch or reuse its ready Verdi session."""
        try:
            payload = decode_waveform_viewer_token(wave)
            workspace = Path(request_workspace(request)[0]).resolve()
            if payload["v"] == 1:
                waveform = (workspace / payload["file"]).resolve()
                waveform.relative_to(workspace)
            else:
                waveform = resolve_latest_waveform_file(workspace, payload["test_dir"],
                                                        payload["test_case"], ["fsdb"])
            if waveform is None or not waveform.is_file() or waveform.suffix.lower() != ".fsdb":
                raise HTTPException(404, "Original FSDB not found; rerun the associated test.")
            cfg = getattr(server.pdb.agent, "cfg", None)
            options = cfg.get_value("cmd_api.verdi", Config()) if cfg is not None else Config()
            if not isinstance(options, Config):
                raise HTTPException(503, "cmd_api.verdi must be a configuration mapping.")
            configured = options.get_value("executable", "verdi")
            dbdir = options.get_value("dbdir", "")
            if not isinstance(configured, str) or not configured or not isinstance(dbdir, str):
                raise HTTPException(503, "cmd_api.verdi requires a nonempty executable and a string dbdir.")
            executable = shutil.which(configured)
            if not executable and configured == "verdi" and os.environ.get("VERDI_HOME"):
                executable = shutil.which(str(Path(os.environ["VERDI_HOME"]) / "bin/verdi"))
            if not executable:
                raise HTTPException(503, "Verdi is unavailable; configure cmd_api.verdi.executable on the CMD host.")
            if dbdir:
                database = (workspace / dbdir).resolve()
                database.relative_to(workspace)
                databases = [database]
            else:
                databases = set()
                for path in workspace.rglob("*.daidir/simv.kdb"):
                    path = path.resolve()
                    path.relative_to(workspace)
                    if "KDB=TRUE" in path.read_text(errors="replace"):
                        databases.add(path.parent)
                databases = sorted(databases)
            for database in databases:
                database.relative_to(workspace)
                manifest = (database / "simv.kdb").resolve()
                manifest.relative_to(workspace)
                if not manifest.is_file() or "KDB=TRUE" not in manifest.read_text(errors="replace"):
                    raise HTTPException(409, "The selected design database was not compiled with VCS -kdb.")
            if len(databases) != 1:
                raise HTTPException(409, "Provide one VCS -kdb design database, or set cmd_api.verdi.dbdir to its workspace-relative .daidir path.")
            stamp = waveform.stat()
            key = hashlib.sha256(json.dumps([str(workspace), wave, str(waveform), stamp.st_mtime_ns,
                                             stamp.st_size, str(databases[0])]).encode()).hexdigest()
            with lock:
                current = sessions.get(key)
                if current:
                    try:
                        server._xpra.socket_path(current)
                        return {"viewer_path": f"../xpra/sessions/{current}/view"}
                    except XpraError:
                        sessions.pop(key, None)
                with ExitStack() as resources:
                    temporary = resources.enter_context(tempfile.TemporaryDirectory(prefix="ucagent-verdi-"))
                    directory = Path(temporary)
                    playback = directory / "view.tcl"
                    playback.write_text(render_verdi_playback(waveform, payload, directory), encoding="utf-8")
                    session = server._xpra.create(
                        command=shlex.join([executable, "-dbdir", str(databases[0]), "-logdir", str(directory / "logs"), "-play", str(playback)]),
                        name=f"Verdi: {waveform.stem}", cwd=str(workspace), idle_timeout=-1)
                    timeout = cfg.get_value("cmd_api.xpra.startup_timeout", 20) if cfg else 20
                    deadline = time.monotonic() + timeout
                    try:
                        while not (directory / "ready.txt").is_file():
                            if (directory / "error.txt").is_file():
                                raise HTTPException(502, (directory / "error.txt").read_text()[:1000])
                            server._xpra.socket_path(session["id"])
                            if time.monotonic() >= deadline:
                                raise HTTPException(504, "Verdi did not load the waveform in time; check the license, design database and CMD host environment.")
                            time.sleep(.1)
                    except Exception:
                        server._xpra.delete(session["id"])
                        raise
                    sessions[key] = session["id"]
                    server._verdi_files.append(resources.pop_all())
                    return {"viewer_path": f"../xpra/sessions/{session['id']}/view"}
        except (WaveformViewerProtocolError, ValueError) as error:
            raise HTTPException(400, str(error)) from None
        except XpraError as error:
            raise HTTPException(error.status, error.detail) from None
        except OSError:
            raise HTTPException(500, "Unable to read waveform or design database files.") from None
