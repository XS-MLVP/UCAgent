# -*- coding: utf-8 -*-
"""Run formal verification and print parsed summary."""

import argparse
import os
import subprocess
import sys


def _bootstrap_formal_import() -> None:
    """Ensure repository root is on sys.path so examples.Formal can be imported."""
    marker = os.path.join("examples", "Formal", "scripts", "formal_tools.py")
    seen = set()
    candidates = []

    for base in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        cur = os.path.abspath(base)
        for _ in range(12):
            if cur in seen:
                break
            seen.add(cur)
            candidates.append(cur)
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent

    for root in candidates:
        if os.path.exists(os.path.join(root, marker)):
            if root not in sys.path:
                sys.path.insert(0, root)
            return

_bootstrap_formal_import()
from examples.Formal.scripts.formal_tools import normalize_output_dir, resolve_formal_paths
from ucagent.util.log import str_error, str_info
from examples.Formal.scripts.formal_adapter import get_adapter


def _resolve_paths(dut_name: str, output_dir: str) -> dict:
    adapter = get_adapter()
    return resolve_formal_paths(
        dut_name,
        output_dir,
        path_specs={
            "tcl_script": ("tests", "{dut_name}_formal.tcl"),
            "log_file": ("tests", adapter.log_filename()),
        },
    )


def _run_formal_verification(tcl_path: str, timeout: int) -> dict:
    adapter = get_adapter()
    exec_dir = os.path.dirname(tcl_path)
    log_path = os.path.join(exec_dir, adapter.log_filename())
    cmd = adapter.build_command(tcl_path, exec_dir)

    try:
        process = subprocess.run(
            cmd,
            cwd=exec_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return {"success": False, "error": f"Command '{cmd[0]}' not found", "stdout": "", "stderr": "", "log_path": log_path, "parsed_log": None}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Timeout after {timeout} seconds", "stdout": "", "stderr": "", "log_path": log_path, "parsed_log": None}

    if process.returncode != 0:
        return {
            "success": False,
            "error": f"Return code {process.returncode}",
            "stdout": process.stdout,
            "stderr": process.stderr,
            "log_path": log_path,
            "parsed_log": None,
        }

    if not os.path.exists(log_path):
        return {
            "success": False,
            "error": "Log not generated",
            "stdout": process.stdout,
            "stderr": process.stderr,
            "log_path": log_path,
            "parsed_log": None,
        }

    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        log_content = f.read()
    has_results = adapter.validate_log_has_results(log_content)
    parsed_log = adapter.parse_log(log_path) if has_results else None

    return {
        "success": has_results,
        "error": None if has_results else "No valid results in log",
        "stdout": process.stdout,
        "stderr": process.stderr,
        "log_path": log_path,
        "parsed_log": parsed_log,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run formal verification by DUT name")
    parser.add_argument("-dut_name", default=os.environ.get("DUT"), help="Top-level DUT module name")
    parser.add_argument("-timeout", type=int, default=300, help="Timeout in seconds")
    args = parser.parse_args()

    if not args.dut_name:
        print(str_error("Missing DUT name. Please provide -dut_name or set DUT environment variable."))
        return
    output_dir = os.environ.get("OUT")
    if not output_dir:
        print(str_error("Missing OUT environment variable."))
        return

    output_dir = normalize_output_dir(output_dir)

    paths = _resolve_paths(args.dut_name, output_dir)
    tcl_path = paths["tcl_script"]
    if not os.path.exists(tcl_path):
        result = str_error(
            f"TCL script does not exist: {tcl_path}\n"
            f"Please run GenerateFormalScript first to generate {args.dut_name}_formal.tcl"
        )
        print(result)
        return

    res = _run_formal_verification(tcl_path, args.timeout)
    if not res["success"]:
        if res["error"] and "not found" in res["error"]:
            result = str_error(f"❌ '{res['error']}', please ensure the tool is installed and in your PATH")
            print(result)
            return
        if res["error"] and "Timeout" in res["error"]:
            result = str_error(
                f"❌ Verification timed out (>{args.timeout}s), "
                "please check if constraints are too weak or design state space is too large"
            )
            print(result)
            return
        stderr = res.get("stderr", "")
        stdout = res.get("stdout", "")
        msg = f"❌ Formal verification execution failed: {res['error']}"
        if stderr:
            msg += f"\n--- STDERR ---\n{stderr[:1500]}"
        if stdout:
            msg += f"\n--- STDOUT ---\n{stdout[:1500]}"
        result = str_error(msg)
        print(result)
        return

    parsed = res["parsed_log"]
    if not parsed:
        print(str_error("❌ Verification completed but no property results found in log"))
        return

    lines = [
        f"✅ Execution completed, log: {res['log_path']}",
        "",
        "📊 Verification Results Summary:",
        f"  Assert Pass        : {len(parsed['pass'])}",
        f"  Assert TRIVIALLY_TRUE : {len(parsed['trivially_true'])}",
        f"  Assert Fail        : {len(parsed['false'])}",
        f"  Cover  Pass        : {len(parsed['cover_pass'])}",
        f"  Cover  Fail        : {len(parsed['cover_fail'])}",
    ]
    if parsed["false"]:
        lines.extend([f"\n❌ Failed Assert Properties ({len(parsed['false'])}):"] + [f"  - {p}" for p in parsed["false"]])
    if parsed["trivially_true"]:
        lines.extend([
            f"\n⚠️  TRIVIALLY_TRUE Properties ({len(parsed['trivially_true'])} - environment over-constrained):"
        ] + [f"  - {p}" for p in parsed["trivially_true"]])
    if parsed["cover_fail"]:
        lines.extend([f"\n⚠️  Failed Cover Properties ({len(parsed['cover_fail'])}):"] + [f"  - {p}" for p in parsed["cover_fail"]])

    result = str_info("\n".join(lines))
    print(result)


if __name__ == "__main__":
    main()
