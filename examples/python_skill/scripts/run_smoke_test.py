#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_PICKER = "/nfs/home/share/unitychip/bin/picker"
DEFAULT_UNITYCHIP_BIN = "/nfs/home/share/unitychip/bin"


def write_file(path: Path, content: str):
    path.write_text(content, encoding="utf-8")


def classify_failure(output: str, dut: str | None):
    if dut and f"No module named '{dut}'" in output:
        return "dut_import_failure"
    if "fixture '" in output and "not found" in output:
        return "fixture_failure"
    if "ERROR collecting" in output or "ImportError while importing test module" in output:
        return "pytest_collection_failure"
    if "FAILED" in output or "AssertionError" in output:
        return "test_failure"
    return "env_failure"


def run(command: list[str], env: dict[str, str], cwd: Path | None = None):
    return subprocess.run(command, capture_output=True, text=True, env=env, cwd=str(cwd) if cwd else None)


def resolve_test_node(raw_test_node: str) -> str:
    if "::" in raw_test_node:
        path_part, remainder = raw_test_node.split("::", 1)
        resolved = Path(path_part).expanduser().resolve()
        return f"{resolved}::{remainder}"

    maybe_path = Path(raw_test_node).expanduser()
    if maybe_path.exists():
        return str(maybe_path.resolve())
    return raw_test_node


def main():
    parser = argparse.ArgumentParser(description="Run a real pytoffee smoke test with optional picker export.")
    parser.add_argument("--workspace", required=True, help="Workflow workspace directory.")
    parser.add_argument("--tests-dir", required=True, help="Tests directory to add onto PYTHONPATH.")
    parser.add_argument("--test-node", required=True, help="Pytest node to execute, e.g. path/to/test.py::test_name")
    parser.add_argument("--dut", help="DUT package name, such as Adder.")
    parser.add_argument("--rtl", help="RTL file to export through picker before running smoke.")
    parser.add_argument("--picker", default=DEFAULT_PICKER, help="Picker executable path.")
    parser.add_argument("--unitychip-bin", default=DEFAULT_UNITYCHIP_BIN, help="Preferred UnityChip bin directory.")
    parser.add_argument("--sim", default="verilator", help="Simulator name passed to picker export.")
    parser.add_argument("--toffee-report", action="store_true", help="Append --toffee-report to the pytest command.")
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    tests_dir = Path(args.tests_dir).expanduser().resolve()
    logs_dir = workspace / "logs"
    exports_dir = workspace / "exports"
    logs_dir.mkdir(parents=True, exist_ok=True)
    exports_dir.mkdir(parents=True, exist_ok=True)

    if not tests_dir.is_dir():
        raise SystemExit(f"RESULT env_failure: tests directory is missing: {tests_dir}")

    env = os.environ.copy()
    env["PATH"] = f"{Path(args.unitychip_bin).expanduser().resolve()}:{env.get('PATH', '')}"

    picker_log = logs_dir / "picker-export.log"
    if args.rtl and args.dut:
        rtl = Path(args.rtl).expanduser().resolve()
        export_dir = exports_dir / args.dut
        if export_dir.exists():
            raise SystemExit(f"RESULT picker_failure: refusing to overwrite existing export directory {export_dir}")
        command = [
            str(Path(args.picker).expanduser().resolve()),
            "export",
            "--autobuild=true",
            str(rtl),
            "--sname",
            args.dut,
            "--tdir",
            str(export_dir),
            "--lang",
            "python",
            "-e",
            "-c",
            "--sim",
            args.sim,
        ]
        export_result = run(command, env)
        write_file(picker_log, (export_result.stdout or "") + (export_result.stderr or ""))
        if export_result.returncode != 0:
            print(f"RESULT picker_failure: picker export failed for {args.dut}")
            print(f"LOG picker export: {picker_log}")
            raise SystemExit(1)
    else:
        write_file(picker_log, "SKIP picker export: no --rtl/--dut pair was provided\n")

    pythonpath_parts = [str(tests_dir)]
    if args.dut:
        pythonpath_parts.insert(0, str(exports_dir))
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)

    smoke_stdout = logs_dir / "smoke-stdout.log"
    smoke_stderr = logs_dir / "smoke-stderr.log"
    smoke_cmd = logs_dir / "smoke-command.txt"

    command = [sys.executable, "-m", "pytest", "-q", resolve_test_node(args.test_node)]
    if args.toffee_report:
        command.append("--toffee-report")
    write_file(smoke_cmd, " ".join(command) + "\n")

    try:
        result = run(command, env, cwd=tests_dir)
    except Exception as exc:
        write_file(smoke_stdout, "")
        write_file(smoke_stderr, f"{type(exc).__name__}: {exc}\n")
        print(f"RESULT env_failure: failed to launch pytest: {exc}")
        print(f"LOG smoke stderr: {smoke_stderr}")
        raise SystemExit(1)

    write_file(smoke_stdout, result.stdout or "")
    write_file(smoke_stderr, result.stderr or "")
    combined = (result.stdout or "") + "\n" + (result.stderr or "")

    if result.returncode == 0:
        print(f"RESULT pass: smoke test passed for {args.test_node}")
        print(f"LOG picker export: {picker_log}")
        print(f"LOG smoke stdout: {smoke_stdout}")
        print(f"LOG smoke stderr: {smoke_stderr}")
        raise SystemExit(0)

    classification = classify_failure(combined, args.dut)
    print(f"RESULT {classification}: smoke test failed for {args.test_node}")
    print(f"LOG picker export: {picker_log}")
    print(f"LOG smoke stdout: {smoke_stdout}")
    print(f"LOG smoke stderr: {smoke_stderr}")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
