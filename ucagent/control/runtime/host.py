"""Application lifetime, human waiting and ordered resource shutdown without a UI."""

from contextlib import contextmanager
import logging
import signal
import threading
import time

from ucagent.control.commands import create_registry, SessionCommands
from ucagent.control.controller import Controller, ControlError, public_data
from ucagent.control.runtime.operations import OperationExecutor, TERMINAL_STATES
from ucagent.control.runtime.output import OutputBuffer, MessageHandler
from ucagent.control.runtime.startup import StartupCommands
from ucagent.util.log import message
from ucagent.control.runtime.services import ServiceManager, lifecycle_timeout
from ucagent.util.functions import chmode_rw


class RuntimeHost:
    """Own one agent and coordinate controls, execution, services and final cleanup."""

    def __init__(self, agent, *, controller=None, operations=None, services=None,
                 mode="console", exit_on_completion=False, shutdown_timeout=5, force_exit=None):
        """Assemble injected owners without starting workers or touching terminal state."""
        if mode not in {"console", "service", "master", "once"}:
            raise ValueError("Unknown runtime mode")
        if getattr(agent, "runtime_host", None) is not None:
            raise ControlError("already_attached", "Agent already belongs to a runtime host.")
        self.agent = agent
        existing = getattr(agent, "_operation_owner", None)
        self.controller = controller or (existing.controller if existing else Controller(agent))
        self.operations = operations or existing or OperationExecutor(self.controller)
        if self.operations.controller is not self.controller:
            raise ValueError("Runtime owners must share one controller")
        self.services = services or getattr(agent, "services", None) or ServiceManager(agent, controller=self.controller)
        self.services.controller = self.controller
        self.force_exit = force_exit
        self.mode = mode
        self.exit_on_completion = exit_on_completion
        self.shutdown_timeout = lifecycle_timeout(shutdown_timeout)
        self.instance_state = "starting"
        self.execution_state = "idle"
        self.task_outcome = None
        self.close_reason = None
        self.exit_code = 0
        self._interrupt_handlers = {}
        self._message_views = set()
        self.errors = []
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._closed = threading.Event()
        self._thread = None
        self._steps = set()
        self._controls = set()
        self._seen_operations = set()
        self.output = OutputBuffer()
        self.messages = OutputBuffer()
        self.startup = StartupCommands(self)
        self._previous_message_handler = None
        self._previous_mcps_logger = None
        self._message_handler_installed = False
        self._cleanup = [self.output.close, self.restore_messages]
        self._close_requested = False
        self.registry = create_registry(self.controller, executors={
            "operations": self.operations, "stages": self.operations.stages,
            "services": self.services, "host": self, "session": SessionCommands()})
        from ucagent.plugins import register_plugin_commands
        register_plugin_commands(self.registry, getattr(agent, "plugins", []))
        agent.runtime_host = self
        agent.runtime_status_provider = self.snapshot
        self.controller.host = self
        self.operations.on_change = self._wake.set
        agent.stage_manager.completion_callback = self.complete_mission

    def attach_control(self, name, *, interrupt=None, messages=False):
        """Register an attached endpoint capable of completing human review."""
        with self._lock:
            if self._close_requested:
                raise ControlError("closing", "Runtime is closing.")
            self._controls.add(name)
            if interrupt is not None:
                self._interrupt_handlers.pop(name, None)
                self._interrupt_handlers[name] = interrupt
            if messages:
                self._message_views.add(name)
        self._wake.set()

    def detach_control(self, name):
        """Remove a disconnected frontend without cancelling its owned operations."""
        with self._lock:
            self._controls.discard(name)
            self._interrupt_handlers.pop(name, None)
            self._message_views.discard(name)
        self._wake.set()

    @property
    def message_view_attached(self):
        """Report whether model messages currently have a dedicated local display."""
        with self._lock:
            return bool(self._message_views)

    def interrupt(self):
        """Route SIGINT to the active control, falling back to runtime pause without a view."""
        with self._lock:
            handler = next(reversed(self._interrupt_handlers.values()), None)
        return handler() if handler is not None else self.pause()

    def message_echo(self, text, end="\n", **kwargs):
        """Keep model and MCP messages available even when no terminal view exists."""
        self.messages.write(str(text) + end)
        if not self.message_view_attached:
            sink = self._previous_message_handler or message
            sink(text, end=end)

    def restore_messages(self):
        """Release the agent message and MCP logger bindings during instance shutdown."""
        if self._message_handler_installed:
            if self._previous_message_handler is None:
                self.agent.unset_message_echo_handler()
            else:
                self.agent.set_message_echo_handler(self._previous_message_handler)
            self._message_handler_installed = False
        self.agent._mcps_logger = self._previous_mcps_logger

    def add_cleanup(self, callback):
        """Register instance-owned terminal or log restoration in reverse acquisition order."""
        self._cleanup.append(callback)

    def start(self):
        """Start the owned output bridge and supervisor; a closed instance cannot restart."""
        with self._lock:
            if self.instance_state != "starting":
                raise ControlError("invalid_state", "Runtime has already started or closed.")
            self.output.install()
            self._previous_message_handler = getattr(self.agent, "message_echo_handler", None)
            self._previous_mcps_logger = getattr(self.agent, "_mcps_logger", None)
            setter = getattr(self.agent, "set_message_echo_handler", None)
            if setter is not None:
                setter(self.message_echo)
                self._message_handler_installed = True
            logger = logging.Logger("ucagent.messages", level=logging.INFO)
            logger.addHandler(MessageHandler(self.message_echo))
            logger.propagate = False
            self.agent._mcps_logger = logger
            self.instance_state = "ready"
            self._thread = threading.Thread(target=self._supervise, name="ucagent-runtime", daemon=True)
            self._thread.start()
        self._wake.set()
        return self.snapshot()

    def snapshot(self):
        """Detach instance, execution and mission state without waiting for domain calls."""
        with self._lock:
            return public_data({"instance": self.instance_state, "execution": self.execution_state,
                                "task_outcome": self.task_outcome, "close_reason": self.close_reason,
                                "exit_code": self.exit_code, "errors": self.errors,
                                "controls": sorted(self._controls)})

    def pause(self):
        """Prevent future rounds; the current call keeps its model reservation."""
        self.agent.set_break(True)
        with self._lock:
            self.execution_state = "pausing" if self.operations._model_id else "paused"
        self._wake.set()
        return self.snapshot()

    def complete_mission(self):
        """Accept a domain-validated Exit notification without stopping its request thread."""
        with self._lock:
            self.task_outcome = "completed"
            self.execution_state = "completed"
            self.agent._is_exit = True
        if self.exit_on_completion or self.mode == "once":
            self.request_shutdown("mission_completed")
        self._wake.set()

    def request_shutdown(self, reason="quit", *, exit_code=0):
        """Record one close request and return immediately to the initiating tool or HTTP call."""
        with self._lock:
            if not self._close_requested:
                self._close_requested = True
                self.close_reason = reason
                self.exit_code = exit_code
                self.instance_state = "closing"
        self.operations.stop_accepting()
        self.services.stop_accepting()
        self._wake.set()
        return self.snapshot()

    def execute(self, command, arguments, session):
        """Handle lifetime commands through the same registry as other entrypoints."""
        if command == "quit":
            if arguments.get("force"):
                if self.force_exit is None:
                    raise ControlError("unavailable", "This runtime does not own process termination.")
                self.request_shutdown("forced_exit", exit_code=130)
                self.force_exit(130)
            return self.request_shutdown()
        raise ControlError("unknown_command", f"Unknown host command '{command}'.")

    def _supervise(self):
        """Observe operation boundaries and process cleanup on a dedicated owner thread."""
        while not self._closed.is_set():
            self._wake.wait()
            self._wake.clear()
            if self._close_requested:
                self._shutdown()
                continue
            records = self.operations.list()
            for record in records:
                if not record["model"] or record["state"] not in TERMINAL_STATES or record["id"] in self._seen_operations:
                    continue
                self._seen_operations.add(record["id"])
                reason = (record["result"] or {}).get("reason") if isinstance(record["result"], dict) else None
                with self._lock:
                    if self.task_outcome != "completed":
                        self.execution_state = ("failed" if record["state"] == "failed" else
                                                "paused" if record["state"] == "cancelled" else
                                                {"round_complete": "idle", "completed": "completed"}.get(reason, reason or "idle"))
                        if self.execution_state == "failed":
                            self.task_outcome = "failed"
            if (self.mode == "once" and self._seen_operations and not self.startup.active
                    and self.execution_state in {"idle", "failed"}
                    and not any(row["model"] and row["state"] not in TERMINAL_STATES for row in records)):
                self.request_shutdown("operation_finished", exit_code=int(self.execution_state == "failed"))
            if any(row["model"] and row["state"] not in TERMINAL_STATES for row in records):
                with self._lock:
                    self.execution_state = "pausing" if self.agent.is_break() else "running"
            with self._lock:
                waiting = self.execution_state == "waiting_human"
                has_control = bool(self._controls) or self.services.status("cmd")["state"] == "ready"
            if waiting and not has_control and self.mode == "once":
                self.task_outcome = "blocked"
                self.request_shutdown("human_review_unavailable", exit_code=2)

    def _shutdown(self):
        """Drain operations before persistence, sync, services and restoration; retain pending owners."""
        pending = self.operations.close(self.shutdown_timeout, cancel=self.close_reason != "mission_completed")
        if not pending["closed"]:
            return  # Operation completion wakes the supervisor for another cleanup attempt.
        steps = [("save", self.agent.stage_manager.save_stage_info),
                 ("sync", lambda: self.services.sync_workspace_back(reason="exit")),
                 ("notify", lambda: self.services.notify_exit(self.close_reason))]
        for name, action in steps:
            if name in self._steps:
                continue
            self._steps.add(name)
            try:
                result = action()
                if isinstance(result, list):
                    self.errors.extend({"step": name, "message": row.get("message", "Cleanup failed")}
                                       for row in result if isinstance(row, dict) and row.get("ok") is False)
            except Exception as error:
                self.errors.append({"step": name, "message": str(error)})
        try:
            stopped = self.services.close(self.shutdown_timeout)
        except Exception as error:
            self.errors.append({"step": "services", "message": str(error)})
            stopped = {"closed": False}
        if not stopped["closed"]:
            # A listener can finish independently of operation notifications.
            self._wake.wait(0.1)
            self._wake.set()
            return
        if "restore" not in self._steps:
            self._steps.add("restore")
            for action in [lambda: chmode_rw(getattr(self.agent, "cwd_read_only_files", [])), *reversed(self._cleanup)]:
                try:
                    action()
                except Exception as error:
                    self.errors.append({"step": "restore", "message": str(error)})
        with self._lock:
            if self.errors:
                self.exit_code = self.exit_code or 1
            self.instance_state = "failed" if self.errors else "closed"
        self._closed.set()

    def wait(self, timeout=None):
        """Wait for actual cleanup; timeout returns a snapshot that can still say closing."""
        self._closed.wait(timeout)
        return self.snapshot()

    @contextmanager
    def signals(self):
        """Install and restore process signals only on the main thread."""
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Runtime signals must be installed on the main thread")
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}

        def handler(signum, frame):
            """Route SIGTERM to shutdown and SIGINT to a safe pause boundary."""
            if signum == signal.SIGTERM:
                self.request_shutdown("signal")
            else:
                self.interrupt()

        try:
            for sig in previous:
                signal.signal(sig, handler)
            yield
        finally:
            for sig, callback in previous.items():
                signal.signal(sig, callback)
