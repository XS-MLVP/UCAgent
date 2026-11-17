"""Standalone recipient commands for a compact ACT delivery with private rebuild evidence."""

from __future__ import annotations

import argparse
import copy
import fcntl
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import uuid

sys.dont_write_bytecode = True
driver = importlib.import_module("act4_driver")
NOTE_PATTERN = rf'(?ms)^\.pushsection {re.escape(driver.NOTE_NAME)},"",@note\r?\n.*?^\.popsection\r?\n?'


def inventory(root: Path) -> dict:
    """Inventory a regular file tree without accepting links or build caches."""
    files = {}
    for directory, children, names in os.walk(root, followlinks=False):
        for child in children:
            driver.safe_path(root, str((Path(directory) / child).relative_to(root)))
        children[:] = [name for name in children if name not in driver.SOURCE_IGNORE_DIRS]
        for name in names:
            relative = str((Path(directory) / name).relative_to(root))
            files[relative] = driver.identity(driver.safe_path(root, relative))
    return files


def verify(root: Path, manifest: dict, modified: bool = False) -> dict:
    """Verify delivered files; explicit local editing permits only source and configuration changes."""
    changes = {}
    for name, expected in manifest["files"].items():
        path = driver.safe_path(root, name)
        current = driver.identity(path) if path.is_file() else None
        if current != expected:
            if not modified or not name.startswith(("src/", "config/")):
                raise ValueError(f"File changed or missing: {name}; restore it or use build --modified for source/config edits")
            changes[name] = {"before": expected, "after": current}
    for directory in ("src", "config", "framework"):
        for relative, current in inventory(driver.safe_path(root, directory)).items():
            name = f"{directory}/{relative}"
            if name not in manifest["files"]:
                if not modified or directory == "framework":
                    raise ValueError(f"Unrecorded input: {name}")
                if directory == "src" and relative.endswith(".S") and Path(relative).parent.name != "env":
                    raise ValueError(f"New test programs need a new ACT selection and review: {name}")
                changes[name] = {"before": None, "after": current}
    return changes


def local_environment(root: Path) -> dict:
    """Reuse isolated recipient tool prefixes without modifying the system environment."""
    environment = dict(os.environ)
    receipt = driver.safe_path(root, "local/environment.json")
    if receipt.is_file():
        paths = json.loads(receipt.read_text())["path"]
        environment["PATH"] = os.pathsep.join([*(str(driver.safe_path(root, path)) for path in paths), environment.get("PATH", "")])
    return environment


def prepare_tools(root: Path, manifest: dict, install: bool, timeout: int) -> dict:
    """Probe pinned build tools and optionally execute supplied recipes in private prefixes."""
    environment = local_environment(root)
    deadline = time.monotonic() + timeout
    report = {"status": "passed", "tools": {}, "path": []}
    attempt = driver.safe_path(root, f"local/setup/{uuid.uuid4().hex}")
    attempt.mkdir(parents=True)
    for tool in manifest["environment"]:
        prefix = driver.safe_path(root, f"local/tools/{tool['id']}")
        paths = [str(driver.safe_path(prefix, name)) for name in tool["bin_dirs"]]
        candidate = {**environment, "PATH": os.pathsep.join([*paths, environment.get("PATH", "")])}
        probe = [part.replace("{PREFIX}", str(prefix)).replace("{PYTHON}", sys.executable) for part in tool["probe"]]
        log = attempt / f"{tool['id']}.log"
        for phase in ("probe", "install") if install else ("probe",):
            remaining = int(deadline - time.monotonic())
            if remaining < 1:
                raise ValueError("Environment preparation timed out; inspect local/setup and retry")
            if phase == "install":
                prefix.mkdir(parents=True, exist_ok=True)
                for index, recipe in enumerate(tool["install"]):
                    command = [part.replace("{PREFIX}", str(prefix)).replace("{PYTHON}", sys.executable) for part in recipe]
                    remaining = int(deadline - time.monotonic())
                    if remaining < 1:
                        raise ValueError("Environment installation timed out; inspect local/setup and retry")
                    result = driver.execute(command, prefix, attempt / f"{tool['id']}-install-{index}.log", remaining, env=candidate)
                    if result["status"] != "passed":
                        break
            result = driver.execute(probe, root, log, min(20, max(1, int(deadline - time.monotonic()))), env=candidate)
            output = log.read_text(errors="replace")
            if result["status"] == "passed" and tool["version"] in output and re.search(tool["expected_output"], output):
                environment = candidate
                report["path"].extend(str(Path(path).relative_to(root)) for path in paths)
                break
        ready = result["status"] == "passed" and tool["version"] in output and bool(re.search(tool["expected_output"], output))
        report["tools"][tool["id"]] = {"status": "ready" if ready else "unavailable", "log": str(log.relative_to(root)),
                                        "required_version": tool["version"], "basis": tool["basis"]}
        if not ready:
            report["tools"][tool["id"]]["next_action"] = tool.get("unavailable_reason", "Inspect the probe/install log and supply the required tool on PATH or rerun setup")
            report["status"] = "failed"
    driver.write_json(driver.safe_path(root, "local/environment.json"), report)
    return report


def rebuild(root: Path, manifest: dict, tests: list[dict], timeout: int, jobs: int, modified: bool) -> dict:
    """Rebuild selected complete ACT programs in an isolated snapshot, regenerating Sail expectations."""
    changes = verify(root, manifest, modified)
    if not 1 <= jobs <= 64:
        raise ValueError("jobs must be in 1..64")
    attempt = driver.safe_path(root, f"local/builds/{uuid.uuid4().hex}")
    attempt.mkdir(parents=True)
    current = driver.safe_path(root, "local/build-result.json")
    driver.write_json(current, {"status": "in_progress", "attempt": str(attempt.relative_to(root))})
    environment_status = prepare_tools(root, manifest, False, min(timeout, 300))
    if environment_status["status"] != "passed":
        driver.write_json(current, {"status": "failed", "attempt": str(attempt.relative_to(root)),
                                    "errors": ["Build tools are unavailable or differ from required versions; run make setup and inspect local/environment.json"]})
        return json.loads(current.read_text())
    for directory, destination in (("framework", "act4"), ("config", "act4/config/xiangshan-kmhv3")):
        for name in inventory(root / directory):
            output = driver.safe_path(attempt, f"{destination}/{name}")
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(driver.safe_path(root / directory, name), output)
    descriptions = {test["path"]: copy.deepcopy(test["description"]) for test in tests}
    selected = set(descriptions)
    all_tests = {test["path"] for test in manifest["tests"]}
    for name in inventory(root / "src"):
        source = driver.safe_path(root / "src", name)
        dependency = driver.safe_path(attempt / "act4/tests", name)
        dependency.parent.mkdir(parents=True, exist_ok=True)
        if name in all_tests:
            dependency.write_bytes(re.sub(NOTE_PATTERN.encode(), b"", source.read_bytes()))
        else:
            shutil.copy2(source, dependency)
        if name in all_tests and name not in selected:
            continue
        destination = driver.safe_path(attempt / "act4/selected-tests", name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if changes and name in descriptions:
            description = descriptions[name]
            description["evidence_level"] = "recipient_modified_unreviewed"
            description["summary"] = "Locally modified; original design mapping requires review. " + description["summary"]
            content = source.read_text(encoding="utf-8")
            if len(re.findall(NOTE_PATTERN, content)) != 1:
                raise ValueError(f"Preserve the single ACT description note in src/{name}")
            content = re.sub(NOTE_PATTERN, lambda match: driver.description_note(description), content)
            destination.write_text("// Local modifications: original TESTS.md and run results require new review.\n" + content, encoding="utf-8")
        else:
            shutil.copy2(source, destination)
    for name in selected:
        if not driver.safe_path(attempt / "act4/selected-tests", name).is_file():
            raise ValueError(f"Selected source is missing: src/{name}")
    files = {f"act4/{name}": value for name, value in inventory(attempt / "act4").items()}
    plan = {"schema_version": 1, "suite": manifest["suite"], "target": manifest["target"], "memory": manifest["memory"],
            "tools": manifest["tools"], "files": files,
            "tests": [{"path": test["path"], "needs_signature": test["needs_signature"], "description": descriptions[test["path"]]} for test in tests]}
    driver.write_json(attempt / "build-plan.json", plan)
    result = driver.build(attempt, "build-result.json", timeout, jobs, env=local_environment(root))
    published = {"status": result["status"], "attempt": str(attempt.relative_to(root)), "changes": changes,
                 "mapping_status": "recipient_modified_unreviewed" if changes else "original_design_mapping",
                 "manifest_sha256": driver.sha256(root / "manifest.json"), "tests": [], "artifacts": {},
                 "input_files": {name: driver.identity(driver.safe_path(root, name)) for name in manifest["files"]
                                 if name.startswith(("src/", "config/", "framework/")) and driver.safe_path(root, name).is_file()},
                 "log": str((attempt / result["log"]).relative_to(root)), "errors": result["errors"]}
    for name in changes:
        if changes[name]["after"] is not None:
            published["input_files"][name] = changes[name]["after"]
    if result["status"] == "passed":
        driver.validate_build(attempt, result)
        for test in result["tests"]:
            record = {"source": test["source"], "binary_load_address": test["binary_load_address"]}
            for kind in ("elf", "bin", "disass"):
                destination = driver.safe_path(root, f"local/{kind}/{Path(test['source']).with_suffix('.' + kind)}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(driver.safe_path(attempt, test[kind]), destination)
                record[kind] = str(destination.relative_to(root))
                published["artifacts"][record[kind]] = driver.identity(destination)
            published["tests"].append(record)
    driver.write_json(current, published)
    return published


def main() -> int:
    """Expose whole-program build/run, environment setup, integrity and description commands."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("verify", "list"):
        commands.add_parser(action)
    describe = commands.add_parser("describe")
    describe.add_argument("elf", help="Package-relative final ELF path")
    for action in ("doctor", "setup", "build", "run"):
        command = commands.add_parser(action)
        command.add_argument("--timeout", type=int, default=3600)
        if action in {"build", "run"}:
            command.add_argument("--test", action="append", default=[], help="Exact ACT program path including .S; omit for all")
        if action == "build":
            command.add_argument("--jobs", type=int, default=1)
            command.add_argument("--modified", action="store_true", help="Allow local source/config edits; invalidate original mapping and execution evidence")
        if action in {"doctor", "run"}:
            command.add_argument("--emu", required=action == "run")
        if action == "run":
            command.add_argument("--local", action="store_true", help="Run the latest successful local rebuild, never fall back to delivered ELFs")
            command.add_argument("--cycles", type=int, default=20000000)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    lock = None
    try:
        manifest = json.loads(driver.safe_path(root, "manifest.json").read_text())
        if manifest.get("schema_version") != 1 or not manifest.get("tests"):
            raise ValueError("Expected a complete ACT recipient manifest")
        if hasattr(args, "timeout") and not 1 <= args.timeout <= 86400:
            raise ValueError("timeout must be in 1..86400 seconds")
        if args.action in {"build", "run", "doctor", "setup"}:
            lock_path = driver.safe_path(root, "local/.operation.lock")
            lock_path.parent.mkdir(exist_ok=True)
            lock = lock_path.open("a")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("Another build, setup or run is active in this delivery; wait for it to finish") from None
        if args.action != "build" and not (args.action == "run" and args.local):
            verify(root, manifest)
        if args.action == "verify":
            print(f"Verified {len(manifest['files'])} files; delivery status: {manifest['status']}")
            return 0
        if args.action == "list":
            for test in manifest["tests"]:
                print(f"{test['path']}\t{test['description']['summary']}")
            return 0
        if args.action == "describe":
            print(json.dumps(driver.elf_description(driver.safe_path(root, args.elf)), ensure_ascii=False, indent=2))
            return 0
        if args.action in {"doctor", "setup"}:
            if args.action == "doctor" and args.emu:
                executable = Path(args.emu).expanduser().resolve()
                if not executable.is_file() or not os.access(executable, os.X_OK):
                    raise ValueError("Supply an executable matching Kunminghu V3 SimTop emu")
                print("Emulator exists; hardware identity and execution have not been verified")
                return 0
            result = prepare_tools(root, manifest, args.action == "setup", args.timeout)
        else:
            available = {test["path"]: test for test in manifest["tests"]}
            if len(set(args.test)) != len(args.test) or set(args.test) - available.keys():
                raise ValueError("Use unique exact ACT paths from 'handoff.py list', including .S; testcase/coverpoint IDs are not standalone programs")
            tests = [available[name] for name in args.test] if args.test else list(available.values())
            if args.action == "build":
                result = rebuild(root, manifest, tests, args.timeout, args.jobs, args.modified)
            else:
                if args.local:
                    verify(root, manifest, modified=True)
                    rebuilt = json.loads(driver.safe_path(root, "local/build-result.json").read_text())
                    if rebuilt["status"] != "passed" or rebuilt["manifest_sha256"] != driver.sha256(root / "manifest.json"):
                        raise ValueError("Latest local build did not pass for this delivery; rebuild before run --local")
                    driver.verify_files(root, rebuilt["input_files"])
                    current_inputs = {f"{directory}/{name}" for directory in ("src", "config", "framework") for name in inventory(root / directory)}
                    if current_inputs != rebuilt["input_files"].keys():
                        raise ValueError("Local inputs changed after compilation; rebuild before run --local")
                    driver.verify_files(root, rebuilt["artifacts"])
                    records = {test["source"]: test for test in rebuilt["tests"]}
                    if not args.test:
                        tests = [test for test in manifest["tests"] if test["path"] in records]
                else:
                    records = {test["path"]: {**test, "source": test["path"]} for test in manifest["tests"] if test["build_status"] == "passed"}
                if any(test["path"] not in records for test in tests):
                    raise ValueError("Requested programs have no successful build in the selected result; build them first")
                selected = [records[test["path"]] for test in tests]
                for test in selected:
                    driver.inspect_elf(driver.safe_path(root, test["elf"]), manifest["memory"])
                result = driver.run_elfs(root, selected, manifest["target"], args.emu, args.timeout, args.cycles, "local/runs", env=local_environment(root))
                result["input_kind"] = "local_rebuild" if args.local else "delivered"
                result["mapping_status"] = rebuilt["mapping_status"] if args.local else "original_design_mapping"
                result["elf_sha256"] = {test["source"]: driver.sha256(driver.safe_path(root, test["elf"])) for test in selected}
                driver.write_json(driver.safe_path(root, "local/run-result.json"), result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "passed" else 1
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"Handoff error: {error}", file=sys.stderr)
        return 2
    finally:
        if lock is not None:
            lock.close()


if __name__ == "__main__":
    sys.exit(main())
