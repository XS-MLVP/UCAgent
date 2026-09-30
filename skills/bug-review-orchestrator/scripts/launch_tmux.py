#!/usr/bin/env python3
"""Prepare and launch one or more bug-review runs in isolated tmux panes."""
from __future__ import annotations
import argparse, json, os, subprocess
from pathlib import Path

def main() -> int:
    """Create runs with the plugin workflow and return their paths."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--dut", action="append", required=True)
    parser.add_argument("--python", default="python3")
    parser.add_argument("--session", default="bug-review")
    parser.add_argument("--backend", default="codex")
    parser.add_argument("--mcp-port", type=int, default=-1, help="MCP port; -1 asks UCAgent to select an available port")
    parser.add_argument("--interactive", action="store_true", help="Keep UCAgent human/TUI flags for manual runs")
    parser.add_argument("--ucagent-root", type=Path, default=Path.cwd())
    parser.add_argument("--plugin-root", type=Path, default=Path("plugins/bug_review"))
    args = parser.parse_args()
    input_root, output_root = args.input_root.resolve(), args.output_root.resolve()
    plugin_root, ucagent_root = args.plugin_root.resolve(), args.ucagent_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["tmux", "kill-session", "-t", args.session], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    session = None
    launched = []
    for dut in args.dut:
        workspace = output_root / f"workspace_{dut}"
        cmd = [args.python, "-m", "bug_review.workflow", "run-analysis", "--input-root", str(input_root), "--output-root", str(output_root), "--run", f"workspace_{dut}={input_root / f'workspace_{dut}'}", "--python", args.python, "--ucagent-root", str(ucagent_root), "--", "--backend", args.backend, "--mcp-server", "--mcp-server-port", str(args.mcp_port)]
        if args.interactive:
            cmd.extend(["--human", "--tui"])
        log = output_root / f"tmux-{dut}.log"
        shell = f"cd {ucagent_root} && PYTHONPATH={plugin_root / 'src'}:{ucagent_root} {' '.join(subprocess.list2cmdline([x]) for x in cmd)} > {log} 2>&1"
        if session is None:
            subprocess.run(["tmux", "new-session", "-d", "-s", args.session, "bash", "-lc", shell], check=True)
            session = args.session
        else:
            subprocess.run(["tmux", "new-window", "-t", args.session, "-n", dut, "bash", "-lc", shell], check=True)
        launched.append({"dut": dut, "log": str(log), "output_root": str(workspace)})
    print(json.dumps({"session": session, "runs": launched}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
