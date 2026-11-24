"""Serializable local view over an existing Super runtime."""
from pathlib import Path
import copy
import threading
import time
from uuid import uuid4
from ucagent.runtime.agent_events import AgentEvents, atomic_json
from ucagent.runtime.control.commands import CommandSession
from ucagent.runtime.control.controller import ControlError
from ucagent.util.output import AGENT_ACTOR, OUTPUT_RECORDED, OUTPUT_METADATA

class LocalAgentView:
    def __init__(self, host, root, agent_id, attempt=1):
        self.host, self.root, self.agent_id, self.attempt = host, Path(root), agent_id, attempt
        self.events = AgentEvents(self.root / "view")
        self.inputs = []
        self._details_at = 0.0
        self._details = {}
        self._attention_id = None
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.session = CommandSession(Path(host.agent.workspace))
        self.host.messages.subscribe(self._message)
        self.host.output.subscribe(self._console)
        self.thread = threading.Thread(target=self._pump, daemon=True, name="ucagent-session-view")
        self.thread.start()

    def _message(self, text):
        actor = AGENT_ACTOR.get() or {"agent_id": self.agent_id, "parent_id": "global"}
        metadata = OUTPUT_METADATA.get()
        worker_result = (actor.get("role") == "sub" and metadata.get("source") == "tool"
                         and metadata.get("kind") == "result")
        kind = "tool_detail" if metadata.get("kind") == "detail" or worker_result else "message"
        for offset in range(0, len(text), 16384):
            self.events.append(actor["agent_id"], kind, attempt=self.attempt,
                               worker_attempt=actor.get("worker_attempt"),
                               parent_id=actor.get("parent_id"), text=text[offset:offset + 16384])

    def _console(self, text):
        # Model messages already have a dedicated event; retain the original log echo.
        if OUTPUT_RECORDED.get(): return
        actor = AGENT_ACTOR.get() or {"agent_id": self.agent_id, "parent_id": "global"}
        for offset in range(0, len(text), 16384):
            self.events.append(actor["agent_id"], "console", attempt=self.attempt,
                               worker_attempt=actor.get("worker_attempt"), parent_id=actor.get("parent_id"),
                               text=text[offset:offset + 16384])

    def snapshot(self):
        host, agent = self.host, self.host.agent
        state = host.snapshot()
        stages = host.operations.stages.snapshot() if host.operations.stages else {"stages": [], "stage_index": 0}
        multi = getattr(agent, "multi_agent", None)
        children = []
        if multi:
            tasks = multi.status()["tasks"]
            views = multi.worker_snapshots()
            for item in tasks:
                children.append({**item, **views.get(item["task_id"], {}), "agent_id": f"{self.agent_id}/attempt-{self.attempt}/{item['task_id']}",
                                 "parent_id": self.agent_id, "role": "sub", "status": item["state"]})
        with self.lock:
            if time.monotonic() - self._details_at >= 1:
                self._details = {"mission": host.controller.mission_info(),
                                 "statistics": host.controller.status(),
                                 "backend": agent.cfg.get_value("backend.key_name", "unknown"),
                                 "use_skills": agent.cfg.get_value("skill.use_skill", False),
                                 "commands": [{"name": row["name"], "aliases": row["aliases"]} for row in host.registry.describe()],
                                 "changed_files": host.controller.changed_files(count=5),
                                 "tools": [{key: row[key] for key in ("name", "call_count", "is_hot")}
                                           for row in host.controller.tool_list()]}
                self._details_at = time.monotonic()
            details = copy.deepcopy(self._details)
            inputs = copy.deepcopy(self.inputs[-100:])
        return {"agent_id": self.agent_id, "role": "super", "attempt": self.attempt,
                "parent_id": "global", "workflow_ref": getattr(agent, "plugin_workflow", ""),
                "status": state["task_outcome"] or state["execution"], "execution": state["execution"],
                "instance": state["instance"], **stages, **details, "children": children, "inputs": inputs,
                "recovery": multi.recovery_status() if multi else {},
                "instructions": copy.deepcopy(multi.operator_instructions[-100:]) if multi else [],
                "operations": [{k: r[k] for k in ("id", "command", "state", "model")} for r in host.operations.list()[-100:]]}

    def events_since(self, cursor=0):
        return self.events.read(cursor)

    def submit_input(self, text, *, command=False):
        if not text.strip() or len(text) > 32000: raise ValueError("Input must contain 1..32000 characters")
        if self.host.snapshot()["instance"] != "ready" or self.host.agent.is_exit():
            raise ValueError("Agent has finished; start or retry a task")
        multi = getattr(self.host.agent, "multi_agent", None)
        if not command and multi:
            return multi.queue_instruction(text)
        with self.lock:
            item = {"id": uuid4().hex, "text": text, "command": command, "state": "queued"}
            self.inputs.append(item)
            return copy.deepcopy(item)

    def recover(self, request):
        """Use the runtime controller for the same recovery contract as Console."""
        if self.host.snapshot()["instance"] != "ready":
            raise ValueError("Agent process has ended; use retry instead")
        return self.host.controller.workflow_recover(request)

    def review(self, issue_id, index, expected_revision, message):
        """Approve the displayed stage version before requesting ordinary recovery."""
        service = getattr(self.host.agent, "multi_agent", None)
        if service is None or not service.issue or service.issue["id"] != issue_id or service.issue["kind"] != "review":
            raise ValueError("Review changed; refresh the task before approving")
        self.host.controller.review_stage(index, expected_revision, True, message)
        if "grant" in service.recovery_status()["actions"]:
            return {"reviewed": True, "next_action": "Add execution budget to continue"}
        return self.recover({"issue_id": issue_id, "action": "resume", "message": message})

    def cancel_operation(self):
        operation = self.host.operations._model_id
        if operation: return self.host.operations.cancel(operation)
        self.host.pause()
        return {"state": "paused"}

    def _pump(self):
        while not self.stop.wait(.1):
            try:
                self.pump()
                snapshot = self.snapshot()
                issue = snapshot.get("recovery", {}).get("issue")
                identity = issue["id"] if issue else None
                if identity != self._attention_id:
                    self.events.append(self.agent_id, "attention", text=(issue["summary"] + "\n" + issue["next_action"]) if issue else "Workflow resumed.")
                    self._attention_id = identity
                atomic_json(self.root / "view_snapshot.json", snapshot)
            except Exception as error:
                self.events.append(self.agent_id, "view_error", error=str(error)[:1000])

    def pump(self):
        if self.host.snapshot()["instance"] != "ready": return
        with self.lock:
            for item in self.inputs:
                if item["state"] == "running":
                    row = self.host.operations.get(item["operation_id"])
                    if row["state"] not in {"succeeded", "failed", "cancelled"}: return
                    item.update(state="delivered" if row["state"] == "succeeded" else row["state"], error=row.get("error"))
                if item["state"] != "queued": continue
                try:
                    if item["command"]:
                        # Reuse the same command policy and model/stage reservation as the local console.
                        result = self.host.registry.submit(item["text"], self.session)
                        data = result.data if result else {}
                        item.update(state="running" if isinstance(data, dict) and data.get("id") else "delivered")
                        if item["state"] == "running": item["operation_id"] = data["id"]
                        self.events.append(self.agent_id, "console", text=str(data))
                    else:
                        def run(context, text=item["text"]):
                            context.checkpoint()
                            self.host.agent.one_loop(text)
                            return {"reason": "round_complete"}
                        row = self.host.operations.submit("agent_message", run, model=True)
                        item.update(state="running", operation_id=row["id"])
                except ControlError as error:
                    if error.code == "busy": return
                    item.update(state="failed", error=str(error))
                return

    def close(self):
        self.stop.set()
        if self.thread is not threading.current_thread(): self.thread.join(2)
        atomic_json(self.root / "view_snapshot.json", self.snapshot())
        self.host.messages.unsubscribe(self._message)
        self.host.output.unsubscribe(self._console)
