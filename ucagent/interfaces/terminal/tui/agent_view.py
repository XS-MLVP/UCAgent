"""Agent page adapters over live transport and persisted run history."""
import json
from pathlib import Path
from ucagent.interfaces.server.agent_session import RemoteAgentView, SavedAgentView

class SuperAgentView:
    def __init__(self, run_provider, agent_id):
        self.run_provider, self.agent_id = run_provider, agent_id
        self._last = {}

    def run(self): return self.run_provider(self.agent_id)

    def _view(self):
        run = self.run()
        result = run.get("result_path")
        if not result: return None
        root = Path(result).parent
        if (root / "connection.json").is_file() and run["status"] not in {"succeeded", "failed", "cancelled"}:
            return RemoteAgentView(root)
        return SavedAgentView(root)

    def snapshot(self):
        run = self.run()
        view = self._view()
        if self._last.get("attempt") != run["attempt"]: self._last = {}
        connected = False
        if view:
            try:
                self._last = view.snapshot()
                connected = isinstance(view, RemoteAgentView)
            except (OSError, ValueError): pass
        return {**self._last, **run, "connected": connected,
                "readonly": not connected or run["status"] in {"succeeded", "failed", "cancelled"},
                "stream_id": f"{run['agent_id']}/attempt-{run['attempt']}"}

    def events_since(self, cursor=0):
        view = self._view()
        if view is None: return {"events": [], "cursor": cursor}
        try: return view.events_since(cursor)
        except (OSError, ValueError):
            return SavedAgentView(Path(self.run()["result_path"]).parent).events_since(cursor)

    def submit_input(self, text, *, command=False):
        view = self._view()
        if view is None: raise ValueError("Super is queued; wait for it to start")
        return view.submit_input(text, command=command)

    def review(self, issue_id, index, expected_revision, message):
        """Pass the displayed review identity to the existing session."""
        view = self._view()
        if view is None: raise ValueError("Super is not ready")
        return view.review(issue_id, index, expected_revision, message)

    def recover(self, request):
        """Recover only through a live session; saved history remains read-only."""
        view = self._view()
        if view is None: raise ValueError("Super is not ready")
        return view.recover(request)

    def cancel_operation(self):
        view = self._view()
        if view is None: raise ValueError("Super is not running")
        return view.cancel_operation()

class SubAgentView:
    def __init__(self, parent, agent_id):
        self.parent, self.agent_id = parent, agent_id
        self.worker_attempt = 1
    def snapshot(self):
        parent = self.parent.snapshot()
        child = next((x for x in parent.get("children", []) if x["agent_id"] == self.agent_id), {})
        self.worker_attempt = child.get("attempt", 1)
        return {**child, "role": "sub", "agent_id": self.agent_id, "children": [],
                "parent_id": self.parent.agent_id, "workflow_ref": parent.get("workflow_ref", ""),
                "readonly": parent["readonly"], "connected": parent.get("connected", False),
                "parent_recovery": parent.get("recovery", {}),
                "stream_id": f"{parent['stream_id']}/worker-attempt-{self.worker_attempt}"}
    def events_since(self, cursor=0):
        page = self.parent.events_since(cursor)
        return {**page, "events": [r for r in page["events"] if r["agent_id"] == self.agent_id
                and r["payload"].get("worker_attempt", 1) == self.worker_attempt]}
    def submit_input(self, text, *, command=False):
        if command: raise ValueError("Run control commands from the parent Super page")
        return self.parent.submit_input(f"Regarding Sub {self.agent_id}: {text}")
    def cancel_operation(self): raise ValueError("Cancel or pause work from the parent Super page")

class DiskRunProvider:
    def __init__(self, directory): self.directory = Path(directory).resolve()
    def __call__(self, agent_id):
        data = json.loads((self.directory / "session.json").read_text())
        run = data["agents"].get(agent_id)
        if run is None: raise ValueError("Unknown Agent ID in this session")
        return {k: v for k, v in run.items() if k not in {"spec", "history", "request_id"}}
