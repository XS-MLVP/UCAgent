"""Direct deterministic project commands; no LLM or Skill is required."""

import argparse
import json
from pathlib import Path

from .audit import audit_project, summarize
from .paths import local_path, write_json
from .project import inspect_inputs, scaffold
from .runner import run_tests
from .stage_audit import RESTORED_PHASES


def main(argv=None):
    """Execute the same implementations exposed through UCAgent tools."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inspect", "scaffold", "audit", "run", "summary"])
    parser.add_argument("workspace", type=Path)
    parser.add_argument("dut")
    parser.add_argument("--project", default="ut_project")
    parser.add_argument("--mode", choices=["auto", "provided", "derive"], default="auto")
    parser.add_argument("--document", action="append")
    parser.add_argument("--rtl-dir", action="append")
    parser.add_argument("--native-package")
    parser.add_argument("--phase", default="tests", choices=["inputs", "design", "plan", "environment", "tests", "triage", "final", *sorted(RESTORED_PHASES)])
    parser.add_argument("--target", action="append")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args(argv)
    try:
        if args.action == "inspect":
            result = inspect_inputs(args.workspace, args.dut, args.project, args.document, args.rtl_dir, args.mode)
            write_json(local_path(args.workspace, (Path(args.project) / "results/input_inventory.json").as_posix()), result)
        elif args.action == "scaffold":
            result = scaffold(args.workspace, args.dut, args.project, args.native_package)
        elif args.action == "audit":
            result = audit_project(args.workspace, args.dut, args.project, args.phase)
        elif args.action == "run":
            result = run_tests(args.workspace, args.dut, args.project, args.target, workers=args.workers, timeout=args.timeout)
        else:
            result = summarize(args.workspace, args.dut, args.project)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f"{error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
