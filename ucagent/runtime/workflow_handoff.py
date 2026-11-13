"""Passive same-process handoff: prepare, commit, retire, then activate a peer Host."""

import hashlib
import json
import os
from pathlib import Path
import threading
import time

from ucagent.core.workflow.chain import HandoffDecision
from ucagent.core.workflow.contracts import source_file
from ucagent.runtime.operations import TERMINAL_STATES


class WorkflowHandoff:
    """Execute accepted Super decisions without performing workflow selection."""

    def __init__(self, chain, host, factory, root, *, on_activate=None):
        """Inject application construction and keep one pending candidate at a time."""
        self.chain = chain
        self.active = host
        self.factory = factory
        self.root = Path(root)
        self.on_activate = on_activate or (lambda host: None)
        self.candidate = None
        self.preparing = None
        self.prepare_error = None
        self.prepare_started = None
        self.prepare_done = threading.Event()
        self._lock = threading.RLock()
        self.stopping = False
        self.control_idle = lambda: True
        self.error = None
        host.agent.multi_agent.handoff = HandoffDecision(chain, chain.current)
        host.workflow_chain_owned = True

    def drained(self, host):
        """Require actual model/tool and delegated work teardown before changing owners."""
        return (self.control_idle() and not host.agent.multi_agent.has_active() and host.agent.backend.wait_idle(0)
                and not host.agent.is_work_busy()
                and not any(row["state"] not in TERMINAL_STATES for row in host.operations.list()))

    def pause(self):
        """Freeze activation even after commit; keep the unique successor identity."""
        with self._lock:
            self.chain.state["status"] = "paused"
            self.chain.save()
            self.active.pause()
            if self.candidate is not None:
                self.candidate.pause()

    def resume(self, instruction=None):
        """Resume the current checkpoint without allocating another successor."""
        with self._lock:
            if self.stopping or self.chain.state["status"] in {"completed", "cancelled"}:
                raise RuntimeError("This workflow chain is closed")
            self.chain.state["status"] = "running"
            self.chain.save()
            self.active.agent.set_break(False)
            if self.candidate:
                self.candidate.agent.set_break(False)
            if self.chain.current["transition"] is None:
                return self.active.agent.multi_agent.start_workflow(instruction)
            return self.chain.view()

    def shutdown(self):
        """Cancel all owned instances; retain preparation ownership until its thread exits."""
        with self._lock:
            self.stopping = True
            if self.chain.state["status"] != "completed":
                self.chain.state["status"] = "cancelled"
                self.chain.save()
            self.active.request_shutdown("chain_shutdown")
            if self.candidate:
                self.candidate.request_shutdown("chain_shutdown")

    def closed(self):
        """Report cleanup only when every candidate, host and preparer has stopped."""
        return self.control_idle() and (self.prepare_done.is_set() or self.preparing is None) and all(
            h is None or h._closed.is_set() for h in (self.active, self.candidate))

    def _prepare(self, run, transition):
        """Copy checked input bytes and construct B behind its business-execution barrier."""
        try:
            workspace = self.root / "runs" / transition["target_run_id"] / "workspace"
            workspace.mkdir(parents=True, exist_ok=False)
            for entry in transition["manifest"]:
                data = source_file(run["workspace"], entry["source"]).read_bytes()
                if hashlib.sha256(data).hexdigest() != entry["sha256"] or len(data) != entry["size"]:
                    raise ValueError("Handoff source changed after decision acceptance")
                target = workspace / entry["target"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                target.chmod(0o444)
            successor = self.chain.new_run(transition["request"]["workflow_ref"], workspace,
                                           run_id=transition["target_run_id"])
            successor["input_manifest"] = transition["manifest"]
            successor["predecessor_run_id"] = run["run_id"]
            manifest_file = workspace.parent / "handoff.json"
            manifest_file.write_text(json.dumps({"source_run_id": run["run_id"], "target_run_id": successor["run_id"],
                "inputs": transition["manifest"], "summary": transition["request"]["summary"]}, indent=2) + "\n")
            transition["successor"] = successor
            self.chain.save()
            self.candidate = self.factory(successor)
            self.candidate.workflow_chain_owned = True
            self.candidate.agent.multi_agent.handoff = HandoffDecision(self.chain, successor)
            if self.candidate.snapshot()["instance"] != "ready":
                raise RuntimeError("Candidate host is not ready")
            if self.candidate.agent.multi_agent.records or self.candidate.agent.is_work_busy():
                raise RuntimeError("Candidate executed business work before activation")
        except BaseException as exc:
            self.candidate = self.candidate or getattr(exc, "handoff_candidate", None)
            self.prepare_error = f"{type(exc).__name__}: {exc}"
        finally:
            self.prepare_done.set()

    def step(self):
        """Advance one bounded lifecycle step; never call the model from a tool callback."""
        with self._lock:
            if self.stopping:
                if self.candidate:
                    self.candidate.request_shutdown("chain_shutdown")
                return
            run = self.chain.current
            transition = run["transition"]
            if transition is None or transition["status"] == "activated":
                return
            state = transition["status"]
            if state == "accepted":
                if not self.drained(self.active) or self.chain.state["status"] != "running":
                    return
                if transition["kind"] == "complete":
                    transition["status"] = "completed"
                    self.chain.state["status"] = "completed"
                    self.chain.event("chain_completed", run_id=run["run_id"])
                    self.active.complete_mission()
                    self.active.request_shutdown("mission_completed")
                    return
                transition["status"] = "preparing"
                self.prepare_started = time.monotonic()
                self.prepare_done.clear()
                self.prepare_error = None
                self.chain.event("candidate_preparing", run_id=run["run_id"], target_run_id=transition["target_run_id"])
                self.preparing = threading.Thread(target=self._prepare, args=(run, transition), name="ucagent-handoff-prepare", daemon=True)
                self.preparing.start()
                return
            if state in {"preparing", "cleanup_pending"}:
                overdue = time.monotonic() - self.prepare_started >= self.chain.settings.ready_timeout_seconds
                if overdue:
                    self.prepare_error = self.prepare_error or "Candidate readiness deadline exceeded"
                if not self.prepare_done.is_set():
                    if overdue and state != "cleanup_pending":
                        transition["status"] = "cleanup_pending"
                        self.chain.event("candidate_cleanup_pending", run_id=run["run_id"])
                    return
                if self.prepare_error:
                    if self.candidate is not None:
                        self.candidate.request_shutdown("candidate_failed", exit_code=1)
                        if not self.candidate._closed.is_set():
                            transition["status"] = "cleanup_pending"
                            return
                        if self.candidate.errors:
                            self.error = "Candidate cleanup failed; operator reconciliation required"
                            self.chain.state["status"] = "paused"
                            self.chain.save()
                            return
                    self.candidate = None
                    self.preparing = None
                    self.chain.failed(run, self.prepare_error)
                    self.active.agent.multi_agent._feedback = {"handoff_error": self.prepare_error}
                    if self.chain.state["status"] == "running":
                        self.active.agent.multi_agent.start_workflow()
                    return
                transition["status"] = "ready"
                self.chain.event("candidate_ready", run_id=run["run_id"], target_run_id=transition["target_run_id"],
                                 pid=os.getpid(), session_id=self.candidate.agent.session_id.hex)
                return
            if state == "ready":
                if self.chain.state["status"] != "running":
                    return
                transition["status"] = "committed"
                self.chain.event("handoff_committed", run_id=run["run_id"], target_run_id=transition["target_run_id"])
                return
            if state == "committed":
                self.active.request_shutdown("workflow_retired")
                if not self.active._closed.is_set():
                    return
                if self.active.errors:
                    self.error = "Source cleanup failed; successor remains gated"
                    self.chain.state["status"] = "paused"
                    self.chain.save()
                    return
                transition["status"] = "retired"
                self.chain.event("source_retired", run_id=run["run_id"])
                return
            if state == "retired" and self.chain.state["status"] == "running":
                # Serialize pause/shutdown with routing and activation. A committed identity is immutable.
                successor = transition["successor"]
                self.on_activate(self.candidate)
                self.active = self.candidate
                self.candidate = None
                self.preparing = None
                self.chain.state["runs"].append(successor)
                transition.pop("successor")
                transition["status"] = "activated"
                self.chain.event("successor_activated", run_id=successor["run_id"], pid=os.getpid())
                os.environ["UCAGENT_WORKSPACE"] = self.active.agent.workspace
                self.active.agent.set_break(False)
                self.active.agent.multi_agent.start_workflow()
