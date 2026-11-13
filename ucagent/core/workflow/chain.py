"""Server-owned chain decisions, cumulative budgets and immutable successor identities."""

import copy
import hashlib
import json
from pathlib import Path
import threading
import time
from uuid import uuid4

from .contracts import NextWorkflow, EndChain, source_file, workflow_fingerprint


class WorkflowChain:
    """Retain policy and accepted decisions independently of retiring Agent instances."""

    def __init__(self, catalog, workflow_ref, workspace, *, goal="", persist=None, state=None):
        """Create a new chain or restore trusted checkpoint data through an injected writer."""
        self.catalog = catalog
        self.settings = catalog.settings
        self.lock = threading.RLock()
        self.persist = persist or (lambda data: None)
        self.state = state or {"schema": 1, "chain_id": uuid4().hex, "goal": goal,
            "instructions": [], "status": "running", "runs": [], "events": []}
        if state is None:
            self.state["runs"].append(self.new_run(workflow_ref, workspace))
        self.save()

    def new_run(self, workflow_ref, workspace, *, run_id=None):
        """Allocate one server-owned workflow run and its non-resetting decision counters."""
        entry = self.catalog.entries[workflow_ref]
        return {"run_id": run_id or uuid4().hex, "workflow_ref": workflow_ref,
                "workspace": str(Path(workspace).resolve()), "business_status": "pending",
                "fingerprint": workflow_fingerprint(entry, self.settings.target_configs.get(workflow_ref)),
                "attempts": 0, "decision": {"backend_turns": 0, "tool_calls": 0, "deadline": None},
                "transition": None, "history": [], "input_manifest": [], "accepted_artifacts": {}}

    @property
    def current(self):
        """Return the committed current run; a pending candidate is never current."""
        return self.state["runs"][-1]

    def save(self):
        """Publish a detached checkpoint through the single chain writer."""
        with self.lock:
            self.persist(copy.deepcopy(self.state))

    def event(self, kind, **data):
        """Keep lifecycle evidence free of backend connection settings."""
        with self.lock:
            self.state["events"].append({"event": kind, "time": time.time(), **data})
            self.save()

    def view(self):
        """Expose state without decision tokens, credential paths or executable configuration."""
        with self.lock:
            result = copy.deepcopy(self.state)
            for run in result["runs"]:
                for transition in [run.get("transition"), *run.get("history", [])]:
                    if transition:
                        transition.pop("token", None)
            return result

    def candidates(self, run):
        """Return only permitted edges, explaining policy and dependency unavailability."""
        visited = {r["workflow_ref"] for r in self.state["runs"]}
        result = []
        for ref in self.settings.allowed_next[run["workflow_ref"]]:
            item = self.catalog.entries[ref].describe()
            if not self.settings.allow_revisit and ref in visited:
                item["unavailable"] = "Workflow revisits are disabled"
            if len(self.state["runs"]) >= self.settings.max_runs:
                item["unavailable"] = "Chain run budget exhausted"
            result.append(item)
        return result

    def charge(self, run, field):
        """Persist consumed decisions before execution so retries and restarts cannot reset them."""
        with self.lock:
            budget = run["decision"]
            if budget["deadline"] is None:
                budget["deadline"] = time.time() + self.settings.decision_limits.timeout_seconds
            limit = getattr(self.settings.decision_limits, field)
            if time.time() >= budget["deadline"] or budget[field] >= limit:
                self.state["status"] = "paused"
                self.save()
                raise RuntimeError("Workflow handoff decision budget exhausted; operator intervention required")
            budget[field] += 1
            self.save()

    def accept(self, run, request):
        """Accept one explicit Super decision; exact replays return its existing identity."""
        with self.lock:
            if run is not self.current or run["business_status"] != "completed":
                raise PermissionError("Only the current completed run may hand off")
            raw = request.model_dump(exclude={"transition_token"})
            fingerprint = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
            existing = run["transition"]
            if existing is not None:
                if existing["token"] == request.transition_token and existing["request_hash"] == fingerprint:
                    return {"accepted": True, "transition_id": existing["transition_id"], "status": existing["status"]}
                raise PermissionError("A decision already exists for this run and token")
            if self.state["status"] != "running":
                raise PermissionError("The workflow chain is paused or closed")
            manifest = []
            attempts_before = run["attempts"]
            kind = "next" if isinstance(request, NextWorkflow) else "complete"
            if kind == "next":
                if len(self.state["runs"]) >= self.settings.max_runs or run["attempts"] >= self.settings.max_start_attempts:
                    raise ValueError("Chain run or startup-attempt budget exhausted")
                self.catalog.select(run["workflow_ref"], request, [r["workflow_ref"] for r in self.state["runs"]])
                declared = self.catalog.entries[run["workflow_ref"]].workflow.outputs
                if set(request.inputs.values()) - set(declared):
                    raise ValueError("Handoff sources must be declared workflow output artifacts")
                for target, relative in request.inputs.items():
                    path = source_file(run["workspace"], relative)
                    data = path.read_bytes()
                    if hashlib.sha256(data).hexdigest() != run["accepted_artifacts"].get(relative):
                        raise ValueError("Handoff source differs from its accepted business artifact")
                    manifest.append({"source_run_id": run["run_id"], "source": relative, "target": target,
                                     "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
                run["attempts"] += 1
            transition = {"transition_id": uuid4().hex, "token": request.transition_token,
                          "request_hash": fingerprint, "kind": kind, "status": "accepted", "request": raw,
                          "target_run_id": uuid4().hex if kind == "next" else None,
                          "manifest": manifest}
            run["transition"] = transition
            event_count = len(self.state["events"])
            try:
                self.event("decision_accepted", run_id=run["run_id"], transition_id=transition["transition_id"], decision_kind=kind)
            except BaseException:
                run["transition"] = None
                run["attempts"] = attempts_before
                del self.state["events"][event_count:]
                raise
            return {"accepted": True, "transition_id": transition["transition_id"], "status": "accepted"}

    def failed(self, run, error):
        """Reopen decision admission only after a failed candidate has actually been cleaned up."""
        with self.lock:
            transition = run["transition"]
            if transition["status"] in {"committed", "retired", "activated"}:
                raise RuntimeError("A committed successor cannot be replaced")
            transition.update(status="failed", error=error)
            run["history"].append(transition)
            run["transition"] = None
            self.event("candidate_failed", run_id=run["run_id"], error=error)


class HandoffDecision:
    """Bind a Super to its own run; old endpoints never acquire the next run's authority."""

    def __init__(self, chain, run):
        """Retain immutable service ownership even when the chain's active run changes."""
        self.chain = chain
        self.run = run

    def record_artifacts(self):
        """Snapshot declared output digests at the authoritative business acceptance boundary."""
        outputs = self.chain.catalog.entries[self.run["workflow_ref"]].workflow.outputs
        self.run["accepted_artifacts"] = {name: hashlib.sha256(source_file(self.run["workspace"], name).read_bytes()).hexdigest()
                                          for name in outputs if (Path(self.run["workspace"]) / name).is_file()}
        self.chain.save()

    def context(self, token=None):
        """Provide original intent, validated run state and permitted candidates for one decision."""
        return {"chain_id": self.chain.state["chain_id"], "run_id": self.run["run_id"],
                "workflow_ref": self.run["workflow_ref"], "original_goal": self.chain.state["goal"],
                "instructions": list(self.chain.state["instructions"]), "transition_token": token,
                "input_manifest": self.run["input_manifest"], "accepted_artifacts": dict(self.run["accepted_artifacts"]), "candidates": self.chain.candidates(self.run),
                "runs_remaining": self.chain.settings.max_runs - len(self.chain.state["runs"]),
                "history": [{"workflow_ref": r["workflow_ref"], "business_status": r["business_status"],
                             "summary": (r.get("transition") or {}).get("request", {}).get("summary")}
                            for r in self.chain.state["runs"]],
                "previous_failures": [{"error": t.get("error")} for t in self.run["history"]]}
