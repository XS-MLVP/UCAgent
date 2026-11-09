"""Runtime-owned initialization that survives terminal view replacement."""

import threading

from ucagent.runtime.control.controller import ControlError
from ucagent.runtime.operations import TERMINAL_STATES, OperationCancelled


class StartupCommands:
    """Run ordered initialization independently of UI timers or input polling."""

    def __init__(self, host):
        """Create an inert readiness gate; execution belongs to the operation executor."""
        self.host = host
        self._ready = threading.Event()
        self.operation_id = None
        self.model_started = False
        self._model_id = None

    @property
    def active(self):
        """Report whether startup still has commands to submit or finish."""
        return self.operation_id is not None and self.host.operations.get(self.operation_id)["state"] not in TERMINAL_STATES

    def release(self):
        """Signal that a display is ready; no startup work runs on the calling UI thread."""
        self._ready.set()

    def start(self, commands, session, *, wait_for_display=False, interactive=False, default_model=False):
        """Submit initialization once; interactive model loops may coexist with later queries."""
        if self.operation_id is not None:
            raise ControlError("already_started", "Initialization has already been submitted.")
        if not wait_for_display:
            self.release()
        commands = tuple(commands)

        def initialize(context):
            """Execute startup with bounded cancellation waits and ordered model admission."""
            while not self._ready.is_set():
                context.wait(0.05)
            try:
                for line in commands:
                    context.checkpoint()
                    if self.host.snapshot()["instance"] != "ready":
                        break
                    stripped = line.strip()
                    if not stripped:
                        continue
                    spec = self.host.registry.resolve(stripped.split(maxsplit=1)[0])
                    # An interactive loop must not prevent following status/config queries.
                    # A subsequent model command must still wait for the reserved model slot.
                    if self._model_id is not None and spec.model:
                        previous = self.wait_for_operation(context, self._model_id)
                        if previous["state"] != "succeeded":
                            raise ControlError("startup_failed", "Previous model operation did not succeed.")
                    result = session.execute_line(line)
                    self.host.output.emit(f"> {line}\n{session.format_result(result)}\n")
                    if result is None:
                        continue
                    data = result.data
                    if isinstance(data, dict) and "id" in data and "state" in data:
                        if data["model"]:
                            self.model_started = True
                            self._model_id = data["id"]
                        if not (interactive and data["model"]):
                            finished = self.wait_for_operation(context, data["id"], wait_models=not interactive)
                            if finished["state"] != "succeeded":
                                error = finished.get("error") or {}
                                raise ControlError(error.get("code", "startup_failed"),
                                                   error.get("message", "Initialization command was cancelled."))
                            data = finished["result"]
                        else:
                            continue
                    if isinstance(data, dict) and data.get("ok") is False:
                        raise ControlError("startup_failed", data.get("message", "Initialization command failed."))
                if default_model and not self.model_started and self.host.snapshot()["instance"] == "ready":
                    result = session.execute_line("continue")
                    self.model_started = True
                    self.host.output.emit(session.format_result(result) + "\n")
                return {"model_started": self.model_started}
            except OperationCancelled:
                raise
            except Exception as error:
                code = error.code if isinstance(error, ControlError) else "execution_failed"
                self.host.output.emit(f"Initialization failed: {code}: {error}\n")
                if not interactive:
                    self.host.request_shutdown("startup_command_failed", exit_code=1)
                raise

        # Publish while holding the executor lock, before the supervisor can observe completion.
        with self.host.operations._lock:
            record = self.host.operations.submit("initial_commands", initialize)
            self.operation_id = record["id"]
        return record

    def wait_for_operation(self, context, operation_id, *, wait_models=True):
        """Wait for the action and its continuation children while remaining cancellable."""
        row = self.host.operations.wait_tree(context, operation_id, wait_models=wait_models)
        descendants = {operation_id}
        # Records are insertion-ordered, so parents always precede their children.
        for child in self.host.operations.list():
            if child["parent_id"] in descendants:
                descendants.add(child["id"])
                if child["model"]:
                    self.model_started = True
                    self._model_id = child["id"]
        return row
