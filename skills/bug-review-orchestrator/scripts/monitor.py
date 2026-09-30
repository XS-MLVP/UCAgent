#!/usr/bin/env python3
"""Print bounded status snapshots for every Bug Review module run."""
from __future__ import annotations
import argparse, json, subprocess
from pathlib import Path

def main() -> int:
    """Report tmux session state and workflow stage state."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--session", default="bug-review")
    parser.add_argument("--python", default="python3")
    parser.add_argument("--plugin-src", type=Path, default=Path("plugins/bug_review/src"))
    args = parser.parse_args()
    session_ok = subprocess.run(["tmux", "has-session", "-t", args.session], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    rows = []
    for run in sorted(args.output_root.glob("workspace_*/runs/run-*")):
        env = {**__import__("os").environ, "PYTHONPATH": f"{args.plugin_src.resolve()}:{Path.cwd()}"}
        status = subprocess.run([args.python, "-m", "bug_review.workflow", "status", "--workspace", str(run)], text=True, capture_output=True, env=env)
        rows.append({"workspace": run.parent.parent.name, "run": run.name, "status": status.stdout.strip()[-2000:], "status_rc": status.returncode})
    print(json.dumps({"session": args.session, "session_exists": session_ok, "runs": rows}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
