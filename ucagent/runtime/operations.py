"""Owned long operations, one model slot, cooperative cancellation and shell work.

Workers never enter an input loop or inject exceptions into other threads.
A cancellation request retains its slot until the actual call has returned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import contextmanager
from contextvars import ContextVar
import math
from pathlib import Path
import random
import shlex
import threading
import time
from typing import Callable
from uuid import uuid4

from ucagent.runtime.control.commands import CommandSession, COMMAND_ORIGIN
from ucagent.core.stage.vmanager import StageManager
from ucagent.runtime.control.controller import ControlError, Controller, public_data
from ucagent.runtime.output import OUTPUT_OWNER
from ucagent.util.output import OUTPUT_METADATA, OUTPUT_SINK, output_context
from ucagent.util.functions import PROCESS_CANCELLATION, run_shell_process


OPERATION_PARENT = ContextVar("ucagent_operation_parent", default=None)


TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})


class OperationCancelled(Exception):
    """A worker reached a cooperative cancellation boundary."""


class OperationFailure(ControlError):
    """An operation failed while still producing useful structured result data."""

    def __init__(self, code, message, result):
        """Preserve the actual result alongside the business error."""
        super().__init__(code, message)
        self.result = result


@dataclass(frozen=True)
class RetryPolicy:
    """Match loop_settings: an attempt budget refreshed only by sustained progress."""

    max_attempts: int = 10
    delay_min: float = 5
    delay_max: float = 10
    progress_reset_after: float = 120

    def __post_init__(self):
        """Reject invalid retry settings before accepting any work."""
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        for value in (self.delay_min, self.delay_max, self.progress_reset_after):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError("Retry timings must be finite non-negative numbers")
        if self.delay_max < self.delay_min:
            raise ValueError("delay_max must not be below delay_min")


@dataclass
class OperationRecord:
    """Keep mutable worker bookkeeping private to the executor's lock."""

    id: str
    command: str
    model: bool
    session_id: str | None = None
    input_line: str = ""
    foreground: bool = False
    parent_id: str | None = None
    result_kind: str = "data"
    state: str = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: object = None
    error: dict | None = None
    attempts: int = 0
    stdout: str = ""
    stderr: str = ""
    output_truncated: bool = False
    cancel: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None

    def snapshot(self):
        """Return detached data; callers must hold the executor lock."""
        return public_data({"id": self.id, "command": self.command, "state": self.state,
                            "model": self.model, "session_id": self.session_id,
                            "input_line": self.input_line, "foreground": self.foreground,
                            "parent_id": self.parent_id, "result_kind": self.result_kind,
                            "created_at": self.created_at,
                            "started_at": self.started_at, "finished_at": self.finished_at,
                            "result": self.result, "error": self.error, "attempts": self.attempts,
                            "cancel_requested": self.cancel.is_set(), "stdout": self.stdout,
                            "stderr": self.stderr, "output_truncated": self.output_truncated})


class OperationContext:
    """Expose cancellation, bounded waits and streamed output to an owned worker."""

    def __init__(self, executor, record):
        """Bind a context to exactly one record and cancellation token."""
        self.executor = executor
        self.record = record
        self.cancel_event = record.cancel

    def checkpoint(self):
        """Stop at a safe boundary without raising in any other thread."""
        if self.cancel_event.is_set():
            raise OperationCancelled()

    def wait(self, seconds):
        """Wait interruptibly; cancellation is handled by this worker itself."""
        if self.cancel_event.wait(seconds):
            raise OperationCancelled()

    def emit(self, stream, text):
        """Keep bounded stdout/stderr tails available to polling frontends."""
        if stream not in ("stdout", "stderr"):
            raise ValueError("Output stream must be stdout or stderr")
        with self.executor._lock:
            value = getattr(self.record, stream) + text
            self.record.output_truncated |= len(value) > self.executor.output_limit
            setattr(self.record, stream, value[-self.executor.output_limit:])
        host = getattr(self.executor.agent, "runtime_host", None)
        if host is not None:
            with output_context(source="command", kind="output", operation_id=self.record.id,
                                session_id=self.record.session_id, stream=stream):
                host.output.emit(text)


class StageCoordinator:
    """Reserve stage mutations briefly, leaving domain checks and queries unblocked."""

    def __init__(self, executor, manager):
        """Bind one manager to the executor's admission lock and completion condition."""
        if manager.control_guard is not None:
            raise ControlError("already_attached", "Stage manager already has a coordinator.")
        self.executor = executor
        self.manager = manager
        self._active = None
        self._cancellation = None
        self._idle = threading.Condition(executor._lock)
        manager.control_guard = self.mutation

    @contextmanager
    def mutation(self, kind, *, stage=None, expected_revision=None, target_index=None, after=None):
        """Admit one mutation, permit same-thread domain nesting, and persist its revision."""
        thread_id = threading.get_ident()
        with self.executor._lock:
            nested = self._active is not None and self._active[0] == thread_id
            if not nested:
                if self._active is not None:
                    raise ControlError("busy", "A stage mutation is still active.")
                model = self.executor._records.get(self.executor._model_id)
                if model is not None and model.cancel.is_set():
                    raise ControlError("busy", "Model cancellation is still in progress.", operation_id=model.id)
                if kind in {"human", "review", "flags", "skip"} and self.executor._model_id is not None:
                    raise ControlError("busy", "A model operation is still active.",
                                       operation_id=self.executor._model_id)
                if not self.executor._accepting:
                    raise ControlError("closing", "Stage coordinator is closing.")
                if expected_revision is not None and expected_revision != self.manager.control_revision:
                    raise ControlError("stale_revision", "Stage state changed; refresh before modifying it.",
                                       control_revision=self.manager.control_revision)
                if target_index is not None and target_index != self.manager.stage_index:
                    raise ControlError("stale_stage", "The requested stage is no longer current.",
                                       stage_index=self.manager.stage_index)
            if stage is not None and kind in {"review", "flags", "skip"}:
                if stage not in self.manager.stages:
                    raise ControlError("invalid_stage", "Stage does not belong to this coordinator.")
                index = self.manager.stages.index(stage)
                if stage.is_completed() or index < self.manager.stage_index:
                    raise ControlError("invalid_stage", "Completed stages cannot be modified.")
                if kind == "skip" and index == self.manager.stage_index:
                    raise ControlError("invalid_stage", "The current stage cannot be skipped or unskipped.")
                if kind == "review" and (index != self.manager.stage_index or stage.is_skipped()
                                         or not stage.is_hmcheck_needed()):
                    raise ControlError("invalid_stage", "Only the current required human review can be modified.")
            if not nested:
                self._active = (thread_id, kind)
                self._cancellation = model.cancel if model is not None else threading.Event()
        cancellation_token = PROCESS_CANCELLATION.set(self._cancellation)
        ticket = {}
        succeeded = False
        persisted = False
        try:
            yield ticket
            succeeded = True
        finally:
            PROCESS_CANCELLATION.reset(cancellation_token)
            if not nested:
                try:
                    # Even a failed mutation can have changed checker evidence.
                    with self.executor._lock:
                        self.manager.control_revision += 1
                        ticket["control_revision"] = self.manager.control_revision
                    self.manager.save_stage_info()
                    persisted = True
                finally:
                    with self.executor._lock:
                        self._active = None
                        self._cancellation = None
                        self._idle.notify_all()
                        self.executor.on_change()
                        # Resume is admitted only after review is saved; no competing
                        # mutation can slip between releasing this reservation and submit.
                        if succeeded and persisted and after is not None:
                            ticket["operation"] = after()

    def snapshot(self):
        """Read detached control fields without invoking checkers or waiting for work."""
        with self.executor._lock:
            stages = []
            for index, stage in enumerate(self.manager.stages):
                approved, message = stage.get_hmcheck_state()
                stages.append({"index": index, "name": stage.name,
                               "is_completed": stage.is_completed(), "is_skipped": stage.is_skipped(),
                               "needs_human_check": stage.is_hmcheck_needed(),
                               "human_review": {"approved": approved, "message": message},
                               "need_fail_llm_suggestion": stage.need_fail_llm_suggestion,
                               "need_pass_llm_suggestion": stage.need_pass_llm_suggestion,
                               "effective_fail_llm_suggestion": self.manager.stage_need_llm_fail_suggestion(stage),
                               "effective_pass_llm_suggestion": self.manager.stage_need_llm_pass_suggestion(stage)})
            return {"stage_index": self.manager.stage_index,
                    "control_revision": self.manager.control_revision,
                    "mutation": self._active[1] if self._active is not None else None,
                    "stages": stages}

    def execute(self, command, arguments, session: CommandSession):
        """Translate the declared stage commands into revision-checked controls."""
        control = self.executor.controller
        snapshot = self.snapshot()
        revision = snapshot["control_revision"]
        current = snapshot["stage_index"]
        rows = snapshot["stages"]
        if command == "hmcheck_cstat":
            return {**snapshot, "stages": rows[current:current + 1]}
        if command == "hmcheck_list":
            return {**snapshot, "stages": [row for row in rows if row["needs_human_check"]]}
        if command in ("lmcheck_plist", "lmcheck_flist"):
            return snapshot
        if command in ("hmcheck_pass", "hmcheck_fail", "hmcheck_pass_and_continue"):
            return control.review_stage(current, revision, command != "hmcheck_fail",
                                        arguments.get("message", ""),
                                        resume=command == "hmcheck_pass_and_continue", session=session)
        if command in ("skip_stage", "unskip_stage"):
            return control.update_stage_flags([arguments["index"]], revision,
                                              skip=command == "skip_stage")
        if command in ("hmcheck_set", "lmcheck_pset", "lmcheck_fset"):
            index, value = arguments["index"], arguments["value"]
            if index == "all":
                indices = [row["index"] for row in rows if not row["is_completed"]
                           and not row["is_skipped"] and row["index"] >= current]
            else:
                control._stage(index)
                indices = [index]
            reading = value is None if command == "hmcheck_set" else value == "unchanged"
            if reading:
                return {**snapshot, "stages": [rows[i] for i in indices]}
            field = {"hmcheck_set": "hmcheck_needed", "lmcheck_pset": "llm_pass_suggestion",
                     "lmcheck_fset": "llm_fail_suggestion"}[command]
            return control.update_stage_flags(indices, revision, **{field: value})
        raise ControlError("unknown_command", f"Unknown stage command '{command}'.")


class OperationExecutor:
    """Own worker threads and the single top-level model slot for one controller."""

    def __init__(self, controller: Controller, *, retry_policy=None, clock=time.monotonic,
                 output_limit=1048576):
        """Read resolved settings and bind ownership without starting a thread."""
        if controller.operations is not None or getattr(controller.agent, "_operation_owner", None) is not None:
            raise ControlError("already_attached", "This agent already has an operation executor.")
        if type(output_limit) is not int or output_limit < 1:
            raise ValueError("output_limit must be a positive integer")
        self.controller = controller
        self.agent = controller.agent
        cfg = self.agent.cfg.as_dict()
        settings = cfg.get("loop_settings", {})
        self.retry_policy = retry_policy or RetryPolicy(
            settings.get("max_loop_retry", 10), settings.get("retry_delay_start", 5),
            settings.get("retry_delay_end", 10), settings.get("loop_alive_time", 120))
        self.shell_timeout = self.parse_timeout(cfg.get("cmd_timeout", 1200))
        self.output_limit = output_limit
        self._clock = clock
        self._lock = threading.RLock()
        self._records: dict[str, OperationRecord] = {}
        self._model_id = None
        self._accepting = True
        self.on_change = lambda: None
        manager = getattr(self.agent, "stage_manager", None)
        self.stages = StageCoordinator(self, manager) if isinstance(manager, StageManager) else None
        controller.operations = self
        self.agent._operation_owner = self

    @staticmethod
    def parse_timeout(value):
        """Parse the documented non-negative timeout or disabled spelling."""
        if isinstance(value, str) and value.lower() in ("off", "none", "disabled"):
            return 0.0
        if isinstance(value, bool):
            raise ControlError("invalid_argument", "Timeout must be a finite non-negative number or off.")
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise ControlError("invalid_argument", "Invalid timeout.") from exc
        if not math.isfinite(value) or value < 0:
            raise ControlError("invalid_argument", "Timeout must be finite and non-negative.")
        return value

    def submit(self, command: str, action: Callable, *, model=False, result_kind="data"):
        """Reserve capacity atomically and return an accepted operation snapshot."""
        with self._lock:
            if not self._accepting:
                raise ControlError("closing", "Operation executor is closing.")
            if model and self.stages is not None and self.stages._active is not None:
                raise ControlError("busy", "A stage mutation is still active.")
            if model and self._model_id is not None:
                raise ControlError("busy", "A model operation is still active.", operation_id=self._model_id)
            service = getattr(self.agent, "multi_agent", None)
            if model and service is not None and service._workflow_lock.locked():
                raise ControlError("busy", "The managed Super workflow is still active.")
            origin = COMMAND_ORIGIN.get()
            parent_id = OPERATION_PARENT.get()
            if parent_id not in self._records:
                parent_id = None
            if parent_id is not None and self._records[parent_id].cancel.is_set():
                raise OperationCancelled()
            if model:
                # Reset pause only after parent cancellation and slot admission have passed.
                self.agent.set_break(False)
            record = OperationRecord(uuid4().hex, command, model,
                                     session_id=origin[0] if origin else None,
                                     input_line=origin[1] if origin else command,
                                     foreground=origin[2] if origin else False,
                                     parent_id=parent_id, result_kind=result_kind)
            self._records[record.id] = record
            if model:
                self._model_id = record.id
            record.thread = threading.Thread(target=self._run, args=(record, action),
                                             name=f"ucagent-operation-{record.id}", daemon=False)
            try:
                record.thread.start()
            except Exception as exc:
                record.state = "failed"
                record.finished_at = time.time()
                record.error = {"code": "start_failed", "message": str(exc), "details": {}}
                if model:
                    self._model_id = None
                record.done.set()
                raise ControlError("start_failed", str(exc), operation_id=record.id) from exc
            return record.snapshot()

    def _run(self, record, action):
        """Finalize once, only after domain work and context cleanup have ended."""
        context = OperationContext(self, record)
        origin_token = COMMAND_ORIGIN.set((record.session_id, record.input_line, record.foreground)
                                          if record.session_id is not None else None)
        parent_token = OPERATION_PARENT.set(record.id)
        token = PROCESS_CANCELLATION.set(record.cancel)
        host = getattr(self.agent, "runtime_host", None)
        output_token = OUTPUT_OWNER.set(host.output if host is not None else None)
        metadata_token = OUTPUT_METADATA.set({"operation_id": record.id, "session_id": record.session_id})
        sink_token = OUTPUT_SINK.set(host.events.append if host is not None else None)
        result, error = None, None
        try:
            with self._lock:
                context.checkpoint()
                record.state = "running"
                record.started_at = time.time()
            self.on_change()
            result = public_data(action(context))
        except OperationCancelled:
            record.cancel.set()
        except BaseException as exc:
            # Even SystemExit raised by a worker must release its reservation.
            error = {"code": "execution_failed", "message": str(exc),
                     "details": {"type": type(exc).__name__}}
            if isinstance(exc, ControlError):
                try:
                    error = exc.as_dict()
                    if isinstance(exc, OperationFailure):
                        result = public_data(exc.result)
                except Exception as serialization_error:
                    # An invalid error payload must still produce a failed record.
                    error = {"code": "unsupported_result", "message": str(exc),
                             "details": {"type": type(exc).__name__,
                                         "serialization_error": str(serialization_error)}}
        finally:
            PROCESS_CANCELLATION.reset(token)
            OUTPUT_OWNER.reset(output_token)
            OUTPUT_METADATA.reset(metadata_token)
            OUTPUT_SINK.reset(sink_token)
            OPERATION_PARENT.reset(parent_token)
            COMMAND_ORIGIN.reset(origin_token)
            with self._lock:
                # A model transport can return before an in-flight MCP check ends.
                # Condition.wait releases this lock so the tool can finish normally.
                while record.model and self.stages is not None and self.stages._active is not None:
                    self.stages._idle.wait()
                record.result = result
                record.error = error
                record.state = "cancelled" if record.cancel.is_set() else ("failed" if error else "succeeded")
                record.finished_at = time.time()
                if record.model:
                    self._model_id = None
                if host is not None:
                    host.events.append(f"{record.command}: {record.state}" +
                                       (f" — {error['message']}" if error else "") + "\n",
                                       source="command", kind="result", operation_id=record.id,
                                       session_id=record.session_id, level="ERROR" if error else "INFO")
                record.done.set()
            self.on_change()

    def record_result(self, command, result, *, error=None, session_id=None, input_line=None):
        """Give an already completed synchronous command the same queryable result contract."""
        with self._lock:
            failed = (isinstance(result, dict) and result.get("ok") is False) or (
                isinstance(result, list) and any(isinstance(row, dict) and row.get("ok") is False for row in result))
            if failed and error is None:
                error = {"code": "command_failed", "message": "Command reported a failure.", "details": {}}
            record = OperationRecord(uuid4().hex, command, False, state="failed" if error else "succeeded",
                                     result=public_data(result), error=public_data(error), finished_at=time.time(),
                                     session_id=session_id, input_line=input_line)
            record.done.set()
            self._records[record.id] = record
            return record.snapshot()

    def get(self, operation_id):
        """Read a snapshot without waiting for a worker or model call."""
        with self._lock:
            if operation_id not in self._records:
                raise ControlError("unknown_operation", "Operation does not belong to this executor.")
            return self._records[operation_id].snapshot()

    def list(self):
        """Read all operation records for this instance."""
        with self._lock:
            return [record.snapshot() for record in self._records.values()]

    def wait(self, operation_id, timeout=None):
        """Wait up to the caller's budget; pending work keeps its actual state."""
        with self._lock:
            if operation_id not in self._records:
                raise ControlError("unknown_operation", "Operation does not belong to this executor.")
            record = self._records[operation_id]
        started = time.monotonic()
        if record.done.wait(timeout):
            remaining = None if timeout is None else max(0, timeout - (time.monotonic() - started))
            if record.thread is not None and record.thread.ident is not None and record.thread is not threading.current_thread():
                record.thread.join(remaining)
        return self.get(operation_id)

    def wait_tree(self, context, operation_id, *, wait_models=True):
        """Wait for a command and its continuation children with cooperative cancellation."""
        while True:
            if context.cancel_event.is_set():
                self.cancel(operation_id)
            row = self.wait(operation_id, 0.05)
            if row["state"] in TERMINAL_STATES:
                break
        for child in self.list():
            if child["parent_id"] != operation_id:
                continue
            if not wait_models and child["model"] and not context.cancel_event.is_set():
                continue
            finished = self.wait_tree(context, child["id"], wait_models=wait_models)
            if finished["state"] != "succeeded":
                return finished
        context.checkpoint()
        return row

    def cancel(self, operation_id):
        """Request cancellation idempotently while retaining the model reservation."""
        with self._lock:
            if operation_id not in self._records:
                raise ControlError("unknown_operation", "Operation does not belong to this executor.")
            record = self._records[operation_id]
            for child in list(self._records.values()):
                if child.parent_id == operation_id:
                    self.cancel(child.id)
            if record.state not in TERMINAL_STATES and not record.cancel.is_set():
                record.cancel.set()
                record.state = "cancelling"
                if record.model:
                    self.agent.set_break(True)
            return record.snapshot()

    def stop_accepting(self):
        """Reject new work while letting the current tool response finish."""
        with self._lock:
            self._accepting = False

    def close(self, timeout=0, *, cancel=True):
        """Stop admission and request cleanup, reporting calls still in progress."""
        deadline = time.monotonic() + self.parse_timeout(timeout)
        with self._lock:
            self._accepting = False
            ids = list(self._records)
            if cancel:
                if self.stages is not None and self.stages._cancellation is not None:
                    self.stages._cancellation.set()
                for operation_id in ids:
                    self.cancel(operation_id)
        for operation_id in ids:
            self.wait(operation_id, max(0, deadline - time.monotonic()))
        with self._lock:
            while self.stages is not None and self.stages._active is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.stages._idle.wait(remaining)
            pending = [record.id for record in self._records.values()
                       if not record.done.is_set() or (record.thread is not None and record.thread.is_alive())]
            stage_pending = self.stages is not None and self.stages._active is not None
            result = {"closed": not pending and not stage_pending, "pending": pending}
            if stage_pending:
                result["pending_stage_mutation"] = self.stages._active[1]
            return result

    def execute(self, command, arguments, session: CommandSession):
        """Dispatch registered runtime commands or submit domain work to the slot."""
        arguments = public_data(arguments)
        if command == "agent_is_break":
            return {"is_break": self.agent.is_break()}
        if command in ("agent_break", "agent_unbreak"):
            with self._lock:
                active = self._records.get(self._model_id)
                if command == "agent_unbreak" and active is not None and active.cancel.is_set():
                    raise ControlError("busy", "Cancellation is still in progress.", operation_id=active.id)
                self.agent.set_break(command == "agent_break")
                return {"is_break": self.agent.is_break()}
        if command == "cmd_timeout":
            if arguments["timeout"] is not None:
                session.shell_timeout = self.parse_timeout(arguments["timeout"])
            return {"seconds": self.shell_timeout if session.shell_timeout is None else session.shell_timeout}
        if command == "shell":
            words = shlex.split(arguments["command"])
            dangerous = {"chmod", "chown", "cp", "dd", "fdisk", "format", "halt", "kill",
                         "killall", "mkfs", "mount", "mv", "pkill", "reboot", "rm", "rmdir",
                         "shutdown", "su", "sudo", "umount"}
            if words and words[0] in dangerous and not session.confirmed:
                raise ControlError("confirmation_required", "Confirm this shell command before execution.")
            cwd = Path(session.cwd).resolve()
            if Path(session.workspace).resolve() != self.controller.workspace or not cwd.is_relative_to(self.controller.workspace):
                raise ControlError("invalid_path", "Shell directory must belong to this workspace.")
            if not cwd.is_dir():
                raise ControlError("invalid_path", "Shell working directory does not exist.")
            if not arguments["command"].strip():
                raise ControlError("invalid_argument", "Shell command cannot be empty.")
            timeout = self.shell_timeout if session.shell_timeout is None else session.shell_timeout

            def shell(context):
                """Execute and retain actual exit status even on timeout or cancellation."""
                result = run_shell_process(cwd, arguments["command"], context.emit,
                                           cancel_event=context.cancel_event, idle_timeout=timeout,
                                           output_limit=self.output_limit)
                if result["reason"] == "timeout":
                    raise OperationFailure("idle_timeout", "Shell command exceeded its idle timeout.", result)
                if result["reason"] != "cancelled" and result["returncode"] != 0:
                    raise OperationFailure("process_failed", "Shell command exited unsuccessfully.", result)
                return result

            return self.submit(command, shell)
        if command == "sleep":
            seconds = self.parse_timeout(arguments["seconds"])

            def sleep(context):
                """Wait without blocking the control interface or ignoring cancellation."""
                context.wait(seconds)
                return {"seconds": seconds}

            return self.submit(command, sleep)
        if command in ("tool_invoke", "messages_summary"):
            def business(context):
                """Run existing domain handlers inside the shared model reservation."""
                context.checkpoint()
                if command == "tool_invoke":
                    return self.controller.tool_invoke(**arguments)
                return self.controller.messages_summary()

            return self.submit(command, business, model=True)
        if command not in {"continue", "continue_with_message", "loop", "next_round",
                           "next_round_with_message", "chat", "short_prompt"}:
            raise ControlError("unknown_command", f"Unknown operation '{command}'.")
        from ucagent.core.backends.blank import BlankBackend
        if isinstance(getattr(self.agent, "backend", None), BlankBackend):
            raise ControlError("unsupported_mode", "Model work is not supported by BlankBackend.")
        message = arguments.get("message", "")
        if command == "short_prompt":
            prompts = self.controller.short_prompt_list()
            name = arguments["name"]
            if name not in prompts:
                raise ControlError("not_found", f"Short prompt '{name}' not found.")
            prompt = str(prompts[name])
            message = prompt.rstrip() + "\n" + message if message else prompt
        if command in ("continue_with_message", "next_round_with_message", "chat") and not message.strip():
            raise ControlError("invalid_argument", "Message cannot be empty.")

        def model(context):
            """Call the domain only after this operation owns the model slot."""
            context.checkpoint()
            if command in ("continue", "continue_with_message", "loop"):
                return self._loop(context, message)
            if command in ("chat", "short_prompt"):
                self.agent.custom_chat(message)
            else:
                self.agent.one_loop(message or None)
            service = getattr(self.agent, "multi_agent", None)
            if service is not None and service.workflow_state == "failed":
                raise OperationFailure("delegation_failed", "Delegated workflow stopped; inspect TaskStatus.", service.status())
            reason = ("completed" if self.agent.is_exit() else "waiting_human" if self.agent._need_human
                      else "paused" if self.agent.is_break() else "round_complete")
            return {"reason": reason,
                    "invoke_round": self.agent.invoke_round}

        return self.submit(command, model, model=True)

    def _loop(self, context, message):
        """Schedule domain rounds and retry failures without entering a debugger."""
        policy = self.retry_policy
        remaining = policy.max_attempts
        if message:
            self.agent.set_continue_msg(message)
        self.agent._need_human = False
        while True:
            context.checkpoint()
            started = self._clock()
            start_round = self.agent.invoke_round
            with self._lock:
                context.record.attempts += 1
            try:
                while not self.agent.is_exit():
                    context.checkpoint()
                    if self.agent.is_break():
                        return {"reason": "paused", "invoke_round": self.agent.invoke_round}
                    revision = self.agent.stage_manager.validation_revision
                    index = self.agent.stage_manager.stage_index
                    self.agent.one_loop()
                    service = getattr(self.agent, "multi_agent", None)
                    if service is not None and service.workflow_state == "failed":
                        raise OperationFailure("delegation_failed", "Delegated workflow stopped; inspect TaskStatus.", service.status())
                    if service is not None and service.handoff is not None and service.workflow_state in {"handoff", "paused"}:
                        return {"reason": service.workflow_state, "invoke_round": self.agent.invoke_round}
                    self.agent._update_stalled_rounds(revision, index)
                    context.checkpoint()
                    if self.agent.is_exit():
                        return {"reason": "completed", "invoke_round": self.agent.invoke_round}
                    if self.agent.is_break():
                        return {"reason": "paused", "invoke_round": self.agent.invoke_round}
                    if self.agent._need_human:
                        return {"reason": "waiting_human", "invoke_round": self.agent.invoke_round}
                return {"reason": "completed", "invoke_round": self.agent.invoke_round}
            except (OperationCancelled, OperationFailure):
                raise
            except Exception:
                context.checkpoint()
                remaining -= 1
                if (self.agent.invoke_round > start_round
                        and self._clock() - started > policy.progress_reset_after):
                    remaining = policy.max_attempts
                if remaining <= 0 or self.agent.is_break():
                    raise
                retry_at = time.monotonic() + random.uniform(policy.delay_min, policy.delay_max)
                while time.monotonic() < retry_at:
                    if self.agent.is_break():
                        return {"reason": "paused", "invoke_round": self.agent.invoke_round}
                    context.wait(min(0.1, max(0, retry_at - time.monotonic())))
