"""In-memory run-wide task admission, bounded execution and verified stage delivery."""

from contextvars import ContextVar
from dataclasses import dataclass, field
import hashlib
from glob import has_magic
import json
import os
from pathlib import Path
import threading
import time
from uuid import uuid4

from ucagent.util.log import log_msg
from ucagent.util.file_policy import normalize_relative_path, is_file_writeable
from .contracts import TaskPlan
from .supervisor import StageDriver


PLANNING_OWNER = ContextVar("multi_agent_planning_owner", default=None)


TERMINAL = {"verified", "failed", "cancelled", "blocked"}


@dataclass
class TaskBudget:
    """Retain logical work budgets even when the planner changes plan/task identifiers."""

    backend_turns: int = 0
    calls: int = 0
    rounds: int = 0
    deadline: float | None = None


@dataclass
class TaskRecord:
    """Keep one logical task's bounded attempts and result private to the service."""

    key: str
    spec: object
    plan_id: str
    lease: object
    split: bool
    role: object
    state: str = "queued"
    attempt: int = 0
    budget: TaskBudget = field(default_factory=TaskBudget)
    result: dict | None = None
    error: str | None = None
    feedback: object = None
    artifacts: dict = field(default_factory=dict)
    inputs: dict = field(default_factory=dict)
    cancel: threading.Event = field(default_factory=threading.Event)
    lock: object = field(default_factory=threading.RLock)
    thread: object = None
    started: float | None = None
    worker: object = field(default=None, repr=False)
    activity: str | None = None
    session_id: str | None = None
    model_rounds_available: bool = False

    def budget_status(self, limits):
        """Report consumed logical budgets across attempts without exposing connection data."""
        return {"backend_turns_used": self.budget.backend_turns, "backend_turns_limit": limits.worker_backend_turns,
                "model_rounds_used": self.rounds if self.model_rounds_available else None,
                "model_rounds_limit": limits.worker_model_rounds if self.model_rounds_available else None,
                "tool_calls_used": self.calls, "tool_calls_limit": limits.worker_tool_calls,
                "seconds_remaining": max(0, round(self.deadline - time.monotonic(), 2))
                    if self.deadline is not None else limits.worker_timeout_seconds}

    @property
    def calls(self):
        """Expose cumulative tool charges across revisions of this work target."""
        return self.budget.calls

    @calls.setter
    def calls(self, value):
        """Charge the persistent target budget through the record interface."""
        self.budget.calls = value

    @property
    def rounds(self):
        """Expose cumulative worker model charges across plan identifiers."""
        return self.budget.rounds

    @rounds.setter
    def rounds(self, value):
        """Update the shared budget for the current logical work target."""
        self.budget.rounds = value

    @property
    def deadline(self):
        """Keep one absolute deadline from the target's first actual start."""
        return self.budget.deadline

    @deadline.setter
    def deadline(self, value):
        """Set the deadline only when the scheduler first starts this target."""
        self.budget.deadline = value


class MultiAgentService:
    """Share one queue and one stage owner across local, MCP and automatic callers."""

    def __init__(self, agent, settings, *, runner_factory=None):
        """Create no model or worker until a validated plan is submitted."""
        self.agent = agent
        self.settings = settings
        self.driver = StageDriver(agent.stage_manager)
        self.workspace = Path(agent.workspace).resolve()
        self.runner_factory = runner_factory
        self.endpoint_factory = None
        self.records = {}
        self.plans = {}
        self._cv = threading.Condition(threading.RLock())
        self._closed = False
        self._running = 0
        self._validating = False
        self._scheduler = None
        self._scope_revisions = {}
        self._task_budgets = {}
        self._events = []
        self.on_change = lambda: None
        self.workflow_thread = None
        self.workflow_state = "idle"
        self._workflow_lock = threading.Lock()
        self.planning = None
        self._planning_turns = {}
        self._workflow_stop = threading.Event()
        self._feedback = None
        self._instruction = None
        self._supervisor_question = None
        self.handoff = None

    def emit(self, kind, **data):
        """Retain bounded structured events and wake attached runtime views."""
        with self._cv:
            record = self.records.get(data.get("task_id"))
            identity = ({"backend": record.role.backend, "session_id": record.session_id,
                         "attempt": record.attempt} if record is not None else
                        {"backend": self.agent.cfg.backend.key_name, "session_id": self.agent.session_id.hex})
            event = {"event": kind, "time": time.time(), **identity, **data}
            self._events.append(event)
            if self.handoff is not None and kind in {"plan_submitted", "task_started", "task_finished", "scope_validated"}:
                self.handoff.chain.event("workflow_" + kind, run_id=self.handoff.run["run_id"],
                    **{key: value for key, value in event.items() if key not in {"event", "time"}})
            log_msg("multi_agent " + json.dumps(event, ensure_ascii=False, default=str))
            self._events = self._events[-500:]
            self._cv.notify_all()
        self.on_change()

    def path(self, relative, *, writing=False):
        """Resolve each use afresh, rejecting traversal, symlinks and hidden state writes."""
        normalized = normalize_relative_path(relative)
        if normalized != relative or not normalized:
            raise ValueError("Task paths must be canonical workspace-relative file paths")
        relative = normalized
        path = self.workspace / relative
        if any(part.is_symlink() for part in [path, *path.parents] if part != self.workspace.parent):
            raise ValueError("Symlink task paths are not allowed")
        if not path.resolve().is_relative_to(self.workspace):
            raise ValueError("Task path escapes workspace")
        if writing:
            if relative.split("/")[0] in {".ucagent", ".git"}:
                raise PermissionError("Task outputs cannot overwrite framework state")
            ok, reason = is_file_writeable(relative, self.agent.cfg.get_value("un_write_dirs", []),
                                           self.agent.cfg.get_value("write_dirs", []))
            if not ok:
                raise PermissionError(reason)
        return path

    def submit(self, plan):
        """Validate a complete plan atomically; duplicates never create extra workers."""
        plan = TaskPlan.model_validate(plan)
        fingerprint = plan.model_dump_json(exclude={"planning_token"})
        with self._cv:
            if self.planning is not None:
                self.validate_planning(plan.planning_token, submitting=True)
            elif plan.planning_token is not None or self._workflow_lock.locked():
                raise PermissionError("No planning turn is accepting plans")
            if self._closed:
                raise RuntimeError("Multi-agent service is closing")
            if plan.plan_id in self.plans:
                if self.plans[plan.plan_id]["fingerprint"] != fingerprint:
                    raise ValueError("plan_id already exists with different contents")
                return self.status(plan.plan_id)
            if self._validating:
                raise RuntimeError("Stage acceptance is in progress")
            _, default_steps = self.driver.resolve_scope(self.settings.delegation_scope)
            if default_steps and plan.scope in {"stage", "task"} and not (plan.scope_reason or "").strip():
                raise ValueError("Current work belongs to a stage subtree. Use scope=auto for continuous substages "
                                 "in one worker; stage/task requires scope_reason for intentional narrowing. "
                                 "scope=task has no Check, ListSkill, SetSkillUsage or stage journal tools.")
            split = plan.scope == "task"
            if not split and len(plan.tasks) != 1:
                raise ValueError("Multiple tasks require scope=task and explicit non-conflicting file outputs")
            active = [r for r in self.records.values() if r.lease is self.driver.active_lease]
            if active and (not split or any(not r.split for r in active)):
                raise RuntimeError("A stage/subtree delegation already owns this stage")
            ids = [t.id for t in plan.tasks]
            if len(set(ids)) != len(ids):
                raise ValueError("Task ids must be unique within a plan")
            specs = {t.id: t for t in plan.tasks}
            for task in plan.tasks:
                if task.id in task.depends_on or set(task.depends_on) - set(ids):
                    raise ValueError("Task dependencies must reference other tasks in the plan")
            pending = set(ids)
            while pending:
                ready = {key for key in pending if not (set(specs[key].depends_on) & pending)}
                if not ready:
                    raise ValueError("Task dependencies contain a cycle")
                pending -= ready
            resolved = []
            outputs = {p for r in active for p in r.spec.outputs}
            active_inputs = {p for r in active for p in r.spec.inputs}
            active_outputs = set(outputs)
            for task in plan.tasks:
                current = self.agent.stage_manager.get_current_stage()
                role_name = task.role or self.settings.stage_roles.get(getattr(current, "name", "")) or self.settings.default_role
                task.role = role_name
                if role_name not in self.settings.roles:
                    raise ValueError(f"Unknown role {role_name}; available: {list(self.settings.roles)}")
                role = self.settings.roles[role_name]
                if split:
                    if not task.outputs:
                        raise ValueError("Split tasks require explicit file outputs")
                    contract = self.settings.task_contracts.get(task.contract)
                    if task.contract is not None and contract is None:
                        raise ValueError("Unknown workflow-authored task contract")
                    if contract is not None:
                        if contract.allowed_roles and role_name not in contract.allowed_roles:
                            raise PermissionError("Role is not allowed by the task contract")
                        if set(task.outputs) != {rule.path for rule in contract.rules}:
                            raise ValueError("Task outputs must exactly match the trusted contract")
                    # Configured artifact rules remain mandatory even when the planner
                    # omits a contract reference. Model-authored tasks cannot weaken them.
                    for configured in self.settings.task_contracts.values():
                        if set(task.outputs) & {rule.path for rule in configured.rules}:
                            if configured.allowed_roles and role_name not in configured.allowed_roles:
                                raise PermissionError("Role is not allowed by the output contract")
                for artifact in task.inputs + task.outputs:
                    path = self.path(artifact, writing=artifact in task.outputs)
                    if has_magic(artifact) or path.is_dir():
                        raise ValueError("Task inputs/outputs require concrete file paths, not globs or directories: "
                                         f"{artifact}. Use FindFiles/PathList and list exact files; "
                                         "stage/auto outputs may be omitted when the stage Checker owns them.")
                for output in task.outputs:
                    if output in active_inputs:
                        raise ValueError("Cross-plan input/output conflicts require one explicit dependency plan")
                    if any(output == other or output.startswith(other + "/") or other.startswith(output + "/")
                           for other in outputs):
                        raise ValueError("Task output ownership conflicts with another task")
                    outputs.add(output)
                for source in task.inputs:
                    self.path(source)
                    if source in active_outputs:
                        raise ValueError("Cross-plan input producers require one explicit dependency plan")
                resolved.append((task, role))
            # A producer must be an explicit ancestor, not merely queued before its consumer.
            for task in plan.tasks:
                ancestors = set(task.depends_on)
                todo = list(ancestors)
                while todo:
                    for dep in specs[todo.pop()].depends_on:
                        if dep not in ancestors:
                            ancestors.add(dep)
                            todo.append(dep)
                for producer in plan.tasks:
                    if set(task.inputs) & set(producer.outputs) and producer.id not in ancestors:
                        raise ValueError("An input producer must be an explicit task dependency")
            current = self.agent.stage_manager.get_current_stage()
            budget_root = current
            while getattr(budget_root, "parent", None) is not None:
                budget_root = budget_root.parent
            revision_key = id(current)
            budget_key = id(budget_root)
            revision = self._scope_revisions.get(revision_key, 0)
            if revision >= self.settings.limits.planning_revisions:
                raise RuntimeError("Stage planning budget exhausted; operator intervention required")
            lease = self.driver.active_lease or self.driver.acquire(
                self.settings.delegation_scope if plan.scope == "auto" else plan.scope)
            self._scope_revisions[revision_key] = revision + 1
            self.plans[plan.plan_id] = {"fingerprint": fingerprint, "state": "running", "lease": lease,
                                        "validation": None, "tasks": []}
            for task, role in resolved:
                key = f"{plan.plan_id}/{task.id}"
                target = tuple(sorted(task.outputs)) if split else ("stage", id(lease.root))
                budget = self._task_budgets.setdefault((budget_key, target), TaskBudget())
                record = TaskRecord(key, task, plan.plan_id, lease, split, role, budget=budget)
                self.records[key] = record
                self.plans[plan.plan_id]["tasks"].append(key)
            if self._scheduler is None or not self._scheduler.is_alive():
                self._scheduler = threading.Thread(target=self._schedule, name="ucagent-task-queue", daemon=True)
                self._scheduler.start()
            if self.planning is not None:
                self.planning["submitted"] = plan.plan_id
            self.emit("plan_submitted", plan_id=plan.plan_id, scope=plan.scope,
                      scope_root=lease.root.name, substages=[step.name for step in lease.steps])
            return self.status(plan.plan_id)

    def status(self, plan_id=None):
        """Return detached public state without leaking role connection configuration."""
        with self._cv:
            if plan_id is not None and plan_id not in self.plans:
                raise ValueError("Unknown plan_id")
            plans = {key: {"state": value["state"], "validation": value["validation"],
                            "tasks": list(value["tasks"])} for key, value in self.plans.items()
                     if plan_id is None or key == plan_id}
            tasks = [{"task_id": r.key, "state": r.state, "attempt": r.attempt,
                      "summary": (r.result or {}).get("summary"), "artifacts": dict(r.artifacts),
                      "error": r.error, "role": r.spec.role or self.settings.default_role,
                      "budget": r.budget_status(self.settings.limits),
                      "activity": r.activity or (r.worker.backend.requests.status() if r.worker is not None
                          and getattr(r.worker.backend, "requests", None) is not None else None)}
                     for r in self.records.values() if plan_id is None or r.plan_id == plan_id]
            return {"plans": plans, "tasks": tasks, "running": self._running,
                    "max_workers": self.settings.max_workers, "workflow_state": self.workflow_state,
                    "planning": self.planning is not None,
                    "metrics": {"plans": len(self.plans), "tasks": len(self.records),
                                "worker_starts": sum(r.attempt for r in self.records.values()),
                                "planning_turns": sum(self._planning_turns.values())},
                    "events": list(self._events[-30:])}

    def wait(self, plan_id, timeout=30):
        """Provide bounded event waiting for MCP clients, never an unbounded tool call."""
        if not 0 <= timeout <= 60:
            raise ValueError("Wait timeout must be between 0 and 60 seconds")
        deadline = time.monotonic() + timeout
        with self._cv:
            if plan_id not in self.plans:
                raise ValueError("Unknown plan_id")
            while self.plans[plan_id]["state"] == "running" and time.monotonic() < deadline:
                self._cv.wait(deadline - time.monotonic())
            return self.status(plan_id)

    def cancel(self, plan_id, *, stop_workflow=True):
        """Request cancellation while retaining running slots until actual teardown."""
        with self._cv:
            if plan_id not in self.plans:
                raise ValueError("Unknown plan_id")
            cancelled = False
            for key in self.plans[plan_id]["tasks"]:
                r = self.records[key]
                if r.state not in TERMINAL and not r.cancel.is_set():
                    cancelled = True
                    r.cancel.set()
                    r.state = "cancelled" if r.state == "queued" else "cancelling"
                    if r.worker is not None and callable(getattr(r.worker.backend, "cancel", None)):
                        r.worker.backend.cancel()
            if cancelled and stop_workflow and self._workflow_lock.locked():
                self._workflow_stop.set()
            if cancelled:
                self.emit("plan_cancel_requested", plan_id=plan_id)
            return self.status(plan_id)

    def has_active(self):
        """Include validation and workflow driving in runtime shutdown decisions."""
        with self._cv:
            return (self._running > 0 or self._validating or self._workflow_lock.locked()
                    or self.workflow_state == "running"
                    or any(p["state"] == "running" for p in self.plans.values()))

    def close(self, timeout=5):
        """Cancel and join workers; report pending owners instead of releasing live state."""
        deadline = time.monotonic() + timeout
        with self._cv:
            self._closed = True
            for name, plan in self.plans.items():
                if plan["state"] == "running":
                    self.cancel(name)
            self._cv.notify_all()
        thread = self._scheduler
        if thread and thread is not threading.current_thread():
            thread.join(max(0, deadline - time.monotonic()))
        workflow = self.workflow_thread
        if workflow and workflow is not threading.current_thread():
            workflow.join(max(0, deadline - time.monotonic()))
        return {"closed": not self.has_active()}

    def drain(self):
        """Retain prepared resources until every outstanding worker has actually stopped."""
        while not self.close(timeout=1)["closed"]:
            pass

    def _schedule(self):
        """Reserve slots under one lock and never hold it during model/checker work."""
        while True:
            validation = None
            with self._cv:
                # A submitted plan freezes the planner, but its model/tool calls
                # must drain before workers can move the stage or write artifacts.
                if self.planning is not None:
                    self._cv.wait(0.1)
                    continue
                active = [r for r in self.records.values() if r.lease is self.driver.active_lease]
                for r in active:
                    if r.state != "queued":
                        continue
                    deps = [self.records[f"{r.plan_id}/{d}"] for d in r.spec.depends_on]
                    if any(d.state in {"failed", "cancelled", "blocked"} for d in deps):
                        r.state, r.error = "blocked", "A task dependency did not pass"
                        continue
                    busy_resources = {name for other in active if other.state in {"running", "submitted", "cancelling"}
                                      for name in other.spec.resources}
                    if self._running >= self.settings.max_workers or set(r.spec.resources) & busy_resources:
                        continue
                    if not all(d.state == "verified" for d in deps):
                        continue
                    self._running += 1
                    r.state, r.attempt = "running", r.attempt + 1
                    r.result, r.error = None, None
                    r.started = time.monotonic()
                    # Absolute time is per logical task, not reset by a repair attempt.
                    if r.deadline is None:
                        r.deadline = r.started + self.settings.limits.worker_timeout_seconds
                    r.thread = threading.Thread(target=self._execute, args=(r,), name=f"worker-{r.key}", daemon=True)
                    r.thread.start()
                    self.emit("task_started", task_id=r.key, role=r.spec.role, attempt=r.attempt)
                if active and not self._running and all(r.state in TERMINAL for r in active):
                    self._validating = True
                    validation = active
                elif self._closed and not self._running:
                    return
                else:
                    self._cv.wait(0.1)
            if validation is not None:
                self._accept_scope(validation)

    def _execute(self, record):
        """Retain capacity through construction, tool draining, and runner teardown."""
        from .worker import WorkerSession
        worker = timer = None
        state, error, error_type = "failed", "Worker did not start", None
        try:
            record.inputs = {name: hashlib.sha256(self.path(name).read_bytes()).hexdigest()
                             for name in record.spec.inputs}
            worker = WorkerSession(self, record)
            record.worker = worker
            timer = threading.Timer(max(0, record.deadline - time.monotonic()), worker.timeout)
            timer.daemon = True
            timer.start()
            try:
                worker.run(self.runner_factory)
            finally:
                # MCP requests can outlive a disconnected process. Drain the task
                # lock before accepting artifacts or releasing its execution slot.
                worker.close()
            if record.cancel.is_set():
                raise RuntimeError(record.error or "Task cancelled")
            if record.result is None:
                raise RuntimeError("Worker exited without SubmitTaskResult")
            if record.result.get("status") == "blocked":
                raise RuntimeError("Worker blocked: " + record.result["summary"])
            for name, digest in record.inputs.items():
                if hashlib.sha256(self.path(name).read_bytes()).hexdigest() != digest:
                    raise RuntimeError("Input artifact changed while the task was running")
            contents = {name: worker.artifact_path(name).read_bytes() for name in record.spec.outputs}
            if record.split:
                if any(not content for content in contents.values()):
                    raise ValueError("Split task outputs must be nonempty files")
                rules = [rule for contract in self.settings.task_contracts.values()
                         for rule in contract.rules if rule.path in contents]
                for rule in rules:
                    content = contents[rule.path]
                    if len(content) < rule.min_bytes:
                        raise ValueError(f"Task contract failed: {rule.path} is too small")
                    if rule.contains and not all(word in content.decode("utf-8") for word in rule.contains):
                        raise ValueError(f"Task contract failed: missing required text in {rule.path}")
                    if rule.json_keys is not None:
                        data = json.loads(content)
                        if not isinstance(data, dict) or set(rule.json_keys) - data.keys():
                            raise ValueError(f"Task contract failed: required JSON keys in {rule.path}")
            if worker.isolated:
                with self.driver.ownership():
                    for name, baseline in worker.output_baselines.items():
                        target = self.path(name, writing=True)
                        current = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
                        if current != baseline:
                            raise RuntimeError("Output changed externally before isolated task publication")
                    for name, content in contents.items():
                        target = self.path(name, writing=True)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        temporary = target.with_name(target.name + "." + uuid4().hex + ".tmp")
                        try:
                            temporary.write_bytes(content)
                            os.replace(temporary, target)
                        finally:
                            temporary.unlink(missing_ok=True)
            record.artifacts = {name: hashlib.sha256(content).hexdigest() for name, content in contents.items()}
            state, error = "verified", None
        except Exception as exc:
            state, error, error_type = "failed", str(exc), type(exc).__name__
        finally:
            if timer is not None:
                timer.cancel()
            if worker is not None and not worker.closed:
                try:
                    worker.close()
                except Exception as exc:
                    state, error, error_type = "failed", f"Worker cleanup failed: {exc}", type(exc).__name__
            with self._cv:
                record.state, record.error = state, error
                if record.cancel.is_set():
                    record.state = "cancelled"
                elif (record.result or {}).get("status") == "blocked":
                    record.state = "blocked"
                elif (state == "failed" and not getattr(self.agent, "_need_human", False)
                      and (record.result or {}).get("status") != "blocked"
                      and record.attempt < self.settings.limits.task_max_attempts
                      and time.monotonic() < record.deadline):
                    record.feedback = error
                    record.state = "queued"
                record.worker = None
                record.activity = None
                self._running -= 1
                self.emit("task_finished", task_id=record.key, state=record.state, attempt=record.attempt,
                          stage_index=self.agent.stage_manager.stage_index,
                          budget=record.budget_status(self.settings.limits),
                          **({"error": error, "error_type": error_type} if error else {}))

    def _accept_scope(self, records):
        """Recheck artifact digests and complete once all writers have stopped."""
        lease = records[0].lease
        result = {"complete": False, "error": "One or more delegated tasks did not pass"}
        try:
            if not self._closed and all(r.state == "verified" and not r.cancel.is_set() for r in records):
                for r in records:
                    for name, digest in r.artifacts.items():
                        if hashlib.sha256(self.path(name).read_bytes()).hexdigest() != digest:
                            raise ValueError("Output changed after task validation")
                timeout = max(self.agent.cfg.get_value("call_time_out", 300),
                              *(r.result.get("timeout", 0) for r in records))
                result = self.driver.finish(lease, timeout,
                    summaries=[r.result["summary"] for r in records],
                    stage_args=records[0].result.get("stage_args") if len(records) == 1 else None)
                if (result.get("complete") and self.handoff is not None
                        and all(stage.is_completed() or stage.is_skipped() for stage in self.agent.stage_manager.stages)):
                    self.handoff.record_artifacts()
        except Exception as exc:
            result = {"complete": False, "error": str(exc)}
        with self._cv:
            retry = (not result.get("complete") and not self._closed
                     and not getattr(self.agent, "_need_human", False)
                     and all(r.state == "verified" and r.attempt < self.settings.limits.task_max_attempts
                             and time.monotonic() < r.deadline for r in records))
            if retry:
                # Parent repair is a new bounded attempt on the same lease. The
                # worker may repair the parent but still cannot complete it.
                if self.agent.stage_manager.get_current_stage() is lease.root:
                    lease.steps = ()
                for r in records:
                    r.state, r.feedback = "queued", result
            else:
                for name in {r.plan_id for r in records}:
                    self.plans[name]["state"] = ("completed" if result.get("complete") else
                        "waiting_human" if getattr(self.agent, "_need_human", False) else
                        "blocked" if any(r.state == "blocked" for r in records) else "failed")
                    self.plans[name]["validation"] = result
                self.driver.release(lease)
                if not self._workflow_lock.locked():
                    self.workflow_state = "waiting_plan" if result.get("complete") else self.plans[records[0].plan_id]["state"]
            self._validating = False
            self.emit("scope_validated", complete=bool(result.get("complete")), retry=retry)

    def planning_context(self):
        """Describe actual stage requirements, role capabilities and current planning ownership."""
        with self._cv:
            current = self.agent.stage_manager.get_current_stage()
            root, steps = self.driver.resolve_scope(self.settings.delegation_scope)
            return {"delegation": {
                        "default_scope": self.settings.delegation_scope,
                        "root": root.title_short() if root is not None else None,
                        "remaining_substages": [{"name": step.name, "title": step.title()} for step in steps],
                        "narrow_scope_requires_reason": bool(steps),
                        "scope_tools": {
                            "auto/subtree": "One worker completes all listed substages with CompleteSubStage, "
                                            "Check, per-step journals and enabled Skill tools before submitting.",
                            "stage": "Only the current step; Check, journals and enabled Skill tools; then submit.",
                            "task": "Independent file artifacts only; no Check, Skill or stage journal tools."}},
                    "handoff": self.handoff.context(self.planning["token"] if self.planning and self.planning.get("handoff") else None) if self.handoff else None,
                    "stage": self.agent.stage_manager.get_current_tips() if current is not None else None,
                    "stage_index": self.agent.stage_manager.stage_index,
                    "stage_name": getattr(current, "name", None),
                    "planning_token": self.planning["token"] if self.planning else None,
                    "max_workers": self.settings.max_workers,
                    "default_role": self.settings.default_role,
                    "stage_roles": dict(self.settings.stage_roles),
                    "roles": {name: {"description": role.description, "backend": role.backend,
                                     "allowed_tools": sorted(set(role.allowed_tools) & self.agent.multi_agent_business_names)}
                              for name, role in self.settings.roles.items()},
                    "write_dirs": self.agent.cfg.get_value("write_dirs", []),
                    "un_write_dirs": self.agent.cfg.get_value("un_write_dirs", []),
                    "task_contracts": {name: contract.model_dump()
                                       for name, contract in self.settings.task_contracts.items()},
                    "split_policy": "Independent file tasks may declare outputs without a named contract. "
                                    "Configured output rules and final stage Checker remain mandatory. "
                                    "Tests and shared protocol state require exclusive scope. "
                                    "Continuous subtree steps use auto/subtree, not separate stage plans."}

    def validate_handoff(self, token):
        """Authorize only the active completed Super's explicit handoff turn."""
        turn = self.planning
        if turn and turn.get("handoff") and turn["submitted"]:
            if self._closed or self.agent._need_break or self._workflow_stop.is_set() or time.monotonic() >= turn["deadline"]:
                raise PermissionError("Supervisor handoff was cancelled or expired")
        else:
            self.validate_planning()
        if (self.handoff is None or not self.planning.get("handoff")
                or self.handoff.run is not self.handoff.chain.current
                or token != self.planning["token"]):
            raise PermissionError("Use the current Super handoff transition_token")
        if self.planning["blocked"]:
            raise PermissionError("Handoff turn is paused")

    def list_workflows(self):
        """List trusted candidate metadata without loading tools into this Agent."""
        if self.handoff is None:
            raise RuntimeError("Workflow handoff runtime is not attached")
        return self.handoff.chain.candidates(self.handoff.run)

    def workflow_transition_status(self):
        """Provide detached chain status for this run's control endpoint."""
        if self.handoff is None:
            raise RuntimeError("Workflow handoff runtime is not attached")
        return self.handoff.chain.view()

    def request_next_workflow(self, **arguments):
        """Accept a structured peer request and yield without starting a candidate inline."""
        from ucagent.core.workflow.contracts import NextWorkflow
        request = NextWorkflow.model_validate(arguments)
        with self._cv:
            self.validate_handoff(request.transition_token)
            result = self.handoff.chain.accept(self.handoff.run, request)
            self.planning["submitted"] = result["transition_id"]
            return result

    def complete_workflow_chain(self, **arguments):
        """Record a final Super decision after real business acceptance."""
        from ucagent.core.workflow.contracts import EndChain
        request = EndChain.model_validate(arguments)
        with self._cv:
            self.validate_handoff(request.transition_token)
            result = self.handoff.chain.accept(self.handoff.run, request)
            self.planning["submitted"] = result["transition_id"]
            return result

    def validate_planning(self, token=None, *, submitting=False):
        """Fence stale callbacks, cancelled turns and extra submissions across both transports."""
        turn = self.planning
        if turn is None:
            raise PermissionError("No active supervisor planning turn")
        if self._closed or self.agent.is_break() or self._workflow_stop.is_set():
            raise PermissionError("Supervisor planning was cancelled")
        if time.monotonic() >= turn["deadline"]:
            raise TimeoutError("Supervisor planning deadline exceeded")
        if self.agent.stage_manager.stage_index != turn["stage_index"]:
            raise PermissionError("Stage changed during planning")
        if submitting:
            if (token or PLANNING_OWNER.get()) != turn["token"]:
                raise PermissionError("Use the current CurrentTips planning_token")
            if turn["submitted"] or turn["blocked"] or turn["final"]:
                raise PermissionError("Planning turn is no longer accepting a plan")

    def charge_planning_tool(self, action):
        """Bound managed tool calls, including reads, without charging external status polling."""
        with self._cv:
            if self.planning is None:
                return
            owned = PLANNING_OWNER.get() == self.planning["token"]
            if action in {"status", "wait", "cancel", "workflow_transition_status"} and not owned:
                return
            if self.planning["submitted"] and self.planning.get("handoff") and action in {"request_next_workflow", "complete_workflow_chain"}:
                return
            self.validate_planning()
            if self.planning["submitted"] or self.planning["blocked"]:
                raise PermissionError("Planning turn already submitted; wait for its result")
            if self.planning.get("handoff"):
                self.handoff.chain.charge(self.handoff.run, "tool_calls")
            self.planning["calls"] += 1
            if self.planning["calls"] > self.settings.limits.supervisor_tool_calls:
                raise RuntimeError("Supervisor tool-call budget exhausted")

    def pause_workflow(self, reason, planning_token=None):
        """Yield to the user without manufacturing a task or accepting a stage."""
        with self._cv:
            if self.planning and self.planning.get("handoff"):
                self.validate_handoff(planning_token or PLANNING_OWNER.get())
                self.handoff.chain.state["status"] = "paused"
                self.handoff.chain.save()
            else:
                self.validate_planning(planning_token, submitting=True)
            self.planning["blocked"] = reason
            self._supervisor_question = reason
            self.agent._need_human = True
            self.emit("supervisor_blocked", reason=reason)
            return {"paused": True, "reason": reason}

    def planning_interrupted(self):
        """Stop an overdue model or a command planner immediately after it submits."""
        turn = self.planning
        return bool(self._workflow_stop.is_set() or (turn and (self._closed
                    or time.monotonic() >= turn["deadline"]
                    or (getattr(self.agent.backend, "requires_mcp", False)
                        and (turn["submitted"] or turn["blocked"])))))

    def before_backend_turn(self):
        """Charge a supervisor execution turn independently of provider model calls."""
        with self._cv:
            self.validate_planning()
            turn = self.planning
            if turn.get("handoff"):
                self.handoff.chain.charge(self.handoff.run, "backend_turns")
            turn["backend_turns"] = turn.get("backend_turns", 0) + 1
            if turn["backend_turns"] > self.settings.limits.supervisor_backend_turns:
                raise RuntimeError("Supervisor backend-turn budget exhausted")

    def before_model(self):
        """Enforce the precise model-call budget when the selected backend exposes it."""
        with self._cv:
            turn = self.planning
            if turn is None or turn["submitted"] or turn["blocked"]:
                return {"jump_to": "end"}
            self.validate_planning()
            turn["rounds"] += 1
            if turn["rounds"] > self.settings.limits.supervisor_model_rounds:
                raise RuntimeError("Supervisor model-round budget exhausted")
        return None

    def yielded(self):
        """A successful control tool, not provider text, decides whether Super must yield."""
        return bool(self.planning and (self.planning["submitted"] or self.planning["blocked"]))

    def plan_turn(self, *, final=False, handoff=False):
        """Run one real bounded Super model turn; only its tools may produce a plan."""
        from ucagent.core.backends.blank import BlankBackend
        if isinstance(self.agent.backend, BlankBackend):
            raise ValueError("Automatic multi-agent planning requires a non-blank Super backend; "
                             "an external MCP Super may submit plans through SubAgentTool instead")
        with self._cv:
            if self.planning is not None:
                raise RuntimeError("A supervisor planning turn is already active")
            current = self.agent.stage_manager.get_current_stage()
            key = id(current)
            count = self._planning_turns.get(key, 0)
            if count >= self.settings.limits.planning_revisions:
                raise RuntimeError("Supervisor planning revisions exhausted; operator intervention required")
            self._planning_turns[key] = count + 1
            turn = {"token": uuid4().hex, "stage_index": self.agent.stage_manager.stage_index,
                    "deadline": time.monotonic() + self.settings.limits.supervisor_timeout_seconds,
                    "rounds": 0, "calls": 0, "submitted": None, "blocked": None, "final": final or handoff, "handoff": handoff}
            if handoff:
                deadline = self.handoff.run["decision"]["deadline"]
                remaining = self.handoff.chain.settings.decision_limits.timeout_seconds if deadline is None else max(0, deadline - time.time())
                turn["deadline"] = min(turn["deadline"], time.monotonic() + remaining)
            self.planning = turn
        token = PLANNING_OWNER.set(turn["token"])
        failed = True
        try:
            self.emit("supervisor_started", stage_index=turn["stage_index"], final=final)
            context = {**self.planning_context(), "user_instruction": self._instruction,
                       "previous_result": self._feedback, "workflow_complete": final or handoff,
                       "phase": "handoff" if handoff else "business",
                       "phase_label": self.agent.cfg.get_value("multi_agent_prompts.handoff_label", "Workflow handoff") if handoff else None}
            from .display import planning_message
            prompt = self.agent._default_system_prompt
            if handoff:
                prompt += "\n\n" + self.agent.cfg.get_value("multi_agent_prompts.handoff", "")
            messages = [self.agent.backend.get_system_message(prompt),
                        self.agent.backend.get_human_message(json.dumps(context, ensure_ascii=False, default=str),
                                                             display_text=planning_message(context))]
            config = self.agent.get_work_config()
            while True:
                self.agent.do_work({"messages": messages}, config)
                if final or turn["submitted"] or turn["blocked"] or self.agent.is_break():
                    break
                # A text-only turn does not surrender the planning lease or reset budgets.
                context["continuation"] = ("Choose RequestNextWorkflow, CompleteWorkflowChain or PauseWorkflow." if handoff else
                                           "Continue this planning turn: submit SubAgentTool or PauseWorkflow.")
                messages = [self.agent.backend.get_human_message(
                    json.dumps(context, ensure_ascii=False, default=str), display_text=context["continuation"])]
            if time.monotonic() >= turn["deadline"]:
                raise TimeoutError("Supervisor planning deadline exceeded")
            if not final and not turn["submitted"] and not turn["blocked"] and not self.agent.is_break():
                raise RuntimeError("Super returned without SubAgentTool or PauseWorkflow; no task was dispatched")
            failed = False
            return turn["submitted"]
        finally:
            PLANNING_OWNER.reset(token)
            with self._cv:
                if failed and turn["submitted"] and not handoff:
                    self.cancel(turn["submitted"], stop_workflow=False)
                self.planning = None
                self.emit("supervisor_finished", stage_index=turn["stage_index"],
                          backend_turns=turn.get("backend_turns", 0),
                          model_rounds=turn["rounds"] if self.agent.backend.capabilities.model_rounds else None,
                          tool_calls=turn["calls"], failed=failed)

    def start_workflow(self, instruction=None):
        """Start one managed Super loop; MCP clients need not poll to advance it."""
        from ucagent.core.backends.blank import BlankBackend
        with self._cv:
            if self._closed:
                raise RuntimeError("Multi-agent service is closing")
            if self._workflow_lock.locked() or (self.workflow_thread and self.workflow_thread.is_alive()):
                return self.status()
            if isinstance(self.agent.backend, BlankBackend):
                raise ValueError("StartWorkflow requires a non-blank Super backend; external MCP planners use SubAgentTool")
            if self.agent.is_work_busy():
                raise RuntimeError("A model operation is already active")
            self.agent.set_break(False)
            current = self.agent.stage_manager.get_current_stage()
            if current is not None and current.is_hmcheck_needed() and current.get_hmcheck_state()[0] is True:
                self.agent._need_human = False
            self.workflow_state = "running"
            self.workflow_thread = threading.Thread(target=self.run_workflow, args=(instruction,),
                                                    name="ucagent-supervisor", daemon=True)
            try:
                self.workflow_thread.start()
            except Exception:
                self.workflow_state = "failed"
                raise
            return self.status()

    def run_workflow(self, message=None):
        """Own the Super planning/result loop and retain ownership through model shutdown."""
        if not self._workflow_lock.acquire(blocking=False):
            raise RuntimeError("A workflow supervisor is already active")
        self._workflow_stop.clear()
        if message is not None:
            self._instruction = message
            if self.handoff is not None:
                if not self.handoff.chain.state["goal"]:
                    self.handoff.chain.state["goal"] = message
                elif message != self.handoff.chain.state["goal"]:
                    self.handoff.chain.state["instructions"].append(message)
                self.handoff.chain.save()
            if self._supervisor_question is not None:
                self.agent._need_human = False
                self._supervisor_question = None
        try:
            return self._drive_workflow()
        except Exception as exc:
            self.workflow_state = "paused" if self.agent.is_break() or self._closed or (self.handoff and self.handoff.run["business_status"] == "completed") else "failed"
            if self.handoff:
                self.handoff.chain.state["status"] = "paused"
                self.handoff.chain.save()
            self.emit("workflow_failed", error=str(exc))
            return self.status()
        finally:
            self._workflow_lock.release()
            self.emit("workflow_stopped", state=self.workflow_state)

    def _drive_workflow(self):
        """Wake Super at stage/result boundaries and block on worker completion between turns."""
        self.workflow_state = "running"
        while not self._closed and not self.agent.is_break() and not self._workflow_stop.is_set():
            if self.agent.stage_manager.get_current_stage() is None:
                # Completing the last child can exhaust the stage list before its
                # worker submits. A failed scope must never become overall success.
                latest = next(reversed(self.plans.values()), None)
                if latest is not None and latest["state"] != "completed":
                    self.workflow_state = "failed"
                    self.emit("workflow_completion_rejected", error="The last delegated scope was not accepted")
                    return self.status()
                if getattr(self.agent, "workflow_handoff_settings", None) is not None:
                    if self.handoff is None:
                        raise RuntimeError("Workflow handoff requires an application-owned executor")
                    if (not all(stage.is_completed() or stage.is_skipped() for stage in self.agent.stage_manager.stages) or self._running or self._validating
                            or self.driver.active_lease is not None or getattr(self.agent, "_need_human", False)):
                        raise RuntimeError("Workflow handoff is waiting for business acceptance and writer teardown")
                    self.agent.stage_manager.save_stage_info()
                    if latest is None and self.handoff.run["business_status"] != "completed":
                        self.handoff.record_artifacts()
                    self.handoff.run["business_status"] = "completed"
                    self.handoff.chain.save()
                    # An accepted decision survives model return/cancellation; only runtime may consume it.
                    if self.handoff.run["transition"] is None:
                        self.plan_turn(handoff=True)
                    self.workflow_state = "handoff" if self.handoff.run["transition"] else "waiting_human"
                    return self.status()
                self.plan_turn(final=True)
                if self.agent.is_break() or self._closed:
                    break
                with self.driver.ownership():
                    result = self.agent.stage_manager.exit()
                self.workflow_state = "completed" if result.get("exit") else "failed"
                return result
            if getattr(self.agent, "_need_human", False):
                self.workflow_state = "waiting_human"
                return self.status()
            with self._cv:
                active = next((key for key, p in self.plans.items() if p["state"] == "running"), None)
            if active is None:
                active = self.plan_turn()
                if active is None:
                    self.workflow_state = "waiting_human" if self.agent._need_human else "paused"
                    return self.status()
            while self.plans[active]["state"] == "running" and not self._closed:
                if self.agent.is_break() or self._workflow_stop.is_set():
                    self.cancel(active)
                # Completion/validation events notify this condition. Waiting
                # spends no Super model turns and never polls through LLM tools.
                with self._cv:
                    if self.plans[active]["state"] == "running":
                        self._cv.wait(0.2)
            self._feedback = self.status(active)
            if self.plans[active]["state"] == "waiting_human":
                self.workflow_state = "waiting_human"
                return self._feedback
            # A failed/blocked plan returns real task and Checker feedback to
            # Super. Per-stage planning and per-target work budgets remain spent.
        self.workflow_state = "paused"
        return self.status()
