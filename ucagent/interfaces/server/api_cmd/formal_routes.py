"""Expose the optional Formal dashboard through the selected command workspace."""

from importlib import import_module
from pathlib import Path

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict

from ucagent.core.plugins import PluginError, configured_plugin_search_paths, load_plugin


class FormalTraceBody(BaseModel):
    """Select one run property and its bounded trace query."""

    model_config = ConfigDict(extra="forbid")
    scope: str
    run_id: str
    property: str
    query: dict


def register_formal_routes(app, agent, request_workspace):
    """Bind the plugin read view and live proof actions to workspace access."""

    def provider(request):
        """Resolve a trusted plugin from the server installation, never the task files."""
        workspace, _, archived = request_workspace(request)
        tool = None if archived else agent.get_tool_by_name("RunFormal")
        try:
            try:
                module = import_module("formal.dashboard")
            except ModuleNotFoundError as exc:
                if exc.name != "formal":
                    raise
                project = Path(__file__).resolve().parents[3] / "plugins" / "Formal"
                if project.is_dir():
                    load_plugin(str(project), check_dependencies=False)
                else:
                    load_plugin("formal", search_paths=configured_plugin_search_paths(agent.cfg), check_dependencies=False)
                module = import_module("formal.dashboard")
            return module.FormalDashboard(workspace, archived=archived or tool is None, cfg=getattr(tool, "_cfg", None)), tool
        except (FileNotFoundError, PluginError, ModuleNotFoundError) as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, OSError, TypeError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/formal/view")
    def view(request: Request, scope: str = "full", run_id: str | None = None):
        """Read a versioned Formal projection for the selected workspace."""
        dashboard, _ = provider(request)
        try:
            return {"status": "ok", "data": dashboard.view(scope, run_id)}
        except (ValueError, OSError, TypeError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/formal/trace")
    def trace(body: FormalTraceBody, request: Request):
        """Read a verified Formal VCD page with the same contract used by RunFormal."""
        dashboard, _ = provider(request)
        query = import_module("formal.trace").TraceQuery
        try:
            return {"status": "ok", "data": dashboard.trace(
                body.scope, body.run_id, body.property, query.model_validate(body.query))}
        except (ValueError, OSError, TypeError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/formal/compare")
    def compare(request: Request, before_id: str, before_scope: str, after_id: str, after_scope: str):
        """Compare frozen inputs and matching Cover properties."""
        dashboard, _ = provider(request)
        try:
            return {"status": "ok", "data": dashboard.compare(before_id, before_scope, after_id, after_scope)}
        except (ValueError, OSError, TypeError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/formal/action")
    def action(body: dict, request: Request):
        """Submit explicit proof actions to the live workspace's public tool."""
        _, tool = provider(request)
        if tool is None:
            raise HTTPException(403, "Proof actions require a live Formal agent.")
        operation = body.get("action")
        if not (operation in ("review", "cancel") and body.get("run_id")
                or operation == "run" and body.get("scope") == "selected"):
            raise HTTPException(422, "Select an exact batch or an explicit selected run.")
        try:
            result = tool.invoke(body)
            if result.get("status") == "error":
                raise HTTPException(422, {"message": result["error"], "diagnostics": result.get("diagnostics", [])})
            return {"status": "ok", "data": result}
        except (ValueError, OSError, TypeError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc
