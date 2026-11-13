"""Stable application controls routed to one current workflow instance with epoch fences."""

from contextlib import contextmanager
from pathlib import Path
from contextvars import ContextVar
import signal
import threading

from ucagent.runtime.control.commands import CommandResult, CommandSession
from ucagent.runtime.control.controller import ControlError
from ucagent.runtime.events import EventBuffer
from ucagent.runtime.output import OutputBuffer
from ucagent.runtime.services import ServiceManager


EXPECTED_RUN = ContextVar("workflow_control_expected_run", default=None)


class RoutedOwner:
    """Resolve reads dynamically and fence captured callbacks to their original instance."""

    def __init__(self, application, attribute):
        """Bind an owner kind, never a mutable Agent reference."""
        self.application = application
        self.attribute = attribute

    def __getattr__(self, name):
        """A callback captured for A must never silently execute against B."""
        app = self.application
        host = app.active
        owner = host
        for part in self.attribute.split("."):
            owner = getattr(owner, part)
        if name == "agent":
            return app.agent
        if name in {"workspace_access", "workspace_queries", "stages"}:
            return RoutedOwner(app, self.attribute + "." + name)
        value = getattr(owner, name)
        if not callable(value):
            return value

        def invoke(*args, **kwargs):
            """Check the routing epoch before invoking a previously captured owner method."""
            with app._route_lock:
                expected = EXPECTED_RUN.get()
                if host is not app.active or (expected and expected != app.executor.chain.current["run_id"]):
                    raise ControlError("stale_run", "The workflow changed; refresh status and resubmit.")
                return value(*args, **kwargs)
        return invoke


class ChainRegistry:
    """Retain one public command surface while rejecting stale-session mutations."""

    def __init__(self, application):
        """Route command lookup and invocation through the application-owned executor."""
        self.application = application
        self._sessions = {}

    def __getattr__(self, name):
        """Expose read-only help and completion from the currently selected registry."""
        return getattr(self.application.active.registry, name)

    def submit(self, line, session):
        """Dispatch once under the route lock, preserving source identity for queued work."""
        app = self.application
        with app._route_lock:
            command = line.strip() or (session.last_command if session.repeat else "")
            if not command:
                return None
            spec = app.active.registry.resolve(command.split()[0])
            name = spec.name
            run_id = app.executor.chain.current["run_id"]
            if EXPECTED_RUN.get() not in (None, run_id):
                raise ControlError("stale_run", "The workflow changed; refresh status and resubmit.")
            if name == "status":
                self._sessions[session.id] = run_id
                session.workspace = Path(app.active.agent.workspace)
                session.cwd = session.workspace
                return CommandResult("workflow_status", app.snapshot())
            if name == "quit":
                if command.split()[1:] == ["force"] and app.force_exit:
                    app.request_shutdown("forced_exit")
                    app.force_exit(130)
                return CommandResult("quit", app.request_shutdown())
            if name == "agent_break":
                return CommandResult("pause", app.pause())
            if self._sessions.setdefault(session.id, run_id) != run_id:
                raise ControlError("stale_run", "The workflow changed; run status before submitting another command.")
            if name in {"continue", "continue_with_message"} and app.executor.chain.state["status"] == "paused":
                arguments = spec.parse(command.partition(" ")[2])
                return CommandResult(name, app.executor.resume(arguments.get("message")))
            transition = app.executor.chain.current["transition"]
            if transition and transition["status"] not in {"activated", "completed"}:
                if name not in {"help", "task_status", "current_tips", "mission_info"}:
                    raise ControlError("handoff_in_progress", "Workflow handoff is in progress; use status, pause or quit.")
            if spec.owner == "services":
                return CommandResult(spec.name, app.services.execute(spec.name, spec.parse(command.partition(" ")[2]), session))
            return app.active.registry.submit(command, session)

    def execute(self, line, session):
        """Keep synchronous callers on the same identity and transition policy."""
        return self.submit(line, session)


class WorkflowApplication:
    """Own application controls and output while peer RuntimeHosts retire independently."""

    def __init__(self, executor, *, force_exit=None, interactive=False):
        """Create no model and make no workflow decision; attach deterministic control routing."""
        self.executor = executor
        self.workflow_chain = executor.chain
        self._route_lock = executor._lock
        self.force_exit = force_exit
        self.interactive = interactive
        self.active = executor.active
        self._writers = 0
        executor.control_idle = lambda: self._writers == 0
        self.agent = RoutedOwner(self, "agent")
        self.controller = RoutedOwner(self, "controller")
        self.operations = RoutedOwner(self, "operations")
        self.events = EventBuffer()
        self.output = OutputBuffer(events=self.events)
        self.messages = OutputBuffer()
        self.registry = ChainRegistry(self)
        self._cleanup = []
        self._controls = {}
        self._closed = threading.Event()
        self.exit_code = 0
        self.session = None
        # This separate manager owns only public application endpoints, not Agent sessions.
        self.agent.services = None
        self.services = ServiceManager(self.agent, controller=self.controller)
        self.agent.runtime_host = self
        self.output.install()
        self.attach_instance(self.active)
        executor.on_activate = self.attach_instance
        self.startup = self.active.startup

    def begin_control_write(self, expected, *, control_only=False):
        """Reserve a public writer before dispatch; handoff waits for its actual response boundary."""
        with self._route_lock:
            current = self.workflow_chain.current
            if expected != current["run_id"]:
                raise ControlError("stale_run", "Refresh status before mutating the current workflow.")
            transition = current["transition"]
            if not control_only and (self.executor.stopping or transition is not None):
                raise ControlError("handoff_in_progress", "Workflow handoff is in progress; use status, pause or quit.")
            self._writers += 1

    def end_control_write(self):
        """Release only after the admitted public mutation has returned."""
        with self._route_lock:
            self._writers -= 1

    def attach_instance(self, host):
        """Move output subscriptions and operator workspace after A cleanup, before B execution."""
        with self._route_lock:
            previous = self.active
            previous.output.unsubscribe(self.output.write)
            previous.messages.unsubscribe(self.messages.write)
            self.active = host
            host.output.subscribe(self.output.write)
            host.messages.subscribe(self.messages.write)
            for name, options in self._controls.items():
                host.attach_control(name, **options)
            self.startup = host.startup
            if self.session is not None:
                # Internal console rebinds explicitly; network sessions must refresh their run fence.
                self.registry._sessions[self.session.session.id] = self.executor.chain.current["run_id"]
                self.session.session = CommandSession(Path(host.agent.workspace))
                self.session._history_file = Path(host.agent.workspace) / ".ucagent/command_history.json"

    def add_cleanup(self, callback):
        """Keep frontend subscriptions alive until the application itself closes."""
        self._cleanup.append(callback)

    def attach_control(self, name, **options):
        """Track application controls so the next Host sees the same human-review capability."""
        self._controls[name] = options
        self.active.attach_control(name, **options)

    def detach_control(self, name):
        """Detach a view without stopping the workflow chain."""
        self._controls.pop(name, None)
        self.active.detach_control(name)

    def message_echo(self, text, end="\n", **kwargs):
        """Route TUI messages through the currently active instance output owner."""
        self.active.message_echo(text, end=end, **kwargs)

    def pause(self):
        """Pause active work and any accepted-but-gated successor."""
        self.executor.pause()
        return self.snapshot()

    def interrupt(self):
        """Apply SIGINT to the entire handoff boundary, including a preparing candidate."""
        return self.pause()

    def request_shutdown(self, reason="quit", *, exit_code=0):
        """Request application shutdown without closing the caller's public endpoint inline."""
        self.exit_code = max(self.exit_code, exit_code)
        self.executor.shutdown()
        return self.snapshot()

    def shutdown_status(self):
        """Include a candidate's pending ownership in the public shutdown view."""
        return {"pending": [h.shutdown_status() for h in (self.active, self.executor.candidate) if h],
                "preparing": self.executor.preparing is not None and not self.executor.prepare_done.is_set()}

    def snapshot(self):
        """Distinguish business completion, transition progress and overall chain outcome."""
        return {**self.active.snapshot(), "instance": "closed" if self._closed.is_set() else
                "closing" if self.executor.stopping else "ready", "exit_code": self.exit_code,
                "workflow_chain": self.executor.chain.view(), "handoff_error": self.executor.error}

    def pump(self):
        """Observe lifecycle events until the chain ends; public services outlive source retirement."""
        try:
            while not self.executor.closed():
                self.executor.step()
                chain = self.executor.chain
                host = self.executor.active
                if not self.executor.stopping and chain.state["status"] != "completed":
                    if host._closed.is_set() and not chain.current["transition"]:
                        self.request_shutdown("active_instance_closed", exit_code=host.exit_code or 2)
                    elif not self.interactive and not host.agent.multi_agent.has_active() and not self._controls and self.services.status("cmd")["state"] != "ready":
                        if self.executor.error or host.agent.multi_agent.workflow_state in {"paused", "waiting_human", "failed"}:
                            self.request_shutdown("unattended_chain_blocked", exit_code=1 if self.executor.error else 2)
                threading.Event().wait(0.02)
        except BaseException as exc:
            self.executor.error = str(exc)
            self.request_shutdown("handoff_failure", exit_code=1)
            while not self.executor.closed():
                self.executor.step()
                threading.Event().wait(0.05)
        finally:
            while not self.services.close(0.1)["closed"]:
                pass
            self.exit_code = max(self.exit_code, self.active.exit_code)
            self.executor.chain.state["quiescent"] = not any(h.errors for h in
                (self.active, self.executor.candidate) if h)
            self.executor.chain.save()
            for cleanup in reversed(self._cleanup):
                cleanup()
            self.output.close()
            self.messages.close()
            self._closed.set()

    def wait(self, timeout=None):
        """Wait for application-wide teardown rather than the retired source Host."""
        self._closed.wait(timeout)
        return self.snapshot()

    @contextmanager
    def signals(self):
        """Install process handlers once for the whole peer workflow chain."""
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Workflow application signals require the main thread")
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}

        def handle(signum, frame):
            """Pause on interrupt and drain all owned resources on termination."""
            self.request_shutdown("signal") if signum == signal.SIGTERM else self.pause()

        try:
            for sig in previous:
                signal.signal(sig, handle)
            yield
        finally:
            for sig, callback in previous.items():
                signal.signal(sig, callback)
