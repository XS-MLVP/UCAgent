"""Event handlers for UCAgent TUI."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time
import traceback
from typing import TYPE_CHECKING

from textual.worker import Worker, WorkerState

from .widgets import ConsoleWidget, ConsoleInput, TaskPanel

if TYPE_CHECKING:
    from .app import VerifyApp


@dataclass
class DetachedCommand:
    command: str
    started_at: float
    is_daemon: bool
    thread: threading.Thread | None = None
    thread_id: int | None = None
    cancel_requested: bool = False

    def is_alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive()


@dataclass
class ForegroundCommandHandle:
    kind: str
    token: Worker | float


class KeyHandler:
    def __init__(self, app: "VerifyApp") -> None:
        self.app = app
        self.last_cmd: str | None = None
        self._active_workers: list[Worker] = []
        self._worker_commands: dict[Worker, str] = {}
        self._worker_threads: dict[Worker, int] = {}
        self._foreground_handles: list[ForegroundCommandHandle] = []
        self._detached_lock = threading.Lock()
        self._detached_commands: dict[float, DetachedCommand] = {}

    def is_exit_cmd(self, cmd: str) -> bool:
        return cmd.lower() in ("q", "exit", "quit")

    def is_detachable_cmd(self, cmd: str) -> bool:
        return cmd.split(maxsplit=1)[0].lower() == "loop"

    def cancel_all_workers(self, *, include_detached: bool = True) -> bool:
        cancelled_any = False
        self._cleanup_finished_state()
        for worker in list(self._active_workers):
            if worker.state in (WorkerState.PENDING, WorkerState.RUNNING):
                self._cancel_worker(worker)
                cancelled_any = True
        self._active_workers.clear()
        self._worker_commands.clear()

        if include_detached:
            for key in self._list_detached_keys():
                if self._cancel_detached_command(key):
                    cancelled_any = True

        self._cleanup_finished_state()
        self._update_busy_state()
        return cancelled_any

    def cancel_last_worker(self) -> bool:
        """Cancel the most recently started foreground command (LIFO)."""
        self._cleanup_finished_state()
        if not self._foreground_handles:
            return False

        handle = self._foreground_handles[-1]
        if handle.kind == "worker":
            worker = handle.token
            if isinstance(worker, Worker) and worker.state in (
                    WorkerState.PENDING, WorkerState.RUNNING
            ):
                self._cancel_worker(worker)
                if worker in self._active_workers:
                    self._active_workers.remove(worker)
                self._worker_commands.pop(worker, None)
                self._cleanup_finished_state()
                self._update_busy_state()
                return True
            return False

        cancelled = self._cancel_detached_command(handle.token)
        self._cleanup_finished_state()
        self._update_busy_state()
        return cancelled

    def get_running_commands(self) -> list[str]:
        """Get list of currently running foreground command texts in execution order."""
        self._cleanup_finished_state()
        commands: list[str] = []
        for handle in self._foreground_handles:
            if handle.kind == "worker":
                worker = handle.token
                if isinstance(worker, Worker) and worker in self._worker_commands:
                    commands.append(self._worker_commands[worker])
                continue

            command = self._get_detached_command(handle.token)
            if command is not None:
                commands.append(command)
        self._update_busy_state()
        return commands

    def has_active_worker(self) -> bool:
        self._cleanup_finished_state()
        return len(self._foreground_handles) > 0

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

        if self.is_detachable_cmd(cmd):
            self._execute_detached_command(cmd, is_daemon=False)
            return

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
        self._foreground_handles.append(
            ForegroundCommandHandle(kind="worker", token=worker)
        )
        self._update_busy_state()

    def _execute_daemon_command(self, cmd: str) -> None:
        self._execute_detached_command(cmd, is_daemon=True)

    def _execute_detached_command(self, cmd: str, *, is_daemon: bool) -> None:
        key = time.time()
        task = DetachedCommand(command=cmd, started_at=key, is_daemon=is_daemon)

        def run_detached() -> None:
            thread_id = threading.current_thread().ident
            with self._detached_lock:
                current = self._detached_commands.get(key)
                if current is None:
                    return
                current.thread_id = thread_id
                should_break = current.cancel_requested

            if should_break and thread_id is not None:
                self.app.vpdb.agent.set_break_thread(thread_id)

            try:
                self.app.vpdb.onecmd(cmd)
            except Exception as e:
                prefix = "Daemon Error" if is_daemon else "Command Error"
                print(
                    f"\033[33m{prefix}: {e}\n{traceback.format_exc()}\033[0m",
                    end="",
                )
            finally:
                if thread_id is not None:
                    self.app.vpdb.agent.clear_break_thread(thread_id)
                with self._detached_lock:
                    finished = self._detached_commands.pop(key, None)
                    self.app.daemon_cmds.pop(key, None)
                if (
                        is_daemon
                        and finished is not None
                        and not finished.cancel_requested
                        and not self.app.is_shutting_down
                ):
                    print(
                        f"\033[33mDaemon command completed: {cmd}\033[0m",
                        end="\n",
                    )

        thread = threading.Thread(
            target=run_detached,
            name=f"tui-detached-{int(key * 1000)}",
            daemon=True,
        )
        task.thread = thread
        with self._detached_lock:
            self._detached_commands[key] = task
            if is_daemon:
                self.app.daemon_cmds[key] = cmd
            else:
                self._foreground_handles.append(
                    ForegroundCommandHandle(kind="detached", token=key)
                )
        thread.start()
        self._update_busy_state()

    def _on_command_complete(self, worker: Worker) -> None:
        if worker in self._active_workers:
            self._active_workers.remove(worker)
        self._worker_commands.pop(worker, None)
        thread_id = self._worker_threads.pop(worker, None)
        if thread_id is not None:
            self.app.vpdb.agent.clear_break_thread(thread_id)
        self._cleanup_finished_state()
        if self.app.is_shutting_down:
            return
        self.app.flush_console_output()
        self._update_busy_state()
        console_input = self.app.query_one(ConsoleInput)
        console_input.update_running_commands()
        if not self.has_active_worker():
            task_panel = self.app.query_one("#task-panel", TaskPanel)
            task_panel.update_content()

    def _register_worker_thread(self, worker: Worker, thread_id: int) -> None:
        self._worker_threads[worker] = thread_id

    def _cancel_worker(self, worker: Worker) -> None:
        thread_id = self._worker_threads.get(worker)
        if thread_id is not None:
            self.app.vpdb.agent.set_break_thread(thread_id)
        worker.cancel()

    def _cancel_detached_command(self, key: float) -> bool:
        with self._detached_lock:
            task = self._detached_commands.get(key)
            if task is None or not task.is_alive():
                return False
            task.cancel_requested = True
            thread_id = task.thread_id

        if thread_id is not None:
            self.app.vpdb.agent.set_break_thread(thread_id)
        return True

    def _list_detached_keys(self) -> list[float]:
        with self._detached_lock:
            return list(self._detached_commands.keys())

    def _get_detached_command(self, key: float) -> str | None:
        with self._detached_lock:
            task = self._detached_commands.get(key)
            if task is None or not task.is_alive():
                return None
            return task.command

    def _cleanup_finished_workers(self) -> None:
        self._active_workers = [
            worker
            for worker in self._active_workers
            if worker.state in (WorkerState.PENDING, WorkerState.RUNNING)
        ]

    def _cleanup_finished_detached_commands(self) -> None:
        with self._detached_lock:
            finished_keys = [
                key
                for key, task in self._detached_commands.items()
                if not task.is_alive()
            ]
            for key in finished_keys:
                self._detached_commands.pop(key, None)
                self.app.daemon_cmds.pop(key, None)

    def _cleanup_foreground_handles(self) -> None:
        active_handles: list[ForegroundCommandHandle] = []
        for handle in self._foreground_handles:
            if handle.kind == "worker":
                worker = handle.token
                if isinstance(worker, Worker) and worker in self._active_workers:
                    active_handles.append(handle)
                continue

            key = handle.token
            if self._get_detached_command(key) is not None:
                active_handles.append(handle)
        self._foreground_handles = active_handles

    def _cleanup_finished_state(self) -> None:
        self._cleanup_finished_workers()
        self._cleanup_finished_detached_commands()
        self._cleanup_foreground_handles()

    def _update_busy_state(self) -> None:
        console = self.app.query_one("#console", ConsoleWidget)
        console.set_busy(self.has_active_worker())

    def _add_to_history(self, cmd: str) -> None:
        """Add command to history."""
        if cmd not in self.app.cmd_history or self.app.cmd_history[-1] != cmd:
            self.app.cmd_history.append(cmd)
            self.app.vpdb.record_cmd_history(cmd)
        self.app.cmd_history_index = len(self.app.cmd_history)

    def complete_command(self, text: str) -> list[str]:
        """Get command completions."""
        cmd, args, _ = self.app.vpdb.parseline(text)

        if " " in text:
            complete_func = getattr(
                self.app.vpdb, f"complete_{cmd}", self.app.vpdb.completedefault
            )
            arg = args
            if " " in args:
                arg = args.split()[-1]
            idx = text.find(arg)
            return complete_func(arg, text, idx, len(text))
        return self.app.vpdb.api_all_cmds(text)

    def get_history_item(self, offset: int) -> str | None:
        """Get command from history with offset."""
        new_index = self.app.cmd_history_index + offset
        if 0 <= new_index < len(self.app.cmd_history):
            self.app.cmd_history_index = new_index
            return self.app.cmd_history[new_index]
        if new_index >= len(self.app.cmd_history):
            self.app.cmd_history_index = len(self.app.cmd_history)
            return ""
        return None
