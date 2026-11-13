"""Single-owner stage access and subtree leases over the existing StageManager."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import threading
from uuid import uuid4


STAGE_OWNER = ContextVar("multi_agent_stage_owner", default=None)


@dataclass
class StageLease:
    """Track the exact stage objects authorized for a single delegation scope."""

    root: object
    steps: tuple
    expected_index: int
    token: str = field(default_factory=lambda: uuid4().hex)
    finished: bool = False


class StageDriver:
    """Keep the real checkers authoritative and deny raw worker stage mutations."""

    def __init__(self, manager):
        """Attach one access guard without replacing the runtime coordinator."""
        self.manager = manager
        self.lock = threading.RLock()
        self.active_lease = None
        manager.multi_agent_access = self.authorize

    def authorize(self, kind):
        """Only controlled calls mutate stages; idle operator review remains available."""
        if STAGE_OWNER.get() is self:
            return
        if kind in {"review", "flags"} and self.active_lease is None:
            return
        raise PermissionError("Use the multi-agent task controls; direct stage mutation is disabled")

    @contextmanager
    def ownership(self):
        """Serialize trusted calls while preserving the existing coordinator gates."""
        with self.lock:
            token = STAGE_OWNER.set(self)
            try:
                yield
            finally:
                STAGE_OWNER.reset(token)

    def resolve_scope(self, scope):
        """Preview the actual remaining tree without acquiring or changing stage ownership."""
        with self.lock:
            current = self.manager.get_current_stage()
            if current is None:
                return None, ()
            root = current
            if scope in {"auto", "subtree"}:
                while getattr(root, "parent", None) is not None:
                    root = root.parent
            sequence = root.get_substages() if root is not current else [current]
            remaining = self.manager.stages[self.manager.stage_index:]
            steps = tuple(stage for stage in sequence if stage is not root and stage in remaining)
            return root, steps

    def acquire(self, scope):
        """Lease the same tree exposed to the planner, never inferred from display numbers."""
        with self.ownership():
            root, steps = self.resolve_scope(scope)
            if root is None:
                raise ValueError("No current stage remains")
            if scope == "subtree" and not getattr(root, "substages", ()):
                raise ValueError("Current stage has no subtree")
            lease = StageLease(root, steps, self.manager.stage_index)
            self.active_lease = lease
            return lease

    def validate(self, lease):
        """Reject stale pointers before any task-bound stage or file operation."""
        if self.active_lease is not lease or lease.finished:
            raise PermissionError("Task stage lease is no longer active")
        if self.manager.stage_index != lease.expected_index:
            raise PermissionError("Stage changed; this task lease is stale")

    def tips(self, lease):
        """Return only the current authorized step, not the next unrelated stage."""
        with self.lock:
            self.validate(lease)
            current = self.manager.get_current_stage()
            done = bool(lease.steps) and current not in lease.steps
            context = {"scope_root": lease.root.name,
                       "remaining_substages": [stage.title_short() for stage in lease.steps
                                               if stage in self.manager.stages[self.manager.stage_index:]]}
            if done:
                return {**context, "scope_done": True, "next_action": "SubmitTaskResult"}
            return {**context, "scope_done": False, "step_token": lease.token,
                    "next_action": "CompleteSubStage" if lease.steps else "SubmitTaskResult",
                    "stage_index": self.manager.stage_index,
                    "tips": self.manager.get_current_tips()}

    def check(self, lease, timeout, stage_args):
        """Run Check under the single mutation owner, including batch transitions."""
        with self.ownership():
            self.validate(lease)
            if lease.steps and self.manager.get_current_stage() not in lease.steps:
                raise PermissionError("Subtree work is finished; submit the task result")
            return self.manager.check(timeout, stage_args=stage_args)

    def complete_substage(self, lease, step_token, timeout, stage_args):
        """Advance one authorized descendant and rotate the per-step token."""
        with self.ownership():
            self.validate(lease)
            if step_token != lease.token:
                return {"validation": {"complete": False}, "error_code": "STALE_STEP_TOKEN",
                        "error": "Stale step_token; use the returned current step_token",
                        **self.tips(lease)}
            if self.manager.get_current_stage() not in lease.steps:
                raise PermissionError("Only delegated descendants can be completed")
            result = self.manager.complete(timeout, stage_args=stage_args)
            lease.expected_index = self.manager.stage_index
            lease.token = uuid4().hex
            return {"validation": result, **self.tips(lease)}

    def finish(self, lease, timeout, *, summaries=(), stage_args=None):
        """Apply parent gates only after all workers relinquish write access."""
        with self.ownership():
            self.validate(lease)
            if self.manager.get_current_stage() in lease.steps:
                return {"complete": False, "error": "Delegated substages remain incomplete"}
            if getattr(lease.root, "is_group", lambda: False)():
                result = {"complete": True, "scope_completed": True}
            elif self.manager.get_current_stage() is not lease.root:
                raise PermissionError("Scope root is no longer current")
            else:
                if lease.root.meta_get_journal() is None and summaries:
                    self.manager.set_current_stage_journal("\n\n".join(summaries))
                result = self.manager.complete(timeout, stage_args=stage_args)
                lease.expected_index = self.manager.stage_index
            if result.get("complete"):
                lease.finished = True
                self.active_lease = None
            return result

    def release(self, lease):
        """Release a failed or paused scope only after worker teardown."""
        with self.lock:
            if self.active_lease is lease:
                self.active_lease = None
