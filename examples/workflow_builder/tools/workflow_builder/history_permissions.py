#!/usr/bin/env python3
"""Keep UCAgent history snapshots owner-writable while a workflow is running."""

from __future__ import annotations

import argparse
import os
import signal
import stat
import threading
from pathlib import Path


def restore_owner_write(root: Path) -> int:
    """Restore owner write bits without following links outside the history tree."""
    if not root.is_dir():
        return 0
    changed = 0
    for current, directories, files in os.walk(root, followlinks=False):
        for name in [*directories, *files]:
            path = Path(current) / name
            try:
                if path.is_symlink():
                    continue
                mode = path.stat().st_mode
                if not mode & stat.S_IWUSR:
                    path.chmod(mode | stat.S_IWUSR)
                    changed += 1
            except FileNotFoundError:
                continue
    return changed


def watch(root: Path, interval: float) -> None:
    stop = threading.Event()

    def request_stop(_signum, _frame) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    while not stop.is_set():
        restore_owner_write(root)
        stop.wait(interval)
    restore_owner_write(root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=0.2)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")
    watch(args.path.resolve(), args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
