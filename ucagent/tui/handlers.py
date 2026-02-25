"""Event handlers for UCAgent TUI."""

from __future__ import annotations

import threading
import time
import traceback
from typing import TYPE_CHECKING

from textual.worker import Worker, WorkerState

from .widgets import ConsoleWidget, ConsoleInput, TaskPanel

if TYPE_CHECKING:
    from .app import VerifyApp


class KeyHandler:
    def __init__(self, app: "VerifyApp") -> None:
        self.app = app
        self.last_cmd: str | None = None
        self._active_workers: list[Worker] = []
        self._worker_commands: dict[Worker, str] = {}
        self._worker_threads: dict[Worker, int] = {}

    def is_exit_cmd(self, cmd: str) -> bool:
        return cmd.lower() in ("q", "exit", "quit")

    def cancel_all_workers(self) -> bool:
        cancelled_any = False
        for worker in self._active_workers:
            if worker.state in (WorkerState.PENDING, WorkerState.RUNNING):
                worker.cancel()
                cancelled_any = True
        self._active_workers.clear()
        self._update_busy_state()
        return cancelled_any

    def cancel_last_worker(self) -> bool:
        """Cancel the most recently started worker (LIFO).

        Returns:
            True if a worker was cancelled, False otherwise
        """
        if not self._active_workers:
            return False

        # Get last worker (most recent)
        worker = self._active_workers[-1]

        # Check if still active
        if worker.state in (WorkerState.PENDING, WorkerState.RUNNING):
            worker.cancel()
            self._active_workers.remove(worker)
            self._worker_commands.pop(worker, None)
            self._update_busy_state()
            return True

        return False

    def get_running_commands(self) -> list[str]:
        """Get list of currently running command texts in execution order.

        Returns:
            List of command strings for active workers
        """
        self._cleanup_finished_workers()
        return [
            self._worker_commands.get(w, "")
            for w in self._active_workers
            if w in self._worker_commands
        ]

    def _register_worker_thread(self, worker: Worker, thread_id: int) -> None:
        self._worker_threads[worker] = thread_id

    def get_last_worker_thread_id(self) -> int | None:
        if not self._active_workers:
            return None
        last_worker = self._active_workers[-1]
        return self._worker_threads.get(last_worker)

    def has_active_worker(self) -> bool:
        self._cleanup_finished_workers()
        return len(self._active_workers) > 0

    def _cleanup_finished_workers(self) -> None:
        self._active_workers = [
            w
            for w in self._active_workers
            if w.state in (WorkerState.PENDING, WorkerState.RUNNING)
        ]

    def process_command(self, cmd: str, daemon: bool = False) -> None:
        if not cmd:
            if self.last_cmd:
                cmd = self.last_cmd
            else:
                task_panel = self.app.query_one("#task-panel", TaskPanel)
                task_panel.update_content()
                return

        self.last_cmd = cmd
        self._add_to_history(cmd)

        if self.is_exit_cmd(cmd):
            self.app.action_quit()
            return

        if cmd == "clear":
            console = self.app.query_one("#console", ConsoleWidget)
            console.clear_output()
            return

        if daemon:
            self._execute_daemon_command(cmd)
        else:
            self._execute_command(cmd)

    def _execute_command(self, cmd: str) -> None:
        console = self.app.query_one("#console", ConsoleWidget)
        console.echo_command(cmd)

        worker_holder: list[Worker] = []
        worker_ready = threading.Event()

        def run_command() -> None:
            worker_ready.wait()
            thread_id = threading.current_thread().ident
            self.app.call_from_thread(
                self._register_worker_thread, worker_holder[0], thread_id
            )
            try:
                self.app.vpdb.onecmd(cmd)
            except Exception as e:
                error_msg = (
                    f"\033[33mCommand Error: {e}\n{traceback.format_exc()}\033[0m\n"
                )
                console.queue_output(error_msg)
            finally:
                if worker_holder:
                    self.app.call_from_thread(
                        self._on_command_complete, worker_holder[0]
                    )

        worker = self.app.run_worker(run_command, thread=True, group="cmd-exec")
        worker_holder.append(worker)
        worker_ready.set()
        self._active_workers.append(worker)
        self._worker_commands[worker] = cmd
        self._update_busy_state()

    def _on_command_complete(self, worker: Worker) -> None:
        if worker in self._active_workers:
            self._active_workers.remove(worker)
        self._worker_commands.pop(worker, None)
        thread_id = self._worker_threads.pop(worker, None)
        if thread_id is not None:
            self.app.vpdb.agent.clear_break_thread(thread_id)
        self.app.flush_console_output()
        self._update_busy_state()
        console_input = self.app.query_one(ConsoleInput)
        console_input.update_running_commands()
        if not self.has_active_worker():
            task_panel = self.app.query_one("#task-panel", TaskPanel)
            task_panel.update_content()

    def _update_busy_state(self) -> None:
        console = self.app.query_one("#console", ConsoleWidget)
        console.set_busy(self.has_active_worker())

    def _execute_daemon_command(self, cmd: str) -> None:
        key = time.time()
        self.app.daemon_cmds[key] = cmd

        def run_daemon() -> None:
            console = self.app.query_one("#console", ConsoleWidget)
            try:
                self.app.vpdb.onecmd(cmd)
            except Exception as e:
                error_msg = (
                    f"\033[33mDaemon Error: {e}\n{traceback.format_exc()}\033[0m\n"
                )
                console.queue_output(error_msg)
            finally:
                self.app.call_from_thread(self.app.flush_console_output)
                if key in self.app.daemon_cmds:
                    del self.app.daemon_cmds[key]
                complete_msg = f"\033[33mDaemon command completed: {cmd}\033[0m\n"
                console.queue_output(complete_msg)

        self.app.run_worker(run_daemon, thread=True, group="cmd-daemon")

    def _add_to_history(self, cmd: str) -> None:
        """Add command to history."""
        if cmd not in self.app.cmd_history or self.app.cmd_history[-1] != cmd:
            self.app.cmd_history.append(cmd)
        self.app.cmd_history_index = len(self.app.cmd_history)

    def complete_command(self, text: str) -> list[str]:
        """Get command completions.

        Args:
            text: Current input text

        Returns:
            List of completion suggestions
        """
        cmd, args, _ = self.app.vpdb.parseline(text)

        if " " in text:
            # Complete argument
            complete_func = getattr(
                self.app.vpdb, f"complete_{cmd}", self.app.vpdb.completedefault
            )
            arg = args
            if " " in args:
                arg = args.split()[-1]
            idx = text.find(arg)
            return complete_func(arg, text, idx, len(text))
        else:
            # Complete command
            return self.app.vpdb.api_all_cmds(text)

    def get_history_item(self, offset: int) -> str | None:
        """Get command from history with offset.

        Args:
            offset: Offset from current position (negative = older, positive = newer)

        Returns:
            Command string or None
        """
        new_index = self.app.cmd_history_index + offset
        if 0 <= new_index < len(self.app.cmd_history):
            self.app.cmd_history_index = new_index
            return self.app.cmd_history[new_index]
        elif new_index >= len(self.app.cmd_history):
            self.app.cmd_history_index = len(self.app.cmd_history)
            return ""
        return None
