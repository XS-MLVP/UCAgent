"""Event handlers for UCAgent TUI."""

from __future__ import annotations

import time
import traceback
from typing import TYPE_CHECKING

from textual.worker import Worker, WorkerCancelled, WorkerState

from .widgets import ConsoleWidget

if TYPE_CHECKING:
    from .app import VerifyApp


class KeyHandler:
    """Handles key bindings and command processing for VerifyApp."""

    def __init__(self, app: "VerifyApp") -> None:
        self.app = app
        self.last_cmd: str | None = None
        self._active_worker: Worker | None = None

    def is_exit_cmd(self, cmd: str) -> bool:
        """Check if command is an exit command."""
        return cmd.lower() in ("q", "exit", "quit")

    def cancel_active_worker(self) -> bool:
        """Cancel the worker running the current command.

        Returns:
            True if a cancellation was requested
        """
        worker = self._active_worker
        if worker is None:
            return False
        if worker.state in (WorkerState.PENDING, WorkerState.RUNNING):
            worker.cancel()
            return True
        return False

    def has_active_worker(self) -> bool:
        """Return True if a command worker is currently running."""
        worker = self._active_worker
        if worker is None:
            return False
        return worker.state in (WorkerState.PENDING, WorkerState.RUNNING)

    async def process_command(self, cmd: str, daemon: bool = False) -> None:
        """Process a command.

        Args:
            cmd: Command string to execute
            daemon: If True, run as daemon command
        """
        if not cmd:
            # Repeat last command if empty
            if self.last_cmd:
                cmd = self.last_cmd
            else:
                self.app.update_task_panel()
                return

        self.last_cmd = cmd

        # Add to history
        self._add_to_history(cmd)

        # Check for exit
        if self.is_exit_cmd(cmd):
            self.app.action_quit()
            return

        # Check for clear
        if cmd == "clear":
            console = self.app.query_one("#console", ConsoleWidget)
            console.clear_output()
            return

        # Execute command
        if daemon:
            await self._execute_daemon_command(cmd)
        else:
            await self._execute_command(cmd)

    async def _execute_command(self, cmd: str) -> None:
        """Execute a command in a worker thread."""
        console = self.app.query_one("#console", ConsoleWidget)
        console.set_busy(True)

        def run_command() -> None:
            try:
                self.app.vpdb.onecmd(cmd)
            except Exception as e:
                error_msg = f"\033[33mCommand Error: {e}\n{traceback.format_exc()}\033[0m\n"
                self.app.call_from_thread(console.append_output, error_msg)

        worker = self.app.run_worker(run_command, thread=True, exclusive=True, group="cmd-exec")
        self._active_worker = worker
        self.app.set_active_command(cmd)

        cancelled = False
        try:
            # Wait for completion
            await worker.wait()
        except WorkerCancelled:
            cancelled = True
        finally:
            self.app.flush_console_output()
            console.set_busy(False)
            self.app.clear_active_command()
            self._active_worker = None

        if cancelled:
            return

        self.app.update_task_panel()

    async def _execute_daemon_command(self, cmd: str) -> None:
        """Execute a command as a daemon (background)."""
        key = time.time()
        self.app.daemon_cmds[key] = cmd

        def run_daemon() -> None:
            try:
                self.app.vpdb.onecmd(cmd)
            except Exception as e:
                error_msg = f"\033[33mDaemon Error: {e}\n{traceback.format_exc()}\033[0m\n"
                console = self.app.query_one("#console", ConsoleWidget)
                self.app.call_from_thread(console.append_output, error_msg)
            finally:
                self.app.call_from_thread(self.app.flush_console_output)
                if key in self.app.daemon_cmds:
                    del self.app.daemon_cmds[key]
                complete_msg = f"\033[33mDaemon command completed: {cmd}\033[0m\n"
                console = self.app.query_one("#console", ConsoleWidget)
                self.app.call_from_thread(console.append_output, complete_msg)

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
                self.app.vpdb,
                f"complete_{cmd}",
                self.app.vpdb.completedefault
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
