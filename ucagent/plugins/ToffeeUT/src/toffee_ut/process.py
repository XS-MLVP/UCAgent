"""Bounded process-group execution shared by build and test automation."""

import os
import signal
import subprocess
import time


def execute(command, cwd, stdout, stderr, timeout, cancelled, progress, env=None):
    """Run argv without a shell and terminate all children on timeout or cancellation."""
    interrupted = ""
    with stdout.open("w") as out, stderr.open("w") as err:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True)
        started = last_notice = time.monotonic()
        try:
            while process.poll() is None:
                if cancelled():
                    interrupted = "cancelled"
                    break
                if time.monotonic() - started > timeout:
                    interrupted = "timeout"
                    break
                if time.monotonic() - last_notice >= 5:
                    progress("Operation still executing; output is retained in project results.")
                    last_notice = time.monotonic()
                time.sleep(0.1)
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            process.wait()
            # A promptly exiting parent may leave children that ignored SIGTERM.
            # The whole group belongs to this operation, even on a normal exit.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    return process.returncode, interrupted
