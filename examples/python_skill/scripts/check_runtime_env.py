#!/usr/bin/env python3
import argparse
import importlib
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_PICKER = "/nfs/home/share/unitychip/bin/picker"
DEFAULT_UNITYCHIP_BIN = "/nfs/home/share/unitychip/bin"


def result(label: str, ok: bool, detail: str):
    status = "PASS" if ok else "FAIL"
    print(f"{status} {label}: {detail}")
    return ok


def resolve_dut_package_parent(args) -> Path | None:
    if args.dut_package_parent:
        return Path(args.dut_package_parent).expanduser().resolve()
    if args.workspace:
        return Path(args.workspace).expanduser().resolve() / "exports"
    return None


def import_module(name: str, extra_paths: list[Path] | None = None):
    original = list(sys.path)
    try:
        for path in reversed(extra_paths or []):
            sys.path.insert(0, str(path))
        return importlib.import_module(name)
    finally:
        sys.path[:] = original


def run_command(command: list[str], env: dict[str, str] | None = None):
    return subprocess.run(command, capture_output=True, text=True, env=env)


def main():
    parser = argparse.ArgumentParser(
        description="Check runtime prerequisites for pytoffee verification and smoke execution."
    )
    parser.add_argument("--picker", default=DEFAULT_PICKER, help="Picker executable path.")
    parser.add_argument("--unitychip-bin", default=DEFAULT_UNITYCHIP_BIN, help="Preferred UnityChip bin directory.")
    parser.add_argument("--workspace", help="Workspace directory used by the workflow.")
    parser.add_argument("--dut", help="DUT package name to import, such as Adder.")
    parser.add_argument("--rtl", help="RTL file used to export the DUT package when it is not yet importable.")
    parser.add_argument("--tests-dir", help="Tests directory whose API module should be importable.")
    parser.add_argument("--dut-package-parent", help="Parent directory that contains the DUT package directory.")
    args = parser.parse_args()

    failures = []
    python_detail = f"{sys.executable} ({sys.version.split()[0]})"
    if not result("python", True, python_detail):
        failures.append("python")

    unitychip_bin = Path(args.unitychip_bin).expanduser().resolve()
    if not result("unitychip bin", unitychip_bin.is_dir(), str(unitychip_bin)):
        failures.append("unitychip_bin")

    picker = Path(args.picker).expanduser().resolve()
    picker_ok = picker.is_file() and os.access(picker, os.X_OK)
    if not result("picker executable", picker_ok, str(picker)):
        failures.append("picker")

    env = os.environ.copy()
    env["PATH"] = f"{unitychip_bin}:{env.get('PATH', '')}" if unitychip_bin.is_dir() else env.get("PATH", "")

    if picker_ok:
        picker_check = run_command([str(picker), "--check"], env=env)
        picker_output = (picker_check.stdout or "") + (picker_check.stderr or "")
        python_support = "[OK ] Support Python" in picker_output
        if not result(
            "picker python support",
            picker_check.returncode == 0 and python_support,
            "python support detected via `picker --check`" if python_support else "run `picker --check` and ensure Python support is installed",
        ):
            failures.append("picker_python")
    else:
        failures.append("picker_python")

    for module_name in ("toffee", "toffee_test", "pytest"):
        try:
            module = import_module(module_name)
            if not result(f"python import {module_name}", True, getattr(module, "__file__", module_name)):
                failures.append(module_name)
        except Exception as exc:
            if not result(
                f"python import {module_name}",
                False,
                f"{type(exc).__name__}: {exc}; install or expose `{module_name}` to python3",
            ):
                failures.append(module_name)

    workspace = Path(args.workspace).expanduser().resolve() if args.workspace else None
    if workspace is not None:
        logs_dir = workspace / "logs"
        writable = workspace.exists() and logs_dir.exists() and os.access(logs_dir, os.W_OK)
        if not result("workspace logs writable", writable, str(logs_dir)):
            failures.append("workspace_logs")

    tests_dir = Path(args.tests_dir).expanduser().resolve() if args.tests_dir else None
    if tests_dir is not None:
        if not result("tests dir", tests_dir.is_dir(), str(tests_dir)):
            failures.append("tests_dir")

    dut_package_parent = resolve_dut_package_parent(args)
    extra_paths = []
    if tests_dir is not None:
        extra_paths.append(tests_dir)
    if dut_package_parent is not None:
        extra_paths.append(dut_package_parent)

    if args.dut:
        try:
            module = import_module(args.dut, extra_paths)
            if not result(f"dut import {args.dut}", True, getattr(module, "__file__", args.dut)):
                failures.append("dut_import")
        except Exception as exc:
            rtl = Path(args.rtl).expanduser().resolve() if args.rtl else None
            if rtl is not None and rtl.is_file() and picker_ok:
                result(
                    f"dut export prerequisite {args.dut}",
                    True,
                    f"{rtl} is available; export `{args.dut}` into `<workspace>/exports/{args.dut}` before smoke",
                )
            else:
                if not result(
                    f"dut import {args.dut}",
                    False,
                    f"{type(exc).__name__}: {exc}; run picker export into `<workspace>/exports/{args.dut}` or set --dut-package-parent",
                ):
                    failures.append("dut_import")

    if tests_dir is not None and args.dut:
        api_module = f"{args.dut}_api"
        try:
            module = import_module(api_module, extra_paths)
            if not result(f"api import {api_module}", True, getattr(module, "__file__", api_module)):
                failures.append("api_import")
        except Exception as exc:
            if not result(
                f"api import {api_module}",
                False,
                f"{type(exc).__name__}: {exc}; verify tests dir and DUT package parent are both on PYTHONPATH",
            ):
                failures.append("api_import")

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
