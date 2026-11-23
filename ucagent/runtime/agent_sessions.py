"""Runtime owner for isolated, on-demand Super workflow sessions."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import time
from uuid import uuid4

from ucagent.core.multi_agent.global_agent.session_contracts import SuperRequest, SuperSpec, TERMINAL_STATES
from ucagent.core.multi_agent.global_agent.result import sha256_file, verify_workflow_run_result, _artifact_path
from ucagent.core.workflow.contracts import canonical_file
from ucagent.runtime.agent_events import AgentEvents, GlobalInbox, atomic_json

class AgentSessions:
    def __init__(self, service, workspace, *, launcher, host=None, root=None):
        self.service, self.settings, self.catalog = service, service.settings, service.catalog
        self.workspace = Path(workspace).resolve()
        base = Path(root or self.settings.root or self.workspace / ".ucagent/global")
        if not base.is_absolute(): base = self.workspace / base
        self.session_id = uuid4().hex
        self.root = base.resolve() / "sessions" / self.session_id
        self.root.mkdir(parents=True, exist_ok=False)
        self.launcher, self.host = launcher, host
        self.events = AgentEvents(self.root)
        self.inbox = GlobalInbox(host, self.root, self.events) if host else None
        self.runs, self.keys, self.request_counts = {}, {}, {}
        self.handles = {}
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.thread = None
        self.closed = False
        self.errors = []
        self._saved_state = None
        self.save()

    def save(self):
        state = {"session_id": self.session_id,
                    "workspace": str(self.workspace), "closed": self.closed,
                    "agents": self.runs, "keys": self.keys, "request_counts": self.request_counts,
                    "errors": self.errors}
        if state != self._saved_state:
            atomic_json(self.root / "session.json", state)
            self._saved_state = copy.deepcopy(state)

    def start(self):
        if self.thread: return
        self.thread = threading.Thread(target=self._loop, name="ucagent-agent-sessions", daemon=True)
        self.thread.start()

    def _loop(self):
        while not self.stop.wait(0.1):
            try: self.tick()
            except Exception as error:
                with self.lock:
                    self.errors.append(str(error)[:2000])
                    self.events.append("global", "runtime_error", error=str(error)[:2000])
                    self.save()
                if self.host: self.host.request_shutdown("session_runtime_failed", exit_code=1)
                return

    def submit_input(self, text):
        if not self.inbox: raise RuntimeError("Conversation runtime is not attached")
        return self.inbox.submit(text)

    def start_initial_task(self, *, workflow_ref, dut_name, instruction=None):
        """Launch an exact CLI task once, without a model reinterpreting its constraints."""
        text = instruction or f"Verify {dut_name} using the selected workflow {workflow_ref}."
        request_id = uuid4().hex
        result = self.start_super(SuperRequest(workflow_ref=workflow_ref, dut_name=dut_name,
                                              instruction=text), request_id=request_id)
        self.events.append("global", "user_input", request_id=request_id, text=text)
        self.events.append("global", "message", text=f"Started {result['agent_id']}: {workflow_ref} ({dut_name})")
        return result

    def _entry(self, spec):
        if spec.workflow_ref not in self.catalog.entries:
            raise ValueError("Unknown workflow; inspect ListWorkflows")
        entry = self.catalog.entries[spec.workflow_ref]
        if entry.unavailable: raise ValueError(entry.unavailable)
        if spec.launch_profile not in self.settings.launch_profiles:
            raise ValueError("Unknown launch profile; inspect ListLaunchProfiles")
        if set(spec.inputs) != set(entry.workflow.inputs):
            raise ValueError(f"Workflow requires exactly these input targets: {sorted(entry.workflow.inputs)}")
        return entry

    def _source(self, source):
        path = Path(source) if source else self.workspace
        if not path.is_absolute(): path = self.workspace / path
        path = path.resolve()
        allowed = [self.workspace, *[Path(p).resolve() for p in self.settings.workspace_roots]]
        if not path.is_dir() or not any(path.is_relative_to(p) for p in allowed):
            raise ValueError("source_workspace must be an existing directory inside the configured workspace roots")
        if path.is_relative_to(self.root): raise ValueError("Cannot use session runtime state as a source workspace")
        return path

    def start_super(self, request, *, request_id="operator"):
        spec = SuperRequest.model_validate(request) if not isinstance(request, SuperRequest) else request
        self._entry(spec)
        source = self._source(spec.source_workspace)
        fingerprint = hashlib.sha256((request_id + json.dumps(spec.model_dump(), sort_keys=True)).encode()).hexdigest()
        with self.lock:
            if self.closed: raise RuntimeError("Global session is closing")
            if fingerprint in self.keys: return self.agent_status(self.keys[fingerprint])
            if self.request_counts.get(request_id, 0) >= self.settings.max_runs_per_request:
                raise ValueError("This user request exhausted its Super launch budget")
            for ref in spec.inputs.values(): self._accepted_artifact(ref.agent_id, ref.attempt, ref.path)
            agent_id = "super-" + uuid4().hex[:12]
            self.runs[agent_id] = {"agent_id": agent_id, "parent_id": "global", "role": "super",
                "request_id": request_id, "spec": spec.model_dump(), "workflow_ref": spec.workflow_ref,
                "source_workspace": str(source), "attempt": 1, "status": "queued", "history": [],
                "artifacts": {}, "error": None, "children": [], "stages": [], "stage_index": 0,
                "created_at": time.time()}
            self.keys[fingerprint] = agent_id
            self.request_counts[request_id] = self.request_counts.get(request_id, 0) + 1
            self.events.append(agent_id, "queued", parent_id="global", workflow_ref=spec.workflow_ref)
            self.save()
            return self.agent_status(agent_id)

    def list_agents(self):
        with self.lock:
            return {"session_id": self.session_id, "session_dir": str(self.root),
                    "agents": [self.agent_status(k) for k in self.runs]}

    def agent_status(self, agent_id):
        with self.lock:
            run = self._run(agent_id)
            result = {k: v for k, v in run.items() if k not in {"spec", "history", "request_id"}}
            result["attempts"] = [{k: x.get(k) for k in ("attempt", "status", "error", "workspace")} for x in run["history"]]
            result["instruction"] = run["spec"]["instruction"]
            result["accepted"] = True
            return copy.deepcopy(result)

    def _run(self, agent_id):
        if agent_id not in self.runs: raise ValueError("Unknown Agent ID; inspect ListAgents")
        return self.runs[agent_id]

    def retry_super(self, agent_id, attempt, *, request_id="operator"):
        with self.lock:
            run = self._run(agent_id)
            if run["attempt"] == attempt + 1: return self.agent_status(agent_id)
            if run["attempt"] != attempt: raise ValueError("Stale attempt; inspect AgentStatus")
            if run["status"] not in {"failed", "cancelled"}: raise ValueError("Only failed or cancelled attempts can be retried")
            profile = self.settings.launch_profiles[run["spec"]["launch_profile"]]
            if attempt >= profile.max_attempts: raise ValueError("Super attempt budget exhausted")
            if self.request_counts.get(request_id, 0) >= self.settings.max_runs_per_request:
                raise ValueError("This user request exhausted its Super launch budget")
            history = run.pop("history")
            history.append(copy.deepcopy(run))
            run.update(history=history, attempt=attempt + 1, status="queued", error=None, artifacts={},
                       children=[], stages=[], stage_index=0, request_id=request_id)
            for key in ("pid", "started_at", "finished_at", "workspace", "result_path", "exit_code"):
                run.pop(key, None)
            self.request_counts[request_id] = self.request_counts.get(request_id, 0) + 1
            self.events.append(agent_id, "queued", attempt=run["attempt"], parent_id="global")
            self.save()
            return self.agent_status(agent_id)

    def cancel_super(self, agent_id):
        with self.lock:
            run = self._run(agent_id)
            if run["status"] in TERMINAL_STATES: return self.agent_status(agent_id)
            run["status"] = "cancelling"
            handle = self.handles.pop(agent_id, None)
            self.save()
        if handle: self.launcher.cancel(handle)
        with self.lock:
            self._finish(run, "cancelled", "Cancelled by the operator")
            return self.agent_status(agent_id)

    def message_super(self, agent_id, message):
        with self.lock:
            run = self._run(agent_id)
            if run["status"] in TERMINAL_STATES | {"cancelling"}: raise ValueError("Agent is finished; retry or start a new Super")
            handle = self.handles.get(agent_id)
            if handle is None or not hasattr(self.launcher, "send_input"):
                raise ValueError("Super is not ready for instructions; retry after AgentStatus reports running")
        return self.launcher.send_input(handle, message)

    def _accepted_artifact(self, agent_id, attempt, path):
        canonical_file(path)
        run = self._run(agent_id)
        row = run if run["attempt"] == attempt else next((r for r in run["history"] if r["attempt"] == attempt), None)
        if row is None or row["status"] != "succeeded": raise ValueError("Artifact source attempt has not succeeded")
        receipt = row["artifacts"].get(path)
        if receipt is None: raise ValueError("Path is not an accepted artifact")
        target = _artifact_path(Path(row["workspace"]), path)
        if not target.is_file() or target.stat().st_size != receipt["size"] or sha256_file(target) != receipt["sha256"]:
            raise ValueError("Accepted artifact changed after verification")
        return target, receipt

    def read_agent_artifact(self, agent_id, attempt, path, max_bytes=65536):
        if type(max_bytes) is not int or not 1 <= max_bytes <= 1048576: raise ValueError("max_bytes must be 1..1048576")
        with self.lock:
            target, receipt = self._accepted_artifact(agent_id, attempt, path)
            with target.open("rb") as stream: data = stream.read(max_bytes)
            # Recheck after the read as well as before it.
            self._accepted_artifact(agent_id, attempt, path)
            return {"agent_id": agent_id, "attempt": attempt, **receipt,
                    "content": data.decode("utf-8", errors="replace"), "truncated": receipt["size"] > len(data)}

    def _available(self, run):
        profile = self.settings.launch_profiles[run["spec"]["launch_profile"]]
        used = {}
        for other in self.runs.values():
            if other["status"] not in {"starting", "running", "waiting_input", "cancelling"}: continue
            for r in self.settings.launch_profiles[other["spec"]["launch_profile"]].resources:
                used[r] = used.get(r, 0) + 1
        return all(used.get(r, 0) < self.settings.resources[r] for r in profile.resources)

    def _launch(self, run):
        spec = SuperSpec(**run["spec"], agent_id=run["agent_id"])
        root = self.root / "agents" / spec.agent_id / f"attempt-{run['attempt']}"
        workspace = root / "workspace"
        workspace.mkdir(parents=True, exist_ok=False)
        source = Path(run["source_workspace"])
        def ignore(directory, names):
            return [n for n in names if n in {".ucagent", ".git", "__pycache__", ".venv"}
                    or (n.startswith(".") and n.endswith("_cache"))
                    or n.endswith(".pyc") or (Path(directory) / n).resolve() == self.root.parent.parent]
        # Prune generated trees before scanning; directory links could create copy cycles.
        for directory, dirs, files in os.walk(source, followlinks=False):
            excluded = set(ignore(directory, dirs + files))
            dirs[:] = [name for name in dirs if name not in excluded]
            for name in dirs + [name for name in files if name not in excluded]:
                link = Path(directory) / name
                if not link.is_symlink(): continue
                if not link.resolve().is_relative_to(source):
                    raise ValueError(f"Source symlink escapes workspace: {link.relative_to(source)}")
                if link.is_dir():
                    raise ValueError(f"Source directory symlink cannot be copied safely: {link.relative_to(source)}")
        shutil.copytree(source, workspace, dirs_exist_ok=True, ignore=ignore)
        for target, ref in spec.inputs.items():
            path, receipt = self._accepted_artifact(ref.agent_id, ref.attempt, ref.path)
            destination = _artifact_path(workspace, target)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            if sha256_file(destination) != receipt["sha256"]: raise ValueError("Input changed during copy")
            destination.chmod(0o444)
        result_path = root / "run_result.json"
        run.update(status="starting", workspace=str(workspace), result_path=str(result_path))
        instruction = (spec.instruction + "\nComplete the selected workflow through Check/Complete. "
                       "Delegate the workflow tasks to Subs. Return control after delegation; "
                       "workflow selection outside this task belongs to Global.\nInputs: " + ", ".join(spec.inputs))
        handle = self.launcher.start(spec, workspace, result_path, instruction, attempt=run["attempt"])
        self.handles[spec.agent_id] = handle
        run.update(status="running", pid=handle.get("pid"), started_at=time.time())
        self.events.append(spec.agent_id, "started", attempt=run["attempt"], parent_id="global", pid=run["pid"])
        self.save()

    def _finish(self, run, status, error=None):
        run.update(status=status, error=str(error)[:2000] if error else None, finished_at=time.time())
        # A large verified manifest must not overflow the model inbox or event stream.
        preview, size = {}, 0
        for path, artifact in run["artifacts"].items():
            size += len(json.dumps({path: artifact}))
            if len(preview) >= 50 or size > 16000: break
            preview[path] = artifact
        detail = {"agent_id": run["agent_id"], "attempt": run["attempt"], "workflow_ref": run["workflow_ref"],
                  "status": status, "error": run["error"], "artifacts": preview,
                  "dut_name": run["spec"].get("dut_name"),
                  "instruction": run["spec"]["instruction"][:4000],
                  "instruction_truncated": len(run["spec"]["instruction"]) > 4000,
                  "artifact_count": len(run["artifacts"]), "artifacts_truncated": len(preview) < len(run["artifacts"])}
        if detail["artifacts_truncated"] or detail["instruction_truncated"]:
            detail["next_action"] = "Use AgentStatus for the full task instruction and accepted artifact index."
        event = self.events.append(run["agent_id"], "result", attempt=run["attempt"], parent_id="global",
                                   **{key: value for key, value in detail.items() if key not in {"agent_id", "attempt"}})
        self.save()
        if self.inbox and not self.closed:
            self.inbox.submit("A Super finished. Report its verified result and perform any requested next work.\n" + json.dumps(detail, ensure_ascii=False),
                              request_id=run["request_id"], event_id=event["seq"])

    def tick(self):
        with self.lock:
            if self.closed: return
            for agent_id, handle in list(self.handles.items()):
                run = self.runs[agent_id]
                try:
                    status = self.launcher.poll(handle)
                    for message in status.get("messages", []):
                        self.events.append(message.get("agent_id", agent_id), "message", attempt=run["attempt"],
                                           parent_id=agent_id, text=message["text"], source=message.get("source", "model"))
                    if status.get("snapshot"):
                        snap = status["snapshot"]
                        for key in ("stages", "stage_index", "children"):
                            if key in snap: run[key] = snap[key]
                        waiting = snap.get("execution") == "waiting_human"
                        if waiting and run["status"] != "waiting_input":
                            event = self.events.append(agent_id, "waiting_input", attempt=run["attempt"], parent_id="global")
                            if self.inbox:
                                self.inbox.submit(f"Super {agent_id} is waiting for operator input or review. Inspect its state and ask the user for the needed action.",
                                                  request_id=run["request_id"], event_id=event["seq"])
                        run["status"] = "waiting_input" if waiting else "running"
                    if status["state"] == "running": continue
                    self.handles.pop(agent_id)
                    run["exit_code"] = status.get("exit_code")
                    if status.get("exit_code") != 0:
                        detail = ""
                        for key in ("stderr_path", "stdout_path"):
                            log = handle.get(key)
                            if log and Path(log).is_file():
                                with Path(log).open("rb") as stream:
                                    stream.seek(max(0, Path(log).stat().st_size - 1600))
                                    detail = stream.read().decode("utf-8", errors="replace")
                                if detail.strip(): break
                        raise ValueError(f"Super exited with code {status.get('exit_code')}: {detail}")
                    spec = SuperSpec(**run["spec"], agent_id=agent_id)
                    result = verify_workflow_run_result(run["result_path"], run["workspace"], spec,
                              list(self._entry(spec).workflow.outputs), expected_attempt=run["attempt"])
                    run["artifacts"] = {x.path: x.model_dump() for x in result.artifacts}
                    run["stages"] = [x.model_dump() for x in result.stages]
                    self._finish(run, "succeeded")
                except Exception as error:
                    remaining = self.handles.pop(agent_id, None)
                    if remaining: self.launcher.cancel(remaining)
                    self._finish(run, "failed", error)
            active = sum(r["status"] in {"running", "starting", "waiting_input", "cancelling"} for r in self.runs.values())
            for run in self.runs.values():
                if active >= self.settings.max_parallel_supers: break
                if run["status"] != "queued" or not self._available(run): continue
                try:
                    self._launch(run)
                    active += 1
                except Exception as error: self._finish(run, "failed", error)
            self.save()
        if self.inbox:
            self.inbox.tick()
            if (self.host.exit_on_completion and self.inbox.items and not self.inbox.pending()
                    and not self.has_active() and self.host.operations._model_id is None):
                failed = self.inbox.failed() or any(r["status"] != "succeeded" for r in self.runs.values())
                self.host.request_shutdown("global_request_finished", exit_code=int(failed))

    def has_active(self):
        with self.lock: return any(r["status"] not in TERMINAL_STATES for r in self.runs.values())

    def close(self):
        self.stop.set()
        with self.lock:
            if self.closed: return
            self.closed = True
            active = [r["agent_id"] for r in self.runs.values() if r["status"] not in TERMINAL_STATES]
        for agent_id in active: self.cancel_super(agent_id)
        if self.thread and self.thread is not threading.current_thread(): self.thread.join(5)
        with self.lock: self.save()
