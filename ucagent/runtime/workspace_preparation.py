"""Cancellable preparation jobs with bounded command execution and isolated logs."""
from pathlib import Path
import os
import re
import signal
import subprocess
import threading
import time

from ucagent.core.workspace.preparation import WorkspacePreparation, PreparationOptions
from ucagent.core.multi_agent.global_agent.result import sha256_file, _artifact_path


class PreparationCancelled(RuntimeError):
    """Signal cancellation without treating it as a workflow failure."""


class PreparationJob:
    """Own one workflow preparation attempt and all of its subprocesses."""

    def __init__(self, workflow, source, workspace, dut_name, options, *, timeout=900,
                 progress=None, inputs=(), cache=None):
        """Build an unstarted job; callbacks must honor the supplied cancellation check."""
        if not isinstance(dut_name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$-]*", dut_name):
            raise ValueError("dut_name must be a module name, not a path")
        self.workflow = workflow
        self.cancelled = threading.Event()
        self.done = threading.Event()
        self.error = None
        self.timeout = timeout
        self.deadline = None
        self.inputs = inputs
        self.log_path = Path(workspace).parent / "preparation.log"
        schema = getattr(workflow, "preparation_schema", None) or PreparationOptions
        self.context = WorkspacePreparation(Path(source).resolve(), Path(workspace).resolve(), dut_name,
            schema.model_validate(options), progress or (lambda message: None), self.check, self.run_command, Path(cache).resolve() if cache else None)
        self.thread = threading.Thread(target=self.execute, name="ucagent-prepare", daemon=True)

    def check(self):
        """Stop cooperative copying and commands on cancellation or the overall deadline."""
        if self.cancelled.is_set():
            raise PreparationCancelled("Preparation cancelled by the operator")
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise TimeoutError(f"Workspace preparation exceeded {self.timeout}s; inspect preparation.log and retry after correcting the environment.")

    def run_command(self, argv, *, cwd=None):
        """Run argv without a shell; terminate and reap its process group on cancellation."""
        self.check()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("ab") as log:
            process = subprocess.Popen([str(arg) for arg in argv], cwd=cwd or self.context.workspace,
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            try:
                while process.poll() is None:
                    self.cancelled.wait(.1)
                    self.check()
                self.check()
                if process.returncode:
                    raise RuntimeError(f"Workspace preparation command failed (exit {process.returncode}); inspect {self.log_path} and repair the task environment before retrying.")
            finally:
                # A command can exit while descendants still run; always reap its group.
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()

    def execute(self):
        """Prepare task assets and accepted inputs; publish completion only after all checks."""
        self.deadline = time.monotonic() + self.timeout
        ctx = self.context
        try:
            self.check()
            ctx.workspace.mkdir(parents=True, exist_ok=False)
            if ctx.workspace.is_relative_to(ctx.source):
                relative = ctx.workspace.relative_to(ctx.source)
                if ".ucagent" not in relative.parts:
                    raise ValueError("Preparation workspace must be outside its source tree")
            hook = getattr(self.workflow, "prepare_workspace", None)
            ctx.progress("Preparing workflow workspace")
            if hook:
                hook(ctx)
            else:
                ctx.copy(ctx.source, ctx.workspace)
            for target, path, receipt in self.inputs:
                destination = _artifact_path(ctx.workspace, target)
                source_ctx = WorkspacePreparation(path.parent, ctx.workspace, ctx.dut_name, ctx.options,
                    ctx.progress, ctx.check_cancelled, ctx.run_command)
                source_ctx.copy(path, destination)
                if sha256_file(destination) != receipt["sha256"]:
                    raise ValueError("Accepted input changed during preparation")
                destination.chmod(0o444)
            self.check()
            ctx.progress("Workspace ready")
        except Exception as error:
            self.error = error
        finally:
            self.done.set()
