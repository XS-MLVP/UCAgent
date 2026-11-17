"""Deadline-bound subprocess execution and cancellation for PPA backends."""

from __future__ import annotations

from pathlib import Path
import os
import signal
import subprocess
import threading
import time


class ProcessRunner:
    """Own active process groups for one analysis tool instance."""

    def __init__(self) -> None:
        """Initialize the thread-safe process registry."""

        self._active_processes = set()
        self._process_lock = threading.Lock()

    def cb_force_exit(self) -> None:
        """Terminate every currently active process group on cancellation or timeout."""

        with self._process_lock:
            processes = list(self._active_processes)
        for process in processes:
            if process.poll() is not None:
                continue
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:  # pragma: no cover - exercised only on Windows
                    process.kill()
            except ProcessLookupError:
                continue

    def _run_process(
        self,
        command: list[str],
        cwd: Path,
        deadline: float,
    ) -> subprocess.CompletedProcess[str]:
        """Run one external tool without a shell under the shared deadline."""

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("PPA analysis deadline expired")
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=(os.name == "posix"),
        )
        with self._process_lock:
            self._active_processes.add(process)
        try:
            stdout, stderr = process.communicate(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:  # pragma: no cover - exercised only on Windows
                process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:  # pragma: no cover - exercised only on Windows
                    process.kill()
                stdout, stderr = process.communicate()
            raise TimeoutError(
                f"command exceeded the remaining PPA timeout: {command[0]}"
            ) from exc
        finally:
            with self._process_lock:
                self._active_processes.discard(process)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
