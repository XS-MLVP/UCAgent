"""Structured interruptions and operator recovery, independent of presentation and transport."""

import copy
import hashlib
import time
from uuid import uuid4
from typing import Literal

from pydantic import Field, model_validator
from .contracts import StrictModel
from .requirements import Requirement, RequirementChecks


# Class-wide policy; concrete tool names and provider error strings never select recovery.
ISSUE_POLICIES = {
    "repairable": {"handling": "replan", "actions": []},
    "capability": {"handling": "check_prerequisites", "actions": ["resume"]},
    "environment": {"handling": "check_prerequisites", "actions": ["resume"]},
    "input": {"handling": "ask_user", "actions": ["reply"]},
    "review": {"handling": "human_review", "actions": ["review"]},
    "budget": {"handling": "extend_budget", "actions": ["grant"]},
    "operator": {"handling": "wait_for_operator", "actions": ["resume"]},
    "execution": {"handling": "execution_circuit", "actions": ["resume"]},
}


class IssueReport(StrictModel):
    """Describe unfinished work; a report is not proof of a tool or environment failure."""

    kind: Literal["repairable", "capability", "environment", "input", "review"]
    summary: str = Field(min_length=1, max_length=2000)
    next_action: str = Field(min_length=1, max_length=2000)
    conditions: list[Requirement] = Field(default_factory=list, max_length=20)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class BudgetGrant(StrictModel):
    """Explicit positive additions, never resets, scoped to this interruption."""

    planning_revisions: int = Field(default=0, ge=0, le=20, strict=True)
    supervisor_backend_turns: int = Field(default=0, ge=0, le=100, strict=True)
    supervisor_model_rounds: int = Field(default=0, ge=0, le=100, strict=True)
    supervisor_tool_calls: int = Field(default=0, ge=0, le=1000, strict=True)
    supervisor_timeout_seconds: int = Field(default=0, ge=0, le=86400, strict=True)
    worker_backend_turns: int = Field(default=0, ge=0, le=1000, strict=True)
    worker_model_rounds: int = Field(default=0, ge=0, le=1000, strict=True)
    worker_tool_calls: int = Field(default=0, ge=0, le=10000, strict=True)
    worker_timeout_seconds: int = Field(default=0, ge=0, le=86400, strict=True)
    task_max_attempts: int = Field(default=0, ge=0, le=10, strict=True)


class RecoveryRequest(StrictModel):
    """Bind an operator action to the displayed interruption and reject stale actions."""

    issue_id: str = Field(min_length=1)
    action: Literal["resume", "reply", "grant"] = "resume"
    message: str = Field(default="", max_length=32000)
    grant: BudgetGrant = Field(default_factory=BudgetGrant)

    @model_validator(mode="after")
    def explicit_grant(self):
        """Additional execution authority must be an explicit grant action."""
        additions = any(self.grant.model_dump().values())
        if (self.action == "grant") != additions:
            raise ValueError("Use action=grant with positive budget additions; other actions cannot add budget")
        if self.action == "reply" and not self.message.strip():
            raise ValueError("A reply requires a nonempty message")
        return self


class BudgetExhausted(RuntimeError):
    """A typed execution limit whose identity is not inferred from exception text."""

    def __init__(self, dimension, used, limit, task_id=None):
        """Retain the measured limit separately from its readable diagnostic."""
        self.dimension, self.used, self.limit, self.task_id = dimension, used, limit, task_id
        super().__init__(f"{dimension} budget exhausted ({used}/{limit})")


class ExecutionCircuitOpen(RuntimeError):
    """Stop a worker after repeated execution failures, not healthy work volume."""

    def __init__(self, category, task_id=None):
        self.category, self.task_id = category, task_id
        super().__init__(f"Repeated {category.replace('_', ' ')} failures opened the execution circuit")


class RecoveryControl:
    """Share interruption state and idempotent recovery across all frontends."""

    def init_recovery(self):
        """Create live-session recovery state without starting any execution."""
        self.issue = None
        self.requirement_checks = RequirementChecks()
        self.recovery_history = []
        self._recovered = set()
        self._stage_grants = {}
        self._pending_budget = None
        self._pending_execution_issue = None
        self._paused_at = None
        self._accepted_at_pause = {}

    def accepted_files(self):
        """Fingerprint declared inputs and outputs of completed stages for live recovery."""
        from ucagent import find_files_by_pattern
        snapshots = {}
        for index, stage in enumerate(self.agent.stage_manager.stages):
            if not stage.is_completed():
                continue
            paths = set(stage.reference_files) | set(find_files_by_pattern(str(self.workspace), stage.output_files))
            snapshot = {}
            for name in paths:
                try:
                    source = self.path(name)
                    if source.is_file():
                        with source.open("rb") as stream:
                            snapshot[name] = hashlib.file_digest(stream, "sha256").hexdigest()
                    else:
                        snapshot[name] = None
                except (ValueError, OSError):
                    snapshot[name] = None
            snapshots[index] = snapshot
        return snapshots

    def supervisor_limit(self, dimension):
        """Apply explicit additions for the currently owned stage."""
        stage = self.agent.stage_manager.get_current_stage()
        return getattr(self.settings.limits, dimension) + self._stage_grants.get(id(stage), {}).get(dimension, 0)

    def worker_limit(self, record, dimension):
        """Retain task additions across attempts and plan identifiers."""
        return getattr(self.settings.limits, dimension) + record.budget.grants.get(dimension, 0)

    def planning_used(self):
        """Report consumed stage planning without double-counting admitted plans."""
        key = id(self.agent.stage_manager.get_current_stage())
        return max(self._planning_turns.get(key, 0), self._scope_revisions.get(key, 0))

    def interrupt_budget(self, dimension, used, limit, task_id=None):
        """Carry typed exhaustion through backends that may wrap tool exceptions."""
        error = BudgetExhausted(dimension, used, limit, task_id)
        if task_id is None:
            self._pending_budget = error
        elif task_id in self.records:
            self.records[task_id].budget_error = error
        return error

    def set_issue(self, kind, summary, next_action, *, source="runtime", task_id=None,
                  evidence=None, budget=None, conditions=None, checks=None, category=None):
        """Publish one actionable interruption after writers have drained."""
        with self._cv:
            self.issue = {"id": uuid4().hex, "kind": kind, "summary": summary,
                          "next_action": next_action, "source": source, "task_id": task_id,
                          "stage_index": self.agent.stage_manager.stage_index, "handling": ISSUE_POLICIES[kind]["handling"],
                          "evidence": copy.deepcopy(evidence or []), "budget": budget,
                          "conditions": copy.deepcopy(conditions or []), "checks": copy.deepcopy(checks or []),
                          "created_at": time.time()}
            if category:
                self.issue["category"] = category
            self._paused_at = time.monotonic()
            self._accepted_at_pause = self.accepted_files()
            self.workflow_state = "waiting_human"
            self.agent._need_human = True
            self.emit("workflow_attention", issue=copy.deepcopy(self.issue))

    def pause_for_budget(self, error):
        """Route measured exhaustion into the shared recoverable pause policy."""
        self.set_issue("budget", str(error), "Add execution budget to continue the unfinished work.",
                       task_id=error.task_id,
                       budget={"dimension": error.dimension, "used": error.used, "limit": error.limit})
        self._pending_budget = None

    def recovery_status(self):
        """Project current reasons and allowed controls without exposing credentials."""
        issue = copy.deepcopy(self.issue)
        actions = []
        suggestion = {}
        if issue:
            kind = issue["kind"]
            actions = list(ISSUE_POLICIES[kind]["actions"])
            if kind == "review":
                current = self.agent.stage_manager.get_current_stage()
                if current is None or not current.is_hmcheck_needed() or current.get_hmcheck_state()[0] is True:
                    actions = ["resume"]
            if kind == "budget":
                dimension = issue["budget"]["dimension"]
                suggestion[dimension] = getattr(self.settings.limits, dimension)
                limit = self.supervisor_limit("planning_revisions")
                if limit > 0 and self.planning_used() >= limit:
                    suggestion["planning_revisions"] = self.settings.limits.planning_revisions
        planning_limit = self.supervisor_limit("planning_revisions")
        if issue and planning_limit > 0 and self.planning_used() >= planning_limit:
            suggestion["planning_revisions"] = self.settings.limits.planning_revisions
            if "grant" not in actions:
                actions.append("grant")
        return {"issue": issue, "actions": actions, "suggested_grant": suggestion,
                "planning": {"used": self.planning_used(), "limit": planning_limit or None},
                "history": copy.deepcopy(self.recovery_history[-20:])}

    def chat(self, message):
        """Answer without dispatch authority or consuming stage planning revisions."""
        with self._cv:
            if self.has_active() or self.planning is not None:
                raise RuntimeError("Execution is active; send guidance or pause before starting a chat")
            stopped, interrupted = self.agent._need_break, self._workflow_stop.is_set()
            self.agent._need_break = False
            self._workflow_stop.clear()
        try:
            return self.plan_turn(chat=message)
        finally:
            self.agent._need_break = stopped
            if interrupted:
                self._workflow_stop.set()
            self._pending_budget = None

    def recover(self, request, *, start=True):
        """Resume this live task once, preserving consumed budgets and accepted stages."""
        request = RecoveryRequest.model_validate(request)
        with self._cv:
            if request.issue_id in self._recovered:
                return {"accepted": True, "duplicate": True, "state": self.workflow_state}
            if self._closed or not self.issue or self.issue["id"] != request.issue_id:
                raise ValueError("Interruption changed; refresh task status before continuing")
            if (self.has_active() or self.planning is not None or self.agent.is_work_busy()
                    or (self.workflow_thread and self.workflow_thread.is_alive())):
                raise RuntimeError("Execution is still stopping; wait for all writers to finish")
            issue = self.issue
            if issue["kind"] == "review":
                current = self.agent.stage_manager.get_current_stage()
                if current is not None and current.is_hmcheck_needed() and current.get_hmcheck_state()[0] is not True:
                    raise ValueError("Complete the pending human review before continuing")
            if issue["kind"] == "input" and not request.message.strip():
                raise ValueError("Reply to the pending question before continuing")
            additions = {k: v for k, v in request.grant.model_dump().items() if v}
            dimension = (issue.get("budget") or {}).get("dimension")
            if dimension and dimension not in additions:
                raise ValueError(f"Add {dimension} budget before continuing")
            current = self.agent.stage_manager.get_current_stage()
            planning_limit = self.supervisor_limit("planning_revisions")
            if planning_limit > 0 and self.planning_used() >= planning_limit and not additions.get("planning_revisions"):
                raise ValueError("Add planning_revisions budget before continuing")
            target = self.records.get(issue.get("task_id"))
            if target and issue.get("kind") == "execution":
                category = issue.get("category")
                if category:
                    target.budget.failure_streaks[category] = 0
                target.execution_issue = None
            if issue.get("kind") == "execution" and issue.get("category", "").startswith("supervisor_"):
                self._supervisor_failure_streaks[issue["category"]] = 0
            if target and issue.get("conditions"):
                checks = self.requirement_checks.evaluate(self, target, issue["conditions"])
                issue["checks"] = checks
                if any(row["satisfied"] is False for row in checks):
                    self.emit("recovery_check_failed", issue=copy.deepcopy(issue))
                    raise ValueError("Prerequisites are still unmet; inspect the interruption checks before continuing")
            worker_additions = {k: v for k, v in additions.items() if k.startswith("worker_") or k == "task_max_attempts"}
            if worker_additions and target is None:
                raise ValueError("This interruption has no worker budget to extend")
            snapshots = self.accepted_files()
            changed = [index for index, files in self._accepted_at_pause.items() if snapshots.get(index) != files]
            if changed:
                with self.driver.ownership():
                    self.agent.stage_manager.invalidate_from(min(changed))
                current = self.agent.stage_manager.get_current_stage()
                self.emit("accepted_evidence_changed", stage_index=min(changed))
            stage_grants = self._stage_grants.setdefault(id(current), {})
            for key, value in additions.items():
                grants = target.budget.grants if key in worker_additions else stage_grants
                grants[key] = grants.get(key, 0) + value
            # Exclude only actual human wait; automatic repair and execution still consume time.
            waited = max(0, time.monotonic() - self._paused_at) if self._paused_at is not None else 0
            for budget in self._task_budgets.values():
                if budget.deadline is not None:
                    budget.deadline += waited
            if target and additions.get("worker_timeout_seconds"):
                target.deadline = max(target.deadline or time.monotonic(), time.monotonic()) + additions["worker_timeout_seconds"]
            self.recovery_history.append({"issue_id": issue["id"], "action": request.action,
                                          "grant": additions, "message": request.message, "time": time.time()})
            self._recovered.add(issue["id"])
            self.issue = None
            self._paused_at = None
            self._pending_budget = None
            self._pending_execution_issue = None
            self.agent._need_human = False
            self._supervisor_question = None
            if request.message.strip():
                self.queue_instruction(request.message)
            # A subtree may have advanced its last child before submitting. Recover that
            # missing submission under a fresh lease, not by declaring the scope accepted.
            resumed_key = None
            if not changed and target and target.lease.steps and current not in target.lease.steps and current is not target.lease.root:
                from .supervisor import StageLease
                lease = StageLease(target.lease.root, target.lease.steps, self.agent.stage_manager.stage_index)
                self.driver.active_lease = lease
                plan_id = "resume-" + uuid4().hex[:12]
                key = plan_id + "/" + target.spec.id
                record = type(target)(key, target.spec, plan_id, lease, target.split, target.role, budget=target.budget)
                record.feedback = "The authorized descendants have passed. Submit the actual aggregate result; do not modify completed artifacts."
                self.records[key] = record
                resumed_key = key
                self.plans[plan_id] = {"fingerprint": "recovery", "state": "running", "lease": lease,
                                       "validation": None, "tasks": [key]}
                self._cv.notify_all()
            self.emit("workflow_resumed", issue_id=issue["id"], grant=additions)
            if start:
                try:
                    return self.start_workflow()
                except Exception:
                    # No worker can start while this lock is held. Roll back only the queued lease.
                    if resumed_key is not None:
                        record = self.records.pop(resumed_key)
                        self.plans.pop(record.plan_id)
                        self.driver.release(record.lease)
                    # Keep the grant and a new actionable issue; retry cannot spend it twice.
                    self.set_issue("environment", "Execution could not be restarted.",
                                   "Retry resume when the execution service is available.", task_id=issue.get("task_id"))
                    raise
            self.agent.set_break(False)
            self.workflow_state = "idle"
            return self.status()
