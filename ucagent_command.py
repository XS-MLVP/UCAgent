#!/usr/bin/env python3
"""
UCAgent command organizer: scenario entries over the existing Makefile targets.

This wrapper adds a task-oriented command surface on top of the repository
Makefile without changing any execution behavior. Every entry resolves to the
same make target (including the DUT workspace preparation prerequisite) that
developers run today, so output, environment, and exit status are identical:

    python3 ucagent_command.py master                             -> make as_master
    python3 ucagent_command.py master unitytest Adder              -> make test_with_master_Adder
    python3 ucagent_command.py master formal ALU754 --backend codex
                                                                  -> make formal_mcp_ALU754 ARGS="--backend codex"
    python3 ucagent_command.py tui unitytest Adder                 -> make test_Adder
    python3 ucagent_command.py mcp unitytest Adder                 -> make mcp_Adder
    python3 ucagent_command.py mcp unitytest Adder --backend codex -> make mcp_Adder ARGS="--backend codex"

Grammar:
    ucagent_command.py <entry> [<workflow>] [<dut>] [<message words>...] [ucagent flags | VAR=value]

- entry: master (workbench / registered task), tui (local interactive run),
  mcp (external-agent access).
- workflow: unitytest (default; aliases unity_test, unity-test, unity) or
  formal. The workflow decides which Makefile target family runs.
- dut: example DUT directory name under examples/ (formal: examples/Formal/).
- message: remaining free-text words; passed to the agent as the initial loop
  message (forwarded as ARGS "--loop --loop-msg <message>").
- ucagent flags: any option understood by ucagent; forwarded through ARGS.
- VAR=value: forwarded as make variables (for example SIM=vcs, CFG=...,
  BBV=true). ARGS itself is generated here, so passing ARGS= is rejected.
- --backend <name>: model backend. A backend task automatically selects the
  MCP master target, because non-langchain backends require MCP.
- --to <host[:port]>: Master address for master entries (make MASTER_IP,
  default 127.0.0.1, same as the Makefile).

The underlying `ucagent` command, `python3 ucagent.py`, and every make target
keep working unchanged; this file only reorganizes how they are invoked.
"""

import os
import re
import shlex
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

# Uppercase NAME= tokens are forwarded as make variables (SIM=vcs, BBV=true).
MAKE_VARIABLE_RE = re.compile(r"^[A-Z][A-Z0-9_]*=")

# Per-workflow make target templates. "master_loop" is the loop-mode target a
# master entry uses without --backend; None falls back to "master_backend"
# (formal has no separate loop/master target).
WORKFLOWS = {
    "unitytest": {
        "aliases": ("unitytest", "unity_test", "unity-test", "unity"),
        "examples_dir": "examples",
        "targets": {
            "tui": "test_%s",
            "mcp": "mcp_%s",
            "master_loop": "test_with_master_%s",
            "master_backend": "mcp_with_master_%s",
        },
    },
    "formal": {
        "aliases": ("formal",),
        "examples_dir": "examples/Formal",
        "targets": {
            "tui": "formal_%s",
            "mcp": "formal_mcp_%s",
            "master_loop": None,
            "master_backend": "formal_mcp_%s",
        },
    },
}

ENTRIES = ("master", "tui", "mcp")

TOP_HELP = """\
UCAgent command organizer: scenario entries over the existing Makefile targets.

Usage:
  python3 ucagent_command.py <entry> [<workflow>] [<dut>] [<message>...] [flags | VAR=value]

Entries:
  master            Start the local Master workbench (make as_master), or run a
                    task locally and register it with a running Master.
  tui               Run local interactive verification (TUI, automatic loop).
  mcp               Start MCP access for an external agent; --backend codex
                    launches the external executor automatically.

Workflows:
  unitytest         UnityChip/toffee verification (default; aliases: unity_test,
                    unity-test, unity) -> make test_% / mcp_% / ..._with_master_%
  formal            Formal (SVA) verification -> make formal_% / formal_mcp_%

Examples:
  python3 ucagent_command.py master
  python3 ucagent_command.py master unitytest Adder "fix the carry bug"
  python3 ucagent_command.py master formal ALU754 --backend codex
  python3 ucagent_command.py tui unitytest Adder
  python3 ucagent_command.py mcp unitytest Adder --backend codex
  python3 ucagent_command.py tui Adder SIM=vcs

Notes:
  <message> is forwarded as ARGS "--loop --loop-msg <message>".
  Uppercase VAR=value tokens are forwarded to make (SIM, CFG, BBV, SRC, ...).
  Use --to host[:port] on master entries to override MASTER_IP (default
  127.0.0.1). The plain `ucagent` command and all make targets are unchanged.
"""

ENTRY_HELP = {
    "master": """\
Usage:
  python3 ucagent_command.py master [--to host[:port]] [flags | VAR=value]
  python3 ucagent_command.py master <workflow> <dut> [message...] [--backend name] [flags | VAR=value]

Starts the local Master workbench, or runs a task locally and registers it
with a running Master (start the workbench first, or point --to at one).
Equivalent make targets:
  master                                   -> make as_master
  master unitytest <DUT> [message]         -> make test_with_master_<DUT>
  master unitytest <DUT> --backend codex   -> make mcp_with_master_<DUT> ARGS="--backend codex"
  master formal <DUT>                      -> make formal_mcp_<DUT>
A --backend task always selects the MCP master target, because command-line
backends communicate through MCP. --to overrides MASTER_IP (default 127.0.0.1).
""",
    "tui": """\
Usage:
  python3 ucagent_command.py tui <workflow> <dut> [message...] [flags | VAR=value]

Runs local interactive verification in TUI mode with the automatic loop.
Equivalent make targets:
  tui unitytest <DUT> [message]            -> make test_<DUT>
  tui formal <DUT>                         -> make formal_<DUT>
""",
    "mcp": """\
Usage:
  python3 ucagent_command.py mcp <workflow> <dut> [message...] [--backend name] [flags | VAR=value]

Starts the MCP server (no file tools) so an external agent can connect, and
opens the local TUI console. With --backend the external executor itself is
launched and connects back through MCP.
Equivalent make targets:
  mcp unitytest <DUT>                      -> make mcp_<DUT>
  mcp unitytest <DUT> --backend codex      -> make mcp_<DUT> ARGS="--backend codex"
  mcp formal <DUT>                         -> make formal_mcp_<DUT>
""",
}


def fail(message: str) -> None:
    """Print a usage failure and exit with status 2."""
    print(f"ucagent_command: {message}", file=sys.stderr)
    sys.exit(2)


def print_help(entry: str = "") -> None:
    """Print the top-level entry menu or one entry's usage and make mapping."""
    print(ENTRY_HELP.get(entry, TOP_HELP))


def resolve_workflow(token: str):
    """Return the workflow name whose alias list contains token, else None."""
    for name, spec in WORKFLOWS.items():
        if token in spec["aliases"]:
            return name
    return None


def available_duts(examples_dir: str):
    """List example DUT directory names usable as <dut> for one workflow."""
    root = REPO_ROOT / examples_dir
    if not root.is_dir():
        return []
    return sorted(
        item.name
        for item in root.iterdir()
        if item.is_dir() and not item.name.startswith(("_", "output"))
    )


def main(argv) -> int:
    """Parse the entry grammar, resolve the make target, and exec make."""
    args = list(argv[1:])
    if not args:
        print_help()
        return 2
    if args[0] in ("-h", "--help"):
        print_help()
        return 0
    entry = args[0]
    if entry not in ENTRIES:
        fail(
            f"unknown entry '{entry}'; available: {', '.join(ENTRIES)} "
            "(see 'python3 ucagent_command.py --help')"
        )
    rest = args[1:]
    if "-h" in rest or "--help" in rest:
        print_help(entry)
        return 0

    workflow = None
    dut = None
    backend = None
    master_address = None
    make_vars = []
    extra_flags = []
    message_words = []

    index = 0
    while index < len(rest):
        token = rest[index]
        if token == "--backend":
            index += 1
            if index >= len(rest) or not rest[index]:
                fail("--backend requires a value, e.g. --backend codex")
            backend = rest[index]
        elif token.startswith("--backend="):
            backend = token.split("=", 1)[1]
        elif token in ("--to", "--master-ip"):
            index += 1
            if index >= len(rest) or not rest[index]:
                fail("--to requires a value, e.g. --to 192.168.1.10:8800")
            master_address = rest[index]
        elif token == "ARGS" or token.startswith("ARGS="):
            fail("ARGS is generated from the message and flags; pass ucagent flags directly")
        elif MAKE_VARIABLE_RE.match(token):
            make_vars.append(token)
        elif token.startswith("-"):
            extra_flags.append(token)
        elif workflow is None and resolve_workflow(token) is not None:
            workflow = resolve_workflow(token)
        elif dut is None:
            dut = token
        else:
            message_words.append(token)
        index += 1

    if entry == "master" and dut is None:
        if workflow is not None:
            fail("the bare master entry takes no workflow; use 'master <workflow> <dut>'")
        if message_words:
            fail("the bare master entry takes no task message; use 'master <workflow> <dut> [message]'")
        target = "as_master"
    else:
        if dut is None:
            fail(
                f"'{entry}' requires <dut> (and optionally <workflow> before it); "
                f"e.g. ucagent_command.py {entry} unitytest Adder"
            )
        workflow = workflow or "unitytest"
        spec = WORKFLOWS[workflow]
        if not (REPO_ROOT / spec["examples_dir"] / dut).is_dir():
            names = ", ".join(available_duts(spec["examples_dir"])) or "(none)"
            fail(f"example DUT '{dut}' not found under {spec['examples_dir']}/; available: {names}")
        targets = spec["targets"]
        if entry == "tui":
            target = targets["tui"] % dut
        elif entry == "mcp":
            target = targets["mcp"] % dut
        else:
            # A backend task needs MCP, so it always uses the MCP master target.
            template = targets["master_backend"] if backend else (targets["master_loop"] or targets["master_backend"])
            target = template % dut

    make_argv = ["make", target]
    make_argv.extend(make_vars)
    if master_address is not None:
        make_argv.append(f"MASTER_IP={master_address}")
    args_flags = list(extra_flags)
    if backend is not None:
        args_flags += ["--backend", backend]
    if message_words:
        args_flags += ["--loop", "--loop-msg", " ".join(message_words)]
    if args_flags:
        make_argv.append("ARGS=" + " ".join(shlex.quote(part) for part in args_flags))

    make_path = shutil.which("make")
    if make_path is None:
        fail("make is required but was not found in PATH")

    print(">> " + " ".join(shlex.quote(part) for part in make_argv[1:]))
    os.chdir(REPO_ROOT)
    os.execv(make_path, make_argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
