#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Public CLI entrypoint, launch orchestration, error presentation and exit codes."""

from ucagent.application.plan import LaunchRequest
import os
import sys
import traceback
from typing import List, Optional

from ucagent.interfaces.cli.actions import run_management_commands
from ucagent.interfaces.cli.arguments import get_args
from ucagent.interfaces.cli.options import parse_launch_options
from ucagent.application.workspace import WorkspaceArchiveError

os.environ['PYTHONPYCACHEPREFIX'] = os.path.join(os.path.expanduser('~'), ".ucagent/__pycache__")

def info(*k, **w):
    """Print CLI status independently of runtime logging."""
    print(*k, **w)


def _extract_web_console_capture_path(argv: Optional[List[str]] = None) -> str:
    """Read the hidden error-capture destination from the process arguments."""
    source_argv = list(sys.argv if argv is None else argv)
    raw_args = source_argv[1:]
    for i, arg in enumerate(raw_args):
        if arg == "--web-console-capture-path":
            if i + 1 < len(raw_args):
                return raw_args[i + 1]
            return ""
        if arg.startswith("--web-console-capture-path="):
            return arg.split("=", 1)[1]
    return ""


def run() -> None:
    """Main entry point for UCAgent CLI."""
    args = get_args()

    if run_management_commands(args):
        return

    if args.web_console is not None and \
       args.web_console_session_host is None and \
       args.web_console_session_port is None:
        from ucagent.interfaces.server.api_terminal import _serve_web_console
        try:
            return _serve_web_console(sys.argv)
        except Exception as e:
            info(f"Failed to start Web UI: {e}")
            sys.exit(1)

    from ucagent.application.launch import run_application
    return run_application(LaunchRequest(**parse_launch_options(args)))


def main() -> None:
    """Main entry point with exception handling."""
    try:
        run()
    except WorkspaceArchiveError as e:
        info(f"Workspace archive error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        info("\nUCAgent interrupted by user.")
        sys.exit(1)
    except Exception as e:
        info(f"UCAgent encountered an error: {e}")
        formatted = traceback.format_exc()
        info(formatted, end="")
        capture_path = _extract_web_console_capture_path().strip()
        if capture_path:
            try:
                os.makedirs(os.path.dirname(os.path.abspath(capture_path)), exist_ok=True)
                with open(capture_path, "a", encoding="utf-8", errors="replace") as fh:
                    fh.write(f"UCAgent encountered an error: {e}\n")
                    fh.write(formatted)
                    if not formatted.endswith("\n"):
                        fh.write("\n")
            except OSError:
                pass
        sys.exit(1)
    info("UCAgent is exited.")


if __name__ == "__main__":
    main()
